import json
import re
import tempfile
from pathlib import Path

import pytest

from coach_app.clip_exporter import (
    ALLOWED_DETECTOR_CHOICES,
    FOCUS_HINT_PATTERN,
    PLATFORM_ID_PATTERN,
    build_candidate_clips_manifest,
    create_minimal_webm_clip,
)


def test_minimal_webm_header_validity():
    webm_bytes = create_minimal_webm_clip(duration_s=4.5)
    assert len(webm_bytes) > 60
    # EBML magic header: 0x1A 0x45 0xDF 0xA3
    assert webm_bytes[:4] == bytes.fromhex("1a45dfa3")
    assert b"webm" in webm_bytes
    assert b"V_VP8" in webm_bytes


def test_manifest_contract_and_blinding():
    with tempfile.TemporaryDirectory() as tmp_dir:
        clips_dir = Path(tmp_dir) / "clips"
        
        candidates = [
            {
                "t0": 15.42,
                "detector_choice": "challenge",
                "replay_group": "group-match-a",
                "focus_team": "blue",
                "player_id": "Steam:76561198000000001",
                "player_name": "ProPlayer1",
                "source_replay": "matchA.replay",
                "outcome": "won_50"
            },
            {
                "t0": 42.10,
                "detector_choice": "shadow",
                "replay_group": "group-match-a",
                "focus_team": "orange",
                "player_id": "Epic:12345678abcdef",
                "player_name": "ProPlayer2",
                "source_replay": "matchA.replay",
                "outcome": "saved_shot"
            },
            {
                "t0": 88.50,
                "detector_choice": "unclear",
                "replay_group": "group-match-b",
                "focus_team": "blue",
                "player_id": "Xbox:9988776655",
                "player_name": "GamerTag",
                "source_replay": "matchB.replay",
                "outcome": "rotate_back"
            },
            {
                "t0": 120.00,
                "detector_choice": "challenge",
                "replay_group": "group-match-c",
                "focus_team": "orange",
                "player_id": "PSN:abcdef123456",
                "player_name": "ConsoleChamp",
                "source_replay": "matchC.replay",
                "outcome": "dribble"
            }
        ]
        
        manifest, private_map = build_candidate_clips_manifest(candidates, clips_dir, seed=42)
        
        assert len(manifest) == 4
        assert private_map["case_count"] == 4
        
        allowed_fields = {
            "case_id", "replay_group", "detector_choice", "source_t0_s",
            "clip_start_s", "clip_end_s", "clip_file", "focus_hint",
        }
        
        lead_ins = []
        for row in manifest:
            # Field exact match
            assert set(row.keys()) == allowed_fields
            
            # Case ID format
            assert re.match(r"^T[0-9]{5}$", row["case_id"])
            
            # Detector choice
            assert row["detector_choice"] in ALLOWED_DETECTOR_CHOICES
            
            # Time interval assertions matching PR #16 commitment_review.py
            t0 = row["source_t0_s"]
            start = row["clip_start_s"]
            end = row["clip_end_s"]
            assert 0 <= start <= t0 <= end
            assert 0 < end - start <= 30
            assert end - t0 <= 3.5
            
            lead_in = t0 - start
            lead_ins.append(lead_in)
            
            # Filename
            assert row["clip_file"].endswith(".webm")
            assert "/" not in row["clip_file"] and "\\" not in row["clip_file"]
            
            # File on disk exists
            file_on_disk = clips_dir / row["clip_file"]
            assert file_on_disk.is_file()
            assert file_on_disk.stat().st_size > 0
            
            # Focus hint validation
            hint = row["focus_hint"]
            assert FOCUS_HINT_PATTERN.match(hint)
            assert not PLATFORM_ID_PATTERN.search(hint)
            assert "ProPlayer" not in hint
            assert "GamerTag" not in hint
            
        # Verify lead-ins vary across clips (reviewer cannot anchor on t0)
        assert len(set(round(l, 2) for l in lead_ins)) > 1
        
        # Verify private map contains true identities and outcome mappings
        for cid, priv in private_map["cases"].items():
            assert cid in [m["case_id"] for m in manifest]
            assert "Steam:" in priv["original_player_id"] or "Epic:" in priv["original_player_id"] or "Xbox:" in priv["original_player_id"] or "PSN:" in priv["original_player_id"]
            assert priv["true_outcome"] in ("won_50", "saved_shot", "rotate_back", "dribble")
            
        # Ensure blinded manifest does NOT leak any private platform IDs or player names
        manifest_json = json.dumps(manifest)
        assert "ProPlayer" not in manifest_json
        assert "Steam:" not in manifest_json
        assert "Epic:" not in manifest_json
        assert "won_50" not in manifest_json
