from __future__ import annotations

from datetime import datetime
from typing import Any

from .agent_message_service import create_agent_message, list_agent_messages
from .agent_report_center_service import build_agent_report_center


AGENT_PROFILES = {
    0: {"label": "User", "role": "질문"},
    1: {"label": "Money Core", "role": "자산/주식/금융"},
    2: {"label": "Car Management", "role": "차량 관리"},
    3: {"label": "Creator Studio", "role": "블로그/유튜브/콘텐츠"},
    4: {"label": "News Intelligence", "role": "IT 뉴스/트렌드"},
    5: {"label": "Approval Center", "role": "승인/검토/결재"},
    6: {"label": "Innovation Lab", "role": "신규 프로젝트/실험"},
    7: {"label": "GYUVIS Core", "role": "총괄 관제"},
}


def run_agent_room_chat(message: str, *, target_agent_id: int | None = None) -> dict[str, Any]:
    clean = " ".join(str(message or "").split())
    if not clean:
        raise ValueError("메시지를 입력해주세요.")

    report = _safe_report()
    create_agent_message(0, clean, topic="user_chat", payload={"source": "agent_live_office"})

    replies = []
    for agent_id in _select_agents(clean, target_agent_id):
        saved = create_agent_message(
            agent_id,
            _build_reply(agent_id, clean, report),
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
        if _looks_broken(message.get("message")):
            continue
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

    text = message.casefold()
    if _asks_news_list(text):
        return [4]
    if any(token in text for token in ("콘텐츠", "블로그", "유튜브", "영상", "아이디어")):
        return [4, 3]
    if any(token in text for token in ("승인", "결재", "검토", "대기")):
        return [5]
    if any(token in text for token in ("프로젝트", "실험", "연구", "개선", "신규")):
        return [6, 7]
    if any(token in text for token in ("돈", "자산", "주식", "금융", "소비", "카드", "잔액")):
        return [1, 7]
    if any(token in text for token in ("차", "차량", "정비", "주유", "연비")):
        return [2, 7]
    if any(token in text for token in ("뉴스", "트렌드", "기술", "it", "기사", "동향")):
        return [4]
    return [7]


def _build_reply(agent_id: int, question: str, report: dict[str, Any]) -> str:
    text = question.casefold()
    if agent_id == 4:
        return _news_reply(report, list_mode=_asks_news_list(text))
    if agent_id == 3:
        return _creator_reply(report)
    if agent_id == 5:
        return _approval_reply(report)
    if agent_id == 6:
        return _innovation_reply(question, report)
    if agent_id == 1:
        return "Money Core입니다. 금융 질문은 Money Core 데이터까지 연결하면 잔액/소비/자산 흐름을 바로 답할 수 있어요. 지금 화면에서는 에이전트 리포트 중심으로 보고 있습니다."
    if agent_id == 2:
        return "Car Management입니다. 차량 질문은 정비/주유 기록 데이터와 붙이면 최근 정비일, 주유비, 상태 알림까지 바로 답할 수 있습니다."
    return _core_reply(report)


def _news_reply(report: dict[str, Any], *, list_mode: bool) -> str:
    panel = report.get("agent1", {}) if isinstance(report, dict) else {}
    items = panel.get("items") or []
    if not items:
        items = [{"title": title} for title in (panel.get("latest_titles") or [])]

    if not items:
        return "News Intelligence입니다. 지금 표시 가능한 뉴스 목록이 비어 있어요. Agent 01 뉴스 수집을 먼저 돌리면 바로 제목 기준으로 답할 수 있습니다."

    lines = []
    for index, item in enumerate(items[:5], start=1):
        title = _clean(item.get("title"))
        source = _clean(item.get("source"))
        published = _clean(item.get("published_at"))
        meta = " · ".join(part for part in (source, published[:10] if published else "") if part)
        lines.append(f"{index}. {title}" + (f" ({meta})" if meta else ""))

    count = int(panel.get("display_count") or len(lines) or panel.get("selected_count") or 0)
    if list_mode:
        return f"News Intelligence입니다. 말한 뉴스 {count}건은 이 목록입니다.\n" + "\n".join(lines)
    return f"News Intelligence입니다. 현재 보고 있는 IT 뉴스 {count}건입니다.\n" + "\n".join(lines)


def _creator_reply(report: dict[str, Any]) -> str:
    drafts = report.get("agent2", {}).get("drafts") or []
    ideas = report.get("agent4", {}).get("ideas") or []
    rows = []
    if drafts:
        rows.append("블로그 초안: " + ", ".join(_clean(draft.get("title")) for draft in drafts[:3]))
    if ideas:
        rows.append("영상 아이디어: " + ", ".join(_clean(idea.get("title")) for idea in ideas[:3]))
    if not rows:
        return "Creator Studio입니다. 아직 바로 이어갈 초안이나 영상 아이디어가 많지는 않아요. 뉴스 하나를 골라주면 블로그/유튜브 제목 후보로 바꿔드릴게요."
    return "Creator Studio입니다. 지금 콘텐츠 재료는 이렇습니다.\n" + "\n".join(f"- {row}" for row in rows)


def _approval_reply(report: dict[str, Any]) -> str:
    proposals = report.get("autonomy", {}).get("proposals") or []
    pending = [item for item in proposals if str(item.get("status") or "").lower() == "pending"]
    queued = [item for item in proposals if str(item.get("status") or "").lower() == "queued"]
    if not pending and not queued:
        return "Approval Center입니다. 지금 자동화 승인 대기나 큐에 걸린 제안은 크게 보이지 않습니다."
    rows = pending[:3] + queued[:2]
    lines = [f"- {item.get('title') or item.get('summary') or '승인 항목'} ({item.get('status')})" for item in rows]
    return f"Approval Center입니다. 대기 {len(pending)}건, 큐 {len(queued)}건이 보여요.\n" + "\n".join(lines)


def _innovation_reply(question: str, report: dict[str, Any]) -> str:
    items = report.get("agent1", {}).get("items") or []
    seed = _clean(items[0].get("title")) if items else "현재 Agent Live Office"
    return (
        "Innovation Lab입니다. 작은 실험으로 쪼개면 좋겠습니다.\n"
        f"1. 기준 재료: {seed}\n"
        f"2. 실험안: '{_short(question, 28)}'를 상황실 액션/요약/승인 플로우 중 하나로 붙이기\n"
        "3. 다음 단계: 화면 버튼, API 응답, 저장 기록 중 어디까지 자동화할지 정하면 됩니다."
    )


def _core_reply(report: dict[str, Any]) -> str:
    cards = report.get("cards") or []
    agent1 = report.get("agent1", {})
    drafts = report.get("agent2", {}).get("drafts") or []
    ideas = report.get("agent4", {}).get("ideas") or []
    return (
        "GYUVIS Core입니다. 현재 상황은 이렇게 볼 수 있어요.\n"
        f"- 활성 에이전트 카드: {len(cards)}개\n"
        f"- 표시 뉴스: {int(agent1.get('display_count') or 0)}건\n"
        f"- 블로그 초안: {len(drafts)}개\n"
        f"- 영상 아이디어: {len(ideas)}개\n"
        "궁금한 항목을 찍어주면 해당 부서가 실제 목록이나 다음 액션까지 이어서 답합니다."
    )


def _safe_report() -> dict[str, Any]:
    try:
        return build_agent_report_center()
    except Exception:
        return {}


def _asks_news_list(text: str) -> bool:
    return ("뉴스" in text or "news" in text or "기사" in text) and any(
        token in text for token in ("뭐", "무엇", "어떤", "목록", "리스트", "보여", "알려", "5건", "건이")
    )


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _short(value: Any, limit: int) -> str:
    text = _clean(value)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _looks_broken(value: Any) -> bool:
    text = str(value or "")
    if text.startswith("?? "):
        return True
    return any(token in text for token in ("Ã", "ì", "í", "ê", "ë")) and not any("가" <= char <= "힣" for char in text)
