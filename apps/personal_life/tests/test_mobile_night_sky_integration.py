import unittest
from unittest.mock import patch

from app.domain.schemas import MobileAssistantCommandCreate, NaturalCommandResponse
from app.services.mobile_assistant_service import process_mobile_assistant_command


class MobileNightSkyIntegrationTests(unittest.TestCase):
    @patch("app.services.mobile_assistant_service.route_intent")
    @patch("app.services.mobile_assistant_service.process_natural_command")
    def test_pc_wake_question_uses_night_sky_before_general_routing(self, natural_command, route_intent):
        natural_command.return_value = NaturalCommandResponse(
            text="오늘 은하수 찍으러 갈 만해?",
            interpreted_as="night_sky",
            summary="오늘 밤은 촬영하기 좋은 편입니다.",
            created_id=0,
            created_type="answer",
        )

        response = process_mobile_assistant_command(
            MobileAssistantCommandCreate(text="오늘 은하수 찍으러 갈 만해?", source="pc-wake")
        )

        self.assertEqual(response.mode, "assistant_reply")
        self.assertEqual(response.summary, "오늘 밤은 촬영하기 좋은 편입니다.")
        natural_command.assert_called_once()
        route_intent.assert_not_called()


if __name__ == "__main__":
    unittest.main()
