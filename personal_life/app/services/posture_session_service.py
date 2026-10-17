"""Core-side storage of privacy-preserving posture sessions and state changes."""

from __future__ import annotations

import logging
import os
from datetime import datetime

from ..storage.database import execute, fetch_all, fetch_one
from .event_bus_service import publish_event


logger = logging.getLogger("gyuos.posture_session")
VALID_STATES = {"NORMAL", "WARNING", "BAD", "NOT_DETECTED"}


def start_posture_session(payload: dict) -> dict:
    session_id = payload["session_id"]
    timestamp = _iso(payload["timestamp"])
    source = payload["source"]
    initial_state = _state(payload["initial_state"])
    _close_stale_sessions(source, timestamp, except_session_id=session_id)

    existing = fetch_one("SELECT session_id, status FROM posture_sessions WHERE session_id = ?", (session_id,))
    if existing:
        return {"session_id": session_id, "started": False, "status": existing["status"]}

    execute(
        """
        INSERT INTO posture_sessions
            (session_id, source, status, started_at, last_observed_at, current_state, current_state_started_at, updated_at)
        VALUES (?, ?, 'active', ?, ?, ?, ?, ?)
        """,
        (session_id, source, timestamp, timestamp, initial_state, timestamp, timestamp),
    )
    logger.info("Posture session started: %s source=%s state=%s", session_id, source, initial_state)
    publish_event("posture.session_started", message="Posture session started", payload={"session_id": session_id, "source": source})
    return {"session_id": session_id, "started": True, "status": "active"}


def record_posture_state_change(payload: dict) -> dict:
    session = _active_session(payload["session_id"])
    occurred_at = _iso(payload["timestamp"])
    requested_previous = _state(payload["previous_state"])
    current_state = _state(payload["current_state"])
    actual_previous = _state(session["current_state"])
    if requested_previous != actual_previous:
        logger.warning("Posture state mismatch for %s: client=%s server=%s", session["session_id"], requested_previous, actual_previous)
    if actual_previous == current_state:
        return {"recorded": False, "reason": "unchanged", "session_id": session["session_id"]}

    previous_duration = max(0.0, _seconds_between(session["current_state_started_at"], occurred_at))
    score = float(payload["score"])
    _add_state_duration(session, actual_previous, previous_duration)
    execute(
        """
        INSERT INTO posture_state_events
            (session_id, occurred_at, previous_state, current_state, previous_state_duration_seconds, posture_score, trigger_type)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (session["session_id"], occurred_at, actual_previous, current_state, previous_duration, score, payload["trigger_type"]),
    )
    _update_session_state(session["session_id"], current_state, occurred_at)
    _mark_recovery_if_applicable(session["session_id"], current_state, occurred_at)
    logger.info("Posture state changed: %s %s->%s duration=%.1fs", session["session_id"], actual_previous, current_state, previous_duration)
    publish_event(
        "posture.state_changed",
        message="Posture state changed",
        payload={"session_id": session["session_id"], "previous_state": actual_previous, "current_state": current_state, "duration_seconds": previous_duration},
    )
    return {"recorded": True, "session_id": session["session_id"], "previous_duration_seconds": round(previous_duration, 2)}


def end_posture_session(payload: dict) -> dict:
    session = _active_session(payload["session_id"], required=False)
    if not session:
        return {"session_id": payload["session_id"], "ended": False, "reason": "not_active"}
    ended_at = _iso(payload["timestamp"])
    _finalize_session(session, ended_at, payload["reason"])
    return {"session_id": session["session_id"], "ended": True, "status": payload["reason"]}


def record_posture_warning(session_id: str | None, warning_event_id: int, warning_at: datetime) -> None:
    """Associate the existing TTS warning record with a session when available."""
    if not session_id:
        return
    session = _active_session(session_id, required=False)
    if not session:
        logger.warning("Posture warning %s has no active session %s", warning_event_id, session_id)
        return
    timestamp = _iso(warning_at)
    elapsed = max(0.0, _seconds_between(session["started_at"], timestamp))
    execute(
        """
        INSERT INTO posture_warning_recoveries (session_id, warning_event_id, warning_at, status, updated_at)
        VALUES (?, ?, ?, 'pending', ?)
        """,
        (session_id, warning_event_id, timestamp, timestamp),
    )
    execute(
        """
        UPDATE posture_sessions
        SET warning_count = warning_count + 1,
            first_warning_at = COALESCE(first_warning_at, ?),
            time_to_first_warning_seconds = COALESCE(time_to_first_warning_seconds, ?),
            updated_at = ?
        WHERE session_id = ?
        """,
        (timestamp, elapsed, timestamp, session_id),
    )
    logger.info("Posture warning recorded: session=%s warning=%s", session_id, warning_event_id)


def list_posture_sessions(*, limit: int = 50, include_active: bool = False) -> list[dict]:
    query = "SELECT * FROM posture_sessions"
    if not include_active:
        query += " WHERE status != 'active'"
    query += " ORDER BY started_at DESC LIMIT ?"
    return [_public_session(row) for row in fetch_all(query, (max(1, min(limit, 200)),))]


def get_posture_session(session_id: str) -> dict | None:
    session = fetch_one("SELECT * FROM posture_sessions WHERE session_id = ?", (session_id,))
    if not session:
        return None
    events = fetch_all(
        "SELECT occurred_at, previous_state, current_state, previous_state_duration_seconds, posture_score, trigger_type FROM posture_state_events WHERE session_id = ? ORDER BY occurred_at",
        (session_id,),
    )
    recoveries = fetch_all(
        "SELECT warning_event_id, warning_at, recovery_at, recovery_seconds, recovery_success, status FROM posture_warning_recoveries WHERE session_id = ? ORDER BY warning_at",
        (session_id,),
    )
    return {"session": _public_session(session), "state_events": events, "warning_recoveries": recoveries}


def _close_stale_sessions(source: str, now: str, *, except_session_id: str) -> None:
    stale = fetch_all("SELECT * FROM posture_sessions WHERE source = ? AND status = 'active' AND session_id != ?", (source, except_session_id))
    for session in stale:
        _finalize_session(session, str(session["last_observed_at"]), "interrupted")


def _finalize_session(session: dict, ended_at: str, reason: str) -> None:
    state = _state(session["current_state"])
    duration = max(0.0, _seconds_between(session["current_state_started_at"], ended_at))
    _add_state_duration(session, state, duration)
    execute(
        """
        INSERT INTO posture_state_events
            (session_id, occurred_at, previous_state, current_state, previous_state_duration_seconds, posture_score, trigger_type)
        VALUES (?, ?, ?, 'NOT_DETECTED', ?, 0, 'session_end')
        """,
        (session["session_id"], ended_at, state, duration),
    )
    _mark_pending_recoveries_no_recovery(session["session_id"], ended_at)
    execute(
        """
        UPDATE posture_sessions
        SET status = ?, ended_at = ?, last_observed_at = ?, current_state = 'NOT_DETECTED',
            current_state_started_at = ?, updated_at = ?
        WHERE session_id = ?
        """,
        (reason, ended_at, ended_at, ended_at, ended_at, session["session_id"]),
    )
    logger.info("Posture session ended: %s reason=%s", session["session_id"], reason)
    publish_event("posture.session_ended", message="Posture session ended", payload={"session_id": session["session_id"], "reason": reason})


def _add_state_duration(session: dict, state: str, seconds: float) -> None:
    valid_increment = seconds if state in {"NORMAL", "WARNING", "BAD"} else 0.0
    normal = seconds if state == "NORMAL" else 0.0
    warning = seconds if state == "WARNING" else 0.0
    bad = seconds if state == "BAD" else 0.0
    first_bad_at = session["current_state_started_at"] if state == "BAD" else None
    first_bad_elapsed = _seconds_between(session["started_at"], session["current_state_started_at"]) if state == "BAD" else None
    execute(
        """
        UPDATE posture_sessions
        SET normal_duration_seconds = normal_duration_seconds + ?,
            warning_duration_seconds = warning_duration_seconds + ?,
            bad_duration_seconds = bad_duration_seconds + ?,
            valid_duration_seconds = valid_duration_seconds + ?,
            longest_bad_duration_seconds = CASE WHEN ? > longest_bad_duration_seconds THEN ? ELSE longest_bad_duration_seconds END,
            first_bad_at = COALESCE(first_bad_at, ?),
            time_to_first_bad_seconds = COALESCE(time_to_first_bad_seconds, ?),
            bad_event_count = bad_event_count + ?,
            updated_at = ?
        WHERE session_id = ?
        """,
        (normal, warning, bad, valid_increment, bad, bad, first_bad_at, first_bad_elapsed, int(state == "BAD"), session["last_observed_at"], session["session_id"]),
    )


def _update_session_state(session_id: str, state: str, occurred_at: str) -> None:
    execute(
        "UPDATE posture_sessions SET current_state = ?, current_state_started_at = ?, last_observed_at = ?, updated_at = ? WHERE session_id = ?",
        (state, occurred_at, occurred_at, occurred_at, session_id),
    )


def _mark_recovery_if_applicable(session_id: str, current_state: str, occurred_at: str) -> None:
    if current_state != "NORMAL":
        return
    pending = fetch_all("SELECT * FROM posture_warning_recoveries WHERE session_id = ? AND status = 'pending'", (session_id,))
    window = max(1, int(os.getenv("GYUVIS_POSTURE_RECOVERY_WINDOW_SECONDS", "120")))
    for row in pending:
        seconds = max(0.0, _seconds_between(row["warning_at"], occurred_at))
        if seconds <= window:
            execute(
                "UPDATE posture_warning_recoveries SET recovery_at = ?, recovery_seconds = ?, recovery_success = 1, status = 'recovered', updated_at = ? WHERE id = ?",
                (occurred_at, seconds, occurred_at, row["id"]),
            )
            execute(
                """
                UPDATE posture_sessions
                SET recovery_count = recovery_count + 1, recovery_total_seconds = recovery_total_seconds + ?,
                    avg_recovery_seconds = (recovery_total_seconds + ?) / (recovery_count + 1), updated_at = ?
                WHERE session_id = ?
                """,
                (seconds, seconds, occurred_at, session_id),
            )
            logger.info("Posture recovery detected: session=%s seconds=%.1f", session_id, seconds)
        else:
            execute("UPDATE posture_warning_recoveries SET status = 'no_recovery', updated_at = ? WHERE id = ?", (occurred_at, row["id"]))


def _mark_pending_recoveries_no_recovery(session_id: str, ended_at: str) -> None:
    execute("UPDATE posture_warning_recoveries SET status = 'no_recovery', updated_at = ? WHERE session_id = ? AND status = 'pending'", (ended_at, session_id))


def _active_session(session_id: str, *, required: bool = True) -> dict | None:
    session = fetch_one("SELECT * FROM posture_sessions WHERE session_id = ? AND status = 'active'", (session_id,))
    if not session and required:
        raise ValueError("Active posture session was not found")
    return session


def _public_session(row: dict) -> dict:
    return {
        key: row.get(key)
        for key in (
            "session_id", "source", "status", "started_at", "ended_at", "last_observed_at", "first_warning_at", "first_bad_at",
            "time_to_first_warning_seconds", "time_to_first_bad_seconds", "normal_duration_seconds", "warning_duration_seconds",
            "bad_duration_seconds", "valid_duration_seconds", "warning_count", "bad_event_count", "recovery_count",
            "longest_bad_duration_seconds", "avg_recovery_seconds", "created_at", "updated_at",
        )
    }


def _state(value: object) -> str:
    state = str(value).upper()
    if state not in VALID_STATES:
        raise ValueError(f"Unsupported posture state: {state}")
    return state


def _iso(value: object) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.astimezone()
        return value.isoformat()
    return str(value)


def _seconds_between(start: object, end: object) -> float:
    return max(0.0, (datetime.fromisoformat(str(end)) - datetime.fromisoformat(str(start))).total_seconds())
