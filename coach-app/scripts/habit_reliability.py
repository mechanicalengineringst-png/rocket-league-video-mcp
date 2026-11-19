"""Are habit metrics stable traits or noise? Split-half reliability on the cohort (Round 13).

Each replay is split into its first and second half (by time). For every player-match, each habit metric is
measured on both halves; the Spearman correlation across player-matches says how much of the metric is a
stable tendency of the player rather than noise. Also writes the habit reference distribution.
Usage (from coach-app/): python scripts/habit_reliability.py CACHE_DIR OUT.json
"""
from __future__ import annotations

import glob
import json
import pickle
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach_app.habit_profile import REFERENCE_PATH, measure, merge  # noqa: E402


def _cut(d, lo, hi):
    return {**d, "frames": [f for f in d["frames"] if lo <= f["t"] < hi],
            "events": [e for e in d["events"] if isinstance(e.get("t"), (int, float)) and lo <= e["t"] < hi]}


def per_match(path: str) -> list[dict]:
    d = pickle.loads(Path(path).read_bytes())
    t0, t1 = d["frames"][0]["t"], d["frames"][-1]["t"]
    mid = (t0 + t1) / 2
    a, b = _cut(d, t0, mid), _cut(d, mid, t1 + 1)
    out = []
    for p in d["players"]:
        out.append({"full": merge([measure(d, p["id"])]), "h1": merge([measure(a, p["id"])]), "h2": merge([measure(b, p["id"])])})
    return out


def _spearman(x, y):
    from scipy.stats import spearmanr
    r = spearmanr(x, y)
    return None if np.isnan(r.correlation) else round(float(r.correlation), 3)


def main(cache: Path, out: Path):
    files = sorted(glob.glob(str(cache / "*.pkl")))
    with ProcessPoolExecutor(2) as ex:
        rows = [r for part in ex.map(per_match, files) for r in part]
    res = {"player_matches": len(rows), "metrics": {}}
    ref = {}
    for name in rows[0]["full"]:
        pairs = [(r["h1"][name]["rate"], r["h2"][name]["rate"]) for r in rows
                 if r["h1"][name]["rate"] is not None and r["h2"][name]["rate"] is not None
                 and r["h1"][name]["n"] >= 3 and r["h2"][name]["n"] >= 3]
        full = [r["full"][name]["rate"] for r in rows if r["full"][name]["rate"] is not None and r["full"][name]["enough_data"]]
        ref[name] = sorted(full)
        res["metrics"][name] = {"n_pairs": len(pairs), "split_half_spearman": _spearman(*zip(*pairs)) if len(pairs) >= 8 else None,
                                "cohort_median": round(float(np.median(full)), 3) if full else None,
                                "cohort_p10_p90": [round(float(np.quantile(full, 0.1)), 3), round(float(np.quantile(full, 0.9)), 3)] if full else None}
    res["note"] = "Halves of the same match share teammates, opponents and score state; reliability across matches is untested."
    out.write_text(json.dumps(res, indent=1))
    REFERENCE_PATH.write_text(json.dumps({"version": "habit-reference/0.1",
                                          "cohort": {"replays": len(files), "player_matches": len(rows),
                                                     "note": "public 2v2 replays, unknown rank"},
                                          "metrics": ref}))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
