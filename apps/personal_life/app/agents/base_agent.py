from typing import Any


class BaseAgent:
    def run(self, query: str) -> tuple[str, dict[str, Any]]:
        raise NotImplementedError
