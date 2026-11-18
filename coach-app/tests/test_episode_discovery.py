"""Round 10 full-match discovery: Stage 1 source evidence, selection neutrality and API."""
from __future__ import annotations

import copy
import json

import pytest
from fastapi.testclient import TestClient

from coach_app.episode_discovery import DiscoveryError, discover_episode_candidates
from coach_app.episode_evidence import build_episode_evidence
from coach_app.coach_lesson import lookup_episode_evidence
from coach_app.main import app
from tests.test_episode_evidence import episode_replay

client = TestClient(app)


def discover(replay=None, **kwargs):
    return discover_episode_candidates(
        replay if replay is not None else episode_replay(), "b1", **kwargs
    )


def test_discovers_real_frame_changes_not_assumed_decisions():
    data = discover()
    assert data["schema"] == "EpisodeCandidatesV0"
    assert data["stage"] == "predecision"
    assert data["mode"] == "deterministic_source_observation"
    assert data["candidate_count"] > 0
    assert data["policy"]["calibration"] == "uncalibrated_attention_heuristics"
    assert "mistakes" in data["policy"]["does_not_establish"]
    for row in data["candidates"]:
        assert len(row["decision_times"]) == 2
        assert row["decision_times"] == [row["comparison_sample_s"], row["primary_t0"]]
        assert row["primary_t0"] - row["episode_start_s"] >= 5
        assert row["status"] == "attention_candidate_not_coaching_verdict"
        assert row["expert_validated"] is False
        assert row["retrospective_consulted"] is False
        assert "not an identified player decision" in row["node_meaning"]["N1"]
        assert "not proof of a tactical mistake" in row["node_meaning"]["N2"]


def test_all_source_ids_resolve_in_actual_sanitized_episode():
    replay = episode_replay()
    results = discover(replay)
    for row in results["candidates"]:
        episode = build_episode_evidence(
            replay, "b1", row["decision_times"], row["episode_start_s"], row["primary_t0"]
        )
        assert episode["status"] != "abstain"
        for signal in row["signals"]:
            refs = signal["evidence_refs"]
            records = lookup_episode_evidence(episode, refs)["records"]
            assert len(records) == len(refs)
            assert [r["id"] for r in records] == refs
            assert all(r["category"] == "observed_or_estimated_node_fact" for r in records)


def test_future_and_event_changes_cannot_change_past_candidate_selection():
    original = episode_replay()
    changed = copy.deepcopy(original)
    original_result = discover(original, horizon_s=9.8)
    assert original_result["candidate_count"] > 0
    for frame in changed["frames"]:
        if frame["t"] > 9.8:
            frame["cars"]["b1"]["boost"] = 100
            frame["ball"]["x"] = 4900
    changed["events"] = [{"type": "goal_context", "t": 9.5, "scoringTeam": "blue"},
                         {"type": "goal_context", "t": 11.0, "scoringTeam": "orange"}]
    changed["title"] = "PRIVATE_PLAYER_AND_MATCH_ID_SHOULD_NOT_LEAK"
    assert discover(changed, horizon_s=9.8) == original_result
    assert "PRIVATE_PLAYER" not in json.dumps(original_result)
    assert "PRIVATE_PLAYER" not in json.dumps(discover(changed, horizon_s=9.8))


def test_candidate_prioritization_has_minimum_separation_and_repeatability():
    one, two = discover(max_candidates=12), discover(max_candidates=12)
    assert one == two
    assert all(b["primary_t0"] - a["primary_t0"] >= 5
               for a, b in zip(one["candidates"], one["candidates"][1:]))
    assert one["candidate_count"] <= 12


def test_missing_kinematics_abstains_instead_of_inventing():
    replay = episode_replay()
    for frame in replay["frames"]:
        frame["cars"]["b1"]["velocity"] = None
        frame["cars"]["b1"]["forward"] = None
        frame["cars"]["b1"]["boost"] = None
        frame["ball"]["velocity"] = None
        frame["ball"]["x"] = None
    out = discover(replay)
    assert out["candidate_count"] == 0
    assert out["status"] == "no_supported_candidates"


def test_bad_replay_or_player_is_rejected_not_guessed():
    r = episode_replay()
    with pytest.raises(DiscoveryError):
        discover_episode_candidates(r, "unknown")
    with pytest.raises(DiscoveryError):
        discover(r, max_candidates=13)
    bad = copy.deepcopy(r)
    bad["frames"][4]["t"] = bad["frames"][3]["t"]
    with pytest.raises(DiscoveryError):
        discover(bad)
    bad = copy.deepcopy(r)
    bad["players"][0]["team"] = "other"
    with pytest.raises(DiscoveryError):
        discover(bad)
    with pytest.raises(DiscoveryError):
        discover(r, horizon_s=500)


def test_candidate_endpoint_returns_valid_lesson_request_and_no_model():
    replay = episode_replay()
    response = client.post("/api/coach/candidates", json={
        "replay": replay, "player_id": "b1", "max_candidates": 3
    })
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["candidate_count"] > 0
    assert out["candidate_count"] <= 3
    for row in out["candidates"]:
        lesson = client.post("/api/coach/lesson", json={
            "replay": replay, "player_id": "b1",
            "decision_times": row["decision_times"],
            "episode_start_s": row["episode_start_s"],
            "primary_t0": row["primary_t0"], "mode": "deterministic",
        })
        assert lesson.status_code == 200, lesson.text
        packet = lesson.json()
        assert packet["schema"] == "CoachLessonV0"
        assert packet["decision"]["t0_s"] == row["primary_t0"]
        assert packet["validation"]["future_outcomes_used"] is False
        assert packet["assessment"]["grade"] == "undetermined"
    caps = client.get("/api/coach/capabilities").json()
    assert caps["source_backed_candidate_discovery"] == "EpisodeCandidatesV0"
    assert caps["automatic_episode_selection"] is False
    assert caps["candidate_discovery_is_tactical_grading"] is False


def test_candidate_endpoint_rejects_bad_limits_cross_origin_and_unknown_player():
    replay = episode_replay()
    base = {"replay": replay, "player_id": "b1"}
    assert client.post("/api/coach/candidates", json={**base, "max_candidates": 0}).status_code == 422
    assert client.post("/api/coach/candidates", json={**base, "horizon_s": -1}).status_code == 422
    assert client.post("/api/coach/candidates", json={**base, "horizon_s": 10000}).status_code == 422
    assert client.post("/api/coach/candidates", json={**base, "player_id": "wrong"}).status_code == 422
    assert client.post("/api/coach/candidates", json=base,
        headers={"origin": "https://attacker.invalid"}).status_code == 403
