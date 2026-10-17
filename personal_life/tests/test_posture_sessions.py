import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

os.environ["DB_BACKEND"] = "sqlite"
os.environ["GYUVIS_POSTURE_API_TOKEN"] = "test-posture-token"
os.environ["GYUVIS_POSTURE_WARNING_COOLDOWN_SECONDS"] = "0"
os.environ["GYUVIS_POSTURE_RECOVERY_WINDOW_SECONDS"] = "120"

from fastapi.testclient import TestClient

from app import create_app
from app.storage import database


class PostureSessionRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database.DATA_DIR = Path(self.temp_dir.name)
        database.SQLITE_DB_PATH = database.DATA_DIR / "test.db"
        self.client = TestClient(create_app())
        self.headers = {"X-API-Token": "test-posture-token"}
        self.started = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=30)
        self.session_id = "posture-session-test-001"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _post(self, path: str, payload: dict):
        response = self.client.post(path, json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_session_summary_records_state_durations_and_recovery(self) -> None:
        self._post(
            "/api/events/posture-session/start",
            {"session_id": self.session_id, "source": "posture_alert", "initial_state": "NORMAL", "timestamp": self.started.isoformat()},
        )
        bad_at = self.started + timedelta(minutes=20)
        self._post(
            "/api/events/posture-state",
            {"session_id": self.session_id, "previous_state": "NORMAL", "current_state": "BAD", "score": 1.0, "timestamp": bad_at.isoformat()},
        )
        warning_at = bad_at + timedelta(seconds=1)
        with patch("app.services.posture_warning_service.speak_gyuvis_text", return_value=True):
            self._post(
                "/api/events/posture-warning",
                {"session_id": self.session_id, "type": "head_down", "duration_seconds": 2.0, "score": 1.0, "timestamp": warning_at.isoformat()},
            )
        recovered_at = bad_at + timedelta(seconds=21)
        self._post(
            "/api/events/posture-state",
            {"session_id": self.session_id, "previous_state": "BAD", "current_state": "NORMAL", "score": 0.2, "timestamp": recovered_at.isoformat()},
        )
        self._post(
            "/api/events/posture-session/end",
            {"session_id": self.session_id, "timestamp": (self.started + timedelta(minutes=30)).isoformat(), "reason": "monitor_stopped"},
        )

        detail = self.client.get(f"/api/posture/sessions/{self.session_id}").json()
        summary = detail["session"]
        self.assertEqual(summary["warning_count"], 1)
        self.assertEqual(summary["bad_event_count"], 1)
        self.assertEqual(summary["recovery_count"], 1)
        self.assertAlmostEqual(summary["time_to_first_bad_seconds"], 1200, places=1)
        self.assertAlmostEqual(summary["bad_duration_seconds"], 21, places=1)
        self.assertAlmostEqual(summary["avg_recovery_seconds"], 20, places=1)
        self.assertGreaterEqual(len(detail["state_events"]), 3)

        stats = self.client.get("/api/posture/stats?days=7").json()
        self.assertEqual(stats["session_count"], 1)
        self.assertEqual(stats["data_status"], "insufficient_data")
        self.assertAlmostEqual(stats["avg_time_to_first_bad_min"], 20, places=1)
        buckets = self.client.get("/api/posture/time-buckets?days=7").json()["buckets"]
        self.assertEqual(buckets[0]["bucket"], "0-30m")
        self.assertGreater(buckets[0]["bad_seconds"], 0)
