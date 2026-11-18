"""Team-perspective strategic state at t0, built on reachability (Round 5, checkpoint 3).

Instead of distances and fixed zones, the state is expressed in *time*:

- ``race``: each car's earliest feasible touch (reachability lower bound) and the
  team margin = fastest opponent minus fastest teammate. Positive means the focus
  team can get to the ball first. The interval comes from the cars' optimistic
  and pessimistic bounds.
- ``roles``: first and second player per team by feasible touch time, not by y.
- ``cover``: how soon the focus's teammate could get goal-side: 0 if already
  between the ball and the own goal (within 1500 uu of that line), otherwise the
  time to a point a third of the way from the ball to the own goal.
- ``boost``: both teams' boost, unknowns listed.

Every number is from the t0 frame. ``None`` means unknown, never zero.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .reachability import Reach, car_state, estimate_reach, ground_time

GOAL_Y = 5120.0


def _frame_at(frames: list[dict], t0: float, lookback: float = 0.15) -> dict | None:
    lo, hi = 0, len(frames)
    while lo < hi:
        mid = (lo + hi) // 2
        if frames[mid].get("t", 0.0) <= t0:
            lo = mid + 1
        else:
            hi = mid
    i = lo - 1
    if i < 0 or t0 - frames[i].get("t", 0.0) > lookback:
        return None
    return frames[i]


@dataclass
class StrategicState:
    t0: float
    focus: str
    team: str
    reach: dict[str, dict[str, Any]]                      # pid -> Reach.to_dict()
    team_of: dict[str, str]
    margin_s: float | None                                # fastest opponent minus fastest teammate
    margin_interval: tuple[float | None, float | None]
    first_man: dict[str, str | None]                      # team -> pid
    focus_is_first: bool | None
    cover_s: float | None                                 # teammate time to goal-side point
    opponent_first_touch_s: float | None
    boost: dict[str, float | None]
    unknowns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _t(r: Reach) -> float | None:
    if r.status == "ok":
        return r.t_min
    if r.status == "out_of_horizon":
        return math.inf
    return None


def _t_hi(r: Reach) -> float | None:
    if r.status == "ok":
        return r.t_max if r.t_max is not None else r.t_min
    if r.status == "out_of_horizon":
        return math.inf
    return None


def goal_side_point(ball: dict, team: str) -> tuple[float, float]:
    """A point a third of the way from the ball to the team's own goal centre."""
    own_y = -GOAL_Y if team == "blue" else GOAL_Y
    return ball["x"] * 2 / 3, ball["y"] + (own_y - ball["y"]) / 3


def _already_goal_side(x: float, y: float, ball: dict, team: str, lateral_uu: float = 1500.0) -> bool:
    """Between the ball and the own goal, and within ``lateral_uu`` of the ball-to-goal line."""
    own_y = -GOAL_Y if team == "blue" else GOAL_Y
    by, bx = ball["y"], ball["x"]
    if not (min(by, own_y) <= y <= max(by, own_y)):
        return False
    u = (y - by) / (own_y - by) if own_y != by else 0.0
    line_x = bx + u * (0.0 - bx)
    return abs(x - line_x) <= lateral_uu


def build_state(payload: dict[str, Any], t0: float, focus: str,
                reach_cache: dict[str, Reach] | None = None) -> StrategicState | None:
    frames = payload.get("frames", [])
    team_of = {p["id"]: p.get("team") for p in payload.get("players", [])}
    team = team_of.get(focus)
    fr = _frame_at(frames, t0)
    if fr is None or team not in ("blue", "orange"):
        return None
    ball = fr.get("ball")
    unknowns: list[str] = []
    reach: dict[str, Reach] = {}
    for pid in team_of:
        if reach_cache is not None and pid in reach_cache:
            reach[pid] = reach_cache[pid]
        else:
            reach[pid] = estimate_reach(fr["cars"].get(pid), ball)
            if reach_cache is not None:
                reach_cache[pid] = reach[pid]
        if reach[pid].status == "abstain":
            unknowns.append(f"{pid}: {reach[pid].reason}")
    mates = [p for p, tm in team_of.items() if tm == team]
    opps = [p for p, tm in team_of.items() if tm not in (None, team)]

    def fastest(pids, f):
        vals = [(f(reach[p]), p) for p in pids]
        if any(v is None for v, _ in vals) or not vals:
            return None, None
        return min(vals)

    m_t, m_p = fastest(mates, _t)
    o_t, o_p = fastest(opps, _t)
    margin = None if m_t is None or o_t is None or math.isinf(m_t) and math.isinf(o_t) else o_t - m_t
    m_hi, _ = fastest(mates, _t_hi)
    o_hi, _ = fastest(opps, _t_hi)
    # pessimistic for us: our slow bound vs their fast bound, and vice versa
    lo = None if m_hi is None or o_t is None else o_t - m_hi
    hi = None if m_t is None or o_hi is None else o_hi - m_t
    _, o_first = fastest(opps, _t)
    cover = None
    mate = next((p for p in mates if p != focus), None)
    if mate and ball:
        c, why = car_state(fr["cars"].get(mate))
        if c is None or c.mode != "ground" or c.heading is None:
            unknowns.append(f"teammate cover time unknown ({why or c.mode if c else why})")
        elif _already_goal_side(c.x, c.y, ball, team):
            cover = 0.0
        else:
            gx, gy = goal_side_point(ball, team)
            g, _ = ground_time(c, gx, gy, 4.0, (c.boost or 0) > 0)
            cover = math.inf if g is None else g
    boost = {p: (fr["cars"].get(p) or {}).get("boost") for p in team_of}
    return StrategicState(
        t0, focus, team, {p: r.to_dict() for p, r in reach.items()}, team_of,
        None if margin is None or math.isinf(margin) else round(margin, 3),
        (None if lo is None or math.isinf(lo) else round(lo, 3), None if hi is None or math.isinf(hi) else round(hi, 3)),
        {team: m_p, "opponent": o_first},
        None if m_p is None else m_p == focus,
        None if cover is None else (round(cover, 3) if not math.isinf(cover) else math.inf),
        None if o_t is None else (round(o_t, 3) if not math.isinf(o_t) else math.inf),
        boost, unknowns)


def distance_margin(payload: dict[str, Any], t0: float, focus: str) -> float | None:
    """Baseline representation: nearest opponent distance minus nearest teammate distance (uu)."""
    fr = _frame_at(payload.get("frames", []), t0)
    team_of = {p["id"]: p.get("team") for p in payload.get("players", [])}
    if fr is None or not fr.get("ball"):
        return None
    b = fr["ball"]
    d = {p: math.dist((c["x"], c["y"], c["z"]), (b["x"], b["y"], b["z"])) for p, c in fr["cars"].items()}
    team = team_of.get(focus)
    mine = [d[p] for p in d if team_of.get(p) == team]
    theirs = [d[p] for p in d if team_of.get(p) not in (None, team)]
    if not mine or not theirs:
        return None
    return min(theirs) - min(mine)
