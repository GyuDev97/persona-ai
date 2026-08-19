from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime

from .config import SensorSettings


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EventSendResult:
    sent: bool
    accepted: bool
    duplicate: bool
    status_code: int | None


class HomeArrivalEventClient:
    def __init__(self, settings: SensorSettings) -> None:
        if not settings.api_url or not settings.api_token:
            raise RuntimeError("API_URL and API_TOKEN must be set in entrance_sensor/.env.")
        self._url = settings.api_url
        self._token = settings.api_token
        self._timeout_seconds = settings.api_timeout_seconds

    def send(self, confidence: float) -> EventSendResult:
        payload = {
            "source": "entrance_camera",
            "event": "home_arrival",
            "person": "owner",
            "confidence": round(float(confidence), 4),
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
                logger.info("Arrival event response: status=%s accepted=%s duplicate=%s", response.status, accepted, duplicate)
                return EventSendResult(True, accepted, duplicate, int(response.status))
        except urllib.error.HTTPError as error:
            logger.warning("Arrival event rejected by Core: HTTP %s", error.code)
            return EventSendResult(False, False, False, error.code)
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            logger.warning("Arrival event could not reach Core: %s", error)
            return EventSendResult(False, False, False, None)
