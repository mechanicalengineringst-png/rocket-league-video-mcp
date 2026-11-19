"""ActionRationaleV0 (Round 11). Synthetic fixtures through the real pipeline; they test the reasoning
scheme (conditions, reasons, defeaters, decisive information, gating), not expert accuracy."""
from __future__ import annotations

import copy
import json

import pytest

from coach_app.action_rationale import (MARGIN_BAND_S, RATIONALES, RationaleError, analyze_action_rationale,
                                        enumerate_condition_worlds)
from coach_app.claim_verifier import verify_stage1_claims
from coach_app.episode_evidence import build_episode_evidence
from coach_app.episode_stage1 import build_stage1_episode_packet
from tests.test_decision_state_v1 import EVEN_UNCOVERED, FIRST_EXPOSED
from tests.test_tactical_options import EVEN, FIRST_MAN, LATE_UNCOVERED, PRIMARY, START, TIMES, replay


def run(cars, **kw):
    packet = build_stage1_episode_packet(build_episode_evidence(replay(cars, **kw), "b1", TIMES, START, PRIMARY))
    return analyze_action_rationale(packet), packet


def test_covered_first_man_aggression_is_supported_by_evidence():
    r, _ = run(FIRST_MAN)
    assert "immediate_challenge" in r["supported"]
    ch = r["actions"]["immediate_challenge"]
    assert any(x["reason"] == "win_it_with_cover" and x["status"] == "satisfied" for x in ch["reasons"])
    assert all(d["status"] == "absent" for d in ch["defeaters"])


def test_several_actions_are_reasonable_with_their_premises_named():
    r, _ = run(EVEN)
    assert {"immediate_challenge", "controlled_fifty_fifty"} <= set(r["supported"])
    assert "shadow_delay" in r["conditional"]
    shadow = next(c for c in r["reasonable_choices"] if c["action"] == "shadow_delay")
    assert shadow["premises"]                                        # the uncertain premise it rests on is named
    assert len(r["reasonable_choices"]) >= 3


def test_decisive_information_says_what_would_change_the_assessment():
    r, _ = run(EVEN)
    d = {x["condition"]: x for x in r["decisive_information"]}
    assert "focus_first" in d and d["focus_first"]["current"] == "within_error"
    assert d["focus_first"]["if_false"].get("controlled_touch") == "conditional -> refuted"
    assert "RocketSim" in d["focus_first"]["how_to_resolve"] or "expert" in d["focus_first"]["how_to_resolve"]


def test_winning_first_without_cover_is_contested_not_refuted_because_contact_angle_is_unobservable():
    r, _ = run(FIRST_EXPOSED)
    ch = r["actions"]["immediate_challenge"]
    assert ch["status"] == "contested"
    steer = next(x for x in ch["reasons"] if x["reason"] == "win_it_and_steer")
    assert steer["status"] == "conditional" and "contact_away_from_second_opponent" in steer["uncertain_premises"]
    assert any(d["defeater"] == "loose_ball_theirs_uncovered" and d["status"] == "present" for d in ch["defeaters"])
    assert "shadow_delay" in r["supported"]


def test_late_uncovered_challenge_is_refuted_and_restraint_supported():
    r, _ = run(LATE_UNCOVERED)
    assert "immediate_challenge" in r["refuted"]
    assert {"shadow_delay", "goal_side_hold"} <= set(r["supported"])
    assert "not a verdict that the action was a mistake" in r["vocabulary_note"]


def test_uncovered_level_contest_is_contested_with_the_unobservable_premise_named():
    r, _ = run(EVEN_UNCOVERED)
    assert r["actions"]["immediate_challenge"]["status"] == "contested"
    decisive = {d["condition"] for d in r["decisive_information"]}
    assert "contact_away_from_second_opponent" in decisive


def test_unobservable_conditions_are_never_resolved():
    for cars in (FIRST_MAN, EVEN, LATE_UNCOVERED):
        r, _ = run(cars)
        for cid in ("contact_away_from_second_opponent", "teammate_will_rotate", "flip_available", "aware_of_second_opponent"):
            assert r["conditions"][cid]["status"] == "unobservable" and r["conditions"][cid]["claim"] is None


def test_margin_band_turns_margin_sensitive_order_into_within_error():
    r, _ = run(LATE_UNCOVERED)
    sens = {k: v["margin_sensitivity"] for k, v in r["conditions"].items() if "margin_sensitivity" in v}
    assert "teammate_first" in sens and r["conditions"]["teammate_first"]["status"] == "within_error"
    assert r["calibration"]["order_margin_band_s"] == list(MARGIN_BAND_S)


def test_gate_withholds_when_order_is_unknown():
    cars = copy.deepcopy(FIRST_MAN)
    cars["o1"].update(x=4050.0, z=700.0)
    r, _ = run(cars)
    assert r["judgment"] == "withheld" and "Arrival order is unknown." in r["reasons_for_withholding"]


def test_outcomes_never_change_the_rationale():
    def conceded(fr):
        fr["ball"] = {"x": 0.0, "y": -5000.0, "z": 300.0, "velocity": [0.0, -2500.0, 0.0]}
    for cars in (FIRST_MAN, LATE_UNCOVERED):
        a, _ = run(cars)
        b, _ = run(cars, future=conceded, events=[{"type": "goal_context", "t": 12.0, "scorerId": "o1"}])
        assert a == b


def test_retrospective_input_refused_and_claims_verify():
    r, packet = run(EVEN)
    with pytest.raises(RationaleError):
        analyze_action_rationale(dict(packet, retrospective_present=True))
    node = next(n for n in packet["nodes"] if n["node_id"] == r["node_id"])["packet"]
    assert verify_stage1_claims(node, r["claims"])["all_structural_checks_passed"]


def test_condition_worlds_explain_without_weighting():
    r, _ = run(EVEN_UNCOVERED)
    worlds = enumerate_condition_worlds(r, max_uncertain=4)
    assert len(worlds) == 16
    statuses = {w["status"]["immediate_challenge"] for w in worlds}
    assert {"contested", "refuted"} <= statuses           # depends on the unobservable contact direction
    assert not any(k in json.dumps(worlds) for k in ("probability", "weight", "likely"))


def test_every_action_family_has_a_rationale_and_vocabulary_limits_are_listed():
    r, _ = run(FIRST_MAN)
    assert set(r["actions"]) == set(RATIONALES)
    assert "bump or demolition on the carrier" in r["unmodelled_alternatives"]
