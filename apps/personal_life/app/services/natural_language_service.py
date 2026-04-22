import json
import re
from dataclasses import dataclass
from datetime import date, timedelta

from ..config import get_settings
from ..domain.schemas import (
    NaturalCommandCreate,
    NaturalCommandResponse,
    QuickCaptureCreate,
    ScheduleCreate,
    TaskCreate,
)
from .briefing_service import build_today_briefing
from .asset_service import build_asset_summary
from .capture_service import create_quick_capture
from .conversation_service import log_conversation
from .finance_service import build_finance_briefing
from .memory_service import list_memory_highlights
from .reminder_service import create_reminder
from .schedule_service import create_schedule
from .task_service import create_task


@dataclass
class ParsedCommand:
    command_type: str
    title: str
    details: str
    scheduled_for: str | None = None
    start_time: str | None = None
    due_date: str | None = None
    capture_type: str = "note"
    reminder_like: bool = False


def process_natural_command(payload: NaturalCommandCreate) -> NaturalCommandResponse:
    settings = get_settings()
    stripped = payload.text.strip()
    log_conversation("user", stripped)

    if _looks_like_question(stripped):
        answer = _answer_question(stripped, settings.openai_model, settings.openai_api_key)
        response = NaturalCommandResponse(
            text=payload.text,
            interpreted_as="answer",
            summary=answer,
            created_id=0,
            created_type="answer",
            reminder_id=None,
        )
        log_conversation("assistant", answer, interpreted_as="answer", created_type="answer")
        return response

    if settings.has_openai:
        parsed = _parse_with_openai(payload.text, settings.openai_model, settings.openai_api_key)
        if parsed is not None:
            response = _save_parsed_command(payload.text, parsed)
            log_conversation(
                "assistant",
                response.summary,
                interpreted_as=response.interpreted_as,
                created_type=response.created_type,
            )
            return response

    parsed = _parse_text_fallback(stripped)
    response = _save_parsed_command(payload.text, parsed)
    log_conversation(
        "assistant",
        response.summary,
        interpreted_as=response.interpreted_as,
        created_type=response.created_type,
    )
    return response


def _save_parsed_command(original_text: str, parsed: ParsedCommand) -> NaturalCommandResponse:
    if parsed.command_type == "schedule":
        created = create_schedule(
            ScheduleCreate(
                title=parsed.title,
                details=parsed.details,
                scheduled_for=parsed.scheduled_for or date.today().isoformat(),
                start_time=parsed.start_time,
            )
        )
        return NaturalCommandResponse(
            text=original_text,
            interpreted_as="schedule",
            summary=_build_schedule_reply(created.scheduled_for, created.start_time, created.title),
            created_id=created.id,
            created_type="schedule",
            reminder_id=None,
        )

    if parsed.command_type == "task":
        created = create_task(
            TaskCreate(
                title=parsed.title,
                details=parsed.details or original_text,
                due_date=parsed.due_date,
                priority=2,
            )
        )
        reminder = _maybe_create_reminder_for_task(created.id, parsed, original_text)
        return NaturalCommandResponse(
            text=original_text,
            interpreted_as="task",
            summary=_build_task_reply(created.title, created.due_date, parsed.reminder_like, reminder is not None),
            created_id=created.id,
            created_type="task",
            reminder_id=reminder.id if reminder else None,
        )

    created = create_quick_capture(
        QuickCaptureCreate(
            capture_type=parsed.capture_type,
            content=parsed.title,
            source="natural-command",
        )
    )
    return NaturalCommandResponse(
        text=original_text,
        interpreted_as="capture",
        summary=_build_capture_reply(parsed.capture_type),
        created_id=created.id,
        created_type="capture",
        reminder_id=None,
    )


def _maybe_create_reminder_for_task(task_id: int, parsed: ParsedCommand, original_text: str):
    if not parsed.reminder_like:
        return None

    remind_on = parsed.due_date or date.today().isoformat()
    remind_time = _extract_reminder_time(original_text)
    return create_reminder(
        title=parsed.title,
        details=parsed.details or original_text,
        remind_on=remind_on,
        remind_time=remind_time,
        origin_type="task",
        origin_id=task_id,
    )


def _extract_reminder_time(text: str) -> str | None:
    explicit_time = _extract_time(text)
    if explicit_time:
        return explicit_time
    if "아침" in text:
        return "08:00"
    if "점심" in text:
        return "12:00"
    if "저녁" in text:
        return "18:30"
    if "퇴근" in text:
        return "18:00"
    return None


def _build_schedule_reply(day: str, start_time: str | None, title: str) -> str:
    if start_time:
        return f"네, {day} {start_time} 일정으로 '{title}' 저장해둘게요."
    return f"네, {day} 일정으로 '{title}' 저장해둘게요."


def _build_task_reply(title: str, due_date: str | None, reminder_like: bool, reminder_created: bool) -> str:
    if reminder_like and due_date and reminder_created:
        return (
            f"네, '{title}' 잊지 않게 {due_date} 할 일로 적어두고 리마인드도 같이 잡아둘게요. "
            "웹에서는 예정 알림으로 먼저 보여드릴 수 있습니다."
        )
    if reminder_like and reminder_created:
        return (
            f"네, '{title}' 잊지 않게 할 일로 적어두고 리마인드도 같이 잡아둘게요. "
            "브라우저 알림 허용해두시면 웹에서도 챙겨드리기 좋습니다."
        )
    if reminder_like and due_date:
        return f"네, '{title}'를 {due_date} 할 일로 적어둘게요. 리마인드까지는 아직 못 만들었지만 기록은 남겨뒀어요."
    if reminder_like:
        return f"네, '{title}' 잊지 않게 할 일로 적어둘게요."
    if due_date:
        return f"네, '{title}'를 {due_date} 할 일로 정리해둘게요."
    return f"네, '{title}' 할 일로 적어둘게요."


def _build_capture_reply(capture_type: str) -> str:
    if capture_type == "expense":
        return "네, 지출 메모로 기록해둘게요."
    if capture_type == "idea":
        return "네, 아이디어로 저장해둘게요."
    if capture_type == "journal":
        return "네, 생각 메모로 남겨둘게요."
    return "네, 메모로 적어둘게요."


def _parse_with_openai(text: str, model: str, api_key: str | None) -> ParsedCommand | None:
    if not api_key:
        return None

    try:
        from openai import OpenAI
    except ImportError:
        return None

    client = OpenAI(api_key=api_key)
    today = date.today().isoformat()
    prompt = (
        "You convert a Korean personal assistant message into structured JSON.\n"
        "Return JSON only with keys: interpreted_as, title, details, scheduled_for, start_time, due_date, capture_type, reminder_like.\n"
        "interpreted_as must be one of: task, schedule, capture.\n"
        "capture_type must be one of: note, expense, idea, journal, routine, task.\n"
        "reminder_like must be true when the user is asking to remember, remind, or not forget something.\n"
        "Use null for missing values.\n"
        f"Assume today's date is {today}.\n"
        "For relative dates like tomorrow or next week, resolve them into absolute YYYY-MM-DD dates.\n"
        "For times, use HH:MM 24-hour format.\n"
        "Keep title short and natural.\n"
        "If it is just a note or memory, choose capture."
    )

    try:
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": prompt}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": text}],
                },
            ],
        )
        content = getattr(response, "output_text", "") or ""
        if not content:
            return None
        data = json.loads(_strip_code_fence(content))
        return ParsedCommand(
            command_type=data.get("interpreted_as", "capture"),
            title=(data.get("title") or text).strip(),
            details=(data.get("details") or "").strip(),
            scheduled_for=data.get("scheduled_for"),
            start_time=data.get("start_time"),
            due_date=data.get("due_date"),
            capture_type=data.get("capture_type") or "note",
            reminder_like=bool(data.get("reminder_like")),
        )
    except Exception:
        return None


def _answer_question(text: str, model: str, api_key: str | None) -> str:
    briefing = build_today_briefing()
    asset_summary = build_asset_summary()
    finance = build_finance_briefing()
    memory_context = list_memory_highlights(limit=5)

    if api_key:
        generated = _answer_question_with_openai(
            text=text,
            briefing=briefing,
            asset_summary=asset_summary,
            finance=finance,
            memory_context=memory_context,
            model=model,
            api_key=api_key,
        )
        if generated:
            return generated

    return _answer_question_fallback(text, briefing, asset_summary, finance)


def _answer_question_with_openai(
    text: str,
    briefing,
    asset_summary,
    finance,
    memory_context: list[dict[str, str]],
    model: str,
    api_key: str | None,
) -> str | None:
    if not api_key:
        return None

    try:
        from openai import OpenAI
    except ImportError:
        return None

    prompt = (
        "You are a Korean personal assistant answering the user's question.\n"
        "Answer in Korean.\n"
        "Be concise, practical, and specific.\n"
        "Sound like a thoughtful human aide, not a chatbot.\n"
        "Use the user's current briefing and memory context.\n"
        "If the user asks for an opinion, give the recommendation first and a short reason after.\n"
        "Do not claim you scheduled or saved something unless the data says it already exists.\n"
        f"Question: {text}\n"
        f"Today: {briefing.today}\n"
        f"Briefing message: {briefing.message}\n"
        f"Open task count: {briefing.open_task_count}\n"
        f"Today's schedule count: {briefing.schedule_count_today}\n"
        f"Completed routines: {briefing.completed_routine_count}/{briefing.total_routine_count}\n"
        f"Top tasks: {json.dumps([task.title for task in briefing.top_tasks], ensure_ascii=False)}\n"
        f"Schedules: {json.dumps([schedule.title for schedule in briefing.schedules], ensure_ascii=False)}\n"
        f"Insights: {json.dumps([item.model_dump() for item in briefing.insights], ensure_ascii=False)}\n"
        f"Opinions: {json.dumps([item.model_dump() for item in briefing.opinions], ensure_ascii=False)}\n"
        f"Asset total: {asset_summary.total_assets}\n"
        f"Asset categories: {json.dumps([item.model_dump() for item in asset_summary.categories], ensure_ascii=False)}\n"
        f"Asset latest change amount: {asset_summary.latest_change_amount}\n"
        f"Asset latest change rate: {asset_summary.latest_change_rate}\n"
        f"Finance headline: {finance.headline}\n"
        f"Finance bullets: {json.dumps(finance.bullets, ensure_ascii=False)}\n"
        f"Memory highlights: {json.dumps(memory_context, ensure_ascii=False)}\n"
    )

    try:
        client = OpenAI(api_key=api_key)
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": prompt}],
                }
            ],
        )
        content = getattr(response, "output_text", "") or ""
        return content.strip() or None
    except Exception:
        return None


def _answer_question_fallback(text: str, briefing, asset_summary, finance) -> str:
    lowered = text.lower()

    if any(keyword in text for keyword in ["자산", "현금성", "비중", "예금", "투자"]):
        if asset_summary.total_assets == 0:
            return (
                "아직 등록된 자산 데이터가 없어서 자산 기준 의견은 드리기 어렵습니다.\n\n"
                "현금, 예금, 투자 같은 항목 몇 개만 먼저 넣어두시면 그다음부터는 비중이 괜찮은지 같이 봐드릴 수 있어요."
            )
        largest = asset_summary.categories[0] if asset_summary.categories else None
        if largest is not None:
            return (
                f"지금 등록된 자산 총합은 {asset_summary.total_assets:,}원이고, "
                f"가장 큰 비중은 '{largest.category}'로 {(largest.ratio * 100):.1f}%입니다.\n\n"
                "한쪽으로 많이 몰린 느낌인지 보려면 예금, 현금, 투자 항목을 조금 더 나눠서 적어두시는 게 좋겠습니다. "
                "그러면 제가 비중 기준으로 더 자연스럽게 의견을 드릴 수 있어요."
            )
        return (
            f"지금 등록된 자산 총합은 {asset_summary.total_assets:,}원입니다.\n\n"
            "카테고리 정보가 더 쌓이면 어디가 과한지, 어디가 비어 있는지도 같이 봐드릴게요."
        )

    if any(keyword in text for keyword in ["돈", "지출", "예산", "소비", "카드", "저축", "현금 목표"]):
        return (
            f"재정 쪽만 보면 {finance.headline}\n\n"
            f"지금은 {finance.monthly_spend_total:,}원 정도 쓰는 흐름이고, 남는 돈은 {finance.remaining_cash:,}원 수준으로 보입니다."
        )

    if "뭐부터" in text or "우선" in text or "먼저" in text:
        if briefing.top_tasks:
            return (
                f"제 생각에는 '{briefing.top_tasks[0].title}'부터 보시는 게 좋겠습니다.\n\n"
                "하나만 먼저 끝내두면 오늘 전체 흐름이 훨씬 덜 복잡하게 느껴질 거예요."
            )
        if briefing.schedule_count_today > 0:
            return (
                "지금은 할 일보다 오늘 일정 확인부터 하시는 편이 좋겠습니다.\n\n"
                "시간이 고정된 약속을 먼저 잡아두면 마음이 좀 더 편해질 거예요."
            )
        return (
            "오늘은 급한 건 많지 않아 보여요.\n\n"
            "루틴 하나만 챙기고 천천히 시작하셔도 괜찮겠습니다."
        )

    if "일정" in text and any(keyword in text for keyword in ["많", "줄", "빡", "무리"]):
        if briefing.schedule_count_today >= 3:
            return (
                "오늘 일정이 많은 편이면 준비 시간이 큰 일정 하나부터 줄이는 게 좋겠습니다.\n\n"
                "고정 약속만 남기고 나머지는 뒤로 미루는 쪽이 부담이 덜해요."
            )
        return (
            "지금 일정 수만 보면 아주 빡빡하진 않아요.\n\n"
            "다만 체감이 버거우시면 준비 시간이 긴 일정 하나만 조정해도 숨통이 트일 것 같습니다."
        )

    if "쉬" in text or "휴식" in text:
        if briefing.schedule_count_today == 0 and briefing.open_task_count == 0:
            return (
                "지금은 조금 쉬어도 괜찮아 보여요.\n\n"
                "급한 일정도 없고 열린 할 일도 적어서, 회복을 먼저 챙기셔도 됩니다."
            )
        return (
            "완전히 멈추기보다는 10분 정도만 짧게 쉬고 다시 보는 쪽을 추천드리고 싶어요.\n\n"
            "남은 일정 확인 후에 판단해도 늦지 않겠습니다."
        )

    if "괜찮" in text or "어때" in text or "생각" in text or "추천" in text or "?" in text or lowered.endswith("까"):
        if briefing.opinions:
            primary = briefing.opinions[0]
            return f"{primary.body}\n\n제 판단 근거는 {primary.reason}"

    return (
        "지금 제 의견부터 드리면, 오늘 브리핑 기준으로 우선순위 하나만 먼저 잡는 쪽이 좋아 보여요.\n\n"
        "원하시면 이 질문도 일정 판단인지, 할 일 정리인지에 맞춰 더 구체적으로 같이 보겠습니다."
    )


def _strip_code_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*", "", cleaned)
        cleaned = cleaned.rstrip("`").strip()
    return cleaned


def _looks_like_question(text: str) -> bool:
    question_keywords = [
        "뭐부터",
        "뭐가 좋",
        "어때",
        "어떨까",
        "괜찮을까",
        "하는 게 좋",
        "추천",
        "생각",
        "어떤 게",
        "할까",
        "말까",
        "쉬는 게",
        "줄일까",
    ]
    normalized = text.strip()
    return normalized.endswith("?") or any(keyword in normalized for keyword in question_keywords)


def _parse_text_fallback(text: str) -> ParsedCommand:
    normalized = " ".join(text.split())
    detected_date = _extract_date(normalized)
    detected_time = _extract_time(normalized)
    reminder_like = _looks_like_reminder(normalized)

    if _looks_like_task(normalized) or reminder_like:
        cleaned = _cleanup_task_text(normalized)
        title, details = _split_title_and_details(cleaned)
        return ParsedCommand(
            command_type="task",
            title=title or "해야 할 일",
            details=details,
            due_date=detected_date,
            reminder_like=reminder_like,
        )

    if _looks_like_schedule(normalized, detected_date, detected_time):
        cleaned = _cleanup_schedule_text(normalized)
        title, details = _split_title_and_details(cleaned)
        return ParsedCommand(
            command_type="schedule",
            title=title,
            details=details,
            scheduled_for=detected_date or date.today().isoformat(),
            start_time=detected_time,
            reminder_like=reminder_like,
        )

    return ParsedCommand(
        command_type="capture",
        title=normalized,
        details="",
        capture_type=_guess_capture_type(normalized),
        reminder_like=reminder_like,
    )


def _looks_like_reminder(text: str) -> bool:
    keywords = [
        "알려줘",
        "알려주라",
        "기억해줘",
        "까먹지",
        "잊지",
        "챙겨줘",
        "리마인드",
        "기억해",
    ]
    return any(keyword in text for keyword in keywords)


def _looks_like_schedule(text: str, detected_date: str | None, detected_time: str | None) -> bool:
    schedule_keywords = [
        "예약",
        "약속",
        "미팅",
        "회의",
        "방문",
        "진료",
        "면담",
        "출발",
        "가기",
    ]
    has_schedule_keyword = any(keyword in text for keyword in schedule_keywords)
    return bool(detected_time or has_schedule_keyword or (detected_date and has_schedule_keyword))


def _looks_like_task(text: str) -> bool:
    task_keywords = [
        "해야",
        "하기",
        "정리",
        "구매",
        "사기",
        "보내기",
        "작성",
        "준비",
        "공부",
        "청소",
        "확인",
        "제출",
        "전화",
        "연락",
        "후속",
        "단속",
        "챙기기",
    ]
    task_prefixes = ["todo", "to do"]
    return any(keyword in text for keyword in task_keywords) or any(text.lower().startswith(prefix) for prefix in task_prefixes)


def _extract_date(text: str) -> str | None:
    today = date.today()
    if "내일" in text:
        return (today + timedelta(days=1)).isoformat()
    if "모레" in text:
        return (today + timedelta(days=2)).isoformat()
    if "오늘" in text:
        return today.isoformat()

    match = re.search(r"(?:(\d{4})[-./])?(\d{1,2})[-./월](\d{1,2})일?", text)
    if not match:
        return None

    year = int(match.group(1) or today.year)
    month = int(match.group(2))
    day = int(match.group(3))
    return date(year, month, day).isoformat()


def _extract_time(text: str) -> str | None:
    hhmm_match = re.search(r"(\d{1,2}):(\d{2})", text)
    if hhmm_match:
        hour = int(hhmm_match.group(1))
        minute = int(hhmm_match.group(2))
        return f"{hour:02d}:{minute:02d}"

    korean_match = re.search(r"(오전|오후)?\s*(\d{1,2})시(?:\s*(\d{1,2})분?)?", text)
    if not korean_match:
        return None

    meridiem = korean_match.group(1)
    hour = int(korean_match.group(2))
    minute = int(korean_match.group(3) or 0)

    if meridiem == "오후" and hour < 12:
        hour += 12
    if meridiem == "오전" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}"


def _cleanup_schedule_text(text: str) -> str:
    cleaned = re.sub(r"(오늘|내일|모레)", "", text)
    cleaned = re.sub(r"(?:(\d{4})[-./])?(\d{1,2})[-./월](\d{1,2})일?", "", cleaned)
    cleaned = re.sub(r"(오전|오후)?\s*\d{1,2}시(?:\s*\d{1,2}분?)?", "", cleaned)
    cleaned = re.sub(r"\d{1,2}:\d{2}", "", cleaned)
    cleaned = re.sub(r"\s*[,|/-]\s*", " ", cleaned)
    return " ".join(cleaned.split())


def _cleanup_task_text(text: str) -> str:
    cleaned = re.sub(r"^(todo|to do)\s*", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"(오늘|내일|모레)", "", cleaned)
    cleaned = re.sub(r"(아침에|점심에|저녁에|새벽에)", "", cleaned)
    cleaned = re.sub(r"(오전|오후)?\s*\d{1,2}시(?:\s*\d{1,2}분?)?", "", cleaned)
    cleaned = re.sub(r"(알려줘|알려주라|기억해줘|기억해|챙겨줘|리마인드해줘|리마인드)", "", cleaned)
    cleaned = re.sub(r"(가라고|라고|하라고|해달라고)$", "", cleaned)
    cleaned = re.sub(r"ㅋㅋ+|ㅎㅎ+|[~!]+", "", cleaned)
    cleaned = re.sub(r"(?:(\d{4})[-./])?(\d{1,2})[-./월](\d{1,2})일?", "", cleaned)
    cleaned = cleaned.replace("하고 가라고", "").replace("하고 가", "")
    cleaned = " ".join(cleaned.split())
    return cleaned.strip(" ,.")


def _split_title_and_details(text: str) -> tuple[str, str]:
    for delimiter in [",", " - ", " / ", " | "]:
        if delimiter in text:
            left, right = text.split(delimiter, 1)
            return left.strip() or text.strip(), right.strip()
    return text.strip(), ""


def _guess_capture_type(text: str) -> str:
    lowered = text.lower()
    if any(keyword in text for keyword in ["지출", "결제", "원", "만원", "카드"]):
        return "expense"
    if any(keyword in text for keyword in ["아이디어", "생각", "기획"]) or "idea" in lowered:
        return "idea"
    if any(keyword in text for keyword in ["일기", "기분", "감정", "오늘은"]):
        return "journal"
    return "note"
