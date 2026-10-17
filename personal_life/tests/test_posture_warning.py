import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

os.environ["DB_BACKEND"] = "sqlite"
os.environ["GYUVIS_POSTURE_API_TOKEN"] = "test-posture-token"
os.environ["GYUVIS_POSTURE_WARNING_COOLDOWN_SECONDS"] = "1500"

from fastapi.testclient import TestClient

from app import create_app
from app.storage import database


class PostureWarningRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database.DATA_DIR = Path(self.temp_dir.name)
        database.SQLITE_DB_PATH = database.DATA_DIR / "test.db"
        self.client = TestClient(create_app())
        self.payload = {
            "type": "head_down",
            "duration_seconds": 12.4,
            "score": 0.82,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_requires_token_then_deduplicates_valid_warning(self) -> None:
        denied = self.client.post("/api/events/posture-warning", json=self.payload)
        self.assertEqual(denied.status_code, 401)

        with patch("app.services.posture_warning_service.speak_gyuvis_text", return_value=True):
            accepted = self.client.post(
                "/api/events/posture-warning",
                json=self.payload,
                headers={"X-API-Token": "test-posture-token"},
            )
            duplicate = self.client.post(
                "/api/events/posture-warning",
                json=self.payload,
                headers={"X-API-Token": "test-posture-token"},
            )

        self.assertEqual(accepted.status_code, 200)
        self.assertTrue(accepted.json()["accepted"])
        self.assertTrue(accepted.json()["tts_success"])
        self.assertEqual(duplicate.status_code, 200)
        self.assertTrue(duplicate.json()["duplicate"])


if __name__ == "__main__":
    unittest.main()
