"""Round 10 Live Coaching Workflow & Replay Fidelity Integration Test.

Tests the full end-to-end coaching pipeline with a genuine Rocket League .replay file:
1. Native parsing of real 2v2 match replay.
2. Decision candidate discovery for coached player.
3. CoachLessonV0 construction with tactical options, physical constraints, and uncertainty.
4. Granular evidence reference lookup via POST /api/coach/evidence.
5. Deterministic evidence navigation follow-up via POST /api/coach/followup.
6. Verification that retrospective hindsight is strictly quarantined behind the Stage 1 firewall.
"""
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from coach_app.main import app
from coach_app.subtr_replays import parse_subtr_replay
from coach_app.decision_cases import extract_all_decision_cases

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

    # Check that Kanye is present
    player_ids = {p["id"] for p in players}
    assert "Steam:76561198994872471" in player_ids


def test_real_replay_candidate_discovery(real_replay):
    """Verify decision candidate discovery extracts genuine tactical commitment cases."""
    cases = extract_all_decision_cases(real_replay)
    assert len(cases) >= 10, f"Expected at least 10 decision cases, got {len(cases)}"

    kanye_cases = [c for c in cases if c.focus_player_id == "Steam:76561198994872471"]
    assert len(kanye_cases) >= 3, f"Expected multiple cases for coached player, got {len(kanye_cases)}"

    # Check case properties
    first_case = kanye_cases[0]
    assert first_case.t0 > 5.0
    assert first_case.situation_type in ("first_man_challenge", "kickoff_support", "last_man_defense")
    assert len(first_case.feasible_alternatives) >= 2


def test_real_replay_coaching_lesson_and_evidence_pipeline(real_replay):
    """Verify end-to-end coaching lesson, evidence lookup, and follow-up Q&A on live API."""
    client = TestClient(app)
    cases = extract_all_decision_cases(real_replay)
    kanye_cases = [c for c in cases if c.focus_player_id == "Steam:76561198994872471"]
    target_case = [c for c in kanye_cases if c.t0 >= 15.0][0]

    t0 = round(target_case.t0, 3)
    episode_start = round(t0 - 5.0, 3)
    context_t = round(t0 - 2.0, 3)
    decision_times = [context_t, t0]

    lesson_payload = {
        "replay": real_replay,
        "player_id": "Steam:76561198994872471",
        "decision_times": decision_times,
        "episode_start_s": episode_start,
        "primary_t0": t0,
        "mode": "deterministic"
    }

    # 1. POST /api/coach/lesson
    res = client.post("/api/coach/lesson", json=lesson_payload)
    assert res.status_code == 200, f"Lesson creation failed: {res.text}"
    lesson = res.json()

    assert lesson["schema"] == "CoachLessonV0"
    assert lesson["stage"] == "predecision"
    assert lesson["decision"]["t0_s"] == t0
    assert "tactical_options" in lesson

    tactics = lesson["tactical_options"]
    assert "options" in tactics
    assert len(tactics["options"]) >= 2

    # Verify physical feasibility and limit claims
    for opt in tactics["options"]:
        assert "action" in opt
        assert "physical_feasibility" in opt
        assert opt["physical_feasibility"] in ("yes", "no", "unknown", "constrained", "feasible", "infeasible")

    # 2. POST /api/coach/evidence (inspect citation)
    # Collect evidence references from claims
    all_refs = []
    for c in lesson.get("claims", []):
        all_refs.extend(c.get("evidence_refs", []))
    for c in tactics.get("claims", []):
        all_refs.extend(c.get("evidence_refs", []))

    assert len(all_refs) > 0, "Expected at least one evidence reference in lesson"
    test_ref = all_refs[0]

    evidence_payload = {
        **lesson_payload,
        "evidence_refs": [test_ref]
    }
    ev_res = client.post("/api/coach/evidence", json=evidence_payload)
    assert ev_res.status_code == 200, f"Evidence lookup failed: {ev_res.text}"
    ev_data = ev_res.json()

    assert ev_data["schema"] == "CoachEvidenceLookupV0"
    assert ev_data["retrospective_exposed"] is False
    assert len(ev_data["records"]) >= 1
    assert ev_data["records"][0]["id"] == test_ref

    # 3. POST /api/coach/followup (deterministic evidence navigation)
    followup_payload = {
        **lesson_payload,
        "question": "What was my boost level at commitment?"
    }
    f_res = client.post("/api/coach/followup", json=followup_payload)
    assert f_res.status_code == 200, f"Followup Q&A failed: {f_res.text}"
    f_data = f_res.json()

    assert f_data["schema"] == "CoachFollowupV0"
    assert f_data["mode"] == "local_evidence_navigation"
    assert "answer" in f_data
    assert len(f_data.get("related_refs", [])) >= 1
