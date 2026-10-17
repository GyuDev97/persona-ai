import logging
import re
from datetime import timedelta

from sqlalchemy import select

from .activity import Activity
from .config import Settings
from .context import ContextManager
from .conversation import ConversationEngine
from .db import Database
from .llm import LLMError, LLMGateway
from .memory import MemoryManager
from .agents.evidence import find_conflicts
from .models import Debate, Evidence, Message, utcnow
from .policy import Policy

logger = logging.getLogger("gyunexus")

SUGGEST_SYSTEM = """당신은 GYUVIS입니다. 사용자가 PC를 쓰기 시작한 지금, 먼저 말을 걸 만한 가치가 있는지 판단합니다.
- 사용자 기억(취미, 관심사, 루틴), 현재 시각/요일, 그리고 실제로 조회한 사실(날씨, 천문)을 근거로 합니다.
- 기억과 사실이 둘 다 맞물려 '지금' 알려줄 가치가 있을 때만 speak=true. 억지로 말 걸지 않습니다.
- 조회된 사실에 없는 날씨·수치는 말하지 않습니다. 사실에 오류가 있거나 조회에 실패했다면 그 점을 숨기지 않습니다.
- 최근에 이미 한 제안과 같은 내용은 반복하지 않습니다.
- message는 친한 비서가 말하듯 자연스러운 한국어 2~4문장. 마지막은 부담 없는 질문이나 제안으로 맺습니다.
JSON만 출력: {"speak":true|false,"message":"...","reason":"왜 지금인지 한 문장"}"""

DELIVER_SYSTEM = """당신은 GYUVIS입니다. 에이전트들이 자율 토론으로 만든 결과를 사용자에게 자연스럽게 전합니다.
- 2~4문장. '채택된 아이디어'만 추천합니다. '추가 확인이 필요한 항목'은 추천하지 말고 확인이 더 필요하다고만 짧게 말합니다.
- '검증된 사실'에 있는 것만 사실로 말하고, 나머지는 추정이라고 밝힙니다. evidence_ids가 비어 있는 아이디어는 증거 없는 일반적인 조언이라고 밝힙니다. '반드시 언급할 경고'(강수확률, 달빛 등)는 빠뜨리지 말고 전하며, 경고와 모순되는 말은 하지 않습니다.
- 마지막에 더 자세히 볼지 묻습니다. 토론 번호를 언급해 대시보드에서 찾을 수 있게 합니다."""


class ProactiveEngine:
    """GYUVIS가 먼저 무엇을, 언제 말할지 결정한다."""

    def __init__(
        self,
        settings: Settings,
        db: Database,
        llm: LLMGateway,
        memory: MemoryManager,
        context: ContextManager,
        policy: Policy,
        conversation: ConversationEngine,
        activity: Activity,
    ):
        self.settings, self.db, self.llm, self.memory = settings, db, llm, memory
        self.context, self.policy, self.conversation, self.activity = context, policy, conversation, activity
        self._last_check = None

    async def tick(self) -> None:
        await self.deliver_debates()
        now = utcnow()
        if self._last_check and now - self._last_check < timedelta(minutes=self.settings.proactive_check_minutes):
            return
        self._last_check = now
        await self.maybe_suggest("periodic")

    def _gate(self) -> str | None:
        """토큰을 쓰기 전의 저비용 검사. 조용히 있어야 하는 이유가 있으면 그 이유를 반환한다."""
        if not self.context.snapshot()["user_present"]:
            return "user_absent"
        since = utcnow() - timedelta(hours=24)
        with self.db.session() as s:
            msgs = list(s.scalars(select(Message).where(Message.proactive.is_(True), Message.created_at >= since)))
        suggestions = [m for m in msgs if m.meta.get("kind") == "suggestion"]
        if len(suggestions) >= self.settings.proactive_daily_max:
            return "daily_limit"
        if suggestions and utcnow() - max(m.created_at for m in suggestions) < timedelta(
            minutes=self.settings.proactive_cooldown_minutes
        ):
            return "cooldown"
        if not self.memory.top(1):
            return "no_memories"
        return None

    async def _gather_facts(self) -> dict:
        facts: dict = {}
        for tool, key in (("astro.moon_phase", "moon"), ("weather.forecast", "weather")):
            if tool == "weather.forecast" and self.settings.latitude is None:
                continue
            r = await self.policy.invoke(tool, {}, actor="gyuvis")
            facts[key] = r.data if r.status == "ok" else {"error": r.error}
        return facts

    async def maybe_suggest(self, trigger: str) -> dict | None:
        if not self.llm.configured:
            return None
        reason = self._gate()
        if reason:
            self.activity.record("gyuvis", "proactive.skipped", trigger=trigger, reason=reason)
            return None
        ctx = self.context.snapshot()
        facts = await self._gather_facts()
        with self.db.session() as s:
            recent = [
                m.content for m in s.scalars(select(Message).where(Message.proactive.is_(True)).order_by(Message.id.desc()).limit(5))
            ]
        user = (
            f"[현재] {ctx['local_time']} {ctx['weekday']} {ctx['part_of_day']}"
            f"{' (퇴근 이후/주말)' if ctx['after_work_hours'] else ''}, 사용 시작 {ctx['session_minutes']}분 경과\n\n"
            f"[사용자 기억]\n{chr(10).join('- ' + m.content for m in self.memory.top(12))}\n\n"
            f"[조회한 사실]\n{facts}\n\n[최근 제안/전달 메시지]\n{chr(10).join('- ' + r[:120] for r in recent) or '(없음)'}"
        )
        try:
            data, _ = await self.llm.json(
                "proactive",
                [{"role": "system", "content": SUGGEST_SYSTEM}, {"role": "user", "content": user}],
                autonomous=True,
                max_tokens=500,
            )
        except LLMError as e:
            self.activity.record("gyuvis", "proactive.failed", level="warn", error=str(e))
            return None
        text = str(data.get("message", "")).strip()
        if not data.get("speak") or not text:
            self.activity.record("gyuvis", "proactive.declined", trigger=trigger, reason=str(data.get("reason", "")))
            return None
        self.activity.record("gyuvis", "proactive.suggested", trigger=trigger, reason=str(data.get("reason", "")))
        return self.conversation.post_assistant_message(
            text, {"kind": "suggestion", "trigger": trigger, "reason": str(data.get("reason", "")), "facts": facts}
        )

    async def deliver_debates(self) -> None:
        """중요도가 기준 이상이고 '채택(accepted)'된 아이디어가 있는 완료 토론만 사용자에게 전달한다.

        중요도가 높아도 검증되지 않은 결과(needs_research/discarded)는 전달하지 않는다.
        """
        with self.db.session() as s:
            candidates = list(
                s.scalars(
                    select(Debate)
                    .where(
                        Debate.status == "completed",
                        Debate.delivered_at.is_(None),
                        Debate.importance >= self.settings.importance_threshold,
                    )
                    .order_by(Debate.id)
                )
            )
            d = next((c for c in candidates if (c.result or {}).get("status") == "accepted"), None)
            if d is None:
                return
            debate_id, title, result = d.id, d.title, d.result or {}
            flags = [f for e in s.scalars(select(Evidence).where(Evidence.debate_id == debate_id)) for f in (e.flags or [])]
        accepted = [i for i in result.get("ideas", []) if i.get("status") == "accepted"]
        needs = [i["title"] for i in result.get("ideas", []) if i.get("status") == "needs_research"]
        warnings = (result.get("warnings") or [])[:4]
        fallback = self._delivery_fallback(debate_id, title, accepted, needs, warnings)
        text = fallback
        if self.llm.configured:
            user = (
                f"토론 #{debate_id}: {title}\n채택된 아이디어: {[{k: i.get(k) for k in ('title', 'description', 'rationale', 'risks', 'evidence_ids')} for i in accepted]}\n"
                f"검증된 사실: {result.get('verified_facts')}\n추가 확인이 필요한 항목: {needs}\n반드시 언급할 경고: {warnings}\n"
                f"검증되지 않은 주장: {result.get('unverified_claims')}"
            )
            try:
                res = await self.llm.chat(
                    "debate_delivery",
                    [{"role": "system", "content": DELIVER_SYSTEM}, {"role": "user", "content": user}],
                    autonomous=True,
                    max_tokens=500,
                )
                text = self._guard_delivery(res.text.strip(), flags, needs, warnings) or fallback
            except LLMError as e:
                self.activity.record("gyuvis", "delivery.fallback", level="warn", error=str(e))
        self.conversation.post_assistant_message(text, {"kind": "debate", "debate_id": debate_id})
        with self.db.session() as s:
            s.get(Debate, debate_id).delivered_at = utcnow()
        self.activity.record("gyuvis", "debate.delivered", debate_id=debate_id)

    @staticmethod
    def _delivery_fallback(debate_id: int, title: str, accepted: list[dict], needs: list[str], warnings: list[str]) -> str:
        text = f"토론 #{debate_id} '{title}'에서 채택된 아이디어가 있어요: " + ", ".join(i["title"] for i in accepted) + "."
        if needs:
            text += " 추가 확인이 필요한 항목: " + ", ".join(needs) + "."
        if warnings:
            text += " ※ 주의: " + "; ".join(warnings)
        return text + " 대시보드에서 자세히 볼 수 있어요."

    @staticmethod
    def _guard_delivery(text: str, flags: list[dict], needs: list[str], warnings: list[str]) -> str | None:
        """전달 문장이 증거와 충돌하면 버리고(None), 빠진 경고·확인 필요 항목은 코드가 덧붙인다."""
        if not text or find_conflicts(text, flags):
            return None
        def mentioned(w: str) -> bool:
            nums = re.findall(r"\d+", w)
            return (bool(nums) and nums[0] in text) or w[:10] in text

        missing = [w for w in warnings if not mentioned(w)]
        if missing:
            text += " ※ 주의: " + "; ".join(missing)
        if needs and not any(n[:6] in text for n in needs):
            text += " (추가 확인이 필요한 항목: " + ", ".join(needs) + ")"
        return text
