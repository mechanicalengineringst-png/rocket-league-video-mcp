"""Validate counterfactual action families and compare them with the Round 12 ledger (Round 13).

For every Round 12 situation (all players, all cached matches, aerial/wall excluded):
1. Forward-model check: the simulated position of the family the player actually chose (Stage B label)
   vs where the car really was at the horizon; compared with a constant-velocity baseline and with the
   simulations of the other families (does the chosen family's simulation match reality best?).
2. Spread: how different the families' value-model scores are at the same t0 (if tiny, counterfactuals
   cannot discriminate).
3. Ledger agreement: when R12 supports one of {challenge, shadow/hold} and refutes the other, does the
   value model (next touch own / danger) prefer the same one?
4. Meaning of "questionable": model-based regret (best family value minus chosen family value, at t0)
   for R12 verdicts sound / questionable / risky / defensible_if.
Usage (from coach-app/): python scripts/counterfactual_study.py CACHE_DIR OUT.json
"""
from __future__ import annotations

import bisect
import glob
import json
import math
import pickle
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach_app import counterfactual as cfx  # noqa: E402
from coach_app.coach_report import analyze_moment  # noqa: E402
from coach_app.coaching_findings import build_stage_a, build_stage_b  # noqa: E402
from coach_app.situations import discover_situations  # noqa: E402
from coach_app.value_model import FutureControlModel  # noqa: E402

FAMILY_MAP = {"touch": "commit", "hold": "shadow", "direct": "retreat", "small_pads": "small_boost",
              "big_boost": "big_boost", "support": "shadow", "support_close": "commit", "push": "commit",
              "keep": "commit", "shot": "commit", "pass": "commit", "clear": "commit"}


def V(row):
    v = row.get("value") or {}
    if "next_touch_own" not in v:
        return None
    return v["next_touch_own"] - v["danger_5s"]


def study(path: str) -> list[dict]:
    d = pickle.loads(Path(path).read_bytes())
    team_of = {p["id"]: p["team"] for p in d["players"]}
    frames, ts = d["frames"], [f["t"] for f in d["frames"]]
    model = FutureControlModel.load()
    rows = []
    for pid in team_of:
        for sit in discover_situations(d, pid):
            sd = sit.to_dict()
            if sd["situation_class"] == "aerial_or_wall":
                continue
            fr = frames[bisect.bisect_right(ts, sd["t0"]) - 1]
            cf = cfx.evaluate(fr, team_of, pid, events=d["events"], value_model=model)
            if not cf or cf.get("status") != "ok" or len(cf["families"]) < 3:
                continue
            try:
                it = analyze_moment(d, pid, sd)
            except Exception:  # noqa: BLE001
                continue
            if not it:
                continue
            fa = build_stage_a(sd, it["rationale"], it["packet"], finding_id="x")
            fb = build_stage_b(fa, d, sd)
            obs = fb["observed_action"]
            fam = FAMILY_MAP.get(obs.get("family"))
            if obs.get("label") == "rotate_through_small_pads":
                fam = "small_boost"
            tau = cf["horizon_s"]
            i2 = bisect.bisect_left(ts, sd["t0"] + tau)
            actual = frames[min(i2, len(frames) - 1)]["cars"].get(pid)
            c0 = fr["cars"][pid]
            cv = (c0["x"] + c0["velocity"][0] * tau, c0["y"] + c0["velocity"][1] * tau)
            errs = {}
            if actual:
                for f, r in cf["families"].items():
                    errs[f] = math.dist(r["focus_xy"], (actual["x"], actual["y"]))
            st = {a: x["status"] for a, x in it["rationale"].get("actions", {}).items()}
            vals = {f: V(r) for f, r in cf["families"].items()}
            rows.append({
                "cls": sd["situation_class"], "tau": tau, "obs_family": fam, "obs_label": obs.get("label"),
                "verdict": fb.get("assessment", {}).get("verdict"),
                "err": errs, "err_cv": math.dist(cv, (actual["x"], actual["y"])) if actual else None,
                "moved_uu": math.dist((c0["x"], c0["y"]), (actual["x"], actual["y"])) if actual else None,
                "values": vals,
                "nt": {f: (r.get("value") or {}).get("next_touch_own") for f, r in cf["families"].items()},
                "dg": {f: (r.get("value") or {}).get("danger_5s") for f, r in cf["families"].items()},
                "own_half": {f: r["own_half_control"] for f, r in cf["families"].items()},
                "ledger": {k: st.get(k) for k in ("immediate_challenge", "shadow_delay", "goal_side_hold", "return_direct",
                                                  "big_boost_detour", "small_pad_route", "support_behind", "aggressive_follow_up")},
            })
    return rows


def _q(xs, p):
    xs = sorted(x for x in xs if x is not None)
    return round(float(xs[int(p * (len(xs) - 1))]), 3) if xs else None


def aggregate(rows: list[dict]) -> dict:
    res: dict = {"situations": len(rows), "horizon_median_s": _q([r["tau"] for r in rows], 0.5)}
    # 1 forward model
    fm = [r for r in rows if r["obs_family"] in r["err"] and r["err_cv"] is not None]
    res["forward_model"] = {
        "n": len(fm),
        "chosen_family_error_median_uu": _q([r["err"][r["obs_family"]] for r in fm], 0.5),
        "constant_velocity_error_median_uu": _q([r["err_cv"] for r in fm], 0.5),
        "chosen_beats_constant_velocity_share": round(sum(r["err"][r["obs_family"]] < r["err_cv"] for r in fm) / max(1, len(fm)), 3),
        "chosen_family_is_closest_share": round(sum(min(r["err"], key=r["err"].get) == r["obs_family"] for r in fm) / max(1, len(fm)), 3),
        "chance_closest_share": round(float(np.mean([1 / len(r["err"]) for r in fm])) if fm else 0, 3),
        "by_family": {f: {"n": len(x), "closest_share": round(sum(min(r["err"], key=r["err"].get) == f for r in x) / max(1, len(x)), 3),
                          "err_median": _q([r["err"][f] for r in x], 0.5), "cv_median": _q([r["err_cv"] for r in x], 0.5)}
                      for f in sorted({r["obs_family"] for r in fm}) for x in [[r for r in fm if r["obs_family"] == f]]},
        "median_distance_moved_uu": _q([r["moved_uu"] for r in fm], 0.5)}
    # 2 spread
    spreads = [max(v for v in r["values"].values() if v is not None) - min(v for v in r["values"].values() if v is not None)
               for r in rows if sum(v is not None for v in r["values"].values()) >= 2]
    res["value_spread_between_families"] = {"median": _q(spreads, 0.5), "p75": _q(spreads, 0.75), "p90": _q(spreads, 0.9),
                                            "note": "value = model next-touch-own minus danger-5s; units are model scores"}
    # 3 ledger agreement on challenge vs hold
    agree = defaultdict(lambda: [0, 0])
    for r in rows:
        ch, sh = r["ledger"].get("immediate_challenge"), r["ledger"].get("shadow_delay") or r["ledger"].get("goal_side_hold")
        vc, vs = r["values"].get("commit"), r["values"].get("shadow")
        if vc is None or vs is None:
            continue
        if ch == "supported" and sh == "refuted":
            agree["ledger_challenge_over_hold"][0] += vc > vs
            agree["ledger_challenge_over_hold"][1] += 1
        if sh == "supported" and ch == "refuted":
            agree["ledger_hold_over_challenge"][0] += vs > vc
            agree["ledger_hold_over_challenge"][1] += 1
        if r["ledger"].get("big_boost_detour") == "refuted" and r["ledger"].get("return_direct") == "supported" and \
                r["values"].get("big_boost") is not None and r["values"].get("retreat") is not None:
            agree["ledger_direct_over_big_boost"][0] += r["values"]["retreat"] > r["values"]["big_boost"]
            agree["ledger_direct_over_big_boost"][1] += 1
    res["ledger_value_agreement"] = {k: {"n": v[1], "value_model_agrees": round(v[0] / v[1], 3) if v[1] else None} for k, v in agree.items()}
    # 4 regret by verdict
    reg = defaultdict(list)
    for r in rows:
        if r["obs_family"] in r["values"] and r["values"][r["obs_family"]] is not None and r["verdict"]:
            best = max(v for v in r["values"].values() if v is not None)
            reg[r["verdict"]].append(best - r["values"][r["obs_family"]])
    res["model_regret_by_r12_verdict"] = {k: {"n": len(v), "median": _q(v, 0.5), "p75": _q(v, 0.75),
                                              "zero_regret_share": round(sum(x < 1e-6 for x in v) / len(v), 3)}
                                          for k, v in reg.items()}
    return res


def main(cache: Path, out: Path, workers: int = 2):
    files = sorted(glob.glob(str(cache / "*.pkl")))
    with ProcessPoolExecutor(workers) as ex:
        parts = list(ex.map(study, files))
    rows = [r for p in parts for r in p]
    res = aggregate(rows)
    out.write_text(json.dumps(res, indent=1))
    out.with_suffix(".rows.json").write_text(json.dumps(rows))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
