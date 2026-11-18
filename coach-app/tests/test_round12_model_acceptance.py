"""Round 12: real loopback HTTP model transport and no-spend acceptance tests.

The local stub is NOT an AI model, nor proof of tactical accuracy. It proves
that an actual HTTP server can receive a sanitized Stage 1 packet and that
the resulting proposal passes through the production API evidence gate.
"""
from __future__ import annotations

import copy
import json
import socket
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from coach_app import coach_model
from coach_app.main import app
from scripts import round12_acceptance as acceptance
from tests.test_episode_evidence import episode_replay

client = TestClient(app)


def episode_request():
    replay = copy.deepcopy(episode_replay())
    replay["title"] = "PRIVATE_MATCH_SHOULD_NOT_LEAK"
    return {
        "replay": replay, "player_id": "b1",
        "decision_times": [2.0, 6.0, 10.0],
        "episode_start_s": 0.5, "primary_t0": 10.0,
    }


def coaching_draft():
    return {
        "schema": "CoachDraftV0",
        "assessment": "tradeoff",
        "claims": [{
            "claim_id": "real-http-c1",
            "node_id": "N3",
            "section": "tactical_context",
            "epistemic_type": "TACTICAL_INFERENCE",
            "temporal_scope": "PRE_DECISION",
            "cited_evidence_ids": ["N3/E.focus.boost"],
            "predicate_checks": [],
            "text": "Delaying could preserve coverage, depending on teammate recovery.",
        }],
    }


@contextmanager
def local_model_stub(*, fenced=False, malformed=False):
    captured = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass  # never leak model prompts in CI output
        def do_POST(self):
            count = int(self.headers.get("content-length", "0"))
            request = json.loads(self.rfile.read(count).decode("utf-8"))
            captured.append(request)
            message = request["messages"][1]["content"]
            packet = json.loads(message.split("\n", 1)[1])
            assert packet["stage1_episode"]["schema"] == "Stage1EpisodePacketV0"
            assert packet["tactical_options"]["schema"] == "CoachTacticalContextV0"
            assert "PRIVATE_MATCH_SHOULD_NOT_LEAK" not in message
            assert "retrospective" not in packet["stage1_episode"]
            assert packet["stage1_episode"].get("retrospective_present") is False
            assert "selection" not in message
            assert "REPLAY_LAB_COACH_MODEL_API_KEY" not in message
            text = json.dumps(coaching_draft())
            if fenced:
                text = "```json\n" + text + "\n```"
            if malformed:
                text = text + "\nUnsupported provider postscript"
            response = json.dumps({"choices": [{"message": {"content": text}}]}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], captured
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _configure_local(monkeypatch, port, *, json_mode=False):
    monkeypatch.setenv("REPLAY_LAB_ENABLE_COACH_MODEL", "1")
    monkeypatch.setenv("REPLAY_LAB_COACH_MODEL_URL", f"http://127.0.0.1:{port}/v1/chat/completions")
    monkeypatch.setenv("REPLAY_LAB_COACH_MODEL_NAME", "mock-transport-not-ai")
    monkeypatch.delenv("REPLAY_LAB_COACH_MODEL_API_KEY", raising=False)
    if json_mode:
        monkeypatch.setenv("REPLAY_LAB_COACH_MODEL_JSON_MODE", "1")
    else:
        monkeypatch.delenv("REPLAY_LAB_COACH_MODEL_JSON_MODE", raising=False)


@pytest.mark.parametrize("enable,url,name,key,expected", [
    ("0", "", "", "", "disabled"),
    ("1", "", "", "", "needs_configuration"),
    ("1", "http://public.example/v1/chat/completions", "test", "", "invalid_configuration"),
    ("1", "https://safe.example/v1/chat/completions", "test", "", "needs_configuration"),
    ("1", "https://safe.example/v1/chat/completions", "test", "SENSITIVE_TEST_ONLY", "configured_unverified"),
    ("1", "http://127.0.0.1:11434/v1/chat/completions", "local-test", "", "configured_unverified"),
])
def test_readonly_model_readiness_never_leaks_secrets_or_contacts_provider(
    monkeypatch, enable, url, name, key, expected,
):
    monkeypatch.setenv("REPLAY_LAB_ENABLE_COACH_MODEL", enable)
    monkeypatch.setenv("REPLAY_LAB_COACH_MODEL_URL", url)
    monkeypatch.setenv("REPLAY_LAB_COACH_MODEL_NAME", name)
    monkeypatch.setenv("REPLAY_LAB_COACH_MODEL_API_KEY", key)
    # A fake server isn't needed: readiness performs no HTTP request.
    r = client.get("/api/coach/model-readiness")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema"] == "CoachModelReadinessV0"
    assert body["status"] == expected
    assert body["outbound_request_made"] is False
    assert body["provider_connection_tested"] is False
    assert body["tactical_accuracy_expert_validated"] is False
    assert body["configuration_complete"] == (expected == "configured_unverified")
    assert url not in r.text if url else True
    assert key not in r.text if key else True
    cap = client.get("/api/coach/capabilities").json()
    assert cap["model_configuration_status"] == expected


@pytest.mark.parametrize("raw,accepted", [
    ('{"schema":"CoachDraftV0"}', True),
    ('  ```json\n{"schema":"CoachDraftV0"}\n```  ', True),
    ('```\n{"schema":"CoachDraftV0"}\n```', True),
    ('{"schema":"CoachDraftV0"}\nThis is safe', False),
    ('```json\n{"schema":"CoachDraftV0"}\n```\nextra', False),
    ('{}{}', False),
    ('[{"schema":"CoachDraftV0"}]', False),
    ('I recommend defensive positioning.', False),
    ('', False),
])
def test_strict_provider_json_wrapping(raw, accepted):
    if accepted:
        assert coach_model._parse_model_content(raw)["schema"] == "CoachDraftV0"
    else:
        with pytest.raises(coach_model.CoachModelError):
            coach_model._parse_model_content(raw)


def test_real_local_http_model_contract_with_strict_json_mode(monkeypatch):
    with local_model_stub(fenced=True) as (port, calls):
        _configure_local(monkeypatch, port, json_mode=True)
        ready = client.get("/api/coach/model-readiness").json()
        assert ready["status"] == "configured_unverified"
        lesson = client.post("/api/coach/lesson", json={**episode_request(), "mode": "model"})
        assert lesson.status_code == 200, lesson.text
        body = lesson.json()
        assert len(calls) == 1
        assert calls[0]["response_format"] == {"type": "json_object"}
        assert calls[0]["model"] == "mock-transport-not-ai"
        assert "PRIVATE_MATCH_SHOULD_NOT_LEAK" not in json.dumps(calls)
        assert body["mode"] == "model_proposal"
        assert body["validation"]["accepted_model_claims"] == 1
        assert body["assessment"]["grade"] == "tradeoff"
        assert body["validation"]["semantic_tactical_accuracy_verified"] is False
        assert body["validation"]["future_outcomes_used"] is False
        assert "PRIVATE_MATCH_SHOULD_NOT_LEAK" not in lesson.text


def test_real_local_http_invalid_output_fails_closed_not_fake_ai(monkeypatch):
    with local_model_stub(malformed=True) as (port, calls):
        _configure_local(monkeypatch, port)
        response = client.post("/api/coach/lesson", json={**episode_request(), "mode": "model"})
        assert len(calls) == 1
        assert response.status_code == 502
        assert "Unsupported provider postscript" not in response.text
        assert "PRIVATE_MATCH_SHOULD_NOT_LEAK" not in response.text


def test_no_unauthorized_ai_call_even_with_valid_local_provider(monkeypatch):
    with local_model_stub() as (port, calls):
        _configure_local(monkeypatch, port)
        response = client.post("/api/coach/lesson", json=episode_request())
        assert response.status_code == 200
        assert response.json()["mode"] == "deterministic_baseline"
        assert calls == []


def test_acceptance_harness_checks_structural_evidence_without_ai_or_native(monkeypatch, tmp_path):
    monkeypatch.delenv("REPLAY_LAB_ENABLE_COACH_MODEL", raising=False)
    data = copy.deepcopy(episode_replay())
    data["source"] = "native-replay"  # synthetic fixture with simulated source tag; NOT real acceptance
    data["primaryPlayerId"] = "b1"
    data["playerMappingVerified"] = True
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>2D Map</html>", encoding="utf-8")
    (static / "app.js").write_text("", encoding="utf-8")
    result = acceptance.assess_decoded_replay(data, static_root=static)
    assert result["schema"] == acceptance.SCHEMA
    assert result["coaching"]["status"] == "ready_for_human_review"
    assert result["coaching"]["candidate_count"] > 0
    assert result["coaching"]["preview_count"] > 0
    assert result["source_evidence"]["status"] == "structural_checks_passed_not_semantic_accuracy"
    assert result["source_evidence"]["source_refs_checked"] > 0
    assert result["model_test"]["status"] == "not_requested"
    assert result["model_test"]["model_called"] is False
    assert result["native_companion"]["status"] == "not_requested"
    assert result["native_companion"]["commands_sent"] == 0
    assert result["viewer"]["high_fidelity"] == "needs_local_hd_build"
    assert result["viewer"]["tactical_2d"] == "assets_present_browser_unverified"
    serialized = json.dumps(result)
    assert "b1" not in serialized
    assert "PRIVATE_MATCH_SHOULD_NOT_LEAK" not in serialized
    assert "primaryPlayerId" not in serialized


def test_acceptance_player_mapping_requires_explicit_confirmation():
    data = copy.deepcopy(episode_replay())
    data["primaryPlayerId"] = "b1"
    data["playerMappingVerified"] = False
    no_guess = acceptance.assess_decoded_replay(data)
    assert no_guess["coaching"]["status"] == "player_selection_required"
    selected = acceptance.assess_decoded_replay(data, player_index=1)
    assert selected["coaching"]["status"] == "ready_for_human_review"


def test_acceptance_1v1_parse_does_not_fake_two_v_two_coaching():
    data = copy.deepcopy(episode_replay())
    data["players"] = data["players"][:2]
    result = acceptance.assess_decoded_replay(data, player_index=1)
    assert result["coaching"]["status"] == "unsupported_mode_2v2_only"
    assert result["source_evidence"]["status"] == "not_run"


def test_port_probe_is_connection_only_with_no_commands(monkeypatch):
    class Connection:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    calls = []
    def open_socket(target, timeout):
        calls.append((target, timeout))
        return Connection()
    monkeypatch.setattr(acceptance.socket, "create_connection", open_socket)
    report = acceptance.native_port_probe()
    assert calls == [(("127.0.0.1", 49123), 0.4)]
    assert report["status"] == "loopback_port_reachable_commands_unverified"
    assert report["commands_sent"] == 0
    assert report["game_replay_load_verified"] is False


def test_cli_report_cannot_include_local_file_or_replay_names(monkeypatch, tmp_path, capsys):
    data = copy.deepcopy(episode_replay())
    data["primaryPlayerId"] = "b1"
    data["playerMappingVerified"] = True
    data["source"] = "native-replay"  # substitute fixture; no native parser success claim
    monkeypatch.setattr(acceptance, "parse_replay_file", lambda _: data)
    replay = tmp_path / "MY_PRIVATE_ACCOUNT_REPLAY.replay"
    replay.write_bytes(b"X" * 64)
    output = tmp_path / "test-results.json"
    exit_code = acceptance.main(["--replay", str(replay), "--report", str(output)])
    assert exit_code == 0
    text = output.read_text(encoding="utf-8")
    assert "MY_PRIVATE_ACCOUNT_REPLAY" not in text
    assert "PRIVATE_MATCH_SHOULD_NOT_LEAK" not in text
    assert "b1" not in text
    assert "MY_PRIVATE_ACCOUNT_REPLAY" not in capsys.readouterr().out
