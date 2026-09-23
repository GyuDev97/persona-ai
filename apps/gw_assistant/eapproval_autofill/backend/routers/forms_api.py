"""Thin HTTP API layer for the schema-driven document pipeline."""
from __future__ import annotations

from typing import Any
import os
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from backend.forms.registry import get_all_schemas, get_schema, list_forms
from backend.services.form_mapper import map_source_to_form
from backend.services.ai_form_mapper import AIMapperError, map_images_with_gpt, recommend_forms, recommend_forms_with_images
from backend.services.result_validation import validate_mapping
from backend.services.document_extractor import InvalidDocument, UnsupportedDocument, extract_document

router = APIRouter()
analysis_sessions: dict[str, Any] = {}


class ExtractRequest(BaseModel):
    form_id: str
    document_text: str


def _extract_upload(filename: str, payload: bytes) -> Any:
    if len(payload) > 25 * 1024 * 1024: raise HTTPException(413, "파일 크기가 25MB 제한을 초과했습니다.")
    return extract_document(filename, payload)


def _map_document(document: Any, form_id: str, source_name: str) -> dict[str, Any]:
    if document.images:
        definition = get_schema(form_id)
        result = validate_mapping(map_images_with_gpt(document.images, definition), definition)
    else:
        result = map_source_to_form(form_id, document.text, source_name)
    result.update({"sourceName": source_name, "documentKind": document.kind, "sourceMetadata": document.metadata})
    return result


@router.get("/forms")
def forms() -> list[dict[str, str]]:
    return list_forms()


@router.get("/ai-status")
def ai_status() -> dict[str, Any]:
    """Expose configuration state only—never expose the API key itself."""
    return {"configured": bool(os.getenv("OPENAI_API_KEY")), "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini")}


@router.get("/forms/{form_id}")
def schema(form_id: str) -> dict[str, Any]:
    try:
        return get_schema(form_id)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error


@router.post("/extract")
def extract(request: ExtractRequest) -> dict[str, Any]:
    try:
        return map_source_to_form(request.form_id, request.document_text)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.post("/upload")
async def upload(file: UploadFile = File(...), form_id: str = Form(...)) -> dict[str, Any]:
    try:
        payload = await file.read()
        return _map_document(_extract_upload(file.filename or "", payload), form_id, file.filename or "")
    except UnsupportedDocument as error:
        raise HTTPException(415, str(error)) from error
    except InvalidDocument as error:
        raise HTTPException(400, str(error)) from error


@router.post("/recommend")
async def recommend(file: UploadFile = File(...)) -> dict[str, Any]:
    try:
        document = _extract_upload(file.filename or "", await file.read())
        result = recommend_forms_with_images(document.images, get_all_schemas()) if document.images else recommend_forms(document.text, get_all_schemas())
        session_id = str(uuid4()); analysis_sessions[session_id] = (document, file.filename or "")
        result.update({"analysisId": session_id, "documentKind": document.kind})
        return result
    except (UnsupportedDocument, InvalidDocument) as error:
        raise HTTPException(415, str(error)) from error
    except AIMapperError as error:
        raise HTTPException(422, f"AI 양식 추천을 실행할 수 없습니다: {error}") from error


@router.post("/recommend/{analysis_id}/apply/{form_id}")
def apply_recommendation(analysis_id: str, form_id: str) -> dict[str, Any]:
    try: document, filename = analysis_sessions[analysis_id]
    except KeyError as error: raise HTTPException(404, "분석 세션이 만료되었습니다. 파일을 다시 등록해 주세요.") from error
    try: return _map_document(document, form_id, filename)
    except AIMapperError as error: raise HTTPException(422, f"AI 자동입력을 실행할 수 없습니다: {error}") from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
