from datetime import datetime

from ..domain.schemas import TaskCreate, TaskResponse
from ..storage.database import fetch_all, fetch_one, execute
from .datetime_utils import ensure_datetime


def create_task(payload: TaskCreate) -> TaskResponse:
    query = """
        INSERT INTO tasks (title, details, due_date, priority, status)
        VALUES (?, ?, ?, ?, 'open')
    """
    task_id = execute(
        query,
        (payload.title, payload.details, payload.due_date, payload.priority),
    )
    row = fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    return _row_to_task(row)


def list_tasks(status: str = "open", limit: int = 50) -> list[TaskResponse]:
    if status == "all":
        rows = fetch_all(
            """
            SELECT *
            FROM tasks
            ORDER BY
                CASE status WHEN 'open' THEN 0 ELSE 1 END,
                priority ASC,
                COALESCE(due_date, '9999-12-31') ASC,
                created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
    else:
        rows = fetch_all(
            """
            SELECT *
            FROM tasks
            WHERE status = ?
            ORDER BY
                priority ASC,
                COALESCE(due_date, '9999-12-31') ASC,
                created_at DESC
            LIMIT ?
            """,
            (status, limit),
        )
    return [_row_to_task(row) for row in rows]


def mark_task_done(task_id: int) -> TaskResponse | None:
    existing = fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    if existing is None:
        return None

    completed_at = datetime.now().isoformat(timespec="seconds")
    execute(
        """
        UPDATE tasks
        SET status = 'done', completed_at = ?
        WHERE id = ?
        """,
        (completed_at, task_id),
    )
    updated = fetch_one("SELECT * FROM tasks WHERE id = ?", (task_id,))
    return _row_to_task(updated)


def count_open_tasks() -> int:
    row = fetch_one(
        "SELECT COUNT(*) AS task_count FROM tasks WHERE status = 'open'",
    )
    return int(row["task_count"])


def count_completed_today(day: str) -> int:
    row = fetch_one(
        """
        SELECT COUNT(*) AS task_count
        FROM tasks
        WHERE status = 'done' AND date(completed_at) = ?
        """,
        (day,),
    )
    return int(row["task_count"])


def _row_to_task(row: dict) -> TaskResponse:
    return TaskResponse(
        id=row["id"],
        title=row["title"],
        details=row["details"],
        due_date=row["due_date"],
        priority=row["priority"],
        status=row["status"],
        created_at=ensure_datetime(row["created_at"]),
        completed_at=ensure_datetime(row["completed_at"]),
    )
