"""Focused tests for the blind evaluation contract; no replay files or API keys."""
import copy

import pytest

from evaluation.score import evaluate


def case(name, time=12.0):
    return {
        "case_id": name,
        "t0": time,
        "situation_type": "first_man_challenge",
        "mode": "2v2",
        "pre_decision_evidence": [
            {
                "key": "observed_positions",
                "claim": "Teammate positioned deeper; defensive coverage unverified",
                "event_time_s": time - 0.03,
                "finalized_through_s": time - 0.03,
                "source": "replay",
                "source_quality": "high",
            },
        ],
    }


def pred(case_id, system, assessment, cites=None):
    return {
        "case_id": case_id, "system_id": system, "assessment": assessment,
        "cited_evidence": ["observed_positions"] if cites is None else cites,
    }


def reviews(case_id, verdict_a, verdict_b):
    return [
        {"case_id": case_id, "rater_id": "rater-a", "verdict": verdict_a},
        {"case_id": case_id, "rater_id": "rater-b", "verdict": verdict_b},
    ]


def test_scores_risk_precision_without_treating_disagreement_as_truth():
    dataset = [case("one"), case("two"), case("three"), case("four")]
    expert = (
        reviews("one", "risk", "risk")
        + reviews("two", "sound", "sound")
        + reviews("three", "risk", "tradeoff")
        + reviews("four", "indeterminate", "indeterminate")
    )
    outputs = [pred("one", "heuristic", "risk"),
               pred("two", "heuristic", "risk"),
               pred("three", "heuristic", "abstain"),
               pred("one", "llm", "tradeoff")]
    quality = [{
        "case_id": "one", "system_id": "heuristic", "rater_id": "rater-a",
        "factual_errors": 0, "unsupported_claims": 1, "useful": False,
    }]
    result = evaluate(dataset, outputs, expert, quality)
    assert result["cases"] == 4
    assert result["consensus_cases"] == 2
    assert result["disputed_case_ids"] == ["three"]
    assert result["indeterminate_consensus_case_ids"] == ["four"]
    old = result["systems"]["heuristic"]
    assert old["predictions"] == 3
    assert old["abstentions"] == 1
    assert old["missing_case_predictions"] == 1
    assert old["risk_warning_precision"] == 0.5
    assert old["risk_warnings_refuted_by_sound_consensus"] == 1
    assert old["human_reported_unsupported_claims"] == 1
    assert old["human_usefulness_fraction"] == 0
    assert result["systems"]["llm"]["consensus_agreement"] == 0.0


def test_predecision_export_rejects_future_finalized_fields():
    example = case("later")
    example["pre_decision_evidence"][0]["finalized_through_s"] = 12.4
    with pytest.raises(ValueError, match="post-decision-derived"):
        evaluate([example], [], [])


def test_does_not_accept_post_outcomes_in_blind_cases():
    example = case("leak")
    example["quarantined_post_decision_outcomes"] = ["goal"]
    with pytest.raises(ValueError, match="non-blind"):
        evaluate([example], [], [])


def test_rejects_external_platform_identifiers_from_public_review_data():
    example = case("private")
    example["pre_decision_evidence"][0]["claim"] = "Steam:76561198000000000 challenged"
    with pytest.raises(ValueError, match="platform identifier"):
        evaluate([example], [], [])


def test_invalid_or_missing_citations_are_counted_not_accepted_as_evidence():
    example = case("valid")
    outputs = [pred("valid", "local", "risk", ["outcome_after_contact"])]
    result = evaluate([example], outputs, reviews("valid", "sound", "sound"))
    assert result["systems"]["local"]["invalid_evidence_citation_outputs"] == 1
    assert result["systems"]["local"]["risk_warning_precision"] == 0.0


def test_no_human_consensus_does_not_invent_a_score():
    result = evaluate([case("unknown")], [pred("unknown", "model", "abstain", [])], [])
    assert result["consensus_cases"] == 0
    assert result["systems"]["model"]["risk_warning_precision"] is None
    assert result["systems"]["model"]["consensus_agreement"] is None
    assert result["insufficient_review_case_ids"] == ["unknown"]


def test_duplicate_prediction_fails_closed():
    with pytest.raises(ValueError, match="Duplicate prediction"):
        evaluate([case("a")], [pred("a", "m", "sound"), pred("a", "m", "risk")], [])


def test_source_only_claims_must_be_complete_and_causally_bounded():
    example = case("at-t0")
    incomplete = copy.deepcopy(example)
    del incomplete["pre_decision_evidence"][0]["finalized_through_s"]
    with pytest.raises(ValueError, match="post-decision-derived"):
        evaluate([incomplete], [], [])
    assert evaluate([example], [], [])["cases"] == 1
