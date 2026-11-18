"""TacticalDecisionStateV1 (Round 10). Synthetic fixtures through the real pipeline; they test reasoning
rules and robustness logic, not expert-level tactical accuracy."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from coach_app.claim_verifier import verify_stage1_claims
from coach_app.decision_state_v1 import (CALIBRATION, DecisionStateError, analyze_decision_state, order,
                                         to_v0_stances)
from coach_app.episode_evidence import build_episode_evidence
from coach_app.episode_stage1 import build_stage1_episode_packet
from coach_app.tactical_options import analyze_tactical_options
from tests.test_tactical_options import EVEN, FIRST_MAN, LATE_UNCOVERED, PRIMARY, START, TIMES, car, replay

# Even contest but the teammate is far up-field and the other opponent sits behind the ball:
EVEN_UNCOVERED = dict(EVEN, b2=car(1500, 2500, fy=-1.0), o2=car(-600, -500, fy=-1.0))
# Focus clearly first and uncovered, the other opponent waits for a loose ball (backboard-type situation):
FIRST_EXPOSED = dict(FIRST_MAN, b2=car(1500, 3000, fy=-1.0), o2=car(-2400, -800, fy=-1.0))


def run(cars, **kw):
    packet = build_stage1_episode_packet(build_episode_evidence(replay(cars, **kw), "b1", TIMES, START, PRIMARY))
    return analyze_decision_state(packet), packet


def act(out, name):
    return next(a for a in out["actions"] if a["action"] == name)


# ---------- calibration ----------

def test_order_margin_comes_from_the_committed_calibration_file():
    data = json.loads((Path(__file__).resolve().parent.parent / CALIBRATION["source"]).read_text())
    assert CALIBRATION["order_margin_s"] == data["chosen"]["margin_s"] == data["raced"]["chosen"]["margin_s"]
    assert CALIBRATION["held_out_accuracy"] == data["chosen"]["held_out_accuracy"]
    m = CALIBRATION["order_margin_s"]
    assert order((0.5, 0.5), (0.5 + m - 0.01, 0.6 + m)) == "ambiguous"
    assert order((0.5, 0.5), (0.5 + m + 0.01, 0.6 + m)) == "a_first"
    assert order((0.5, 1.9), (0.5 + m + 0.01, 1.2)) == "ambiguous"     # pessimistic bounds disagree
    assert order(None, (1.0, 1.0)) == "unknown"


# ---------- strong decisions are not criticized ----------

def test_covered_aggressive_first_man_challenge_is_robustly_defensible():
    out, _ = run(FIRST_MAN)
    assert out["scenario"]["profile"] == "pressure_window"
    ch = act(out, "immediate_challenge")
    assert ch["stance"] == "robustly_defensible" and ch["exposed_branches"] == []
    assert act(out, "shadow_delay")["stance"] == "defensible_tradeoff"      # restraint is allowed, with its cost named
    assert act(out, "shadow_delay")["named_cost"]


def test_deliberate_fifty_fifty_with_cover_is_robust_and_several_choices_coexist():
    out, _ = run(EVEN)
    assert out["scenario"]["focus_vs_carrier"] == "ambiguous" and out["scenario"]["profile"] == "forced_contest"
    assert act(out, "controlled_fifty_fifty")["stance"] == "robustly_defensible"
    assert {"immediate_challenge", "controlled_fifty_fifty", "shadow_delay"} <= set(out["supported_choices"])
    assert out["picks_single_best"] is False


def test_uncovered_even_contest_is_a_named_gamble_not_a_mistake():
    out, _ = run(EVEN_UNCOVERED)
    ch = act(out, "immediate_challenge")
    assert out["scenario"]["cover"]["status"] == "uncovered"
    assert ch["stance"] == "defensible_gamble" and ch["exposed_branches"]
    assert ch["named_cost"] and "exposed" in ch["named_cost"]
    assert "mistake" not in json.dumps(out).lower()


# ---------- questionable decisions and restraint ----------

def test_late_uncovered_challenge_is_questionable_and_restraint_is_affirmed():
    out, _ = run(LATE_UNCOVERED)
    assert out["scenario"]["profile"] == "restraint_window"
    assert act(out, "immediate_challenge")["stance"] == "questionable"
    assert act(out, "immediate_challenge")["exposed_branches"] == ["carrier_touches_first"]
    for a in ("shadow_delay", "goal_side_hold"):
        assert act(out, a)["stance"] == "robustly_defensible"
        assert "restraint" in act(out, a)["named_upside"].lower()


def test_winning_the_ball_first_does_not_make_a_challenge_safe():
    """Backboard-type case: focus is first, but the loose ball favours their second player and nobody covers."""
    out, _ = run(FIRST_EXPOSED)
    sc = out["scenario"]
    assert sc["focus_vs_carrier"] == "a_first" and sc["cover"]["status"] == "uncovered"
    assert sc["loose_ball_race"] == "second_opponent_first"
    assert act(out, "immediate_challenge")["stance"] == "questionable"
    assert act(out, "controlled_touch")["stance"] == "defensible_gamble"     # keeping it is the safer commit


# ---------- teammate context, unknowns, abstention ----------

def test_teammate_position_changes_stances_without_blame():
    covered, _ = run(FIRST_MAN)
    exposed, _ = run(FIRST_EXPOSED)
    assert act(covered, "immediate_challenge")["stance"] != act(exposed, "immediate_challenge")["stance"]
    text = json.dumps(exposed).lower()
    assert not any(w in text for w in ("blame", "fault", "mistake", "should have"))


def test_unknown_boost_widens_the_interval_and_is_never_a_fact():
    cars = copy.deepcopy(FIRST_MAN)
    cars["b1"]["boost"] = None
    out, _ = run(cars)
    lo, hi = out["scenario"]["reach_intervals_s"]["focus"]
    assert hi >= lo + CALIBRATION["order_margin_s"] - 1e-9
    assert "boost" not in out["scenario"]["claims"]
    assert any(u["id"] == "U.focus.boost" for u in out["unknowns"])


def test_opponent_on_a_wall_makes_the_decision_abstain():
    cars = copy.deepcopy(FIRST_MAN)
    cars["o1"].update(x=4050.0, z=700.0)
    out, _ = run(cars)
    assert out["status"] == "abstain" and out["scenario"]["focus_vs_carrier"] == "unknown"
    assert act(out, "immediate_challenge")["stance"] == "undetermined"
    assert out["robust_choices"] == []


def test_missing_teammate_cover_is_partial_and_commit_actions_are_undetermined():
    cars = copy.deepcopy(FIRST_MAN)
    cars["b2"].update(x=4050.0, z=700.0)                     # teammate on a wall: cover unknown
    out, _ = run(cars)
    assert out["status"] == "partial" and "Teammate cover is unknown." in out["abstain_reasons"]
    assert act(out, "immediate_challenge")["stance"] == "undetermined"


# ---------- hindsight ----------

def _conceded(fr):
    fr["ball"] = {"x": 0.0, "y": -5000.0, "z": 300.0, "velocity": [0.0, -2500.0, 0.0]}


@pytest.mark.parametrize("cars", [FIRST_MAN, LATE_UNCOVERED, EVEN_UNCOVERED])
def test_a_conceded_goal_or_missed_shot_never_changes_the_assessment(cars):
    calm, _ = run(cars)
    goal, _ = run(cars, future=_conceded, events=[{"type": "goal_context", "t": 12.0, "scorerId": "o1"},
                                                  {"type": "touch", "t": 11.4, "playerId": "b1"}])
    assert calm == goal


def test_retrospective_input_is_refused():
    _, packet = run(FIRST_MAN)
    with pytest.raises(DecisionStateError):
        analyze_decision_state(dict(packet, retrospective_present=True))


# ---------- verifier and compatibility ----------

@pytest.mark.parametrize("cars", [FIRST_MAN, EVEN, LATE_UNCOVERED, EVEN_UNCOVERED, FIRST_EXPOSED])
def test_claims_pass_the_existing_verifier(cars):
    out, packet = run(cars)
    node = next(n for n in packet["nodes"] if n["node_id"] == out["node_id"])["packet"]
    assert verify_stage1_claims(node, out["claims"])["all_structural_checks_passed"]
    for a in out["actions"]:
        assert set(a["claims"]) <= {c["claim_id"] for c in out["claims"]}


def test_v0_remains_available_and_v1_maps_onto_its_vocabulary():
    out, packet = run(FIRST_MAN)
    v0 = analyze_tactical_options(packet)
    mapped = to_v0_stances(out)
    assert set(mapped) == {o["action"] for o in v0["options"]}
    assert set(mapped.values()) <= {"defensible", "defensible_with_conditions", "questionable", "not_available",
                                    "not_assessable"}
    both = analyze_decision_state(packet, include_v0=True)
    assert both["tactical_options_v0"] == v0
