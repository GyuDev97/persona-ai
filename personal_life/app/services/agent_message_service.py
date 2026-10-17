import json
from typing import Any

from ..storage.database import execute, fetch_all


AGENT_NAMES = {
    1: "Agent 01",
    2: "Agent 02",
    3: "Agent 03",
    4: "Agent 04",
}


def create_agent_message(
    from_agent_id: int,
    message: str,
    *,
    to_agent_id: int | None = None,
    topic: str = "general",
    payload: dict[str, Any] | None = None,
    status: str = "posted",
) -> dict[str, Any]:
    clean_message = " ".join(str(message or "").split())
    if not clean_message:
        raise ValueError("message 값이 필요합니다.")

    message_id = execute(
        """
        INSERT INTO agent_messages (
            from_agent_id, to_agent_id, topic, message, payload_json, status
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            int(from_agent_id),
            int(to_agent_id) if to_agent_id is not None else None,
            str(topic or "general")[:100],
            clean_message,
            json.dumps(payload or {}, ensure_ascii=False, default=str),
            str(status or "posted")[:30],
        ),
    )
    return get_agent_message(message_id)


def list_agent_messages(limit: int = 12, topic: str | None = None) -> list[dict[str, Any]]:
    safe_limit = max(1, min(int(limit or 12), 50))
    if topic:
        rows = fetch_all(
            """
            SELECT *
            FROM agent_messages
            WHERE topic = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (topic, safe_limit),
        )
    else:
        rows = fetch_all(
            """
            SELECT *
            FROM agent_messages
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (safe_limit,),
        )
    return [_message_payload(row) for row in rows]


def get_agent_message(message_id: int) -> dict[str, Any]:
    rows = fetch_all("SELECT * FROM agent_messages WHERE id = ? LIMIT 1", (int(message_id),))
    if not rows:
        raise ValueError("Agent message not found")
    return _message_payload(rows[0])


def _message_payload(row: dict[str, Any]) -> dict[str, Any]:
    from_agent_id = int(row.get("from_agent_id") or 0)
    to_agent_id = row.get("to_agent_id")
    parsed_to_agent_id = int(to_agent_id) if to_agent_id is not None else None
    return {
        "id": int(row.get("id")),
        "from_agent_id": from_agent_id,
        "from_agent_label": AGENT_NAMES.get(from_agent_id, f"Agent {from_agent_id:02d}"),
        "to_agent_id": parsed_to_agent_id,
        "to_agent_label": AGENT_NAMES.get(parsed_to_agent_id, f"Agent {parsed_to_agent_id:02d}")
        if parsed_to_agent_id
        else "전체",
        "topic": row.get("topic") or "general",
        "message": row.get("message") or "",
        "payload": _payload_dict(row.get("payload_json")),
        "status": row.get("status") or "posted",
        "created_at": str(row.get("created_at")) if row.get("created_at") is not None else None,
    }


def _payload_dict(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
