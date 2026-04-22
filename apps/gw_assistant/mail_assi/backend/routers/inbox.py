from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.services.db import connect, ensure_database
from backend.services.mail_logic import analyze_message, utc_now_iso


router = APIRouter()


class IncomingMessage(BaseModel):
    sender: str = Field(..., description="보낸 사람")
    subject: str = Field(..., description="쪽지 제목")
    body: str = Field(..., description="쪽지 본문")


def load_messages() -> list[dict]:
    ensure_database()
    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, sender, subject, body, created_at, summary, action, reason, draft_reply
                FROM messages
                ORDER BY id DESC
                """
            )
            rows = cursor.fetchall()

    return [
        {
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
            },
        }
        for row in rows
    ]


@router.get("/messages")
def list_messages() -> dict[str, list[dict]]:
    return {"messages": load_messages()}


@router.post("/messages")
def create_message(payload: IncomingMessage) -> dict:
    analysis = analyze_message(payload.sender, payload.subject, payload.body)
    ensure_database()
    created_at = utc_now_iso()

    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO messages (sender, subject, body, summary, action, reason, draft_reply, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    payload.sender,
                    payload.subject,
                    payload.body,
                    analysis.summary,
                    analysis.action,
                    analysis.reason,
                    analysis.draft_reply,
                    created_at,
                ),
            )
            message_id = cursor.lastrowid

    record = {
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
        },
    }
    return record


@router.delete("/messages/{message_id}")
def delete_message(message_id: int) -> dict[str, str]:
    ensure_database()
    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM messages WHERE id = %s", (message_id,))
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="메시지를 찾지 못했습니다.")
    return {"status": "deleted"}
