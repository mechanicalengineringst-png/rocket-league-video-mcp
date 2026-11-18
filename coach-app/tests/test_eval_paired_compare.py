"""Regression tests for paired model comparisons with replay-group correlation."""
import copy

import pytest

from evaluation.paired_compare import paired_compare


def case(cid: str, group: str) -> dict:
    return {
        "case_id": cid,
        "t0": 10.0,
        "situation_type": "first_man_challenge",
        "mode": "2v2",
        "replay_group": group,
        "pre_decision_evidence": [{
            "key": "E1", "claim": "Car position and teammate coverage at t0",
            "event_time_s": 9.9, "finalized_through_s": 9.95,
            "source": "replay_telemetry", "source_quality": "high",
        }],
    }


def reviews(cases: list[dict], label: str = "sound") -> list[dict]:
    return [
        {"case_id": c["case_id"], "rater_id": rater, "verdict": label}
        for c in cases for rater in ("reviewer-a", "reviewer-b")
    ]


def pred(cid: str, system: str, label: str, citations=None) -> dict:
    return {
        "case_id": cid, "system_id": system, "assessment": label,
        "cited_evidence": ["E1"] if citations is None else citations,
    }


def test_unequal_match_sizes_reverse_naive_case_weighted_winner():
    cases = [case(f"large-{i}", "large") for i in range(12)]
    cases += [case("small-a", "small-a"), case("small-b", "small-b")]
    predictions = []
    for c in cases:
        cid = c["case_id"]
        predictions += [
            pred(cid, "a", "sound" if cid.startswith("large") else "risk"),
            pred(cid, "b", "risk" if cid.startswith("large") else "sound"),
        ]
    report = paired_compare(cases, predictions, reviews(cases), "a", "b",
                            bootstrap_samples=200)
    metric = report["metrics"]["grounded_correct"]
    assert report["consensus_cases"] == 14
    assert report["consensus_match_groups"] == 3
    assert metric["first_events"] == 12
    assert metric["second_events"] == 2
    # Counting all 14 clip-level decisions incorrectly favors system a.
    assert metric["delta_case_weighted"] == round(10 / 14, 4)
    # Equal replay weighting reveals that a is worse on 2/3 matches.
    assert metric["delta_match_equal"] == round(-1 / 3, 4)
    assert metric["bootstrap_status"] == "exploratory_cluster_interval"
    assert metric["bootstrap_95pct_interval_of_match_equal_delta"] is not None
    assert metric["delta_match_equal"] != metric["delta_case_weighted"]


def test_missing_abstentions_and_unsupported_evidence_never_inflate_score():
    cases = [case("first", "r1"), case("second", "r2"), case("third", "r3")]
    lab = reviews([cases[0]], "sound") + reviews([cases[1]], "risk") + reviews(
        [cases[2]], "sound"
    )
    predictions = [
        pred("first", "a", "risk", []),        # unsupported false blame
        pred("second", "a", "risk"),           # correct
        pred("third", "a", "abstain"),         # not a selective success
        pred("first", "b", "sound"),           # correct
        # System b never answered second.
        pred("third", "b", "risk"),            # grounded but false blame
    ]
    report = paired_compare(cases, predictions, lab, "a", "b",
                            bootstrap_samples=200)
    m = report["metrics"]
    assert m["grounded_correct"]["first_events"] == 1
    assert m["grounded_correct"]["second_events"] == 1
    assert m["grounded_coverage"]["first_events"] == 1
    assert m["grounded_coverage"]["second_events"] == 2
    assert m["unsupported_attempt"]["first_events"] == 1
    assert m["unsupported_attempt"]["second_events"] == 0
    assert m["false_blame_on_sound"]["paired_cases"] == 2
    assert m["false_blame_on_sound"]["first_events"] == 1
    assert m["false_blame_on_sound"]["second_events"] == 1


def test_expert_disagreement_indeterminacy_and_missing_labels_are_not_truth():
    cases = [case("good", "r1"), case("disagree", "r2"),
             case("missing", "r3"), case("unknown", "r4")]
    lab = [
        *reviews([cases[0]], "sound"),
        {"case_id": "disagree", "rater_id": "one", "verdict": "sound"},
        {"case_id": "disagree", "rater_id": "two", "verdict": "risk"},
        {"case_id": "missing", "rater_id": "one", "verdict": "risk"},
        *reviews([cases[3]], "indeterminate"),
    ]
    predictions = [
        pred(c["case_id"], sys, "sound")
        for c in cases for sys in ("a", "b")
    ]
    report = paired_compare(cases, predictions, lab, "a", "b",
                            bootstrap_samples=200)
    assert report["consensus_cases"] == 1
    assert report["excluded_disputed"] == 1
    assert report["excluded_insufficient_review"] == 1
    assert report["excluded_indeterminate"] == 1
    metric = report["metrics"]["grounded_correct"]
    assert metric["paired_cases"] == 1
    assert metric["bootstrap_95pct_interval_of_match_equal_delta"] is None
    assert metric["bootstrap_status"] == "insufficient_match_groups_for_interval"


def test_duplicate_citations_count_as_unsupported_and_not_as_correct():
    cases = [case("c1", "r1"), case("c2", "r2"), case("c3", "r3")]
    predictions = [
        pred(c["case_id"], "a", "sound", ["E1", "E1"])
        for c in cases
    ] + [
        pred(c["case_id"], "b", "sound", ["E1"])
        for c in cases
    ]
    report = paired_compare(cases, predictions, reviews(cases), "a", "b",
                            bootstrap_samples=200)
    assert report["metrics"]["grounded_correct"]["first_events"] == 0
    assert report["metrics"]["grounded_correct"]["second_events"] == 3
    assert report["metrics"]["unsupported_attempt"]["first_events"] == 3
    assert report["metrics"]["unsupported_attempt"]["second_events"] == 0


def test_cluster_bootstrap_is_seeded_and_identical_systems_have_zero_delta():
    cases = [case(f"{g}-{i}", g) for g in ("r1", "r2", "r3", "r4")
             for i in range(3)]
    predictions = [
        pred(c["case_id"], sys, "sound" if i % 2 == 0 else "tradeoff")
        for c in cases for i in [int(c["case_id"][-1])]
        for sys in ("a", "b")
    ]
    inputs = (cases, predictions, reviews(cases), "a", "b")
    a = paired_compare(*inputs, seed=19, bootstrap_samples=200)
    b = paired_compare(*inputs, seed=19, bootstrap_samples=200)
    assert a == b
    for m in a["metrics"].values():
        if m["paired_cases"]:
            assert m["delta_match_equal"] == 0
            if m["eligible_match_groups"] >= 3:
                assert m["bootstrap_95pct_interval_of_match_equal_delta"] == [0, 0]


def test_reject_invalid_timestamp_system_ids_and_lack_of_expert_consensus():
    cases = [case("c1", "r1"), case("c2", "r2"), case("c3", "r3")]
    predictions = [pred(c["case_id"], sys, "sound")
                   for c in cases for sys in ("a", "b")]
    labels = reviews(cases)
    with pytest.raises(ValueError, match="distinct"):
        paired_compare(cases, predictions, labels, "a", "a")
    with pytest.raises(ValueError, match="Both systems"):
        paired_compare(cases, predictions, labels, "a", "never-exported")
    with pytest.raises(ValueError, match="bootstrap_samples"):
        paired_compare(cases, predictions, labels, "a", "b",
                       bootstrap_samples=9)
    future = copy.deepcopy(cases)
    future[0]["pre_decision_evidence"][0]["finalized_through_s"] = 11
    with pytest.raises(ValueError, match="post-decision-derived evidence"):
        paired_compare(future, predictions, labels, "a", "b")
    with pytest.raises(ValueError, match="No two-reviewer"):
        paired_compare(cases, predictions, [
            {"case_id": c["case_id"], "rater_id": "one", "verdict": "sound"}
            for c in cases
        ], "a", "b", bootstrap_samples=200)
