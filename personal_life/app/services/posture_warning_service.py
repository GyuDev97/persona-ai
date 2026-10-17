"""Core-side handling for authenticated, local posture warning events."""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
from datetime import datetime, timedelta

from ..storage.database import execute, fetch_one
from .event_bus_service import publish_event
from .gyuvis_tts_service import speak_gyuvis_text
from .posture_session_service import record_posture_warning


logger = logging.getLogger("gyuos.posture_warning")
EVENT_TYPE = "posture_warning"
_cooldown_lock = threading.Lock()


def is_valid_posture_api_token(provided_token: str | None) -> bool:
    expected_token = os.getenv("GYUVIS_POSTURE_API_TOKEN", "").strip()
    return bool(expected_token and provided_token and secrets.compare_digest(provided_token, expected_token))


def handle_posture_warning(payload: dict) -> dict:
    cooldown_seconds = max(0, int(os.getenv("GYUVIS_POSTURE_WARNING_COOLDOWN_SECONDS", "1500")))
    with _cooldown_lock:
        duplicate = _find_recent_warning(cooldown_seconds)
        if duplicate:
            result = {
                "accepted": False,
                "duplicate": True,
                "message": "A recent posture warning is still in cooldown.",
                "event_id": duplicate["id"],
                "tts_success": None,
            }
            publish_event(EVENT_TYPE, message="Duplicate posture warning ignored", payload={**payload, **result})
            return result

        event_id = execute(
            """
            INSERT INTO posture_warning_events
                (posture_type, duration_seconds, score, sensor_timestamp, processing_result, tts_success, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["type"],
                float(payload["duration_seconds"]),
                float(payload["score"]),
                payload["timestamp"].isoformat(),
                "processing",
                0,
                json.dumps(payload, ensure_ascii=False, default=str),
            ),
        )
        try:
            record_posture_warning(payload.get("session_id"), event_id, payload["timestamp"])
        except Exception:
            # Analytics must never suppress the existing posture warning/TTS path.
            logger.exception("Failed to associate posture warning with an analytics session")

    message = os.getenv("GYUVIS_POSTURE_WARNING_MESSAGE", "보스, 자세 고치세요.")
    tts_success = speak_gyuvis_text(message, backend_override_env="GYUVIS_POSTURE_TTS_BACKEND")
    processing_result = "completed" if tts_success else "partial_failure"
    execute(
        "UPDATE posture_warning_events SET processing_result = ?, tts_success = ? WHERE id = ?",
        (processing_result, int(tts_success), event_id),
    )
    result = {
        "accepted": True,
        "duplicate": False,
        "message": "Posture warning processed.",
        "event_id": event_id,
        "tts_success": tts_success,
    }
    publish_event(EVENT_TYPE, message="Posture warning processed", payload={**payload, **result})
    return result


def _find_recent_warning(cooldown_seconds: int) -> dict | None:
    if cooldown_seconds <= 0:
        return None
    cutoff = (datetime.now() - timedelta(seconds=cooldown_seconds)).replace(microsecond=0).isoformat(sep=" ")
    return fetch_one(
        "SELECT id FROM posture_warning_events WHERE created_at >= ? ORDER BY id DESC LIMIT 1",
        (cutoff,),
    )
