from dataclasses import dataclass
from typing import Any

from .activity import Activity
from .db import Database
from .events import EventBus
from .models import Approval, row_dict, utcnow
from .tools import ToolError, ToolRegistry


@dataclass
class InvokeResult:
    status: str  # ok | approval_required | denied | error
    data: dict | None = None
    approval_id: int | None = None
    error: str | None = None
    error_kind: str | None = None  # timeout | network | http_503 | no_data | unsupported_date | internal ...
    attempts: int = 1


class Policy:
    """호출자(에이전트, GYUVIS)와 도구 사이의 단일 관문.

    read 도구는 즉시 실행하고, write/external 도구는 사용자 승인 후에만 실행한다.
    """

    def __init__(self, registry: ToolRegistry, db: Database, bus: EventBus, activity: Activity):
        self.registry = registry
        self.db = db
        self.bus = bus
        self.activity = activity
        # 도구 레지스트리에 노출하지 않는 내부 승인 항목(예: AI 직원 결과물 확정)의 처리기: 이름 -> async (args, approve) -> result
        self.internal: dict = {}

    def decide(self, tool_name: str) -> str:
        tool = self.registry.get(tool_name)
        if tool is None:
            return "deny"
        if tool.risk == "project":
            return "project"  # 프로젝트 도구: 허용 여부는 직원의 프로젝트 권한(도구 안에서 검사)이 정한다
        return "allow" if tool.risk == "read" else "approval"

    async def invoke(
        self, name: str, args: dict[str, Any], *, actor: str, reason: str = "", debate_id: int | None = None, ctx: dict | None = None
    ) -> InvokeResult:
        verdict = self.decide(name)
        if verdict == "deny":
            self.activity.record("policy", "tool.denied", level="warn", agent_id=actor, debate_id=debate_id, tool=name)
            return InvokeResult("denied", error=f"unknown tool: {name}")
        if verdict == "project":
            # ctx(직원·실행 ID)는 서버가 넣는 값이다. 모델이 만든 인자에 같은 이름(_로 시작)이 있으면 위조 시도이므로 거부한다.
            if not ctx or any(str(k).startswith("_") for k in args):
                self.activity.record("policy", "tool.denied", level="warn", agent_id=actor, tool=name, reason="project tool needs server context")
                return InvokeResult("denied", error="프로젝트 도구는 직원 업무 실행 안에서만 쓸 수 있습니다", error_kind="no_context")
            try:
                data = await self.registry.execute(name, {**args, "_ctx": ctx})
            except Exception as e:
                kind = e.kind if isinstance(e, ToolError) else "internal"
                self.activity.record("tool", "tool.error", level="warn", agent_id=actor, tool=name, error_kind=kind, error=str(e) if isinstance(e, ToolError) else type(e).__name__)
                return InvokeResult("error", error=str(e) if isinstance(e, ToolError) else type(e).__name__, error_kind=kind)
            self.activity.record("tool", "tool.ok", agent_id=actor, tool=name, args={k: (v if not isinstance(v, str) or len(v) < 200 else v[:200] + "…") for k, v in args.items()})
            return InvokeResult("ok", data=data)
        if verdict == "approval":
            return InvokeResult(
                "approval_required", approval_id=self.request_approval(name, args, actor, reason, debate_id)
            )
        safe_args = {k: v for k, v in args.items() if k not in ("latitude", "longitude")}  # 위치 좌표는 로그에 남기지 않는다
        try:
            data = await self.registry.execute(name, args)
        except Exception as e:  # 도구 하나의 실패가 호출자(서버)로 전파되지 않도록 격리한다
            kind = e.kind if isinstance(e, ToolError) else "internal"
            attempts = e.attempts if isinstance(e, ToolError) else 1
            self.activity.record(
                "tool",
                "tool.error",
                level="warn",
                agent_id=actor,
                debate_id=debate_id,
                tool=name,
                args=safe_args,
                error_kind=kind,
                attempts=attempts,
                error=str(e) if isinstance(e, ToolError) else type(e).__name__,
            )
            return InvokeResult("error", error=str(e) if isinstance(e, ToolError) else type(e).__name__, error_kind=kind, attempts=attempts)
        self.activity.record("tool", "tool.ok", agent_id=actor, debate_id=debate_id, tool=name, args=safe_args)
        return InvokeResult("ok", data=data)

    def request_approval(self, name: str, args: dict, actor: str, reason: str, debate_id: int | None) -> int:
        with self.db.session() as s:
            a = Approval(tool=name, args=args, reason=reason, requested_by=actor, debate_id=debate_id)
            s.add(a)
            s.flush()
            payload, approval_id = row_dict(a), a.id
        self.activity.record("policy", "approval.requested", agent_id=actor, debate_id=debate_id, tool=name, id=approval_id)
        self.bus.publish("approval.created", payload)
        return approval_id

    async def decide_approval(self, approval_id: int, approve: bool, decided_by: str | None = None) -> dict:
        """승인/반려. decided_by 가 None 이면 사용자의 결정이다(자동 승인 정책은 "autonomy:policy" 를 남겨 구분한다)."""
        with self.db.session() as s:
            a = s.get(Approval, approval_id)
            if a is None:
                raise KeyError(approval_id)
            if a.status != "pending":
                raise ValueError(f"approval already {a.status}")
            tool, args = a.tool, dict(a.args)
            a.decided_at = utcnow()
            a.decided_by = decided_by
            if not approve:
                a.status = "rejected"
        handler = self.internal.get(tool)
        if approve or handler is not None:
            try:
                if handler is not None:  # 반려도 처리기에 알려 상태를 정리하게 한다
                    result, status = await handler(args, approve, approval_id), "executed" if approve else "rejected"
                else:
                    result, status = await self.registry.execute(tool, args), "executed"
            except ToolError as e:
                result, status = {"error": str(e)}, "failed"
            if status != "rejected":
                with self.db.session() as s:
                    a = s.get(Approval, approval_id)
                    a.status, a.result = status, result
        self.activity.record(
            "policy", "approval.approved" if approve else "approval.rejected", id=approval_id, tool=tool, decided_by=decided_by or "user"
        )
        with self.db.session() as s:
            payload = row_dict(s.get(Approval, approval_id))
        self.bus.publish("approval.updated", payload)
        return payload
