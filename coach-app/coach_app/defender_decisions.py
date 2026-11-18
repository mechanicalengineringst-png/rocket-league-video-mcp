"""First-defender decisions: challenge, shadow or something else (Round 5, checkpoint 3).

The moment comes from ``choices.find_defender_candidates`` (eligible from t0
only). The reading has three layers that are never mixed:

- **feasible** (t0): who can touch first, by how much, and whether the teammate
  can get goal-side in time, all from the reachability model;
- **chosen** (retrospective ``observed_action``): what the defender did next;
- **happened**: not used here at all.

The verdict is a *hypothesis about fit* between the t0 situation and the
choice, under one stated principle (a defender who can't contest in time and
has no cover should delay). It is not a claim that one playstyle is correct:
the principle and both thresholds are listed so expert ratings can replace them.
"""
from __future__ import annotations

import math
from typing import Any

from .choices import ChoiceLabel
from .strategic_state import StrategicState
from .tactical_analysis import Alternative, Finding, Statement

CONTEST_WINDOW_S = 0.3     # defender's earliest touch at most this long after the carrier's: a real 50/50
COVER_WINDOW_S = 1.0       # teammate goal-side within this long after the carrier's touch
PRINCIPLE = ("Cover-first principle: a defender who cannot contest in time and has no teammate covering "
             "should delay rather than dive in. Other successful styles weigh pressure more; this is a hypothesis "
             "to be calibrated by expert ratings, not a rule.")


def _fmt(t: float | None) -> str:
    return "unknown" if t is None else ("more than 4 s" if math.isinf(t) else f"{t:.2f} s")


def defender_factors(st: StrategicState) -> dict[str, Any]:
    r = st.reach
    opp = [p for p, tm in st.team_of.items() if tm not in (None, st.team)]
    carrier = min((r[p]["t_min"] for p in opp if r[p]["status"] == "ok"), default=None)
    focus_t = r[st.focus]["t_min"] if r[st.focus]["status"] == "ok" else None
    contest = None if carrier is None or focus_t is None else focus_t <= carrier + CONTEST_WINDOW_S
    cover = None if st.cover_s is None or carrier is None else st.cover_s <= carrier + COVER_WINDOW_S
    return {"contest_in_time": contest, "teammate_can_cover": cover,
            "_carrier_t": carrier, "_focus_t": focus_t, "_cover_t": st.cover_s}


VERDICT_TABLE = {
    # (choice family, contest_in_time, teammate_can_cover) -> verdict
    ("challenge", True, True): "reinforce",
    ("challenge", True, False): "tradeoff",
    ("challenge", False, True): "tradeoff",
    ("challenge", False, False): "risk_hypothesis",
    ("delay", False, False): "reinforce",
    ("delay", False, True): "reinforce",
    ("delay", True, False): "reinforce",
    ("delay", True, True): "tradeoff",
}
HEADLINES = {
    ("challenge", "reinforce"): "Challenge in time with a teammate covering",
    ("challenge", "tradeoff"): "Challenge with part of the support missing",
    ("challenge", "risk_hypothesis"): "Late challenge with no cover behind",
    ("delay", "reinforce"): "Held back when a challenge would have been late or uncovered",
    ("delay", "tradeoff"): "Held back although a covered 50/50 was available",
}


def defender_verdict(factors: dict[str, Any], choice: str | None) -> str:
    fam = {"challenge": "challenge", "shadow": "delay", "retreat": "delay"}.get(choice or "")
    if fam is None:
        return "situation_brief"
    c, v = factors.get("contest_in_time"), factors.get("teammate_can_cover")
    if c is None or v is None:
        return "abstain"
    return VERDICT_TABLE[(fam, c, v)]


def assess_defender(st: StrategicState, choice: ChoiceLabel | None, case_id: str, names: dict[str, str] | None = None) -> Finding:
    names = names or {}
    fx = defender_factors(st)
    choice_name = choice.choice if choice else None
    statements = [
        Statement("derived", f"Earliest feasible touch at t0: the ball carrier {_fmt(fx['_carrier_t'])}, "
                             f"this defender {_fmt(fx['_focus_t'])}.", ["opponents", "focus"],
                  ["Kinematic lower bounds (reachability model); real players are often slower."]),
        Statement("derived", f"The teammate could be goal-side in {_fmt(fx['_cover_t'])}.", ["mate"],
                  ["Goal-side point: a third of the way from the ball to the own goal."]),
    ]
    if st.margin_s is not None:
        lo, hi = st.margin_interval
        statements.append(Statement("derived", f"Team race margin {st.margin_s:+.2f} s (positive = this team first); "
                                               f"range {_fmt(lo)} to {_fmt(hi)} under pessimistic/optimistic bounds.",
                                    ["all cars"]))
    if fx["contest_in_time"] is not None:
        statements.append(Statement(
            "interpretation",
            "The defender could contest about as the carrier touches." if fx["contest_in_time"]
            else "The defender would arrive after the carrier's touch: a challenge would be late.",
            ["focus", "opponents"], [f"'In time' = within {CONTEST_WINDOW_S} s of the carrier's earliest touch.", PRINCIPLE], "medium"))
    if fx["teammate_can_cover"] is not None:
        statements.append(Statement(
            "interpretation",
            "A beaten challenge would likely leave the teammate goal-side in time." if fx["teammate_can_cover"]
            else "If this defender is beaten, the teammate is unlikely to be goal-side in time.",
            ["mate"], [f"'In time' = within {COVER_WINDOW_S} s of the carrier's earliest touch."], "medium"))
    verdict = defender_verdict(fx, choice_name)
    fam = {"challenge": "challenge", "shadow": "delay", "retreat": "delay"}.get(choice_name or "")
    headline = HEADLINES.get((fam, verdict)) if fam else None
    if verdict == "abstain":
        headline = "Arrival times or cover unknown at t0: not judged"
    elif headline is None:
        headline = "First-defender moment (no clear challenge or shadow)"
    alts = [
        Alternative("challenge now", "plausible" if fx["contest_in_time"] else ("unclear" if fx["contest_in_time"] is None else "implausible"),
                    "Feasible contest by arrival times." if fx["contest_in_time"] else "Arrival order or timing does not support a contest."),
        Alternative("shadow (stay goal-side, match the carrier)", "plausible", "Defender is goal-side at t0 (eligibility rule)."),
        Alternative("retreat toward the net or a big boost", "plausible" if fx["teammate_can_cover"] is not None else "unclear",
                    "Always physically available; costs pressure on the carrier."),
    ]
    return Finding(case_id, st.t0, "defender_decision", headline, verdict, statements, alts, list(st.unknowns),
                   ["Whether the challenge would be won.", "What the carrier intended.", "Team communication."],
                   choice_name,
                   factors={k: v for k, v in fx.items() if not k.startswith("_")})
