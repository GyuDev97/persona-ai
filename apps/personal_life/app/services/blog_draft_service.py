import json
import os
from datetime import datetime
from typing import Any

from ..storage.database import execute, fetch_all, fetch_one
from .agent_message_service import create_agent_message
from .agent_news_service import AGENT1_ID, list_agent_news_items
from .news_processing_service import build_blog_ready_news, build_blog_title_from_grouped_news


AGENT2_STANDBY_MESSAGE = os.getenv(
    "GYUVIS_AGENT2_STANDBY_MESSAGE",
    "블로그 초안 #{draft_id} 작성 완료했습니다. 발행은 하지 않고 다시 대기하겠습니다.",
)


def create_it_blog_draft_from_agent1(limit: int = 5) -> dict[str, Any]:
    news_items = list_agent_news_items(agent_id=AGENT1_ID, limit=limit)
    if not news_items:
        title = "모바일 출시·업데이트와 AI 주요 소식 정리"
        body = (
            "오늘은 아직 에이전트 1번이 수집한 IT 뉴스가 충분하지 않아, 임시 초안 형태로 정리합니다.\n\n"
            "이 블로그에서는 주로 스마트폰, 워치 같은 모바일 제품의 출시 소식과 업데이트 내용을 다루고, "
            "함께 보면 좋은 AI·플랫폼·보안 관련 IT 주요 소식을 전합니다.\n\n"
            "## 오늘 정리할 포인트\n\n"
            "1. 스마트폰과 웨어러블 신제품 또는 출시 일정\n"
            "2. iOS, 갤럭시, 앱 업데이트처럼 사용자가 바로 체감할 수 있는 변화\n"
            "3. AI 기능이 모바일 경험 안으로 들어오는 흐름\n\n"
            "수집 데이터가 쌓이면 실제 헤드라인을 기반으로 본문을 자동 보강하겠습니다."
        )
    else:
        processed = build_blog_ready_news(news_items, limit=5)
        title = build_blog_title_from_grouped_news(processed["grouped"])
        body = processed["draft"]

    draft_id = execute(
        """
        INSERT INTO agent_blog_drafts (
            agent_id, source_agent_id, title, body, platform, status, source_payload
        )
        VALUES (2, ?, ?, ?, 'naver_blog', 'drafted', ?)
        """,
        (
            AGENT1_ID,
            title,
            body,
            json.dumps(
                {
                    "news_items": news_items,
                    "processed_news": processed if news_items else None,
                },
                ensure_ascii=False,
                default=str,
            ),
        ),
    )
    draft = get_blog_draft(draft_id)
    try:
        create_agent_message(
            2,
            AGENT2_STANDBY_MESSAGE.format(
                draft_id=draft_id,
                title=draft.get("title") or "",
                news_count=len(news_items),
            ),
            to_agent_id=1,
            topic="blog_draft",
            payload={
                "draft_id": draft_id,
                "title": draft.get("title"),
                "source_agent_id": AGENT1_ID,
                "news_count": len(news_items),
            },
        )
    except Exception:
        pass
    return draft


def get_latest_blog_draft(platform: str = "naver_blog") -> dict[str, Any] | None:
    return fetch_one(
        """
        SELECT *
        FROM agent_blog_drafts
        WHERE platform = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (platform,),
    )


def get_blog_draft(draft_id: int) -> dict[str, Any]:
    row = fetch_one("SELECT * FROM agent_blog_drafts WHERE id = ?", (draft_id,))
    if row is None:
        raise ValueError("Blog draft not found")
    return row


def update_blog_draft_status(draft_id: int, status: str) -> dict[str, Any]:
    execute(
        """
        UPDATE agent_blog_drafts
        SET status = ?, updated_at = ?
        WHERE id = ?
        """,
        (status, datetime.now().replace(microsecond=0).isoformat(sep=" "), draft_id),
    )
    return get_blog_draft(draft_id)


def list_blog_drafts(limit: int = 10) -> list[dict[str, Any]]:
    return fetch_all(
        """
        SELECT *
        FROM agent_blog_drafts
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    )


def _build_blog_title(news_items: list[dict[str, Any]]) -> str:
    titles = " ".join(item["title"] for item in news_items)
    mobile_labels = _pick_topic_labels(
        titles,
        (
            ("아이폰 폴드", ("아이폰 폴드", "폴더블 아이폰")),
            ("iOS 업데이트", ("iOS", "아이오에스", "업데이트")),
            ("갤럭시 AI폰", ("갤럭시", "AI폰", "AI 폰")),
            ("스마트폰", ("스마트폰", "모바일")),
            ("워치", ("워치", "웨어러블")),
        ),
    )
    it_labels = _pick_topic_labels(
        titles,
        (
            ("AI", ("AI", "인공지능", "온디바이스", "에이전트")),
            ("보안", ("보안", "취약점")),
            ("플랫폼", ("플랫폼", "구글", "애플", "삼성")),
        ),
    )

    labels = (mobile_labels + it_labels)[:3]
    if labels:
        return f"{'·'.join(labels)}, 오늘 모바일·IT 주요 소식 정리"
    return "모바일 출시·업데이트와 IT 주요 소식 정리"


def _build_blog_body(news_items: list[dict[str, Any]]) -> str:
    headlines = [item["title"] for item in news_items[:5]]
    headline_lines = "\n".join(f"- {title}" for title in headlines)
    mobile_items = [
        item["title"]
        for item in news_items
        if any(keyword in item["title"] for keyword in ("아이폰", "갤럭시", "스마트폰", "모바일", "iOS", "워치", "웨어러블", "업데이트", "출시"))
    ]
    major_items = [
        item["title"]
        for item in news_items
        if any(keyword in item["title"] for keyword in ("AI", "인공지능", "보안", "플랫폼", "구글", "애플", "삼성", "헬스케어"))
    ]
    first = headlines[0] if headlines else "IT 업계의 변화"
    mobile_lines = "\n".join(f"- {title}" for title in mobile_items[:3]) or "- 오늘은 별도 모바일 제품 소식보다 IT 흐름성 이슈가 더 많았습니다."
    major_lines = "\n".join(f"- {title}" for title in major_items[:3]) or "- AI와 플랫폼 변화는 모바일 경험과 연결해서 지켜볼 필요가 있습니다."
    return (
        "오늘은 모바일 제품 출시와 업데이트, 그리고 AI가 사용자 경험 안으로 들어오는 흐름을 중심으로 정리해보겠습니다.\n\n"
        "스마트폰이나 워치 같은 기기는 이제 단순히 사양만 좋아지는 방향이 아니라, 업데이트와 AI 기능을 통해 "
        "사용자가 매일 체감하는 기능을 얼마나 자연스럽게 바꾸는지가 중요해지고 있습니다.\n\n"
        "## 오늘 체크한 주요 헤드라인\n\n"
        f"{headline_lines}\n\n"
        "## 모바일 출시·업데이트 포인트\n\n"
        f"{mobile_lines}\n\n"
        "모바일 소식에서 가장 먼저 볼 부분은 실제 사용자가 체감할 변화입니다. "
        "새로운 폼팩터, 운영체제 업데이트, AI 기능, 연결성 개선처럼 매일 쓰는 경험에 영향을 주는 요소가 핵심입니다.\n\n"
        "## 주요 IT 소식 포인트\n\n"
        f"{major_lines}\n\n"
        f"특히 '{first}' 같은 소식은 단독 이슈로 끝나기보다, 앞으로 스마트폰과 앱 서비스가 어떤 방향으로 바뀔지 보여주는 신호로 볼 수 있습니다.\n\n"
        "## 정리\n\n"
        "최근 IT 흐름은 모바일 기기와 AI 기능이 따로 움직이지 않는다는 점이 중요합니다. "
        "스마트폰은 더 똑똑한 개인 비서처럼 변하고 있고, 업데이트는 단순한 버그 수정이 아니라 새로운 사용 경험을 추가하는 방식으로 바뀌고 있습니다.\n\n"
        "앞으로도 신제품 출시 소식뿐 아니라, 실제로 써볼 만한 업데이트와 체감 기능 중심으로 계속 정리해보겠습니다."
    )


def _pick_topic_labels(text: str, candidates: tuple[tuple[str, tuple[str, ...]], ...]) -> list[str]:
    labels = []
    lowered = text.lower()
    for label, keywords in candidates:
        if any(keyword.lower() in lowered or keyword in text for keyword in keywords):
            labels.append(label)
    return labels
