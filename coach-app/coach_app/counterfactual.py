"""Physics-informed counterfactuals for the next second (Round 13, experimental).

Question answered: *if the focus player had started action family A at t0, what would the field look
like a moment later, before anyone could touch the ball?* Not: what would the ball do after a contact
(Round 12 showed the next ball cannot be predicted better than the base rate).

Method, from the t0 frame only:
1. The ball follows its ballistic path (``predict_ball``).
2. The horizon is cut at the earliest moment any car could touch the ball (kinematic lower bound), or
   ``HORIZON_S``, whichever is first: beyond a possible contact nothing is modelled.
3. The focus car is simulated driving each action family (steering limited by the speed-dependent
   curvature, throttle and boost acceleration, boost consumed):
     commit        toward the ball's predicted position at the horizon
     shadow        toward the goal-side point of the ball's predicted position, no boost
     retreat       toward the own goal centre
     big_boost / small_boost   toward the nearest available pad (availability from pickups <= t0)
4. The other three cars continue their t0 velocity (a stated assumption; they would react).
5. Each resulting frame is scored with field control and the team recovery debt, plus, if supplied,
   the learned future-control model (``value_model``).

``validate`` compares the simulated position of the family the player actually chose with where the
car really was, against a constant-velocity baseline (``scripts/counterfactual_study.py``).
"""
from __future__ import annotations

import copy
import math
from typing import Any

from . import field_control as fc
from .boost_pad_events import PADS
from .reachability import BOOST_ACCEL, BOOST_PER_S, MAX_SPEED, estimate_reach, max_curvature, predict_ball, throttle_accel

VERSION = "counterfactual/0.1"
HORIZON_S = 1.0
MIN_HORIZON_S = 0.25
DT = 1.0 / 30.0
FAMILIES = ("commit", "shadow", "retreat", "big_boost", "small_boost")
GOAL_Y = 5120.0


def _pad_available(events: list[dict], t0: float, pad: dict) -> bool:
    window = 10.0 if pad["big"] else 4.0
    return not any(e.get("type") == "boost_pickups" and e.get("padId") == pad["id"] and
                   isinstance(e.get("t"), (int, float)) and t0 - window < e["t"] <= t0 for e in events)


def drive(car: dict, target: tuple[float, float], tau: float, *, use_boost: bool, speed_cap: float | None = None) -> dict:
    """Simple car simulation toward a target for tau seconds; returns the car dict at tau."""
    x, y = float(car["x"]), float(car["y"])
    vx, vy = float(car["velocity"][0]), float(car["velocity"][1])
    fw = car.get("forward") or [vx, vy, 0.0]
    h = math.atan2(fw[1], fw[0]) if math.hypot(fw[0], fw[1]) > 1e-6 else math.atan2(vy, vx)
    v = math.hypot(vx, vy) * (1 if (vx * math.cos(h) + vy * math.sin(h)) >= 0 else -1)
    b = float(car.get("boost") or 0.0)
    t = 0.0
    while t < tau - 1e-9:
        dt = min(DT, tau - t)
        want = math.atan2(target[1] - y, target[0] - x)
        err = (want - h + math.pi) % (2 * math.pi) - math.pi
        dist = math.hypot(target[0] - x, target[1] - y)
        rate = max(abs(v), 300.0) * max_curvature(max(abs(v), 300.0))
        h += max(-rate * dt, min(rate * dt, err))
        cap = MAX_SPEED if (use_boost and b > 0) else min(MAX_SPEED, max(abs(v), 1410.0))
        if speed_cap is not None:
            cap = min(cap, speed_cap)
        if dist < 200:                                   # arrived: brake to a stop
            acc = -min(3500.0, abs(v) / dt) * (1 if v > 0 else -1)
        elif abs(err) > 2.2 and v > 300:                 # facing away: brake and turn
            acc = -3500.0
        else:
            acc = throttle_accel(abs(v)) if v < cap else -525.0
            if use_boost and b > 0 and v < cap and abs(err) < 1.0:
                acc += BOOST_ACCEL
                b = max(0.0, b - BOOST_PER_S * dt)
        v = max(-1400.0, min(cap if v <= cap else v, v + acc * dt))
        x += v * math.cos(h) * dt
        y += v * math.sin(h) * dt
        x, y = max(-4000.0, min(4000.0, x)), max(-5000.0, min(5000.0, y))
        t += dt
    return {**car, "x": x, "y": y, "z": 17.0, "velocity": [v * math.cos(h), v * math.sin(h), 0.0],
            "forward": [math.cos(h), math.sin(h), 0.0], "boost": b}


def coast(car: dict, tau: float) -> dict:
    v = car["velocity"]
    out = copy.deepcopy(car)
    out["x"] = max(-4000.0, min(4000.0, car["x"] + v[0] * tau))
    out["y"] = max(-5000.0, min(5000.0, car["y"] + v[1] * tau))
    if car.get("z", 17) > 40:
        out["z"] = max(17.0, car["z"] + v[2] * tau - 325.0 * tau * tau)
    return out


def horizon(frame: dict, cap: float = HORIZON_S) -> float:
    ts = []
    for c in frame.get("cars", {}).values():
        r = estimate_reach(c, frame.get("ball"), horizon=cap + 0.1)
        if r.status == "ok":
            ts.append(r.t_min)
    return max(MIN_HORIZON_S, min([cap] + ts))


def targets(frame: dict, focus: str, team: str, tau: float, events: list[dict], t0: float) -> dict[str, tuple]:
    path = predict_ball(frame["ball"], horizon=tau + 0.05)
    bp = path[min(len(path) - 1, int(round(tau * 30)))]
    s = 1 if team == "blue" else -1
    c = frame["cars"][focus]
    gx, gy = fc.goal_side_point({"x": bp.x, "y": bp.y}, team)
    out = {"commit": ((bp.x, bp.y), True, None), "shadow": ((gx, gy), False, None),
           "retreat": ((0.0, -s * (GOAL_Y - 300)), True, None)}
    for name, big in (("big_boost", True), ("small_boost", False)):
        pads = [p for p in PADS if p["big"] == big and _pad_available(events, t0, p)]
        if pads:
            p = min(pads, key=lambda q: math.hypot(q["x"] - c["x"], q["y"] - c["y"]))
            out[name] = ((p["x"], p["y"]), True, None)
    return out


def evaluate(frame: dict, team_of: dict[str, str], focus: str, *, events: list[dict] | None = None,
             value_model=None, cap: float = HORIZON_S) -> dict[str, Any] | None:
    """Counterfactual field states for each action family at the pre-contact horizon (t0 frame only)."""
    events = [e for e in (events or []) if isinstance(e.get("t"), (int, float)) and e["t"] <= frame["t"] + 1e-9]
    team = team_of.get(focus)
    cars = frame.get("cars", {})
    if team not in ("blue", "orange") or focus not in cars or not cars[focus] or len(cars) < 4:
        return None
    if cars[focus].get("z", 17) > 60:
        return {"version": VERSION, "status": "unsupported", "reason": "focus car airborne: aerial control not modelled"}
    tau = horizon(frame, cap)
    others = {p: coast(c, tau) for p, c in cars.items() if p != focus and c}
    ball = frame["ball"]
    path = predict_ball(ball, horizon=tau + 0.05)
    bp = path[min(len(path) - 1, int(round(tau * 30)))]
    vel = ball["velocity"]
    fut_ball = {"x": bp.x, "y": bp.y, "z": bp.z, "velocity": [vel[0] * 0.97, vel[1] * 0.97, vel[2]]}
    out = {"version": VERSION, "status": "ok", "horizon_s": round(tau, 2), "families": {},
           "assumptions": ["Other cars keep their t0 velocity until the horizon.",
                           "Horizon ends at the earliest possible touch by anyone; nothing after a contact is modelled.",
                           "Ballistic ball path (no spin)."]}
    for fam, (tgt, boost, cap_s) in targets(frame, focus, team, tau, events, frame["t"]).items():
        sim = drive(cars[focus], tgt, tau, use_boost=boost, speed_cap=cap_s)
        fr2 = {"t": frame["t"] + tau, "ball": fut_ball, "cars": {**others, focus: sim}}
        summ = fc.summarise(fr2, team_of, team)
        if summ is None:
            continue
        row = {"focus_xy": [round(sim["x"]), round(sim["y"])], "focus_boost": round(sim["boost"]),
               "own_half_control": summ["regions"]["own_half"]["own"],
               "own_goal_zone_control": summ["regions"]["own_goal_zone"]["own"],
               "ball_corridor_own": summ["regions"]["ball_corridor_2s"]["own"],
               "ball_corridor_opponent": summ["regions"]["ball_corridor_2s"]["opponent"],
               "team_recovery_debt_s": summ["team_debt"]["own"],
               "focus_recovery_debt_s": summ["recovery_debt"].get(focus)}
        if value_model is not None:
            row["value"] = value_model.score(fr2, team_of, team)
        out["families"][fam] = row
    return out
