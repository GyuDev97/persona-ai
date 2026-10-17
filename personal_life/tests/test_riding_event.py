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

    def test_long_climb_uses_ai_then_same_ride_cooldown_without_server_tts(self) -> None:
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

    def test_same_policy_in_a_different_ride_is_not_suppressed(self) -> None:
        first = self._long_climb_payload(ride_id="ride-a")
        second = self._long_climb_payload(ride_id="ride-b")
        with patch(
            "app.services.riding_event_service._call_riding_ai",
            return_value={"speak": True, "message": "업힐 페이스를 확인해 보세요."},
        ) as ai_call:
            self.assertTrue(self._post(first, token="test-riding-token").speak)
            self.assertTrue(self._post(second, token="test-riding-token").speak)
        self.assertEqual(ai_call.call_count, 2)

    def test_route_and_response_contract_are_registered(self) -> None:
        app = FastAPI()
        app.include_router(events_router)
        operation = app.openapi()["paths"]["/api/events/riding"]["post"]
        self.assertEqual(operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"], "#/components/schemas/RidingEventResponse")

    def test_stable_long_climb_can_receive_positive_ai_coaching(self) -> None:
        payload = self._long_climb_payload()
        payload["ride_context"].update({"avg_speed_1m": 6.0, "avg_speed_5m": 6.1, "avg_speed_10m": 6.2})
        with patch(
            "app.services.riding_event_service._call_riding_ai",
            return_value={"speak": True, "message": "오르막이 이어져도 페이스가 안정적입니다. 지금 리듬 좋습니다."},
        ) as ai_call:
            response = self._post(payload, token="test-riding-token")
        self.assertTrue(response.speak)
        self.assertIn("안정적", response.message)
        ai_call.assert_called_once()

    def test_pace_drop_requires_sustained_uphill_context(self) -> None:
        payload = self._long_climb_payload(event_type="PACE_DROPPED", ride_id="pace-uphill")
        payload["ride_context"].update(
            {
                "avg_speed_1m": 3.5,
                "avg_speed_5m": 4.5,
                "avg_speed_10m": 5.2,
                "ride_state": "CLIMB",
                "estimated_grade": 5.5,
            }
        )
        with patch(
            "app.services.riding_event_service._call_riding_ai",
            return_value={"speak": True, "message": "업힐 페이스를 조절해 보세요."},
        ) as ai_call:
            response = self._post(payload, token="test-riding-token")
        self.assertTrue(response.speak)
        ai_call.assert_called_once()

        level_payload = self._long_climb_payload(event_type="PACE_DROPPED", ride_id="pace-level")
        level_payload["ride_context"].update(
            {
                "avg_speed_1m": 3.5,
                "avg_speed_5m": 4.5,
                "avg_speed_10m": 5.2,
                "ride_state": "CRUISING",
                "estimated_grade": 0,
            }
        )
        with patch("app.services.riding_event_service._call_riding_ai") as ai_call:
            response = self._post(level_payload, token="test-riding-token")
        self.assertFalse(response.speak)
        ai_call.assert_not_called()

    def test_danger_event_keeps_deterministic_safety_fallback(self) -> None:
        payload = self._long_climb_payload(event_type="DANGER_APPROACH")
        payload["ride_context"].update(
            {
                "nearest_danger_distance": 80,
                "danger_id": "danger-123",
                "current_speed": 48,
                "ride_state": "DESCENT",
            }
        )
        with patch("app.services.riding_event_service._call_riding_ai", return_value=None) as ai_call:
            response = self._post(payload, token="test-riding-token")
        self.assertEqual(response.priority, "critical")
        self.assertTrue(response.speak)
        self.assertIn("속도를 줄이고", response.message)
        ai_call.assert_not_called()

        low_risk = self._long_climb_payload(event_type="DANGER_APPROACH", ride_id="low-risk")
        low_risk["ride_context"].update({"nearest_danger_distance": 80, "current_speed": 18, "ride_state": "DESCENT"})
        self.assertFalse(self._post(low_risk, token="test-riding-token").speak)

    def test_fast_descent_keeps_deterministic_safety_fallback(self) -> None:
        payload = self._long_climb_payload(event_type="FAST_DESCENT")
        payload["ride_context"]["current_speed"] = 56
        with patch("app.services.riding_event_service._call_riding_ai") as ai_call:
            response = self._post(payload, token="test-riding-token")
        self.assertEqual(response.priority, "critical")
        self.assertTrue(response.speak)
        ai_call.assert_not_called()

    def test_milestone_uses_ai_instead_of_a_fixed_hydration_message(self) -> None:
        payload = self._long_climb_payload(event_type="RIDE_MILESTONE", ride_id="milestone-ride")
        with patch(
            "app.services.riding_event_service._call_riding_ai",
            return_value={"speak": True, "message": "오늘 누적 상승이 꽤 쌓였습니다. 지금 흐름을 이어가 보죠."},
        ) as ai_call:
            response = self._post(payload, token="test-riding-token")
        self.assertTrue(response.speak)
        self.assertNotIn("수분", response.message)
        ai_call.assert_called_once()

    def test_coaching_ai_failure_is_silent_without_fixed_fallback(self) -> None:
        payload = self._long_climb_payload(event_type="PACE_DROPPED", ride_id="ai-failure")
        payload["ride_context"].update(
            {"avg_speed_1m": 3.5, "avg_speed_5m": 4.5, "avg_speed_10m": 5.2, "ride_state": "LONG_CLIMB"}
        )
        with patch("app.services.riding_event_service._call_riding_ai", return_value=None):
            response = self._post(payload, token="test-riding-token")
        self.assertEqual(response.model_dump(), {"speak": False, "message": None, "priority": "low", "cooldown_sec": 0})

    def test_ai_receives_recent_coaching_for_the_same_ride(self) -> None:
        first = self._long_climb_payload(ride_id="session-history")
        second = self._long_climb_payload(event_type="PACE_DROPPED", ride_id="session-history")
        second["ride_context"].update(
            {"avg_speed_1m": 3.5, "avg_speed_5m": 4.5, "avg_speed_10m": 5.2, "ride_state": "LONG_CLIMB"}
        )
        with patch(
            "app.services.riding_event_service._call_riding_ai",
            side_effect=[
                {"speak": True, "message": "오르막 리듬을 천천히 유지해 보세요."},
                {"speak": False, "message": None},
            ],
        ) as ai_call:
            self._post(first, token="test-riding-token")
            self._post(second, token="test-riding-token")
        session_context = ai_call.call_args_list[1].args[3]
        self.assertEqual(session_context["recent_events"][-1]["event_type"], "LONG_CLIMB_STARTED")
        self.assertEqual(session_context["recent_coaching"][-1]["message"], "오르막 리듬을 천천히 유지해 보세요.")

    def test_context_is_extensible_but_location_is_not_persisted(self) -> None:
        payload = self._long_climb_payload(event_type="FAST_DESCENT")
        payload["ride_context"].update(
            {
                "current_altitude": 220,
                "descent_duration_sec": 90,
                "total_elevation_gain": 680,
                "ride_state": "DESCENT",
                "estimated_grade": -8.5,
                "nearest_danger_distance": 120,
                "danger_id": "danger-123",
                "gps_latitude": 37.5,
            }
        )
        response = self._post(payload, token="test-riding-token")
        self.assertEqual(response.priority, "low")
        self.assertFalse(response.speak)
        stored = database.fetch_one("SELECT context_json FROM riding_events ORDER BY id DESC LIMIT 1")
        self.assertIsNotNone(stored)
        stored_context = json.loads(stored["context_json"])
        self.assertNotIn("gps_latitude", stored_context)
        self.assertEqual(stored_context["current_altitude"], 220)
        self.assertEqual(stored_context["ride_state"], "DESCENT")
        self.assertEqual(stored_context["descent_duration_sec"], 90)
        self.assertEqual(stored_context["total_elevation_gain"], 680)
        self.assertEqual(stored_context["estimated_grade"], -8.5)
        self.assertEqual(stored_context["nearest_danger_distance"], 120)
        self.assertEqual(stored_context["danger_id"], "danger-123")
        event = database.fetch_one("SELECT ride_id, event_id FROM riding_events ORDER BY id DESC LIMIT 1")
        self.assertEqual(event, {"ride_id": "ride-default", "event_id": "event-default"})

    def test_identifiers_are_optional_during_trailgo_rollout(self) -> None:
        payload = self._long_climb_payload(event_type="FAST_DESCENT")
        payload.pop("ride_id")
        payload.pop("event_id")
        self._post(payload, token="test-riding-token")
        event = database.fetch_one("SELECT ride_id, event_id FROM riding_events ORDER BY id DESC LIMIT 1")
        self.assertEqual(event, {"ride_id": "__legacy__", "event_id": None})

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

    def _long_climb_payload(
        self,
        event_type: str = "LONG_CLIMB_STARTED",
        ride_id: str = "ride-default",
    ) -> dict:
        return {
            "ride_id": ride_id,
            "event_id": "event-default",
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
