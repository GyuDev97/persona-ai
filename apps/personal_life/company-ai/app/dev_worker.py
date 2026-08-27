from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .build_runner import BuildRunner
from .codex_runner import CodexRunner, CommandResult, build_codex_prompt
from .database import Database
from .models import TaskStatus, TERMINAL_STATUSES
from .project_manager import ProfileError, ProjectManager
from .report_generator import generate_report, protected_changes, write_report


def now() -> str:
    return datetime.now().astimezone().isoformat()


def task_id() -> str:
    return f"TASK-{datetime.now():%Y%m%d-%H%M%S-%f}"[:-3]


class DevWorker:
    """One in-process worker per task. V1 intentionally has no queue infrastructure."""

    def __init__(self, db: Database, projects: ProjectManager, codex: CodexRunner, builds: BuildRunner, reports_dir: Path) -> None:
        self.db, self.projects, self.codex, self.builds, self.reports_dir = db, projects, codex, builds, reports_dir
        self._cancel_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def create_task(self, project_id: str, requirement: str) -> dict[str, Any]:
        self.projects.load_profile(project_id)  # validate before storing
        identifier = task_id()
        timestamp = now()
        self.db.execute("INSERT INTO tasks (id, project_id, requirement, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (identifier, project_id, requirement.strip(), TaskStatus.PENDING.value, timestamp, timestamp))
        self._emit_event(identifier, None, "TASK_STARTED", "작업을 시작했습니다.")
        return self.get_task(identifier)

    def start(self, identifier: str) -> None:
        with self._lock:
            if identifier in self._cancel_events:
                return
            event = threading.Event()
            self._cancel_events[identifier] = event
        threading.Thread(target=self._run, args=(identifier, event), name=f"dev-worker-{identifier}", daemon=True).start()

    def cancel(self, identifier: str) -> bool:
        task = self.get_task(identifier)
        if not task or TaskStatus(task["status"]) in TERMINAL_STATUSES:
            return False
        with self._lock:
            event = self._cancel_events.get(identifier)
        if event:
            event.set()
        else:
            self._set_status(identifier, TaskStatus.CANCELLED, "Cancelled before execution started.", finished=True)
        self._append_log(identifier, None, "system", "Cancellation requested.")
        return True

    def get_task(self, identifier: str) -> dict[str, Any] | None:
        row = self.db.fetchone("SELECT * FROM tasks WHERE id = ?", (identifier,))
        if not row:
            return None
        task = self.db.decode_task(row)
        task["attempts"] = self.db.fetchall("SELECT * FROM attempts WHERE task_id = ? ORDER BY attempt_no", (identifier,))
        for attempt in task["attempts"]:
            attempt["changed_files"] = json.loads(attempt.pop("changed_files_json"))
        task["logs"] = self.db.fetchall("SELECT attempt_no, stream, message, created_at FROM task_logs WHERE task_id = ? ORDER BY id DESC LIMIT 300", (identifier,))
        task["logs"].reverse()
        task["events"] = self.events_after(identifier, 0)
        return task

    def events_after(self, identifier: str, after_id: int) -> list[dict[str, Any]]:
        return self.db.fetchall("""SELECT id, attempt_no, event_type, message, created_at
                                 FROM task_events WHERE task_id = ? AND id > ? ORDER BY id""", (identifier, after_id))

    def list_tasks(self, limit: int = 30) -> list[dict[str, Any]]:
        # Creation time alone controls dashboard order; status changes never move a card.
        rows = self.db.fetchall("SELECT * FROM tasks ORDER BY created_at DESC, id DESC LIMIT ?", (limit,))
        return [self.db.decode_task(row) for row in rows]

    def _run(self, identifier: str, cancel_event: threading.Event) -> None:
        workspace: Path | None = None
        profile = None
        try:
            task = self.get_task(identifier)
            if not task:
                return
            self._set_status(identifier, TaskStatus.PREPARING)
            self._emit_event(identifier, None, "PROJECT_PREPARING", "프로젝트 준비를 시작했습니다.")
            self._append_log(identifier, None, "system", "Loading project profile and creating isolated Git worktree.")
            profile = self.projects.load_profile(task["project_id"])
            self._emit_event(identifier, None, "PROJECT_PROFILE_LOADED", "프로젝트 설정을 불러왔습니다.")
            workspace = self.projects.create_worktree(profile, identifier)
            self.db.execute("UPDATE tasks SET workspace_path = ?, updated_at = ? WHERE id = ?", (str(workspace), now(), identifier))
            self._emit_event(identifier, None, "PROJECT_READY", "격리된 작업 공간을 준비했습니다.")
            previous_error: str | None = None
            for attempt_no in range(1, profile.retry_limit + 1):
                if cancel_event.is_set():
                    self._set_status(identifier, TaskStatus.CANCELLED, "Cancelled by user.", finished=True)
                    break
                self._start_attempt(identifier, attempt_no)
                prompt = build_codex_prompt(profile, task["requirement"], attempt_no, previous_error)
                self._set_status(identifier, TaskStatus.RUNNING_CODEX, attempt_no=attempt_no)
                self._emit_event(identifier, attempt_no, "CODEX_STARTED", "Codex가 코드 분석을 시작했습니다.")
                self._append_log(identifier, attempt_no, "system", f"Starting Codex attempt {attempt_no}/{profile.retry_limit}.")
                codex_result = self.codex.run(identifier, workspace, prompt, self._callback(identifier, attempt_no), cancel_event)
                self._append_log(identifier, attempt_no, "codex", f"Codex finished with exit code {codex_result.exit_code}.")
                if codex_result.cancelled:
                    self._finish_attempt(identifier, attempt_no, codex_result, None, None, "Cancelled by user.", workspace)
                    self._set_status(identifier, TaskStatus.CANCELLED, "Cancelled by user.", finished=True)
                    break
                if codex_result.exit_code != 0 or codex_result.timed_out:
                    error = self._codex_failure(codex_result)
                    self._emit_event(identifier, attempt_no, "CODEX_FAILED", "Codex 실행에 실패했습니다. 오류 원인을 확인합니다.")
                    self._finish_attempt(identifier, attempt_no, codex_result, None, None, error, workspace)
                    previous_error = error
                    if attempt_no == profile.retry_limit:
                        self._set_status(identifier, TaskStatus.FAILED_NEEDS_HUMAN, error, attempt_no, finished=True)
                    else:
                        self._set_status(identifier, TaskStatus.RETRYING, error, attempt_no)
                        self._emit_event(identifier, attempt_no, "RETRY_STARTED", f"자동 수정 {attempt_no + 1}/{profile.retry_limit}회를 시작합니다.")
                        self._append_log(identifier, attempt_no, "system", "Codex failed; sending concise error context to the next attempt.")
                    continue
                self._set_status(identifier, TaskStatus.BUILDING, attempt_no=attempt_no)
                self._emit_event(identifier, attempt_no, "BUILD_STARTED", "빌드를 시작했습니다.")
                build_result = self.builds.run(profile.build_command, workspace, self._callback(identifier, attempt_no), cancel_event)
                if build_result.cancelled:
                    self._finish_attempt(identifier, attempt_no, codex_result, build_result, None, "Cancelled by user.", workspace)
                    self._set_status(identifier, TaskStatus.CANCELLED, "Cancelled by user.", finished=True)
                    break
                self._emit_event(identifier, attempt_no, "BUILD_SUCCESS" if build_result.exit_code == 0 else "BUILD_FAILED",
                                 "빌드에 성공했습니다." if build_result.exit_code == 0 else "빌드에 실패했습니다. 오류 원인을 분석합니다.")
                self._set_status(identifier, TaskStatus.TESTING, attempt_no=attempt_no)
                self._emit_event(identifier, attempt_no, "TEST_STARTED", "테스트를 시작했습니다.")
                test_result = self.builds.run(profile.test_command, workspace, self._callback(identifier, attempt_no), cancel_event)
                self._emit_event(identifier, attempt_no, "TEST_SUCCESS" if test_result.exit_code == 0 else "TEST_FAILED",
                                 "테스트가 완료되었습니다." if test_result.exit_code == 0 else "테스트에 실패했습니다. 오류 원인을 분석합니다.")
                error = self._error_summary(codex_result, build_result, test_result)
                protected = protected_changes(workspace, profile.protected_paths)
                if protected:
                    error = f"Safety stop: protected path modified: {', '.join(protected)}"
                self._finish_attempt(identifier, attempt_no, codex_result, build_result, test_result, error, workspace)
                if not error:
                    self._set_status(identifier, TaskStatus.SUCCESS, None, attempt_no, finished=True)
                    break
                previous_error = error
                if attempt_no == profile.retry_limit:
                    self._set_status(identifier, TaskStatus.FAILED_NEEDS_HUMAN, error, attempt_no, finished=True)
                else:
                    self._set_status(identifier, TaskStatus.RETRYING, error, attempt_no)
                    self._emit_event(identifier, attempt_no, "RETRY_STARTED", f"자동 수정 {attempt_no + 1}/{profile.retry_limit}회를 시작합니다.")
                    self._append_log(identifier, attempt_no, "system", "Build/test failed; sending concise error context to the next Codex attempt.")
            self._finalize_report(identifier, profile, workspace)
            final_status = self.get_task(identifier)["status"]
            if final_status == TaskStatus.SUCCESS.value:
                self._emit_event(identifier, None, "TASK_SUCCESS", "작업이 완료되었습니다.")
            elif final_status == TaskStatus.FAILED_NEEDS_HUMAN.value:
                self._emit_event(identifier, None, "TASK_FAILED", "자동 수정 후에도 완료하지 못했습니다. 사용자 확인이 필요합니다.")
            elif final_status == TaskStatus.CANCELLED.value:
                self._emit_event(identifier, None, "TASK_CANCELLED", "작업이 취소되었습니다.")
        except Exception as exc:  # retain a reportable failure rather than losing the task
            message = f"Worker error: {type(exc).__name__}: {exc}"
            self._append_log(identifier, None, "system", message)
            self._set_status(identifier, TaskStatus.FAILED, message, finished=True)
            if profile:
                self._finalize_report(identifier, profile, workspace)
            self._emit_event(identifier, None, "TASK_FAILED", "작업 처리 중 오류가 발생했습니다. 사용자 확인이 필요합니다.")
        finally:
            with self._lock:
                self._cancel_events.pop(identifier, None)

    def _callback(self, identifier: str, attempt_no: int):
        def callback(stream: str, message: str) -> None:
            self._append_log(identifier, attempt_no, stream, message)
            summary = self._user_event_from_output(message)
            if summary:
                self._emit_event(identifier, attempt_no, summary[0], summary[1], deduplicate=True)
        return callback

    def _set_status(self, identifier: str, status: TaskStatus, error: str | None = None,
                    attempt_no: int | None = None, finished: bool = False) -> None:
        parts = ["status = ?", "updated_at = ?"]
        params: list[Any] = [status.value, now()]
        if error is not None:
            parts.append("error_summary = ?")
            params.append(error[:4000])
        if attempt_no is not None:
            parts.append("current_attempt = ?")
            params.append(attempt_no)
        if finished:
            parts.append("finished_at = ?")
            params.append(now())
        params.append(identifier)
        self.db.execute(f"UPDATE tasks SET {', '.join(parts)} WHERE id = ?", tuple(params))

    def _start_attempt(self, identifier: str, attempt_no: int) -> None:
        self.db.execute("INSERT INTO attempts (task_id, attempt_no, started_at) VALUES (?, ?, ?)", (identifier, attempt_no, now()))

    def _finish_attempt(self, identifier: str, attempt_no: int, codex: CommandResult, build: CommandResult | None,
                        test: CommandResult | None, error: str | None, workspace: Path) -> None:
        from .report_generator import changed_files
        self.db.execute("""UPDATE attempts SET codex_exit_code = ?, build_exit_code = ?, test_exit_code = ?, codex_output = ?,
                           build_output = ?, test_output = ?, error_summary = ?, changed_files_json = ?, finished_at = ?
                           WHERE task_id = ? AND attempt_no = ?""",
                        (codex.exit_code, build.exit_code if build else None, test.exit_code if test else None, codex.output[-30000:],
                         build.output[-30000:] if build else None, test.output[-30000:] if test else None, error,
                         json.dumps(changed_files(workspace), ensure_ascii=False), now(), identifier, attempt_no))

    def _append_log(self, identifier: str, attempt_no: int | None, stream: str, message: str) -> None:
        if message:
            self.db.execute("INSERT INTO task_logs (task_id, attempt_no, stream, message, created_at) VALUES (?, ?, ?, ?, ?)",
                            (identifier, attempt_no, stream, message[:8000], now()))

    def _emit_event(self, identifier: str, attempt_no: int | None, event_type: str, message: str,
                    deduplicate: bool = False) -> None:
        if deduplicate:
            recent = self.db.fetchone("SELECT event_type, message FROM task_events WHERE task_id = ? ORDER BY id DESC LIMIT 1", (identifier,))
            if recent and recent["event_type"] == event_type and recent["message"] == message:
                return
        self.db.execute("""INSERT INTO task_events (task_id, attempt_no, event_type, message, created_at)
                         VALUES (?, ?, ?, ?, ?)""", (identifier, attempt_no, event_type, message, now()))

    @staticmethod
    def _user_event_from_output(message: str) -> tuple[str, str] | None:
        lowered = message.lower()
        if "apply patch" in lowered or "patch: completed" in lowered or "write_file" in lowered:
            return "CODEX_EDITING", "코드 수정을 진행하고 있습니다."
        if "rg " in lowered or "get-content" in lowered or "get-childitem" in lowered or "read_file" in lowered:
            return "CODEX_ANALYZING", "관련 코드와 파일을 확인하고 있습니다."
        if "git diff" in lowered:
            return "CODEX_REVIEWING", "변경 내용을 확인하고 있습니다."
        return None

    def _error_summary(self, codex: CommandResult, build: CommandResult, test: CommandResult) -> str | None:
        failures: list[str] = []
        for name, result in (("Codex", codex), ("Build", build), ("Test", test)):
            if result.exit_code != 0 or result.timed_out:
                excerpt = self._extract_error(result.output)
                failures.append(f"{name} {'timed out' if result.timed_out else f'failed (exit {result.exit_code})'}: {excerpt}")
        return "\n".join(failures) if failures else None

    def _codex_failure(self, result: CommandResult) -> str:
        state = "timed out" if result.timed_out else f"failed (exit {result.exit_code})"
        return f"Codex {state}: {self._extract_error(result.output)}"

    @staticmethod
    def _extract_error(output: str) -> str:
        candidates = [line.strip() for line in output.splitlines() if any(token in line.lower() for token in ("error", "failed", "exception", "traceback"))]
        return " | ".join(candidates[-8:])[:3500] or output.strip()[-2000:] or "No diagnostic output."

    def _finalize_report(self, identifier: str, profile, workspace: Path | None) -> None:
        task = self.get_task(identifier)
        if not task:
            return
        self._emit_event(identifier, None, "REPORT_GENERATING", "작업 결과를 정리하고 있습니다.")
        markdown, payload = generate_report(task, profile.name, task["attempts"], workspace, profile.protected_paths)
        write_report(self.reports_dir, identifier, markdown, payload)
        self.db.execute("UPDATE tasks SET report_markdown = ?, report_json = ?, updated_at = ? WHERE id = ?",
                        (markdown, json.dumps(payload, ensure_ascii=False), now(), identifier))
        self._emit_event(identifier, None, "REPORT_READY", "작업 결과를 생성했습니다.")
