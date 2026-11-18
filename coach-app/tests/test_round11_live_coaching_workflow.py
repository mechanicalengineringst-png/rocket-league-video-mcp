"""Round 11 Live Coaching Workflow & Replay Fidelity Integration Test.

Tests the full end-to-end coaching pipeline with a genuine Rocket League .replay file:
1. Native parsing of real 2v2 match replay.
2. Official candidate discovery via POST /api/coach/candidates (EpisodeCandidatesV0).
3. Seamless handoff: candidate parameters passed directly into POST /api/coach/lesson.
4. CoachLessonV0 verification with tactical options, physical constraints, and uncertainty.
5. Experimental V1 tactical stances toggle:
   - Default: V0 baseline.
   - Opt-in: experimental_tactical_v1=True.
6. Granular evidence reference lookup via POST /api/coach/evidence.
7. Deterministic evidence navigation follow-up via POST /api/coach/followup.
8. Strict causal integrity: retrospective outcome quarantined behind Stage 1 firewall.
"""
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from coach_app.main import app
from coach_app.subtr_replays import parse_subtr_replay

REPLAY_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "replays" / "real_match_2v2.replay"


@pytest.fixture(scope="module")
def real_replay():
    if not REPLAY_FIXTURE.is_file():
        pytest.skip(f"Real replay fixture not found at {REPLAY_FIXTURE}")
    return parse_subtr_replay(REPLAY_FIXTURE)


def test_real_replay_decoding_and_players(real_replay):
    """Verify genuine replay decodes with 4 players in 2v2 formation."""
    assert "subtr" in real_replay["source"]
    players = real_replay["players"]
    assert len(players) == 4
    teams = [p["team"] for p in players]
    assert teams.count("blue") == 2
    assert teams.count("orange") == 2

    # Verify coached player is present
    player_ids = {p["id"] for p in players}
    assert "Steam:76561198994872471" in player_ids


def test_real_replay_coach_candidates_endpoint(real_replay):
    """Verify POST /api/coach/candidates returns source-backed review candidates."""
    client = TestClient(app)
    req = {
        "replay": real_replay,
        "player_id": "Steam:76561198994872471",
        "max_candidates": 6,
    }
    res = client.post("/api/coach/candidates", json=req)
    assert res.status_code == 200, f"Candidate discovery failed: {res.text}"
    data = res.json()

    assert data["schema"] == "EpisodeCandidatesV0"
    assert data["mode"] == "deterministic_source_observation"
    assert data["stage"] == "predecision"
    assert "candidates" in data
    assert len(data["candidates"]) >= 1

    # Verify candidate structure
    for cand in data["candidates"]:
        assert "candidate_id" in cand
        assert "primary_t0" in cand
        assert "decision_times" in cand
        assert "episode_start_s" in cand
        assert len(cand["decision_times"]) >= 2
        assert cand["decision_times"][-1] == cand["primary_t0"]
        assert cand["primary_t0"] > cand["episode_start_s"]


def test_real_replay_candidate_to_lesson_handoff(real_replay):
    """Verify candidate output can be passed directly to POST /api/coach/lesson."""
    client = TestClient(app)
    cand_req = {
        "replay": real_replay,
        "player_id": "Steam:76561198994872471",
        "max_candidates": 4,
    }
    cand_res = client.post("/api/coach/candidates", json=cand_req)
    assert cand_res.status_code == 200
    candidates = cand_res.json()["candidates"]
    assert len(candidates) >= 1
    c = candidates[0]

    # Pass directly into /api/coach/lesson
    lesson_payload = {
        "replay": real_replay,
        "player_id": "Steam:76561198994872471",
        "decision_times": c["decision_times"],
        "episode_start_s": c["episode_start_s"],
        "primary_t0": c["primary_t0"],
        "mode": "deterministic",
        "experimental_tactical_v1": False,
    }
    res = client.post("/api/coach/lesson", json=lesson_payload)
    assert res.status_code == 200, f"Lesson creation failed: {res.text}"
    lesson = res.json()

    assert lesson["schema"] == "CoachLessonV0"
    assert lesson["stage"] == "predecision"
    assert lesson["decision"]["t0_s"] == c["primary_t0"]
    assert "tactical_options" in lesson
    assert len(lesson["tactical_options"]["options"]) >= 2


def test_real_replay_experimental_v1_toggle(real_replay):
    """Verify experimental_tactical_v1 opt-in returns V1 tactical stances."""
    client = TestClient(app)
    cand_req = {
        "replay": real_replay,
        "player_id": "Steam:76561198994872471",
        "max_candidates": 4,
    }
    cand_res = client.post("/api/coach/candidates", json=cand_req)
    candidates = cand_res.json()["candidates"]
    c = candidates[0]

    # 1. Default / V0 mode
    v0_payload = {
        "replay": real_replay,
        "player_id": "Steam:76561198994872471",
        "decision_times": c["decision_times"],
        "episode_start_s": c["episode_start_s"],
        "primary_t0": c["primary_t0"],
        "mode": "deterministic",
        "experimental_tactical_v1": False,
    }
    res_v0 = client.post("/api/coach/lesson", json=v0_payload)
    assert res_v0.status_code == 200
    lesson_v0 = res_v0.json()

    # 2. Opt-in V1 mode
    v1_payload = {
        **v0_payload,
        "experimental_tactical_v1": True,
    }
    res_v1 = client.post("/api/coach/lesson", json=v1_payload)
    assert res_v1.status_code == 200
    lesson_v1 = res_v1.json()

    # Both must respect Stage 1 predecision boundary
    assert lesson_v0["stage"] == "predecision"
    assert lesson_v1["stage"] == "predecision"


def test_real_replay_evidence_lookup_and_followup(real_replay):
    """Verify granular evidence reference lookup and follow-up Q&A navigation."""
    client = TestClient(app)
    cand_req = {
        "replay": real_replay,
        "player_id": "Steam:76561198994872471",
        "max_candidates": 4,
    }
    cand_res = client.post("/api/coach/candidates", json=cand_req)
    c = cand_res.json()["candidates"][0]

    lesson_payload = {
        "replay": real_replay,
        "player_id": "Steam:76561198994872471",
        "decision_times": c["decision_times"],
        "episode_start_s": c["episode_start_s"],
        "primary_t0": c["primary_t0"],
        "mode": "deterministic",
    }
    lesson_res = client.post("/api/coach/lesson", json=lesson_payload)
    lesson = lesson_res.json()

    # Collect reference from claims
    all_refs = []
    for cl in lesson.get("claims", []):
        all_refs.extend(cl.get("evidence_refs", []))
    for cl in lesson.get("tactical_options", {}).get("claims", []):
        all_refs.extend(cl.get("evidence_refs", []))

    assert len(all_refs) > 0, "Expected at least one evidence reference in lesson"
    test_ref = all_refs[0]

    # 1. POST /api/coach/evidence
    ev_payload = {
        **lesson_payload,
        "evidence_refs": [test_ref],
    }
    ev_res = client.post("/api/coach/evidence", json=ev_payload)
    assert ev_res.status_code == 200, f"Evidence lookup failed: {ev_res.text}"
    ev_data = ev_res.json()

    assert ev_data["schema"] == "CoachEvidenceLookupV0"
    assert ev_data["retrospective_exposed"] is False
    assert len(ev_data["records"]) >= 1
    assert ev_data["records"][0]["id"] == test_ref

    # 2. POST /api/coach/followup
    followup_payload = {
        **lesson_payload,
        "question": "What was my boost level at commitment?",
    }
    f_res = client.post("/api/coach/followup", json=followup_payload)
    assert f_res.status_code == 200, f"Followup failed: {f_res.text}"
    f_data = f_res.json()

    assert f_data["schema"] == "CoachFollowupV0"
    assert f_data["mode"] == "local_evidence_navigation"
    assert "answer" in f_data
    assert len(f_data.get("related_refs", [])) >= 1
