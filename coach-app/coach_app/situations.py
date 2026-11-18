"""Decision-situation discovery for 2v2 beyond first-defender moments (Round 12).

Every class is decided from the t0 frame alone (plus earlier candidates for debouncing), so a
candidate cannot depend on what happened next. Classes describe *what decision the focus player
faced*, not whether they handled it well:

- ``first_defender``        goal-side, an opponent about to play the ball, the focus player can contest
- ``possession``            the focus player has the ball under control (Round 4 heuristic: close, moving
                            with it, low ball)
- ``offensive_first_man``   the focus player is their team's first to a ball in the opponent half, no control yet
- ``second_man_support``    the teammate is clearly first to the ball and about to play it
- ``loose_ball``            nobody can touch within 1.2 s and the ball is travelling: a transition read
- ``recovery_and_boost``    the focus player is far from the play, so the route back (direct, small
                            pads, big boost) is the decision
- ``aerial_or_wall``        the ball is high near the focus player, or the focus player is on a wall:
                            recorded for completeness, but mechanics are NOT modelled (observation only)

Salience for ranking is computed later from t0 features only (``moment_ranking``).
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field
from typing import Any

from .decision_state_v1 import margin_override, order
from .reachability import car_state, estimate_reach

RULE_VERSION = "situations/0.1"
SCAN_STEP_S = 0.25
CLASS_DEBOUNCE_S = 4.0
ANY_GAP_S = 1.5
KICKOFF_EXCLUSION_S = 3.0            # kickoff play is its own discipline and is not analysed here
ELIGIBILITY_MARGIN_S = 0.30          # lower end of the Round 11 band: eligibility is inclusive, judgment is not
GOAL_Y = 5120.0
CLASSES = ("first_defender", "possession", "offensive_first_man", "second_man_support", "loose_ball",
           "recovery_and_boost", "aerial_or_wall")
SUPPORTED_FOR_JUDGMENT = {"first_defender", "possession", "offensive_first_man", "second_man_support",
                          "loose_ball", "recovery_and_boost"}


@dataclass
class Situation:
    situation_class: str
    t0: float
    player_id: str
    team: str
    values: dict[str, Any]
    frames_used_through_s: float
    rule: str = RULE_VERSION
    supported_for_judgment: bool = True
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _rel(team: str, x: float, y: float) -> tuple[float, float]:
    return (x, y) if team == "blue" else (-x, -y)


def _iv(r) -> tuple[float, float] | None:
    if r.status == "ok":
        return (r.t_min, r.t_max if r.t_max is not None else r.t_min)
    if r.status == "out_of_horizon":
        return (math.inf, math.inf)
    return None


def _controls(car: dict, ball: dict) -> bool:
    d = math.dist((car["x"], car["y"]), (ball["x"], ball["y"]))
    rel = math.dist(car["velocity"][:2], ball["velocity"][:2])
    return d < 350.0 and rel < 700.0 and ball["z"] < 400.0


def classify_frame(frame: dict, players: list[dict], focus: str, *, reach_cache: dict | None = None) -> Situation | None:
    """The single most specific class for the focus player in this frame, or None."""
    team_of = {p["id"]: p.get("team") for p in players}
    team = team_of.get(focus)
    cars, ball = frame.get("cars", {}), frame.get("ball") or {}
    if team not in ("blue", "orange") or len(cars) < 4 or not ball.get("velocity") or focus not in cars:
        return None
    if ball.get("x") == 0 and ball.get("y") == 0 and not any(ball["velocity"]):
        return None                      # kickoff setup
    fc, _ = car_state(cars[focus])
    if fc is None:
        return None
    mate = next((p for p, t in team_of.items() if t == team and p != focus), None)
    opps = [p for p, t in team_of.items() if t not in (None, team)]
    cache = reach_cache if reach_cache is not None else {}
    for pid in cars:
        if pid not in cache:
            cache[pid] = estimate_reach(cars[pid], ball)
    iv = {pid: _iv(cache[pid]) for pid in cars}
    bx, by = _rel(team, ball["x"], ball["y"])
    fx, fy = _rel(team, fc.x, fc.y)
    base = {"ball_rel_y": round(by), "ball_z": round(ball["z"]), "focus_rel_y": round(fy),
            "focus_boost": cars[focus].get("boost"), "focus_mode": fc.mode,
            "focus_t": None if iv.get(focus) is None else iv[focus][0]}
    t = frame["t"]

    def mk(cls, **vals):
        return Situation(cls, t, focus, team, {**base, **vals}, t, supported_for_judgment=cls in SUPPORTED_FOR_JUDGMENT)

    if fc.mode == "wall" or (ball["z"] > 600 and math.dist((fc.x, fc.y), (ball["x"], ball["y"])) < 2000):
        return mk("aerial_or_wall")
    known_opp = [iv[p] for p in opps if iv.get(p) is not None]
    if len(known_opp) < len(opps) or iv.get(focus) is None or (mate and iv.get(mate) is None):
        return None
    carrier = min(opps, key=lambda p: iv[p][0])
    c_t = iv[carrier][0]
    with margin_override(ELIGIBILITY_MARGIN_S):
        f_vs_c = order(iv[focus], iv[carrier])
        mate_vs_focus = order(iv[mate], iv[focus]) if mate else "unknown"
    if _controls(cars[focus], ball) and fc.mode == "ground":
        return mk("possession", nearest_opponent_t=c_t)
    soonest = min(iv[focus][0], c_t, iv[mate][0] if mate else math.inf)
    if soonest > 1.2 and math.hypot(*ball["velocity"][:2]) > 1000 and abs(by) < 3000:
        return mk("loose_ball", soonest_touch_s=round(soonest, 2))
    if mate and mate_vs_focus == "a_first" and iv[mate][0] <= 1.0:
        mx, my = _rel(team, cars[mate]["x"], cars[mate]["y"])
        return mk("second_man_support", teammate_t=iv[mate][0], focus_behind_teammate=fy < my)
    if (fc.mode == "ground" and c_t <= 0.5 and fy < by - 200 and by <= 1500 and iv[focus][0] <= c_t + 1.0
            and (not mate or iv[focus][0] <= iv[mate][0])):
        return mk("first_defender", carrier_t=c_t)
    if by > 1000 and f_vs_c in ("a_first", "ambiguous") and (not mate or mate_vs_focus != "a_first") and iv[focus][0] <= 1.5:
        return mk("offensive_first_man", carrier_t=c_t, order=f_vs_c)
    if iv[focus][0] >= 2.5 and fc.mode == "ground":
        return mk("recovery_and_boost", teammate_t=iv[mate][0] if mate else None)
    return None


def discover_situations(payload: dict[str, Any], focus: str, *, start: float | None = None,
                        end: float | None = None) -> list[Situation]:
    """Scan the replay; each decision uses the t0 frame and earlier candidates only."""
    frames = payload.get("frames", [])
    if not frames:
        return []
    times = [f["t"] for f in frames]
    t = times[0] + 3.0 if start is None else start
    end = times[-1] if end is None else end
    kick = sorted(e["t"] for e in payload.get("events", []) if e.get("type") == "kickoff" and isinstance(e.get("t"), (int, float)))
    goals = sorted(e["t"] for e in payload.get("events", []) if e.get("type") == "goal_context" and isinstance(e.get("t"), (int, float)))

    def dead_ball(t: float) -> bool:
        """Before the first kickoff, between a goal and the next kickoff, or just after a kickoff (past events only)."""
        k = kick[bisect.bisect_right(kick, t) - 1] if kick and kick[0] <= t else None
        g = goals[bisect.bisect_right(goals, t) - 1] if goals and goals[0] <= t else None
        if kick and k is None:
            return True
        if g is not None and (k is None or g > k):
            return True
        return k is not None and t - k < KICKOFF_EXCLUSION_S

    last_by_class: dict[str, float] = {}
    last_any = -1e9
    out: list[Situation] = []
    while t <= end:
        t = round(t, 3)
        fr = frames[bisect.bisect_right(times, t) - 1]
        if t - fr["t"] <= 0.15 and t - last_any >= ANY_GAP_S and not dead_ball(t):
            s = classify_frame(fr, payload.get("players", []), focus)
            if s is not None and t - last_by_class.get(s.situation_class, -1e9) >= CLASS_DEBOUNCE_S:
                s.t0 = t
                out.append(s)
                last_by_class[s.situation_class] = t
                last_any = t
        t += SCAN_STEP_S
    return out
