import asyncio
import json
import logging
import time
from typing import Callable

from sqlalchemy import select

from .activity import Activity
from .config import Settings
from .context import ContextManager
from .db import Database
from .events import EventBus
from .llm import LLMError, LLMGateway
from .memory import MemoryManager
from .models import Conversation, Debate, Message, Memory, row_dict, utcnow
from .policy import InvokeResult, Policy
from .routing import PRIVATE_KEYS, ConversationRouter, Routing, describe_conditions

logger = logging.getLogger("gyunexus")

PERSONA = """당신은 GYUVIS(규비스), 사용자 한 사람을 위한 개인 AI 비서입니다. 침착하고 믿음직하되 과장 없이, 사람처럼 자연스러운 한국어로 대화합니다.
- 짧은 대화체로 답하고, 필요할 때만 길게 설명합니다.
- '기억'은 사용자에 대해 알고 있는 내용입니다. 관련 있을 때만 자연스럽게 녹이고, 나열하거나 "기억에 따르면" 같은 말은 쓰지 않습니다.
- 모르는 것은 모른다고 말하고 지어내지 않습니다.
- 날씨·천문·시세 같은 실시간 정보는 [조회한 사실]에 있는 값만 말합니다. 없으면 "확인하지 못했다"고 밝히고, 확인하려면 어떤 데이터(위치, 조회 도구 등)가 필요한지 안내합니다. 일반론으로 때우거나 그럴듯하게 추측하지 않습니다.
- 이전 대화에 나온 날씨·천문 수치는 그때 조건(날짜·장소)의 값입니다. 조건이 바뀌었으면 이번에 조회한 [조회한 사실]만 현재 값으로 말하고, 이전 수치를 현재 값처럼 말하지 않습니다.
- 지금 대화에서는 PC 제어나 외부 서비스 실행을 할 수 없습니다. 실행한 것처럼 말하지 않습니다.
- 에이전트 토론 결과를 전할 때는 검증된 사실과 추정을 구분해서 말합니다."""

FACT_KEYS = {"astro.moon_phase": "moon", "weather.forecast": "weather"}
TOOL_LABELS = {"astro.moon_phase": "달 위상", "weather.forecast": "날씨 예보"}
RESULT_SUMMARY_KEYS = ("date", "period", "avg_cloud_cover_pct", "max_precip_prob_pct", "avg_temp_c", "window_passed",
                       "phase", "illumination_pct")
FAILURE_REASONS = {
    "timeout": "응답 시간이 초과되었습니다",
    "network": "네트워크 연결에 실패했습니다",
    "bad_response": "응답 형식이 올바르지 않았습니다",
    "no_data": "요청한 시간대의 예보 데이터가 없습니다",
    "unsupported_date": "지원하지 않는 날짜 범위입니다",
    "no_location": "위치가 설정되어 있지 않습니다",
    "internal": "내부 오류가 발생했습니다",
}


def failure_message(tool: str, r: InvokeResult, conditions: str) -> str:
    """도구 실패를 사용자가 이해할 수 있는 안내로 바꾼다. 이전 조회 값을 현재 사실로 쓰지 못하게 명시한다."""
    kind = r.error_kind or "internal"
    if kind.startswith("http_"):
        reason = f"외부 서비스가 일시적으로 오류(HTTP {kind[5:]})를 반환했습니다"
    else:
        reason = FAILURE_REASONS.get(kind, "알 수 없는 오류가 발생했습니다")
    return (
        f"{TOOL_LABELS.get(tool, tool)}: 이번 조건({conditions})의 조회에 실패했습니다 - {reason} ({r.attempts}회 시도). "
        "지금은 확인할 수 없다고 알리고, 잠시 후 다시 물어보면 다시 조회한다고 안내하세요. "
        "이전에 조회한 값은 현재 조건의 사실이 아니므로 사용하지 마세요."
    )


class ConversationEngine:
    def __init__(
        self,
        db: Database,
        llm: LLMGateway,
        memory: MemoryManager,
        context: ContextManager,
        policy: Policy,
        router: ConversationRouter,
        bus: EventBus,
        activity: Activity,
        settings: Settings,
        on_new_memories: Callable[[list[Memory]], None] | None = None,
    ):
        self.db, self.llm, self.memory, self.context, self.policy = db, llm, memory, context, policy
        self.router = router
        self.bus, self.activity, self.settings = bus, activity, settings
        self.on_new_memories = on_new_memories
        self._background: set[asyncio.Task] = set()

    async def _execute_plan(self, routing: Routing, trace: dict) -> tuple[dict, list[str]]:
        """라우터가 세운 계획대로 읽기 도구를 실행한다(조회는 항상 현재 조건으로 새로 수행). (사실, 조회하지 못한 데이터)."""
        trace["steps"].append(f"의도 해석({routing.interpreted_by}): {routing.intent} - {routing.reason}")
        if routing.intent == "chat":
            return {}, []
        trace["sky_intent"] = routing.state is not None and routing.state.topic == "sky_observation"
        conditions = describe_conditions(routing.state)
        results = await asyncio.gather(*(self.policy.invoke(p["tool"], p["args"], actor="gyuvis") for p in routing.plan))
        facts: dict = {}
        unavailable = list(routing.unavailable)
        for p, r in zip(routing.plan, results):
            safe_args = {k: v for k, v in p["args"].items() if k not in PRIVATE_KEYS}
            entry = {"name": p["tool"], "status": r.status, "reason": p["reason"], "args": safe_args}
            if r.status == "ok":
                facts[FACT_KEYS.get(p["tool"], p["tool"])] = r.data
                entry["result"] = {k: r.data[k] for k in RESULT_SUMMARY_KEYS if k in (r.data or {})}
                if (r.data or {}).get("window_passed"):
                    # 오늘의 이미 지난 시간대: 앞으로의 관측 조건처럼 말하지 않도록 명시한다
                    facts.pop(FACT_KEYS.get(p["tool"], p["tool"]), None)  # 지난 시간대의 값은 모델에 전달하지 않는다
                    unavailable.append(
                        f"요청한 시간대({conditions})는 이미 지나서 예보 값을 제공하지 않습니다. 앞으로의 날씨·구름 조건을 말하지 말고 "
                        "이미 지난 시간대라고 알린 뒤, 다음 시간대(예: 다음 날 새벽)를 원하는지 물어보세요."
                    )
                    routing.advice.append("요청한 시간대는 이미 지났습니다")
                    entry["window_passed"] = True
            else:
                entry.update(error=r.error, error_kind=r.error_kind, attempts=r.attempts)
                unavailable.append(failure_message(p["tool"], r, conditions))
            trace["tools"].append(entry)
        for sk in routing.skipped:
            trace["tools"].append({"name": sk["tool"], "status": "skipped", "error": sk["reason"], "reason": sk["reason"]})
        trace["steps"].append(f"도구 {len(routing.plan)}건 실행, {len(routing.skipped)}건 건너뜀")
        return facts, unavailable

    def _system_prompt(self, query: str, facts: dict, missing: list[str], conditions: str | None) -> tuple[str, list[Memory]]:
        ctx = self.context.snapshot()
        mems = self.memory.retrieve(query)
        parts = [
            PERSONA,
            f"[현재 상황] {ctx['local_time']} {ctx['weekday']} {ctx['part_of_day']}"
            + (", 퇴근 이후 시간" if ctx["after_work_hours"] and not ctx["is_weekend"] else "")
            + (", 주말" if ctx["is_weekend"] else ""),
        ]
        if mems:
            parts.append("[기억]\n" + "\n".join(f"- {m.content}" for m in mems))
        with self.db.session() as s:
            debates = list(
                s.scalars(select(Debate).where(Debate.status == "completed").order_by(Debate.id.desc()).limit(8))
            )
            lines = []
            for d in debates:  # 폐기된 아이디어와 검증되지 않은 요약은 추천 근거로 쓰지 않는다(채택/추가 조사 항목만)
                rec = (d.result or {}).get("recommendation") or {}
                if not (rec.get("accepted") or rec.get("needs_research")):
                    continue
                warn = "; ".join(((d.result or {}).get("warnings") or [])[:2])
                lines.append(
                    f"- #{d.id} {d.title}: 채택 {rec.get('accepted') or '없음'} / 추가 조사 필요(추천하지 말 것) {rec.get('needs_research') or '없음'}"
                    + (f" / 경고: {warn}" if warn else "")
                )
        if lines:
            parts.append("[최근 에이전트 토론 결과]\n" + "\n".join(lines[:3]))
        if conditions:
            parts.append(f"[이번 질문의 해석] {conditions}\n(이전 질문의 조건 중 바뀌지 않은 것은 유지된 값입니다)")
        if facts or missing:
            parts.append(
                "[조회한 사실] (이번 질문의 현재 조건으로 도구에서 실제 조회한 값. 날씨·천문 조건은 이 안의 내용만 말할 수 있음)\n"
                + (json.dumps(facts, ensure_ascii=False) if facts else "(없음)")
            )
        if missing:
            parts.append(
                "[조회하지 못한 데이터]\n"
                + "\n".join(f"- {m}" for m in missing)
                + "\n위 항목에 해당하는 조건(구름, 강수, 월출입, 시야, 뉴스 등)은 추측하거나 일반론으로 단정하지 마세요. "
                "아직 확인하지 못했다고 밝히고, 판단하려면 어떤 데이터가 필요한지 사용자에게 안내하세요. "
                "[조회한 사실]에 있는 값은 그대로 활용해도 됩니다."
            )
        return "\n\n".join(parts), mems

    def latest_conversation_id(self) -> int:
        """GYUVIS가 먼저 보내는 메시지를 받을 대화. 없으면 새로 만든다."""
        with self.db.session() as s:
            conv = s.scalars(select(Conversation).order_by(Conversation.updated_at.desc()).limit(1)).first()
            if conv is None:
                conv = Conversation(title="GYUVIS")
                s.add(conv)
                s.flush()
            return conv.id

    def post_assistant_message(self, text: str, meta: dict) -> dict:
        """GYUVIS가 먼저 보내는(능동) 메시지를 최근 대화에 추가한다."""
        conv_id = self.latest_conversation_id()
        with self.db.session() as s:
            msg = Message(conversation_id=conv_id, role="assistant", content=text, proactive=True, meta=meta)
            s.add(msg)
            s.get(Conversation, conv_id).updated_at = utcnow()
            s.flush()
            payload = row_dict(msg)
        self.bus.publish("proactive.message", payload)
        return payload

    async def chat(self, text: str, conversation_id: int | None = None) -> dict:
        # 처리 과정 추적: 해석된 의도, 상태 변화, 도구 선택·결과, 사용한 기억, LLM 호출을 응답 meta와 활동 로그에 남긴다
        trace: dict = {"steps": [], "tools": [], "memories": [], "missing_data": [], "sky_intent": False}
        with self.db.session() as s:
            if conversation_id and s.get(Conversation, conversation_id) is None:
                raise KeyError(conversation_id)
            history = (
                list(
                    s.scalars(
                        select(Message)
                        .where(Message.conversation_id == conversation_id)
                        .order_by(Message.id.desc())
                        .limit(self.settings.chat_history_limit)
                    )
                )[::-1]
                if conversation_id
                else []
            )
            hist_msgs = [{"role": m.role, "content": m.content} for m in history]

        # 라우팅(대화 상태 + 이전 대화 기반 해석)과 도구 실행. 어떤 실패도 대화 자체를 막지 않는다.
        routing: Routing | None = None
        facts: dict = {}
        missing: list[str] = []
        try:
            routing = await self.router.route(text, self.router.load_state(conversation_id), hist_msgs)
            facts, missing = await self._execute_plan(routing, trace)
            trace["routing"] = routing.trace()
        except Exception:
            logger.exception("routing/tool step failed")
            self.activity.record("gyuvis", "routing.failed", level="error")
            routing, facts = None, {}
            missing = ["도구 조회 과정에서 내부 오류가 발생해 실시간 데이터를 확인하지 못했습니다. 날씨·천문 수치를 말하지 말고 잠시 후 다시 시도해 달라고 안내하세요."]
            trace["steps"].append("라우팅/도구 단계 내부 오류 -> 도구 없이 계속")
        trace["missing_data"] = missing

        conditions = describe_conditions(routing.state) if routing and routing.state else None
        system, mems = self._system_prompt(text, facts, missing, conditions)
        trace["memories"] = [{"id": m.id, "kind": m.kind, "content": m.content} for m in mems]
        trace["steps"].append(f"기억 {len(mems)}건 검색해 시스템 프롬프트에 포함")
        msgs = [{"role": "system", "content": system}, *hist_msgs, {"role": "user", "content": text}]

        started = time.perf_counter()
        try:
            res = await self.llm.chat("chat", msgs, max_tokens=1200)  # 실패하면 아무것도 저장되기 전에 예외가 발생한다
        except LLMError as e:
            trace["llm"] = {"called": False, "error": str(e)}
            self.activity.record("gyuvis", "chat.failed", level="warn", trace=trace, error=str(e))
            raise
        trace["llm"] = {
            "called": True,
            "purpose": "chat",
            "model": self.llm.model,
            "history_messages": len(hist_msgs),
            "tokens": res.tokens,
            "cost_usd": round(res.cost_usd, 6),
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
        trace["steps"].append("LLM(chat) 호출 완료 -> 응답 저장")

        with self.db.session() as s:
            if conversation_id is None:
                conv = Conversation(title=text.strip()[:30])
                s.add(conv)
                s.flush()
                conv_id = conv.id
            else:
                conv_id = conversation_id
            user_msg = Message(conversation_id=conv_id, role="user", content=text)
            reply = Message(conversation_id=conv_id, role="assistant", content=res.text.strip(), meta={"trace": trace})
            s.add_all([user_msg, reply])
            s.get(Conversation, conv_id).updated_at = utcnow()
            s.flush()
            out = {"conversation_id": conv_id, "user_message": row_dict(user_msg), "reply": row_dict(reply)}

        if routing and routing.state:
            self.router.save_state(conv_id, routing.state)
        r = trace.get("routing", {})
        self.activity.record(
            "gyuvis",
            "chat.trace",
            conversation_id=conv_id,
            llm_called=True,
            tokens=trace["llm"]["tokens"],
            intent=r.get("intent"),
            interpreted_by=r.get("interpreted_by"),
            changes=r.get("changes"),
            merged_state=r.get("merged_state"),
            memory_ids=[m["id"] for m in trace["memories"]],
            tools=[f"{t['name']}:{t['status']}" for t in trace["tools"]],
            missing_data=trace["missing_data"],
        )
        task = asyncio.create_task(self._learn(text, reply.content))
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        return out

    async def _learn(self, user_text: str, reply: str) -> None:
        try:
            created = await self.memory.extract_and_store(user_text, reply)
            if created:
                self.bus.publish("memory.updated", {"count": len(created)})
                if self.on_new_memories:
                    self.on_new_memories(created)
        except Exception:
            logger.exception("post-turn learning failed")
