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

    def decide(self, tool_name: str) -> str:
        tool = self.registry.get(tool_name)
        if tool is None:
            return "deny"
        return "allow" if tool.risk == "read" else "approval"

    async def invoke(
        self, name: str, args: dict[str, Any], *, actor: str, reason: str = "", debate_id: int | None = None
    ) -> InvokeResult:
        verdict = self.decide(name)
        if verdict == "deny":
            self.activity.record("policy", "tool.denied", level="warn", agent_id=actor, debate_id=debate_id, tool=name)
            return InvokeResult("denied", error=f"unknown tool: {name}")
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

    async def decide_approval(self, approval_id: int, approve: bool) -> dict:
        with self.db.session() as s:
            a = s.get(Approval, approval_id)
            if a is None:
                raise KeyError(approval_id)
            if a.status != "pending":
                raise ValueError(f"approval already {a.status}")
            tool, args = a.tool, dict(a.args)
            a.decided_at = utcnow()
            if not approve:
                a.status = "rejected"
        if approve:
            try:
                result, status = await self.registry.execute(tool, args), "executed"
            except ToolError as e:
                result, status = {"error": str(e)}, "failed"
            with self.db.session() as s:
                a = s.get(Approval, approval_id)
                a.status, a.result = status, result
        self.activity.record(
            "policy", "approval.approved" if approve else "approval.rejected", id=approval_id, tool=tool
        )
        with self.db.session() as s:
            payload = row_dict(s.get(Approval, approval_id))
        self.bus.publish("approval.updated", payload)
        return payload
