from dataclasses import replace
import unittest

from posture_monitor.config import get_settings
from posture_monitor.models import PoseMetrics
from posture_monitor.posture_analyzer import PostureAnalyzer, PostureBaseline


class PostureAnalyzerTest(unittest.TestCase):
    def setUp(self) -> None:
        settings = replace(
            get_settings(),
            forward_head_delta=0.20,
            head_down_angle_delta_degrees=20.0,
            warning_ratio=0.65,
            smoothing_alpha=1.0,
        )
        self.analyzer = PostureAnalyzer(PostureBaseline(1.0, 0.0, 20), settings)

    def test_bad_posture_must_persist_and_missing_pose_resets_timer(self) -> None:
        normal = self.analyzer.assess(_metrics(1.0, 0.0), now=0.0)
        warning = self.analyzer.assess(_metrics(1.14, 0.0), now=1.0)
        bad_started = self.analyzer.assess(_metrics(1.24, 0.0), now=2.0)
        bad_sustained = self.analyzer.assess(_metrics(1.24, 0.0), now=14.0)
        missing = self.analyzer.assess(None, now=15.0)

        self.assertEqual(normal.state, "NORMAL")
        self.assertEqual(warning.state, "WARNING")
        self.assertEqual(bad_started.state, "BAD")
        self.assertEqual(bad_started.bad_duration_seconds, 0.0)
        self.assertEqual(bad_sustained.bad_duration_seconds, 12.0)
        self.assertEqual(missing.state, "NOT_DETECTED")
        self.assertEqual(missing.bad_duration_seconds, 0.0)


def _metrics(forward_offset: float, angle: float) -> PoseMetrics:
    return PoseMetrics(forward_offset=forward_offset, nose_ear_angle_degrees=angle)
