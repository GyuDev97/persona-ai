import json
import time
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from datetime import datetime

from app.config import load_env_file
from app.services.agent_task_service import claim_next_agent_task, complete_agent_task, fail_agent_task
from app.storage.database import initialize_database


POLL_SECONDS = 5
DEVICE_LABEL = "pc-agent"


def main() -> None:
    load_env_file()
    initialize_database()
    print(f"[{datetime.now().isoformat(timespec='seconds')}] PC agent started as '{DEVICE_LABEL}'")
    while True:
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


def handle_task(task_type: str, query: str) -> tuple[str, dict]:
    if task_type == "news_briefing":
        return build_news_briefing(query)
    if task_type == "weather_briefing":
        return build_weather_briefing(query)
    return build_web_search_briefing(query)


def build_news_briefing(query: str) -> tuple[str, dict]:
    search_query = query or "최신 뉴스"
    open_browser_search(search_query, tab="news")

    rss_url = (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote(search_query)
        + "&hl=ko&gl=KR&ceid=KR:ko"
    )
    root = ET.fromstring(fetch_text(rss_url))
    items = root.findall("./channel/item")[:5]
    titles = [clean_text(item.findtext("title", default="")) for item in items if item.findtext("title")]
    if not titles:
        raise RuntimeError("뉴스 헤드라인을 찾지 못했습니다.")

    summary = "최신 뉴스 기준으로 이런 흐름입니다.\n\n" + "\n".join(
        f"{index + 1}. {title}" for index, title in enumerate(titles[:3])
    )
    return summary, {"titles": titles}


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
