"""Field control: who can get where first, across the whole field (Round 13).

Rounds 10-12 asked one question about space: who reaches *the ball* first. High-level 2v2 is
decided as much by the space around the ball: where the next touch can go, who can reach those
places, and how long each player needs before they are useful again. This module computes, from a
single frame (no future):

- ``arrival_times``: a vectorised kinematic arrival-time estimate for each car to every point of a
  field grid (turn at the speed-dependent curvature, then accelerate along the line; airborne cars
  land first). Calibrated against ``reachability.ground_time`` (``scripts/calibrate_field_control.py``).
- ``control``: per grid cell, which team arrives first by more than the ordering band, else contested.
- region summaries: own-half, own-goal zone, and the predicted ball corridor over the next 2 s.
- ``recovery_debt``: per player, seconds to reach the goal-side point (0 if already goal-side and
  facing play); per team, the summed debt of players not on the ball.

Grid control is a *physical reachability* statement ("this team can be there first"), not a
probability and not a statement of intent. It ignores the ball's influence on cars, bumps and demos.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from .reachability import GRAVITY, MAX_SPEED, predict_ball

VERSION = "field-control/0.1"
FIELD_X, FIELD_Y = 4096.0, 5120.0
CELL = 256.0
BAND_S = 0.30                     # Round 11 ordering band (lower end)
NO_BOOST_MAX = 1410.0
# Functional form and constants fitted to reachability.ground_time (scripts/calibrate_field_control.py,
# docs/round13/field_control_calibration.json): turn cost KT*phi, then accelerate along the line with an
# acceleration and top speed that scale with available boost.
KT = 0.15                         # s per radian of heading change
ACC_BOOST = 2200.0
ACC_NO_BOOST = 400.0
KEEP = 0.5                        # speed kept along the new line ~ cos(phi)**KEEP
ARC_CREDIT = 0.6                  # distance covered while turning, as a share of |v| * phi / pi
BOOST_FULL = 25.0                 # boost amount above which full boosted acceleration is assumed
TURN_CAP_S = 1.2
REACH_UU = 120.0

_xs = np.arange(-FIELD_X + CELL / 2, FIELD_X, CELL)
_ys = np.arange(-FIELD_Y + CELL / 2, FIELD_Y, CELL)
GX, GY = np.meshgrid(_xs, _ys)          # rows = y, cols = x
GRID = np.stack([GX.ravel(), GY.ravel()], axis=1)


def arrival_times(car: dict, points: np.ndarray = GRID) -> np.ndarray | None:
    """Earliest-arrival estimate (s) of one car to each point; None if the car state is unusable."""
    try:
        x, y, z = float(car["x"]), float(car["y"]), float(car.get("z", 17.0))
        vx, vy, vz = (float(v) for v in car["velocity"][:3])
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (x, y, z, vx, vy, vz)):
        return None
    t0 = 0.0
    fwd = car.get("forward") or [vx, vy, 0.0]
    if z > 60.0:                                     # airborne: land first, keep horizontal velocity
        t0 = (vz + math.sqrt(max(vz * vz + 2 * GRAVITY * (z - 17.0), 0.0))) / GRAVITY
        x, y = x + vx * t0, y + vy * t0
        fwd = [vx, vy, 0.0]
    if abs(x) > FIELD_X + 50 or abs(y) > FIELD_Y + 50 or z > 2100:
        return None
    speed = math.hypot(vx, vy)
    hx, hy = fwd[0], fwd[1]
    hn = math.hypot(hx, hy)
    if hn < 1e-6:
        hx, hy, hn = (vx, vy, speed) if speed > 1 else (0.0, 1.0, 1.0)
    hx, hy = hx / hn, hy / hn
    dx, dy = points[:, 0] - x, points[:, 1] - y
    d = np.hypot(dx, dy)
    cosphi = np.clip((dx * hx + dy * hy) / np.maximum(d, 1e-6), -1.0, 1.0)
    phi = np.arccos(cosphi)
    v_fwd = speed if (vx * hx + vy * hy) >= 0 else -speed
    bo = float(car.get("boost") or 0.0)
    f = min(max(bo / BOOST_FULL, 0.0), 1.0)
    acc = ACC_NO_BOOST + (ACC_BOOST - ACC_NO_BOOST) * f
    vmax = NO_BOOST_MAX + (MAX_SPEED - NO_BOOST_MAX) * min(max(bo / (BOOST_FULL * 0.5), 0.0), 1.0)
    v_start = np.where(phi < math.pi / 2, max(v_fwd, 0.0) * np.maximum(np.cos(phi), 0.0) ** KEEP, 0.0)
    v_start = np.minimum(v_start, vmax)
    dd = np.maximum(d - REACH_UU - ARC_CREDIT * abs(v_fwd) * phi / math.pi, 0.0)
    t_acc = (vmax - v_start) / acc
    d_acc = v_start * t_acc + 0.5 * acc * t_acc ** 2
    t_in = (-v_start + np.sqrt(np.maximum(v_start ** 2 + 2 * acc * dd, 0.0))) / acc
    t_line = np.where(dd <= d_acc, t_in, t_acc + (dd - d_acc) / vmax)
    t_turn = np.minimum(KT * phi, TURN_CAP_S)
    return t0 + t_turn + t_line


def _team_rel(team: str, y: np.ndarray | float) -> np.ndarray | float:
    return y if team == "blue" else -y


def control(frame: dict, team_of: dict[str, str], *, band: float = BAND_S,
            cars_override: dict[str, dict] | None = None) -> dict[str, Any] | None:
    """Team control of every grid cell. ``cars_override`` lets a counterfactual replace car states."""
    cars = dict(frame.get("cars", {}))
    if cars_override:
        cars.update(cars_override)
    times = {}
    for pid, c in cars.items():
        if team_of.get(pid) not in ("blue", "orange") or not c:
            continue
        t = arrival_times(c)
        if t is not None:
            times[pid] = t
    teams = {"blue": [p for p in times if team_of[p] == "blue"], "orange": [p for p in times if team_of[p] == "orange"]}
    if not teams["blue"] or not teams["orange"]:
        return None
    tb = np.min([times[p] for p in teams["blue"]], axis=0)
    to = np.min([times[p] for p in teams["orange"]], axis=0)
    owner = np.where(tb < to - band, 1, np.where(to < tb - band, -1, 0))   # +1 blue, -1 orange, 0 contested
    return {"times": times, "t_blue": tb, "t_orange": to, "owner": owner,
            "complete": len(times) == len([p for p in cars if team_of.get(p) in ("blue", "orange")])}


def _share(owner: np.ndarray, mask: np.ndarray, sign: int) -> float | None:
    n = int(mask.sum())
    if n == 0:
        return None
    return float(((owner == sign) & mask).sum() / n)


def regions(frame: dict, team: str, ctl: dict) -> dict[str, Any]:
    """Region control from the given team's perspective (shares of cells, not probabilities)."""
    sign = 1 if team == "blue" else -1
    ry = _team_rel(team, GRID[:, 1])
    gx = GRID[:, 0] * (1 if team == "blue" else -1)
    own_half = ry < 0
    own_goal = np.hypot(gx, ry + FIELD_Y) < 3000
    opp_goal = np.hypot(gx, ry - FIELD_Y) < 3000
    ball = frame.get("ball") or {}
    corridor = np.zeros(len(GRID), dtype=bool)
    if ball.get("velocity") is not None:
        path = predict_ball(ball, horizon=2.0)
        for bp in path[::6]:
            corridor |= np.hypot(GRID[:, 0] - bp.x, GRID[:, 1] - bp.y) < 900
    out = {}
    for name, m in (("own_half", own_half), ("own_goal_zone", own_goal), ("opponent_goal_zone", opp_goal),
                    ("ball_corridor_2s", corridor)):
        out[name] = {"own": _share(ctl["owner"], m, sign), "opponent": _share(ctl["owner"], m, -sign),
                     "contested": _share(ctl["owner"], m, 0)}
    out["field"] = {"own": _share(ctl["owner"], np.ones(len(GRID), bool), sign),
                    "opponent": _share(ctl["owner"], np.ones(len(GRID), bool), -sign)}
    return out


def goal_side_point(ball: dict, team: str) -> tuple[float, float]:
    """A third of the way from the ball to the own goal centre (the V1/R12 definition)."""
    own_y = -FIELD_Y if team == "blue" else FIELD_Y
    return ball["x"] * 2 / 3, ball["y"] + (own_y - ball["y"]) / 3


def recovery_debt(frame: dict, team_of: dict[str, str]) -> dict[str, Any]:
    """Seconds each player needs to be goal-side; 0 when already goal-side of the ball."""
    ball = frame.get("ball")
    out = {}
    if not ball:
        return out
    for pid, c in frame.get("cars", {}).items():
        team = team_of.get(pid)
        if team not in ("blue", "orange") or not c:
            continue
        if _team_rel(team, c["y"]) < _team_rel(team, ball["y"]) - 300:
            out[pid] = 0.0
            continue
        gx, gy = goal_side_point(ball, team)
        t = arrival_times(c, np.array([[gx, gy]]))
        out[pid] = None if t is None else round(float(t[0]), 2)
    return out


def summarise(frame: dict, team_of: dict[str, str], team: str, *, cars_override: dict | None = None) -> dict[str, Any] | None:
    ctl = control(frame, team_of, cars_override=cars_override)
    if ctl is None:
        return None
    fr = frame if not cars_override else {**frame, "cars": {**frame["cars"], **cars_override}}
    debt = recovery_debt(fr, team_of)
    own = [p for p in debt if team_of[p] == team]
    opp = [p for p in debt if team_of[p] != team]
    return {"version": VERSION, "regions": regions(frame, team, ctl), "recovery_debt": debt,
            "team_debt": {"own": _sum(debt, own), "opponent": _sum(debt, opp)}, "complete": ctl["complete"]}


def _sum(debt, ids):
    vals = [debt[p] for p in ids]
    return None if any(v is None for v in vals) else round(sum(vals), 2)
