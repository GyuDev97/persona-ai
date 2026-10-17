import json
import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Protocol

from sqlalchemy import func, select

from .config import Settings
from .db import Database
from .models import LlmUsage
from .textutil import redact


class LLMError(Exception):
    pass


class LLMNotConfigured(LLMError):
    pass


class BudgetExceeded(LLMError):
    pass


@dataclass
class Completion:
    text: str
    prompt_tokens: int
    completion_tokens: int


@dataclass
class LLMResult:
    text: str
    tokens: int
    cost_usd: float


class LLMProvider(Protocol):
    """다른 LLM 벤더를 붙이려면 이 인터페이스를 구현한다."""

    model: str

    async def complete(
        self, messages: list[dict], *, json_mode: bool, max_tokens: int, purpose: str
    ) -> Completion: ...


class OpenAIProvider:
    def __init__(self, api_key: str, model: str, base_url: str = ""):
        from openai import AsyncOpenAI

        self.model = model
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url or None, timeout=60, max_retries=2)

    async def complete(self, messages, *, json_mode, max_tokens, purpose) -> Completion:
        from openai import OpenAIError

        kwargs: dict = {"model": self.model, "messages": messages, "max_completion_tokens": max_tokens}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            resp = await self._client.chat.completions.create(**kwargs)
        except OpenAIError as e:
            raise LLMError(f"OpenAI request failed: {redact(str(e))}") from e
        usage = resp.usage
        return Completion(
            text=resp.choices[0].message.content or "",
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
        )


class LLMGateway:
    """Provider를 감싸 사용량 기록, 비용 추정, 자율 작업 일일 예산을 관리한다."""

    def __init__(self, provider: LLMProvider | None, db: Database, settings: Settings):
        self.provider = provider
        self.db = db
        self.settings = settings

    @property
    def configured(self) -> bool:
        return self.provider is not None

    @property
    def model(self) -> str:
        return self.provider.model if self.provider else self.settings.openai_model

    def spent_today(self, autonomous_only: bool = True) -> float:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(self.settings.timezone)
        local_midnight = datetime.combine(datetime.now(tz).date(), time.min, tzinfo=tz)
        start = local_midnight.astimezone(timezone.utc).replace(tzinfo=None)
        q = select(func.coalesce(func.sum(LlmUsage.cost_usd), 0.0)).where(LlmUsage.ts >= start)
        if autonomous_only:
            q = q.where(LlmUsage.autonomous.is_(True))
        with self.db.session() as s:
            return float(s.scalar(q) or 0.0)

    def budget_left(self) -> float:
        return max(0.0, self.settings.daily_budget_usd - self.spent_today())

    async def chat(
        self,
        purpose: str,
        messages: list[dict],
        *,
        autonomous: bool = False,
        debate_id: int | None = None,
        json_mode: bool = False,
        max_tokens: int = 1500,
    ) -> LLMResult:
        if self.provider is None:
            raise LLMNotConfigured("OPENAI_API_KEY is not set")
        if autonomous and self.budget_left() <= 0:
            raise BudgetExceeded("daily autonomous budget exhausted")
        c = await self.provider.complete(messages, json_mode=json_mode, max_tokens=max_tokens, purpose=purpose)
        cost = (
            c.prompt_tokens * self.settings.price_in_per_m + c.completion_tokens * self.settings.price_out_per_m
        ) / 1_000_000
        with self.db.session() as s:
            s.add(
                LlmUsage(
                    purpose=purpose,
                    model=self.model,
                    prompt_tokens=c.prompt_tokens,
                    completion_tokens=c.completion_tokens,
                    cost_usd=cost,
                    autonomous=autonomous,
                    debate_id=debate_id,
                )
            )
        return LLMResult(c.text, c.prompt_tokens + c.completion_tokens, cost)

    async def json(self, purpose: str, messages: list[dict], **kw) -> tuple[dict, LLMResult]:
        res = await self.chat(purpose, messages, json_mode=True, **kw)
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", res.text.strip())
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMError(f"{purpose}: model returned invalid JSON") from e
        if not isinstance(data, dict):
            raise LLMError(f"{purpose}: expected a JSON object")
        return data, res


def build_gateway(settings: Settings, db: Database, provider: LLMProvider | None = None) -> LLMGateway:
    if provider is None and settings.openai_api_key:
        provider = OpenAIProvider(settings.openai_api_key, settings.openai_model, settings.openai_base_url)
    return LLMGateway(provider, db, settings)
