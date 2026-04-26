from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

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
from ..config import get_settings
from ..services.asset_service import build_asset_summary, create_asset, list_assets, update_asset
from ..services.briefing_service import build_evening_briefing, build_morning_briefing, build_today_briefing
from ..services.capture_service import create_quick_capture, list_quick_captures
from ..services.conversation_service import list_conversations
from ..services.finance_service import build_finance_briefing
from ..services.memory_service import import_profile_yaml, list_profile_memories
from ..services.mobile_assistant_service import process_mobile_assistant_command
from ..services.natural_language_service import process_natural_command
from ..services.reminder_service import list_reminders
from ..services.routine_service import create_routine, create_routine_checkin, list_routines
from ..services.schedule_service import create_schedule, list_schedules
from ..services.task_service import create_task, list_tasks, mark_task_done

router = APIRouter()
FRONTEND_PATH = Path(__file__).resolve().parents[1] / "frontend" / "index.html"
FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"

@router.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    return FileResponse(FRONTEND_PATH)

@router.get("/{page_name}.html", include_in_schema=False)
def frontend_pages(page_name: str):
    file_path = FRONTEND_DIR / f"{page_name}.html"

    if file_path.exists():
        return FileResponse(file_path)

    raise HTTPException(status_code=404, detail="Page not found")
    
@router.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


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
