import asyncio
import json

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from .agents.orchestrator import Busy, DuplicateTopic
from .memory import KINDS
from .models import (
    ActivityLog,
    Agent,
    Approval,
    Conversation,
    Debate,
    DebateMessage,
    Evidence,
    Idea,
    Memory,
    Message,
    Reminder,
    Suggestion,
    Topic,
    row_dict,
)
from .runtime_settings import set_value
from .suggestions import TOPIC_LABELS, parse_quiet, set_prefs

router = APIRouter(prefix="/api")


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: int | None = None


class MemoryIn(BaseModel):
    kind: str = "fact"
    content: str = Field(min_length=1, max_length=500)
    importance: int = Field(5, ge=1, le=10)


class RunIn(BaseModel):
    topic: str | None = Field(None, min_length=3, max_length=300)


class SettingsIn(BaseModel):
    autonomous_enabled: bool | None = None
    debate_interval_minutes: int | None = Field(None, ge=5, le=10080)


def svc(request: Request):
    return request.app.state.svc


def _effective_settings(v) -> dict:
    return {
        "autonomous_enabled": v.scheduler.autonomous_enabled(),
        "debate_interval_minutes": v.scheduler.interval_minutes(),
        "daily_budget_usd": v.settings.daily_budget_usd,
        "spent_today_usd": round(v.llm.spent_today(), 4),
        "llm_configured": v.llm.configured,
        "model": v.llm.model,
        "debate_running": v.orchestrator.busy,
    }


@router.get("/health")
async def health(request: Request):
    return {"status": "ok", **_effective_settings(svc(request))}


# ---------- GYUVIS ----------


@router.post("/chat")
async def chat(body: ChatIn, request: Request):
    try:
        return await svc(request).conversation.chat(body.message, body.conversation_id)
    except KeyError:
        raise HTTPException(404, "conversation not found")


@router.get("/conversations")
async def conversations(request: Request):
    with svc(request).db.session() as s:
        return [row_dict(c) for c in s.scalars(select(Conversation).order_by(Conversation.updated_at.desc()))]


@router.get("/conversations/{conv_id}/messages")
async def messages(conv_id: int, request: Request):
    with svc(request).db.session() as s:
        if s.get(Conversation, conv_id) is None:
            raise HTTPException(404, "conversation not found")
        return [row_dict(m) for m in s.scalars(select(Message).where(Message.conversation_id == conv_id).order_by(Message.id))]


@router.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: int, request: Request):
    with svc(request).db.session() as s:
        conv = s.get(Conversation, conv_id)
        if conv is None:
            raise HTTPException(404, "conversation not found")
        for m in s.scalars(select(Message).where(Message.conversation_id == conv_id)):
            s.delete(m)
        s.delete(conv)
    return {"ok": True}


@router.get("/memories")
async def memories(request: Request):
    return [row_dict(m) for m in svc(request).memory.all()]


@router.post("/memories", status_code=201)
async def add_memory(body: MemoryIn, request: Request):
    if body.kind not in KINDS:
        raise HTTPException(422, f"kind must be one of {KINDS}")
    m, _ = svc(request).memory.add(body.kind, body.content, body.importance, source="manual")
    return row_dict(m)


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: int, request: Request):
    if not svc(request).memory.delete(memory_id):
        raise HTTPException(404, "memory not found")
    return {"ok": True}


@router.post("/context/activity")
async def activity_heartbeat(request: Request):
    v = svc(request)
    hb = v.context.heartbeat()
    if hb["returned"] and v.llm.configured and v.scheduler.autonomous_enabled():
        task = asyncio.create_task(v.proactive.on_event("dashboard_opened"))
        v.background.add(task)
        task.add_done_callback(v.background.discard)
    return hb


@router.get("/context")
async def context(request: Request):
    return svc(request).context.snapshot()


@router.post("/proactive/check")
async def proactive_check(request: Request):
    """지금 즉시 능동 제안을 평가한다(접속 여부, 쿨다운, 일일 한도는 그대로 적용)."""
    v = svc(request)
    if not v.llm.configured:
        raise HTTPException(503, "OPENAI_API_KEY is not set")
    msg = await v.proactive.maybe_suggest("manual_check")
    return {"suggested": msg is not None, "message": msg}


class ProactiveSettingsIn(BaseModel):
    enabled: bool | None = None
    daily_max: int | None = Field(None, ge=0, le=20)
    quiet_hours: str | None = Field(None, max_length=11)  # "23:00-07:00", 빈 문자열이면 조용한 시간 없음
    topics: dict[str, bool] | None = None


@router.get("/proactive/settings")
async def proactive_settings(request: Request):
    v = svc(request)
    return {**v.proactive.prefs(), "topic_labels": TOPIC_LABELS}


@router.put("/proactive/settings")
async def put_proactive_settings(body: ProactiveSettingsIn, request: Request):
    v = svc(request)
    if body.quiet_hours not in (None, "") and parse_quiet(body.quiet_hours) is None:
        raise HTTPException(422, "quiet_hours must look like 23:00-07:00 (or empty)")
    if body.topics and set(body.topics) - set(TOPIC_LABELS):
        raise HTTPException(422, f"unknown topic; allowed: {list(TOPIC_LABELS)}")
    set_prefs(v.db, enabled=body.enabled, daily_max=body.daily_max, quiet_hours=body.quiet_hours, topics=body.topics)
    v.activity.record("system", "proactive.settings_changed", **body.model_dump(exclude_none=True))
    return {**v.proactive.prefs(), "topic_labels": TOPIC_LABELS}


@router.get("/proactive/suggestions")
async def proactive_suggestions(request: Request, limit: int = Query(50, ge=1, le=200)):
    """제안 후보와 판단 기록(점수 구성, 게이트, 이유, 사용자 반응). 나중에 판단을 검증하는 용도."""
    with svc(request).db.session() as s:
        return [row_dict(r) for r in s.scalars(select(Suggestion).order_by(Suggestion.id.desc()).limit(limit))]


@router.get("/proactive/reminders")
async def proactive_reminders(request: Request):
    with svc(request).db.session() as s:
        return [row_dict(r) for r in s.scalars(select(Reminder).order_by(Reminder.due_at.desc()).limit(50))]


@router.post("/proactive/reminders/{reminder_id}/cancel")
async def cancel_reminder(reminder_id: int, request: Request):
    with svc(request).db.session() as s:
        r = s.get(Reminder, reminder_id)
        if r is None:
            raise HTTPException(404, "reminder not found")
        if r.status == "pending":
            r.status = "cancelled"
        return row_dict(r)


# ---------- 에이전트 / 토론 ----------


@router.get("/agents")
async def agents(request: Request):
    with svc(request).db.session() as s:
        return [row_dict(a, exclude=("system_prompt",)) for a in s.scalars(select(Agent))]


@router.get("/topics")
async def topics(request: Request):
    with svc(request).db.session() as s:
        return [row_dict(t) for t in s.scalars(select(Topic).order_by(Topic.id.desc()).limit(100))]


@router.post("/debates/run", status_code=202)
async def run_debate(body: RunIn, request: Request):
    v = svc(request)
    if not v.llm.configured:
        raise HTTPException(503, "OPENAI_API_KEY is not set")
    if v.orchestrator.busy:
        raise HTTPException(409, "a debate is already running")
    try:
        topic_id = v.orchestrator.enqueue_topic(body.topic, source="manual") if body.topic else None
        v.orchestrator.start(trigger="manual", topic_id=topic_id)
    except DuplicateTopic as e:
        raise HTTPException(409, str(e))
    except Busy as e:
        raise HTTPException(409, str(e))
    return {"started": True, "topic_id": topic_id}


@router.get("/debates")
async def debates(request: Request):
    with svc(request).db.session() as s:
        return [row_dict(d, exclude=("result",)) for d in s.scalars(select(Debate).order_by(Debate.id.desc()).limit(100))]


@router.get("/debates/{debate_id}")
async def debate_detail(debate_id: int, request: Request):
    with svc(request).db.session() as s:
        d = s.get(Debate, debate_id)
        if d is None:
            raise HTTPException(404, "debate not found")
        return {
            **row_dict(d),
            "messages": [row_dict(m) for m in s.scalars(select(DebateMessage).where(DebateMessage.debate_id == debate_id).order_by(DebateMessage.id))],
            "ideas": [row_dict(i) for i in s.scalars(select(Idea).where(Idea.debate_id == debate_id))],
            "evidence": [row_dict(e) for e in s.scalars(select(Evidence).where(Evidence.debate_id == debate_id))],
        }


@router.get("/ideas")
async def ideas(request: Request, status: str = Query("active", pattern="^(active|all|accepted|needs_research|discarded)$")):
    """기본은 활성 아이디어(accepted, needs_research). 폐기된 아이디어는 status=discarded 또는 all로만 본다(감사용)."""
    q = select(Idea, Debate.title).join(Debate, Debate.id == Idea.debate_id).order_by(Idea.id.desc()).limit(200)
    if status == "active":  # status가 null인 이전 버전 데이터도 활성으로 본다
        q = q.where(or_(Idea.status.is_(None), Idea.status != "discarded"))
    elif status != "all":
        q = q.where(Idea.status == status)
    with svc(request).db.session() as s:
        return [{**row_dict(i), "debate_title": title} for i, title in s.execute(q)]


# ---------- 정책 / 운영 ----------


@router.get("/approvals")
async def approvals(request: Request):
    with svc(request).db.session() as s:
        return [row_dict(a) for a in s.scalars(select(Approval).order_by(Approval.id.desc()).limit(100))]


async def _decide(approval_id: int, approve: bool, request: Request):
    try:
        return await svc(request).policy.decide_approval(approval_id, approve)
    except KeyError:
        raise HTTPException(404, "approval not found")
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.post("/approvals/{approval_id}/approve")
async def approve(approval_id: int, request: Request):
    return await _decide(approval_id, True, request)


@router.post("/approvals/{approval_id}/reject")
async def reject(approval_id: int, request: Request):
    return await _decide(approval_id, False, request)


@router.get("/logs")
async def logs(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    agent_id: str | None = None,
    debate_id: int | None = None,
):
    q = select(ActivityLog).order_by(ActivityLog.id.desc()).limit(limit)
    if agent_id:
        q = q.where(ActivityLog.agent_id == agent_id)
    if debate_id:
        q = q.where(ActivityLog.debate_id == debate_id)
    with svc(request).db.session() as s:
        return [row_dict(r) for r in s.scalars(q)]


@router.get("/settings")
async def get_settings(request: Request):
    return _effective_settings(svc(request))


@router.put("/settings")
async def put_settings(body: SettingsIn, request: Request):
    v = svc(request)
    with v.db.session() as s:
        if body.autonomous_enabled is not None:
            set_value(s, "autonomous_enabled", body.autonomous_enabled)
        if body.debate_interval_minutes is not None:
            set_value(s, "debate_interval_minutes", body.debate_interval_minutes)
    v.activity.record("system", "settings.changed", **body.model_dump(exclude_none=True))
    return _effective_settings(v)


@router.get("/events")
async def events(request: Request):
    bus = svc(request).bus

    async def stream():
        with bus.subscribe() as q:
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    return
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"event: {ev['type']}\ndata: {json.dumps(ev['data'], ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
