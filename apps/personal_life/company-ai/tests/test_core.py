import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from app.codex_runner import CommandResult, build_codex_prompt
from app.database import Database
from app.dev_worker import DevWorker
from app.models import TaskStatus
from app.project_manager import ProjectManager


class FakeCodex:
    def run(self, task_id, workspace, prompt, callback, cancel_event):
        callback("codex", "fake implementation completed")
        return CommandResult(0, "implementation completed")


class FailingBuilds:
    def run(self, command, workspace, callback, cancel_event):
        callback("process", "ERROR: controlled test failure")
        return CommandResult(1, "ERROR: controlled test failure")


class FailingCodex:
    def run(self, task_id, workspace, prompt, callback, cancel_event):
        callback("codex", "ERROR: controlled Codex startup failure")
        return CommandResult(1, "ERROR: controlled Codex startup failure")


class MustNotBuild:
    def run(self, *args, **kwargs):
        raise AssertionError("Build/Test must not execute when Codex failed")


class CoreTests(unittest.TestCase):
    def _make_repo(self, root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Company AI Test"], cwd=repo, check=True)
        (repo / "app.txt").write_text("baseline", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", "baseline"], cwd=repo, check=True, capture_output=True)
        return repo

    def _write_profile(self, profiles: Path, repo: Path) -> None:
        profiles.mkdir()
        (profiles / "demo_profile.yaml").write_text(f"""id: demo
name: Demo
repo_path: {repo.as_posix()}
build_command: echo build
test_command: echo test
retry_limit: 99
rules:
  - Keep scope small.
protected_paths:
  - deploy
""", encoding="utf-8")

    def test_profile_clamps_retry_limit_and_prompt_has_safety_context(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); repo = self._make_repo(root); profiles = root / "profiles"; self._write_profile(profiles, repo)
            profile = ProjectManager(profiles, root / "workspace").load_profile("demo")
            prompt = build_codex_prompt(profile, "Add a simple endpoint", 2, "Build failed: missing import")
            self.assertEqual(profile.retry_limit, 3)
            self.assertIn("CURRENT ATTEMPT: 2", prompt)
            self.assertIn("PREVIOUS BUILD/TEST ERROR", prompt)
            self.assertIn("Never run git push", prompt)

    def test_failed_run_stops_after_three_attempts_and_writes_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); repo = self._make_repo(root); profiles = root / "profiles"; self._write_profile(profiles, repo)
            db = Database(root / "data" / "tasks.db")
            worker = DevWorker(db, ProjectManager(profiles, root / "workspace"), FakeCodex(), FailingBuilds(), root / "reports")
            task = worker.create_task("demo", "Make a controlled change")
            worker._run(task["id"], threading.Event())
            finished = worker.get_task(task["id"])
            self.assertEqual(finished["status"], TaskStatus.FAILED_NEEDS_HUMAN.value)
            self.assertEqual(len(finished["attempts"]), 3)
            self.assertTrue((root / "reports" / f"{task['id']}.md").is_file())
            event_types = [event["event_type"] for event in worker.events_after(task["id"], 0)]
            self.assertTrue({"TASK_STARTED", "PROJECT_READY", "CODEX_STARTED", "BUILD_STARTED", "BUILD_FAILED", "RETRY_STARTED", "REPORT_READY", "TASK_FAILED"}.issubset(event_types))

    def test_codex_startup_failure_retries_without_running_build_or_test(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); repo = self._make_repo(root); profiles = root / "profiles"; self._write_profile(profiles, repo)
            db = Database(root / "data" / "tasks.db")
            worker = DevWorker(db, ProjectManager(profiles, root / "workspace"), FailingCodex(), MustNotBuild(), root / "reports")
            task = worker.create_task("demo", "Make a controlled change")
            worker._run(task["id"], threading.Event())
            finished = worker.get_task(task["id"])
            self.assertEqual(finished["status"], TaskStatus.FAILED_NEEDS_HUMAN.value)
            self.assertEqual(len(finished["attempts"]), 3)
            self.assertTrue(all(attempt["build_exit_code"] is None for attempt in finished["attempts"]))

    def test_recent_tasks_use_creation_time_then_task_id_descending(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = Database(root / "data" / "tasks.db")
            worker = DevWorker(db, None, None, None, root / "reports")
            timestamp = "2026-08-27T22:48:00+09:00"
            for identifier in ("TASK-001", "TASK-003", "TASK-002"):
                db.execute("INSERT INTO tasks (id, project_id, requirement, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                           (identifier, "demo", identifier, TaskStatus.PENDING.value, timestamp, timestamp))
            db.execute("INSERT INTO tasks (id, project_id, requirement, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                       ("TASK-000", "demo", "older", TaskStatus.SUCCESS.value, "2026-08-27T22:47:00+09:00", timestamp))
            self.assertEqual([task["id"] for task in worker.list_tasks()], ["TASK-003", "TASK-002", "TASK-001", "TASK-000"])

    def test_raw_codex_output_is_reduced_to_safe_user_events(self):
        self.assertEqual(DevWorker._user_event_from_output("Get-ChildItem -Force; rg -n greeting ."),
                         ("CODEX_ANALYZING", "관련 코드와 파일을 확인하고 있습니다."))
        self.assertEqual(DevWorker._user_event_from_output("apply patch: completed"),
                         ("CODEX_EDITING", "코드 수정을 진행하고 있습니다."))
        self.assertIsNone(DevWorker._user_event_from_output("model reasoning token count: 99"))


if __name__ == "__main__":
    unittest.main()
