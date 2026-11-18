"""Calibrate and validate the ground-contact model in coach_app.contact_geometry (Round 12).

Labels are held-out decoder events. For each decoder `touch` with a clean before/after sample:
  before = last frame before the touch, after = first frame >= 0.08 s later (no other touch in between);
  kept if ball and car are low (ground contact) and the ball's velocity changed by >= 300 uu/s.
1. Fit k (|dv| / closing speed along the centre line) on FIT matches; measure the outgoing-direction
   error of the model and of two baselines on HELD-OUT matches; cone half-width = p75 error on FIT.
2. Validate the next-ball race (toucher excluded): on held-out touches, run race_after_contact from the before-frame and
   compare the majority direction outcome with the team of the next touch by a DIFFERENT player within 3 s.
   Baselines: "toucher's team keeps it" and "team of the nearest other car to the contact point".

Usage (from coach-app/): python scripts/calibrate_contact_model.py CACHE_DIR OUT.json
"""
from __future__ import annotations

import bisect
import glob
import hashlib
import json
import math
import pickle
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach_app import contact_geometry as cg  # noqa: E402


def _ang(a, b):
    return abs(math.degrees((a - b + math.pi) % (2 * math.pi) - math.pi))


def touches(d: dict) -> tuple[list[dict], Counter]:
    fr, ts = d["frames"], [x["t"] for x in d["frames"]]
    team = {p["id"]: p["team"] for p in d["players"]}
    tou = sorted((e["t"], e["playerId"]) for e in d["events"] if e.get("type") == "touch" and e.get("playerId"))
    out, drop = [], Counter()
    for k, (t, pid) in enumerate(tou):
        i, j = bisect.bisect_left(ts, t) - 1, bisect.bisect_left(ts, t + 0.08)
        if i < 1 or j >= len(fr):
            drop["edge"] += 1
            continue
        if k + 1 < len(tou) and tou[k + 1][0] <= ts[j]:
            drop["next_touch_within_0.08s"] += 1
            continue
        c, b0, b1 = fr[i]["cars"].get(pid), fr[i]["ball"], fr[j]["ball"]
        if not c or not b0.get("velocity") or not b1.get("velocity"):
            drop["missing"] += 1
            continue
        if b0["z"] > 400 or c["z"] > 120:
            drop["airborne"] += 1
            continue
        dv = (b1["velocity"][0] - b0["velocity"][0], b1["velocity"][1] - b0["velocity"][1])
        if math.hypot(*dv) < 300:
            drop["weak_touch"] += 1
            continue
        nxt = next(((tt, p) for tt, p in tou[k + 1:] if p != pid and tt <= t + 3.0), None)
        zone_actual = None
        if not (k + 1 < len(tou) and tou[k + 1][0] <= t + 1.0):
            jz = bisect.bisect_left(ts, t + 1.0)
            if jz < len(fr) and fr[jz]["ball"].get("z") is not None:
                from coach_app.contact_geometry import zone_of
                zone_actual = zone_of(fr[jz]["ball"]["x"], fr[jz]["ball"]["y"], team[pid])
        out.append({"t": t, "pid": pid, "team": team[pid], "car": c, "b0": b0, "b1": b1, "dv": dv,
                    "cars": fr[i]["cars"], "team_of": team,
                    "next_other_team": team.get(nxt[1]) if nxt else None, "zone_actual": zone_actual})
    return out, drop


def main(cache: Path, out: Path) -> dict:
    fit, held, drops = [], [], Counter()
    for f in sorted(glob.glob(str(cache / "*.pkl"))):
        d = pickle.loads(Path(f).read_bytes())
        rows, dr = touches(d)
        drops.update(dr)
        (held if int(hashlib.sha256(Path(f).stem.encode()).hexdigest(), 16) % 3 == 0 else fit).extend(rows)

    def closing(r):
        c, b = r["car"], r["b0"]
        nx, ny = b["x"] - c["x"], b["y"] - c["y"]
        n = math.hypot(nx, ny) or 1.0
        return ((c["velocity"][0] - b["velocity"][0]) * nx + (c["velocity"][1] - b["velocity"][1]) * ny) / n

    k = statistics.median(math.hypot(*r["dv"]) / closing(r) for r in fit if closing(r) > 300)

    def errors(rows):
        e_model, e_line, e_vel = [], [], []
        for r in rows:
            c, b0, b1 = r["car"], r["b0"], r["b1"]
            dvx, dvy = cg.predicted_dv((c["x"], c["y"]), c["velocity"][:2], (b0["x"], b0["y"]), b0["velocity"][:2], k=k)
            out_a = math.atan2(b1["velocity"][1], b1["velocity"][0])
            e_model.append(_ang(out_a, math.atan2(b0["velocity"][1] + dvy, b0["velocity"][0] + dvx)))
            e_line.append(_ang(out_a, math.atan2(b0["y"] - c["y"], b0["x"] - c["x"])))
            if math.hypot(*c["velocity"][:2]) > 300:
                e_vel.append(_ang(out_a, math.atan2(c["velocity"][1], c["velocity"][0])))
        return e_model, e_line, e_vel

    def q(xs, p):
        xs = sorted(xs)
        return round(xs[int(p * (len(xs) - 1))], 1) if xs else None

    fm, _, _ = errors(fit)
    hm, hl, hv = errors(held)
    cone = q(fm, 0.75)
    cg.MODEL.update(k=k, cone_half_deg=cone)
    # 2. next-ball race validation on held-out touches
    conf, base_keep, base_near, n = Counter(), 0, 0, 0
    for r in held:
        if r["next_other_team"] is None:
            continue
        c = r["car"]
        res = cg.race_after_contact(r["cars"], r["team_of"], r["pid"], (r["b0"]["x"], r["b0"]["y"], r["b0"]["z"]), 0.0,
                                    tuple(c["velocity"][:2]), tuple(r["b0"]["velocity"][:2]), r["team"],
                                    include_toucher=False)
        if res["status"] == "unsupported":
            continue
        cnt = res["counts"]
        decided = {"own": cnt["own"], "opponents": cnt["opponents"]}
        pred = "contested" if cnt["contested"] >= max(decided.values()) else max(decided, key=decided.get)
        actual = "own" if r["next_other_team"] == r["team"] else "opponents"
        conf[(pred, actual)] += 1
        n += 1
        base_keep += actual == "own"
        others = [(math.hypot(cc["x"] - r["b0"]["x"], cc["y"] - r["b0"]["y"]), p) for p, cc in r["cars"].items() if p != r["pid"]]
        near = min(others)[1] if others else None
        base_near += ("own" if r["team_of"].get(near) == r["team"] else "opponents") == actual
    # 3. destination-zone validation: centre-direction zone vs the ball's actual zone 1 s later (no touch between)
    zone_n = zone_centre = zone_in_cone = zone_stay = zone_prev = zone_carv = 0
    for r in held:
        if r.get("zone_actual") is None:
            continue
        c = r["car"]
        z = cg.destination_zones((c["x"], c["y"]), tuple(c["velocity"][:2]), (r["b0"]["x"], r["b0"]["y"], r["b0"]["z"]),
                                 tuple(r["b0"]["velocity"][:2]), r["team"])
        zone_n += 1
        zone_centre += z["centre_zone"] == r["zone_actual"]
        zone_stay += cg.zone_of(r["b0"]["x"], r["b0"]["y"], r["team"]) == r["zone_actual"]
        nx, ny = r["b0"]["x"] + r["b0"]["velocity"][0], r["b0"]["y"] + r["b0"]["velocity"][1]
        zone_prev += cg.zone_of(nx, ny, r["team"]) == r["zone_actual"]
        nx, ny = r["b0"]["x"] + c["velocity"][0], r["b0"]["y"] + c["velocity"][1]
        zone_carv += cg.zone_of(nx, ny, r["team"]) == r["zone_actual"]
        zone_in_cone += r["zone_actual"] in z["zone_counts"]
    decided_n = sum(v for (p, _), v in conf.items() if p != "contested")
    correct = sum(v for (p, a), v in conf.items() if p == a)
    report = {
        "k": round(k, 3), "cone_half_deg": cone, "floor_uu_s": cg.MODEL["floor_uu_s"],
        "touches": {"fit": len(fit), "held_out": len(held), "dropped": dict(drops)},
        "airborne_share_of_candidate_touches": round(drops["airborne"] / max(1, drops["airborne"] + len(fit) + len(held)
                                                                             + drops["weak_touch"]), 3),
        "fit": {"median_deg": q(fm, 0.5), "p75_deg": cone, "n": len(fm)},
        "held_out": {"median_deg": q(hm, 0.5), "p75_deg": q(hm, 0.75), "p90_deg": q(hm, 0.9), "n": len(hm),
                     "baseline_centre_line": {"median_deg": q(hl, 0.5), "p75_deg": q(hl, 0.75)},
                     "baseline_car_velocity": {"median_deg": q(hv, 0.5), "p75_deg": q(hv, 0.75)}},
        "next_ball_validation_held_out": {
            "touches": n, "confusion_pred_actual": {f"{p}|{a}": v for (p, a), v in sorted(conf.items())},
            "model_accuracy_when_decided": round(correct / decided_n, 3) if decided_n else None,
            "model_decided": decided_n,
            "baseline_toucher_team_keeps": round(base_keep / n, 3) if n else None,
            "baseline_always_opponents": round(1 - base_keep / n, 3) if n else None,
            "verdict": "NOT VALIDATED: the next-ball race does not beat the base rate. Destination zones only tie the "
                       "car-velocity baseline. Findings use neither; contact outcome stays a named, unobservable assumption.",
            "baseline_nearest_other_car": round(base_near / n, 3) if n else None},
        "destination_zone_validation_held_out": {
            "touches": zone_n, "centre_zone_correct": round(zone_centre / zone_n, 3) if zone_n else None,
            "actual_zone_inside_modelled_band": round(zone_in_cone / zone_n, 3) if zone_n else None,
            "baseline_ball_stays_in_zone": round(zone_stay / zone_n, 3) if zone_n else None,
            "baseline_pre_touch_ball_velocity": round(zone_prev / zone_n, 3) if zone_n else None,
            "baseline_car_velocity_direction": round(zone_carv / zone_n, 3) if zone_n else None},
        "note": "Public unknown-rank replays; ground contacts only; labels are decoder touch events (held out).",
    }
    out.write_text(json.dumps(report, indent=1))
    return report


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1]), Path(sys.argv[2])), indent=1))
