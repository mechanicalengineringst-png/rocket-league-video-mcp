"""Round 10 opt-in V1 adapter integration gates, with stable V0 default."""
from __future__ import annotations

import copy

from fastapi.testclient import TestClient

from coach_app.main import app
from tests.test_coach_api_v0 import payload
from tests.test_tactical_options import FIRST_MAN, PRIMARY, START, TIMES, replay

client = TestClient(app)


def _live_pattern(cars=FIRST_MAN):
    return {"replay": replay(cars), "player_id": "b1",
            "decision_times": TIMES, "episode_start_s": START, "primary_t0": PRIMARY}


def test_default_lesson_is_unchanged_and_v1_is_explicit_opt_in():
    req = payload()
    old = client.post("/api/coach/lesson", json=req)
    assert old.status_code == 200, old.text
    stable = old.json()
    assert "experimental_decision_state_v1" not in stable
    experimental = client.post("/api/coach/lesson", json={
        **req, "experimental_tactical_v1": True
    })
    assert experimental.status_code == 200, experimental.text
    trial = experimental.json()
    assert trial["assessment"] == stable["assessment"]
    assert trial["mode"] == stable["mode"] == "deterministic_baseline"
    assert trial["tactical_options"] == stable["tactical_options"]
    assert trial["validation"] == stable["validation"]
    assert trial["claims"] == stable["claims"]
    assert trial["experimental_decision_state_v1"]["schema"] == "TacticalDecisionStateV1"
    assert trial["experimental_decision_state_v1"]["validation"]["model_called"] is False


def test_source_backed_v1_claims_and_hypotheses_not_expert_grades():
    req = _live_pattern()
    res = client.post("/api/coach/lesson", json={**req, "experimental_tactical_v1": True})
    assert res.status_code == 200, res.text
    lesson = res.json()
    v1 = lesson["experimental_decision_state_v1"]
    assert v1["node_id"] == lesson["decision"]["node_id"]
    assert v1["t0_s"] == lesson["decision"]["t0_s"]
    assert v1["status"] in ("ok", "partial")
    assert v1["analysis_type"] == "experimental_uncalibrated_tactical_hypotheses"
    assert v1["validation"]["semantic_tactical_accuracy_verified"] is False
    assert v1["validation"]["expert_validated"] is False
    assert v1["validation"]["best_move_established"] is False
    assert len(v1["actions"]) == 9
    assert {a["action"] for a in v1["actions"]} == {o["action"] for o in lesson["tactical_options"]["options"]}
    assert v1["claims"]
    assert all(ref.startswith(v1["node_id"] + "/E.") or ref.startswith(v1["node_id"] + "/C.")
               for claim in v1["claims"] for ref in claim["evidence_refs"])
    assert v1["validation"]["stage1_claims_checked"] == len(v1["claims"])
    assert all(not c["semantic_accuracy_verified"] for c in v1["claims"])
    assert all(not a["semantic_tactical_accuracy_verified"] for a in v1["actions"])


def test_v1_does_not_change_when_future_goal_or_frames_are_rewritten():
    req = _live_pattern()
    base = client.post("/api/coach/lesson", json={
        **req, "experimental_tactical_v1": True
    })
    assert base.status_code == 200, base.text
    future = copy.deepcopy(req)
    future["replay"]["events"].append({
        "type": "goal_context", "t": PRIMARY + 1.0, "scoringTeam": "orange",
        "scorerId": "o1"
    })
    for frame in future["replay"]["frames"]:
        if frame["t"] > PRIMARY:
            frame["ball"]["x"] = 1000
            frame["cars"]["b1"]["boost"] = 100
    follow = client.post("/api/coach/lesson", json={
        **future, "experimental_tactical_v1": True
    })
    assert follow.status_code == 200, follow.text
    assert base.json() == follow.json()


def test_missing_opponent_reach_abstains_integration_without_advice():
    cars = copy.deepcopy(FIRST_MAN)
    cars["o1"] = {**cars["o1"], "x": 4050.0, "z": 700.0}
    req = _live_pattern(cars)
    res = client.post("/api/coach/lesson", json={
        **req, "experimental_tactical_v1": True
    })
    assert res.status_code == 200, res.text
    v1 = res.json()["experimental_decision_state_v1"]
    assert v1["status"] == "abstain"
    assert v1["actions"] == []
    assert v1["claims"] == []
    assert v1["branches"] == []
    assert v1["validation"]["expert_validated"] is False


def test_model_requests_cannot_mix_experimental_v1_into_model_prompt(monkeypatch):
    calls = []
    async def no_call(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("A model was unexpectedly called.")
    from coach_app import coach_api
    monkeypatch.setattr(coach_api, "propose_coach_draft", no_call)
    res = client.post("/api/coach/lesson", json={
        **payload(), "mode": "model", "experimental_tactical_v1": True
    })
    assert res.status_code == 422
    assert calls == []


def test_experimental_v1_is_not_silently_enabled_in_capabilities():
    data = client.get("/api/coach/capabilities").json()
    assert data["experimental_decision_state_v1"] == "explicit_opt_in_deterministic_only"
    assert data["experimental_v1_expert_validated"] is False
    assert data["experimental_v1_default_enabled"] is False


def test_v1_rejects_tampered_claim_references(monkeypatch):
    from coach_app import decision_state_v1
    true_analyze = decision_state_v1.analyze_decision_state
    def forged(packet, **kwargs):
        out = true_analyze(packet, **kwargs)
        assert out["claims"]
        out["claims"][0]["cited_evidence_ids"] = ["E.made_up_source"]
        return out
    monkeypatch.setattr(decision_state_v1, "analyze_decision_state", forged)
    res = client.post("/api/coach/lesson", json={
        **_live_pattern(), "experimental_tactical_v1": True
    })
    assert res.status_code == 422
    assert "made_up_source" not in res.text


def test_no_change_to_followup_or_evidence_api_when_v1_is_requested():
    base = payload()
    old = client.post("/api/coach/followup", json={
        **base, "question": "Could my teammate cover?"
    })
    new = client.post("/api/coach/followup", json={
        **base, "question": "Could my teammate cover?", "experimental_tactical_v1": True
    })
    assert old.status_code == new.status_code == 200
    assert old.json() == new.json()
