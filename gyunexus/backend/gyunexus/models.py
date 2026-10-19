from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    """tzinfo 없는 UTC. DB의 모든 시각은 UTC로 저장한다."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def row_dict(obj: Base, exclude: tuple[str, ...] = ()) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in obj.__table__.columns:
        if col.key in exclude:
            continue
        v = getattr(obj, col.key)
        out[col.key] = v.isoformat() + "Z" if isinstance(v, datetime) else v
    return out


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="새 대화")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ConversationState(Base):
    """대화 세션별 현재 활성 주제와 조건(slots). 서버를 재시작해도 유지된다."""

    __tablename__ = "conversation_states"
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True)
    topic: Mapped[str | None] = mapped_column(String(40), nullable=True)
    slots: Mapped[dict] = mapped_column(JSON, default=dict)
    missing_fields: Mapped[list] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    proactive: Mapped[bool] = mapped_column(Boolean, default=False)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Memory(Base):
    __tablename__ = "memories"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # preference | interest | routine | fact | goal
    content: Mapped[str] = mapped_column(Text)
    importance: Mapped[int] = mapped_column(Integer, default=5)
    source: Mapped[str] = mapped_column(String(20), default="chat")
    use_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    system_prompt: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="idle")  # idle | thinking
    current_task: Mapped[str | None] = mapped_column(String(300), nullable=True)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Topic(Base):
    __tablename__ = "topics"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    rationale: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(30))  # manual | schedule | event | discovery
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|done|failed
    debate_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Debate(Base):
    __tablename__ = "debates"
    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"))
    title: Mapped[str] = mapped_column(String(300))
    goal: Mapped[str] = mapped_column(Text, default="")
    trigger: Mapped[str] = mapped_column(String(30))  # manual | schedule | event
    status: Mapped[str] = mapped_column(String(20), default="running")  # running|completed|failed
    participants: Mapped[list] = mapped_column(JSON, default=list)
    max_rounds: Mapped[int] = mapped_column(Integer, default=3)
    rounds_done: Mapped[int] = mapped_column(Integer, default=0)
    stop_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    importance: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    plan: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 에이전트 선택/제외 이유(규칙·LLM 의견 포함)
    progress: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 라운드별 새 증거·반박·수정 추적, 종료 판단
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DebateMessage(Base):
    __tablename__ = "debate_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    debate_id: Mapped[int] = mapped_column(ForeignKey("debates.id", ondelete="CASCADE"), index=True)
    round: Mapped[int] = mapped_column(Integer)
    agent_id: Mapped[str] = mapped_column(String(40))
    content: Mapped[str] = mapped_column(Text)
    claims: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Idea(Base):
    __tablename__ = "ideas"
    id: Mapped[int] = mapped_column(primary_key=True)
    debate_id: Mapped[int] = mapped_column(ForeignKey("debates.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    feasibility: Mapped[str] = mapped_column(String(10), default="medium")
    risks: Mapped[list] = mapped_column(JSON, default=list)
    next_steps: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    # accepted(충분히 검토됨) | needs_research(추가 근거 필요) | discarded(폐기: 감사용 기록만 유지). null은 이전 버전 데이터.
    status: Mapped[str | None] = mapped_column(String(20), default="needs_research", nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, default="", nullable=True)  # 상태 판정 이유(검증 게이트 결과 포함)
    evidence_ids: Mapped[list | None] = mapped_column(JSON, default=list, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    debate_id: Mapped[int] = mapped_column(ForeignKey("debates.id", ondelete="CASCADE"), index=True)
    tool: Mapped[str] = mapped_column(String(80))
    args: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(500), default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str | None] = mapped_column(String(10), default="ok", nullable=True)  # ok | error(도구 실패 기록)
    flags: Mapped[list | None] = mapped_column(JSON, default=list, nullable=True)  # 도구 결과의 경고·제약(코드가 계산)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(primary_key=True)
    tool: Mapped[str] = mapped_column(String(80))
    args: Mapped[dict] = mapped_column(JSON, default=dict)
    reason: Mapped[str] = mapped_column(Text, default="")
    requested_by: Mapped[str] = mapped_column(String(60))
    debate_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|rejected|executed|failed
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(60), nullable=True)  # 결정 주체: 비어 있으면 사용자, "autonomy:policy" 는 자동 승인 정책(기존 승인 이력은 수정하지 않는다)


class Suggestion(Base):
    """능동 제안 후보와 그 처리 결과. 후보 생성 -> 점수·게이트 -> 전달/보류/폐기 -> 사용자 반응까지 한 행에 남겨 나중에 검증할 수 있다."""

    __tablename__ = "suggestions"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(30))  # sky_observation | idea
    topic_key: Mapped[str] = mapped_column(String(30), index=True)  # sky | idea (주제별 허용 설정의 단위)
    dedupe_key: Mapped[str] = mapped_column(String(160), index=True)
    event: Mapped[str] = mapped_column(String(30))  # dashboard_opened | scheduled | manual | idea_created | reminder_due
    status: Mapped[str] = mapped_column(String(20), default="candidate")  # candidate|held|dropped|delivered|expired
    decision: Mapped[str | None] = mapped_column(String(20), nullable=True)  # deliver | hold | drop | llm_judge | llm_declined
    decision_reason: Mapped[str] = mapped_column(Text, default="")
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_detail: Mapped[dict] = mapped_column(JSON, default=dict)  # 구성 요소·패널티·게이트·임계값
    confidence: Mapped[str] = mapped_column(String(10), default="low")  # high | medium | low (근거 신뢰 수준)
    title: Mapped[str] = mapped_column(String(300), default="")
    reason: Mapped[str] = mapped_column(Text, default="")  # 제안 이유
    needed_action: Mapped[str] = mapped_column(Text, default="")  # 사용자에게 필요한 행동
    params: Mapped[dict] = mapped_column(JSON, default=dict)  # 날짜, 시간대, 장소 이름 등
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)  # 사용한 기억, 도구 결과(facts, flags), 관측/추정 상황
    user_requested: Mapped[bool] = mapped_column(Boolean, default=False)  # 사용자가 요청한 재알림에서 나온 후보
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    conversation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reaction: Mapped[str | None] = mapped_column(String(20), nullable=True)  # interested|details|declined|snoozed|muted|chat
    reaction_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)  # 거절/연기 후 같은 주제 제안 금지 시각


class Reminder(Base):
    __tablename__ = "reminders"
    id: Mapped[int] = mapped_column(primary_key=True)
    topic_key: Mapped[str] = mapped_column(String(30), index=True)
    suggestion_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_at: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending | fired | cancelled
    attempts: Mapped[int] = mapped_column(Integer, default=0)  # 데이터 조회 실패로 미룬 횟수
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    fired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Worker(Base):
    """AI 직원: 상시 실행되는 LLM이 아니라, 업무가 실행될 때만 기존 LLM Provider를 호출하는 '책임 단위'."""

    __tablename__ = "workers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    role: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(80))
    allowed_tools: Mapped[list] = mapped_column(JSON, default=list)  # 이 직원이 쓸 수 있는 도구의 상한(업무별 허용 목록은 이 안에서만 고른다)
    permission_level: Mapped[str] = mapped_column(String(30), default="read_only")  # read_only | write_with_approval
    max_cost_usd: Mapped[float] = mapped_column(Float, default=0.05)  # 업무 1회 실행당 상한의 상한
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WorkerTask(Base):
    __tablename__ = "worker_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    instructions: Mapped[str] = mapped_column(Text)
    completion_criteria: Mapped[list] = mapped_column(JSON, default=list)  # 자연어 완료 기준(검토 호출이 인용으로 증명해야 통과)
    checks: Mapped[dict] = mapped_column(JSON, default=dict)  # 코드가 검사하는 기준: min_chars, required_sections, required_keys
    mode: Mapped[str] = mapped_column(String(12), default="manual")  # manual | scheduled
    interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tools: Mapped[list] = mapped_column(JSON, default=list)  # 이 업무의 도구 허용 목록(직원 허용 도구의 부분집합)
    max_seconds: Mapped[int] = mapped_column(Integer, default=120)
    max_cost_usd: Mapped[float] = mapped_column(Float, default=0.03)
    output_type: Mapped[str] = mapped_column(String(12), default="markdown")  # markdown | text | json
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_agents: Mapped[bool] = mapped_column(Boolean, default=False)  # 기존 토론 결과(에이전트 산출물)를 근거로 가져다 쓸지
    requires_materials: Mapped[bool] = mapped_column(Boolean, default=False)  # 자료가 없으면 지어내지 않고 자료를 요청한다
    materials: Mapped[list] = mapped_column(JSON, default=list)  # [{"name","content"}] 사용자가 직접 제공한 자료
    input_files: Mapped[list] = mapped_column(JSON, default=list)  # 작업 공간 inputs/ 안의 파일 이름
    status: Mapped[str] = mapped_column(String(10), default="active")  # active | paused
    max_tool_calls: Mapped[int] = mapped_column(Integer, default=4, server_default="4")  # 실행 1회당 도구 호출 총량 상한
    tool_rounds: Mapped[int] = mapped_column(Integer, default=1, server_default="1")  # 도구 계획 라운드 수(2라운드: 후보 수집 -> 원문 확인)
    report_kind: Mapped[str] = mapped_column(String(12), default="generic", server_default="generic")  # generic | news(뉴스 조사 보고서: 코드가 URL·날짜·검증 상태를 기록)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WorkerRun(Base):
    """업무 1회 실행 기록. pending -> running -> reviewing -> awaiting_approval -> completed 와 예외 상태를 명시적으로 가진다."""

    __tablename__ = "worker_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("worker_tasks.id", ondelete="CASCADE"), index=True)
    worker_id: Mapped[int] = mapped_column(Integer, index=True)
    trigger: Mapped[str] = mapped_column(String(12), default="manual")  # manual | schedule
    # pending|running|reviewing|awaiting_approval|completed|failed|cancelled|rejected|needs_input
    status: Mapped[str] = mapped_column(String(20), default="pending")
    slot_key: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)  # 정기 실행 슬롯 하나는 한 번만 실행(재시작 중복 방지)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    error_kind: Mapped[str | None] = mapped_column(String(30), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    steps: Mapped[list] = mapped_column(JSON, default=list)  # 단계별 추적(권한·예산·도구·LLM·검증)
    evidence: Mapped[list] = mapped_column(JSON, default=list)  # 증거 번들(도구 결과·자료 요약)
    verification: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")  # 결과물에서 코드가 뽑은 발췌(LLM이 쓴 요약이 아님)
    approval_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    artifact_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inputs: Mapped[list | None] = mapped_column(JSON, default=list, nullable=True)  # 입력으로 참조한 Artifact: [{artifact_id, sha256, version, filename, from_run_id}] (고정 해시 참조)
    directive: Mapped[str] = mapped_column(Text, default="", server_default="")  # 워크플로 단계가 이번 실행에만 덧붙인 지시(업무 정의는 바꾸지 않는다)
    workflow_step_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # 이 실행이 속한 워크플로. 비용 집계의 기준이다(단계 행은 계획 수정으로 삭제될 수 있지만 실행 기록과 그 비용은 남는다)
    workflow_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    notify_state: Mapped[str] = mapped_column(String(10), default="none")  # none | pending | sent | skipped (GYUVIS 알림)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WorkerArtifact(Base):
    __tablename__ = "worker_artifacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("worker_runs.id", ondelete="CASCADE"), index=True)
    worker_id: Mapped[int] = mapped_column(Integer, index=True)
    filename: Mapped[str] = mapped_column(String(160))
    rel_path: Mapped[str] = mapped_column(String(300))  # 작업 공간 루트 기준 상대 경로
    media_type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Workflow(Base):
    """사용자의 자연어 목표를 여러 AI 직원이 나눠 수행하도록 만든 실행 계획(DAG)과 그 진행 상태."""

    __tablename__ = "workflows"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    goal: Mapped[str] = mapped_column(Text)
    # planned(계획 확인 대기) | running | paused | completed | failed(재시도 필요한 단계 있음) | cancelled
    status: Mapped[str] = mapped_column(String(12), default="planned")
    auto_run: Mapped[bool] = mapped_column(Boolean, default=False)  # 사용자가 계획 확인 없이 자동 실행을 명시적으로 허용했는가
    budget_usd: Mapped[float] = mapped_column(Float, default=0.5)  # 계획+모든 단계 실행의 총비용 상한
    planning_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    plan_notes: Mapped[str] = mapped_column(Text, default="")  # 플래너의 설명·경고
    plan_version: Mapped[int] = mapped_column(Integer, default=1)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)  # 실행 단계의 실패 원인(계획 생성 실패는 아래 plan_* 에 따로 둔다)
    # 계획 생성 상태: ok(유효한 계획이 있음) | failed(계획 생성·검증에 실패해 단계가 없음). 실패 기록은 WorkflowPlanAttempt 에 이력으로 남는다
    plan_state: Mapped[str] = mapped_column(String(12), default="ok", server_default="ok")
    plan_error: Mapped[str | None] = mapped_column(Text, nullable=True)  # 현재 유효한 계획 생성 실패 원인(해소되면 비워지고 이력만 남는다)
    plan_error_kind: Mapped[str | None] = mapped_column(String(12), nullable=True)  # budget(예산 때문에만 실패) | invalid(그 밖의 검증 실패)
    plan_error_budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True)  # 실패 메시지를 만든 시점의 예산
    proposed_steps: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 실패한 플래너 제안 원본(새 LLM 호출 없이 재검증하는 데 쓴다)
    # --- 통합 자율 실행(autonomy.py). 모두 기본값이 있어 기존 행·기존 동작은 그대로다(manual = 기존 수동 방식)
    exec_mode: Mapped[str] = mapped_column(String(12), default="manual", server_default="manual")  # manual | supervised | autonomous
    origin: Mapped[str] = mapped_column(String(12), default="user", server_default="user")  # user | chat | schedule | event | proactive | chain
    trigger_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)  # 이 워크플로를 시작시킨 상시 자율 운영 트리거
    trigger_reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # 시작 사유(사람이 읽는 문장)
    conversation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 진행·결과를 알릴 GYUVIS 대화
    chain_depth: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # 선행 업무 완료로 이어진 횟수(무한 연쇄 방지)
    auto_retries: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # 자동 재시도한 횟수(상한 적용)
    policy_decision: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 코드가 내린 자동 실행 판정(단계별 사유 포함)
    notified_state: Mapped[str | None] = mapped_column(String(80), nullable=True)  # 마지막으로 대화에 알린 상태(같은 알림 반복 방지)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AutonomyTrigger(Base):
    """상시 자율 운영 트리거: 조건이 맞으면 목표를 기존 Workflow Engine 에 전달한다(별도 실행 엔진 없음)."""

    __tablename__ = "autonomy_triggers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(12))  # once | interval | daily | event | proactive | chain
    goal: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)  # kind 별 설정(run_at | minutes | time/weekdays | event | topic_key | after_trigger_id/after_workflow_id)
    exec_mode: Mapped[str] = mapped_column(String(12), default="supervised")  # manual(계획만 준비) | supervised | autonomous
    budget_usd: Mapped[float] = mapped_column(Float, default=0.3)  # 실행 1회(워크플로 1건)의 총예산
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=60)
    max_runs_per_day: Mapped[int] = mapped_column(Integer, default=6)
    daily_cost_cap_usd: Mapped[float] = mapped_column(Float, default=0.5)  # 이 트리거가 하루에 쓸 수 있는 비용 상한
    max_retries: Mapped[int] = mapped_column(Integer, default=1)  # 실패한 워크플로당 자동 재시도 상한
    next_fire_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fire_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AutonomyRun(Base):
    """트리거 발동 1회의 기록(시작 사유와 결과). slot_key 가 유일해 같은 발동이 서버 재시작 뒤에도 두 번 실행되지 않는다."""

    __tablename__ = "autonomy_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    trigger_id: Mapped[int] = mapped_column(Integer, index=True)
    workflow_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    slot_key: Mapped[str | None] = mapped_column(String(160), unique=True, nullable=True)  # 실제 시작을 시도한 발동만 슬롯을 점유한다(건너뜀은 NULL)
    reason: Mapped[str] = mapped_column(Text, default="")  # 시작 사유
    status: Mapped[str] = mapped_column(String(12), default="starting")  # starting | started | blocked | skipped | failed | completed | cancelled
    skip_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)  # cooldown | already_running | daily_budget | disabled ...
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WorkflowPlanAttempt(Base):
    """계획 생성·재검증·재생성 시도 이력(성공·실패 모두). 계획이 복구돼도 과거 실패 기록은 지우지 않는다."""

    __tablename__ = "workflow_plan_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(12), default="initial")  # initial | auto(예산 증액 후 자동 재검증) | revalidate | replan | manual(사용자가 직접 계획 저장)
    source: Mapped[str] = mapped_column(String(12), default="llm")  # llm(새 제안) | proposal(저장된 제안 재검증) | user | legacy(이전 버전 기록 이전)
    status: Mapped[str] = mapped_column(String(12), default="failed")  # succeeded | failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_kind: Mapped[str | None] = mapped_column(String(12), nullable=True)
    budget_usd: Mapped[float] = mapped_column(Float, default=0.0)  # 시도 당시의 예산
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)  # 이 시도에서 새로 쓴 계획 생성 비용(재검증은 0)
    step_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WorkflowBudgetChange(Base):
    """워크플로 총예산 변경 이력. 변경 전후 값, 당시 사용액·남은 단계 요구량, 상태, 시각을 남긴다(실행 이력·비용 기록은 건드리지 않는다)."""

    __tablename__ = "workflow_budget_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), index=True)
    old_usd: Mapped[float] = mapped_column(Float)
    new_usd: Mapped[float] = mapped_column(Float)
    spent_usd: Mapped[float] = mapped_column(Float, default=0.0)  # 변경 시점까지 사용한 비용(계획 생성 포함)
    required_usd: Mapped[float] = mapped_column(Float, default=0.0)  # 변경 시점에 남은 단계가 앞으로 쓸 수 있는 최대 비용
    status: Mapped[str] = mapped_column(String(12), default="")  # 변경 시점의 워크플로 상태
    source: Mapped[str] = mapped_column(String(12), default="budget")  # budget(예산 변경) | plan(계획 수정과 함께)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WorkflowStep(Base):
    __tablename__ = "workflow_steps"
    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(40))  # 계획 안에서의 단계 식별자
    title: Mapped[str] = mapped_column(String(200))
    directive: Mapped[str] = mapped_column(Text, default="")  # 이 단계에서 수행할 구체적 지시(목표 반영)
    worker_id: Mapped[int] = mapped_column(Integer)
    task_id: Mapped[int] = mapped_column(Integer)  # 기존 업무 템플릿(실행 엔진은 Worker 의 것을 그대로 쓴다)
    depends_on: Mapped[list] = mapped_column(JSON, default=list)
    reason: Mapped[str] = mapped_column(Text, default="")  # 플래너가 이 직원·업무를 고른 이유
    # pending | running | awaiting_approval | completed | failed | cancelled | removed(계획에서 삭제됨: 실행 이력이 있어 행은 보존)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 가장 최근 실행
    model: Mapped[str] = mapped_column(String(80), default="")
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)  # 모든 시도의 누적 비용
    error_kind: Mapped[str | None] = mapped_column(String(30), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    inputs: Mapped[list] = mapped_column(JSON, default=list)  # 마지막 시도에 연결된 Artifact 참조(고정 해시)
    output_artifact_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DevProject(Base):
    """AI 개발 직원이 접근할 수 있는 로컬 프로젝트. 경로는 사용자가 등록하고(코드에 하드코딩하지 않음), 직원별 권한은 WorkerProjectGrant 가 정한다."""

    __tablename__ = "dev_projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    root_path: Mapped[str] = mapped_column(String(1000))  # 등록 시 실제 경로(심볼릭 링크 해석 후)로 저장
    description: Mapped[str] = mapped_column(Text, default="")
    allow_read: Mapped[bool] = mapped_column(Boolean, default=True)
    allow_write: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_exec: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_git: Mapped[bool] = mapped_column(Boolean, default=True)
    # 실행 프로파일: [{name, kind(test|build|lint|other), argv[list], timeout_seconds, allow_args(bool), allowed_flags[list]}]. AI 는 이름으로만 고른다(임의 명령 불가)
    exec_profiles: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WorkerProjectGrant(Base):
    """직원별 프로젝트 권한. 실제 권한은 프로젝트의 allow_* 와 이 값의 교집합이다."""

    __tablename__ = "worker_project_grants"
    id: Mapped[int] = mapped_column(primary_key=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("dev_projects.id", ondelete="CASCADE"), index=True)
    can_read: Mapped[bool] = mapped_column(Boolean, default=True)
    can_write: Mapped[bool] = mapped_column(Boolean, default=False)
    can_exec: Mapped[bool] = mapped_column(Boolean, default=False)


class ProjectChange(Base):
    """개발 직원이 프로젝트 파일에 적용한 변경 기록(변경 전후 해시, diff). 실행 기록과 함께 남아 나중에 검토할 수 있다."""

    __tablename__ = "project_changes"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    worker_id: Mapped[int] = mapped_column(Integer, index=True)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    path: Mapped[str] = mapped_column(String(500))  # 프로젝트 루트 기준 상대 경로(/ 구분)
    action: Mapped[str] = mapped_column(String(10))  # create | modify
    tool: Mapped[str] = mapped_column(String(20))  # code.write | code.patch
    before_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    after_sha256: Mapped[str] = mapped_column(String(64))
    before_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # 변경 전 내용(상한 이하일 때만 보관: 복구·diff 용)
    diff: Mapped[str] = mapped_column(Text, default="")
    added_lines: Mapped[int] = mapped_column(Integer, default=0)
    removed_lines: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class LlmUsage(Base):
    __tablename__ = "llm_usage"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    purpose: Mapped[str] = mapped_column(String(60))
    model: Mapped[str] = mapped_column(String(80))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    autonomous: Mapped[bool] = mapped_column(Boolean, default=False)
    debate_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ActivityLog(Base):
    __tablename__ = "activity_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    source: Mapped[str] = mapped_column(String(30))
    agent_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    debate_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    level: Mapped[str] = mapped_column(String(10), default="info")
    event: Mapped[str] = mapped_column(String(60))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)

