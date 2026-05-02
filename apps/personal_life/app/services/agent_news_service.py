import json
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from ..storage.database import execute, fetch_all, fetch_one


AGENT1_ID = 1
AGENT1_TOPIC = "IT 모바일 테크 기술 뉴스"
AGENT1_DISPLAY_LABEL = "최신 IT 뉴스"
NEWS_TIMEZONE = timezone(timedelta(hours=9))


def save_news_items(agent_id: int, topic: str, items: list[dict[str, Any]]) -> int:
    inserted = 0
    for item in items:
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or "").strip()
        if not url or not title:
            continue

        exists = fetch_one("SELECT id FROM agent_news_items WHERE agent_id = ? AND url = ?", (agent_id, url))
        if exists is not None:
            continue

        execute(
            """
            INSERT INTO agent_news_items (
                agent_id, topic, title, url, source, published_at, importance_score
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agent_id,
                topic,
                title,
                url,
                str(item.get("source") or ""),
                _normalize_datetime(item.get("published_at")),
                int(item.get("importance_score") or score_news_title(title)),
            ),
        )
        inserted += 1
    return inserted


def get_agent_news_stats(agent_id: int = AGENT1_ID, report_date: str | None = None) -> dict[str, Any]:
    target_date = report_date or date.today().isoformat()
    today_items = list_agent_news_items(agent_id=agent_id, report_date=target_date, limit=200)
    display_items = list_agent_news_display_items(agent_id=agent_id, report_date=target_date, limit=200)
    report = get_agent_report(agent_id=agent_id, report_date=target_date)
    return {
        "agent_id": agent_id,
        "report_date": target_date,
        "label": AGENT1_DISPLAY_LABEL,
        "collected_count": len(display_items),
        "today_count": len(today_items),
        "selected_count": min(len(display_items), 5),
        "latest_titles": [item["title"] for item in display_items[:5]],
        "last_collected_at": display_items[0]["collected_at"] if display_items else None,
        "scope_days": 1 if len(today_items) >= 3 else 3,
        "report": report,
    }


def list_agent_news_items(
    agent_id: int = AGENT1_ID,
    report_date: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    target_date = report_date or date.today().isoformat()
    return fetch_all(
        """
        SELECT *
        FROM agent_news_items
        WHERE agent_id = ? AND DATE(COALESCE(published_at, collected_at)) = ?
        ORDER BY COALESCE(published_at, collected_at) DESC, importance_score DESC, collected_at DESC, id DESC
        LIMIT ?
        """,
        (agent_id, target_date, limit),
    )


def list_agent_news_display_items(
    agent_id: int = AGENT1_ID,
    report_date: str | None = None,
    limit: int = 5,
    min_today: int = 3,
    fallback_days: int = 3,
) -> list[dict[str, Any]]:
    target_date = report_date or date.today().isoformat()
    today_items = list_agent_news_items(agent_id=agent_id, report_date=target_date, limit=max(limit * 4, limit))
    today_display_items = _filter_display_news(today_items)
    if len(today_display_items) >= min_today:
        return today_display_items[:limit]

    try:
        target = date.fromisoformat(target_date)
    except ValueError:
        target = date.today()
    start_date = (target - timedelta(days=max(1, fallback_days) - 1)).isoformat()
    fallback_items = fetch_all(
        """
        SELECT *
        FROM agent_news_items
        WHERE agent_id = ?
          AND DATE(COALESCE(published_at, collected_at)) BETWEEN ? AND ?
        ORDER BY COALESCE(published_at, collected_at) DESC, importance_score DESC, collected_at DESC, id DESC
        LIMIT ?
        """,
        (agent_id, start_date, target_date, max(limit * 6, limit)),
    )
    fallback_display_items = _filter_display_news(fallback_items)
    return (fallback_display_items or fallback_items)[:limit]


def get_agent_report(agent_id: int = AGENT1_ID, report_date: str | None = None) -> dict[str, Any] | None:
    target_date = report_date or date.today().isoformat()
    report = fetch_one(
        """
        SELECT *
        FROM agent_reports
        WHERE agent_id = ? AND report_date = ?
        """,
        (agent_id, target_date),
    )
    if report is None:
        return None
    try:
        report["highlights"] = json.loads(report.get("highlights_json") or "[]")
    except json.JSONDecodeError:
        report["highlights"] = []
    return report


def build_agent1_daily_report(report_date: str | None = None) -> dict[str, Any]:
    target_date = report_date or date.today().isoformat()
    today_count = len(list_agent_news_items(agent_id=AGENT1_ID, report_date=target_date, limit=200))
    items = list_agent_news_display_items(agent_id=AGENT1_ID, report_date=target_date, limit=100)
    highlights = items[:5]
    if highlights:
        summary = (
            f"에이전트 1번 {target_date} 최신 IT 뉴스 보고입니다. "
            f"오늘 발행 기준 {today_count}건을 확인했고, 부족할 경우 최근 3일 범위까지 확장해 "
            f"최신순 {len(highlights)}건을 선별했습니다."
        )
    else:
        summary = (
            f"에이전트 1번 {target_date} 최신 IT 뉴스 보고입니다. "
            "오늘과 최근 3일 범위에서 표시할 IT 뉴스가 아직 없습니다. 수집기를 다시 실행해 확인이 필요합니다."
        )

    highlights_payload = [
        {
            "title": item["title"],
            "url": item["url"],
            "source": item.get("source") or "",
            "published_at": _stringify_datetime(item.get("published_at")),
            "importance_score": item.get("importance_score"),
        }
        for item in highlights
    ]
    existing = get_agent_report(agent_id=AGENT1_ID, report_date=target_date)
    if existing is None:
        execute(
            """
            INSERT INTO agent_reports (
                agent_id, report_date, title, summary, highlights_json, status
            )
            VALUES (?, ?, ?, ?, ?, 'completed')
            """,
            (AGENT1_ID, target_date, AGENT1_DISPLAY_LABEL, summary, json.dumps(highlights_payload, ensure_ascii=False)),
        )
    else:
        execute(
            """
            UPDATE agent_reports
            SET title = ?, summary = ?, highlights_json = ?, status = 'completed', updated_at = ?
            WHERE agent_id = ? AND report_date = ?
            """,
            (
                AGENT1_DISPLAY_LABEL,
                summary,
                json.dumps(highlights_payload, ensure_ascii=False),
                datetime.now().replace(microsecond=0).isoformat(sep=" "),
                AGENT1_ID,
                target_date,
            ),
        )
    return get_agent_report(agent_id=AGENT1_ID, report_date=target_date) or {}


def score_news_title(title: str) -> int:
    keywords = {
        "AI": 3,
        "OpenAI": 3,
        "GPT": 3,
        "인공지능": 3,
        "반도체": 3,
        "Mobile": 2,
        "스마트폰": 2,
        "Smartphone": 2,
        "모바일": 2,
        "Galaxy": 2,
        "갤럭시": 2,
        "iPhone": 2,
        "아이폰": 2,
        "iOS": 2,
        "Android": 2,
        "안드로이드": 2,
        "Wearable": 2,
        "웨어러블": 2,
        "Apple": 2,
        "애플": 2,
        "Google": 2,
        "구글": 2,
        "Samsung": 2,
        "삼성": 2,
        "보안": 2,
        "업데이트": 1,
        "출시": 1,
    }
    score = 1
    lowered = title.lower()
    for keyword, weight in keywords.items():
        if keyword.lower() in lowered or keyword in title:
            score += weight
    return min(score, 10)


def _filter_display_news(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in items if score_news_title(str(item.get("title") or "")) > 1]


def split_title_source(raw_title: str) -> tuple[str, str]:
    title = " ".join(raw_title.split())
    if " - " not in title:
        return title, ""
    main, source = title.rsplit(" - ", 1)
    return main.strip(), source.strip()


def parse_rss_datetime(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(NEWS_TIMEZONE).replace(tzinfo=None, microsecond=0).isoformat(sep=" ")


def _normalize_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat(sep=" ")
    return str(value)


def _stringify_datetime(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
