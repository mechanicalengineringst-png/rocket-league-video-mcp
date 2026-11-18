"""Fail-closed, local video-structure gate for blinded commitment clips.

Do NOT mistake container magic, a filename extension, or manifest metadata for
real gameplay video. ffprobe must observe sufficient actual video frames and
duration in every source file before evaluation.commitment_review copies it.

This is a *necessary*, not sufficient, validation gate. It cannot establish
that the footage depicts Rocket League, that t0 aligns with the rendered
action, that player IDs are masked, or that no goal/outcome is visible.
Those properties require independent visual/timecode review.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any


class InvalidReviewVideo(ValueError):
    """Source clip is not a verifiably usable time-aligned video."""


def _duration(value: Any) -> float | None:
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _fps(value: Any) -> float | None:
    if not isinstance(value, str) or not value or value == "0/0":
        return None
    try:
        n = float(Fraction(value))
    except (ValueError, TypeError, ZeroDivisionError):
        return None
    return n if math.isfinite(n) and n > 0 else None


def validate_probe(
    data: dict[str, Any],
    *,
    expected_duration_s: float,
    min_fps: float = 15.0,
) -> dict[str, Any]:
    """Check decoded frame count and duration, not only media metadata/magic.

    ffprobe -count_frames reports the number of VIDEO frames read by its
    demuxer. It does not prove decoded image content was human-viewable, so
    reviewers must additionally play/inspect the clip.
    """
    if not isinstance(data, dict):
        raise InvalidReviewVideo("ffprobe did not return an object")
    if not isinstance(expected_duration_s, (float, int)) or isinstance(expected_duration_s, bool) \
            or not math.isfinite(expected_duration_s) or expected_duration_s <= 0:
        raise InvalidReviewVideo("Invalid expected duration")

    streams = data.get("streams")
    if not isinstance(streams, list) or len(streams) != 1:
        raise InvalidReviewVideo("Expected exactly one probed video stream")
    video = streams[0]
    if not isinstance(video, dict):
        raise InvalidReviewVideo("Invalid probed video stream")
    codec = video.get("codec_name")
    if not isinstance(codec, str) or codec.lower() in ("", "unknown", "none"):
        raise InvalidReviewVideo("No valid video codec detected")
    w, h = video.get("width"), video.get("height")
    if type(w) is not int or type(h) is not int or w < 160 or h < 90:
        raise InvalidReviewVideo("Video resolution is missing or unusably small")
    fps = _fps(video.get("avg_frame_rate"))
    if fps is None or fps < min_fps or fps > 240:
        raise InvalidReviewVideo("Video frame rate is unavailable or too low")
    try:
        frame_count = int(video.get("nb_read_frames"))
    except (ValueError, TypeError):
        raise InvalidReviewVideo("ffprobe could not count video frames")
    if frame_count < 1 or str(frame_count) != str(video.get("nb_read_frames")):
        raise InvalidReviewVideo("Invalid video frame count")

    info = data.get("format")
    dur = _duration(info.get("duration")) if isinstance(info, dict) else None
    if dur is None:
        dur = _duration(video.get("duration"))
    if dur is None:
        raise InvalidReviewVideo("Video has no measurable duration")

    # A 2-8s commitment clip may have a few hundredths of a second of
    # container-level tail rounding. Do not accept a one-frame placeholder
    # with a plausible 8s duration metadata field.
    allowed_gap = max(0.25, expected_duration_s * 0.04)
    if abs(dur - expected_duration_s) > allowed_gap:
        raise InvalidReviewVideo(
            f"Video duration {dur:.3f}s differs from requested "
            f"{expected_duration_s:.3f}s by more than {allowed_gap:.3f}s"
        )
    if frame_count < max(16, math.floor(expected_duration_s * fps * 0.80)):
        raise InvalidReviewVideo(
            f"Only {frame_count} video frames found for a "
            f"{expected_duration_s:.2f}s clip at {fps:.1f} FPS"
        )
    # Avoid personally identifying source paths in public report outputs.
    return {
        "duration_s": round(dur, 4),
        "frame_count": frame_count,
        "avg_fps": round(fps, 3),
        "resolution": [w, h],
        "codec_name": codec,
        "source_visual_review_required": True,
    }


def verify_clip_media(
    path: Path,
    expected_duration_s: float,
    *,
    ffprobe_executable: str = "ffprobe",
) -> dict[str, Any]:
    """Require FFprobe frame-count verification before copying a private clip."""
    if not isinstance(path, Path):
        path = Path(path)
    if not path.is_file():
        raise InvalidReviewVideo(f"Source clip missing: {path.name}")
    probe = shutil.which(ffprobe_executable)
    if probe is None:
        raise InvalidReviewVideo(
            "ffprobe is required to prepare human-review clips; install FFmpeg "
            "and verify 'ffprobe' is on PATH. No header-only fallback is allowed."
        )
    args = [
        probe, "-v", "error", "-count_frames", "-select_streams", "v:0",
        "-show_entries",
        "stream=codec_name,width,height,avg_frame_rate,nb_read_frames,duration:format=duration",
        "-of", "json", str(path),
    ]
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, check=False, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InvalidReviewVideo("ffprobe failed or exceeded its timeout") from exc
    if result.returncode != 0:
        raise InvalidReviewVideo(
            f"Cannot inspect the source video ({path.name}); ffprobe returned an error"
        )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise InvalidReviewVideo("ffprobe returned invalid JSON") from exc
    return validate_probe(data, expected_duration_s=expected_duration_s)
