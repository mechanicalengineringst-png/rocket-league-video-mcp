"""Round 11: one decoded-replay request -> auditable shortlist and lesson previews.

The older web flow uploads the same potentially large replay to two endpoints,
then again for each case/lesson. This module composes existing verified source
contracts into one bounded local deterministic request. It DOES NOT choose a
best move, infer discrete decisions from snapshot deltas, or invoke a model.

Stage 1 lessons are generated from exact timestamps chosen by the audited
EpisodeCandidatesV0 selector. The two nodes are comparison observations rather
than proven prior decisions or a causal chain. Previews are optional and capped.
"""
from __future__ import annotations

import math
from typing import Any

from .coach_lesson import build_lesson_from_episode
from .episode_discovery import (
    DiscoveryError, MAX_CANDIDATES, discover_episode_candidates,
)
from .episode_evidence import EpisodeError, build_episode_evidence
from .stage1_packet import Stage1PacketError
from .tactical_options import TacticalOptionsError
from .coach_lesson import CoachDraftError

SCHEMA = "CoachReviewBundleV0"
MAX_PREVIEWS = 4


def _check_limit(value: int, lo: int, hi: int, name: str) -> None:
    if type(value) is not int or not lo <= value <= hi:
        raise ValueError(f"{name} must be an integer from {lo} to {hi}.")


def build_review_bundle(
    replay: dict[str, Any],
    player_id: str,
    *,
    max_candidates: int = 8,
    preview_count: int = 3,
    experimental_tactical_v1: bool = False,
    horizon_s: float | None = None,
) -> dict[str, Any]:
    """Return source-audited candidate list and at most 4 verified lessons.

    Results contain no replay metadata, raw frame arrays, player names, future
    goal events, cloud prompts, or fabricated source facts. A lesson failure
    becomes a per-candidate omission, never a fictitious fallback.
    """
    _check_limit(max_candidates, 1, MAX_CANDIDATES, "max_candidates")
    _check_limit(preview_count, 0, MAX_PREVIEWS, "preview_count")
    if type(experimental_tactical_v1) is not bool:
        raise ValueError("Experimental V1 must be a boolean.")
    if horizon_s is not None and (type(horizon_s) not in (float, int) or not math.isfinite(horizon_s)):
        raise ValueError("Discovery horizon must be finite.")

    discovered = discover_episode_candidates(
        replay, player_id, max_candidates=max_candidates, horizon_s=horizon_s,
    )
    rows = discovered["candidates"]
    # Rank review previews by observational change salience, NOT by predicted
    # mistakes or game outcome. The full candidate list remains chronological.
    priority = sorted(
        rows, key=lambda c: (-c["salience_score"], c["primary_t0"], c["candidate_id"]),
    )[:min(preview_count, len(rows))]
    prepared: list[dict[str, Any]] = []
    unavailable: list[dict[str, str]] = []
    for candidate in priority:
        try:
            ep = build_episode_evidence(
                replay, player_id, candidate["decision_times"],
                candidate["episode_start_s"], candidate["primary_t0"],
            )
            if ep["status"] == "abstain":
                unavailable.append({"candidate_id": candidate["candidate_id"],
                                    "reason_code": "insufficient_decision_time_evidence"})
                continue
            lesson = build_lesson_from_episode(
                ep, experimental_tactical_v1=experimental_tactical_v1,
            )
            if lesson.get("schema") != "CoachLessonV0" or lesson.get("stage") != "predecision":
                unavailable.append({"candidate_id": candidate["candidate_id"],
                                    "reason_code": "lesson_contract_unavailable"})
                continue
            # Fail closed if a future contract accidentally changes cutoff
            # times or begins returning non-deterministic conclusions.
            if (lesson.get("decision", {}).get("t0_s") != candidate["primary_t0"]
                    or lesson.get("mode") != "deterministic_baseline"
                    or lesson.get("validation", {}).get("future_outcomes_used") is not False
                    or lesson.get("validation", {}).get("semantic_tactical_accuracy_verified") is not False
                    or lesson.get("assessment", {}).get("grade") != "undetermined"):
                unavailable.append({"candidate_id": candidate["candidate_id"],
                                    "reason_code": "lesson_contract_unavailable"})
                continue
            if experimental_tactical_v1:
                v1 = lesson.get("experimental_decision_state_v1")
                if (not isinstance(v1, dict) or v1.get("schema") != "TacticalDecisionStateV1"
                        or v1.get("validation", {}).get("expert_validated") is not False):
                    unavailable.append({"candidate_id": candidate["candidate_id"],
                                        "reason_code": "experimental_comparison_unavailable"})
                    continue
            elif "experimental_decision_state_v1" in lesson:
                unavailable.append({"candidate_id": candidate["candidate_id"],
                                    "reason_code": "unexpected_experimental_inclusion"})
                continue
            prepared.append({
                "candidate_id": candidate["candidate_id"],
                "primary_t0": candidate["primary_t0"],
                "node_semantics": candidate["node_meaning"],
                "selection_reason": {
                    "signal": candidate["primary_signal"],
                    "source_refs": sorted({
                        ref for signal in candidate["signals"]
                        for ref in signal["evidence_refs"]
                    }),
                    "rule": "largest observed state change, not a decision-quality assessment",
                },
                "lesson": lesson,
            })
        except (EpisodeError, Stage1PacketError, TacticalOptionsError, CoachDraftError,
                DiscoveryError, ValueError, TypeError, KeyError, IndexError, OverflowError):
            # No raw internal messages or replay names escape to the caller.
            unavailable.append({"candidate_id": candidate["candidate_id"],
                                "reason_code": "lesson_evidence_unavailable"})

    prepared.sort(key=lambda row: (row["primary_t0"], row["candidate_id"]))
    unavailable.sort(key=lambda row: row["candidate_id"])
    if not rows:
        status = "no_supported_candidates"
    elif unavailable:
        status = "partial"
    else:
        status = "ok"
    return {
        "schema": SCHEMA,
        "mode": "local_deterministic",
        "stage": "predecision",
        "status": status,
        "candidate_count": len(rows),
        "preview_count": len(prepared),
        "preview_attempts": len(priority),
        "discovery_horizon_s": discovered["discovery_horizon_s"],
        "discovery": discovered,
        "previews": prepared,
        "unavailable_previews": unavailable,
        "selection": {
            "version": "review-bundle-selection/0.1",
            "preview_priority": "observational_salience_only",
            "not_a_rank_of_mistakes": True,
            "review_candidate_nodes_are_not_confirmed_decisions": True,
            "expert_validated": False,
            "experimental_v1_requested": experimental_tactical_v1,
            "model_called": False,
            "replay_uploaded_once_per_bundle": True,
        },
        "privacy": {
            "replay_retained": False,
            "raw_frames_returned": False,
            "raw_player_names_returned": False,
            "cloud_model_called": False,
        },
    }
