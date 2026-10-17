from datetime import datetime

from ..domain.schemas import QuickCaptureCreate, QuickCaptureResponse
from ..storage.database import fetch_all, fetch_one, execute
from .datetime_utils import ensure_datetime


def create_quick_capture(payload: QuickCaptureCreate) -> QuickCaptureResponse:
    query = """
        INSERT INTO quick_captures (capture_type, content, source)
        VALUES (?, ?, ?)
    """
    capture_id = execute(query, (payload.capture_type, payload.content, payload.source))
    row = fetch_one(
        """
        SELECT id, capture_type, content, source, created_at
        FROM quick_captures
        WHERE id = ?
        """,
        (capture_id,),
    )
    return _row_to_capture(row)


def list_quick_captures(limit: int = 20) -> list[QuickCaptureResponse]:
    rows = fetch_all(
        """
        SELECT id, capture_type, content, source, created_at
        FROM quick_captures
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [_row_to_capture(row) for row in rows]


def count_captures_for_day(day: str) -> int:
    row = fetch_one(
        """
        SELECT COUNT(*) AS capture_count
        FROM quick_captures
        WHERE date(created_at) = ?
        """,
        (day,),
    )
    return int(row["capture_count"])


def _row_to_capture(row: dict) -> QuickCaptureResponse:
    return QuickCaptureResponse(
        id=row["id"],
        capture_type=row["capture_type"],
        content=row["content"],
        source=row["source"],
        created_at=ensure_datetime(row["created_at"]),
    )
