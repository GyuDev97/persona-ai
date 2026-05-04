import json
from datetime import datetime

from ..domain.schemas import AgentTaskResponse
from ..storage.database import execute, fetch_all, fetch_one, get_connection
from .datetime_utils import ensure_datetime


def create_agent_task(
    *,
    command_text: str,
    task_type: str,
    search_query: str | None = None,
    source: str = "mobile",
    payload: dict | None = None,
) -> AgentTaskResponse:
    task_id = execute(
        """
        INSERT INTO agent_tasks (source, command_text, task_type, search_query, status, result_payload)
        VALUES (?, ?, ?, ?, 'pending', ?)
        """,
        (source, command_text, task_type, search_query, json.dumps(payload or {}, ensure_ascii=False)),
    )
    return get_agent_task(task_id)


def list_agent_tasks(status: str | None = None, limit: int = 20) -> list[AgentTaskResponse]:
    if status:
        rows = fetch_all(
            """
            SELECT *
            FROM agent_tasks
            WHERE status = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (status, limit),
        )
    else:
        rows = fetch_all(
            """
            SELECT *
            FROM agent_tasks
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
    return [_row_to_agent_task(row) for row in rows]


def get_agent_task(task_id: int) -> AgentTaskResponse:
    row = fetch_one("SELECT * FROM agent_tasks WHERE id = ?", (task_id,))
    if row is None:
        raise ValueError("Agent task not found")
    return _row_to_agent_task(row)


def claim_next_agent_task(device_label: str) -> AgentTaskResponse | None:
    with get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute(_adapt("SELECT id FROM agent_tasks WHERE status = 'pending' ORDER BY created_at ASC, id ASC LIMIT 1"))
        row = cursor.fetchone()
        if row is None:
            return None

        task_id = int((row["id"] if isinstance(row, dict) else row["id"]))
        now = _timestamp_now()
        cursor.execute(
            _adapt(
                """
                UPDATE agent_tasks
                SET status = 'claimed', device_label = ?, claimed_at = ?
                WHERE id = ? AND status = 'pending'
                """
            ),
            (device_label, now, task_id),
        )
        if cursor.rowcount == 0:
            connection.commit()
            return None
        connection.commit()

    return get_agent_task(task_id)


def complete_agent_task(task_id: int, summary: str, payload: dict | None = None) -> AgentTaskResponse:
    execute(
        """
        UPDATE agent_tasks
        SET status = 'completed',
            completed_at = ?,
            result_summary = ?,
            result_payload = ?,
            error_message = NULL
        WHERE id = ?
        """,
        (_timestamp_now(), summary, json.dumps(payload or {}, ensure_ascii=False), task_id),
    )
    return get_agent_task(task_id)


def fail_agent_task(task_id: int, message: str) -> AgentTaskResponse:
    execute(
        """
        UPDATE agent_tasks
        SET status = 'failed',
            completed_at = ?,
            error_message = ?
        WHERE id = ?
        """,
        (_timestamp_now(), message, task_id),
    )
    return get_agent_task(task_id)


def _row_to_agent_task(row: dict) -> AgentTaskResponse:
    return AgentTaskResponse(
        id=int(row["id"]),
        source=row["source"],
        command_text=row["command_text"],
        task_type=row["task_type"],
        search_query=row.get("search_query"),
        status=row["status"],
        device_label=row.get("device_label"),
        claimed_at=ensure_datetime(row.get("claimed_at")),
        completed_at=ensure_datetime(row.get("completed_at")),
        result_summary=row.get("result_summary"),
        result_payload=row.get("result_payload"),
        error_message=row.get("error_message"),
        created_at=ensure_datetime(row["created_at"]),
    )


def _adapt(query: str) -> str:
    # Small local helper to avoid importing a private function.
    from ..storage.database import _adapt_query  # noqa: PLC0415

    return _adapt_query(query)


def _timestamp_now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")
