"""Control timeline and turning points: sequence-level coaching selection (Round 13, experimental).

An alternative to isolated decision labels. The learned FutureControlModel scores every half second
of the match for one team: ``control = P(next touch is ours) - P(ball reaches our goal zone within 5 s)``
(model scores, never shown as percentages). Turning points are the largest changes of that score over
a short window, in both directions, so good sequences are found as readily as bad ones.

For each turning point the change is attributed to players by a leave-one-player-out swap: the score at
the end of the window is recomputed with one player's state put back to where it was at the start
(everyone else as they ended). A large share means "this player's movement in the window is what moved
the team's expected control". This is attribution of a *model score change*, not blame, and touches in
the window are listed separately.

Selection here is RETROSPECTIVE by construction (it looks at what changed). Any judgment of a
decision inside the window must still come from decision-time evidence (Stage A).
"""
from __future__ import annotations

import bisect
from typing import Any

from .state_features import reach_times
from .value_model import FutureControlModel

VERSION = "control-timeline/0.1"
STEP_S = 0.5
WINDOW_S = 2.0
MIN_SEPARATION_S = 6.0


def _control(scores: dict[str, float] | None) -> float | None:
    if not scores:
        return None
    return scores["next_touch_own"] - scores["danger_5s"]


def _dead_windows(events: list[dict]) -> list[tuple[float, float]]:
    kicks = sorted(e["t"] for e in events if e.get("type") == "kickoff")
    goals = sorted(e["t"] for e in events if e.get("type") == "goal_context")
    out = []
    for g in goals:
        k = next((k for k in kicks if k > g), g + 15.0)
        out.append((g - 0.5, k + 3.0))
    for k in kicks:
        out.append((k - 4.0, k + 3.0))
    return out


def timeline(replay: dict, team: str, model: FutureControlModel | None = None, step: float = STEP_S) -> list[dict]:
    model = model or FutureControlModel.load()
    if model is None:
        return []
    team_of = {p["id"]: p.get("team") for p in replay.get("players", [])}
    frames = replay.get("frames", [])
    ts = [f["t"] for f in frames]
    dead = _dead_windows(replay.get("events", []))
    out = []
    t = ts[0] + 3.0 if ts else 0.0
    while ts and t <= ts[-1]:
        fr = frames[bisect.bisect_right(ts, t) - 1]
        if t - fr["t"] < 0.1 and not any(a <= t <= b for a, b in dead):
            s = model.score(fr, team_of, team)
            c = _control(s)
            if c is not None:
                out.append({"t": round(fr["t"], 3), "control": round(c, 4), "next_touch_own": s["next_touch_own"],
                            "danger_5s": s["danger_5s"]})
        t += step
    return out


def _frame(replay: dict, t: float) -> dict | None:
    ts = [f["t"] for f in replay["frames"]]
    i = bisect.bisect_right(ts, t + 1e-6) - 1
    return replay["frames"][i] if i >= 0 else None


def attribute(replay: dict, team: str, t_a: float, t_b: float, model: FutureControlModel) -> dict[str, Any]:
    """Leave-one-player-out: how much of the score change at t_b depends on each player's movement since t_a."""
    team_of = {p["id"]: p.get("team") for p in replay.get("players", [])}
    fa, fb = _frame(replay, t_a), _frame(replay, t_b)
    if not fa or not fb:
        return {}
    base = _control(model.score(fb, team_of, team))
    start = _control(model.score(fa, team_of, team))
    if base is None or start is None:
        return {}
    contrib = {}
    for pid in team_of:
        if pid not in fa["cars"] or pid not in fb["cars"] or not fa["cars"][pid]:
            continue
        swapped = {**fb, "cars": {**fb["cars"], pid: fa["cars"][pid]}}
        alt = _control(model.score(swapped, team_of, team, reach=reach_times(swapped)))
        if alt is not None:
            contrib[pid] = round(base - alt, 4)      # > 0: this player's movement raised our control
    touches = [{"t": round(e["t"], 2), "player": e.get("playerId"), "own_team": team_of.get(e.get("playerId")) == team}
               for e in replay.get("events", []) if e.get("type") == "touch" and t_a < e.get("t", -1) <= t_b]
    return {"start": round(start, 4), "end": round(base, 4), "change": round(base - start, 4), "player_contribution": contrib,
            "touches": touches}


def turning_points(replay: dict, team: str, *, k: int = 8, model: FutureControlModel | None = None,
                   tl: list[dict] | None = None) -> dict[str, Any]:
    model = model or FutureControlModel.load()
    if model is None:
        return {"version": VERSION, "status": "unavailable", "points": []}
    tl = tl if tl is not None else timeline(replay, team, model)
    times = [r["t"] for r in tl]
    cands = []
    for i, r in enumerate(tl):
        j = bisect.bisect_left(times, r["t"] + WINDOW_S)
        if j >= len(tl) or tl[j]["t"] - r["t"] > WINDOW_S + 0.6:
            continue
        cands.append((tl[j]["control"] - r["control"], r["t"], tl[j]["t"]))
    cands.sort(key=lambda c: -abs(c[0]))
    chosen = []
    for d, ta, tb in cands:
        if len(chosen) >= k:
            break
        if all(abs(ta - c[1]) >= MIN_SEPARATION_S for c in chosen):
            chosen.append((d, ta, tb))
    pts = []
    for d, ta, tb in sorted(chosen, key=lambda c: c[1]):
        a = attribute(replay, team, ta, tb, model)
        pts.append({"t_start": ta, "t_end": tb, "direction": "gain" if d > 0 else "loss", **a})
    changes = sorted(abs(c[0]) for c in cands)
    return {"version": VERSION, "status": "ok", "team": team, "points": pts, "samples": len(tl),
            "change_p90": round(changes[int(0.9 * (len(changes) - 1))], 4) if changes else None,
            "selection": "retrospective (largest model-score changes over 2 s, both directions)"}
