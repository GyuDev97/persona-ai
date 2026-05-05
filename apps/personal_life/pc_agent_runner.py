import json
import os
import pathlib
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from datetime import date, datetime, time as dt_time, timedelta

from app.agents import Agent1News, Agent2Blog, Agent3Codex, Agent4Youtube, BaseAgent
from app.config import load_env_file
from app.services.blog_draft_service import create_it_blog_draft_from_agent1
from app.services.money_core_service import build_money_core_summary
from app.services.agent_news_service import (
    AGENT1_ID,
    AGENT1_DISPLAY_LABEL,
    AGENT1_TOPIC,
    build_agent1_daily_report,
    list_agent_news_display_items,
    parse_rss_datetime,
    save_news_items,
    score_news_title,
    split_title_source,
)
from app.services.agent_task_service import claim_next_agent_task, complete_agent_task, fail_agent_task
from app.services.agent_task_service import create_agent_task
from app.services.agent_message_service import create_agent_message, list_agent_messages
from app.services.agent_status_service import (
    agent_id_for_task_type,
    mark_agent_error,
    mark_agent_running,
    mark_agent_success,
)
from app.services.naver_news_email_service import is_news_email_enabled, send_agent1_morning_news_email
from app.storage.database import fetch_one, initialize_database


load_env_file()

POLL_SECONDS = 5
DEVICE_LABEL = "pc-agent"
AGENT1_COLLECT_INTERVAL_SECONDS = int(os.getenv("GYUVIS_AGENT1_COLLECT_INTERVAL_SECONDS", "600"))
AGENT1_START_TIME = os.getenv("GYUVIS_AGENT1_START_TIME", "06:00")
AGENT1_END_TIME = os.getenv("GYUVIS_AGENT1_END_TIME", "23:00")
AGENT1_NEWS_EMAIL_TIME = os.getenv("GYUVIS_AGENT1_NEWS_EMAIL_TIME", "08:00")
AGENT1_NEWS_RECENT_DAYS = max(1, int(os.getenv("GYUVIS_AGENT1_NEWS_RECENT_DAYS", "1")))
AGENT2_AUTO_DRAFT_FROM_AGENT1 = os.getenv("GYUVIS_AGENT2_AUTO_DRAFT_FROM_AGENT1", "1")
AGENT4_AUTO_IDEA_FROM_AGENT1 = os.getenv("GYUVIS_AGENT4_AUTO_IDEA_FROM_AGENT1", "1")
AGENT1_OFF_DUTY_MESSAGE = os.getenv(
    "GYUVIS_AGENT1_OFF_DUTY_MESSAGE",
    "오늘 수집 시간 종료했습니다. 최종 보고까지 정리했으니 Agent 01은 이만 퇴근하겠습니다.",
)
AGENT1_ON_DUTY_MESSAGE = os.getenv(
    "GYUVIS_AGENT1_ON_DUTY_MESSAGE",
    "Agent 01 출근했습니다. 오늘도 IT 뉴스 수집 시작하겠습니다.",
)
AGENT2_AGENT1_OFF_DUTY_REPLY = os.getenv(
    "GYUVIS_AGENT2_AGENT1_OFF_DUTY_REPLY",
    "Agent 01, 오늘 자료 수집하느라 고생했어. 넘겨준 자료는 내가 블로그 초안 쪽에서 이어서 볼게.",
)
AGENT3_AGENT1_OFF_DUTY_REPLY = os.getenv(
    "GYUVIS_AGENT3_AGENT1_OFF_DUTY_REPLY",
    "Agent 01 수고했습니다. 오늘 리포트 기준으로 필요한 개선 작업은 Codex 승인 큐에서 차분히 확인하겠습니다.",
)
AGENT4_AGENT1_OFF_DUTY_REPLY = os.getenv(
    "GYUVIS_AGENT4_AGENT1_OFF_DUTY_REPLY",
    "Agent 01 고생했어. 오늘 뉴스 흐름은 유튜브 아이디어 쪽에서도 참고해둘게.",
)
AGENT3_STANDBY_MESSAGE = os.getenv(
    "GYUVIS_AGENT3_STANDBY_MESSAGE",
    "Codex 작업 요청 확인 완료했습니다. 자동 수정은 하지 않고 다시 대기하겠습니다.",
)
AGENT4_STANDBY_MESSAGE = os.getenv(
    "GYUVIS_AGENT4_STANDBY_MESSAGE",
    "유튜브 아이디어 후보 {idea_count}개 정리했습니다. 다음 자료가 들어올 때까지 대기하겠습니다.",
)
AGENT1_NEWS_QUERIES = [
    query.strip()
    for query in os.getenv(
        "GYUVIS_AGENT1_NEWS_QUERIES",
        "AI,모바일,스마트폰,갤럭시,아이폰,iOS,안드로이드,웨어러블",
    ).split(",")
    if query.strip()
]

_last_agent1_collect_at = 0.0
_last_agent1_on_duty_date: str | None = None
_last_agent1_report_date: str | None = None
_last_agent1_email_date: str | None = None

AGENT_HANDLERS: dict[str, BaseAgent] = {
    "agent1_it_news_window": Agent1News(),
    "agent2_it_blog_draft": Agent2Blog(),
    "naver_blog_fill_draft": Agent2Blog(mode="fill"),
    "coding_app_update": Agent3Codex(),
    "youtube_idea_research": Agent4Youtube(),
}


def main() -> None:
    load_env_file()
    initialize_database()
    print(f"[{datetime.now().isoformat(timespec='seconds')}] PC agent started as '{DEVICE_LABEL}'")
    while True:
        run_scheduled_collectors()
        task = claim_next_agent_task(DEVICE_LABEL)
        if task is None:
            time.sleep(POLL_SECONDS)
            continue

        print(f"[{datetime.now().isoformat(timespec='seconds')}] claimed task #{task.id} ({task.task_type})")
        agent_id = agent_id_for_task_type(task.task_type)
        mark_agent_running(agent_id, f"Task #{task.id} started: {task.task_type}")
        try:
            summary, payload = handle_task(task.task_type, task.search_query or task.command_text)
            complete_agent_task(task.id, summary, payload)
            mark_agent_success(agent_id, f"Task #{task.id} completed: {task.task_type}")
            print(f"[{datetime.now().isoformat(timespec='seconds')}] completed task #{task.id}")
        except Exception as error:
            fail_agent_task(task.id, str(error))
            mark_agent_error(agent_id, f"Task #{task.id} failed: {error}")
            print(f"[{datetime.now().isoformat(timespec='seconds')}] failed task #{task.id}: {error}")


def run_scheduled_collectors() -> None:
    run_agent1_it_news_collector()
    run_agent1_news_email_sender()


def run_agent1_it_news_collector(force: bool = False) -> None:
    global _last_agent1_collect_at, _last_agent1_on_duty_date, _last_agent1_report_date

    now = datetime.now()
    today = date.today().isoformat()
    start_time = parse_clock_time(AGENT1_START_TIME, dt_time(6, 0))
    end_time = parse_clock_time(AGENT1_END_TIME, dt_time(23, 0))
    is_collect_window = start_time <= now.time() < end_time
    is_report_window = now.time() >= end_time

    if force or is_collect_window:
        if _last_agent1_on_duty_date != today:
            post_agent1_on_duty_message(today)
            _last_agent1_on_duty_date = today

        elapsed = time.monotonic() - _last_agent1_collect_at
        if force or elapsed >= AGENT1_COLLECT_INTERVAL_SECONDS:
            try:
                mark_agent_running(AGENT1_ID, "Scheduled Agent 1 IT news collection started")
                inserted = collect_agent1_it_news()
                maybe_enqueue_agent2_blog_draft(inserted)
                maybe_enqueue_agent4_youtube_ideas(inserted)
                mark_agent_success(AGENT1_ID, f"Scheduled Agent 1 IT news collection completed: {inserted} new items")
                _last_agent1_collect_at = time.monotonic()
                print(
                    f"[{datetime.now().isoformat(timespec='seconds')}] agent1 collected {inserted} new IT news items"
                )
            except Exception as error:
                mark_agent_error(AGENT1_ID, f"Scheduled Agent 1 IT news collection failed: {error}")
                print(f"[{datetime.now().isoformat(timespec='seconds')}] agent1 collect failed: {error}")

    if is_report_window and _last_agent1_report_date != today:
        try:
            mark_agent_running(AGENT1_ID, f"Scheduled Agent 1 daily report started: {today}")
            report = build_agent1_daily_report(today)
            post_agent1_off_duty_message(today, report)
            mark_agent_success(AGENT1_ID, f"Scheduled Agent 1 daily report completed: {report.get('title')}")
            _last_agent1_report_date = today
            print(
                f"[{datetime.now().isoformat(timespec='seconds')}] agent1 daily report ready: {report.get('title')}"
            )
        except Exception as error:
            mark_agent_error(AGENT1_ID, f"Scheduled Agent 1 daily report failed: {error}")
            print(f"[{datetime.now().isoformat(timespec='seconds')}] agent1 report failed: {error}")


def run_agent1_news_email_sender() -> None:
    global _last_agent1_email_date

    if not is_news_email_enabled():
        return

    now = datetime.now()
    today = date.today().isoformat()
    send_time = parse_clock_time(AGENT1_NEWS_EMAIL_TIME, dt_time(8, 0))
    if now.time() < send_time or _last_agent1_email_date == today:
        return

    try:
        mark_agent_running(AGENT1_ID, f"Scheduled Agent 1 news email started: {today}")
        result = send_agent1_morning_news_email(today)
        _last_agent1_email_date = today
        mark_agent_success(AGENT1_ID, f"Scheduled Agent 1 news email sent: {result.get('sent_count')} items")
        print(
            f"[{datetime.now().isoformat(timespec='seconds')}] agent1 news email sent: "
            f"{result.get('sent_count')} items"
        )
    except Exception as error:
        mark_agent_error(AGENT1_ID, f"Scheduled Agent 1 news email failed: {error}")
        print(f"[{datetime.now().isoformat(timespec='seconds')}] agent1 news email failed: {error}")


def post_agent1_off_duty_message(report_date: str, report: dict) -> None:
    message = AGENT1_OFF_DUTY_MESSAGE.format(
        date=report_date,
        start_time=AGENT1_START_TIME,
        end_time=AGENT1_END_TIME,
        title=report.get("title") or "",
    )
    payload = {
        "report_date": report_date,
        "report_title": report.get("title"),
        "start_time": AGENT1_START_TIME,
        "end_time": AGENT1_END_TIME,
    }
    if not agent_message_exists("agent_off_duty", AGENT1_ID, report_date):
        try:
            create_agent_message(
                1,
                message,
                topic="agent_off_duty",
                payload=payload,
            )
        except Exception as error:
            print(f"[{datetime.now().isoformat(timespec='seconds')}] agent1 off-duty message failed: {error}")
    post_agent1_off_duty_replies(report_date, payload)


def post_agent1_off_duty_replies(report_date: str, payload: dict) -> None:
    replies = (
        (2, AGENT2_AGENT1_OFF_DUTY_REPLY),
        (3, AGENT3_AGENT1_OFF_DUTY_REPLY),
        (4, AGENT4_AGENT1_OFF_DUTY_REPLY),
    )
    for agent_id, template in replies:
        if agent_message_exists("agent_off_duty_reply", agent_id, report_date):
            continue
        try:
            create_agent_message(
                agent_id,
                template.format(
                    date=report_date,
                    start_time=AGENT1_START_TIME,
                    end_time=AGENT1_END_TIME,
                    title=payload.get("report_title") or "",
                ),
                to_agent_id=1,
                topic="agent_off_duty_reply",
                payload=payload,
            )
        except Exception as error:
            print(
                f"[{datetime.now().isoformat(timespec='seconds')}] "
                f"agent{agent_id} off-duty reply failed: {error}"
            )


def post_agent1_on_duty_message(report_date: str) -> None:
    if agent_message_exists("agent_on_duty", AGENT1_ID, report_date):
        return
    message = AGENT1_ON_DUTY_MESSAGE.format(
        date=report_date,
        start_time=AGENT1_START_TIME,
        end_time=AGENT1_END_TIME,
    )
    try:
        create_agent_message(
            1,
            message,
            topic="agent_on_duty",
            payload={
                "report_date": report_date,
                "start_time": AGENT1_START_TIME,
                "end_time": AGENT1_END_TIME,
            },
        )
    except Exception as error:
        print(f"[{datetime.now().isoformat(timespec='seconds')}] agent1 on-duty message failed: {error}")


def agent_message_exists(topic: str, from_agent_id: int, report_date: str) -> bool:
    try:
        messages = list_agent_messages(limit=50, topic=topic)
    except Exception as error:
        print(f"[{datetime.now().isoformat(timespec='seconds')}] agent message duplicate check failed: {error}")
        return False
    for message in messages:
        payload = message.get("payload") or {}
        if int(message.get("from_agent_id") or 0) == from_agent_id and payload.get("report_date") == report_date:
            return True
    return False


def collect_agent1_it_news() -> int:
    items = collect_agent1_it_news_items(limit=5, recent_days=AGENT1_NEWS_RECENT_DAYS)
    return save_news_items(AGENT1_ID, AGENT1_TOPIC, items)


def maybe_enqueue_agent2_blog_draft(inserted_count: int, *, force: bool = False) -> None:
    if not force and inserted_count <= 0:
        return
    if not _truthy(AGENT2_AUTO_DRAFT_FROM_AGENT1):
        return

    today = date.today()
    start_at = today.isoformat()
    end_at = (today + timedelta(days=1)).isoformat()
    existing_draft = fetch_one(
        """
        SELECT id
        FROM agent_blog_drafts
        WHERE source_agent_id = ?
          AND created_at >= ?
          AND created_at < ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (AGENT1_ID, start_at, end_at),
    )
    if existing_draft:
        return

    existing_task = fetch_one(
        """
        SELECT id
        FROM agent_tasks
        WHERE task_type = 'agent2_it_blog_draft'
          AND source = 'agent-collaboration'
          AND status IN ('pending', 'claimed')
          AND created_at >= ?
          AND created_at < ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (start_at, end_at),
    )
    if existing_task:
        return

    task = create_agent_task(
        command_text="Agent 01 수집 자료를 바탕으로 네이버 블로그 초안 작성",
        task_type="agent2_it_blog_draft",
        search_query=f"source_agent_id={AGENT1_ID};date={start_at}",
        source="agent-collaboration",
        payload={
            "trigger": "agent1_news_collected",
            "source_agent_id": AGENT1_ID,
            "inserted_count": inserted_count,
            "safety": "draft_only_no_publish",
        },
    )
    create_agent_message(
        1,
        f"Agent 02, 방금 새 자료 {inserted_count}건이 들어왔어. 블로그 초안 작업 큐 #{task.id}번으로 넘겨둘게.",
        to_agent_id=2,
        topic="news_to_blog",
        payload={"task_id": task.id, "inserted_count": inserted_count},
    )


def maybe_enqueue_agent4_youtube_ideas(inserted_count: int, *, force: bool = False) -> None:
    if not force and inserted_count <= 0:
        return
    if not _truthy(AGENT4_AUTO_IDEA_FROM_AGENT1):
        return

    today = date.today()
    start_at = today.isoformat()
    end_at = (today + timedelta(days=1)).isoformat()
    existing_task = fetch_one(
        """
        SELECT id
        FROM agent_tasks
        WHERE task_type = 'youtube_idea_research'
          AND source = 'agent-collaboration'
          AND created_at >= ?
          AND created_at < ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (start_at, end_at),
    )
    if existing_task:
        return

    task = create_agent_task(
        command_text="Agent 01 수집 자료를 바탕으로 유튜브 아이디어 후보 정리",
        task_type="youtube_idea_research",
        search_query="IT 모바일 AI 유튜브 아이디어",
        source="agent-collaboration",
        payload={
            "trigger": "agent1_news_collected",
            "source_agent_id": AGENT1_ID,
            "inserted_count": inserted_count,
            "safety": "idea_only_no_publish",
        },
    )
    create_agent_message(
        1,
        f"Agent 04도 참고해줘. 같은 자료로 유튜브 아이디어 작업 큐 #{task.id}번을 열어둘게.",
        to_agent_id=4,
        topic="news_to_youtube",
        payload={"task_id": task.id, "inserted_count": inserted_count},
    )


def collect_agent1_it_news_items(limit: int = 5, recent_days: int | None = 1) -> list[dict]:
    merged: dict[str, dict] = {}
    per_query_limit = max(5, limit)

    for keyword in AGENT1_NEWS_QUERIES:
        query = build_agent1_news_query(keyword)
        try:
            items = fetch_google_news_items(query, limit=per_query_limit, recent_days=recent_days)
        except Exception as error:
            print(f"[{datetime.now().isoformat(timespec='seconds')}] agent1 query failed ({keyword}): {error}")
            continue

        for item in items:
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            current = merged.get(url)
            if current is None or news_sort_key(item) > news_sort_key(current):
                item["query_keyword"] = keyword
                merged[url] = item

    ordered = sorted(merged.values(), key=news_sort_key, reverse=True)
    return ordered[: max(limit, 5)]


def build_agent1_news_query(keyword: str) -> str:
    return f"{keyword} IT 모바일 뉴스"


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def handle_task(task_type: str, query: str) -> tuple[str, dict]:
    handler = AGENT_HANDLERS.get(task_type)
    if handler is not None:
        return handler.run(query)
    return default_handler(task_type, query)


def default_handler(task_type: str, query: str) -> tuple[str, dict]:
    if task_type == "finance_monthly_summary":
        return build_finance_monthly_summary()
    if task_type == "news_briefing":
        return build_news_briefing(query)
    if task_type == "weather_briefing":
        return build_weather_briefing(query)
    return build_web_search_briefing(query)


def build_agent2_it_blog_draft() -> tuple[str, dict]:
    draft = create_it_blog_draft_from_agent1()
    summary = (
        "에이전트 2번 보고입니다.\n\n"
        f"네이버 블로그용 IT/모바일 뉴스 초안 #{draft['id']}번을 생성했습니다.\n\n"
        f"제목: {draft['title']}\n\n"
        "발행은 하지 않고, 요청 시 글쓰기 화면에 제목과 본문만 입력하겠습니다."
    )
    return summary, {"draft_id": draft["id"], "title": draft["title"], "platform": draft["platform"]}


def fill_latest_naver_blog_draft(query: str = "") -> tuple[str, dict]:
    script_path = pathlib.Path(__file__).resolve().parent / "naver_blog_writer.py"
    mode = os.getenv("GYUVIS_NAVER_BLOG_MODE", "edge-existing")
    input_mode = os.getenv("GYUVIS_NAVER_INPUT_MODE", "direct")
    command = [sys.executable, str(script_path), "--mode", mode, "--input-mode", input_mode]
    draft_id = extract_draft_id_from_query(query)
    if draft_id is not None:
        command.extend(["--draft-id", str(draft_id)])
    if mode == "edge-existing":
        completed = subprocess.run(
            command,
            cwd=str(script_path.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.stdout:
            print(completed.stdout.strip())
        if completed.returncode != 0:
            details = (completed.stderr or completed.stdout or "네이버 블로그 자동 입력에 실패했습니다.").strip()
            raise RuntimeError(details)
    else:
        subprocess.Popen(command, cwd=str(script_path.parent))
    return (
        "열려 있는 Edge의 네이버 블로그 화면에 초안을 입력했습니다. 발행은 하지 않습니다.",
        {
            "platform": "naver_blog",
            "publish": False,
            "mode": mode,
            "input_mode": input_mode,
            "draft_id": draft_id,
        },
    )


def extract_draft_id_from_query(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"draft_id\s*=\s*(\d+)|초안\s*#?\s*(\d+)", value)
    if not match:
        return None
    return int(next(group for group in match.groups() if group))


def build_coding_app_update_report(query: str) -> tuple[str, dict]:
    summary = (
        "에이전트 3번 보고입니다.\n\n"
        "코딩/앱 업데이트 요청을 접수했습니다. 현재 자동 코드 수정은 하지 않고 Codex 작업 승인 루프로 넘겨집니다.\n"
        "요청 내용은 작업 큐에 기록되며, 보스가 승인하면 Codex가 실제 파일 수정과 검증을 진행할 수 있습니다."
    )
    try:
        create_agent_message(
            3,
            AGENT3_STANDBY_MESSAGE.format(request=query or ""),
            topic="agent_standby",
            payload={"request": query, "safety": "no_auto_file_write"},
        )
    except Exception:
        pass
    return summary, {"agent_id": 3, "request": query, "requires_codex": True}


def build_youtube_idea_report(query: str) -> tuple[str, dict]:
    search_query = query or "IT 모바일 AI 유튜브 아이디어"
    source_titles, _links = fetch_google_news_titles(search_query, limit=5)
    titles = [build_youtube_idea_from_headline(title) for title in source_titles[:5]]
    if not titles:
        raise RuntimeError("유튜브 아이디어 생성에 사용할 최신 뉴스를 찾지 못했습니다.")
    summary = "에이전트 4번 보고입니다.\n\n최신 검색 뉴스를 바탕으로 유튜브 아이디어 후보를 정리했습니다.\n\n" + "\n".join(
        f"{index + 1}. {title}" for index, title in enumerate(titles)
    )
    try:
        create_agent_message(
            4,
            AGENT4_STANDBY_MESSAGE.format(idea_count=len(titles), query=search_query),
            to_agent_id=1,
            topic="youtube_idea",
            payload={"query": search_query, "ideas": titles},
        )
    except Exception:
        pass
    return summary, {
        "agent_id": 4,
        "query": search_query,
        "source_titles": source_titles,
        "ideas": titles,
    }


def build_youtube_idea_from_headline(title: str) -> str:
    cleaned = clean_text(title)
    if len(cleaned) > 58:
        cleaned = cleaned[:58].rstrip() + "..."
    return f"{cleaned} 쉽게 풀어보기"


def build_agent1_it_news_window(query: str) -> tuple[str, dict]:
    search_query = query or ", ".join(AGENT1_NEWS_QUERIES)
    items = collect_agent1_it_news_items(limit=5, recent_days=AGENT1_NEWS_RECENT_DAYS)
    inserted = save_news_items(AGENT1_ID, AGENT1_TOPIC, items)
    report = build_agent1_daily_report()
    display_items = list_agent_news_display_items(agent_id=AGENT1_ID, limit=5)
    titles = [item["title"] for item in display_items]
    if not display_items:
        raise RuntimeError("표시할 최신 IT 뉴스 헤드라인을 찾지 못했습니다.")

    top_titles = titles[:5]
    summary = (
        "에이전트 1번 보고입니다.\n\n"
        f"AI, 모바일, 스마트폰, 갤럭시, 아이폰, iOS, 안드로이드, 웨어러블 키워드로 확인했습니다. "
        f"이번 실행에서 신규 {inserted}건을 저장했고, 중복 제거 후 최신 발행일 기준 상위 뉴스는 다음과 같습니다.\n\n"
        + "\n".join(f"{index + 1}. {title}" for index, title in enumerate(top_titles))
    )
    try:
        create_agent_message(
            1,
            f"오늘 자료 수집해왔어. 블로그로 쓸 만한 IT 뉴스 {len(top_titles)}개를 추려놨어.",
            to_agent_id=2,
            topic="news_to_blog",
            payload={
                "inserted": inserted,
                "titles": top_titles,
                "report_date": report.get("report_date") if isinstance(report, dict) else None,
            },
        )
    except Exception:
        pass
    maybe_enqueue_agent2_blog_draft(inserted)
    maybe_enqueue_agent4_youtube_ideas(inserted)
    return summary, {
        "agent_id": 1,
        "label": AGENT1_DISPLAY_LABEL,
        "window_start": "10:00",
        "window_end": "18:00",
        "query": search_query,
        "query_keywords": AGENT1_NEWS_QUERIES,
        "titles": titles,
        "links": [item["url"] for item in display_items],
        "inserted": inserted,
        "report": report,
    }

def build_news_briefing(query: str) -> tuple[str, dict]:
    search_query = query or "최신 뉴스"
    open_browser_search(search_query, tab="news")

    titles, _links = fetch_google_news_titles(search_query, limit=5)
    if not titles:
        raise RuntimeError("뉴스 헤드라인을 찾지 못했습니다.")

    summary = "최신 뉴스 기준으로 이런 흐름입니다.\n\n" + "\n".join(
        f"{index + 1}. {title}" for index, title in enumerate(titles[:3])
    )
    return summary, {"titles": titles}


def build_finance_monthly_summary() -> tuple[str, dict]:
    data = build_money_core_summary()
    summary = (
        "Money Core 이번 달 소비 요약입니다.\n\n"
        f"월급은 {data['salary']:,}원, 총 소비 계획은 {data['monthly_spend_total']:,}원입니다.\n"
        f"예상 잔여 현금은 {data['remaining_cash']:,}원이고 카드 사용률은 {data['card_usage_rate'] * 100:.1f}%입니다.\n"
        + "\n".join(f"- {tip}" for tip in data.get("tips", [])[:3])
    )
    return summary, data


def fetch_google_news_titles(query: str, limit: int = 5) -> tuple[list[str], list[str]]:
    items = fetch_google_news_items(query, limit=limit, recent_days=1)
    return [item["title"] for item in items], [item["url"] for item in items]


def fetch_google_news_items(query: str, limit: int = 5, recent_days: int | None = 1) -> list[dict]:
    search_query = query.strip()
    if recent_days and "when:" not in search_query:
        search_query = f"{search_query} when:{max(1, recent_days)}d"
    rss_url = (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote(search_query)
        + "&hl=ko&gl=KR&ceid=KR:ko"
    )
    root = ET.fromstring(fetch_text(rss_url))
    items = root.findall("./channel/item")[: max(limit * 3, limit)]
    parsed_items = []
    for item in items:
        raw_title = item.findtext("title", default="")
        link = item.findtext("link", default="")
        if not raw_title or not link:
            continue
        title, source = split_title_source(raw_title)
        title = clean_text(title)
        parsed_items.append(
            {
                "title": title,
                "url": link,
                "source": source,
                "published_at": parse_rss_datetime(item.findtext("pubDate")),
                "importance_score": score_news_title(title),
            }
        )
    relevant_items = [item for item in parsed_items if int(item.get("importance_score") or 0) > 1]
    if relevant_items:
        parsed_items = relevant_items
    parsed_items.sort(key=news_sort_key, reverse=True)
    if recent_days:
        cutoff = datetime.now() - timedelta(days=max(1, recent_days))
        recent_items = []
        for item in parsed_items:
            published_at = parse_news_datetime(item.get("published_at"))
            if published_at is None or published_at >= cutoff:
                recent_items.append(item)
        if recent_items:
            parsed_items = recent_items
    return parsed_items[:limit]


def parse_news_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def news_sort_key(item: dict) -> tuple[datetime, int]:
    published_at = parse_news_datetime(item.get("published_at")) or datetime.min
    return published_at, int(item.get("importance_score") or 0)


def parse_clock_time(value: str, fallback: dt_time) -> dt_time:
    try:
        hour_text, minute_text = value.split(":", 1)
        return dt_time(int(hour_text), int(minute_text))
    except (ValueError, TypeError):
        return fallback


def build_weather_briefing(query: str) -> tuple[str, dict]:
    open_browser_search(query or "내일 날씨", tab="weather")

    weather_data = json.loads(fetch_text("https://wttr.in/Seoul?format=j1"))
    current = weather_data["current_condition"][0]
    tomorrow = weather_data["weather"][1] if len(weather_data["weather"]) > 1 else weather_data["weather"][0]
    avg_temp = tomorrow.get("avgtempC", "-")
    max_temp = tomorrow.get("maxtempC", "-")
    min_temp = tomorrow.get("mintempC", "-")
    rain_chance = tomorrow.get("hourly", [{}])[4].get("chanceofrain", "-")

    summary = (
        f"내일 서울 기준으로 보면 평균 {avg_temp}도, 최고 {max_temp}도, 최저 {min_temp}도로 보입니다.\n\n"
        f"비 올 가능성은 대략 {rain_chance}% 정도라서, 외출 일정이 있으면 우산까지 같이 보시면 좋겠습니다.\n\n"
        f"지금 현재 기온은 {current.get('temp_C', '-')}도입니다."
    )
    return summary, {"current": current, "tomorrow": tomorrow}


def build_web_search_briefing(query: str) -> tuple[str, dict]:
    open_browser_search(query)
    summary = (
        f"PC에서 '{query}' 검색 결과를 열어두었습니다.\n\n"
        "이 단계에서는 브라우저까지 바로 열고, 검색을 시작하는 흐름으로 먼저 연결해두었습니다."
    )
    return summary, {"query": query}


def open_browser_search(query: str, tab: str | None = None) -> None:
    q = urllib.parse.quote(query)
    suffix = "&tbm=nws" if tab == "news" else ""
    url = f"https://www.google.com/search?q={q}{suffix}"
    webbrowser.open(url)


def fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return response.read().decode("utf-8")


def clean_text(value: str) -> str:
    return " ".join(value.replace(" - ", " ").split())


if __name__ == "__main__":
    main()


