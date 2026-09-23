"""Reliable PDF classification and extraction using PyMuPDF, not PDF stream regexes."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class PdfDocument:
    kind: str  # text or scanned
    text: str
    page_images: list[bytes]
    page_count: int

def extract_pdf(payload: bytes, minimum_text_chars: int = 40) -> PdfDocument:
    try:
        import pymupdf as fitz
    except ImportError as error:
        raise RuntimeError("PyMuPDF가 설치되지 않았습니다. requirements.txt를 설치해주세요.") from error
    try:
        pdf = fitz.open(stream=payload, filetype="pdf")
    except Exception as error:
        raise ValueError("유효한 PDF 파일을 열지 못했습니다.") from error
    try:
        texts = [page.get_text("text") for page in pdf]
        text = "\n".join(part.strip() for part in texts if part.strip()).strip()
        if len("".join(text.split())) >= minimum_text_chars:
            return PdfDocument(kind="text", text=text, page_images=[], page_count=len(pdf))
        # Render only when text extraction genuinely indicates a scan/image PDF.
        images = [page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).tobytes("png") for page in list(pdf)[:10]]
        return PdfDocument(kind="scanned", text=text, page_images=images, page_count=len(pdf))
    finally:
        pdf.close()
