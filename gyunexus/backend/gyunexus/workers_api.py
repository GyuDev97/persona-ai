"""AI 직원 REST API. 서비스 로직은 workers.py 에 있고, 여기서는 HTTP 오류 매핑과 응답 조립만 한다."""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query, Request
from sqlalchemy import func, select

from .models import Approval, Worker, WorkerArtifact, WorkerRun, WorkerTask, row_dict
from .workers import WorkerError
from .workspace import WorkspaceError

router = APIRouter(prefix="/api/workers")
STATUS = {"validation": 422, "not_found": 404, "duplicate": 409, "disabled": 409, "conflict": 409, "llm": 503}


def svc(request: Request):
    return request.app.state.svc.workers


def _call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except WorkerError as e:
        raise HTTPException(STATUS.get(e.code, 400), str(e)) from e


def _worker_row(db, w: Worker) -> dict:
    with db.session() as s:
        tasks = s.scalar(select(func.count()).select_from(WorkerTask).where(WorkerTask.worker_id == w.id)) or 0
        waiting = s.scalar(select(func.count()).select_from(WorkerRun).where(WorkerRun.worker_id == w.id, WorkerRun.status == "awaiting_approval")) or 0
        running = s.scalar(select(func.count()).select_from(WorkerRun).where(WorkerRun.worker_id == w.id, WorkerRun.status.in_(("pending", "running", "reviewing")))) or 0
        last = s.scalars(select(WorkerRun).where(WorkerRun.worker_id == w.id).order_by(WorkerRun.id.desc())).first()
    state = "disabled" if not w.enabled else "working" if running else "waiting_approval" if waiting else "idle"
    return {**row_dict(w), "task_count": tasks, "awaiting_approval": waiting, "running": running, "state": state,
            "last_run": {"id": last.id, "status": last.status, "ended_at": last.ended_at.isoformat() + "Z" if last.ended_at else None} if last else None}


def _run_row(db, r: WorkerRun, detail: bool = False) -> dict:
    with db.session() as s:
        t, w = s.get(WorkerTask, r.task_id), s.get(Worker, r.worker_id)
        art = s.get(WorkerArtifact, r.artifact_id) if r.artifact_id else None
        ap = s.get(Approval, r.approval_id) if r.approval_id else None
    out = row_dict(r, exclude=() if detail else ("steps", "evidence", "verification"))
    out |= {"task_title": t.title if t else None, "worker_name": w.name if w else None,
            "artifact": row_dict(art) if art else None, "approval_status": ap.status if ap else None}
    return out


@router.get("/options")
async def options(request: Request):
    return svc(request).options()


@router.get("")
async def list_workers(request: Request):
    v = svc(request)
    with v.db.session() as s:
        rows = list(s.scalars(select(Worker).order_by(Worker.id)))
    return [_worker_row(v.db, w) for w in rows]


@router.post("", status_code=201)
async def create_worker(request: Request, body: dict = Body(...)):
    return row_dict(_call(svc(request).create_worker, body))


@router.get("/runs")
async def list_runs(request: Request, worker_id: int | None = None, task_id: int | None = None, status: str | None = None, limit: int = Query(50, ge=1, le=200)):
    v = svc(request)
    q = select(WorkerRun).order_by(WorkerRun.id.desc()).limit(limit)
    if worker_id:
        q = q.where(WorkerRun.worker_id == worker_id)
    if task_id:
        q = q.where(WorkerRun.task_id == task_id)
    if status:
        q = q.where(WorkerRun.status == status)
    with v.db.session() as s:
        rows = list(s.scalars(q))
    return [_run_row(v.db, r) for r in rows]


@router.get("/runs/{run_id}")
async def run_detail(run_id: int, request: Request):
    v = svc(request)
    r = _call(v.get_run, run_id)
    out = _run_row(v.db, r, detail=True)
    art = out["artifact"]
    if art:
        with v.db.session() as s:
            content = v.read_artifact(s.get(WorkerArtifact, art["id"]))
        out["content"] = content
    return out


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: int, request: Request):
    v = svc(request)
    try:
        r = await v.cancel(run_id)
    except WorkerError as e:
        raise HTTPException(STATUS.get(e.code, 400), str(e)) from e
    return _run_row(v.db, r)


@router.get("/runs/{run_id}/delete-check")
async def run_delete_check(run_id: int, request: Request):
    """이 실행을 지울 수 있는가(없으면 막는 이유). 삭제 확인 화면이 쓴다."""
    why = _call(svc(request).run_delete_block, run_id)
    return {"deletable": why is None, "reason": why}


@router.delete("/runs/{run_id}")
async def delete_run(run_id: int, request: Request):
    """실행 이력 1건 삭제(결과물 파일·승인 기록 포함). 진행 중이거나 워크플로에 속하거나 결과물이 다른 실행의 입력으로 쓰인 경우는 409."""
    return _call(svc(request).delete_run, run_id)


@router.post("/{worker_id}/runs/purge-unsuccessful")
async def purge_unsuccessful(worker_id: int, request: Request, body: dict = Body(default={})):
    """이 직원의 실패·취소·반려·자료 부족 실행을 한꺼번에 삭제한다(task_id 로 업무를 좁힐 수 있다). 완료·승인 대기 실행은 건드리지 않는다."""
    _call(svc(request).get_worker, worker_id)
    return _call(svc(request).delete_unsuccessful_runs, worker_id, body.get("task_id"))


@router.put("/tasks/{task_id}")
async def update_task(task_id: int, request: Request, body: dict = Body(...)):
    return row_dict(_call(svc(request).update_task, task_id, body))


@router.post("/tasks/{task_id}/pause")
async def pause_task(task_id: int, request: Request):
    return row_dict(_call(svc(request).set_task_status, task_id, "paused"))


@router.post("/tasks/{task_id}/resume")
async def resume_task(task_id: int, request: Request):
    return row_dict(_call(svc(request).set_task_status, task_id, "active"))


@router.post("/tasks/{task_id}/run", status_code=202)
async def run_task(task_id: int, request: Request):
    """수동 실행. 같은 업무의 진행 중 실행이 있으면 409."""
    try:
        run_id = await svc(request).start(task_id, "manual")
    except WorkerError as e:
        raise HTTPException(STATUS.get(e.code, 400), str(e)) from e
    return {"run_id": run_id}


@router.get("/{worker_id}/delete-impact")
async def delete_impact(worker_id: int, request: Request):
    """삭제하면 사라지는 것(업무·실행·결과물·워크플로 단계)과 삭제를 막는 조건. 삭제 확인 화면이 쓴다."""
    return _call(svc(request).delete_impact, worker_id)


@router.delete("/{worker_id}")
async def delete_worker(worker_id: int, request: Request, purge: bool = False):
    """직원 삭제. 이력이 있으면 purge=true 를 명시해야 하며 이력까지 영구 삭제된다(되돌릴 수 없음)."""
    return _call(svc(request).delete_worker, worker_id, purge)


@router.get("/{worker_id}")
async def worker_detail(worker_id: int, request: Request):
    v = svc(request)
    w = _call(v.get_worker, worker_id)
    with v.db.session() as s:
        tasks = [row_dict(t) for t in s.scalars(select(WorkerTask).where(WorkerTask.worker_id == worker_id).order_by(WorkerTask.id))]
    return {**_worker_row(v.db, w), "tasks": tasks, "inputs": v.workspace.list_inputs(worker_id)}


@router.put("/{worker_id}")
async def update_worker(worker_id: int, request: Request, body: dict = Body(...)):
    return row_dict(_call(svc(request).update_worker, worker_id, body))


@router.post("/{worker_id}/tasks", status_code=201)
async def create_task(worker_id: int, request: Request, body: dict = Body(...)):
    return row_dict(_call(svc(request).create_task, worker_id, body))


@router.put("/{worker_id}/inputs")
async def put_input(worker_id: int, request: Request, body: dict = Body(...)):
    """작업 공간 inputs/ 에 자료 파일을 올린다(이름·확장자는 서버가 검증)."""
    v = svc(request)
    _call(v.get_worker, worker_id)
    content = body.get("content")
    if not isinstance(content, str) or len(content) > v.settings.worker_materials_max_chars:
        raise HTTPException(422, f"content must be a string up to {v.settings.worker_materials_max_chars} chars")
    try:
        return v.workspace.write_input(worker_id, str(body.get("name", "")), content)
    except WorkspaceError as e:
        raise HTTPException(422, str(e)) from e
