"""Validate and safely coerce an AI mapping before it reaches the browser."""
from __future__ import annotations
import re
from typing import Any

def _number(value: Any) -> int | float | None:
    if value is None: return None
    if isinstance(value, (int, float)): return value
    raw = re.sub(r"[^\d.-]", "", str(value))
    return float(raw) if "." in raw else int(raw) if raw else None

def _date(value: Any) -> str | None:
    if value is None: return None
    hit = re.search(r"(\d{4})[./년 -]+(\d{1,2})[./월 -]+(\d{1,2})", str(value))
    return f"{hit.group(1)}-{int(hit.group(2)):02d}-{int(hit.group(3)):02d}" if hit else None

def validate_mapping(data: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    warnings = list(data.get("warnings", [])); fields = {}; tables = {}
    for field in schema["fields"]:
        item = data.get("fields", {}).get(field["id"], {})
        value = item.get("value") if isinstance(item, dict) else None
        if field["type"] == "number": value = _number(value)
        if field["type"] == "date":
            parsed = _date(value)
            if value is not None and parsed is None: warnings.append(f"{field['label']} 날짜 형식을 확인해주세요.")
            value = parsed
        fields[field["id"]] = {"value": value, "confidence": max(0.0, min(1.0, float(item.get("confidence", 0) or 0))), "sourceText": item.get("sourceText")}
    for table in schema["tables"]:
        rows = data.get("tables", {}).get(table["id"], []); clean_rows = []
        for row in rows if isinstance(rows, list) else []:
            clean = {col["id"]: row.get(col["id"]) for col in table["columns"]}
            for key in {"quantity", "unitPrice", "amount", "supplyAmount", "tax"}.intersection(clean): clean[key] = _number(clean[key])
            if clean.get("quantity") is not None and clean.get("unitPrice") is not None:
                expected = clean["quantity"] * clean["unitPrice"]
                if clean.get("amount") is None: clean["amount"] = expected
                elif clean["amount"] != expected: warnings.append("수량 × 단가와 금액이 일치하지 않는 행이 있습니다.")
            if all(clean.get(key) is not None for key in ("supplyAmount", "tax", "amount")) and clean["supplyAmount"] + clean["tax"] != clean["amount"]: warnings.append("공급가액 + 세액과 합계가 일치하지 않는 행이 있습니다.")
            clean_rows.append(clean)
        tables[table["id"]] = clean_rows
    return {"formId": schema["formId"], "formName": schema["formName"], "fields": fields, "tables": tables, "warnings": warnings}
