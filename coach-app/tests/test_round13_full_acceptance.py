"""Full Round 13 production API smoke using synthetic data (not ranked replay)."""
from __future__ import annotations

import copy

from scripts.round13_full_acceptance import (
    PASS, assess_full_coaching, manual_episode,
)
from tests.test_episode_evidence import episode_replay


def _fixture():
    r = copy.deepcopy(episode_replay())
    r["source"] = "synthetic"
    r["primaryPlayerId"] = "b1"
    r["playerMappingVerified"] = True
    return r


def test_all_local_coaching_routes_work_without_provider_or_native(monkeypatch, tmp_path):
    monkeypatch.delenv("REPLAY_LAB_ENABLE_COACH_MODEL", raising=False)
    result = assess_full_coaching(_fixture(), static_root=tmp_path)
    assert result["schema"] == "Round13FullCoachingAcceptanceV0"
    assert result["input"]["source"] == "fixture_or_unverified_source"
    assert result["checks"]["capabilities"] == PASS
    assert result["checks"]["model_readiness"] == "disabled_no_provider_contact"
    assert result["checks"]["review_bundle"] == PASS
    assert result["checks"]["deterministic_lesson"] == PASS
    assert result["checks"]["evidence_lookup"] == PASS
    assert result["checks"]["scene_relations"] == PASS
    assert result["checks"]["manual_moment"] == PASS
    assert result["checks"]["situation_report"] in (PASS, "valid_but_no_supported_findings")
    assert result["checks"]["optional_model"] == "not_requested_no_provider_contact"
    assert result["privacy"]["cloud_model_called_automatically"] is False
    assert result["privacy"]["native_game_commands_sent"] is False
    assert result["owner_gate"].startswith("api_structural_pass")
    assert result["hd"] == "needs_local_hd_build"
    assert result["frontend"] == "missing_frontend_assets"
    serialized = repr(result)
    assert "b1" not in serialized
    assert "synthetic-episode" not in serialized


def test_mapping_guard_never_guesses_player():
    r = _fixture()
    r["playerMappingVerified"] = False
    result = assess_full_coaching(r)
    assert result["owner_gate"] == "requires_explicit_player_selection"
    assert all(v == "not_run" for v in result["checks"].values())


def test_manual_replay_window_uses_recorded_past_and_refuses_short_replays():
    r = _fixture()
    m = manual_episode(r, "b1")
    assert m is not None
    assert m["decision_times"] == sorted(m["decision_times"])
    assert m["decision_times"][-1] == m["primary_t0"]
    assert m["episode_start_s"] <= m["decision_times"][0]
    r["frames"] = r["frames"][:100]
    assert manual_episode(r, "b1") is None


def test_not_supported_when_match_is_not_two_vs_two():
    r = _fixture()
    r["players"] = r["players"][:2]
    result = assess_full_coaching(r, player_index=1)
    assert result["owner_gate"] == "requires_valid_2v2_replay"
