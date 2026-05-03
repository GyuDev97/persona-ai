from __future__ import annotations

import re
from typing import Any


TOPIC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("AI", ("ai", "gpt", "openai", "오픈ai", "인공지능", "온디바이스", "에이전트")),
    ("모바일·스마트폰", ("스마트폰", "모바일", "갤럭시", "아이폰", "iphone", "galaxy", "android", "안드로이드")),
    ("운영체제·업데이트", ("ios", "업데이트", "update", "베타", "보안패치", "패치", "버전")),
    ("웨어러블·디바이스", ("웨어러블", "워치", "watch", "헤드셋", "기기", "디바이스")),
    ("플랫폼·빅테크", ("삼성", "애플", "구글", "microsoft", "마이크로소프트", "네이버", "카카오", "플랫폼")),
    ("보안·규제", ("보안", "취약점", "해킹", "개인정보", "규제", "법안")),
)


def build_blog_ready_news(news_items: list[dict[str, Any]] | list[str], limit: int = 8) -> dict[str, Any]:
    titles = _extract_titles(news_items)
    cleaned_titles = remove_duplicate_titles(titles)[:limit]
    grouped = group_titles_by_topic(cleaned_titles)
    summary = summarize_grouped_news(grouped)
    draft = build_structured_blog_draft(grouped, summary)
    return {
        "titles": cleaned_titles,
        "grouped": grouped,
        "summary": summary,
        "draft": draft,
    }


def remove_duplicate_titles(titles: list[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for title in titles:
        readable = clean_news_title(title)
        key = _dedupe_key(readable)
        if not readable or key in seen:
            continue
        seen.add(key)
        cleaned.append(readable)
    return cleaned


def group_titles_by_topic(titles: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for title in titles:
        topic = detect_topic(title)
        grouped.setdefault(topic, []).append(title)
    return dict(sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])))


def summarize_grouped_news(grouped: dict[str, list[str]]) -> str:
    if not grouped:
        return "오늘은 블로그 초안으로 정리할 만한 IT 뉴스가 아직 충분하지 않습니다."

    topic_names = list(grouped)
    lead_topic = topic_names[0]
    lead_title = grouped[lead_topic][0]
    if len(topic_names) == 1:
        topic_text = lead_topic
    elif len(topic_names) == 2:
        topic_text = f"{topic_names[0]}와 {topic_names[1]}"
    else:
        topic_text = f"{topic_names[0]}, {topic_names[1]}, {topic_names[2]}"

    return (
        f"오늘 IT 뉴스는 {topic_text} 흐름으로 묶어볼 수 있습니다. "
        f"가장 먼저 볼 만한 소식은 '{lead_title}'이며, 단일 기사로 보기보다 "
        "모바일 기기와 서비스 경험이 AI, 업데이트, 플랫폼 전략과 함께 움직이는 신호로 해석하면 좋겠습니다."
    )


def build_structured_blog_draft(grouped: dict[str, list[str]], summary: str) -> str:
    if not grouped:
        return (
            "오늘은 아직 정리할 뉴스가 충분하지 않습니다.\n\n"
            "뉴스가 더 수집되면 AI, 모바일, 업데이트, 플랫폼 흐름으로 묶어 블로그 초안을 만들겠습니다."
        )

    sections = []
    all_titles = [title for titles in grouped.values() for title in titles]
    headline_lines = "\n".join(f"- {title}" for title in all_titles[:5])

    for topic, titles in grouped.items():
        title_lines = "\n".join(f"- {title}" for title in titles[:4])
        sections.append(
            f"## {topic}\n\n"
            f"{title_lines}\n\n"
            f"{_topic_commentary(topic, titles)}"
        )

    return (
        f"{build_blog_title_from_grouped_news(grouped)}\n\n"
        "## 한눈에 보는 오늘의 흐름\n\n"
        f"{summary}\n\n"
        "## 오늘 체크한 주요 헤드라인\n\n"
        f"{headline_lines}\n\n"
        + "\n\n".join(sections)
        + "\n\n## 정리\n\n"
        "오늘 소식의 핵심은 기술 자체보다 사용자가 실제로 체감할 변화입니다. "
        "AI 기능, 모바일 업데이트, 플랫폼 전략은 따로 움직이지 않고 하나의 사용자 경험으로 합쳐지고 있습니다. "
        "앞으로도 신제품 소식뿐 아니라 업데이트 이후 무엇이 달라지는지 중심으로 계속 살펴보면 좋겠습니다."
    )


def build_blog_title_from_grouped_news(grouped: dict[str, list[str]]) -> str:
    topics = list(grouped)[:3]
    if not topics:
        return "모바일·IT 주요 소식 정리"
    if len(topics) == 1:
        return f"{topics[0]}, 오늘 IT 주요 소식 정리"
    return f"{'·'.join(topics)}, 오늘 모바일·IT 주요 소식 정리"


def detect_topic(title: str) -> str:
    lowered = title.lower()
    for topic, keywords in TOPIC_RULES:
        if any(keyword.lower() in lowered for keyword in keywords):
            return topic
    return "기타 IT 이슈"


def clean_news_title(title: str) -> str:
    text = " ".join(str(title or "").split())
    text = re.sub(r"\s+-\s+[^-]{2,30}$", "", text).strip()
    text = re.sub(r"\[[^\]]+\]|\([^)]*속보[^)]*\)", "", text).strip()
    text = re.sub(r"^[\"'“”‘’]+|[\"'“”‘’]+$", "", text).strip()
    return text


def _extract_titles(news_items: list[dict[str, Any]] | list[str]) -> list[str]:
    titles: list[str] = []
    for item in news_items:
        if isinstance(item, dict):
            titles.append(str(item.get("title") or ""))
        else:
            titles.append(str(item or ""))
    return titles


def _dedupe_key(title: str) -> str:
    text = title.lower()
    text = re.sub(r"[^0-9a-z가-힣]+", "", text)
    return text[:80]


def _topic_commentary(topic: str, titles: list[str]) -> str:
    first = titles[0] if titles else "관련 소식"
    comments = {
        "AI": f"'{first}' 같은 소식은 AI가 별도 서비스가 아니라 기기와 앱 안으로 들어오는 흐름을 보여줍니다.",
        "모바일·스마트폰": f"'{first}'는 실제 구매나 업데이트 판단과 연결될 수 있어 사용자 체감 변화 중심으로 보는 편이 좋습니다.",
        "운영체제·업데이트": f"'{first}'처럼 업데이트 관련 소식은 새 기능보다 안정성, 호환성, 보안 변화를 함께 확인해야 합니다.",
        "웨어러블·디바이스": f"'{first}'는 스마트폰 밖의 기기들이 건강, 알림, 생산성 경험과 더 강하게 연결되는 흐름으로 볼 수 있습니다.",
        "플랫폼·빅테크": f"'{first}'는 개별 제품보다 기업들이 생태계를 어떻게 묶고 있는지 보여주는 소식입니다.",
        "보안·규제": f"'{first}'는 편의성과 함께 개인정보, 보안, 정책 변화도 같이 봐야 한다는 신호입니다.",
    }
    return comments.get(topic, f"'{first}'를 중심으로 보면 오늘의 IT 흐름을 조금 더 쉽게 정리할 수 있습니다.")
