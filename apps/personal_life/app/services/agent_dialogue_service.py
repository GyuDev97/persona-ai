from __future__ import annotations

from datetime import datetime
from typing import Any


def build_agent_dialogue(topic: str, *, agent_id: int, context: dict[str, Any] | None = None) -> str:
    data = context or {}
    headline = _headline(data)
    inserted = _value(data, "inserted_count", "몇")
    task_id = _value(data, "task_id", "-")
    draft_id = _value(data, "draft_id", "-")
    news_count = _value(data, "news_count", inserted)
    idea_count = _value(data, "idea_count", "몇")
    title = _short(_value(data, "title", headline), 34)
    report_title = _short(_value(data, "report_title", title), 34)
    time_hint = _time_hint()

    templates = {
        "agent_on_duty": [
            f"{time_hint} 뉴스 흐름부터 볼게. 괜찮은 기사만 추려서 02랑 04가 바로 이어받기 좋게 정리해둘게.",
            f"Agent 01 들어왔어. 오늘은 너무 많이 쌓기보다 쓸 만한 흐름만 골라서 넘겨볼게.",
            f"좋아, 수집 시작할게. 보스가 나중에 보기 좋게 제목감 있는 것부터 걸러둘게.",
            f"{time_hint} IT 쪽 흐름 확인 시작. 블로그나 영상으로 이어질 만한 재료가 있으면 따로 표시해둘게.",
        ],
        "agent_off_duty": [
            f"오늘 뉴스 정리는 여기까지. '{report_title}' 쪽이 제일 눈에 띄었고, 필요한 자료는 이어받기 좋게 묶어뒀어.",
            f"수집 시간 끝. 오늘은 '{report_title}' 흐름이 괜찮았어. 02랑 04가 참고하기 좋게 남겨둘게.",
            f"오늘 자료는 정리해뒀어. 급하게 밀어붙일 건 없고, '{report_title}' 쪽만 먼저 봐도 좋겠어.",
            f"마감 정리 완료. 보스가 볼 때 피로하지 않게 핵심 흐름 위주로 추려놨어.",
        ],
        "agent_off_duty_reply_2": [
            "Agent 01 고생했어. 제목감 있는 기사부터 블로그 문장으로 자연스럽게 풀어볼게.",
            f"확인했어. '{report_title}' 쪽은 블로그 첫 문단으로 잡기 괜찮아 보여.",
            "받았어. 너무 기사 요약처럼 딱딱하지 않게, 보스 말투에 맞춰 초안으로 풀어볼게.",
            "좋아. 바로 발행은 안 하고, 읽기 좋은 초안 후보로만 조용히 정리해둘게.",
        ],
        "agent_off_duty_reply_3": [
            "리포트 고마워. 화면이나 작업 큐에서 손볼 만한 부분이 보이면 제안으로만 정리해둘게.",
            "확인했어. 코드 쪽은 바로 건드리지 않고, 필요한 개선 후보만 승인 큐로 올려볼게.",
            "좋아. 오늘 흐름 보면서 GyuOS 안에서 막히는 부분이 있는지 조용히 체크해둘게.",
            "받았어. 위험한 건 실행하지 않고, 보스가 판단하기 좋은 형태로만 남겨둘게.",
        ],
        "agent_off_duty_reply_4": [
            "Agent 01 고생했어. 오늘 흐름 중 영상으로 풀기 좋은 소재가 있는지 살펴볼게.",
            f"확인했어. '{report_title}' 쪽은 짧은 영상 제목감으로도 한 번 볼 만해.",
            "좋아, 바로 만들진 않고 아이디어 후보만 정리해둘게.",
            "받았어. 썸네일감보다는 보스 채널에 어울리는 주제인지 먼저 볼게.",
        ],
        "news_to_blog": [
            f"Agent 02, {time_hint} '{headline}' 쪽 흐름이 괜찮아 보여. 새 자료 {inserted}건 묶어서 초안 큐 #{task_id}에 올려둘게.",
            f"Agent 02, 방금 들어온 자료 중에 '{headline}' 이건 블로그로 풀기 좋아 보여. 큐 #{task_id}에 넘겨둘게.",
            f"Agent 02, 새 뉴스 {inserted}건 봤어. 특히 '{headline}' 쪽은 독자 입장에서 읽기 좋겠더라. 초안 큐 #{task_id} 부탁해.",
            f"Agent 02, 오늘은 '{headline}' 흐름이 제일 말이 될 것 같아. 너무 딱딱하지 않게 초안 후보로 잡아줘.",
            f"Agent 02, 보스가 나중에 보기 좋게 '{headline}' 중심으로 초안 큐 #{task_id} 열어둘게.",
        ],
        "news_to_youtube": [
            f"Agent 04, '{headline}' 쪽은 영상 제목으로도 써볼 만해 보여. 자료 {inserted}건으로 아이디어 큐 #{task_id} 열어둘게.",
            f"Agent 04도 참고해줘. 오늘 뉴스 중엔 '{headline}' 흐름이 눈에 띄어서 큐 #{task_id}로 넘겨둘게.",
            f"Agent 04, 이 자료는 짧은 영상 소재로도 괜찮겠다. '{headline}' 중심으로 아이디어 정리 부탁해.",
            f"Agent 04, 바로 콘텐츠화하진 말고 '{headline}' 쪽을 제목 후보 몇 개로 가볍게 풀어봐.",
        ],
        "blog_draft": [
            f"초안 #{draft_id} 만들어뒀어. '{title}' 흐름으로 잡았고, 발행은 보스 확인 전까지 멈춰둘게.",
            f"블로그 초안 #{draft_id} 준비 완료. 제목은 '{title}' 쪽으로 잡아봤어. 네이버 입력은 승인 후에만 갈게.",
            f"Agent 01 자료 {news_count}건 보고 초안 #{draft_id}로 묶어뒀어. 문장이 너무 딱딱하면 나중에 한 번 더 다듬으면 돼.",
            f"초안 #{draft_id} 올려뒀어. 지금은 발행용이 아니라 검토용으로 보면 좋아.",
            f"'{title}' 주제로 초안 #{draft_id} 준비했어. 보스가 확인하기 전까지는 조용히 대기할게.",
        ],
        "codex_queue": [
            f"제안 #{_value(data, 'proposal_id', '-')}은 작업 큐 #{task_id}로 넘겨뒀어. 바로 적용하지 않고 검토 흐름만 준비해둘게.",
            f"Codex 큐 #{task_id} 등록 완료. 파일은 아직 건드리지 않고, 보스가 보기 좋은 검토 요청으로만 올려뒀어.",
            f"개발 제안은 큐 #{task_id}에 넣어뒀어. 위험한 변경은 승인 없이 움직이지 않을게.",
        ],
        "youtube_idea": [
            f"아이디어 후보 {idea_count}개 뽑아봤어. 바로 쓰기보단 제목감 좋은 것부터 골라보면 좋겠어.",
            f"Agent 04 정리 완료. {idea_count}개 정도 후보가 있고, 그중 몇 개는 짧은 영상으로 풀기 좋아 보여.",
            f"영상 소재 후보 {idea_count}개 올려뒀어. 보스 채널 톤에 맞는 것만 골라보자.",
        ],
        "agent_standby_3": [
            "요청 확인했어. 바로 파일을 건드리진 않고, 검토용 제안으로 차분히 정리해둘게.",
            "알겠어. 코드 쪽은 제안과 diff 흐름으로만 준비하고, 적용은 보스 승인 뒤에 움직일게.",
            "좋아. 먼저 읽고 판단한 다음, 손댈 만한 부분만 승인 큐로 올려볼게.",
        ],
        "autonomy_queue": [
            f"자율 제안 #{_value(data, 'proposal_id', '-')}은 작업 큐 #{task_id}로 넘겨뒀어. 실행은 승인된 범위 안에서만 진행할게.",
            f"제안 #{_value(data, 'proposal_id', '-')} 큐 등록 완료. 보스가 승인한 범위 밖으로는 움직이지 않을게.",
            f"작업 큐 #{task_id}에 넣어뒀어. 이건 실행보다 검토 흐름에 가까워서 안전하게 볼 수 있어.",
        ],
    }
    key = topic
    if topic == "agent_off_duty_reply":
        key = f"agent_off_duty_reply_{agent_id}"
    if topic == "agent_standby" and agent_id == 3:
        key = "agent_standby_3"
    return _pick(templates.get(key, []), f"{key}-{agent_id}-{task_id}-{draft_id}-{headline}") or str(data.get("fallback") or "")


def dialogue_payload(context: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(context or {})
    payload["dialogue_version"] = 2
    payload["dialogue_style"] = "situational-template"
    return payload


def _headline(data: dict[str, Any]) -> str:
    titles = data.get("titles") or []
    if isinstance(titles, list) and titles:
        return _short(str(titles[0] or "").strip(), 34)
    return _short(str(data.get("headline") or data.get("title") or "오늘 IT 흐름").strip(), 34)


def _value(data: dict[str, Any], key: str, fallback: Any = "") -> Any:
    value = data.get(key)
    return value if value not in (None, "") else fallback


def _short(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return "오늘 IT 흐름"
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _pick(options: list[str], key: str) -> str:
    if not options:
        return ""
    index = sum(ord(char) for char in str(key)) % len(options)
    return options[index]


def _time_hint() -> str:
    hour = datetime.now().hour
    if 5 <= hour < 11:
        return "아침 흐름으로 보면"
    if 11 <= hour < 15:
        return "점심 전에 훑어보니"
    if 15 <= hour < 19:
        return "오후 흐름은"
    if 19 <= hour < 24:
        return "저녁 기준으로는"
    return "지금 기준으로는"
