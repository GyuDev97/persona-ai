from datetime import datetime
from typing import Any

from ..storage.database import execute, fetch_all, fetch_one


DEFAULT_AGENT_DEFINITIONS = [
    {
        "id": 1,
        "title": "오전 10시~오후 6시 IT 뉴스 요약",
        "description": "모바일, AI, 테크 뉴스 수집과 일일 요약을 담당합니다.",
        "task_types": "agent1_it_news_window",
        "status": "활성",
        "processing": "완료",
        "tone": "active",
        "sort_order": 10,
    },
    {
        "id": 2,
        "title": "IT/모바일 관련 블로그 초안 추천",
        "description": "수집된 IT 뉴스를 바탕으로 네이버 블로그 초안을 작성합니다.",
        "task_types": "agent2_it_blog_draft,naver_blog_fill_draft",
        "status": "활성",
        "processing": "진행중",
        "tone": "active",
        "sort_order": 20,
    },
    {
        "id": 3,
        "title": "코딩 / 앱 업데이트 처리",
        "description": "Codex 승인 대기 작업과 앱 업데이트 요청을 관리합니다.",
        "task_types": "coding_app_update",
        "status": "대기",
        "processing": "대기중",
        "tone": "idle",
        "sort_order": 30,
    },
    {
        "id": 4,
        "title": "유튜브 아이디어 탐색",
        "description": "유튜브 콘텐츠 아이디어 후보를 탐색하고 정리합니다.",
        "task_types": "youtube_idea_research",
        "status": "대기",
        "processing": "대기중",
        "tone": "idle",
        "sort_order": 40,
    },
]


def list_agent_definitions(include_disabled: bool = False) -> list[dict[str, Any]]:
    ensure_default_agent_definitions()
    where = "" if include_disabled else "WHERE is_enabled = 1"
    rows = fetch_all(
        f"""
        SELECT *
        FROM agent_definitions
        {where}
        ORDER BY sort_order ASC, id ASC
        """
    )
    return [_normalize_agent_definition(row) for row in rows]


def get_agent_definition(agent_id: int) -> dict[str, Any]:
    ensure_default_agent_definitions()
    row = fetch_one("SELECT * FROM agent_definitions WHERE id = ?", (agent_id,))
    if row is None:
        raise ValueError(f"에이전트 {agent_id}번을 찾을 수 없습니다.")
    return _normalize_agent_definition(row)


def create_agent_definition(payload: dict[str, Any]) -> dict[str, Any]:
    title = _required_text(payload.get("title"), "title")
    task_types = _normalize_task_types(payload.get("task_types"))
    now = _now()
    agent_id = execute(
        """
        INSERT INTO agent_definitions (
            title, description, task_types, status, processing, tone, sort_order, is_enabled, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (
            title,
            str(payload.get("description") or ""),
            ",".join(task_types),
            str(payload.get("status") or "대기"),
            str(payload.get("processing") or "대기중"),
            _normalize_tone(payload.get("tone")),
            int(payload.get("sort_order") or 100),
            now,
            now,
        ),
    )
    return get_agent_definition(agent_id)


def update_agent_definition(agent_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    current = get_agent_definition(agent_id)
    title = _required_text(payload.get("title", current["title"]), "title")
    task_types = _normalize_task_types(payload.get("task_types", current["task_types"]))
    execute(
        """
        UPDATE agent_definitions
        SET title = ?, description = ?, task_types = ?, status = ?, processing = ?,
            tone = ?, sort_order = ?, is_enabled = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            title,
            str(payload.get("description", current.get("description") or "")),
            ",".join(task_types),
            str(payload.get("status", current.get("status") or "대기")),
            str(payload.get("processing", current.get("processing") or "대기중")),
            _normalize_tone(payload.get("tone", current.get("tone"))),
            int(payload.get("sort_order", current.get("sort_order") or 100)),
            1 if bool(payload.get("is_enabled", current.get("is_enabled", True))) else 0,
            _now(),
            agent_id,
        ),
    )
    return get_agent_definition(agent_id)


def disable_agent_definition(agent_id: int) -> dict[str, Any]:
    get_agent_definition(agent_id)
    execute(
        """
        UPDATE agent_definitions
        SET is_enabled = 0, status = '비활성', processing = '비활성화됨', tone = 'idle', updated_at = ?
        WHERE id = ?
        """,
        (_now(), agent_id),
    )
    return get_agent_definition(agent_id)


def ensure_default_agent_definitions() -> None:
    for agent in DEFAULT_AGENT_DEFINITIONS:
        exists = fetch_one("SELECT id FROM agent_definitions WHERE id = ?", (agent["id"],))
        if exists is not None:
            continue
        now = _now()
        execute(
            """
            INSERT INTO agent_definitions (
                id, title, description, task_types, status, processing, tone, sort_order, is_enabled, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                agent["id"],
                agent["title"],
                agent["description"],
                agent["task_types"],
                agent["status"],
                agent["processing"],
                agent["tone"],
                agent["sort_order"],
                now,
                now,
            ),
        )


def _normalize_agent_definition(row: dict[str, Any]) -> dict[str, Any]:
    task_types = _normalize_task_types(row.get("task_types"))
    return {
        "id": int(row.get("id") or 0),
        "title": row.get("title") or "",
        "description": row.get("description") or "",
        "task_types": task_types,
        "status": row.get("status") or "대기",
        "processing": row.get("processing") or "대기중",
        "tone": _normalize_tone(row.get("tone")),
        "sort_order": int(row.get("sort_order") or 100),
        "is_enabled": bool(row.get("is_enabled")),
        "created_at": str(row.get("created_at") or ""),
        "updated_at": str(row.get("updated_at") or ""),
    }


def _normalize_task_types(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = str(value or "").replace("\n", ",").split(",")
    return [str(item).strip() for item in raw_items if str(item).strip()]


def _normalize_tone(value: Any) -> str:
    tone = str(value or "idle").strip()
    return tone if tone in {"active", "idle", "error"} else "idle"


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} 값이 필요합니다.")
    return text


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")
