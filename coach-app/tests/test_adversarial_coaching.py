"""Adversarial and tactical regression test suite for Replay Lab coaching backend.

Validates evidence integrity, hindsight leakage suppression, tactical honesty
(treating relative depth as depth rather than verified coverage; framing choices
as hypotheses with tradeoffs), and failsafe abstentions.
"""
from __future__ import annotations

import pytest

from coach_app.decision_cases import (
    DecisionCase,
    _find_car_at_time,
    _find_ball_at_time,
)
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


# Scenario 1: Valid Kickoff Cheat (Framed as Hypothesis with Tradeoffs, Not Double-Commit)
def test_scenario_1_kickoff_cheat_framed_as_tradeoff_hypothesis():
    """A player advancing on kickoff is framed as a tactical hypothesis with tradeoffs, not an overlap error."""
    ev = (
        make_evidence("kickoff_spawn", "Player spawned center with 33 boost", 8.0, 8.0),
        make_evidence("kickoff_role", "Player is second man observing kicker", 8.0, 8.0, source="derived"),
        make_evidence("kickoff_approach_motion", "Player advancing toward midfield at t0", 9.5, 9.5),
        make_evidence("kickoff_outcome", "Kickoff was killed at midfield", 10.5, 10.5, kind="post_decision_outcome"),
    )
    case = DecisionCase(
        case_id="adv-case-1-cheat",
        replay_id="test-replay",
        t0=9.5,
        focus_player_id="player-1",
        focus_player_name="Player 1",
        focus_player_team="blue",
        situation_type="kickoff_support",
        evidence=ev,
        tactical_context={
            "spawn_position": "center",
            "start_boost": 33.0,
            "observed_motion_at_t0": "advancing toward midfield",
        },
        feasible_alternatives=("cheat_up_for_dead_ball", "route_to_corner_boost"),
        uncertainties=("Comms between teammates",),
    )

    finding = evaluate_decision_case_heuristics(case)
    assert finding is not None
    assert finding["assessment"] == "tactical_hypothesis"
    assert finding["type"] == "tradeoff_consideration"
    assert "cheat" in finding["title"].lower()
    # Admissibility check: cited evidence must strictly be pre-decision
    assert "kickoff_outcome" not in finding["cited_evidence"]
    assert "kickoff_approach_motion" in finding["cited_evidence"]


# Scenario 2: First-Man Challenge (Depth Is Not Equated with Verified Coverage)
def test_scenario_2_first_man_challenge_depth_not_claimed_as_verified_coverage():
    """A teammate positioned behind provides geometric depth, but cannot be claimed as verified coverage."""
    ev = (
        make_evidence("challenge_approach", "Player contested 50/50 as first man", 42.0, 42.0, source="derived"),
        make_evidence("challenge_boost", "Player had 52 boost", 42.0, 42.0),
        make_evidence("second_man_depth", "Teammate was 1800 units away at defensive depth (behind Player 1)", 42.0, 42.0),
        make_evidence("fifty_fifty_outcome", "50/50 spilled into corner", 42.5, 42.5, kind="post_decision_outcome"),
    )
    case = DecisionCase(
        case_id="adv-case-2-spill",
        replay_id="test-replay",
        t0=42.0,
        focus_player_id="player-1",
        focus_player_name="Player 1",
        focus_player_team="blue",
        situation_type="first_man_challenge",
        evidence=ev,
        tactical_context={
            "mate_distance": 1800,
            "mate_relative_depth": "behind",
            "defensive_coverage_verified": False,
        },
        feasible_alternatives=("commit_to_50_50_block", "fake_challenge"),
        uncertainties=("Teammate orientation and momentum toward net cannot be verified from depth alone",),
    )

    finding = evaluate_decision_case_heuristics(case)
    assert finding is not None
    # Must NOT claim dogmatic "sound" or verified coverage
    assert finding["assessment"] == "unverified_coverage_hypothesis"
    assert finding["type"] == "depth_observation"
    assert "depth" in finding["title"].lower()
    assert "orientation" in finding["evidence"] or "orientation" in finding["advice"]


# Scenario 3: Failed Aerial Evaluated Without Hindsight Leakage
def test_scenario_3_failed_aerial_evaluated_without_hindsight_leakage():
    """An aerial attempt that failed later must be judged by state at commitment, not the post-decision whiff."""
    ev = (
        make_evidence("challenge_approach", "Player jumped for contest", 60.0, 60.0, source="derived"),
        make_evidence("challenge_boost", "Player had 85 boost at launch", 60.0, 60.0),
        make_evidence("second_man_depth", "Teammate was 2000 units away at defensive depth (behind Player 1)", 60.0, 60.0),
        make_evidence("aerial_whiff", "Player whiffed aerial and opponent scored", 62.5, 62.5, kind="post_decision_outcome"),
    )
    case = DecisionCase(
        case_id="adv-case-3-aerial",
        replay_id="test-replay",
        t0=60.0,
        focus_player_id="player-1",
        focus_player_name="Player 1",
        focus_player_team="blue",
        situation_type="first_man_challenge",
        evidence=ev,
        tactical_context={
            "mate_distance": 2000,
            "mate_relative_depth": "behind",
            "defensive_coverage_verified": False,
        },
        feasible_alternatives=("aerial_challenge", "shadow_defense"),
        uncertainties=("Exact ball read off ceiling",),
    )

    finding = evaluate_decision_case_heuristics(case)
    assert finding is not None
    # Must evaluate based on pre-decision depth, NOT the subsequent whiff
    assert finding["assessment"] == "unverified_coverage_hypothesis"
    with pytest.raises(ValueError, match="retrospective"):
        case.validate_admissibility(["aerial_whiff"])


# Scenario 4: Unsupported Challenge Flagged as Risk
def test_scenario_4_unsupported_challenge_flagged_as_risk():
    """First man diving while teammate is caught forward leaves open net; correctly flagged as risk."""
    ev = (
        make_evidence("challenge_approach", "Player dove into challenge", 75.0, 75.0, source="derived"),
        make_evidence("challenge_boost", "Player had 40 boost", 75.0, 75.0),
        make_evidence("second_man_depth", "Teammate was ahead of play in opponent corner", 75.0, 75.0),
    )
    case = DecisionCase(
        case_id="adv-case-4-unsupported",
        replay_id="test-replay",
        t0=75.0,
        focus_player_id="player-1",
        focus_player_name="Player 1",
        focus_player_team="blue",
        situation_type="first_man_challenge",
        evidence=ev,
        tactical_context={
            "mate_distance": 6000,
            "mate_relative_depth": "ahead",
            "defensive_coverage_verified": False,
        },
        feasible_alternatives=("fake_challenge_and_rotate_out", "shadow_and_delay"),
        uncertainties=("Opponent flick capability",),
    )

    finding = evaluate_decision_case_heuristics(case)
    assert finding is not None
    assert finding["assessment"] == "tactical_risk"
    assert finding["type"] == "tactical_risk"
    assert "without defensive depth" in finding["title"].lower()


# Scenario 5: Structured Prompt Generation with Sanitized Pre-Decision Context
def test_scenario_5_prompt_generation_strictly_sanitizes_context():
    """Structured LLM prompt must contain pre-decision facts and omit post-decision timestamps."""
    ev = (
        make_evidence("challenge_approach", "Player challenging at midfield", 85.0, 85.0, source="derived"),
        make_evidence("second_man_depth", "Teammate at defensive depth 1200 units behind", 85.0, 85.0),
    )
    case = DecisionCase(
        case_id="adv-case-5-support",
        replay_id="test-replay",
        t0=85.0,
        focus_player_id="player-1",
        focus_player_name="Player 1",
        focus_player_team="blue",
        situation_type="first_man_challenge",
        evidence=ev,
        tactical_context={
            "mate_distance": 1200,
            "mate_relative_depth": "behind",
            "resolve_time": 85.4,  # Future timestamp deliberately injected!
            "outcome": "loss",      # Future outcome deliberately injected!
        },
        feasible_alternatives=("maintain_pressure", "rotate_to_midfield"),
        uncertainties=("Teammate pass trajectory",),
    )

    prompt = build_decision_case_llm_prompt(case, include_quarantined_outcomes=False)
    # The prompt MUST NOT contain the leaked resolve_time or outcome
    assert "85.4" not in prompt
    assert '"outcome": "loss"' not in prompt
    assert "SECTION 1: VERIFIED PRE-DECISION FACTS" in prompt
    assert "HYPOTHETICAL ALTERNATIVES TO INSPECT" in prompt


# Scenario 6: Low-Boost Goalkeeper (Constrained Situation vs Mistake)
def test_scenario_6_low_boost_goalkeeper_framed_as_constrained_situation():
    """A low-boost goalkeeper should be framed as in a constrained position, advising pad pathing."""
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
        focus_player_name="Player 1",
        focus_player_team="blue",
        situation_type="last_man_defense",
        evidence=ev,
        tactical_context={
            "dist_to_goal": 200,
            "ball_dist": 1200,
            "boost_at_t0": 6.0,
            "is_constrained_boost": True,
        },
        feasible_alternatives=("shadow_across_goal_mouth", "hold_back_post_position"),
        uncertainties=("Shooter placement accuracy",),
    )

    finding = evaluate_decision_case_heuristics(case)
    assert finding is not None
    assert finding["assessment"] == "constrained_situation"
    assert "Low-boost" in finding["title"]
    assert "small pads" in finding["advice"]


# Scenario 7: Positive Defensive Alignment Hypothesis
def test_scenario_7_positive_defensive_alignment_hypothesis():
    """Player positioned at back post with boost receives tactical positioning hypothesis."""
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
        focus_player_name="Player 1",
        focus_player_team="blue",
        situation_type="last_man_defense",
        evidence=ev,
        tactical_context={
            "dist_to_goal": 450,
            "ball_dist": 2200,
            "boost_at_t0": 65.0,
            "is_constrained_boost": False,
        },
        feasible_alternatives=("hold_back_post_position", "shadow_across_goal_mouth"),
        uncertainties=("Opponent pass or backboard read",),
    )

    finding = evaluate_decision_case_heuristics(case)
    assert finding is not None
    assert finding["assessment"] == "tactical_hypothesis"
    assert "Last-man goal defense posture" in finding["title"]


# Scenario 8: Ambiguous / Missing Telemetry Fails Closed
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
        focus_player_name="Player 1",
        focus_player_team="blue",
        situation_type="last_man_defense",
        evidence=ev,
        tactical_context={"dist_to_goal": 200, "is_constrained_boost": False},
        feasible_alternatives=("hold_net",),
        uncertainties=("Missing boost telemetry",),
    )

    with pytest.raises(ValueError, match="unknown, retrospective, or future-derived"):
        evaluate_decision_case_heuristics(case)


# =========================================================================
# Priority 1: Deliberate Hindsight Leakage Regression Tests
# =========================================================================

def test_hindsight_leakage_in_tactical_context_is_blocked():
    """Deliberately injects post-t0 timestamps and outcome labels; verifies sanitization blocks them."""
    case = DecisionCase(
        case_id="leak-test",
        replay_id="test-replay",
        t0=10.0,
        focus_player_id="p1",
        focus_player_name="Player 1",
        focus_player_team="blue",
        situation_type="first_man_challenge",
        evidence=(),
        tactical_context={
            "valid_pre_decision_metric": 42.0,
            "resolve_time": 10.4,          # Leak: timestamp > t0
            "end_time": 12.0,              # Leak: timestamp > t0
            "winning_team": "blue",        # Leak: outcome label
            "outcome": "goal_scored",      # Leak: outcome label
            "scoring_margin": 1,           # Leak: outcome metric
        },
        feasible_alternatives=(),
        uncertainties=(),
    )

    sanitized = case.sanitized_pre_decision_context()
    assert "valid_pre_decision_metric" in sanitized
    assert "resolve_time" not in sanitized
    assert "end_time" not in sanitized
    assert "winning_team" not in sanitized
    assert "outcome" not in sanitized
    assert "scoring_margin" not in sanitized

    payload = case.to_llm_payload()
    payload_ctx = payload["tactical_context"]
    assert "valid_pre_decision_metric" in payload_ctx
    assert "resolve_time" not in payload_ctx
    assert "winning_team" not in payload_ctx


def test_nearest_frame_lookup_never_samples_future_frame():
    """Verify that _find_car_at_time and _find_ball_at_time NEVER select a frame after target_time."""
    # Frame 0: t=9.92 (0.08s before target)
    # Frame 1: t=10.01 (0.01s after target - mathematically closer!)
    frames = [
        {"t": 9.92, "cars": {"p1": {"x": 100, "y": 200, "z": 17, "boost": 40}}, "ball": {"x": 0, "y": 0, "z": 90}},
        {"t": 10.01, "cars": {"p1": {"x": 500, "y": 600, "z": 50, "boost": 10}}, "ball": {"x": 100, "y": 200, "z": 300}},
    ]

    # Target is exactly 10.0
    car = _find_car_at_time(frames, target_time=10.0, player_id="p1")
    assert car is not None
    # Must return frame at 9.92, NOT the closer future frame at 10.01!
    assert car["x"] == 100
    assert car["boost"] == 40

    ball = _find_ball_at_time(frames, target_time=10.0)
    assert ball is not None
    assert ball["x"] == 0
    assert ball["z"] == 90


def test_kickoff_support_classified_cannot_be_cited_at_t0():
    """Verify that decoder-derived support_behavior finalized at touch time cannot be cited at t0."""
    t0 = 9.5
    t_touch = 10.0
    ev = (
        make_evidence("kickoff_spawn", "Spawned center", 7.5, 7.5),
        make_evidence("kickoff_role", "Second man", 7.5, 7.5, source="derived"),
        # Classified behavior finalized through t_touch > t0
        Evidence(
            key="kickoff_support_classified",
            claim="Decoder post-hoc classified as cheat",
            event_time_s=t0,
            finalized_through_s=t_touch,
            kind="decision_context",
            source="derived",
            source_quality="medium",
        ),
    )
    case = DecisionCase(
        case_id="kickoff-leak",
        replay_id="test",
        t0=t0,
        focus_player_id="p1",
        focus_player_name="P1",
        focus_player_team="blue",
        situation_type="kickoff_support",
        evidence=ev,
        tactical_context={"spawn_position": "center"},
        feasible_alternatives=(),
        uncertainties=(),
    )

    # Pre-decision evidence must NOT contain kickoff_support_classified
    pre_keys = [e.key for e in case.pre_decision_evidence()]
    assert "kickoff_support_classified" not in pre_keys

    # Attempting to cite kickoff_support_classified at t0 must raise ValueError
    with pytest.raises(ValueError, match="unknown, retrospective, or future-derived"):
        case.validate_admissibility(["kickoff_support_classified"])


def test_mock_llm_prompt_strictly_excludes_outcomes_by_default():
    """Verify that build_decision_case_llm_prompt withholds post-decision outcomes by default."""
    ev = (
        make_evidence("kickoff_spawn", "Spawned center", 8.0, 8.0),
        make_evidence("kickoff_outcome", "Opponent scored a goal 3 seconds later", 12.0, 12.0, kind="post_decision_outcome"),
    )
    case = DecisionCase(
        case_id="prompt-leak",
        replay_id="test",
        t0=9.0,
        focus_player_id="p1",
        focus_player_name="P1",
        focus_player_team="blue",
        situation_type="kickoff_support",
        evidence=ev,
        tactical_context={"spawn": "center"},
        feasible_alternatives=(),
        uncertainties=(),
    )

    prompt = build_decision_case_llm_prompt(case)
    assert "Opponent scored a goal" not in prompt
    assert "SECTION 5" not in prompt

    res = evaluate_decision_case_llm_mock(case)
    assert res["mode"] == "llm_structured_evaluation"
    assert "Opponent scored a goal" not in res.get("advice", "")
