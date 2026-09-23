from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SCHEMA_DIR = Path(__file__).resolve().parent


def list_forms() -> list[dict[str, str]]:
    return [
        {"formId": schema["formId"], "formName": schema["formName"]}
        for schema in _all_schemas().values()
    ]


def get_all_schemas() -> list[dict[str, Any]]:
    return list(_all_schemas().values())


def get_schema(form_id: str) -> dict[str, Any]:
    try:
        return _all_schemas()[form_id]
    except KeyError as exc:
        raise ValueError(f"지원하지 않는 결재양식입니다: {form_id}") from exc


def _all_schemas() -> dict[str, dict[str, Any]]:
    schemas: dict[str, dict[str, Any]] = {}
    for path in SCHEMA_DIR.glob("*.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        schemas[schema["formId"]] = schema
    return schemas
