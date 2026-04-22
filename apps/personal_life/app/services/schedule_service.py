from datetime import datetime

from ..domain.schemas import ScheduleCreate, ScheduleResponse
from ..storage.database import fetch_all, fetch_one, execute
from .datetime_utils import ensure_datetime


def create_schedule(payload: ScheduleCreate) -> ScheduleResponse:
    schedule_id = execute(
        """
        INSERT INTO schedules (title, details, scheduled_for, start_time)
        VALUES (?, ?, ?, ?)
        """,
        (payload.title, payload.details, payload.scheduled_for, payload.start_time),
    )
    row = fetch_one("SELECT * FROM schedules WHERE id = ?", (schedule_id,))
    return _row_to_schedule(row)


def list_schedules(day: str | None = None, limit: int = 20) -> list[ScheduleResponse]:
    if day:
        rows = fetch_all(
            """
            SELECT *
            FROM schedules
            WHERE scheduled_for = ?
            ORDER BY COALESCE(start_time, '23:59') ASC, created_at ASC
            LIMIT ?
            """,
            (day, limit),
        )
    else:
        rows = fetch_all(
            """
            SELECT *
            FROM schedules
            ORDER BY scheduled_for ASC, COALESCE(start_time, '23:59') ASC
            LIMIT ?
            """,
            (limit,),
        )
    return [_row_to_schedule(row) for row in rows]


def count_schedules_for_day(day: str) -> int:
    row = fetch_one(
        """
        SELECT COUNT(*) AS schedule_count
        FROM schedules
        WHERE scheduled_for = ?
        """,
        (day,),
    )
    return int(row["schedule_count"])


def _row_to_schedule(row: dict) -> ScheduleResponse:
    return ScheduleResponse(
        id=row["id"],
        title=row["title"],
        details=row["details"],
        scheduled_for=row["scheduled_for"],
        start_time=row["start_time"],
        created_at=ensure_datetime(row["created_at"]),
    )
