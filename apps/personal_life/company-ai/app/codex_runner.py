from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .project_manager import ProjectProfile


LogCallback = Callable[[str, str], None]


@dataclass
class CommandResult:
    exit_code: int | None
    output: str
    timed_out: bool = False
    cancelled: bool = False


def build_codex_prompt(profile: ProjectProfile, requirement: str, attempt: int, previous_error: str | None) -> str:
    rules = "\n".join(f"- {rule}" for rule in profile.rules) or "- Keep changes minimal and scoped."
    protected = "\n".join(f"- {path}" for path in profile.protected_paths) or "- (none)"
    error_section = previous_error or "None. This is the first attempt."
    return f"""You are the implementation worker for a company repository. Complete the task in the current Git worktree only.

PROJECT RULES:
{rules}
- Never run git push, merge, commit, deployment, or access production systems.
- Do not change database schemas.
- Do not modify protected paths listed below.

PROTECTED PATHS:
{protected}

USER REQUIREMENT:
{requirement}

CURRENT ATTEMPT: {attempt}

PREVIOUS BUILD/TEST ERROR:
{error_section}

Analyze the existing code first. Make only the changes necessary for the requirement. Do not stop to ask questions; implement a safe best-effort solution. Do not run destructive Git commands. Finish with a brief summary of changed files and remaining risks."""


class CodexRunner:
    def __init__(self, logs_dir: Path, timeout_seconds: int = 20 * 60, executable: str | None = None) -> None:
        self.logs_dir = logs_dir
        self.timeout_seconds = timeout_seconds
        self.executable = executable or os.environ.get("CODEX_CLI_PATH", "codex")

    def run(self, task_id: str, workspace: Path, prompt: str, callback: LogCallback, cancel_event: threading.Event) -> CommandResult:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        output_file = self.logs_dir / f"{task_id}-codex-final.md"
        # --approve-for-me already uses Codex's workspace-write approval flow.
        # Current Codex CLI versions reject an explicit --sandbox alongside it.
        command = [self.executable, "exec", "--cd", str(workspace), "--ephemeral", "--approve-for-me", "--color", "never", "--output-last-message", str(output_file), prompt]
        result = run_command(command, workspace, self.timeout_seconds, callback, cancel_event)
        if output_file.is_file():
            final_message = output_file.read_text(encoding="utf-8", errors="replace")
            if final_message:
                callback("codex", final_message)
                result.output += f"\n[Codex final message]\n{final_message}"
        return result


def run_command(command: list[str] | str, cwd: Path, timeout_seconds: int, callback: LogCallback,
                cancel_event: threading.Event, shell: bool = False) -> CommandResult:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(command, cwd=cwd, shell=shell, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=creationflags)
    lines: list[str] = []
    started = time.monotonic()
    assert process.stdout is not None
    output_queue: queue.Queue[str | None] = queue.Queue()

    def read_output() -> None:
        try:
            for line in process.stdout:
                output_queue.put(line)
        finally:
            output_queue.put(None)

    threading.Thread(target=read_output, name="process-output-reader", daemon=True).start()
    while True:
        try:
            line = output_queue.get(timeout=0.2)
        except queue.Empty:
            line = ""
        if line and line is not None:
            lines.append(line)
            callback("process", line.rstrip())
        if cancel_event.is_set():
            process.terminate()
            return_code = process.wait(timeout=10)
            return CommandResult(return_code, "".join(lines), cancelled=True)
        if time.monotonic() - started > timeout_seconds:
            process.terminate()
            return_code = process.wait(timeout=10)
            return CommandResult(return_code, "".join(lines), timed_out=True)
        if process.poll() is not None and (line is None or output_queue.empty()):
            return CommandResult(process.returncode, "".join(lines))
