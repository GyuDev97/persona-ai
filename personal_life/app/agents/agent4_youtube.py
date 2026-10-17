from typing import Any

from .base_agent import BaseAgent


class Agent4Youtube(BaseAgent):
    def run(self, query: str) -> tuple[str, dict[str, Any]]:
        from pc_agent_runner import build_youtube_idea_report

        return build_youtube_idea_report(query)
