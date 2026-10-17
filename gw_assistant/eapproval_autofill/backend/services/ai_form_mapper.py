"""Optional OpenAI Structured Outputs adapter."""
from __future__ import annotations
import json
import os
import base64
from typing import Any

class AIMapperError(RuntimeError): pass

def _value_schema(kind: str | None = None) -> dict[str, Any]:
    value_type = {"type": ["number", "integer", "null"]} if kind == "number" else {"type": ["string", "null"]}
    return {"type": "object", "properties": {"value": value_type, "confidence": {"type": "number"}, "sourceText": {"type": ["string", "null"]}}, "required": ["value", "confidence", "sourceText"], "additionalProperties": False}

def _output_schema(form: dict[str, Any]) -> dict[str, Any]:
    fields = {field["id"]: _value_schema(field.get("type")) for field in form["fields"]}
    tables = {}
    for table in form["tables"]:
        props = {column["id"]: {"type": ["string", "number", "integer", "null"]} for column in table["columns"]}
        tables[table["id"]] = {"type": "array", "items": {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}}
    return {"type": "object", "properties": {"formId": {"type": "string", "enum": [form["formId"]]}, "fields": {"type": "object", "properties": fields, "required": list(fields), "additionalProperties": False}, "tables": {"type": "object", "properties": tables, "required": list(tables), "additionalProperties": False}, "warnings": {"type": "array", "items": {"type": "string"}}}, "required": ["formId", "fields", "tables", "warnings"], "additionalProperties": False}

def map_with_gpt(document_text: str, form: dict[str, Any]) -> dict[str, Any]:
    if not os.getenv("OPENAI_API_KEY"): raise AIMapperError("OPENAI_API_KEY가 설정되지 않았습니다.")
    try: from openai import OpenAI
    except ImportError as error: raise AIMapperError("openai 패키지가 설치되지 않았습니다.") from error
    instructions = "Map only facts explicitly present in the source to the supplied form. Never infer missing account data, contacts, dates, prices, quantities, names, departments, or titles. Return null and confidence 0 when absent; sourceText is an exact excerpt for each non-null value."
    try:
        response = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=25.0).responses.create(model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"), instructions=instructions, input=f"FORM SCHEMA:\n{json.dumps(form, ensure_ascii=False)}\n\nSOURCE DOCUMENT:\n{document_text[:30000]}", text={"format": {"type": "json_schema", "name": "eapproval_mapping", "strict": True, "schema": _output_schema(form)}})
        if not response.output_text: raise AIMapperError("GPT가 구조화된 결과를 반환하지 않았습니다.")
        return json.loads(response.output_text)
    except (AIMapperError, json.JSONDecodeError): raise
    except Exception as error: raise AIMapperError(f"GPT 문서 분석 호출에 실패했습니다: {error}") from error

def map_images_with_gpt(page_images: list[bytes], form: dict[str, Any]) -> dict[str, Any]:
    """Vision route for scan PDFs. It never fabricates OCR when no Vision API is available."""
    if not os.getenv("OPENAI_API_KEY"): raise AIMapperError("스캔 PDF 분석에는 OPENAI_API_KEY가 필요합니다.")
    try: from openai import OpenAI
    except ImportError as error: raise AIMapperError("openai 패키지가 설치되지 않았습니다.") from error
    content = [{"type": "input_text", "text": "Read these scanned PDF pages and map only explicitly visible facts to this form. Never infer missing values; return null with confidence 0. FORM SCHEMA:\n" + json.dumps(form, ensure_ascii=False)}]
    content.extend({"type": "input_image", "image_url": f"data:image/png;base64,{base64.b64encode(image).decode('ascii')}", "detail": "high"} for image in page_images)
    try:
        response = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=45.0).responses.create(model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"), input=[{"role": "user", "content": content}], text={"format": {"type": "json_schema", "name": "eapproval_mapping", "strict": True, "schema": _output_schema(form)}})
        if not response.output_text: raise AIMapperError("Vision 분석이 구조화된 결과를 반환하지 않았습니다.")
        return json.loads(response.output_text)
    except (AIMapperError, json.JSONDecodeError): raise
    except Exception as error: raise AIMapperError(f"GPT Vision 분석 호출에 실패했습니다: {error}") from error

def recommend_forms(document_text: str, forms: list[dict[str, Any]]) -> dict[str, Any]:
    """Rank schemas only; the user always makes the final selection."""
    if not os.getenv("OPENAI_API_KEY"): raise AIMapperError("OPENAI_API_KEY가 설정되지 않았습니다.")
    try: from openai import OpenAI
    except ImportError as error: raise AIMapperError("openai 패키지가 설치되지 않았습니다.") from error
    properties = {form["formId"]: {"type": "object", "properties": {"formId": {"type": "string", "enum": [form["formId"]]}, "confidence": {"type": "number"}, "reason": {"type": "string"}}, "required": ["formId", "confidence", "reason"], "additionalProperties": False} for form in forms}
    schema = {"type": "object", "properties": {"recommendations": {"type": "array", "items": {"anyOf": list(properties.values())}}}, "required": ["recommendations"], "additionalProperties": False}
    prompt = "Rank relevant approval forms for this source document. This is only a user-facing priority indicator, not a factual probability. Do not select a form automatically. Give concise evidence-based Korean reasons.\nFORMS:\n" + json.dumps([{key: form.get(key) for key in ("formId", "formName", "description", "documentHints")} for form in forms], ensure_ascii=False) + "\nDOCUMENT:\n" + document_text[:30000]
    try:
        response = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=25.0).responses.create(model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"), instructions="Recommend forms only from document evidence. Return the requested JSON.", input=prompt, text={"format": {"type": "json_schema", "name": "form_recommendations", "strict": True, "schema": schema}})
        if not response.output_text: raise AIMapperError("GPT가 추천 결과를 반환하지 않았습니다.")
        return json.loads(response.output_text)
    except (AIMapperError, json.JSONDecodeError): raise
    except Exception as error: raise AIMapperError(f"GPT 양식 추천 호출에 실패했습니다: {error}") from error

def recommend_forms_with_images(images: list[bytes], forms: list[dict[str, Any]]) -> dict[str, Any]:
    """Vision recommendation for receipts, business cards, and scanned documents."""
    if not os.getenv("OPENAI_API_KEY"): raise AIMapperError("OPENAI_API_KEY가 설정되지 않았습니다.")
    try: from openai import OpenAI
    except ImportError as error: raise AIMapperError("openai 패키지가 설치되지 않았습니다.") from error
    alternatives = [{"type": "object", "properties": {"formId": {"type": "string", "enum": [form["formId"]]}, "confidence": {"type": "number"}, "reason": {"type": "string"}}, "required": ["formId", "confidence", "reason"], "additionalProperties": False} for form in forms]
    schema = {"type": "object", "properties": {"recommendations": {"type": "array", "items": {"anyOf": alternatives}}}, "required": ["recommendations"], "additionalProperties": False}
    prompt = "Analyze these document images and recommend relevant approval forms only as ranked candidates. Do not automatically choose one. Reasons must be concise Korean and based on visible evidence. FORMS:\n" + json.dumps([{key: form.get(key) for key in ("formId", "formName", "description", "documentHints")} for form in forms], ensure_ascii=False)
    content = [{"type": "input_text", "text": prompt}]
    content.extend({"type": "input_image", "image_url": f"data:image/png;base64,{base64.b64encode(image).decode('ascii')}", "detail": "high"} for image in images)
    try:
        response = OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=45.0).responses.create(model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"), input=[{"role": "user", "content": content}], text={"format": {"type": "json_schema", "name": "vision_form_recommendations", "strict": True, "schema": schema}})
        if not response.output_text: raise AIMapperError("Vision이 추천 결과를 반환하지 않았습니다.")
        return json.loads(response.output_text)
    except (AIMapperError, json.JSONDecodeError): raise
    except Exception as error: raise AIMapperError(f"GPT Vision 양식 추천 호출에 실패했습니다: {error}") from error
