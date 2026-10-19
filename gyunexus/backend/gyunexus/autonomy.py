"""통합 자율 실행: 요청형 자동 실행과 상시 자율 운영을 **기존 Workflow Engine 위의 정책 계층**으로 제공한다.

- 실행 엔진은 새로 만들지 않는다. 계획은 WorkflowService.plan(), 실행은 WorkflowService.start()/advance(), 직원 실행·승인·Artifact 해시 전달·
  단계별 예산 차단은 WorkerService 가 이미 하는 일을 그대로 쓴다. 이 모듈은 "언제 자동으로 시작해도 되는가", "무엇을 자동으로 승인해도 되는가"만 판정한다.
- 판정은 전부 코드가 한다(권한·도구 위험도·비용·검증 결과). LLM 은 계획 제안만 하고, LLM 의 판단으로 권한이 넓어지는 경로는 없다.
- 실행 모드: manual(기존 방식: 사용자가 시작) | supervised(검증된 계획을 자동 시작, 승인 게이트는 그대로) | autonomous(+ 정책을 통과한 읽기 전용 결과물 자동 승인).
- 자동 시작/자동 승인 모두 읽기 전용 직원 + 읽기 도구만 쓰는 단계에서만 허용된다. 그 밖의 단계가 하나라도 있으면 계획은 만들어 두되 시작하지 않고 사용자 확인을 기다린다.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .activity import Activity
from .config import Settings
from .db import Database
from .events import EventBus
from .models import (Approval, AutonomyRun, AutonomyTrigger, Conversation, Message, Worker, WorkerArtifact, WorkerRun, WorkerTask, Workflow, WorkflowStep,
                     row_dict, utcnow)
from .policy import Policy
from .runtime_settings import get_value, set_value
from .workers import FAIL_LABELS, WorkerService
from .workflows import WorkflowError, WorkflowService

logger = logging.getLogger("gyunexus")

MODES = ("manual", "supervised", "autonomous")
MODE_LABEL = {"manual": "수동", "supervised": "감독 자동(승인 게이트 유지)", "autonomous": "자율(허용된 작업 자동 진행)"}
KINDS = ("once", "interval", "daily", "event", "proactive", "chain")
TRIGGER_ORIGINS = ("schedule", "event", "proactive", "chain")  # 상시 자율 운영이 시작한 워크플로의 origin
KIND_ORIGIN = {"once": "schedule", "interval": "schedule", "daily": "schedule", "event": "event", "proactive": "proactive", "chain": "chain"}
TRANSIENT = {"llm_error", "timeout", "interrupted", "internal"}  # 같은 입력으로 다시 해 볼 만한 실패만 자동 재시도한다(검증 실패·반려·예산·자료 부족은 제외)
LIVE_WF = ("planned", "running", "paused")
EVENT_RE = re.compile(r"^[a-z][a-z0-9_.:-]{1,39}$")
BUILTIN_EVENTS = {"dashboard_opened": "대시보드 접속(오랜만에 돌아왔을 때)"}
STATUS_RE = re.compile(r"(워크플로|작업|업무|직원).{0,14}(진행|상태|어디까지|결과|끝났|됐|되었)|(진행|상태).{0,8}(알려|보여|어때|어떻)")


class AutonomyError(WorkflowError):
    """code: validation | not_found | conflict | llm (WorkflowError 와 같은 HTTP 매핑을 쓴다)."""


def _norm_goal(goal: str) -> str:
    return re.sub(r"\s+", " ", (goal or "").strip()).casefold()


class AutonomyService:
    def __init__(self, settings: Settings, db: Database, workflows: WorkflowService, workers: WorkerService, policy: Policy, bus: EventBus, activity: Activity):
        self.settings, self.db, self.wf, self.workers, self.policy, self.bus, self.activity = settings, db, workflows, workers, policy, bus, activity
        self.now = utcnow
        self._locks: dict[int, asyncio.Lock] = {}
        self._bg: set[asyncio.Task] = set()
        self._tick_lock = asyncio.Lock()
        workflows.progress_hook = self.on_progress
        workflows.annotate = self.annotate

    # ------------------------------------------------------------------ 설정(전체 ON/OFF·허용 범위·한도)

    def config(self) -> dict:
        s = self.settings
        with self.db.session() as ses:
            c = {
                "enabled": bool(get_value(ses, "autonomy_enabled", s.autonomy_enabled)),
                "max_mode": get_value(ses, "autonomy_max_mode", s.autonomy_max_mode),
                "auto_approve": bool(get_value(ses, "autonomy_auto_approve", s.autonomy_auto_approve)),
                "max_concurrent": int(get_value(ses, "autonomy_max_concurrent", s.autonomy_max_concurrent)),
                "daily_cost_cap_usd": float(get_value(ses, "autonomy_daily_cost_cap_usd", s.autonomy_daily_cost_cap_usd)),
            }
        return c

    def enabled(self) -> bool:
        return self.config()["enabled"]

    def full_config(self) -> dict:
        s = self.settings
        return {**self.config(), "modes": [{"id": m, "label": MODE_LABEL[m]} for m in MODES], "spent_today_usd": round(self._spend_today(), 4),
                "min_interval_minutes": s.autonomy_min_interval_minutes, "max_chain_depth": s.autonomy_max_chain_depth, "builtin_events": BUILTIN_EVENTS,
                "request_max_retries": s.autonomy_request_max_retries, "retry_delay_minutes": s.autonomy_retry_delay_minutes}

    async def set_config(self, *, enabled: bool | None = None, max_mode: str | None = None, auto_approve: bool | None = None,
                         max_concurrent: int | None = None, daily_cost_cap_usd: float | None = None) -> dict:
        errors = []
        if max_mode is not None and max_mode not in MODES[1:]:
            errors.append("허용 범위는 supervised 또는 autonomous 여야 합니다")
        if max_concurrent is not None and not (1 <= max_concurrent <= 10):
            errors.append("동시 실행 한도는 1~10 이어야 합니다")
        if daily_cost_cap_usd is not None and not (0 < daily_cost_cap_usd <= 50):
            errors.append("일일 비용 한도는 0 초과 50 이하(USD)여야 합니다")
        if errors:
            raise AutonomyError("validation", "; ".join(errors))
        was = self.enabled()
        with self.db.session() as s:
            for key, val in (("autonomy_enabled", enabled), ("autonomy_max_mode", max_mode), ("autonomy_auto_approve", auto_approve),
                             ("autonomy_max_concurrent", max_concurrent), ("autonomy_daily_cost_cap_usd", daily_cost_cap_usd)):
                if val is not None:
                    set_value(s, key, val)
        self.activity.record("autonomy", "autonomy.config_changed", enabled=enabled, max_mode=max_mode, auto_approve=auto_approve,
                             max_concurrent=max_concurrent, daily_cost_cap_usd=daily_cost_cap_usd)
        if was and enabled is False:
            await self._pause_trigger_workflows("autonomy_off")  # 꺼지는 순간 상시 자율 운영이 시작한 워크플로가 새 단계를 시작하지 않게 한다
        self.bus.publish("workflow.updated", {"autonomy": True})
        return self.full_config()

    async def _pause_trigger_workflows(self, why: str) -> None:
        with self.db.session() as s:
            ids = [w.id for w in s.scalars(select(Workflow).where(Workflow.origin.in_(TRIGGER_ORIGINS), Workflow.status == "running"))]
        for wid in ids:
            try:
                await self.wf.pause(wid)
            except WorkflowError:
                continue
            with self.db.session() as s:
                row = s.get(Workflow, wid)
                row.policy_decision = {**(row.policy_decision or {}), "paused_by": why}
            self.activity.record("autonomy", "autonomy.paused", level="warn", workflow_id=wid, why=why)

    # ------------------------------------------------------------------ 정책 판정(코드)

    def _max_mode(self) -> str:
        return self.config()["max_mode"]

    def _check_mode(self, mode: str, *, cap: bool) -> str:
        """모드를 검증한다. 사용자가 직접 고른 모드가 허용 범위를 넘으면 거부(cap=False), 트리거는 허용 범위로 낮춘다(cap=True)."""
        if mode not in MODES:
            raise AutonomyError("validation", f"실행 모드는 {', '.join(MODES)} 중 하나여야 합니다")
        mx = self._max_mode()
        if MODES.index(mode) > MODES.index(mx):
            if cap:
                return mx
            raise AutonomyError("validation", f"'{mode}' 모드는 현재 허용된 자동 실행 범위({mx})를 넘습니다. 자율 운영 설정에서 허용 범위를 바꾸세요")
        return mode

    def assess(self, wid: int) -> dict:
        """계획의 모든 단계를 검사한다. 읽기 전용 직원 + 읽기 도구만 쓰는 단계만 자동 실행·자동 승인 대상이다."""
        out, blockers = [], []
        with self.db.session() as s:
            for st in self.wf.steps(wid):
                w, t = s.get(Worker, st.worker_id), s.get(WorkerTask, st.task_id)
                reasons: list[str] = []
                if w is None or t is None:
                    reasons.append("직원 또는 업무를 찾을 수 없음")
                else:
                    if not w.enabled:
                        reasons.append(f"직원 '{w.name}'이(가) 비활성 상태")
                    if t.status != "active":
                        reasons.append(f"업무 '{t.title}'이(가) 일시정지 상태")
                    if w.permission_level == "developer":  # 개발 직원: 사전 부여된 프로젝트 범위 안의 작업은 자동 진행(범위 검사는 도구가 한다)
                        if self.workers.dev is None or not self.workers.dev.worker_projects(w.id):
                            reasons.append(f"개발 직원 '{w.name}'에게 부여된 프로젝트가 없음")
                    elif w.permission_level != "read_only":
                        reasons.append(f"직원 '{w.name}'은(는) 쓰기 권한(승인 후 쓰기)이 있는 직원")
                    risky = [n for n in t.tools if n in w.allowed_tools and (self.workers.tools.get(n) is None or self.workers.tools.get(n).risk not in ("read", "project"))]
                    if risky:
                        reasons.append(f"읽기 전용이 아닌 도구 사용: {', '.join(risky)}")
                out.append({"key": st.key, "title": st.title, "requires_approval": bool(t and t.requires_approval), "blockers": reasons})
                blockers += [f"[{st.title}] {r}" for r in reasons]
        return {"auto_runnable": not blockers and bool(out), "blockers": blockers, "steps": out}

    def _save_decision(self, wid: int, fields: dict) -> dict:
        with self.db.session() as s:
            row = s.get(Workflow, wid)
            d = {**(row.policy_decision or {}), **fields, "checked_at": self.now().isoformat() + "Z"}
            row.policy_decision = d
        return d

    async def decide_and_start(self, wid: int) -> dict:
        """계획이 만들어진 워크플로를 모드에 맞게 자동 시작할지 판단하고, 허용되면 기존 start() 로 시작한다."""
        wf = self.wf.get(wid)
        base = {"mode": wf.exec_mode, "started": False, "auto_start": False, "blockers": [], "reason": ""}
        if wf.plan_state != "ok" or not self.wf.steps(wid):
            return self._save_decision(wid, {**base, "reason": "계획 생성에 실패해 시작할 수 없습니다. 계획을 다시 만들거나 직접 수정하세요"})
        if wf.exec_mode == "manual":
            return self._save_decision(wid, {**base, "reason": "수동 모드: 계획을 확인한 뒤 직접 실행하세요"})
        a = self.assess(wid)
        if not a["auto_runnable"]:
            self.activity.record("autonomy", "autonomy.blocked", level="warn", workflow_id=wid, blockers=a["blockers"][:6])
            return self._save_decision(wid, {**base, "blockers": a["blockers"], "reason": "자동 실행이 허용되지 않는 단계가 있어 시작하지 않았습니다. 계획을 확인하고 직접 실행하세요"})
        try:
            await self.wf.start(wid)  # 기존 시작 경로: 권한·존재·예산을 다시 검증한다
        except WorkflowError as e:
            return self._save_decision(wid, {**base, "auto_start": True, "reason": f"시작 검증에 실패했습니다: {e}"})
        self.activity.record("autonomy", "autonomy.auto_started", workflow_id=wid, mode=wf.exec_mode, origin=wf.origin, trigger_id=wf.trigger_id)
        return self._save_decision(wid, {**base, "auto_start": True, "started": True, "reason": "정책 검사를 통과해 자동으로 시작했습니다"})

    async def submit_goal(self, goal: str, *, mode: str = "manual", budget: float | None = None, origin: str = "user", conversation_id: int | None = None,
                          trigger_id: int | None = None, reason: str | None = None, chain_depth: int = 0) -> int:
        """자연어 목표 -> (기존) 플래너가 계획 -> 코드가 검증 -> 모드에 따라 자동 시작. 워크플로 ID 를 돌려준다."""
        mode = self._check_mode(mode, cap=origin in TRIGGER_ORIGINS)
        wid = await self.wf.plan(goal, budget=budget, auto_run=False)
        with self.db.session() as s:
            row = s.get(Workflow, wid)
            row.exec_mode, row.origin, row.conversation_id, row.trigger_id = mode, origin, conversation_id, trigger_id
            row.trigger_reason, row.chain_depth = reason, chain_depth
            row.auto_run = mode != "manual"
        self.activity.record("autonomy", "autonomy.goal_submitted", workflow_id=wid, mode=mode, origin=origin, trigger_id=trigger_id, reason=reason)
        await self.decide_and_start(wid)
        self.wf._emit(wid)
        return wid

    async def set_mode(self, wid: int, mode: str) -> Workflow:
        mode = self._check_mode(mode, cap=False)
        wf = self.wf.get(wid)
        if wf.status in ("completed", "cancelled"):
            raise AutonomyError("conflict", f"{wf.status} 상태의 워크플로는 모드를 바꿀 수 없습니다")
        with self.db.session() as s:
            row = s.get(Workflow, wid)
            row.exec_mode = mode
            row.auto_run = mode != "manual"
        self.activity.record("autonomy", "autonomy.mode_changed", workflow_id=wid, old=wf.exec_mode, new=mode)
        self.wf._emit(wid)
        await self.on_progress(wid)  # 자율로 바꾸면 이미 대기 중인 승인 중 정책을 통과하는 것만 이어서 처리한다
        return self.wf.get(wid)

    # ------------------------------------------------------------------ 자동 승인

    def _approval_check(self, st: WorkflowStep, wf: Workflow, a: dict | None = None) -> tuple[bool, str]:
        """승인 대기 단계가 자동 승인 대상인가. (가능 여부, 사유). 승인 정책을 우회하지 않고, 하나라도 어긋나면 사용자 승인을 요구한다."""
        if wf.exec_mode != "autonomous":
            return False, f"실행 모드가 '{wf.exec_mode}'라서 자동 승인하지 않습니다(자율 모드에서만 정책을 통과한 읽기 전용 결과물을 자동 승인)"
        cfg = self.config()
        if not cfg["auto_approve"]:
            return False, "자동 승인이 설정에서 꺼져 있습니다"
        if wf.origin in TRIGGER_ORIGINS and not cfg["enabled"]:
            return False, "상시 자율 운영이 꺼져 있습니다"
        a = a or self.assess(wf.id)
        sa = next((x for x in a["steps"] if x["key"] == st.key), None)
        if sa is None or sa["blockers"]:
            return False, "읽기 전용이 아닌 직원·도구가 포함된 단계라 사용자 승인이 필요합니다: " + "; ".join(sa["blockers"] if sa else ["단계 정보 없음"])
        with self.db.session() as s:
            run = s.get(WorkerRun, st.run_id) if st.run_id else None
            ap = s.get(Approval, run.approval_id) if run is not None and run.approval_id else None
            art = s.get(WorkerArtifact, run.artifact_id) if run is not None and run.artifact_id else None
            v = (run.verification if run is not None else None) or {}
            injected = bool(run and any(x.get("kind") == "injection_suspected" for x in (run.steps or [])))
        if run is None or ap is None or art is None:
            return False, "실행·승인·결과물 기록을 확인할 수 없습니다"
        if ap.status != "pending" or ap.tool != "worker.finalize" or int((ap.args or {}).get("run_id", 0)) != run.id or run.status != "awaiting_approval":
            return False, "승인 항목이 실행 상태와 일치하지 않습니다"
        if v.get("passed") is not True or not art.verified:
            return False, "결과물 검증을 통과하지 못했습니다(검증 실패는 승인으로 취급하지 않습니다)"
        if (ap.args or {}).get("sha256") != art.sha256:
            return False, "승인 요청 이후 결과물이 바뀌었습니다"
        if v.get("warnings") or injected:
            return False, "검증 경고(자료 부족·지시문 의심 등)가 있어 사용자 검토가 필요합니다"
        return True, "읽기 전용 단계의 결과물이 검증을 통과해 자동 승인 대상입니다"

    async def _auto_approve(self, wid: int) -> None:
        wf = self.wf.get(wid)
        if wf.status != "running" or wf.exec_mode != "autonomous":
            return
        a = self.assess(wid)
        for st in self.wf.steps(wid):
            with self.db.session() as s:
                run = s.get(WorkerRun, st.run_id) if st.run_id else None
                aid = run.approval_id if run is not None and run.status == "awaiting_approval" else None
            if aid is None:
                continue
            ok, why = self._approval_check(st, wf, a)
            if not ok:
                continue
            try:
                await self.policy.decide_approval(aid, True, decided_by="autonomy:policy")  # 사용자 승인과 같은 경로(기록·해시 재검증 포함)
            except (KeyError, ValueError):
                continue  # 이미 처리됨(사용자 또는 다른 호출)
            except Exception:
                logger.exception("auto approval failed")
                self.activity.record("autonomy", "autonomy.auto_approve_error", level="error", workflow_id=wid, approval_id=aid)
                continue
            self.activity.record("autonomy", "autonomy.auto_approved", workflow_id=wid, step=st.key, approval_id=aid, run_id=st.run_id, rule=why)

    # ------------------------------------------------------------------ 진행 훅(자동 승인 -> 기록 동기화 -> 대화 알림 -> 연쇄 트리거)

    def _lock(self, wid: int) -> asyncio.Lock:
        return self._locks.setdefault(wid, asyncio.Lock())

    async def on_progress(self, wid: int) -> None:
        async with self._lock(wid):
            wf = self.wf.get(wid)
            if wf.exec_mode != "manual":
                await self._auto_approve(wid)
            self._sync_run(wid)
            await self._notify_chat(wid)
        self._chain(wid)

    def _sync_run(self, wid: int) -> None:
        wf = self.wf.get(wid)
        if wf.trigger_id is None:
            return
        status = {"completed": "completed", "cancelled": "cancelled", "failed": "failed", "running": "started", "paused": "started"}.get(wf.status)
        if status is None:
            return
        with self.db.session() as s:
            run = s.scalars(select(AutonomyRun).where(AutonomyRun.workflow_id == wid).order_by(AutonomyRun.id.desc())).first()
            if run is not None and run.status != status and run.status not in ("skipped",):
                run.status, run.updated_at = status, self.now()
                if status == "failed":
                    run.detail = {**(run.detail or {}), "error": wf.error}

    # ------------------------------------------------------------------ 대화 알림

    def _facts(self, wid: int) -> dict:
        wf = self.wf.get(wid)
        sts = self.wf.steps(wid)
        dependents = {d for s in sts for d in s.depends_on}
        with self.db.session() as s:
            rows = []
            for st in sts:
                run = s.get(WorkerRun, st.run_id) if st.run_id else None
                w, t = s.get(Worker, st.worker_id), s.get(WorkerTask, st.task_id)
                art = s.get(WorkerArtifact, st.output_artifact_id) if st.output_artifact_id else None
                rows.append({"key": st.key, "title": st.title, "status": st.status, "worker": w.name if w else "?", "task": t.title if t else "?", "error_kind": st.error_kind, "error": st.error,
                             "run_status": run.status if run else None, "approval_id": run.approval_id if run and run.status == "awaiting_approval" else None,
                             "summary": run.summary if run else "", "leaf": st.key not in dependents,
                             "artifact": {"id": art.id, "title": art.title or art.filename, "verified": art.verified, "sha8": art.sha256[:8]} if art else None, "step": st})
        return {"wf": wf, "steps": rows}

    def _state_key(self, f: dict) -> str | None:
        wf, rows = f["wf"], f["steps"]
        awaiting = [r for r in rows if r["approval_id"]]
        if wf.status == "completed":
            return "completed"
        if wf.status == "failed":
            return "failed:" + ",".join(sorted(f"{r['key']}={r['error_kind']}" for r in rows if r["status"] in ("failed", "cancelled")))
        if wf.status == "cancelled":
            return "cancelled"
        if awaiting:
            return "approval:" + ",".join(str(r["approval_id"]) for r in awaiting)
        if wf.status == "paused":
            return "paused"
        return None

    def _message(self, f: dict, key: str) -> str:
        wf, rows = f["wf"], f["steps"]
        head = f"워크플로 #{wf.id} '{wf.title or wf.goal[:30]}'"
        if key == "completed":
            lines = [f"{head}이(가) 끝났습니다. ({sum(1 for r in rows if r['status'] == 'completed')}/{len(rows)}단계 완료, 비용 ${self.wf._spent(wf.id):.4f} / 예산 ${wf.budget_usd:.4f})"]
            for r in rows:
                if r["leaf"] and r["artifact"]:
                    a = r["artifact"]
                    lines.append(f"· 최종 결과물 #{a['id']} '{a['title']}' — {r['worker']}, {'검증됨' if a['verified'] else '검증되지 않음'}(sha256 {a['sha8']}…)")
                    if r["summary"]:
                        lines.append(f"  발췌: {r['summary'][:200]}")
            lines.append("전체 내용과 입력 계보는 워크플로 화면에서 확인할 수 있습니다.")
            return "\n".join(lines)
        if key.startswith("failed"):
            bad = [r for r in rows if r["status"] in ("failed", "cancelled")]
            lines = [f"{head}이(가) 멈췄습니다. 성공으로 처리하지 않았습니다."]
            for r in bad:
                kind = r["error_kind"] or ""
                label = "자료 부족(필요한 자료가 없음)" if kind in ("no_input", "needs_input") else FAIL_LABELS.get(kind, kind or "원인 미상")
                lines.append(f"· [{r['title']}] {r['worker']}: {label}" + (f" — {r['error'][:160]}" if r["error"] else ""))
            return "\n".join(lines)
        if key.startswith("approval"):
            lines = [f"{head}이(가) 사용자 승인을 기다립니다. 승인하기 전에는 다음 단계가 시작되지 않습니다."]
            a = self.assess(wf.id)
            for r in rows:
                if r["approval_id"]:
                    _, why = self._approval_check(r["step"], wf, a)
                    lines.append(f"· [{r['title']}] {r['worker']} — 사유: {why if wf.exec_mode == 'autonomous' else '이 업무는 결과물 확정에 승인이 필요합니다(' + why + ')'}")
            lines.append("승인 화면에서 검토할 수 있습니다.")
            return "\n".join(lines)
        if key == "paused":
            reason = (wf.policy_decision or {}).get("paused_by")
            return f"{head}이(가) 일시정지되었습니다." + (" (상시 자율 운영이 꺼져 멈췄습니다. 필요하면 워크플로 화면에서 재개하세요)" if reason == "autonomy_off" else "")
        return f"{head}이(가) 취소되었습니다."

    async def _notify_chat(self, wid: int) -> None:
        wf = self.wf.get(wid)
        if wf.conversation_id is None:
            return
        f = self._facts(wid)
        key = self._state_key(f)
        if key is None or key == wf.notified_state:
            return
        text = self._message(f, key)
        with self.db.session() as s:
            conv = s.get(Conversation, wf.conversation_id)
            if conv is not None:
                msg = Message(conversation_id=conv.id, role="assistant", content=text, proactive=True,
                              meta={"kind": "workflow", "workflow_id": wid, "state": key.split(":")[0]})
                s.add(msg)
                conv.updated_at = utcnow()
                s.flush()
                payload = row_dict(msg)
            else:
                payload = None
            s.get(Workflow, wid).notified_state = key
        if payload:
            self.bus.publish("proactive.message", payload)
        self.activity.record("autonomy", "autonomy.chat_notified", workflow_id=wid, state=key.split(":")[0])

    # ------------------------------------------------------------------ GYUVIS 대화 연동

    @staticmethod
    def is_delegation(text: str) -> bool:
        return text.lstrip().startswith(("/위임", "/목표"))

    def is_status_query(self, text: str, conversation_id: int | None) -> bool:
        t = text.strip()
        if t in ("/상태", "/status"):
            return True
        return bool(conversation_id) and bool(STATUS_RE.search(t)) and bool(self._conv_workflows(conversation_id))

    def _conv_workflows(self, conversation_id: int | None, limit: int = 3) -> list[Workflow]:
        if not conversation_id:
            return []
        with self.db.session() as s:
            return list(s.scalars(select(Workflow).where(Workflow.conversation_id == conversation_id).order_by(Workflow.id.desc()).limit(limit)))

    def _save_turn(self, conversation_id: int | None, user_text: str, reply: str, meta: dict) -> dict:
        with self.db.session() as s:
            if conversation_id is None:
                conv = Conversation(title=user_text.strip()[:30])
                s.add(conv)
                s.flush()
            else:
                conv = s.get(Conversation, conversation_id)
                if conv is None:
                    raise KeyError(conversation_id)
            u = Message(conversation_id=conv.id, role="user", content=user_text)
            r = Message(conversation_id=conv.id, role="assistant", content=reply, meta=meta)
            s.add_all([u, r])
            conv.updated_at = utcnow()
            s.flush()
            return {"conversation_id": conv.id, "user_message": row_dict(u), "reply": row_dict(r)}

    def _plan_text(self, wid: int) -> str:
        wf = self.wf.get(wid)
        sts = self.wf.steps(wid)
        lv = self.wf.levels(sts)
        with self.db.session() as s:
            names = {st.key: (s.get(Worker, st.worker_id).name if s.get(Worker, st.worker_id) else "?") for st in sts}
        lines = [f"· {st.title} — {names[st.key]}" + (f" (선행: {', '.join(st.depends_on)})" if st.depends_on else "") + (" [병렬 가능]" if sum(1 for o in sts if lv[o.key] == lv[st.key]) > 1 else "") for st in sts]
        return "\n".join(lines)

    async def chat_delegate(self, text: str, conversation_id: int | None, mode: str, budget: float | None) -> dict:
        goal = re.sub(r"^/(위임|목표)\s*", "", text.strip())
        if conversation_id is not None:
            with self.db.session() as s:
                if s.get(Conversation, conversation_id) is None:
                    raise KeyError(conversation_id)
        # 대화가 아직 없으면 먼저 만들어 워크플로가 알림을 받을 대화로 연결한다(LLM 설정 오류로 실패하면 지운다)
        created_conv = conversation_id is None
        if created_conv:
            with self.db.session() as s:
                conv = Conversation(title=goal[:30])
                s.add(conv)
                s.flush()
                conversation_id = conv.id
        try:
            wid = await self.submit_goal(goal, mode=mode, budget=budget, origin="chat", conversation_id=conversation_id)
        except WorkflowError as e:
            if e.code == "llm":
                if created_conv:
                    with self.db.session() as s:
                        s.delete(s.get(Conversation, conversation_id))
                raise
            return self._save_turn(conversation_id, text, f"요청을 처리하지 못했습니다. 아무것도 실행하지 않았습니다: {e}", {"kind": "workflow", "state": "error"})
        wf = self.wf.get(wid)
        d = wf.policy_decision or {}
        if wf.plan_state != "ok" or not self.wf.steps(wid):
            body = f"목표를 접수했지만 실행 계획을 만들지 못했습니다. 아무것도 실행하지 않았습니다.\n사유: {wf.plan_error or wf.plan_notes or '카탈로그의 직원·업무로 수행할 수 없는 목표입니다'}\n워크플로 #{wid}에서 계획을 다시 만들거나 직접 수정할 수 있습니다."
        else:
            status = "자동 실행을 시작했습니다." if d.get("started") else f"아직 시작하지 않았습니다. {d.get('reason', '')}"
            if d.get("blockers"):
                status += "\n" + "\n".join(f"  - {b}" for b in d["blockers"][:5])
            body = (f"워크플로 #{wid} '{wf.title}'을(를) 만들었습니다. (모드: {MODE_LABEL.get(wf.exec_mode, wf.exec_mode)}, 예산 ${wf.budget_usd:.4f})\n"
                    f"실행 계획:\n{self._plan_text(wid)}\n{status}\n진행 상황은 여기서 \"/상태\"로 물어볼 수 있고, 승인 대기·실패·완료는 이 대화로 알려 드립니다.")
        out = self._save_turn(conversation_id, text, body, {"kind": "workflow", "workflow_id": wid, "state": "created"})
        self.activity.record("autonomy", "autonomy.chat_delegated", workflow_id=wid, conversation_id=conversation_id, mode=wf.exec_mode, started=bool(d.get("started")))
        return out

    def chat_status(self, text: str, conversation_id: int | None) -> dict:
        wfs = self._conv_workflows(conversation_id)
        if not wfs:
            return self._save_turn(conversation_id, text, "이 대화에서 맡긴 워크플로가 없습니다. 입력창의 '직원에게 맡기기'를 켜거나 \"/위임 목표\"로 맡길 수 있습니다.", {"kind": "workflow", "state": "none"})
        lines = []
        for wf in wfs:
            f = self._facts(wf.id)
            rows = f["steps"]
            done = sum(1 for r in rows if r["status"] == "completed")
            cur = [f"{r['worker']}({r['title']}, {'승인 대기' if r['approval_id'] else '실행 중'})" for r in rows if r["status"] in ("running", "awaiting_approval")]
            lines.append(f"워크플로 #{wf.id} '{wf.title}': 상태 {wf.status}, {done}/{len(rows)}단계 완료" + (f", 현재 담당 {', '.join(cur)}" if cur else ""))
            key = self._state_key(f)
            if key and key != "completed" and wf.status in ("running", "failed", "paused"):
                lines.append("  " + self._message(f, key).replace("\n", "\n  "))
            elif wf.status == "planned":
                lines.append("  " + ((wf.policy_decision or {}).get("reason") or "계획 확인 대기 중입니다"))
        return self._save_turn(conversation_id, text, "\n".join(lines), {"kind": "workflow", "state": "status", "workflow_id": wfs[0].id})

    # ------------------------------------------------------------------ 상세 화면용 상태

    def annotate(self, wid: int) -> dict:
        wf = self.wf.get(wid)
        f = self._facts(wid)
        rows = f["steps"]
        a = self.assess(wid) if rows else {"blockers": [], "steps": []}
        current = [{"key": r["key"], "title": r["title"], "worker": r["worker"], "status": r["status"]} for r in rows if r["status"] in ("running", "awaiting_approval")]
        done = {r["key"] for r in rows if r["status"] == "completed"}
        nxt = [{"key": r["key"], "title": r["title"], "worker": r["worker"], "waiting_for": [d for d in r["step"].depends_on if d not in done]}
               for r in rows if r["status"] == "pending"]
        attention: list[str] = []
        d = wf.policy_decision or {}
        if wf.status == "planned" and wf.exec_mode != "manual" and not d.get("started"):
            attention.append(d.get("reason") or "자동 시작되지 않았습니다")
            attention += d.get("blockers", [])
        if wf.status == "paused" and d.get("paused_by") == "autonomy_off":
            attention.append("상시 자율 운영이 꺼져 일시정지되었습니다")
        for r in rows:
            if r["approval_id"]:
                ok, why = self._approval_check(r["step"], wf, a)
                attention.append(f"[{r['title']}] 승인 대기: " + (f"자동 승인 대상이지만 아직 처리되지 않았습니다({why})" if ok else why))
        for r in rows:
            if r["status"] == "failed":
                attention.append(f"[{r['title']}] 실패: {FAIL_LABELS.get(r['error_kind'] or '', r['error_kind'] or '원인 미상')}")
        with self.db.session() as s:
            trig = s.get(AutonomyTrigger, wf.trigger_id) if wf.trigger_id else None
        limit = trig.max_retries if trig else self.settings.autonomy_request_max_retries
        return {"mode": wf.exec_mode, "mode_label": MODE_LABEL.get(wf.exec_mode, wf.exec_mode), "origin": wf.origin, "trigger": {"id": trig.id, "name": trig.name} if trig else None,
                "trigger_reason": wf.trigger_reason, "decision": d, "auto_started": bool(d.get("started")), "current": current, "next": nxt, "attention": attention,
                "auto_retries": wf.auto_retries, "retry_limit": limit if wf.exec_mode != "manual" else 0, "max_mode": self._max_mode(), "conversation_id": wf.conversation_id,
                "auto_approval_possible": wf.exec_mode == "autonomous" and a["auto_runnable"] if rows else False}

    # ------------------------------------------------------------------ 트리거 CRUD

    def _tz(self) -> ZoneInfo:
        return ZoneInfo(self.settings.timezone)

    def _day_start(self) -> datetime:
        tz = self._tz()
        local_midnight = datetime.combine(datetime.now(tz).date(), dtime.min, tzinfo=tz)
        return local_midnight.astimezone(timezone.utc).replace(tzinfo=None)

    def compute_next(self, kind: str, cfg: dict, after: datetime) -> datetime | None:
        if kind == "interval":
            return after + timedelta(minutes=int(cfg["minutes"]))
        if kind == "once":
            run_at = datetime.fromisoformat(str(cfg["run_at"]).replace("Z", "+00:00"))
            if run_at.tzinfo is None:
                run_at = run_at.replace(tzinfo=self._tz())
            at = run_at.astimezone(timezone.utc).replace(tzinfo=None)
            return at if at > after else None
        if kind == "daily":
            hh, mm = (int(x) for x in str(cfg["time"]).split(":"))
            tz = self._tz()
            local_after = after.replace(tzinfo=timezone.utc).astimezone(tz)
            days = cfg.get("weekdays") or list(range(7))
            for i in range(0, 9):
                cand = datetime.combine(local_after.date() + timedelta(days=i), dtime(hh, mm), tzinfo=tz)
                if cand > local_after and cand.weekday() in days:
                    return cand.astimezone(timezone.utc).replace(tzinfo=None)
        return None

    def _validate_trigger(self, data: dict, current: AutonomyTrigger | None = None) -> dict:
        errors: list[str] = []
        d = {**({c.key: getattr(current, c.key) for c in AutonomyTrigger.__table__.columns} if current else {}), **{k: v for k, v in data.items() if v is not None}}
        name = str(d.get("name") or "").strip()
        if not (1 <= len(name) <= 120):
            errors.append("이름은 1~120자여야 합니다")
        kind = d.get("kind")
        if kind not in KINDS:
            errors.append(f"종류는 {', '.join(KINDS)} 중 하나여야 합니다")
        goal = str(d.get("goal") or "").strip()
        if not (3 <= len(goal) <= 1800):
            errors.append("목표는 3~1800자여야 합니다")
        if d.get("exec_mode") not in MODES:
            errors.append(f"실행 모드는 {', '.join(MODES)} 중 하나여야 합니다")
        for key, lo, hi, label in (("cooldown_minutes", 0, 10080, "쿨다운(분)"), ("max_runs_per_day", 1, 100, "하루 최대 실행 횟수"), ("max_retries", 0, 5, "재시도 상한")):
            v = d.get(key)
            if not isinstance(v, int) or isinstance(v, bool) or not (lo <= v <= hi):
                errors.append(f"{label}는 {lo}~{hi} 정수여야 합니다")
        b, cap = d.get("budget_usd"), d.get("daily_cost_cap_usd")
        if not isinstance(b, (int, float)) or isinstance(b, bool) or not (0 < b <= self.settings.workflow_max_budget_usd):
            errors.append(f"실행 1회 예산은 0 초과 {self.settings.workflow_max_budget_usd} 이하(USD)여야 합니다")
        if not isinstance(cap, (int, float)) or isinstance(cap, bool) or not (0 < cap <= 50):
            errors.append("일일 비용 한도는 0 초과 50 이하(USD)여야 합니다")
        elif isinstance(b, (int, float)) and b > cap:
            errors.append("실행 1회 예산이 트리거의 일일 비용 한도보다 클 수 없습니다")
        cfg = d.get("config") if isinstance(d.get("config"), dict) else {}
        if kind == "interval":
            m = cfg.get("minutes")
            if not isinstance(m, int) or isinstance(m, bool) or not (self.settings.autonomy_min_interval_minutes <= m <= 10080):
                errors.append(f"반복 간격은 {self.settings.autonomy_min_interval_minutes}~10080분 정수여야 합니다")
            cfg = {"minutes": m}
        elif kind == "once":
            try:
                if self.compute_next("once", cfg, self.now()) is None and (current is None or cfg != (current.config or {})):
                    errors.append("실행 시각이 이미 지났습니다")
            except (KeyError, ValueError, TypeError):
                errors.append("run_at 은 ISO 형식 시각이어야 합니다(예: 2026-10-20T09:00)")
            cfg = {"run_at": cfg.get("run_at")}
        elif kind == "daily":
            if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", str(cfg.get("time") or "")):
                errors.append("time 은 HH:MM 형식이어야 합니다")
            wd = cfg.get("weekdays", [])
            if not isinstance(wd, list) or not all(isinstance(x, int) and 0 <= x <= 6 for x in wd):
                errors.append("weekdays 는 0(월)~6(일) 정수 목록이어야 합니다")
            cfg = {"time": cfg.get("time"), "weekdays": wd}
        elif kind == "event":
            ev = str(cfg.get("event") or "")
            if not EVENT_RE.match(ev):
                errors.append("event 이름은 영문 소문자로 시작하는 2~40자(영문·숫자·._:-)여야 합니다")
            cfg = {"event": ev}
        elif kind == "proactive":
            from .suggestions import TOPIC_LABELS
            topics = [k for k in TOPIC_LABELS if k != "worker"]  # 직원 결과 알림은 트리거로 쓰지 않는다(직원 -> 알림 -> 직원 순환 방지)
            tk = str(cfg.get("topic_key") or "*")
            if tk != "*" and tk not in topics:
                errors.append(f"topic_key 는 '*' 또는 {', '.join(topics)} 중 하나여야 합니다")
            cfg = {"topic_key": tk}
        elif kind == "chain":
            at, aw = cfg.get("after_trigger_id"), cfg.get("after_workflow_id")
            if (at is None) == (aw is None):
                errors.append("선행 트리거 또는 선행 워크플로 중 하나만 지정하세요")
            with self.db.session() as s:
                if at is not None:
                    if not isinstance(at, int) or s.get(AutonomyTrigger, at) is None:
                        errors.append("존재하지 않는 선행 트리거입니다")
                    elif current is not None and (at == current.id or self._chain_cycle(s, current.id, at)):
                        errors.append("선행 트리거가 순환(자기 자신 포함)하여 무한 반복될 수 있습니다")
                if aw is not None and (not isinstance(aw, int) or s.get(Workflow, aw) is None):
                    errors.append("존재하지 않는 선행 워크플로입니다")
            cfg = {k: v for k, v in (("after_trigger_id", at), ("after_workflow_id", aw)) if v is not None}
        if errors:
            raise AutonomyError("validation", "; ".join(errors))
        return {"name": name, "kind": kind, "goal": goal, "exec_mode": d["exec_mode"], "config": cfg, "budget_usd": float(b), "cooldown_minutes": d["cooldown_minutes"],
                "max_runs_per_day": d["max_runs_per_day"], "daily_cost_cap_usd": float(cap), "max_retries": d["max_retries"], "enabled": bool(d.get("enabled", True))}

    @staticmethod
    def _chain_cycle(s, trigger_id: int, start_after: int) -> bool:
        """trigger_id 가 start_after 의 (직간접) 후속이면 순환이다."""
        seen, cur = set(), start_after
        while cur is not None and cur not in seen:
            if cur == trigger_id:
                return True
            seen.add(cur)
            t = s.get(AutonomyTrigger, cur)
            cur = (t.config or {}).get("after_trigger_id") if t and t.kind == "chain" else None
        return False

    DEFAULTS = {"exec_mode": "supervised", "budget_usd": 0.3, "cooldown_minutes": 60, "max_runs_per_day": 6, "daily_cost_cap_usd": 0.5, "max_retries": 1, "enabled": True}

    def create_trigger(self, data: dict) -> AutonomyTrigger:
        v = self._validate_trigger({**self.DEFAULTS, **{k: x for k, x in data.items() if x is not None}})  # 새 트리거는 아직 후속이 없으므로 순환이 생기지 않는다
        with self.db.session() as s:
            t = AutonomyTrigger(**v, next_fire_at=self.compute_next(v["kind"], v["config"], self.now()) if v["kind"] in ("once", "interval", "daily") else None)
            s.add(t)
            s.flush()
            tid = t.id
        self.activity.record("autonomy", "autonomy.trigger_created", trigger_id=tid, kind=v["kind"], mode=v["exec_mode"])
        self.bus.publish("workflow.updated", {"autonomy": True})
        return self.get_trigger(tid)

    def update_trigger(self, tid: int, data: dict) -> AutonomyTrigger:
        cur = self.get_trigger(tid)
        v = self._validate_trigger({**data, "kind": cur.kind}, cur)  # 종류는 바꿀 수 없다(이력의 의미가 달라진다)
        with self.db.session() as s:
            t = s.get(AutonomyTrigger, tid)
            sched_changed = v["config"] != (t.config or {}) or (v["enabled"] and not t.enabled)
            for k, val in v.items():
                setattr(t, k, val)
            if v["kind"] in ("once", "interval", "daily") and (sched_changed or t.next_fire_at is None and v["enabled"] and v["kind"] != "once"):
                t.next_fire_at = self.compute_next(v["kind"], v["config"], self.now()) if v["enabled"] else t.next_fire_at
            t.updated_at = self.now()
        self.activity.record("autonomy", "autonomy.trigger_updated", trigger_id=tid, enabled=v["enabled"])
        self.bus.publish("workflow.updated", {"autonomy": True})
        return self.get_trigger(tid)

    def delete_trigger(self, tid: int) -> None:
        self.get_trigger(tid)
        with self.db.session() as s:
            # 이 트리거를 선행으로 삼는 연쇄 트리거가 남아 있으면 지울 수 없다(조용히 끊기지 않게)
            for o in s.scalars(select(AutonomyTrigger).where(AutonomyTrigger.kind == "chain")):
                if (o.config or {}).get("after_trigger_id") == tid:
                    raise AutonomyError("conflict", f"트리거 '{o.name}'이(가) 이 트리거 완료 후 실행되도록 연결되어 있어 삭제할 수 없습니다")
            s.delete(s.get(AutonomyTrigger, tid))  # 실행 이력(AutonomyRun)과 워크플로는 남는다
        self.activity.record("autonomy", "autonomy.trigger_deleted", trigger_id=tid)
        self.bus.publish("workflow.updated", {"autonomy": True})

    def get_trigger(self, tid: int) -> AutonomyTrigger:
        with self.db.session() as s:
            t = s.get(AutonomyTrigger, tid)
        if t is None:
            raise AutonomyError("not_found", "trigger not found")
        return t

    def trigger_view(self, t: AutonomyTrigger) -> dict:
        with self.db.session() as s:
            live = s.scalar(select(func.count()).select_from(Workflow).where(Workflow.trigger_id == t.id, Workflow.status.in_(LIVE_WF)))
            last = s.scalars(select(AutonomyRun).where(AutonomyRun.trigger_id == t.id).order_by(AutonomyRun.id.desc())).first()
        return {**row_dict(t), "live_workflows": int(live or 0), "spent_today_usd": round(self._spend_today(t.id), 4),
                "last_run": row_dict(last) if last else None}

    def list_triggers(self) -> list[dict]:
        with self.db.session() as s:
            rows = list(s.scalars(select(AutonomyTrigger).order_by(AutonomyTrigger.id)))
        return [self.trigger_view(t) for t in rows]

    def list_runs(self, limit: int = 50) -> list[dict]:
        with self.db.session() as s:
            rows = list(s.scalars(select(AutonomyRun).order_by(AutonomyRun.id.desc()).limit(limit)))
            names = {t.id: t.name for t in s.scalars(select(AutonomyTrigger))}
            wf = {w.id: w for w in s.scalars(select(Workflow).where(Workflow.id.in_([r.workflow_id for r in rows if r.workflow_id])))} if rows else {}
        return [{**row_dict(r), "trigger_name": names.get(r.trigger_id), "workflow_title": wf[r.workflow_id].title if r.workflow_id in wf else None,
                 "workflow_status": wf[r.workflow_id].status if r.workflow_id in wf else None} for r in rows]

    # ------------------------------------------------------------------ 발동: 게이트(코드) -> 슬롯 점유 -> 기존 엔진에 목표 전달

    def _spend_today(self, trigger_id: int | None = None) -> float:
        """오늘 상시 자율 운영(트리거)이 쓴 비용 = 오늘 만든 워크플로의 계획 비용 + 오늘 발생한 모든 실행 비용."""
        start = self._day_start()
        with self.db.session() as s:
            q = select(Workflow.id).where(Workflow.origin.in_(TRIGGER_ORIGINS))
            if trigger_id is not None:
                q = q.where(Workflow.trigger_id == trigger_id)
            ids = list(s.scalars(q))
            if not ids:
                return 0.0
            run_cost = s.scalar(select(func.coalesce(func.sum(WorkerRun.cost_usd), 0.0)).where(WorkerRun.workflow_id.in_(ids), WorkerRun.created_at >= start))
            plan_cost = s.scalar(select(func.coalesce(func.sum(Workflow.planning_cost_usd), 0.0)).where(Workflow.id.in_(ids), Workflow.created_at >= start))
        return float(run_cost or 0.0) + float(plan_cost or 0.0)

    def _reserved(self) -> tuple[float, dict[int, float]]:
        """진행 중(running/paused)인 자율 워크플로의 남은 예산(예산 - 지금까지 사용). (전체 합, 트리거별 합)."""
        total, per = 0.0, {}
        with self.db.session() as s:
            live = list(s.scalars(select(Workflow).where(Workflow.origin.in_(TRIGGER_ORIGINS), Workflow.status.in_(("running", "paused")))))
        for w in live:
            left = max(w.budget_usd - self.wf._spent(w.id), 0.0)
            total += left
            per[w.trigger_id] = per.get(w.trigger_id, 0.0) + left
        return total, per

    def _skip(self, t: AutonomyTrigger, code: str, message: str, reason: str) -> AutonomyRun:
        with self.db.session() as s:
            r = AutonomyRun(trigger_id=t.id, slot_key=None, reason=reason, status="skipped", skip_reason=code, detail={"message": message}, created_at=self.now(), updated_at=self.now())
            s.add(r)
            s.flush()
            out = r
        self.activity.record("autonomy", "autonomy.skipped", level="info", trigger_id=t.id, code=code, message=message)
        return out

    def gate(self, t: AutonomyTrigger, chain_depth: int = 0) -> tuple[str, str] | None:
        """발동 전 코드 검사. 막히면 (코드, 사유), 통과하면 None."""
        cfg = self.config()
        if not cfg["enabled"]:
            return "disabled", "상시 자율 운영이 꺼져 있습니다"
        if not t.enabled:
            return "trigger_disabled", "이 트리거가 비활성화되어 있습니다"
        if chain_depth > self.settings.autonomy_max_chain_depth:
            return "loop_guard", f"연쇄 깊이가 상한({self.settings.autonomy_max_chain_depth})을 넘어 반복을 막았습니다"
        now = self.now()
        with self.db.session() as s:
            if s.scalar(select(func.count()).select_from(Workflow).where(Workflow.trigger_id == t.id, Workflow.status.in_(LIVE_WF))):
                return "already_running", "이 트리거가 시작한 워크플로가 아직 끝나지 않았습니다"
            live_goals = {_norm_goal(g) for g in s.scalars(select(Workflow.goal).where(Workflow.origin.in_(TRIGGER_ORIGINS), Workflow.status.in_(LIVE_WF)))}
            running = s.scalar(select(func.count()).select_from(Workflow).where(Workflow.origin.in_(TRIGGER_ORIGINS), Workflow.status == "running"))
            last = s.scalars(select(AutonomyRun).where(AutonomyRun.trigger_id == t.id, AutonomyRun.slot_key.is_not(None)).order_by(AutonomyRun.id.desc())).first()
            today = s.scalar(select(func.count()).select_from(AutonomyRun).where(AutonomyRun.trigger_id == t.id, AutonomyRun.slot_key.is_not(None), AutonomyRun.created_at >= self._day_start()))
        if _norm_goal(t.goal) in live_goals:
            return "duplicate_goal", "같은 목표의 자율 업무가 이미 진행 중입니다"
        if last is not None and now - last.created_at < timedelta(minutes=t.cooldown_minutes):
            return "cooldown", f"쿨다운({t.cooldown_minutes}분) 중입니다"
        if int(today or 0) >= t.max_runs_per_day:
            return "daily_limit", f"하루 최대 실행 횟수({t.max_runs_per_day}회)에 도달했습니다"
        if int(running or 0) >= cfg["max_concurrent"]:
            return "concurrency", f"동시 실행 한도({cfg['max_concurrent']}건)에 도달했습니다"
        reserved = self._reserved()  # 이미 실행 중인 자율 워크플로가 앞으로 쓸 수 있는 예산도 한도에서 미리 뺀다(동시에 여러 건이 한도를 넘지 못하게)
        spent, spent_t = self._spend_today() + reserved[0], self._spend_today(t.id) + reserved[1].get(t.id, 0.0)
        if spent + t.budget_usd > cfg["daily_cost_cap_usd"] + 1e-9:
            return "daily_budget", f"일일 자율 비용 한도 ${cfg['daily_cost_cap_usd']:.2f}를 넘을 수 있습니다(오늘 ${spent:.4f} + 실행 예산 ${t.budget_usd:.2f})"
        if spent_t + t.budget_usd > t.daily_cost_cap_usd + 1e-9:
            return "trigger_budget", f"이 트리거의 일일 비용 한도 ${t.daily_cost_cap_usd:.2f}를 넘을 수 있습니다(오늘 ${spent_t:.4f} + 실행 예산 ${t.budget_usd:.2f})"
        return None

    def _claim(self, t: AutonomyTrigger, slot: str, reason: str) -> int | None:
        """슬롯을 점유한다(유일 키). 이미 있으면 같은 발동의 중복이므로 None. 점유와 발동 횟수 갱신은 한 트랜잭션이다."""
        try:
            with self.db.session() as s:
                r = AutonomyRun(trigger_id=t.id, slot_key=slot[:160], reason=reason, status="starting", created_at=self.now(), updated_at=self.now())
                s.add(r)
                s.flush()
                rid = r.id
                row = s.get(AutonomyTrigger, t.id)
                row.last_fired_at, row.fire_count = self.now(), row.fire_count + 1
            return rid
        except IntegrityError:
            return None

    async def fire(self, tid: int, *, reason: str, slot: str, chain_depth: int = 0, context: str = "") -> dict:
        """트리거 1회 발동. 반환: {"status": started|blocked|skipped|duplicate|failed, ...}."""
        t = self.get_trigger(tid)
        with self.db.session() as s:
            if s.scalar(select(func.count()).select_from(AutonomyRun).where(AutonomyRun.slot_key == slot[:160])):
                self.activity.record("autonomy", "autonomy.duplicate_slot", trigger_id=tid, slot=slot)
                return {"status": "duplicate", "slot": slot}
        blocked = self.gate(t, chain_depth)
        if blocked:
            r = self._skip(t, blocked[0], blocked[1], reason)
            return {"status": "skipped", "code": blocked[0], "message": blocked[1], "run_id": r.id}
        rid = self._claim(t, slot, reason)
        if rid is None:
            self.activity.record("autonomy", "autonomy.duplicate_slot", trigger_id=tid, slot=slot)
            return {"status": "duplicate", "slot": slot}
        goal = t.goal + (f"\n(발생 맥락: {context[:300]})" if context else "")
        try:
            wid = await self.submit_goal(goal, mode=t.exec_mode, budget=t.budget_usd, origin=KIND_ORIGIN[t.kind], trigger_id=t.id, reason=reason, chain_depth=chain_depth)
        except WorkflowError as e:
            self._finish_run(rid, "failed", {"error": str(e)})
            self.activity.record("autonomy", "autonomy.fire_failed", level="warn", trigger_id=tid, error=str(e)[:300])
            return {"status": "failed", "run_id": rid, "error": str(e)}
        except Exception as e:  # 한 트리거의 예기치 못한 실패가 스케줄러를 멈추지 않는다
            logger.exception("autonomy fire failed")
            self._finish_run(rid, "failed", {"error": type(e).__name__})
            return {"status": "failed", "run_id": rid, "error": type(e).__name__}
        wf = self.wf.get(wid)
        d = wf.policy_decision or {}
        if wf.plan_state != "ok":
            status = "failed"
            detail = {"error": wf.plan_error}
        elif d.get("started"):
            status, detail = "started", {}
        else:
            status, detail = "blocked", {"reason": d.get("reason"), "blockers": d.get("blockers", [])}
        self._finish_run(rid, status, detail, wid)
        self.activity.record("autonomy", f"autonomy.fire_{status}", trigger_id=tid, workflow_id=wid, reason=reason)
        return {"status": status, "run_id": rid, "workflow_id": wid}

    def _finish_run(self, rid: int, status: str, detail: dict, wid: int | None = None) -> None:
        with self.db.session() as s:
            r = s.get(AutonomyRun, rid)
            r.status, r.detail, r.updated_at = status, {**(r.detail or {}), **detail}, self.now()
            if wid is not None:
                r.workflow_id = wid

    # --- 트리거 종류별 진입점

    async def tick(self) -> None:
        """스케줄러가 주기적으로 호출한다: 진행 동기화 -> (켜져 있으면) 도래한 일정 발동 -> 일시적 실패 자동 재시도."""
        if self._tick_lock.locked():
            return
        async with self._tick_lock:
            await self._retry_failed()
            if not self.enabled():
                return
            now = self.now()
            with self.db.session() as s:
                due = [t.id for t in s.scalars(select(AutonomyTrigger).where(AutonomyTrigger.enabled.is_(True), AutonomyTrigger.next_fire_at.is_not(None), AutonomyTrigger.next_fire_at <= now))]
            for tid in due:
                t = self.get_trigger(tid)
                at = t.next_fire_at
                slot = f"t{t.id}:{at.isoformat()}"
                with self.db.session() as s:  # 발동 시도 전에 다음 일정으로 넘긴다: 실패·건너뜀·재시작이 같은 일정을 반복 실행하지 못한다(최대 한 번)
                    row = s.get(AutonomyTrigger, tid)
                    row.next_fire_at = self.compute_next(t.kind, t.config, now) if t.kind != "once" else None
                if t.kind == "once" and now - at > timedelta(minutes=self.settings.autonomy_missed_grace_minutes):
                    self._skip(t, "missed", f"예정 시각({at.isoformat()}Z)에서 {self.settings.autonomy_missed_grace_minutes}분 넘게 지나 실행하지 않았습니다", "일정 시각 도래")
                    continue
                label = {"once": "한 번 실행 예약", "interval": f"{(t.config or {}).get('minutes')}분 간격 반복", "daily": f"매일 {(t.config or {}).get('time')}"}[t.kind]
                await self.fire(tid, reason=f"예약 일정 도래: {label} (예정 {at.isoformat()}Z)", slot=slot)

    async def emit_event(self, name: str, key: str | None = None) -> list[dict]:
        if not EVENT_RE.match(name or ""):
            raise AutonomyError("validation", "이벤트 이름이 올바르지 않습니다")
        with self.db.session() as s:
            ids = [t.id for t in s.scalars(select(AutonomyTrigger).where(AutonomyTrigger.kind == "event", AutonomyTrigger.enabled.is_(True)))
                   if (t.config or {}).get("event") == name]
        out = []
        stamp = key or self.now().strftime("%Y%m%d%H%M")
        for tid in ids:
            out.append(await self.fire(tid, reason=f"이벤트 '{name}' 발생", slot=f"t{tid}:ev:{name}:{stamp}"))
        self.activity.record("autonomy", "autonomy.event", name=name, triggers=len(ids))
        return out

    def emit_event_bg(self, name: str) -> None:
        try:
            self._spawn(self.emit_event(name))
        except RuntimeError:
            pass

    def on_proactive(self, suggestion_id: int, topic_key: str, title: str) -> None:
        """ProactiveEngine 이 제안을 전달했을 때 호출된다(사용자 상황 기반 선제 제안을 트리거로 쓴다)."""
        with self.db.session() as s:
            ids = [t.id for t in s.scalars(select(AutonomyTrigger).where(AutonomyTrigger.kind == "proactive", AutonomyTrigger.enabled.is_(True)))
                   if (t.config or {}).get("topic_key") in ("*", topic_key)]
        for tid in ids:
            try:
                self._spawn(self.fire(tid, reason=f"능동 제안 #{suggestion_id} 전달: {title[:80]}", slot=f"t{tid}:sg{suggestion_id}", context=title))
            except RuntimeError:
                pass

    def _chain(self, wid: int) -> None:
        wf = self.wf.get(wid)
        if wf.status != "completed":
            return
        with self.db.session() as s:
            ids = [(t.id, t.name) for t in s.scalars(select(AutonomyTrigger).where(AutonomyTrigger.kind == "chain", AutonomyTrigger.enabled.is_(True)))
                   if (t.config or {}).get("after_workflow_id") == wid or (wf.trigger_id is not None and (t.config or {}).get("after_trigger_id") == wf.trigger_id)]
        for tid, _ in ids:
            try:
                self._spawn(self.fire(tid, reason=f"선행 업무 완료: 워크플로 #{wid} '{wf.title[:40]}'", slot=f"t{tid}:wf{wid}", chain_depth=wf.chain_depth + 1, context=wf.title))
            except RuntimeError:
                pass

    def _spawn(self, coro) -> None:
        task = asyncio.get_running_loop().create_task(coro)  # 루프가 없으면 RuntimeError(호출자가 무시)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    # ------------------------------------------------------------------ 실패 재시도(일시적 실패만, 상한 적용)

    async def _retry_failed(self) -> None:
        cfg_on = self.enabled()
        now = self.now()
        with self.db.session() as s:
            wfs = list(s.scalars(select(Workflow).where(Workflow.status == "failed", Workflow.exec_mode != "manual")))
        for wf in wfs:
            if wf.origin in TRIGGER_ORIGINS and not cfg_on:
                continue
            with self.db.session() as s:
                trig = s.get(AutonomyTrigger, wf.trigger_id) if wf.trigger_id else None
            limit = trig.max_retries if trig else self.settings.autonomy_request_max_retries
            if wf.auto_retries >= limit or wf.ended_at is None or now - wf.ended_at < timedelta(minutes=self.settings.autonomy_retry_delay_minutes):
                continue
            failed = [s for s in self.wf.steps(wf.id) if s.status in ("failed", "cancelled")]
            if not failed or any(s.status == "cancelled" or s.error_kind not in TRANSIENT for s in failed):
                continue  # 사용자가 판단해야 하는 실패(검증·반려·예산·자료 부족 등)는 자동으로 다시 하지 않는다
            if not self.assess(wf.id)["auto_runnable"]:
                continue
            with self.db.session() as s:
                s.get(Workflow, wf.id).auto_retries += 1  # 시도 전에 먼저 센다: 재시도가 또 실패해도 상한을 넘지 않는다
            self.activity.record("autonomy", "autonomy.retry", level="warn", workflow_id=wf.id, attempt=wf.auto_retries + 1, limit=limit, steps=[s.key for s in failed])
            for st in failed:
                try:
                    await self.wf.retry_step(wf.id, st.key)
                except WorkflowError:
                    break

    # ------------------------------------------------------------------ 시작/복구

    def recover(self) -> dict:
        """서버 시작 시: 시작 도중 끊긴 발동을 정리한다(슬롯은 이미 소진됐으므로 다시 실행하지 않는다). 일정은 DB 의 next_fire_at 에서 이어진다."""
        n = 0
        with self.db.session() as s:
            for r in s.scalars(select(AutonomyRun).where(AutonomyRun.status == "starting")):
                wf = s.scalars(select(Workflow).where(Workflow.trigger_id == r.trigger_id, Workflow.created_at >= r.created_at).order_by(Workflow.id)).first()
                if wf is not None:
                    r.workflow_id, r.status = wf.id, "started" if wf.status in ("running", "paused", "completed") else "blocked"
                else:
                    r.status, r.detail = "failed", {**(r.detail or {}), "error": "서버가 재시작되어 시작이 중단되었습니다. 중복 실행을 막기 위해 자동으로 다시 시작하지 않습니다"}
                r.updated_at = self.now()
                n += 1
        if n:
            self.activity.record("autonomy", "autonomy.recovered", level="warn", interrupted=n)
        return {"interrupted": n}

    # ------------------------------------------------------------------ 대시보드 요약

    def overview(self) -> dict:
        with self.db.session() as s:
            auto = list(s.scalars(select(Workflow).where(Workflow.exec_mode != "manual").order_by(Workflow.id.desc()).limit(80)))
            trig = list(s.scalars(select(AutonomyTrigger).order_by(AutonomyTrigger.id)))
        def card(w: Workflow) -> dict:
            a = self.annotate(w.id)
            sts = self.wf.steps(w.id)
            return {"id": w.id, "title": w.title or w.goal[:40], "status": w.status, "mode": w.exec_mode, "origin": w.origin, "trigger_reason": w.trigger_reason,
                    "done": sum(1 for x in sts if x.status == "completed"), "total": len(sts), "current": a["current"], "attention": a["attention"], "ended_at": w.ended_at,
                    "created_at": w.created_at}
        cards = [card(w) for w in auto]
        needs = [c for c in cards if c["attention"] and c["status"] not in ("completed", "cancelled")]
        upcoming = sorted((t for t in trig if t.enabled and t.next_fire_at is not None), key=lambda t: t.next_fire_at)
        return {"config": self.config(),
                "running": [c for c in cards if c["status"] == "running"],
                "needs_attention": needs,
                "completed": [c for c in cards if c["status"] == "completed"][:5],
                "upcoming": [{"id": t.id, "name": t.name, "kind": t.kind, "next_fire_at": t.next_fire_at.isoformat() + "Z", "mode": t.exec_mode} for t in upcoming[:6]],
                "event_triggers": [{"id": t.id, "name": t.name, "kind": t.kind, "config": t.config} for t in trig if t.enabled and t.kind in ("event", "proactive", "chain")][:6],
                "recent_runs": self.list_runs(8)}
