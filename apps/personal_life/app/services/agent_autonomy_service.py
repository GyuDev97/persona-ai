from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ..storage.database import execute, fetch_all, fetch_one
from .agent_dialogue_service import build_agent_dialogue, dialogue_payload
from .agent_message_service import create_agent_message
from .agent_task_service import create_agent_task


ALLOWED_PROPOSAL_STATUSES = {"pending", "approved", "held", "rejected", "queued", "done"}
ALLOWED_RISK_LEVELS = {"low", "medium", "high"}


def create_observation(payload: dict[str, Any]) -> dict[str, Any]:
    observation_id = execute(
        """
        INSERT INTO agent_observations (
            agent_id, source, observation_type, title, summary, payload_json
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            int(payload.get("agent_id") or 0),
            _text(payload.get("source"), "gyuos-core"),
            _text(payload.get("observation_type"), "status"),
            _required_text(payload.get("title"), "title"),
            _text(payload.get("summary")),
            json.dumps(payload.get("payload") or {}, ensure_ascii=False),
        ),
    )
    return get_observation(observation_id)


def list_observations(limit: int = 20) -> list[dict[str, Any]]:
    rows = fetch_all(
        """
        SELECT *
        FROM agent_observations
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [_observation_payload(row) for row in rows]


def get_observation(observation_id: int) -> dict[str, Any]:
    row = fetch_one("SELECT * FROM agent_observations WHERE id = ?", (observation_id,))
    if row is None:
        raise ValueError("Observation not found")
    return _observation_payload(row)


def create_autonomy_proposal(payload: dict[str, Any]) -> dict[str, Any]:
    target_files = _normalize_list(payload.get("target_files"))
    risk_level = _normalize_risk(payload.get("risk_level"))
    source_key = _optional_text(payload.get("source_key"))
    existing = fetch_one("SELECT id FROM agent_autonomy_proposals WHERE source_key = ?", (source_key,)) if source_key else None
    if existing:
        return get_autonomy_proposal(int(existing["id"]))

    proposal_id = execute(
        """
        INSERT INTO agent_autonomy_proposals (
            agent_id, title, summary, reason, expected_action, target_area, target_files,
            risk_level, approval_required, suggested_task_type, command_text, payload_json,
            status, source_key
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        """,
        (
            int(payload.get("agent_id") or 0),
            _required_text(payload.get("title"), "title"),
            _text(payload.get("summary")),
            _text(payload.get("reason")),
            _text(payload.get("expected_action")),
            _text(payload.get("target_area")),
            json.dumps(target_files, ensure_ascii=False),
            risk_level,
            1 if payload.get("approval_required", True) else 0,
            _text(payload.get("suggested_task_type"), "autonomy_review"),
            _text(payload.get("command_text")),
            json.dumps(payload.get("payload") or {}, ensure_ascii=False),
            source_key,
        ),
    )
    return get_autonomy_proposal(proposal_id)


def list_autonomy_proposals(status: str | None = None, limit: int = 20, *, seed: bool = True) -> list[dict[str, Any]]:
    if seed:
        ensure_default_autonomy_proposals()
    if status:
        rows = fetch_all(
            """
            SELECT *
            FROM agent_autonomy_proposals
            WHERE status = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (status, limit),
        )
    else:
        rows = fetch_all(
            """
            SELECT *
            FROM agent_autonomy_proposals
            ORDER BY
                CASE status
                    WHEN 'pending' THEN 0
                    WHEN 'held' THEN 1
                    WHEN 'queued' THEN 2
                    WHEN 'approved' THEN 3
                    ELSE 4
                END,
                created_at DESC,
                id DESC
            LIMIT ?
            """,
            (limit,),
        )
    return [_proposal_payload(row) for row in rows]


def get_autonomy_proposal(proposal_id: int) -> dict[str, Any]:
    row = fetch_one("SELECT * FROM agent_autonomy_proposals WHERE id = ?", (proposal_id,))
    if row is None:
        raise ValueError("Autonomy proposal not found")
    return _proposal_payload(row)


def update_autonomy_proposal_status(proposal_id: int, status: str) -> dict[str, Any]:
    if status not in ALLOWED_PROPOSAL_STATUSES:
        raise ValueError("Unsupported autonomy proposal status")
    completed_at = _now() if status == "done" else None
    execute(
        """
        UPDATE agent_autonomy_proposals
        SET status = ?, completed_at = COALESCE(?, completed_at)
        WHERE id = ?
        """,
        (status, completed_at, proposal_id),
    )
    return get_autonomy_proposal(proposal_id)


def approve_autonomy_proposal(proposal_id: int) -> dict[str, Any]:
    proposal = get_autonomy_proposal(proposal_id)
    if proposal["status"] not in {"pending", "held"}:
        return proposal

    task = create_agent_task(
        command_text=_build_task_command(proposal),
        task_type=proposal.get("suggested_task_type") or "autonomy_review",
        search_query=f"autonomy_proposal_id={proposal_id}",
        source="agent-autonomy",
        payload={
            "autonomy_proposal_id": proposal_id,
            "agent_id": proposal.get("agent_id"),
            "target_area": proposal.get("target_area"),
            "target_files": proposal.get("target_files") or [],
            "risk_level": proposal.get("risk_level"),
            "approval_required": True,
            "safety": "user_approved_queue_only",
            **(proposal.get("payload") or {}),
        },
    )
    now = _now()
    execute(
        """
        UPDATE agent_autonomy_proposals
        SET status = 'queued', approved_at = ?, queued_at = ?, task_id = ?
        WHERE id = ?
        """,
        (now, now, task.id, proposal_id),
    )
    try:
        message_payload = {
            "proposal_id": proposal_id,
            "task_id": task.id,
            "risk_level": proposal.get("risk_level"),
        }
        fallback = f"자율 제안 #{proposal_id}은 작업 큐 #{task.id}로 넘겨뒀어. 실행은 승인된 범위 안에서만 진행할게."
        create_agent_message(
            int(proposal.get("agent_id") or 3),
            build_agent_dialogue("autonomy_queue", agent_id=int(proposal.get("agent_id") or 3), context={**message_payload, "fallback": fallback}) or fallback,
            topic="autonomy_queue",
            payload=dialogue_payload(message_payload),
        )
    except Exception:
        pass
    return get_autonomy_proposal(proposal_id)


def ensure_default_autonomy_proposals() -> None:
    seeds = [
        {
            "agent_id": 3,
            "title": "Money Core 저장/수정/집계 흐름 점검",
            "summary": "최근 Money Core 수정이 많았으니 저장, 수정, 월 합계 계산이 서로 어긋나지 않는지 점검하면 좋아 보여.",
            "reason": "월급은 직접 입력, 카드사용/자동이체/할부는 항목 합계 기반으로 바뀌어서 회귀 점검 가치가 큽니다.",
            "expected_action": "Money Core 화면과 서비스의 저장/수정/집계 흐름을 읽고, 필요한 수정 후보를 Codex 작업 큐로 정리합니다.",
            "target_area": "Money Core",
            "target_files": [
                "app/frontend/money_core.html",
                "app/services/money_core_service.py",
                "app/api/routes.py",
            ],
            "risk_level": "medium",
            "suggested_task_type": "coding_app_update",
            "command_text": "Agent 03 autonomy proposal: Money Core 저장/수정/집계 흐름을 점검하고, 기존 기능 삭제 없이 필요한 수정 후보를 제안해줘.",
            "source_key": "v1-money-core-integrity",
        },
        {
            "agent_id": 2,
            "title": "최신 블로그 초안 발행 전 검토",
            "summary": "최신 초안은 바로 발행하지 말고 제목, 첫 문단, 네이버 입력 준비 상태만 먼저 확인하는 흐름이 좋아 보여.",
            "reason": "발행은 위험 액션이라 자동으로 하지 않고, 입력 준비와 검토만 작업 큐로 분리합니다.",
            "expected_action": "초안 목록과 최신 초안을 확인하고, 네이버 입력 전에 다듬을 포인트를 정리합니다.",
            "target_area": "Creator Studio",
            "target_files": ["app/frontend/agent_report_center.html", "app/services/blog_draft_service.py"],
            "risk_level": "low",
            "suggested_task_type": "autonomy_review",
            "command_text": "Agent 02 autonomy proposal: 최신 블로그 초안의 제목/첫 문단/네이버 입력 준비 상태를 검토해줘. 발행은 하지 마.",
            "source_key": "v1-blog-draft-review",
        },
        {
            "agent_id": 4,
            "title": "뉴스 메일 아침 8시 초안 기능 준비",
            "summary": "뉴스 8개와 2-3줄 요약을 메일 초안으로 준비하는 기능은 스케줄러에 얹기 좋아 보여.",
            "reason": "처음에는 자동 발송보다 초안 생성과 승인 흐름이 안전합니다.",
            "expected_action": "네이버 뉴스 메일 서비스와 Agent Runner 스케줄러 연결 범위를 점검합니다.",
            "target_area": "News Email",
            "target_files": ["pc_agent_runner.py", "app/services/naver_news_email_service.py"],
            "risk_level": "medium",
            "suggested_task_type": "coding_app_update",
            "command_text": "Agent 04 autonomy proposal: 매일 아침 8시 뉴스 메일 초안 생성 흐름을 점검하고 승인 기반으로 설계해줘. 자동 발송은 하지 마.",
            "source_key": "v1-news-email-draft",
        },
    ]
    for seed in seeds:
        try:
            create_autonomy_proposal(seed)
        except Exception:
            pass


def _build_task_command(proposal: dict[str, Any]) -> str:
    if proposal.get("command_text"):
        return str(proposal["command_text"])
    files = ", ".join(proposal.get("target_files") or []) or "대상 없음"
    return (
        f"GyuOS autonomy proposal #{proposal['id']}: {proposal.get('title')}\n\n"
        f"Summary: {proposal.get('summary')}\n"
        f"Reason: {proposal.get('reason')}\n"
        f"Expected action: {proposal.get('expected_action')}\n"
        f"Target area: {proposal.get('target_area')}\n"
        f"Target files: {files}\n"
        f"Risk level: {proposal.get('risk_level')}\n\n"
        "Keep existing features. Queue/review only. Do not publish, pay, delete, or auto-apply code."
    )


def _proposal_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "agent_id": int(row.get("agent_id") or 0),
        "title": row.get("title") or "",
        "summary": row.get("summary") or "",
        "reason": row.get("reason") or "",
        "expected_action": row.get("expected_action") or "",
        "target_area": row.get("target_area") or "",
        "target_files": _json_list(row.get("target_files")),
        "risk_level": row.get("risk_level") or "low",
        "approval_required": bool(row.get("approval_required")),
        "suggested_task_type": row.get("suggested_task_type") or "autonomy_review",
        "command_text": row.get("command_text") or "",
        "payload": _json_dict(row.get("payload_json")),
        "status": row.get("status") or "pending",
        "source_key": row.get("source_key"),
        "created_at": _stringify(row.get("created_at")),
        "approved_at": _stringify(row.get("approved_at")),
        "queued_at": _stringify(row.get("queued_at")),
        "completed_at": _stringify(row.get("completed_at")),
        "task_id": row.get("task_id"),
    }


def _observation_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "agent_id": int(row.get("agent_id") or 0),
        "source": row.get("source") or "gyuos-core",
        "observation_type": row.get("observation_type") or "status",
        "title": row.get("title") or "",
        "summary": row.get("summary") or "",
        "payload": _json_dict(row.get("payload_json")),
        "created_at": _stringify(row.get("created_at")),
    }


def _normalize_risk(value: Any) -> str:
    risk = str(value or "low").strip().lower()
    return risk if risk in ALLOWED_RISK_LEVELS else "low"


def _normalize_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [item.strip().replace("\\", "/") for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip().replace("\\", "/") for item in value if str(item).strip()]
    return []


def _json_list(value: Any) -> list[str]:
    parsed = _json_value(value, [])
    return parsed if isinstance(parsed, list) else []


def _json_dict(value: Any) -> dict[str, Any]:
    parsed = _json_value(value, {})
    return parsed if isinstance(parsed, dict) else {}


def _json_value(value: Any, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} 값이 필요합니다.")
    return text


def _text(value: Any, fallback: str = "") -> str:
    return str(value if value is not None else fallback).strip()


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")
