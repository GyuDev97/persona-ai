from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .build_runner import BuildRunner
from .codex_runner import CodexRunner
from .database import Database
from .dev_worker import DevWorker
from .models import ProjectSummary, TaskCreateRequest, TaskDetail, TaskSummary
from .project_manager import ProfileError, ProjectManager


ROOT = Path(__file__).resolve().parent.parent
db = Database(ROOT / "data" / "company_ai.db")
projects = ProjectManager(ROOT / "profiles", ROOT / "workspace")
worker = DevWorker(db, projects, CodexRunner(ROOT / "logs"), BuildRunner(), ROOT / "reports")

app = FastAPI(title="Company AI Dev Worker", version="1.0.0")
app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/projects", response_model=list[ProjectSummary])
def list_projects():
    return [ProjectSummary(id=p.id, name=p.name, stack=p.stack, retry_limit=p.retry_limit) for p in projects.list_profiles()]


@app.post("/api/tasks", response_model=TaskSummary, status_code=202)
def create_task(request: TaskCreateRequest):
    try:
        task = worker.create_task(request.project_id, request.requirement)
    except ProfileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    worker.start(task["id"])
    return task


@app.get("/api/tasks", response_model=list[TaskSummary])
def list_tasks():
    return worker.list_tasks()


@app.get("/api/tasks/{task_id}", response_model=TaskDetail)
def task_detail(task_id: str):
    task = worker.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.get("/api/tasks/{task_id}/events")
async def task_events(task_id: str, request: Request, after: int = 0):
    """Replay persisted user-facing events, then keep the dashboard up to date via SSE."""
    if not worker.get_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found")
    try:
        after_id = max(after, int(request.headers.get("last-event-id", "0")))
    except ValueError:
        after_id = 0

    async def stream():
        cursor = after_id
        while True:
            for event in worker.events_after(task_id, cursor):
                cursor = event["id"]
                task = worker.get_task(task_id)
                payload = {**event, "task": {
                    "status": task["status"], "current_attempt": task["current_attempt"],
                    "workspace_path": task["workspace_path"], "error_summary": task["error_summary"],
                    "report_json": task["report_json"], "attempts": task["attempts"],
                }}
                yield f"id: {cursor}\nevent: task_event\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            if await request.is_disconnected():
                break
            yield ": keepalive\n\n"
            await asyncio.sleep(0.75)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/api/tasks/{task_id}/cancel", response_model=TaskSummary)
def cancel_task(task_id: str):
    task = worker.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not worker.cancel(task_id):
        raise HTTPException(status_code=409, detail="Task is already finished")
    return worker.get_task(task_id)
