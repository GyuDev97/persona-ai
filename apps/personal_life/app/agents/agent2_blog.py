from typing import Any, Literal

from .base_agent import BaseAgent


class Agent2Blog(BaseAgent):
    def __init__(self, mode: Literal["draft", "fill"] = "draft") -> None:
        self.mode = mode

    def run(self, query: str) -> tuple[str, dict[str, Any]]:
        if self.mode == "fill":
            from pc_agent_runner import fill_latest_naver_blog_draft

            return fill_latest_naver_blog_draft(query)

        from pc_agent_runner import build_agent2_it_blog_draft

        return build_agent2_it_blog_draft()
