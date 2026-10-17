import unittest
from unittest.mock import patch

from app.services.agent_report_center_service import build_creator_ideas_data


class CreatorIdeasServiceTests(unittest.TestCase):
    @patch("app.services.agent_report_center_service._list_tasks_by_types")
    def test_returns_only_agent4_idea_data(self, list_tasks):
        list_tasks.return_value = [
            {
                "id": 12,
                "task_type": "youtube_idea_research",
                "status": "completed",
                "result_payload": '{"ideas": ["AI phone comparison"]}',
                "completed_at": "2026-09-22 08:00:00",
                "created_at": "2026-09-22 07:59:00",
            }
        ]

        result = build_creator_ideas_data()

        self.assertEqual(result["agent4"]["ideas"][0]["title"], "AI phone comparison")
        self.assertEqual(result["tasks"][0]["task_type"], "youtube_idea_research")
        self.assertNotIn("agent1", result)
        list_tasks.assert_called_once_with(("youtube_idea_research",), limit=8)
