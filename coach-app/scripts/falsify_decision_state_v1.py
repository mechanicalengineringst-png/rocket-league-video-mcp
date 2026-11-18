"""Round 11 Phase A: attack TacticalDecisionStateV1's assumptions on real replays.

Experiments (all labels are held-out decoder events, never inputs):
1. margin_generalization: per-match accuracy of the 0.55 s ordering margin on raced pairs, leave-one-match-out
   margin selection, and a match-bootstrap distribution of the chosen margin.
2. interval_semantics: is [t_min, t_max] an interval for *actual* arrival? Share of touches before t_min,
   inside the interval, and after t_max; share of zero-width intervals.
3. branch_informativeness: at V1 decision nodes, when V1 says the focus player / carrier is first or the
   order is ambiguous, who actually touched first among the two within 3 s (or neither).
4. robust_is_not_safe: reuses Round 10's regain proxy figures (see decision_state_v1_real_replays.json).

Usage (from coach-app/): python scripts/falsify_decision_state_v1.py CACHE_DIR PRIVATE_MANIFEST_DIR OUT.json
"""
from __future__ import annotations

import bisect
import glob
import hashlib
import json
import pickle
import random
import sys
from collections import Counter, defaultdict
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach_app.decision_state_v1 import CALIBRATION, analyze_decision_state  # noqa: E402
from coach_app.episode_evidence import build_episode_evidence  # noqa: E402
from coach_app.episode_stage1 import build_stage1_episode_packet  # noqa: E402
from coach_app.reachability import estimate_reach  # noqa: E402

STEP, HORIZON, TARGET = 1.0, 3.0, 0.90
MARGINS = [round(0.05 * k, 2) for k in range(0, 31)]


def sample(d: dict):
    """Raced opposing pairs (|delta|, correct) and per-car (t_min, t_max, actual) rows."""
    frames, times = d["frames"], [f["t"] for f in d["frames"]]
    team = {p["id"]: p["team"] for p in d["players"]}
    touches = sorted((e["t"], e["playerId"]) for e in d["events"] if e.get("type") == "touch")
    raced, cars = [], []
    t = times[0] + 2.0
    while t < times[-1] - HORIZON:
        fr = frames[bisect.bisect_right(times, t) - 1]
        b = fr["ball"]
        if len(fr["cars"]) == 4 and b.get("velocity") and not (b["x"] == 0 and b["y"] == 0):
            est = {}
            for pid, car in fr["cars"].items():
                r = estimate_reach(car, b)
                if r.status == "ok":
                    est[pid] = r
                    nxt = next((tt for tt, p in touches if t < tt <= t + HORIZON and p == pid), None)
                    if nxt is not None:
                        cars.append((r.t_min, r.t_max if r.t_max is not None else r.t_min, nxt - t))
            for a, c in product([p for p in est if team[p] == "blue"], [p for p in est if team[p] == "orange"]):
                window = [p for tt, p in touches if t < tt <= t + HORIZON and p in (a, c)]
                if a in window and c in window:
                    delta = est[a].t_min - est[c].t_min
                    if delta:
                        raced.append((abs(delta), (window[0] == a) == (delta < 0)))
        t += STEP
    return raced, cars


def acc(rows, m):
    res = [ok for d, ok in rows if d > m]
    return (sum(res) / len(res) if res else None), len(res)


def choose(rows):
    for m in MARGINS:
        a, n = acc(rows, m)
        if a is not None and a >= TARGET and n >= 30:
            return m
    return None


def main(cache: Path, mdir: Path, out: Path) -> dict:
    random.seed(11)
    per_match, all_cars = {}, []
    files = sorted(glob.glob(str(cache / "*.pkl")))
    payloads = {}
    for f in files:
        d = pickle.loads(Path(f).read_bytes())
        key = "match-" + hashlib.sha256(Path(f).stem.encode()).hexdigest()[:8]
        payloads[key] = d
        per_match[key], cars = sample(d)
        all_cars += cars
    m0 = CALIBRATION["order_margin_s"]
    # 1. generalization
    pm = {k: {"pairs": len(v), "accuracy_at_margin": None if acc(v, m0)[0] is None else round(acc(v, m0)[0], 3),
              "resolved": acc(v, m0)[1]} for k, v in per_match.items()}
    loo = {}
    for k in per_match:
        rest = [r for kk, v in per_match.items() if kk != k for r in v]
        m = choose(rest)
        a, n = acc(per_match[k], m) if m is not None else (None, 0)
        loo[k] = {"margin_fit_on_others": m, "accuracy_on_this_match": None if a is None else round(a, 3), "resolved": n}
    boots = []
    keys = list(per_match)
    for _ in range(300):
        rows = [r for k in random.choices(keys, k=len(keys)) for r in per_match[k]]
        boots.append(choose(rows))
    bc = Counter("none" if b is None else b for b in boots)
    # 2. interval semantics
    n = len(all_cars)
    before = sum(a < lo - 0.1 for lo, hi, a in all_cars)
    inside = sum(lo - 0.1 <= a <= hi + 0.1 for lo, hi, a in all_cars)
    zero = sum(hi - lo < 1e-6 for lo, hi, a in all_cars)
    # 3. branch informativeness on V1 decision nodes
    rows = {r["case_id"]: r for r in json.loads((mdir / "PRIVATE_candidate_manifest.json").read_text())}
    side = json.loads((mdir / "PRIVATE_candidate_provenance.json").read_text())
    branch = defaultdict(Counter)
    for s in side:
        r = rows[s["case_id"]]
        d = payloads[r["replay_group"]]
        t, pid = r["source_t0_s"], s["player_id"]
        times = [round(t - 8, 3), round(t - 4, 3), t]
        if times[0] - 1 < d["frames"][0]["t"]:
            continue
        ep = build_episode_evidence(d, pid, times, t - 9, t)
        v1 = analyze_decision_state(build_stage1_episode_packet(ep))
        if v1["status"] == "abstain":
            continue
        slots = ep["nodes"][-1]["snapshot"]["slots"]
        inv = {}
        from coach_app.decision_evidence import _slots
        for p_id, slot in _slots(d["players"], pid).items():
            inv[slot] = p_id
        carrier = inv.get(v1["scenario"]["carrier_slot"])
        first = next((p for tt, p in sorted((e["t"], e["playerId"]) for e in d["events"] if e.get("type") == "touch")
                      if t < tt <= t + HORIZON and p in (pid, carrier)), None)
        label = "focus" if first == pid else "carrier" if first == carrier else "neither"
        branch[v1["scenario"]["focus_vs_carrier"]][label] += 1
        _ = slots
    report = {
        "margin_under_test_s": m0,
        "margin_generalization": {"per_match": pm, "leave_one_match_out": loo,
                                  "bootstrap_chosen_margin": dict(sorted(bc.items(), key=lambda x: str(x[0]))),
                                  "bootstrap_resamples": len(boots)},
        "interval_semantics": {"car_touch_rows": n, "touch_before_t_min": round(before / n, 3),
                               "touch_inside_interval": round(inside / n, 3),
                               "touch_after_t_max": round(1 - (before + inside) / n, 3),
                               "zero_width_intervals": round(zero / n, 3)},
        "branch_informativeness": {k: dict(v) for k, v in branch.items()},
        "note": "Public unknown-rank replays only; no high-rank data was available to test generalization.",
    }
    out.write_text(json.dumps(report, indent=1))
    return report


if __name__ == "__main__":
    print(json.dumps(main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])), indent=1))
