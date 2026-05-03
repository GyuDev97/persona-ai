from typing import Any

from .base_agent import BaseAgent


class Agent1News(BaseAgent):
    def run(self, query: str) -> tuple[str, dict[str, Any]]:
        from pc_agent_runner import build_agent1_it_news_window

        return build_agent1_it_news_window(query)
