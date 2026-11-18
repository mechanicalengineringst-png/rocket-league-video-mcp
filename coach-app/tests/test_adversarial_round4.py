"""Adversarial cases for the Round 4 coach (Phase 4). Synthetic fixtures only.

Each test is a situation where a naive coach would say something false or
unfair. The fixtures are hand-built; passing them shows the rules hold on these
constructions, not that the coach is accurate on real games. Categories already
covered elsewhere are listed at the bottom so the set can be read as a whole.
"""
from __future__ import annotations

import copy

from coach_app.coaching_qa import build_packet, validate_answer
from coach_app.decision_cases import extract_first_man_challenge_cases
from coach_app.decision_evaluation import evaluate_decision_case_heuristics
from coach_app.tactical_analysis import analyze_case, assess_challenge, assess_last_man, assess_shot, read_state
from tests.test_causal_integrity import challenge_payload
from tests.test_tactical_analysis import EXAMPLE_A, ball, car, snapshot

SUPPORTED = {"b1": car(0, 500, vy=1400, boost=70), "b2": car(-300, -1800, boost=60),
             "o1": car(0, 1500, vy=-1000, boost=40), "o2": car(1500, 4500, boost=50)}


# ---------- good decision, unlucky outcome ----------

def test_lost_fifty_and_conceded_goal_do_not_change_the_verdict():
    """The supported challenge is lost and a goal follows. Neither is known at t0."""
    won = challenge_payload()
    won["events"][0]["winningTeam"] = "blue"
    lost = copy.deepcopy(won)
    lost["events"][0]["winningTeam"] = "orange"
    lost["events"].append({"type": "goal", "t": 13.5, "scoringTeam": "orange"})
    a = [c for c in extract_first_man_challenge_cases(won) if c.focus_player_id == "b1"][0]
    b = [c for c in extract_first_man_challenge_cases(lost) if c.focus_player_id == "b1"][0]
    assert evaluate_decision_case_heuristics(a)["assessment"] == evaluate_decision_case_heuristics(b)["assessment"]
    assert analyze_case(a, won).to_dict() == analyze_case(b, lost).to_dict()


def test_correct_aggressive_challenge_is_reinforced_even_when_lost():
    f = assess_challenge(read_state(snapshot(SUPPORTED, ball(0, 1000)), 10.0, "b1"), "c")
    assert f.verdict == "reinforce"
    assert all("lost" not in s.text.lower() for s in f.statements)


# ---------- misleading future-derived labels ----------

def test_a_later_goal_label_cannot_turn_a_blocked_shot_into_praise():
    """Retrospective 'shot' label on a moment with a defender on the line."""
    cars = dict(EXAMPLE_A["cars"], o1=car(0, 5000, boost=3))
    f = assess_shot(read_state(snapshot(cars, EXAMPLE_A["ball"]), 10.0, "b1"), "s", reviewed_action="shot")
    assert f.verdict == "abstain"


def test_answer_that_uses_a_later_event_as_a_reason_is_rejected():
    f = assess_shot(read_state(snapshot(**EXAMPLE_A), 10.0, "b1"), "s-b1", reviewed_action="no_shot")
    p = build_packet(f, "why_flagged")
    r = next(i.id for i in p.items if i.kind == "retrospective")
    bad = {"sentences": [{"text": "Because no shot was taken, the lane must have looked closed.", "cites": [r]}]}
    assert validate_answer(bad, p)


# ---------- missing or unknown player data ----------

def test_demolished_or_missing_focus_car_abstains():
    cars = dict(SUPPORTED)
    cars["b1"] = dict(cars["b1"], demolished=True)
    for c in (cars, {k: v for k, v in SUPPORTED.items() if k != "b1"}):
        f = assess_challenge(read_state(snapshot(c, ball(0, 1000)), 10.0, "b1"), "d")
        assert f.verdict == "abstain"
        assert f.unknowns


def test_missing_ball_velocity_is_unknown_not_zero():
    f = assess_shot(read_state(snapshot(EXAMPLE_A["cars"], {"x": 0, "y": 3000, "z": 93}), 10.0, "b1"), "v", "no_shot")
    assert f.verdict == "abstain"
    assert any("Ball state" in u for u in f.unknowns)


def test_stale_frame_beyond_lookback_is_not_used():
    payload = snapshot(**EXAMPLE_A, t=9.0)          # last frame 1 s before t0
    r = read_state(payload, 10.0, "b1")
    assert r.focus is None and r.ball is None


# ---------- false-positive last-man accusations ----------

def test_last_man_reading_never_issues_a_verdict():
    """Deep defender, low boost, attacker bearing down: describe, do not judge."""
    cars = {"b1": car(0, -4200, boost=5), "b2": car(0, 2000, boost=50),
            "o1": car(0, -2500, vy=-1800, boost=8), "o2": car(1000, 0)}
    f = assess_last_man(read_state(snapshot(cars, ball(0, -2800, vy=-1500)), 10.0, "b1"), "l")
    assert f.verdict == "situation_brief"
    assert any("limits aerial and power options, but not a grounded shot" in s.text for s in f.statements)
    assert "What the defender chose (no choice label for this situation yet)." in f.not_established


# Covered in other files:
#   low-boost defender still saves ........ test_tactical_analysis::test_low_boost_defender_on_the_line_still_blocks
#   open net with an unseen defender ....... test_tactical_analysis::test_missing_opponent_means_the_net_is_never_called_open
#   unknown boost .......................... test_tactical_analysis::test_unknown_boost_never_becomes_costly_recovery
#   last man while teammate is deeper ...... test_causal_integrity::test_last_man_case_is_dropped_when_teammate_is_deeper
#   future-frame poisoning ................. test_causal_integrity / test_tactical_analysis (both layers)
