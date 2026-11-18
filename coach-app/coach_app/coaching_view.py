"""One coaching interpretation per moment (Round 5, checkpoint 3, Part F).

Two systems can judge the same moment: the Round 1-4 rule verdict
(``decision_evaluation``, kept as baseline ``rule_v1``) and the t0 tactical
reading (``tactical_analysis`` / ``defender_decisions``). Showing both as
authoritative would contradict itself, so this module produces a single
display and keeps the other as a labelled baseline.

Policy (simple on purpose, so it can be audited and replaced by ratings):

1. Each verdict maps to a stance: support, neutral, concern, describe or abstain.
2. The tactical reading is primary: its inputs are verified at t0 and it
   abstains on unknowns. The rule verdict is shown only as a baseline.
3. If the primary abstains or only describes, nothing is judged. A non-committal
   rule label ("tradeoff", "unverified hypothesis") is no opinion, not a vote.
4. If the two stances are opposite (support vs concern), the moment is
   ``disputed``: no verdict is shown, both sets of reasons are, and it is
   flagged for expert rating.
5. If they differ by one step, the more cautious stance (neutral) is shown.
6. Agreement is reported but never raises confidence above "hypothesis".

The display always separates what was feasible (t0), what the player chose
(retrospective) and what happened (outcome, never used to judge).
"""
from __future__ import annotations

from typing import Any

from .tactical_analysis import Finding

# Only explicit judgements count as a second opinion. After Round 4 the rule verdict
# returns a non-committal label for almost every case (on 15 real replays: 406 of 406
# challenges), and treating that as a "neutral vote" would silently erase every
# reading. Non-committal labels are therefore "no_opinion", not "neutral".
RULE_STANCE = {
    "tactical_risk": "concern", "sound_positioning": "support",
    "tradeoff": "no_opinion", "unverified_coverage_hypothesis": "no_opinion",
    "tactical_hypothesis": "no_opinion", "constrained_situation": "no_opinion",
    "abstain": "abstain",
}
READING_STANCE = {
    "risk_hypothesis": "concern", "missed_opportunity_hypothesis": "concern", "tradeoff": "neutral",
    "reinforce": "support", "situation_brief": "describe", "abstain": "abstain",
}
ORDER = {"concern": -1, "neutral": 0, "support": 1}
POLICY_VERSION = "reconcile/0.1"


def reconcile(finding: Finding, rule_eval: dict[str, Any] | None, *, outcome_note: str | None = None) -> dict[str, Any]:
    primary = READING_STANCE.get(finding.verdict, "abstain")
    baseline = RULE_STANCE.get((rule_eval or {}).get("assessment", "abstain"), "abstain")
    if primary in ("abstain", "describe"):
        status, shown = ("abstain" if primary == "abstain" else "describe"), primary
    elif baseline in ("abstain", "describe", "no_opinion"):
        status, shown = "single_method", primary
    elif primary == baseline:
        status, shown = "agree", primary
    elif {primary, baseline} == {"support", "concern"}:
        status, shown = "disputed", "disputed"
    else:
        status, shown = "partial", "neutral"
    headline = {
        "abstain": "Not judged: key inputs are unknown at t0",
        "describe": finding.headline,
        "disputed": "Methods disagree on this moment: no verdict shown",
    }.get(shown, finding.headline if shown == primary else "A tradeoff to review")
    layers = {
        "feasible_at_t0": [s.text for s in finding.statements if s.kind in ("fact", "derived")],
        "interpretation": [s.text for s in finding.statements if s.kind == "interpretation"],
        "alternatives": [{"action": a.action, "feasibility": a.feasibility} for a in finding.alternatives],
        "chosen": None if not finding.reviewed_action else {
            "label": finding.reviewed_action, "kind": "observed_action",
            "note": "Retrospective: what the player did next. Not known at t0, not intent."},
        "happened": None if not outcome_note else {
            "note": outcome_note, "used_in_judgement": False},
    }
    return {
        "policy": POLICY_VERSION,
        "display": {"stance": shown, "headline": headline,
                    "confidence": "hypothesis" if shown in ("support", "neutral", "concern") else None},
        "agreement": status,
        "needs_expert_rating": status in ("disputed", "partial"),
        "primary": {"system": finding.version, "verdict": finding.verdict, "stance": primary,
                    "factors": finding.factors},
        "baselines": {"rule_v1": {"assessment": (rule_eval or {}).get("assessment"), "stance": baseline,
                                  "title": (rule_eval or {}).get("title"),
                                  "shown_to_player": False}},
        "layers": layers,
        "unknowns": list(finding.unknowns),
        "not_established": list(finding.not_established),
    }
