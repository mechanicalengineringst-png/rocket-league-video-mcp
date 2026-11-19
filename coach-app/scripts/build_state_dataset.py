"""Build the Round 13 state dataset: features at t (frames <= t) and labels from the next seconds.

One row per sampled frame and team perspective. Labels (never used as features):
- next_touch_own      1/0: team of the next touch within 3 s (rows with no touch in 3 s get NaN)
- danger_5s           the ball centre comes within 2000 uu of the own goal within 5 s
- opportunity_5s      ... of the opponent goal
- goal_against_10s / goal_for_10s
Rows are excluded in dead-ball windows (goal to next kickoff + 3 s) and in the last 10 s of a replay.
Usage (from coach-app/): python scripts/build_state_dataset.py CACHE_DIR OUT.parquet [STEP_S]
"""
from __future__ import annotations

import bisect
import glob
import hashlib
import math
import pickle
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from coach_app.state_features import frame_features, reach_times  # noqa: E402

GOAL_Y = 5120.0


def match_id(path: str) -> str:
    return hashlib.sha256(Path(path).stem.encode()).hexdigest()[:8]


def dead(t, kicks, goals):
    k = kicks[bisect.bisect_right(kicks, t) - 1] if kicks and kicks[0] <= t else None
    g = goals[bisect.bisect_right(goals, t) - 1] if goals and goals[0] <= t else None
    if k is None:
        return True
    if g is not None and g > k:
        return True
    return t - k < 3.0


def rows_for(path: str, step: float = 0.5) -> list[dict]:
    d = pickle.loads(Path(path).read_bytes())
    team_of = {p["id"]: p["team"] for p in d["players"]}
    frames = d["frames"]
    ts = [f["t"] for f in frames]
    ev = d["events"]
    kicks = sorted(e["t"] for e in ev if e["type"] == "kickoff")
    goals = sorted((e["t"], e.get("scoringTeam")) for e in ev if e["type"] == "goal_context")
    gts = [g[0] for g in goals]
    touches = sorted((e["t"], team_of.get(e.get("playerId"))) for e in ev if e["type"] == "touch" and e.get("playerId"))
    tt = [x[0] for x in touches]
    out = []
    t = ts[0] + 5.0
    while t < ts[-1] - 10.0:
        i = bisect.bisect_right(ts, t) - 1
        fr = frames[i]
        if t - fr["t"] > 0.1 or dead(t, kicks, gts):
            t += step
            continue
        reach = reach_times(fr)
        j = bisect.bisect_right(tt, fr["t"])
        nxt = touches[j] if j < len(touches) and touches[j][0] <= fr["t"] + 3.0 else None
        g_next = next(((gt, team) for gt, team in goals if fr["t"] < gt <= fr["t"] + 10.0), None)
        k_end = bisect.bisect_right(ts, fr["t"] + 5.0)
        fut = frames[i + 1:k_end]
        for team in ("blue", "orange"):
            f = frame_features(fr, team_of, team, reach=reach)
            if f is None:
                continue
            s = 1 if team == "blue" else -1
            danger = any(math.hypot(x["ball"]["x"], s * x["ball"]["y"] + GOAL_Y) < 2000 for x in fut)
            opp = any(math.hypot(x["ball"]["x"], s * x["ball"]["y"] - GOAL_Y) < 2000 for x in fut)
            f.update({
                "match": match_id(path), "t": round(fr["t"], 3), "team": team,
                "next_touch_own": (float(nxt[1] == team) if nxt else float("nan")),
                "danger_5s": float(danger), "opportunity_5s": float(opp),
                "goal_against_10s": float(bool(g_next) and g_next[1] not in (None, team)),
                "goal_for_10s": float(bool(g_next) and g_next[1] == team),
            })
            out.append(f)
        t += step
    return out


def main(cache: Path, out: Path, step: float = 0.5, workers: int = 2):
    files = sorted(glob.glob(str(cache / "*.pkl")))
    with ProcessPoolExecutor(workers) as ex:
        parts = list(ex.map(rows_for, files, [step] * len(files)))
    df = pd.DataFrame([r for p in parts for r in p])
    df.to_parquet(out) if out.suffix == ".parquet" else df.to_pickle(out)
    print(df.shape, df["match"].nunique(), "matches")
    print(df[["next_touch_own", "danger_5s", "opportunity_5s", "goal_against_10s"]].describe().T)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), float(sys.argv[3]) if len(sys.argv) > 3 else 0.5)
