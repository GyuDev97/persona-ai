from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
import re


ReplyAction = Literal["reply", "ignore", "review"]


@dataclass
class MessageAnalysis:
    summary: str
    action: ReplyAction
    reason: str
    draft_reply: str


QUESTION_MARKERS = ("?", "가능", "부탁", "확인", "문의", "요청", "언제", "어떻게", "회신")
IGNORE_MARKERS = ("광고", "홍보", "뉴스레터", "구독", "수신거부", "영수증", "결제 완료")
REVIEW_MARKERS = ("계약", "비용", "결제", "송금", "주민등록", "비밀번호", "민감", "법무", "개인정보")


def normalize_text(*parts: str) -> str:
    joined = "\n".join(part.strip() for part in parts if part and part.strip())
    return re.sub(r"\n{3,}", "\n\n", joined).strip()


def build_summary(sender: str, subject: str, body: str) -> str:
    snippets = [line.strip() for line in body.splitlines() if line.strip()]
    preview = " ".join(snippets[:2])[:180]
    bits = [f"보낸 사람: {sender}", f"제목: {subject}"]
    if preview:
        bits.append(f"핵심 내용: {preview}")
    return " / ".join(bits)


def classify_message(subject: str, body: str) -> tuple[ReplyAction, str]:
    haystack = f"{subject}\n{body}".lower()

    if any(marker in haystack for marker in (marker.lower() for marker in REVIEW_MARKERS)):
        return "review", "금전, 계약, 개인정보처럼 민감한 표현이 있어서 사람이 먼저 확인하는 편이 안전합니다."

    if any(marker in haystack for marker in (marker.lower() for marker in IGNORE_MARKERS)):
        return "ignore", "광고, 영수증, 공지 성격이 강해서 바로 답장할 필요가 낮아 보입니다."

    if any(marker in haystack for marker in (marker.lower() for marker in QUESTION_MARKERS)):
        return "reply", "질문이나 요청 표현이 보여서 답장 초안을 만드는 게 적절해 보입니다."

    return "review", "문맥이 애매해서 자동 분류보다 사람이 한 번 확인하는 쪽이 안전합니다."


def build_draft(sender: str, subject: str, body: str, action: ReplyAction) -> str:
    if action == "ignore":
        return "답장 초안이 필요하지 않은 메시지로 분류되었습니다."

    greeting = f"{sender}님, 안녕하세요."
    if action == "review":
        return "\n".join(
            [
                greeting,
                "",
                f"'{subject}' 내용 확인했습니다.",
                "관련 내용은 검토 후 다시 답변드리겠습니다.",
                "확인이 필요한 사항이 있으면 정리해서 따로 안내드릴게요.",
                "",
                "감사합니다.",
            ]
        )

    body_lines = [line.strip() for line in body.splitlines() if line.strip()]
    key_line = body_lines[0] if body_lines else "보내주신 내용을 확인했습니다."
    return "\n".join(
        [
            greeting,
            "",
            f"'{subject}' 관련해서 메시지 잘 받았습니다.",
            f"우선 {key_line[:100]} 부분 확인했습니다.",
            "필요한 내용 기준으로 정리해서 답변드리겠습니다.",
            "",
            "감사합니다.",
        ]
    )


def analyze_message(sender: str, subject: str, body: str) -> MessageAnalysis:
    normalized_body = normalize_text(body)
    action, reason = classify_message(subject, normalized_body)
    return MessageAnalysis(
        summary=build_summary(sender, subject, normalized_body),
        action=action,
        reason=reason,
        draft_reply=build_draft(sender, subject, normalized_body, action),
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
