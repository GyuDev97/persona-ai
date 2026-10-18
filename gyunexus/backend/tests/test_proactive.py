"""GYUVIS 능동 제안: 후보 생성, 점수·게이트, 사용자 반응, 재알림, 아이디어 연동, 대화 문맥, 재시작 복구."""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from conftest import patch_sky, wait_for
from fastapi.testclient import TestClient

from gyunexus.main import create_app
from gyunexus.suggestions import classify_reaction, in_quiet_hours, parse_quiet

KST = ZoneInfo("Asia/Seoul")
FRI = date(2026, 10, 23)  # 금요일
SAT_BEST = {"2026-10-24": {"cloud": 0, "precip": 0, "moon": 5}}  # 토요일 밤만 관측 조건이 좋다
BAD = {"cloud": 85, "precip": 60, "moon": 10}


def at(client, y, m, d, h, mi=0):
    utc = (datetime(y, m, d, h, 0, tzinfo=KST) + timedelta(minutes=mi)).astimezone(timezone.utc).replace(tzinfo=None)
    client.app.state.svc.context._clock = lambda: utc


def S(client):
    return client.app.state.svc


def memo(client, text="사용자는 은하수 촬영을 즐긴다", imp=9, kind="interest"):
    client.post("/api/memories", json={"kind": kind, "content": text, "importance": imp})


def open_dashboard(client, kind="dashboard_opened"):
    S(client).context.heartbeat()  # 사용자가 지금 대시보드를 보고 있다(관측된 사실)
    return client.portal.call(S(client).proactive.on_event, kind)


def rows(client):
    return client.get("/api/proactive/suggestions").json()


def chat(client, text, conv):
    r = client.post("/api/chat", json={"message": text, "conversation_id": conv})
    assert r.status_code == 200, r.text
    return r.json()


def friday_suggestion(client, provider=None):
    """금요일 저녁 접속 -> 토요일 밤 출사 제안이 전달된 상태를 만든다."""
    patch_sky(client, by_date=SAT_BEST, cloud=70, precip=30, moon=10)
    memo(client)
    at(client, 2026, 10, 23, 19, 30)
    return open_dashboard(client)


# ---------------------------------------------------------------- 1. 금요일 저녁 접속 -> 출사 제안 후보

def test_friday_evening_open_creates_a_grounded_candidate_and_delivers_it(client, provider):
    payload = friday_suggestion(client)
    assert payload and payload["proactive"] is True
    row = rows(client)[0]
    assert (row["type"], row["topic_key"], row["status"], row["confidence"]) == ("sky_observation", "sky", "delivered", "high")
    assert row["dedupe_key"] == "sky:2026-10-24"  # 금요일에는 주말 밤을 살피고 가장 조건이 좋은 토요일 밤을 골랐다
    assert "은하수" in row["reason"] and row["needed_action"] and row["valid_until"] and row["created_at"]
    ev = row["evidence"]
    assert ev["memories"][0]["content"].endswith("즐긴다") and set(ev["facts"]) >= {"weather", "moon"} and ev["facts"]["weather"]["avg_cloud_cover_pct"] == 0
    # 관측과 추정 분리: 접속은 사실, 퇴근 여부는 낮은 확신의 추정
    assert ev["context"]["observed"]["user_present"] is True and ev["context"]["inferred"]["confidence"] == "low"
    detail = row["score_detail"]
    assert set(detail["components"]) == {"relevance", "usefulness", "time_sensitivity", "evidence", "quiet"} and detail["thresholds"]["deliver"] == 0.62
    assert row["score"] >= 0.62 and row["decision"] == "deliver"
    assert payload["meta"]["suggestion_id"] == row["id"] and payload["meta"]["trigger"] == "user_returned"
    assert provider.calls.count("proactive") == 1


def test_llm_text_that_assumes_commute_or_invents_numbers_is_replaced(client, provider):
    provider.overrides["proactive"] = {"speak": True, "message": "퇴근하셨네요! 구름 3%로 완벽해요.", "reason": "테스트"}
    payload = friday_suggestion(client)
    assert "퇴근" not in payload["content"] and "3%" not in payload["content"]  # 단정·근거 없는 수치 -> 사실 기반 문구로 대체
    assert "구름 0%" in payload["content"] and "내일 밤" in payload["content"]  # 금요일 기준 토요일 밤 = 내일 밤


# ---------------------------------------------------------------- 2. 날씨 불량/조회 실패/미설정 -> 무리한 추천 금지

@pytest.mark.parametrize("kw,reason", [({"cloud": 85, "precip": 60, "moon": 10}, "not_useful"), ({"fail": True}, "weather_unavailable"),
                                       ({"cloud": 5, "precip": 0, "moon": 70}, "not_useful")])
def test_poor_or_missing_data_never_produces_a_recommendation(client, provider, kw, reason):
    patch_sky(client, **kw)
    memo(client)
    at(client, 2026, 10, 23, 19, 30)
    assert open_dashboard(client) is None
    r = rows(client)[0]
    assert r["status"] == "dropped" and r["decision_reason"].startswith(reason)
    assert provider.calls.count("proactive") == 0  # 버려지는 후보에는 LLM 비용을 쓰지 않는다
    assert not [m for c in client.get("/api/conversations").json() for m in client.get(f"/api/conversations/{c['id']}/messages").json()]


def test_unconfigured_location_means_no_weather_means_no_recommendation(client, provider):
    memo(client)
    at(client, 2026, 10, 23, 19, 30)
    assert S(client).settings.latitude is None
    assert open_dashboard(client) is None
    assert rows(client)[0]["decision_reason"].startswith("not_useful") and provider.calls.count("proactive") == 0


# ---------------------------------------------------------------- 3. 관련 기억 없음 -> 제안하지 않음

def test_no_related_memory_means_silence(client, provider):
    patch_sky(client)
    memo(client, "사용자는 요리를 좋아한다", 9)
    at(client, 2026, 10, 23, 19, 30)
    assert open_dashboard(client) is None
    assert rows(client) == [] and provider.calls.count("proactive") == 0


# ---------------------------------------------------------------- 4. 같은 제안 중복 전달 방지, 이벤트 폭주 방지

def test_same_night_is_not_suggested_twice_and_event_bursts_are_ignored(client, provider):
    friday_suggestion(client)
    assert open_dashboard(client) is None  # 같은 접속 이벤트가 곧바로 또 들어옴 -> 무시
    assert any(l["detail"].get("reason") == "duplicate_event" for l in client.get("/api/logs", params={"limit": 50}).json() if l["event"] == "proactive.skipped")
    at(client, 2026, 10, 24, 2, 0)  # 쿨다운(6시간)이 지난 뒤
    assert open_dashboard(client, "manual") is None
    last = rows(client)[0]
    assert last["status"] == "dropped" and last["decision_reason"].startswith("duplicate")
    assert provider.calls.count("proactive") == 1
    assert len([m for m in _all_messages(client) if m["proactive"]]) == 1


def _all_messages(client):
    return [m for c in client.get("/api/conversations").json() for m in client.get(f"/api/conversations/{c['id']}/messages").json()]


# ---------------------------------------------------------------- 5. 거절 후 반복 제안 방지

def test_decline_blocks_the_topic_for_the_day_without_writing_long_term_memory(client, provider):
    payload = friday_suggestion(client)
    conv = payload["conversation_id"]
    memories_before = len(client.get("/api/memories").json())
    chat(client, "오늘은 피곤해서 안 갈래", conv)
    row = rows(client)[0]
    assert row["reaction"] == "declined" and row["blocked_until"].startswith("2026-10-23T15:00")  # 금요일 24:00 KST = 15:00Z
    system = provider.last_chat_system
    assert "[직전 능동 제안]" in system and "거절" in system and "장기기억에는 저장하지 않음" in system
    assert len(client.get("/api/memories").json()) == memories_before  # 일시적 반응은 기억에 저장하지 않는다
    at(client, 2026, 10, 23, 21, 0)
    assert open_dashboard(client, "manual") is None
    assert rows(client)[0]["decision_reason"].startswith("recent_declined")


def test_reaction_classifier_covers_the_six_kinds():
    fri = FRI
    k = lambda t, topic="sky": classify_reaction(t, fri, topic)  # noqa: E731
    assert k("오늘은 피곤해서 안 갈래").kind == "declined"
    assert k("이번 주말은 안 갈래").block_until_date == date(2026, 10, 24)  # 날짜를 말하면 그날까지
    assert k("좋아, 확인해 줘").kind == "interested"
    assert k("어디가 좋은데?").kind == "details"
    s = k("다음 주 금요일에 다시 알려줘")
    assert (s.kind, s.due_date, s.hour) == ("snoozed", date(2026, 10, 30), 19)
    assert k("나중에 다시 알려줘").delay_hours == 3.0
    assert k("내일 저녁 8시에 다시 알려줘").hour == 20
    assert k("출사 알림은 그만 알려줘").kind == "muted" and k("모든 알림 그만 보내줘").scope == "all"
    assert k("그건 됐고 오늘 뉴스 알려줘").kind == "chat" and k("오늘 뉴스 알려줘").kind == "chat"  # 다른 주제로 넘어가면 반응이 아니라 일반 대화
    assert k("안녕, 점심 뭐 먹지").kind == "chat"


# ---------------------------------------------------------------- 6. 재알림 요청, 7. 시점 도래 후 다시 판단

def test_snooze_registers_a_real_date_reminder_once_and_skips_tools(client, provider):
    payload = friday_suggestion(client)
    calls = patch_sky(client, by_date=SAT_BEST, cloud=70, precip=30, moon=10)
    out = chat(client, "다음 주 금요일에 다시 알려줘", payload["conversation_id"])
    rem = client.get("/api/proactive/reminders").json()
    assert len(rem) == 1 and rem[0]["status"] == "pending" and rem[0]["due_at"].startswith("2026-10-30T10:00")  # 19:00 KST
    assert "2026-10-30" in provider.last_chat_system and "재알림" in provider.last_chat_system
    assert calls == [] and out["reply"]["meta"]["trace"]["tools"] == []  # 재알림 요청을 날씨 조회로 오해하지 않는다
    again = S(client).proactive._apply_reaction(rows(client)[0]["id"], "sky", classify_reaction("다음 주 금요일에 다시 알려줘", FRI, "sky"), S(client).context.now())
    assert "합쳤다" in again and len(client.get("/api/proactive/reminders").json()) == 1  # 중복 등록 방지
    assert rows(client)[0]["reaction"] == "snoozed"
    at(client, 2026, 10, 24, 10, 0)
    memo(client, "사용자는 별 사진을 좋아한다", 8)
    assert open_dashboard(client, "manual") is None  # 재알림이 걸린 주제는 그 사이 다시 묻지 않는다


def test_reminder_is_rejudged_with_fresh_data_when_due(client, provider):
    payload = friday_suggestion(client)
    chat(client, "다음 주 금요일에 다시 알려줘", payload["conversation_id"])
    at(client, 2026, 10, 30, 19, 10)
    calls = patch_sky(client, by_date={"2026-10-30": {"cloud": 5, "precip": 0, "moon": 8}})
    client.portal.call(S(client).proactive.process_reminders)
    msg = [m for m in _all_messages(client) if m["proactive"]][-1]
    assert msg["meta"]["trigger"] == "reminder"
    assert {a["date"] for k, a in calls if k == "weather"} >= {"2026-10-30"}  # 지난번 결과를 재사용하지 않고 새로 조회
    assert client.get("/api/proactive/reminders").json()[0]["status"] == "fired"
    assert any(r["user_requested"] and r["status"] == "delivered" for r in rows(client))


def test_due_reminder_with_bad_conditions_is_reported_honestly(client, provider):
    payload = friday_suggestion(client)
    chat(client, "다음 주 금요일에 다시 알려줘", payload["conversation_id"])
    at(client, 2026, 10, 30, 19, 10)
    patch_sky(client, **BAD)
    before = provider.calls.count("proactive")
    client.portal.call(S(client).proactive.process_reminders)
    text = [m for m in _all_messages(client) if m["proactive"]][-1]["content"]
    assert "조건이 좋지 않아요" in text and "가실래요" not in text
    assert provider.calls.count("proactive") == before  # 나쁜 조건은 권유 문장을 만들지 않으므로 LLM을 쓰지 않는다


def test_reminder_retries_on_api_failure_then_admits_it_could_not_check(client, provider):
    payload = friday_suggestion(client)
    chat(client, "다음 주 금요일에 다시 알려줘", payload["conversation_id"])
    at(client, 2026, 10, 30, 19, 10)
    patch_sky(client, fail=True)
    for i in range(3):
        at(client, 2026, 10, 30, 19, 10 + 35 * i)
        client.portal.call(S(client).proactive.process_reminders)
    rem = client.get("/api/proactive/reminders").json()[0]
    assert rem["status"] == "fired" and rem["attempts"] == 3
    assert "확인하지 못했어요" in [m for m in _all_messages(client) if m["proactive"]][-1]["content"]  # 추측하지 않고 실패를 알린다


# ---------------------------------------------------------------- 8. 조용한 시간대

def test_quiet_hours_hold_suggestions_and_release_them_when_still_valid(client, provider):
    r = client.put("/api/proactive/settings", json={"quiet_hours": "23:00-07:00"})
    assert r.status_code == 200 and r.json()["quiet_hours"] == "23:00-07:00"
    patch_sky(client, by_date=SAT_BEST, cloud=70, precip=30, moon=10)
    memo(client)
    at(client, 2026, 10, 23, 23, 30)
    assert open_dashboard(client) is None
    held = rows(client)[0]
    assert held["status"] == "held" and held["decision_reason"].startswith("quiet_hours") and provider.calls.count("proactive") == 0
    at(client, 2026, 10, 24, 7, 30)
    payload = open_dashboard(client, "scheduled")
    assert payload and rows(client)[0]["status"] == "delivered"  # 조용한 시간이 끝났고 정보도 여전히 유효하다
    assert [x["status"] for x in rows(client)].count("held") == 0  # 보류 행이 남아 전달을 되풀이하지 않는다(만료 처리됨)


def test_quiet_hour_helpers():
    assert parse_quiet("23:00-07:00") == (1380, 420) and parse_quiet("") is None and parse_quiet("25:00-07:00") is None
    sat = datetime(2026, 10, 24, 0, 30, tzinfo=KST)
    assert in_quiet_hours("23:00-07:00", sat) and not in_quiet_hours("23:00-07:00", sat.replace(hour=12)) and in_quiet_hours("13:00-15:00", sat.replace(hour=14))


# ---------------------------------------------------------------- 사용자 통제

def test_user_controls_disable_daily_limit_and_topic_toggle(client, provider):
    assert client.put("/api/proactive/settings", json={"quiet_hours": "late"}).status_code == 422
    assert client.put("/api/proactive/settings", json={"topics": {"unknown": True}}).status_code == 422
    patch_sky(client)
    memo(client)
    at(client, 2026, 10, 23, 19, 30)
    client.put("/api/proactive/settings", json={"enabled": False})
    assert open_dashboard(client) is None and provider.calls.count("proactive") == 0
    client.put("/api/proactive/settings", json={"enabled": True, "topics": {"sky": False}})
    S(client).context.heartbeat()
    assert client.portal.call(S(client).proactive.on_event, "manual") is None and rows(client) == []
    client.put("/api/proactive/settings", json={"topics": {"sky": True}, "daily_max": 1})
    S(client).settings.proactive_cooldown_minutes = 0
    patch_sky(client, by_date={"2026-10-23": {"cloud": 0, "precip": 0, "moon": 5}})
    assert client.portal.call(S(client).proactive.on_event, "manual")
    patch_sky(client, by_date={"2026-10-25": {"cloud": 0, "precip": 0, "moon": 5}})
    at(client, 2026, 10, 23, 20, 30)
    S(client).context.heartbeat()
    assert client.portal.call(S(client).proactive.on_event, "manual") is None
    assert rows(client)[0]["decision_reason"].startswith("daily_limit") and rows(client)[0]["status"] == "held"


def test_mute_is_a_persistent_preference_unlike_a_decline(client, provider):
    payload = friday_suggestion(client)
    chat(client, "출사 알림은 그만 알려줘", payload["conversation_id"])
    prefs = client.get("/api/proactive/settings").json()
    assert prefs["topics"]["sky"] is False and prefs["topics"]["idea"] is True
    assert any("원하지 않는다" in m["content"] and m["kind"] == "preference" for m in client.get("/api/memories").json())
    assert rows(client)[0]["reaction"] == "muted"


def test_borderline_score_asks_the_llm_once_and_respects_its_veto(client, provider):
    S(client).settings.proactive_deliver_threshold = 0.99  # 거의 모든 후보가 경계 구간이 된다
    provider.proactive_speak = False
    patch_sky(client, by_date=SAT_BEST, cloud=70, precip=30, moon=10)
    memo(client)
    at(client, 2026, 10, 23, 19, 30)
    assert open_dashboard(client) is None
    r = rows(client)[0]
    assert r["decision"] == "llm_declined" and r["status"] == "dropped" and provider.calls.count("proactive") == 1


def test_expired_information_is_never_used(client):
    from gyunexus.suggestions import Candidate

    patch_sky(client)
    at(client, 2026, 10, 23, 19, 30)
    now = S(client).context.now()
    c = Candidate("sky_observation", "sky", "sky:x", "manual", "t", "r", "", {}, {}, "high", now - timedelta(minutes=1),
                  {"relevance": 1, "usefulness": 1, "time_sensitivity": 1, "evidence": 1})
    status, decision, reason = S(client).proactive._gate(c, S(client).proactive.prefs(), now)
    assert (status, decision) == ("dropped", "drop") and reason.startswith("expired")


# ---------------------------------------------------------------- 9·10. 채택된 에이전트 아이디어 전달, 폐기/미검증 차단

def run_debate(client, topic):
    r = client.post("/api/debates/run", json={"topic": topic})
    assert r.status_code == 202, r.text
    return wait_for(lambda: next((d for d in client.get("/api/debates").json() if d["status"] != "running" and d["title"] == topic), None), 15)


def test_accepted_idea_is_delivered_once_and_repeats_are_blocked(client, provider):
    run_debate(client, "결과를 사용자에게 알려야 할까?")
    client.portal.call(S(client).proactive.deliver_debates)
    delivered = [r for r in rows(client) if r["type"] == "idea"]
    assert len(delivered) == 1 and delivered[0]["status"] == "delivered" and delivered[0]["confidence"] in ("high", "medium")
    assert delivered[0]["evidence"]["titles"] == ["아이디어 A"] and delivered[0]["params"]["debate_id"] >= 1
    msg = [m for m in _all_messages(client) if m["proactive"]][-1]
    assert msg["meta"]["kind"] == "debate" and msg["meta"]["suggestion_id"] == delivered[0]["id"]
    client.portal.call(S(client).proactive.deliver_debates)
    assert len([m for m in _all_messages(client) if m["proactive"]]) == 1  # 같은 토론 재전달 없음
    S(client).settings.proactive_cooldown_minutes = 0
    run_debate(client, "다른 주제로 같은 아이디어가 또 채택되면 어떻게 할까?")
    client.portal.call(S(client).proactive.deliver_debates)
    assert len([m for m in _all_messages(client) if m["proactive"]]) == 1  # 이미 전달한 것과 같은 아이디어는 다시 알리지 않는다
    assert any(r["status"] == "dropped" and r["decision_reason"].startswith("duplicate") for r in rows(client))


def test_discarded_or_unverified_ideas_never_become_candidates(client, provider):
    base = {"feasibility": "medium", "confidence": 0.6, "risks": [], "next_steps": []}
    provider.overrides["debate_synthesis"] = {"summary": "요약", "decision": "adopt", "importance": 10, "ideas": [
        {**base, "title": "폐기된 아이디어", "description": "d", "status": "discarded", "rationale": "r"},
        {**base, "title": "추가조사 아이디어", "description": "d", "status": "needs_research", "rationale": "r"}]}
    run_debate(client, "결과를 사용자에게 알려야 할까?")
    S(client).settings.importance_threshold = 0
    client.portal.call(S(client).proactive.deliver_debates)
    assert [r for r in rows(client) if r["type"] == "idea"] == [] and not [m for m in _all_messages(client) if m["proactive"]]  # 중요도가 높아도 전달 안 함


def test_idea_delivery_respects_quiet_hours_and_the_idea_topic_switch(client, provider):
    client.put("/api/proactive/settings", json={"topics": {"idea": False}})
    run_debate(client, "결과를 사용자에게 알려야 할까?")
    client.portal.call(S(client).proactive.deliver_debates)
    assert not [m for m in _all_messages(client) if m["proactive"]]
    client.put("/api/proactive/settings", json={"topics": {"idea": True}})
    client.portal.call(S(client).proactive.deliver_debates)
    assert len([m for m in _all_messages(client) if m["proactive"]]) == 1  # 꺼져 있던 동안 막혔을 뿐 폐기되지 않았다


# ---------------------------------------------------------------- 11. 제안 이후 후속 대화 문맥 유지

def test_follow_up_questions_keep_the_suggestions_topic_date_and_evidence(client, provider):
    payload = friday_suggestion(client)
    conv = payload["conversation_id"]
    calls = patch_sky(client, by_date=SAT_BEST, cloud=70, precip=30, moon=10)
    first = chat(client, "어디가 좋은데?", conv)
    system = provider.last_chat_system
    assert "[직전 능동 제안]" in system and "avg_cloud_cover_pct" in system and "내일 밤" in system  # 금요일 기준 토요일 밤 = 내일 밤
    tr = first["reply"]["meta"]["trace"]
    assert tr["proactive"]["reaction"] == "details" and tr["routing"]["prior_state"]["topic"] == "sky_observation"
    assert tr["routing"]["prior_state"]["slots"]["target_date"] == "2026-10-24"
    second = chat(client, "그럼 토요일 새벽은?", conv)
    r2 = second["reply"]["meta"]["trace"]["routing"]
    assert r2["intent"] == "followup" and r2["merged_state"]["slots"]["time_period"] == "새벽"
    assert ("weather", {"date": "2026-10-24", "period": "새벽", "latitude": 37.5, "longitude": 127.0, "location_name": "기본 위치(설정값)"}) in calls


def test_reminder_request_after_a_few_turns_is_still_registered(client, provider):
    """실제 LLM 실행에서 발견: '어디가 좋은데?' 뒤의 '다음 주 금요일에 다시 알려줘'가 재알림으로 처리되지 않던 문제."""
    payload = friday_suggestion(client)
    conv = payload["conversation_id"]
    chat(client, "어디가 좋은데?", conv)
    assert "지명을 지어내지 말고" in provider.last_chat_system  # 장소 데이터가 없으면 지명을 만들지 않는다
    calls = patch_sky(client, by_date=SAT_BEST, cloud=70, precip=30, moon=10)
    out = chat(client, "다음 주 금요일에 다시 알려줘", conv)
    rem = client.get("/api/proactive/reminders").json()
    assert len(rem) == 1 and rem[0]["due_at"].startswith("2026-10-30T10:00") and "2026-10-30" in provider.last_chat_system
    assert out["reply"]["meta"]["trace"]["tools"] == [] and calls == []
    assert rows(client)[0]["reaction"] == "snoozed"


# ---------------------------------------------------------------- 12. 서버 재시작 후 상태 유지

def test_state_survives_a_server_restart(settings, provider):
    app1 = create_app(settings, provider, run_scheduler=False)
    c1 = TestClient(app1).__enter__()
    payload = friday_suggestion(c1)
    chat(c1, "다음 주 금요일에 다시 알려줘", payload["conversation_id"])
    c1.__exit__(None, None, None)

    app2 = create_app(settings, provider, run_scheduler=False)  # 같은 DB 파일로 다시 시작
    with TestClient(app2) as c2:
        calls = patch_sky(c2, by_date={"2026-10-30": {"cloud": 0, "precip": 0, "moon": 5}})
        assert c2.get("/api/proactive/reminders").json()[0]["status"] == "pending"  # 재알림 유지
        at(c2, 2026, 10, 23, 19, 40)
        S(c2).context.heartbeat()
        assert c2.portal.call(S(c2).proactive.on_event, "dashboard_opened") is None  # 이벤트 간격 기록도 유지(중복 접속 이벤트)
        at(c2, 2026, 10, 24, 2, 0)
        assert c2.portal.call(S(c2).proactive.on_event, "manual") is None
        assert rows(c2)[0]["decision_reason"].startswith(("duplicate", "snoozed", "recent_snoozed"))  # 전달 이력·재알림 상태 유지
        # 대화 상태 유지: 재시작 뒤 첫 후속 질문이 제안 문맥을 이어받는다
        out = chat(c2, "그럼 토요일 새벽은?", payload["conversation_id"])
        assert out["reply"]["meta"]["trace"]["routing"]["prior_state"]["slots"]["target_date"] == "2026-10-24"
        at(c2, 2026, 10, 30, 19, 10)
        c2.portal.call(S(c2).proactive.process_reminders)
        assert c2.get("/api/proactive/reminders").json()[0]["status"] == "fired"
        assert any(a["date"] == "2026-10-30" for k, a in calls if k == "weather")


# ---------------------------------------------------------------- 실제 API 경로

def test_dashboard_heartbeat_endpoint_starts_the_event(client, provider):
    patch_sky(client, by_date=SAT_BEST, cloud=70, precip=30, moon=10)
    memo(client)
    at(client, 2026, 10, 23, 19, 30)
    assert client.post("/api/context/activity").json()["returned"] is True
    wait_for(lambda: rows(client) and rows(client)[0]["status"] == "delivered")
    assert rows(client)[0]["event"] == "dashboard_opened"
