"""Round 9 coach endpoints — manual episode, validated Stage 1 and opt-in AI.

Antigravity owns frontend UI; backend owns these contracts. These endpoints do
NOT call a model unless the user requests mode="model" AND the local server
is explicitly configured to allow it.
"""
from __future__ import annotations

import math
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, field_validator

from .coach_lesson import CoachDraftError, answer_evidence_followup, build_lesson_from_episode, lookup_episode_evidence
from .coach_model import CoachModelDisabled, CoachModelError, model_enabled, model_readiness, propose_coach_draft
from .episode_evidence import EpisodeError, build_episode_evidence
from .episode_discovery import DiscoveryError, discover_episode_candidates
from .episode_stage1 import build_stage1_episode_packet
from .stage1_packet import Stage1PacketError
from .review_bundle import build_review_bundle
from .relational_invariants import build_relational_invariants

router = APIRouter(tags=["coaching"])
MAX_JSON_BYTES = 24 * 1024 * 1024
MAX_FRAMES = 30000
MAX_EVENTS = 30000


class EpisodeLessonRequest(BaseModel):
    replay: dict[str, Any]
    player_id: str = Field(min_length=1, max_length=256)
    decision_times: list[float] = Field(min_length=2, max_length=4)
    episode_start_s: float
    primary_t0: float
    mode: Literal["deterministic", "model"] = "deterministic"
    experimental_tactical_v1: bool = False

    @field_validator("replay")
    @classmethod
    def validate_replay(cls, r: dict[str, Any]) -> dict[str, Any]:
        frames, players = r.get("frames"), r.get("players")
        events = r.get("events", [])
        if not isinstance(frames, list) or not 1 <= len(frames) <= MAX_FRAMES:
            raise ValueError("Expected 1-30000 decoded replay frames.")
        if not isinstance(players, list) or len(players) != 4:
            raise ValueError("Round 9 lessons require a four-player 2v2 replay.")
        if not isinstance(events, list) or len(events) > MAX_EVENTS:
            raise ValueError("Replay event count exceeds supported limit.")
        teams = [p.get("team") for p in players if isinstance(p, dict)]
        if len(teams) != 4 or teams.count("blue") != 2 or teams.count("orange") != 2:
            raise ValueError("Expected exactly two players on each team.")
        if any(not isinstance(p.get("id"), str) or not p["id"] or len(p["id"]) > 256
               for p in players):
            raise ValueError("Every player requires an ID.")
        return r

    @field_validator("decision_times")
    @classmethod
    def validate_times(cls, times: list[float]) -> list[float]:
        if any(not math.isfinite(t) or t < 0 for t in times):
            raise ValueError("Decision times must be finite and nonnegative.")
        if len(set(round(t, 3) for t in times)) != len(times):
            raise ValueError("Decision times must be distinct.")
        return times

    @field_validator("episode_start_s", "primary_t0")
    @classmethod
    def finite_time(cls, t: float) -> float:
        if not math.isfinite(t) or t < 0:
            raise ValueError("Episode timestamps must be finite and nonnegative.")
        return t


class EpisodeFollowupRequest(EpisodeLessonRequest):
    question: str = Field(min_length=1, max_length=500)


class EpisodeEvidenceRequest(EpisodeLessonRequest):
    evidence_refs: list[str] = Field(min_length=1, max_length=20)


class EpisodeCandidatesRequest(BaseModel):
    replay: dict[str, Any]
    player_id: str = Field(min_length=1, max_length=256)
    max_candidates: int = Field(default=8, ge=1, le=12)
    horizon_s: float | None = None

    @field_validator("replay")
    @classmethod
    def require_2v2(cls, r: dict[str, Any]) -> dict[str, Any]:
        return EpisodeLessonRequest.validate_replay(r)

    @field_validator("horizon_s")
    @classmethod
    def finite_horizon(cls, t: float | None) -> float | None:
        if t is not None and (not math.isfinite(t) or t < 0):
            raise ValueError("Discovery horizon must be a finite nonnegative number.")
        return t


class ReviewBundleRequest(EpisodeCandidatesRequest):
    preview_count: int = Field(default=3, ge=0, le=4)
    experimental_tactical_v1: bool = False


async def _read_json_request(request: Request, model_class: type[BaseModel]) -> BaseModel:
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(415, "Send the coaching request as application/json.")
    size = 0
    chunks = []
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_JSON_BYTES:
            raise HTTPException(413, "Coaching request exceeds 24 MB.")
        chunks.append(chunk)
    try:
        return model_class.model_validate_json(b"".join(chunks))
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "Invalid episode or replay request.") from exc


def _build_episode(req: EpisodeLessonRequest) -> dict:
    try:
        if req.player_id not in {p["id"] for p in req.replay["players"]}:
            raise EpisodeError("Selected player is not in this replay.")
        return build_episode_evidence(
            req.replay, req.player_id, req.decision_times,
            req.episode_start_s, req.primary_t0,
        )
    except (EpisodeError, ValueError, KeyError, TypeError, OverflowError) as exc:
        raise HTTPException(422, "Could not construct the selected tactical episode.") from exc


@router.get("/api/coach/capabilities")
def coach_capabilities():
    return {
        "schema": "CoachCapabilitiesV0",
        "lesson": "CoachLessonV0",
        "followup": "CoachFollowupV0",
        "local_deterministic_available": True,
        "optional_model_enabled": model_enabled(),
        "model_configuration_status": model_readiness()["status"],
        "model_requires_request_opt_in": True,
        "stage": "predecision",
        "automatic_episode_selection": False,
        "source_backed_candidate_discovery": "EpisodeCandidatesV0",
        "single_request_review_bundle": "CoachReviewBundleV0",
        "coaching_report_v1": "experimental_opt_in_local",
        "coaching_report_v1_invokes_model": False,
        "coaching_report_v1_expert_validated": False,
        "coaching_report_v1_auto_generated": False,
        "local_scene_relations": "RelationalInvariantsV0",
        "scene_relations_use_model": False,
        "scene_relations_predict_outcomes": False,
        "review_bundle_max_previews": 4,
        "review_bundle_invokes_model": False,
        "candidate_discovery_is_tactical_grading": False,
        "experimental_decision_state_v1": "explicit_opt_in_deterministic_only",
        "experimental_v1_expert_validated": False,
        "experimental_v1_default_enabled": False,
        "tactical_accuracy_expert_verified": False,
    }


@router.get("/api/coach/model-readiness")
def coach_model_readiness_endpoint():
    """Safe, read-only settings check; does NOT contact an AI provider."""
    return model_readiness()


@router.post("/api/coach/candidates")
async def coach_candidates_endpoint(request: Request):
    """Source-backed full-match review candidates; no tactical blame or model call.

    Returns an inspectable (comparison timestamp, primary timestamp) pair
    for each candidate; use the same times with /api/coach/lesson. These
    are observed-state comparisons, not asserted chains of decisions.
    """
    req = await _read_json_request(request, EpisodeCandidatesRequest)
    try:
        return await run_in_threadpool(
            discover_episode_candidates, req.replay, req.player_id,
            max_candidates=req.max_candidates, horizon_s=req.horizon_s,
        )
    except (DiscoveryError, ValueError, TypeError, KeyError, OverflowError) as exc:
        raise HTTPException(422, "Could not safely discover source-backed review candidates.") from exc


@router.post("/api/coach/review-bundle")
async def coach_review_bundle_endpoint(request: Request):
    """Prepare source-checked review leads + bounded lessons in one replay request.

    No user replay is retained; no external model called; comparison samples
    are NOT inferred prior player decisions or tactical grades.
    """
    req = await _read_json_request(request, ReviewBundleRequest)
    try:
        return await run_in_threadpool(
            build_review_bundle, req.replay, req.player_id,
            max_candidates=req.max_candidates, preview_count=req.preview_count,
            experimental_tactical_v1=req.experimental_tactical_v1,
            horizon_s=req.horizon_s,
        )
    except (DiscoveryError, ValueError, TypeError, KeyError, OverflowError) as exc:
        raise HTTPException(422, "Could not safely build this replay review bundle.") from exc


@router.post("/api/coach/scene-relations")
async def coach_scene_relations_endpoint(request: Request):
    """Local-only measured geometry; not a tactical verdict or model call."""
    req = await _read_json_request(request, EpisodeLessonRequest)
    if req.mode != "deterministic" or req.experimental_tactical_v1:
        raise HTTPException(422, "Scene relations require local deterministic mode.")
    episode = await run_in_threadpool(_build_episode, req)
    try:
        return await run_in_threadpool(
            build_relational_invariants,
            await run_in_threadpool(build_stage1_episode_packet, episode),
        )
    except (Stage1PacketError, ValueError, TypeError) as exc:
        raise HTTPException(422, "Could not safely compute local source-backed geometry.") from exc


@router.post("/api/coach/lesson")
async def coach_lesson_endpoint(request: Request):
    """Build a lesson from a manually selected 5-20s 2v2 sequence."""
    req = await _read_json_request(request, EpisodeLessonRequest)
    # V1 has not demonstrated expert merit. Compare it locally and explicitly;
    # never forward its inferred stances or branch consequences to a model.
    if req.experimental_tactical_v1 and req.mode != "deterministic":
        raise HTTPException(422, "Experimental V1 is available for deterministic lessons only.")
    # No model call unless the explicit request AND server gates are both open.
    if req.mode == "model" and not model_enabled():
        raise HTTPException(403, "Optional coaching model is disabled by default.")
    episode = await run_in_threadpool(_build_episode, req)
    try:
        if req.mode == "model":
            packet = await run_in_threadpool(build_stage1_episode_packet, episode)
            draft = await propose_coach_draft(packet)
        else:
            draft = None
        return await run_in_threadpool(
            build_lesson_from_episode, episode, model_draft=draft,
            experimental_tactical_v1=req.experimental_tactical_v1,
        )
    except CoachModelDisabled as e:
        raise HTTPException(503, str(e)) from e
    except (CoachModelError, CoachDraftError) as e:
        raise HTTPException(502, "Coaching model returned no valid structured lesson.") from e
    except (Stage1PacketError, ValueError, TypeError) as e:
        raise HTTPException(422, "Episode could not be safely converted into a coaching lesson.") from e


@router.post("/api/coach/evidence")
async def coach_evidence_endpoint(request: Request):
    """Read-only inspector: source-backed node/episode references, never future."""
    req = await _read_json_request(request, EpisodeEvidenceRequest)
    if req.mode != "deterministic":
        raise HTTPException(422, "Evidence inspection never invokes a model.")
    episode = await run_in_threadpool(_build_episode, req)
    try:
        return await run_in_threadpool(lookup_episode_evidence, episode, req.evidence_refs)
    except (Stage1PacketError, ValueError, TypeError) as e:
        raise HTTPException(422, "Requested citation cannot be resolved from Stage 1 evidence.") from e


@router.post("/api/coach/followup")
async def coach_followup_endpoint(request: Request):
    """Local evidence-navigation follow-up; no cloud or chat inference in V0."""
    req = await _read_json_request(request, EpisodeFollowupRequest)
    if req.mode != "deterministic":
        raise HTTPException(422, "Model follow-up is not yet enabled in CoachFollowupV0.")
    episode = await run_in_threadpool(_build_episode, req)
    try:
        return await run_in_threadpool(answer_evidence_followup, episode, req.question)
    except (Stage1PacketError, ValueError, TypeError) as e:
        raise HTTPException(422, "Cannot safely answer from this episode evidence.") from e
