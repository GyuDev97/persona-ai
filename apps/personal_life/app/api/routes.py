from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..domain.schemas import (
    AgentTaskClaimRequest,
    AgentTaskCompleteRequest,
    AgentTaskFailRequest,
    AgentTaskResponse,
    AssetCreate,
    AssetResponse,
    AssetSummaryResponse,
    AssetUpdate,
    AssistantStatusResponse,
    BriefingDigestResponse,
    BriefingResponse,
    ConversationMessageResponse,
    FinanceBriefingResponse,
    MobileAssistantCommandCreate,
    MobileAssistantCommandResponse,
    NaturalCommandCreate,
    NaturalCommandResponse,
    ProfileMemoryImportRequest,
    ProfileMemoryImportResponse,
    ProfileMemoryRecord,
    QuickCaptureCreate,
    QuickCaptureResponse,
    RoutineCheckinResponse,
    RoutineCreate,
    RoutineResponse,
    ReminderResponse,
    ScheduleCreate,
    ScheduleResponse,
    TaskCreate,
    TaskResponse,
)
from ..services.agent_task_service import (
    claim_next_agent_task,
    complete_agent_task,
    fail_agent_task,
    get_agent_task,
    list_agent_tasks,
)
from ..services.agent_definition_service import (
    create_agent_definition,
    disable_agent_definition,
    get_agent_definition,
    list_agent_definitions,
    update_agent_definition,
)
from ..services.agent_report_center_service import build_agent_report_center, create_naver_blog_fill_task
from ..services.agent_standby_service import focus_agent, get_agent_standby_status, open_agent_detail, recover_agent
from ..services.agent3_dev_planner_ai_service import generate_ai_dev_proposal
from ..config import get_settings
from ..services.asset_service import build_asset_summary, create_asset, list_assets, update_asset
from ..services.blog_draft_service import get_blog_draft
from ..services.briefing_service import build_evening_briefing, build_morning_briefing, build_today_briefing
from ..services.capture_service import create_quick_capture, list_quick_captures
from ..services.conversation_service import list_conversations
from ..services.dev_planner_service import (
    approve_dev_proposal,
    create_dev_project,
    create_dev_proposal,
    get_dev_proposal,
    list_dev_projects,
    list_dev_proposals,
    scan_dev_project,
    update_dev_proposal_code_preview,
    update_dev_proposal_status,
)
from ..services.finance_service import build_finance_briefing
from ..services.memory_service import import_profile_yaml, list_profile_memories
from ..services.mobile_assistant_service import process_mobile_assistant_command
from ..services.money_core_service import (
    build_money_core_summary,
    create_auto_transfer,
    create_card_usage,
    create_expense,
    create_installment,
    delete_money_core_item,
    list_assets_history,
    list_auto_transfer,
    list_card_usage,
    list_expenses,
    list_installments,
    save_asset_history,
    save_income_summary,
    update_auto_transfer,
    update_card_usage,
    update_expense,
    update_installment,
)
from ..services.money_ai_chat_service import ask_money_core_ai
from ..services.natural_language_service import process_natural_command
from ..services.reminder_service import list_reminders
from ..services.routine_service import create_routine, create_routine_checkin, list_routines
from ..services.schedule_service import create_schedule, list_schedules
from ..services.system_status_service import build_system_status
from ..services.subtitle_service import get_subtitles, update_subtitles
from ..services.task_service import create_task, list_tasks, mark_task_done

router = APIRouter()
FRONTEND_PATH = Path(__file__).resolve().parents[1] / "frontend" / "index.html"
FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
MOBILE_FRONTEND_DIR = FRONTEND_DIR / "mobile"
GYUVIS_HUD_DIR = Path(__file__).resolve().parents[3] / "javis-app"
GYUVIS_STANDBY_V2_PATH = GYUVIS_HUD_DIR / "standby-v2.html"
GYUVIS_STANDBY_V3_PATH = GYUVIS_HUD_DIR / "standby-v3.html"
AGENT_REPORT_CENTER_PATH = FRONTEND_DIR / "agent_report_center.html"
MONEY_CORE_PATH = FRONTEND_DIR / "money_core.html"


class AssistantSubtitleUpdate(BaseModel):
    input: str | None = None
    output: str | None = None


class AgentDefinitionPayload(BaseModel):
    title: str
    description: str = ""
    task_types: list[str] | str = ""
    status: str = "대기"
    processing: str = "대기중"
    tone: str = "idle"
    sort_order: int = 100
    is_enabled: bool = True


class DevProjectPayload(BaseModel):
    name: str
    root_path: str
    description: str = ""
    stack: str = ""
    status: str = "active"


class DevProposalPayload(BaseModel):
    project_id: int | None = None
    title: str
    summary: str = ""
    reason: str = ""
    change_type: str = "modify"
    affected_files: list[str] | str = []
    target_files: list[str] | str = []
    risk_level: str = "low"
    code_preview: str = ""
    diff_preview: str = ""


class DevProposalCodePreviewPayload(BaseModel):
    affected_file: str
    generated_code: str


class DevProposalAiGeneratePayload(BaseModel):
    request: str
    project_id: int | None = None
    candidate_files: list[str] | str = []


class DevProposalStatusPayload(BaseModel):
    status: str


class MoneyAiChatPayload(BaseModel):
    question: str
    month: str | None = None


@router.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    return FileResponse(FRONTEND_PATH)

@router.get("/{page_name}.html", include_in_schema=False)
def frontend_pages(page_name: str):
    file_path = FRONTEND_DIR / f"{page_name}.html"

    if file_path.exists():
        return FileResponse(file_path)

    raise HTTPException(status_code=404, detail="Page not found")


@router.get("/mobile/{page_name}.html", include_in_schema=False)
def mobile_frontend_pages(page_name: str):
    file_path = MOBILE_FRONTEND_DIR / f"{page_name}.html"

    if file_path.exists():
        return FileResponse(file_path)

    raise HTTPException(status_code=404, detail="Mobile page not found")


@router.get("/gyuvis/standby-v2", include_in_schema=False)
def gyuvis_standby_v2() -> FileResponse:
    if not GYUVIS_STANDBY_V2_PATH.exists():
        raise HTTPException(status_code=404, detail="GYUVIS standby UI not found")

    return FileResponse(GYUVIS_STANDBY_V2_PATH)


@router.get("/gyuvis/standby-v3", include_in_schema=False)
def gyuvis_standby_v3() -> FileResponse:
    if not GYUVIS_STANDBY_V3_PATH.exists():
        raise HTTPException(status_code=404, detail="GYUVIS standby V3 UI not found")

    return FileResponse(
        GYUVIS_STANDBY_V3_PATH,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@router.get("/agent/report-center", include_in_schema=False)
def agent_report_center_page() -> FileResponse:
    if not AGENT_REPORT_CENTER_PATH.exists():
        raise HTTPException(status_code=404, detail="Agent Report Center not found")

    return FileResponse(AGENT_REPORT_CENTER_PATH)


@router.get("/money-core", include_in_schema=False)
def money_core_page() -> FileResponse:
    if not MONEY_CORE_PATH.exists():
        raise HTTPException(status_code=404, detail="Money Core page not found")

    return FileResponse(MONEY_CORE_PATH)
    
@router.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@router.get("/system/status")
def get_system_status() -> dict:
    return build_system_status()


@router.get("/assistant/status", response_model=AssistantStatusResponse)
def get_assistant_status() -> AssistantStatusResponse:
    settings = get_settings()
    return AssistantStatusResponse(
        ai_enabled=settings.has_openai,
        mode="openai" if settings.has_openai else "fallback",
        model=settings.openai_model if settings.has_openai else None,
    )


@router.get("/briefing/today", response_model=BriefingResponse)
def get_today_briefing() -> BriefingResponse:
    return build_today_briefing()


@router.get("/briefing/morning", response_model=BriefingDigestResponse)
def get_morning_briefing() -> BriefingDigestResponse:
    return build_morning_briefing()


@router.get("/briefing/evening", response_model=BriefingDigestResponse)
def get_evening_briefing() -> BriefingDigestResponse:
    return build_evening_briefing()


@router.get("/finance/briefing", response_model=FinanceBriefingResponse)
def get_finance_briefing() -> FinanceBriefingResponse:
    return build_finance_briefing()


@router.get("/finance/summary")
def get_money_core_summary(month: str | None = None) -> dict:
    return build_money_core_summary(month)


@router.post("/finance/summary")
def post_money_core_summary(payload: dict) -> dict:
    try:
        return save_income_summary(payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/finance/ai-chat")
def post_money_core_ai_chat(payload: MoneyAiChatPayload) -> dict:
    try:
        return ask_money_core_ai(payload.question, payload.month)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/finance/expenses")
def get_money_core_expenses(month: str | None = None) -> list[dict]:
    return list_expenses(month)


@router.post("/finance/expenses")
def post_money_core_expense(payload: dict) -> dict:
    try:
        return create_expense(payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.put("/finance/expenses/{item_id}")
def put_money_core_expense(item_id: int, payload: dict) -> dict:
    try:
        return update_expense(item_id, payload)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.delete("/finance/expenses/{item_id}")
def delete_money_core_expense(item_id: int) -> dict:
    try:
        return delete_money_core_item("expenses", item_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/finance/card")
def get_money_core_card(month: str | None = None) -> list[dict]:
    return list_card_usage(month)


@router.post("/finance/card")
def post_money_core_card(payload: dict) -> dict:
    try:
        return create_card_usage(payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.put("/finance/card/{item_id}")
def put_money_core_card(item_id: int, payload: dict) -> dict:
    try:
        return update_card_usage(item_id, payload)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.delete("/finance/card/{item_id}")
def delete_money_core_card(item_id: int) -> dict:
    try:
        return delete_money_core_item("card_usage", item_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/finance/installments")
def get_money_core_installments(month: str | None = None) -> list[dict]:
    return list_installments(month)


@router.post("/finance/installments")
def post_money_core_installment(payload: dict) -> dict:
    try:
        return create_installment(payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.put("/finance/installments/{item_id}")
def put_money_core_installment(item_id: int, payload: dict) -> dict:
    try:
        return update_installment(item_id, payload)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.delete("/finance/installments/{item_id}")
def delete_money_core_installment(item_id: int) -> dict:
    try:
        return delete_money_core_item("installments", item_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/finance/assets")
def get_money_core_assets() -> list[dict]:
    return list_assets_history()


@router.post("/finance/assets")
def post_money_core_asset(payload: dict) -> dict:
    try:
        return save_asset_history(payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/finance/auto-transfer")
def get_money_core_auto_transfer() -> list[dict]:
    return list_auto_transfer()


@router.post("/finance/auto-transfer")
def post_money_core_auto_transfer(payload: dict) -> dict:
    try:
        return create_auto_transfer(payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.put("/finance/auto-transfer/{item_id}")
def put_money_core_auto_transfer(item_id: int, payload: dict) -> dict:
    try:
        return update_auto_transfer(item_id, payload)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.delete("/finance/auto-transfer/{item_id}")
def delete_money_core_auto_transfer(item_id: int) -> dict:
    try:
        return delete_money_core_item("auto_transfer", item_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/assets", response_model=AssetResponse)
def post_asset(payload: AssetCreate) -> AssetResponse:
    return create_asset(payload)


@router.get("/assets", response_model=list[AssetResponse])
def get_assets(limit: int = 100) -> list[AssetResponse]:
    return list_assets(limit=limit)


@router.get("/assets/summary", response_model=AssetSummaryResponse)
def get_asset_summary() -> AssetSummaryResponse:
    return build_asset_summary()


@router.put("/assets/{asset_id}", response_model=AssetResponse)
def put_asset(asset_id: int, payload: AssetUpdate) -> AssetResponse:
    asset = update_asset(asset_id, payload)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


@router.post("/commands/natural", response_model=NaturalCommandResponse)
def post_natural_command(payload: NaturalCommandCreate) -> NaturalCommandResponse:
    return process_natural_command(payload)


@router.post("/mobile/assistant/command", response_model=MobileAssistantCommandResponse)
def post_mobile_assistant_command(payload: MobileAssistantCommandCreate) -> MobileAssistantCommandResponse:
    return process_mobile_assistant_command(payload)


@router.get("/agent/tasks", response_model=list[AgentTaskResponse])
def get_agent_tasks(status: str | None = None, limit: int = 20) -> list[AgentTaskResponse]:
    return list_agent_tasks(status=status, limit=limit)


@router.get("/agent/tasks/{task_id}", response_model=AgentTaskResponse)
def get_agent_task_detail(task_id: int) -> AgentTaskResponse:
    try:
        return get_agent_task(task_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/agent/tasks/claim", response_model=AgentTaskResponse | None)
def post_agent_task_claim(payload: AgentTaskClaimRequest) -> AgentTaskResponse | None:
    return claim_next_agent_task(payload.device_label)


@router.post("/agent/tasks/{task_id}/complete", response_model=AgentTaskResponse)
def post_agent_task_complete(task_id: int, payload: AgentTaskCompleteRequest) -> AgentTaskResponse:
    return complete_agent_task(task_id, payload.summary, payload.payload)


@router.post("/agent/tasks/{task_id}/fail", response_model=AgentTaskResponse)
def post_agent_task_fail(task_id: int, payload: AgentTaskFailRequest) -> AgentTaskResponse:
    return fail_agent_task(task_id, payload.error_message)


@router.get("/agent/standby-status")
def get_agent_standby_status_route() -> dict:
    return get_agent_standby_status()


@router.get("/agent/report-center/data")
def get_agent_report_center_data() -> dict:
    return build_agent_report_center()


@router.get("/agent/dev-projects")
def get_agent_dev_projects() -> list[dict]:
    return list_dev_projects()


@router.post("/agent/dev-projects")
def post_agent_dev_project(payload: DevProjectPayload) -> dict:
    try:
        return create_dev_project(payload.dict())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/agent/dev-projects/{project_id}/scan")
def post_agent_dev_project_scan(project_id: int) -> dict:
    try:
        return scan_dev_project(project_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/agent/dev-proposals")
def get_agent_dev_proposals(status: str | None = None, limit: int = 20) -> list[dict]:
    return list_dev_proposals(status=status, limit=limit)


@router.get("/agent/dev-proposals/{proposal_id}")
def get_agent_dev_proposal_detail(proposal_id: int) -> dict:
    try:
        return get_dev_proposal(proposal_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/agent/dev-proposals")
def post_agent_dev_proposal(payload: DevProposalPayload) -> dict:
    try:
        return create_dev_proposal(payload.dict())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/agent/dev-proposals/{proposal_id}/approve")
def post_agent_dev_proposal_approve(proposal_id: int) -> dict:
    try:
        return approve_dev_proposal(proposal_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/agent/dev-proposals/{proposal_id}/code-preview")
def post_agent_dev_proposal_code_preview(proposal_id: int, payload: DevProposalCodePreviewPayload) -> dict:
    try:
        return update_dev_proposal_code_preview(
            proposal_id,
            affected_file=payload.affected_file,
            generated_code=payload.generated_code,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/agent/dev-proposals/ai-generate")
def post_agent_dev_proposal_ai_generate(payload: DevProposalAiGeneratePayload) -> dict:
    try:
        return generate_ai_dev_proposal(payload.dict())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/agent/dev-proposals/{proposal_id}/status")
def post_agent_dev_proposal_status(proposal_id: int, payload: DevProposalStatusPayload) -> dict:
    try:
        return update_dev_proposal_status(proposal_id, payload.status)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/agent/blog-drafts/{draft_id}")
def get_agent_blog_draft_detail(draft_id: int) -> dict:
    try:
        draft = get_blog_draft(draft_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {
        "id": int(draft.get("id")),
        "title": draft.get("title"),
        "body": draft.get("body"),
        "status": draft.get("status"),
        "platform": draft.get("platform"),
        "created_at": str(draft.get("created_at")) if draft.get("created_at") is not None else None,
        "updated_at": str(draft.get("updated_at")) if draft.get("updated_at") is not None else None,
    }


@router.get("/agent/definitions")
def get_agent_definitions(include_disabled: bool = False) -> list[dict]:
    return list_agent_definitions(include_disabled=include_disabled)


@router.get("/agent/definitions/{agent_id}")
def get_agent_definition_route(agent_id: int) -> dict:
    try:
        return get_agent_definition(agent_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/agent/definitions")
def post_agent_definition(payload: AgentDefinitionPayload) -> dict:
    try:
        return create_agent_definition(payload.dict())
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.put("/agent/definitions/{agent_id}")
def put_agent_definition(agent_id: int, payload: AgentDefinitionPayload) -> dict:
    try:
        return update_agent_definition(agent_id, payload.dict())
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.delete("/agent/definitions/{agent_id}")
def delete_agent_definition(agent_id: int) -> dict:
    try:
        return disable_agent_definition(agent_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/agent/blog-drafts/{draft_id}/fill")
def post_agent_blog_draft_fill(draft_id: int) -> dict:
    try:
        return create_naver_blog_fill_task(draft_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/agent/standby-status/focus/{agent_id}")
def post_agent_standby_focus(agent_id: int) -> dict:
    return focus_agent(agent_id if agent_id > 0 else None)


@router.post("/agent/standby-status/detail/{agent_id}")
def post_agent_standby_detail(agent_id: int) -> dict:
    return open_agent_detail(agent_id if agent_id > 0 else None)


@router.post("/agent/standby-status/recover/{agent_id}")
def post_agent_standby_recover(agent_id: int) -> dict:
    return recover_agent(agent_id if agent_id > 0 else None)


@router.get("/assistant/subtitles")
def get_assistant_subtitles() -> dict:
    return get_subtitles()


@router.post("/assistant/subtitles")
def post_assistant_subtitles(payload: AssistantSubtitleUpdate) -> dict:
    return update_subtitles(input_text=payload.input, output_text=payload.output)


@router.get("/conversations", response_model=list[ConversationMessageResponse])
def get_conversations(limit: int = 20) -> list[ConversationMessageResponse]:
    return list_conversations(limit=limit)


@router.get("/reminders", response_model=list[ReminderResponse])
def get_reminders(status: str = "scheduled", limit: int = 20) -> list[ReminderResponse]:
    return list_reminders(status=status, limit=limit)


@router.post("/memories/import-profile", response_model=ProfileMemoryImportResponse)
def post_profile_memory_import(payload: ProfileMemoryImportRequest) -> ProfileMemoryImportResponse:
    return import_profile_yaml(payload.yaml_text)


@router.get("/memories/profile", response_model=list[ProfileMemoryRecord])
def get_profile_memories() -> list[ProfileMemoryRecord]:
    return list_profile_memories()


@router.post("/captures", response_model=QuickCaptureResponse)
def post_quick_capture(payload: QuickCaptureCreate) -> QuickCaptureResponse:
    return create_quick_capture(payload)


@router.get("/captures", response_model=list[QuickCaptureResponse])
def get_quick_captures(limit: int = 20) -> list[QuickCaptureResponse]:
    return list_quick_captures(limit=limit)


@router.post("/tasks", response_model=TaskResponse)
def post_task(payload: TaskCreate) -> TaskResponse:
    return create_task(payload)


@router.get("/tasks", response_model=list[TaskResponse])
def get_tasks(status: str = "open") -> list[TaskResponse]:
    return list_tasks(status=status)


@router.post("/tasks/{task_id}/done", response_model=TaskResponse)
def complete_task(task_id: int) -> TaskResponse:
    task = mark_task_done(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/schedules", response_model=ScheduleResponse)
def post_schedule(payload: ScheduleCreate) -> ScheduleResponse:
    return create_schedule(payload)


@router.get("/schedules", response_model=list[ScheduleResponse])
def get_schedules(day: str | None = None) -> list[ScheduleResponse]:
    return list_schedules(day=day)


@router.post("/routines", response_model=RoutineResponse)
def post_routine(payload: RoutineCreate) -> RoutineResponse:
    return create_routine(payload)


@router.get("/routines", response_model=list[RoutineResponse])
def get_routines(active_only: bool = True) -> list[RoutineResponse]:
    return list_routines(active_only=active_only)


@router.post("/routines/{routine_id}/checkins", response_model=RoutineCheckinResponse)
def post_routine_checkin(routine_id: int, day: str, status: str = "done") -> RoutineCheckinResponse:
    checkin = create_routine_checkin(routine_id=routine_id, day=day, status=status)
    if checkin is None:
        raise HTTPException(status_code=404, detail="Routine not found")
    return checkin
