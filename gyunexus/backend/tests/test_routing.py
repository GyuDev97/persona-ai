"""대화 상태 기반 후속 질문 처리와 도구 라우팅 시나리오 테스트. 외부 HTTP(Open-Meteo)는 MockTransport로 대체한다."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

from gyunexus.main import create_app
from gyunexus.routing import find_place, parse_date, parse_period
from gyunexus.textutil import redact

SEOUL = (37.5665, 126.978)
TODAY = datetime.now(ZoneInfo("Asia/Seoul")).date()


class Weather:
    """가짜 Open-Meteo. mode: ok | 503 | 400 | timeout | flaky(처음 2번 503). 구름량은 위도 정수값으로 장소별 차이를 만든다."""

    def __init__(self):
        self.requests: list[dict] = []
        self.mode = "ok"
        self.flaky_left = 2

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(dict(request.url.params))
        if self.mode == "timeout":
            raise httpx.ConnectTimeout("timeout", request=request)
        if self.mode == "503" or (self.mode == "flaky" and self.flaky_left > 0):
            self.flaky_left -= 1
            return httpx.Response(503, text="Service Unavailable")
        if self.mode == "400":
            return httpx.Response(400, json={"reason": "bad"})
        p = request.url.params
        lat = float(p["latitude"])
        times = [f"{TODAY + timedelta(days=d)}T{h:02d}:00" for d in range(int(p["forecast_days"])) for h in range(24)]
        n = len(times)
        return httpx.Response(
            200,
            json={"hourly": {"time": times, "cloud_cover": [int(lat)] * n, "precipitation_probability": [10] * n,
                             "temperature_2m": [15.0] * n}},
        )


@pytest.fixture
def weather():
    return Weather()


@pytest.fixture
def make_client(settings, provider, weather):
    """(settings 수정 가능한) 앱을 만들어 TestClient를 돌려주는 팩토리. 같은 DB로 여러 번 만들면 재시작을 흉내 낸다."""
    opened: list[TestClient] = []

    def factory(**overrides):
        for k, v in {"latitude": SEOUL[0], "longitude": SEOUL[1], **overrides}.items():
            setattr(settings, k, v)
        app = create_app(settings, provider, run_scheduler=False, http_transport=httpx.MockTransport(weather.handler))
        c = TestClient(app).__enter__()
        opened.append(c)
        return c

    yield factory
    for c in opened:
        c.__exit__(None, None, None)


def ask(client, text, conv=None):
    r = client.post("/api/chat", json={"message": text, "conversation_id": conv})
    assert r.status_code == 200, r.text
    body = r.json()
    return body["conversation_id"], body["reply"]["meta"]["trace"]


def tool(trace, name):
    return next(t for t in trace["tools"] if t["name"] == name)


def saturday():
    return TODAY + timedelta(days=(5 - TODAY.weekday()) % 7)


# ---------- 시나리오 ----------


def test_single_sky_question_uses_defaults_without_extra_llm_call(make_client, provider, weather):
    c = make_client()
    _, tr = ask(c, "오늘 은하수 어때?")
    r = tr["routing"]
    assert r["intent"] == "new_topic" and r["interpreted_by"] == "rules"
    assert r["merged_state"]["slots"] == {"target_date": TODAY.isoformat(), "time_period": "밤",
                                          "location": "기본 위치(설정값)", "location_precision": "configured"}
    assert tool(tr, "astro.moon_phase")["status"] == "ok" and tool(tr, "weather.forecast")["status"] == "ok"
    assert "latitude" not in str(tr)  # 좌표는 추적 정보에 남기지 않는다
    assert provider.calls.count("intent") == 0 and provider.calls.count("chat") == 1
    assert len(weather.requests) == 1


def test_followup_changes_only_the_date_and_requeries(make_client, provider, weather):
    c = make_client()
    conv, _ = ask(c, "오늘 은하수 어때?")
    _, tr = ask(c, "그럼 내일은?", conv)
    ch = tr["routing"]["changes"]
    assert set(ch) == {"target_date"} and ch["target_date"]["to"] == (TODAY + timedelta(days=1)).isoformat()
    assert tr["routing"]["intent"] == "followup" and tr["routing"]["interpreted_by"] == "rules"
    assert tr["routing"]["merged_state"]["slots"]["time_period"] == "밤"  # 시간대는 유지
    assert len(weather.requests) == 2  # 날짜가 바뀌었으므로 다시 조회
    assert tool(tr, "weather.forecast")["result"]["date"] == (TODAY + timedelta(days=1)).isoformat()
    assert provider.calls.count("intent") == 0


def test_followup_changes_only_the_place(make_client, weather):
    c = make_client()
    conv, _ = ask(c, "오늘 은하수 어때?")
    _, tr = ask(c, "강원도에서 보면?", conv)
    assert set(tr["routing"]["changes"]) == {"location"}
    slots = tr["routing"]["merged_state"]["slots"]
    assert slots["location"] == "강원도" and slots["location_precision"] == "province"
    assert slots["target_date"] == TODAY.isoformat() and slots["time_period"] == "밤"
    assert float(weather.requests[-1]["latitude"]) == pytest.approx(37.8813)
    assert any("대표 지점" in a for a in tr["routing"]["advice"])  # 광역 단위 정밀도 안내


def test_spec_sequence_date_period_then_place_then_correction(make_client, provider, weather):
    c = make_client()
    conv, _ = ask(c, "오늘 은하수 어때?")
    _, t2 = ask(c, "그럼 토요일 새벽은?", conv)
    assert t2["routing"]["merged_state"]["slots"]["target_date"] == saturday().isoformat()
    assert t2["routing"]["merged_state"]["slots"]["time_period"] == "새벽"
    assert set(t2["routing"]["changes"]) == {"target_date", "time_period"} or saturday() == TODAY

    _, t3 = ask(c, "강원도에서 보면?", conv)
    s3 = t3["routing"]["merged_state"]["slots"]
    assert (s3["location"], s3["time_period"], s3["target_date"]) == ("강원도", "새벽", saturday().isoformat())
    assert "새벽" in provider.chat_systems[-1] and "강원도" in provider.chat_systems[-1]

    _, t4 = ask(c, "아니 서울 기준으로", conv)
    s4 = t4["routing"]["merged_state"]["slots"]
    assert (s4["location"], s4["location_precision"], s4["time_period"]) == ("서울", "city", "새벽")
    lats = [float(r["latitude"]) for r in weather.requests]
    assert lats == pytest.approx([37.5665, 37.5665, 37.8813, 37.5665])  # 턴마다 현재 장소로 다시 조회했다
    assert provider.calls.count("intent") == 0  # 네 턴 모두 규칙으로 해석, 추가 LLM 호출 없음


def test_switch_to_new_topic_resets_conditions(make_client, weather):
    c = make_client()
    conv, _ = ask(c, "오늘 은하수 어때?")
    ask(c, "강원도에서 보면?", conv)
    n = len(weather.requests)
    _, tr = ask(c, "그건 됐고 오늘 뉴스 알려줘", conv)
    r = tr["routing"]
    assert r["intent"] == "new_topic" and r["merged_state"]["topic"] == "news"
    assert "location" not in r["merged_state"]["slots"]  # 뉴스에는 장소 조건을 이어받지 않는다
    assert len(weather.requests) == n  # 날씨 API 호출 없음
    assert tool(tr, "news.search")["status"] == "skipped"
    assert any("뉴스" in m for m in tr["missing_data"])


def test_related_topic_carries_date_and_place(make_client):
    c = make_client()
    conv, _ = ask(c, "오늘 은하수 어때?")
    ask(c, "강원도에서 보면?", conv)
    _, tr = ask(c, "구름은 어때?", conv)  # 은하수 -> 날씨: 같은 날짜·장소를 이어받는다
    s = tr["routing"]["merged_state"]
    assert s["topic"] == "weather" and s["slots"]["location"] == "강원도"
    assert {t["name"] for t in tr["tools"]} == {"weather.forecast"}


def test_weather_api_503_is_retried_then_reported_without_inventing_data(make_client, provider, weather):
    c = make_client()
    conv, _ = ask(c, "오늘 은하수 어때?")
    weather.mode = "503"
    before = len(weather.requests)
    _, tr = ask(c, "그럼 내일은?", conv)
    w = tool(tr, "weather.forecast")
    assert w["status"] == "error" and w["error_kind"] == "http_503" and w["attempts"] == 3
    assert len(weather.requests) - before == 3  # 제한된 재시도(최대 3회)
    system = provider.chat_systems[-1]
    assert "조회에 실패했습니다" in system and "HTTP 503" in system and "사용하지 마세요" in system
    facts = system.split("[조회한 사실]")[-1].split("[조회하지 못한 데이터]")[0]
    assert '"weather"' not in facts  # 이전 턴의 날씨 값이 재사용되지 않는다
    assert any(l["event"] == "tool.error" and l["detail"]["error_kind"] == "http_503" for l in c.get("/api/logs").json())


def test_already_passed_time_window_is_not_presented_as_future(make_client, provider, monkeypatch):
    import gyunexus.tools as tools_mod

    class At22(datetime):  # 지금이 오늘 22시라고 고정
        @classmethod
        def now(cls, tz=None):
            base = datetime.now(ZoneInfo("Asia/Seoul")).replace(hour=22, minute=0, second=0, microsecond=0)
            return base.astimezone(tz) if tz else base.replace(tzinfo=None)

    monkeypatch.setattr(tools_mod, "datetime", At22)
    c = make_client()
    _, past = ask(c, "오늘 새벽 은하수 어때?")  # 오늘 새벽(00~05시)은 이미 지났다
    assert tool(past, "weather.forecast")["window_passed"] is True
    assert "이미 지났습니다" in " ".join(past["routing"]["advice"]) and "이미 지나서" in provider.chat_systems[-1]
    facts = provider.chat_systems[-1].split("[조회한 사실]")[-1].split("[조회하지 못한 데이터]")[0]
    assert "avg_cloud_cover_pct" not in facts  # 지난 시간대의 날씨 값은 모델에 전달되지 않는다
    _, night = ask(c, "오늘 밤 은하수 어때?")  # 오늘 밤(22시~)은 아직 진행 중/예정
    assert "window_passed" not in tool(night, "weather.forecast")
    assert "이미 지나서" not in provider.chat_systems[-1]


def test_flaky_api_recovers_within_retries(make_client, weather):
    c = make_client()
    weather.mode = "flaky"
    _, tr = ask(c, "오늘 은하수 어때?")
    assert tool(tr, "weather.forecast")["status"] == "ok" and len(weather.requests) == 3


@pytest.mark.parametrize("mode,kind,attempts", [("timeout", "timeout", 3), ("400", "http_400", 1)])
def test_failure_kinds_and_retry_policy(make_client, weather, mode, kind, attempts):
    c = make_client()
    weather.mode = mode
    _, tr = ask(c, "오늘 은하수 어때?")  # 서버가 죽지 않고 200으로 응답한다
    w = tool(tr, "weather.forecast")
    assert (w["error_kind"], w["attempts"]) == (kind, attempts)  # 4xx는 재시도하지 않는다


def test_unsupported_date_ranges(make_client, weather):
    c = make_client()
    conv, _ = ask(c, "오늘 은하수 어때?")
    n = len(weather.requests)

    _, far = ask(c, "그럼 10일 뒤는?", conv)  # 예보 범위(7일) 초과: 날씨는 건너뛰고 달 위상만 계산
    assert tool(far, "weather.forecast")["status"] == "skipped" and tool(far, "astro.moon_phase")["status"] == "ok"
    assert "target_date" in far["routing"]["merged_state"]["missing_fields"]

    _, month = ask(c, "그럼 다음 달은?", conv)
    assert tool(month, "weather.forecast")["status"] == "skipped"

    _, past = ask(c, "그럼 어제는 어땠어?", conv)  # 지난 날짜: 아무 도구도 호출하지 않는다
    assert {t["status"] for t in past["tools"]} == {"skipped"}
    assert len(weather.requests) == n  # 어느 경우에도 날씨 API를 부르지 않았다


def test_ambiguous_and_unknown_places_ask_instead_of_guessing(make_client, provider, weather):
    c = make_client()
    conv, _ = ask(c, "오늘 은하수 어때?")
    n = len(weather.requests)

    _, amb = ask(c, "광주에서 보면?", conv)
    s = amb["routing"]["merged_state"]
    assert s["missing_fields"] == ["location"] and "location" not in s["slots"]
    assert "광주광역시, 경기 광주" in provider.chat_systems[-1]
    assert tool(amb, "weather.forecast")["status"] == "skipped" and len(weather.requests) == n

    _, fixed = ask(c, "광주광역시로 알려줘", conv)  # 사용자가 명확히 하면 바로 조회
    assert fixed["routing"]["merged_state"]["slots"]["location"] == "광주광역시"
    assert tool(fixed, "weather.forecast")["status"] == "ok"

    _, unk = ask(c, "울릉도에서 보면?", conv)
    assert "울릉도" in provider.chat_systems[-1] and unk["routing"]["merged_state"]["missing_fields"] == ["location"]


def test_state_survives_server_restart(make_client, weather):
    c1 = make_client()
    conv, _ = ask(c1, "오늘 은하수 어때?")
    ask(c1, "강원도에서 보면?", conv)
    c1.__exit__(None, None, None)

    c2 = make_client()  # 같은 DB 파일로 새 앱(=재시작)
    _, tr = ask(c2, "그럼 내일은?", conv)
    s = tr["routing"]["merged_state"]["slots"]
    assert s["location"] == "강원도" and s["target_date"] == (TODAY + timedelta(days=1)).isoformat()
    assert tr["routing"]["prior_state"]["slots"]["location"] == "강원도"
    assert float(weather.requests[-1]["latitude"]) == pytest.approx(37.8813)


def test_states_are_isolated_per_conversation(make_client):
    c = make_client()
    ask(c, "오늘 은하수 어때?")
    ask(c, "강원도 날씨 어때?")  # 새 대화
    _, tr = ask(c, "그럼 내일은?")  # 또 다른 새 대화: 이전 대화의 주제를 이어받지 않는다
    assert tr["routing"]["intent"] == "chat" and tr["tools"] == []


def test_llm_interprets_only_ambiguous_followups(make_client, provider):
    c = make_client()
    conv, _ = ask(c, "오늘 은하수 어때?")
    tomorrow = (TODAY + timedelta(days=1)).isoformat()
    provider.intent_response = {"intent": "followup", "topic": "sky_observation", "target_date": tomorrow,
                                "time_period": None, "location": "속초"}
    _, tr = ask(c, "그럼 거기는?", conv)  # 규칙으로 단서가 없는 후속 발화
    assert provider.calls.count("intent") == 1 and tr["routing"]["interpreted_by"] == "llm"
    s = tr["routing"]["merged_state"]["slots"]
    assert (s["target_date"], s["location"]) == (tomorrow, "속초")

    provider.intent_response = {"intent": "chat"}
    _, chat = ask(c, "그럼 고마워", conv)
    assert chat["routing"]["intent"] == "chat" and chat["tools"] == []
    assert provider.calls.count("intent") == 2


def test_routing_failure_does_not_break_chat(make_client, provider):
    c = make_client()

    async def boom(*a, **k):
        raise RuntimeError("router bug")

    c.app.state.svc.conversation.router.route = boom
    _, tr = ask(c, "오늘 은하수 어때?")
    assert "내부 오류" in provider.chat_systems[-1] and tr["llm"]["called"] is True


def test_secrets_are_redacted_from_logs(make_client):
    c = make_client()
    c.app.state.svc.activity.record("system", "probe", error="auth failed for sk-proj-ABCDEF123456 and token=abc123&x=1")
    detail = next(l for l in c.get("/api/logs").json() if l["event"] == "probe")["detail"]
    assert "ABCDEF123456" not in str(detail) and "abc123" not in str(detail)
    assert redact({"k": ["Bearer abcdef.123"]}) == {"k": ["[REDACTED]"]}


# ---------- 파서 단위 테스트 ----------


@pytest.mark.parametrize("text,delta", [("오늘", 0), ("내일 어때", 1), ("모레는", 2), ("내일모레", 2), ("3일 뒤", 3), ("어제", -1)])
def test_parse_relative_dates(text, delta):
    assert parse_date(text, TODAY).date == TODAY + timedelta(days=delta)


def test_parse_weekday_and_period_pick_last_mention():
    monday = TODAY - timedelta(days=TODAY.weekday())
    assert parse_date("다음주 월요일", TODAY).date == monday + timedelta(days=7)
    assert parse_date("이번 주 수요일", TODAY).date == monday + timedelta(days=2)
    assert parse_date("토요일", TODAY).date == saturday()
    assert parse_date("다음 달 초", TODAY).beyond and parse_date("그냥 안녕", TODAY).mentioned is False
    assert parse_period("새벽 말고 저녁에") == "저녁" and parse_period("밤하늘 어때") is None
    assert parse_period("토요일 새벽") == "새벽"


def test_find_place_rightmost_and_precision():
    assert find_place("서울 말고 강릉에서").place.name == "강릉"
    assert find_place("강원도").place.precision == "province"
    assert find_place("광주").ambiguous and find_place("경기 광주").place.name == "경기 광주"
    assert find_place("울릉도에서 보면").unresolved == "울릉도"
    assert find_place("37.55, 127.21 에서").place.precision == "coordinates"
    assert not find_place("집에서 쉬는 중").any


def test_weather_tool_rejects_out_of_range_directly(make_client):
    c = make_client()
    svc = c.app.state.svc
    import asyncio

    r = asyncio.run(svc.policy.invoke("weather.forecast", {"date": (date.today() + timedelta(days=30)).isoformat()}, actor="t"))
    assert r.status == "error" and r.error_kind == "unsupported_date"
