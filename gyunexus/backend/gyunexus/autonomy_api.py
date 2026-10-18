"""통합 자율 실행 REST API. 로직은 autonomy.py, 여기서는 HTTP 오류 매핑만 한다."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, HTTPException, Query, Request

from .models import row_dict
from .workflows import WorkflowError

router = APIRouter(prefix="/api/autonomy")
STATUS = {"validation": 422, "not_found": 404, "conflict": 409, "llm": 503}


def svc(request: Request):
    return request.app.state.svc


def _err(e: Exception) -> HTTPException:
    return HTTPException(STATUS.get(getattr(e, "code", ""), 400), str(e))


@router.get("/settings")
async def get_settings(request: Request):
    return svc(request).autonomy.full_config()


@router.put("/settings")
async def put_settings(request: Request, body: dict = Body(...)):
    try:
        return await svc(request).autonomy.set_config(enabled=body.get("enabled"), max_mode=body.get("max_mode"), auto_approve=body.get("auto_approve"),
                                                      max_concurrent=body.get("max_concurrent"), daily_cost_cap_usd=body.get("daily_cost_cap_usd"))
    except WorkflowError as e:
        raise _err(e) from e


@router.get("/overview")
async def overview(request: Request):
    return svc(request).autonomy.overview()


@router.get("/triggers")
async def list_triggers(request: Request):
    return svc(request).autonomy.list_triggers()


@router.post("/triggers", status_code=201)
async def create_trigger(request: Request, body: dict = Body(...)):
    a = svc(request).autonomy
    try:
        return a.trigger_view(a.create_trigger(body))
    except WorkflowError as e:
        raise _err(e) from e


@router.put("/triggers/{tid}")
async def update_trigger(tid: int, request: Request, body: dict = Body(...)):
    a = svc(request).autonomy
    try:
        return a.trigger_view(a.update_trigger(tid, body))
    except WorkflowError as e:
        raise _err(e) from e


@router.delete("/triggers/{tid}")
async def delete_trigger(tid: int, request: Request):
    try:
        svc(request).autonomy.delete_trigger(tid)
    except WorkflowError as e:
        raise _err(e) from e
    return {"ok": True}


@router.post("/triggers/{tid}/fire")
async def fire_trigger(tid: int, request: Request):
    """사용자가 트리거를 지금 발동시킨다. 전체 ON/OFF·쿨다운·중복·동시 실행·비용 한도 검사는 예약 발동과 똑같이 적용된다."""
    a = svc(request).autonomy
    try:
        a.get_trigger(tid)
        return await a.fire(tid, reason="사용자가 수동으로 발동", slot=f"t{tid}:manual:{uuid.uuid4().hex[:12]}")  # 클릭마다 고유(같은 클릭의 재전송만 막을 필요는 없다)
    except WorkflowError as e:
        raise _err(e) from e


@router.get("/runs")
async def list_runs(request: Request, limit: int = Query(50, ge=1, le=200)):
    return svc(request).autonomy.list_runs(limit)


@router.post("/events")
async def emit_event(request: Request, body: dict = Body(...)):
    """등록된 이벤트(트리거의 event 이름)를 알린다. 같은 key 의 이벤트는 한 번만 처리된다."""
    a = svc(request).autonomy
    try:
        return {"results": await a.emit_event(str(body.get("name", "")), body.get("key"))}
    except WorkflowError as e:
        raise _err(e) from e


@router.put("/workflows/{wid}/mode")
async def set_mode(wid: int, request: Request, body: dict = Body(...)):
    v = svc(request)
    try:
        await v.autonomy.set_mode(wid, str(body.get("exec_mode", "")))
    except WorkflowError as e:
        raise _err(e) from e
    return v.workflows.detail(wid)
