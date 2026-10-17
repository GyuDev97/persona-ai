from typing import Any

from .base_agent import BaseAgent


class Agent3Codex(BaseAgent):
    def run(self, query: str) -> tuple[str, dict[str, Any]]:
        from pc_agent_runner import build_coding_app_update_report

        return build_coding_app_update_report(query)
