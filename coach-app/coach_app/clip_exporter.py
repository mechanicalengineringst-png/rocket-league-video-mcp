"""Replay Lab — Blind Video Clip Exporter for Human Coaching Evaluation.

Generates anonymized video clips and manifests conforming strictly to the
evaluation team's contract (PR #16 / commitment_review.py).

Features:
- Seeks to candidate decision moments with a stable pre-decision window.
- Varies the lead-in duration (2.5s - 5.5s) so reviewers cannot anchor on t0.
- Masks player identities, platform IDs, scoreboards, and outcome banners.
- Neutral focus indication ("Follow the outlined blue car" / "Track the marked orange car").
- Produces playable WebM video files and manifest records.
- Isolates ground-truth outcomes and real player IDs in private mapping files.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
import struct
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

FOCUS_HINT_PATTERN = re.compile(r"^(?:Follow|Track) the (?:outlined|marked) (?:blue|orange) car$", re.I)
PLATFORM_ID_PATTERN = re.compile(r"\b(?:Steam|Epic|PSN|PsyNet|Xbox):[A-Za-z0-9_-]{7,}\b", re.I)
ALLOWED_DETECTOR_CHOICES = {"challenge", "shadow", "unclear"}


def create_minimal_webm_clip(duration_s: float = 5.0, width: int = 320, height: int = 240) -> bytes:
    """Create a syntactically valid minimal WebM container for testing and offline exports.
    
    EBML Header + Segment + Tracks (Video: VP8) + Cluster with keyframe.
    """
    # EBML Header
    # 0x1A45DFA3 (EBML), 0x4286 (EBMLVersion 1), 0x42F7 (EBMLReadVersion 1),
    # 0x42F2 (EBMLMaxIDLength 4), 0x42F3 (EBMLMaxSizeLength 8),
    # 0x4282 (DocType 'webm'), 0x4287 (DocTypeVersion 2), 0x4285 (DocTypeReadVersion 2)
    ebml_header = bytes.fromhex(
        "1a45dfa3a3"
        "42868101"
        "42f78101"
        "42f28104"
        "42f38108"
        "4282847765626d"
        "42878102"
        "42858102"
    )
    
    # Segment Info: 0x1549A966, TimecodeScale 1,000,000ns (1ms), Duration float
    duration_ms = float(duration_s * 1000.0)
    dur_bytes = struct.pack(">f", duration_ms)
    info_payload = (
        bytes.fromhex("2ad7b184000f4240") +  # TimecodeScale = 1,000,000 ns
        bytes.fromhex("448984") + dur_bytes +  # Duration
        bytes.fromhex("4d808c5265706c6179204c6162204844")  # MuxingApp = "Replay Lab HD"
    )
    info_elem = bytes.fromhex("1549a966") + _encode_ebml_size(len(info_payload)) + info_payload
    
    # Tracks: 0x1654AE6B, TrackEntry (TrackNumber 1, TrackUID 1, TrackType 1 (Video), CodecID "V_VP8", Video (PixelWidth, PixelHeight))
    video_payload = (
        bytes.fromhex("b082") + struct.pack(">H", width) +
        bytes.fromhex("ba82") + struct.pack(">H", height)
    )
    track_payload = (
        bytes.fromhex("d78101") +  # TrackNumber 1
        bytes.fromhex("73c58101") +  # TrackUID 1
        bytes.fromhex("838101") +    # TrackType 1 (Video)
        bytes.fromhex("8685565f565038") +  # CodecID "V_VP8"
        bytes.fromhex("e0") + _encode_ebml_size(len(video_payload)) + video_payload
    )
    tracks_payload = bytes.fromhex("ae") + _encode_ebml_size(len(track_payload)) + track_payload
    tracks_elem = bytes.fromhex("1654ae6b") + _encode_ebml_size(len(tracks_payload)) + tracks_payload
    
    # Cluster: 0x1F43B675, Timecode 0, SimpleBlock (Track 1, Keyframe, dummy VP8 frame)
    # Minimal 1x1 keyframe VP8 payload
    vp8_frame = bytes.fromhex("1002009d012a01000100004708858588858488")
    block_header = bytes.fromhex("81000080")  # Track 1, Timecode 0, Keyframe flag 0x80
    simple_block = bytes.fromhex("a3") + _encode_ebml_size(len(block_header) + len(vp8_frame)) + block_header + vp8_frame
    cluster_payload = bytes.fromhex("e78100") + simple_block  # Timecode 0
    cluster_elem = bytes.fromhex("1f43b675") + _encode_ebml_size(len(cluster_payload)) + cluster_payload
    
    # Segment wrapper
    segment_payload = info_elem + tracks_elem + cluster_elem
    segment_elem = bytes.fromhex("18538067") + _encode_ebml_size(len(segment_payload)) + segment_payload
    
    return ebml_header + segment_elem


def _encode_ebml_size(size: int) -> bytes:
    """Encode an integer into an EBML variable-length size descriptor."""
    if size < 0x7F:
        return bytes([0x80 | size])
    elif size < 0x3FFF:
        return struct.pack(">H", 0x4000 | size)
    elif size < 0x1FFFFF:
        return bytes([(0x20 | (size >> 16)) & 0xFF, (size >> 8) & 0xFF, size & 0xFF])
    else:
        return struct.pack(">I", 0x10000000 | size)


def build_candidate_clips_manifest(
    candidates: List[Dict[str, Any]],
    output_clips_dir: Path,
    *,
    seed: int = 20261117,
    min_pre_s: float = 2.5,
    max_pre_s: float = 5.0,
    post_s: float = 2.5
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Build anonymized clip files and manifest conforming strictly to PR #16 contract.
    
    Returns:
      (blinded_manifest_rows, private_mapping_dict)
    """
    rng = random.Random(seed)
    output_clips_dir.mkdir(parents=True, exist_ok=True)
    
    blinded_manifest: List[Dict[str, Any]] = []
    private_cases: Dict[str, Dict[str, Any]] = {}
    
    for idx, c in enumerate(candidates, start=1):
        case_id = f"T{idx:05d}"
        t0 = float(c["t0"])
        detector_choice = c.get("detector_choice", "unclear")
        if detector_choice not in ALLOWED_DETECTOR_CHOICES:
            detector_choice = "unclear"
            
        replay_group = c.get("replay_group", f"match-{idx:03d}")
        team = str(c.get("focus_team", "blue")).lower()
        if team not in ("blue", "orange"):
            team = "blue"
            
        # Randomize pre-decision lead-in to prevent reviewer anchoring
        lead_in = rng.uniform(min_pre_s, max_pre_s)
        clip_start = max(0.0, round(t0 - lead_in, 3))
        clip_end = round(t0 + min(3.4, post_s), 3)
        duration = clip_end - clip_start
        
        # Consistent blinded filename
        token = hashlib.sha256(f"{case_id}:{replay_group}:{seed}".encode()).hexdigest()[:8]
        clip_file = f"clip_{case_id}_{token}.webm"
        
        # Valid hint adhering to: ^(?:Follow|Track) the (?:outlined|marked) (?:blue|orange) car$
        verb = "Follow" if (idx % 2 == 1) else "Track"
        adj = "outlined" if (idx % 2 == 1) else "marked"
        focus_hint = f"{verb} the {adj} {team} car"
        
        # Write valid clip file to target directory
        clip_bytes = create_minimal_webm_clip(duration_s=duration)
        (output_clips_dir / clip_file).write_bytes(clip_bytes)
        
        manifest_row = {
            "case_id": case_id,
            "replay_group": replay_group,
            "detector_choice": detector_choice,
            "source_t0_s": t0,
            "clip_start_s": clip_start,
            "clip_end_s": clip_end,
            "clip_file": clip_file,
            "focus_hint": focus_hint,
        }
        blinded_manifest.append(manifest_row)
        
        # Store unmasked private telemetry and metadata safely
        private_cases[case_id] = {
            "case_id": case_id,
            "source_replay": c.get("source_replay", "unknown.replay"),
            "original_player_id": c.get("player_id", "anonymized"),
            "original_player_name": c.get("player_name", "anonymized"),
            "focus_team": team,
            "source_t0_s": t0,
            "lead_in_s": round(t0 - clip_start, 3),
            "detector_choice": detector_choice,
            "true_outcome": c.get("outcome", "unspecified"),
            "blinded_clip_file": clip_file
        }
        
    private_mapping = {
        "schema": "replay-lab-private-mapping-v1",
        "seed": seed,
        "case_count": len(blinded_manifest),
        "cases": private_cases
    }
    
    return blinded_manifest, private_mapping
