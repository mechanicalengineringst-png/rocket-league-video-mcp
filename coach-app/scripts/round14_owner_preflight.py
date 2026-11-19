"""Read-only, offline Round 14.5 owner preflight for Windows.

This checks *prerequisites*, never coaching merit, actual HTTP behavior,
WebGL pixels, identity mapping, native-game commands, or paid model access.

From coach-app:
    .venv\Scripts\python.exe -m scripts.round14_owner_preflight --replay "C:\path\match.replay"

No replay contents are loaded. No provider contacted. No environment-variable
values, usernames, replay filenames, or raw player IDs are printed.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Callable, Mapping

SCHEMA = "ReplayLabOwnerPreflightV0"
REQUIRED_MODULES = (
    "fastapi", "uvicorn", "httpx", "numpy", "pandas", "subtr_actor",
)
REQUIRED_FRONTEND = (
    "index.html", "app.js", "report-v2.js", "experimental-report.js",
    "coaching-experience.js", "model-coaching.js", "manual-review.js",
    "blind-review.js", "decision-lens.js",
)
REQUIRED_IDS = (
    "id=\"reportV2Panel\"", "id=\"reportV2Btn\"",
    "id=\"experimentalReportBtn\"", "id=\"lensManualReviewBtn\"",
    "id=\"blindStartBtn\"", "id=\"modelCoachConsent\"",
    "id=\"hdInlineFrame\"",
)
MAX_REPLAY_BYTES = 20 * 1024 * 1024


def preflight(
    root: Path,
    replay: Path | None = None,
    *,
    version: tuple[int, ...] | None = None,
    package_available: Callable[[str], bool] | None = None,
    env: Mapping[str, str] | None = None,
) -> dict:
    """Return sanitized statuses only. Injectability supports harmless CI tests."""
    root = Path(root)
    version = tuple(version or sys.version_info[:3])
    package_available = package_available or (
        lambda name: importlib.util.find_spec(name) is not None
    )
    env = os.environ if env is None else env

    python_ok = (3, 12) <= version[:2] < (4, 0)
    missing = [name for name in REQUIRED_MODULES if not package_available(name)]
    static = root / "coach_app" / "static"
    missing_front = [name for name in REQUIRED_FRONTEND if not (static / name).is_file()]
    html = (
        (static / "index.html").read_text(encoding="utf-8", errors="replace")
        if (static / "index.html").is_file() else ""
    )
    missing_controls = [name for name in REQUIRED_IDS if name not in html]
    hd = (static / "hd-player" / "index.html").is_file()
    replay_state = "not_selected"
    if replay is not None:
        try:
            valid = (replay.is_file() and replay.suffix.lower() == ".replay"
                     and 32 <= replay.stat().st_size <= MAX_REPLAY_BYTES)
            replay_state = (
                "candidate_present_not_decoded" if valid
                else "missing_or_unsupported_format_or_size"
            )
        except OSError:
            replay_state = "unreadable"

    enabled = env.get("REPLAY_LAB_ENABLE_COACH_MODEL") == "1"
    model_state = "disabled_no_model_call"
    if enabled:
        model_state = (
            "configured_by_environment_provider_unverified"
            if env.get("REPLAY_LAB_COACH_MODEL_URL") and env.get("REPLAY_LAB_COACH_MODEL_NAME")
            else "enabled_but_configuration_incomplete"
        )
    results = {
        "python": "supported" if python_ok else "requires_python_3_12_or_newer",
        "backend_dependencies": "installed" if not missing else "missing_packages",
        "frontend_assets": (
            "present_no_browser_verification"
            if not missing_front and not missing_controls else "incomplete"
        ),
        "hd_bundle": "present_no_webgl_verification" if hd else "not_built",
        "replay": replay_state,
        "external_model": model_state,
    }
    must = (
        python_ok and not missing and not missing_front and not missing_controls
        and hd and replay_state == "candidate_present_not_decoded"
    )
    next_steps = []
    if not python_ok:
        next_steps.append("Use Python 3.12 or newer, below Python 4.")
    if missing:
        next_steps.append("Install coach-app requirements in the active Python environment.")
    if missing_front or missing_controls:
        next_steps.append("Switch to the complete Round 14 integration branch.")
    if not hd:
        next_steps.append("Run the Windows launcher to install and build the current HD bundle.")
    if replay_state != "candidate_present_not_decoded":
        next_steps.append("Select a real 2v2 .replay within the supported file-size limit.")
    if must:
        next_steps.append("Open the running local app and verify the real player, 3D/map sync, V1/V2 reports and blind workflow.")
    return {
        "schema": SCHEMA,
        "checks": results,
        "missing_dependency_names": missing,
        "missing_static_asset_names": missing_front,
        "missing_control_names": missing_controls,
        "owner_browser_attempt": (
            "prerequisites_present_not_verified" if must
            else "blocked_or_setup_incomplete"
        ),
        "privacy": {
            "replay_filename_or_contents_disclosed": False,
            "environment_secret_values_disclosed": False,
            "outbound_requests": 0,
            "native_game_commands": 0,
        },
        "scope": [
            "This probe does not decode or inspect replay telemetry or confirm player identity.",
            "Present HTML/bundle does not prove working browser playback or correct camera.",
            "No V1/V2 tactical judgment, external LLM response, or GC accuracy is verified.",
            "A successful manual review pin does not run V2 on that pinned episode; V2 reports are match-level.",
        ],
        "next_steps": next_steps,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only, no-spend Replay Lab Windows test prerequisites"
    )
    parser.add_argument("--replay", type=Path, help="Original local 2v2 replay (name never printed)")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    result = preflight(root, replay=args.replay)
    print(json.dumps(result, indent=2))
    return 0 if result["owner_browser_attempt"] == "prerequisites_present_not_verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
