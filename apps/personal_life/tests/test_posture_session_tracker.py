from dataclasses import replace
from datetime import datetime, timezone
import unittest

from posture_alert.config import get_settings
from posture_alert.posture_analyzer import PostureAssessment
from posture_alert.session_tracker import PostureSessionTracker


class PostureSessionTrackerTest(unittest.TestCase):
    def test_session_and_state_events_are_stabilized(self) -> None:
        settings = replace(
            get_settings(),
            session_start_detection_seconds=2.0,
            session_end_absence_seconds=10.0,
            state_debounce_seconds=1.5,
        )
        tracker = PostureSessionTracker(settings)
        now = datetime.now(timezone.utc)
        normal = PostureAssessment("NORMAL", None, 0.1, 0)
        bad = PostureAssessment("BAD", "head_down", 1.0, 0)
        missing = PostureAssessment("NOT_DETECTED", None, 0.0, 0)

        self.assertEqual(tracker.observe(normal, 0.0, now), [])
        start = tracker.observe(normal, 2.0, now)
        self.assertEqual(start[0].kind, "start")
        self.assertEqual(start[0].state, "NORMAL")

        self.assertEqual(tracker.observe(bad, 3.0, now), [])
        changed = tracker.observe(bad, 4.5, now)
        self.assertEqual(changed[0].kind, "state_change")
        self.assertEqual(changed[0].previous_state, "NORMAL")
        self.assertEqual(changed[0].state, "BAD")

        self.assertEqual(tracker.observe(missing, 5.0, now), [])
        missing_change = tracker.observe(missing, 6.5, now)
        self.assertEqual(missing_change[0].state, "NOT_DETECTED")
        ended = tracker.observe(missing, 15.0, now)
        self.assertEqual(ended[0].kind, "end")
        self.assertEqual(ended[0].reason, "absence")

