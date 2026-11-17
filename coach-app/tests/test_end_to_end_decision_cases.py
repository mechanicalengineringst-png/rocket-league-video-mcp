"""Genuine End-to-End Test: Native Replay Upload -> /api/replays -> /api/decision-cases.

Verifies the full pipeline:
Native .replay upload -> subtr-actor decode -> rich normalized events preserved ->
POST /api/decision-cases -> kickoff, first-man, and last-man defense cases all extracted
and evaluated with strict pre-decision evidence integrity.
"""
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from coach_app.main import app
from coach_app.decision_cases import PRE_DECISION_CONTEXT_ALLOWLIST
from tests.test_decision_cases_real_replay import get_replay_dir

client = TestClient(app)


def test_end_to_end_native_replay_decision_cases():
    replay_dir = get_replay_dir()
    replay_path = replay_dir / "23A661D44DBC5964B0718DBC5F956A33.replay"
    if not replay_path.exists():
        pytest.skip(f"Real replay fixture not found at {replay_path}. Set RL_REPLAY_DIR to run end-to-end tests.")

    replay_bytes = replay_path.read_bytes()
    assert len(replay_bytes) > 100_000

    # Step 1: Upload native .replay via POST /api/replays
    upload_resp = client.post(
        "/api/replays",
        content=replay_bytes,
        headers={
            "content-type": "application/octet-stream",
            "x-replay-name": "23A661D44DBC5964B0718DBC5F956A33.replay",
        },
    )
    assert upload_resp.status_code == 200, f"Upload failed: {upload_resp.text}"
    upload_data = upload_resp.json()
    assert "replay" in upload_data
    replay_json = upload_data["replay"]

    # Verify normalized events exist and contain rich metadata
    events = replay_json.get("events", [])
    assert len(events) > 50

    event_types = {e.get("type") for e in events}
    assert "kickoff" in event_types
    assert "fifty_fifty" in event_types
    assert "depth_role" in event_types

    # Step 2: Call opt-in POST /api/decision-cases with the live uploaded replay payload
    cases_resp = client.post(
        "/api/decision-cases",
        json={
            "replay": replay_json,
            "evaluate": True,
        },
    )
    assert cases_resp.status_code == 200, f"Decision cases failed: {cases_resp.text}"
    cases_data = cases_resp.json()
    assert cases_data.get("mode") == "opt_in_decision_engine"
    cases = cases_data.get("cases", [])
    assert len(cases) > 0, "No decision cases extracted from live uploaded replay!"

    # Step 3: Verify all three tactical situation families are produced
    situations = {c.get("situation_type") for c in cases}
    assert "kickoff_support" in situations, f"Missing kickoff_support in {situations}"
    assert "first_man_challenge" in situations, f"Missing first_man_challenge in {situations}"
    assert "last_man_defense" in situations, f"Missing last_man_defense in {situations}"

    # Step 4: Strict temporal integrity and evidence allowlist audit
    for c in cases:
        t0 = c["decision_time_s"]
        sit = c["situation_type"]
        allowed_keys = PRE_DECISION_CONTEXT_ALLOWLIST.get(sit, set())

        # Verify tactical_context has zero hindsight leakage
        for k, v in c.get("tactical_context", {}).items():
            assert k in allowed_keys, f"Disallowed key {k} leaked into tactical_context for {sit}"
            if "time" in k.lower() and isinstance(v, (int, float)) and not isinstance(v, bool):
                assert v <= t0, f"Timestamp {v} > t0 {t0} leaked in key {k}"

        # Verify pre_decision_facts timestamps <= t0
        for fact in c.get("pre_decision_facts", []):
            assert fact["event_time_s"] <= t0 + 0.001, f"Future fact {fact['key']} at {fact['event_time_s']} > t0 {t0}"

        # Verify evaluation citations
        if "evaluation" in c and c["evaluation"]:
            ev = c["evaluation"]
            assert ev["assessment"] in ("tactical_hypothesis", "tactical_risk", "tradeoff", "constrained_situation", "sound_positioning", "abstain", "unverified_coverage_hypothesis")
            admissible_fact_keys = {f["key"] for f in c.get("pre_decision_facts", [])}
            for cited in ev.get("cited_evidence", []):
                assert cited in admissible_fact_keys, f"Citation {cited} not in admissible pre-decision facts!"
