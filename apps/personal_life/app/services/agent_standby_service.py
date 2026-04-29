from datetime import datetime

from ..storage.database import fetch_all
from .agent_news_service import get_agent_news_stats
from .blog_draft_service import get_latest_blog_draft


DEFAULT_AGENTS = [
    {
        "id": 1,
        "title": "오전 10시~오후 6시 IT 뉴스 요약",
        "status": "활성",
        "processing": "완료",
        "tone": "active",
    },
    {
        "id": 2,
        "title": "IT/모바일 관련 블로그 초안 추천",
        "status": "활성",
        "processing": "진행중",
        "tone": "active",
    },
    {
        "id": 3,
        "title": "코딩 / 앱 업데이트 처리",
        "status": "대기",
        "processing": "대기중",
        "tone": "idle",
    },
    {
        "id": 4,
        "title": "유튜브 아이디어 탐색",
        "status": "대기",
        "processing": "대기중",
        "tone": "idle",
    },
]

_active_agent_id: int | None = None
_detail_agent_id: int | None = None
_detail_requested_at: str | None = None

AGENT_TASK_TYPES = {
    1: ("agent1_it_news_window",),
    2: ("agent2_it_blog_draft", "naver_blog_fill_draft"),
    3: ("coding_app_update",),
    4: ("youtube_idea_research",),
}


def get_agent_standby_status() -> dict:
    agents = [dict(agent) for agent in DEFAULT_AGENTS]
    _apply_agent1_news_state(agents[0])
    _apply_agent2_draft_state(agents[1])
    for agent in agents:
        _apply_agent_task_state(agent, AGENT_TASK_TYPES.get(agent["id"], ()))
    return {
        "active_agent_id": _active_agent_id,
        "detail_agent_id": _detail_agent_id,
        "detail_requested_at": _detail_requested_at,
        "agents": agents,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def focus_agent(agent_id: int | None) -> dict:
    global _active_agent_id
    valid_ids = {agent["id"] for agent in DEFAULT_AGENTS}
    _active_agent_id = agent_id if agent_id in valid_ids else None
    return get_agent_standby_status()


def open_agent_detail(agent_id: int | None) -> dict:
    global _active_agent_id, _detail_agent_id, _detail_requested_at
    valid_ids = {agent["id"] for agent in DEFAULT_AGENTS}
    selected_agent_id = agent_id if agent_id in valid_ids else None
    _active_agent_id = selected_agent_id
    _detail_agent_id = selected_agent_id
    _detail_requested_at = datetime.now().isoformat(timespec="milliseconds")
    return get_agent_standby_status()


def recover_agent(agent_id: int | None) -> dict:
    global _active_agent_id
    valid_ids = {agent["id"] for agent in DEFAULT_AGENTS}
    if agent_id not in valid_ids:
        return get_agent_standby_status()

    _active_agent_id = agent_id
    return get_agent_standby_status()


def build_agent_status_reply(agent_id: int | None = None) -> str:
    state = get_agent_standby_status()
    agents = state["agents"]
    if agent_id is not None:
        agent = next((item for item in agents if item["id"] == agent_id), None)
        if agent is None:
            return "현재 표시 가능한 에이전트는 1번부터 4번까지입니다."
        return _build_single_agent_reply(agent)

    active_count = sum(1 for agent in agents if agent.get("tone") == "active")
    error_count = sum(1 for agent in agents if agent.get("tone") == "error")
    idle_count = max(len(agents) - active_count - error_count, 0)
    lines = [
        f"현재 에이전트는 총 {len(agents)}개입니다. 활성 {active_count}개, 대기 {idle_count}개, 확인 필요 {error_count}개로 보입니다."
    ]
    for agent in agents:
        lines.append(f"{agent['id']}번은 {agent['title']} 담당이고, 상태는 {agent['status']}, 처리는 {agent['processing']}입니다.")
    return " ".join(lines)


def _apply_agent1_news_state(agent: dict) -> None:
    try:
        stats = get_agent_news_stats(agent_id=1)
    except Exception:
        agent["status"] = "확인중"
        agent["processing"] = "뉴스 저장소 확인중"
        agent["tone"] = "idle"
        return

    collected_count = int(stats.get("collected_count") or 0)
    report = stats.get("report")
    agent["collected_count"] = collected_count
    agent["selected_count"] = int(stats.get("selected_count") or 0)
    agent["latest_titles"] = stats.get("latest_titles") or []
    agent["last_collected_at"] = stats.get("last_collected_at")
    agent["report"] = report
    if report:
        agent["status"] = "완료"
        agent["processing"] = f"{collected_count}건 수집 / 보고 완료"
        agent["tone"] = "active"
    elif collected_count:
        agent["status"] = "활성"
        agent["processing"] = f"{collected_count}건 수집 / 선별중"
        agent["tone"] = "active"
    else:
        agent["status"] = "대기"
        agent["processing"] = "10:00 수집 대기"
        agent["tone"] = "idle"


def _apply_agent2_draft_state(agent: dict) -> None:
    try:
        draft = get_latest_blog_draft()
    except Exception:
        return

    if not draft:
        return

    body = str(draft.get("body") or "")
    preview = body[:520].strip()
    if len(body) > len(preview):
        preview += "..."
    agent["draft"] = {
        "id": draft.get("id"),
        "title": draft.get("title"),
        "body_preview": preview,
        "status": draft.get("status"),
        "created_at": str(draft.get("created_at") or ""),
    }
    agent["status"] = "활성"
    agent["processing"] = f"초안 #{draft.get('id')} 준비"
    agent["tone"] = "active"


def _apply_agent_task_state(agent: dict, task_types: tuple[str, ...]) -> None:
    try:
        tasks = _list_recent_tasks_by_type(task_types, limit=8)
    except Exception as error:
        agent["tasks"] = []
        agent["latest_task"] = {
            "status": "failed",
            "error_message": str(error),
        }
        agent["status"] = "확인 필요"
        agent["processing"] = "작업 큐 확인 실패"
        agent["tone"] = "error"
        return

    agent["tasks"] = [_task_payload(task) for task in tasks]
    if not tasks:
        return

    pending_count = sum(1 for task in tasks if task.get("status") == "pending")
    claimed_count = sum(1 for task in tasks if task.get("status") == "claimed")
    failed_count = sum(1 for task in tasks if task.get("status") == "failed")
    completed_count = sum(1 for task in tasks if task.get("status") == "completed")
    latest = tasks[0]

    if failed_count:
        agent["status"] = "확인 필요"
        agent["processing"] = f"실패 {failed_count}건 / 최근 #{latest.get('id')}"
        agent["tone"] = "error"
    elif claimed_count:
        agent["status"] = "활성"
        agent["processing"] = f"진행중 {claimed_count}건 / 대기 {pending_count}건"
        agent["tone"] = "active"
    elif pending_count:
        agent["status"] = "대기"
        agent["processing"] = f"작업 대기 {pending_count}건"
        agent["tone"] = "idle"
    elif completed_count:
        # Keep stronger data-derived state such as agent1 collected count or agent2 draft ready.
        if agent.get("tone") not in {"active", "error"}:
            agent["status"] = "완료"
            agent["processing"] = f"최근 작업 #{latest.get('id')} 완료"
            agent["tone"] = "active"

    agent["latest_task"] = _task_payload(latest)


def _list_recent_tasks_by_type(task_types: tuple[str, ...], limit: int = 8) -> list[dict]:
    if not task_types:
        return []
    placeholders = ", ".join("?" for _ in task_types)
    return fetch_all(
        f"""
        SELECT *
        FROM agent_tasks
        WHERE task_type IN ({placeholders})
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (*task_types, limit),
    )


def _task_payload(task: dict) -> dict:
    return {
        "id": task.get("id"),
        "task_type": task.get("task_type"),
        "status": task.get("status"),
        "command_text": task.get("command_text"),
        "result_summary": task.get("result_summary"),
        "error_message": task.get("error_message"),
        "created_at": str(task.get("created_at") or ""),
        "completed_at": str(task.get("completed_at") or ""),
    }


def _build_single_agent_reply(agent: dict) -> str:
    base = f"에이전트 {agent['id']}번은 {agent['title']} 담당입니다. 현재 상태는 {agent['status']}, 처리는 {agent['processing']}입니다."
    if agent["id"] != 1:
        latest_task = agent.get("latest_task") or {}
        if latest_task:
            task_status = latest_task.get("status")
            task_text = latest_task.get("command_text") or latest_task.get("result_summary") or latest_task.get("error_message")
            if task_text:
                return f"{base} 최근 작업 #{latest_task.get('id')}은 {task_status} 상태이며, 내용은 {task_text}입니다."
        return base

    collected_count = int(agent.get("collected_count") or 0)
    report = agent.get("report")
    if report:
        return f"{base} 오늘 수집된 IT 뉴스는 {collected_count}건이고, 최종 보고가 생성되어 있습니다."
    if collected_count:
        return f"{base} 오늘 수집된 IT 뉴스는 {collected_count}건이며, 18시에 최종 보고로 정리됩니다."
    return f"{base} 상시 수집 시간은 10시부터 18시까지입니다. 아직 오늘 수집된 뉴스는 없습니다."
