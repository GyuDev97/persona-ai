from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


CaptureType = Literal["note", "expense", "idea", "journal", "routine", "task"]
TaskStatus = Literal["open", "done"]
RoutineStatus = Literal["pending", "done", "skipped"]
ReminderStatus = Literal["scheduled", "sent", "dismissed"]
ConversationRole = Literal["user", "assistant"]
AgentTaskStatus = Literal["pending", "claimed", "completed", "failed"]


class QuickCaptureCreate(BaseModel):
    capture_type: CaptureType = Field(
        default="note",
        description="Category of the captured item.",
    )
    content: str = Field(min_length=1, max_length=2000)
    source: str = Field(default="manual", max_length=100)


class QuickCaptureResponse(BaseModel):
    id: int
    capture_type: CaptureType
    content: str
    source: str
    created_at: datetime


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    details: str = Field(default="", max_length=2000)
    due_date: str | None = Field(
        default=None,
        description="Optional due date in YYYY-MM-DD format.",
    )
    priority: int = Field(default=2, ge=1, le=3)


class TaskResponse(BaseModel):
    id: int
    title: str
    details: str
    due_date: str | None
    priority: int
    status: TaskStatus
    created_at: datetime
    completed_at: datetime | None


class ScheduleCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    details: str = Field(default="", max_length=2000)
    scheduled_for: str = Field(
        description="Schedule date in YYYY-MM-DD format.",
    )
    start_time: str | None = Field(
        default=None,
        description="Optional start time in HH:MM format.",
    )


class ScheduleResponse(BaseModel):
    id: int
    title: str
    details: str
    scheduled_for: str
    start_time: str | None
    created_at: datetime


class AssetCreate(BaseModel):
    asset_name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    current_value: int = Field(ge=0)
    as_of_date: str | None = Field(default=None, description="Optional YYYY-MM-DD date.")
    notes: str = Field(default="", max_length=2000)


class AssetUpdate(BaseModel):
    asset_name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    current_value: int = Field(ge=0)
    as_of_date: str | None = Field(default=None, description="Optional YYYY-MM-DD date.")
    notes: str = Field(default="", max_length=2000)


class AssetResponse(BaseModel):
    id: int
    asset_name: str
    category: str
    current_value: int
    as_of_date: str | None
    notes: str
    created_at: datetime
    updated_at: datetime


class AssetCategorySummary(BaseModel):
    category: str
    total_value: int
    ratio: float


class AssetTrendPoint(BaseModel):
    snapshot_date: str
    total_value: int


class AssetSummaryResponse(BaseModel):
    total_assets: int
    categories: list[AssetCategorySummary]
    latest_change_amount: int
    latest_change_rate: float
    trend: list[AssetTrendPoint]


class RoutineCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    frequency: str = Field(default="daily", max_length=50)


class RoutineResponse(BaseModel):
    id: int
    name: str
    description: str
    frequency: str
    is_active: bool
    created_at: datetime


class RoutineCheckinResponse(BaseModel):
    id: int
    routine_id: int
    routine_name: str
    checkin_date: str
    status: RoutineStatus
    created_at: datetime


class NaturalCommandCreate(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class NaturalCommandResponse(BaseModel):
    text: str
    interpreted_as: Literal["task", "schedule", "capture", "answer", "desktop_action", "briefing"]
    summary: str
    created_id: int
    created_type: str
    reminder_id: int | None = None


class AssistantStatusResponse(BaseModel):
    ai_enabled: bool
    mode: Literal["openai", "fallback"]
    model: str | None


class HomeArrivalEventCreate(BaseModel):
    source: str = Field(min_length=1, max_length=100)
    event: Literal["home_arrival"]
    person: Literal["owner"]
    confidence: float = Field(ge=0, le=1)
    timestamp: datetime


class PostureWarningEventCreate(BaseModel):
    type: Literal["head_down", "forward_head"]
    duration_seconds: float = Field(ge=0, le=3600)
    score: float = Field(ge=0, le=1)
    timestamp: datetime


RidingEventType = Literal[
    "LONG_CLIMB_STARTED",
    "PACE_DROPPED",
    "FAST_DESCENT",
    "DANGER_APPROACH",
    "RIDE_MILESTONE",
]
RidingPriority = Literal["critical", "high", "normal", "low"]


class RidingContext(BaseModel):
    """TrailGo's extensible, unit-defined riding measurements.

    Speed values are km/h, elevation gain and ride distance are meters, and
    duration values are seconds. Future non-location fields are accepted so a
    TrailGo release can add context without breaking this endpoint.
    """

    model_config = ConfigDict(extra="allow")

    current_speed: float | None = Field(default=None, ge=0, le=200)
    current_altitude: float | None = Field(default=None, ge=-1_000, le=15_000)
    avg_speed_1m: float | None = Field(default=None, ge=0, le=200)
    avg_speed_5m: float | None = Field(default=None, ge=0, le=200)
    avg_speed_10m: float | None = Field(default=None, ge=0, le=200)
    climb_duration_sec: int | None = Field(default=None, ge=0, le=86_400)
    descent_duration_sec: int | None = Field(default=None, ge=0, le=86_400)
    elevation_gain: float | None = Field(default=None, ge=0, le=20_000)
    total_elevation_gain: float | None = Field(default=None, ge=0, le=50_000)
    ride_distance: float | None = Field(default=None, ge=0, le=2_000_000)
    ride_duration_sec: int | None = Field(default=None, ge=0, le=172_800)
    ride_state: str | None = Field(default=None, min_length=1, max_length=64)
    estimated_grade: float | None = Field(default=None, ge=-100, le=100)
    nearest_danger_distance: float | None = Field(default=None, ge=0, le=100_000)
    danger_id: str | None = Field(default=None, min_length=1, max_length=128)


class RidingEventCreate(BaseModel):
    # Optional during TrailGo's contract rollout. Requests without a ride_id
    # retain the legacy shared cooldown scope until TrailGo starts sending it.
    ride_id: str | None = Field(default=None, min_length=1, max_length=128)
    event_id: str | None = Field(default=None, min_length=1, max_length=128)
    event_type: RidingEventType
    timestamp: datetime
    ride_context: RidingContext


class RidingEventResponse(BaseModel):
    speak: bool
    message: str | None
    priority: RidingPriority
    cooldown_sec: int = Field(ge=0)


class ProfileMemoryRecord(BaseModel):
    id: int
    category: str
    memory_key: str
    value_text: str
    value_type: str
    confidence: str
    memory_kind: str
    source: str
    created_at: datetime
    updated_at: datetime


class ProfileMemoryImportRequest(BaseModel):
    yaml_text: str = Field(min_length=1)


class ProfileMemoryImportResponse(BaseModel):
    imported_count: int
    categories: list[str]
    message: str


class BriefingInsight(BaseModel):
    title: str
    body: str


class AssistantOpinion(BaseModel):
    title: str
    body: str
    reason: str


class ReminderResponse(BaseModel):
    id: int
    title: str
    details: str
    remind_on: str
    remind_time: str | None
    status: ReminderStatus
    origin_type: str
    origin_id: int | None
    created_at: datetime
    notified_at: datetime | None


class ConversationMessageResponse(BaseModel):
    id: int
    role: ConversationRole
    message: str
    interpreted_as: str | None
    created_type: str | None
    created_at: datetime


class AgentTaskResponse(BaseModel):
    id: int
    source: str
    command_text: str
    task_type: str
    search_query: str | None
    status: AgentTaskStatus
    device_label: str | None
    claimed_at: datetime | None
    completed_at: datetime | None
    result_summary: str | None
    result_payload: str | None
    error_message: str | None
    created_at: datetime


class MobileAssistantCommandCreate(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    source: str = Field(default="mobile", max_length=30)

class MobileAssistantCommandResponse(BaseModel):
    mode: Literal["assistant_reply", "agent_task"]
    spoken_text: str
    summary: str
    task: AgentTaskResponse | None = None


class AgentTaskClaimRequest(BaseModel):
    device_label: str = Field(min_length=1, max_length=100)


class AgentTaskCompleteRequest(BaseModel):
    summary: str = Field(min_length=1, max_length=4000)
    payload: dict = Field(default_factory=dict)


class AgentTaskFailRequest(BaseModel):
    error_message: str = Field(min_length=1, max_length=2000)


class BriefingDigestResponse(BaseModel):
    period: Literal["morning", "evening"]
    headline: str
    bullets: list[str]


class FinanceBriefingResponse(BaseModel):
    source_month: str
    target_sheet: str
    headline: str
    bullets: list[str]
    monthly_income: int
    monthly_savings: int
    fixed_cost: int
    check_card_spend: int
    credit_card_spend: int
    monthly_spend_total: int
    remaining_cash: int
    savings_rate: float
    spending_rate: float
    credit_limit: int
    credit_over_limit: int
    current_cash_goal_year: int | None
    current_cash_goal_amount: int | None


class BriefingResponse(BaseModel):
    today: str
    open_task_count: int
    completed_today_count: int
    capture_count_today: int
    schedule_count_today: int
    completed_routine_count: int
    total_routine_count: int
    top_tasks: list[TaskResponse]
    schedules: list[ScheduleResponse]
    routine_checkins: list[RoutineCheckinResponse]
    message: str
    insights: list[BriefingInsight]
    opinions: list[AssistantOpinion]
