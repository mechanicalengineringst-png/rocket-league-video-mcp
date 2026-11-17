"""Adversarial and tactical regression test suite for Replay Lab coaching backend.

Validates that coaching logic avoids hindsight bias, respects evidence admissibility,
suppresses common false positives (e.g. valid kickoff cheats, supported 50/50 spills),
and correctly detects genuine tactical risks (e.g. unsupported last-man dives).
"""
from __future__ import annotations

import pytest

from coach_app.decision_cases import DecisionCase
from coach_app.decision_evaluation import (
    build_decision_case_llm_prompt,
    evaluate_decision_case_heuristics,
    evaluate_decision_case_llm_mock,
)
from coach_app.evidence import Evidence


def make_evidence(
    key: str,
    claim: str,
    t_event: float = 10.0,
    t_final: float = 10.0,
    kind: str = "decision_context",
    source: str = "replay",
) -> Evidence:
    return Evidence(
        key=key,
        claim=claim,
        event_time_s=t_event,
        finalized_through_s=t_final,
        kind=kind,
        source=source,
        source_quality="high",
    )


# Scenario 1: Valid Kickoff Cheat (GC2 Competitive Standard)
def test_scenario_1_valid_kickoff_cheat_not_flagged_as_double_commit():
    """A player cheating up behind the kicker is standard GC2 meta; must not be flagged as overlap."""
    ev = (
        make_evidence("kickoff_spawn", "Player spawned center with 33 boost", 8.0, 8.0),
        make_evidence("kickoff_role", "Player is second man observing kicker", 8.0, 8.0, source="derived"),
        make_evidence("kickoff_support_chosen", "Player committed to cheat kickoff support", 9.5, 9.5),
        make_evidence("kickoff_outcome", "Kickoff was killed at midfield", 10.5, 10.5, kind="post_decision_outcome"),
    )
    case = DecisionCase(
        case_id="adv-case-1-cheat",
        replay_id="test-replay",
        t0=9.5,
        focus_player_id="player-1",
        focus_player_name="Plormby",
        focus_player_team="blue",
        situation_type="kickoff_support",
        evidence=ev,
        tactical_context={
            "spawn_position": "center",
            "support_behavior": "cheat",
            "start_boost": 33.0,
        },
        feasible_alternatives=("cheat_up_for_dead_ball", "route_to_corner_boost"),
        uncertainties=("Comms between teammates",),
    )

    finding = evaluate_decision_case_heuristics(case)
    assert finding is not None
    assert finding["assessment"] == "sound"
    assert finding["type"] == "positive_recognition"
    assert "cheat" in finding["title"].lower()
    # Ensure evidence cited only pre-decision facts
    assert "kickoff_outcome" not in finding["cited_evidence"]


# Scenario 2: Deliberately Lost 50/50 Spill to Teammate
def test_scenario_2_supported_fifty_fifty_recognized_as_sound():
    """A first-man challenge where teammate is in position to receive the spill is structurally sound."""
    ev = (
        make_evidence("challenge_approach", "Plormby contested 50/50 as first man", 42.0, 42.0, source="derived"),
        make_evidence("challenge_boost", "Plormby had 52 boost", 42.0, 42.0),
        make_evidence("second_man_coverage", "Teammate was 1800 units behind in goal mouth", 42.0, 42.0),
        make_evidence("fifty_fifty_outcome", "50/50 spilled into corner to teammate", 42.5, 42.5, kind="post_decision_outcome"),
    )
    case = DecisionCase(
        case_id="adv-case-2-spill",
        replay_id="test-replay",
        t0=42.0,
        focus_player_id="player-1",
        focus_player_name="Plormby",
        focus_player_team="blue",
        situation_type="first_man_challenge",
        evidence=ev,
        tactical_context={
            "mate_distance": 1800,
            "mate_is_covering": True,
            "has_backup": True,
        },
        feasible_alternatives=("commit_to_50_50_block", "fake_challenge"),
        uncertainties=("Opponent flip direction",),
    )

    finding = evaluate_decision_case_heuristics(case)
    assert finding is not None
    assert finding["assessment"] == "sound"
    assert finding["type"] == "positive_recognition"
    assert "Supported first-man challenge" in finding["title"]


# Scenario 3: Failed Aerial with Sound Initial Risk/Reward (No Hindsight Bias)
def test_scenario_3_failed_aerial_evaluated_without_hindsight_leakage():
    """An aerial attempt that failed later must be judged by the state at launch, not the missed shot."""
    ev = (
        make_evidence("challenge_approach", "Player jumped for contest", 60.0, 60.0, source="derived"),
        make_evidence("challenge_boost", "Player had 85 boost at launch", 60.0, 60.0),
        make_evidence("second_man_coverage", "Teammate was 2000 units back covering net", 60.0, 60.0),
        make_evidence("aerial_whiff", "Player whiffed aerial and opponent scored", 62.5, 62.5, kind="post_decision_outcome"),
    )
    case = DecisionCase(
        case_id="adv-case-3-aerial",
        replay_id="test-replay",
        t0=60.0,
        focus_player_id="player-1",
        focus_player_name="Plormby",
        focus_player_team="blue",
        situation_type="first_man_challenge",
        evidence=ev,
        tactical_context={
            "mate_distance": 2000,
            "mate_is_covering": True,
            "has_backup": True,
        },
        feasible_alternatives=("aerial_challenge", "shadow_defense"),
        uncertainties=("Exact ball read off ceiling",),
    )

    # Heuristic evaluation at t0 should treat the decision as structurally supported
    finding = evaluate_decision_case_heuristics(case)
    assert finding is not None
    assert finding["assessment"] == "sound"
    # Attempting to cite aerial_whiff as pre-decision evidence MUST raise ValueError
    with pytest.raises(ValueError, match="retrospective"):
        case.validate_admissibility(["aerial_whiff"])


# Scenario 4: Unsupported Last-Man Challenge (Legitimate Tactical Mistake)
def test_scenario_4_unsupported_challenge_flagged_as_risk():
    """First/last man diving while teammate is caught forward leaves an open net; must be flagged."""
    ev = (
        make_evidence("challenge_approach", "Player dove into challenge", 75.0, 75.0, source="derived"),
        make_evidence("challenge_boost", "Player had 40 boost", 75.0, 75.0),
        make_evidence("second_man_coverage", "Teammate was ahead of play in opponent corner", 75.0, 75.0),
    )
    case = DecisionCase(
        case_id="adv-case-4-unsupported",
        replay_id="test-replay",
        t0=75.0,
        focus_player_id="player-1",
        focus_player_name="Plormby",
        focus_player_team="blue",
        situation_type="first_man_challenge",
        evidence=ev,
        tactical_context={
            "mate_distance": 6000,
            "mate_is_covering": False,
            "has_backup": False,
        },
        feasible_alternatives=("fake_challenge_and_rotate_out", "shadow_and_delay"),
        uncertainties=("Opponent flick capability",),
    )

    finding = evaluate_decision_case_heuristics(case)
    assert finding is not None
    assert finding["assessment"] == "high_risk"
    assert finding["type"] == "tactical_risk"
    assert "Unsupported" in finding["title"]


# Scenario 5: Close Second-Man Support Tactically Justified
def test_scenario_5_close_second_man_support_prompt_generation():
    """Structured LLM payload preserves pre-decision spacing without pre-judging as a double-commit."""
    ev = (
        make_evidence("support_spacing", "Second man positioned 950 units behind first man pressing backboard", 85.0, 85.0),
        make_evidence("possession_pressure", "Opponent trapped in corner under heavy pressure", 85.0, 85.0),
    )
    case = DecisionCase(
        case_id="adv-case-5-support",
        replay_id="test-replay",
        t0=85.0,
        focus_player_id="player-1",
        focus_player_name="Plormby",
        focus_player_team="blue",
        situation_type="second_man_support",
        evidence=ev,
        tactical_context={
            "spacing_units": 950,
            "is_offensive_third": True,
            "opponent_pressure": "high",
        },
        feasible_alternatives=("maintain_tight_support", "rotate_to_midfield_relief"),
        uncertainties=("Teammate pass trajectory",),
    )

    prompt = build_decision_case_llm_prompt(case)
    assert "SECTION 1: VERIFIED PRE-DECISION FACTS" in prompt
    assert "support_spacing" in prompt
    assert "maintain_tight_support" in prompt


# Scenario 6: Low-Boost Goalkeeper (Forced Position vs Poor Decision)
def test_scenario_6_low_boost_goalkeeper_framed_as_forced_constraint():
    """A low-boost goalkeeper should be advised on pad pathing and patience, not blamed for defending."""
    ev = (
        make_evidence("last_man_role", "Player defending goal line", 110.0, 110.0, source="derived"),
        make_evidence("last_man_boost", "Player has 6 boost", 110.0, 110.0),
        make_evidence("ball_threat", "Ball is 1200 units away on goal approach", 110.0, 110.0),
    )
    case = DecisionCase(
        case_id="adv-case-6-lowboost",
        replay_id="test-replay",
        t0=110.0,
        focus_player_id="player-1",
        focus_player_name="Plormby",
        focus_player_team="blue",
        situation_type="last_man_defense",
        evidence=ev,
        tactical_context={
            "dist_to_goal": 200,
            "ball_dist": 1200,
            "boost": 6.0,
            "is_low_boost": True,
        },
        feasible_alternatives=("shadow_across_goal_mouth", "hold_back_post_position"),
        uncertainties=("Shooter placement accuracy",),
    )

    finding = evaluate_decision_case_heuristics(case)
    assert finding is not None
    assert finding["assessment"] == "forced_situation"
    assert "Low-boost" in finding["title"]
    assert "small pads" in finding["advice"]


# Scenario 7: Positive Recognition for Solid Defensive Positioning
def test_scenario_7_positive_recognition_for_back_post_positioning():
    """Player properly set up at back post with boost receives positive reinforcement."""
    ev = (
        make_evidence("last_man_role", "Player stationed at back post", 140.0, 140.0, source="derived"),
        make_evidence("last_man_boost", "Player has 65 boost", 140.0, 140.0),
        make_evidence("ball_threat", "Ball 2200 units out on opponent corner cross", 140.0, 140.0),
    )
    case = DecisionCase(
        case_id="adv-case-7-backpost",
        replay_id="test-replay",
        t0=140.0,
        focus_player_id="player-1",
        focus_player_name="Plormby",
        focus_player_team="blue",
        situation_type="last_man_defense",
        evidence=ev,
        tactical_context={
            "dist_to_goal": 450,
            "ball_dist": 2200,
            "boost": 65.0,
            "is_low_boost": False,
        },
        feasible_alternatives=("hold_back_post_position", "shadow_across_goal_mouth"),
        uncertainties=("Opponent pass or backboard read",),
    )

    finding = evaluate_decision_case_heuristics(case)
    assert finding is not None
    assert finding["assessment"] == "sound"
    assert "Last-man goal defense posture" in finding["title"]


# Scenario 8: Ambiguous/Missing Telemetry Requires Abstention
def test_scenario_8_missing_telemetry_fails_closed():
    """If required evidence is missing or cannot be cited, coaching evaluation must fail closed."""
    ev = (
        make_evidence("last_man_role", "Player defending goal line", 160.0, 160.0, source="derived"),
        # Missing last_man_boost and ball_threat!
    )
    case = DecisionCase(
        case_id="adv-case-8-missing",
        replay_id="test-replay",
        t0=160.0,
        focus_player_id="player-1",
        focus_player_name="Plormby",
        focus_player_team="blue",
        situation_type="last_man_defense",
        evidence=ev,
        tactical_context={"dist_to_goal": 200, "is_low_boost": False},
        feasible_alternatives=("hold_net",),
        uncertainties=("Missing boost telemetry",),
    )

    # Attempting heuristic evaluation will fail admissibility check for missing evidence
    with pytest.raises(ValueError, match="unknown, retrospective, or future-derived"):
        evaluate_decision_case_heuristics(case)


# Test Offline Mock LLM Adapter
def test_offline_llm_mock_adapter():
    """Verify that evaluate_decision_case_llm_mock executes deterministically and verifies citations."""
    ev = (
        make_evidence("kickoff_spawn", "Spawned center", 5.0, 5.0),
        make_evidence("kickoff_role", "Second man", 5.0, 5.0, source="derived"),
        make_evidence("kickoff_support_chosen", "Cheat support", 6.5, 6.5),
    )
    case = DecisionCase(
        case_id="test-llm-mock",
        replay_id="test-replay",
        t0=6.5,
        focus_player_id="p1",
        focus_player_name="Player 1",
        focus_player_team="blue",
        situation_type="kickoff_support",
        evidence=ev,
        tactical_context={"support_behavior": "cheat", "spawn_position": "center"},
        feasible_alternatives=("cheat_up", "boost"),
        uncertainties=("comms",),
    )

    res = evaluate_decision_case_llm_mock(case)
    assert res["mode"] == "llm_structured_evaluation"
    assert res["model_assessment"] == "sound"
    assert len(res["verified_evidence_citations"]) >= 1
