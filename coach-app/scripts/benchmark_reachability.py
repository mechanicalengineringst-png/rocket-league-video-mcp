"""Benchmark the kinematic reachability engine against the Round 4 baseline on real replays.

Labels are held out: for a decision time t0 and a car, the label is the time
until that car's next decoder ``touch`` event. Estimates read only the t0 frame.

A car can only touch the ball after the earliest time it physically could, so
a correct feasibility estimate should be a LOWER bound on the label:
- violation: estimate > label + tolerance (the car did something the model says is impossible);
- gap: label - estimate (how loose the bound is; players do not always hurry);
- first-to-ball: does the smallest estimate pick the car that actually touched first?

Usage (from coach-app/): python scripts/benchmark_reachability.py REPLAY_DIR OUT.json [CACHE_DIR]
"""
from __future__ import annotations

import bisect
import json
import math
import pickle
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach_app.reachability import baseline_reach, estimate_reach, max_curvature  # noqa: E402

TOL = 0.1
LABEL_HORIZON = 4.0
STEP_S = 1.0


def load(path: Path, cache: Path | None) -> dict | None:
    import subtr_actor
    from coach_app.subtr_replays import parse_subtr_replay
    meta = subtr_actor.get_replay_meta(str(path))
    meta = meta.get("replay_meta", meta)
    if not (len(meta["team_zero"]) == 2 and len(meta["team_one"]) == 2):
        return None
    if cache:
        f = cache / (path.stem + ".pkl")
        if f.exists():
            return pickle.loads(f.read_bytes())
    payload = parse_subtr_replay(path)
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
        (cache / (path.stem + ".pkl")).write_bytes(pickle.dumps(payload))
    return payload


def _reset_between(frames, times, t0, t1) -> bool:
    i, j = bisect.bisect_right(times, t0), bisect.bisect_right(times, t1)
    prev = None
    for f in frames[max(i - 1, 0):j]:
        b = f["ball"]
        if prev and math.hypot(b["x"] - prev["x"], b["y"] - prev["y"]) > 1500:
            return True
        if b["x"] == 0 and b["y"] == 0 and not any(b.get("velocity") or [0]):
            return True
        prev = b
    return False


def pct(xs, q):
    xs = sorted(xs)
    return None if not xs else round(xs[min(len(xs) - 1, int(q * (len(xs) - 1) + 0.5))], 3)


def summarize(vals):
    return {"n": len(vals), "p10": pct(vals, 0.1), "median": pct(vals, 0.5), "p90": pct(vals, 0.9),
            "mean_abs": round(statistics.fmean(abs(v) for v in vals), 3) if vals else None}


def turning_check(frames, window: int = 6) -> dict:
    """Observed ground curvature over ~0.2 s windows relative to the model's no-powerslide maximum.

    Frames repeat network states, so single-frame differences overstate turn
    rate; a 6-sample window averages over that.
    """
    ratios = defaultdict(list)
    for a, b in zip(frames, frames[window:]):
        dt = b["t"] - a["t"]
        if not 0.15 < dt < 0.25:
            continue
        for pid, ca in a["cars"].items():
            cb = b["cars"].get(pid)
            if not cb or not ca.get("forward") or not cb.get("forward") or ca["z"] > 40 or cb["z"] > 40:
                continue
            v = (math.hypot(*ca["velocity"][:2]) + math.hypot(*cb["velocity"][:2])) / 2
            if v < 300:
                continue
            h1 = math.atan2(ca["forward"][1], ca["forward"][0])
            h2 = math.atan2(cb["forward"][1], cb["forward"][0])
            dh = abs((h2 - h1 + math.pi) % (2 * math.pi) - math.pi)
            ratios[min(int(v // 500) * 500, 2000)].append((dh / dt / v) / max_curvature(v))
    return {f"{k}-{k + 500} uu/s": {"n": len(r), "median_ratio": pct(r, 0.5), "p95_ratio": pct(r, 0.95),
                                     "share_above_model": round(sum(x > 1.05 for x in r) / len(r), 3)}
            for k, r in sorted(ratios.items())}


def _group(rows):
    g = defaultdict(list)
    for r in rows:
        g[(r["approach"] or "none").split(" +")[0]].append(r)
    return g


def run(replay_dir: Path, out: Path, cache: Path | None) -> dict:
    rows, abstain, order = [], Counter(), Counter()
    turning_frames = []
    t_start = time.time()
    n_replays = 0
    for path in sorted(replay_dir.glob("*.replay")):
        payload = load(path, cache)
        if payload is None:
            continue
        n_replays += 1
        frames = payload["frames"]
        times = [f["t"] for f in frames]
        touches = defaultdict(list)
        for e in payload["events"]:
            if e.get("type") == "touch" and e.get("playerId"):
                touches[e["playerId"]].append(e["t"])
        all_touch = sorted((t, p) for p, ts in touches.items() for t in ts)
        if n_replays <= 5:
            turning_frames.extend(frames[:9000])
        t0 = times[0] + 2.0
        while t0 < times[-1] - LABEL_HORIZON:
            fr = frames[bisect.bisect_right(times, t0) - 1]
            t0_cur, t0 = t0, t0 + STEP_S
            ball = fr["ball"]
            if len(fr["cars"]) < 4 or (ball["x"] == 0 and ball["y"] == 0 and not any(ball.get("velocity") or [0])):
                continue
            ests = {}
            for pid, car in fr["cars"].items():
                r = estimate_reach(car, ball)
                b = baseline_reach(car, ball)
                nxt = [t for t in touches.get(pid, []) if t0_cur < t <= t0_cur + LABEL_HORIZON]
                label = (nxt[0] - t0_cur) if nxt else None
                if label is not None and _reset_between(frames, times, t0_cur, t0_cur + label):
                    label = None
                if r.status == "abstain":
                    abstain[r.reason] += 1
                rows.append({"replay": path.stem[:8], "t0": round(t0_cur, 2), "pid": pid[-6:], "label": label,
                             "status": r.status, "new": r.t_min, "new_hi": r.t_max, "approach": r.approach,
                             "base": b, "z": car.get("z"), "speed": round(math.hypot(*car["velocity"][:2]))
                             if car.get("velocity") else None})
                ests[pid] = (r.t_min if r.status == "ok" else (math.inf if r.status == "out_of_horizon" else None), b)
            first = next(((t, p) for t, p in all_touch if t0_cur < t <= t0_cur + 2.5), None)
            if first and not _reset_between(frames, times, t0_cur, first[0]) and ests.get(first[1], (None,))[0] is not None \
                    and all(v[0] is not None for v in ests.values()):
                order["cases"] += 1
                order["new_correct"] += min(ests, key=lambda p: ests[p][0]) == first[1]
                order["base_correct"] += min(ests, key=lambda p: ests[p][1]) == first[1]
    labelled = [r for r in rows if r["label"] is not None]
    ok = [r for r in labelled if r["status"] == "ok"]
    report = {
        "replays": n_replays, "t0_samples_x_cars": len(rows), "with_touch_label": len(labelled),
        "runtime_s": round(time.time() - t_start, 1),
        "abstentions": dict(abstain), "out_of_horizon_with_label": sum(r["status"] == "out_of_horizon" for r in labelled),
        "lower_bound_violations": {
            "new": sum(r["new"] > r["label"] + TOL for r in ok),
            "baseline_same_rows": sum(r["base"] > r["label"] + TOL for r in ok),
            "rows": len(ok),
            "new_out_of_horizon_but_touched": sum(r["status"] == "out_of_horizon" for r in labelled),
        },
        "gap_label_minus_estimate_s": {"new": summarize([r["label"] - r["new"] for r in ok]),
                                       "baseline": summarize([r["label"] - r["base"] for r in ok])},
        "gap_when_touch_within_1_5s": {
            "new": summarize([r["label"] - r["new"] for r in ok if r["label"] <= 1.5]),
            "baseline": summarize([r["label"] - r["base"] for r in ok if r["label"] <= 1.5])},
        "baseline_over_4s_while_touch_within_2s": sum(r["base"] > 4 and r["label"] <= 2 for r in ok),
        "new_over_4s_while_touch_within_2s": sum((r["new"] or 0) > 4 and r["label"] <= 2 for r in ok),
        "first_to_ball_within_2_5s": {"cases": order["cases"],
                                      "new_accuracy": round(order["new_correct"] / max(order["cases"], 1), 3),
                                      "baseline_accuracy": round(order["base_correct"] / max(order["cases"], 1), 3),
                                      "chance": 0.25},
        "violations_by_approach": {k: f"{sum(r['new'] > r['label'] + TOL for r in g)}/{len(g)}" for k, g in _group(ok).items()},
        "approach_used": Counter(r["approach"].split(" +")[0] if r["approach"] else None for r in ok),
        "worst_new_violations": sorted(({k: r[k] for k in ("replay", "t0", "label", "new", "approach", "z", "speed")}
                                        for r in ok if r["new"] > r["label"] + TOL),
                                       key=lambda r: r["label"] - r["new"])[:8],
        "turning_model_check": turning_check(turning_frames),
    }
    out.write_text(json.dumps(report, indent=1, default=str))
    return report


if __name__ == "__main__":
    rep = run(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]) if len(sys.argv) > 3 else None)
    print(json.dumps({k: v for k, v in rep.items() if k != "worst_new_violations"}, indent=1, default=str))
