from __future__ import annotations

from datetime import date
from typing import Any

from ..domain.schemas import AssistantOpinion, BriefingDigestResponse, BriefingInsight, BriefingResponse
from .capture_service import count_captures_for_day
from .memory_service import get_memory_value, list_memory_highlights
from .money_core_service import build_money_core_summary
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

    money = _safe_money_summary()
    agent = _safe_agent_report_summary()
    message = _build_today_message(open_task_count, schedule_count_today)
    if _prefers_answer_first():
        message = f"핵심부터 말씀드리면, {message}"

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
        insights=build_briefing_insights(
            open_task_count=open_task_count,
            schedule_count_today=schedule_count_today,
            completed_routine_count=completed_routine_count,
            total_routine_count=total_routine_count,
            money=money,
            agent=agent,
        ),
        opinions=build_assistant_opinions(
            open_task_count=open_task_count,
            schedule_count_today=schedule_count_today,
            completed_routine_count=completed_routine_count,
            total_routine_count=total_routine_count,
            top_tasks=top_tasks,
            schedules=schedules,
            money=money,
            agent=agent,
        )
        if include_opinions
        else [],
    )


def build_morning_briefing() -> BriefingDigestResponse:
    briefing = build_today_briefing(include_opinions=False)
    money = _safe_money_summary()
    agent = _safe_agent_report_summary()
    due_reminders = list_due_reminders(briefing.today, limit=3)
    bullets: list[str] = []

    if due_reminders:
        bullets.append(f"먼저 챙길 리마인드는 {', '.join(reminder.title for reminder in due_reminders[:2])}입니다.")
    if briefing.schedules:
        first = briefing.schedules[0]
        time_text = f" {first.start_time}" if first.start_time else ""
        bullets.append(f"오늘 첫 일정은 '{first.title}'{time_text}입니다. 이동과 준비 시간을 먼저 확인해두면 좋겠습니다.")
    if briefing.top_tasks:
        bullets.append(f"할 일은 '{briefing.top_tasks[0].title}'부터 하나만 먼저 붙잡는 흐름을 추천드립니다.")
    if money.get("monthly_spend_total"):
        bullets.append(f"Money Core 기준 이번 달 소비는 {_won(money['monthly_spend_total'])}, 남은 현금은 {_won(money.get('remaining_cash'))}입니다.")
    if agent.get("news_count") or agent.get("draft_count"):
        bullets.append(f"Agent Report에는 뉴스 {agent.get('news_count', 0)}건, 블로그 초안 {agent.get('draft_count', 0)}개가 준비되어 있습니다.")
    if not bullets:
        bullets.append("오늘은 급하게 몰린 항목이 적어 보입니다. 일정 확인 후 가장 작은 루틴 하나부터 시작해보세요.")

    return BriefingDigestResponse(
        period="morning",
        headline="오늘의 첫 움직임만 정리하면 충분히 좋은 출발을 만들 수 있습니다.",
        bullets=bullets[:4],
    )


def build_evening_briefing() -> BriefingDigestResponse:
    briefing = build_today_briefing(include_opinions=False)
    money = _safe_money_summary()
    agent = _safe_agent_report_summary()
    bullets: list[str] = [
        f"오늘 완료한 할 일은 {briefing.completed_today_count}개, 기록한 메모는 {briefing.capture_count_today}개입니다."
    ]

    if briefing.top_tasks:
        bullets.append(f"내일로 넘길 후보는 '{briefing.top_tasks[0].title}'부터 확인하면 정리가 빠르겠습니다.")
    elif not briefing.schedules:
        bullets.append("오늘 등록된 일정과 할 일은 비교적 가볍게 마무리된 상태입니다.")
    if briefing.total_routine_count:
        bullets.append(f"루틴은 {briefing.completed_routine_count}/{briefing.total_routine_count}개 진행했습니다.")
    if money.get("monthly_spend_total"):
        bullets.append(f"재정 흐름은 이번 달 소비 {_won(money['monthly_spend_total'])}, 카드 사용률 {round(float(money.get('card_usage_rate') or 0) * 100)}%입니다.")
    if agent.get("pending_codex_count"):
        bullets.append(f"Codex 승인 대기 후보가 {agent['pending_codex_count']}건 있습니다. 자동 배포 없이 검토 중심으로 남겨두었습니다.")

    return BriefingDigestResponse(
        period="evening",
        headline="오늘 하루도 고생하셨습니다. 내일 아침이 가벼워지도록 핵심만 정리해두겠습니다.",
        bullets=bullets[:4],
    )


def build_briefing_insights(
    open_task_count: int,
    schedule_count_today: int,
    completed_routine_count: int,
    total_routine_count: int,
    money: dict[str, Any] | None = None,
    agent: dict[str, Any] | None = None,
) -> list[BriefingInsight]:
    insights: list[BriefingInsight] = []
    money = money or {}
    agent = agent or {}

    for item in list_memory_highlights(limit=2):
        insights.append(
            BriefingInsight(
                title=f"{item['category']} · {item['memory_key']}",
                body=f"{item['value_text']} ({item['memory_kind']}, {item['confidence']})",
            )
        )
    if open_task_count:
        insights.append(BriefingInsight(title="오늘의 집중 포인트", body=f"열린 할 일이 {open_task_count}개 있습니다. 가장 작은 항목부터 닫아가면 흐름이 안정됩니다."))
    if schedule_count_today:
        insights.append(BriefingInsight(title="일정 감각", body=f"오늘 일정은 {schedule_count_today}건입니다. 첫 일정 전 준비 시간을 먼저 확보해두세요."))
    if total_routine_count:
        insights.append(BriefingInsight(title="생활 리듬", body=f"루틴은 {completed_routine_count}/{total_routine_count}개 진행 중입니다."))
    if money.get("monthly_spend_total") or money.get("salary"):
        insights.append(
            BriefingInsight(
                title="Money Core",
                body=f"이번 달 소비는 {_won(money.get('monthly_spend_total'))}, 남은 현금은 {_won(money.get('remaining_cash'))}입니다.",
            )
        )
    if agent.get("news_count") or agent.get("draft_count"):
        insights.append(
            BriefingInsight(
                title="Agent Report",
                body=f"최신 IT 뉴스 {agent.get('news_count', 0)}건, 블로그 초안 {agent.get('draft_count', 0)}개, 유튜브 아이디어 {agent.get('idea_count', 0)}개가 있습니다.",
            )
        )
    if not insights:
        insights.append(BriefingInsight(title="가벼운 시작", body="아직 개인화 데이터가 많지 않습니다. 일정, 소비, 메모를 조금씩 쌓으면 브리핑이 더 정확해집니다."))
    return insights[:5]


def build_assistant_opinions(
    open_task_count: int,
    schedule_count_today: int,
    completed_routine_count: int,
    total_routine_count: int,
    top_tasks: list,
    schedules: list,
    money: dict[str, Any] | None = None,
    agent: dict[str, Any] | None = None,
) -> list[AssistantOpinion]:
    opinions: list[AssistantOpinion] = []
    money = money or {}
    agent = agent or {}

    if schedules:
        opinions.append(
            AssistantOpinion(
                title="첫 일정 전 준비물을 먼저 정리해두면 좋겠습니다",
                body=f"오늘은 '{schedules[0].title}' 일정이 보입니다. 출발 전 필요한 메모나 준비물을 한 번만 확인해두면 하루가 덜 흔들릴 것 같습니다.",
                reason="시간이 고정된 항목은 미리 정리할수록 뒤쪽 일정의 부담이 줄어듭니다.",
            )
        )
    if top_tasks:
        opinions.append(
            AssistantOpinion(
                title="할 일은 하나만 먼저 닫는 쪽이 좋아 보입니다",
                body=f"지금은 '{top_tasks[0].title}'부터 처리하는 흐름을 추천드립니다. 여러 개를 동시에 펼치기보다 첫 항목을 끝내면 다음 판단이 쉬워집니다.",
                reason="열린 작업 수를 줄이면 일정, 루틴, 콘텐츠 작업의 체감 부담이 같이 내려갑니다.",
            )
        )
    if money.get("card_usage_rate", 0) >= 0.8:
        opinions.append(
            AssistantOpinion(
                title="오늘은 카드보다 현금 흐름 기준으로 보는 편이 안전합니다",
                body=f"카드 사용률이 {round(float(money.get('card_usage_rate') or 0) * 100)}%입니다. 결제 전까지는 큰 지출 후보를 한 번 걸러보는 쪽이 좋겠습니다.",
                reason="카드 사용률이 높을 때는 남은 현금과 결제 예정액을 같이 보는 편이 안전합니다.",
            )
        )
    if agent.get("draft_count"):
        opinions.append(
            AssistantOpinion(
                title="콘텐츠는 초안 하나만 열어보면 충분합니다",
                body=f"블로그 초안이 {agent['draft_count']}개 있습니다. 오늘은 발행까지 가지 않고, 가장 괜찮은 초안 하나를 읽고 다듬는 정도가 좋아 보입니다.",
                reason="Creator Studio 흐름은 검토와 입력을 분리해두었기 때문에 부담 없이 다음 단계만 고르면 됩니다.",
            )
        )
    if total_routine_count and completed_routine_count < total_routine_count:
        opinions.append(
            AssistantOpinion(
                title="루틴은 가장 짧은 것 하나만 체크해도 충분합니다",
                body=f"아직 {total_routine_count - completed_routine_count}개 루틴이 남아 있습니다. 오늘의 리듬을 되살리는 용도로 가장 짧은 루틴 하나만 먼저 해보세요.",
                reason="작은 완료 표시 하나가 남은 작업을 시작하기 쉽게 만듭니다.",
            )
        )
    if not opinions:
        opinions.append(
            AssistantOpinion(
                title="오늘은 흐름을 무리하게 채우지 않아도 괜찮습니다",
                body="급하게 몰린 일정이나 작업이 많지 않아 보입니다. 메모 하나, 소비 기록 하나처럼 작은 기록만 남겨도 GyuOS가 다음 브리핑을 더 잘 준비할 수 있습니다.",
                reason="비어 있는 날은 생산성을 밀어붙이기보다 다음 날을 위한 맥락을 쌓기 좋습니다.",
            )
        )
    return opinions[:3]


def _build_today_message(open_task_count: int, schedule_count_today: int) -> str:
    if open_task_count == 0 and schedule_count_today == 0:
        return "오늘은 일정과 할 일이 비교적 가벼운 편입니다. 루틴 하나와 기록 하나만 챙겨도 충분히 좋은 하루가 되겠습니다."
    if open_task_count == 0:
        return "오늘은 일정 중심으로만 차분히 움직이면 되겠습니다. 첫 일정 준비부터 확인해볼게요."
    if schedule_count_today == 0:
        return f"오늘은 열린 할 일 {open_task_count}개가 있습니다. 시간 제약은 적으니 가장 중요한 하나부터 닫아보면 좋겠습니다."
    return f"오늘은 일정 {schedule_count_today}건과 열린 할 일 {open_task_count}개가 있습니다. 우선순위를 잡아서 부담을 줄여드리겠습니다."


def _safe_money_summary() -> dict[str, Any]:
    try:
        return build_money_core_summary()
    except Exception:
        return {}


def _safe_agent_report_summary() -> dict[str, Any]:
    try:
        from .agent_report_center_service import build_agent_report_center

        report = build_agent_report_center()
        return {
            "news_count": int(report.get("agent1", {}).get("display_count") or 0),
            "draft_count": len(report.get("agent2", {}).get("drafts") or []),
            "idea_count": len(report.get("agent4", {}).get("ideas") or []),
            "pending_codex_count": len(report.get("agent3", {}).get("codex_pending_tasks") or []),
        }
    except Exception:
        return {}


def _prefers_answer_first() -> bool:
    structure_pref = get_memory_value("ideal_response_mode", "structure")
    return bool(structure_pref and "answer_first" in structure_pref)


def _won(value: Any) -> str:
    return f"{int(value or 0):,}원"
