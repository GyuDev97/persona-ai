from datetime import datetime, timezone

import pytest

from gyunexus.textutil import similarity
from gyunexus.tools import ToolError, moon_info


def test_similarity_catches_near_duplicate_korean_titles():
    a = "은하수 촬영 계획을 돕는 기능은 무엇이어야 할까?"
    assert similarity(a, "은하수 촬영 계획을 돕는 기능은 무엇이어야 할까") > 0.9
    assert similarity(a, "주식 포트폴리오 리밸런싱 자동화") < 0.2


def test_moon_phase_known_dates():
    full = moon_info(datetime(2024, 1, 25, 18, tzinfo=timezone.utc))  # 2024-01-25 보름달
    assert full["phase"] == "보름달" and full["illumination_pct"] > 95 and not full["dark_sky_friendly"]
    new = moon_info(datetime(2024, 1, 11, 11, tzinfo=timezone.utc))  # 2024-01-11 신월
    assert new["illumination_pct"] < 5 and new["dark_sky_friendly"]


def test_policy_decisions_and_notes_path_safety(settings):
    import asyncio

    from gyunexus.main import build_services

    svc = build_services(settings)
    svc.db.create_all()
    assert svc.policy.decide("astro.moon_phase") == "allow"
    assert svc.policy.decide("notes.write") == "approval"
    assert svc.policy.decide("shell.exec") == "deny"

    async def go():
        res = await svc.policy.invoke("notes.write", {"filename": "a.md", "content": "x"}, actor="t")
        assert res.status == "approval_required"  # 승인 없이는 절대 실행되지 않는다
        assert (await svc.policy.invoke("shell.exec", {}, actor="t")).status == "denied"
        with pytest.raises(ToolError):
            await svc.tools.execute("notes.write", {"filename": "../evil.md", "content": "x"})
        with pytest.raises(ToolError):
            await svc.tools.execute("weather.forecast", {})  # 위치 미설정

    asyncio.run(go())
    assert not settings.notes_dir.exists()


def test_reasoning_models_get_effort_and_token_headroom_but_others_do_not():
    import asyncio
    from types import SimpleNamespace

    from gyunexus.config import Settings
    from gyunexus.llm import OpenAIProvider, build_gateway

    assert Settings(openai_model="gpt-5-mini").reasoning_model and Settings(openai_model="o3").reasoning_model and not Settings(openai_model="gpt-4o-mini").reasoning_model
    seen = []

    async def fake_create(**kw):
        seen.append(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))], usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1))

    def provider(model):
        s = Settings(openai_api_key="test-key-not-real", openai_model=model, database_url="sqlite:///:memory:")
        p = build_gateway(s, db=None).provider
        p._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))
        return p

    asyncio.run(provider("gpt-5-mini").complete([{"role": "user", "content": "x"}], json_mode=True, max_tokens=1400, purpose="t"))
    asyncio.run(provider("gpt-4o-mini").complete([{"role": "user", "content": "x"}], json_mode=True, max_tokens=1400, purpose="t"))
    r, n = seen
    assert r["reasoning_effort"] == "low" and r["max_completion_tokens"] == 1400 + 2500 and r["response_format"] == {"type": "json_object"}
    assert "reasoning_effort" not in n and n["max_completion_tokens"] == 1400  # 기존 모델의 호출은 그대로다