from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib import error, request


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("MAIL_ASSI_LLM_MODEL", "gpt-4.1-mini")
OPENAI_BASE_URL = os.getenv("MAIL_ASSI_OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")


@dataclass
class AIDraftResult:
    draft: str | None
    source: str
    error_message: str | None = None


def tone_instruction(tone: str) -> str:
    mapping = {
        "warm": "부드럽고 다정한 톤으로 쓰되, 과하게 가볍거나 친한 말투는 피합니다.",
        "balanced": "자연스럽고 편안하지만 업무 메일로도 무리 없는 톤으로 씁니다.",
        "formal": "정중하고 단정한 톤으로 쓰되 지나치게 딱딱하거나 장황하지 않게 씁니다.",
    }
    return mapping.get(tone, mapping["balanced"])


def extract_output_text(payload: dict[str, Any]) -> str:
    direct_text = payload.get("output_text")
    if isinstance(direct_text, str) and direct_text.strip():
        return direct_text.strip()

    parts: list[str] = []
    for item in payload.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                text = content.get("text", "").strip()
                if text:
                    parts.append(text)
    return "\n".join(parts).strip()


def clean_ai_draft(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"^제목\s*:\s*.*$", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^답장\s*:\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"^초안\s*:\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = cleaned.strip().strip('"').strip("'")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not lines:
        return ""

    if len(lines) > 6:
        lines = lines[:6]

    return "\n".join(lines).strip()


def build_prompt(sender: str, subject: str, body: str, tone: str) -> str:
    return f"""
당신은 한국어 메일 어시스턴트입니다.
받은 메일에 대한 답장 초안을 자연스럽고 사람답게 작성하세요.
{tone_instruction(tone)}

작성 규칙:
- 한국어로만 작성합니다.
- 바로 보낼 수 있는 메일 본문만 씁니다.
- 4~6줄 정도의 짧은 답장으로 씁니다.
- 첫 줄은 자연스러운 인사로 시작합니다.
- 메일을 받았다는 확인, 핵심 응답 방향, 마무리 인사를 포함합니다.
- 제목을 그대로 반복하거나 본문을 길게 복붙하지 않습니다.
- 설명, 해설, bullet, 번호 목록을 쓰지 않습니다.
- 확답이 어려운 내용은 검토 후 다시 안내하겠다고 씁니다.
- 지나치게 딱딱한 표현, 같은 말 반복, AI 같은 문장을 피합니다.

보낸 사람: {sender}
제목: {subject}
본문:
{body}
""".strip()


def generate_ai_reply(sender: str, subject: str, body: str, tone: str, action: str) -> AIDraftResult:
    if action != "reply":
        return AIDraftResult(draft=None, source="none", error_message="draft generation skipped")

    if not OPENAI_API_KEY:
        return AIDraftResult(draft=None, source="rule", error_message="OPENAI_API_KEY is not set")

    response_format = {
        "model": OPENAI_MODEL,
        "temperature": 0.8,
        "max_output_tokens": 220,
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": "너는 한국어 업무 메일 답장 초안을 짧고 자연스럽게 작성하는 도우미다.",
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": build_prompt(sender, subject, body, tone),
                    }
                ],
            },
        ],
    }

    req = request.Request(
        url=f"{OPENAI_BASE_URL}/responses",
        data=json.dumps(response_format).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        return AIDraftResult(draft=None, source="rule", error_message=f"HTTP {exc.code}: {details}")
    except Exception as exc:  # noqa: BLE001
        return AIDraftResult(draft=None, source="rule", error_message=str(exc))

    draft = clean_ai_draft(extract_output_text(payload))
    if not draft:
        return AIDraftResult(draft=None, source="rule", error_message="empty response")
    return AIDraftResult(draft=draft, source="ai")
