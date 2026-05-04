from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..config import get_settings
from .dev_planner_service import (
    create_dev_proposal,
    ensure_default_dev_project,
    get_dev_project,
    update_dev_proposal_code_preview,
)


APP_ROOT = Path(__file__).resolve().parents[2].resolve()
MAX_CONTEXT_FILES = 3
MAX_FILE_CHARS = 18000
AI_TIMEOUT_SECONDS = 45


def generate_ai_dev_proposal(payload: dict[str, Any]) -> dict[str, Any]:
    request_text = str(payload.get("request") or "").strip()
    if not request_text:
        raise ValueError("request 값이 필요합니다.")

    settings = get_settings()
    if not settings.has_openai:
        raise ValueError("OPENAI_API_KEY 설정이 필요합니다.")

    project_id = int(payload.get("project_id") or ensure_default_dev_project()["id"])
    project = get_dev_project(project_id)
    root = _safe_project_root(project["root_path"])
    context_files = _select_context_files(root, request_text, payload.get("candidate_files"))
    if not context_files:
        raise ValueError("AI 제안에 사용할 안전한 텍스트 파일을 찾지 못했습니다.")

    ai_payload = _call_openai_for_proposal(settings.openai_api_key, settings.openai_model, request_text, root, context_files)
    primary_file = _normalize_ai_file(ai_payload.get("primary_file"), context_files)
    generated_code = str(ai_payload.get("generated_code") or "").strip()
    if not generated_code:
        raise ValueError("AI가 코드 미리보기를 생성하지 못했습니다.")

    proposal = create_dev_proposal(
        {
            "project_id": project_id,
            "title": str(ai_payload.get("title") or "Agent 03 AI 개발 제안")[:240],
            "summary": str(ai_payload.get("summary") or request_text),
            "reason": _build_reason(ai_payload),
            "change_type": str(ai_payload.get("change_type") or "modify"),
            "affected_files": [item["path"] for item in context_files],
            "risk_level": str(ai_payload.get("risk_level") or "medium"),
        }
    )
    return update_dev_proposal_code_preview(proposal["id"], primary_file, generated_code)


def _call_openai_for_proposal(
    api_key: str | None,
    model: str,
    request_text: str,
    root: Path,
    context_files: list[dict[str, str]],
) -> dict[str, Any]:
    try:
        from openai import OpenAI
    except ImportError as error:
        raise ValueError("openai 패키지가 설치되어 있지 않습니다.") from error

    file_context = "\n\n".join(
        f"--- FILE: {item['path']} ---\n{item['content']}"
        for item in context_files
    )
    allowed_files = [item["path"] for item in context_files]
    prompt = (
        "You are Agent 03, a SAFE junior developer inside GyuOS.\n"
        "You suggest code, but you NEVER apply changes.\n"
        "Return JSON only. No markdown fences.\n"
        "The user is the senior engineer and must approve everything.\n"
        "Rules:\n"
        "- Work only inside apps/personal_life.\n"
        "- Choose exactly one primary_file from allowed_files.\n"
        "- generated_code must be the full replacement text for primary_file only.\n"
        "- Do not delete existing features or large unrelated functions.\n"
        "- Do not modify DB schema, payments, publishing, deleting, or external transfer behavior.\n"
        "- If the request is broad, make the smallest useful UI/service proposal.\n"
        "- Korean UI text should stay Korean.\n"
        "- risk_level must be low, medium, or high.\n"
        "- change_type must be add, modify, or refactor.\n"
        "JSON keys: title, summary, proposal_points, flow_steps, change_type, risk_level, primary_file, generated_code.\n"
        f"Project root: {root}\n"
        f"Allowed files: {json.dumps(allowed_files, ensure_ascii=False)}\n"
        f"User request: {request_text}\n\n"
        f"File context:\n{file_context}\n"
    )

    client = OpenAI(api_key=api_key, timeout=AI_TIMEOUT_SECONDS)
    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": [{"type": "input_text", "text": prompt}]},
        ],
    )
    raw = getattr(response, "output_text", "") or ""
    try:
        data = json.loads(_strip_code_fence(raw))
    except json.JSONDecodeError as error:
        raise ValueError("AI 응답을 JSON으로 해석하지 못했습니다.") from error
    if not isinstance(data, dict):
        raise ValueError("AI 응답 형식이 올바르지 않습니다.")
    return data


def _select_context_files(root: Path, request_text: str, candidate_files: Any) -> list[dict[str, str]]:
    requested = _normalize_file_list(candidate_files)
    if requested:
        paths = [_resolve_safe_file(root, item) for item in requested]
    else:
        paths = _rank_project_files(root, request_text)

    selected: list[dict[str, str]] = []
    for path in paths:
        if len(selected) >= MAX_CONTEXT_FILES:
            break
        if not _is_text_target(path):
            continue
        try:
            content = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            continue
        selected.append(
            {
                "path": str(path.relative_to(root)).replace("\\", "/"),
                "content": content[:MAX_FILE_CHARS],
            }
        )
    return selected


def _rank_project_files(root: Path, request_text: str) -> list[Path]:
    lowered = request_text.lower()
    files = [path for path in root.rglob("*") if path.is_file() and _is_text_target(path)]
    scored: list[tuple[int, str, Path]] = []
    for path in files:
        relative = str(path.relative_to(root)).replace("\\", "/")
        haystack = relative.lower()
        score = 0
        for token in _request_tokens(lowered):
            if token in haystack:
                score += 5
        if "report" in lowered or "제안" in lowered or "agent 03" in lowered or "agent3" in lowered:
            if relative.endswith("agent_report_center.html"):
                score += 50
            if relative.endswith("dev_planner_service.py"):
                score += 35
            if relative.endswith("routes.py"):
                score += 20
        if "money" in lowered or "돈" in lowered:
            if "money_core" in haystack:
                score += 40
        if "voice" in lowered or "음성" in lowered:
            if "wake_listener" in haystack or "natural_language" in haystack:
                score += 40
        scored.append((score, relative, path))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [path for _, _, path in scored[:MAX_CONTEXT_FILES]]


def _build_reason(ai_payload: dict[str, Any]) -> str:
    points = ai_payload.get("proposal_points")
    steps = ai_payload.get("flow_steps")
    point_lines = _lines_from_ai_list(points) or ["요청 범위에 맞춰 가장 작은 안전 변경안을 제안합니다."]
    step_lines = _lines_from_ai_list(steps) or [
        "코드 미리보기를 확인합니다.",
        "diff 미리보기를 확인합니다.",
        "사용자가 승인하면 작업 큐에 등록합니다.",
        "자동 파일 적용은 하지 않습니다.",
    ]
    return (
        "제안 내용:\n"
        + "\n".join(f"- {line}" for line in point_lines)
        + "\n\n진행 방식:\n"
        + "\n".join(f"{index + 1}. {line}" for index, line in enumerate(step_lines))
    )


def _normalize_ai_file(primary_file: Any, context_files: list[dict[str, str]]) -> str:
    allowed = {item["path"] for item in context_files}
    candidate = str(primary_file or "").replace("\\", "/").strip()
    if candidate in allowed:
        return candidate
    return context_files[0]["path"]


def _safe_project_root(root_path: str) -> Path:
    root = Path(root_path).resolve()
    if root != APP_ROOT and APP_ROOT not in root.parents:
        raise ValueError("Agent 03 AI proposals are restricted to apps/personal_life/*.")
    return root


def _resolve_safe_file(root: Path, file_path: str) -> Path:
    candidate = (root / file_path).resolve()
    if candidate != APP_ROOT and APP_ROOT not in candidate.parents:
        raise ValueError(f"File outside allowed scope: {file_path}")
    return candidate


def _is_text_target(path: Path) -> bool:
    if any(part.startswith(".") or part in {"__pycache__", "node_modules", "venv"} for part in path.parts):
        return False
    return path.suffix.lower() in {".py", ".html", ".css", ".js", ".md", ".bat", ".toml", ".json"}


def _request_tokens(text: str) -> list[str]:
    return [token for token in re.split(r"[^0-9a-zA-Z가-힣_]+", text) if len(token) >= 2]


def _normalize_file_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip().replace("\\", "/") for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip().replace("\\", "/") for item in value if str(item).strip()]
    return []


def _lines_from_ai_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [line.strip().lstrip("-").strip() for line in value.splitlines() if line.strip()]
    return []


def _strip_code_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    return cleaned
