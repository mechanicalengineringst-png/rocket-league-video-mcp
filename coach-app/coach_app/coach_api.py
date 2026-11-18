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

from .coach_lesson import CoachDraftError, answer_evidence_followup, build_lesson_from_episode
from .coach_model import CoachModelDisabled, CoachModelError, model_enabled, propose_coach_draft
from .episode_evidence import EpisodeError, build_episode_evidence
from .episode_stage1 import build_stage1_episode_packet
from .stage1_packet import Stage1PacketError

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
        "model_requires_request_opt_in": True,
        "stage": "predecision",
        "automatic_episode_selection": False,
        "tactical_accuracy_expert_verified": False,
    }


@router.post("/api/coach/lesson")
async def coach_lesson_endpoint(request: Request):
    """Build a lesson from a manually selected 5-20s 2v2 sequence."""
    req = await _read_json_request(request, EpisodeLessonRequest)
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
        return await run_in_threadpool(build_lesson_from_episode, episode, model_draft=draft)
    except CoachModelDisabled as e:
        raise HTTPException(503, str(e)) from e
    except (CoachModelError, CoachDraftError) as e:
        raise HTTPException(502, "Coaching model returned no valid structured lesson.") from e
    except (Stage1PacketError, ValueError, TypeError) as e:
        raise HTTPException(422, "Episode could not be safely converted into a coaching lesson.") from e


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
