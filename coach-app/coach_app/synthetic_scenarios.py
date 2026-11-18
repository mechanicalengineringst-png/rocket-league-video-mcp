"""SYNTHETIC difficult coaching scenarios for Round 12 (labelled synthetic everywhere they are reported).

These are hand-built replays that exercise the real pipeline (``coach_report.coach_moment``) on the
cases the assignment names: the backboard benchmark, a sound decision followed by a conceded goal, a
poor decision that works, several defensible options, off-ball decisions, teammate-cover uncertainty,
incomplete mechanics, excellent aggression and excellent restraint. They test the reasoning scheme and
its separation of decision-time evidence from outcomes. They are NOT real gameplay and NOT evidence of
tactical accuracy. Each scenario has two futures where useful, so tests can check that Stage A does not
change when only the future changes.
"""
from __future__ import annotations

import copy
import math
from typing import Any, Callable

PLAYERS = [{"id": "b1", "name": "focus", "team": "blue"}, {"id": "b2", "name": "mate", "team": "blue"},
           {"id": "o1", "name": "opp1", "team": "orange"}, {"id": "o2", "name": "opp2", "team": "orange"}]
T0 = 11.0
DURATION = 17.0
HZ = 30


def car(x, y, vx=0.0, vy=0.0, fy=None, boost=60.0, z=17.0):
    sp = math.hypot(vx, vy)
    fwd = [vx / sp, vy / sp, 0.0] if sp > 1 else [0.0, 1.0 if fy is None else fy, 0.0]
    return {"x": x, "y": y, "z": z, "velocity": [vx, vy, 0.0], "forward": fwd, "boost": boost,
            "rotation": [0.0, 0.0, 0.0]}


def build(cars: dict, ball: tuple, ball_v=(0.0, 0.0, 0.0), *, future: Callable | None = None,
          events: list | None = None, drop_focus_at_t0: bool = False) -> dict[str, Any]:
    """Cars and ball move at constant velocity up to T0 (so states are consistent); ``future`` rewrites t > T0."""
    frames = []
    for i in range(int(DURATION * HZ) + 1):
        t = round(i / HZ, 4)
        dt = min(t, T0) - T0
        cs = {}
        for pid, c in cars.items():
            cc = copy.deepcopy(c)
            cc["x"] += c["velocity"][0] * dt
            cc["y"] += c["velocity"][1] * dt
            cs[pid] = cc
        b = {"x": ball[0] + ball_v[0] * dt, "y": ball[1] + ball_v[1] * dt, "z": ball[2], "velocity": list(ball_v)}
        fr = {"t": t, "ball": b, "cars": cs}
        if drop_focus_at_t0 and abs(t - T0) < 0.5:
            fr["cars"].pop("b1", None)
        if future and t > T0:
            future(fr, t - T0)
        frames.append(fr)
    ev = [{"type": "kickoff", "t": 0.5}] + list(events or [])
    return {"title": "SYNTHETIC", "synthetic": True, "players": PLAYERS, "frames": frames, "events": ev}


def toward(fr, pid, target, tau, speed, start=None):
    """Move a car from its T0 position toward target at speed (synthetic future motion)."""
    c = fr["cars"][pid]
    sx, sy = start if start else (c["x"], c["y"])
    dx, dy = target[0] - sx, target[1] - sy
    d = math.hypot(dx, dy) or 1.0
    step = min(d, speed * tau)
    c["x"], c["y"] = sx + dx / d * step, sy + dy / d * step
    c["velocity"] = [dx / d * speed, dy / d * speed, 0.0] if step < d else [0.0, 0.0, 0.0]


def _future(*moves, ball_after: tuple | None = None, ball_from: float = 9e9):
    def f(fr, tau):
        for pid, target, speed in moves:
            toward(fr, pid, target, tau, speed, start=_START[pid])
        if ball_after and tau >= ball_from:
            bx, by, bvx, bvy = ball_after
            k = tau - ball_from
            fr["ball"].update(x=bx + bvx * k, y=by + bvy * k, velocity=[bvx, bvy, 0.0])
    return f


_START: dict[str, tuple] = {}


def _scenario(name, desc, cars, ball, ball_v=(0.0, 0.0, 0.0), futures=None, expect=None, **kw):
    return {"name": name, "description": desc, "cars": cars, "ball": ball, "ball_v": ball_v,
            "futures": futures or {}, "expect": expect or {}, "kw": kw, "synthetic": True}


def scenarios() -> list[dict[str, Any]]:
    out = []
    # 1. Backboard benchmark (ground variant): an opponent controls the ball in our corner by the backboard.
    bb_cars = {"b1": car(1200, -4900, fy=1.0, boost=45), "b2": car(-300, 1200, vy=-600, boost=30),
               "o1": car(2650, -4200, vx=-250, vy=-200, boost=40), "o2": car(-1400, -1600, vy=-300, boost=70)}
    out.append(_scenario(
        "backboard_benchmark_ground",
        "An opponent has the ball under control by our backboard corner; the teammate is up-field, their second "
        "player waits at the far post area. Challenge, shadow, or hold?",
        bb_cars, (2700, -4450, 93), (-250, -200, 0),
        futures={"challenge_then_their_goal": dict(moves=[("b1", (2700, -4500), 1400)], touch=("b1", 0.9),
                                                    goal=("orange", 3.2)),
                 "hold_then_save": dict(moves=[("b1", (900, -5000), 300)], touch=("o1", 0.8))},
        expect={"class": "first_defender", "challenge_not_supported": True}))
    # 1b. Backboard benchmark (aerial variant): mechanics not modelled -> observation only.
    out.append(_scenario(
        "backboard_benchmark_aerial",
        "Same corner, but the ball is high on the backboard and the opponent is in the air: aerial/backboard "
        "mechanics are not modelled, so the coach must abstain from judgment.",
        {"b1": car(800, -4800, boost=45), "b2": car(-300, 1200, vy=-600), "o1": car(2000, -4300, z=600, vy=-400),
         "o2": car(-1400, -1600)}, (1600, -4900, 1100), (0, -200, 0),
        expect={"observation_only": True}))
    # 2. Sound restraint followed by a conceded goal / 3. the same state with a challenge that works.
    late = {"b1": car(0, -3700, fy=1.0, boost=12), "b2": car(1500, 1500, vy=-500, boost=40),
            "o1": car(0, -760, vy=-300, boost=50), "o2": car(700, 200, vy=-500, boost=60)}
    out.append(_scenario(
        "restraint_then_conceded",
        "An opponent dribbles at us with support; we are low on boost, the teammate is far up-field. We shadow and "
        "they score anyway. The shadow should not be criticised for the goal.",
        late, (0, -1000, 93), (0, -300, 0),
        futures={"shadow_then_their_goal": dict(moves=[("b1", (0, -4400), 450)], touch=("o1", 0.5), goal=("orange", 3.5)),
                 "shadow_then_save": dict(moves=[("b1", (0, -4400), 450)], touch=("o1", 0.5))},
        expect={"class": "first_defender", "verdict": {"shadow_then_their_goal": "sound", "shadow_then_save": "sound"}}))
    out.append(_scenario(
        "challenge_works_anyway",
        "Same state, but we dive in and it happens to work (we win it and our team scores). The decision-time read "
        "still argued against it; the outcome must not turn that into praise.",
        late, (0, -1000, 93), (0, -300, 0),
        futures={"challenge_then_our_goal": dict(moves=[("b1", (0, -1100), 1600)], touch=("b1", 0.5), goal=("blue", 4.0))},
        expect={"class": "first_defender", "verdict": {"challenge_then_our_goal": ("questionable", "risky")}}))
    # 4. Several defensible: a level contest with cover.
    out.append(_scenario(
        "level_contest_with_cover",
        "We and the nearest opponent reach the ball at about the same time; the teammate is deep. Several choices "
        "should be presented as defensible.",
        {"b1": car(0, -1800, fy=1.0), "b2": car(-400, -4300, fy=1.0), "o1": car(0, -200, fy=-1.0), "o2": car(2500, 3500, fy=-1.0)},
        (0, -1000, 93), expect={"kind_in": ("several_defensible", "hard_to_judge", "leaning_with_uncertainty")}))
    # 5. Excellent aggression: first with cover.
    out.append(_scenario(
        "covered_first_man_aggression",
        "We are clearly first to a loose ball with the teammate deep behind us. Challenging is supported; the "
        "coach should recognise it rather than suggest caution.",
        {"b1": car(0, -1600, vy=400, fy=1.0), "b2": car(-400, -4300, fy=1.0), "o1": car(0, 900, fy=-1.0), "o2": car(2500, 3500, fy=-1.0)},
        (0, -1000, 93),
        futures={"challenge_then_their_goal": dict(moves=[("b1", (0, -1050), 1500)], touch=("b1", 0.4), goal=("orange", 4.5))},
        expect={"supported_includes": "immediate_challenge", "verdict": {"challenge_then_their_goal": "sound"}}))
    # 6. Off-ball second man, low boost, pads nearby.
    out.append(_scenario(
        "second_man_low_boost",
        "The teammate is about to play the ball in midfield; we are behind with little boost. Support close, support "
        "deep, or take a pad on the way back?",
        {"b1": car(-1500, -2600, vy=300, boost=8), "b2": car(0, -300, vy=900, boost=50),
         "o1": car(400, 1600, vy=-500, boost=50), "o2": car(-2000, 3500, boost=80)}, (0, 200, 93), (0, 100, 0),
        futures={"took_pads": dict(moves=[("b1", (-3584, -2484), 1400)], pickups=[("b1", 0.9, "big", 3)])},
        expect={"class": "second_man_support"}))
    # 7. Teammate cover uncertainty: the cover estimate sits at the edge of the band.
    out.append(_scenario(
        "teammate_cover_borderline",
        "The opponent will reach the ball first; whether the teammate can get goal-side in time is borderline. The "
        "coach should name that as the deciding unknown instead of picking a side.",
        {"b1": car(0, -2600, fy=1.0, boost=50), "b2": car(-1800, -900, vy=-900, boost=40),
         "o1": car(0, -300, vy=-200), "o2": car(2500, 2500)}, (0, -900, 93), (0, -200, 0),
        expect={"class": "first_defender", "decisive_or_uncertain": "teammate_covers"}))
    # 8. Incomplete telemetry: the focus car is missing around t0.
    out.append(_scenario(
        "missing_focus_telemetry",
        "The focus car is absent from the frames around the decision (e.g. demolished or not sampled). The coach must "
        "abstain.",
        {"b1": car(0, -1800), "b2": car(-400, -4300), "o1": car(0, -200, fy=-1.0), "o2": car(2500, 3500)}, (0, -1000, 93),
        expect={"abstain": True}, drop_focus_at_t0=True))
    # 9. Recovery with boost choices.
    out.append(_scenario(
        "recovery_route",
        "We are deep in their half after a challenge with little boost; an opponent is coming at our goal and the "
        "teammate is back. Direct, small pads, or the big pad?",
        {"b1": car(-2000, 3200, vy=-600, boost=10), "b2": car(0, -4400, fy=1.0), "o1": car(500, -500, vy=-900),
         "o2": car(2500, 1500, vy=-300)}, (300, -900, 93), (0, -900, 0),
        futures={"big_boost": dict(moves=[("b1", (-3584, 4240), 1400)], pickups=[("b1", 0.8, "big", 4)]),
                 "direct": dict(moves=[("b1", (0, -2500), 1400)])},
        expect={"class": "recovery_and_boost"}))
    # 10. Possession in range with an open lane.
    out.append(_scenario(
        "possession_open_lane",
        "We have the ball under control in their half, in range, with both defenders out of the lane. Shoot, keep it, "
        "or pass?",
        {"b1": car(-200, 2400, vy=900, boost=50), "b2": car(-1500, 0, vy=600), "o1": car(3000, 3000, vx=-300),
         "o2": car(-3200, 4600)}, (-200, 2600, 93), (0, 900, 0),
        futures={"shot": dict(moves=[("b1", (-200, 2900), 1000)], touch=("b1", 0.3), ball_after=(-200, 2950, 0, 3000), ball_from=0.3)},
        expect={"class": "possession"}))
    return out


def materialise(sc: dict, future_name: str | None = None) -> dict:
    fut = sc["futures"].get(future_name) if future_name else None
    _START.clear()
    for pid, c in sc["cars"].items():
        _START[pid] = (c["x"], c["y"])
    events = []
    f = None
    if fut:
        f = _future(*fut.get("moves", []), ball_after=fut.get("ball_after"), ball_from=fut.get("ball_from", 9e9))
        if "touch" in fut:
            events.append({"type": "touch", "t": round(T0 + fut["touch"][1], 3), "playerId": fut["touch"][0]})
        if "goal" in fut:
            team, at = fut["goal"]
            scorer = "b2" if team == "blue" else "o2"
            events.append({"type": "goal_context", "t": round(T0 + at, 3), "playerId": scorer, "scorerId": scorer,
                           "scoringTeam": team})
        for pid, at, ptype, pad in fut.get("pickups", []):
            events.append({"type": "boost_pickups", "t": round(T0 + at, 3), "playerId": pid, "padType": ptype, "padId": pad})
    return build(sc["cars"], sc["ball"], sc["ball_v"], future=f, events=events, **sc["kw"])
