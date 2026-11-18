"""Deterministic tactical reading of a 2v2 decision point (Round 4, Phase 2).

Everything here is computed from frames at or before ``t0``. Each statement is
typed so a reader (or a language model) can tell how much to trust it:

- ``fact``: a value read from telemetry at a stated frame time.
- ``derived``: a deterministic calculation from facts, with its assumptions named.
- ``interpretation``: a tactical reading of facts. Confidence is capped at
  "medium"; nothing here is validated against expert labels yet.

No function returns a scoring probability or a counterfactual outcome. Where an
answer would need one, the output says it is "not established".

Coordinates are rotated so the focus team always attacks +y (a 180-degree
rotation for orange). Units are Unreal units (uu) and seconds.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

import bisect

from .decision_cases import DecisionCase
from .reachability import car_state as reach_car_state
from .reachability import estimate_reach, ground_time

GOAL_Y = 5120.0
POST_X = 893.0
BALL_R = 93.0
LANE_BLOCK_UU = 200.0          # car half-width + ball radius + margin
ASSUMED_SHOT_SPEED = 2500.0    # uu/s; a firm grounded shot. An assumption, not a measurement.
BIG_PADS = [(-3072.0, -4096.0), (3072.0, -4096.0), (-3584.0, 0.0), (3584.0, 0.0),
            (-3072.0, 4096.0), (3072.0, 4096.0)]
ANALYSIS_VERSION = "tactical-reading/0.1"


# ---------- state at t0 ----------

@dataclass
class CarState:
    pid: str
    team: str
    x: float
    y: float
    z: float
    vx: float
    vy: float
    boost: float | None
    t_source: float | None

    @property
    def speed(self) -> float:
        return math.hypot(self.vx, self.vy)


@dataclass
class Reading:
    """The world at t0 from the focus team's perspective. Unknowns are listed, never filled."""

    t0: float
    focus: CarState | None
    mate: CarState | None
    opponents: list[CarState]
    ball: dict[str, float] | None
    unknowns: list[str] = field(default_factory=list)
    names: dict[str, str] = field(default_factory=dict)
    raw_cars: dict[str, dict] = field(default_factory=dict)    # world-frame car dicts at t0 (for reachability)
    raw_ball: dict | None = None

    @property
    def complete(self) -> bool:
        return self.focus is not None and self.ball is not None and not self.unknowns


def _rot(team: str, x: float, y: float) -> tuple[float, float]:
    return (x, y) if team == "blue" else (-x, -y)


_TIMES: dict[int, tuple[list[dict], list[float]]] = {}


def _frame_at_or_before(frames: list[dict], t: float, max_lookback_s: float = 0.15) -> dict | None:
    """Latest frame with time <= t (never a later one), within a short lookback."""
    key = id(frames)
    cached = _TIMES.get(key)
    if cached is None or cached[0] is not frames or len(cached[1]) != len(frames):
        cached = (frames, [f.get("t", 0.0) for f in frames])
        _TIMES.clear()
        _TIMES[key] = cached
    i = bisect.bisect_right(cached[1], t) - 1
    if i < 0 or t - cached[1][i] > max_lookback_s:
        return None
    return frames[i]


def _find_car_at_time(frames: list[dict], t: float, pid: str) -> dict | None:
    fr = _frame_at_or_before(frames, t)
    return None if fr is None else (fr.get("cars") or {}).get(pid)


def _find_ball_at_time(frames: list[dict], t: float) -> dict | None:
    fr = _frame_at_or_before(frames, t)
    return None if fr is None else fr.get("ball")


def _car_state(frames: list[dict], t0: float, pid: str, team: str, focus_team: str) -> CarState | None:
    car = _find_car_at_time(frames, t0, pid)
    if not car or car.get("demolished"):
        return None
    v = car.get("velocity") or [None, None, None]
    if v[0] is None or v[1] is None:
        return None
    x, y = _rot(focus_team, float(car.get("x", 0.0)), float(car.get("y", 0.0)))
    vx, vy = _rot(focus_team, float(v[0]), float(v[1]))
    b = car.get("boost")
    return CarState(pid, team, x, y, float(car.get("z", 17.0)), vx, vy, None if b is None else float(b), t0)


def read_state(payload: dict[str, Any], t0: float, focus_id: str) -> Reading:
    frames = payload.get("frames", [])
    players = {p["id"]: p for p in payload.get("players", [])}
    team = players.get(focus_id, {}).get("team")
    unknowns: list[str] = []
    if team not in ("blue", "orange"):
        return Reading(t0, None, None, [], None, ["Focus player's team is unknown."])
    focus = _car_state(frames, t0, focus_id, team, team)
    if focus is None:
        unknowns.append("Focus player's car state at t0 is unknown (absent, demolished or not sampled).")
    mates = [p for p, info in players.items() if info.get("team") == team and p != focus_id]
    mate = _car_state(frames, t0, mates[0], team, team) if mates else None
    if mate is None:
        unknowns.append("Teammate position at t0 is unknown.")
    opps = []
    for p, info in players.items():
        if info.get("team") not in (None, team):
            s = _car_state(frames, t0, p, info["team"], team)
            if s is None:
                unknowns.append(f"Opponent {info.get('name', p)} position at t0 is unknown.")
            else:
                opps.append(s)
    raw_ball = _find_ball_at_time(frames, t0)
    ball = None
    if raw_ball and raw_ball.get("velocity"):
        bx, by = _rot(team, float(raw_ball.get("x", 0.0)), float(raw_ball.get("y", 0.0)))
        bvx, bvy = _rot(team, float(raw_ball["velocity"][0]), float(raw_ball["velocity"][1]))
        ball = {"x": bx, "y": by, "z": float(raw_ball.get("z", 93.0)), "vx": bvx, "vy": bvy,
                "vz": float(raw_ball["velocity"][2])}
    else:
        unknowns.append("Ball state at t0 is unknown.")
    for s in [focus, mate, *opps]:
        if s is not None and s.boost is None:
            unknowns.append(f"Boost of {players.get(s.pid, {}).get('name', s.pid)} at t0 is unknown.")
    raw = {p: _find_car_at_time(frames, t0, p) for p in players}
    return Reading(t0, focus, mate, opps, ball, unknowns, {p: i.get("name", p) for p, i in players.items()},
                   {p: c for p, c in raw.items() if c}, raw_ball if ball is not None else None)


def kin_time(r: Reading, pid: str, target: tuple[float, float] | None = None) -> float | None:
    """Kinematic lower bound (s) for ``pid`` to touch the ball, or to reach a team-frame point.

    Uses only the t0 states. ``math.inf`` = not within the model horizon; ``None`` = unknown
    (wall, demolished, no heading, airborne for point targets).
    """
    car = r.raw_cars.get(pid)
    if target is None:
        if r.raw_ball is None:
            return None
        e = estimate_reach(car, r.raw_ball)
        return e.t_min if e.status == "ok" else (math.inf if e.status == "out_of_horizon" else None)
    c, _ = reach_car_state(car)
    if c is None or c.mode != "ground" or c.heading is None:
        return None
    team = r.focus.team if r.focus else "blue"
    wx, wy = _rot(team, target[0], target[1])          # the rotation is its own inverse
    t, _ = ground_time(c, wx, wy, 4.0, (c.boost or 0.0) > 0)
    return math.inf if t is None else t


def _fmt_t(t: float | None) -> str:
    return "unknown" if t is None else ("more than 4 s" if math.isinf(t) else f"{t:.1f} s")


def time_to_point(car: CarState, px: float, py: float) -> float:
    """Round 4 arrival-time approximation, kept only as a comparison baseline.

    Superseded by ``kin_time`` (coach_app.reachability), which models heading,
    turning, boost, jumps and the ball's motion. See docs/round5/02_REACHABILITY.md.
    """
    dx, dy = px - car.x, py - car.y
    d = math.hypot(dx, dy)
    closing = (car.vx * dx + car.vy * dy) / d if d > 1.0 else 0.0
    return d / min(max(closing + 1000.0, 500.0), 2300.0)


# ---------- typed statements ----------

@dataclass
class Statement:
    kind: str                      # fact | derived | interpretation
    text: str
    inputs: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    confidence: str | None = None  # interpretations only: low | medium

    def __post_init__(self) -> None:
        if self.kind not in ("fact", "derived", "interpretation"):
            raise ValueError("Statement kind must be fact, derived or interpretation.")
        if self.kind == "interpretation" and self.confidence not in ("low", "medium"):
            raise ValueError("Interpretations carry low or medium confidence, never high.")


@dataclass
class Alternative:
    action: str
    feasibility: str               # plausible | unclear | implausible
    basis: str
    unknowns: list[str] = field(default_factory=list)


@dataclass
class Finding:
    case_id: str
    t0: float
    situation: str
    headline: str
    verdict: str                   # reinforce | tradeoff | missed_opportunity_hypothesis | risk_hypothesis | situation_brief | abstain
    statements: list[Statement]
    alternatives: list[Alternative]
    unknowns: list[str]
    not_established: list[str]
    reviewed_action: str | None = None
    ranking: dict[str, Any] = field(default_factory=dict)
    factors: dict[str, Any] = field(default_factory=dict)   # the verdict's inputs; None = unknown
    version: str = ANALYSIS_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


VERDICTS = {"reinforce", "tradeoff", "missed_opportunity_hypothesis", "risk_hypothesis", "situation_brief", "abstain"}


# ---------- shot geometry (Example A) ----------

def shot_lane(r: Reading) -> dict[str, Any]:
    """How much of the goal mouth is unblocked from the ball, and who can reach the line.

    Nine targets across the goal mouth; a target is blocked if a known opponent is
    ahead of the ball and within ``LANE_BLOCK_UU`` of the straight path.
    """
    b = r.ball
    targets = [-(POST_X - BALL_R) + i * (2 * (POST_X - BALL_R) / 8) for i in range(9)]
    open_count = 0
    for tx in targets:
        sx, sy = tx - b["x"], GOAL_Y - b["y"]
        seg2 = sx * sx + sy * sy
        blocked = False
        for o in r.opponents:
            u = ((o.x - b["x"]) * sx + (o.y - b["y"]) * sy) / seg2 if seg2 > 0 else 0.0
            if 0.0 < u <= 1.05:
                px, py = b["x"] + u * sx, b["y"] + u * sy
                if math.hypot(o.x - px, o.y - py) < LANE_BLOCK_UU:
                    blocked = True
                    break
        open_count += not blocked
    dist_goal = math.hypot(b["x"], GOAL_Y - b["y"])
    ball_time = dist_goal / ASSUMED_SHOT_SPEED
    reach = []
    for o in r.opponents:
        # nearest point on the centre line between ball and goal
        sx, sy = -b["x"], GOAL_Y - b["y"]
        seg2 = sx * sx + sy * sy
        u = min(max(((o.x - b["x"]) * sx + (o.y - b["y"]) * sy) / seg2, 0.0), 1.0) if seg2 > 0 else 1.0
        px, py = b["x"] + u * sx, b["y"] + u * sy
        t_def = kin_time(r, o.pid, (px, py))
        reach.append({"pid": o.pid, "time_to_line_s": t_def, "ball_time_s": ball_time * u,
                      "slack_s": None if t_def is None else t_def - ball_time * u, "boost": o.boost,
                      "speed": o.speed, "goal_side": o.y > b["y"]})
    return {"open_fraction": open_count / len(targets), "dist_to_goal": dist_goal,
            "ball_time_s": ball_time, "defenders": reach}


def has_possession(r: Reading) -> bool:
    """Focus is the nearest car to a low ball, moving with it. A heuristic, not a control detector."""
    if r.focus is None or r.ball is None:
        return False
    b, f = r.ball, r.focus
    d = math.hypot(f.x - b["x"], f.y - b["y"])
    nearest = all(math.hypot(o.x - b["x"], o.y - b["y"]) > d for o in r.opponents)
    rel = math.hypot(f.vx - b["vx"], f.vy - b["vy"])
    return nearest and d < 350.0 and rel < 700.0 and b["z"] < 400.0


def assess_shot(r: Reading, case_id: str, reviewed_action: str | None = None) -> Finding:
    names = r.names
    if r.ball is None or r.focus is None:
        return _abstain(case_id, r, "possession_shot_opportunity", "Ball or focus state unknown at t0.")
    lane = shot_lane(r)
    st = [
        Statement("fact", f"Ball {lane['dist_to_goal']:.0f} uu from the opponent goal centre, {r.ball['z']:.0f} uu high.", ["ball"]),
        Statement("derived", f"{lane['open_fraction'] * 9:.0f} of 9 straight lines from ball to goal mouth are unblocked by a known opponent.",
                  ["ball", "opponents"], [f"A car within {LANE_BLOCK_UU:.0f} uu of a line blocks it; ball curve and bounces ignored."]),
    ]
    for d in sorted(lane["defenders"], key=lambda d: (d["slack_s"] is None, d["slack_s"] or 0.0)):
        boost = "unknown boost" if d["boost"] is None else f"{d['boost']:.0f} boost"
        who = f"Defender {names.get(d['pid'], d['pid'])} ({boost}, {d['speed']:.0f} uu/s, {'goal-side' if d['goal_side'] else 'not goal-side'})"
        if d["slack_s"] is None:
            st.append(Statement("fact", f"{who}: time to the shot line is unknown (airborne, on a wall or no heading at t0).",
                                [d["pid"]]))
            continue
        st.append(Statement(
            "derived", f"{who} could reach the shot line at the earliest {d['slack_s']:+.2f} s relative to the ball.",
            [d["pid"]], [f"Shot travels at {ASSUMED_SHOT_SPEED:.0f} uu/s.",
                         "Defender time is a kinematic lower bound (fastest feasible), so 'late' is conservative."]))
    unseen = [u for u in r.unknowns if "Opponent" in u] + \
        [f"Defender {names.get(d['pid'], d['pid'])} time to the shot line is unknown." for d in lane["defenders"] if d["slack_s"] is None]
    min_slack = min((d["slack_s"] for d in lane["defenders"] if d["slack_s"] is not None), default=float("inf"))
    low_boost_but_close = [d for d in lane["defenders"] if d["boost"] is not None and d["boost"] < 20
                           and d["slack_s"] is not None and d["slack_s"] <= 0]
    alts = []
    factors = {"all_opponents_known": not unseen, "ball_low": r.ball["z"] <= 300,
               "lane_mostly_open": lane["open_fraction"] >= 0.45, "defenders_late": min_slack > 0.15}
    feas, basis = shot_feasibility(factors)
    alts.append(Alternative("immediate shot", feas, basis, unseen))
    weak_pressure = [d for d in lane["defenders"] if d["boost"] is not None and d["boost"] < 20 and d["speed"] < 300]
    if has_possession(r):
        basis = "Ball under control by the possession heuristic at t0."
        if weak_pressure and len(weak_pressure) == len(lane["defenders"]):
            basis += " Every known defender is low on boost and nearly stationary, so pressure on a carry is limited."
        alts.append(Alternative("keep possession (dribble or carry)", "plausible", basis, ["Dribble outcomes are not modelled."]))
    else:
        alts.append(Alternative("keep possession (dribble or carry)", "unclear", "Possession at t0 is not established.",
                                ["Dribble outcomes are not modelled."]))
    if low_boost_but_close:
        st.append(Statement("interpretation",
                            "A defender is low on boost but already close to the shot line; low boost does not stop a grounded save.",
                            [d["pid"] for d in low_boost_but_close], confidence="medium"))
    headline = {"shot": "Shot taken while the lane was open",
                "no_shot": "An immediate shot appears feasible here"}.get(reviewed_action or "", "Open shooting lane at t0") \
        if feas == "plausible" else "No clear shot at t0"
    if feas == "plausible" and reviewed_action == "shot":
        st.append(Statement("interpretation", "Shooting matched a favourable read: open lane, no defender ahead of the ball.",
                            confidence="medium"))
    elif feas == "plausible" and reviewed_action == "no_shot":
        st.append(Statement("interpretation",
                            "An immediate shot appears feasible from ball control and defender positions. Whether it beat the "
                            "play that followed is not known.", confidence="low"))
    verdict = shot_verdict(factors, reviewed_action)
    return Finding(case_id, r.t0, "possession_shot_opportunity", headline, verdict, st, alts, list(r.unknowns),
                   ["Scoring probability of the shot.", "Whether the player saw the lane.", "Value of the alternative actually taken."],
                   reviewed_action, factors=factors)


def shot_feasibility(factors: dict[str, Any]) -> tuple[str, str]:
    """Pure rule: shot-lane factors -> feasibility of an immediate shot."""
    if not factors["all_opponents_known"]:
        return "unclear", "An opponent's position is unknown, so the net cannot be called open."
    if not factors["ball_low"]:
        return "unclear", "The ball is in the air; a shot needs an aerial touch whose reliability is not measured."
    if factors["lane_mostly_open"] and factors["defenders_late"]:
        return "plausible", "Most of the goal mouth is unblocked and no known defender reaches the line before the ball."
    return "implausible", "The lane is mostly blocked or a defender reaches the line first."


def shot_verdict(factors: dict[str, Any], reviewed_action: str | None) -> str:
    feas = shot_feasibility(factors)[0]
    if feas != "plausible":
        return "abstain"
    return {"shot": "reinforce", "no_shot": "missed_opportunity_hypothesis"}.get(reviewed_action or "", "situation_brief")


# ---------- first-man challenge (Example B) ----------

def assess_challenge(r: Reading, case_id: str) -> Finding:
    if r.focus is None or r.ball is None:
        return _abstain(case_id, r, "first_man_challenge", "Focus or ball state unknown at t0.")
    f, b = r.focus, r.ball
    st: list[Statement] = [
        Statement("fact", f"At t0 the ball is at y={b['y']:+.0f} (attacking toward +y), {b['z']:.0f} uu high, "
                          f"{abs(b['x']):.0f} uu from the centre line.", ["ball"]),
    ]
    if f.boost is not None:
        st.append(Statement("fact", f"Challenger has {f.boost:.0f} boost and is {math.hypot(f.x, f.y + GOAL_Y):.0f} uu from their own goal.", ["focus"]))
    deep_corner = b["y"] > 4200 and (abs(b["x"]) > 2000 or b["z"] > 600)
    if deep_corner:
        st.append(Statement("interpretation",
                            "The ball is in the opponent's corner or high on their backboard: a contact here tends to send it "
                            "into the wall or corner rather than toward goal.", ["ball"],
                            ["Ball direction after contact is not simulated."], "medium"))
    factors: dict[str, bool | None] = {"low_leverage_ball": deep_corner}
    if r.mate is None:
        factors["teammate_exposed_1v2"] = None
    else:
        m = r.mate
        mate_goal_side = m.y < b["y"]
        mate_own_goal = math.hypot(m.x, m.y + GOAL_Y)
        # The opponent NOT in the 50/50 is the one who collects a spill.
        opp_t = {o.pid: kin_time(r, o.pid) for o in r.opponents}
        known = None not in opp_t.values()
        others = sorted(r.opponents, key=lambda o: opp_t[o.pid]) if known else []
        spare = others[1] if len(others) > 1 else None
        st.append(Statement("fact", f"Teammate is {'goal-side' if mate_goal_side else 'not goal-side'} of the ball, "
                                    f"{mate_own_goal:.0f} uu from own goal"
                                    + ("" if m.boost is None else f", {m.boost:.0f} boost") + ".", ["mate"]))
        exposed = True if not mate_goal_side else None
        mate_t = kin_time(r, m.pid)
        if spare is not None and mate_t is not None:
            spare_t = opp_t[spare.pid]
            st.append(Statement("derived", f"Earliest feasible touch: second opponent {_fmt_t(spare_t)}, teammate {_fmt_t(mate_t)}.",
                                [spare.pid, "mate"], ["Kinematic lower bounds from t0 (reachability model)."]))
            # Exposed: the teammate is up the field too, or the opponent not in the
            # 50/50 could reach a loose ball before the teammate could.
            exposed = (not mate_goal_side) or spare_t < mate_t
        elif exposed is None:
            st.append(Statement("fact", "An opponent's or the teammate's earliest touch is unknown at t0 (wall, air or no heading).",
                                ["opponents", "mate"]))
        factors["teammate_exposed_1v2"] = exposed
        if exposed:
            why = ("the teammate is not goal-side either" if not mate_goal_side
                   else "the second opponent reaches a loose ball before the teammate")
            st.append(Statement("interpretation",
                                f"If this challenge is lost, {why}: the teammate may have to defend two attackers.",
                                [spare.pid if spare else "opponents", "mate"], confidence="medium"))
    costly = None if f.boost is None else (f.boost < 30 and math.hypot(f.x, f.y + GOAL_Y) > 7000)
    factors["costly_recovery"] = costly
    if costly:
        st.append(Statement("interpretation", "Low boost and far from goal: getting back into the play after the challenge will be slow.",
                            ["focus"], confidence="medium"))
    pad = min(BIG_PADS, key=lambda p: math.hypot(p[0] - f.x, p[1] - f.y))
    alts = [
        Alternative("shadow back and cut off the clear", "plausible" if r.mate is not None else "unclear",
                    "Keeps a second defender between ball and goal; costs the chance to win possession now.",
                    [] if r.mate is not None else ["Teammate position unknown."]),
        Alternative(f"take the big boost about {math.hypot(pad[0] - f.x, pad[1] - f.y):.0f} uu away, then rejoin", "plausible",
                    "Distance only; whether it is reached before the opponents play the ball is not checked."),
        Alternative("challenge (what was done)", "plausible", "Observed retrospectively; included so it is compared, not assumed wrong."),
    ]
    verdict = challenge_verdict(factors)
    headline = CHALLENGE_HEADLINES[verdict]
    if verdict == "reinforce":
        st.append(Statement("interpretation", "No exposure factor was found at t0; the challenge fits the situation.",
                            confidence="low"))
    return Finding(case_id, r.t0, "first_man_challenge", headline, verdict, st, alts, list(r.unknowns),
                   ["Probability of winning the 50/50.", "Where the ball goes after contact.",
                    "Whether teammates had agreed who challenges."], "challenge", factors=factors)


CHALLENGE_HEADLINES = {
    "abstain": "Teammate coverage unknown: the challenge cannot be judged",
    "risk_hypothesis": "Low-value challenge that likely leaves your teammate in a 1v2",
    "reinforce": "Challenge looks supported: teammate covering, ball not trapped in the corner",
    "tradeoff": "Challenge with some exposure: compare with shadowing",
}


def challenge_verdict(factors: dict[str, Any]) -> str:
    """Pure rule. risk only when all three factors are known and unfavourable;
    reinforce only when all three are known and favourable."""
    exposed = factors.get("teammate_exposed_1v2")
    if exposed is None:
        return "abstain"
    vals = [factors.get(k) for k in ("low_leverage_ball", "teammate_exposed_1v2", "costly_recovery")]
    if all(v is True for v in vals):
        return "risk_hypothesis"
    if all(v is False for v in vals):
        return "reinforce"
    return "tradeoff"


# ---------- last-man defence ----------

def assess_last_man(r: Reading, case_id: str) -> Finding:
    if r.focus is None or r.ball is None:
        return _abstain(case_id, r, "last_man_defense", "Focus or ball state unknown at t0.")
    f, b = r.focus, r.ball
    attacker = min(r.opponents, key=lambda o: math.hypot(o.x - b["x"], o.y - b["y"]), default=None)
    st = [Statement("fact", f"Defender is {math.hypot(f.x, f.y + GOAL_Y):.0f} uu from own goal centre with "
                            + ("unknown boost" if f.boost is None else f"{f.boost:.0f} boost") + ".", ["focus"])]
    alts: list[Alternative] = []
    if attacker is not None:
        a_d = math.hypot(attacker.x - b["x"], attacker.y - b["y"])
        st.append(Statement("fact", f"Nearest attacker is {a_d:.0f} uu from the ball at {attacker.speed:.0f} uu/s"
                                    + ("" if attacker.boost is None else f" with {attacker.boost:.0f} boost") + ".", [attacker.pid]))
        f_t, a_t = kin_time(r, f.pid), kin_time(r, attacker.pid)
        st.append(Statement("derived", f"Earliest feasible touch: defender {_fmt_t(f_t)}, attacker {_fmt_t(a_t)}.",
                            ["focus", attacker.pid], ["Kinematic lower bounds from t0 (reachability model)."]))
        first = None if f_t is None or a_t is None else f_t < a_t
        alts.append(Alternative("challenge early", "plausible" if first else "unclear",
                                "Defender can arrive first." if first else
                                ("Attacker can arrive first; an early challenge risks being beaten." if first is False
                                 else "Arrival order unknown at t0.")))
        if attacker.boost is not None and attacker.boost < 15:
            st.append(Statement("interpretation", "The attacker is low on boost, which limits aerial and power options, "
                                                  "but not a grounded shot or a dribble.", [attacker.pid], confidence="medium"))
    alts.append(Alternative("shadow toward the goal", "plausible" if f.y < b["y"] else "unclear",
                            "Defender is goal-side of the ball." if f.y < b["y"] else "Defender is not goal-side."))
    if r.mate is not None:
        st.append(Statement("derived", f"Teammate could reach the own goal area in {_fmt_t(kin_time(r, r.mate.pid, (0.0, -GOAL_Y + 500)))}.",
                            ["mate"], ["Kinematic lower bound from t0; unknown if the teammate is airborne or on a wall."]))
    return Finding(case_id, r.t0, "last_man_defense", "Last-defender situation brief", "situation_brief", st, alts,
                   list(r.unknowns), ["What the defender chose (no choice label for this situation yet).",
                                      "Shot outcome probabilities."])


def _abstain(case_id: str, r: Reading, situation: str, why: str) -> Finding:
    return Finding(case_id, r.t0, situation, why, "abstain", [], [], list(r.unknowns) or [why], [])


# ---------- missed opportunities beyond native events ----------

def _shot_followed(frames: list[dict], t0: float, team: str, window: float = 1.5) -> str | None:
    """Retrospective label: did the ball head at the goal mouth fast (>1800 uu/s) within ``window`` s?

    Crude: a slow shot, a pass or a shot just after the window all read as "no_shot". None if unknown.
    """
    seen = False
    for fr in frames:
        t = fr.get("t", 0.0)
        if t <= t0 or t > t0 + window:
            continue
        ball = fr.get("ball") or {}
        v = ball.get("velocity")
        if not v:
            continue
        seen = True
        x, y = _rot(team, ball.get("x", 0.0), ball.get("y", 0.0))
        vx, vy = _rot(team, v[0], v[1])
        if vy > 1800:
            x_at_goal = x + vx * (GOAL_Y - y) / vy
            if abs(x_at_goal) < POST_X + 300:
                return "shot"
    return "no_shot" if seen else None


def find_shot_opportunities(payload: dict[str, Any], focus_id: str, step_s: float = 0.2,
                            gap_s: float = 3.0) -> list[Finding]:
    """Moments the focus player had the ball in the attacking half with an open lane.

    The scan decides each candidate from its own t0 state. Whether a shot followed
    is attached afterwards as a retrospective label and never changes the reading.
    """
    frames = payload.get("frames", [])
    team = {p["id"]: p.get("team") for p in payload.get("players", [])}.get(focus_id)
    if not frames or team not in ("blue", "orange"):
        return []
    out: list[Finding] = []
    last = -1e9
    next_t = frames[0].get("t", 0.0)
    for fr in frames:
        t = fr.get("t", 0.0)
        if t < next_t:
            continue
        next_t = t + step_s
        if t - last < gap_s:
            continue
        r = read_state(payload, t, focus_id)
        if r.ball is None or r.ball["y"] < 1000 or not has_possession(r) or any("Opponent" in u for u in r.unknowns):
            continue
        lane = shot_lane(r)
        slacks = [d["slack_s"] for d in lane["defenders"]]
        if lane["open_fraction"] < 0.45 or None in slacks or min(slacks, default=1.0) <= 0.15:
            continue
        last = t
        out.append(assess_shot(r, f"shot-{focus_id}-{t:.1f}", _shot_followed(frames, t, team)))
    return out


# ---------- ranking ----------

BASE_IMPACT = {"risk_hypothesis": 0.85, "missed_opportunity_hypothesis": 0.75, "reinforce": 0.6,
               "tradeoff": 0.5, "situation_brief": 0.35, "abstain": 0.1}


def rank(findings: list[Finding], focus_id: str | None = None) -> list[Finding]:
    """Order findings for review. A transparent ordering heuristic, not a probability.

    impact: by verdict type; confidence: falls with each unknown input;
    relevance: findings about the selected player first.
    """
    for f in findings:
        impact = BASE_IMPACT.get(f.verdict, 0.1)
        confidence = max(0.2, 0.9 - 0.15 * len(f.unknowns))
        relevance = 1.0 if (focus_id is None or focus_id in f.case_id) else 0.5
        f.ranking = {"impact": impact, "confidence": round(confidence, 2), "relevance": relevance,
                     "score": round(impact * confidence * relevance, 3),
                     "note": "Ordering heuristic for review, not a probability or a measured effect size."}
    return sorted(findings, key=lambda f: -f.ranking["score"])


def analyze_case(case: DecisionCase, payload: dict[str, Any]) -> Finding:
    r = read_state(payload, case.t0, case.focus_player_id)
    if case.situation_type == "first_man_challenge":
        return assess_challenge(r, case.case_id)
    if case.situation_type == "last_man_defense":
        return assess_last_man(r, case.case_id)
    return _abstain(case.case_id, r, case.situation_type, "No tactical reading is implemented for this situation yet.")


def review_replay(payload: dict[str, Any], cases: list[DecisionCase], focus_id: str) -> list[Finding]:
    """Ranked review for one player: analysed decision cases plus open-lane opportunities."""
    findings = [analyze_case(c, payload) for c in cases if c.focus_player_id == focus_id]
    findings += find_shot_opportunities(payload, focus_id)
    return rank(findings, focus_id)
