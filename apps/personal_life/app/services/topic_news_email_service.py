from __future__ import annotations

import smtplib
from datetime import datetime
from email.message import EmailMessage
from typing import Any

from .naver_news_email_service import _email_config


def send_hourly_topic_news_emails(
    it_items: list[dict[str, Any]],
    finance_items: list[dict[str, Any]],
) -> dict[str, Any]:
    sent_at = datetime.now().replace(microsecond=0)
    results = [
        _send_topic_news_email(
            sent_at,
            category="IT·모바일·AI",
            subject=f"[GyuOS] {sent_at:%H:%M} IT·모바일·AI 뉴스",
            items=it_items,
            focus="AI, 인공지능, 모바일, 스마트폰 관련 최신 뉴스",
        ),
        _send_topic_news_email(
            sent_at,
            category="경제·부동산·증권",
            subject=f"[GyuOS] {sent_at:%H:%M} 경제·부동산·증권 뉴스",
            items=finance_items,
            focus="경제, 부동산, 증권 뉴스 중 대출·금리·환율 우선",
        ),
    ]
    return {
        "sent_at": sent_at.isoformat(sep=" "),
        "mail_count": len(results),
        "it_news_count": len(it_items),
        "finance_news_count": len(finance_items),
        "subjects": [result["subject"] for result in results],
    }


def _send_topic_news_email(
    sent_at: datetime,
    *,
    category: str,
    subject: str,
    items: list[dict[str, Any]],
    focus: str,
) -> dict[str, Any]:
    config = _email_config()
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config["sender"]
    message["To"] = config["recipient"]
    message.set_content(_build_text_body(sent_at, category, focus, items))
    message.add_alternative(_build_html_body(sent_at, category, focus, items), subtype="html")

    with smtplib.SMTP(config["host"], config["port"], timeout=20) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(config["username"], config["password"])
        smtp.send_message(message)

    return {"subject": subject, "item_count": len(items)}


def _build_text_body(
    sent_at: datetime,
    category: str,
    focus: str,
    items: list[dict[str, Any]],
) -> str:
    lines = [
        f"GyuOS {category} 뉴스 브리핑",
        f"수집 시각: {sent_at:%Y-%m-%d %H:%M}",
        f"수집 기준: {focus}",
        "",
    ]
    if not items:
        lines.append("이번 시간에는 표시할 최신 뉴스가 없습니다.")
    for index, item in enumerate(items, start=1):
        lines.extend(
            [
                f"{index}. {item.get('title') or '-'}",
                f"   출처: {item.get('source') or '-'}",
                f"   발행: {item.get('published_at') or '-'}",
                f"   링크: {item.get('url') or '-'}",
                "",
            ]
        )
    lines.extend(["", "이 메일은 GPT API 없이 Google News RSS와 네이버 SMTP로 생성·발송되었습니다."])
    return "\n".join(lines)


def _build_html_body(
    sent_at: datetime,
    category: str,
    focus: str,
    items: list[dict[str, Any]],
) -> str:
    rows = "".join(_news_card(index, item) for index, item in enumerate(items, start=1))
    if not rows:
        rows = '<div style="padding:16px;border:1px dashed #d9e2ec;border-radius:12px;">이번 시간에는 표시할 최신 뉴스가 없습니다.</div>'
    return f"""
    <!doctype html>
    <html lang="ko">
    <body style="margin:0;padding:24px;background:#f5f7fa;color:#172b4d;font-family:Malgun Gothic,Arial,sans-serif;">
      <main style="max-width:760px;margin:0 auto;background:#ffffff;border:1px solid #dfe3e8;border-radius:18px;padding:24px;">
        <h1 style="margin:0 0 8px;font-size:24px;">GyuOS { _escape_html(category) } 뉴스 브리핑</h1>
        <div style="color:#6b778c;font-weight:700;">{sent_at:%Y-%m-%d %H:%M}</div>
        <p style="margin:16px 0 20px;color:#344563;line-height:1.6;font-weight:700;">수집 기준: {_escape_html(focus)}</p>
        {rows}
        <p style="margin:22px 0 0;color:#6b778c;font-size:12px;">GPT API 없이 Google News RSS와 네이버 SMTP로 발송했습니다.</p>
      </main>
    </body>
    </html>
    """


def _news_card(index: int, item: dict[str, Any]) -> str:
    title = _escape_html(item.get("title") or "-")
    url = _escape_html(item.get("url") or "")
    source = _escape_html(item.get("source") or "-")
    published = _escape_html(item.get("published_at") or "-")
    linked_title = (
        f'<a href="{url}" target="_blank" rel="noreferrer" style="color:#0052cc;text-decoration:none;">{title}</a>'
        if url
        else title
    )
    return f"""
    <article style="margin:0 0 14px;padding:16px;border:1px solid #dfe3e8;border-radius:14px;background:#fafbfc;">
      <div style="font-size:16px;font-weight:800;line-height:1.5;">{index}. {linked_title}</div>
      <div style="margin-top:7px;color:#6b778c;font-size:13px;font-weight:700;">{source} · {published}</div>
    </article>
    """


def _escape_html(value: Any) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )
