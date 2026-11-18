"""Round 11 ReviewBundleV0: one replay input, source-backed selection, safe lesson preview."""
from __future__ import annotations

import copy
import json

import pytest
from fastapi.testclient import TestClient

from coach_app.main import app
from coach_app.review_bundle import build_review_bundle
from tests.test_episode_evidence import episode_replay

client = TestClient(app)


def request(**kwargs):
    return {"replay": episode_replay(), "player_id": "b1", **kwargs}


def post(**kwargs):
    return client.post("/api/coach/review-bundle", json=request(**kwargs))


def test_bundle_has_real_source_backed_candidates_and_valid_lesson_previews():
    res = post(max_candidates=5, preview_count=3)
    assert res.status_code == 200, res.text
    result = res.json()
    assert result["schema"] == "CoachReviewBundleV0"
    assert result["stage"] == "predecision"
    assert result["mode"] == "local_deterministic"
    assert result["candidate_count"] > 0
    assert 0 < result["preview_count"] <= 3
    assert result["preview_attempts"] <= 3
    assert result["discovery"]["schema"] == "EpisodeCandidatesV0"
    assert result["selection"]["not_a_rank_of_mistakes"] is True
    assert result["selection"]["review_candidate_nodes_are_not_confirmed_decisions"] is True
    assert result["selection"]["model_called"] is False
    assert result["privacy"]["replay_retained"] is False
    assert result["privacy"]["raw_frames_returned"] is False
    assert result["privacy"]["raw_player_names_returned"] is False
    assert result["privacy"]["cloud_model_called"] is False
    assert "synthetic-episode" not in json.dumps(result)


def test_every_preview_is_exactly_reproducible_from_original_lesson_endpoint():
    raw = episode_replay()
    result = client.post("/api/coach/review-bundle", json={
        "replay": raw, "player_id": "b1", "max_candidates": 5,
        "preview_count": 4,
    })
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["preview_count"] > 0
    candidate_by_id = {c["candidate_id"]: c for c in data["discovery"]["candidates"]}
    for preview in data["previews"]:
        candidate = candidate_by_id[preview["candidate_id"]]
        lesson_request = {
            "replay": raw, "player_id": "b1", "mode": "deterministic",
            "episode_start_s": candidate["episode_start_s"],
            "decision_times": candidate["decision_times"],
            "primary_t0": candidate["primary_t0"],
        }
        r = client.post("/api/coach/lesson", json=lesson_request)
        assert r.status_code == 200, r.text
        assert preview["lesson"] == r.json()
        assert preview["node_semantics"] == candidate["node_meaning"]
        assert preview["selection_reason"]["signal"] == candidate["primary_signal"]


def test_no_preview_still_gives_source_checked_candidate_list():
    r = post(max_candidates=5, preview_count=0)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["candidate_count"] > 0
    assert body["preview_count"] == body["preview_attempts"] == 0
    assert body["previews"] == []
    assert body["unavailable_previews"] == []


def test_opt_in_v1_adds_unvalidated_hypotheses_without_changing_default_v0():
    default = post(max_candidates=4, preview_count=2)
    experimental = post(max_candidates=4, preview_count=2, experimental_tactical_v1=True)
    assert default.status_code == experimental.status_code == 200
    a, b = default.json(), experimental.json()
    assert a["discovery"] == b["discovery"]
    assert a["candidate_count"] == b["candidate_count"]
    assert b["selection"]["experimental_v1_requested"] is True
    by_id = {p["candidate_id"]: p["lesson"] for p in a["previews"]}
    assert b["previews"], b["unavailable_previews"]
    for row in b["previews"]:
        lesson = row["lesson"]
        v1 = lesson["experimental_decision_state_v1"]
        assert v1["schema"] == "TacticalDecisionStateV1"
        assert v1["validation"]["expert_validated"] is False
        assert v1["validation"]["best_move_established"] is False
        assert v1["validation"]["model_called"] is False
        assert lesson["assessment"]["grade"] == "undetermined"
        assert lesson["tactical_options"] == by_id[row["candidate_id"]]["tactical_options"]
    assert all("experimental_decision_state_v1" not in p["lesson"] for p in a["previews"])


def test_future_rewrite_outside_explicit_horizon_does_not_change_any_preview():
    raw = episode_replay()
    base = build_review_bundle(raw, "b1", max_candidates=4, preview_count=3, horizon_s=9.8)
    assert base["candidate_count"] > 0
    altered = copy.deepcopy(raw)
    for frame in altered["frames"]:
        if frame["t"] > 9.8:
            frame["ball"].update(x=1500, y=4900)
            frame["cars"]["b1"]["boost"] = 100
    altered["events"] = [e for e in altered["events"] if e["t"] <= 9.8] + [
        {"type": "goal_context", "t": 10.1, "scoringTeam": "orange", "scorerId": "o1"}]
    assert build_review_bundle(altered, "b1", max_candidates=4, preview_count=3, horizon_s=9.8) == base


def test_empty_review_is_honest_and_never_replaced_by_demo():
    data = episode_replay()
    for frame in data["frames"]:
        frame["ball"]["x"] = None
    res = client.post("/api/coach/review-bundle", json={
        "replay": data, "player_id": "b1",
    })
    assert res.status_code == 200, res.text
    result = res.json()
    assert result["status"] == "no_supported_candidates"
    assert result["candidate_count"] == 0
    assert result["previews"] == []
    assert result["unavailable_previews"] == []


def test_individual_lesson_failure_is_reported_not_silently_replaced(monkeypatch):
    import coach_app.review_bundle as bundle
    calls = []
    def unable(*args, **kwargs):
        calls.append(1)
        raise ValueError("PRIVATE_RAW_REPLAY_DO_NOT_EXPOSE")
    monkeypatch.setattr(bundle, "build_lesson_from_episode", unable)
    result = bundle.build_review_bundle(episode_replay(), "b1", max_candidates=4, preview_count=2)
    assert result["candidate_count"] > 0
    assert len(calls) > 0
    assert result["status"] == "partial"
    assert result["previews"] == []
    assert all(x["reason_code"] == "lesson_evidence_unavailable" for x in result["unavailable_previews"])
    assert "PRIVATE_RAW_REPLAY" not in json.dumps(result)


def test_only_bounded_number_of_previews_are_generated(monkeypatch):
    import coach_app.review_bundle as bundle
    original = bundle.build_lesson_from_episode
    calls = []
    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(bundle, "build_lesson_from_episode", counted)
    bundle.build_review_bundle(episode_replay(), "b1", max_candidates=8, preview_count=1)
    assert len(calls) == 1


@pytest.mark.parametrize("changes", [
    {"max_candidates": 0},
    {"max_candidates": 13},
    {"preview_count": -1},
    {"preview_count": 5},
    {"horizon_s": -2},
    {"horizon_s": 1000},
    {"player_id": "not-in-this-match"},
])
def test_invalid_bundle_parameters_rejected(changes):
    args = request()
    args.update(changes)
    r = client.post("/api/coach/review-bundle", json=args)
    assert r.status_code == 422, r.text


def test_1v1_and_unverified_teams_rejected():
    data = episode_replay()
    data["players"] = data["players"][:2]
    assert client.post("/api/coach/review-bundle", json={
        "replay": data, "player_id": "b1"
    }).status_code == 422
    data = episode_replay()
    data["players"] = copy.deepcopy(data["players"])
    data["players"][0]["team"] = "unknown"
    assert client.post("/api/coach/review-bundle", json={
        "replay": data, "player_id": "b1"
    }).status_code == 422


def test_same_origin_and_json_requirements_and_caps():
    assert post().status_code == 200
    r = client.post("/api/coach/review-bundle", json=request(),
                    headers={"origin": "https://attacker.invalid"})
    assert r.status_code == 403
    assert client.post("/api/coach/review-bundle", content="nope",
                       headers={"content-type": "text/plain"}).status_code == 415
    capabilities = client.get("/api/coach/capabilities").json()
    assert capabilities["single_request_review_bundle"] == "CoachReviewBundleV0"
    assert capabilities["review_bundle_max_previews"] == 4
    assert capabilities["review_bundle_invokes_model"] is False
