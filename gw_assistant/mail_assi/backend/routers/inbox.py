from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.services.db import connect, ensure_database
from backend.services.mail_logic import analyze_message, utc_now_iso


router = APIRouter()

DEFAULT_PAGE = 1
DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 50


class IncomingMessage(BaseModel):
    sender: str = Field(..., description="보낸 사람")
    subject: str = Field(..., description="메일 제목")
    body: str = Field(..., description="메일 본문")
    tone: str = Field(default="balanced", description="답장 톤")


class TonePreviewRequest(BaseModel):
    sender: str = Field(..., description="보낸 사람")
    subject: str = Field(..., description="메일 제목")
    body: str = Field(..., description="메일 본문")


def serialize_message(row: dict) -> dict:
    return {
        "id": row["id"],
        "sender": row["sender"],
        "subject": row["subject"],
        "body": row["body"],
        "created_at": row["created_at"],
        "analysis": {
            "summary": row["summary"],
            "action": row["action"],
            "reason": row["reason"],
            "draft_reply": row["draft_reply"],
            "tone": row.get("tone", "balanced"),
            "draft_source": row.get("draft_source", "rule"),
        },
    }


def load_messages(page: int, page_size: int) -> tuple[list[dict], int]:
    ensure_database()
    offset = (page - 1) * page_size

    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS total FROM messages")
            total = int(cursor.fetchone()["total"])
            cursor.execute(
                """
                SELECT id, sender, subject, body, created_at, summary, action, reason, draft_reply, tone, draft_source
                FROM messages
                ORDER BY id DESC
                LIMIT %s OFFSET %s
                """,
                (page_size, offset),
            )
            rows = cursor.fetchall()

    return [serialize_message(row) for row in rows], total


@router.get("/messages")
def list_messages(
    page: int = Query(DEFAULT_PAGE, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> dict:
    messages, total = load_messages(page, page_size)
    total_pages = max(1, (total + page_size - 1) // page_size)
    return {
        "messages": messages,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "has_prev": page > 1,
            "has_next": page < total_pages,
        },
    }


@router.post("/messages")
def create_message(payload: IncomingMessage) -> dict:
    analysis = analyze_message(payload.sender, payload.subject, payload.body, payload.tone)
    ensure_database()
    created_at = utc_now_iso()

    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO messages (
                    sender, subject, body, summary, action, reason, draft_reply, tone, draft_source, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    payload.sender,
                    payload.subject,
                    payload.body,
                    analysis.summary,
                    analysis.action,
                    analysis.reason,
                    analysis.draft_reply,
                    analysis.tone,
                    analysis.draft_source,
                    created_at,
                ),
            )
            message_id = cursor.lastrowid

    return {
        "id": message_id,
        "sender": payload.sender,
        "subject": payload.subject,
        "body": payload.body,
        "created_at": created_at,
        "analysis": {
            "summary": analysis.summary,
            "action": analysis.action,
            "reason": analysis.reason,
            "draft_reply": analysis.draft_reply,
            "tone": analysis.tone,
            "draft_source": analysis.draft_source,
        },
    }


@router.post("/messages/preview-tones")
def preview_tones(payload: TonePreviewRequest) -> dict[str, list[dict]]:
    previews: list[dict] = []
    for tone in ("warm", "balanced", "formal"):
        analysis = analyze_message(payload.sender, payload.subject, payload.body, tone)
        previews.append(
            {
                "tone": analysis.tone,
                "action": analysis.action,
                "reason": analysis.reason,
                "draft_reply": analysis.draft_reply,
                "draft_source": analysis.draft_source,
            }
        )
    return {"previews": previews}


@router.delete("/messages/{message_id}")
def delete_message(message_id: int) -> dict[str, str]:
    ensure_database()
    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM messages WHERE id = %s", (message_id,))
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="메시지를 찾지 못했습니다.")
    return {"status": "deleted"}
