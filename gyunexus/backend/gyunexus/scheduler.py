import asyncio
import logging
from datetime import timedelta

from sqlalchemy import func, select

from .activity import Activity
from .agents.orchestrator import AgentOrchestrator
from .config import Settings
from .db import Database
from .llm import LLMGateway
from .models import Debate, utcnow
from .proactive import ProactiveEngine
from .runtime_settings import get_value

logger = logging.getLogger("gyunexus")


class Scheduler:
    """asyncio 루프 하나로 정기 자율 토론을 시작하고 Proactive Engine을 구동한다."""

    def __init__(
        self,
        settings: Settings,
        db: Database,
        llm: LLMGateway,
        orchestrator: AgentOrchestrator,
        proactive: ProactiveEngine,
        activity: Activity,
    ):
        self.settings, self.db, self.llm = settings, db, llm
        self.orchestrator, self.proactive, self.activity = orchestrator, proactive, activity
        self._started = self._last_attempt = utcnow()
        self._budget_warned = False

    def autonomous_enabled(self) -> bool:
        with self.db.session() as s:
            return bool(get_value(s, "autonomous_enabled", self.settings.autonomous_enabled))

    def interval_minutes(self) -> int:
        with self.db.session() as s:
            return int(get_value(s, "debate_interval_minutes", self.settings.debate_interval_minutes))

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("scheduler tick failed")
            await asyncio.sleep(self.settings.scheduler_tick_seconds)

    async def tick(self) -> None:
        if not self.llm.configured or not self.autonomous_enabled():
            return
        await self.proactive.tick()
        if self.orchestrator.busy:
            return
        with self.db.session() as s:
            last = s.scalar(select(func.max(Debate.started_at)))
        due_at = max(last or self._started, self._started, self._last_attempt) + timedelta(
            minutes=self.interval_minutes()
        )
        if utcnow() < due_at:
            return
        if self.llm.budget_left() <= 0:
            if not self._budget_warned:
                self.activity.record("scheduler", "budget.exhausted", level="warn", limit=self.settings.daily_budget_usd)
                self._budget_warned = True
            return
        self._budget_warned = False
        self._last_attempt = utcnow()  # 시작에 실패해도 매 tick마다 재시도하지 않도록 기록
        self.activity.record("scheduler", "debate.due", interval_minutes=self.interval_minutes())
        self.orchestrator.start(trigger="schedule")
