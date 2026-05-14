from __future__ import annotations

import os
import smtplib
from datetime import date, datetime
from email.message import EmailMessage
from typing import Any

from .agent_news_service import AGENT1_ID, build_agent1_daily_report, list_agent_news_display_items
from .agent_report_center_service import build_agent_report_center

DEFAULT_SMTP_HOST = "smtp.naver.com"
DEFAULT_SMTP_PORT = 587
DEFAULT_NEWS_EMAIL_LIMIT = 8


def is_news_email_enabled() -> bool:
    return _truthy(os.getenv("GYUVIS_NEWS_EMAIL_ENABLED", "0"))


def is_hourly_agent_email_enabled() -> bool:
    return _truthy(os.getenv("GYUVIS_HOURLY_AGENT_EMAIL_ENABLED", "0"))


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


def send_hourly_agent_status_email() -> dict[str, Any]:
    now = datetime.now().replace(microsecond=0)
    target_date = now.date().isoformat()
    config = _email_config()
    limit = _hourly_email_limit()
    report_data = build_agent_report_center()
    items = list_agent_news_display_items(agent_id=AGENT1_ID, report_date=target_date, limit=limit)
    subject = os.getenv("GYUVIS_HOURLY_AGENT_EMAIL_SUBJECT") or f"[GyuOS] {now:%H:%M} Agent 상태와 뉴스 수집 결과"
    text_body = _build_hourly_text_body(now, report_data, items)
    html_body = _build_hourly_html_body(now, report_data, items)

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
        "sent_at": now.isoformat(sep=" "),
        "recipient": config["recipient"],
        "news_count": len(items),
        "agent_count": len(report_data.get("cards") or []),
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


def _hourly_email_limit() -> int:
    try:
        return max(1, min(20, int(os.getenv("GYUVIS_HOURLY_AGENT_EMAIL_LIMIT", str(DEFAULT_NEWS_EMAIL_LIMIT)))))
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


def _build_hourly_text_body(sent_at: datetime, report_data: dict[str, Any], items: list[dict[str, Any]]) -> str:
    cards = report_data.get("cards") or []
    agent_lines = []
    for card in cards:
        label = f"Agent {int(card.get('agent_id') or 0):02d}"
        title = card.get("title") or ""
        status = card.get("status") or "-"
        summary = card.get("latest_result_summary") or card.get("description") or "-"
        updated = card.get("updated_at") or "-"
        agent_lines.extend(
            [
                f"- {label} · {title}",
                f"  상태: {status} / 업데이트: {updated}",
                f"  요약: {summary}",
            ]
        )
        if card.get("error_message"):
            agent_lines.append(f"  확인 필요: {card.get('error_message')}")

    news_lines = []
    if not items:
        news_lines.append("- 이번 시간에 표시할 뉴스 후보가 아직 없습니다.")
    for index, item in enumerate(items, start=1):
        news_lines.extend(
            [
                f"{index}. {item.get('title') or '-'}",
                f"   출처: {item.get('source') or '-'}",
                f"   수집/발행: {item.get('collected_at') or item.get('published_at') or '-'}",
                f"   링크: {item.get('url') or '-'}",
            ]
        )

    pending_proposals = int((report_data.get("autonomy") or {}).get("pending_count") or 0)
    drafts = report_data.get("agent2", {}).get("drafts") or []
    ideas = report_data.get("agent4", {}).get("ideas") or []
    lines = [
        f"GyuOS 시간별 Agent 리포트 - {sent_at:%Y-%m-%d %H:%M}",
        "",
        "[요약]",
        f"- Agent: {len(cards)}명",
        f"- 수집 뉴스 표시: {len(items)}건",
        f"- 블로그 초안: {len(drafts)}건",
        f"- 유튜브 아이디어: {len(ideas)}건",
        f"- 자율 제안 승인 대기: {pending_proposals}건",
        "",
        "[Agent 상태]",
        *agent_lines,
        "",
        "[뉴스 수집 결과]",
        *news_lines,
        "",
        "발행/결제/삭제 같은 위험 액션은 자동 실행하지 않습니다.",
        "이 메일은 GYUVIS_HOURLY_AGENT_EMAIL_ENABLED=1일 때만 발송됩니다.",
    ]
    return "\n".join(lines)


def _build_hourly_html_body(sent_at: datetime, report_data: dict[str, Any], items: list[dict[str, Any]]) -> str:
    cards = report_data.get("cards") or []
    drafts = report_data.get("agent2", {}).get("drafts") or []
    ideas = report_data.get("agent4", {}).get("ideas") or []
    pending_proposals = int((report_data.get("autonomy") or {}).get("pending_count") or 0)

    agent_html = "".join(
        f"""
        <article style="padding:14px;border:1px solid #efe4d9;border-radius:14px;background:#fffdfa;margin-bottom:10px;">
          <div style="font-size:15px;font-weight:900;color:#211b17;">Agent {int(card.get('agent_id') or 0):02d} · {_escape_html(card.get('title') or '')}</div>
          <div style="margin-top:6px;color:#7b6e64;font-size:13px;font-weight:700;">상태 {_escape_html(card.get('status') or '-')} · 업데이트 {_escape_html(card.get('updated_at') or '-')}</div>
          <div style="margin-top:8px;color:#4f463f;font-size:14px;line-height:1.6;font-weight:700;">{_escape_html(card.get('latest_result_summary') or card.get('description') or '-')}</div>
          {f'<div style="margin-top:8px;color:#c52f2a;font-size:13px;font-weight:800;">확인 필요: {_escape_html(card.get("error_message"))}</div>' if card.get("error_message") else ''}
        </article>
        """
        for card in cards
    )
    news_html = "".join(
        f"""
        <article style="padding:14px;border:1px solid #efe4d9;border-radius:14px;background:#fffdfa;margin-bottom:10px;">
          <div style="font-size:15px;font-weight:900;line-height:1.45;">{index}. {_link_or_title(item)}</div>
          <div style="margin-top:6px;color:#7b6e64;font-size:13px;font-weight:700;">{_escape_html(item.get('source') or '-')} · {_escape_html(item.get('collected_at') or item.get('published_at') or '-')}</div>
          <ul style="margin:10px 0 0 0;padding-left:18px;color:#4f463f;font-size:13px;font-weight:700;line-height:1.55;">
            {''.join(f'<li>{_escape_html(line)}</li>' for line in _summarize_news_item(item)[:2])}
          </ul>
        </article>
        """
        for index, item in enumerate(items, start=1)
    ) or """
        <article style="padding:14px;border:1px dashed #efe4d9;border-radius:14px;background:#fffdfa;">
          이번 시간에 표시할 뉴스 후보가 아직 없습니다.
        </article>
    """
    return f"""
    <!doctype html>
    <html lang="ko">
    <body style="margin:0;padding:24px;background:#fbf7f1;color:#211b17;font-family:Malgun Gothic,Arial,sans-serif;">
      <main style="max-width:860px;margin:0 auto;background:#fffaf5;border:1px solid #efe4d9;border-radius:18px;padding:24px;">
        <h1 style="margin:0;font-size:24px;">GyuOS 시간별 Agent 리포트</h1>
        <div style="margin-top:6px;color:#8d8379;font-weight:700;">{sent_at:%Y-%m-%d %H:%M} · 로컬 PC Agent Runner</div>
        <section style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:20px 0;">
          {_metric_html('뉴스', len(items))}
          {_metric_html('초안', len(drafts))}
          {_metric_html('아이디어', len(ideas))}
          {_metric_html('자율 제안', pending_proposals)}
        </section>
        <h2 style="margin:20px 0 10px;font-size:18px;">Agent 상태</h2>
        {agent_html or '<div style="color:#8d8379;">Agent 상태 데이터가 없습니다.</div>'}
        <h2 style="margin:22px 0 10px;font-size:18px;">뉴스 수집 결과</h2>
        {news_html}
        <p style="margin:24px 0 0 0;color:#8d8379;font-size:12px;line-height:1.6;">
          발행/결제/삭제 같은 위험 액션은 자동 실행하지 않습니다. 이 메일은 시간별 리포트 설정이 켜진 경우에만 발송됩니다.
        </p>
      </main>
    </body>
    </html>
    """


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


def _metric_html(label: str, value: int) -> str:
    return f"""
    <div style="padding:12px;border:1px solid #efe4d9;border-radius:13px;background:#fffdfa;">
      <div style="color:#8d8379;font-size:12px;font-weight:800;">{_escape_html(label)}</div>
      <div style="margin-top:5px;font-size:22px;font-weight:900;color:#211b17;">{value}</div>
    </div>
    """


def _link_or_title(item: dict[str, Any]) -> str:
    title = _escape_html(item.get("title") or "-")
    url = _escape_html(item.get("url") or "")
    return f'<a href="{url}" target="_blank" rel="noreferrer" style="color:#a6420b;text-decoration:none;">{title}</a>' if url else title


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
