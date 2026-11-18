"""Kinematic reachability: how soon could a car touch the ball, and how? (Round 5, checkpoint 2)

Replaces the Round 4 "distance over a clamped closing speed" estimate. For each
car it simulates several approaches from the car's state at t0 and reports the
fastest one, an interval, the approach used, and every assumption and unknown.

Model (Rocket League constants as documented by the RLBot community and
RocketSim; validated against real replays in ``scripts/benchmark_reachability.py``):

- Ground car: forward speed along its nose, heading from the rotation-derived
  forward vector, throttle curve (1600 uu/s^2 at rest falling to 0 at 1410 uu/s),
  boost (+991.7 uu/s^2, 33.3 boost/s, max 2300 uu/s), braking 3500 uu/s^2, and a
  speed-dependent maximum turning curvature.
- Approaches: drive (boosting if boost remains), brake-then-turn, powerslide
  turn (1.35x curvature, calibrated on replay turn rates), forward dodge
  (+500 uu/s, ~1.2 s without control), half-flip for targets behind.
- Ball contact height: a single jump, double jump, or boosted aerial is added
  for raised balls; the lower bound assumes the climb overlaps the drive.
- Airborne car: either keep flying toward the ball (optimistic) or land on its
  ballistic arc and drive (pessimistic).
- Ball path: gravity, drag, floor/wall/ceiling bounces (restitution 0.6). The
  car may arrive early and wait, so the answer is the earliest time T at which
  the car can be where the ball is at T.

Not modelled (each pushes real times up or down): powerslide speed loss, wall
driving, aerial steering, car-to-car bumps, other cars blocking, the goal
mouth, spin on the ball. Cars on a wall abstain.

Only the t0 car and ball states are read. Nothing after t0 is used.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

GRAVITY = 650.0
MAX_SPEED = 2300.0
BOOST_ACCEL = 991.667
BOOST_PER_S = 33.3
BRAKE = 3500.0
REACH_UU = 165.0              # car centre to ball centre at a front contact on a ground ball (hitbox half-length + offset + ball radius)
CONTACT_3D = 240.0            # car centre to ball centre within which a touch is already possible (corner/roof contacts)
GROUND_HIT_Z = 170.0          # ball centre height reachable without jumping
DT = 1.0 / 30.0
HORIZON_S = 4.0
T_STEP = 0.1
CURVATURE = [(0.0, 0.0069), (500.0, 0.00398), (1000.0, 0.00235), (1500.0, 0.001375), (1750.0, 0.0011), (2300.0, 0.00088)]
ARENA_X, ARENA_Y, CEILING = 4096.0, 5120.0, 2044.0
BALL_R = 92.75
MODEL_VERSION = "kinematic-reach/0.1"


def throttle_accel(v: float) -> float:
    v = abs(v)
    if v < 1400.0:
        return 1600.0 - 1440.0 * v / 1400.0
    if v < 1410.0:
        return 160.0 * (1410.0 - v) / 10.0
    return 0.0


def max_curvature(v: float) -> float:
    v = min(abs(v), 2300.0)
    for (v0, k0), (v1, k1) in zip(CURVATURE, CURVATURE[1:]):
        if v <= v1:
            return k0 + (k1 - k0) * (v - v0) / (v1 - v0)
    return CURVATURE[-1][1]


def _wrap(a: float) -> float:
    return (a + math.pi) % (2 * math.pi) - math.pi


# ---------- states ----------

@dataclass
class CarState:
    x: float
    y: float
    z: float
    vx: float
    vy: float
    vz: float
    heading: float | None        # radians, from the forward vector; None if unknown
    boost: float | None
    mode: str                    # ground | air | wall


def car_state(car: dict | None) -> tuple[CarState | None, str | None]:
    """Build a state from one frame's car dict. Returns (state, reason_if_unusable)."""
    if not car:
        return None, "car absent at t0"
    if car.get("demolished"):
        return None, "car demolished at t0"
    v = car.get("velocity")
    if not v or any(c is None for c in v):
        return None, "car velocity unknown at t0"
    x, y, z = float(car.get("x", 0.0)), float(car.get("y", 0.0)), float(car.get("z", 17.0))
    fwd = car.get("forward")
    heading = None
    if fwd and math.hypot(fwd[0], fwd[1]) > 0.3:
        heading = math.atan2(fwd[1], fwd[0])
    on_wall = (abs(x) > ARENA_X - 200 or abs(y) > ARENA_Y - 200) and z > 80
    if on_wall:
        mode = "wall"
    elif z < 40 and (fwd is None or abs(fwd[2]) < 0.35):
        mode = "ground"
    else:
        mode = "air"
    b = car.get("boost")
    return CarState(x, y, z, float(v[0]), float(v[1]), float(v[2]), heading,
                    None if b is None else float(b), mode), None


@dataclass
class BallPoint:
    t: float
    x: float
    y: float
    z: float


def predict_ball(ball: dict, horizon: float = HORIZON_S, dt: float = DT) -> list[BallPoint]:
    """Ballistic ball path with drag and bounces. Spin and goals are ignored."""
    x, y, z = float(ball["x"]), float(ball["y"]), float(ball["z"])
    vx, vy, vz = (float(c) for c in ball["velocity"])
    out = [BallPoint(0.0, x, y, z)]
    t = 0.0
    while t < horizon - 1e-9:
        t += dt
        vz -= GRAVITY * dt
        drag = 1.0 - 0.0305 * dt
        vx, vy, vz = vx * drag, vy * drag, vz * drag
        x, y, z = x + vx * dt, y + vy * dt, z + vz * dt
        if z < BALL_R:
            z = BALL_R
            if vz < 0:
                vz = -0.6 * vz if -vz > 30 else 0.0
                vx, vy = vx * 0.92, vy * 0.92
        if z > CEILING - BALL_R and vz > 0:
            z, vz = CEILING - BALL_R, -0.6 * vz
        if abs(x) > ARENA_X - BALL_R:
            x = math.copysign(ARENA_X - BALL_R, x)
            vx = -0.6 * vx
        if abs(y) > ARENA_Y - BALL_R and not (abs(x) < 893 and z < 642):
            y = math.copysign(ARENA_Y - BALL_R, y)
            vy = -0.6 * vy
        out.append(BallPoint(t, x, y, z))
    return out


# ---------- climbing to a raised ball ----------

def _simplest(options: list[tuple[float, str]]) -> tuple[float, str]:
    rank = {"single jump": 0, "double jump": 1, "aerial": 2}
    return min(options, key=lambda o: (round(o[0], 3), rank[o[1]]))


def climb_time(height: float, boost: float | None) -> tuple[float | None, str]:
    """Time for the car's roof to rise to a ball centre at ``height``; None if out of reach."""
    need = height - GROUND_HIT_Z
    if need <= 0:
        return 0.0, "ground"
    # single jump: 291.7 uu/s impulse, +1458 uu/s^2 held for 0.2 s; second jump at 0.25 s
    options: list[tuple[float, str]] = []
    for jumps in (1, 2):
        t, z, vz = 0.0, 0.0, 291.667
        while t < 1.6:
            acc = (1458.33 if t < 0.2 else 0.0) - GRAVITY
            if jumps == 2 and abs(t - 0.25) < DT / 2:
                vz += 291.667
            vz += acc * DT
            z += vz * DT
            t += DT
            if z >= need:
                options.append((t, "single jump" if jumps == 1 else "double jump"))
                break
            if vz < 0 and t > 0.3:
                break
    if boost is not None and boost <= 5:
        return _simplest(options) if options else (None, "aerial needs boost")
    # boosted aerial: double jump then net +341 uu/s^2 upward (boost minus gravity, nose up)
    t, z, vz = 0.0, 0.0, 291.667
    while t < 3.0:
        acc = (1458.33 if t < 0.2 else 0.0) + (BOOST_ACCEL if t >= 0.25 else 0.0) - GRAVITY
        if abs(t - 0.25) < DT / 2:
            vz += 291.667
        vz += acc * DT
        z += vz * DT
        t += DT
        if z >= need:
            options.append((t, "aerial"))
            break
    return _simplest(options) if options else (None, "too high")


# ---------- ground approaches ----------

def _drive(c: CarState, tx: float, ty: float, t_max: float, *, use_boost: bool, brake_turn: bool,
           dodge: bool, half_flip: bool, slide: float = 1.0) -> float | None:
    """Simulate one approach toward a fixed point; time to come within reach, or None."""
    x, y, th = c.x, c.y, c.heading
    v = c.vx * math.cos(th) + c.vy * math.sin(th)      # speed along the nose; sideways slide dropped
    b = c.boost if c.boost is not None else 0.0
    t, flip_left, dodged = 0.0, 0.0, False
    if half_flip:
        ang = _wrap(math.atan2(ty - y, tx - x) - th)
        if abs(ang) < 2.0:
            return None
        while v > 0 and t < t_max:                      # brake to a stop
            v = max(0.0, v - BRAKE * DT)
            x += v * math.cos(th) * DT
            y += v * math.sin(th) * DT
            t += DT
        for _ in range(int(0.25 / DT)):                 # reverse briefly
            v -= throttle_accel(v) * DT
            x += v * math.cos(th) * DT
            y += v * math.sin(th) * DT
            t += DT
        th = _wrap(th + math.pi)
        v = abs(v) + 500.0
        flip_left = 0.9
    while t <= t_max:
        dx, dy = tx - x, ty - y
        if math.hypot(dx, dy) <= REACH_UU:
            return t
        ang = _wrap(math.atan2(dy, dx) - th)
        if flip_left > 0:
            flip_left -= DT
        elif brake_turn and abs(ang) > 1.75 and v > 700:
            v = max(0.0, v - BRAKE * DT)
        else:
            if dodge and not dodged and abs(ang) < 0.2 and v < 2000 and math.hypot(dx, dy) > 1200:
                v, dodged, flip_left = min(MAX_SPEED, v + 500.0), True, 1.2
            else:
                acc = throttle_accel(v) if v >= 0 else BRAKE
                if use_boost and b > 0 and v < MAX_SPEED:
                    acc += BOOST_ACCEL
                    b -= BOOST_PER_S * DT
                v = min(MAX_SPEED, v + acc * DT)
            k = max_curvature(v) * (slide if abs(ang) > 0.5 else 1.0)
            turn = k * abs(v) * DT
            th = _wrap(th + max(-turn, min(turn, ang)))
        x += v * math.cos(th) * DT
        y += v * math.sin(th) * DT
        t += DT
    return None


APPROACHES = {
    "drive": dict(brake_turn=False, dodge=False, half_flip=False),
    "brake_and_turn": dict(brake_turn=True, dodge=False, half_flip=False),
    "dodge": dict(brake_turn=False, dodge=True, half_flip=False),
    "half_flip": dict(brake_turn=False, dodge=False, half_flip=True),
    # Replays show ~10-18% of 0.2 s ground windows turning tighter than the no-slide
    # limit (p95 about 1.2-1.36x): powerslides. Modelled as 1.35x curvature, no speed loss.
    "powerslide": dict(brake_turn=False, dodge=False, half_flip=False, slide=1.35),
}


def ground_time(c: CarState, tx: float, ty: float, t_max: float, use_boost: bool) -> tuple[float | None, str | None]:
    best: tuple[float | None, str | None] = (None, None)
    for name, kw in APPROACHES.items():
        r = _drive(c, tx, ty, t_max, use_boost=use_boost, **kw)
        if r is not None and (best[0] is None or r < best[0]):
            best = (r, name)
    return best


# ---------- the public estimate ----------

@dataclass
class Reach:
    status: str                          # ok | abstain | out_of_horizon
    t_min: float | None = None           # earliest feasible contact (s after t0) under optimistic assumptions
    t_max: float | None = None           # same contact under pessimistic assumptions
    approach: str | None = None
    contact: tuple[float, float, float] | None = None
    assumptions: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    reason: str | None = None
    model: str = MODEL_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in ("status", "t_min", "t_max", "approach", "contact", "assumptions",
                                              "unknowns", "reason", "model")}


def _intercept(c: CarState, path: list[BallPoint], use_boost: bool, overlap: bool) -> tuple[float, str, BallPoint] | None:
    step = max(1, int(round(T_STEP / DT)))
    for bp in path[::step]:
        climb, how = climb_time(bp.z, c.boost if use_boost else 0.0)
        if climb is None:
            continue
        budget = bp.t if overlap else bp.t - climb
        if budget < 0:
            continue
        g, name = ground_time(c, bp.x, bp.y, budget, use_boost)
        if g is None:
            continue
        total = max(g, climb) if overlap else g + climb
        if total <= bp.t + 1e-9:
            label = name if how == "ground" else f"{name} + {how}"
            return bp.t, label, bp
    return None


def _air_estimates(c: CarState, path: list[BallPoint]) -> tuple[float | None, float | None, str]:
    """Optimistic: fly straight at the ball at current speed plus boost. Pessimistic: land and drive."""
    speed = math.sqrt(c.vx ** 2 + c.vy ** 2 + c.vz ** 2)
    has_boost = (c.boost or 0.0) > 5
    lo = None
    for bp in path:
        d = math.dist((c.x, c.y, c.z), (bp.x, bp.y, bp.z)) - CONTACT_3D
        acc = BOOST_ACCEL if has_boost else 0.0
        reach = speed * bp.t + 0.5 * acc * bp.t ** 2
        if reach >= d:
            lo = bp.t
            break
    # land: z(t) = z + vz t - g t^2 / 2 = 17
    a, bq, cq = -GRAVITY / 2, c.vz, c.z - 17.0
    t_land = (-bq - math.sqrt(bq * bq - 4 * a * cq)) / (2 * a)
    hi = None
    if t_land < HORIZON_S:
        h = math.atan2(c.vy, c.vx) if math.hypot(c.vx, c.vy) > 100 else (c.heading or 0.0)
        landed = CarState(c.x + c.vx * t_land, c.y + c.vy * t_land, 17.0, c.vx, c.vy, 0.0, h, c.boost, "ground")
        rest = [BallPoint(bp.t - t_land, bp.x, bp.y, bp.z) for bp in path if bp.t >= t_land]
        r = _intercept(landed, rest, use_boost=has_boost, overlap=False) if rest else None
        if r is not None:
            hi = r[0] + t_land
    return lo, hi, f"lands in {t_land:.2f} s"


def estimate_reach(car: dict | None, ball: dict | None, horizon: float = HORIZON_S) -> Reach:
    """Earliest time this car could touch the ball, from t0 states only."""
    c, why = car_state(car)
    if c is None:
        return Reach("abstain", reason=why, unknowns=[why])
    if not ball or not ball.get("velocity") or any(v is None for v in ball["velocity"]):
        return Reach("abstain", reason="ball velocity unknown at t0", unknowns=["ball velocity unknown at t0"])
    if math.dist((c.x, c.y, c.z), (float(ball["x"]), float(ball["y"]), float(ball["z"]))) <= CONTACT_3D:
        return Reach("ok", 0.0, 0.0, "already at the ball", (round(float(ball["x"])), round(float(ball["y"])),
                     round(float(ball["z"]))), ["Car and ball are within contact distance at t0."], [])
    if c.mode == "wall":
        return Reach("abstain", reason="car on a wall: wall driving is not modelled")
    path = predict_ball(ball, horizon)
    assumptions = ["Ball path ignores spin and car interference.",
                   "Powerslide modelled as a tighter turn with no speed loss; sideways slide at t0 is dropped."]
    unknowns: list[str] = []
    if c.boost is None:
        unknowns.append("boost unknown at t0: optimistic bound assumes boost, pessimistic assumes none")
    if c.mode == "air":
        lo, hi, note = _air_estimates(c, path)
        assumptions.append(f"Airborne at t0 ({note}). Lower bound flies straight at the ball; upper bound lands and drives.")
        if lo is None and hi is None:
            return Reach("out_of_horizon", assumptions=assumptions, unknowns=unknowns, reason="no approach within horizon")
        return Reach("ok", lo if lo is not None else hi, hi, "aerial continuation" if lo is not None else "land and drive",
                     None, assumptions, unknowns)
    if c.heading is None:
        return Reach("abstain", reason="car orientation unknown at t0", unknowns=["car orientation unknown at t0"])
    boost_opt = c.boost is None or c.boost > 0
    best = _intercept(c, path, use_boost=boost_opt, overlap=True)
    if best is None:
        return Reach("out_of_horizon", assumptions=assumptions, unknowns=unknowns,
                     reason=f"no modelled approach reaches the ball within {horizon:.0f} s")
    worst = _intercept(c, path, use_boost=(c.boost or 0.0) > 0, overlap=False)
    t, how, bp = best
    if "jump" in how or "aerial" in how:
        assumptions.append("Lower bound assumes the jump is timed to finish as the car arrives.")
    return Reach("ok", t, None if worst is None else worst[0], how, (round(bp.x), round(bp.y), round(bp.z)),
                 assumptions, unknowns)


def baseline_reach(car: dict | None, ball: dict | None) -> float | None:
    """Round 4 estimate kept for comparison: distance to the ball's current spot over a clamped closing speed."""
    c, _ = car_state(car)
    if c is None or not ball:
        return None
    dx, dy = float(ball["x"]) - c.x, float(ball["y"]) - c.y
    d = math.hypot(dx, dy)
    closing = (c.vx * dx + c.vy * dy) / d if d > 1.0 else 0.0
    return d / min(max(closing + 1000.0, 500.0), 2300.0)
