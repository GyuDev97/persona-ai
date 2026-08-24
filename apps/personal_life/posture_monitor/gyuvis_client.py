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
            raise RuntimeError("posture_monitor/.env에 POSTURE_API_TOKEN을 설정해야 합니다.")
        self._url = settings.api_url
        self._token = settings.api_token
        self._timeout_seconds = settings.api_timeout_seconds

    def send_warning(self, posture_type: str, duration_seconds: float, score: float) -> WarningSendResult:
        payload = {
            "type": posture_type,
            "duration_seconds": round(duration_seconds, 1),
            "score": round(min(1.0, max(0.0, score)), 3),
            "timestamp": datetime.now().astimezone().isoformat(),
        }
        request = urllib.request.Request(
            self._url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "X-API-Token": self._token},
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
                accepted = bool(body.get("accepted"))
                duplicate = bool(body.get("duplicate"))
                logger.info("자세 경고 API 응답: 상태=%s 승인=%s 중복=%s", response.status, accepted, duplicate)
                return WarningSendResult(True, accepted, duplicate, int(response.status))
        except urllib.error.HTTPError as error:
            logger.warning("Core가 자세 경고를 거부했습니다: HTTP %s", error.code)
            return WarningSendResult(False, False, False, error.code)
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            logger.warning("Core에 자세 경고를 전송하지 못했습니다: %s", error)
            return WarningSendResult(False, False, False, None)
