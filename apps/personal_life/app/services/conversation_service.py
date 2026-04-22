from ..domain.schemas import ConversationMessageResponse
from ..storage.database import execute, fetch_all
from .datetime_utils import ensure_datetime


def log_conversation(
    role: str,
    message: str,
    interpreted_as: str | None = None,
    created_type: str | None = None,
) -> ConversationMessageResponse:
    conversation_id = execute(
        """
        INSERT INTO assistant_conversations (role, message, interpreted_as, created_type)
        VALUES (?, ?, ?, ?)
        """,
        (role, message, interpreted_as, created_type),
    )
    row = fetch_all(
        """
        SELECT id, role, message, interpreted_as, created_type, created_at
        FROM assistant_conversations
        WHERE id = ?
        """,
        (conversation_id,),
    )[0]
    return _row_to_conversation(row)


def list_conversations(limit: int = 20) -> list[ConversationMessageResponse]:
    rows = fetch_all(
        """
        SELECT id, role, message, interpreted_as, created_type, created_at
        FROM assistant_conversations
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [_row_to_conversation(row) for row in reversed(rows)]


def _row_to_conversation(row: dict) -> ConversationMessageResponse:
    return ConversationMessageResponse(
        id=row["id"],
        role=row["role"],
        message=row["message"],
        interpreted_as=row["interpreted_as"],
        created_type=row["created_type"],
        created_at=ensure_datetime(row["created_at"]),
    )
