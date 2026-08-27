from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml


class ProfileError(ValueError):
    pass


@dataclass(frozen=True)
class ProjectProfile:
    id: str
    name: str
    repo_path: Path
    stack: list[str]
    build_command: str
    test_command: str
    retry_limit: int
    rules: list[str]
    protected_paths: list[str]


class ProjectManager:
    def __init__(self, profiles_dir: Path, workspace_root: Path) -> None:
        self.profiles_dir = profiles_dir
        self.workspace_root = workspace_root

    def list_profiles(self) -> list[ProjectProfile]:
        return [self.load_profile(path.stem) for path in sorted(self.profiles_dir.glob("*.yaml"))]

    def load_profile(self, profile_id: str) -> ProjectProfile:
        path = self.profiles_dir / f"{profile_id}.yaml"
        if not path.is_file():
            path = next((candidate for candidate in self.profiles_dir.glob("*.yaml")
                         if (yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}).get("id") == profile_id), path)
        if not path.is_file():
            raise ProfileError(f"Project profile not found: {profile_id}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        required = ("id", "name", "repo_path", "build_command", "test_command")
        missing = [key for key in required if not raw.get(key)]
        if missing:
            raise ProfileError(f"Profile missing required fields: {', '.join(missing)}")
        repo_path = Path(raw["repo_path"])
        if not repo_path.is_absolute():
            repo_path = (path.parent / repo_path).resolve()
        retry_limit = int(raw.get("retry_limit", 3))
        return ProjectProfile(
            id=str(raw["id"]), name=str(raw["name"]), repo_path=repo_path,
            stack=[str(value) for value in raw.get("stack", [])],
            build_command=str(raw["build_command"]), test_command=str(raw["test_command"]),
            retry_limit=max(1, min(retry_limit, 3)),
            rules=[str(value) for value in raw.get("rules", [])],
            protected_paths=[str(value).replace("\\", "/").strip("/") for value in raw.get("protected_paths", [])],
        )

    def create_worktree(self, profile: ProjectProfile, task_id: str) -> Path:
        if not profile.repo_path.is_dir():
            raise ProfileError(f"Repository path does not exist: {profile.repo_path}")
        if not (profile.repo_path / ".git").exists():
            raise ProfileError(f"Repository must be a Git checkout: {profile.repo_path}")
        target = (self.workspace_root / task_id).resolve()
        if target.exists():
            raise ProfileError(f"Workspace already exists: {target}")
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            ["git", "-C", str(profile.repo_path), "worktree", "add", "--detach", str(target), "HEAD"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        if completed.returncode != 0:
            shutil.rmtree(target, ignore_errors=True)
            detail = (completed.stderr or completed.stdout).strip()
            raise ProfileError(f"Could not create isolated Git worktree: {detail}")
        return target
