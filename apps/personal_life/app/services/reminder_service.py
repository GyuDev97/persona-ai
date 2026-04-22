from ..domain.schemas import ReminderResponse
from ..storage.database import execute, fetch_all, fetch_one
from .datetime_utils import ensure_datetime


def create_reminder(
    title: str,
    remind_on: str,
    remind_time: str | None = None,
    details: str = "",
    origin_type: str = "manual",
    origin_id: int | None = None,
) -> ReminderResponse:
    reminder_id = execute(
        """
        INSERT INTO reminders (title, details, remind_on, remind_time, status, origin_type, origin_id)
        VALUES (?, ?, ?, ?, 'scheduled', ?, ?)
        """,
        (title, details, remind_on, remind_time, origin_type, origin_id),
    )
    row = fetch_one(
        """
        SELECT id, title, details, remind_on, remind_time, status, origin_type, origin_id, created_at, notified_at
        FROM reminders
        WHERE id = ?
        """,
        (reminder_id,),
    )
    return _row_to_reminder(row)


def list_reminders(status: str = "scheduled", limit: int = 20) -> list[ReminderResponse]:
    if status == "all":
        rows = fetch_all(
            """
            SELECT id, title, details, remind_on, remind_time, status, origin_type, origin_id, created_at, notified_at
            FROM reminders
            ORDER BY remind_on ASC, COALESCE(remind_time, '23:59') ASC, id ASC
            LIMIT ?
            """,
            (limit,),
        )
    else:
        rows = fetch_all(
            """
            SELECT id, title, details, remind_on, remind_time, status, origin_type, origin_id, created_at, notified_at
            FROM reminders
            WHERE status = ?
            ORDER BY remind_on ASC, COALESCE(remind_time, '23:59') ASC, id ASC
            LIMIT ?
            """,
            (status, limit),
        )
    return [_row_to_reminder(row) for row in rows]


def list_due_reminders(day: str, limit: int = 10) -> list[ReminderResponse]:
    rows = fetch_all(
        """
        SELECT id, title, details, remind_on, remind_time, status, origin_type, origin_id, created_at, notified_at
        FROM reminders
        WHERE status = 'scheduled' AND remind_on <= ?
        ORDER BY remind_on ASC, COALESCE(remind_time, '23:59') ASC, id ASC
        LIMIT ?
        """,
        (day, limit),
    )
    return [_row_to_reminder(row) for row in rows]


def _row_to_reminder(row: dict) -> ReminderResponse:
    return ReminderResponse(
        id=row["id"],
        title=row["title"],
        details=row["details"],
        remind_on=row["remind_on"],
        remind_time=row["remind_time"],
        status=row["status"],
        origin_type=row["origin_type"],
        origin_id=row["origin_id"],
        created_at=ensure_datetime(row["created_at"]),
        notified_at=ensure_datetime(row["notified_at"]),
    )
