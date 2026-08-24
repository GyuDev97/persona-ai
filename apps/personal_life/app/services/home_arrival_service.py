"""Core-side handling for authenticated entrance-camera arrival events."""

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
from .jarvis_hud_service import launch_jarvis_hud


logger = logging.getLogger("gyuos.home_arrival")
EVENT_TYPE = "home_arrival"
_cooldown_lock = threading.Lock()


def is_valid_api_token(provided_token: str | None) -> bool:
    expected_token = os.getenv("GYUVIS_HOME_ARRIVAL_API_TOKEN", "").strip()
    return bool(expected_token and provided_token and secrets.compare_digest(provided_token, expected_token))


def handle_home_arrival(payload: dict) -> dict:
    cooldown_seconds = max(0, int(os.getenv("GYUVIS_HOME_ARRIVAL_COOLDOWN_SECONDS", "600")))
    with _cooldown_lock:
        duplicate = _find_recent_event(cooldown_seconds)
        if duplicate:
            result = {
                "accepted": False,
                "duplicate": True,
                "message": "A recent home-arrival event is still in cooldown.",
                "event_id": duplicate["id"],
                "wake_success": None,
                "tts_success": None,
            }
            publish_event(EVENT_TYPE, message="Duplicate home arrival ignored", payload={**payload, **result})
            return result

        event_id = execute(
            """
            INSERT INTO home_arrival_events
                (source, person, confidence, sensor_timestamp, processing_result, wake_success, tts_success, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["source"],
                payload["person"],
                float(payload["confidence"]),
                payload["timestamp"].isoformat(),
                "processing",
                0,
                0,
                json.dumps(payload, ensure_ascii=False, default=str),
            ),
        )

    wake_success = _wake_gyuvis()
    tts_success = speak_gyuvis_text(
        os.getenv("GYUVIS_HOME_ARRIVAL_GREETING", "어서 오세요."),
        backend_override_env="GYUVIS_HOME_ARRIVAL_TTS_BACKEND",
    )
    processing_result = "completed" if wake_success and tts_success else "partial_failure"
    execute(
        "UPDATE home_arrival_events SET processing_result = ?, wake_success = ?, tts_success = ? WHERE id = ?",
        (processing_result, int(wake_success), int(tts_success), event_id),
    )
    result = {
        "accepted": True,
        "duplicate": False,
        "message": "Home arrival processed.",
        "event_id": event_id,
        "wake_success": wake_success,
        "tts_success": tts_success,
    }
    publish_event(EVENT_TYPE, message="Home arrival processed", payload={**payload, **result})
    return result


def _find_recent_event(cooldown_seconds: int) -> dict | None:
    if cooldown_seconds <= 0:
        return None
    cutoff = (datetime.now() - timedelta(seconds=cooldown_seconds)).replace(microsecond=0).isoformat(sep=" ")
    return fetch_one(
        "SELECT id FROM home_arrival_events WHERE created_at >= ? ORDER BY id DESC LIMIT 1",
        (cutoff,),
    )


def _wake_gyuvis() -> bool:
    try:
        target = launch_jarvis_hud(immediate=True)
        logger.info("GYUVIS HUD wake succeeded: %s", target)
        return True
    except Exception:
        logger.exception("GYUVIS HUD wake failed")
        return False
