"""Coaching decision evaluation engine: Approach A (Enhanced Deterministic) & Approach B (Structured LLM).

This module implements two complementary coaching paradigms operating on DecisionCase instances:
- Approach A: Conservative deterministic tactical domain logic with strict false-positive suppression
  and tactical honesty (treating relative depth as depth rather than verified coverage; framing choices
  as hypotheses with tradeoffs rather than dogmatic verdicts).
- Approach B: Evidence-guarded structured prompting for LLMs that completely withholds post-decision
  outcomes from the decision evaluation prompt, with an offline mock adapter for deterministic evaluation.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from .decision_cases import DecisionCase
from .evidence import require_decision_evidence


def evaluate_decision_case_heuristics(case: DecisionCase) -> dict[str, Any] | None:
    """Approach A: Conservative deterministic tactical evaluation.

    Returns a structured tactical hypothesis/finding or an abstention when telemetry is ambiguous.
    Strictly verifies that any finding cites valid pre-decision evidence keys.
    """
    ctx = case.tactical_context

    if case.situation_type == "kickoff_support":
        motion = ctx.get("observed_motion_at_t0", "")
        spawn = ctx.get("spawn_position", "unknown")
        boost = ctx.get("start_boost", 33.0)

        # Pre-decision admissible keys
        pre_keys = ["kickoff_spawn", "kickoff_role", "kickoff_approach_motion"]
        case.validate_admissibility(pre_keys)

        boost_str = f"{boost:.1f}%" if boost is not None else "unrecorded"

        if motion.lower() in ("unknown", "", "none"):
            return {
                "case_id": case.case_id,
                "t": case.t0,
                "type": "abstain",
                "title": "Kickoff approach unrecorded",
                "assessment": "abstain",
                "evidence": (
                    f"{case.focus_player_name} spawned at {spawn} ({boost_str} boost). "
                    "Car motion at t0 was unrecorded or ambiguous in replay samples."
                ),
                "advice": (
                    "Inspect player kickoff approach and cheat line directly in 3D replay."
                ),
                "cited_evidence": pre_keys,
            }
        elif "midfield" in motion.lower() or "forward" in motion.lower():
            return {
                "case_id": case.case_id,
                "t": case.t0,
                "type": "tradeoff_consideration",
                "title": "Kickoff cheat support hypothesis",
                "assessment": "tactical_hypothesis",
                "evidence": (
                    f"{case.focus_player_name} advanced toward midfield from {spawn} spawn ({boost_str} boost). "
                    "Cheating up gains secondary possession if the kickoff stalls or spills neutral, "
                    "but carries risk of an open net if the kickoff pinches high or is lost cleanly over the car."
                ),
                "advice": (
                    "Inspect whether cheating up matched kicker communication and speed. "
                    "If the kicker frequently loses kickoffs high, consider holding net or taking a wider arc."
                ),
                "cited_evidence": pre_keys,
            }
        else:
            return {
                "case_id": case.case_id,
                "t": case.t0,
                "type": "tradeoff_consideration",
                "title": "Corner boost kickoff route hypothesis",
                "assessment": "tactical_hypothesis",
                "evidence": (
                    f"{case.focus_player_name} directed motion toward perimeter/corner on kickoff. "
                    "Secures 100 boost for an offensive corner sequence, but concedes immediate central ball control."
                ),
                "advice": (
                    "Inspect whether conceding initial central pressure allowed opponents an uncontested first touch."
                ),
                "cited_evidence": pre_keys,
            }

    elif case.situation_type == "first_man_challenge":
        mate_depth = ctx.get("mate_relative_depth", "unknown")
        mate_dist = ctx.get("mate_distance")

        # Admissible pre-decision keys
        required_keys = ["challenge_approach"]
        available_pre = {e.key for e in case.pre_decision_evidence()}
        if "challenge_boost" in available_pre:
            required_keys.append("challenge_boost")
        if "second_man_depth" in available_pre:
            required_keys.append("second_man_depth")

        case.validate_admissibility(required_keys)

        if mate_depth != "behind" or (mate_dist is not None and mate_dist > 4500):
            dist_str = f"{mate_dist:.0f} units away" if mate_dist is not None else "distant"
            return {
                "case_id": case.case_id,
                "t": case.t0,
                "type": "tactical_risk",
                "title": "First-man challenge without defensive depth",
                "assessment": "tactical_risk",
                "evidence": (
                    f"{case.focus_player_name} committed to a challenge while teammate was "
                    f"{'ahead of play' if mate_depth != 'behind' else dist_str}."
                ),
                "advice": (
                    "Challenging without a recovering teammate behind leaves the net vulnerable if beaten. "
                    "Inspect whether fake challenging or shadowing to delay the attack was preferable."
                ),
                "cited_evidence": required_keys,
            }
        else:
            # Teammate has relative depth, but orientation/coverage cannot be proven from depth alone
            dist_str = f"{mate_dist:.0f} units behind" if mate_dist is not None else "behind"
            return {
                "case_id": case.case_id,
                "t": case.t0,
                "type": "depth_observation",
                "title": "First-man challenge with teammate at defensive depth",
                "assessment": "unverified_coverage_hypothesis",
                "evidence": (
                    f"{case.focus_player_name} committed to a challenge with teammate positioned {dist_str}. "
                    "Telemetry confirms relative depth, but car orientation, momentum toward net, and recovery "
                    "readiness cannot be verified from depth coordinates alone."
                ),
                "advice": (
                    "Review teammate's perspective and camera in the 3D replay. "
                    "Verify whether they were turned toward the goal and ready to contest a spilled ball."
                ),
                "cited_evidence": required_keys,
            }

    elif case.situation_type == "last_man_defense":
        is_constrained = ctx.get("is_constrained_boost", False)
        boost = ctx.get("boost_at_t0")
        dist_to_goal = ctx.get("dist_to_goal", 0.0)

        available_pre = {e.key for e in case.pre_decision_evidence()}
        required_keys = ["last_man_role", "ball_threat"]
        if "last_man_boost" in available_pre:
            required_keys.append("last_man_boost")
        case.validate_admissibility(required_keys)

        if is_constrained and boost is not None:
            return {
                "case_id": case.case_id,
                "t": case.t0,
                "type": "contextual_advice",
                "title": "Low-boost net defense posture",
                "assessment": "constrained_situation",
                "evidence": (
                    f"{case.focus_player_name} is defending goal with {boost:.1f} boost. "
                    "Low boost constrains aerial reach and recovery speed."
                ),
                "advice": (
                    "Hold back post, pick up goal-line small pads, and force the shooter to commit. "
                    "Do not dive forward into an early challenge with limited boost."
                ),
                "cited_evidence": required_keys,
            }
        else:
            boost_desc = f"with {boost:.1f} boost" if boost is not None else "(boost level unrecorded)"
            return {
                "case_id": case.case_id,
                "t": case.t0,
                "type": "tactical_positioning",
                "title": "Last-man goal defense posture",
                "assessment": "tactical_hypothesis",
                "evidence": (
                    f"{case.focus_player_name} is positioned {dist_to_goal:.0f} units from goal line {boost_desc}."
                ),
                "advice": (
                    "Inspect whether back-post alignment covered the full net width and allowed reacting "
                    "to both a direct ground shot and an aerial backboard bounce."
                ),
                "cited_evidence": required_keys,
            }

    return None


def build_decision_case_llm_prompt(case: DecisionCase, include_quarantined_outcomes: bool = False) -> str:
    """Approach B: Formats DecisionCase into an evidence-guarded LLM prompt.

    Default strictly withholds post-decision outcomes so that decision-point critique
    cannot be contaminated by hindsight bias.
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
        "=== SECTION 2: PRE-DECISION TACTICAL CONTEXT ===",
        json.dumps(payload["tactical_context"], indent=2),
        "",
        "=== SECTION 3: HYPOTHETICAL ALTERNATIVES TO INSPECT ===",
        "(Note: These are exploratory hypotheses for replay review, not physically proven paths)",
    ])
    for alt in payload["hypothetical_alternatives_to_inspect"]:
        lines.append(f"- {alt}")

    lines.extend([
        "",
        "=== SECTION 4: EPISTEMIC UNCERTAINTIES (Cannot be established from telemetry) ===",
    ])
    for unc in payload["epistemic_uncertainties"]:
        lines.append(f"- {unc}")

    if include_quarantined_outcomes and "quarantined_post_decision_outcomes" in payload:
        lines.extend([
            "",
            "=== SECTION 5: [QUARANTINED POST-DECISION OUTCOME - POST-MATCH CONTEXT ONLY] ===",
            "WARNING: The following occurred AFTER the decision was committed. You MUST NOT use whether a goal",
            "or favorable outcome occurred to judge whether the decision was sound at t0.",
        ])
        for out in payload["quarantined_post_decision_outcomes"]:
            lines.append(f"- [{out['key']}] (finalized t={out['finalized_time_s']}s): {out['outcome']}")

    lines.extend([
        "",
        "INSTRUCTIONS:",
        "1. Evaluate ONLY whether the decision was tactically reasonable given facts in Section 1 & 2.",
        "2. Do NOT treat relative depth as verified coverage: a teammate behind may not be facing the threat.",
        "3. Explicitly acknowledge the epistemic uncertainties in Section 4.",
        "4. If telemetry is insufficient to make a determination, return assessment: 'abstain'.",
        "5. Return JSON: {\"assessment\": \"tactical_hypothesis\"|\"tactical_risk\"|\"tradeoff\"|\"abstain\", "
        "\"title\": \"...\", \"advice\": \"...\", \"cited_evidence\": [\"...\"]}",
    ])

    return "\n".join(lines)


def evaluate_decision_case_llm_mock(
    case: DecisionCase,
    custom_model_fn: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Offline test adapter for Approach B.

    Evaluates prompt generation and validates that the model output adheres to evidence admissibility.
    Pre-decision evaluation strictly withholds post-decision outcomes.
    """
    prompt = build_decision_case_llm_prompt(case, include_quarantined_outcomes=False)

    if custom_model_fn is not None:
        raw_output = custom_model_fn(prompt)
    else:
        # High-fidelity mock model adhering strictly to prompt instructions
        heuristic = None
        try:
            heuristic = evaluate_decision_case_heuristics(case)
        except ValueError:
            heuristic = None

        if heuristic:
            raw_output = {
                "assessment": heuristic.get("assessment", "tactical_hypothesis"),
                "title": heuristic.get("title", "Tactical Review"),
                "advice": heuristic.get("advice", ""),
                "cited_evidence": heuristic.get("cited_evidence", []),
            }
        else:
            pre_keys = [e.key for e in case.pre_decision_evidence()]
            raw_output = {
                "assessment": "abstain",
                "title": "Tactical Play Under Observation",
                "advice": "Telemetry does not provide conclusive grounds for critique.",
                "cited_evidence": pre_keys[:1] if pre_keys else [],
            }

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
