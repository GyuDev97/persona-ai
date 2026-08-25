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
from ..storage.database import execute, fetch_one


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

# Persist and log only known, non-location measurements. Unknown future
# context remains usable during this request, but is not retained by GYUVIS.
STORED_CONTEXT_FIELDS = {
    "current_speed",
    "avg_speed_1m",
    "avg_speed_5m",
    "avg_speed_10m",
    "climb_duration_sec",
    "elevation_gain",
    "ride_distance",
    "ride_duration_sec",
    "gradient",
    "descent_duration",
    "nearest_danger_distance",
    "curve_distance",
    "curve_severity",
    "current_state",
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
    context = dict(payload.get("ride_context") or {})
    stored_context = _stored_context(context)
    request_timestamp = _timestamp_text(payload["timestamp"])
    logger.info(
        "riding_request event_type=%s timestamp=%s ride_context=%s",
        event_type,
        request_timestamp,
        stored_context,
    )
    decision = _evaluate_rules(event_type, context)
    policy_cooldown = COOLDOWN_BY_POLICY[decision.policy_key]
    ai_called = False
    ai_result = "not_needed"

    with _cooldown_lock:
        if decision.should_consider_speaking and _is_in_cooldown(decision.policy_key, policy_cooldown):
            response = _silent_response()
            ai_result = "cooldown"
        elif not decision.should_consider_speaking:
            response = _silent_response()
        else:
            response, ai_called, ai_result = _build_response(decision, event_type, context, policy_cooldown)

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
        sustained = _at_least(context.get("climb_duration_sec"), 600) and _at_least(context.get("elevation_gain"), 100)
        pace_dropping = _pace_is_dropping(context, first_to_second=0.92, second_to_third=0.92)
        if sustained and pace_dropping:
            return RuleDecision("LONG_CLIMB_REST", True, "normal", _long_climb_message(context), True, "sustained_climb_with_declining_pace")
        return RuleDecision("LONG_CLIMB_REST", False, "low", None, False, "climb_not_actionable")

    if event_type == "PACE_DROPPED":
        if _pace_is_dropping(context, first_to_second=0.85, second_to_third=0.90):
            return RuleDecision("PACE_DROP", True, "normal", "페이스가 평소 흐름보다 떨어지고 있습니다. 호흡과 수분 상태를 잠시 확인해 보세요.", True, "pace_drop_confirmed")
        return RuleDecision("PACE_DROP", False, "low", None, False, "pace_drop_not_confirmed")

    if event_type == "FAST_DESCENT":
        speed = _number(context.get("current_speed"))
        if speed is not None and speed >= 55:
            return RuleDecision("FAST_DESCENT", True, "critical", "매우 빠른 내리막 구간입니다. 속도를 줄이고 전방을 주의하세요.", False, "fast_descent_critical")
        if speed is not None and speed >= 45:
            return RuleDecision("FAST_DESCENT", True, "high", "빠른 내리막 구간입니다. 속도를 조절하고 전방을 주의하세요.", False, "fast_descent_high")
        return RuleDecision("FAST_DESCENT", False, "low", None, False, "fast_descent_below_threshold")

    if event_type == "DANGER_APPROACH":
        distance = _number(context.get("nearest_danger_distance"))
        if distance is not None and 0 <= distance <= 100:
            return RuleDecision("DANGER_APPROACH", True, "critical", "위험 요소가 가까이 있습니다. 감속하고 전방을 주의하세요.", False, "danger_near")
        if distance is not None and distance <= 250:
            return RuleDecision("DANGER_APPROACH", True, "high", "앞쪽 위험 구간에 주의하세요. 속도를 조절해 주세요.", False, "danger_approaching")
        return RuleDecision("DANGER_APPROACH", False, "low", None, False, "danger_distance_not_actionable")

    # TrailGo emits this only when it has already identified a milestone.
    distance = _number(context.get("ride_distance"))
    if distance is not None and distance > 0:
        km = max(1, round(distance / 1000))
        return RuleDecision("RIDE_MILESTONE", True, "normal", f"주행 {km}킬로미터를 달렸습니다. 수분 보충도 챙겨 주세요.", False, "trailgo_milestone")
    return RuleDecision("RIDE_MILESTONE", False, "low", None, False, "milestone_distance_missing")


def _build_response(
    decision: RuleDecision,
    event_type: str,
    context: dict[str, Any],
    policy_cooldown: int,
) -> tuple[dict[str, Any], bool, str]:
    if decision.ai_eligible:
        ai_decision = _call_riding_ai(event_type, context, decision)
        if ai_decision is not None:
            if not ai_decision["speak"]:
                return _silent_response(), True, "suppressed"
            message = ai_decision.get("message") or decision.message
            if message:
                return _speak_response(message, decision.priority, policy_cooldown), True, "accepted"
        # A coaching fallback is intentionally concise and rule-backed.
        if decision.message:
            return _speak_response(decision.message, decision.priority, policy_cooldown), True, "fallback"
        return _silent_response(), True, "fallback_silent"

    return _speak_response(decision.message or "", decision.priority, policy_cooldown), False, "rule_only"


def _call_riding_ai(event_type: str, context: dict[str, Any], decision: RuleDecision) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.has_openai:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None

    # Do not send arbitrary extra context: it could include GPS information in
    # a future TrailGo release. The AI only needs the same numeric inputs as
    # rule evaluation to decide whether a coaching interruption is worthwhile.
    prompt_context = _stored_context(context)
    prompt = (
        "You are GYUVIS Riding Assistant. Return JSON only, without markdown.\n"
        "Decide whether this coaching prompt is worth saying aloud while cycling.\n"
        "Safety is important, but this is not an emergency dispatcher. Do not invent hazards.\n"
        "Avoid frequent or unnecessary interruption. Use one short Korean sentence, easy to understand without looking at a screen.\n"
        "Do not list many numbers, make unsupported claims, chat, or give long explanations.\n"
        "Output exactly: {\"speak\": boolean, \"message\": string|null}.\n"
        f"Event type: {event_type}\n"
        f"Rule result: {decision.result}\n"
        f"Riding context: {json.dumps(prompt_context, ensure_ascii=False)}"
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
        if message is not None:
            message = " ".join(str(message).split())[:180]
        return {"speak": data["speak"], "message": message}
    except Exception:
        # Do not emit provider exception details: they can include request or
        # account metadata that is not useful for riding-event tuning.
        logger.warning("Riding AI decision failed; using rule fallback")
        return None


def _is_in_cooldown(policy_key: str, cooldown_seconds: int) -> bool:
    cutoff = (datetime.now() - timedelta(seconds=cooldown_seconds)).replace(microsecond=0).isoformat(sep=" ")
    return fetch_one(
        "SELECT id FROM riding_events WHERE policy_key = ? AND speak = 1 AND created_at >= ? ORDER BY id DESC LIMIT 1",
        (policy_key, cutoff),
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
            (event_type, policy_key, sensor_timestamp, rule_result, ai_called, ai_result,
             speak, message_text, priority, cooldown_sec, processing_ms, context_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
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
