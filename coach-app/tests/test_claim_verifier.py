"""Claim verification checks source-backed numbers; free prose never auto-verifies."""
from __future__ import annotations

import copy

import pytest

from coach_app.claim_verifier import verify_stage1_claims
from coach_app.decision_evidence import build_decision_evidence
from coach_app.stage1_packet import Stage1PacketError, build_stage1_packet
from tests.test_defender_choices import scenario


def _packet(payload=None):
    p = scenario() if payload is None else payload
    return build_stage1_packet(build_decision_evidence(p, 1.0, "b1"))


def claim(ref="E.ball.position", path=None, value=-1800.0, kind="OBSERVED_FACT", text=None):
    result = {
        "claim_id": "claim1",
        "epistemic_type": kind,
        "temporal_scope": "PRE_DECISION",
        "cited_evidence_ids": [ref],
        "predicate_checks": [
            {"evidence_id": ref, "value_path": [1] if path is None else path,
             "relation": "eq", "stated_value": value}
        ],
    }
    if text is not None:
        result["text"] = text
    return result


def result(packet, c):
    report = verify_stage1_claims(packet, [c])
    assert report["all_factual_text_verified"] is False
    assert len(report["results"]) == 1
    return report["results"][0]


def test_exact_scalar_fact_with_genuine_observation_can_be_machine_checked():
    r = result(_packet(), claim())
    assert r["status"] == "structured_fact_verified"
    assert r["verified_predicates"][0]["source_value"] == -1800.0
    assert r["errors"] == []


def test_real_evidence_id_with_invented_number_is_rejected():
    bad = claim(ref="E.focus.boost", path=[], value=62.0,
                text="You had 62 boost and could immediately attack.")
    r = result(_packet(), bad)
    assert r["status"] == "rejected"
    assert any("contradicts" in e for e in r["errors"])


def test_correct_number_in_model_prose_still_requires_semantic_review():
    prose = claim(ref="E.focus.boost", path=[], value=50.0,
                  text="You had 50 boost, therefore your teammate was definitely able to cover.")
    r = result(_packet(), prose)
    assert r["status"] == "needs_semantic_review"
    assert any("meaning" in w for w in r["warnings"])
    assert any("freshness" in w for w in r["warnings"])


def test_claim_including_a_second_unverified_numeral_is_rejected():
    c = claim(ref="E.focus.boost", path=[], value=50.0,
              text="You had 50 boost, with a 90 percent success chance.")
    r = result(_packet(), c)
    assert r["status"] == "rejected"
    assert any("90" in e for e in r["errors"])


def test_source_missing_boost_remains_unknown_not_zero():
    p = scenario()
    for frame in p["frames"]:
        frame["cars"]["b1"]["boost"] = None
        frame["cars"]["b2"]["boost"] = 0.0
    pkt = _packet(p)
    known_boost = claim(ref="E.focus.boost", path=[], value=0.0)
    r = result(pkt, known_boost)
    assert r["status"] == "rejected"
    unknown = {
        "claim_id": "uncertain1", "epistemic_type": "UNKNOWN_INFORMATION",
        "temporal_scope": "PRE_DECISION",
        "cited_evidence_ids": ["U.focus.boost"],
        "predicate_checks": [],
        "text": "The focus player's boost at the decision is unknown.",
    }
    r2 = result(pkt, unknown)
    assert r2["status"] == "needs_semantic_review"
    assert r2["errors"] == []
    zero = claim(ref="E.teammate.boost", path=[], value=0.0)
    assert result(pkt, zero)["status"] != "rejected"


def test_derived_role_is_not_a_direct_observed_fact():
    c = {
        "claim_id": "role", "epistemic_type": "OBSERVED_FACT",
        "temporal_scope": "PRE_DECISION",
        "cited_evidence_ids": ["E.roles.own"], "predicate_checks": [],
        "text": "You were definitely first man.",
    }
    r = result(_packet(), c)
    assert r["status"] == "rejected"
    assert any("Derived estimate" in e for e in r["errors"])


def test_unknown_and_retrospective_citations_cannot_support_claims():
    p = _packet()
    c = claim(ref="R.goal_within_5s", value=1.0)
    assert "Retrospective" in " ".join(result(p, c)["errors"])
    c["cited_evidence_ids"] = ["U.nonexistent"]
    c["predicate_checks"][0]["evidence_id"] = "U.nonexistent"
    assert result(p, c)["status"] == "rejected"


def test_physical_prediction_requires_actual_kinematic_model_provenance():
    p = _packet()
    c = claim(kind="PHYSICALLY_ESTIMATED_FEASIBILITY")
    r = result(p, c)
    assert r["status"] == "rejected"
    assert any("kinematic" in e for e in r["errors"])
    reach = next((x for x in p["evidence"] if x["id"] == "E.reach.focus"), None)
    if reach is not None and isinstance(reach["value"], dict) and reach["value"]["t_min_s"] is not None:
        predicted = claim(ref="E.reach.focus", path=["t_min_s"],
                          value=reach["value"]["t_min_s"],
                          kind="PHYSICALLY_ESTIMATED_FEASIBILITY")
        r = result(p, predicted)
        assert r["status"] == "needs_semantic_review"
        assert r["errors"] == []


def test_future_source_time_or_corrupt_data_fails_closed():
    p = _packet()
    damaged = copy.deepcopy(p)
    damaged["evidence"][0]["source_time_s"] = 3.0
    with pytest.raises(Stage1PacketError, match="post-decision"):
        verify_stage1_claims(damaged, [claim()])
    damaged = copy.deepcopy(p)
    damaged["evidence"][0]["source_time_s"] = float("nan")
    with pytest.raises(Stage1PacketError):
        verify_stage1_claims(damaged, [claim()])


def test_nested_predicate_value_path_cannot_claim_unrecorded_fields():
    c = claim(ref="E.reach.focus", path=["unobserved_intent"], value=0.9)
    r = result(_packet(), c)
    assert r["status"] == "rejected"
    assert any("unavailable" in e for e in r["errors"])


def test_bogus_camera_claim_cannot_be_justified_by_ball_position():
    c = {
        "claim_id": "camera", "epistemic_type": "OBSERVED_FACT",
        "temporal_scope": "PRE_DECISION",
        "cited_evidence_ids": ["E.focus.camera_mode"],
        "predicate_checks": [],
        "text": "You had ball cam on and saw the second opponent.",
    }
    r = result(_packet(), c)
    assert r["status"] == "rejected"
    assert any("Nonexistent" in e for e in r["errors"])


def test_hypothetical_alternatives_are_not_marked_verified_facts():
    c = {
        "claim_id": "hypothesis", "epistemic_type": "HYPOTHETICAL_ALTERNATIVE",
        "temporal_scope": "PRE_DECISION",
        "cited_evidence_ids": ["E.ball.position"],
        "predicate_checks": [],
        "text": "A fake challenge might have kept the opponent guessing.",
    }
    r = result(_packet(), c)
    assert r["status"] == "needs_semantic_review"
    assert r["verified_predicates"] == []


def test_an_abstaining_packet_cannot_prove_what_happened():
    p = scenario()
    p["frames"] = [frame for frame in p["frames"] if frame["t"] < 0.5]
    pkt = _packet(p)
    assert pkt["status"] == "abstain"
    r = result(pkt, claim())
    assert r["status"] == "rejected"
    assert any("Abstained" in e for e in r["errors"])


def test_duplicate_ids_bad_type_and_bad_scope_rejected():
    pkt = _packet()
    pair = [claim(), claim()]
    assert not verify_stage1_claims(pkt, pair)["all_structural_checks_passed"]
    assert verify_stage1_claims(pkt, pair)["results"][1]["status"] == "rejected"
    c = claim()
    c["epistemic_type"] = "MAGICAL_OPTIMAL"
    assert result(pkt, c)["status"] == "rejected"
    c = claim()
    c["temporal_scope"] = "POST_DECISION"
    assert result(pkt, c)["status"] == "rejected"


def test_inequality_checks_are_relative_to_source_values_not_assumed_probability():
    pkt = _packet()
    c = claim(value=-1750.0)
    c["predicate_checks"][0]["relation"] = "lte"
    assert result(pkt, c)["status"] == "structured_fact_verified"
    c["predicate_checks"][0]["relation"] = "gte"
    assert result(pkt, c)["status"] == "rejected"
