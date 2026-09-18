import unittest
from unittest.mock import Mock, patch

from pc_wake_listener import GyuvisWakeListener


class WakeOverlayIndependenceTests(unittest.TestCase):
    @patch("pc_wake_listener.launch_jarvis_hud")
    @patch("pc_wake_listener.OPEN_JARVIS_HUD_ON_WAKE", False)
    def test_wake_listener_does_not_open_command_center_by_default(self, launch_hud):
        listener = object.__new__(GyuvisWakeListener)
        listener._last_hud_launch_at = 0.0
        listener._log = Mock()

        listener._launch_hud_if_needed()

        launch_hud.assert_not_called()

    def test_server_backed_followup_gets_an_immediate_investigation_acknowledgement(self):
        listener = object.__new__(GyuvisWakeListener)

        self.assertEqual(
            listener._build_followup_acknowledgement("오늘 은하수 촬영 어때?"),
            "네 보스. 오늘 은하수 촬영 조건을 알아보겠습니다.",
        )
        self.assertEqual(
            listener._build_followup_acknowledgement("오늘 일정 알려줘"),
            "네 보스. 오늘 일정 알아보겠습니다.",
        )
