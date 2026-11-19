"""Round 13 adversarial Stage-1 firewall tests — synthetic, not expert labels.

Three distinct t0 cutoffs. Rewrites all future ball/player outcomes and a
misleading 'conceded goal' replay title / score AFTER the decision. The source
packet and lesson judgment must be identical. No external provider is called.
"""
from __future__ import annotations

import copy

import pytest

from coach_app.coach_lesson import build_lesson_from_episode
from coach_app.episode_evidence import build_episode_evidence
from coach_app.episode_stage1 import build_stage1_episode_packet
from coach_app.relational_invariants import build_relational_invariants
from tests.test_episode_evidence import episode_replay


def _episode(replay: dict, t0: float):
    # Two prior recorded context samples, not asserted causal player decisions.
    return build_episode_evidence(replay, "b1", [2.0, 6.0, t0], 0.5, t0)


@pytest.mark.parametrize("t0", [8.0, 9.0, 10.0])
def test_stage1_and_model_sanitized_geometry_ignore_future_and_outcome_metadata(t0):
    original = episode_replay()
    modified = copy.deepcopy(original)
    # Adversarial titles and score fields should never reach the Stage 1 model.
    modified["title"] = "PRIVATE_SCORING_LOSS_0_3_GOAL_CONCEDED"
    modified["scoreboard"] = {"blue": 0, "orange": 3, "post_t0": True}
    modified["result"] = {"winner": "orange", "end_goal": "conceded"}
    for frame in modified["frames"]:
        if frame["t"] > t0:
            frame["ball"].update(x=-3900.0, y=4800.0, z=600.0)
            frame["cars"]["b1"].update(x=3800.0, y=4900.0, boost=100.0)
            frame["cars"]["o1"].update(x=-3800.0, y=-4900.0, boost=0.0)
    modified["events"] = [
        e for e in modified["events"] if e.get("t", float("inf")) <= t0
    ] + [
        {"type": "touch", "t": round(t0 + .25, 2), "playerId": "b2"},
        {"type": "goal_context", "t": round(t0 + 1, 2),
         "scorerId": "o1", "scoringTeam": "orange"},
    ]

    initial = _episode(original, t0)
    swapped = _episode(modified, t0)
    stage_a = build_stage1_episode_packet(initial)
    stage_b = build_stage1_episode_packet(swapped)
    assert stage_a == stage_b
    assert stage_a["retrospective_present"] is False
    assert "PRIVATE_SCORING_LOSS" not in repr(stage_a)
    assert "GOAL_CONCEDED" not in repr(stage_a)
    assert "post_t0" not in repr(stage_a)
    assert "scoreboard" not in repr(stage_a)

    spatial_a = build_relational_invariants(stage_a)
    spatial_b = build_relational_invariants(stage_b)
    assert spatial_a == spatial_b
    assert spatial_a["uses_future"] is False

    lesson_a = build_lesson_from_episode(initial)
    lesson_b = build_lesson_from_episode(swapped)
    assert lesson_a["validation"]["stage1_packet_sha256"] == lesson_b["validation"]["stage1_packet_sha256"]
    assert lesson_a["assessment"] == lesson_b["assessment"]
    assert lesson_a["claims"] == lesson_b["claims"]
    assert lesson_a["tactical_options"] == lesson_b["tactical_options"]
    assert lesson_a["validation"]["future_outcomes_used"] is False
