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
from app.storage.database import initialize_database


load_env_file()

POLL_SECONDS = 5
DEVICE_LABEL = "pc-agent"
AGENT1_COLLECT_INTERVAL_SECONDS = int(os.getenv("GYUVIS_AGENT1_COLLECT_INTERVAL_SECONDS", "600"))
AGENT1_START_TIME = os.getenv("GYUVIS_AGENT1_START_TIME", "06:00")
AGENT1_END_TIME = os.getenv("GYUVIS_AGENT1_END_TIME", "23:00")
AGENT1_NEWS_RECENT_DAYS = max(1, int(os.getenv("GYUVIS_AGENT1_NEWS_RECENT_DAYS", "1")))
AGENT1_NEWS_QUERIES = [
    query.strip()
    for query in os.getenv(
        "GYUVIS_AGENT1_NEWS_QUERIES",
        "AI,모바일,스마트폰,갤럭시,아이폰,iOS,안드로이드,웨어러블",
    ).split(",")
    if query.strip()
]

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
    start_time = parse_clock_time(AGENT1_START_TIME, dt_time(6, 0))
    end_time = parse_clock_time(AGENT1_END_TIME, dt_time(23, 0))
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
    items = collect_agent1_it_news_items(limit=5, recent_days=AGENT1_NEWS_RECENT_DAYS)
    return save_news_items(AGENT1_ID, AGENT1_TOPIC, items)


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
        "?먯씠?꾪듃 2踰?蹂닿퀬?낅땲??\n\n"
        f"?ㅼ씠踰?釉붾줈洹몄슜 IT/紐⑤컮???댁뒪 珥덉븞 #{draft['id']}踰덉쓣 ?앹꽦?덉뒿?덈떎.\n\n"
        f"?쒕ぉ: {draft['title']}\n\n"
        "諛쒗뻾? ?섏? ?딆븯怨? ?붿껌 ??湲?곌린 ?붾㈃???쒕ぉ怨?蹂몃Ц留??낅젰?섍쿋?듬땲??"
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
            details = (completed.stderr or completed.stdout or "?ㅼ씠踰?釉붾줈洹??먮룞 ?낅젰???ㅽ뙣?덉뒿?덈떎.").strip()
            raise RuntimeError(details)
    else:
        subprocess.Popen(command, cwd=str(script_path.parent))
    return (
        "?대젮 ?덈뒗 Edge???ㅼ씠踰?釉붾줈洹??붾㈃??珥덉븞???낅젰?덉뒿?덈떎. 諛쒗뻾? ?섏? ?딆븯?듬땲??",
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
    match = re.search(r"draft_id\s*=\s*(\d+)|珥덉븞\s*#?\s*(\d+)", value)
    if not match:
        return None
    return int(next(group for group in match.groups() if group))


def build_coding_app_update_report(query: str) -> tuple[str, dict]:
    summary = (
        "?먯씠?꾪듃 3踰?蹂닿퀬?낅땲??\n\n"
        "肄붾뵫/???낅뜲?댄듃 ?붿껌???묒닔?덉뒿?덈떎. ?꾩옱 ?먮룞 肄붾뱶 ?섏젙? Codex ?묒뾽 ?뱀씤 猷⑦봽濡??섍꺼???⑸땲??\n"
        "?붿껌 ?댁슜? ?묒뾽 ?먯뿉 湲곕줉?덉쑝硫? 蹂댁뒪媛 ?뱀씤?섎㈃ Codex媛 ?ㅼ젣 ?뚯씪 ?섏젙怨?寃利앹쓣 吏꾪뻾?????덉뒿?덈떎."
    )
    return summary, {"agent_id": 3, "request": query, "requires_codex": True}


def build_youtube_idea_report(query: str) -> tuple[str, dict]:
    search_query = query or "IT 紐⑤컮??AI ?좏뒠釉??꾩씠?붿뼱"
    source_titles, _links = fetch_google_news_titles(search_query, limit=5)
    titles = [build_youtube_idea_from_headline(title) for title in source_titles[:5]]
    if not titles:
        raise RuntimeError("?좏뒠釉??꾩씠?붿뼱 ?먯깋???ъ슜??理쒖떊 ?뚯뒪瑜?李얠? 紐삵뻽?듬땲??")
    summary = "?먯씠?꾪듃 4踰?蹂닿퀬?낅땲??\n\n理쒖떊 寃???뚯뒪瑜?諛뷀깢?쇰줈 ?좏뒠釉??꾩씠?붿뼱 ?꾨낫瑜??뺣━?덉뒿?덈떎.\n\n" + "\n".join(
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
    search_query = query or "理쒖떊 ?댁뒪"
    open_browser_search(search_query, tab="news")

    titles, _links = fetch_google_news_titles(search_query, limit=5)
    if not titles:
        raise RuntimeError("?댁뒪 ?ㅻ뱶?쇱씤??李얠? 紐삵뻽?듬땲??")

    summary = "理쒖떊 ?댁뒪 湲곗??쇰줈 ?대윴 ?먮쫫?낅땲??\n\n" + "\n".join(
        f"{index + 1}. {title}" for index, title in enumerate(titles[:3])
    )
    return summary, {"titles": titles}


def build_finance_monthly_summary() -> tuple[str, dict]:
    data = build_money_core_summary()
    summary = (
        "Money Core ?대쾲 ???뚮퉬 ?붿빟?낅땲??\n\n"
        f"?붽툒? {data['salary']:,}?? 珥??뚮퉬 怨꾪쉷? {data['monthly_spend_total']:,}?먯엯?덈떎.\n"
        f"?덉긽 ?⑥? ?꾧툑? {data['remaining_cash']:,}?먯씠怨? 移대뱶 ?ъ슜瑜좎? {data['card_usage_rate'] * 100:.1f}%?낅땲??\n"
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
    open_browser_search(query or "?댁씪 ?좎뵪", tab="weather")

    weather_data = json.loads(fetch_text("https://wttr.in/Seoul?format=j1"))
    current = weather_data["current_condition"][0]
    tomorrow = weather_data["weather"][1] if len(weather_data["weather"]) > 1 else weather_data["weather"][0]
    avg_temp = tomorrow.get("avgtempC", "-")
    max_temp = tomorrow.get("maxtempC", "-")
    min_temp = tomorrow.get("mintempC", "-")
    rain_chance = tomorrow.get("hourly", [{}])[4].get("chanceofrain", "-")

    summary = (
        f"?댁씪 ?쒖슱 湲곗??쇰줈 蹂대㈃ ?됯퇏 {avg_temp}???뺣룄怨? 理쒓퀬 {max_temp}??理쒖? {min_temp}?꾨줈 蹂댁엯?덈떎.\n\n"
        f"鍮???媛?μ꽦? ???{rain_chance}% ?뺣룄?쇱꽌, ?몄텧 ?쇱젙 ?덉쑝硫??곗궛 梨숆만吏 媛숈씠 蹂댁떆硫?醫뗪쿋?듬땲??\n\n"
        f"吏湲??꾩옱 湲곗삩? {current.get('temp_C', '-')}?꾩엯?덈떎."
    )
    return summary, {"current": current, "tomorrow": tomorrow}


def build_web_search_briefing(query: str) -> tuple[str, dict]:
    open_browser_search(query)
    summary = (
        f"PC?먯꽌 '{query}' 寃??寃곌낵瑜??댁뼱??듬땲??\n\n"
        "???④퀎?먯꽌??釉뚮씪?곗?源뚯? 諛붾줈 ?닿퀬, 寃?됱쓣 ?쒖옉?섎뒗 ?먮쫫?쇰줈 癒쇱? ?곌껐?대??댁슂."
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


