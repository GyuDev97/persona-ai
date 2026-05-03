import re
from typing import Any


OPEN_PAGE_TARGETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("agent_report", ("에이전트리포트", "에이전트대시보드", "agentreport")),
    ("creator", ("크리에이터", "creatorstudio", "콘텐츠작업실", "콘텐츠")),
    ("money", ("돈관리", "재정", "moneycore", "머니코어")),
    ("car", ("자동차", "차량", "drive")),
    ("settings", ("설정", "setting")),
    ("schedule", ("일정", "스케줄", "schedule")),
    ("briefing", ("브리핑", "briefing")),
    ("naver", ("네이버",)),
    ("google", ("구글", "google")),
    ("youtube", ("유튜브", "youtube")),
    ("gpt", ("gpt", "지피티", "챗지피티", "chatgpt")),
)


def parse_intent(text: str) -> dict[str, Any]:
    normalized = _normalize(text)
    agent_id = _extract_agent_id(normalized)

    if not normalized:
        return _intent("UNKNOWN", confidence=0.0)

    if _has_any(normalized, ("브리핑", "오늘정리", "하루정리", "상황정리")) and _has_any(
        normalized, ("해줘", "진행", "시작", "보고", "정리")
    ):
        return _intent("START_BRIEFING", action="start", confidence=0.92)

    if _has_any(normalized, ("뉴스가져", "뉴스수집", "최신뉴스가져", "it뉴스가져", "아이티뉴스가져")):
        return _intent("RUN_AGENT", target=1, action="agent1_it_news_window", confidence=0.9)

    if _has_any(normalized, ("초안생성", "초안작성", "블로그초안")):
        return _intent("RUN_AGENT", target=2, action="agent2_it_blog_draft", confidence=0.88)

    if _has_any(normalized, ("유튜브아이디어", "영상아이디어")):
        return _intent("RUN_AGENT", target=4, action="youtube_idea_research", confidence=0.86)

    if _has_any(normalized, ("상태", "어때", "확인")) and _has_any(normalized, ("에이전트", "agent", "서버", "시스템")):
        return _intent("SHOW_STATUS", target=agent_id, action="status", confidence=0.87)

    if _has_any(normalized, ("열어", "보여", "띄워", "이동", "실행", "open", "show", "켜줘", "가자")):
        if agent_id is not None and _has_any(normalized, ("에이전트", "agent")):
            return _intent("OPEN_PAGE", target=agent_id, action="open_agent_detail", confidence=0.94)
        for target, keywords in OPEN_PAGE_TARGETS:
            if _has_any(normalized, keywords):
                return _intent("OPEN_PAGE", target=target, action="open", confidence=0.9)

    if _has_any(normalized, ("유튜브", "youtube")) and _has_any(normalized, ("틀어", "재생", "음악", "ncs")):
        return _intent("CONTROL_BROWSER", target="youtube", action="play_or_search", confidence=0.86)

    if "모니터" in normalized:
        return _intent("CONTROL_PC", target="monitor", action="desktop_monitor", confidence=0.8)

    if _has_any(normalized, ("돈", "재정", "소비", "카드", "월급", "money")):
        return _intent("QUERY_MONEY", target="money", action="query", confidence=0.74)

    if _has_any(normalized, ("자동차", "차량", "주유", "정비", "보험")):
        return _intent("QUERY_CAR", target="car", action="query", confidence=0.74)

    if _has_any(normalized, ("너오늘어때", "오늘힘들", "고마워", "수고", "안녕")):
        return _intent("SMALL_TALK", action="reply", confidence=0.7)

    return _intent("UNKNOWN", confidence=0.1)


def _intent(
    intent: str,
    target: str | int | None = None,
    action: str | None = None,
    confidence: float = 0.5,
) -> dict[str, Any]:
    return {
        "intent": intent,
        "target": target,
        "action": action,
        "confidence": confidence,
    }


def _normalize(text: str) -> str:
    return re.sub(r"[\s?!.,~]+", "", str(text or "").strip().lower())


def _has_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _extract_agent_id(normalized: str) -> int | None:
    match = re.search(r"([1-4])번?", normalized)
    if match:
        return int(match.group(1))
    labels = {
        "일번": 1,
        "한번": 1,
        "첫번째": 1,
        "두번째": 2,
        "삼번": 3,
        "세번": 3,
        "세번째": 3,
        "사번": 4,
        "네번": 4,
        "넷번": 4,
        "네번째": 4,
    }
    for token, agent_id in labels.items():
        if token in normalized:
            return agent_id
    return None
