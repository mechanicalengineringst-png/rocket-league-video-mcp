"""Round 9 API tests: explicit opt-in, replay bounds, client controls, no hindsight upload."""
from __future__ import annotations

import copy
import json

from fastapi.testclient import TestClient

from coach_app.main import app
from tests.test_episode_evidence import episode_replay

client = TestClient(app)


def payload():
    return {
        "replay": copy.deepcopy(episode_replay()),  # never mutate shared PLAYERS fixture
        "player_id": "b1",
        "decision_times": [2.0, 6.0, 10.0],
        "episode_start_s": 0.5,
        "primary_t0": 10.0,
    }


def test_coach_capabilities_are_truthful_and_baseline_requires_no_key(monkeypatch):
    monkeypatch.delenv("REPLAY_LAB_ENABLE_COACH_MODEL", raising=False)
    r = client.get("/api/coach/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert body["local_deterministic_available"] is True
    assert body["optional_model_enabled"] is False
    assert body["tactical_accuracy_expert_verified"] is False
    assert body["automatic_episode_selection"] is False
    lesson = client.post("/api/coach/lesson", json=payload())
    assert lesson.status_code == 200, lesson.text
    data = lesson.json()
    assert data["schema"] == "CoachLessonV0"
    assert data["stage"] == "predecision"
    assert data["mode"] == "deterministic_baseline"
    assert data["decision"]["t0_s"] == 10.0
    assert data["claims"]
    assert data["assessment"]["grade"] == "undetermined"
    assert data["validation"]["rejected_model_claims"] == []


def test_model_requests_are_forbidden_without_both_opt_ins(monkeypatch):
    monkeypatch.delenv("REPLAY_LAB_ENABLE_COACH_MODEL", raising=False)
    r = client.post("/api/coach/lesson", json={**payload(), "mode": "model"})
    assert r.status_code == 403
    assert "disabled" in r.text.lower()
    monkeypatch.setenv("REPLAY_LAB_ENABLE_COACH_MODEL", "1")
    monkeypatch.delenv("REPLAY_LAB_COACH_MODEL_URL", raising=False)
    assert client.post("/api/coach/lesson", json={**payload(), "mode": "model"}).status_code == 503


def test_model_transport_gets_only_stage1_packet_when_explicitly_enabled(monkeypatch):
    from coach_app import coach_model
    monkeypatch.setenv("REPLAY_LAB_ENABLE_COACH_MODEL", "1")
    monkeypatch.setenv("REPLAY_LAB_COACH_MODEL_URL", "https://model.example/v1/chat/completions")
    monkeypatch.setenv("REPLAY_LAB_COACH_MODEL_NAME", "owner-approved-model")
    monkeypatch.setenv("REPLAY_LAB_COACH_MODEL_API_KEY", "test-placeholder-only")
    made_calls = []

    class FakeResponse:
        content = b'{"ok":true}'
        def raise_for_status(self):
            pass
        def json(self):
            return {"choices": [{"message": {"content": json.dumps({
                "schema": "CoachDraftV0", "assessment": "tradeoff", "claims": [{
                    "claim_id": "a",
                    "node_id": "N3",
                    "section": "tactical_context",
                    "epistemic_type": "TACTICAL_INFERENCE",
                    "temporal_scope": "PRE_DECISION",
                    "cited_evidence_ids": ["N3/E.focus.boost"],
                    "predicate_checks": [],
                    "text": "A delayed challenge might be defensible if teammate recovery is uncertain.",
                }],
            })}}]}

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["follow_redirects"] is False
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def post(self, url, *, headers, json):
            assert url == "https://model.example/v1/chat/completions"
            assert headers["Authorization"] == "Bearer test-placeholder-only"
            assert json["model"] == "owner-approved-model"
            assert len(json["messages"]) == 2
            content = json["messages"][1]["content"]
            packet = __import__("json").loads(content.split("\n", 1)[1])
            assert packet["schema"] == "Stage1EpisodePacketV0"
            assert "retrospective" not in packet
            assert "selection" not in content
            assert "PRIVATE_OUTCOME" not in content
            assert all("source" not in n["packet"] for n in packet["nodes"])
            made_calls.append(packet)
            return FakeResponse()

    monkeypatch.setattr(coach_model.httpx, "AsyncClient", FakeClient)
    raw = payload()
    raw["replay"]["title"] = "PRIVATE_OUTCOME"
    raw["mode"] = "model"
    response = client.post("/api/coach/lesson", json=raw)
    assert response.status_code == 200, response.text
    assert len(made_calls) == 1
    lesson = response.json()
    assert lesson["mode"] == "model_proposal"
    assert lesson["assessment"]["grade"] == "tradeoff"
    assert lesson["validation"]["accepted_model_claims"] == 1
    assert "PRIVATE_OUTCOME" not in response.text


def test_bad_model_response_not_silently_exposed_as_coaching(monkeypatch):
    from coach_app import coach_model
    monkeypatch.setenv("REPLAY_LAB_ENABLE_COACH_MODEL", "1")
    monkeypatch.setenv("REPLAY_LAB_COACH_MODEL_URL", "http://127.0.0.1:11434/v1/chat/completions")
    monkeypatch.setenv("REPLAY_LAB_COACH_MODEL_NAME", "local")

    async def fake(*args, **kwargs):
        return {"schema": "UntrustedRetrospectiveAnswer", "best_goal": "the future"}
    monkeypatch.setattr(coach_model, "propose_coach_draft", fake)
    # coach_api imports the function separately: patch its injected reference.
    from coach_app import coach_api
    monkeypatch.setattr(coach_api, "propose_coach_draft", fake)
    r = client.post("/api/coach/lesson", json={**payload(), "mode": "model"})
    assert r.status_code == 502
    assert "best_goal" not in r.text


def test_followup_provides_real_references_without_llm_or_future_facts():
    r = client.post("/api/coach/followup", json={
        **payload(), "question": "Could my teammate cover the net?",
    })
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["schema"] == "CoachFollowupV0"
    assert out["topic"] == "teammate_support"
    assert out["related_refs"]
    assert out["model_called"] is False
    assert out["semantic_answer_verified"] is False
    other = client.post("/api/coach/followup", json={
        **payload(), "mode": "model", "question": "What happened next?",
    })
    assert other.status_code == 422


def test_lesson_does_not_change_when_future_match_result_changes():
    baseline = client.post("/api/coach/lesson", json=payload()).json()
    future = payload()
    future["replay"]["events"].append({
        "type": "goal_context", "t": 11.0, "scoringTeam": "orange",
        "scorerId": "o1",
    })
    future["replay"]["frames"][-1]["cars"]["b1"]["boost"] = 100
    assert client.post("/api/coach/lesson", json=future).json() == baseline


def test_invalid_episode_replay_player_and_times_fail_closed():
    bad = payload()
    bad["player_id"] = "nonexistent"
    assert client.post("/api/coach/lesson", json=bad).status_code == 422
    bad = payload()
    bad["episode_start_s"] = 8.0  # requires a full 5-second window
    assert client.post("/api/coach/lesson", json=bad).status_code == 422
    bad = payload()
    bad["decision_times"] = [2, 2, 10]
    assert client.post("/api/coach/lesson", json=bad).status_code == 422
    bad = payload()
    bad["replay"]["players"][0]["team"] = "not-real"
    assert client.post("/api/coach/lesson", json=bad).status_code == 422
    bad = payload()
    bad["replay"]["players"][0]["team"] = None
    assert client.post("/api/coach/lesson", json=bad).status_code == 422
    bad = payload()
    bad["replay"]["frames"] = []
    assert client.post("/api/coach/lesson", json=bad).status_code == 422


def test_cross_origin_write_denied_before_model_or_processing():
    r = client.post("/api/coach/lesson", json=payload(),
                    headers={"origin": "https://attacker.invalid"})
    assert r.status_code == 403
    assert "Cross-origin" in r.text


def test_replay_content_type_and_request_size_limits():
    r = client.post("/api/coach/lesson", content="hello", headers={"content-type": "text/plain"})
    assert r.status_code == 415
    # The limit is enforced before JSON parsing or model access.
    r = client.post("/api/coach/lesson", content=b"x" * (24 * 1024 * 1024 + 1),
                    headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_evidence_inspector_opens_real_sources_and_labels_derived_math_unverified():
    original = payload()
    original["replay"]["title"] = "PRIVATE_MATCH_WITH_A_REAL_ACCOUNT_NAME"
    refs = ["N3/E.focus.boost", "N1/E.focus.boost",
            "D.N1-N2.focus.boost", "H.1", "T.touch.1"]
    r = client.post("/api/coach/evidence", json={
        **original, "evidence_refs": refs,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema"] == "CoachEvidenceLookupV0"
    assert body["stage"] == "predecision"
    assert body["retrospective_exposed"] is False
    assert [x["id"] for x in body["records"]] == refs
    assert body["records"][0]["value"] == 10.0
    assert body["records"][1]["value"] == 60.0
    assert body["records"][2]["value"] == -40.0
    assert body["records"][2]["verification"] == "derived_value_needs_independent_math_check"
    assert body["records"][3]["established_cause"] is False
    assert "PRIVATE_MATCH_WITH_A_REAL_ACCOUNT_NAME" not in r.text
    lesson = client.post("/api/coach/lesson", json=original)
    assert lesson.status_code == 200
    assert body["stage1_packet_sha256"] == lesson.json()["validation"]["stage1_packet_sha256"]


def test_evidence_inspector_never_returns_future_or_nonexistent_citation():
    for ref in ("N3/R.goal_within_5s", "R.future_result", "N3/E.nonexistent"):
        r = client.post("/api/coach/evidence", json={
            **payload(), "evidence_refs": [ref],
        })
        assert r.status_code == 422
        assert "future_result" not in r.text
    r = client.post("/api/coach/evidence", json={
        **payload(), "evidence_refs": ["N3/E.focus.boost", "N3/E.focus.boost"],
    })
    assert r.status_code == 422
    r = client.post("/api/coach/evidence", json={
        **payload(), "mode": "model", "evidence_refs": ["N3/E.focus.boost"],
    })
    assert r.status_code == 422

