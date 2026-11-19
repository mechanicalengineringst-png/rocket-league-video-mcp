"""Offline Round 14.5 preflight must never leak replay paths or provider secrets."""
from __future__ import annotations

import json

from scripts.round14_owner_preflight import (
    REQUIRED_FRONTEND, REQUIRED_IDS, preflight,
)


def fixture(root):
    static = root / "coach_app" / "static"
    static.mkdir(parents=True)
    for filename in REQUIRED_FRONTEND:
        (static / filename).write_text("asset", encoding="utf-8")
    (static / "index.html").write_text(
        " ".join(REQUIRED_IDS), encoding="utf-8"
    )
    bundle = static / "hd-player"
    bundle.mkdir()
    (bundle / "index.html").write_text("compiled", encoding="utf-8")
    rp = root / "PRIVATE_IDENTITY_AND_MATCH_NAME.replay"
    rp.write_bytes(b"x" * 64)
    return rp


def test_absent_assets_and_replay_block_owner_while_remaining_read_only(tmp_path):
    result = preflight(
        tmp_path, version=(3, 12, 1), package_available=lambda _: True, env={}
    )
    assert result["owner_browser_attempt"] == "blocked_or_setup_incomplete"
    assert result["checks"]["frontend_assets"] == "incomplete"
    assert result["checks"]["hd_bundle"] == "not_built"
    assert result["checks"]["replay"] == "not_selected"
    assert result["checks"]["external_model"] == "disabled_no_model_call"
    assert result["privacy"]["outbound_requests"] == 0
    assert result["privacy"]["native_game_commands"] == 0
    assert result["scope"]


def test_all_assets_present_is_prerequisite_only_not_a_coaching_pass(tmp_path):
    rp = fixture(tmp_path)
    result = preflight(
        tmp_path, replay=rp, version=(3, 12, 3),
        package_available=lambda _: True, env={}
    )
    assert result["owner_browser_attempt"] == "prerequisites_present_not_verified"
    assert result["checks"]["replay"] == "candidate_present_not_decoded"
    assert result["checks"]["frontend_assets"] == "present_no_browser_verification"
    assert result["checks"]["hd_bundle"] == "present_no_webgl_verification"
    assert result["checks"]["external_model"] == "disabled_no_model_call"
    assert any("does not decode" in line for line in result["scope"])
    output = json.dumps(result)
    assert "PRIVATE_IDENTITY_AND_MATCH_NAME" not in output
    assert str(tmp_path) not in output


def test_incomplete_model_configuration_prints_no_values(tmp_path):
    replay = fixture(tmp_path)
    secret = "PRIVATE_API_KEY_NEVER_PRINT"
    result = preflight(
        tmp_path, replay=replay, version=(3, 13, 0),
        package_available=lambda _: True,
        env={"REPLAY_LAB_ENABLE_COACH_MODEL": "1",
             "REPLAY_LAB_COACH_MODEL_URL": "https://secret.private.invalid/v1/chat/completions",
             "REPLAY_LAB_COACH_MODEL_API_KEY": secret}
    )
    assert result["checks"]["external_model"] == "enabled_but_configuration_incomplete"
    text = json.dumps(result)
    assert secret not in text
    assert "secret.private.invalid" not in text
    assert "PRIVATE_IDENTITY_AND_MATCH_NAME" not in text


def test_configured_model_is_never_treated_as_provider_tested(tmp_path):
    replay = fixture(tmp_path)
    result = preflight(
        tmp_path, replay=replay, version=(3, 12, 0),
        package_available=lambda _: True,
        env={"REPLAY_LAB_ENABLE_COACH_MODEL": "1",
             "REPLAY_LAB_COACH_MODEL_URL": "http://localhost:11434/v1/chat/completions",
             "REPLAY_LAB_COACH_MODEL_NAME": "private-model-name"}
    )
    assert result["checks"]["external_model"] == "configured_by_environment_provider_unverified"
    assert "private-model-name" not in json.dumps(result)
    assert result["privacy"]["outbound_requests"] == 0


def test_missing_dependencies_and_wrong_python_are_reported_without_importing(tmp_path):
    replay = fixture(tmp_path)
    result = preflight(
        tmp_path, replay=replay, version=(3, 11, 8),
        package_available=lambda name: name not in ("subtr_actor", "httpx"),
        env={}
    )
    assert result["checks"]["python"] == "requires_python_3_12_or_newer"
    assert result["checks"]["backend_dependencies"] == "missing_packages"
    assert result["missing_dependency_names"] == ["httpx", "subtr_actor"]
    assert result["owner_browser_attempt"] == "blocked_or_setup_incomplete"


def test_bad_size_bad_extension_and_absent_replay_cannot_pass(tmp_path):
    fixture(tmp_path)
    for bad in [
        tmp_path / "unknown.replay",
        tmp_path / "too_small.replay",
        tmp_path / "not_a_replay.json",
    ]:
        if bad.name == "too_small.replay":
            bad.write_bytes(b"x")
        elif bad.name == "not_a_replay.json":
            bad.write_bytes(b"x" * 64)
        result = preflight(
            tmp_path, replay=bad, version=(3, 12, 3),
            package_available=lambda _: True, env={}
        )
        assert result["owner_browser_attempt"] == "blocked_or_setup_incomplete"
        assert result["checks"]["replay"] in (
            "missing_or_unsupported_format_or_size", "unreadable"
        )
