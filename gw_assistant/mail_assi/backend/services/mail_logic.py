from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
import re

from backend.services.ai_draft import generate_ai_reply


ReplyAction = Literal["reply", "ignore", "review"]
ReplyTone = Literal["warm", "balanced", "formal"]


@dataclass
class MessageAnalysis:
    summary: str
    action: ReplyAction
    reason: str
    draft_reply: str
    tone: ReplyTone
    draft_source: str


QUESTION_MARKERS = (
    "?",
    "문의",
    "질문",
    "요청",
    "부탁",
    "가능",
    "확인",
    "회신",
    "답변",
)
IGNORE_MARKERS = (
    "광고",
    "홍보",
    "뉴스레터",
    "구독",
    "수신거부",
    "영수증",
    "결제 완료",
)
REVIEW_MARKERS = (
    "계약",
    "비용",
    "결제",
    "입금",
    "주민등록",
    "비밀번호",
    "민감",
    "법무",
    "개인정보",
)


def normalize_text(*parts: str) -> str:
    joined = "\n".join(part.strip() for part in parts if part and part.strip())
    return re.sub(r"\n{3,}", "\n\n", joined).strip()


def normalize_tone(tone: str | None) -> ReplyTone:
    allowed: set[str] = {"warm", "balanced", "formal"}
    if tone in allowed:
        return tone  # type: ignore[return-value]
    return "balanced"


def first_meaningful_line(body: str) -> str:
    for line in body.splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip(" -\t")
        if cleaned:
            return cleaned
    return ""


def build_summary(sender: str, subject: str, body: str) -> str:
    preview = " ".join(
        re.sub(r"\s+", " ", line).strip() for line in body.splitlines() if line.strip()
    )[:180]
    bits = [f"보낸 사람: {sender}", f"제목: {subject}"]
    if preview:
        bits.append(f"핵심 내용: {preview}")
    return " / ".join(bits)


def classify_message(subject: str, body: str) -> tuple[ReplyAction, str]:
    haystack = f"{subject}\n{body}".lower()

    if any(marker in haystack for marker in (marker.lower() for marker in REVIEW_MARKERS)):
        return "review", "금전, 계약, 개인정보처럼 민감한 내용이 보여서 사람이 먼저 확인하는 편이 안전합니다."

    if any(marker in haystack for marker in (marker.lower() for marker in IGNORE_MARKERS)):
        return "ignore", "광고나 안내 성격이 강해서 바로 답장하지 않아도 될 가능성이 높습니다."

    if any(marker in haystack for marker in (marker.lower() for marker in QUESTION_MARKERS)):
        return "reply", "질문이나 요청이 보여서 답장 초안을 함께 준비하는 편이 좋아 보입니다."

    return "review", "문맥이 애매해서 자동 답장보다 사람이 한 번 확인하는 쪽이 더 안전합니다."


def clean_sender_name(sender: str) -> str:
    cleaned = re.sub(r"<[^>]+>", "", sender)
    cleaned = re.sub(r"\([^)]*\)", "", cleaned)
    cleaned = re.sub(r"\[[^\]]*\]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,")
    return cleaned or "안녕하세요"


def build_greeting(sender: str, tone: ReplyTone) -> str:
    name = clean_sender_name(sender)
    if name.endswith(("님", "팀", "실", "센터")):
        return f"{name}, 안녕하세요."
    if tone == "warm":
        return f"{name}님, 안녕하세요."
    if tone == "formal":
        return f"{name}님, 안녕하세요."
    return f"{name}님, 안녕하세요."


def trim_sentence(text: str, limit: int = 90) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return ""
    if len(compact) <= limit:
        return compact.rstrip(".") + "."
    return compact[: limit - 1].rstrip() + "…"


def infer_reply_focus(subject: str, body: str, tone: ReplyTone) -> str:
    combined = f"{subject}\n{body}"

    if any(keyword in combined for keyword in ("미팅", "회의", "일정", "가능", "시간")):
        if tone == "formal":
            return "일정 관련 내용은 확인 후 가능한 시간 기준으로 정리해 다시 안내드리겠습니다."
        if tone == "warm":
            return "일정은 바로 확인해 보고 가능한 시간 기준으로 편하게 다시 말씀드릴게요."
        return "일정 관련 내용 확인했고 가능한 시간 기준으로 정리해서 말씀드릴게요."

    if any(keyword in combined for keyword in ("자료", "문서", "첨부", "공유")):
        if tone == "formal":
            return "필요하신 자료와 공유 범위를 정리한 뒤 다시 전달드리겠습니다."
        if tone == "warm":
            return "필요하신 자료는 챙겨서 보기 쉽게 정리한 뒤 다시 보내드릴게요."
        return "필요하신 자료나 공유드릴 내용 기준으로 정리해 답변드릴게요."

    if any(keyword in combined for keyword in ("견적", "비용", "금액")):
        return "비용이나 조건은 한 번 더 확인한 뒤 정확하게 안내드릴게요."

    if any(keyword in combined for keyword in ("문의", "질문", "확인", "부탁", "요청")):
        if tone == "formal":
            return "문의 주신 항목은 순서대로 검토한 뒤 정리해서 회신드리겠습니다."
        if tone == "warm":
            return "문의 주신 부분은 차근차근 확인해서 부담 없이 다시 답변드릴게요."
        return "문의 주신 부분은 순서대로 확인해서 편하게 다시 답변드릴게요."

    if tone == "formal":
        return "내용 정리 후 확인되는 부분부터 차분히 다시 안내드리겠습니다."
    if tone == "warm":
        return "내용 정리해서 너무 딱딱하지 않게 다시 답변드릴게요."
    return "내용 정리해서 무리 없게 다시 답변드릴게요."


def build_reply_draft(sender: str, subject: str, body: str, tone: ReplyTone) -> str:
    opener = trim_sentence(first_meaningful_line(body), limit=72)
    focus_line = infer_reply_focus(subject, body, tone)

    if tone == "formal":
        received_line = f"'{subject}' 관련 메일 잘 받았습니다."
        opener_line = f"우선 {opener} 부분부터 확인하고 있습니다." if opener else "보내주신 내용은 순서대로 확인하고 있습니다."
    elif tone == "warm":
        received_line = f"'{subject}' 메일 잘 받았습니다."
        opener_line = f"말씀 주신 내용 중 먼저 {opener} 부분부터 살펴보고 있어요." if opener else "보내주신 내용부터 하나씩 확인하고 있어요."
    else:
        received_line = f"'{subject}' 관련 메일 잘 받았습니다."
        opener_line = f"말씀 주신 내용 중 우선 {opener} 부분부터 확인하고 있습니다." if opener else "보내주신 내용 확인하면서 답변 포인트를 정리하고 있습니다."

    return "\n".join(
        [
            build_greeting(sender, tone),
            "",
            received_line,
            opener_line,
            focus_line,
            "",
            "감사합니다.",
        ]
    )


def build_ignore_note() -> str:
    return ""


def build_rule_draft(sender: str, subject: str, body: str, action: ReplyAction, tone: ReplyTone) -> str:
    if action == "ignore":
        return build_ignore_note()
    if action == "review":
        return ""
    return build_reply_draft(sender, subject, body, tone)


def analyze_message(sender: str, subject: str, body: str, tone: str | None = None) -> MessageAnalysis:
    normalized_body = normalize_text(body)
    normalized_tone = normalize_tone(tone)
    action, reason = classify_message(subject, normalized_body)

    if action in {"review", "ignore"}:
        return MessageAnalysis(
            summary=build_summary(sender, subject, normalized_body),
            action=action,
            reason=reason,
            draft_reply=build_rule_draft(sender, subject, normalized_body, action, normalized_tone),
            tone=normalized_tone,
            draft_source="none",
        )

    ai_result = generate_ai_reply(sender, subject, normalized_body, normalized_tone, action)
    rule_draft = build_rule_draft(sender, subject, normalized_body, action, normalized_tone)
    draft_reply = ai_result.draft or rule_draft
    draft_source = "ai" if ai_result.source == "ai" and draft_reply else "rule"

    return MessageAnalysis(
        summary=build_summary(sender, subject, normalized_body),
        action=action,
        reason=reason if draft_source == "ai" else f"{reason} AI 초안이 없으면 규칙 기반 초안으로 대체합니다.",
        draft_reply=draft_reply,
        tone=normalized_tone,
        draft_source=draft_source,
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
