"""Round 13.5 model-provenance contract: deterministic vs model with/without claims.

These are synthetic evidence-gate unit tests, not live provider/expert tests.
"""
from __future__ import annotations

import json

from coach_app.coach_lesson import build_lesson_from_episode
from tests.test_coach_lesson import draft, episode, simple_claim


def test_local_deterministic_response_has_unambiguous_provenance():
    lesson = build_lesson_from_episode(episode())
    p = lesson["validation"]["response_provenance"]
    assert lesson["mode"] == "deterministic_baseline"
    assert p == {
        "source": "local_deterministic",
        "status": "deterministic_only",
        "model_claims_submitted": 0,
        "model_claims_accepted": 0,
        "model_claims_rejected": 0,
        "baseline_facts_only": True,
        "tactical_hypothesis_emitted": False,
        "semantic_accuracy_verified": False,
    }


def test_model_tactical_hypothesis_provenance_never_claims_expert_certification():
    lesson = build_lesson_from_episode(
        episode(), model_draft=draft(simple_claim(), assessment="tradeoff")
    )
    p = lesson["validation"]["response_provenance"]
    assert lesson["mode"] == "model_proposal"
    assert p["source"] == "model_draft_evidence_checked"
    assert p["status"] == "model_tactical_hypothesis"
    assert p["model_claims_submitted"] == 1
    assert p["model_claims_accepted"] == 1
    assert p["model_claims_rejected"] == 0
    assert p["baseline_facts_only"] is False
    assert p["tactical_hypothesis_emitted"] is True
    assert p["semantic_accuracy_verified"] is False


def test_accepted_observation_does_not_become_a_tactical_grade():
    fact = simple_claim(
        claim_id="observed", section="observation", epistemic_type="OBSERVED_FACT",
        refs=["N1/E.focus.boost", "N3/E.focus.boost"],
        text="Focus boost fell from 60 to 10.",
        preds=[
            {"evidence_id": "N1/E.focus.boost", "value_path": [], "relation": "eq", "stated_value": 60.0},
            {"evidence_id": "N3/E.focus.boost", "value_path": [], "relation": "eq", "stated_value": 10.0},
        ],
    )
    lesson = build_lesson_from_episode(
        episode(), model_draft=draft(fact, assessment="risky")
    )
    p = lesson["validation"]["response_provenance"]
    assert p["status"] == "model_claims_without_tactical_grade"
    assert p["model_claims_accepted"] == 1
    assert p["tactical_hypothesis_emitted"] is False
    assert lesson["assessment"]["grade"] == "undetermined"


def test_rejected_model_claim_is_not_silent_fallback_or_false_model_success():
    wrong = simple_claim(
        claim_id="wrong", section="observation", epistemic_type="OBSERVED_FACT",
        text="Focus boost was 90.",
        preds=[{"evidence_id": "N3/E.focus.boost", "value_path": [],
                "relation": "eq", "stated_value": 90.0}],
    )
    lesson = build_lesson_from_episode(
        episode(), model_draft=draft(wrong, assessment="risky")
    )
    p = lesson["validation"]["response_provenance"]
    assert lesson["mode"] == "model_proposal"  # a draft was supplied
    assert lesson["assessment"]["grade"] == "undetermined"
    assert p["status"] == "model_claims_withheld"
    assert p["model_claims_submitted"] == 1
    assert p["model_claims_accepted"] == 0
    assert p["model_claims_rejected"] == 1
    assert p["baseline_facts_only"] is True
    assert p["tactical_hypothesis_emitted"] is False
    assert not [c for c in lesson["claims"] if c["author"] == "model_proposal"]
    serialized = json.dumps(lesson)
    assert "PRIVATE_FUTURE_OUTCOME_GOAL" not in serialized
