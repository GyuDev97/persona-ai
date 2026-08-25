"""TrailGo riding-event interpretation without server-side audio playback."""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from ..config import get_settings
from ..storage.database import execute, fetch_all, fetch_one


# Uvicorn's error logger has an INFO handler in the existing startup commands,
# so these operational records are visible in the API server console.
logger = logging.getLogger("uvicorn.error.gyuos.riding_events")
_cooldown_lock = threading.Lock()

Priority = Literal["critical", "high", "normal", "low"]

# Keep these policy keys distinct from source event names: an event can later
# gain multiple coaching policies without changing the TrailGo contract.
COOLDOWN_BY_POLICY = {
    "LONG_CLIMB_REST": 10,
    "PACE_DROP": 10,
    "FAST_DESCENT": 60,
    "DANGER_APPROACH": 45,
    "RIDE_MILESTONE": 10,
}
LEGACY_RIDE_ID = "__legacy__"
COACHING_EVENT_TYPES = frozenset({"LONG_CLIMB_STARTED", "PACE_DROPPED", "RIDE_MILESTONE"})
SESSION_HISTORY_LIMIT = 5

# Persist and log only known, non-location measurements. Unknown future
# context remains usable during this request, but is not retained by GYUVIS.
STORED_CONTEXT_FIELDS = {
    "current_speed",
    "current_altitude",
    "avg_speed_1m",
    "avg_speed_5m",
    "avg_speed_10m",
    "climb_duration_sec",
    "descent_duration_sec",
    "elevation_gain",
    "total_elevation_gain",
    "ride_distance",
    "ride_duration_sec",
    "ride_state",
    "estimated_grade",
    "nearest_danger_distance",
    "danger_id",
}


@dataclass(frozen=True)
class RuleDecision:
    policy_key: str
    should_consider_speaking: bool
    priority: Priority
    message: str | None
    ai_eligible: bool
    result: str


def is_valid_riding_api_token(provided_token: str | None) -> bool:
    expected_token = os.getenv("GYUVIS_RIDING_API_TOKEN", "").strip()
    return bool(expected_token and provided_token and secrets.compare_digest(provided_token, expected_token))


def handle_riding_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Return text for TrailGo Android TTS; never play audio on the server."""
    started = time.perf_counter()
    event_type = str(payload["event_type"])
    ride_id = _cooldown_ride_id(payload.get("ride_id"))
    context = dict(payload.get("ride_context") or {})
    stored_context = _stored_context(context)
    request_timestamp = _timestamp_text(payload["timestamp"])
    logger.info(
        "riding_request event_type=%s ride_id=%s event_id=%s timestamp=%s ride_context=%s",
        event_type,
        ride_id,
        payload.get("event_id"),
        request_timestamp,
        stored_context,
    )
    decision = _evaluate_rules(event_type, context)
    policy_cooldown = COOLDOWN_BY_POLICY[decision.policy_key]
    ai_called = False
    ai_result = "not_needed"

    with _cooldown_lock:
        if decision.should_consider_speaking and _is_in_cooldown(ride_id, decision.policy_key, policy_cooldown):
            response = _silent_response()
            ai_result = "cooldown"
        elif not decision.should_consider_speaking:
            response = _silent_response()
        else:
            response, ai_called, ai_result = _build_response(
                decision,
                event_type,
                context,
                ride_id,
                policy_cooldown,
            )

        processing_ms = int((time.perf_counter() - started) * 1000)
        _record_event(
            payload=payload,
            stored_context=stored_context,
            decision=decision,
            response=response,
            ai_called=ai_called,
            ai_result=ai_result,
            policy_cooldown=policy_cooldown,
            processing_ms=processing_ms,
        )

    logger.info(
        "riding_analysis event_type=%s rule=%s ai_called=%s ai_result=%s speak=%s priority=%s cooldown=%s processing_ms=%s",
        event_type,
        decision.result,
        ai_called,
        ai_result,
        response["speak"],
        response["priority"],
        response["cooldown_sec"],
        processing_ms,
    )
    logger.info("riding_response status=200 event_type=%s", event_type)
    return response


def _evaluate_rules(event_type: str, context: dict[str, Any]) -> RuleDecision:
    if event_type == "LONG_CLIMB_STARTED":
        if _has_long_climb_context(context):
            return RuleDecision(
                "LONG_CLIMB_REST",
                True,
                "normal",
                None,
                True,
                _long_climb_result(context),
            )
        return RuleDecision("LONG_CLIMB_REST", False, "low", None, False, "long_climb_context_insufficient")

    if event_type == "PACE_DROPPED":
        # The source event alone is not enough: leave momentary flat-road
        # slowdowns silent, but let the AI assess a meaningful uphill trend.
        pace_declining = _pace_is_dropping(context, first_to_second=0.97, second_to_third=0.97)
        if pace_declining and _is_uphill_effort_context(context):
            return RuleDecision("PACE_DROP", True, "normal", None, True, "uphill_pace_change")
        return RuleDecision("PACE_DROP", False, "low", None, False, "pace_drop_not_actionable")

    if event_type == "FAST_DESCENT":
        speed = _number(context.get("current_speed"))
        if speed is not None and speed >= 55:
            return RuleDecision("FAST_DESCENT", True, "critical", "매우 빠른 내리막 구간입니다. 속도를 줄이고 전방을 주의하세요.", False, "fast_descent_critical")
        if speed is not None and speed >= 45:
            return RuleDecision("FAST_DESCENT", True, "high", "빠른 내리막 구간입니다. 속도를 조절하고 전방을 주의하세요.", False, "fast_descent_high")
        return RuleDecision("FAST_DESCENT", False, "low", None, False, "fast_descent_below_threshold")

    if event_type == "DANGER_APPROACH":
        distance = _number(context.get("nearest_danger_distance"))
        speed = _number(context.get("current_speed"))
        # TrailGo already gives its standard proximity notice. GYUVIS only
        # adds a warning for the higher-risk combination, not for proximity alone.
        if distance is not None and distance <= 100 and speed is not None and speed >= 40 and _is_descending_context(context):
            return RuleDecision("DANGER_APPROACH", True, "critical", "가까운 위험 구간으로 빠르게 내려가고 있습니다. 속도를 줄이고 전방을 보세요.", False, "danger_high_speed_descent")
        return RuleDecision("DANGER_APPROACH", False, "low", None, False, "danger_covered_by_trailgo")

    # TrailGo identifies the milestone; the AI decides whether it is worth
    # interrupting the rider and what coaching, if any, fits this ride.
    distance = _number(context.get("ride_distance"))
    if distance is not None and distance >= 1_000:
        return RuleDecision("RIDE_MILESTONE", True, "normal", None, True, "ride_milestone_context_available")
    return RuleDecision("RIDE_MILESTONE", False, "low", None, False, "milestone_distance_missing")


def _build_response(
    decision: RuleDecision,
    event_type: str,
    context: dict[str, Any],
    ride_id: str,
    policy_cooldown: int,
) -> tuple[dict[str, Any], bool, str]:
    if event_type in COACHING_EVENT_TYPES and decision.ai_eligible:
        ai_decision = _call_riding_ai(event_type, context, decision, _recent_session_context(ride_id))
        if ai_decision is not None:
            if not ai_decision["speak"]:
                return _silent_response(), True, "suppressed"
            message = ai_decision.get("message")
            if message:
                return _speak_response(message, decision.priority, policy_cooldown), True, "accepted"
            return _silent_response(), True, "invalid_silent"
        # Coaching must not fall back to a repeated, event-specific sentence.
        return _silent_response(), True, "coaching_ai_unavailable"

    if decision.message:
        return _speak_response(decision.message, decision.priority, policy_cooldown), False, "rule_only"
    return _silent_response(), False, "rule_silent"


def _call_riding_ai(
    event_type: str,
    context: dict[str, Any],
    decision: RuleDecision,
    session_context: dict[str, Any],
) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.has_openai:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None

    # Do not send arbitrary extra context: it could include GPS information in
    # a future TrailGo release. The AI receives the known measurements plus a
    # small, non-location session history to avoid repeated coaching topics.
    prompt_context = _stored_context(context)
    prompt = (
        "You are GYUVIS, an AI Riding Coach riding alongside the cyclist. Return JSON only, without markdown.\n"
        "First decide whether saying anything now is genuinely useful. Silence is preferred when the context has no new coaching value.\n"
        "Use the event, all provided ride measurements, and recent coaching together; do not treat an event name as a fixed action or fixed script.\n"
        "You may encourage a stable rhythm or recognize a meaningful ride milestone when useful, but do not overpraise.\n"
        "Never diagnose or assert dehydration, fatigue, fitness, or another body state not measured by the data. Phrase unmeasured conditions as optional suggestions only.\n"
        "Do not repeat the same advice or topic from recent coaching. If there is no materially new value, set speak to false.\n"
        "If speaking, write one or two short natural Korean TTS sentences. Avoid long explanations, lists, more than two numbers, unsupported hazards, and exaggerated cheering.\n"
        "Output exactly: {\"speak\": boolean, \"message\": string|null}.\n"
        f"Event type: {event_type}\n"
        f"Rule result: {decision.result}\n"
        f"Riding context: {json.dumps(prompt_context, ensure_ascii=False)}\n"
        f"Recent ride session: {json.dumps(session_context, ensure_ascii=False)}"
    )
    try:
        client = OpenAI(api_key=settings.openai_api_key, timeout=10)
        response = client.responses.create(
            model=settings.openai_model,
            input=[{"role": "system", "content": [{"type": "input_text", "text": prompt}]}],
        )
        raw = (getattr(response, "output_text", "") or "").strip()
        data = json.loads(_strip_code_fence(raw))
        if not isinstance(data, dict) or not isinstance(data.get("speak"), bool):
            return None
        message = data.get("message")
        if message is not None and not isinstance(message, str):
            return None
        if message is not None:
            message = " ".join(message.split())[:180]
        return {"speak": data["speak"], "message": message}
    except Exception:
        # Do not emit provider exception details: they can include request or
        # account metadata that is not useful for riding-event tuning.
        logger.warning("Riding AI decision failed; silencing coaching event")
        return None


def _is_in_cooldown(ride_id: str, policy_key: str, cooldown_seconds: int) -> bool:
    cutoff = (datetime.now() - timedelta(seconds=cooldown_seconds)).replace(microsecond=0).isoformat(sep=" ")
    return fetch_one(
        "SELECT id FROM riding_events WHERE ride_id = ? AND policy_key = ? AND speak = 1 AND created_at >= ? ORDER BY id DESC LIMIT 1",
        (ride_id, policy_key, cutoff),
    ) is not None


def _record_event(
    *,
    payload: dict[str, Any],
    stored_context: dict[str, Any],
    decision: RuleDecision,
    response: dict[str, Any],
    ai_called: bool,
    ai_result: str,
    policy_cooldown: int,
    processing_ms: int,
) -> None:
    timestamp_text = _timestamp_text(payload["timestamp"])
    execute(
        """
        INSERT INTO riding_events
            (ride_id, event_id, event_type, policy_key, sensor_timestamp, rule_result, ai_called, ai_result,
             speak, message_text, priority, cooldown_sec, processing_ms, context_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _cooldown_ride_id(payload.get("ride_id")),
            payload.get("event_id"),
            str(payload["event_type"]),
            decision.policy_key,
            timestamp_text,
            decision.result,
            int(ai_called),
            ai_result,
            int(response["speak"]),
            response["message"],
            response["priority"],
            policy_cooldown,
            processing_ms,
            json.dumps(stored_context, ensure_ascii=False, default=str),
        ),
    )


def _stored_context(context: dict[str, Any]) -> dict[str, Any]:
    return {key: context[key] for key in STORED_CONTEXT_FIELDS if key in context and context[key] is not None}


def _recent_session_context(ride_id: str) -> dict[str, Any]:
    """Return a small chronological history for coaching de-duplication."""
    # Legacy clients do not identify a session, so do not mix unrelated rides.
    if ride_id == LEGACY_RIDE_ID:
        return {"recent_events": [], "recent_coaching": [], "last_coaching_at": None}

    rows = fetch_all(
        """
        SELECT event_type, sensor_timestamp, speak, message_text, created_at
        FROM riding_events
        WHERE ride_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (ride_id, SESSION_HISTORY_LIMIT),
    )
    rows.reverse()
    recent_events = [
        {
            "event_type": str(row["event_type"]),
            "timestamp": str(row["sensor_timestamp"]),
            "spoke": bool(row["speak"]),
        }
        for row in rows
    ]
    recent_coaching = [
        {"timestamp": str(row["created_at"]), "message": str(row["message_text"])}
        for row in rows
        if bool(row["speak"]) and row.get("message_text")
    ]
    last_coaching_at = recent_coaching[-1]["timestamp"] if recent_coaching else None
    return {
        "recent_events": recent_events,
        "recent_coaching": recent_coaching[-3:],
        "last_coaching_at": last_coaching_at,
    }


def _timestamp_text(timestamp: Any) -> str:
    return timestamp.isoformat() if isinstance(timestamp, datetime) else str(timestamp)


def _pace_is_dropping(context: dict[str, Any], *, first_to_second: float, second_to_third: float) -> bool:
    one = _number(context.get("avg_speed_1m"))
    five = _number(context.get("avg_speed_5m"))
    ten = _number(context.get("avg_speed_10m"))
    return bool(
        one is not None
        and five is not None
        and ten is not None
        and one <= five * first_to_second
        and five <= ten * second_to_third
    )


def _has_long_climb_context(context: dict[str, Any]) -> bool:
    # TrailGo's source event is meaningful, but require enough observed climb
    # data before spending an AI call. This does not infer rider fatigue.
    return _at_least(context.get("climb_duration_sec"), 300) and _at_least(context.get("elevation_gain"), 30)


def _long_climb_result(context: dict[str, Any]) -> str:
    pace_dropping = _pace_is_dropping(context, first_to_second=0.97, second_to_third=0.97)
    if pace_dropping and _current_speed_supports_drop(context):
        return "long_climb_with_declining_pace"
    if _at_least(context.get("estimated_grade"), 4):
        return "long_steep_climb_with_stable_or_inconclusive_pace"
    return "long_climb_with_stable_or_inconclusive_pace"


def _current_speed_supports_drop(context: dict[str, Any]) -> bool:
    current = _number(context.get("current_speed"))
    one_minute = _number(context.get("avg_speed_1m"))
    return current is None or one_minute is None or current <= one_minute * 1.05


def _is_uphill_effort_context(context: dict[str, Any]) -> bool:
    state = _ride_state(context)
    if state and ("CLIMB" in state or "UPHILL" in state or "ASCENT" in state):
        return True
    # Grade is noisy, so use it with sustained-climb duration rather than as a
    # standalone fatigue signal.
    grade = _number(context.get("estimated_grade"))
    return bool(grade is not None and grade >= 2 and _at_least(context.get("climb_duration_sec"), 180))


def _is_descending_context(context: dict[str, Any]) -> bool:
    state = _ride_state(context)
    if state and ("DESCENT" in state or "DOWNHILL" in state or "DESCENDING" in state):
        return True
    grade = _number(context.get("estimated_grade"))
    return bool(grade is not None and grade <= -3 and _at_least(context.get("descent_duration_sec"), 60))


def _ride_state(context: dict[str, Any]) -> str:
    value = context.get("ride_state")
    return str(value).strip().upper() if value is not None else ""


def _cooldown_ride_id(ride_id: Any) -> str:
    value = str(ride_id).strip() if ride_id is not None else ""
    return value or LEGACY_RIDE_ID


def _long_climb_message(context: dict[str, Any]) -> str:
    minutes = max(1, round((_number(context.get("climb_duration_sec")) or 0) / 60))
    return f"업힐이 {minutes}분째 이어지고 있고 페이스가 떨어지고 있습니다. 잠시 쉬었다 가는 건 어떨까요?"


def _at_least(value: Any, threshold: float) -> bool:
    number = _number(value)
    return number is not None and number >= threshold


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _speak_response(message: str, priority: Priority, cooldown_sec: int) -> dict[str, Any]:
    return {"speak": True, "message": message, "priority": priority, "cooldown_sec": cooldown_sec}


def _silent_response() -> dict[str, Any]:
    return {"speak": False, "message": None, "priority": "low", "cooldown_sec": 0}


def _strip_code_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
    return cleaned.strip()
