"""Round 13: all local coaching APIs against one decoded Rocket League 2v2.

Privacy-safe status/counts only. This is NOT a real-browser / GC-level quality test.
No model call unless --model is explicitly passed; no native-game commands.
Run from coach-app:
  python -m scripts.round13_full_acceptance --replay MATCH.replay --player-index 1
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from coach_app.main import app
from coach_app.replays import ReplayParseError, parse_replay_file
from scripts.round12_acceptance import (
    MAX_FILE_BYTES, _selected_player, _validated_2v2, viewer_readiness,
)

SCHEMA = "Round13FullCoachingAcceptanceV0"
PASS = "api_contract_passed_browser_and_tactics_unverified"


def manual_episode(replay: dict, player_id: str) -> dict | None:
    """Use recorded, fresh frames to exercise a user-selected local moment."""
    frames = replay.get("frames", [])
    if not isinstance(frames, list) or len(frames) < 10:
        return None
    times = [frame.get("t") for frame in frames]
    if any(not isinstance(t, (int, float)) or not math.isfinite(t) for t in times):
        return None
    if times != sorted(times) or times[-1] - times[0] < 8:
        return None
    first, last = times[0], times[-1]
    t0 = min(last - .5, max(first + 7.1, first + (last - first) * .5))
    selected = []
    for wanted in (t0 - 6, t0 - 3, t0):
        index = bisect.bisect_right(times, wanted) - 1
        if index < 0 or wanted - times[index] > .2:
            return None
        frame = frames[index]
        if not isinstance(frame.get("ball"), dict):
            return None
        if not isinstance(frame.get("cars", {}).get(player_id), dict):
            return None
        selected.append(round(times[index], 3))
    if len(set(selected)) != 3 or selected[-1] - selected[0] < 5:
        return None
    return {
        "replay": replay, "player_id": player_id,
        "decision_times": selected,
        "episode_start_s": round(max(first, selected[-1] - 7), 3),
        "primary_t0": selected[-1], "mode": "deterministic",
        "experimental_tactical_v1": False,
    }


def post(client: TestClient, path: str, payload: dict) -> dict:
    response = client.post(path, json=payload)
    if response.status_code != 200:
        raise ValueError("Non-200 backend response")
    result = response.json()
    if not isinstance(result, dict):
        raise ValueError("Unexpected backend response")
    return result


def frontend_readiness(root: Path) -> str:
    expected = ("coaching-experience.js", "model-coaching.js", "manual-review.js",
                "blind-review.js", "experimental-report.js", "decision-lens.js",
                "hd-bridge.js")
    ids = ("coachingExperienceContainer", "experimentalReportBtn", "lensManualReviewBtn",
           "blindStartBtn", "blindLockBtn", "modelCoachConsent", "modelCoachRunBtn",
           "hdInlineFrame", "viewTabSplit")
    html_path = root / "index.html"
    if not html_path.is_file() or any(not (root / f).is_file() for f in expected):
        return "missing_frontend_assets"
    html = html_path.read_text(encoding="utf-8")
    if any('id="' + key + '"' not in html for key in ids):
        return "missing_frontend_controls"
    return "assets_present_browser_interaction_unverified"


def assess_full_coaching(
    replay: dict, *, player_index: int | None = None, model: bool = False,
    static_root: Path | None = None,
) -> dict:
    """Never include private replay data, player IDs, credentials or model text."""
    root = static_root or Path(__file__).resolve().parents[1] / "coach_app" / "static"
    report = {
        "schema": SCHEMA,
        "input": {
            "source": ("native_replay_decoded" if replay.get("source") == "native-replay"
                       else "fixture_or_unverified_source"),
            "players": len(replay.get("players", [])),
            "frames": len(replay.get("frames", [])),
        },
        "privacy": {
            "raw_replay_or_player_ids_returned": False,
            "file_path_or_credentials_returned": False,
            "cloud_model_called_automatically": False,
            "native_game_commands_sent": False,
        },
        "frontend": frontend_readiness(root),
        "hd": viewer_readiness(root)["high_fidelity"],
        "checks": {k: "not_run" for k in (
            "capabilities", "model_readiness", "review_bundle", "deterministic_lesson",
            "evidence_lookup", "scene_relations", "manual_moment", "situation_report",
            "optional_model",
        )},
        "counts": {
            "automatic_candidates": 0, "lesson_previews": 0,
            "source_evidence_records": 0, "situation_findings": 0,
            "situation_withheld": 0, "model_accepted_claims": 0,
        },
        "owner_gate": "blocked",
        "limitations": [
            "Backend API success does not prove browser playback, camera or native game.",
            "Source-checked tactical proposals are not expert verified.",
            "A provider response does not prove useful high-rank coaching.",
        ],
    }
    if not _validated_2v2(replay):
        report["owner_gate"] = "requires_valid_2v2_replay"
        return report
    focus = _selected_player(replay, player_index=player_index)
    if not focus:
        report["owner_gate"] = "requires_explicit_player_selection"
        return report

    episode = None
    with TestClient(app) as client:
        try:
            r = client.get("/api/coach/capabilities")
            cap = r.json()
            assert r.status_code == 200
            assert cap["single_request_review_bundle"] == "CoachReviewBundleV0"
            assert cap["coaching_report_v1_invokes_model"] is False
            assert cap["coaching_report_v1_expert_validated"] is False
            assert cap["model_requires_request_opt_in"] is True
            report["checks"]["capabilities"] = PASS
        except (ValueError, AssertionError, KeyError, TypeError):
            report["checks"]["capabilities"] = "failed_contract"

        try:
            r = client.get("/api/coach/model-readiness")
            ready = r.json()
            assert r.status_code == 200
            assert ready["schema"] == "CoachModelReadinessV0"
            assert ready["outbound_request_made"] is False
            assert ready["provider_connection_tested"] is False
            report["checks"]["model_readiness"] = ready["status"] + "_no_provider_contact"
        except (ValueError, AssertionError, KeyError, TypeError):
            report["checks"]["model_readiness"] = "failed_contract"

        try:
            bundle = post(client, "/api/coach/review-bundle", {
                "replay": replay, "player_id": focus, "max_candidates": 6,
                "preview_count": 3, "experimental_tactical_v1": False,
            })
            assert bundle["schema"] == "CoachReviewBundleV0"
            assert bundle["stage"] == "predecision"
            assert bundle["mode"] == "local_deterministic"
            report["counts"]["automatic_candidates"] = bundle["candidate_count"]
            report["counts"]["lesson_previews"] = bundle["preview_count"]
            report["checks"]["review_bundle"] = (
                PASS if bundle["previews"] else "valid_but_no_preview_available"
            )
            if bundle["previews"]:
                preview = bundle["previews"][0]
                candidates = {
                    row["candidate_id"]: row for row in bundle["discovery"]["candidates"]
                }
                candidate = candidates[preview["candidate_id"]]
                assert preview["primary_t0"] == candidate["primary_t0"]
                episode = {
                    "replay": replay, "player_id": focus,
                    "decision_times": candidate["decision_times"],
                    "episode_start_s": candidate["episode_start_s"],
                    "primary_t0": candidate["primary_t0"], "mode": "deterministic",
                    "experimental_tactical_v1": False,
                }
                lesson = post(client, "/api/coach/lesson", episode)
                assert lesson == preview["lesson"]
                assert lesson["schema"] == "CoachLessonV0"
                assert lesson["mode"] == "deterministic_baseline"
                assert lesson["stage"] == "predecision"
                assert lesson["validation"]["future_outcomes_used"] is False
                assert lesson["validation"]["semantic_tactical_accuracy_verified"] is False
                report["checks"]["deterministic_lesson"] = PASS

                refs = [ref for claim in lesson.get("claims", [])
                        for ref in claim.get("evidence_refs", [])]
                if not refs:
                    refs = preview["selection_reason"]["source_refs"]
                refs = list(dict.fromkeys(refs))[:8]
                if refs:
                    evidence = post(client, "/api/coach/evidence",
                                    {**episode, "evidence_refs": refs})
                    assert evidence["schema"] == "CoachEvidenceLookupV0"
                    assert evidence["retrospective_exposed"] is False
                    assert [x["id"] for x in evidence["records"]] == refs
                    report["counts"]["source_evidence_records"] = len(refs)
                    report["checks"]["evidence_lookup"] = PASS
                else:
                    report["checks"]["evidence_lookup"] = "no_evidence_refs_available"

                relations = post(client, "/api/coach/scene-relations", episode)
                assert relations["schema"] == "RelationalInvariantsV0"
                assert relations["stage"] == "predecision"
                assert relations["uses_future"] is False
                assert relations["expert_calibrated"] is False
                report["checks"]["scene_relations"] = PASS
        except (ValueError, AssertionError, KeyError, TypeError, IndexError):
            if report["checks"]["review_bundle"] == "not_run":
                report["checks"]["review_bundle"] = "failed_contract"
            if episode is not None and report["checks"]["deterministic_lesson"] == "not_run":
                report["checks"]["deterministic_lesson"] = "failed_contract"

        try:
            manual = manual_episode(replay, focus)
            if manual is None:
                report["checks"]["manual_moment"] = "no_fresh_manual_window_available"
            else:
                lesson = post(client, "/api/coach/lesson", manual)
                assert lesson["schema"] == "CoachLessonV0"
                assert lesson["mode"] == "deterministic_baseline"
                assert lesson["decision"]["t0_s"] == manual["primary_t0"]
                assert lesson["validation"]["future_outcomes_used"] is False
                report["checks"]["manual_moment"] = PASS
        except (ValueError, AssertionError, KeyError, TypeError, IndexError):
            report["checks"]["manual_moment"] = "failed_contract"

        try:
            tactical = post(client, "/api/coach/coaching-report-v1", {
                "replay": replay, "player_id": focus, "max_findings": 6,
                "include_retrospective": True,
            })
            assert tactical["schema"] == "CoachingReportV1"
            assert tactical["experimental"] is True
            assert tactical["expert_validated"] is False
            assert tactical["method"]["model_called"] is False
            assert tactical["method"]["ranking_uses_future"] is False
            assert tactical["method"]["retrospective_included"] is True
            assert len(tactical["findings"]) <= 6
            report["counts"]["situation_findings"] = len(tactical["findings"])
            report["counts"]["situation_withheld"] = sum(
                f.get("status") == "withheld_validation_failed"
                for f in tactical["findings"]
            )
            for finding in tactical["findings"]:
                if finding.get("status") == "ok":
                    val = finding["validation"]
                    assert val["future_frames_used"] is False
                    assert val["semantic_tactical_accuracy_verified"] is False
                    assert val["untraced_numbers"] == []
                    assert val["rejected_claims"] == []
            report["checks"]["situation_report"] = (
                PASS if tactical["findings"] else "valid_but_no_supported_findings"
            )
        except (ValueError, AssertionError, KeyError, TypeError, IndexError):
            report["checks"]["situation_report"] = "failed_contract"

        if not model:
            report["checks"]["optional_model"] = "not_requested_no_provider_contact"
        elif episode is None:
            report["checks"]["optional_model"] = "no_primary_episode"
        elif report["checks"]["model_readiness"] != "configured_unverified_no_provider_contact":
            report["checks"]["optional_model"] = "provider_not_configured"
        else:
            try:
                ai = post(client, "/api/coach/lesson", {**episode, "mode": "model"})
                assert ai["schema"] == "CoachLessonV0"
                assert ai["mode"] == "model_proposal"
                assert ai["validation"]["future_outcomes_used"] is False
                assert ai["validation"]["semantic_tactical_accuracy_verified"] is False
                count = ai["validation"]["accepted_model_claims"]
                report["counts"]["model_accepted_claims"] = count
                report["checks"]["optional_model"] = (
                    "provider_responded_source_checked_not_expert_validated"
                    if count else "provider_responded_no_accepted_claims"
                )
            except (ValueError, AssertionError, KeyError, TypeError, IndexError):
                report["checks"]["optional_model"] = "provider_or_claim_validation_failed"

    needed = ("capabilities", "review_bundle", "deterministic_lesson",
              "evidence_lookup", "scene_relations", "manual_moment")
    okay = all(report["checks"][k] == PASS for k in needed)
    okay &= report["checks"]["situation_report"] in (
        PASS, "valid_but_no_supported_findings",
    )
    okay &= report["checks"]["model_readiness"] not in ("not_run", "failed_contract")
    if model:
        okay &= report["checks"]["optional_model"].startswith("provider_responded")
    report["owner_gate"] = (
        "api_structural_pass_browser_and_expert_unverified"
        if okay else "blocked_inspect_failed_or_unavailable_checks"
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay Lab full local coaching API gate")
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--player-index", type=int, choices=(1, 2, 3, 4))
    parser.add_argument("--report", type=Path, help="Save sanitized status/counts JSON")
    parser.add_argument("--model", action="store_true",
                        help="EXPLICITLY authorize ONE provider call, only if configured")
    args = parser.parse_args(argv)
    try:
        if not args.replay.is_file() or args.replay.suffix.lower() != ".replay":
            raise ReplayParseError("Invalid replay")
        if not 32 <= args.replay.stat().st_size <= MAX_FILE_BYTES:
            raise ReplayParseError("Replay size invalid")
        result = assess_full_coaching(
            parse_replay_file(args.replay), player_index=args.player_index,
            model=args.model,
        )
    except (ReplayParseError, OSError, ValueError, TypeError):
        print("Replay decode failed; nothing is accepted.", file=sys.stderr)
        return 2
    if args.report:
        try:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        except OSError:
            print("Could not write sanitized report.", file=sys.stderr)
            return 2
    print(json.dumps(result, indent=2))
    return 0 if result["owner_gate"].startswith("api_structural_pass") else 1


if __name__ == "__main__":
    raise SystemExit(main())
