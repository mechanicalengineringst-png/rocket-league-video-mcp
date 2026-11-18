"""Round 12C owner-selected missed-moment review API acceptance.

A manual moment is an observational EpisodeEvidenceV0 input, not evidence
that the user made a mistake. These are synthetic replay fixtures and don't
establish tactical quality. No actual model provider is invoked.
"""
from __future__ import annotations

import copy

from fastapi.testclient import TestClient

from coach_app.main import app
from tests.test_episode_evidence import episode_replay


client = TestClient(app)
PRIMARY = 10.033
START = 3.033
TIMES = [5.667, 8.067, PRIMARY]


def request(replay=None):
    r = replay or episode_replay()
    r["source"] = "native-replay"  # synthetic fixture with a source tag
    return {
        "replay": r,
        "player_id": "b1",
        "decision_times": TIMES,
        "episode_start_s": START,
        "primary_t0": PRIMARY,
        "mode": "deterministic",
        "experimental_tactical_v1": False,
    }


def test_manual_moment_local_endpoint_produces_real_evidence_lesson():
    res = client.post("/api/coach/lesson", json=request())
    assert res.status_code == 200, res.text
    result = res.json()
    assert result["schema"] == "CoachLessonV0"
    assert result["stage"] == "predecision"
    assert result["mode"] == "deterministic_baseline"
    assert result["decision"]["node_id"] == "N3"
    assert result["decision"]["t0_s"] == PRIMARY
    assert result["decision"]["episode_start_s"] == START
    assert [n["t0_s"] for n in result["decision"]["other_decisions"]] == TIMES[:2]
    assert result["validation"]["accepted_model_claims"] == 0
    assert result["validation"]["future_outcomes_used"] is False
    assert result["validation"]["semantic_tactical_accuracy_verified"] is False


def test_manual_predecision_evidence_independent_of_all_future_events():
    base = episode_replay()
    modified = copy.deepcopy(base)
    for frame in modified["frames"]:
        if frame["t"] > PRIMARY:
            frame["ball"]["x"] = -4000
            frame["ball"]["y"] = 4900
            frame["cars"]["b1"]["boost"] = 0
    modified["events"] = [e for e in modified["events"] if e["t"] <= PRIMARY] + [
        {"type": "touch", "t": 10.5, "playerId": "b2"},
        {"type": "goal_context", "t": 11.0, "scorerId": "b2"},
    ]
    a = client.post("/api/coach/lesson", json=request(base))
    b = client.post("/api/coach/lesson", json=request(modified))
    assert a.status_code == b.status_code == 200
    left, right = a.json(), b.json()
    assert left["validation"]["stage1_packet_sha256"] == right["validation"]["stage1_packet_sha256"]
    assert left["claims"] == right["claims"]
    assert left["assessment"] == right["assessment"]
    assert left["tactical_options"] == right["tactical_options"]


def test_manual_source_evidence_lookups_still_never_call_model():
    r = client.post("/api/coach/evidence", json={
        **request(), "evidence_refs": ["N3/E.focus.boost", "N3/E.focus.position"],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema"] == "CoachEvidenceLookupV0"
    assert body["retrospective_exposed"] is False
    assert [x["id"] for x in body["records"]] == [
        "N3/E.focus.boost", "N3/E.focus.position",
    ]
    assert all(x.get("source_time_s") is None or x["source_time_s"] <= PRIMARY
               for x in body["records"])
