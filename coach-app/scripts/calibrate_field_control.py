"""Fit the straight-line acceleration constants of field_control against reachability.ground_time.

Samples real car states from cached replays, random field targets, and compares the vectorised
estimate with the reference kinematic model. Reports error before/after the fit.
Usage (from coach-app/): python scripts/calibrate_field_control.py CACHE_DIR [N] [OUT.json]
"""
from __future__ import annotations

import glob
import json
import pickle
import random
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach_app import field_control as fc  # noqa: E402
from coach_app.reachability import car_state, ground_time  # noqa: E402


def samples(cache: Path, n: int, seed: int = 7):
    rng = random.Random(seed)
    files = sorted(glob.glob(str(cache / "*.pkl")))
    out = []
    while len(out) < n:
        d = pickle.loads(Path(rng.choice(files)).read_bytes())
        fr = rng.choice(d["frames"])
        for c in fr["cars"].values():
            if c and c.get("z", 0) < 40:
                st, _ = car_state(c)
                if st is None or st.mode != "ground":
                    continue
                tx, ty = rng.uniform(-3800, 3800), rng.uniform(-4800, 4800)
                ref, _ = ground_time(st, tx, ty, 6.0, (c.get("boost") or 0) > 0)
                if ref is not None and fc.arrival_times(c, np.array([[tx, ty]])) is not None:
                    out.append((c, tx, ty, ref))
    return out


def err(rows):
    e = np.array([float(fc.arrival_times(c, np.array([[tx, ty]]))[0]) - ref for c, tx, ty, ref in rows])
    return {"n": len(e), "median_abs_s": round(float(np.median(np.abs(e))), 3), "p90_abs_s": round(float(np.quantile(np.abs(e), 0.9)), 3),
            "bias_s": round(float(np.mean(e)), 3)}


def main(cache: Path, n: int, out: Path | None = None):
    import itertools
    rows = samples(cache, n)
    fit, held = rows[: n // 2], rows[n // 2:]
    names = ("KT", "ACC_BOOST", "ACC_NO_BOOST", "KEEP", "ARC_CREDIT", "BOOST_FULL")
    default = {k: getattr(fc, k) for k in names}
    before = err(held)
    best = None
    grid = itertools.product((0.05, 0.1, 0.15, 0.2, 0.25), (1500, 1800, 2200, 2600), (400, 600, 800), (0.5, 1.0),
                             (0.3, 0.6, 0.9, 1.2), (10.0, 25.0, 50.0))
    for vals in grid:
        for k, v in zip(names, vals):
            setattr(fc, k, v)
        e = err(fit)
        score = e["median_abs_s"] + 0.5 * abs(e["bias_s"])
        if best is None or score < best[0]:
            best = (score, vals)
    for k, v in zip(names, best[1]):
        setattr(fc, k, v)
    res = {"fitted": dict(zip(names, best[1])), "previous": default, "held_out_with_previous": before,
           "held_out_fitted": err(held),
           "reference": "reachability.ground_time, ground cars from cached replays, targets uniform on the field, horizon 6 s",
           "note": "This calibrates an approximation to our own kinematic model, not to real arrival times."}
    print(json.dumps(res, indent=1))
    if out:
        out.write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    main(Path(sys.argv[1]), int(sys.argv[2]) if len(sys.argv) > 2 else 1200, Path(sys.argv[3]) if len(sys.argv) > 3 else None)
