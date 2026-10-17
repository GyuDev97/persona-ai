import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

os.environ["DB_BACKEND"] = "sqlite"
os.environ["GYUVIS_HOME_ARRIVAL_API_TOKEN"] = "test-arrival-token"
os.environ["GYUVIS_HOME_ARRIVAL_COOLDOWN_SECONDS"] = "600"

from fastapi.testclient import TestClient

from app import create_app
from app.storage import database
from app.services.jarvis_hud_service import get_jarvis_hud_url


class HomeArrivalRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database.DATA_DIR = Path(self.temp_dir.name)
        database.SQLITE_DB_PATH = database.DATA_DIR / "test.db"
        self.client = TestClient(create_app())
        self.payload = {
            "source": "entrance_camera",
            "event": "home_arrival",
            "person": "owner",
            "confidence": 0.94,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_requires_token_then_deduplicates_a_valid_event(self) -> None:
        denied = self.client.post("/api/events/home-arrival", json=self.payload)
        self.assertEqual(denied.status_code, 401)

        with patch("app.services.home_arrival_service.launch_jarvis_hud", return_value="http://hud"), patch(
            "app.services.home_arrival_service.speak_gyuvis_text", return_value=True
        ):
            accepted = self.client.post(
                "/api/events/home-arrival",
                json=self.payload,
                headers={"X-API-Token": "test-arrival-token"},
            )
            duplicate = self.client.post(
                "/api/events/home-arrival",
                json=self.payload,
                headers={"X-API-Token": "test-arrival-token"},
            )

        self.assertEqual(accepted.status_code, 200)
        self.assertTrue(accepted.json()["accepted"])
        self.assertTrue(accepted.json()["wake_success"])
        self.assertTrue(accepted.json()["tts_success"])
        self.assertEqual(duplicate.status_code, 200)
        self.assertTrue(duplicate.json()["duplicate"])

    def test_arrival_hud_url_bypasses_the_gesture_veil(self) -> None:
        url = get_jarvis_hud_url(immediate=True)
        self.assertIn("boot=ready", url)
        self.assertIn("veil=0", url)
        self.assertIn("autoGesture=0", url)


if __name__ == "__main__":
    unittest.main()
