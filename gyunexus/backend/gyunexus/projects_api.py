"""개발 프로젝트·직원 프로젝트 권한 REST API. 로직은 devtools.py, 여기서는 HTTP 오류 매핑만 한다."""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Query, Request

from .devtools import DevError
from .models import row_dict

router = APIRouter(prefix="/api")
STATUS = {"validation": 422, "not_found": 404, "conflict": 409}


def dev(request: Request):
    return request.app.state.svc.dev


def _err(e: DevError) -> HTTPException:
    return HTTPException(STATUS.get(e.code, 400), str(e))


@router.get("/projects")
async def list_projects(request: Request):
    return dev(request).list_projects()


@router.post("/projects", status_code=201)
async def create_project(request: Request, body: dict = Body(...)):
    try:
        return row_dict(dev(request).create_project(body))
    except DevError as e:
        raise _err(e) from e


@router.get("/projects/changes")
async def list_changes(request: Request, run_id: int | None = None, project_id: int | None = None, limit: int = Query(100, ge=1, le=500), diff: bool = True):
    """직원이 프로젝트 파일에 적용한 변경 기록(변경 전후 해시·diff). 실행 기록(run_id)과 연결되어 나중에 검토할 수 있다."""
    return dev(request).changes(run_id=run_id, project_id=project_id, limit=limit, with_diff=diff)


@router.get("/projects/{pid}")
async def project_detail(pid: int, request: Request):
    try:
        return row_dict(dev(request).get_project(pid))
    except DevError as e:
        raise _err(e) from e


@router.put("/projects/{pid}")
async def update_project(pid: int, request: Request, body: dict = Body(...)):
    try:
        return row_dict(dev(request).update_project(pid, body))
    except DevError as e:
        raise _err(e) from e


@router.delete("/projects/{pid}")
async def delete_project(pid: int, request: Request):
    try:
        dev(request).delete_project(pid)
    except DevError as e:
        raise _err(e) from e
    return {"ok": True}


@router.get("/workers/{worker_id}/projects")
async def get_worker_projects(worker_id: int, request: Request):
    d = dev(request)
    return {"grants": d.get_grants(worker_id), "effective": d.worker_projects(worker_id)}


@router.put("/workers/{worker_id}/projects")
async def put_worker_projects(worker_id: int, request: Request, body: dict = Body(...)):
    """직원의 프로젝트 권한을 교체한다. 프로젝트가 허용하지 않은 권한은 부여할 수 없다."""
    d = dev(request)
    try:
        d.set_grants(worker_id, body.get("grants"))
    except DevError as e:
        raise _err(e) from e
    return {"grants": d.get_grants(worker_id), "effective": d.worker_projects(worker_id)}
