from __future__ import annotations

import re
from typing import Any


TOPIC_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("AI", ("ai", "gpt", "openai", "오픈ai", "인공지능", "온디바이스", "에이전트")),
    ("모바일·스마트폰", ("스마트폰", "모바일", "갤럭시", "아이폰", "iphone", "galaxy", "android", "안드로이드")),
    ("운영체제·업데이트", ("ios", "업데이트", "update", "베타", "보안패치", "패치", "버전")),
    ("웨어러블·디바이스", ("웨어러블", "워치", "watch", "헤드셋", "기기", "디바이스")),
    ("플랫폼·빅테크", ("삼성", "애플", "구글", "microsoft", "마이크로소프트", "네이버", "카카오", "플랫폼", "스토어")),
    ("보안·규제", ("보안", "취약점", "해킹", "개인정보", "규제", "법안")),
    ("게임·콘텐츠", ("게임", "검은사막", "콘서트", "보상", "이벤트", "서비스 3000일")),
)


def build_blog_ready_news(news_items: list[dict[str, Any]] | list[str], limit: int = 5) -> dict[str, Any]:
    titles = _extract_titles(news_items)
    cleaned_titles = remove_duplicate_titles(titles)[:limit]
    grouped = group_titles_by_topic(cleaned_titles)
    summary = summarize_grouped_news(grouped)
    draft = build_structured_blog_draft(cleaned_titles, grouped, summary)
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
    return dict(sorted(grouped.items(), key=lambda item: (_topic_priority(item[0]), item[0])))


def summarize_grouped_news(grouped: dict[str, list[str]]) -> str:
    if not grouped:
        return "오늘은 블로그 초안으로 정리할 만한 IT 뉴스가 아직 충분하지 않습니다."
    topics = list(grouped)[:3]
    return f"오늘은 {_join_korean_list(topics)} 흐름을 중심으로 살펴볼 만합니다."


def build_structured_blog_draft(titles: list[str], grouped: dict[str, list[str]], summary: str) -> str:
    selected_titles = titles[:5]
    if not selected_titles:
        return (
            "안녕하세요 TechGyu입니다.\n\n"
            "오늘은 아직 블로그 본문으로 풀어쓸 만한 IT 뉴스가 충분히 모이지 않았습니다. "
            "뉴스가 더 수집되면 실제 사용자가 체감할 변화가 큰 소식부터 골라 정리해보겠습니다."
        )

    lead_title = selected_titles[0]
    paragraphs = [
        "안녕하세요 TechGyu입니다.",
        (
            f"이번에 '{lead_title}' 소식이 나왔는데요. 오늘은 이 뉴스를 시작점으로, "
            "눈에 들어온 IT 소식들을 사용자 입장에서 한번 정리해보겠습니다. "
            "기술 이름 자체보다 중요한 건 결국 우리가 일하거나, 앱을 쓰거나, 콘텐츠를 즐기는 방식이 어떻게 달라지느냐니까요."
        ),
    ]

    for index, title in enumerate(selected_titles, start=1):
        paragraphs.append(_build_news_paragraph(index, title))

    paragraphs.append(
        "정리해보면 오늘의 흐름은 단순히 AI, 모바일, 플랫폼 같은 키워드로만 나누기보다 "
        "실제 사용 장면에서 무엇이 편해지고, 무엇을 새로 확인해야 하는지로 보는 편이 더 좋겠습니다. "
        "업무는 조금 더 모바일화되고, AI는 특정 서비스 밖으로 퍼지고, 앱과 콘텐츠 시장은 선택지가 늘어나는 방향으로 움직이고 있습니다."
    )
    return "\n\n".join(paragraphs)


def build_blog_title_from_grouped_news(grouped: dict[str, list[str]]) -> str:
    titles = [title for grouped_titles in grouped.values() for title in grouped_titles][:5]
    if not titles:
        return "오늘 사용자가 체감할 모바일·IT 소식 정리"
    lead_title = _blog_title_subject(titles[0])
    topics = [topic for topic in grouped if topic != "기타 IT 이슈"][:2]
    topic_suffix = f"{_join_korean_list(topics)} 흐름" if topics else "오늘 IT 흐름"
    return f"{lead_title}, {topic_suffix}"


def detect_topic(title: str) -> str:
    lowered = title.lower()
    if _is_app_market(title):
        return "플랫폼·빅테크"
    if _is_game_or_content(title):
        return "게임·콘텐츠"
    for topic, keywords in TOPIC_RULES:
        if any(keyword.lower() in lowered for keyword in keywords):
            return topic
    return "기타 IT 이슈"


def clean_news_title(title: str) -> str:
    text = " ".join(str(title or "").split())
    text = re.sub(r"\s+-\s+[^-]{2,30}$", "", text).strip()
    text = re.sub(r"\[[^\]]+\]|\([^)]*?속보[^)]*\)", "", text).strip()
    text = re.sub(r"^[\"'“”‘’]+|[\"'“”‘’]+$", "", text).strip()
    return text


def _build_news_paragraph(index: int, title: str) -> str:
    category = _classify_title(title)
    lead = f"{index}. {title}"
    take = _human_news_take(title, category)
    user_change = _user_change_comment(title, category)
    return f"{lead}\n\n{take} 사용자 입장에서 보면 {user_change}"


def _classify_title(title: str) -> str:
    text = title.lower()
    if _is_app_market(title):
        return "app_market"
    if any(keyword in text for keyword in ("공무원", "업무", "결재", "행정", "정부", "공공")):
        return "public_work"
    if any(keyword in text for keyword in ("콘서트", "강연", "세미나", "컨퍼런스", "unist")):
        return "event_education"
    if _is_game_or_content(title):
        return "game_content"
    if any(keyword in text for keyword in ("보안", "취약", "해킹", "개인정보", "규제", "정책")):
        return "security_policy"
    if any(keyword in text for keyword in ("업데이트", "update", "ios", "android", "패치", "버전")):
        return "os_update"
    if any(keyword in text for keyword in ("ai", "gpt", "openai", "인공지능", "어시스턴트")):
        return "ai_product"
    if any(keyword in text for keyword in ("아이폰", "iphone", "갤럭시", "galaxy", "스마트폰", "모바일")):
        return "mobile_device"
    return "general"


def _human_news_take(title: str, category: str) -> str:
    subject = _quoted_subject(title)
    comments = {
        "public_work": (
            f"{subject} 공공기관 업무가 데스크톱 중심에서 모바일 중심으로 조금씩 옮겨가는 사례로 볼 수 있습니다. "
            "특히 결재처럼 매일 반복되는 업무에 AI가 붙는다는 점이 눈에 들어옵니다."
        ),
        "event_education": (
            f"{subject} 제품 출시 소식이라기보다는 AI를 어떻게 이해하고 받아들일지에 대한 관심이 커지고 있다는 신호에 가깝습니다. "
            "기술 자체보다 사람들의 학습과 인식 변화 쪽에 초점이 있습니다."
        ),
        "game_content": (
            f"{subject} 모바일 게임 이용자에게는 반가운 이벤트성 소식입니다. "
            "다만 전체 IT 흐름으로 보면 신기술 변화보다는 콘텐츠 서비스가 장기 이용자를 붙잡는 방식에 가깝습니다."
        ),
        "app_market": (
            f"{subject} 앱을 설치하고 결제하는 통로가 조금씩 다양해지는 흐름과 연결됩니다. "
            "특히 iOS에서 외부 스토어 이야기가 나올 때는 개발자와 이용자 모두에게 의미가 있습니다."
        ),
        "security_policy": (
            f"{subject} 편리함만큼 보안과 개인정보 기준도 함께 봐야 한다는 점을 떠올리게 합니다."
        ),
        "os_update": (
            f"{subject} 새 기능보다 업데이트 이후 안정성, 호환성, 사용감이 실제 체감에 더 중요할 수 있는 소식입니다."
        ),
        "ai_product": (
            f"{subject} AI가 별도 서비스가 아니라 일상 앱 안으로 더 깊게 들어오는 흐름을 보여줍니다."
        ),
        "mobile_device": (
            f"{subject} 스마트폰을 바꿀지, 기존 기기를 계속 쓸지 판단할 때 참고할 만한 모바일 소식입니다."
        ),
    }
    return comments.get(
        category,
        f"{subject} 당장 큰 변화처럼 보이지 않아도 앱과 서비스를 고르는 기준에 영향을 줄 수 있는 소식입니다.",
    )


def _user_change_comment(title: str, category: str) -> str:
    comments = {
        "public_work": "이동 중 승인이나 확인이 쉬워지고, 반복 문서 처리 시간이 줄어드는 쪽으로 체감될 가능성이 큽니다.",
        "event_education": "당장 앱 기능이 바뀌지는 않지만, AI를 업무나 공부에 어떻게 써야 할지 고민하는 사람이 더 많아질 수 있습니다.",
        "game_content": "해당 게임을 즐기는 이용자라면 접속 보상이나 복귀 동기가 생기지만, 일반 사용자에게 직접적인 기기 변화는 크지 않습니다.",
        "app_market": "앱 설치 경로와 결제 선택지가 늘어날 수 있고, 장기적으로는 수수료나 앱 가격에도 영향을 줄 수 있습니다.",
        "security_policy": "권한 설정, 업데이트 적용, 개인정보 동의 범위를 한 번 더 확인해야 할 일이 늘어날 수 있습니다.",
        "os_update": "새 기능보다 배터리, 알림, 앱 호환성처럼 매일 쓰는 부분의 변화가 먼저 느껴질 수 있습니다.",
        "ai_product": "검색하거나 직접 입력하던 일을 앱 안에서 요약, 추천, 자동 작성으로 처리하는 장면이 늘어날 수 있습니다.",
        "mobile_device": "구매 타이밍, 기기 교체 이유, 사진·메신저·결제 같은 일상 사용감에 영향을 줄 수 있습니다.",
    }
    return comments.get(category, "사용 방식이 크게 바뀌지는 않아도 서비스 선택 기준을 조금씩 바꿀 수 있습니다.")


def _is_game_or_content(title: str) -> bool:
    text = title.lower()
    if _is_app_market(title):
        return False
    return any(keyword in text for keyword in ("게임", "검은사막", "콘서트", "보상", "이벤트", "서비스 3000일"))


def _is_app_market(title: str) -> bool:
    text = title.lower()
    return any(keyword in text for keyword in ("앱스토어", "스토어", "epic", "에픽게임즈", "ios용"))


def _join_korean_list(values: list[str]) -> str:
    if not values:
        return "모바일·IT"
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]}와 {values[1]}"
    return f"{values[0]}, {values[1]}, {values[2]}"


def _topic_priority(topic: str) -> int:
    priorities = {
        "AI": 0,
        "모바일·스마트폰": 1,
        "운영체제·업데이트": 2,
        "플랫폼·빅테크": 3,
        "웨어러블·디바이스": 4,
        "보안·규제": 5,
        "게임·콘텐츠": 6,
        "기타 IT 이슈": 7,
    }
    return priorities.get(topic, 99)


def _quoted_subject(text: str) -> str:
    return f"'{text}'{_topic_particle(text)}"


def _blog_title_subject(title: str) -> str:
    text = clean_news_title(title)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(단독|속보|종합|영상)\s*[:：-]?\s*", "", text).strip()
    text = re.sub(r"[\"'“”‘’]", "", text)
    text = re.split(r"\s*[.…]|[?？!！]", text, maxsplit=1)[0].strip()
    if len(text) > 30:
        cut = text[:30].rstrip()
        last_space = cut.rfind(" ")
        if last_space >= 14:
            cut = cut[:last_space]
        text = f"{cut}…"
    return text or "오늘 IT 주요 소식"


def _topic_particle(text: str) -> str:
    return "은" if _has_final_consonant(text) else "는"


def _has_final_consonant(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    code = ord(stripped[-1])
    if 0xAC00 <= code <= 0xD7A3:
        return (code - 0xAC00) % 28 != 0
    return False


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
