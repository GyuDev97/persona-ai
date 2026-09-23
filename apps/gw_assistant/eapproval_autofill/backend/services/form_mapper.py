"""Map normalized source facts to an independently defined Form Schema."""
from __future__ import annotations

import re
from typing import Any

from backend.forms.registry import get_schema
from backend.services.source_extraction import extract_source_document
from backend.services.ai_form_mapper import AIMapperError, map_with_gpt
from backend.services.result_validation import validate_mapping


def _key(value: str) -> str:
    return re.sub(r"[\s_()\-]", "", value.strip().lower())


def _date(value: str) -> str | None:
    hit = re.search(r"(\d{4})[./년 -]+(\d{1,2})[./월 -]+(\d{1,2})", value)
    return f"{hit.group(1)}-{int(hit.group(2)):02d}-{int(hit.group(3)):02d}" if hit else None


def _field_value(labels: dict[str, str], definition: dict[str, Any]) -> Any:
    raw = next((labels[_key(alias)] for alias in definition["aliases"] if _key(alias) in labels), None)
    if raw is None: return None
    if definition["type"] == "date": return _date(raw)
    if definition["type"] == "number":
        digits = re.sub(r"[^\d]", "", raw)
        return int(digits) if digits else None
    return raw


def _best_rows(source_tables: list[dict[str, Any]], columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    desired = {column["id"] for column in columns}
    candidate = max(source_tables, key=lambda table: len(desired.intersection(table["columns"])), default=None)
    if not candidate or not desired.intersection(candidate["columns"]): return []
    return [{column["id"]: row.get(column["id"], "") for column in columns} for row in candidate["rows"]]


def map_source_to_form(form_id: str, text: str, source_name: str | None = None) -> dict[str, Any]:
    schema = get_schema(form_id)
    try:
        result = validate_mapping(map_with_gpt(text, schema), schema)
        result["sourceName"] = source_name
        return result
    except AIMapperError as error:
        ai_warning = f"AI 분석을 사용할 수 없어 규칙 기반 추출 결과를 표시합니다: {error}"
    source = extract_source_document(text)
    fields = {}
    for definition in schema["fields"]:
        value = _field_value(source["labels"], definition)
        fields[definition["id"]] = {"value": value, "confidence": 0.95 if value is not None else None}
    tables = {table["id"]: _best_rows(source["tables"], table["columns"]) for table in schema["tables"]}
    warnings = [ai_warning, *[f"{table['label']}을 찾지 못했습니다. 열 제목 또는 구분된 표를 확인해주세요." for table in schema["tables"] if not tables[table["id"]]]]
    return {"formId": form_id, "formName": schema["formName"], "sourceName": source_name, "fields": fields, "tables": tables, "warnings": warnings, "rawTextPreview": source["rawTextPreview"]}
