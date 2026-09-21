from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime

from .config import PostureSettings


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WarningSendResult:
    sent: bool
    accepted: bool
    duplicate: bool
    status_code: int | None


class GyuvisPostureClient:
    def __init__(self, settings: PostureSettings) -> None:
        if not settings.api_token:
            raise RuntimeError("posture_alert/.env에 POSTURE_API_TOKEN을 설정해야 합니다.")
        self._url = settings.api_url
        self._token = settings.api_token
        self._timeout_seconds = settings.api_timeout_seconds
        self._settings = settings

    def send_warning(self, posture_type: str, duration_seconds: float, score: float, *, session_id: str | None = None) -> WarningSendResult:
        payload = {
            "type": posture_type,
            "duration_seconds": round(duration_seconds, 1),
            "score": round(min(1.0, max(0.0, score)), 3),
            "timestamp": datetime.now().astimezone().isoformat(),
        }
        if session_id:
            payload["session_id"] = session_id
        body = self._post(self._url, payload, timeout=self._timeout_seconds)
        if body is None:
            return WarningSendResult(False, False, False, None)
        accepted = bool(body.get("accepted"))
        duplicate = bool(body.get("duplicate"))
        logger.info("자세 경고 API 응답: 승인=%s 중복=%s", accepted, duplicate)
        return WarningSendResult(True, accepted, duplicate, 200)

    def start_session(self, session_id: str, source: str, initial_state: str, timestamp: datetime) -> bool:
        return self._post_analytics("/posture-session/start", {"session_id": session_id, "source": source, "initial_state": initial_state, "timestamp": timestamp.isoformat()}) is not None

    def send_state_change(self, session_id: str, previous_state: str, current_state: str, score: float, timestamp: datetime, trigger_type: str) -> bool:
        return self._post_analytics(
            "/posture-state",
            {"session_id": session_id, "previous_state": previous_state, "current_state": current_state, "score": round(min(1.0, max(0.0, score)), 3), "timestamp": timestamp.isoformat(), "trigger_type": trigger_type},
        ) is not None

    def end_session(self, session_id: str, timestamp: datetime, reason: str) -> bool:
        return self._post_analytics("/posture-session/end", {"session_id": session_id, "timestamp": timestamp.isoformat(), "reason": reason}) is not None

    def _post_analytics(self, suffix: str, payload: dict) -> dict | None:
        base = self._url.rsplit("/posture-warning", 1)[0]
        return self._post(base + suffix, payload, timeout=self._settings.analytics_timeout_seconds)

    def _post(self, url: str, payload: dict, *, timeout: float) -> dict | None:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "X-API-Token": self._token},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
                return body
        except urllib.error.HTTPError as error:
            logger.warning("Core 자세 API가 요청을 거부했습니다: HTTP %s", error.code)
            return None
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            logger.warning("Core에 자세 데이터를 전송하지 못했습니다: %s", error)
            return None
