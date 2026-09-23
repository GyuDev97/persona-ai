"""Format adapters that convert uploads into a common DocumentData payload."""
from __future__ import annotations
import csv, io, mimetypes, zipfile
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any
import xml.etree.ElementTree as ET

from backend.services.pdf_extraction import extract_pdf

class UnsupportedDocument(ValueError): pass
class InvalidDocument(ValueError): pass

@dataclass
class DocumentData:
    kind: str
    text: str = ""
    tables: list[dict[str, Any]] = field(default_factory=list)
    images: list[bytes] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

def _type(filename: str, payload: bytes) -> str:
    extension = PurePath(filename).suffix.lower()
    if payload.startswith(b"%PDF-"): return "pdf"
    if payload.startswith(b"\x89PNG\r\n\x1a\n"): return "image"
    if payload.startswith(b"\xff\xd8\xff"): return "image"
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP": return "image"
    if payload.startswith(b"\xd0\xcf\x11\xe0"): return "hwp" if extension == ".hwp" else "doc"
    if payload.startswith(b"PK\x03\x04"):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = set(archive.namelist())
            if "[Content_Types].xml" in names:
                content = archive.read("[Content_Types].xml")
                if b"spreadsheetml" in content: return "xlsx"
                if b"wordprocessingml" in content: return "docx"
            if any(name.startswith("Contents/") for name in names): return "hwpx"
        return "zip"
    if extension in {".csv"}: return "csv"
    if extension in {".txt", ".md", ".log"}: return "text"
    if extension == ".xls": return "xls"
    return "unknown"

def _decode(payload: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try: return payload.decode(encoding)
        except UnicodeDecodeError: continue
    raise InvalidDocument("텍스트 인코딩을 해석하지 못했습니다.")

def _table_text(tables: list[dict[str, Any]]) -> str:
    output = []
    for table in tables:
        output.append(f"[Table] {table['name']}")
        output.extend(" | ".join("" if value is None else str(value) for value in row) for row in table["rows"])
    return "\n".join(output)

def _excel(payload: bytes, kind: str) -> DocumentData:
    try:
        if kind == "xlsx":
            import openpyxl
            book = openpyxl.load_workbook(io.BytesIO(payload), data_only=True, read_only=True)
            tables = [{"name": sheet.title, "rows": [list(row) for row in sheet.iter_rows(values_only=True)]} for sheet in book.worksheets]
        else:
            import xlrd
            book = xlrd.open_workbook(file_contents=payload)
            tables = [{"name": sheet.name, "rows": [sheet.row_values(index) for index in range(sheet.nrows)]} for sheet in book.sheets()]
    except Exception as error: raise InvalidDocument(f"Excel 파일을 읽지 못했습니다: {error}") from error
    return DocumentData(kind=kind, text=_table_text(tables), tables=tables)

def _docx(payload: bytes) -> DocumentData:
    try:
        from docx import Document
        document = Document(io.BytesIO(payload))
        tables = [{"name": f"table-{index + 1}", "rows": [[cell.text for cell in row.cells] for row in table.rows]} for index, table in enumerate(document.tables)]
        text = "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text)
        return DocumentData(kind="docx", text="\n".join(filter(None, [text, _table_text(tables)])), tables=tables)
    except Exception as error: raise InvalidDocument(f"DOCX 파일을 읽지 못했습니다: {error}") from error

def _hwpx(payload: bytes) -> DocumentData:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            texts = []
            for name in archive.namelist():
                if name.endswith(".xml"):
                    root = ET.fromstring(archive.read(name)); texts.extend(node.strip() for node in root.itertext() if node.strip())
        return DocumentData(kind="hwpx", text="\n".join(texts))
    except Exception as error: raise InvalidDocument(f"HWPX 파일을 읽지 못했습니다: {error}") from error

def extract_document(filename: str, payload: bytes) -> DocumentData:
    if not payload: raise InvalidDocument("내용이 없는 파일입니다.")
    kind = _type(filename, payload); mime = mimetypes.guess_type(filename)[0]
    if kind == "pdf":
        pdf = extract_pdf(payload)
        return DocumentData(kind="scanned_pdf" if pdf.kind == "scanned" else "text_pdf", text=pdf.text, images=pdf.page_images, metadata={"pages": pdf.page_count, "mime": mime})
    if kind == "image": return DocumentData(kind="image", images=[payload], metadata={"mime": mime})
    if kind in {"xlsx", "xls"}: return _excel(payload, kind)
    if kind == "csv":
        rows = list(csv.reader(io.StringIO(_decode(payload)))); tables = [{"name": "CSV", "rows": rows}]
        return DocumentData(kind="csv", text=_table_text(tables), tables=tables)
    if kind == "text": return DocumentData(kind="text", text=_decode(payload))
    if kind == "docx": return _docx(payload)
    if kind == "hwpx": return _hwpx(payload)
    if kind in {"doc", "hwp"}: raise UnsupportedDocument(f"{kind.upper()}는 현재 실행환경에 안정적인 변환기가 없어 지원하지 않습니다. DOCX 또는 HWPX로 변환해 주세요.")
    raise UnsupportedDocument("현재 분석을 지원하지 않는 파일 형식입니다.")
