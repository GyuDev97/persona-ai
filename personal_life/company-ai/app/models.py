from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    PREPARING = "PREPARING"
    RUNNING_CODEX = "RUNNING_CODEX"
    BUILDING = "BUILDING"
    TESTING = "TESTING"
    RETRYING = "RETRYING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    FAILED_NEEDS_HUMAN = "FAILED_NEEDS_HUMAN"
    CANCELLED = "CANCELLED"


TERMINAL_STATUSES = {TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.FAILED_NEEDS_HUMAN, TaskStatus.CANCELLED}


class TaskCreateRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=100)
    requirement: str = Field(min_length=3, max_length=20_000)


class ProjectSummary(BaseModel):
    id: str
    name: str
    description: str = ""
    repo_path: str = ""
    stack: list[str]
    retry_limit: int
    enabled: bool = True
    updated_at: str = ""


class ProjectProfileRequest(BaseModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,99}$")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    repo_path: str = Field(min_length=1, max_length=1000)
    vcs: str = Field(default="git", pattern=r"^(git|svn|none)$")
    default_branch: str = Field(default="main", max_length=200)
    stack: list[str] = []
    build_command: str = Field(default="", max_length=2000)
    test_command: str = Field(default="", max_length=2000)
    working_directory: str = Field(default="", max_length=1000)
    retry_limit: int = Field(default=3, ge=1, le=3)
    rules: list[str] = []
    additional_instructions: str = Field(default="", max_length=10000)
    protected_paths: list[str] = []
    blocked_commands: list[str] = []
    links: dict[str, str] = {}
    enabled: bool = True


class TaskSummary(BaseModel):
    id: str
    project_id: str
    requirement: str
    status: TaskStatus
    current_attempt: int
    created_at: str
    updated_at: str
    error_summary: str | None = None


class TaskDetail(TaskSummary):
    workspace_path: str | None = None
    report_markdown: str | None = None
    report_json: dict[str, Any] | None = None
    attempts: list[dict[str, Any]] = []
    logs: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
