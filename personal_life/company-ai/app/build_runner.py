from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from .codex_runner import CommandResult, run_command


class BuildRunner:
    def __init__(self, timeout_seconds: int = 15 * 60) -> None:
        self.timeout_seconds = timeout_seconds

    def run(self, command: str, workspace: Path, callback: Callable[[str, str], None], cancel_event: threading.Event) -> CommandResult:
        return run_command(command, workspace, self.timeout_seconds, callback, cancel_event, shell=True)
