import json
import os
import re
from dataclasses import dataclass
from typing import Any, Literal

from ..config import get_settings


IntentName = Literal[
    "agent_status_query",
    "agent_detail_open",
    "agent_task_create",
    "blog_draft_fill_request",
    "briefing_request",
    "smalltalk",
    "unknown",
]


@dataclass
class RoutedIntent:
    intent: IntentName
    confidence: float
    agent_id: int | None = None
    action: str | None = None
    task_type: str | None = None
    search_query: str | None = None
    requires_confirmation: bool = False
    reply: str | None = None
    source: str = "rule"


MIN_LLM_CONFIDENCE = float(os.getenv("GYUVIS_INTENT_MIN_CONFIDENCE", "0.72"))
LLM_TIMEOUT_SECONDS = float(os.getenv("GYUVIS_INTENT_TIMEOUT_SECONDS", "3.0"))


def route_intent(text: str) -> RoutedIntent:
    rule_intent = route_intent_by_rules(text)
    if rule_intent.intent != "unknown" and rule_intent.confidence >= 0.82:
        return rule_intent

    llm_intent = route_intent_with_openai(text) if should_try_llm_router(text) else None
    if llm_intent is not None and llm_intent.confidence >= MIN_LLM_CONFIDENCE:
        return llm_intent

    return rule_intent


def route_intent_by_rules(text: str) -> RoutedIntent:
    normalized = " ".join(text.strip().split())
    compact = re.sub(r"[\s?!.,~]+", "", normalized.lower())
    agent_id = extract_agent_id(compact)
    agent_id = agent_id or infer_agent_id_from_alias(compact)

    if compact in {"에이전트", "에이전트들", "에이전트들의", "agent", "agents"}:
        return RoutedIntent(
            intent="smalltalk",
            confidence=0.96,
            action="ask_agent_scope",
            reply="네 보스. 에이전트들의 상태를 확인할까요, 아니면 전체 에이전트 브리핑을 진행할까요?",
        )

    if _looks_like_agent_detail(compact):
        return RoutedIntent(
            intent="agent_detail_open",
            confidence=0.94,
            agent_id=agent_id,
            action="open_detail",
            reply=None if agent_id else "어떤 에이전트를 열지 번호를 말씀해주시면 바로 표시하겠습니다.",
        )

    if _looks_like_agent_status(compact):
        return RoutedIntent(
            intent="agent_status_query",
            confidence=0.93,
            agent_id=agent_id,
            action="status_or_role",
        )

    fill_requested = _looks_like_blog_fill_request(normalized, compact)
    if fill_requested:
        return RoutedIntent(
            intent="blog_draft_fill_request",
            confidence=0.92,
            agent_id=2,
            action="queue_naver_fill",
            task_type="naver_blog_fill_draft",
            search_query="네이버 블로그 최신 초안 입력",
            requires_confirmation=True,
        )

    task_type = _detect_agent_task_type(normalized, compact, agent_id)
    if task_type:
        return RoutedIntent(
            intent="agent_task_create",
            confidence=0.9,
            agent_id=_agent_id_for_task_type(task_type, agent_id),
            action="create_task",
            task_type=task_type,
            search_query=_build_search_query(normalized, task_type),
            requires_confirmation=task_type in {"naver_blog_fill_draft"},
        )

    if "브리핑" in compact and any(token in compact for token in ("진행", "시작", "해줘", "하세요", "들려")):
        return RoutedIntent(intent="briefing_request", confidence=0.82, action="briefing")

    return RoutedIntent(intent="unknown", confidence=0.0)


def route_intent_with_openai(text: str) -> RoutedIntent | None:
    settings = get_settings()
    if not settings.has_openai:
        return None

    try:
        from openai import OpenAI
    except ImportError:
        return None

    prompt = (
        "You classify a Korean voice command for a local assistant named GYUVIS.\n"
        "Return JSON only. Do not execute anything.\n"
        "Allowed intents: agent_status_query, agent_detail_open, agent_task_create, "
        "blog_draft_fill_request, briefing_request, smalltalk, unknown.\n"
        "Allowed task_type values: agent1_it_news_window, agent2_it_blog_draft, "
        "coding_app_update, youtube_idea_research, naver_blog_fill_draft, news_briefing, weather_briefing, web_search.\n"
        "Use agent_id 1 for IT news, 2 for blog draft/Naver blog, 3 for coding/app update, 4 for YouTube ideas.\n"
        "Set requires_confirmation true for browser writing, blog filling, file/code changes, or any risky action.\n"
        "Output keys: intent, confidence, agent_id, action, task_type, search_query, requires_confirmation, reply.\n"
        "confidence must be 0.0 to 1.0.\n"
        "If the command is incomplete, choose smalltalk and ask a concise Korean clarification in reply.\n"
    )

    try:
        client = OpenAI(api_key=settings.openai_api_key, timeout=LLM_TIMEOUT_SECONDS)
        response = client.responses.create(
            model=settings.openai_model,
            input=[
                {"role": "system", "content": [{"type": "input_text", "text": prompt}]},
                {"role": "user", "content": [{"type": "input_text", "text": text}]},
            ],
        )
        raw = getattr(response, "output_text", "") or ""
        data = json.loads(_strip_code_fence(raw))
    except Exception:
        return None

    return _intent_from_payload(data)


def should_try_llm_router(text: str) -> bool:
    compact = re.sub(r"[\s?!.,~]+", "", text.strip().lower())
    return any(
        token in compact
        for token in (
            "에이전트",
            "agent",
            "초안",
            "블로그",
            "네이버",
            "유튜브",
            "아이디어",
            "영상소재",
            "콘텐츠",
            "코딩",
            "코드",
            "앱수정",
            "브리핑",
        )
    ) or extract_agent_id(compact) is not None


def extract_agent_id(compact_text: str) -> int | None:
    digit_match = re.search(r"([1-4])번?", compact_text)
    if digit_match:
        return int(digit_match.group(1))

    word_numbers = {
        "일": 1,
        "한": 1,
        "첫": 1,
        "이": 2,
        "두": 2,
        "둘": 2,
        "삼": 3,
        "세": 3,
        "셋": 3,
        "사": 4,
        "네": 4,
        "넷": 4,
    }
    for token, value in word_numbers.items():
        if f"{token}번" in compact_text or f"{token}번째" in compact_text:
            return value
    return None


def infer_agent_id_from_alias(compact_text: str) -> int | None:
    aliases = (
        (1, ("뉴스보는애", "뉴스수집", "it뉴스", "아이티뉴스", "뉴스애")),
        (2, ("블로그애", "초안애", "글쓰는애", "네이버블로그")),
        (3, ("코딩애", "코드애", "개발애", "수정하는애", "앱업데이트")),
        (4, ("유튜브애", "아이디어애", "영상소재", "콘텐츠소재")),
    )
    for agent_id, tokens in aliases:
        if any(token in compact_text for token in tokens):
            return agent_id
    return None


def _looks_like_agent_detail(compact: str) -> bool:
    if "에이전트" not in compact and "agent" not in compact and infer_agent_id_from_alias(compact) is None:
        return False
    return any(token in compact for token in ("열어", "보여", "상세", "확대", "펼쳐", "띄워", "확인"))


def _looks_like_agent_status(compact: str) -> bool:
    agent_related = (
        "에이전트" in compact
        or "agent" in compact
        or extract_agent_id(compact) is not None
        or infer_agent_id_from_alias(compact) is not None
        or any(token in compact for token in ("뉴스보는애", "뉴스수집", "it뉴스", "아이티뉴스", "일하는애", "노는애"))
    )
    status_related = any(
        token in compact
        for token in (
            "상태",
            "뭐해",
            "뭐하",
            "뭐하고",
            "뭘",
            "뭐할",
            "할거",
            "할거야",
            "어떤거",
            "어떤걸",
            "담당",
            "역할",
            "어때",
            "진행",
            "일하",
            "놀고",
            "완료",
            "수집",
            "몇건",
            "몇개",
            "보고됐",
            "잘되고",
            "모았",
            "모은",
        )
    )
    return agent_related and status_related


def _looks_like_blog_fill_request(normalized: str, compact: str) -> bool:
    if "네이버" in normalized and "블로그" in normalized:
        return any(token in normalized for token in ("넣어", "입력", "올려", "채워", "글쓰기"))
    return (
        any(token in compact for token in ("이초안", "초안", "블로그초안"))
        and any(token in compact for token in ("네이버에넣", "블로그에넣", "넣어", "입력", "채워"))
    )


def _detect_agent_task_type(normalized: str, compact: str, agent_id: int | None) -> str | None:
    if (
        (agent_id == 1 or any(token in compact for token in ("에이전트1", "에이전트일", "에이전트한", "agent1")))
        and any(keyword in normalized for keyword in ("IT", "it", "아이티", "모바일", "테크", "기술", "뉴스"))
        and any(keyword in normalized for keyword in ("뉴스", "요약", "브리핑", "정리", "수집", "모아"))
    ):
        return "agent1_it_news_window"
    if (
        (agent_id == 2 or any(token in compact for token in ("에이전트2", "에이전트이", "에이전트두", "agent2")))
        and any(keyword in normalized for keyword in ("블로그", "초안", "글", "포스팅"))
        and any(keyword in normalized for keyword in ("작성", "추천", "만들", "생성", "써", "뽑아"))
    ):
        return "agent2_it_blog_draft"
    if (
        (agent_id == 3 or any(token in compact for token in ("에이전트3", "에이전트삼", "에이전트세", "agent3")))
        and any(keyword in normalized for keyword in ("코딩", "코드", "앱", "수정", "업데이트", "개발", "버그", "기능"))
    ):
        return "coding_app_update"
    if (
        (agent_id == 4 or any(token in compact for token in ("에이전트4", "에이전트사", "에이전트네", "agent4")))
        and any(keyword in normalized for keyword in ("유튜브", "아이디어", "영상", "콘텐츠", "주제", "소재"))
    ):
        return "youtube_idea_research"
    if any(keyword in normalized for keyword in ("유튜브", "영상", "콘텐츠")) and any(
        keyword in normalized for keyword in ("아이디어", "소재", "주제", "뽑아", "찾아", "추천")
    ):
        return "youtube_idea_research"
    if any(keyword in normalized for keyword in ("뉴스", "헤드라인", "속보")) and any(
        keyword in normalized for keyword in ("가져와", "가져와봐", "불러와", "알려", "보여", "요약", "정리", "브리핑", "찾아")
    ):
        return "news_briefing"
    if any(keyword in normalized for keyword in ("날씨", "비 와", "기온", "우산")):
        return "weather_briefing"
    if any(keyword in normalized for keyword in ("검색", "찾아봐", "알아봐", "웹에서", "인터넷")):
        return "web_search"
    return None


def _agent_id_for_task_type(task_type: str, fallback: int | None) -> int | None:
    return {
        "agent1_it_news_window": 1,
        "agent2_it_blog_draft": 2,
        "naver_blog_fill_draft": 2,
        "coding_app_update": 3,
        "youtube_idea_research": 4,
    }.get(task_type, fallback)


def _build_search_query(text: str, task_type: str) -> str:
    if task_type == "agent1_it_news_window":
        return "IT 모바일 테크 기술 뉴스"
    if task_type == "agent2_it_blog_draft":
        return "IT 모바일 AI 관련 블로그 초안"
    if task_type == "naver_blog_fill_draft":
        return "네이버 블로그 최신 초안 입력"
    if task_type == "coding_app_update":
        return text
    if task_type == "youtube_idea_research":
        return "IT 모바일 AI 유튜브 아이디어"
    if task_type == "news_briefing":
        return _clean_search_query(text, ("뉴스", "헤드라인", "속보")) or "최신 뉴스"
    if task_type == "weather_briefing":
        cleaned = _clean_search_query(text, ("날씨", "기온", "비", "우산"))
        return f"{cleaned} 날씨".strip() if cleaned else "내일 날씨"
    return _clean_search_query(text, ())


def _clean_search_query(text: str, remove_words: tuple[str, ...]) -> str:
    cleaned = f" {text.strip()} "
    patterns = [
        r"(요새|요즘|최근|최신)\s*",
        r"(흐름이|흐름은|상황이|상황은)\s*",
        r"(어떻게 돼|어떻게 돼요|어떻게 되어가|어떻게 되어가요)\s*",
        r"(어때|어떄)\s*",
        r"((알려|요약해|정리해|검색해|보여|말해|찾아봐|알아봐|가져와|불러와)\s*(줘|주|봐|볼래|볼까|줄래)?)\s*",
        r"(좀|한번|한 번|약간|지금)\s*",
        r"[?？！~!]+",
    ]
    for pattern in patterns:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    for word in remove_words:
        cleaned = re.sub(rf"\b{re.escape(word)}\b", " ", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip(" ,.")


def _intent_from_payload(data: dict[str, Any]) -> RoutedIntent:
    intent = str(data.get("intent") or "unknown")
    allowed = set(IntentName.__args__)  # type: ignore[attr-defined]
    if intent not in allowed:
        intent = "unknown"

    agent_id = data.get("agent_id")
    try:
        agent_id = int(agent_id) if agent_id is not None else None
    except (TypeError, ValueError):
        agent_id = None
    if agent_id not in {1, 2, 3, 4}:
        agent_id = None

    task_type = data.get("task_type")
    if task_type not in {
        "agent1_it_news_window",
        "agent2_it_blog_draft",
        "coding_app_update",
        "youtube_idea_research",
        "naver_blog_fill_draft",
        "news_briefing",
        "weather_briefing",
        "web_search",
    }:
        task_type = None

    return RoutedIntent(
        intent=intent,  # type: ignore[arg-type]
        confidence=_bounded_float(data.get("confidence")),
        agent_id=agent_id,
        action=str(data.get("action") or "") or None,
        task_type=task_type,
        search_query=str(data.get("search_query") or "") or None,
        requires_confirmation=bool(data.get("requires_confirmation")),
        reply=str(data.get("reply") or "") or None,
        source="openai",
    )


def _bounded_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(number, 1.0))


def _strip_code_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    return cleaned
