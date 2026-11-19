"""Opt-in experimental endpoint: POST /api/coach/coaching-report-v1 -> CoachingReportV1 (Round 12).

Separate router so existing contracts (CoachLessonV0, CoachReviewBundleV0) are untouched. Local and
deterministic; never calls a model. Raises 422 on invalid input and never returns raw frames, names or IDs.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, field_validator

from .coach_api import EpisodeLessonRequest, _read_json_request
from .coach_report import build_coaching_report

router = APIRouter(tags=["coaching-experimental"])


class CoachingReportRequest(BaseModel):
    replay: dict[str, Any]
    player_id: str = Field(min_length=1, max_length=256)
    max_findings: int = Field(default=6, ge=1, le=12)
    include_retrospective: bool = True

    @field_validator("replay")
    @classmethod
    def require_2v2(cls, r: dict[str, Any]) -> dict[str, Any]:
        return EpisodeLessonRequest.validate_replay(r)


@router.post("/api/coach/coaching-report-v1")
async def coaching_report_endpoint(request: Request):
    req = await _read_json_request(request, CoachingReportRequest)
    if req.player_id not in {p["id"] for p in req.replay["players"]}:
        raise HTTPException(422, "Selected player is not in this replay.")
    try:
        return await run_in_threadpool(build_coaching_report, req.replay, req.player_id,
                                       max_findings=req.max_findings, include_retrospective=req.include_retrospective)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise HTTPException(422, "Could not build the coaching report for this replay.") from exc
