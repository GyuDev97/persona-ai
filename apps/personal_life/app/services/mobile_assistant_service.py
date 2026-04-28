import re

from ..domain.schemas import MobileAssistantCommandCreate, MobileAssistantCommandResponse, NaturalCommandCreate
from .agent_standby_service import open_agent_detail
from .agent_task_service import create_agent_task
from .conversation_service import log_conversation
from .natural_language_service import classify_natural_intent, process_natural_command


def process_mobile_assistant_command(payload: MobileAssistantCommandCreate) -> MobileAssistantCommandResponse:
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

    task_type = _detect_agent_task_type(payload.text)
    if task_type is not None:
        log_conversation("user", payload.text, interpreted_as="mobile_command", created_type="mobile")
        task = create_agent_task(
            command_text=payload.text,
            task_type=task_type,
            search_query=_build_search_query(payload.text, task_type),
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


def _detect_agent_task_type(text: str) -> str | None:
    normalized = " ".join(text.strip().split())
    if any(keyword in normalized for keyword in ["뉴스", "헤드라인", "속보"]):
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


def _build_search_query(text: str, task_type: str) -> str:
    normalized = " ".join(text.strip().split())
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
        r"((알려|요약해|정리해|검색해|보여|말해)\s*줘)\s*",
        r"((알려|요약해|정리해|검색해|보여|말해)\s*주)\s*",
        r"((알려|요약해|정리해|검색해|보여|말해)\s*볼래)\s*",
        r"((알려|요약해|정리해|검색해|보여|말해)\s*볼까)\s*",
        r"((알려|요약해|정리해|검색해|보여|말해)\s*줄래)\s*",
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
