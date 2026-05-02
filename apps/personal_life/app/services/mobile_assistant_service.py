import re

from ..domain.schemas import MobileAssistantCommandCreate, MobileAssistantCommandResponse, NaturalCommandCreate
from .agent_standby_service import build_agent_status_reply, open_agent_detail
from .agent_task_service import create_agent_task
from .conversation_service import log_conversation
from .intent_router_service import RoutedIntent, route_intent
from .natural_language_service import classify_natural_intent, process_natural_command


def process_mobile_assistant_command(payload: MobileAssistantCommandCreate) -> MobileAssistantCommandResponse:
    routed = route_intent(payload.text)
    routed_response = _process_routed_intent(payload, routed)
    if routed_response is not None:
        return routed_response

    natural_intent = classify_natural_intent(payload.text)
    print(f"[mobile] text={payload.text!r} intent={natural_intent}")
    detail_agent_id = _detect_agent_detail_id(payload.text)
    if detail_agent_id is not None:
        open_agent_detail(detail_agent_id)
        return MobileAssistantCommandResponse(
            mode="assistant_reply",
            spoken_text=payload.text,
            summary=f"네 보스. 에이전트 {detail_agent_id}번 상세 화면을 열겠습니다.",
            task=None,
        )

    status_agent_id = _detect_agent_status_query(payload.text)
    if status_agent_id is not False:
        return MobileAssistantCommandResponse(
            mode="assistant_reply",
            spoken_text=payload.text,
            summary=build_agent_status_reply(status_agent_id),
            task=None,
        )

    task_type = _detect_agent_task_type(payload.text)
    if task_type is not None:
        return _create_agent_task_response(
            payload=payload,
            task_type=task_type,
            search_query=_build_search_query(payload.text, task_type),
            interpreted_as="mobile_command",
        )

    if natural_intent in {"assistant_chat", "self_state_question", "general_question"}:
        response = process_natural_command(NaturalCommandCreate(text=payload.text))
        return MobileAssistantCommandResponse(
            mode="assistant_reply",
            spoken_text=payload.text,
            summary=response.summary,
            task=None,
        )

    response = process_natural_command(NaturalCommandCreate(text=payload.text))
    return MobileAssistantCommandResponse(
        mode="assistant_reply",
        spoken_text=payload.text,
        summary=response.summary,
        task=None,
    )


def _process_routed_intent(
    payload: MobileAssistantCommandCreate,
    routed: RoutedIntent,
) -> MobileAssistantCommandResponse | None:
    if routed.intent == "smalltalk" and routed.reply:
        return MobileAssistantCommandResponse(
            mode="assistant_reply",
            spoken_text=payload.text,
            summary=routed.reply,
            task=None,
        )

    if routed.intent == "agent_detail_open":
        if routed.agent_id is None:
            return MobileAssistantCommandResponse(
                mode="assistant_reply",
                spoken_text=payload.text,
                summary=routed.reply or "어떤 에이전트를 열지 번호를 말씀해주시면 바로 표시하겠습니다.",
                task=None,
            )
        open_agent_detail(routed.agent_id)
        return MobileAssistantCommandResponse(
            mode="assistant_reply",
            spoken_text=payload.text,
            summary=f"네 보스. 에이전트 {routed.agent_id}번 상세 화면을 열겠습니다.",
            task=None,
        )

    if routed.intent == "agent_status_query":
        return MobileAssistantCommandResponse(
            mode="assistant_reply",
            spoken_text=payload.text,
            summary=build_agent_status_reply(routed.agent_id),
            task=None,
        )

    if routed.intent in {"agent_task_create", "blog_draft_fill_request"} and routed.task_type:
        if routed.requires_confirmation and routed.intent == "blog_draft_fill_request":
            # Blog filling is allowed as a queued job, not as immediate publish/submit.
            pass
        return _create_agent_task_response(
            payload=payload,
            task_type=routed.task_type,
            search_query=routed.search_query or _build_search_query(payload.text, routed.task_type),
            interpreted_as=f"intent_router:{routed.intent}:{routed.source}",
        )

    if routed.intent == "briefing_request":
        response = process_natural_command(NaturalCommandCreate(text=payload.text))
        return MobileAssistantCommandResponse(
            mode="assistant_reply",
            spoken_text=payload.text,
            summary=response.summary,
            task=None,
        )

    return None


def _create_agent_task_response(
    *,
    payload: MobileAssistantCommandCreate,
    task_type: str,
    search_query: str,
    interpreted_as: str,
) -> MobileAssistantCommandResponse:
    log_conversation("user", payload.text, interpreted_as=interpreted_as, created_type="mobile")
    task = create_agent_task(
        command_text=payload.text,
        task_type=task_type,
        search_query=search_query,
        source=payload.source,
    )
    response = MobileAssistantCommandResponse(
        mode="agent_task",
        spoken_text=payload.text,
        summary=_build_agent_waiting_summary(task_type),
        task=task,
    )
    log_conversation("assistant", response.summary, interpreted_as="agent_task", created_type=task_type)
    return response


def _looks_like_incomplete_agent_fragment(text: str) -> bool:
    compact = re.sub(r"[\s?!.,~]+", "", text.strip().lower())
    if compact in {"에이전트", "에이전트들", "에이전트들의", "agent", "agents"}:
        return True
    if compact in {"에이전트상태", "에이전트들상태", "에이전트들의상태"}:
        return False
    return False


def _detect_agent_task_type(text: str) -> str | None:
    normalized = " ".join(text.strip().split())
    compact = re.sub(r"[\s?!.,~]+", "", normalized.lower())
    agent_id = _extract_agent_id(compact)
    if (
        (agent_id == 1 or "에이전트1" in compact or "에이전트일" in compact or "에이전트한" in compact or "agent1" in compact)
        and any(keyword in normalized for keyword in ["IT", "it", "아이티", "모바일", "테크", "기술"])
        and any(keyword in normalized for keyword in ["뉴스", "요약", "브리핑", "정리"])
    ):
        return "agent1_it_news_window"
    if (
        (agent_id == 2 or "에이전트2" in compact or "에이전트이" in compact or "에이전트두" in compact or "agent2" in compact)
        and any(keyword in normalized for keyword in ["블로그", "초안", "글"])
        and any(keyword in normalized for keyword in ["작성", "추천", "만들", "생성", "써"])
    ):
        return "agent2_it_blog_draft"
    if (
        (agent_id == 3 or "에이전트3" in compact or "에이전트삼" in compact or "에이전트세" in compact or "agent3" in compact)
        and any(keyword in normalized for keyword in ["코딩", "코드", "앱", "수정", "업데이트", "개발", "버그", "기능"])
    ):
        return "coding_app_update"
    if (
        (agent_id == 4 or "에이전트4" in compact or "에이전트사" in compact or "에이전트네" in compact or "agent4" in compact)
        and any(keyword in normalized for keyword in ["유튜브", "아이디어", "영상", "콘텐츠", "주제"])
    ):
        return "youtube_idea_research"
    if (
        "네이버" in normalized
        and "블로그" in normalized
        and any(keyword in normalized for keyword in ["넣어", "입력", "올려", "채워", "글쓰기"])
    ):
        return "naver_blog_fill_draft"
    if any(keyword in normalized for keyword in ["뉴스", "헤드라인", "속보"]) and any(
        keyword in normalized for keyword in ["가져와", "가져와봐", "불러와", "알려", "보여", "요약", "정리", "브리핑", "찾아"]
    ):
        return "news_briefing"
    if any(keyword in normalized for keyword in ["전쟁", "분쟁", "사태", "이슈", "정세", "흐름"]) and any(
        keyword in normalized for keyword in ["어때", "어떻게", "요새", "요즘", "최근", "흐름", "상황"]
    ):
        return "news_briefing"
    if any(keyword in normalized for keyword in ["날씨", "비 와", "기온", "우산"]):
        return "weather_briefing"
    if any(keyword in normalized for keyword in ["검색", "찾아봐", "알아봐", "웹에서", "인터넷"]):
        return "web_search"
    return None


def _detect_agent_detail_id(text: str) -> int | None:
    compact = re.sub(r"[\s?!.,~]+", "", text.strip().lower())
    if "에이전트" not in compact and "agent" not in compact:
        return None
    if not any(token in compact for token in ["열어", "보여", "상세", "확대", "펼쳐", "띄워", "확인"]):
        return None

    digit_match = re.search(r"([1-4])번?", compact)
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
        if f"{token}번" in compact or f"{token}번째" in compact:
            return value
    return None


def _detect_agent_status_query(text: str) -> int | None | bool:
    compact = re.sub(r"[\s?!.,~]+", "", text.strip().lower())
    agent_related = (
        "에이전트" in compact
        or "agent" in compact
        or _extract_agent_id(compact) is not None
        or "뉴스보는애" in compact
        or "뉴스수집" in compact
        or "it뉴스" in compact
        or "아이티뉴스" in compact
        or "일하는애" in compact
        or "노는애" in compact
    )
    status_related = any(
        token in compact
        for token in [
            "상태",
            "뭐해",
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
        ]
    )
    if not (agent_related and status_related):
        return False

    agent_id = _extract_agent_id(compact)
    if agent_id is None and any(token in compact for token in ["뉴스", "it", "아이티", "모바일", "테크"]):
        return 1
    return agent_id


def _extract_agent_id(compact_text: str) -> int | None:
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


def _build_search_query(text: str, task_type: str) -> str:
    normalized = " ".join(text.strip().split())
    if task_type == "agent1_it_news_window":
        return "IT 모바일 테크 기술 뉴스"
    if task_type == "agent2_it_blog_draft":
        return "IT 모바일 AI 관련 블로그 초안"
    if task_type == "naver_blog_fill_draft":
        return "네이버 블로그 최신 초안 입력"
    if task_type == "coding_app_update":
        return normalized
    if task_type == "youtube_idea_research":
        return "IT 모바일 AI 유튜브 아이디어"
    if task_type == "news_briefing":
        cleaned = _clean_search_query(normalized)
        cleaned = re.sub(r"\b(뉴스|헤드라인|속보)\b", "", cleaned).strip()
        return cleaned or "최신 뉴스"
    if task_type == "weather_briefing":
        cleaned = _clean_search_query(normalized)
        cleaned = re.sub(r"\b(날씨|기온|비|우산)\b", "", cleaned).strip()
        return f"{cleaned} 날씨".strip() if cleaned else "내일 날씨"
    return _clean_search_query(normalized)


def _build_agent_waiting_summary(task_type: str) -> str:
    if task_type == "agent1_it_news_window":
        return "에이전트 1번에게 오전 10시부터 오후 6시까지의 IT 관련 뉴스 요약 작업을 배정했습니다."
    if task_type == "agent2_it_blog_draft":
        return "에이전트 2번에게 IT/모바일 뉴스 기반 블로그 초안 작성을 배정했습니다."
    if task_type == "naver_blog_fill_draft":
        return "네이버 블로그 글쓰기 화면에 최신 초안을 입력하겠습니다. 발행은 하지 않습니다."
    if task_type == "coding_app_update":
        return "에이전트 3번에게 코딩/앱 업데이트 작업을 배정했습니다."
    if task_type == "youtube_idea_research":
        return "에이전트 4번에게 유튜브 아이디어 탐색 작업을 배정했습니다."
    if task_type == "news_briefing":
        return "확인해보겠습니다. 핵심만 정리해드릴게요."
    if task_type == "weather_briefing":
        return "확인해보겠습니다. 바로 말씀드릴게요."
    return "확인해보겠습니다. 정리해서 말씀드릴게요."


def _clean_search_query(text: str) -> str:
    cleaned = f" {text.strip()} "
    patterns = [
        r"(요새|요즘|최근|최신)\s*",
        r"(흐름이|흐름은|상황이|상황은)\s*",
        r"(어떻게 돼|어떻게 돼요|어떻게 되어가|어떻게 되어가요)\s*",
        r"(어때|어떄)\s*",
        r"((알려|요약해|정리해|검색해|보여|말해|가져와|불러와)\s*줘)\s*",
        r"((알려|요약해|정리해|검색해|보여|말해|가져와|불러와)\s*주)\s*",
        r"((알려|요약해|정리해|검색해|보여|말해|가져와|불러와)\s*봐)\s*",
        r"((알려|요약해|정리해|검색해|보여|말해|가져와|불러와)\s*볼래)\s*",
        r"((알려|요약해|정리해|검색해|보여|말해|가져와|불러와)\s*볼까)\s*",
        r"((알려|요약해|정리해|검색해|보여|말해|가져와|불러와)\s*줄래)\s*",
        r"((찾아봐|알아봐)\s*줘)\s*",
        r"((찾아봐|알아봐)\s*주)\s*",
        r"((찾아봐|알아봐)\s*볼래)\s*",
        r"((찾아봐|알아봐)\s*줄래)\s*",
        r"(요약\s*해\s*줘|정리\s*해\s*줘|검색\s*해\s*줘)\s*",
        r"(좀|한번|한 번|약간|지금)\s*",
        r"[?？！~!]+",
    ]
    for pattern in patterns:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.")
    cleaned = cleaned.replace("  ", " ").strip()
    return cleaned


def _looks_like_self_state_question(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text.strip())
    compact = re.sub(r"[ ?!.,~]+", "", normalized)

    phrases = [
        "너 기분이 어때",
        "너 기분 어때",
        "기분이 어때",
        "기분 어때",
        "너 상태가 어때",
        "너 상태 어때",
        "상태가 어때",
        "상태 어때",
        "요즘 상태 어때",
        "요즘 어때",
        "너 오늘 어때",
        "오늘 너 어때",
        "너 하루 어떠냐",
        "너 하루 어때",
        "피곤하냐",
        "피곤해",
        "괜찮냐",
        "괜찮아",
        "컨디션 어때",
        "컨디션이 어때",
    ]
    if any(phrase in normalized for phrase in phrases):
        return True

    compact_phrases = [re.sub(r"[ ?!.,~]+", "", phrase) for phrase in phrases]
    if any(phrase in compact for phrase in compact_phrases):
        return True

    has_self_subject = any(token in normalized for token in ["너", "규비스", "너는", "오늘 너", "요즘"])
    has_state_word = any(token in normalized for token in ["기분", "상태", "컨디션", "하루", "피곤"])
    has_question_tone = any(token in normalized for token in ["어때", "어떠", "괜찮", "피곤"])
    return has_self_subject and has_state_word and has_question_tone


def _looks_like_assistant_chat(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text.strip())
    compact = re.sub(r"[ ?!.,~]+", "", normalized)

    phrases = [
        "규비스",
        "너 지금 뭐해",
        "너 지금 뭐하고 있어",
        "너 뭐해",
        "너 뭐하고 있어",
        "너 이름이 뭐야",
        "너 누구야",
        "너가 할 수",
        "네가 할 수",
        "할 수 있는 영역",
        "뭐까지 할 수",
        "어디까지 할 수",
        "어디까지 가능해",
        "뭐까지 가능해",
        "가능한 게 뭐야",
        "가능한건 뭐야",
    ]
    if any(phrase in normalized for phrase in phrases):
        return True
    if any(re.sub(r"[ ?!.,~]+", "", phrase) in compact for phrase in phrases):
        return True

    if any(token in normalized for token in ["어디까지 가능", "뭐까지 가능", "가능한 게 뭐", "가능한건 뭐", "할 수 있어"]):
        return True

    addresses_assistant = any(token in normalized for token in ["규비스", "너", "너는"])
    chat_tone = any(token in normalized for token in ["뭐해", "뭐 하", "누구", "이름", "대답", "할 수", "가능", "영역", "기능"])
    return addresses_assistant and chat_tone
