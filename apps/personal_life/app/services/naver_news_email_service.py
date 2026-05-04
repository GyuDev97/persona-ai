from __future__ import annotations

import os
import smtplib
from datetime import date
from email.message import EmailMessage
from typing import Any

from .agent_news_service import AGENT1_ID, build_agent1_daily_report, list_agent_news_display_items

DEFAULT_SMTP_HOST = "smtp.naver.com"
DEFAULT_SMTP_PORT = 587
DEFAULT_NEWS_EMAIL_LIMIT = 8


def is_news_email_enabled() -> bool:
    return _truthy(os.getenv("GYUVIS_NEWS_EMAIL_ENABLED", "0"))


def send_agent1_morning_news_email(report_date: str | None = None) -> dict[str, Any]:
    target_date = report_date or date.today().isoformat()
    config = _email_config()
    limit = _news_email_limit()
    report = build_agent1_daily_report(target_date)
    items = list_agent_news_display_items(agent_id=AGENT1_ID, report_date=target_date, limit=limit)
    subject = os.getenv("GYUVIS_NEWS_EMAIL_SUBJECT", f"[GyuOS] {target_date} IT 뉴스 브리핑")
    text_body = _build_text_body(target_date, report, items)
    html_body = _build_html_body(target_date, report, items)

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config["sender"]
    message["To"] = config["recipient"]
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(config["host"], config["port"], timeout=20) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(config["username"], config["password"])
        smtp.send_message(message)

    return {
        "date": target_date,
        "recipient": config["recipient"],
        "sent_count": len(items),
        "subject": subject,
    }


def _email_config() -> dict[str, Any]:
    username = (os.getenv("GYUVIS_NAVER_EMAIL_USERNAME") or "").strip()
    password = os.getenv("GYUVIS_NAVER_EMAIL_PASSWORD") or ""
    recipient = (os.getenv("GYUVIS_NEWS_EMAIL_TO") or username).strip()
    sender = (os.getenv("GYUVIS_NEWS_EMAIL_FROM") or username).strip()
    host = os.getenv("GYUVIS_NAVER_SMTP_HOST", DEFAULT_SMTP_HOST).strip() or DEFAULT_SMTP_HOST
    port = int(os.getenv("GYUVIS_NAVER_SMTP_PORT", str(DEFAULT_SMTP_PORT)))

    if not username:
        raise ValueError("GYUVIS_NAVER_EMAIL_USERNAME 설정이 필요합니다.")
    if not password:
        raise ValueError("GYUVIS_NAVER_EMAIL_PASSWORD 설정이 필요합니다.")
    if not recipient:
        raise ValueError("GYUVIS_NEWS_EMAIL_TO 설정이 필요합니다.")

    return {
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "recipient": recipient,
        "sender": sender,
    }


def _news_email_limit() -> int:
    try:
        return max(1, min(20, int(os.getenv("GYUVIS_NEWS_EMAIL_LIMIT", str(DEFAULT_NEWS_EMAIL_LIMIT)))))
    except ValueError:
        return DEFAULT_NEWS_EMAIL_LIMIT


def _build_text_body(target_date: str, report: dict[str, Any], items: list[dict[str, Any]]) -> str:
    lines = [
        f"GyuOS IT 뉴스 브리핑 - {target_date}",
        "",
        str(report.get("summary") or "오늘의 IT 뉴스 요약입니다."),
        "",
    ]
    if not items:
        lines.append("표시할 뉴스가 아직 없습니다. Agent 01 수집 상태를 확인해주세요.")
    for index, item in enumerate(items, start=1):
        summary_lines = _summarize_news_item(item)
        lines.extend(
            [
                f"{index}. {item.get('title') or '-'}",
                f"   출처: {item.get('source') or '-'}",
                f"   발행: {item.get('published_at') or item.get('collected_at') or '-'}",
                "   요약:",
                *[f"   - {line}" for line in summary_lines],
                f"   링크: {item.get('url') or '-'}",
                "",
            ]
        )
    lines.extend(
        [
            "",
            "이 메일은 GyuOS 로컬 Agent 01이 생성했습니다.",
            "기사 본문 전문이 아닌 수집된 제목, 출처, 발행일 기반의 짧은 요약입니다.",
            "자동 발송은 GYUVIS_NEWS_EMAIL_ENABLED 설정이 켜진 경우에만 실행됩니다.",
        ]
    )
    return "\n".join(lines)


def _build_html_body(target_date: str, report: dict[str, Any], items: list[dict[str, Any]]) -> str:
    rows = []
    for index, item in enumerate(items, start=1):
        title = _escape_html(item.get("title") or "-")
        url = _escape_html(item.get("url") or "")
        source = _escape_html(item.get("source") or "-")
        published = _escape_html(item.get("published_at") or item.get("collected_at") or "-")
        title_html = f'<a href="{url}" target="_blank" rel="noreferrer" style="color:#a6420b;text-decoration:none;">{title}</a>' if url else title
        summary_html = "".join(
            f"<li style=\"margin:0 0 5px 0;line-height:1.55;\">{_escape_html(line)}</li>"
            for line in _summarize_news_item(item)
        )
        rows.append(
            f"""
            <article style="margin:0 0 18px 0;padding:16px;border:1px solid #efe4d9;border-radius:14px;background:#fffdfa;">
              <div style="font-size:16px;font-weight:800;line-height:1.45;">{index}. {title_html}</div>
              <div style="margin-top:6px;color:#7b6e64;font-size:13px;font-weight:700;">{source} · {published}</div>
              <ul style="margin:12px 0 0 0;padding-left:20px;color:#4f463f;font-size:14px;font-weight:700;">{summary_html}</ul>
            </article>
            """
        )
    if not rows:
        rows.append(
            """
            <article style="padding:16px;border:1px dashed #efe4d9;border-radius:14px;">
              표시할 뉴스가 아직 없습니다. Agent 01 수집 상태를 확인해주세요.
            </article>
            """
        )

    return f"""
    <!doctype html>
    <html lang="ko">
    <body style="margin:0;padding:24px;background:#fbf7f1;color:#211b17;font-family:Malgun Gothic,Arial,sans-serif;">
      <main style="max-width:760px;margin:0 auto;background:#fffaf5;border:1px solid #efe4d9;border-radius:18px;padding:24px;">
        <h1 style="margin:0 0 8px 0;font-size:24px;">GyuOS IT 뉴스 브리핑</h1>
        <div style="color:#8d8379;font-weight:700;">{_escape_html(target_date)} · Agent 01 · {_news_email_limit()}개 후보</div>
        <p style="margin:18px 0;color:#4f463f;line-height:1.7;font-weight:700;">{_escape_html(report.get("summary") or "오늘의 IT 뉴스 요약입니다.")}</p>
        <section>{''.join(rows)}</section>
        <p style="margin:24px 0 0 0;color:#8d8379;font-size:12px;line-height:1.6;">
          이 메일은 GyuOS 로컬 Agent 01이 생성했습니다. 요약은 기사 본문 전문이 아닌 수집된 제목, 출처, 발행일 기반입니다.
          자동 발송은 설정이 켜진 경우에만 실행됩니다.
        </p>
      </main>
    </body>
    </html>
    """


def _summarize_news_item(item: dict[str, Any]) -> list[str]:
    title = " ".join(str(item.get("title") or "").split())
    source = str(item.get("source") or "관련 매체").strip() or "관련 매체"
    published = str(item.get("published_at") or item.get("collected_at") or "").strip()
    topic = _topic_from_title(title)
    published_text = f"{published} 기준으로 " if published else ""
    return [
        f"{source}에서 확인된 {topic} 관련 소식입니다.",
        f"{published_text}GyuOS Agent 01이 중요도가 높은 IT/모바일 뉴스 후보로 분류했습니다.",
        _impact_sentence(title, topic),
    ]


def _topic_from_title(title: str) -> str:
    lowered = title.lower()
    if any(keyword in lowered for keyword in ("ai", "gpt", "openai", "인공지능", "에이전트")):
        return "AI"
    if any(keyword in lowered for keyword in ("아이폰", "iphone", "ios", "애플")):
        return "애플·iOS"
    if any(keyword in lowered for keyword in ("갤럭시", "삼성", "android", "안드로이드")):
        return "삼성·안드로이드"
    if any(keyword in lowered for keyword in ("웨어러블", "워치", "watch", "헤드셋")):
        return "웨어러블"
    if any(keyword in lowered for keyword in ("보안", "취약점", "패치", "규제")):
        return "보안·정책"
    return "IT/모바일"


def _impact_sentence(title: str, topic: str) -> str:
    if topic == "AI":
        return "AI 서비스와 개인 비서, 생산성 도구 흐름에 영향을 줄 수 있어 후속 업데이트를 지켜볼 만합니다."
    if topic == "애플·iOS":
        return "아이폰, iOS 업데이트, 앱 생태계 변화와 연결될 수 있어 사용자 경험 관점에서 체크할 만합니다."
    if topic == "삼성·안드로이드":
        return "갤럭시와 안드로이드 기기 사용성, 모바일 시장 흐름에 영향을 줄 가능성이 있습니다."
    if topic == "웨어러블":
        return "워치, 헬스, 디바이스 연동 경험과 관련된 변화로 볼 수 있습니다."
    if topic == "보안·정책":
        return "개인정보, 보안 업데이트, 서비스 이용 정책과 연결될 수 있어 확인 우선순위가 높습니다."
    if title:
        return "오늘의 IT 흐름을 파악하는 데 참고할 만한 기사라 링크를 열어 세부 내용을 확인해볼 수 있습니다."
    return "세부 내용은 링크를 열어 원문에서 확인하는 것이 좋습니다."


def _escape_html(value: Any) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}
