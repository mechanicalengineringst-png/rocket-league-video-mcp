"""Coaching decision evaluation engine: Approach A (Enhanced Deterministic) & Approach B (Structured LLM).

This module implements two complementary coaching paradigms operating on DecisionCase instances:
- Approach A: High-level deterministic tactical domain logic with strict false-positive suppression
  (e.g., distinguishing valid kickoff cheats from double-commits; recognizing advantageous 50/50 spills).
- Approach B: Evidence-guarded structured prompting for LLMs that quarantines post-decision outcomes
  to prevent hindsight leakage, with an offline mock adapter for deterministic evaluation.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from .decision_cases import DecisionCase
from .evidence import require_decision_evidence


def evaluate_decision_case_heuristics(case: DecisionCase) -> dict[str, Any] | None:
    """Approach A: Enhanced deterministic tactical evaluation.

    Returns a structured coaching finding or None if the play is sound / within normal variance.
    Strictly verifies that any finding cites valid pre-decision evidence keys.
    """
    ctx = case.tactical_context

    if case.situation_type == "kickoff_support":
        behavior = ctx.get("support_behavior")
        spawn = ctx.get("spawn_position")
        if behavior == "cheat":
            # Valid tactical play in 2v2 GC+: Cheating up follows the kicker to win dead balls.
            # Must NEVER be flagged as double-commit or spacing error.
            case.validate_admissibility(["kickoff_spawn", "kickoff_role", "kickoff_support_chosen"])
            return {
                "case_id": case.case_id,
                "t": case.t0,
                "type": "positive_recognition",
                "title": "Tactically sound kickoff cheat",
                "assessment": "sound",
                "evidence": f"{case.focus_player_name} cheated up on kickoff from {spawn}. In competitive 2v2, cheating up secures secondary possession on killed or soft kickoffs.",
                "advice": "Continue cheating up when coordinating with teammate. Maintain enough distance to react if the kickoff pinches high toward your net.",
                "cited_evidence": ["kickoff_spawn", "kickoff_role", "kickoff_support_chosen"],
            }
        elif behavior == "corner_boost":
            case.validate_admissibility(["kickoff_spawn", "kickoff_role", "kickoff_support_chosen"])
            return {
                "case_id": case.case_id,
                "t": case.t0,
                "type": "tactical_tradeoff",
                "title": "Corner boost kickoff route",
                "assessment": "tradeoff",
                "evidence": f"{case.focus_player_name} chose corner boost route on kickoff.",
                "advice": "Taking corner boost grants 100 boost but leaves net vulnerable if teammate loses kickoff cleanly. Ensure kickoff partner delays the 50/50.",
                "cited_evidence": ["kickoff_spawn", "kickoff_role", "kickoff_support_chosen"],
            }

    elif case.situation_type == "first_man_challenge":
        has_backup = ctx.get("has_backup", False)
        mate_covering = ctx.get("mate_is_covering", False)
        mate_dist = ctx.get("mate_distance")

        # Check pre-decision evidence
        required_keys = ["challenge_approach"]
        if "challenge_boost" in [e.key for e in case.pre_decision_evidence()]:
            required_keys.append("challenge_boost")
        if "second_man_coverage" in [e.key for e in case.pre_decision_evidence()]:
            required_keys.append("second_man_coverage")

        case.validate_admissibility(required_keys)

        if not mate_covering or (mate_dist is not None and mate_dist > 4500):
            return {
                "case_id": case.case_id,
                "t": case.t0,
                "type": "tactical_risk",
                "title": "Unsupported first-man challenge",
                "assessment": "high_risk",
                "evidence": f"{case.focus_player_name} committed to a challenge while teammate was {'ahead of play' if not mate_covering else f'{mate_dist:.0f} units away'}.",
                "advice": "As first man without defensive coverage, fake challenge or shadow to buy time for your teammate to recover rather than diving.",
                "cited_evidence": required_keys,
            }
        else:
            # Teammate was covering: this challenge is structurally sound
            return {
                "case_id": case.case_id,
                "t": case.t0,
                "type": "positive_recognition",
                "title": "Supported first-man challenge",
                "assessment": "sound",
                "evidence": f"{case.focus_player_name} challenged with teammate positioned defensively ({mate_dist:.0f} units behind).",
                "advice": "Good challenge timing: even if the 50/50 is lost or neutral, your teammate is in position to clean up.",
                "cited_evidence": required_keys,
            }

    elif case.situation_type == "last_man_defense":
        is_low_boost = ctx.get("is_low_boost", False)
        boost = ctx.get("boost", 0.0)
        dist_to_goal = ctx.get("dist_to_goal", 0.0)

        case.validate_admissibility(["last_man_role", "last_man_boost", "ball_threat"])

        if is_low_boost:
            return {
                "case_id": case.case_id,
                "t": case.t0,
                "type": "contextual_advice",
                "title": "Low-boost net defense",
                "assessment": "forced_situation",
                "evidence": f"{case.focus_player_name} is defending goal with only {boost:.1f} boost.",
                "advice": "Do not dive forward into an early challenge with low boost. Hold back post, pick up small pads across the goal line, and force the shooter to make the first move.",
                "cited_evidence": ["last_man_role", "last_man_boost", "ball_threat"],
            }
        else:
            return {
                "case_id": case.case_id,
                "t": case.t0,
                "type": "tactical_positioning",
                "title": "Last-man goal defense posture",
                "assessment": "sound",
                "evidence": f"{case.focus_player_name} is positioned {dist_to_goal:.0f} units from goal line with {boost:.1f} boost.",
                "advice": "Maintain back-post alignment to cover the entirety of the net while reading whether opponent has an unassisted shot.",
                "cited_evidence": ["last_man_role", "last_man_boost", "ball_threat"],
            }

    return None


def build_decision_case_llm_prompt(case: DecisionCase, include_quarantined_outcomes: bool = False) -> str:
    """Approach B: Formats DecisionCase into an evidence-guarded LLM prompt.

    Quarantines post-decision outcomes to prevent hindsight leakage.
    """
    payload = case.to_llm_payload(include_quarantined_outcomes=include_quarantined_outcomes)

    lines = [
        "You are an expert Rocket League tactical coach reviewing a single decision moment.",
        f"DECISION TIMESTAMP: {payload['decision_time_s']}s",
        f"FOCUS PLAYER: {payload['focus_player']['name']} (Team: {payload['focus_player']['team']})",
        f"SITUATION TYPE: {payload['situation_type']}",
        "",
        "=== SECTION 1: VERIFIED PRE-DECISION FACTS (Known at or before decision time) ===",
    ]
    for fact in payload["pre_decision_facts"]:
        lines.append(f"- [{fact['key']}] (t={fact['event_time_s']}s): {fact['fact']}")

    lines.extend([
        "",
        "=== SECTION 2: TACTICAL CONTEXT ===",
        json.dumps(payload["tactical_context"], indent=2),
        "",
        "=== SECTION 3: FEASIBLE ALTERNATIVES CONSIDERED ===",
    ])
    for alt in payload["feasible_alternatives"]:
        lines.append(f"- {alt}")

    lines.extend([
        "",
        "=== SECTION 4: EPISTEMIC UNCERTAINTIES (Cannot be established from telemetry) ===",
    ])
    for unc in payload["epistemic_uncertainties"]:
        lines.append(f"- {unc}")

    if "quarantined_post_decision_outcomes" in payload:
        lines.extend([
            "",
            "=== SECTION 5: [QUARANTINED POST-DECISION OUTCOME - DO NOT CONFOUND WITH DECISION QUALITY] ===",
            "WARNING: The following occurred AFTER the decision was committed. You MUST NOT use whether a goal",
            "or favorable outcome occurred to judge whether the decision was sound at t0.",
        ])
        for out in payload["quarantined_post_decision_outcomes"]:
            lines.append(f"- [{out['key']}] (finalized t={out['finalized_time_s']}s): {out['outcome']}")

    lines.extend([
        "",
        "INSTRUCTIONS:",
        "1. Evaluate ONLY whether the decision was tactically reasonable given facts in Section 1 & 2.",
        "2. Do NOT criticize a decision solely because an unfavorable outcome followed.",
        "3. Explicitly acknowledge the uncertainties in Section 4.",
        "4. Return JSON: {\"assessment\": \"sound\"|\"high_risk\"|\"tradeoff\", \"title\": \"...\", \"advice\": \"...\", \"cited_evidence\": [\"...\"]}",
    ])

    return "\n".join(lines)


def evaluate_decision_case_llm_mock(
    case: DecisionCase,
    custom_model_fn: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Offline test adapter for Approach B.

    Evaluates prompt generation and validates that the model output adheres to evidence admissibility.
    """
    prompt = build_decision_case_llm_prompt(case, include_quarantined_outcomes=True)

    if custom_model_fn is not None:
        raw_output = custom_model_fn(prompt)
    else:
        # High-fidelity mock model adhering strictly to prompt instructions
        heuristic = evaluate_decision_case_heuristics(case)
        if heuristic:
            raw_output = {
                "assessment": heuristic.get("assessment", "sound"),
                "title": heuristic.get("title", "Tactical Review"),
                "advice": heuristic.get("advice", ""),
                "cited_evidence": heuristic.get("cited_evidence", []),
            }
        else:
            raw_output = {
                "assessment": "sound",
                "title": "Tactical Play",
                "advice": "Decision was within normal competitive parameters.",
                "cited_evidence": [e.key for e in case.pre_decision_evidence()[:1]],
            }

    # Verify that returned cited_evidence keys are admissible
    cited = raw_output.get("cited_evidence", [])
    admissible = case.validate_admissibility(cited)

    return {
        "case_id": case.case_id,
        "t": case.t0,
        "mode": "llm_structured_evaluation",
        "prompt_char_count": len(prompt),
        "prompt_token_estimate": len(prompt) // 4,
        "model_assessment": raw_output.get("assessment"),
        "title": raw_output.get("title"),
        "advice": raw_output.get("advice"),
        "verified_evidence_citations": [e.key for e in admissible],
    }
