import os
import sys
import tempfile
import types
import unittest
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

os.environ["DB_BACKEND"] = "sqlite"
os.environ["GYUVIS_RIDING_API_TOKEN"] = "test-riding-token"

# The focused SQLite tests do not exercise MariaDB. Keep them runnable in a
# minimal local environment where the optional MariaDB client is absent.
try:
    import pymysql  # noqa: F401
except ModuleNotFoundError:
    pymysql_stub = types.ModuleType("pymysql")
    pymysql_stub.cursors = types.SimpleNamespace(DictCursor=dict)
    sys.modules["pymysql"] = pymysql_stub

from fastapi import FastAPI, HTTPException
from app.api.routers.events_routes import post_riding_event, router as events_router
from app.domain.schemas import RidingEventCreate
from app.storage import database


class RidingEventRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database.DATA_DIR = Path(self.temp_dir.name)
        database.SQLITE_DB_PATH = database.DATA_DIR / "test.db"
        database.initialize_sqlite()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_long_climb_uses_ai_then_cooldown_without_server_tts(self) -> None:
        payload = self._long_climb_payload()
        with self.assertRaises(HTTPException) as denied:
            self._post(payload)
        self.assertEqual(denied.exception.status_code, 401)

        with patch(
            "app.services.riding_event_service._call_riding_ai",
            return_value={"speak": True, "message": "업힐 페이스가 떨어지고 있습니다. 잠시 쉬었다 가세요."},
        ) as ai_call:
            accepted = self._post(payload, token="test-riding-token")
            duplicate = self._post(payload, token="test-riding-token")

        self.assertEqual(accepted.priority, "normal")
        self.assertTrue(accepted.speak)
        self.assertEqual(accepted.cooldown_sec, 10)
        self.assertFalse(duplicate.speak)
        self.assertEqual(ai_call.call_count, 1)

    def test_route_and_response_contract_are_registered(self) -> None:
        app = FastAPI()
        app.include_router(events_router)
        operation = app.openapi()["paths"]["/api/events/riding"]["post"]
        self.assertEqual(operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"], "#/components/schemas/RidingEventResponse")

    def test_stable_long_climb_is_silent_without_ai_call(self) -> None:
        payload = self._long_climb_payload()
        payload["ride_context"].update({"avg_speed_1m": 6.0, "avg_speed_5m": 6.1, "avg_speed_10m": 6.2})
        with patch("app.services.riding_event_service._call_riding_ai") as ai_call:
            response = self._post(payload, token="test-riding-token")
        self.assertEqual(response.model_dump(), {"speak": False, "message": None, "priority": "low", "cooldown_sec": 0})
        ai_call.assert_not_called()

    def test_danger_event_falls_back_to_rule_without_ai(self) -> None:
        payload = self._long_climb_payload(event_type="DANGER_APPROACH")
        payload["ride_context"]["nearest_danger_distance"] = 80
        with patch("app.services.riding_event_service._call_riding_ai") as ai_call:
            response = self._post(payload, token="test-riding-token")
        self.assertEqual(response.priority, "critical")
        self.assertTrue(response.speak)
        ai_call.assert_not_called()

    def test_context_is_extensible_but_location_is_not_persisted(self) -> None:
        payload = self._long_climb_payload(event_type="FAST_DESCENT")
        payload["ride_context"].update(
            {"gradient": -8.5, "current_state": "DESCENDING", "gps_latitude": 37.5}
        )
        response = self._post(payload, token="test-riding-token")
        self.assertEqual(response.priority, "low")
        self.assertFalse(response.speak)
        stored = database.fetch_one("SELECT context_json FROM riding_events ORDER BY id DESC LIMIT 1")
        self.assertIsNotNone(stored)
        self.assertNotIn("gps_latitude", json.loads(stored["context_json"]))

    def test_logs_sanitized_request_and_200_response_status(self) -> None:
        payload = self._long_climb_payload(event_type="FAST_DESCENT")
        payload["ride_context"]["gps_latitude"] = 37.5
        with self.assertLogs("uvicorn.error.gyuos.riding_events", level="INFO") as logs:
            self._post(payload, token="test-riding-token")
        output = "\n".join(logs.output)
        self.assertIn("riding_request event_type=FAST_DESCENT", output)
        self.assertIn("riding_response status=200 event_type=FAST_DESCENT", output)
        self.assertNotIn("gps_latitude", output)

    @staticmethod
    def _post(payload: dict, token: str | None = None):
        return post_riding_event(
            RidingEventCreate(**payload),
            x_api_token=token,
        )

    def _long_climb_payload(self, event_type: str = "LONG_CLIMB_STARTED") -> dict:
        return {
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "ride_context": {
                "current_speed": 4.2,
                "avg_speed_1m": 4.2,
                "avg_speed_5m": 4.8,
                "avg_speed_10m": 6.3,
                "climb_duration_sec": 720,
                "elevation_gain": 140,
                "ride_distance": 18200,
                "ride_duration_sec": 5400,
            },
        }


if __name__ == "__main__":
    unittest.main()
