"""Blind review package generation and round-trip resolution tests."""
import copy

import pytest

from evaluation.prepare import build_packets, resolve_submissions
from evaluation.score import evaluate


def cases():
    return [
        {
            "case_id": name,
            "replay_group": "anonymous-match-1",
            "mode": "2v2",
            "t0": 15.0 + i,
            "situation_type": "first_man_challenge",
            "pre_decision_evidence": [{
                "key": "observed_state",
                "claim": "Teammate was deeper; defensive readiness unknown.",
                "event_time_s": 14.97 + i,
                "finalized_through_s": 14.98 + i,
                "source": "replay",
                "source_quality": "high",
            }],
        }
        for i, name in enumerate(["real-case-1", "real-case-2", "real-case-3"])
    ]


def predictions():
    return [
        {"case_id": name, "system_id": system,
         "assessment": assessment, "cited_evidence": ["observed_state"],
         "title": "A possible tactical tradeoff", "advice": "Review teammate coverage."}
        for name, assessment in [("real-case-1", "risk"), ("real-case-2", "sound")]
        for system in ["small-value-model", "cloud-model"]
    ]


def test_blinded_packets_hide_original_case_ids_and_model_names():
    packets = build_packets(cases(), predictions())
    decisions = packets["decision_packets"]
    quality = packets["quality_packets"]
    assert len(decisions) == 3
    assert len(quality) == 4
    assert all(d["review_id"].startswith("C") for d in decisions)
    assert all(q["review_id"].startswith("Q") for q in quality)
    assert all(not set(d).intersection({"system_id", "case_id", "replay_group", "outcome"})
               for d in decisions)
    assert all(not set(q).intersection({"system_id", "case_id", "replay_group", "outcome"})
               for q in quality)
    assert set(packets["private_map"]["decision_ids"].values()) == {
        "real-case-1", "real-case-2", "real-case-3"}
    assert {pair["system_id"] for pair in packets["private_map"]["quality_ids"].values()} == {
        "small-value-model", "cloud-model"}
    assert packets == build_packets(cases(), predictions()), "same seed must reproduce packets"


def test_decision_reviews_round_trip_to_scoring():
    fixtures = cases()
    packets = build_packets(fixtures, predictions(), seed=7)
    raw_reviews = [
        {"review_id": blind, "rater_id": rater,
         "verdict": "risk" if original == "real-case-1" else "tradeoff"}
        for blind, original in packets["private_map"]["decision_ids"].items()
        for rater in ["a", "b"]
    ]
    reviews = resolve_submissions(raw_reviews, packets["private_map"], "decision")
    result = evaluate(fixtures, predictions(), reviews)
    assert result["consensus_cases"] == 3
    assert result["systems"]["small-value-model"]["risk_warning_precision"] == 1
    assert result["systems"]["small-value-model"]["consensus_answer_coverage"] == 0.6667


def test_anonymous_quality_reviews_round_trip():
    packets = build_packets(cases(), predictions())
    blinded_id = next(iter(packets["private_map"]["quality_ids"]))
    target = packets["private_map"]["quality_ids"][blinded_id]
    result = resolve_submissions([{
        "review_id": blinded_id, "rater_id": "expert-one",
        "factual_errors": 0, "unsupported_claims": 2, "useful": False,
    }], packets["private_map"], "quality")
    assert result == [{
        "case_id": target["case_id"], "system_id": target["system_id"],
        "rater_id": "expert-one", "factual_errors": 0,
        "unsupported_claims": 2, "useful": False,
    }]


def test_future_observation_or_outcome_field_prevents_packet_generation():
    fixture = cases()
    fixture[0]["pre_decision_evidence"][0]["finalized_through_s"] = 18.0
    with pytest.raises(ValueError, match="post-decision-derived"):
        build_packets(fixture, predictions())
    fixture = cases()
    fixture[0]["post_decision_outcomes"] = [{"result": "lost"}]
    with pytest.raises(ValueError, match="non-blind"):
        build_packets(fixture, predictions())


def test_unknown_review_ids_duplicate_ratings_and_bad_labels_fail_closed():
    packets = build_packets(cases(), predictions())
    mapping = packets["private_map"]
    with pytest.raises(ValueError, match="Unknown blind review ID"):
        resolve_submissions([{"review_id": "C99999", "rater_id": "a", "verdict": "sound"}],
                            mapping, "decision")
    blind = next(iter(mapping["decision_ids"]))
    duplicated = [{"review_id": blind, "rater_id": "a", "verdict": "sound"}] * 2
    with pytest.raises(ValueError, match="Duplicate review"):
        resolve_submissions(duplicated, mapping, "decision")
    with pytest.raises(ValueError, match="Invalid verdict"):
        resolve_submissions([{"review_id": blind, "rater_id": "a", "verdict": "automatic_win"}],
                            mapping, "decision")


def test_malformed_predictions_and_hidden_platform_identifiers_are_rejected():
    bad = predictions()
    bad[0] = {**bad[0], "assessment": "definitely_wrong"}
    with pytest.raises(ValueError, match="Invalid assessment"):
        build_packets(cases(), bad)
    bad_cases = copy.deepcopy(cases())
    bad_cases[0]["pre_decision_evidence"][0]["claim"] += " Steam:76561198000000000"
    with pytest.raises(ValueError, match="platform identifier"):
        build_packets(bad_cases, predictions())


def test_blind_quality_packet_rejects_self_identifying_model_text():
    agents = predictions()
    agents[0]["title"] = "Gemini recommends rotating"
    with pytest.raises(ValueError, match="self-identifies the model"):
        build_packets(cases(), agents)

    agents = predictions()
    agents[0]["advice"] = "The small-value-model rates this as a bad play"
    with pytest.raises(ValueError, match="self-identifies the model"):
        build_packets(cases(), agents)
