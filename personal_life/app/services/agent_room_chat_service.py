from __future__ import annotations

from datetime import datetime
from typing import Any

from .agent_message_service import create_agent_message, list_agent_messages
from .agent_report_center_service import build_agent_report_center


AGENT_PROFILES = {
    0: {
        "label": "User",
        "role": "질문",
    },
    1: {
        "label": "Money Core",
        "role": "자산/주식/금융",
        "keywords": ("돈", "자산", "주식", "금융", "소비", "카드", "잔액", "money", "finance"),
    },
    2: {
        "label": "Car Management",
        "role": "차량 관리",
        "keywords": ("차", "차량", "정비", "주유", "연비", "car", "fuel"),
    },
    3: {
        "label": "Creator Studio",
        "role": "블로그/유튜브/콘텐츠",
        "keywords": ("블로그", "유튜브", "콘텐츠", "글", "영상", "아이디어", "creator", "youtube"),
    },
    4: {
        "label": "News Intelligence",
        "role": "IT 뉴스/트렌드",
        "keywords": ("뉴스", "트렌드", "기술", "it", "기사", "동향", "news"),
    },
    5: {
        "label": "Approval Center",
        "role": "승인/검토/결재",
        "keywords": ("승인", "결재", "검토", "대기", "허가", "approval", "approve"),
    },
    6: {
        "label": "Innovation Lab",
        "role": "신규 프로젝트/실험",
        "keywords": ("프로젝트", "실험", "연구", "개선", "신규", "innovation", "lab"),
    },
    7: {
        "label": "GYUVIS Core",
        "role": "총괄 관제",
        "keywords": ("전체", "상황", "요약", "뭐해", "진행", "상태", "core", "gyuvis", "gyuos"),
    },
}


def run_agent_room_chat(message: str, *, target_agent_id: int | None = None) -> dict[str, Any]:
    clean = " ".join(str(message or "").split())
    if not clean:
        raise ValueError("메시지를 입력해주세요.")

    report = _safe_report()
    create_agent_message(
        0,
        clean,
        topic="user_chat",
        payload={"source": "agent_headqurater"},
    )

    selected_ids = _select_agents(clean, target_agent_id)
    replies = []
    for agent_id in selected_ids:
        reply = _build_reply(agent_id, clean, report)
        saved = create_agent_message(
            agent_id,
            reply,
            to_agent_id=0,
            topic="user_chat",
            payload={"question": clean, "agent_label": AGENT_PROFILES[agent_id]["label"]},
        )
        saved["from_agent_label"] = AGENT_PROFILES[agent_id]["label"]
        saved["from_agent_role"] = AGENT_PROFILES[agent_id]["role"]
        replies.append(saved)

    return {
        "question": clean,
        "replies": replies,
        "messages": get_agent_room_messages(limit=24),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def get_agent_room_messages(limit: int = 24) -> list[dict[str, Any]]:
    messages = list_agent_messages(limit=limit, topic="user_chat")
    normalized = []
    for message in reversed(messages):
        agent_id = int(message.get("from_agent_id") or 0)
        profile = AGENT_PROFILES.get(agent_id)
        if profile:
            message["from_agent_label"] = profile["label"]
            message["from_agent_role"] = profile["role"]
        normalized.append(message)
    return normalized


def _select_agents(message: str, target_agent_id: int | None) -> list[int]:
    if target_agent_id in AGENT_PROFILES and target_agent_id != 0:
        return [int(target_agent_id)]

    lowered = message.lower()
    matched = [
        agent_id
        for agent_id, profile in AGENT_PROFILES.items()
        if agent_id != 0 and any(keyword.lower() in lowered for keyword in profile.get("keywords", ()))
    ]
    if matched:
        if 7 not in matched:
            matched.append(7)
        return matched[:3]
    return [7, 4, 3]


def _build_reply(agent_id: int, question: str, report: dict[str, Any]) -> str:
    if agent_id == 1:
        return "Money Core 확인했습니다. 자산/소비/금융 흐름 쪽 질문이면 현재 금융 요약과 지출 데이터를 기준으로 먼저 이상 흐름부터 볼게요."
    if agent_id == 2:
        return "Car Management가 받았습니다. 차량 상태, 정비 이력, 주유 기록 관점에서 확인할게요. 필요한 경우 다음 정비 후보까지 같이 정리하겠습니다."
    if agent_id == 3:
        drafts = len(report.get("agent2", {}).get("drafts") or [])
        ideas = len(report.get("agent4", {}).get("ideas") or [])
        return f"Creator Studio입니다. 지금 블로그 초안 {drafts}개, 영상 아이디어 {ideas}개 흐름을 참고해서 콘텐츠로 만들 만한 방향을 정리할게요."
    if agent_id == 4:
        count = int(report.get("agent1", {}).get("display_count") or report.get("agent1", {}).get("collected_count") or 0)
        return f"News Intelligence입니다. 현재 수집된 IT 뉴스 {count}건을 기준으로 질문과 관련된 트렌드 신호를 먼저 추려보겠습니다."
    if agent_id == 5:
        pending = _count_tasks(report, "pending")
        return f"Approval Center입니다. 승인이나 검토가 필요한 항목은 실행 전에 멈춰 세우겠습니다. 현재 대기 작업은 약 {pending}건으로 보고 있어요."
    if agent_id == 6:
        return "Innovation Lab입니다. 이 질문은 신규 기능/실험 후보로도 볼 수 있어요. 바로 실행할 것과 프로토타입으로 볼 것을 나눠서 제안하겠습니다."

    active = len(report.get("cards") or [])
    return f"GYUVIS Core입니다. 질문 접수했습니다. 현재 {active or 7}개 에이전트 관점으로 나눠 보고, 필요한 부서가 이어서 답하도록 조율하겠습니다."


def _safe_report() -> dict[str, Any]:
    try:
        return build_agent_report_center()
    except Exception:
        return {}


def _count_tasks(report: dict[str, Any], status: str) -> int:
    tasks = report.get("tasks") or report.get("recent_tasks") or []
    if not isinstance(tasks, list):
        return 0
    return sum(1 for task in tasks if str(task.get("status") or "").lower() == status)
