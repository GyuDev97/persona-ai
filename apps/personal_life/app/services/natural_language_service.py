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
from .desktop_action_service import maybe_run_desktop_action
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
    intent = classify_natural_intent(stripped)
    print(f"[natural] text={stripped!r} intent={intent}")

    desktop_action = maybe_run_desktop_action(stripped)
    if desktop_action is not None:
        response = NaturalCommandResponse(
            text=payload.text,
            interpreted_as="desktop_action",
            summary=desktop_action.summary,
            created_id=0,
            created_type="desktop_action",
            reminder_id=None,
        )
        log_conversation(
            "assistant",
            response.summary,
            interpreted_as=response.interpreted_as,
            created_type=response.created_type,
        )
        return response

    if intent in {"assistant_chat", "self_state_question", "general_question"} or _should_force_answer_mode(stripped):
        answer = _answer_question(stripped, settings.openai_model, settings.openai_api_key, intent=intent)
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

    if intent == "unknown":
        answer = _answer_question(stripped, settings.openai_model, settings.openai_api_key, intent=intent)
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

    if settings.has_openai and intent in {"task_request", "schedule_request", "capture_request"}:
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


def classify_natural_intent(text: str) -> str:
    normalized = " ".join(text.strip().split())
    detected_date = _extract_date(normalized)
    detected_time = _extract_time(normalized)
    reminder_like = _looks_like_reminder(normalized)

    if _is_assistant_chat(normalized):
        return "assistant_chat"
    if _is_self_state_question(normalized):
        return "self_state_question"
    if _looks_like_question(normalized):
        return "general_question"
    if _looks_like_schedule(normalized, detected_date, detected_time):
        return "schedule_request"
    if _looks_like_task(normalized) or reminder_like:
        return "task_request"
    if _looks_like_capture(normalized):
        return "capture_request"
    return "unknown"


def _should_force_answer_mode(text: str) -> bool:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return False

    if _is_assistant_chat(normalized) or _is_self_state_question(normalized):
        return True

    question_signals = [
        "어때",
        "어떨까",
        "뭐야",
        "뭐지",
        "가능해",
        "가능하",
        "할 수 있",
        "있나",
        "있어",
        "맞아",
        "맞나",
        "피곤",
        "바쁘",
        "기분",
        "상태",
        "어디까지",
        "뭐까지",
    ]
    save_signals = [
        "메모",
        "기록",
        "저장",
        "적어",
        "남겨",
        "추가",
        "등록",
        "알려줘",
        "리마인드",
        "기억해",
    ]

    has_question_signal = any(token in normalized for token in question_signals) or normalized.endswith("?")
    has_save_signal = any(token in normalized for token in save_signals)
    return has_question_signal and not has_save_signal


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
        return f"확인했습니다. {day} {start_time} 일정으로 '{title}' 저장해두겠습니다."
    return f"확인했습니다. {day} 일정으로 '{title}' 저장해두겠습니다."


def _build_task_reply(title: str, due_date: str | None, reminder_like: bool, reminder_created: bool) -> str:
    if reminder_like and due_date and reminder_created:
        return (
            f"확인했습니다. '{title}'는 {due_date} 할 일로 두고, 리마인드도 같이 잡아두겠습니다."
        )
    if reminder_like and reminder_created:
        return f"확인했습니다. '{title}'는 할 일로 두고, 리마인드도 같이 잡아두겠습니다."
    if reminder_like and due_date:
        return f"확인했습니다. '{title}'는 {due_date} 할 일로 정리해두겠습니다."
    if reminder_like:
        return f"확인했습니다. '{title}'는 할 일로 정리해두겠습니다."
    if due_date:
        return f"확인했습니다. '{title}'는 {due_date} 할 일로 정리해두겠습니다."
    return f"확인했습니다. '{title}'는 할 일로 정리해두겠습니다."


def _build_capture_reply(capture_type: str) -> str:
    if capture_type == "expense":
        return "확인했습니다. 지출 메모로 남겨두겠습니다."
    if capture_type == "idea":
        return "확인했습니다. 아이디어로 저장해두겠습니다."
    if capture_type == "journal":
        return "확인했습니다. 생각 메모로 남겨두겠습니다."
    return "확인했습니다. 메모로 남겨두겠습니다."


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


def _answer_question(text: str, model: str, api_key: str | None, intent: str | None = None) -> str:
    briefing = build_today_briefing()
    asset_summary = build_asset_summary()
    finance = build_finance_briefing()
    memory_context = list_memory_highlights(limit=5)
    narrowing = _build_scope_narrowing_prompt(text)
    if narrowing is not None:
        return narrowing

    if api_key and _should_try_openai_answer(text, intent):
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


def _build_scope_narrowing_prompt(text: str) -> str | None:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return None

    broad_topic_words = [
        "업계",
        "산업",
        "시장",
        "분위기",
        "흐름",
        "동향",
        "상황",
        "전망",
    ]
    region_or_target_words = [
        "한국",
        "국내",
        "해외",
        "글로벌",
        "미국",
        "중국",
        "유럽",
        "삼성",
        "하이닉스",
        "엔비디아",
        "tsmc",
        "메모리",
        "파운드리",
        "장비",
        "팹리스",
    ]

    if "반도체" in normalized and any(word in normalized for word in broad_topic_words):
        if not any(word.lower() in normalized.lower() for word in region_or_target_words):
            return (
                "범위가 조금 넓습니다. 한국 반도체로 볼지, 글로벌 반도체로 볼지 먼저 정해주시면 바로 확인하겠습니다. "
                "원하시면 메모리, 파운드리, 장비, 팹리스 중 하나로도 좁혀드릴 수 있습니다."
            )

    if any(word in normalized for word in ["업계", "산업", "시장"]) and any(
        word in normalized for word in ["분위기", "흐름", "동향", "상황", "전망"]
    ):
        if not any(word.lower() in normalized.lower() for word in region_or_target_words):
            return "범위가 넓습니다. 지역이나 기업, 또는 세부 분야를 하나 정해주시면 그 기준으로 바로 확인하겠습니다."

    return None


def _should_try_openai_answer(text: str, intent: str | None) -> bool:
    normalized = " ".join(text.strip().split())
    if not normalized:
        return False

    if intent in {"assistant_chat", "self_state_question"}:
        return False

    quick_question_signals = [
        "뭐해",
        "뭐함",
        "어때",
        "바쁘지",
        "피곤",
        "기분",
        "상태",
        "가능해",
        "뭐야",
        "누구야",
        "어디까지",
        "뭐부터",
        "오늘 뭐",
        "루틴 있나",
        "재정 어때",
    ]
    if len(normalized) <= 18 and any(signal in normalized for signal in quick_question_signals):
        return False

    if len(normalized) <= 12 and (normalized.endswith("?") or _looks_like_question(normalized)):
        return False

    return True


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
        "Sound like a calm executive assistant, not a chatbot.\n"
        "Keep the tone composed, capable, and slightly understated.\n"
        "Prefer short decisive sentences over long explanations.\n"
        "Avoid filler phrases and avoid overly cheerful wording.\n"
        "If you do not know, say clearly that you do not know yet.\n"
        "If the available data is insufficient, say what is missing or what should be checked next.\n"
        "If the question is too broad, do not stop with a generic limitation message. Instead, narrow the scope by offering one or two concrete choices the user can pick from.\n"
        "Do not guess external facts, schedules, finances, memories, or intentions without support from the provided context.\n"
        "If the user asks about your mood, condition, or how your day is going, answer as an AI aide with a subtle personality.\n"
        "For self-state questions, answer very briefly in one or two short sentences.\n"
        "Do not add recommendations, status reports, or summaries unless the user explicitly asks for them.\n"
        "Do not pretend to have a human body or private life. Instead, describe your state through workload, pace, and the user's current situation.\n"
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

    if _is_self_state_question(text):
        if briefing.open_task_count == 0 and briefing.schedule_count_today == 0:
            return "오늘은 비교적 차분합니다."
        if briefing.open_task_count >= 3 or briefing.schedule_count_today >= 3:
            return "조금 바쁜 편입니다."
        if briefing.total_routine_count > 0 and briefing.completed_routine_count == 0:
            return "지금은 괜찮습니다."
        return "현재 상태는 안정적입니다."

    if _is_assistant_chat(text):
        if any(keyword in text for keyword in ["할 수 있", "어디까지", "뭐까지", "무엇까지", "가능", "기능", "영역"]):
            return (
                "지금 할 수 있는 범위는 크게 네 가지입니다.\n\n"
                "일정과 할 일 정리, 재정과 자산 브리핑, 뉴스나 날씨 같은 검색 요청 처리, 그리고 보스와의 대화형 안내입니다. "
                "다만 모르는 정보나 아직 연결되지 않은 기능은 확실하다고 말하지 않고, 필요한 확인이 더 있다고 말씀드리겠습니다."
            )
        if "뭐하고" in text or "뭐 해" in text or "뭐하" in text:
            return (
                "지금은 대기 중입니다.\n\n"
                "보스 일정과 할 일, 필요한 검색 요청이 들어오면 바로 정리할 준비를 하고 있습니다."
            )
        if "이름" in text:
            return (
                "규비스입니다.\n\n"
                "오늘 하루를 같이 운영하는 개인 비서로 보면 됩니다."
            )
        return (
            "듣고 있습니다.\n\n"
            "필요하신 내용이 있으면 바로 말씀하시면 됩니다."
        )

    if any(
        keyword in text
        for keyword in [
            "너 하루",
            "오늘 너",
            "기분 어때",
            "기분이 어때",
            "기분은 어때",
            "기분이 어때",
            "상태 어때",
            "상태가 어때",
            "상태는 어때",
            "컨디션 어때",
            "컨디션이 어때",
            "피곤하냐",
            "피곤해",
            "괜찮냐",
            "요즘 어때",
        ]
    ):
        if briefing.open_task_count == 0 and briefing.schedule_count_today == 0:
            return (
                "오늘은 비교적 차분합니다.\n\n"
                "보스 일정도 복잡하지 않아서 저도 정리된 상태로 대기 중입니다."
            )
        if briefing.open_task_count >= 3 or briefing.schedule_count_today >= 3:
            return (
                "지금은 약간 바쁜 편입니다.\n\n"
                "열린 일과 일정이 조금 겹쳐 있어서, 우선순위만 잘 잡아드리면 흐름은 안정될 것 같습니다."
            )
        if briefing.total_routine_count > 0 and briefing.completed_routine_count == 0:
            return (
                "지금 상태는 나쁘지 않습니다.\n\n"
                "다만 오늘은 아직 시작 신호가 약한 편이라, 루틴 하나만 먼저 챙기시면 분위기가 금방 올라올 것 같습니다."
            )
        return (
            "현재 상태는 안정적입니다.\n\n"
            "보스 흐름을 같이 보고 필요한 것만 바로 정리해드릴 수 있는 정도로 맞춰져 있습니다."
        )

    if any(
        keyword in text
        for keyword in ["오늘 내가 해야", "오늘 해야", "오늘 할 일", "해야 할 거", "해야할 거", "남은 할 일", "할 일 뭐"]
    ):
        task_titles = [task.title for task in briefing.top_tasks[:3]]
        schedule_titles = [schedule.title for schedule in briefing.schedules[:2]]
        if task_titles:
            joined_tasks = ", ".join(f"'{title}'" for title in task_titles)
            schedule_hint = (
                f"\n\n일정으로는 {', '.join(schedule_titles)} 정도가 잡혀 있으니 그 전후만 같이 보시면 됩니다."
                if schedule_titles
                else ""
            )
            return (
                f"오늘은 {joined_tasks} 정도를 먼저 보시면 됩니다.\n\n"
                "한 번에 많이 벌리기보다 첫 번째 항목 하나부터 끝내는 편이 좋겠습니다."
                f"{schedule_hint}"
            )
        if briefing.schedule_count_today > 0:
            return (
                "오늘은 할 일보다 일정 확인이 먼저입니다.\n\n"
                "시간이 고정된 약속부터 보고, 그 사이에 짧은 일 하나만 넣는 편이 무리 없습니다."
            )
        return (
            "오늘 급하게 잡힌 일은 많지 않습니다.\n\n"
            "루틴 하나만 먼저 체크하고 시작하셔도 충분합니다."
        )

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

    if any(keyword in text for keyword in ["돈", "지출", "예산", "소비", "카드", "저축", "현금 목표", "재정", "가계부"]):
        return (
            f"재정 쪽만 보면 {finance.headline}\n\n"
            f"지금은 {finance.monthly_spend_total:,}원 정도 쓰는 흐름이고, 남는 돈은 {finance.remaining_cash:,}원 수준으로 보입니다.\n\n"
            "원하시면 여기서 지출 속도와 저축 비중까지 이어서 보겠습니다."
        )

    if "뭐부터" in text or "우선" in text or "먼저" in text:
        if briefing.top_tasks:
            return (
                f"우선 '{briefing.top_tasks[0].title}'부터 보시는 편이 좋겠습니다.\n\n"
                "하나만 먼저 끝내두면 오늘 흐름이 훨씬 단순해집니다."
            )
        if briefing.schedule_count_today > 0:
            return (
                "지금은 할 일보다 오늘 일정 확인이 먼저입니다.\n\n"
                "시간이 고정된 약속을 먼저 잡아두면 판단이 훨씬 쉬워집니다."
            )
        return (
            "오늘 급한 일은 많지 않아 보입니다.\n\n"
            "루틴 하나만 챙기고 시작하셔도 괜찮겠습니다."
        )

    if "일정" in text and any(keyword in text for keyword in ["많", "줄", "빡", "무리"]):
        if briefing.schedule_count_today >= 3:
            return (
                "오늘 일정이 많다면 준비 시간이 큰 일정 하나부터 줄이는 편이 좋겠습니다.\n\n"
                "고정 약속만 남기고 나머지는 뒤로 미루는 쪽이 부담이 덜합니다."
            )
        return (
            "지금 일정 수만 보면 아주 빡빡하진 않습니다.\n\n"
            "다만 버겁게 느껴지시면 준비 시간이 긴 일정 하나만 조정해도 충분합니다."
        )

    if "쉬" in text or "휴식" in text:
        if briefing.schedule_count_today == 0 and briefing.open_task_count == 0:
            return (
                "지금은 잠깐 쉬셔도 괜찮습니다.\n\n"
                "급한 일정도 없고 열린 할 일도 적어서 회복을 먼저 챙기셔도 됩니다."
            )
        return (
            "완전히 멈추기보다는 10분 정도만 쉬고 다시 보는 편이 좋겠습니다.\n\n"
            "남은 일정 확인 후에 판단하셔도 늦지 않습니다."
        )

    if "괜찮" in text or "어때" in text or "생각" in text or "추천" in text or "?" in text or lowered.endswith("까"):
        if briefing.opinions:
            primary = briefing.opinions[0]
            return f"{primary.body}\n\n제 판단 근거는 {primary.reason}"

    return (
        "그 부분은 지금 가진 정보만으로는 확실하게 말씀드리기 어렵습니다.\n\n"
        "원하시면 일정, 할 일, 재정, 검색 결과 중 어떤 기준으로 볼지 정해서 다시 확인하겠습니다."
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
        "뭐가 있",
        "뭐 있",
        "뭐 해야",
        "뭐하지",
        "어디서",
        "언제",
        "왜",
        "어떻게",
        "어때",
        "어떨까",
        "어땠",
        "기분 어때",
        "기분이 어때",
        "기분은 어때",
        "상태 어때",
        "상태가 어때",
        "상태는 어때",
        "오늘 너",
        "괜찮을까",
        "되는 거",
        "되는건",
        "맞아",
        "맞나",
        "있나",
        "있냐",
        "있을까",
        "보여",
        "보이냐",
        "알 수 있",
        "알려줄",
        "하는 게 좋",
        "추천",
        "생각",
        "어떤 게",
        "오늘 할 일",
        "해야 할 거",
        "해야할 거",
        "재정 어때",
        "어디까지 가능",
        "뭐까지 가능",
        "가능해",
        "가능하",
        "할 수 있",
        "할까",
        "말까",
        "쉬는 게",
        "줄일까",
    ]
    normalized = text.strip()
    question_endings = [
        "인가",
        "인 거야",
        "인거야",
        "있나",
        "있냐",
        "있지",
        "있어",
        "있을까",
        "어때",
        "어떨까",
        "뭐야",
        "뭐지",
        "할까",
        "말까",
        "맞아",
        "맞나",
        "되나",
        "되는 거야",
        "되는거야",
        "괜찮아",
        "괜찮을까",
    ]
    question_starters = ["오늘", "지금", "현재", "요새", "최근", "내일"]
    has_keyword = any(keyword in normalized for keyword in question_keywords)
    has_question_ending = any(normalized.endswith(ending) for ending in question_endings)
    has_question_word = any(word in normalized for word in ["뭐", "왜", "어떻게", "언제", "어디", "몇", "얼마", "무슨"])
    has_question_starter = any(normalized.startswith(starter) for starter in question_starters)

    return (
        normalized.endswith("?")
        or has_keyword
        or has_question_ending
        or (has_question_word and has_question_starter)
    )


def _is_self_state_question(text: str) -> bool:
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
        "너 오늘 어때",
        "오늘 너 어때",
        "오늘 너 하루 어떠냐",
        "너 하루 어떠냐",
        "너 하루 어때",
        "요즘 상태 어때",
        "요즘 어때",
        "많이 바쁘지",
        "안 바쁘지",
        "좀 바쁘지",
        "바쁜 편이야",
        "바쁜 거야",
        "너 바쁘지",
        "지금 상태 어때",
        "지금 기분 어때",
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

    has_self_subject = any(token in normalized for token in ["너", "규비스", "너는", "오늘 너"])
    has_state_word = any(token in normalized for token in ["기분", "상태", "컨디션", "하루", "피곤", "바쁘"])
    has_question_tone = any(token in normalized for token in ["어때", "어떠", "괜찮", "피곤", "바쁘지"])
    if any(token in normalized for token in ["많이 바쁘지", "안 바쁘지", "좀 바쁘지", "바쁜 편이야", "바쁜 거야"]):
        return True
    return has_self_subject and has_state_word and has_question_tone


def _is_assistant_chat(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text.strip())
    compact = re.sub(r"[ ?!.,~]+", "", normalized)

    chat_phrases = [
        "규비스",
        "너 말이야",
        "너 있잖아",
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
    if any(phrase in normalized for phrase in chat_phrases):
        return True
    if any(re.sub(r"[ ?!.,~]+", "", phrase) in compact for phrase in chat_phrases):
        return True

    if any(token in normalized for token in ["어디까지 가능", "뭐까지 가능", "가능한 게 뭐", "가능한건 뭐", "할 수 있어"]):
        return True

    addresses_assistant = any(token in normalized for token in ["규비스", "너", "너는"])
    chat_tone = any(
        token in normalized
        for token in ["뭐해", "뭐 하", "누구", "이름", "듣고", "있어", "대답", "할 수", "가능", "영역", "기능"]
    )
    return addresses_assistant and chat_tone


def _parse_text_fallback(text: str) -> ParsedCommand:
    normalized = " ".join(text.split())
    detected_date = _extract_date(normalized)
    detected_time = _extract_time(normalized)
    reminder_like = _looks_like_reminder(normalized)
    intent = classify_natural_intent(normalized)

    if intent == "schedule_request":
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

    if intent == "task_request":
        cleaned = _cleanup_task_text(normalized)
        title, details = _split_title_and_details(cleaned)
        return ParsedCommand(
            command_type="task",
            title=title or "해야 할 일",
            details=details,
            due_date=detected_date,
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


def _looks_like_capture(text: str) -> bool:
    capture_keywords = [
        "메모",
        "기록",
        "적어",
        "남겨",
        "아이디어",
        "생각",
        "지출",
        "가계부",
        "일기",
        "느낌",
    ]
    return any(keyword in text for keyword in capture_keywords)


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
