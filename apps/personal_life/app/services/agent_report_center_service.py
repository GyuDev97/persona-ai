import json
import re
from datetime import date
from typing import Any

from ..storage.database import fetch_all
from .agent_news_service import AGENT1_ID, get_agent_news_stats, list_agent_news_items
from .agent_standby_service import get_agent_standby_status
from .agent_task_service import create_agent_task
from .blog_draft_service import get_blog_draft, list_blog_drafts


AGENT_TASK_TYPES = {
    1: ("agent1_it_news_window",),
    2: ("agent2_it_blog_draft", "naver_blog_fill_draft"),
    3: ("coding_app_update",),
    4: ("youtube_idea_research",),
}


def build_agent_report_center() -> dict[str, Any]:
    standby = get_agent_standby_status()
    today = date.today().isoformat()
    cards = []
    for agent in standby.get("agents", []):
        agent_id = int(agent.get("id") or 0)
        latest_task = _latest_task_for_agent(agent_id)
        cards.append(_build_agent_card(agent, latest_task))

    return {
        "date": today,
        "updated_at": standby.get("updated_at"),
        "cards": cards,
        "agent1": _build_agent1_panel(today),
        "agent2": _build_agent2_panel(),
        "agent3": _build_agent3_panel(),
        "agent4": _build_agent4_panel(),
    }


def create_naver_blog_fill_task(draft_id: int) -> dict[str, Any]:
    draft = get_blog_draft(draft_id)
    task = create_agent_task(
        command_text=f"네이버 블로그 글쓰기 화면에 초안 #{draft_id} 입력",
        task_type="naver_blog_fill_draft",
        search_query=f"draft_id={draft_id}",
        source="report-center",
    )
    return {
        "task_id": task.id,
        "draft_id": draft_id,
        "draft_title": draft.get("title"),
        "status": task.status,
        "message": "네이버 블로그 입력 작업을 큐에 등록했습니다. 발행은 하지 않습니다.",
    }


def _build_agent_card(agent: dict[str, Any], latest_task: dict[str, Any] | None) -> dict[str, Any]:
    error_message = None
    latest_summary = None
    highlights: list[str] = []
    updated_at = agent.get("last_collected_at") or agent.get("updated_at")
    if latest_task:
        latest_summary = _build_card_summary(int(agent.get("id") or 0), latest_task)
        highlights = _build_card_highlights(int(agent.get("id") or 0), latest_task)
        error_message = latest_task.get("error_message") if latest_task.get("status") == "failed" else None
        updated_at = latest_task.get("completed_at") or latest_task.get("claimed_at") or latest_task.get("created_at")

    return {
        "agent_id": int(agent.get("id") or 0),
        "label": f"Agent {int(agent.get('id') or 0):02d}",
        "title": agent.get("title"),
        "status": agent.get("status"),
        "tone": agent.get("tone"),
        "latest_result_summary": latest_summary or agent.get("processing"),
        "highlights": highlights,
        "updated_at": _stringify(updated_at),
        "error_message": error_message,
    }


def _build_card_summary(agent_id: int, task: dict[str, Any]) -> str:
    payload = _payload_dict(task)
    status = str(task.get("status") or "")
    command_text = str(task.get("command_text") or "").strip()
    result_summary = str(task.get("result_summary") or "").strip()

    if status == "failed":
        return "최근 작업 확인이 필요합니다."

    if agent_id == 1:
        inserted = payload.get("inserted")
        titles = payload.get("titles") or []
        if inserted is not None:
            return f"최근 실행에서 신규 뉴스 {inserted}건을 저장했습니다."
        if titles:
            return f"IT 뉴스 후보 {len(titles)}건을 확인했습니다."

    if agent_id == 2:
        title = payload.get("title")
        draft_id = payload.get("draft_id")
        if title and draft_id:
            return f"블로그 초안 #{draft_id} 준비 완료: {title}"
        if draft_id:
            return f"블로그 초안 #{draft_id} 준비 완료"

    if agent_id == 3:
        if payload.get("requires_codex"):
            return "Codex 승인 후 코드 수정과 검증을 진행할 수 있습니다."
        return "코딩/앱 업데이트 작업 상태를 확인했습니다."

    if agent_id == 4:
        ideas = payload.get("ideas") or []
        if ideas:
            return f"유튜브 아이디어 후보 {len(ideas)}개"

    cleaned = _clean_report_text(result_summary or command_text)
    return _truncate(cleaned or "최근 결과가 없습니다.", 150)


def _build_card_highlights(agent_id: int, task: dict[str, Any]) -> list[str]:
    payload = _payload_dict(task)
    if agent_id == 4:
        return [str(idea) for idea in (payload.get("ideas") or [])[:5]]
    if agent_id == 1:
        return [str(title) for title in (payload.get("titles") or [])[:5]]
    return []


def _build_agent1_panel(today: str) -> dict[str, Any]:
    try:
        stats = get_agent_news_stats(agent_id=AGENT1_ID, report_date=today)
        items = list_agent_news_items(agent_id=AGENT1_ID, report_date=today, limit=5)
    except Exception as error:
        return {
            "collected_count": 0,
            "latest_titles": [],
            "items": [],
            "error_message": str(error),
        }

    return {
        "collected_count": int(stats.get("collected_count") or 0),
        "selected_count": int(stats.get("selected_count") or 0),
        "latest_titles": stats.get("latest_titles") or [],
        "last_collected_at": _stringify(stats.get("last_collected_at")),
        "items": [
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "source": item.get("source"),
                "published_at": _stringify(item.get("published_at")),
                "collected_at": _stringify(item.get("collected_at")),
            }
            for item in items
        ],
        "report": stats.get("report"),
    }


def _build_agent2_panel() -> dict[str, Any]:
    try:
        drafts = list_blog_drafts(limit=8)
    except Exception as error:
        return {"drafts": [], "error_message": str(error)}

    return {
        "drafts": [
            {
                "id": int(draft.get("id")),
                "title": draft.get("title"),
                "status": draft.get("status"),
                "platform": draft.get("platform"),
                "created_at": _stringify(draft.get("created_at")),
                "updated_at": _stringify(draft.get("updated_at")),
            }
            for draft in drafts
        ]
    }


def _build_agent3_panel() -> dict[str, Any]:
    tasks = _list_tasks_by_types(("coding_app_update",), limit=8)
    return {
        "codex_pending_tasks": [
            {
                "id": int(task.get("id")),
                "status": task.get("status"),
                "request": task.get("command_text") or task.get("search_query"),
                "summary": task.get("result_summary"),
                "requires_codex": _payload_dict(task).get("requires_codex", True),
                "created_at": _stringify(task.get("created_at")),
                "updated_at": _stringify(task.get("completed_at") or task.get("claimed_at") or task.get("created_at")),
                "error_message": task.get("error_message"),
            }
            for task in tasks
            if task.get("status") in {"pending", "claimed", "completed", "failed"}
        ]
    }


def _build_agent4_panel() -> dict[str, Any]:
    tasks = _list_tasks_by_types(("youtube_idea_research",), limit=8)
    ideas: list[dict[str, Any]] = []
    for task in tasks:
        payload = _payload_dict(task)
        for idea in payload.get("ideas") or []:
            ideas.append(
                {
                    "task_id": int(task.get("id")),
                    "title": str(idea),
                    "status": task.get("status"),
                    "updated_at": _stringify(task.get("completed_at") or task.get("created_at")),
                }
            )
    return {"ideas": ideas[:12], "tasks": [_task_payload(task) for task in tasks]}


def _latest_task_for_agent(agent_id: int) -> dict[str, Any] | None:
    rows = _list_tasks_by_types(AGENT_TASK_TYPES.get(agent_id, ()), limit=1)
    return rows[0] if rows else None


def _list_tasks_by_types(task_types: tuple[str, ...], limit: int = 8) -> list[dict[str, Any]]:
    if not task_types:
        return []
    placeholders = ", ".join("?" for _ in task_types)
    try:
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
    except Exception:
        return []


def _task_payload(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(task.get("id")),
        "task_type": task.get("task_type"),
        "status": task.get("status"),
        "command_text": task.get("command_text"),
        "result_summary": task.get("result_summary"),
        "error_message": task.get("error_message"),
        "created_at": _stringify(task.get("created_at")),
        "updated_at": _stringify(task.get("completed_at") or task.get("claimed_at") or task.get("created_at")),
    }


def _payload_dict(task: dict[str, Any]) -> dict[str, Any]:
    raw = task.get("result_payload")
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _clean_report_text(value: str) -> str:
    text = " ".join(str(value or "").split())
    text = re.sub(r"^에이전트\s*\d+번\s*보고입니다\.?\s*", "", text)
    text = re.sub(r"^보고입니다\.?\s*", "", text)
    text = re.sub(r"\s*\d+\.\s*", " / ", text)
    text = re.sub(r"\s*/\s*/\s*", " / ", text).strip(" /")
    return text


def _truncate(value: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def extract_draft_id_from_query(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"draft_id\s*=\s*(\d+)|초안\s*#?\s*(\d+)", value)
    if not match:
        return None
    return int(next(group for group in match.groups() if group))


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
