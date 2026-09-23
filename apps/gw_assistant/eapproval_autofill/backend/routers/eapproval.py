from __future__ import annotations

import re
import zlib
from io import BytesIO
from typing import Any
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from backend.services.pdf_extraction import extract_pdf


router = APIRouter()


class ExtractRequest(BaseModel):
    template: str = Field(..., description="전자결재 양식 이름")
    document_text: str = Field(..., description="OCR 또는 텍스트 추출 결과")


def normalize_number(raw: str | None) -> int | None:
    if not raw:
        return None
    digits = re.sub(r"[^\d]", "", raw)
    return int(digits) if digits else None


def extract_by_patterns(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            value = match.group(1).strip()
            value = re.sub(r"^[|:：\s]+", "", value)
            return value.strip()
    return None


def extract_date(text: str) -> str | None:
    match = re.search(r"(\d{4})[./년 -]+(\d{1,2})[./월 -]+(\d{1,2})", text)
    if not match:
        return None
    year, month, day = match.groups()
    return f"{year}-{int(month):02d}-{int(day):02d}"


def extract_named_date(text: str, labels: list[str]) -> str | None:
    for label in labels:
        match = re.search(
            rf"{label}\s*(?:[:：]|\|)?\s*(\d{{4}}[./년 -]+\d{{1,2}}[./월 -]+\d{{1,2}})",
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        if match:
            return extract_date(match.group(1))
    return None


def extract_line_items(text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    pipe_pattern = re.compile(
        r"^(?P<name>[A-Za-z가-힣0-9()/_ -]+)\s*\|\s*"
        r"(?P<spec>[A-Za-z가-힣0-9()/_ -]+)\s*\|\s*"
        r"(?P<qty>\d+)\s*\|\s*"
        r"(?P<unit>\d[\d,]*)\s*\|\s*"
        r"(?P<amount>\d[\d,]*)$"
    )
    space_pattern = re.compile(
        r"^(?P<name>[A-Za-z가-힣0-9()/_ -]+)\s+"
        r"(?P<spec>[A-Za-z가-힣0-9()/_ -]+)\s+"
        r"(?P<qty>\d+)\s+"
        r"(?P<unit>\d[\d,]*)\s+"
        r"(?P<amount>\d[\d,]*)$"
    )

    seen_rows: set[tuple[str, str, int, int | None, int | None]] = set()

    for line in text.splitlines():
        normalized_line = line.strip()
        if not normalized_line:
            continue
        for pattern in (pipe_pattern, space_pattern):
            match = pattern.match(normalized_line)
            if not match:
                continue
            row_key = (
                match.group("name").strip(),
                match.group("spec").strip(),
                int(match.group("qty")),
                normalize_number(match.group("unit")),
                normalize_number(match.group("amount")),
            )
            if row_key in seen_rows:
                continue
            seen_rows.add(row_key)
            items.append(
                {
                    "name": row_key[0],
                    "spec": row_key[1],
                    "quantity": row_key[2],
                    "unit_price": row_key[3],
                    "amount": row_key[4],
                }
            )
            break

    return items


def build_title(template: str, vendor_name: str | None) -> str:
    vendor_prefix = f"{vendor_name} " if vendor_name else ""
    return f"{vendor_prefix}{template} 초안".strip()


def build_response(template: str, text: str, source_name: str | None = None) -> dict[str, Any]:
    request_department = extract_by_patterns(
        text,
        [
            r"(?:요청부서|신청부서|부서명|부서)\s*[:：]\s*(.+)",
            r"(?:요청부서|신청부서|부서명|부서)\s+(.+)",
            r"(?:요청부서|신청부서|부서명|부서)\s*\|\s*(.+)",
        ],
    )
    vendor = extract_by_patterns(
        text,
        [
            r"(?:공급자|상호|업체명|거래처)\s*[:：]\s*(.+)",
            r"(?:공급자|상호|업체명|거래처)\s+(.+)",
            r"(?:공급자|상호|업체명|거래처)\s*\|\s*(.+)",
        ],
    )
    supply_amount_raw = extract_by_patterns(
        text,
        [
            r"(?:공급가액|공급금액)\s*[:：]\s*([\d,]+)",
            r"(?:공급가액|공급금액)\s+([\d,]+)",
            r"(?:공급가액|공급금액)\s*\|\s*([\d,]+)",
        ],
    )
    vat_amount_raw = extract_by_patterns(
        text,
        [
            r"(?:부가세|VAT)\s*[:：]\s*([\d,]+)",
            r"(?:부가세|VAT)\s+([\d,]+)",
            r"(?:부가세|VAT)\s*\|\s*([\d,]+)",
        ],
    )
    total_amount_raw = extract_by_patterns(
        text,
        [
            r"(?:총합계|합계금액|총액)\s*[:：]\s*([\d,]+)",
            r"(?:총합계|합계금액|총액)\s+([\d,]+)",
            r"(?:총합계|합계금액|총액)\s*\|\s*([\d,]+)",
        ],
    )

    fields = {
        "request_department": request_department,
        "delivery_request_date": extract_named_date(
            text,
            [
                "납품요청일",
                "납품요청일자",
                "납기일",
                "납기",
                "납품일",
                "요청납기일",
                "희망납기일",
                "납품희망일",
                "요청일자",
            ],
        ),
        "vendor_name": vendor,
        "supply_amount": normalize_number(supply_amount_raw),
        "vat_amount": normalize_number(vat_amount_raw),
        "total_amount": normalize_number(total_amount_raw),
        "quote_date": extract_date(text),
    }

    line_items = extract_line_items(text)
    evidence = {
        "request_department": f"요청부서: {request_department}" if request_department else None,
        "delivery_request_date": f"납품요청일: {fields['delivery_request_date']}" if fields["delivery_request_date"] else None,
        "vendor_name": f"공급자: {vendor}" if vendor else None,
        "supply_amount": f"공급가액: {supply_amount_raw}" if supply_amount_raw else None,
        "vat_amount": f"부가세: {vat_amount_raw}" if vat_amount_raw else None,
        "total_amount": f"총합계: {total_amount_raw}" if total_amount_raw else None,
    }

    warnings: list[str] = []
    if fields["supply_amount"] is not None and fields["vat_amount"] is not None and fields["total_amount"] is not None:
        if fields["supply_amount"] + fields["vat_amount"] != fields["total_amount"]:
            warnings.append("공급가액 + 부가세와 총액이 일치하지 않습니다.")
    if not request_department:
        warnings.append("요청부서를 찾지 못했습니다.")
    if not fields["delivery_request_date"]:
        warnings.append("납품요청일을 찾지 못했습니다.")
    if not vendor:
        warnings.append("거래처명을 찾지 못했습니다.")
    if not line_items:
        warnings.append("품목 테이블을 찾지 못했습니다.")

    return {
        "template": template,
        "source_name": source_name,
        "document_type": "estimate",
        "raw_text_preview": text[:500],
        "title": build_title(template, vendor),
        "fields": fields,
        "line_items": line_items,
        "evidence": {key: value for key, value in evidence.items() if value},
        "warnings": warnings,
    }


def normalize_whitespace(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def parse_xlsx(payload: bytes) -> str:
    namespace = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    workbook_lines: list[str] = []

    with ZipFile(BytesIO(payload)) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for si in shared_root.findall("main:si", namespace):
                parts = [node.text or "" for node in si.findall(".//main:t", namespace)]
                shared_strings.append("".join(parts))

        sheet_names: dict[str, str] = {}
        if "xl/workbook.xml" in archive.namelist():
            workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
            for index, sheet in enumerate(workbook_root.findall("main:sheets/main:sheet", namespace), start=1):
                sheet_names[f"xl/worksheets/sheet{index}.xml"] = sheet.attrib.get("name", f"Sheet{index}")

        for name in sorted(item for item in archive.namelist() if item.startswith("xl/worksheets/sheet") and item.endswith(".xml")):
            sheet_root = ET.fromstring(archive.read(name))
            workbook_lines.append(f"[Sheet] {sheet_names.get(name, name.split('/')[-1])}")

            for row in sheet_root.findall(".//main:sheetData/main:row", namespace):
                values: list[str] = []
                for cell in row.findall("main:c", namespace):
                    cell_type = cell.attrib.get("t")
                    value_node = cell.find("main:v", namespace)
                    inline_node = cell.find("main:is", namespace)

                    cell_value = ""
                    if cell_type == "s" and value_node is not None and value_node.text is not None:
                        shared_index = int(value_node.text)
                        if 0 <= shared_index < len(shared_strings):
                            cell_value = shared_strings[shared_index]
                    elif inline_node is not None:
                        parts = [node.text or "" for node in inline_node.findall(".//main:t", namespace)]
                        cell_value = "".join(parts)
                    elif value_node is not None and value_node.text is not None:
                        cell_value = value_node.text

                    cell_value = cell_value.strip()
                    if cell_value:
                        values.append(cell_value)

                if values:
                    workbook_lines.append(" | ".join(values))

    if not workbook_lines:
        raise HTTPException(status_code=400, detail="엑셀 파일에서 읽을 수 있는 텍스트를 찾지 못했습니다.")

    return normalize_whitespace("\n".join(workbook_lines))


def parse_pdf(payload: bytes) -> str:
    extracted = extract_pdf(payload)
    if extracted.kind == "text":
        return extracted.text
    raise HTTPException(status_code=400, detail="스캔 PDF입니다. Vision 분석 경로를 사용해야 합니다.")

def legacy_parse_pdf_stream(payload: bytes) -> str:
    candidates: list[str] = []

    for stream_match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", payload, flags=re.DOTALL):
        stream_data = stream_match.group(1)

        decoded_options = [stream_data]
        try:
            decoded_options.append(zlib.decompress(stream_data))
        except zlib.error:
            pass

        for decoded in decoded_options:
            for match in re.finditer(rb"\((.*?)\)", decoded, flags=re.DOTALL):
                raw = match.group(1)
                raw = raw.replace(rb"\(", b"(").replace(rb"\)", b")").replace(rb"\\n", b"\n").replace(rb"\\r", b"\n")
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    try:
                        text = raw.decode("latin-1")
                    except UnicodeDecodeError:
                        continue

                text = re.sub(r"[^0-9A-Za-z가-힣\s:.,()/_-]", " ", text)
                text = re.sub(r"\s+", " ", text).strip()
                if len(text) >= 2:
                    candidates.append(text)

    merged = normalize_whitespace("\n".join(candidates))
    if not merged:
        raise HTTPException(
            status_code=400,
            detail="PDF에서 텍스트를 추출하지 못했습니다. 현재는 디지털 텍스트 PDF를 우선 지원하며, 스캔본 PDF는 OCR이 추가되어야 합니다.",
        )
    return merged


def decode_upload(file: UploadFile, payload: bytes) -> str:
    content_type = (file.content_type or "").lower()
    filename = (file.filename or "").lower()

    if content_type.startswith("text/") or filename.endswith((".txt", ".md", ".csv", ".log")):
        for encoding in ("utf-8", "cp949", "euc-kr"):
            try:
                return payload.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise HTTPException(status_code=400, detail="텍스트 파일 인코딩을 해석하지 못했습니다.")

    if filename.endswith(".xlsx"):
        return parse_xlsx(payload)

    if filename.endswith(".pdf") or content_type == "application/pdf":
        return parse_pdf(payload)

    raise HTTPException(
        status_code=400,
        detail="현재 데모는 txt, md, csv, log, xlsx, pdf 업로드를 지원합니다.",
    )


@router.post("/extract")
def extract_eapproval(request: ExtractRequest) -> dict[str, Any]:
    return build_response(request.template, request.document_text)


@router.post("/upload")
async def upload_eapproval(
    file: UploadFile = File(...),
    template: str = Form(...),
) -> dict[str, Any]:
    payload = await file.read()
    document_text = decode_upload(file, payload)
    return build_response(template, document_text, source_name=file.filename)
