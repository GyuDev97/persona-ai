"""Form Schema와 무관하게 원본 문서의 의미를 정규화합니다."""
from __future__ import annotations

import re
from typing import Any


# Source-side vocabulary: new vendors only need aliases here, not a new approval form.
COLUMN_ALIASES = {
    "name": {"품명", "제품명", "상품명", "item", "product", "name"},
    "spec": {"규격", "모델명", "description", "spec", "model"},
    "quantity": {"수량", "qty", "quantity", "ea"},
    "unitPrice": {"단가", "공급단가", "price", "unit price"},
    "amount": {"금액", "공급가액", "total", "amount", "합계"},
    "date": {"월/일", "일자", "date"},
    "supplyAmount": {"공급가액", "공급금액", "supply amount"},
    "tax": {"세액", "부가세", "vat", "tax"},
    "remarks": {"비고", "참고", "remarks", "note"},
    "evidence": {"증빙", "증빙서류", "evidence"},
    "title": {"도서명", "책제목", "book title", "title"},
    "publisher": {"출판사", "publisher"},
    "author": {"저자", "author"},
}


def _key(value: str) -> str:
    return re.sub(r"[\s_()\-]", "", value.strip().lower())


def _number(value: str) -> int | None:
    digits = re.sub(r"[^\d]", "", value)
    return int(digits) if digits else None


def _semantic_header(value: str) -> str | None:
    normalized = _key(value)
    for meaning, aliases in COLUMN_ALIASES.items():
        if normalized in {_key(alias) for alias in aliases}:
            return meaning
    return None


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in re.split(r"\s*[|\t]\s*", line.strip())]


def _tables(text: str) -> list[dict[str, Any]]:
    lines = [line for line in text.splitlines() if line.strip()]
    found: list[dict[str, Any]] = []
    index = 0
    while index < len(lines):
        headers = _cells(lines[index])
        meanings = [_semantic_header(header) for header in headers]
        if len(headers) > 1 and sum(item is not None for item in meanings) >= 2:
            rows: list[dict[str, Any]] = []
            index += 1
            while index < len(lines):
                values = _cells(lines[index])
                if len(values) != len(headers): break
                row = {meaning: values[pos] for pos, meaning in enumerate(meanings) if meaning and values[pos]}
                if row:
                    for numeric in ("quantity", "unitPrice", "amount", "supplyAmount", "tax"):
                        if numeric in row: row[numeric] = _number(row[numeric])
                    rows.append(row)
                index += 1
            if rows: found.append({"columns": [item for item in meanings if item], "rows": rows})
        else:
            index += 1
    return found


def _legacy_rows(text: str) -> list[dict[str, Any]]:
    """Compatibility fallback for headerless five-column estimates; no vendor/file assumptions."""
    rows = []
    for line in text.splitlines():
        values = _cells(line)
        if len(values) != 5 or not values[2].isdigit() or _number(values[3]) is None or _number(values[4]) is None:
            continue
        rows.append({"name": values[0], "spec": values[1], "quantity": int(values[2]), "unitPrice": _number(values[3]), "amount": _number(values[4])})
    return rows


def extract_source_document(text: str) -> dict[str, Any]:
    """Return source facts and canonical table columns without knowing the selected approval form."""
    tables = _tables(text)
    if not tables:
        fallback = _legacy_rows(text)
        if fallback: tables.append({"columns": list(fallback[0]), "rows": fallback})
    labels: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^\s*([^:：|\t]+)\s*[:：|\t]\s*(.+?)\s*$", line)
        if match: labels[_key(match.group(1))] = match.group(2).strip()
    return {"labels": labels, "tables": tables, "rawTextPreview": text[:500]}
