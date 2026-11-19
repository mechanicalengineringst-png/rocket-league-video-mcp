"""Round 13 falsification of Round 10-12 assumptions on the public cohort (unknown rank).

A  Reachability on real touches: at 0.5-2.0 s before each touch, was the toucher's kinematic earliest
   touch time (a claimed LOWER bound) actually <= the time they took? Violations = the model says "cannot
   get there" but they did.
B  Field-control arrival model on real motion: is each car's actual position 1 s / 2 s later reachable
   in that time according to field_control.arrival_times?
C  Intent proxy: does the nearest opponent's closing speed (R12 "carrier_committing", > 500 uu/s)
   predict that this player makes the next touch within 1.5 s? Compared with reach time and distance.
D  Cover window: for R12 first-defender situations, the predicted teammate cover time vs the time the
   teammate actually became goal-side, and (separately) how long after an opponent touch in our half the
   ball took to reach our goal zone (the time a covering teammate actually has).
E  Observed-action labels: stability of the R12 Stage B label when the window changes (2.0/2.5/3.0 s),
   and agreement with the Round 5 choice classifier on first-defender moments.
Usage (from coach-app/): python scripts/falsify_round13.py CACHE_DIR OUT.json
"""
from __future__ import annotations

import bisect
import glob
import json
import math
import pickle
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach_app import coaching_findings as cf  # noqa: E402
from coach_app import field_control as fc  # noqa: E402
from coach_app.choices import classify_choice  # noqa: E402
from coach_app.coach_report import analyze_moment  # noqa: E402
from coach_app.reachability import estimate_reach  # noqa: E402
from coach_app.situations import discover_situations  # noqa: E402
from coach_app.strategic_state import _already_goal_side  # noqa: E402
from coach_app.tactical_options import _State  # noqa: E402

GOAL_Y = 5120.0
LEADS = (0.5, 1.0, 1.5, 2.0)


def _auc(scores, labels):
    s, y = np.asarray(scores, float), np.asarray(labels, int)
    ok = ~np.isnan(s)
    s, y = s[ok], y[ok]
    if y.sum() == 0 or y.sum() == len(y):
        return None
    order = np.argsort(s)
    ranks = np.empty(len(s))
    ranks[order] = np.arange(1, len(s) + 1)
    return float((ranks[y == 1].sum() - y.sum() * (y.sum() + 1) / 2) / (y.sum() * (len(y) - y.sum())))


def study(path: str) -> dict:
    d = pickle.loads(Path(path).read_bytes())
    team_of = {p["id"]: p["team"] for p in d["players"]}
    frames, ts = d["frames"], [f["t"] for f in d["frames"]]
    ev = d["events"]
    touches = sorted((e["t"], e["playerId"]) for e in ev if e["type"] == "touch" and e.get("playerId"))
    out: dict = {"A": [], "B": [], "C": [], "D_cover": [], "D_danger": [], "E": []}

    def frame_at(t):
        i = bisect.bisect_right(ts, t) - 1
        return frames[i] if i >= 0 and t - frames[i]["t"] < 0.1 else None

    # A
    prev_t = -1e9
    for t, pid in touches:
        if t - prev_t < 0.3:          # follow-up touches of the same contact
            prev_t = t
            continue
        prev_t = t
        fr_t = frame_at(t)
        if not fr_t:
            continue
        air = fr_t["ball"]["z"] > 300
        for L in LEADS:
            fr = frame_at(t - L)
            if not fr or pid not in fr["cars"] or not fr["cars"][pid]:
                continue
            if any(t - L < tt < t for tt, _ in touches):
                continue                # someone touched in between: the ball path changed
            r = estimate_reach(fr["cars"][pid], fr["ball"])
            tmin = r.t_min if r.status == "ok" else (math.inf if r.status == "out_of_horizon" else None)
            if tmin is None:
                continue
            out["A"].append({"lead": L, "air": air, "t_min": None if math.isinf(tmin) else round(tmin, 3),
                             "violation_s": (round(tmin - L, 3) if not math.isinf(tmin) else 99.0)})
    # B and C on sampled frames
    for k in range(0, len(frames), 45):
        fr = frames[k]
        if len(fr.get("cars", {})) < 4:
            continue
        for tau in (1.0, 2.0):
            f2 = frame_at(fr["t"] + tau)
            if not f2:
                continue
            for pid, c in fr["cars"].items():
                c2 = f2["cars"].get(pid)
                if not c or not c2 or c2["z"] > 60:
                    continue
                at = fc.arrival_times(c, np.array([[c2["x"], c2["y"]]]))
                if at is not None and math.dist((c["x"], c["y"]), (c2["x"], c2["y"])) > 300:
                    out["B"].append({"tau": tau, "pred": round(float(at[0]), 3)})
        b = fr["ball"]
        j = bisect.bisect_right([x[0] for x in touches], fr["t"])
        nxt = touches[j] if j < len(touches) and touches[j][0] <= fr["t"] + 1.5 else None
        reach = {}
        for pid, c in fr["cars"].items():
            if not c:
                continue
            r = estimate_reach(c, b)
            reach[pid] = r.t_min if r.status == "ok" else None
        for team in ("blue", "orange"):
            opp = [p for p in reach if team_of.get(p) == team and reach[p] is not None]
            if not opp:
                continue
            p = min(opp, key=lambda q: reach[q])
            c = fr["cars"][p]
            dx, dy = b["x"] - c["x"], b["y"] - c["y"]
            dist = math.hypot(dx, dy) or 1.0
            closing = ((c["velocity"][0] - b["velocity"][0]) * dx + (c["velocity"][1] - b["velocity"][1]) * dy) / dist
            out["C"].append({"closing": round(closing), "reach": round(reach[p], 3), "dist": round(dist),
                             "touches_next": int(bool(nxt) and nxt[1] == p)})
    # D and E on R12 situations
    for t, pid in touches:
        team = team_of.get(pid)
        fr = frame_at(t)
        if not fr or team is None:
            continue
        s = 1 if team == "blue" else -1          # defending team = the other one; its own goal is at +s*GOAL_Y
        if s * fr["ball"]["y"] <= 0:              # opponent touch in the defending team's half
            continue
        k = bisect.bisect_right(ts, t)
        tdanger = None
        for f2 in frames[k:k + 180]:
            if any(t < tt <= f2["t"] and team_of.get(pp) != team for tt, pp in touches):
                break                              # defenders touched first
            if math.hypot(f2["ball"]["x"], f2["ball"]["y"] - s * GOAL_Y) < 2000:
                tdanger = f2["t"] - t
                break
        out["D_danger"].append({"t_to_goal_zone_s": None if tdanger is None else round(tdanger, 2)})
    for pid in team_of:
        for sit in discover_situations(d, pid):
            sd = sit.to_dict()
            if sd["situation_class"] in ("first_defender", "loose_ball", "offensive_first_man"):
                labels = {}
                for w in (2.0, 2.5, 3.0):
                    cf.OBS_WINDOW_S = w
                    labels[w] = cf.observe_action(d, sd)["family"]
                cf.OBS_WINDOW_S = 2.5
                ch = classify_choice(d, sd["t0"], pid).choice
                out["E"].append({"w2": labels[2.0], "w25": labels[2.5], "w3": labels[3.0], "r5": ch,
                                 "cls": sd["situation_class"]})
            if sd["situation_class"] != "first_defender":
                continue
            try:
                it = analyze_moment(d, pid, sd)
            except Exception:  # noqa: BLE001
                continue
            if not it:
                continue
            cov = it["rationale"]["conditions"].get("teammate_covers", {})
            st = _State(it["packet"])
            pred = st.val("E.cover.teammate") if "E.cover.teammate" in st.ev else None
            mate = next((p for p in team_of if team_of[p] == team_of[pid] and p != pid), None)
            team = team_of[pid]
            s = 1 if team == "blue" else -1
            actual = None
            k = bisect.bisect_right(ts, sd["t0"])
            for f2 in frames[k:k + 150]:
                c = f2["cars"].get(mate)
                if c and _already_goal_side(c["x"], c["y"], f2["ball"], team):   # the same test the cover estimate uses
                    actual = round(f2["t"] - sd["t0"], 2)
                    break
            carrier_t = it["situation"]["values"].get("carrier_t")
            out["D_cover"].append({"status": cov.get("status"), "pred": pred, "actual": actual,
                                   "already": bool(pred == 0), "carrier_t": carrier_t})
    return out


def _q(xs, p):
    xs = sorted(x for x in xs if x is not None)
    return round(xs[int(p * (len(xs) - 1))], 3) if xs else None


def aggregate(parts: list[dict]) -> dict:
    allr = defaultdict(list)
    for p in parts:
        for k, v in p.items():
            allr[k] += v
    res: dict = {}
    A = allr["A"]
    res["A_reach_lower_bound_on_real_touches"] = {
        f"{'air' if air else 'ground'}_lead_{L}": {
            "n": len(rows), "violated_share": round(sum(r["violation_s"] > 0.0 for r in rows) / max(1, len(rows)), 3),
            "violated_by_more_than_0.3s": round(sum(r["violation_s"] > 0.3 for r in rows) / max(1, len(rows)), 3),
            "beyond_horizon_share": round(sum(r["violation_s"] == 99.0 for r in rows) / max(1, len(rows)), 3)}
        for air in (False, True) for L in LEADS for rows in [[r for r in A if r["air"] == air and r["lead"] == L]]}
    B = allr["B"]
    res["B_field_arrival_on_real_motion"] = {
        f"tau_{tau}": {"n": len(rows), "predicted_slower_than_actual": round(sum(r["pred"] > tau for r in rows) / max(1, len(rows)), 3),
                       "by_more_than_0.3s": round(sum(r["pred"] > tau + 0.3 for r in rows) / max(1, len(rows)), 3),
                       "median_pred_s": _q([r["pred"] for r in rows], 0.5)}
        for tau in (1.0, 2.0) for rows in [[r for r in B if r["tau"] == tau]]}
    C = allr["C"]
    y = [r["touches_next"] for r in C]
    hi = [r for r in C if r["closing"] > 500]
    lo = [r for r in C if r["closing"] <= 500]
    res["C_intent_proxy"] = {
        "n": len(C), "base_rate_touch_within_1.5s": round(sum(y) / max(1, len(y)), 3),
        "rate_if_closing_gt_500": round(sum(r["touches_next"] for r in hi) / max(1, len(hi)), 3), "n_closing_gt_500": len(hi),
        "rate_if_closing_le_500": round(sum(r["touches_next"] for r in lo) / max(1, len(lo)), 3),
        "auc_closing_speed": _r(_auc([r["closing"] for r in C], y)),
        "auc_minus_reach_time": _r(_auc([-r["reach"] for r in C], y)),
        "auc_minus_distance": _r(_auc([-r["dist"] for r in C], y)),
        "rate_by_reach_and_closing": {
            f"reach_{lo_}-{hi_}": {"closing>500": _rate([r for r in C if lo_ <= r["reach"] < hi_ and r["closing"] > 500]),
                                   "closing<=500": _rate([r for r in C if lo_ <= r["reach"] < hi_ and r["closing"] <= 500])}
            for lo_, hi_ in ((0, 0.5), (0.5, 1.0), (1.0, 2.0))}}
    D = allr["D_cover"]
    rows = [r for r in D if r["pred"] not in (None, 0) and r["actual"] is not None]
    err = [r["actual"] - r["pred"] for r in rows]
    res["D_cover"] = {
        "first_defender_situations": len(D), "status_counts": dict(Counter(r["status"] for r in D)),
        "teammate_already_goal_side": sum(r["already"] for r in D),
        "teammate_became_goal_side_within_5s": sum(r["actual"] is not None for r in D),
        "pred_vs_actual_n": len(rows), "actual_minus_pred_median_s": _q(err, 0.5),
        "actual_minus_pred_p25_s": _q(err, 0.25), "actual_minus_pred_p75_s": _q(err, 0.75),
        "by_status": {st: {"n": len(x),
                           "goal_side_within_carrier_t_plus_1s": round(sum(r["actual"] is not None and r["carrier_t"] is not None and
                                                                          r["actual"] <= r["carrier_t"] + 1.0 for r in x) / max(1, len(x)), 3),
                           "goal_side_within_5s": round(sum(r["actual"] is not None for r in x) / max(1, len(x)), 3)}
                      for st in ("holds", "within_error", "fails", "unknown") for x in [[r for r in D if r["status"] == st]]},
        "note": "actual = first time the teammate met the same goal-side test the cover estimate uses (moving ball); "
                "the teammate may not have tried, so 'fails' can also mean 'did not try'."}
    dz = [r["t_to_goal_zone_s"] for r in allr["D_danger"]]
    reached = [x for x in dz if x is not None]
    res["D_time_to_goal_zone_after_opponent_touch_in_our_half"] = {
        "opponent_touches": len(dz), "reached_goal_zone_within_6s_before_a_defender_touch": len(reached),
        "median_s": _q(reached, 0.5), "p25_s": _q(reached, 0.25), "p75_s": _q(reached, 0.75), "p10_s": _q(reached, 0.1)}
    E = allr["E"]
    res["E_observed_action_labels"] = {
        "n": len(E), "unlabelled_at_2.5s": sum(r["w25"] is None for r in E),
        "same_family_2.0_vs_2.5": _agree(E, "w2", "w25"), "same_family_2.5_vs_3.0": _agree(E, "w25", "w3"),
        "r12_vs_round5_choice": _crosstab(E)}
    return res


def _r(x):
    return None if x is None else round(x, 3)


def _rate(rows):
    return {"n": len(rows), "rate": round(sum(r["touches_next"] for r in rows) / len(rows), 3) if rows else None}


def _agree(E, a, b):
    rows = [r for r in E if r[a] is not None and r[b] is not None]
    return {"n": len(rows), "agree": round(sum(r[a] == r[b] for r in rows) / max(1, len(rows)), 3)}


def _crosstab(E):
    m = {"touch": "challenge", "hold": "shadow", "boost": "boost"}
    rows = [r for r in E if r["w25"] in m and r["r5"] in ("challenge", "shadow", "retreat", "boost")]
    agree = sum(m[r["w25"]] == r["r5"] or (r["w25"] == "hold" and r["r5"] == "retreat") for r in rows)
    return {"n_both_labelled": len(rows), "agree_share": round(agree / max(1, len(rows)), 3),
            "pairs": {f"{k[0]}|{k[1]}": v for k, v in Counter((r["w25"], r["r5"]) for r in E).most_common(12)}}


def main(cache: Path, out: Path, workers: int = 2):
    files = sorted(glob.glob(str(cache / "*.pkl")))
    with ProcessPoolExecutor(workers) as ex:
        parts = list(ex.map(study, files))
    res = aggregate(parts)
    res["cohort"] = {"replays": len(files), "note": "public 2v2 replays of unknown rank; no human labels"}
    out.write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
