"""Round 9 CoachLessonV0 evidence and adversarial model-output tests.

All synthetic fixtures. These test claim provenance and safe behavior, NOT
expert correctness of tactical advice or actual model quality.
"""
from __future__ import annotations

import copy
import json

import pytest

from coach_app.coach_lesson import (
    CoachDraftError, answer_evidence_followup, build_lesson_from_episode,
)
from coach_app.episode_evidence import build_episode_evidence
from tests.test_episode_evidence import episode_replay


def episode(source=None):
    return build_episode_evidence(
        episode_replay() if source is None else source,
        "b1", [2.0, 6.0, 10.0], 0.5, 10.0,
        label="PRIVATE_FUTURE_OUTCOME_GOAL",
    )


def simple_claim(*, claim_id="t1", node_id="N3", epistemic_type="TACTICAL_INFERENCE",
                 section="tactical_context", refs=None, text=None, preds=None):
    return {
        "claim_id": claim_id,
        "node_id": node_id,
        "section": section,
        "epistemic_type": epistemic_type,
        "temporal_scope": "PRE_DECISION",
        "cited_evidence_ids": ["N3/E.focus.boost"] if refs is None else refs,
        "predicate_checks": [] if preds is None else preds,
        "text": ("Holding goal-side position might preserve a defensive option."
                 if text is None else text),
    }


def draft(*claims, assessment="tradeoff"):
    return {"schema": "CoachDraftV0", "assessment": assessment, "claims": list(claims)}


def test_deterministic_baseline_is_useful_evidence_not_fabricated_coaching():
    lesson = build_lesson_from_episode(episode())
    assert lesson["schema"] == "CoachLessonV0"
    assert lesson["mode"] == "deterministic_baseline"
    assert lesson["stage"] == "predecision"
    assert lesson["decision"]["node_id"] == "N3"
    assert lesson["decision"]["t0_s"] == 10.0
    assert lesson["assessment"]["grade"] == "undetermined"
    assert len(lesson["claims"]) == 2
    assert {c["text"] for c in lesson["claims"]} == {
        "Recorded focus boost was 10.",
        "Recorded teammate boost was 45.",
    }
    assert all(c["author"] == "deterministic_template" for c in lesson["claims"])
    assert all(c["evidence_refs"][0].startswith("N3/E.") for c in lesson["claims"])
    assert lesson["earlier_factors"]
    assert all(f["status"] == "hypothesis_unverified" for f in lesson["earlier_factors"])
    assert lesson["validation"]["semantic_tactical_accuracy_verified"] is False
    assert lesson["validation"]["future_outcomes_used"] is False
    text = json.dumps(lesson)
    assert "PRIVATE_FUTURE_OUTCOME_GOAL" not in text
    assert "scorerId" not in text
    assert '"retrospective"' not in text


def test_model_proposal_with_real_citations_is_shown_only_as_a_hypothesis():
    a = simple_claim(
        claim_id="a", refs=["N3/E.focus.boost", "N3/E.teammate.position"],
        text="A controlled shadow could remain defensible depending on teammate recovery.",
    )
    b = simple_claim(
        claim_id="b", section="alternative", epistemic_type="HYPOTHETICAL_ALTERNATIVE",
        refs=["N3/E.focus.boost", "N3/E.ball.position"],
        text="A controlled 50/50 might also be reasonable if the contact is reachable.",
    )
    c = simple_claim(
        claim_id="c", section="earlier_factor",
        refs=["N1/E.focus.boost", "N3/E.focus.boost", "H.1"],
        text="An earlier boost decision merits review, but causation is unverified.",
    )
    lesson = build_lesson_from_episode(episode(), model_draft=draft(a, b, c))
    assert lesson["mode"] == "model_proposal"
    assert lesson["assessment"] == {
        "grade": "tradeoff", "status": "model_hypothesis_not_expert_validated",
    }
    assert lesson["validation"]["accepted_model_claims"] == 3
    assert lesson["validation"]["rejected_model_claims"] == []
    model_claims = [x for x in lesson["claims"] if x["author"] == "model_proposal"]
    assert len(model_claims) == 3
    assert all(x["review_status"] == "needs_semantic_review" for x in model_claims)
    assert all(x["review_warnings"] for x in model_claims)
    assert all("retrospective" not in x["text"] for x in model_claims)


def test_correct_scalar_assertion_is_checked_across_node_scopes():
    c = simple_claim(
        claim_id="facts", epistemic_type="OBSERVED_FACT",
        section="observation", refs=["N1/E.focus.boost", "N3/E.focus.boost"],
        text="Focus boost fell from 60 to 10.",
        preds=[
            {"evidence_id": "N1/E.focus.boost", "value_path": [], "relation": "eq", "stated_value": 60.0},
            {"evidence_id": "N3/E.focus.boost", "value_path": [], "relation": "eq", "stated_value": 10.0},
        ],
    )
    lesson = build_lesson_from_episode(episode(), model_draft=draft(c, assessment="undetermined"))
    assert lesson["validation"]["accepted_model_claims"] == 1
    item = next(x for x in lesson["claims"] if x["claim_id"] == "facts")
    assert len(item["predicate_checks"]) == 2
    assert {p["evidence_id"] for p in item["predicate_checks"]} == {
        "N1/E.focus.boost", "N3/E.focus.boost",
    }
    assert item["review_status"] == "needs_semantic_review"


def test_false_source_value_is_rejected_despite_correct_citation_id():
    c = simple_claim(
        claim_id="badnum", epistemic_type="OBSERVED_FACT", section="observation",
        text="Focus boost was 90.",
        preds=[{"evidence_id": "N3/E.focus.boost", "value_path": [],
                "relation": "eq", "stated_value": 90.0}],
    )
    lesson = build_lesson_from_episode(episode(), model_draft=draft(c, assessment="risky"))
    assert lesson["assessment"]["grade"] == "undetermined"
    assert lesson["validation"]["accepted_model_claims"] == 0
    assert len(lesson["validation"]["rejected_model_claims"]) == 1
    assert not any(x["claim_id"] == "badnum" for x in lesson["claims"])


def test_false_probability_is_rejected_even_when_other_numbers_are_right():
    c = simple_claim(
        claim_id="prob", epistemic_type="OBSERVED_FACT", section="observation",
        text="Focus boost was 10, with a 90 percent win probability.",
        preds=[{"evidence_id": "N3/E.focus.boost", "value_path": [],
                "relation": "eq", "stated_value": 10.0}],
    )
    lesson = build_lesson_from_episode(episode(), model_draft=draft(c))
    assert lesson["validation"]["rejected_model_claims"]
    assert lesson["validation"]["accepted_model_claims"] == 0


def test_earlier_node_cannot_use_future_node_citations():
    c = simple_claim(node_id="N1", refs=["N3/E.focus.boost"],
                     text="Later boost proved the earlier decision was wrong.")
    lesson = build_lesson_from_episode(episode(), model_draft=draft(c))
    assert lesson["validation"]["rejected_model_claims"]
    assert lesson["assessment"]["grade"] == "undetermined"


def test_retrospective_citation_is_rejected():
    c = simple_claim(refs=["N3/R.goal_within_5s"])
    lesson = build_lesson_from_episode(episode(), model_draft=draft(c))
    assert lesson["validation"]["rejected_model_claims"]
    assert lesson["validation"]["accepted_model_claims"] == 0


def test_unsupported_hypothesis_only_or_certain_causation_rejected():
    only_h = simple_claim(refs=["H.1"], text="This earlier choice caused the entire collapse.")
    certain = simple_claim(refs=["N1/E.focus.boost", "H.1"],
                           text="This definitely caused the goal.", claim_id="causal")
    lesson = build_lesson_from_episode(episode(), model_draft=draft(only_h, certain))
    assert len(lesson["validation"]["rejected_model_claims"]) == 2
    assert lesson["assessment"]["grade"] == "undetermined"


def test_numeric_time_claim_requires_direct_source_predicate():
    c = simple_claim(text="The teammate was fully recovered at 10.0 seconds.")
    lesson = build_lesson_from_episode(episode(), model_draft=draft(c))
    assert lesson["validation"]["rejected_model_claims"]
    assert not any(x["author"] == "model_proposal" for x in lesson["claims"])


def test_unverified_tactical_language_is_not_certified_by_matching_numbers():
    c = simple_claim(
        claim_id="unsupported", epistemic_type="TACTICAL_INFERENCE",
        section="takeaway", text="Focus had 10 boost, therefore shadowing was guaranteed to prevent a goal.",
        preds=[{"evidence_id": "N3/E.focus.boost", "value_path": [],
                "relation": "eq", "stated_value": 10.0}],
    )
    lesson = build_lesson_from_episode(episode(), model_draft=draft(c))
    accepted = [x for x in lesson["claims"] if x["author"] == "model_proposal"]
    # Numeric grounding cannot make guaranteed tactical outcomes true.
    assert accepted == []
    assert len(lesson["validation"]["rejected_model_claims"]) == 1
    assert lesson["validation"]["semantic_tactical_accuracy_verified"] is False


def test_undisclosed_observation_cannot_become_known_when_primary_abstains():
    r = episode_replay()
    r["frames"] = [f for f in r["frames"] if not 9.7 <= f["t"] <= 10.0]
    basic = build_lesson_from_episode(episode(r))
    assert basic["decision"]["status"] == "abstain"
    assert basic["claims"] == []
    c = simple_claim(text="Shadowing was obviously the best play.")
    model = build_lesson_from_episode(episode(r), model_draft=draft(c, assessment="defensible"))
    assert model["validation"]["rejected_model_claims"]
    assert model["assessment"]["grade"] == "undetermined"


def test_future_rewrite_has_no_effect_on_lesson_or_followup_hash():
    raw = episode_replay()
    future = copy.deepcopy(raw)
    for frame in future["frames"]:
        if frame["t"] > 10:
            frame["cars"]["b1"]["boost"] = 100
            frame["ball"]["y"] = 5000
    future["events"] += [{"type": "goal_context", "t": 10.25, "scorerId": "b1"}]
    assert build_lesson_from_episode(episode(raw)) == build_lesson_from_episode(episode(future))
    assert answer_evidence_followup(episode(raw), "What boost did I have?") == (
        answer_evidence_followup(episode(future), "What boost did I have?")
    )


def test_followup_navigates_evidence_but_does_not_fabricate_answer():
    e = episode()
    r = answer_evidence_followup(e, "Was my teammate positioned to cover?")
    assert r["schema"] == "CoachFollowupV0"
    assert r["mode"] == "local_evidence_navigation"
    assert r["topic"] == "teammate_support"
    assert any(ref.endswith("E.teammate.position") for ref in r["related_refs"])
    assert r["model_called"] is False
    assert r["semantic_answer_verified"] is False
    vague = answer_evidence_followup(e, "Why did they intentionally double fake?")
    assert vague["semantic_answer_verified"] is False


def test_malformed_model_draft_does_not_silently_pass():
    with pytest.raises(CoachDraftError):
        build_lesson_from_episode(episode(), model_draft={"assessment": "risky"})
    with pytest.raises(CoachDraftError):
        build_lesson_from_episode(episode(), model_draft={
            "schema": "CoachDraftV0", "assessment": "perfect", "claims": [],
        })
    with pytest.raises(CoachDraftError):
        build_lesson_from_episode(episode(), model_draft={
            "schema": "CoachDraftV0", "assessment": "risky", "claims": [], "verified": True,
        })


def test_bad_claim_fields_never_become_user_facing_text():
    c = simple_claim()
    c["assertion_was_verified"] = True
    lesson = build_lesson_from_episode(episode(), model_draft=draft(c))
    assert lesson["validation"]["accepted_model_claims"] == 0
    assert len(lesson["validation"]["rejected_model_claims"]) == 1
