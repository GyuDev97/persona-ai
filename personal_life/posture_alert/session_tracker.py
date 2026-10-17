"""Local session lifecycle and debounced analytics state transitions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from .config import PostureSettings
from .posture_analyzer import PostureAssessment


@dataclass(frozen=True)
class SessionAction:
    kind: str
    session_id: str
    timestamp: datetime
    state: str | None = None
    previous_state: str | None = None
    score: float = 0.0
    reason: str | None = None


class PostureSessionTracker:
    """Keeps analytics state separate from the real-time TTS/BAD timer."""

    def __init__(self, settings: PostureSettings) -> None:
        self._settings = settings
        self._session_id: str | None = None
        self._visible_since: float | None = None
        self._missing_since: float | None = None
        self._reported_state: str | None = None
        self._candidate_state: str | None = None
        self._candidate_since: float | None = None

    @property
    def session_id(self) -> str | None:
        return self._session_id

    def observe(self, assessment: PostureAssessment, monotonic_now: float, wall_now: datetime) -> list[SessionAction]:
        state = assessment.state
        actions: list[SessionAction] = []
        if state == "NOT_DETECTED":
            self._visible_since = None
            if self._missing_since is None:
                self._missing_since = monotonic_now
            if self._session_id and monotonic_now - self._missing_since >= self._settings.session_end_absence_seconds:
                actions.extend(self._end(wall_now, "absence"))
            elif self._session_id:
                actions.extend(self._stabilize(state, assessment.score, monotonic_now, wall_now))
            return actions

        self._missing_since = None
        if self._visible_since is None:
            self._visible_since = monotonic_now
        if not self._session_id and monotonic_now - self._visible_since >= self._settings.session_start_detection_seconds:
            self._session_id = uuid.uuid4().hex
            self._reported_state = state
            self._candidate_state = state
            self._candidate_since = monotonic_now
            actions.append(SessionAction("start", self._session_id, wall_now, state=state, score=assessment.score))
            return actions
        if self._session_id:
            actions.extend(self._stabilize(state, assessment.score, monotonic_now, wall_now))
        return actions

    def stop(self, wall_now: datetime) -> list[SessionAction]:
        return self._end(wall_now, "monitor_stopped") if self._session_id else []

    def _stabilize(self, state: str, score: float, now: float, wall_now: datetime) -> list[SessionAction]:
        if state == self._reported_state:
            self._candidate_state = state
            self._candidate_since = now
            return []
        if state != self._candidate_state:
            self._candidate_state = state
            self._candidate_since = now
            return []
        if self._candidate_since is None or now - self._candidate_since < self._settings.state_debounce_seconds:
            return []
        previous = self._reported_state or "NORMAL"
        self._reported_state = state
        occurred_at = wall_now - timedelta(seconds=now - self._candidate_since)
        return [SessionAction("state_change", self._session_id or "", occurred_at, state=state, previous_state=previous, score=score)]

    def _end(self, wall_now: datetime, reason: str) -> list[SessionAction]:
        session_id = self._session_id
        self._session_id = None
        self._reported_state = None
        self._candidate_state = None
        self._candidate_since = None
        self._missing_since = None
        self._visible_since = None
        return [SessionAction("end", session_id or "", wall_now, reason=reason)]
