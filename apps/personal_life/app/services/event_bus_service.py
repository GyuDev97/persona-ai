from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .agent_message_service import create_agent_message
from .agent_status_service import add_agent_log


logger = logging.getLogger("gyuos.events")


@dataclass(frozen=True)
class GyuOSEvent:
    event_type: str
    agent_id: int = 0
    task_id: int | None = None
    level: str = "info"
    message: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().replace(microsecond=0).isoformat(sep=" "))


def publish_event(
    event_type: str,
    *,
    agent_id: int = 0,
    task_id: int | None = None,
    level: str = "info",
    message: str = "",
    payload: dict[str, Any] | None = None,
    mirror_to_agent_log: bool = False,
    mirror_to_agent_message: bool = False,
) -> GyuOSEvent:
    event = GyuOSEvent(
        event_type=str(event_type or "system.event"),
        agent_id=int(agent_id or 0),
        task_id=task_id,
        level=_normalize_level(level),
        message=str(message or event_type or "system.event"),
        payload=payload or {},
    )
    _log_event(event)

    if mirror_to_agent_log and event.agent_id > 0:
        try:
            add_agent_log(event.agent_id, event.message, level=event.level)
        except Exception:
            logger.exception("Failed to mirror event to agent_log: %s", event.event_type)

    if mirror_to_agent_message and event.agent_id > 0:
        try:
            create_agent_message(
                event.agent_id,
                event.message,
                topic=event.event_type,
                payload={"task_id": event.task_id, **event.payload},
            )
        except Exception:
            logger.exception("Failed to mirror event to agent_messages: %s", event.event_type)

    return event


def _log_event(event: GyuOSEvent) -> None:
    log_payload = {
        "event_type": event.event_type,
        "agent_id": event.agent_id,
        "task_id": event.task_id,
        "payload": event.payload,
    }
    if event.level == "error":
        logger.error("%s | %s | %s", event.event_type, event.message, log_payload)
        return
    logger.info("%s | %s | %s", event.event_type, event.message, log_payload)


def _normalize_level(level: str) -> str:
    return "error" if str(level).lower() == "error" else "info"
