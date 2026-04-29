import json
from datetime import date

from ..config import get_settings
from ..domain.schemas import AssistantOpinion, BriefingDigestResponse, BriefingInsight, BriefingResponse
from .capture_service import count_captures_for_day
from .memory_service import get_memory_value, list_memory_highlights
from .reminder_service import list_due_reminders
from .routine_service import count_completed_routines_for_day, count_routines, list_routine_checkins
from .schedule_service import count_schedules_for_day, list_schedules
from .task_service import count_completed_today, count_open_tasks, list_tasks


def build_today_briefing(include_opinions: bool = True) -> BriefingResponse:
    today = date.today().isoformat()
    open_task_count = count_open_tasks()
    completed_today_count = count_completed_today(today)
    capture_count_today = count_captures_for_day(today)
    schedule_count_today = count_schedules_for_day(today)
    completed_routine_count = count_completed_routines_for_day(today)
    total_routine_count = count_routines()
    top_tasks = list_tasks(status="open", limit=3)
    schedules = list_schedules(day=today)
    routine_checkins = list_routine_checkins(day=today)

    insights = build_briefing_insights(
        open_task_count=open_task_count,
        schedule_count_today=schedule_count_today,
        completed_routine_count=completed_routine_count,
        total_routine_count=total_routine_count,
    )
    opinions = (
        build_assistant_opinions(
            today=today,
            open_task_count=open_task_count,
            schedule_count_today=schedule_count_today,
            completed_routine_count=completed_routine_count,
            total_routine_count=total_routine_count,
            top_tasks=top_tasks,
            schedules=schedules,
        )
        if include_opinions
        else []
    )

    prefers_directness = get_memory_value("communication_style", "prefers_directness")
    structure_pref = get_memory_value("ideal_response_mode", "structure")

    if open_task_count == 0 and schedule_count_today == 0:
        message = "오늘은 크게 밀린 일은 없어 보여요. 루틴 하나만 챙기고 편하게 흐름을 가져가셔도 괜찮겠습니다."
    elif open_task_count == 0:
        message = "오늘은 할 일보다 일정 쪽만 차분히 챙기면 되겠습니다. 출발 전 준비만 먼저 봐두시면 편할 것 같아요."
    elif prefers_directness == "True":
        message = (
            f"오늘은 열린 할 일 {open_task_count}개가 있습니다. "
            "제 기준으로는 가장 앞의 한 가지부터 먼저 정리하는 흐름이 좋겠습니다."
        )
    else:
        message = (
            f"오늘은 열린 할 일 {open_task_count}개가 있어요. "
            "우선순위가 높은 것부터 하나씩 정리해가면 하루가 훨씬 덜 복잡하게 느껴질 것 같습니다."
        )

    if structure_pref and "answer_first" in structure_pref:
        message = f"핵심만 먼저 말씀드리면, {message}"

    return BriefingResponse(
        today=today,
        open_task_count=open_task_count,
        completed_today_count=completed_today_count,
        capture_count_today=capture_count_today,
        schedule_count_today=schedule_count_today,
        completed_routine_count=completed_routine_count,
        total_routine_count=total_routine_count,
        top_tasks=top_tasks,
        schedules=schedules,
        routine_checkins=routine_checkins,
        message=message,
        insights=insights,
        opinions=opinions,
    )


def build_morning_briefing() -> BriefingDigestResponse:
    briefing = build_today_briefing(include_opinions=False)
    due_reminders = list_due_reminders(briefing.today, limit=3)

    bullets: list[str] = []
    if due_reminders:
        bullets.append(f"먼저 챙길 리마인드는 {', '.join(reminder.title for reminder in due_reminders[:2])} 정도가 보입니다.")
    if briefing.schedules:
        first_schedule = briefing.schedules[0]
        time_text = f" {first_schedule.start_time}" if first_schedule.start_time else ""
        bullets.append(f"오늘 첫 일정은 '{first_schedule.title}'{time_text}입니다. 준비물과 이동만 미리 보면 편하겠습니다.")
    if briefing.top_tasks:
        bullets.append(f"할 일은 '{briefing.top_tasks[0].title}' 하나만 먼저 붙잡는 쪽을 추천드리고 싶어요.")
    if briefing.total_routine_count > briefing.completed_routine_count:
        bullets.append("루틴은 가장 짧은 것 하나만 먼저 체크해두면 하루 리듬이 빨리 잡힐 것 같습니다.")
    if not bullets:
        bullets.append("오늘은 크게 급한 건 없어 보여요. 일정 확인만 하고 여유 있게 시작하셔도 괜찮겠습니다.")

    return BriefingDigestResponse(
        period="morning",
        headline="아침에는 오늘의 첫 움직임만 정해두면 충분해 보입니다.",
        bullets=bullets[:4],
    )


def build_evening_briefing() -> BriefingDigestResponse:
    briefing = build_today_briefing(include_opinions=False)
    open_tasks = briefing.top_tasks
    bullets: list[str] = []

    bullets.append(f"오늘 완료한 할 일은 {briefing.completed_today_count}개, 기록한 메모는 {briefing.capture_count_today}개입니다.")
    if open_tasks:
        bullets.append(f"내일로 넘길 후보는 '{open_tasks[0].title}'부터 보시면 정리가 쉬울 것 같아요.")
    if briefing.schedules:
        bullets.append(f"내일 대비해서 '{briefing.schedules[0].title}' 관련 준비물을 미리 적어두면 아침이 훨씬 가벼워집니다.")
    if briefing.total_routine_count > 0:
        bullets.append(
            f"루틴은 오늘 {briefing.completed_routine_count} / {briefing.total_routine_count} 진행했습니다. "
            "조금이라도 한 건 챙겼다면 흐름은 유지된 걸로 봐도 좋겠습니다."
        )

    return BriefingDigestResponse(
        period="evening",
        headline="저녁에는 남은 일보다 내일 아침을 가볍게 만드는 정리만 해두면 좋겠습니다.",
        bullets=bullets[:4],
    )


def build_evening_briefing() -> BriefingDigestResponse:
    briefing = build_today_briefing(include_opinions=False)
    open_tasks = briefing.top_tasks
    bullets: list[str] = []

    bullets.append(f"오늘 완료한 할 일은 {briefing.completed_today_count}개, 기록한 메모는 {briefing.capture_count_today}개입니다.")
    if open_tasks:
        bullets.append(f"내일로 넘길 후보는 '{open_tasks[0].title}'부터 보시면 정리가 쉬울 것 같습니다.")
    elif not briefing.schedules:
        bullets.append("오늘 등록된 일정은 모두 마무리되었습니다.")
    if briefing.schedules:
        bullets.append(f"내일을 대비해 '{briefing.schedules[0].title}' 관련 준비물을 미리 적어두면 아침이 가벼워집니다.")
    if briefing.total_routine_count > 0:
        bullets.append(
            f"루틴은 오늘 {briefing.completed_routine_count} / {briefing.total_routine_count} 진행했습니다. "
            "조금이라도 챙겼다면 흐름은 유지된 것으로 봐도 좋겠습니다."
        )

    return BriefingDigestResponse(
        period="evening",
        headline="저녁에는 남은 일보다 내일 아침을 가볍게 만드는 정리만 해두면 좋겠습니다.",
        bullets=bullets[:4],
    )


def build_briefing_insights(
    open_task_count: int,
    schedule_count_today: int,
    completed_routine_count: int,
    total_routine_count: int,
) -> list[BriefingInsight]:
    insights: list[BriefingInsight] = []

    for item in list_memory_highlights(limit=3):
        insights.append(
            BriefingInsight(
                title=f"{item['category']} · {item['memory_key']}",
                body=f"{item['value_text']} ({item['memory_kind']}, {item['confidence']})",
            )
        )

    if open_task_count > 0:
        insights.append(
            BriefingInsight(
                title="오늘의 집중 포인트",
                body=f"열린 할 일 {open_task_count}개 중 가장 중요한 한 가지부터 처리하는 흐름이 좋아 보여요.",
            )
        )

    if schedule_count_today > 0:
        insights.append(
            BriefingInsight(
                title="일정 감각",
                body=f"오늘 일정 {schedule_count_today}개가 있습니다. 외출 전 준비 시간을 미리 잡아두시면 덜 바쁠 거예요.",
            )
        )

    if total_routine_count > 0:
        insights.append(
            BriefingInsight(
                title="생활 리듬",
                body=f"루틴은 {completed_routine_count} / {total_routine_count} 진행 중입니다.",
            )
        )

    if not insights:
        insights.append(
            BriefingInsight(
                title="가벼운 시작",
                body="기억과 일정이 더 쌓이면 비서가 지금보다 더 개인적인 제안을 드릴 수 있어요.",
            )
        )

    return insights[:5]


def build_assistant_opinions(
    today: str,
    open_task_count: int,
    schedule_count_today: int,
    completed_routine_count: int,
    total_routine_count: int,
    top_tasks: list,
    schedules: list,
) -> list[AssistantOpinion]:
    settings = get_settings()
    if settings.has_openai:
        generated = build_assistant_opinions_with_openai(
            today=today,
            open_task_count=open_task_count,
            schedule_count_today=schedule_count_today,
            completed_routine_count=completed_routine_count,
            total_routine_count=total_routine_count,
            top_tasks=top_tasks,
            schedules=schedules,
            model=settings.openai_model,
            api_key=settings.openai_api_key,
        )
        if generated:
            return generated

    opinions: list[AssistantOpinion] = []

    if schedule_count_today > 0:
        first_schedule = schedules[0].title if schedules else "오늘 일정"
        opinions.append(
            AssistantOpinion(
                title="일정부터 한 번만 정리해두면 좋겠습니다",
                body=(
                    f"오늘은 '{first_schedule}' 일정이 있어서, 약속 시간과 이동 준비만 먼저 확인해두시면 마음이 한결 편하실 것 같아요. "
                    "출발 전에 급하게 챙기지 않도록 필요한 메모나 준비물을 지금 한 번만 보고 넘어가시면 좋겠습니다."
                ),
                reason="오늘은 시간 고정 요소가 있어서, 일정 준비를 먼저 끝내두는 편이 하루 전체 흐름을 안정적으로 만들어줍니다.",
            )
        )

    if top_tasks:
        opinions.append(
            AssistantOpinion(
                title="할 일은 하나만 먼저 끝내는 쪽이 좋아 보입니다",
                body=(
                    f"지금은 '{top_tasks[0].title}' 하나만 먼저 끝내는 방향을 추천드리고 싶어요. "
                    "여러 개를 동시에 붙잡기보다 첫 번째 항목만 정리해두면 그다음 판단이 훨씬 가벼워질 가능성이 큽니다."
                ),
                reason="우선순위가 있는 작업 하나를 먼저 끝내면 남은 일정과 루틴을 볼 때 압박감이 줄어듭니다.",
            )
        )
    elif schedule_count_today == 0:
        opinions.append(
            AssistantOpinion(
                title="오늘은 조금 여유 있게 운영하셔도 되겠습니다",
                body=(
                    "급하게 밀어붙여야 할 항목은 많지 않아 보여요. "
                    "루틴 하나만 챙기고, 남는 시간은 정리성 업무나 머리를 덜 쓰는 일부터 가볍게 손대보시면 좋겠습니다."
                ),
                reason="열린 할 일과 일정이 많지 않은 날에는 속도를 올리기보다 리듬을 유지하는 편이 오래 갑니다.",
            )
        )

    if total_routine_count > 0:
        remaining = max(total_routine_count - completed_routine_count, 0)
        if remaining > 0:
            opinions.append(
                AssistantOpinion(
                    title="루틴은 크게 잡지 말고 하나만 가볍게 끝내보시죠",
                    body=(
                        f"루틴이 아직 {remaining}개 남아 있는데, 전부 한 번에 끝내려 하기보다 가장 짧은 것 하나만 먼저 체크하시면 좋겠습니다. "
                        "작게라도 완료 표시가 하나 생기면 그 뒤 컨디션도 조금 더 정돈되는 편입니다."
                    ),
                    reason="루틴은 양보다 흐름 유지가 중요해서, 작은 완료 하나가 하루 분위기를 바꾸는 경우가 많습니다.",
                )
            )

    if not opinions:
        opinions.append(
            AssistantOpinion(
                title="오늘은 무리해서 벌리기보다 흐름만 지켜보시죠",
                body="당장 급하게 치고 나가야 할 건 없어 보여요. 일정 확인과 컨디션 점검 정도만 해두시면 충분해 보입니다.",
                reason="비어 있는 날은 무리하게 채우기보다 다음 며칠을 위해 정돈하는 쪽이 더 효율적일 때가 많습니다.",
            )
        )

    return opinions[:3]


def build_assistant_opinions_with_openai(
    today: str,
    open_task_count: int,
    schedule_count_today: int,
    completed_routine_count: int,
    total_routine_count: int,
    top_tasks: list,
    schedules: list,
    model: str,
    api_key: str | None,
) -> list[AssistantOpinion] | None:
    if not api_key:
        return None

    try:
        from openai import OpenAI
    except ImportError:
        return None

    memory_context = list_memory_highlights(limit=5)
    top_task_text = [task.title for task in top_tasks[:3]]
    schedule_text = [schedule.title for schedule in schedules[:3]]
    prompt = (
        "You are an in-person Korean personal assistant sitting beside the user and looking over today's plan.\n"
        "Return JSON only as an array of 2 or 3 objects.\n"
        "Each object must have: title, body, reason.\n"
        "Write like a real human aide, not a dashboard or report.\n"
        "Prefer soft recommendation language such as '좋겠습니다', '같아요', '추천드리고 싶어요'.\n"
        "Do not sound stiff, managerial, or overly formal.\n"
        "Avoid numbered plans, checklists, and generic productivity jargon unless truly necessary.\n"
        "Each title should read like a natural cue, not a report heading.\n"
        "Each body should be 2-3 Korean sentences, warm but practical, grounded in today's context.\n"
        "Each reason should be one sentence explaining why that suggestion makes sense today.\n"
        f"Today is {today}.\n"
        f"Open tasks: {open_task_count}\n"
        f"Today's schedules: {schedule_count_today}\n"
        f"Routines completed: {completed_routine_count}/{total_routine_count}\n"
        f"Top tasks: {json.dumps(top_task_text, ensure_ascii=False)}\n"
        f"Schedules: {json.dumps(schedule_text, ensure_ascii=False)}\n"
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
        if not content:
            return None
        parsed = json.loads(content)
        return [
            AssistantOpinion(
                title=item["title"],
                body=item["body"],
                reason=item["reason"],
            )
            for item in parsed[:3]
        ]
    except Exception:
        return None
