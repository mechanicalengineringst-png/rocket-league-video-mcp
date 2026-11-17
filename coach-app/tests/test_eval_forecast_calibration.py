"""Verify calibrated outcome-forecast scoring without retrospective feature leakage."""
import math

import pytest

from evaluation.forecast import evaluate_forecasts


def case(cid, t0):
    return {
        "case_id": cid, "t0": t0, "mode": "2v2",
        "replay_group": "anonymous-match-a", "situation_type": "first_man_challenge",
        "pre_decision_evidence": [{
            "key": "prior_ball_position", "claim": "Ball in opponent half",
            "event_time_s": t0, "finalized_through_s": t0,
            "source": "replay", "source_quality": "high",
        }],
    }


def future(cid, t0, scored, conceded, complete=True):
    return {
        "case_id": cid, "horizon_s": 5,
        "observed_through_s": t0 + (5 if complete else 2),
        "scored_within_horizon": scored,
        "conceded_within_horizon": conceded,
    }


def forecast(cid, p_score, p_concede, system="small-value-model"):
    return {
        "case_id": cid, "system_id": system, "horizon_s": 5,
        "p_score": p_score, "p_concede": p_concede,
    }


def test_brier_calibration_and_coverage_keep_heldout_labels_separate():
    cases = [case("a", 10), case("b", 20), case("c", 30)]
    labels = [
        future("a", 10, True, False),
        future("b", 20, False, True),
        future("c", 30, False, False, complete=False),
    ]
    outputs = [
        forecast("a", 0.8, 0.2),
        forecast("b", 0.2, 0.8),
        forecast("c", 0.99, 0.99),  # censored: never scored as a negative
    ]
    report = evaluate_forecasts(cases, outputs, labels, horizon_s=5)
    stats = report["systems"]["small-value-model"]
    assert report["complete_outcome_cases"] == 2
    assert report["censored_case_ids"] == ["c"]
    assert stats["scored_forecasts"] == 2
    assert stats["forecast_coverage"] == 1.0
    assert stats["tasks"]["score"]["brier"] == 0.04
    assert stats["tasks"]["concede"]["brier"] == 0.04
    assert stats["tasks"]["score"]["constant_base_rate_brier"] == 0.25
    assert sum(b["n"] for b in stats["tasks"]["score"]["calibration_bins"]) == 2


def test_missing_forecasts_report_coverage_not_fabricated_accuracy():
    cases = [case("a", 10), case("b", 20)]
    labels = [future("a", 10, True, False), future("b", 20, False, False)]
    report = evaluate_forecasts(cases, [forecast("a", 1, 0)], labels, 5)
    stats = report["systems"]["small-value-model"]
    assert stats["missing_complete_outcome_forecasts"] == 1
    assert stats["forecast_coverage"] == 0.5


def test_never_treat_incomplete_end_of_match_as_safe_negative():
    cases = [case("a", 10)]
    labels = [future("a", 10, False, False, complete=False)]
    report = evaluate_forecasts(cases, [forecast("a", 0, 0)], labels, 5)
    assert report["complete_outcome_cases"] == 0
    assert report["systems"]["small-value-model"]["tasks"]["score"]["brier"] is None


def test_invalid_probability_and_inconsistent_horizon_fail_closed():
    cases = [case("a", 10)]
    labels = [future("a", 10, False, False)]
    with pytest.raises(ValueError, match="p_score must be between"):
        evaluate_forecasts(cases, [forecast("a", math.nan, 0.5)], labels, 5)
    with pytest.raises(ValueError, match="p_score must be between"):
        evaluate_forecasts(cases, [forecast("a", 1.01, 0.5)], labels, 5)
    bad = forecast("a", 0.3, 0.4)
    bad["horizon_s"] = 15
    with pytest.raises(ValueError, match="forecast horizon mismatch"):
        evaluate_forecasts(cases, [bad], labels, 5)


def test_duplicate_labels_or_future_conditioned_case_rejected():
    cases = [case("a", 10)]
    labels = [future("a", 10, True, False)]
    with pytest.raises(ValueError, match="Duplicate outcome"):
        evaluate_forecasts(cases, [], labels + labels, 5)
    cases[0]["pre_decision_evidence"][0]["finalized_through_s"] = 10.5
    with pytest.raises(ValueError, match="post-decision-derived"):
        evaluate_forecasts(cases, [], labels, 5)
