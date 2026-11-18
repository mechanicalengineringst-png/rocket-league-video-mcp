"""Calibrate the "who reaches the ball first" ambiguity margin from real replays (Round 10).

For live moments sampled every STEP s, take every pair of opposing cars whose reachability estimates exist
and where one of the two makes the next touch among the pair within HORIZON s (decoder touch events,
held out: never an input). Delta = t_min(a) - t_min(b). For each candidate margin m, the order is
"resolved" when |Delta| > m; accuracy = share of resolved pairs where the smaller estimate touched first.

Two label sets: all such pairs, and "raced" pairs where BOTH cars touched within the horizon (both went for
the ball), which isolates physical ordering from the choice not to contest. The margin uses raced pairs.
Matches are split by hash into fit (2/3) and held-out (1/3) groups. The margin is the smallest m whose
FIT accuracy on resolved pairs is >= TARGET; it is then reported on the HELD-OUT matches.

Usage (from coach-app/): python scripts/calibrate_contest_margin.py CACHE_DIR OUT.json
"""
from __future__ import annotations

import bisect
import glob
import hashlib
import json
import pickle
import sys
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coach_app.reachability import estimate_reach  # noqa: E402

STEP, HORIZON, TARGET = 1.0, 3.0, 0.90
MARGINS = [round(0.05 * k, 2) for k in range(0, 21)]


def pairs_for(d: dict) -> tuple[list, list]:
    """(all_pairs, raced_pairs). raced = both cars touched within the horizon, i.e. both went for the ball."""
    frames, times = d["frames"], [f["t"] for f in d["frames"]]
    team = {p["id"]: p["team"] for p in d["players"]}
    touches = sorted((e["t"], e["playerId"]) for e in d["events"] if e.get("type") == "touch")
    out, raced = [], []
    t = times[0] + 2.0
    while t < times[-1] - HORIZON:
        fr = frames[bisect.bisect_right(times, t) - 1]
        b = fr["ball"]
        if len(fr["cars"]) == 4 and b.get("velocity") and not (b["x"] == 0 and b["y"] == 0):
            est = {}
            for pid, car in fr["cars"].items():
                r = estimate_reach(car, b)
                if r.status == "ok":
                    est[pid] = r.t_min
            blue = [p for p in est if team[p] == "blue"]
            orange = [p for p in est if team[p] == "orange"]
            for a, c in product(blue, orange):
                window = [p for tt, p in touches if t < tt <= t + HORIZON and p in (a, c)]
                if not window:
                    continue
                delta = est[a] - est[c]
                if delta == 0:
                    continue
                row = (abs(delta), (window[0] == a) == (delta < 0))
                out.append(row)
                if a in window and c in window:
                    raced.append(row)
        t += STEP
    return out, raced


def accuracy(rows, m):
    res = [ok for d, ok in rows if d > m]
    return (sum(res) / len(res) if res else None), len(res)


def main(cache: Path, out: Path) -> dict:
    data = {"all": ([], []), "raced": ([], [])}
    groups = {"fit": 0, "held_out": 0}
    for f in sorted(glob.glob(str(cache / "*.pkl"))):
        rows, raced = pairs_for(pickle.loads(Path(f).read_bytes()))
        bucket = "held_out" if int(hashlib.sha256(Path(f).stem.encode()).hexdigest(), 16) % 3 == 0 else "fit"
        groups[bucket] += 1
        data["all"][1 if bucket == "held_out" else 0].extend(rows)
        data["raced"][1 if bucket == "held_out" else 0].extend(raced)
    report = {"method": __doc__.strip().splitlines()[0], "target_accuracy": TARGET, "matches": groups,
              "note": "Public unknown-rank replays; the margin describes the kinematic model's ordering error, "
                      "not expert judgement. 'all' pairs include players who chose not to go for the ball, so their "
                      "order mixes choice with capability; 'raced' pairs (both touched within the horizon) isolate "
                      "capability and are used for the margin."}
    for label, (fit, held) in data.items():
        table = _table(fit, held)
        chosen = next((r for r in table if r["fit_accuracy"] is not None and r["fit_accuracy"] >= TARGET), table[-1])
        report[label] = {"pairs": {"fit": len(fit), "held_out": len(held)}, "chosen": chosen, "table": table}
    report["chosen"] = report["raced"]["chosen"]
    out.write_text(json.dumps(report, indent=1))
    return report


def _table(fit, held):
    table = []
    for m in MARGINS:
        fa, fn = accuracy(fit, m)
        ha, hn = accuracy(held, m)
        table.append({"margin_s": m, "fit_accuracy": None if fa is None else round(fa, 3), "fit_resolved": fn,
                      "held_out_accuracy": None if ha is None else round(ha, 3), "held_out_resolved": hn})
    return table


if __name__ == "__main__":
    r = main(Path(sys.argv[1]), Path(sys.argv[2]))
    print(json.dumps({"matches": r["matches"], "all": {k: r["all"][k] for k in ("pairs", "chosen")},
                      "raced": {k: r["raced"][k] for k in ("pairs", "chosen")}}, indent=1))
