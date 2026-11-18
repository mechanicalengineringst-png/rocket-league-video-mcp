"""Regression tests: never copy a header-only/single-frame fake study video."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluation.clip_media_gate import (
    InvalidReviewVideo, validate_probe, verify_clip_media,
)


def probe(*, frames="180", duration="6.0", fps="30/1",
          width=1280, height=720, codec="vp8"):
    return {
        "streams": [{
            "codec_name": codec, "width": width, "height": height,
            "avg_frame_rate": fps, "nb_read_frames": frames,
        }],
        "format": {"duration": duration},
    }


def test_realistic_video_passes_but_is_not_declared_visually_blind():
    report = validate_probe(probe(), expected_duration_s=6.0)
    assert report["frame_count"] == 180
    assert report["avg_fps"] == 30
    assert report["duration_s"] == 6
    assert report["source_visual_review_required"] is True


def test_syntactically_valid_webm_with_one_dummy_frame_is_rejected():
    # Round 5 Antigravity's create_minimal_webm_clip advertises long duration
    # but embeds a single dummy VP8 SimpleBlock. Container headers do not
    # establish playable footage of the requested match decision.
    with pytest.raises(InvalidReviewVideo, match="Only 1 video frames"):
        validate_probe(probe(frames="1"), expected_duration_s=6.0)


def test_no_frame_count_is_never_treated_as_valid_zero_or_unknown():
    for val in ("N/A", None, "0", "-1", "10.5"):
        with pytest.raises(InvalidReviewVideo):
            validate_probe(probe(frames=val), expected_duration_s=6.0)


def test_duration_metadata_must_match_manifest_and_frame_count():
    with pytest.raises(InvalidReviewVideo, match="differs from requested"):
        validate_probe(probe(duration="3"), expected_duration_s=6.0)
    with pytest.raises(InvalidReviewVideo, match="Only 12 video frames"):
        validate_probe(probe(frames="12"), expected_duration_s=6.0)
    with pytest.raises(InvalidReviewVideo, match="measurable duration"):
        validate_probe(probe(duration="N/A"), expected_duration_s=6.0)


def test_missing_or_low_frame_rate_rejected():
    for rate in ("0/0", "3/1", "bad", "241/1", None):
        with pytest.raises(InvalidReviewVideo, match="frame rate"):
            validate_probe(probe(fps=rate), expected_duration_s=6.0)


def test_fake_metadata_and_bad_streams_rejected():
    with pytest.raises(InvalidReviewVideo, match="exactly one"):
        validate_probe({"streams": []}, expected_duration_s=6.0)
    with pytest.raises(InvalidReviewVideo, match="codec"):
        validate_probe(probe(codec="unknown"), expected_duration_s=6.0)
    with pytest.raises(InvalidReviewVideo, match="resolution"):
        validate_probe(probe(width=1), expected_duration_s=6.0)
    with pytest.raises(InvalidReviewVideo, match="Invalid expected"):
        validate_probe(probe(), expected_duration_s=float("nan"))


def test_ffprobe_absent_has_no_fallback_to_file_header(tmp_path, monkeypatch):
    path = tmp_path / "fake.webm"
    path.write_bytes(bytes.fromhex("1a45dfa3") + b"webm" * 30)
    monkeypatch.setattr("evaluation.clip_media_gate.shutil.which", lambda _: None)
    with pytest.raises(InvalidReviewVideo, match="ffprobe is required"):
        verify_clip_media(path, 6.0)


def test_verify_invokes_ffprobe_safely_and_uses_its_full_result(tmp_path, monkeypatch):
    path = tmp_path / "clip_001.webm"
    path.write_bytes(b"not verified by suffix")
    monkeypatch.setattr(
        "evaluation.clip_media_gate.shutil.which", lambda _: "/mock/ffprobe"
    )
    observed = []
    def run(args, **kwargs):
        observed.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=json.dumps(probe()))
    monkeypatch.setattr("evaluation.clip_media_gate.subprocess.run", run)
    report = verify_clip_media(path, 6.0)
    assert report["frame_count"] == 180
    args, kwargs = observed[0]
    assert args[0] == "/mock/ffprobe"
    assert args[-1] == str(path)
    assert "-count_frames" in args and "-select_streams" in args
    assert kwargs["timeout"] == 30
    assert kwargs["check"] is False


def test_ffprobe_errors_fail_closed(tmp_path, monkeypatch):
    path = tmp_path / "clip.webm"
    path.write_bytes(b"clip")
    monkeypatch.setattr(
        "evaluation.clip_media_gate.shutil.which", lambda _: "/mock/ffprobe"
    )
    for response in (
        SimpleNamespace(returncode=1, stdout=""),
        SimpleNamespace(returncode=0, stdout="{bad"),
    ):
        monkeypatch.setattr(
            "evaluation.clip_media_gate.subprocess.run",
            lambda *args, **kwargs: response
        )
        with pytest.raises(InvalidReviewVideo):
            verify_clip_media(path, 6.0)
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["ffprobe"], timeout=30)
    monkeypatch.setattr("evaluation.clip_media_gate.subprocess.run", timeout)
    with pytest.raises(InvalidReviewVideo, match="timeout"):
        verify_clip_media(path, 6.0)


def test_missing_clip_is_rejected_before_ffprobe_lookup(tmp_path):
    with pytest.raises(InvalidReviewVideo, match="missing"):
        verify_clip_media(tmp_path / "never-recorded.webm", 6.0)
