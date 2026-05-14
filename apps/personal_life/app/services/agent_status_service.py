from __future__ import annotations

from datetime import datetime
from typing import Any

from ..storage.database import execute, fetch_all, fetch_one


TASK_AGENT_MAP = {
    "agent1_it_news_window": 1,
    "agent2_it_blog_draft": 2,
    "naver_blog_fill_draft": 2,
    "coding_app_update": 3,
    "autonomy_review": 3,
    "finance_monthly_summary": 3,
    "youtube_idea_research": 4,
}


def agent_id_for_task_type(task_type: str) -> int:
    return TASK_AGENT_MAP.get(task_type, 0)


def mark_agent_running(agent_id: int, message: str) -> None:
    if agent_id <= 0:
        return
    now = _now()
    _upsert_agent_status(
        agent_id=agent_id,
        status="running",
        last_run_at=now,
        last_success_at=None,
        last_error=None,
        update_success=False,
    )
    add_agent_log(agent_id, message, level="info")


def mark_agent_success(agent_id: int, message: str) -> None:
    if agent_id <= 0:
        return
    now = _now()
    _upsert_agent_status(
        agent_id=agent_id,
        status="idle",
        last_run_at=None,
        last_success_at=now,
        last_error=None,
        update_success=True,
    )
    add_agent_log(agent_id, message, level="info")


def mark_agent_error(agent_id: int, message: str) -> None:
    if agent_id <= 0:
        return
    _upsert_agent_status(
        agent_id=agent_id,
        status="error",
        last_run_at=None,
        last_success_at=None,
        last_error=message,
        update_success=False,
    )
    add_agent_log(agent_id, message, level="error")


def add_agent_log(agent_id: int, message: str, level: str = "info") -> None:
    if agent_id <= 0:
        return
    execute(
        """
        INSERT INTO agent_log (agent_id, message, level, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (agent_id, message[:2000], _normalize_level(level), _now()),
    )


def list_agent_statuses() -> dict[int, dict[str, Any]]:
    rows = fetch_all(
        """
        SELECT agent_id, status, last_run_at, last_success_at, last_error
        FROM agent_status
        """
    )
    return {int(row["agent_id"]): _status_payload(row) for row in rows}


def get_agent_status(agent_id: int) -> dict[str, Any] | None:
    row = fetch_one(
        """
        SELECT agent_id, status, last_run_at, last_success_at, last_error
        FROM agent_status
        WHERE agent_id = ?
        """,
        (agent_id,),
    )
    return _status_payload(row) if row else None


def _upsert_agent_status(
    agent_id: int,
    status: str,
    last_run_at: str | None,
    last_success_at: str | None,
    last_error: str | None,
    update_success: bool,
) -> None:
    existing = fetch_one("SELECT agent_id FROM agent_status WHERE agent_id = ?", (agent_id,))
    if existing:
        if update_success:
            execute(
                """
                UPDATE agent_status
                SET status = ?, last_success_at = ?, last_error = NULL
                WHERE agent_id = ?
                """,
                (status, last_success_at, agent_id),
            )
        elif last_run_at is not None:
            execute(
                """
                UPDATE agent_status
                SET status = ?, last_run_at = ?, last_error = NULL
                WHERE agent_id = ?
                """,
                (status, last_run_at, agent_id),
            )
        else:
            execute(
                """
                UPDATE agent_status
                SET status = ?, last_error = ?
                WHERE agent_id = ?
                """,
                (status, last_error, agent_id),
            )
        return

    execute(
        """
        INSERT INTO agent_status (agent_id, status, last_run_at, last_success_at, last_error)
        VALUES (?, ?, ?, ?, ?)
        """,
        (agent_id, status, last_run_at, last_success_at, last_error),
    )


def _status_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "agent_id": int(row.get("agent_id") or 0),
        "status": row.get("status") or "idle",
        "last_run_at": _stringify(row.get("last_run_at")),
        "last_success_at": _stringify(row.get("last_success_at")),
        "last_error": row.get("last_error"),
    }


def _normalize_level(level: str) -> str:
    return "error" if str(level).lower() == "error" else "info"


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
