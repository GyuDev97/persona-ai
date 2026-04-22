from datetime import datetime
from typing import Any

import yaml

from ..domain.schemas import (
    ProfileMemoryImportResponse,
    ProfileMemoryRecord,
)
from ..storage.database import execute, fetch_all


def import_profile_yaml(yaml_text: str) -> ProfileMemoryImportResponse:
    parsed = yaml.safe_load(yaml_text) or {}
    profile = parsed.get("user_profile", parsed)
    rows = _flatten_profile(profile)

    categories = sorted({row[0] for row in rows})
    imported_count = 0

    for row in rows:
        category, memory_key, value_text, value_type, confidence, memory_kind, source = row
        existing = fetch_all(
            """
            SELECT id
            FROM profile_memories
            WHERE category = ? AND memory_key = ?
            """,
            (category, memory_key),
        )
        if existing:
            execute(
                """
                UPDATE profile_memories
                SET value_text = ?, value_type = ?, confidence = ?, memory_kind = ?, source = ?, updated_at = CURRENT_TIMESTAMP
                WHERE category = ? AND memory_key = ?
                """,
                (value_text, value_type, confidence, memory_kind, source, category, memory_key),
            )
        else:
            execute(
                """
                INSERT INTO profile_memories (
                    category, memory_key, value_text, value_type, confidence, memory_kind, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )
        imported_count += 1

    return ProfileMemoryImportResponse(
        imported_count=imported_count,
        categories=categories,
        message="프로필 메모리를 가져왔어요.",
    )


def list_profile_memories() -> list[ProfileMemoryRecord]:
    rows = fetch_all(
        """
        SELECT id, category, memory_key, value_text, value_type, confidence, memory_kind, source, created_at, updated_at
        FROM profile_memories
        ORDER BY category ASC, memory_key ASC
        """
    )
    return [_row_to_memory(row) for row in rows]


def get_memory_value(category: str, memory_key: str) -> str | None:
    rows = fetch_all(
        """
        SELECT value_text
        FROM profile_memories
        WHERE category = ? AND memory_key = ?
        LIMIT 1
        """,
        (category, memory_key),
    )
    if not rows:
        return None
    return rows[0]["value_text"]


def list_memory_highlights(limit: int = 6) -> list[dict[str, str]]:
    return fetch_all(
        """
        SELECT category, memory_key, value_text, memory_kind, confidence
        FROM profile_memories
        ORDER BY
            CASE memory_kind
                WHEN 'preference' THEN 0
                WHEN 'fact' THEN 1
                ELSE 2
            END,
            category ASC,
            memory_key ASC
        LIMIT ?
        """,
        (limit,),
    )


def _row_to_memory(row: dict[str, Any]) -> ProfileMemoryRecord:
    return ProfileMemoryRecord(
        id=row["id"],
        category=row["category"],
        memory_key=row["memory_key"],
        value_text=row["value_text"],
        value_type=row["value_type"],
        confidence=row["confidence"],
        memory_kind=row["memory_kind"],
        source=row["source"],
        created_at=_to_datetime(row["created_at"]),
        updated_at=_to_datetime(row["updated_at"]),
    )


def _to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace(" ", "T"))


def _flatten_profile(profile: dict[str, Any]) -> list[tuple[str, str, str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str, str, str]] = []
    for category, value in profile.items():
        rows.extend(_flatten_value(category, value))
    return rows


def _flatten_value(
    category: str,
    value: Any,
    prefix: str = "",
) -> list[tuple[str, str, str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str, str, str]] = []

    if isinstance(value, dict):
        for key, item in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_flatten_value(category, item, next_prefix))
        return rows

    memory_key = prefix
    value_type = _infer_value_type(value)
    confidence = _infer_confidence(memory_key, value)
    memory_kind = _infer_memory_kind(memory_key)
    source = "imported"

    if isinstance(value, list):
        value_text = ", ".join(str(item) for item in value)
    else:
        value_text = str(value)

    rows.append((category, memory_key, value_text, value_type, confidence, memory_kind, source))
    return rows


def _infer_value_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, list):
        return "list"
    return "text"


def _infer_confidence(memory_key: str, value: Any) -> str:
    lowered_key = memory_key.lower()
    if any(token in lowered_key for token in ["likely", "inference", "inferred"]):
        return "medium"
    if isinstance(value, str) and value in {"confirmed", "high", "medium_high", "likely"}:
        if value == "confirmed":
            return "high"
        if value == "likely":
            return "medium"
    return "high"


def _infer_memory_kind(memory_key: str) -> str:
    lowered_key = memory_key.lower()
    if any(token in lowered_key for token in ["prefers", "dislikes", "values", "tone", "style", "usage_preferences"]):
        return "preference"
    if any(token in lowered_key for token in ["likely", "inference", "inferred"]):
        return "inference"
    return "fact"
