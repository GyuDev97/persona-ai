from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ProfileError(ValueError):
    pass


@dataclass(frozen=True)
class ProjectProfile:
    id: str
    name: str
    description: str
    repo_path: Path
    vcs: str
    default_branch: str
    stack: list[str]
    build_command: str
    test_command: str
    retry_limit: int
    rules: list[str]
    additional_instructions: str
    protected_paths: list[str]
    blocked_commands: list[str]
    working_directory: str
    links: dict[str, str]
    enabled: bool
    updated_at: str


class ProjectManager:
    def __init__(self, profiles_dir: Path, workspace_root: Path) -> None:
        self.profiles_dir = profiles_dir
        self.workspace_root = workspace_root

    def list_profiles(self) -> list[ProjectProfile]:
        profiles = [self.load_profile(path.stem) for path in self.profiles_dir.glob("*.yaml")]
        return sorted(profiles, key=lambda profile: (profile.updated_at, profile.id), reverse=True)

    def load_profile(self, profile_id: str) -> ProjectProfile:
        path = self.profiles_dir / f"{profile_id}.yaml"
        if not path.is_file():
            path = next((candidate for candidate in self.profiles_dir.glob("*.yaml")
                         if (yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}).get("id") == profile_id), path)
        if not path.is_file():
            raise ProfileError(f"Project profile not found: {profile_id}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        required = ("id", "name", "repo_path")
        missing = [key for key in required if not raw.get(key)]
        if missing:
            raise ProfileError(f"Profile missing required fields: {', '.join(missing)}")
        repo_path = Path(raw["repo_path"])
        if not repo_path.is_absolute():
            repo_path = (path.parent / repo_path).resolve()
        retry_limit = int(raw.get("retry_limit", 3))
        return ProjectProfile(
            id=str(raw["id"]), name=str(raw["name"]), description=str(raw.get("description", "")), repo_path=repo_path,
            vcs=str(raw.get("vcs", "git")).lower(), default_branch=str(raw.get("default_branch", "main")),
            stack=[str(value) for value in raw.get("stack", [])],
            build_command=str(raw.get("build_command", "")), test_command=str(raw.get("test_command", "")),
            retry_limit=max(1, min(retry_limit, 3)),
            rules=[str(value) for value in raw.get("rules", [])],
            additional_instructions=str(raw.get("additional_instructions", "")),
            protected_paths=[str(value).replace("\\", "/").strip("/") for value in raw.get("protected_paths", [])],
            blocked_commands=[str(value) for value in raw.get("blocked_commands", [])],
            working_directory=str(raw.get("working_directory", "")),
            links={str(key): str(value) for key, value in (raw.get("links") or {}).items()},
            enabled=bool(raw.get("enabled", True)), updated_at=str(raw.get("updated_at", "")),
        )

    def save_profile(self, data: dict[str, Any], original_id: str | None = None) -> ProjectProfile:
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        identifier = str(data["id"])
        target = self.profiles_dir / f"{identifier}.yaml"
        if original_id is None and any(profile.id == identifier for profile in self.list_profiles()):
            raise ProfileError(f"Project ID already exists: {identifier}")
        if original_id and original_id != identifier and any(profile.id == identifier for profile in self.list_profiles()):
            raise ProfileError(f"Project ID already exists: {identifier}")
        payload = dict(data)
        payload["updated_at"] = datetime.now().astimezone().isoformat()
        target.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
        if original_id and original_id != identifier:
            old = self.profiles_dir / f"{original_id}.yaml"
            if old.exists():
                old.unlink()
        return self.load_profile(identifier)

    def delete_profile(self, profile_id: str) -> None:
        path = self.profiles_dir / f"{profile_id}.yaml"
        if not path.is_file():
            raise ProfileError(f"Project profile not found: {profile_id}")
        path.unlink()

    def validate_command(self, profile: ProjectProfile, command: str) -> None:
        normalized = " ".join(command.lower().split())
        for pattern in profile.blocked_commands:
            blocked = " ".join(pattern.lower().split())
            if blocked and (normalized.startswith(blocked) or blocked in normalized):
                raise ProfileError(f"Blocked command detected: {pattern}")

    @staticmethod
    def command_directory(profile: ProjectProfile, workspace: Path) -> Path:
        if not profile.working_directory:
            return workspace
        configured = Path(profile.working_directory)
        if configured.is_absolute():
            try:
                relative = configured.resolve().relative_to(profile.repo_path.resolve())
            except ValueError:
                return workspace
        else:
            relative = configured
        target = (workspace / relative).resolve()
        try:
            target.relative_to(workspace.resolve())
        except ValueError as exc:
            raise ProfileError("Working directory must stay inside the project workspace.") from exc
        if not target.is_dir():
            raise ProfileError(f"Working directory does not exist: {relative}")
        return target

    def check_environment(self, profile_id: str) -> dict[str, Any]:
        profile = self.load_profile(profile_id)
        checks: list[dict[str, Any]] = []
        def add(label: str, ok: bool, detail: str = "") -> None:
            checks.append({"label": label, "ok": ok, "detail": detail})
        add("Repository 접근", profile.repo_path.is_dir(), str(profile.repo_path))
        if profile.vcs == "git":
            add("Git 저장소", (profile.repo_path / ".git").exists())
            branch = subprocess.run(["git", "-C", str(profile.repo_path), "branch", "--list", profile.default_branch], capture_output=True, text=True) if profile.repo_path.is_dir() else None
            add("기본 Branch", bool(branch and branch.returncode == 0 and branch.stdout.strip()), profile.default_branch)
        elif profile.vcs == "svn":
            add("SVN 실행파일", shutil.which("svn") is not None)
        add("Codex CLI", shutil.which("codex") is not None)
        executable = profile.build_command.strip().split(maxsplit=1)[0] if profile.build_command.strip() else ""
        add("Build Command", bool(executable and (shutil.which(executable) or executable.lower() in {"python", "py"})), profile.build_command or "미설정")
        add("Test Command", bool(profile.test_command.strip()), profile.test_command or "미설정")
        return {"available": all(check["ok"] for check in checks), "checked_at": datetime.now().astimezone().isoformat(), "checks": checks}

    def create_worktree(self, profile: ProjectProfile, task_id: str) -> Path:
        if not profile.enabled:
            raise ProfileError("Disabled project cannot run tasks.")
        if profile.vcs != "git":
            raise ProfileError("V1 task automation currently requires Git.")
        if not profile.repo_path.is_dir():
            raise ProfileError(f"Repository path does not exist: {profile.repo_path}")
        if not (profile.repo_path / ".git").exists():
            raise ProfileError(f"Repository must be a Git checkout: {profile.repo_path}")
        target = (self.workspace_root / task_id).resolve()
        if target.exists():
            raise ProfileError(f"Workspace already exists: {target}")
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            ["git", "-C", str(profile.repo_path), "worktree", "add", "--detach", str(target), profile.default_branch],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        if completed.returncode != 0:
            shutil.rmtree(target, ignore_errors=True)
            detail = (completed.stderr or completed.stdout).strip()
            raise ProfileError(f"Could not create isolated Git worktree: {detail}")
        return target
