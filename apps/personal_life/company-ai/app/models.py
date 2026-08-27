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
    stack: list[str]
    retry_limit: int


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
