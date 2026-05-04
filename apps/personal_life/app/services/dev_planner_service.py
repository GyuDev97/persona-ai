from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..storage.database import execute, fetch_all, fetch_one
from .agent_task_service import create_agent_task
from .diff_preview_service import build_diff_preview, summarize_diff


APP_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROJECT_NAME = "GyuOS"
ALLOWED_ROOT = APP_ROOT.resolve()
ALLOWED_CHANGE_TYPES = {"add", "modify", "refactor"}
ALLOWED_RISK_LEVELS = {"low", "medium", "high"}


def ensure_default_dev_project() -> dict[str, Any]:
    existing = fetch_one("SELECT * FROM agent_dev_projects WHERE root_path = ?", (str(APP_ROOT),))
    if existing:
        return _project_payload(existing)
    project_id = execute(
        """
        INSERT INTO agent_dev_projects (name, root_path, description, stack, status)
        VALUES (?, ?, ?, ?, 'active')
        """,
        (
            DEFAULT_PROJECT_NAME,
            str(APP_ROOT),
            "Local personal AI OS project",
            "Python, FastAPI, MariaDB, HTML, CSS, JavaScript",
        ),
    )
    return get_dev_project(project_id)


def create_dev_project(payload: dict[str, Any]) -> dict[str, Any]:
    name = _required_text(payload.get("name"), "name")
    root_path = _required_text(payload.get("root_path"), "root_path")
    _ensure_allowed_project_root(root_path)
    project_id = execute(
        """
        INSERT INTO agent_dev_projects (name, root_path, description, stack, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            name,
            root_path,
            str(payload.get("description") or ""),
            str(payload.get("stack") or ""),
            str(payload.get("status") or "active"),
        ),
    )
    return get_dev_project(project_id)


def list_dev_projects() -> list[dict[str, Any]]:
    ensure_default_dev_project()
    rows = fetch_all(
        """
        SELECT *
        FROM agent_dev_projects
        ORDER BY created_at ASC, id ASC
        """
    )
    return [_project_payload(row) for row in rows]


def get_dev_project(project_id: int) -> dict[str, Any]:
    row = fetch_one("SELECT * FROM agent_dev_projects WHERE id = ?", (project_id,))
    if row is None:
        raise ValueError("Dev project not found")
    return _project_payload(row)


def create_dev_proposal(payload: dict[str, Any]) -> dict[str, Any]:
    project_id = int(payload.get("project_id") or ensure_default_dev_project()["id"])
    project = get_dev_project(project_id)
    affected_files = _normalize_file_list(payload.get("affected_files") or payload.get("target_files") or [])
    _ensure_allowed_files(project["root_path"], affected_files)
    change_type = _normalize_change_type(payload.get("change_type"))
    risk_level = _normalize_risk_level(payload.get("risk_level"), affected_files, change_type)
    code_preview = str(payload.get("code_preview") or "")
    diff_preview = str(payload.get("diff_preview") or "")
    proposal_id = execute(
        """
        INSERT INTO agent_dev_proposals (
            project_id, title, summary, reason, change_type, affected_files, target_files,
            risk_level, code_preview, diff_preview, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
        """,
        (
            project_id,
            _required_text(payload.get("title"), "title"),
            str(payload.get("summary") or ""),
            str(payload.get("reason") or ""),
            change_type,
            json.dumps(affected_files, ensure_ascii=False),
            json.dumps(affected_files, ensure_ascii=False),
            risk_level,
            code_preview,
            diff_preview,
        ),
    )
    return get_dev_proposal(proposal_id)


def list_dev_proposals(status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    ensure_default_dev_project()
    if status:
        rows = fetch_all(
            """
            SELECT p.*, pr.name AS project_name, pr.root_path
            FROM agent_dev_proposals p
            JOIN agent_dev_projects pr ON pr.id = p.project_id
            WHERE p.status = ?
            ORDER BY p.created_at DESC, p.id DESC
            LIMIT ?
            """,
            (status, limit),
        )
    else:
        rows = fetch_all(
            """
            SELECT p.*, pr.name AS project_name, pr.root_path
            FROM agent_dev_proposals p
            JOIN agent_dev_projects pr ON pr.id = p.project_id
            ORDER BY p.created_at DESC, p.id DESC
            LIMIT ?
            """,
            (limit,),
        )
    return [_proposal_payload(row) for row in rows]


def get_dev_proposal(proposal_id: int) -> dict[str, Any]:
    row = fetch_one(
        """
        SELECT p.*, pr.name AS project_name, pr.root_path
        FROM agent_dev_proposals p
        JOIN agent_dev_projects pr ON pr.id = p.project_id
        WHERE p.id = ?
        """,
        (proposal_id,),
    )
    if row is None:
        raise ValueError("Dev proposal not found")
    return _proposal_payload(row)


def scan_dev_project(project_id: int) -> dict[str, Any]:
    project = get_dev_project(project_id)
    root = Path(project["root_path"])
    findings = _scan_project_root(root)
    proposal = _proposal_from_findings(project, findings)
    return {
        "project": project,
        "findings": findings,
        "proposal": proposal,
    }


def approve_dev_proposal(proposal_id: int) -> dict[str, Any]:
    proposal = get_dev_proposal(proposal_id)
    if proposal["status"] not in {"pending", "held"}:
        return proposal

    command_text = _build_codex_command(proposal)
    task = create_agent_task(
        command_text=command_text,
        task_type="coding_app_update",
        search_query=f"dev_proposal_id={proposal_id}",
        source="agent3-dev-planner",
        payload={
            "dev_proposal_id": proposal_id,
            "affected_files": proposal.get("affected_files") or [],
            "code_preview": proposal.get("code_preview") or "",
            "diff_preview": proposal.get("diff_preview") or "",
            "safety": "preview_only_no_file_write",
        },
    )
    execute(
        """
        UPDATE agent_dev_proposals
        SET status = 'approved', approved_at = ?, codex_task_id = ?
        WHERE id = ?
        """,
        (_now(), task.id, proposal_id),
    )
    return get_dev_proposal(proposal_id)


def update_dev_proposal_code_preview(
    proposal_id: int,
    affected_file: str,
    generated_code: str,
) -> dict[str, Any]:
    proposal = get_dev_proposal(proposal_id)
    project = get_dev_project(proposal["project_id"])
    affected_files = _normalize_file_list([affected_file])
    _ensure_allowed_files(project["root_path"], affected_files)
    if not generated_code.strip():
        raise ValueError("generated_code 값이 필요합니다.")

    target_path = _resolve_project_file(project["root_path"], affected_file)
    try:
        original = target_path.read_text(encoding="utf-8-sig") if target_path.exists() else ""
    except UnicodeDecodeError as error:
        raise ValueError(f"Text preview is only supported for UTF-8 compatible files: {affected_file}") from error
    diff_preview = build_diff_preview(original, generated_code, affected_file)
    diff_summary = summarize_diff(original, generated_code)
    risk_level = _normalize_risk_level(proposal.get("risk_level"), affected_files, proposal.get("change_type"))
    if diff_summary["removed_lines"] > 40 or diff_summary["changed_sections"] > 8:
        risk_level = "high"

    merged_files = _merge_file_lists(proposal.get("affected_files") or [], affected_files)
    execute(
        """
        UPDATE agent_dev_proposals
        SET affected_files = ?, target_files = ?, code_preview = ?, diff_preview = ?, risk_level = ?
        WHERE id = ?
        """,
        (
            json.dumps(merged_files, ensure_ascii=False),
            json.dumps(merged_files, ensure_ascii=False),
            generated_code,
            diff_preview,
            risk_level,
            proposal_id,
        ),
    )
    return get_dev_proposal(proposal_id)


def update_dev_proposal_status(proposal_id: int, status: str) -> dict[str, Any]:
    allowed = {"pending", "approved", "held", "rejected", "completed"}
    if status not in allowed:
        raise ValueError("Unsupported proposal status")
    completed_at = _now() if status == "completed" else None
    execute(
        """
        UPDATE agent_dev_proposals
        SET status = ?, completed_at = COALESCE(?, completed_at)
        WHERE id = ?
        """,
        (status, completed_at, proposal_id),
    )
    return get_dev_proposal(proposal_id)


def _scan_project_root(root: Path) -> dict[str, Any]:
    if not root.exists():
        return {"exists": False, "summary": "프로젝트 경로를 찾지 못했습니다.", "target_files": []}
    _ensure_allowed_project_root(str(root))

    files = [path for path in root.rglob("*") if path.is_file() and _is_scan_target(path)]
    target_files = [str(path.relative_to(root)) for path in files[:12]]
    frontend_files = [str(path.relative_to(root)) for path in files if path.suffix.lower() in {".html", ".css", ".js"}]
    backend_files = [str(path.relative_to(root)) for path in files if path.suffix.lower() == ".py"]
    has_frontend = any(path.name.endswith(".html") or path.suffix in {".js", ".css"} for path in files)
    has_backend = any(path.suffix == ".py" for path in files)
    summary_bits = []
    if has_backend:
        summary_bits.append("Python 백엔드")
    if has_frontend:
        summary_bits.append("프론트엔드")
    summary = ", ".join(summary_bits) or "일반 프로젝트"
    return {
        "exists": True,
        "summary": f"{summary} 파일 {len(files)}개를 확인했습니다.",
        "target_files": target_files,
        "backend_count": len(backend_files),
        "frontend_count": len(frontend_files),
    }


def _proposal_from_findings(project: dict[str, Any], findings: dict[str, Any]) -> dict[str, Any]:
    if not findings.get("exists"):
        return create_dev_proposal(
            {
                "project_id": project["id"],
                "title": f"{project['name']} 프로젝트 경로 점검 필요",
                "summary": findings["summary"],
                "reason": "등록된 프로젝트 경로가 현재 PC에서 확인되지 않습니다.",
                "change_type": "modify",
                "affected_files": [],
                "risk_level": "low",
            }
        )

    summary = (
        f"{findings['summary']} 우선 Agent 03 안전 승인 흐름, Report Center 표시, "
        "작업 큐 연결부를 중심으로 개선 후보를 정리합니다."
    )
    reason = (
        "제안 내용:\n"
        "- Agent 03 제안 카드에서 승인 전에 목적, 영향 파일, 위험도를 더 명확히 보여줍니다.\n"
        "- 코드가 필요한 경우 파일에 바로 쓰지 않고 code_preview와 diff_preview만 생성합니다.\n"
        "- 승인 후에도 실제 파일 수정이 아니라 coding_app_update 작업 큐에 검토 요청만 등록합니다.\n"
        "- 영향 파일은 apps/personal_life 내부로 제한하고, runner/API/DB 관련 변경은 high risk로 표시합니다.\n\n"
        "진행 방식:\n"
        "1. 대상 파일을 읽고 현재 구조를 분석합니다.\n"
        "2. 변경 후보를 텍스트와 diff 미리보기로 만듭니다.\n"
        "3. 사용자가 코드 보기와 diff 보기를 확인합니다.\n"
        "4. 승인 시 다음 작업 큐에 넘기며, 자동 적용은 하지 않습니다."
    )
    return create_dev_proposal(
        {
            "project_id": project["id"],
            "title": f"{project['name']} 개선 후보 점검",
            "summary": summary,
            "reason": reason,
            "change_type": "modify",
            "affected_files": findings.get("target_files") or [],
            "risk_level": "low",
        }
    )


def _build_codex_command(proposal: dict[str, Any]) -> str:
    files = ", ".join(proposal.get("affected_files") or proposal.get("target_files") or []) or "검토 후 결정"
    return (
        f"Agent 03 approved dev proposal #{proposal['id']}: {proposal['title']}\n\n"
        f"Project: {proposal.get('project_name')} ({proposal.get('root_path')})\n"
        f"Change type: {proposal.get('change_type')}\n"
        f"Risk level: {proposal.get('risk_level')}\n"
        f"Summary: {proposal.get('summary')}\n"
        f"Reason: {proposal.get('reason')}\n"
        f"Target files: {files}\n\n"
        "Code preview and diff preview are stored in the proposal. "
        "Keep existing functionality. Do not delete features. Do not apply changes without explicit user approval."
    )


def _project_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "name": row.get("name"),
        "root_path": row.get("root_path"),
        "description": row.get("description") or "",
        "stack": row.get("stack") or "",
        "status": row.get("status") or "active",
        "created_at": _stringify(row.get("created_at")),
        "updated_at": _stringify(row.get("updated_at")),
    }


def _proposal_payload(row: dict[str, Any]) -> dict[str, Any]:
    try:
        target_files = json.loads(row.get("target_files") or "[]")
    except json.JSONDecodeError:
        target_files = []
    try:
        affected_files = json.loads(row.get("affected_files") or "[]")
    except json.JSONDecodeError:
        affected_files = target_files
    return {
        "id": int(row["id"]),
        "project_id": int(row["project_id"]),
        "project_name": row.get("project_name"),
        "root_path": row.get("root_path"),
        "title": row.get("title"),
        "summary": row.get("summary") or "",
        "reason": row.get("reason") or "",
        "change_type": row.get("change_type") or "modify",
        "affected_files": affected_files if isinstance(affected_files, list) else [],
        "target_files": target_files if isinstance(target_files, list) else [],
        "risk_level": row.get("risk_level") or "low",
        "code_preview": row.get("code_preview") or "",
        "diff_preview": row.get("diff_preview") or "",
        "status": row.get("status") or "pending",
        "created_at": _stringify(row.get("created_at")),
        "approved_at": _stringify(row.get("approved_at")),
        "completed_at": _stringify(row.get("completed_at")),
        "codex_task_id": row.get("codex_task_id"),
    }


def _is_scan_target(path: Path) -> bool:
    if any(part.startswith(".") or part in {"__pycache__", "node_modules", "venv"} for part in path.parts):
        return False
    return path.suffix.lower() in {".py", ".html", ".css", ".js", ".md", ".bat", ".toml", ".json"}


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} 값이 필요합니다.")
    return text


def _normalize_file_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip().replace("\\", "/") for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip().replace("\\", "/") for item in value if str(item).strip()]
    return []


def _merge_file_lists(left: list[str], right: list[str]) -> list[str]:
    merged: list[str] = []
    for item in [*left, *right]:
        if item not in merged:
            merged.append(item)
    return merged


def _normalize_change_type(value: Any) -> str:
    change_type = str(value or "modify").strip().lower()
    return change_type if change_type in ALLOWED_CHANGE_TYPES else "modify"


def _normalize_risk_level(value: Any, affected_files: list[str], change_type: Any) -> str:
    risk = str(value or "low").strip().lower()
    if risk not in ALLOWED_RISK_LEVELS:
        risk = "low"
    high_risk_files = ("database.py", "routes.py", "pc_agent_runner.py", "pc_wake_listener.py")
    if change_type == "refactor" or any(Path(path).name in high_risk_files for path in affected_files):
        return "high"
    return risk


def _ensure_allowed_project_root(root_path: str) -> None:
    root = Path(root_path).resolve()
    if root != ALLOWED_ROOT and ALLOWED_ROOT not in root.parents:
        raise ValueError("Agent 03 proposals are restricted to apps/personal_life/*.")


def _ensure_allowed_files(root_path: str, affected_files: list[str]) -> None:
    _ensure_allowed_project_root(root_path)
    for file_path in affected_files:
        _resolve_project_file(root_path, file_path)


def _resolve_project_file(root_path: str, file_path: str) -> Path:
    if Path(file_path).is_absolute():
        candidate = Path(file_path).resolve()
    else:
        candidate = (Path(root_path) / file_path).resolve()
    if candidate != ALLOWED_ROOT and ALLOWED_ROOT not in candidate.parents:
        raise ValueError(f"File outside allowed scope: {file_path}")
    return candidate


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
