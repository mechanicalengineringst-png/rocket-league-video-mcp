"""Decision-time state features for one team's perspective (Round 13).

Everything is computed from a single frame (plus nothing after it). The frame is mirrored for the
orange team so that "own goal" is always at -y. Players are ordered by role at that instant:
``own1``/``opp1`` = the player of that team with the earlier kinematic ball-reach time, ``own2``/``opp2``
the other. Missing values are NaN so models can see what was unknown.

Feature groups (used to test *which* information predicts the next seconds, ``scripts/future_control_study.py``):
- ``ball``: position, height, velocity
- ``reach``: kinematic earliest-touch times per role and the margins between teams (Rounds 10-12 core)
- ``players``: positions relative to ball/goal, speed, boost, facing, closing speed, goal-side
- ``control``: field-control region shares and recovery debt (field_control.py)
"""
from __future__ import annotations

import math
from typing import Any

from . import field_control as fc
from .reachability import estimate_reach

GOAL_Y = 5120.0
NAN = float("nan")
GROUPS: dict[str, list[str]] = {}


def _mirror_car(c: dict, team: str) -> dict:
    if team == "blue":
        return c
    v = c.get("velocity") or [0.0, 0.0, 0.0]
    f = c.get("forward") or [0.0, 0.0, 0.0]
    return {**c, "x": -c["x"], "y": -c["y"], "velocity": [-v[0], -v[1], v[2]], "forward": [-f[0], -f[1], f[2]]}


def mirror_frame(frame: dict, team: str) -> dict:
    if team == "blue":
        return frame
    b = frame["ball"]
    bv = b.get("velocity") or [0.0, 0.0, 0.0]
    return {**frame, "ball": {**b, "x": -b["x"], "y": -b["y"], "velocity": [-bv[0], -bv[1], bv[2]]},
            "cars": {p: (_mirror_car(c, team) if c else c) for p, c in frame.get("cars", {}).items()}}


def reach_times(frame: dict) -> dict[str, float | None]:
    """Earliest kinematic touch time per car (inf = beyond horizon, None = unknown). Perspective-free."""
    out = {}
    for pid, c in frame.get("cars", {}).items():
        r = estimate_reach(c, frame.get("ball"))
        out[pid] = r.t_min if r.status == "ok" else (math.inf if r.status == "out_of_horizon" else None)
    return out


def _cap(t: float | None, cap: float = 5.0) -> float:
    if t is None:
        return NAN
    return min(t, cap)


def frame_features(frame: dict, team_of: dict[str, str], team: str, *, reach: dict | None = None) -> dict[str, float] | None:
    ball = frame.get("ball")
    cars = frame.get("cars", {})
    if not ball or ball.get("velocity") is None or len([p for p in cars if cars[p]]) < 4:
        return None
    reach = reach if reach is not None else reach_times(frame)
    m = mirror_frame(frame, team)
    b = m["ball"]
    own = [p for p in cars if team_of.get(p) == team and cars[p]]
    opp = [p for p in cars if team_of.get(p) not in (None, team) and cars[p]]
    if len(own) != 2 or len(opp) != 2:
        return None

    def key(p):
        t = reach.get(p)
        return math.inf if t is None else t

    own.sort(key=key)
    opp.sort(key=key)
    f: dict[str, float] = {
        "ball_x_abs": abs(b["x"]), "ball_y": b["y"], "ball_z": b["z"], "ball_vy": b["velocity"][1],
        "ball_vx_abs": abs(b["velocity"][0]), "ball_vz": b["velocity"][2], "ball_speed": math.hypot(*b["velocity"][:2]),
        "ball_own_goal_dist": math.hypot(b["x"], b["y"] + GOAL_Y), "ball_opp_goal_dist": math.hypot(b["x"], b["y"] - GOAL_Y),
    }
    r = {f"{tag}{i + 1}": _cap(reach.get(p)) for tag, grp in (("own", own), ("opp", opp)) for i, p in enumerate(grp)}
    f.update({f"reach_{k}": v for k, v in r.items()})
    f["reach_margin_first"] = r["opp1"] - r["own1"]               # > 0: own team is first
    f["reach_margin_second"] = r["opp2"] - r["own2"]
    f["reach_own_gap"] = r["own2"] - r["own1"]
    f["reach_opp_gap"] = r["opp2"] - r["opp1"]
    for tag, grp in (("own", own), ("opp", opp)):
        for i, p in enumerate(grp):
            c = m["cars"][p]
            v = c.get("velocity") or [0.0, 0.0, 0.0]
            fw = c.get("forward") or [0.0, 0.0, 0.0]
            dx, dy = b["x"] - c["x"], b["y"] - c["y"]
            d = math.hypot(dx, dy) or 1.0
            k = f"{tag}{i + 1}"
            f[f"{k}_y_rel_ball"] = c["y"] - b["y"]
            f[f"{k}_x_rel_ball_abs"] = abs(c["x"] - b["x"])
            f[f"{k}_dist_ball"] = d
            f[f"{k}_own_goal_dist"] = math.hypot(c["x"], c["y"] + GOAL_Y) if tag == "own" else math.hypot(c["x"], c["y"] - GOAL_Y)
            f[f"{k}_speed"] = math.hypot(v[0], v[1])
            f[f"{k}_boost"] = float(c.get("boost") if c.get("boost") is not None else NAN)
            f[f"{k}_z"] = c["z"]
            f[f"{k}_facing_ball"] = (fw[0] * dx + fw[1] * dy) / d
            f[f"{k}_closing"] = (v[0] * dx + v[1] * dy) / d
            f[f"{k}_goal_side"] = float((c["y"] < b["y"]) if tag == "own" else (c["y"] > b["y"]))
    ctl = fc.control(frame, team_of)
    if ctl is not None:
        reg = fc.regions(frame, team, ctl)
        for name in ("own_half", "own_goal_zone", "opponent_goal_zone", "ball_corridor_2s"):
            f[f"ctl_{name}_own"] = _nan(reg[name]["own"])
            f[f"ctl_{name}_opp"] = _nan(reg[name]["opponent"])
        f["ctl_field_own"] = _nan(reg["field"]["own"])
        debt = fc.recovery_debt(frame, team_of)
        for tag, grp in (("own", own), ("opp", opp)):
            for i, p in enumerate(grp):
                f[f"debt_{tag}{i + 1}"] = _nan(debt.get(p))
    return f


def _nan(v: Any) -> float:
    return NAN if v is None else float(v)


def group_of(name: str) -> str:
    if name.startswith("ball_"):
        return "ball"
    if name.startswith("reach_"):
        return "reach"
    if name.startswith(("ctl_", "debt_")):
        return "control"
    return "players"
