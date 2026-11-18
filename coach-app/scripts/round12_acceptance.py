"""Round 12: privacy-safe local acceptance of a genuine Rocket League .replay.

Run from coach-app:
    python -m scripts.round12_acceptance --replay "C:/path/to/match.replay"
    python -m scripts.round12_acceptance --replay "..." --native-probe
    python -m scripts.round12_acceptance --replay "..." --model

No AI request, native-game command, private replay upload, settings edit or
persistent replay cache occurs unless the owner explicitly opts in. The
--native-probe flag only opens/closes a *loopback TCP connection*. This is not
a proof that Rocket League will accept LoadReplay/SeekReplay commands. Full
native command acceptance belongs to the separate native-companion workflow.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sys
from pathlib import Path
from typing import Any

from coach_app.coach_lesson import (
    CoachDraftError, build_lesson_from_episode, lookup_episode_evidence,
)
from coach_app.coach_model import CoachModelError, model_readiness, propose_coach_draft
from coach_app.episode_evidence import build_episode_evidence
from coach_app.episode_stage1 import build_stage1_episode_packet
from coach_app.replays import ReplayParseError, parse_replay_file
from coach_app.review_bundle import build_review_bundle

SCHEMA = "Round12LocalAcceptanceV0"
MAX_FILE_BYTES = 20 * 1024 * 1024


def native_port_probe(*, port: int = 49123) -> dict[str, Any]:
    """Never send a packet, modify config, or claim real-game commands work."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            pass
    except OSError:
        status = "loopback_port_unreachable"
    else:
        status = "loopback_port_reachable_commands_unverified"
    return {
        "status": status, "commands_sent": 0,
        "game_replay_load_verified": False,
        "game_seek_verified": False,
        "game_pov_verified": False,
        "game_speed_and_pause_verified": False,
        "capture_verified": False,
        "notes": "A TCP connection alone cannot establish that Rocket League is responding.",
    }


def viewer_readiness(static_root: Path | None = None) -> dict[str, Any]:
    """Asset/build preflight, not live rendering, FPS or camera verification."""
    if static_root is None:
        static_root = Path(__file__).resolve().parents[1] / "coach_app" / "static"
    html = static_root / "index.html"
    map_present = html.is_file() and (static_root / "app.js").is_file()
    high_fidelity = (static_root / "hd-player" / "index.html").is_file()
    old_geometry_mode = html.is_file() and "viewTab3d" in html.read_text(
        encoding="utf-8", errors="replace"
    )
    return {
        "tactical_2d": ("assets_present_browser_unverified"
                        if map_present else "missing_assets"),
        "high_fidelity": ("compiled_assets_present_browser_unverified"
                          if high_fidelity else "needs_local_hd_build"),
        "legacy_geometric_3d": ("still_in_current_branch_needs_removal"
                                if old_geometry_mode else "not_visible_in_html"),
        "hd_camera_and_texture_qa_verified": False,
        "hd_2d_sync_live_verified": False,
        "native_rocket_league_used_as_renderer": False,
    }


def _validated_2v2(replay: dict[str, Any]) -> bool:
    players = replay.get("players", [])
    if not isinstance(players, list) or len(players) != 4:
        return False
    return (sum(p.get("team") == "blue" for p in players if isinstance(p, dict)) == 2
            and sum(p.get("team") == "orange" for p in players if isinstance(p, dict)) == 2)


def _selected_player(replay: dict[str, Any], *, player_index: int | None) -> str | None:
    players = replay.get("players", [])
    if not isinstance(players, list):
        return None
    if player_index is not None:
        if player_index < 1 or player_index > len(players):
            return None
        return players[player_index - 1].get("id")
    # We do not guess a player to coach when kickoff-based identity is
    # unverified. The human may select a 1-based roster index explicitly.
    primary = replay.get("primaryPlayerId")
    if replay.get("playerMappingVerified") is False:
        return None
    if isinstance(primary, str) and any(p.get("id") == primary for p in players):
        return primary
    return None


def _source_check(
    replay: dict[str, Any], player_id: str, discovery: dict, previews: list,
) -> dict[str, Any]:
    candidate_map = {c["candidate_id"]: c for c in discovery["candidates"]}
    refs_checked = 0
    for row in previews:
        candidate = candidate_map[row["candidate_id"]]
        # Rebuild each selected episode from the ORIGINAL decoded data;
        # independently verify source lookups and exact lesson parity.
        episode = build_episode_evidence(
            replay, player_id, candidate["decision_times"],
            candidate["episode_start_s"], candidate["primary_t0"],
        )
        direct = build_lesson_from_episode(episode)
        # The acceptance runner only checks the stable/default V0 contract.
        if direct != row["lesson"]:
            return {"status": "lesson_mismatch", "source_refs_checked": refs_checked}
        refs = [r for claim in direct.get("claims", [])
                for r in claim.get("evidence_refs", [])]
        if not refs:
            refs = row["selection_reason"]["source_refs"]
        refs = list(dict.fromkeys(refs))[:20]
        if refs:
            lookup = lookup_episode_evidence(episode, refs)
            if lookup.get("schema") != "CoachEvidenceLookupV0":
                return {"status": "evidence_lookup_mismatch", "source_refs_checked": refs_checked}
            if [item.get("id") for item in lookup["records"]] != refs:
                return {"status": "evidence_lookup_mismatch", "source_refs_checked": refs_checked}
            refs_checked += len(refs)
    return {
        "status": "structural_checks_passed_not_semantic_accuracy",
        "source_refs_checked": refs_checked,
        "lesson_previews_checked": len(previews),
    }


def assess_decoded_replay(
    replay: dict[str, Any], *,
    player_index: int | None = None,
    native_probe: bool = False,
    model: bool = False,
    static_root: Path | None = None,
) -> dict[str, Any]:
    """Return only diagnostic counts and statuses, never names/IDs/raw frames."""
    players = replay.get("players", [])
    frames = replay.get("frames", [])
    raw_status = ("native_replay_decoded" if replay.get("source") == "native-replay"
                  else "fixture_or_other_source_not_native_acceptance")
    model_config = model_readiness()
    native = (native_port_probe() if native_probe else {
        "status": "not_requested",
        "commands_sent": 0, "game_replay_load_verified": False,
        "game_seek_verified": False, "game_pov_verified": False,
        "game_speed_and_pause_verified": False, "capture_verified": False,
    })
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "privacy": {
            "raw_replay_in_report": False,
            "player_names_or_ids_in_report": False,
            "replay_path_in_report": False,
            "model_credentials_in_report": False,
            "external_replay_upload": False,
        },
        "decoder": {
            "status": raw_status,
            "frame_count": len(frames) if isinstance(frames, list) else 0,
            "player_count": len(players) if isinstance(players, list) else 0,
            "full_game_timing_verified_against_native_client": False,
        },
        "viewer": viewer_readiness(static_root),
        "native_companion": native,
        "model_configuration": model_config,
        "model_test": {
            "status": "not_requested" if not model else "not_run",
            "model_called": False, "expert_validated": False,
        },
        "coaching": {
            "status": "not_run",
            "candidate_count": 0,
            "preview_count": 0,
            "strategic_accuracy_expert_verified": False,
        },
        "source_evidence": {"status": "not_run", "source_refs_checked": 0},
        "next_actions": [],
    }
    if not _validated_2v2(replay):
        report["coaching"]["status"] = "unsupported_mode_2v2_only"
        report["next_actions"].append("Try a valid four-player 2v2 replay for tactical coaching.")
        return report
    player_id = _selected_player(replay, player_index=player_index)
    if not player_id:
        report["coaching"]["status"] = "player_selection_required"
        report["next_actions"].append(
            "Confirm who is being coached; use --player-index 1-4 to select a specific roster slot.")
        return report
    try:
        bundle = build_review_bundle(replay, player_id, max_candidates=8, preview_count=3)
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        report["coaching"]["status"] = "discovery_failed"
        report["next_actions"].append("Inspect local parser/Stage 1 errors without publishing private data.")
        return report
    report["coaching"].update({
        "status": ("ready_for_human_review" if bundle["preview_count"] else
                   "source_backed_candidates_only" if bundle["candidate_count"] else
                   "no_usable_candidates"),
        "candidate_count": bundle["candidate_count"],
        "preview_count": bundle["preview_count"],
        "unavailable_preview_count": len(bundle["unavailable_previews"]),
        "candidate_semantics": "observational_attention_not_verified_decisions",
    })
    if not bundle["previews"]:
        report["next_actions"].append(
            "No complete lesson previews. Inspect a different replay or select a valid moment manually.")
        return report
    try:
        report["source_evidence"] = _source_check(
            replay, player_id, bundle["discovery"], bundle["previews"],
        )
    except (ValueError, TypeError, KeyError, IndexError, OverflowError):
        report["source_evidence"] = {
            "status": "source_verification_failed", "source_refs_checked": 0,
        }
        report["next_actions"].append("Source-evidence failure blocks trusting coaching results.")
        return report

    if not model:
        report["next_actions"].append(
            "AI model was not called. Use --model only after explicitly configuring an approved provider.")
        return report
    if model_config["status"] != "configured_unverified":
        report["model_test"]["status"] = "configuration_incomplete"
        report["next_actions"].append("Configure and explicitly enable the model endpoint before model testing.")
        return report
    try:
        candidate_by_id = {
            c["candidate_id"]: c for c in bundle["discovery"]["candidates"]
        }
        candidate = candidate_by_id[bundle["previews"][0]["candidate_id"]]
        episode = build_episode_evidence(
            replay, player_id, candidate["decision_times"],
            candidate["episode_start_s"], candidate["primary_t0"],
        )
        packet = build_stage1_episode_packet(episode)
        # SINGLE intentional model request, maximum. No automatic retries.
        report["model_test"]["model_called"] = True
        draft = asyncio.run(propose_coach_draft(packet))
        lesson = build_lesson_from_episode(episode, model_draft=draft)
        checked = lesson["validation"]
        report["model_test"].update({
            "status": ("validated_proposal_not_expert_verified"
                       if checked["accepted_model_claims"] else
                       "provider_responded_no_accepted_coaching_claims"),
            "model_called": True,
            "accepted_claim_count": checked["accepted_model_claims"],
            "rejected_claim_count": len(checked["rejected_model_claims"]),
            "expert_validated": False,
            "tactical_grade_is_hypothesis": True,
        })
    except (CoachModelError, CoachDraftError, ValueError, TypeError, KeyError,
            IndexError, OverflowError):
        report["model_test"].update({
            "status": "provider_or_validation_failed",
            "model_called": True, "expert_validated": False,
        })
        report["next_actions"].append(
            "The configured model failed or returned claims that could not be validated.")
    return report


def _write_report(report: dict, output: Path) -> None:
    # No names, paths, credentials, original evidence, or model text are serialized.
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay Lab Round 12 local-only acceptance checks")
    parser.add_argument("--replay", type=Path, required=True, help="Original native .replay file")
    parser.add_argument("--player-index", type=int, choices=[1, 2, 3, 4],
                        help="Explicit 1-based decoded roster slot to coach")
    parser.add_argument("--native-probe", action="store_true",
                        help="Only try read-only 127.0.0.1:49123 TCP connection; NO game commands")
    parser.add_argument("--model", action="store_true",
                        help="EXPLICIT outbound opt-in: send one sanitized Stage 1 episode to configured provider")
    parser.add_argument("--report", type=Path, help="Write privacy-safe results JSON")
    args = parser.parse_args(argv)
    try:
        if (not args.replay.is_file() or args.replay.suffix.lower() != ".replay"
                or not 32 <= args.replay.stat().st_size <= MAX_FILE_BYTES):
            raise ReplayParseError("Invalid replay size or extension.")
        replay = parse_replay_file(args.replay)
    except (ReplayParseError, OSError, ValueError, TypeError):
        print("Replay decode failed. Check the original .replay file and parser.", file=sys.stderr)
        return 2
    report = assess_decoded_replay(
        replay, player_index=args.player_index, native_probe=args.native_probe,
        model=args.model,
    )
    if args.report:
        try:
            _write_report(report, args.report)
        except OSError:
            print("Could not write private local acceptance summary.", file=sys.stderr)
            return 2
    # All output is sanitized diagnostics, not player names or replay details.
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["source_evidence"]["status"] == "structural_checks_passed_not_semantic_accuracy" else 1


if __name__ == "__main__":
    raise SystemExit(main())
