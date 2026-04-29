import json
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import Any

from ..storage.database import execute, fetch_all, fetch_one


AGENT1_ID = 1
AGENT1_TOPIC = "IT 모바일 테크 기술 뉴스"


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
    items = list_agent_news_items(agent_id=agent_id, report_date=target_date, limit=200)
    report = get_agent_report(agent_id=agent_id, report_date=target_date)
    return {
        "agent_id": agent_id,
        "report_date": target_date,
        "collected_count": len(items),
        "selected_count": min(len(items), 5),
        "latest_titles": [item["title"] for item in items[:5]],
        "last_collected_at": items[0]["collected_at"] if items else None,
        "report": report,
    }


def list_agent_news_items(agent_id: int = AGENT1_ID, report_date: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    target_date = report_date or date.today().isoformat()
    return fetch_all(
        """
        SELECT *
        FROM agent_news_items
        WHERE agent_id = ? AND DATE(collected_at) = ?
        ORDER BY importance_score DESC, published_at DESC, collected_at DESC, id DESC
        LIMIT ?
        """,
        (agent_id, target_date, limit),
    )


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
    items = list_agent_news_items(agent_id=AGENT1_ID, report_date=target_date, limit=100)
    highlights = items[:5]
    if highlights:
        summary = (
            f"에이전트 1번 {target_date} IT 뉴스 보고입니다. "
            f"오늘 10시부터 18시 사이 수집 기준으로 총 {len(items)}건을 확인했고, "
            f"그중 핵심 {len(highlights)}건을 우선 선별했습니다. "
            "상세 화면에서 주요 헤드라인을 확인하시면 됩니다."
        )
    else:
        summary = (
            f"에이전트 1번 {target_date} IT 뉴스 보고입니다. "
            "오늘 수집된 IT 뉴스가 아직 없습니다. 수집기가 실행 중인지 확인이 필요합니다."
        )

    title = "오전 10시~오후 6시 IT 뉴스 요약"
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
            (AGENT1_ID, target_date, title, summary, json.dumps(highlights_payload, ensure_ascii=False)),
        )
    else:
        execute(
            """
            UPDATE agent_reports
            SET title = ?, summary = ?, highlights_json = ?, status = 'completed', updated_at = ?
            WHERE agent_id = ? AND report_date = ?
            """,
            (
                title,
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
        "인공지능": 3,
        "반도체": 3,
        "스마트폰": 2,
        "모바일": 2,
        "갤럭시": 2,
        "아이폰": 2,
        "애플": 2,
        "구글": 2,
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
    return parsed.replace(tzinfo=None, microsecond=0).isoformat(sep=" ")


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
