"""Read-only posture history and aggregate statistics endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ...services.posture_session_service import get_posture_session, list_posture_sessions
from ...services.posture_stats_service import build_posture_stats, build_time_buckets


router = APIRouter(prefix="/api/posture", tags=["posture"])


def _days(days: int) -> int:
    if days not in {7, 30}:
        raise HTTPException(status_code=422, detail="days must be 7 or 30")
    return days


@router.get("/stats")
def get_posture_stats(days: int = Query(default=7)) -> dict:
    return build_posture_stats(_days(days))


@router.get("/time-buckets")
def get_posture_time_buckets(days: int = Query(default=7)) -> dict:
    return build_time_buckets(_days(days))


@router.get("/sessions")
def get_posture_sessions(limit: int = Query(default=50, ge=1, le=200), include_active: bool = False) -> list[dict]:
    return list_posture_sessions(limit=limit, include_active=include_active)


@router.get("/sessions/{session_id}")
def get_posture_session_detail(session_id: str) -> dict:
    detail = get_posture_session(session_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Posture session not found")
    return detail
