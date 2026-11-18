"""Where can the ball go after a ground contact, and who gets it next? (Round 12)

The Round 10/11 engine only asked who reaches the ball first. A challenge that is
won can still hand the ball to the opponent's second player. This module models
the *value of the ball after a contact* from decision-time states, without
predicting a single outcome:

1. **Contact direction model, calibrated on real touches.** For a ground contact the
   ball's change in velocity points along the car-to-ball centre line, with a
   magnitude proportional to the closing speed: ``dv = k * max(closing, floor) * n``
   (``scripts/calibrate_contact_model.py`` fits ``k`` and measures the direction error
   on held-out matches; ``docs/round12/contact_model_calibration.json``).
2. **A cone, not a point.** Contact offset (where on the ball the car hits) is the
   player's choice and execution, so outgoing directions are sampled across the
   calibrated error band around the centre-line prediction. Directions are NOT
   weighted: the output is "in how many of the sampled directions", never a
   probability.
3. **Next-ball race per direction.** The ball is rolled forward (ground roll,
   drag, walls; no spin, no lift) and, at successive times, the cars that could be
   there by then (reachability lower bounds from t0) are compared with the
   calibrated ordering margin. Per direction the result is ``own``, ``opponents``,
   ``contested`` or ``loose``.

Scope: ground contacts only. Aerial, wall and ceiling contacts return
``unsupported`` (43% of decoder touches in the public cohort are airborne).
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .reachability import CarState, car_state, ground_time, predict_ball

MODEL = {
    "version": "contact-cone/0.1",
    "k": None, "floor_uu_s": 300.0, "cone_half_deg": None, "held_out_median_error_deg": None,
    "held_out_p75_error_deg": None, "held_out_touches": None,
    "source": "docs/round12/contact_model_calibration.json",
}
DIRECTIONS = 7
SAMPLE_TIMES_S = (0.4, 0.8, 1.2, 1.6, 2.0)
ORDER_MARGIN_S = 0.30            # lower end of the Round 11 margin band; ties within it are "contested"
TOUCHER_SPEED_FACTOR = 0.5       # assumption: the toucher keeps half its approach speed after contact
GROUND_BALL_Z = 300.0
GOAL_Y = 5120.0


def _load() -> None:
    f = Path(__file__).resolve().parent.parent / MODEL["source"]
    try:
        d = json.loads(f.read_text())
    except (OSError, ValueError):
        return
    MODEL.update(k=d["k"], cone_half_deg=d["cone_half_deg"], held_out_median_error_deg=d["held_out"]["median_deg"],
                 held_out_p75_error_deg=d["held_out"]["p75_deg"], held_out_touches=d["held_out"]["n"])


def _ready() -> bool:
    return MODEL["k"] is not None and MODEL["cone_half_deg"] is not None


def predicted_dv(car_xy: tuple[float, float], car_v: tuple[float, float], ball_xy: tuple[float, float],
                 ball_v: tuple[float, float], k: float | None = None) -> tuple[float, float]:
    """Calibrated ground-contact impulse: along the centre line, scaled by closing speed."""
    k = MODEL["k"] if k is None else k
    nx, ny = ball_xy[0] - car_xy[0], ball_xy[1] - car_xy[1]
    norm = math.hypot(nx, ny) or 1.0
    nx, ny = nx / norm, ny / norm
    closing = (car_v[0] - ball_v[0]) * nx + (car_v[1] - ball_v[1]) * ny
    m = k * max(closing, MODEL["floor_uu_s"])
    return m * nx, m * ny


def _rotate(v: tuple[float, float], deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    return v[0] * math.cos(a) - v[1] * math.sin(a), v[0] * math.sin(a) + v[1] * math.cos(a)


def cone_velocities(car_xy, car_v, ball_xy, ball_v, directions: int = DIRECTIONS) -> list[tuple[float, float, float]]:
    """Outgoing horizontal ball velocities across the calibrated band: (offset_deg, vx, vy)."""
    dv = predicted_dv(car_xy, car_v, ball_xy, ball_v)
    h = MODEL["cone_half_deg"]
    out = []
    for i in range(directions):
        off = -h + 2 * h * i / (directions - 1) if directions > 1 else 0.0
        rx, ry = _rotate(dv, off)
        out.append((round(off, 1), ball_v[0] + rx, ball_v[1] + ry))
    return out


def _arrival(c: CarState | None, x: float, y: float, horizon: float) -> float | None:
    """Earliest arrival at a point. Ground: kinematic model; air: straight line at top speed (a lower bound)."""
    if c is None:
        return None
    if c.mode == "ground" and c.heading is not None:
        t, _ = ground_time(c, x, y, horizon, (c.boost or 0.0) > 0)
        return math.inf if t is None else t
    if c.mode == "wall":
        return None
    return max(0.0, math.hypot(x - c.x, y - c.y) - 150.0) / 2300.0


def race_after_contact(cars: dict[str, dict | None], team_of: dict[str, str], toucher: str,
                       contact_xyz: tuple[float, float, float], contact_t: float,
                       approach_v: tuple[float, float], ball_v_at_contact: tuple[float, float],
                       focus_team: str, *, include_toucher: bool = True) -> dict[str, Any]:
    """Per sampled contact direction: which team could take the next touch (own / opponents / contested / loose)."""
    if not _ready():
        return {"status": "unsupported", "reason": "contact model not calibrated"}
    if contact_xyz[2] > GROUND_BALL_Z:
        return {"status": "unsupported", "reason": "aerial contact: not modelled"}
    states: dict[str, CarState | None] = {}
    unknown = []
    for pid, raw in cars.items():
        if pid == toucher:
            continue
        st, _ = car_state(raw)
        states[pid] = st
        if st is None or st.mode == "wall":
            unknown.append(pid)
    sp = math.hypot(*approach_v) * TOUCHER_SPEED_FACTOR
    heading = math.atan2(approach_v[1], approach_v[0]) if math.hypot(*approach_v) > 1 else 0.0
    toucher_after = CarState(contact_xyz[0], contact_xyz[1], 17.0, sp * math.cos(heading), sp * math.sin(heading), 0.0,
                             heading, None, "ground")
    approach_from = (contact_xyz[0] - approach_v[0] * 0.1, contact_xyz[1] - approach_v[1] * 0.1)
    rows = []
    for off, vx, vy in cone_velocities(approach_from, approach_v, contact_xyz[:2], ball_v_at_contact):
        path = predict_ball({"x": contact_xyz[0], "y": contact_xyz[1], "z": 93.0, "velocity": [vx, vy, 0.0]},
                            horizon=max(SAMPLE_TIMES_S) + 0.05)
        result, where = "loose", None
        for tau in SAMPLE_TIMES_S:
            bp = path[min(len(path) - 1, int(round(tau * 30)))]
            T = contact_t + tau
            arr = {}
            for pid, st in states.items():
                a = _arrival(st, bp.x, bp.y, T + 1.0)
                if a is not None:
                    arr[pid] = a
            ta = _arrival(toucher_after, bp.x, bp.y, tau + 1.0) if include_toucher else None
            if ta is not None:
                arr[toucher] = contact_t + ta
            able = {pid: a for pid, a in arr.items() if a <= T}
            if not able:
                continue
            best = min(able.values())
            near = {team_of.get(pid) for pid, a in arr.items() if a <= best + ORDER_MARGIN_S and a <= T + ORDER_MARGIN_S}
            if len(near) > 1:
                result = "contested"
            else:
                result = "own" if near == {focus_team} else "opponents"
            own_half = (bp.y if focus_team == "blue" else -bp.y) < 0
            where = {"tau_s": tau, "ball_xy": [round(bp.x), round(bp.y)], "in_own_half": own_half}
            break
        rows.append({"offset_deg": off, "next_ball": result, "at": where})
    counts = {k: sum(r["next_ball"] == k for r in rows) for k in ("own", "opponents", "contested", "loose")}
    danger = sum(r["next_ball"] == "opponents" and r["at"] and r["at"]["in_own_half"] for r in rows)
    return {"status": "ok" if not unknown else "partial", "unknown_cars": unknown, "directions": rows,
            "counts": counts, "opponents_in_own_half": danger, "sampled_directions": len(rows),
            "cone_half_deg": MODEL["cone_half_deg"], "model": MODEL["version"],
            "assumptions": ["Ground contact; outgoing direction sampled across the calibrated error band, unweighted.",
                            "Ball rolls on the ground after contact (no lift, no spin).",
                            f"The toucher keeps {TOUCHER_SPEED_FACTOR:.0%} of its approach speed.",
                            "Car arrival times are kinematic lower bounds from the decision-time state."]}


ZONE_TIME_S = 1.0


def zone_of(x: float, y: float, team: str) -> str:
    """Coarse field zone in the given team's frame (own goal at -y)."""
    ry, rx = (y if team == "blue" else -y), (x if team == "blue" else -x)
    if abs(rx) > 3600:
        return "side_wall"
    if ry < -3400:
        return "own_goal_area" if abs(rx) < 1800 else "own_corner"
    if ry > 3400:
        return "opponent_goal_area" if abs(rx) < 1800 else "opponent_corner"
    if ry < -1000:
        return "own_half"
    if ry > 1000:
        return "opponent_half"
    return "midfield"


def destination_zones(car_xy, car_v, ball_xyz, ball_v, team: str, directions: int = DIRECTIONS) -> dict[str, Any]:
    """Validated part of the model: where the ball goes (zone after ZONE_TIME_S) across the contact band."""
    if not _ready():
        return {"status": "unsupported", "reason": "contact model not calibrated"}
    if ball_xyz[2] > GROUND_BALL_Z:
        return {"status": "unsupported", "reason": "aerial contact: not modelled"}
    rows = []
    for off, vx, vy in cone_velocities(car_xy, car_v, ball_xyz[:2], ball_v, directions):
        path = predict_ball({"x": ball_xyz[0], "y": ball_xyz[1], "z": 93.0, "velocity": [vx, vy, 0.0]},
                            horizon=ZONE_TIME_S + 0.05)
        bp = path[min(len(path) - 1, int(round(ZONE_TIME_S * 30)))]
        rows.append({"offset_deg": off, "zone": zone_of(bp.x, bp.y, team), "ball_xy": [round(bp.x), round(bp.y)],
                     "speed_uu_s": round(math.hypot(vx, vy))})
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["zone"]] = counts.get(r["zone"], 0) + 1
    centre = rows[len(rows) // 2]["zone"]
    return {"status": "ok", "directions": rows, "zone_counts": counts, "centre_zone": centre,
            "sampled_directions": len(rows), "cone_half_deg": MODEL["cone_half_deg"], "model": MODEL["version"],
            "validated": "outgoing direction (held-out median error in calibration file)",
            "assumptions": ["Ground contact; outgoing direction sampled across the calibrated error band, unweighted.",
                            f"Ball position {ZONE_TIME_S:.0f} s after contact with ground roll, drag and walls; no spin or lift."]}


def summarise(r: dict[str, Any]) -> str | None:
    """Plain wording for a race result (counts of sampled directions, never a probability)."""
    if r.get("status") not in ("ok", "partial"):
        return None
    c, n = r["counts"], r["sampled_directions"]
    lead = max(c, key=c.get)
    word = {"own": "the own team could take the next touch", "opponents": "an opponent could take the next touch",
            "contested": "the next ball would be contested", "loose": "nobody could reach the ball within 2 s"}[lead]
    return f"In {c[lead]} of {n} modelled contact directions (unweighted), {word}."


_load()
