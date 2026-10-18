import itertools
import json
import re
import time

import pytest
from fastapi.testclient import TestClient

from gyunexus.config import Settings
from gyunexus.llm import Completion
from gyunexus.main import create_app


class FakeProvider:
    """호출 목적(purpose)별로 고정 응답을 돌려주는 LLM 대역. 테스트에서만 사용한다."""

    model = "fake-model"

    def __init__(self):
        self.calls: list[str] = []
        self._topics = itertools.count(1)
        self.proactive_speak = True
        self.prompts: list[tuple[str, list]] = []  # (purpose, messages) 전체 호출 기록
        self.overrides: dict = {}
        self.dedupe_response = None  # topic_dedupe 호출의 duplicate_of 응답
        self.chat_systems: list[str] = []  # chat 호출마다 전달된 시스템 프롬프트
        self.intent_response: dict = {"intent": "chat"}  # 규칙으로 판단 불가할 때의 LLM 의도 해석 응답

    async def complete(self, messages, *, json_mode, max_tokens, purpose):
        self.calls.append(purpose)
        self.prompts.append((purpose, messages))
        user = messages[-1]["content"]
        if purpose in self.overrides:  # 테스트가 특정 호출의 응답을 직접 지정한다(dict/str 또는 호출 가능 객체)
            out = self.overrides[purpose]
            out = out(messages) if callable(out) else out
        elif purpose == "topic_dedupe":
            out = {"duplicate_of": self.dedupe_response, "reason": "테스트"}
        elif purpose == "intent":
            out = self.intent_response
        elif purpose == "chat":
            self.last_chat_system = messages[0]["content"]
            self.chat_systems.append(messages[0]["content"])
            out = "안녕하세요, 무엇을 도와드릴까요?"
        elif purpose == "memory_extract":
            out = {"memories": [{"kind": "interest", "content": "사용자는 은하수 촬영을 좋아한다", "importance": 8}]}
        elif purpose == "topic_discovery":
            n = next(self._topics)
            out = {"title": f"주제 {n}번: 완전히 다른 분야의 질문 {'가나다라마바사'[n % 7] * 6}{n}", "rationale": "테스트"}
        elif purpose == "debate_plan":
            out = {"participants": ["research", "idea"], "goal": "아이디어 도출", "reason": "테스트"}
        elif purpose.startswith("debate_turn:"):
            agent = purpose.split(":")[1]
            user = next((m["content"] for m in reversed(messages) if "[열린 반박]" in m["content"]), user)  # 재시도 때는 마지막 메시지가 피드백이다
            open_ids = [int(i) for i in re.findall(r"- \[B(\d+)\]", user.split("[열린 반박]")[1].split("[지금까지의 토론]")[0])]
            if agent == "research":
                cites = [1] if "[E1]" in user else [99]
                out = {
                    "message": "자료를 조사했습니다.",
                    "claims": [{"text": "달은 밝다", "type": "fact", "evidence_ids": cites}],
                    "tool_requests": [{"tool": "astro.moon_phase", "args": {}}, {"tool": "notes.write", "args": {}}],
                }
            elif agent == "critic":
                target = "자료를 조사했습니다" if "Research Agent" in user else "idea 의견"
                if "라운드: 2" in user:  # 2라운드에는 열린 반박이 모두 처리됐다고 보고 합의한다
                    out = {"message": "남은 문제가 없습니다.", "rebuttals": [], "endorsements": ["달은 밝다"], "resolved": True}
                else:
                    out = {"message": "조건이 빠져 있습니다.", "resolved": False, "endorsements": [], "rebuttals": [{
                        "kind": "missing_condition", "target": target,
                        "detail": "관측 시각과 위치 조건이 빠져 있어 결과를 그대로 적용할 수 없습니다.",
                        "suggestion": "관측 시각과 위치 조건을 명시해 다시 제시하세요."}]}
            else:
                out = {"message": f"{agent} 의견", "claims": [{"text": "가정", "type": "assumption"}],
                       "responses": [{"rebuttal_id": i, "action": "accept", "reason": "반박을 수용해 조건을 보완합니다"} for i in open_ids]}
        elif purpose == "debate_synthesis":
            out = {
                "summary": "요약",
                "decision": "adopt",
                "ideas": [{"title": "아이디어 A", "description": "설명", "feasibility": "high", "confidence": 0.8,
                           "status": "accepted", "rationale": "검토 완료", "evidence_ids": [1]}],
                "verified_facts": [{"text": "달은 밝다", "evidence_ids": [1]}, {"text": "조작된 근거", "evidence_ids": [77]}],
                "unverified_claims": ["미확인"],
                "open_questions": ["질문"],
                "importance": 8,
                "proposed_actions": [
                    {"tool": "notes.write", "args": {"filename": "result.md", "content": "# 결과"}, "reason": "저장"},
                    {"tool": "astro.moon_phase", "args": {}, "reason": "read tools are never queued"},
                ],
            }
        elif purpose == "proactive":
            out = {"speak": self.proactive_speak, "message": "오늘 밤 은하수 보러 가실래요?", "reason": "금요일 저녁"}
        elif purpose == "debate_delivery":
            out = "토론 결과를 알려드릴게요."
        else:
            raise AssertionError(f"unexpected purpose {purpose}")
        text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
        return Completion(text, 100, 50)


@pytest.fixture
def provider():
    return FakeProvider()


@pytest.fixture
def settings(tmp_path):
    return Settings(
        data_dir=tmp_path,
        openai_api_key="",
        latitude=None,  # 사용자의 .env 값에 테스트가 영향받지 않도록 고정
        longitude=None,
        autonomous_enabled=True,
        proactive_quiet_hours="",  # 기본 조용한 시간(23~07시)이 테스트 실행 시각에 좌우되지 않게 끈다
        daily_budget_usd=0.50,
        proactive_cooldown_minutes=360,
        scheduler_tick_seconds=3600,
        tool_retry_backoff=[0, 0],  # 테스트에서는 재시도 대기 없이 최대 3회 시도
    )


@pytest.fixture
def client(settings, provider):
    app = create_app(settings, provider, run_scheduler=False)
    with TestClient(app) as c:
        c.app_state = app.state.svc
        yield c


def patch_sky(client, cloud=10, precip=5, moon=10, fail=False, by_date=None):
    """날씨·달 위상 도구를 고정 값으로 대체한다(실제 날짜의 달 위상에 테스트가 좌우되지 않게). 호출 인자를 돌려준다.

    by_date: {"YYYY-MM-DD": {"cloud":..,"precip":..,"moon":..}} 날짜별 값. fail=True면 날씨 조회가 실패한다.
    """
    from gyunexus.tools import ToolError

    svc = client.app.state.svc
    svc.settings.latitude, svc.settings.longitude = 37.5, 127.0
    calls = []

    def vals(args):
        v = {"cloud": cloud, "precip": precip, "moon": moon}
        v.update((by_date or {}).get(args.get("date"), {}))
        return v

    async def weather(args):
        calls.append(("weather", dict(args)))
        if fail:
            raise ToolError("upstream 503", kind="http_503", attempts=3)
        v = vals(args)
        return {"date": args.get("date"), "period": args.get("period"), "location": "기본 위치(설정값)", "avg_cloud_cover_pct": v["cloud"],
                "max_precip_prob_pct": v["precip"], "avg_temp_c": 14.0, "hours_sampled": 5, "window_passed": False, "source": "test"}

    async def moon_phase(args):
        calls.append(("moon", dict(args)))
        v = vals(args)
        return {"phase": "초승달", "age_days": 3.0, "illumination_pct": v["moon"], "days_to_next_new_moon": 26.0,
                "dark_sky_friendly": v["moon"] < 25, "for": {"date": args.get("date"), "period": args.get("period")}, "source": "test"}

    svc.tools.get("weather.forecast").handler = weather
    svc.tools.get("astro.moon_phase").handler = moon_phase
    return calls


def wait_for(fn, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        value = fn()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("condition not met in time")
