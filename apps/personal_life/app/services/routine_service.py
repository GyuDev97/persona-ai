from datetime import datetime

from ..domain.schemas import RoutineCheckinResponse, RoutineCreate, RoutineResponse
from ..storage.database import fetch_all, fetch_one, execute
from .datetime_utils import ensure_datetime


def create_routine(payload: RoutineCreate) -> RoutineResponse:
    routine_id = execute(
        """
        INSERT INTO routines (name, description, frequency, is_active)
        VALUES (?, ?, ?, 1)
        """,
        (payload.name, payload.description, payload.frequency),
    )
    row = fetch_one("SELECT * FROM routines WHERE id = ?", (routine_id,))
    return _row_to_routine(row)


def list_routines(active_only: bool = True) -> list[RoutineResponse]:
    if active_only:
        rows = fetch_all(
            """
            SELECT *
            FROM routines
            WHERE is_active = 1
            ORDER BY created_at DESC
            """
        )
    else:
        rows = fetch_all(
            """
            SELECT *
            FROM routines
            ORDER BY is_active DESC, created_at DESC
            """
        )
    return [_row_to_routine(row) for row in rows]


def create_routine_checkin(routine_id: int, day: str, status: str) -> RoutineCheckinResponse | None:
    routine = fetch_one("SELECT * FROM routines WHERE id = ? AND is_active = 1", (routine_id,))
    if routine is None:
        return None

    existing = fetch_one(
        """
        SELECT rc.id, rc.routine_id, r.name AS routine_name, rc.checkin_date, rc.status, rc.created_at
        FROM routine_checkins rc
        JOIN routines r ON r.id = rc.routine_id
        WHERE rc.routine_id = ? AND rc.checkin_date = ?
        """,
        (routine_id, day),
    )
    if existing:
        execute(
            """
            UPDATE routine_checkins
            SET status = ?
            WHERE id = ?
            """,
            (status, existing["id"]),
        )
    else:
        execute(
            """
            INSERT INTO routine_checkins (routine_id, checkin_date, status)
            VALUES (?, ?, ?)
            """,
            (routine_id, day, status),
        )

    updated = fetch_one(
        """
        SELECT rc.id, rc.routine_id, r.name AS routine_name, rc.checkin_date, rc.status, rc.created_at
        FROM routine_checkins rc
        JOIN routines r ON r.id = rc.routine_id
        WHERE rc.routine_id = ? AND rc.checkin_date = ?
        """,
        (routine_id, day),
    )
    return _row_to_routine_checkin(updated)


def list_routine_checkins(day: str) -> list[RoutineCheckinResponse]:
    rows = fetch_all(
        """
        SELECT rc.id, rc.routine_id, r.name AS routine_name, rc.checkin_date, rc.status, rc.created_at
        FROM routine_checkins rc
        JOIN routines r ON r.id = rc.routine_id
        WHERE rc.checkin_date = ?
        ORDER BY rc.created_at DESC
        """,
        (day,),
    )
    return [_row_to_routine_checkin(row) for row in rows]


def count_routines() -> int:
    row = fetch_one(
        """
        SELECT COUNT(*) AS routine_count
        FROM routines
        WHERE is_active = 1
        """
    )
    return int(row["routine_count"])


def count_completed_routines_for_day(day: str) -> int:
    row = fetch_one(
        """
        SELECT COUNT(*) AS routine_count
        FROM routine_checkins
        WHERE checkin_date = ? AND status = 'done'
        """,
        (day,),
    )
    return int(row["routine_count"])


def _row_to_routine(row: dict) -> RoutineResponse:
    return RoutineResponse(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        frequency=row["frequency"],
        is_active=bool(row["is_active"]),
        created_at=ensure_datetime(row["created_at"]),
    )


def _row_to_routine_checkin(row: dict) -> RoutineCheckinResponse:
    return RoutineCheckinResponse(
        id=row["id"],
        routine_id=row["routine_id"],
        routine_name=row["routine_name"],
        checkin_date=row["checkin_date"],
        status=row["status"],
        created_at=ensure_datetime(row["created_at"]),
    )
