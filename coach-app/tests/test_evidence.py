"""Regression tests for temporal and source-provenance evidence gates."""
from dataclasses import replace
import math

import pytest

from coach_app.evidence import Evidence, partition_evidence, require_decision_evidence


def item(
    key="boost",
    *,
    event_time_s=42.0,
    finalized_through_s=42.0,
    kind="decision_context",
    source="replay",
    source_quality="high",
):
    return Evidence(
        key=key, claim="Player has 45 boost",
        event_time_s=event_time_s, finalized_through_s=finalized_through_s,
        kind=kind, source=source, source_quality=source_quality
    )


def test_observed_boost_is_usable_at_decision_time():
    before = item()
    partition = partition_evidence([before], decision_time_s=42.0)
    assert partition.decision_context == (before,)
    assert require_decision_evidence(["boost"], [before], 42.0) == (before,)


def test_post_decision_possession_is_not_decision_evidence():
    possession = item("possession", event_time_s=43.2,
                      finalized_through_s=43.2, kind="post_decision_outcome")
    part = partition_evidence([possession], decision_time_s=42.0)
    assert part.outcomes == (possession,)
    with pytest.raises(ValueError, match="retrospective"):
        require_decision_evidence(["possession"], [possession], 42.0)


def test_touch_label_finalized_after_play_is_withheld():
    label = item("pass", event_time_s=42.0, finalized_through_s=44.0,
                 source="derived", source_quality="medium")
    part = partition_evidence([label], decision_time_s=42.0)
    assert part.future_derived == (label,)
    assert part.decision_context == ()


def test_model_score_can_still_depend_on_future_information():
    score = item("value", event_time_s=42.0, finalized_through_s=52.0,
                 source="model", source_quality="experimental")
    assert partition_evidence([score], 42.0).future_derived == (score,)


def test_player_intention_is_not_rewritten_as_telemetry():
    user = item("intent", event_time_s=42.0, finalized_through_s=44.0,
                kind="player_intent", source="player_feedback")
    assert partition_evidence([user], 45.0).player_intent == (user,)
    with pytest.raises(ValueError, match="retrospective"):
        require_decision_evidence(["intent"], [user], 45.0)


def test_prior_boost_and_later_goal_stay_separate():
    boost = item()
    goal = item("goal", event_time_s=49.0, finalized_through_s=49.0,
                kind="post_decision_outcome")
    part = partition_evidence([boost, goal], 42.0)
    assert part.decision_context == (boost,)
    assert part.outcomes == (goal,)


def test_unknown_and_duplicate_references_fail_closed():
    evidence = [item()]
    with pytest.raises(ValueError, match="at least one"):
        require_decision_evidence([], evidence, 42.0)
    with pytest.raises(ValueError, match="unknown"):
        require_decision_evidence(["missing"], evidence, 42.0)
    with pytest.raises(ValueError, match="repeat"):
        require_decision_evidence(["boost", "boost"], evidence, 42.0)
    with pytest.raises(ValueError, match="Duplicate evidence key"):
        partition_evidence([evidence[0], evidence[0]], 42.0)


@pytest.mark.parametrize("bad_time", [float("nan"), float("inf"), -0.1, True])
def test_invalid_timestamps_are_rejected(bad_time):
    with pytest.raises(ValueError):
        partition_evidence([], bad_time)
    with pytest.raises(ValueError):
        replace(item(), finalized_through_s=bad_time)


def test_finalization_cannot_precede_event():
    with pytest.raises(ValueError, match="before"):
        replace(item(), finalized_through_s=41.9)


def test_a_later_decision_can_use_a_previously_finalized_label():
    label = item("known_label", event_time_s=42.0,
                 finalized_through_s=44.0, source="derived")
    assert partition_evidence([label], 43.9).future_derived == (label,)
    assert partition_evidence([label], 44.0).decision_context == (label,)
