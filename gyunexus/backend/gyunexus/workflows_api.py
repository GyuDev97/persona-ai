"""워크플로 REST API. 로직은 workflows.py, 여기서는 HTTP 오류 매핑만 한다."""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException, Request

from .models import WorkerArtifact, row_dict
from .workers import WorkerError
from .workflows import WorkflowError

router = APIRouter(prefix="/api")
STATUS = {"validation": 422, "not_found": 404, "conflict": 409, "llm": 503, "duplicate": 409, "disabled": 409}


def svc(request: Request):
    return request.app.state.svc


def _err(e: Exception) -> HTTPException:
    return HTTPException(STATUS.get(getattr(e, "code", ""), 400), str(e))


@router.get("/workflows")
async def list_workflows(request: Request):
    return svc(request).workflows.list()


@router.post("/workflows", status_code=201)
async def create_workflow(request: Request, body: dict = Body(...)):
    """자연어 목표로 실행 계획(DAG)을 만든다. auto_run=true 를 명시한 경우에만 계획 확인 없이 바로 시작한다."""
    wf = svc(request).workflows
    try:
        wid = await wf.plan(str(body.get("goal", "")), budget=body.get("budget_usd"), auto_run=bool(body.get("auto_run", False)))
    except WorkflowError as e:
        raise _err(e) from e
    return wf.detail(wid)


@router.get("/workflows/options")
async def workflow_options(request: Request):
    """프런트엔드가 서버와 같은 예산 검증 규칙(0 초과, 상한 이하, USD)을 쓰도록 값을 내려 준다."""
    s = svc(request).settings
    return {"currency": "USD", "default_budget_usd": s.workflow_default_budget_usd, "max_budget_usd": s.workflow_max_budget_usd, "max_steps": s.workflow_max_steps}


@router.get("/workflows/{wid}")
async def workflow_detail(wid: int, request: Request):
    try:
        return svc(request).workflows.detail(wid)
    except WorkflowError as e:
        raise _err(e) from e


@router.put("/workflows/{wid}")
async def update_workflow(wid: int, request: Request, body: dict = Body(...)):
    wf = svc(request).workflows
    try:
        await wf.update_meta(wid, title=body.get("title"), budget=body.get("budget_usd"), auto_run=body.get("auto_run"))
    except WorkflowError as e:
        raise _err(e) from e
    return wf.detail(wid)


@router.put("/workflows/{wid}/plan")
async def update_plan(wid: int, request: Request, body: dict = Body(...)):
    wf = svc(request).workflows
    try:
        await wf.update_plan(wid, body.get("steps"), budget=body.get("budget_usd"))  # 예산을 함께 보내면 계획과 한 번에(전부 성공하거나 전부 실패) 반영
    except WorkflowError as e:
        raise _err(e) from e
    return wf.detail(wid)


async def _control(request: Request, wid: int, action: str, *args):
    wf = svc(request).workflows
    try:
        await getattr(wf, action)(wid, *args)
    except (WorkflowError, WorkerError) as e:
        raise _err(e) from e
    return wf.detail(wid)


@router.post("/workflows/{wid}/replan")
async def replan_workflow(wid: int, request: Request, body: dict = Body(default={})):
    """계획 생성에 실패한 워크플로의 계획을 복구한다(ID·예산 이력·비용 유지). 보관된 제안은 새 LLM 호출 없이 재검증하고, regenerate=true 면 새로 제안받는다."""
    return await _control(request, wid, "replan", bool(body.get("regenerate", False)))


@router.post("/workflows/{wid}/start")
async def start_workflow(wid: int, request: Request):
    return await _control(request, wid, "start")


@router.post("/workflows/{wid}/pause")
async def pause_workflow(wid: int, request: Request):
    return await _control(request, wid, "pause")


@router.post("/workflows/{wid}/resume")
async def resume_workflow(wid: int, request: Request):
    return await _control(request, wid, "resume")


@router.post("/workflows/{wid}/cancel")
async def cancel_workflow(wid: int, request: Request):
    return await _control(request, wid, "cancel")


@router.post("/workflows/{wid}/steps/{key}/retry")
async def retry_step(wid: int, key: str, request: Request):
    return await _control(request, wid, "retry_step", key)


# ---------- Artifact 조회(경로가 아닌 ID 로만) ----------

@router.get("/artifacts/{artifact_id}")
async def artifact_detail(artifact_id: int, request: Request):
    v = svc(request)
    with v.db.session() as s:
        art = s.get(WorkerArtifact, artifact_id)
    if art is None:
        raise HTTPException(404, "artifact not found")
    return {**row_dict(art, exclude=("rel_path",)), "content": v.workers.read_artifact(art), "version": v.workers.version_of(artifact_id)}


@router.get("/artifacts/{artifact_id}/lineage")
async def artifact_lineage(artifact_id: int, request: Request):
    try:
        return svc(request).workers.lineage(artifact_id)
    except WorkerError as e:
        raise _err(e) from e
