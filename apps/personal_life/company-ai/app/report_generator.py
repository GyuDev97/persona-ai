from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


def _git_output(workspace: Path, *args: str) -> str:
    completed = subprocess.run(["git", "-C", str(workspace), *args], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=30)
    return completed.stdout.strip() if completed.returncode == 0 else ""


def changed_files(workspace: Path) -> list[str]:
    return [line for line in _git_output(workspace, "status", "--short").splitlines() if line]


def diff_summary(workspace: Path) -> str:
    return _git_output(workspace, "diff", "--stat") or "No uncommitted diff."


def protected_changes(workspace: Path, protected_paths: list[str]) -> list[str]:
    names = _git_output(workspace, "diff", "--name-only").splitlines()
    return [name for name in names if any(name == path or name.startswith(f"{path}/") for path in protected_paths)]


def generate_report(task: dict[str, Any], profile_name: str, attempts: list[dict[str, Any]], workspace: Path | None,
                    protected_paths: list[str]) -> tuple[str, dict[str, Any]]:
    changes = changed_files(workspace) if workspace else []
    diff = diff_summary(workspace) if workspace else "Workspace was not created."
    protected = protected_changes(workspace, protected_paths) if workspace else []
    final = attempts[-1] if attempts else {}
    review_items = []
    if protected:
        review_items.append(f"Protected-path changes detected: {', '.join(protected)}")
    if task["status"] == "SUCCESS":
        review_items.append("Review the Git diff in the isolated worktree before manually merging or committing.")
    else:
        review_items.append("Review the final build/test error and finish the change manually if needed.")
    payload = {
        "task_id": task["id"], "project": profile_name, "requirement": task["requirement"], "status": task["status"],
        "attempts": len(attempts), "changed_files": changes, "git_diff_summary": diff,
        "build_result": final.get("build_exit_code"), "test_result": final.get("test_exit_code"),
        "failure_reason": task.get("error_summary"), "human_review_required": review_items,
        "started_at": task["created_at"], "finished_at": task.get("finished_at"),
        "duration_seconds": _duration(task["created_at"], task.get("finished_at")), "generated_at": datetime.now().astimezone().isoformat(),
    }
    markdown = f"""# {task['id']}

**Status:** {task['status']}

## Project
{profile_name}

## Requirement
{task['requirement']}

## Attempts
{len(attempts)}

## Changed Files
{chr(10).join(f'- {item}' for item in changes) or '- None'}

## Git Diff Summary
```text
{diff}
```

## Build / Test
- Build exit code: {final.get('build_exit_code', 'not run')}
- Test exit code: {final.get('test_exit_code', 'not run')}

## Failure Reason
{task.get('error_summary') or 'None'}

## Human Review Required
{chr(10).join(f'- {item}' for item in review_items)}

## Timing
- Started: {task['created_at']}
- Finished: {task.get('finished_at') or 'Not finished'}
- Total duration: {payload['duration_seconds']} seconds
"""
    return markdown, payload


def write_report(reports_dir: Path, task_id: str, markdown: str, payload: dict[str, Any]) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"{task_id}.md").write_text(markdown, encoding="utf-8")
    (reports_dir / f"{task_id}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _duration(start: str, end: str | None) -> int | None:
    if not end:
        return None
    return max(0, int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()))
