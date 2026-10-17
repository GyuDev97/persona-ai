import logging
from typing import Any

from .db import Database
from .events import EventBus
from .models import ActivityLog, row_dict
from .textutil import redact

logger = logging.getLogger("gyunexus")


class Activity:
    """실행 로그를 DB에 저장하고 이벤트 스트림으로도 내보낸다."""

    def __init__(self, db: Database, bus: EventBus):
        self.db = db
        self.bus = bus

    def record(
        self,
        source: str,
        event: str,
        *,
        level: str = "info",
        agent_id: str | None = None,
        debate_id: int | None = None,
        **detail: Any,
    ) -> None:
        detail = redact(detail)
        with self.db.session() as s:
            row = ActivityLog(
                source=source, event=event, level=level, agent_id=agent_id, debate_id=debate_id, detail=detail
            )
            s.add(row)
            s.flush()
            payload = row_dict(row)
        logger.log(logging.WARNING if level in ("warn", "error") else logging.INFO, "%s %s %s", source, event, detail)
        self.bus.publish("log", payload)
