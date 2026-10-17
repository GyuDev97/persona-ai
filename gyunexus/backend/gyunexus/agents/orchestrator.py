import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ..activity import Activity
from ..config import Settings
from ..db import Database
from ..events import EventBus
from ..llm import BudgetExceeded, LLMError, LLMGateway
from ..memory import MemoryManager
from ..models import Agent, Debate, DebateMessage, Evidence, Idea, Topic, row_dict, utcnow
from ..policy import Policy
from ..textutil import similarity
from ..tools import ToolRegistry
from .definitions import (
    AGENT_BY_ID,
    AGENTS,
    COMMON_RULES,
    CRITIC_SCHEMA,
    DEDUPE_SYSTEM,
    DISCOVER_SYSTEM,
    GENERAL_SCHEMA,
    ORDER,
    PLAN_SYSTEM,
    SYNTHESIS_SYSTEM,
    TOOL_HELP,
)
from .evidence import evidence_flags, evidence_summary, find_conflicts, uncovered_dates, unverified_entities, verify_claim
from .ledger import KIND_LABELS, Ledger
from .planner import plan_participants

logger = logging.getLogger("gyunexus")

TOPIC_DUPLICATE_THRESHOLD = 0.6
SEMANTIC_PREFILTER = 0.05  # 글자가 조금이라도 겹치는 기존 주제가 있을 때만 의미 중복 판정(LLM 1회, 약 $0.0001)을 한다
SYNTHESIS_RESERVE_TOKENS = 5000
MAX_PENDING_EVENT_TOPICS = 3
TRANSCRIPT_CHARS = 7000
STOPWORDS = {"사용자는", "사용자", "즐긴다", "있다", "자주", "위해", "한다", "확인한다", "중이다", "하는", "것을"}


class Busy(Exception):
    pass


class DuplicateTopic(Exception):
    pass


def _clamp(value, lo, hi, default):
    try:
        return max(lo, min(hi, type(default)(value)))
    except (TypeError, ValueError):
        return default


def _stems(text: str) -> set[str]:
    """한국어 조사를 대충 떼어낸 키워드(앞 2글자). 주제가 어떤 기억을 다뤘는지 대략 세는 용도."""
    return {w[:2].lower() for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", text) if w not in STOPWORDS}


class AgentOrchestrator:
    """자율 멀티 에이전트 토론 실행: 주제 -> 참여자 계획 -> 라운드 -> 종합 -> 결과 저장."""

    def __init__(
        self,
        settings: Settings,
        db: Database,
        llm: LLMGateway,
        memory: MemoryManager,
        policy: Policy,
        tools: ToolRegistry,
        bus: EventBus,
        activity: Activity,
    ):
        self.settings, self.db, self.llm, self.memory = settings, db, llm, memory
        self.policy, self.tools, self.bus, self.activity = policy, tools, bus, activity
        self._task: asyncio.Task | None = None
        self.tz = ZoneInfo(settings.timezone)

    # ---------- 에이전트 등록 / 상태 ----------

    def register_agents(self) -> None:
        with self.db.session() as s:
            for d in AGENTS:
                a = s.get(Agent, d["id"])
                fields = {k: d[k] for k in ("name", "role", "description", "system_prompt")}
                if a is None:
                    s.add(Agent(id=d["id"], **fields))
                else:
                    for k, v in fields.items():
                        setattr(a, k, v)
                    a.status, a.current_task = "idle", None

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def _set_agent(self, agent_id: str, status: str, task: str | None = None) -> None:
        with self.db.session() as s:
            a = s.get(Agent, agent_id)
            if a is not None:
                a.status, a.current_task, a.last_active_at = status, task, utcnow()
        self.bus.publish("agent.status", {"id": agent_id, "status": status, "current_task": task})

    # ---------- 주제 ----------

    def _lexical_duplicate(self, title: str) -> Topic | None:
        with self.db.session() as s:
            for t in s.scalars(select(Topic).order_by(Topic.id.desc()).limit(300)):
                if similarity(t.title, title) >= TOPIC_DUPLICATE_THRESHOLD:
                    return t
        return None

    def enqueue_topic(self, title: str, rationale: str = "", source: str = "manual") -> int:
        title = title.strip()
        dup = self._lexical_duplicate(title)
        if dup is not None:
            raise DuplicateTopic(f"similar topic already exists: #{dup.id} {dup.title}")
        with self.db.session() as s:
            t = Topic(title=title, rationale=rationale, source=source)
            s.add(t)
            s.flush()
            topic_id = t.id
        self.activity.record("scheduler", "topic.queued", topic_id=topic_id, title=title, topic_source=source)
        self.bus.publish("topic.created", {"id": topic_id})
        return topic_id

    def on_new_memories(self, memories) -> None:
        """이벤트 트리거: 새로 알게 된 관심사/목표를 토론 주제로 만든다."""
        for m in memories:
            if m.kind not in ("interest", "goal"):
                continue
            with self.db.session() as s:
                pending = len(list(s.scalars(select(Topic).where(Topic.status == "queued", Topic.source == "event"))))
            if pending >= MAX_PENDING_EVENT_TOPICS:
                return
            try:
                self.enqueue_topic(
                    f"{m.content} — 이를 위해 GyuNexus가 사용자에게 해줄 수 있는 유용한 일은?",
                    rationale="새로 알게 된 사용자 관심사",
                    source="event",
                )
            except DuplicateTopic:
                pass

    @staticmethod
    def pick_focus(memories, recent_topics) -> tuple[object, dict]:
        """가장 적게 다룬 기억을 이번 주제의 중심으로 고른다(LLM의 자유 선택에 맡기면 한 관심사에 쏠린다)."""
        topic_stems = [_stems(f"{t.title} {t.rationale}") for t in recent_topics]
        coverage = {m.id: sum(1 for ts in topic_stems if _stems(m.content) & ts) for m in memories}
        focus = min(memories, key=lambda m: (coverage[m.id], -m.importance, -m.id))
        return focus, coverage

    async def _semantic_duplicate(self, title: str, recent: list[Topic]) -> Topic | None:
        """표현이 달라도 같은 질문인지 판정한다. 비슷한 기존 주제가 있을 때만 LLM을 1회 호출한다."""
        near = sorted(((similarity(title, t.title), t) for t in recent), key=lambda x: x[0], reverse=True)[:3]
        near = [t for sc, t in near if sc >= SEMANTIC_PREFILTER]
        if not near:
            return None
        user = "[기존 주제]\n" + "\n".join(f"#{t.id}: {t.title}" for t in near) + f"\n\n[새 후보]\n{title}"
        try:
            data, _ = await self.llm.json("topic_dedupe", [{"role": "system", "content": DEDUPE_SYSTEM}, {"role": "user", "content": user}],
                                          autonomous=True, max_tokens=120)
        except LLMError as e:
            self.activity.record("scheduler", "topic.dedupe_failed", level="warn", error=str(e))
            return None
        dup = data.get("duplicate_of")
        return next((t for t in near if dup is not None and str(t.id) == str(dup).lstrip("#")), None)

    async def discover_topic(self, trigger: str) -> int | None:
        with self.db.session() as s:
            recent_topics = list(s.scalars(select(Topic).order_by(Topic.id.desc()).limit(20)))
        mems = self.memory.top(10)
        focus, coverage = self.pick_focus(mems, recent_topics) if mems else (None, {})
        rejected: list[str] = []
        for _ in range(3):
            user = (
                f"[이번에 중심으로 삼을 기억]\n{('- ' + focus.content) if focus else '(없음)'}\n\n"
                f"[전체 사용자 기억 (괄호는 최근 이 기억을 다룬 주제 수)]\n"
                f"{chr(10).join(f'- {m.content} ({coverage.get(m.id, 0)}건)' for m in mems) or '(아직 없음)'}\n\n"
                f"[이미 다룬 주제]\n{chr(10).join('- ' + t.title for t in recent_topics) or '(없음)'}\n\n"
                f"[이번 시도에서 중복으로 거절된 제안]\n{chr(10).join('- ' + t for t in rejected) or '(없음)'}\n\n"
                f"발굴 계기: {trigger}. 새 주제를 하나 제안하세요."
            )
            data, _ = await self.llm.json(
                "topic_discovery",
                [{"role": "system", "content": DISCOVER_SYSTEM}, {"role": "user", "content": user}],
                autonomous=True,
                max_tokens=400,
            )
            title = str(data.get("title", "")).strip()
            if not title:
                continue
            if self._lexical_duplicate(title) is not None:
                rejected.append(title)
                continue
            dup = await self._semantic_duplicate(title, recent_topics)
            if dup is not None:
                self.activity.record("scheduler", "topic.semantic_duplicate", title=title, duplicate_of=dup.id)
                rejected.append(f"{title} (같은 뜻: #{dup.id})")
                continue
            try:
                topic_id = self.enqueue_topic(title, str(data.get("rationale", "")), source="discovery")
            except DuplicateTopic:
                rejected.append(title)
                continue
            if focus is not None:
                self.activity.record("scheduler", "topic.focus", topic_id=topic_id, focus_memory=focus.content, coverage=coverage.get(focus.id, 0))
            return topic_id
        self.activity.record("scheduler", "topic.discovery_exhausted", level="warn", rejected=rejected)
        return None

    # ---------- 파이프라인 ----------

    def start(self, *, trigger: str, topic_id: int | None = None) -> None:
        """토론 1건을 백그라운드로 시작한다. 동시에 하나만 실행된다."""
        if self.busy:
            raise Busy("a debate is already running")
        self._task = asyncio.create_task(self._pipeline(trigger, topic_id))

    async def wait(self) -> None:
        if self._task:
            await asyncio.shield(self._task)

    async def _pipeline(self, trigger: str, topic_id: int | None) -> None:
        autonomous = trigger != "manual"
        debate_id: int | None = None
        try:
            if topic_id is None:
                with self.db.session() as s:
                    queued = s.scalars(select(Topic).where(Topic.status == "queued").order_by(Topic.id).limit(1)).first()
                    topic_id = queued.id if queued else None
            if topic_id is None:
                topic_id = await self.discover_topic(trigger)
            if topic_id is None:
                return
            with self.db.session() as s:
                topic = s.get(Topic, topic_id)
                topic.status = "running"
                title, rationale = topic.title, topic.rationale
            plan = await self._plan(title, rationale, autonomous)
            with self.db.session() as s:
                d = Debate(
                    topic_id=topic_id,
                    title=title,
                    goal=plan["goal"],
                    trigger=trigger,
                    participants=plan["participants"],
                    plan={"reasons": plan["reasons"], "needs_facts": plan["needs_facts"], "llm_reason": plan["reason"]},
                    max_rounds=self.settings.debate_max_rounds,
                )
                s.add(d)
                s.flush()
                debate_id = d.id
                s.get(Topic, topic_id).debate_id = debate_id
                payload = row_dict(d)
            self.activity.record(
                "agent", "debate.started", debate_id=debate_id, title=title, participants=plan["participants"], reason=plan["reason"]
            )
            for agent_id, r in plan["reasons"].items():
                self.activity.record("agent", "debate.plan", debate_id=debate_id, agent_id=agent_id, selected=r["selected"],
                                     reason=r["reason"], decided_by=r["by"])
            self.bus.publish("debate.started", payload)
            await self._run_debate(debate_id, autonomous)
        except Exception as e:
            level = "warn" if isinstance(e, LLMError) else "error"
            self.activity.record("agent", "debate.failed", level=level, debate_id=debate_id, error=str(e))
            if level == "error":
                logger.exception("debate pipeline failed")
            self._fail(topic_id, debate_id, str(e))

    def _fail(self, topic_id: int | None, debate_id: int | None, error: str) -> None:
        with self.db.session() as s:
            if topic_id and (t := s.get(Topic, topic_id)):
                t.status = "failed"
            if debate_id and (d := s.get(Debate, debate_id)):
                d.status, d.error, d.ended_at = "failed", error, utcnow()
        for a in ORDER:
            self._set_agent(a, "idle")
        self.bus.publish("debate.updated", {"id": debate_id})

    async def _plan(self, title: str, rationale: str, autonomous: bool) -> dict:
        """목표는 LLM이 정하고, 참가자는 규칙이 정한다. LLM 호출이 실패해도 규칙만으로 계획을 세운다."""
        data: dict = {}
        try:
            data, _ = await self.llm.json(
                "debate_plan",
                [{"role": "system", "content": PLAN_SYSTEM}, {"role": "user", "content": f"주제: {title}\n배경: {rationale or '-'}"}],
                autonomous=autonomous,
                max_tokens=300,
            )
        except LLMError as e:
            self.activity.record("agent", "plan.llm_failed", level="warn", error=str(e))
        with self.db.session() as s:
            enabled = {a.id for a in s.scalars(select(Agent).where(Agent.enabled.is_(True)))}
        plan = plan_participants(title, rationale, data, enabled)
        plan["goal"] = str(data.get("goal") or title)
        plan["reason"] = str(data.get("reason", ""))
        return plan

    # ---------- 토론 루프 ----------

    async def _run_debate(self, debate_id: int, autonomous: bool) -> None:
        s_ = self.settings
        with self.db.session() as s:
            d = s.get(Debate, debate_id)
            title, goal, participants, topic_id = d.title, d.goal, list(d.participants), d.topic_id
            needs_facts = bool((d.plan or {}).get("needs_facts"))
            rationale = s.get(Topic, topic_id).rationale
        known = f"{title} {rationale} " + " ".join(m.content for m in self.memory.top(20))
        ledger = Ledger(known, needs_facts)
        tokens, cost, failures = 0, 0.0, 0
        retries_left = s_.debate_critic_retries
        stop_reason, stop_detail, rounds_done = "max_rounds", f"{s_.debate_max_rounds}라운드 도달", 0
        budget_for_turns = s_.debate_max_tokens - SYNTHESIS_RESERVE_TOKENS
        ctx = {"title": title, "goal": goal, "participants": participants, "debate_id": debate_id, "autonomous": autonomous}

        try:
            for rnd in range(1, s_.debate_max_rounds + 1):
                stats = {"round": rnd, "new_evidence": 0, "new_verified": 0, "valid_rebuttals": 0, "rejected_rebuttals": 0,
                         "duplicate_rebuttals": 0, "addressed_rebuttals": 0, "regressions": 0, "critic_retries": 0}
                stopped = None
                resolved = False
                for aid in participants:
                    if tokens >= budget_for_turns:
                        stopped = ("token_budget", f"토큰 {tokens}/{budget_for_turns} 사용")
                        break
                    self._set_agent(aid, "thinking", f"토론 #{debate_id}: {title[:60]}")
                    try:
                        out = await self._agent_turn(aid, rnd, ctx, ledger, stats, retries_left, budget_for_turns - tokens)
                    except BudgetExceeded:
                        stopped = ("daily_budget", "일일 자율 예산 소진")
                        break
                    except LLMError as e:
                        failures += 1
                        self.activity.record("agent", "turn.failed", level="warn", agent_id=aid, debate_id=debate_id, error=str(e))
                        if failures >= 2:
                            stopped = ("llm_errors", "LLM 오류 2회")
                            break
                        continue
                    finally:
                        self._set_agent(aid, "idle")
                    tokens += out["tokens"]
                    cost += out["cost"]
                    retries_left -= out["retries"]
                    resolved = resolved or out["resolved"]
                    with self.db.session() as s:
                        d = s.get(Debate, debate_id)
                        d.tokens_used, d.cost_usd = tokens, cost
                ledger.progress.append(stats)
                if stopped:
                    stop_reason, stop_detail = stopped
                    break
                rounds_done = rnd
                with self.db.session() as s:
                    dd = s.get(Debate, debate_id)
                    dd.rounds_done, dd.progress = rnd, list(ledger.progress)
                self.bus.publish("debate.updated", {"id": debate_id})
                verdict = self._evaluate_stop(ledger, rnd, stats, resolved)
                if verdict:
                    stop_reason, stop_detail = verdict
                    break

            if not ledger.messages:
                raise LLMError(f"no agent produced output ({stop_reason})")
            result = await self._synthesize(debate_id, ctx, ledger, autonomous)
        finally:
            for a in participants:
                self._set_agent(a, "idle")

        ledger.progress.append({"stop": {"reason": stop_reason, "detail": stop_detail}})
        with self.db.session() as s:
            d = s.get(Debate, debate_id)
            d.status, d.stop_reason, d.ended_at = "completed", stop_reason, utcnow()
            d.tokens_used, d.cost_usd = tokens + result["_tokens"], cost + result["_cost"]
            d.rounds_done = max(d.rounds_done, rounds_done)
            d.importance = result["importance"]
            d.progress = list(ledger.progress)
            d.result = {k: v for k, v in result.items() if not k.startswith("_")}
            s.get(Topic, topic_id).status = "done"
            payload = row_dict(d)
        self.activity.record("agent", "debate.completed", debate_id=debate_id, stop_reason=stop_reason, stop_detail=stop_detail,
                             importance=result["importance"], result_status=result["status"])
        self.bus.publish("debate.completed", payload)

    def _evaluate_stop(self, ledger: Ledger, rnd: int, stats: dict, resolved: bool) -> tuple[str, str] | None:
        """라운드 종료 후 종료 여부와 이유를 판단한다. 모든 에이전트가 동의했다는 것만으로 결론을 정확하다고 보지 않는다."""
        s_ = self.settings
        open_reb = ledger.open_rebuttals()
        conflicted = [c for c in ledger.claims if c.status == "conflicted"]
        verified = ledger.by_status("verified")
        if resolved and rnd >= s_.debate_min_rounds:
            if open_reb:
                self.activity.record("agent", "consensus.ignored", level="warn", reason=f"열린 반박 {len(open_reb)}건")
            elif conflicted:
                self.activity.record("agent", "consensus.ignored", level="warn", reason="증거와 충돌한 주장이 있음")
            elif ledger.needs_facts and not verified:
                self.activity.record("agent", "consensus.ignored", level="warn", reason="사실 확인이 필요한 주제인데 검증된 사실이 없음")
            else:
                return "consensus", "Critic이 열린 반박·증거 충돌이 없다고 확인"
        novelty = stats["new_evidence"] + stats["new_verified"] + stats["valid_rebuttals"] + stats["addressed_rebuttals"]
        if rnd >= 2 and novelty == 0:
            unresolved = len(open_reb) + len(ledger.by_status("unverified")) + (1 if ledger.needs_facts and not verified else 0)
            detail = (f"새 증거·새 반박·반박 처리 없음(거부된 반박 {stats['rejected_rebuttals']}건, 중복 {stats['duplicate_rebuttals']}건)")
            if unresolved:
                return "needs_research", (
                    f"{detail}. 미해결: 열린 반박 {len(open_reb)}건, 미검증 주장 {len(ledger.by_status('unverified'))}건, "
                    f"검증된 사실 {len(verified)}건{' (사실 확인이 필요한 주제)' if ledger.needs_facts else ''}"
                )
            return "stagnation", detail
        return None

    # ---------- 에이전트 발언 ----------

    def _context_block(self) -> str:
        """모델이 날짜·요일을 틀리지 않도록 오늘/내일/이번 주말 날짜를 코드가 계산해 알려준다."""
        today = datetime.now(self.tz).date()
        wd = "월화수목금토일"
        sat = today + timedelta(days=(5 - today.weekday()) % 7) if today.weekday() != 6 else today
        weekend = f"{sat.isoformat()}(토)·{(sat + timedelta(days=1)).isoformat()}(일)" if today.weekday() != 6 else f"{today.isoformat()}(일)"
        loc = "설정됨(도구에 위치를 생략하면 기본 위치 사용)" if self.settings.latitude is not None else "설정 안 됨"
        return (
            f"오늘 날짜: {today.isoformat()}({wd[today.weekday()]}요일), 내일: {(today + timedelta(days=1)).isoformat()}, "
            f"모레: {(today + timedelta(days=2)).isoformat()}, 이번 주말: {weekend}. 기본 위치: {loc}."
        )

    def _transcript(self, ledger: Ledger) -> str:
        lines = []
        for m in ledger.messages:
            lines.append(f"[R{m['round']} {AGENT_BY_ID[m['agent']]['name']}] {m['text']}")
            for c in ledger.claims:
                if c.round == m["round"] and c.agent == m["agent"]:
                    lines.append(f"   - ({c.status}) {c.text}")
        for r in ledger.rebuttals:
            lines.append(f"[반박 B{r.id} R{r.round} {'처리됨' if r.status == 'addressed' else '열림'}] ({KIND_LABELS[r.kind]}) {r.target} -> {r.detail}")
        return "\n".join(lines)[-TRANSCRIPT_CHARS:]

    def _turn_messages(self, aid: str, rnd: int, ctx: dict, ledger: Ledger) -> list[dict]:
        agent = AGENT_BY_ID[aid]
        system = agent["system_prompt"] + COMMON_RULES
        if agent["can_use_tools"]:
            system += TOOL_HELP.format(tools=self.tools.describe(read_only=True))
        system += CRITIC_SCHEMA if aid == "critic" else GENERAL_SCHEMA
        user = (
            f"{self._context_block()}\n주제: {ctx['title']}\n목표: {ctx['goal']}\n"
            f"참여자: {', '.join(AGENT_BY_ID[p]['name'] for p in ctx['participants'])}\n"
            f"라운드: {rnd}/{self.settings.debate_max_rounds}\n\n[증거 목록] (증거 id는 숫자만 인용)\n{ledger.evidence_prompt()}\n\n"
            f"[보존해야 할 검증 내용]\n{ledger.preserved_prompt()}\n\n[열린 반박]\n{ledger.open_prompt()}\n\n"
            f"[지금까지의 토론]\n{self._transcript(ledger) or '(아직 발언 없음 — 당신이 먼저 시작합니다)'}\n\n{agent['name']}로서 발언하세요."
        )
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    async def _agent_turn(self, aid: str, rnd: int, ctx: dict, ledger: Ledger, stats: dict, retries_left: int, tokens_left: int) -> dict:
        messages = self._turn_messages(aid, rnd, ctx, ledger)
        purpose = f"debate_turn:{aid}"
        kw = {"autonomous": ctx["autonomous"], "debate_id": ctx["debate_id"], "max_tokens": 1200}
        data, res = await self.llm.json(purpose, messages, **kw)
        tokens, cost, retries = res.tokens, res.cost_usd, 0

        if aid == "critic":
            valid, rejected = ledger.validate_rebuttals(data.get("rebuttals"), rnd)
            endorsements = [str(e).strip() for e in (data.get("endorsements") or []) if str(e).strip()][:5]
            # resolved는 열린 반박이 없고 인정할 내용이 있을 때만 인정한다
            resolved = bool(data.get("resolved")) and not ledger.open_rebuttals() and bool(endorsements) and not valid
            if not valid and not resolved and retries_left > 0 and tokens_left - tokens > 0:
                feedback = "\n".join(f"- {r['reason']}" for r in rejected) or "- 구체적인 반박이 하나도 없습니다(rebuttals가 비었거나 resolved 조건 미충족)"
                self.activity.record("agent", "critic.retry", agent_id="critic", debate_id=ctx["debate_id"], reasons=[r["reason"] for r in rejected])
                stats["rejected_rebuttals"] += len(rejected)
                stats["duplicate_rebuttals"] += sum(1 for r in rejected if "중복" in r["reason"])
                retry_msgs = messages + [
                    {"role": "assistant", "content": json.dumps(data, ensure_ascii=False)},
                    {"role": "user", "content": f"방금 반박이 검증에서 거부되었습니다:\n{feedback}\n"
                     "규칙에 맞는 구체적 반박(error/missing_condition/evidence_conflict/counterexample/execution_risk)으로 다시 작성하세요. "
                     "더 이상 구체적인 문제가 없다면 rebuttals를 비우고 endorsements와 resolved:true로 답하세요."},
                ]
                data, res2 = await self.llm.json(purpose, retry_msgs, **kw)
                tokens, cost, retries = tokens + res2.tokens, cost + res2.cost_usd, 1
                stats["critic_retries"] += 1
                valid, rejected = ledger.validate_rebuttals(data.get("rebuttals"), rnd)
                endorsements = [str(e).strip() for e in (data.get("endorsements") or []) if str(e).strip()][:5]
                resolved = bool(data.get("resolved")) and not ledger.open_rebuttals() and bool(endorsements) and not valid
                stats["rejected_rebuttals"] += len(rejected)
                stats["duplicate_rebuttals"] += sum(1 for r in rejected if "중복" in r["reason"])
            else:
                stats["rejected_rebuttals"] += len(rejected)
                stats["duplicate_rebuttals"] += sum(1 for r in rejected if "중복" in r["reason"])
            stats["valid_rebuttals"] += len(valid)
            if not valid and not resolved:
                self.activity.record("agent", "critic.rejected", level="warn", agent_id="critic", debate_id=ctx["debate_id"],
                                     round=rnd, rejected=[r["reason"] for r in rejected])
                return {"tokens": tokens, "cost": cost, "retries": retries, "resolved": False}
            message = str(data.get("message", "")).strip() or f"반박 {len(valid)}건" + (", 합의 가능" if resolved else "")
            claims = [{"text": f"[B{r.id}] {KIND_LABELS[r.kind]}: {r.detail} (제안: {r.suggestion})", "type": "rebuttal", "status": "rebuttal",
                       "evidence_ids": r.evidence_ids, "notes": [], "entities": []} for r in valid]
            claims += [{"text": e, "type": "endorsement", "status": "endorsed", "evidence_ids": [], "notes": [], "entities": []} for e in endorsements]
            self._persist_message(ctx["debate_id"], rnd, aid, message, claims)
            ledger.add_message(rnd, aid, message)
            return {"tokens": tokens, "cost": cost, "retries": retries, "resolved": resolved}

        message = str(data.get("message", "")).strip()
        if not message:
            raise LLMError("empty agent message")
        verified_before = ledger.by_status("verified")
        new_claims = ledger.add_claims(aid, rnd, data.get("claims"))
        stats["new_verified"] += sum(
            1 for c in new_claims if c.status == "verified" and not any(similarity(c.text, v.text) >= 0.6 for v in verified_before)
        )
        stats["addressed_rebuttals"] += ledger.apply_responses(data.get("responses"))
        if aid in ("idea", "developer"):
            dropped = ledger.missing_preserved([message] + [c.text for c in new_claims])
            if dropped:
                stats["regressions"] += len(dropped)
                self.activity.record("agent", "preserved.dropped", level="warn", agent_id=aid, debate_id=ctx["debate_id"],
                                     round=rnd, dropped=[c.text[:60] for c in dropped])
        if AGENT_BY_ID[aid]["can_use_tools"]:
            stats["new_evidence"] += await self._execute_tool_requests(aid, ctx["debate_id"], data.get("tool_requests"), ledger)
        self._persist_message(ctx["debate_id"], rnd, aid, message, [c.public() for c in new_claims])
        ledger.add_message(rnd, aid, message)
        return {"tokens": tokens, "cost": cost, "retries": retries, "resolved": False}

    def _persist_message(self, debate_id: int, rnd: int, aid: str, message: str, claims: list[dict]) -> None:
        with self.db.session() as s:
            row = DebateMessage(debate_id=debate_id, round=rnd, agent_id=aid, content=message, claims=claims)
            s.add(row)
            s.flush()
            payload = row_dict(row)
        self.bus.publish("debate.message", payload)

    async def _execute_tool_requests(self, aid: str, debate_id: int, requests, ledger: Ledger) -> int:
        """읽기 도구만 실행한다. 성공은 증거로, 실패도 '확인 불가' 증거로 기록해 이후 발언과 종합에 전달한다. 새 증거 수를 반환."""
        new_ok = 0
        for req in (requests if isinstance(requests, list) else [])[:2]:
            if not isinstance(req, dict) or not isinstance(req.get("tool"), str):
                continue
            tool = self.tools.get(req["tool"])
            if tool is None or tool.risk != "read":
                # 에이전트는 자료 수집만 가능. 실행성 작업은 종합 단계의 proposed_actions -> 사용자 승인을 거친다
                self.activity.record("policy", "tool.request_ignored", level="warn", agent_id=aid, debate_id=debate_id, tool=req["tool"])
                continue
            args = req.get("args") if isinstance(req.get("args"), dict) else {}
            res = await self.policy.invoke(req["tool"], args, actor=aid, debate_id=debate_id)
            if res.status == "ok":
                summary, status = evidence_summary(res.data), "ok"
                flags = evidence_flags(req["tool"], res.data)
                source = str((res.data or {}).get("source", req["tool"]))[:500]
                new_ok += 1
            elif res.status == "error":
                summary, status = f"조회 실패({res.error_kind}): {res.error}", "error"
                flags = evidence_flags(req["tool"], None, error=res.error, error_kind=res.error_kind)
                source = req["tool"]
            else:
                continue
            safe_args = {k: v for k, v in args.items() if k not in ("latitude", "longitude")}
            with self.db.session() as s:
                ev = Evidence(debate_id=debate_id, tool=req["tool"], args=safe_args, source=source, summary=summary, status=status, flags=flags)
                s.add(ev)
                s.flush()
                ledger.add_evidence(ev.id, ev.tool, summary, status, flags)
        return new_ok

    # ---------- 종합 ----------

    async def _synthesize(self, debate_id: int, ctx: dict, ledger: Ledger, autonomous: bool) -> dict:
        fl = ledger.all_flags()
        conflicted = [c for c in ledger.claims if c.status == "conflicted"]
        user = (
            f"{self._context_block()}\n주제: {ctx['title']}\n목표: {ctx['goal']}\n\n[증거 목록]\n{ledger.evidence_prompt()}\n\n"
            f"[증거 경고]\n{chr(10).join('- ' + w for w in ledger.warnings()) or '(없음)'}\n\n"
            f"[증거와 충돌한 주장]\n{chr(10).join('- ' + c.text for c in conflicted) or '(없음)'}\n\n"
            f"[보존해야 할 검증 내용]\n{ledger.preserved_prompt()}\n\n[열린 반박]\n{ledger.open_prompt()}\n\n[토론 기록]\n{self._transcript(ledger)}"
        )
        try:
            data, res = await self.llm.json(
                "debate_synthesis",
                [{"role": "system", "content": SYNTHESIS_SYSTEM.format(tools=self.tools.describe())}, {"role": "user", "content": user}],
                autonomous=autonomous, debate_id=debate_id, max_tokens=2200,
            )
            tokens, cost = res.tokens, res.cost_usd
        except BudgetExceeded:
            self.activity.record("agent", "synthesis.skipped", level="warn", debate_id=debate_id, reason="daily_budget")
            data, tokens, cost = {"summary": "일일 예산 소진으로 요약을 생략했습니다. 토론 원문을 확인하세요.", "ideas": []}, 0, 0.0
        result = self._gate_result(data, ledger, fl)
        result["_tokens"], result["_cost"] = tokens, cost

        with self.db.session() as s:
            s.add_all(
                Idea(debate_id=debate_id, title=i["title"], description=i["description"], feasibility=i["feasibility"], risks=i["risks"],
                     next_steps=i["next_steps"], confidence=i["confidence"], status=i["status"], rationale=i["rationale"],
                     evidence_ids=i["evidence_ids"])
                for i in result["ideas"]
            )
        if result["status"] == "accepted":  # 채택된 결과만 후속 조치(승인 대기)를 제안할 수 있다
            for act in (data.get("proposed_actions") or [])[:3]:
                if not isinstance(act, dict):
                    continue
                tool = self.tools.get(str(act.get("tool", "")))
                if tool is None or tool.risk == "read":
                    continue
                self.policy.request_approval(tool.name, act.get("args") if isinstance(act.get("args"), dict) else {}, "debate",
                                             str(act.get("reason", "")), debate_id)
        return result

    def _gate_result(self, data: dict, ledger: Ledger, flags: list[dict]) -> dict:
        """LLM이 쓴 종합 결과를 증거 기준으로 검증하는 최종 관문. 증거와 충돌하거나 근거가 없으면 확정하지 않는다."""
        known = ledger.evidence_known_text()
        warn_texts = [f["text"] for f in flags if f["severity"] != "info"]
        ideas = []
        idea_entities: set[str] = set()
        for raw in (data.get("ideas") or [])[:6]:
            if not isinstance(raw, dict) or not str(raw.get("title", "")).strip():
                continue
            status = raw.get("status") if raw.get("status") in ("accepted", "needs_research", "discarded") else "needs_research"
            ev_ids = [i for i in (raw.get("evidence_ids") or []) if isinstance(i, int) and i in ledger.evidence and ledger.evidence[i]["status"] == "ok"]
            title, desc = str(raw["title"]).strip()[:300], str(raw.get("description", ""))
            steps = [str(x) for x in (raw.get("next_steps") or [])][:6]
            text = f"{title} {desc} {' '.join(steps)}"
            if not ev_ids:  # 모델이 증거 id를 빠뜨려도, 같은 내용을 다룬 검증/해석 주장이 인용한 증거는 근거로 인정한다
                ev_ids = sorted({i for c in ledger.claims if c.status in ("verified", "interpretation") and similarity(c.text, text) >= 0.3
                                 for i in c.evidence_ids})
            ents = unverified_entities(text, known)
            idea_entities.update(ents)
            conflicts = find_conflicts(text, flags)
            notes: list[str] = []
            if status == "accepted":
                if ents:
                    status = "needs_research"
                    notes.append(f"존재가 확인되지 않은 이름 포함: {', '.join(ents)}")
                if conflicts:
                    status = "needs_research"
                    notes.append("증거 경고와 충돌: " + "; ".join(c["text"] for c in conflicts))
                if ledger.needs_facts and not ev_ids:  # 사실 확인이 필요한 주제의 아이디어는 증거 없이 채택하지 않는다
                    status = "needs_research"
                    notes.append("뒷받침하는 증거 없음")
                unc = uncovered_dates(text, ledger.evidence_dates()) if ledger.needs_facts else []
                if unc:
                    status = "needs_research"
                    notes.append(f"증거가 다루지 않은 날짜: {', '.join(unc)}")
                open_hits = [r for r in ledger.open_rebuttals() if max(similarity(r.target, text), similarity(r.detail, text)) >= 0.25]
                if open_hits:
                    status = "needs_research"
                    notes.append("해소되지 않은 반박: " + ", ".join(f"B{r.id}" for r in open_hits))
                if status == "accepted" and not ev_ids:
                    notes.append("증거 없이 일반 지식에 기반함")
            elif status == "needs_research":
                if ents:
                    notes.append(f"존재 미확인: {', '.join(ents)}")
                if conflicts:
                    notes.append("증거 경고와 충돌: " + "; ".join(c["text"] for c in conflicts))
            risks = [str(x) for x in (raw.get("risks") or [])][:6]
            if status != "discarded":
                risks += [f"증거 경고: {w}" for w in warn_texts[:3] if f"증거 경고: {w}" not in risks]
            ideas.append({
                "title": title, "description": desc + (f" (존재 미확인: {', '.join(ents)})" if ents else ""),
                "feasibility": raw.get("feasibility") if raw.get("feasibility") in ("low", "medium", "high") else "medium",
                "risks": risks, "next_steps": steps, "confidence": _clamp(raw.get("confidence"), 0.0, 1.0, 0.5),
                "status": status, "rationale": " / ".join(filter(None, [str(raw.get("rationale", "")).strip(), *notes])),
                "evidence_ids": ev_ids,
            })

        summary = str(data.get("summary", ""))
        summary_conflicts = find_conflicts(summary, flags)
        if summary_conflicts:
            summary += " ⚠ 위 서술 중 증거 경고와 충돌하는 부분이 있어 확정하지 않습니다: " + "; ".join(c["text"] for c in summary_conflicts)

        counts = {s: sum(1 for i in ideas if i["status"] == s) for s in ("accepted", "needs_research", "discarded")}
        if summary_conflicts:
            status = "needs_research"
        elif counts["accepted"]:
            status = "accepted"
        elif counts["needs_research"]:
            status = "needs_research"
        else:
            status = "discarded"
        decision = data.get("decision") if data.get("decision") in ("adopt", "revise", "discard") else "revise"
        if (status != "accepted" and decision == "adopt") or (status == "needs_research" and decision == "discard"):
            decision = "revise"
        if status == "discarded":
            decision = "discard"

        verified = [{"text": c.text, "evidence_ids": c.evidence_ids} for c in ledger.by_status("verified")]
        unverified = [str(x) for x in (data.get("unverified_claims") or []) if str(x).strip()][:10]
        for f in data.get("verified_facts") or []:  # 모델이 직접 적은 사실도 같은 검증을 통과해야 한다
            text = str(f.get("text", "")) if isinstance(f, dict) else str(f)
            v = verify_claim(text, "fact", f.get("evidence_ids") if isinstance(f, dict) else [], ledger.evidence, known, flags)
            if v["status"] == "verified" and not any(similarity(text, x["text"]) >= 0.6 for x in verified):
                verified.append({"text": text, "evidence_ids": v["evidence_ids"]})
            elif v["status"] != "verified" and text and text not in unverified:
                unverified.append(text)
        for c in ledger.by_status("unverified"):
            if c.text not in unverified:
                unverified.append(c.text)
        questions = [str(x) for x in (data.get("open_questions") or [])][:6]
        for e in sorted({e for c in ledger.claims for e in c.entities} | idea_entities):
            questions.append(f"'{e}'의 존재와 조건을 확인해야 함")

        importance = _clamp(data.get("importance"), 0, 10, 0)
        if status != "accepted":
            importance = min(importance, 4)  # 검증되지 않은 결과는 높은 중요도로 사용자에게 밀어내지 않는다
        return {
            "summary": summary, "decision": decision, "status": status, "ideas": ideas,
            "verified_facts": verified[:10], "unverified_claims": unverified[:12], "open_questions": questions[:8],
            "warnings": (ledger.warnings())[:8], "conflicts": [c["text"] for c in summary_conflicts], "importance": importance,
            "recommendation": {"accepted": [i["title"] for i in ideas if i["status"] == "accepted"],
                               "needs_research": [i["title"] for i in ideas if i["status"] == "needs_research"]},
        }
