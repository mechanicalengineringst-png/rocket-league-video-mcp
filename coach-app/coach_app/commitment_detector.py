"""Physics-based tactical commitment window detection for Rocket League replays.

Distinguishes:
1. Cognitive intention / acceleration onset (t_earliest): When the car transitions from
   shadowing, circling, or neutral positioning to actively accelerating/boosting toward the play.
2. Irreversible physical commitment (t_latest): The point of no return where stopping or
   aborting is physically impossible under Rocket League friction, braking, and ballistic jump dynamics.
3. Agency window [t_earliest, t_latest]: The critical interval where tactical choice exists.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


# Rocket League physical constants (Unreal Units / cm)
MAX_BRAKING_DECEL = 3500.0       # Max ground braking deceleration (cm/s^2)
MAX_CAR_SPEED = 2300.0           # Supersonic speed threshold (cm/s)
RESTING_CAR_Z = 17.0             # Car center height resting flat on wheels (cm)
JUMP_AIRBORNE_Z = 28.0           # Minimum center height indicating airborne jump (cm)


@dataclass(frozen=True)
class CommitmentWindow:
    """Represents the temporal window during which a player executed a tactical commitment."""

    t_earliest: float            # Cognitive / acceleration onset (seconds)
    t_latest: float              # Physical irreversibility / point of no return (seconds)
    t_recommended_t0: float      # Recommended observation instant for coaching evaluation
    primary_constraint: str      # "jump_dodge", "stopping_distance_exceeded", or "boost_acceleration_lock"
    stopping_distance_at_t0: float  # Minimum stopping distance v^2 / (2 * a_brake) in cm
    closing_speed_at_t0: float   # Speed along vector toward contest target (cm/s)
    uncertainty_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "t_earliest_s": round(self.t_earliest, 3),
            "t_latest_s": round(self.t_latest, 3),
            "t_recommended_t0_s": round(self.t_recommended_t0, 3),
            "window_duration_s": round(max(0.0, self.t_latest - self.t_earliest), 3),
            "primary_constraint": self.primary_constraint,
            "stopping_distance_cm": round(self.stopping_distance_at_t0, 1),
            "closing_speed_cms": round(self.closing_speed_at_t0, 1),
            "uncertainty_reasons": list(self.uncertainty_reasons),
        }


def detect_commitment_window(
    frames: list[dict[str, Any]],
    player_id: str,
    t_contest_start: float,
    max_lookback_s: float = 2.5,
) -> CommitmentWindow:
    """Identify the authentic physical commitment window leading into a contest.

    Scans frames in [t_contest_start - max_lookback_s, t_contest_start] to detect:
    1. Jump / dodge initiation (airborne ballistic trajectory cannot be ground-braked).
    2. Stopping distance point-of-no-return (distance to target < v^2 / (2 * a_brake)).
    3. Longitudinal acceleration / boost expenditure onset toward the target.
    """
    if not frames:
        t0 = round(max(0.0, t_contest_start - 0.4), 3)
        return CommitmentWindow(
            t_earliest=t0,
            t_latest=t_contest_start,
            t_recommended_t0=t0,
            primary_constraint="fallback_fixed_offset",
            stopping_distance_at_t0=0.0,
            closing_speed_at_t0=0.0,
            uncertainty_reasons=("No telemetry frames provided; fell back to fixed offset.",),
        )

    # Window of relevant frames leading into the contest
    t_min = max(0.0, t_contest_start - max_lookback_s)
    sub_frames = [f for f in frames if t_min <= f.get("t", 0.0) <= t_contest_start]

    if len(sub_frames) < 2:
        t0 = round(max(0.0, t_contest_start - 0.4), 3)
        return CommitmentWindow(
            t_earliest=t0,
            t_latest=t_contest_start,
            t_recommended_t0=t0,
            primary_constraint="sparse_frames_fallback",
            stopping_distance_at_t0=0.0,
            closing_speed_at_t0=0.0,
            uncertainty_reasons=("Telemetry frames too sparse in pre-contest window.",),
        )

    t_jump: float | None = None
    t_no_stop: float | None = None
    t_accel: float | None = None
    primary_constraint = "stopping_distance_exceeded"
    uncertainties: list[str] = []

    # 1. Forward scan: find when jump/dodge or point-of-no-return occurs
    for f in sub_frames:
        t = f.get("t", 0.0)
        cars = f.get("cars", {})
        car = cars.get(player_id)
        if not car:
            continue
        ball = f.get("ball", {})

        v = car.get("velocity", [0.0, 0.0, 0.0])
        speed = math.hypot(v[0], v[1], v[2])
        dist = math.hypot(car.get("x", 0.0) - ball.get("x", 0.0), car.get("y", 0.0) - ball.get("y", 0.0))

        # Max ground stopping distance under full emergency braking
        stop_dist = (speed * speed) / (2.0 * MAX_BRAKING_DECEL)

        # Check airborne jump / dodge activation
        is_jump = bool(car.get("jumpActive")) or (car.get("z", RESTING_CAR_Z) > JUMP_AIRBORNE_Z and v[2] > 50.0)
        if is_jump and t_jump is None:
            t_jump = t

        # Check stopping distance point-of-no-return
        if dist <= stop_dist and t_no_stop is None:
            t_no_stop = t

    # 2. Backward scan: find the onset of forward acceleration and boost toward the contest
    for i in range(len(sub_frames) - 1, 0, -1):
        f_curr = sub_frames[i]
        f_prev = sub_frames[i - 1]
        t = f_curr.get("t", 0.0)

        c_curr = f_curr.get("cars", {}).get(player_id)
        c_prev = f_prev.get("cars", {}).get(player_id)
        if not c_curr or not c_prev:
            continue

        ball = f_curr.get("ball", {})
        dx = ball.get("x", 0.0) - c_curr.get("x", 0.0)
        dy = ball.get("y", 0.0) - c_curr.get("y", 0.0)
        d_len = math.hypot(dx, dy)
        if d_len > 1.0:
            nx, ny = dx / d_len, dy / d_len
            v_curr = c_curr.get("velocity", [0.0, 0.0, 0.0])
            v_prev = c_prev.get("velocity", [0.0, 0.0, 0.0])

            # Closing velocity along vector toward ball
            v_close_curr = v_curr[0] * nx + v_curr[1] * ny
            v_close_prev = v_prev[0] * nx + v_prev[1] * ny
            dv_close = v_close_curr - v_close_prev

            boost_used = max(0.0, c_prev.get("boost", 0.0) - c_curr.get("boost", 0.0))

            # Active acceleration toward target: positive velocity increase or boost expenditure
            if (dv_close > 15.0 and v_close_curr > 400.0) or (boost_used > 0.4 and v_close_curr > 500.0):
                t_accel = t

    # Resolve t_latest (physical point of no return)
    candidates_latest = [t for t in (t_jump, t_no_stop) if t is not None]
    if candidates_latest:
        t_latest = min(candidates_latest)
        if t_latest == t_jump:
            primary_constraint = "jump_airborne_lock"
        else:
            primary_constraint = "stopping_distance_exceeded"
    else:
        # Fallback if car stayed slow on ground until collision
        t_latest = max(0.0, t_contest_start - 0.15)
        primary_constraint = "contact_proximity_cutoff"

    # Resolve t_earliest (intention / acceleration onset)
    if t_accel is not None and t_accel < t_latest:
        t_earliest = t_accel
    else:
        # If steady-speed approach without change point, lookback 0.5s before latest
        t_earliest = max(t_min, t_latest - 0.5)
        uncertainties.append("No distinct acceleration change point found; estimated from steady approach.")

    # Recommended evaluation instant: at earliest commitment when player had agency
    t_rec = round(t_earliest, 3)

    # Telemetry metrics at t_recommended
    rec_frames = [f for f in sub_frames if f.get("t", 0.0) <= t_rec]
    car_rec = rec_frames[-1].get("cars", {}).get(player_id) if rec_frames else None
    ball_rec = rec_frames[-1].get("ball", {}) if rec_frames else None

    if car_rec:
        v_rec = car_rec.get("velocity", [0.0, 0.0, 0.0])
        spd_rec = math.hypot(v_rec[0], v_rec[1], v_rec[2])
        stop_dist_rec = (spd_rec * spd_rec) / (2.0 * MAX_BRAKING_DECEL)
        if ball_rec:
            bx, by = ball_rec.get("x", 0.0), ball_rec.get("y", 0.0)
            cx, cy = car_rec.get("x", 0.0), car_rec.get("y", 0.0)
            d_ball = math.hypot(bx - cx, by - cy)
            closing_spd = ((bx - cx) * v_rec[0] + (by - cy) * v_rec[1]) / max(1.0, d_ball)
        else:
            closing_spd = spd_rec
    else:
        stop_dist_rec = 0.0
        closing_spd = 0.0

    return CommitmentWindow(
        t_earliest=round(t_earliest, 3),
        t_latest=round(t_latest, 3),
        t_recommended_t0=t_rec,
        primary_constraint=primary_constraint,
        stopping_distance_at_t0=round(stop_dist_rec, 1),
        closing_speed_at_t0=round(closing_spd, 1),
        uncertainty_reasons=tuple(uncertainties),
    )
