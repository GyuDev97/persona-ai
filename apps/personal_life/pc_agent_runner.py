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
from datetime import date, datetime, time as dt_time

from app.config import load_env_file
from app.services.blog_draft_service import create_it_blog_draft_from_agent1
from app.services.agent_news_service import (
    AGENT1_ID,
    AGENT1_TOPIC,
    build_agent1_daily_report,
    parse_rss_datetime,
    save_news_items,
    score_news_title,
    split_title_source,
)
from app.services.agent_task_service import claim_next_agent_task, complete_agent_task, fail_agent_task
from app.storage.database import initialize_database


load_env_file()

POLL_SECONDS = 5
DEVICE_LABEL = "pc-agent"
AGENT1_COLLECT_INTERVAL_SECONDS = int(os.getenv("GYUVIS_AGENT1_COLLECT_INTERVAL_SECONDS", "600"))
AGENT1_START_TIME = os.getenv("GYUVIS_AGENT1_START_TIME", "10:00")
AGENT1_END_TIME = os.getenv("GYUVIS_AGENT1_END_TIME", "18:00")

_last_agent1_collect_at = 0.0
_last_agent1_report_date: str | None = None


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
        try:
            summary, payload = handle_task(task.task_type, task.search_query or task.command_text)
            complete_agent_task(task.id, summary, payload)
            print(f"[{datetime.now().isoformat(timespec='seconds')}] completed task #{task.id}")
        except Exception as error:
            fail_agent_task(task.id, str(error))
            print(f"[{datetime.now().isoformat(timespec='seconds')}] failed task #{task.id}: {error}")


def run_scheduled_collectors() -> None:
    run_agent1_it_news_collector()


def run_agent1_it_news_collector(force: bool = False) -> None:
    global _last_agent1_collect_at, _last_agent1_report_date

    now = datetime.now()
    today = date.today().isoformat()
    start_time = parse_clock_time(AGENT1_START_TIME, dt_time(10, 0))
    end_time = parse_clock_time(AGENT1_END_TIME, dt_time(18, 0))
    is_collect_window = start_time <= now.time() < end_time
    is_report_window = now.time() >= end_time

    if force or is_collect_window:
        elapsed = time.monotonic() - _last_agent1_collect_at
        if force or elapsed >= AGENT1_COLLECT_INTERVAL_SECONDS:
            try:
                inserted = collect_agent1_it_news()
                _last_agent1_collect_at = time.monotonic()
                print(
                    f"[{datetime.now().isoformat(timespec='seconds')}] agent1 collected {inserted} new IT news items"
                )
            except Exception as error:
                print(f"[{datetime.now().isoformat(timespec='seconds')}] agent1 collect failed: {error}")

    if is_report_window and _last_agent1_report_date != today:
        try:
            report = build_agent1_daily_report(today)
            _last_agent1_report_date = today
            print(
                f"[{datetime.now().isoformat(timespec='seconds')}] agent1 daily report ready: {report.get('title')}"
            )
        except Exception as error:
            print(f"[{datetime.now().isoformat(timespec='seconds')}] agent1 report failed: {error}")


def collect_agent1_it_news() -> int:
    items = fetch_google_news_items(AGENT1_TOPIC, limit=12)
    return save_news_items(AGENT1_ID, AGENT1_TOPIC, items)


def handle_task(task_type: str, query: str) -> tuple[str, dict]:
    if task_type == "agent1_it_news_window":
        return build_agent1_it_news_window(query)
    if task_type == "agent2_it_blog_draft":
        return build_agent2_it_blog_draft()
    if task_type == "naver_blog_fill_draft":
        return fill_latest_naver_blog_draft(query)
    if task_type == "coding_app_update":
        return build_coding_app_update_report(query)
    if task_type == "youtube_idea_research":
        return build_youtube_idea_report(query)
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
        "발행은 하지 않았고, 요청 시 글쓰기 화면에 제목과 본문만 입력하겠습니다."
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
        completed = subprocess.run(command, cwd=str(script_path.parent), capture_output=True, text=True)
        if completed.stdout:
            print(completed.stdout.strip())
        if completed.returncode != 0:
            details = (completed.stderr or completed.stdout or "네이버 블로그 자동 입력에 실패했습니다.").strip()
            raise RuntimeError(details)
    else:
        subprocess.Popen(command, cwd=str(script_path.parent))
    return (
        "열려 있는 Edge의 네이버 블로그 화면에 초안을 입력했습니다. 발행은 하지 않았습니다.",
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
        "코딩/앱 업데이트 요청을 접수했습니다. 현재 자동 코드 수정은 Codex 작업 승인 루프로 넘겨야 합니다.\n"
        "요청 내용은 작업 큐에 기록했으며, 보스가 승인하면 Codex가 실제 파일 수정과 검증을 진행할 수 있습니다."
    )
    return summary, {"agent_id": 3, "request": query, "requires_codex": True}


def build_youtube_idea_report(query: str) -> tuple[str, dict]:
    search_query = query or "IT 모바일 AI 유튜브 아이디어"
    source_titles, _links = fetch_google_news_titles(search_query, limit=5)
    titles = [build_youtube_idea_from_headline(title) for title in source_titles[:5]]
    if not titles:
        raise RuntimeError("유튜브 아이디어 탐색에 사용할 최신 소스를 찾지 못했습니다.")
    summary = "에이전트 4번 보고입니다.\n\n최신 검색 소스를 바탕으로 유튜브 아이디어 후보를 정리했습니다.\n\n" + "\n".join(
        f"{index + 1}. {title}" for index, title in enumerate(titles)
    )
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
    search_query = query or AGENT1_TOPIC
    items = fetch_google_news_items(search_query, limit=12)
    inserted = save_news_items(AGENT1_ID, AGENT1_TOPIC, items)
    report = build_agent1_daily_report()
    titles = [item["title"] for item in items]
    if not items:
        raise RuntimeError("IT 뉴스 헤드라인을 찾지 못했습니다.")

    top_titles = titles[:5]
    summary = (
        "에이전트 1번 보고입니다.\n\n"
        f"이번 실행에서 신규 {inserted}건을 저장했습니다. "
        "오전 10시부터 오후 6시까지 확인할 IT 관련 뉴스 흐름은 다음과 같습니다.\n\n"
        + "\n".join(f"{index + 1}. {title}" for index, title in enumerate(top_titles))
    )
    return summary, {
        "agent_id": 1,
        "window_start": "10:00",
        "window_end": "18:00",
        "query": search_query,
        "titles": titles,
        "links": [item["url"] for item in items],
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


def fetch_google_news_titles(query: str, limit: int = 5) -> tuple[list[str], list[str]]:
    items = fetch_google_news_items(query, limit=limit)
    return [item["title"] for item in items], [item["url"] for item in items]


def fetch_google_news_items(query: str, limit: int = 5) -> list[dict]:
    rss_url = (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote(query)
        + "&hl=ko&gl=KR&ceid=KR:ko"
    )
    root = ET.fromstring(fetch_text(rss_url))
    items = root.findall("./channel/item")[:limit]
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
    return parsed_items


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
        f"내일 서울 기준으로 보면 평균 {avg_temp}도 정도고, 최고 {max_temp}도 최저 {min_temp}도로 보입니다.\n\n"
        f"비 올 가능성은 대략 {rain_chance}% 정도라서, 외출 일정 있으면 우산 챙길지 같이 보시면 좋겠습니다.\n\n"
        f"지금 현재 기온은 {current.get('temp_C', '-')}도입니다."
    )
    return summary, {"current": current, "tomorrow": tomorrow}


def build_web_search_briefing(query: str) -> tuple[str, dict]:
    open_browser_search(query)
    summary = (
        f"PC에서 '{query}' 검색 결과를 열어뒀습니다.\n\n"
        "이 단계에서는 브라우저까지 바로 열고, 검색을 시작하는 흐름으로 먼저 연결해뒀어요."
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
