import json
import unittest
from datetime import datetime
from unittest.mock import patch

from app.services.agent_task_service import _serialize_payload, complete_agent_task, create_agent_task


class AgentTaskSerializationTests(unittest.TestCase):
    def test_datetime_payload_serializes_as_text(self):
        encoded = _serialize_payload({"collected_at": datetime(2026, 9, 18, 21, 4, 37)})

        self.assertEqual(json.loads(encoded)["collected_at"], "2026-09-18 21:04:37")

    @patch("app.services.agent_task_service.get_agent_task")
    @patch("app.services.agent_task_service.execute", return_value=42)
    def test_create_task_accepts_datetime_payload(self, execute, _get_task):
        create_agent_task(command_text="뉴스", task_type="agent1_it_news_window", payload={"observed_at": datetime(2026, 9, 18)})

        self.assertEqual(json.loads(execute.call_args.args[1][-1])["observed_at"], "2026-09-18 00:00:00")

    @patch("app.services.agent_task_service.get_agent_task")
    @patch("app.services.agent_task_service.execute")
    def test_complete_task_accepts_datetime_payload(self, execute, _get_task):
        complete_agent_task(42, "완료", {"collected_at": datetime(2026, 9, 18)})

        self.assertEqual(json.loads(execute.call_args.args[1][2])["collected_at"], "2026-09-18 00:00:00")
