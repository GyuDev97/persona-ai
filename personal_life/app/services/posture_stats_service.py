"""Read-only aggregate statistics for stored posture sessions."""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timedelta

from ..storage.database import fetch_all


BUCKETS: tuple[tuple[str, float, float | None], ...] = (
    ("0-30m", 0, 30 * 60),
    ("30-60m", 30 * 60, 60 * 60),
    ("60-90m", 60 * 60, 90 * 60),
    ("90-120m", 90 * 60, 120 * 60),
    ("120m+", 120 * 60, None),
)
VALID_STATES = {"NORMAL", "WARNING", "BAD"}


def build_posture_stats(days: int) -> dict:
    sessions = _closed_sessions(days)
    total_valid = sum(float(row["valid_duration_seconds"] or 0) for row in sessions)
    first_bad = [float(row["time_to_first_bad_seconds"]) for row in sessions if row["time_to_first_bad_seconds"] is not None]
    ratios = [float(row["bad_duration_seconds"] or 0) / float(row["valid_duration_seconds"]) for row in sessions if float(row["valid_duration_seconds"] or 0) > 0]
    recovery_values = [float(row["avg_recovery_seconds"]) for row in sessions if row["avg_recovery_seconds"] is not None]
    data_status = _data_status(len(sessions), total_valid)
    buckets = build_time_buckets(days, sessions=sessions)
    result = {
        "period_days": days,
        "data_status": data_status,
        "session_count": len(sessions),
        "sessions_with_bad": len(first_bad),
        "total_monitoring_hours": round(total_valid / 3600, 2),
        "avg_time_to_first_bad_min": _minutes_mean(first_bad),
        "median_time_to_first_bad_min": _minutes_median(first_bad),
        "avg_bad_ratio": _mean(ratios),
        "avg_recovery_seconds": _mean(recovery_values),
        "bad_ratio_after_30m": _ratio_after(buckets, 30 * 60),
        "bad_ratio_after_60m": _ratio_after(buckets, 60 * 60),
        "bad_ratio_after_90m": _ratio_after(buckets, 90 * 60),
        "worst_time_range": _worst_time_range(sessions),
        "trend": _trend(sessions, total_valid) if data_status != "insufficient_data" else None,
    }
    return result


def build_time_buckets(days: int, *, sessions: list[dict] | None = None) -> dict:
    sessions = sessions if sessions is not None else _closed_sessions(days)
    totals = {name: {"observed": 0.0, "normal": 0.0, "warning": 0.0, "bad": 0.0, "bad_event_count": 0} for name, _, _ in BUCKETS}
    for session in sessions:
        started = _parse(session["started_at"])
        events = fetch_all(
            "SELECT occurred_at, previous_state, current_state, previous_state_duration_seconds FROM posture_state_events WHERE session_id = ? ORDER BY occurred_at",
            (session["session_id"],),
        )
        for event in events:
            state = str(event["previous_state"])
            duration = float(event["previous_state_duration_seconds"] or 0)
            if duration > 0 and state in VALID_STATES:
                end = _parse(event["occurred_at"])
                _split_interval(totals, started, end - timedelta(seconds=duration), end, state)
            if str(event["current_state"]) == "BAD":
                elapsed = max(0.0, (_parse(event["occurred_at"]) - started).total_seconds())
                bucket = _bucket_for(elapsed)
                totals[bucket]["bad_event_count"] += 1

    rows = []
    for name, start, end in BUCKETS:
        value = totals[name]
        observed = value["observed"]
        rows.append(
            {
                "bucket": name,
                "start_minutes": start / 60,
                "end_minutes": None if end is None else end / 60,
                "observed_seconds": round(observed, 2),
                "bad_seconds": round(value["bad"], 2),
                "warning_seconds": round(value["warning"], 2),
                "bad_ratio": round(value["bad"] / observed, 4) if observed else None,
                "warning_ratio": round(value["warning"] / observed, 4) if observed else None,
                "bad_event_count": value["bad_event_count"],
            }
        )
    return {"period_days": days, "session_count": len(sessions), "buckets": rows}


def _closed_sessions(days: int) -> list[dict]:
    cutoff = (datetime.now().astimezone() - timedelta(days=days)).isoformat()
    return fetch_all(
        "SELECT * FROM posture_sessions WHERE status != 'active' AND started_at >= ? ORDER BY started_at",
        (cutoff,),
    )


def _split_interval(totals: dict, session_started: datetime, start: datetime, end: datetime, state: str) -> None:
    cursor = max(start, session_started)
    while cursor < end:
        elapsed = max(0.0, (cursor - session_started).total_seconds())
        bucket = _bucket_for(elapsed)
        _, _, bucket_end = next(item for item in BUCKETS if item[0] == bucket)
        until = end if bucket_end is None else min(end, session_started + timedelta(seconds=bucket_end))
        seconds = max(0.0, (until - cursor).total_seconds())
        totals[bucket]["observed"] += seconds
        totals[bucket][state.lower()] += seconds
        cursor = until


def _bucket_for(elapsed_seconds: float) -> str:
    for name, start, end in BUCKETS:
        if elapsed_seconds >= start and (end is None or elapsed_seconds < end):
            return name
    return BUCKETS[-1][0]


def _ratio_after(bucket_result: dict, minimum_seconds: float) -> float | None:
    observed = 0.0
    bad = 0.0
    for row in bucket_result["buckets"]:
        if row["start_minutes"] * 60 >= minimum_seconds:
            observed += row["observed_seconds"]
            bad += row["bad_seconds"]
    return round(bad / observed, 4) if observed else None


def _worst_time_range(sessions: list[dict]) -> str | None:
    hours: dict[int, float] = defaultdict(float)
    for session in sessions:
        events = fetch_all(
            "SELECT occurred_at, previous_state, previous_state_duration_seconds FROM posture_state_events WHERE session_id = ? ORDER BY occurred_at",
            (session["session_id"],),
        )
        for event in events:
            if event["previous_state"] != "BAD":
                continue
            end = _parse(event["occurred_at"])
            start = end - timedelta(seconds=float(event["previous_state_duration_seconds"] or 0))
            cursor = start
            while cursor < end:
                next_hour = (cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
                until = min(end, next_hour)
                hours[cursor.hour] += (until - cursor).total_seconds()
                cursor = until
    if not hours:
        return None
    start_hour = max(hours, key=hours.get)
    return f"{start_hour:02d}:00-{(start_hour + 2) % 24:02d}:00"


def _trend(sessions: list[dict], total_valid: float) -> str | None:
    if len(sessions) < 6 or total_valid < 3 * 3600:
        return None
    midpoint = len(sessions) // 2
    earlier = _mean(_session_ratio(item) for item in sessions[:midpoint])
    recent = _mean(_session_ratio(item) for item in sessions[midpoint:])
    if earlier is None or recent is None:
        return None
    if recent <= earlier - 0.03:
        return "improving"
    if recent >= earlier + 0.03:
        return "worsening"
    return "stable"


def _session_ratio(session: dict) -> float:
    valid = float(session["valid_duration_seconds"] or 0)
    return float(session["bad_duration_seconds"] or 0) / valid if valid else 0.0


def _data_status(session_count: int, total_valid_seconds: float) -> str:
    if session_count < 5 or total_valid_seconds < 3 * 3600:
        return "insufficient_data"
    if session_count < 10 or total_valid_seconds < 7 * 3600:
        return "reference_only"
    return "sufficient"


def _parse(value: object) -> datetime:
    return datetime.fromisoformat(str(value))


def _mean(values) -> float | None:
    values = list(values)
    return round(statistics.fmean(values), 4) if values else None


def _minutes_mean(values: list[float]) -> float | None:
    value = _mean(values)
    return round(value / 60, 2) if value is not None else None


def _minutes_median(values: list[float]) -> float | None:
    return round(statistics.median(values) / 60, 2) if values else None
