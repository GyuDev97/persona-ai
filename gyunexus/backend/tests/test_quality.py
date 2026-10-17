"""자율 토론 협업 품질 개선 검증: 증거 일관성, 에이전트 선택, Critic 품질, 정체 종료, 결과 분류·전달, 주제 발굴, 비용 상한."""

import asyncio
import re
import sqlite3
import time

import pytest
from conftest import wait_for

from gyunexus.agents.evidence import evidence_flags, find_conflicts, numbers_missing, unverified_entities, verify_claim
from gyunexus.agents.ledger import Ledger
from gyunexus.agents.orchestrator import AgentOrchestrator
from gyunexus.agents.planner import plan_participants
from gyunexus.main import build_services
from gyunexus.tools import ToolError

ALL = {"research", "idea", "developer", "critic"}
WEATHER_61 = {"date": "2026-10-18", "period": "저녁", "location": "임진각", "avg_cloud_cover_pct": 17,
              "max_precip_prob_pct": 61, "window_passed": False, "source": "test"}


def run_and_wait(client, topic):
    r = client.post("/api/debates/run", json={"topic": topic})
    assert r.status_code == 202, r.text
    deb = wait_for(lambda: next((d for d in client.get("/api/debates").json() if d["status"] != "running"), None), 15)
    return client.get(f"/api/debates/{deb['id']}").json()


def round_of(messages):
    text = next(m["content"] for m in reversed(messages) if "라운드: " in m["content"])
    return int(re.search(r"라운드: (\d+)/", text).group(1))


# ---------- 1·2. 에이전트 선택 ----------


def test_research_is_required_when_external_facts_are_needed():
    plan = plan_participants("이번 주말 은하수 촬영하기 좋은 장소는 어디일까?", "", {"participants": ["idea", "critic"]}, ALL)
    assert "research" in plan["participants"] and plan["needs_facts"] is True
    r = plan["reasons"]["research"]
    assert r["selected"] and r["by"] == "rule" and "LLM은 제외를 제안했으나 규칙이 우선" in r["reason"]


def test_research_is_skipped_when_no_facts_needed_and_expertise_must_match():
    plan = plan_participants("은하수 사진의 구도를 개선하는 아이디어", "", {"participants": ["research", "developer", "idea", "critic"]}, ALL)
    assert plan["participants"] == ["idea", "critic"] and plan["needs_facts"] is False
    assert "LLM이 제안했지만 외부 사실이 필요한 표현이 없어 제외" in plan["reasons"]["research"]["reason"]
    assert "전문성이 맞지 않아 제외" in plan["reasons"]["developer"]["reason"]
    sw = plan_participants("GyuNexus의 기억 검색을 FastAPI로 구현하는 방법", "", {}, ALL)
    assert sw["participants"] == ["idea", "developer", "critic"]
    assert plan_participants("뭐든", "", {}, ALL - {"critic"})["reasons"]["critic"]["selected"] is False  # 비활성 에이전트는 제외 이유 기록


def test_selection_reasons_are_recorded_in_debate_and_log(client):
    d = run_and_wait(client, "이번 주말 은하수 출사 날씨 조건은 어떨까?")
    assert d["participants"][0] == "research"
    reasons = d["plan"]["reasons"]
    assert set(reasons) == ALL and reasons["developer"]["selected"] is False and d["plan"]["needs_facts"] is True
    logged = {l["agent_id"]: l for l in client.get("/api/logs", params={"limit": 200}).json() if l["event"] == "debate.plan"}
    assert logged["research"]["detail"]["selected"] is True and "조사 필수" in logged["research"]["detail"]["reason"]


# ---------- 3. 증거와 충돌하는 결론 ----------


def test_conflict_detection_for_the_two_reported_cases():
    precip = evidence_flags("weather.forecast", WEATHER_61)
    assert precip[0]["code"] == "high_precip" and "61%" in precip[0]["text"]
    assert find_conflicts("10월 18일은 비 올 확률이 낮아 출사에 적합합니다.", precip)
    assert not find_conflicts("10월 18일은 강수확률이 61%로 높아 우산이 필요합니다.", precip)
    assert not find_conflicts("10월 19일은 비 올 확률이 낮습니다.", precip)  # 다른 날짜는 해당 없음

    moon = evidence_flags("astro.moon_phase", {"phase": "상현달", "illumination_pct": 37, "dark_sky_friendly": False})
    assert moon[0]["code"] == "moon_bright"
    assert find_conflicts("달은 상현달로 37%의 조명이라 별 사진 촬영에 유리합니다.", moon)
    assert not find_conflicts("달빛이 밝아 은하수 촬영에는 불리합니다.", moon)
    assert evidence_flags("weather.forecast", None, error="timeout", error_kind="timeout")[0]["severity"] == "error"


def test_rules_do_not_flag_consistent_statements():
    """실제 LLM 실행에서 나온 오탐 사례: 부정 표현, '적합'의 '적', 날짜가 여럿인 일반론."""
    moon = evidence_flags("astro.moon_phase", {"phase": "상현달", "illumination_pct": 33, "dark_sky_friendly": False, "for": {"date": "2026-10-17"}})
    cloud = evidence_flags("weather.forecast", {"date": "2026-10-17", "period": "밤", "avg_cloud_cover_pct": 60, "max_precip_prob_pct": 2})
    assert not find_conflicts("2026-10-17은 평균 구름량이 60%이고 달의 밝기가 33%로 어두운 하늘 조건이 아니다.", moon + cloud)
    assert not find_conflicts("2026-10-23의 구름량은 32%로 적합할 가능성이 있다.", cloud)  # 다른 날짜 + '적합'의 '적'
    assert not find_conflicts("2026-10-17은 부적합하다. 촬영은 구름량이 낮은 날이 바람직하다. 2026-10-23을 보자.", cloud)  # 날짜가 여럿인 일반론
    assert find_conflicts("2026-10-17 밤하늘은 맑다.", cloud)  # 같은 날짜의 모순은 계속 잡는다
    assert find_conflicts("이 날은 구름이 적고 맑습니다.", cloud)  # 날짜 언급이 전혀 없는 글은 경고에 적용한다
    assert find_conflicts("10월 17일이 가장 좋습니다. 이 날은 하늘이 맑고 구름도 적습니다.", cloud)  # 단일 날짜 글의 후속 문장


def test_general_advice_sentences_are_not_treated_as_date_specific_facts():
    cloud = evidence_flags("weather.forecast", {"date": "2026-10-17", "period": "저녁", "avg_cloud_cover_pct": 72, "max_precip_prob_pct": 0})
    moon = evidence_flags("astro.moon_phase", {"phase": "상현달", "illumination_pct": 38, "dark_sky_friendly": False})
    assert not find_conflicts("구름이 적은 장소로 이동하는 것이 필요하다.", cloud)
    assert not find_conflicts("고지대와 인공 조명이 적은 지역은 은하수 촬영에 유리하다.", moon)  # '조명'은 달빛이 아니다
    assert find_conflicts("달은 상현달로 38%라 은하수 촬영에 유리합니다.", moon)  # 달에 대한 모순은 계속 잡는다
    assert not find_conflicts("달 밝기 38%로 약간 밝지만 날씨가 우수해 촬영에 더 적합합니다.", moon)  # 한계를 인정한 서술은 충돌이 아니다


def test_unverified_technology_names_are_flagged():
    ents = unverified_entities("spaCy와 Hugging Face의 Transformers, AWS, FastAPI를 쓴다. API와 NLP는 일반 용어.", "Python/FastAPI/React")
    assert {"spaCy", "Hugging Face", "Transformers", "AWS"} <= set(ents) and "FastAPI" not in ents and "API" not in ents


def test_dates_without_evidence_are_reported():
    from gyunexus.agents.evidence import uncovered_dates

    assert uncovered_dates("11월 초로 일정을 조정하는 것이 좋다", {"2026-10-22"}) == ["11월 초/중/말"]
    assert uncovered_dates("10월 22일과 2026-10-29 출사", {"2026-10-22"}) == ["2026-10-29"]
    assert uncovered_dates("10월 22일 출사", {"2026-10-22"}) == []


def _gate(ledger, ideas, summary="요약"):
    svc = build_services(__import__("gyunexus.config", fromlist=["Settings"]).Settings(data_dir=__import__("tempfile").mkdtemp()))
    return svc.orchestrator._gate_result({"summary": summary, "importance": 9, "ideas": ideas}, ledger, ledger.all_flags())


def _idea(title, desc, ev=(), status="accepted"):
    return {"title": title, "description": desc, "status": status, "rationale": "r", "evidence_ids": list(ev)}


def test_gate_blocks_unsupported_dates_missing_evidence_and_open_rebuttals():
    led = Ledger("은하수 출사", needs_facts=True)
    led.add_evidence(1, "weather.forecast", '{"date": "2026-10-22", "avg_cloud_cover_pct": 24}', "ok", [])
    led.add_message(2, "idea", "11월 초로 일정을 조정하자고 제안합니다.")
    led.validate_rebuttals([{"kind": "execution_risk", "target": "11월 초로 일정을 조정하자고 제안합니다",
                            "detail": "11월 초의 날씨와 달 위상을 확인하지 않아 실행 가능성을 알 수 없습니다.", "suggestion": "11월 초 예보와 월령을 먼저 조회하세요."}], 2)
    res = _gate(led, [
        _idea("11월 초 출사", "11월 초로 일정을 조정하는 것이 가장 좋다", ev=[1]),  # 증거가 다루지 않은 날짜 + 해소되지 않은 반박
        _idea("준비물", "삼각대와 광각 렌즈를 챙긴다"),  # 사실 확인이 필요한 주제인데 증거 없음
        _idea("10월 22일 출사", "10월 22일 밤은 구름량 24%로 양호하다", ev=[1]),  # 증거가 뒷받침
    ])
    by = {i["title"]: i for i in res["ideas"]}
    assert by["11월 초 출사"]["status"] == "needs_research" and "증거가 다루지 않은 날짜" in by["11월 초 출사"]["rationale"]
    assert "해소되지 않은 반박: B1" in by["11월 초 출사"]["rationale"]
    assert by["준비물"]["status"] == "needs_research" and "뒷받침하는 증거 없음" in by["준비물"]["rationale"]
    assert by["10월 22일 출사"]["status"] == "accepted"
    assert res["status"] == "accepted" and res["recommendation"]["accepted"] == ["10월 22일 출사"]


def test_context_block_gives_exact_weekend_dates(settings):
    from datetime import date, timedelta

    svc = build_services(settings)
    block = svc.orchestrator._context_block()
    today = date.today()
    sat = today + timedelta(days=(5 - today.weekday()) % 7) if today.weekday() != 6 else today
    assert sat.isoformat() in block and "이번 주말:" in block


def test_entity_check_ignores_descriptive_phrases_and_known_names():
    assert unverified_entities("빛 공해가 적은 국립공원이나 높은 국립공원에서 촬영", "") == []
    assert unverified_entities("정선의 오선폭포 주변", "주제: 오선폭포") == []


def test_preserved_claims_count_as_kept_when_numbers_are_restated():
    led = Ledger("", needs_facts=True)
    led.add_evidence(1, "weather.forecast", '{"avg_cloud_cover_pct": 0, "date": "2026-10-21"}', "ok", [])
    led.add_claims("idea", 1, [{"text": "21일 저녁은 평균 구름량이 0%로 맑다", "type": "fact", "evidence_ids": [1]}])
    assert led.missing_preserved(["2026년 10월 21일 저녁이 가장 좋습니다. 구름량이 0%라서 맑고 비도 없습니다."]) == []
    assert len(led.missing_preserved(["준비물은 삼각대와 렌즈입니다."])) == 1


def test_planner_ignores_rationale_words():
    plan = plan_participants("GyuNexus의 비서 기능을 개선할 아이디어", "사용자가 주말 출사를 즐겨서", {}, ALL)
    assert "research" not in plan["participants"] and "developer" in plan["participants"]


def test_verified_means_evidence_directly_supports_a_fact():
    ev = {1: {"tool": "weather.forecast", "status": "ok", "summary": '{"max_precip_prob_pct": 61, "date": "2026-10-18"}',
              "flags": evidence_flags("weather.forecast", WEATHER_61)}}
    flags = ev[1]["flags"]
    v = lambda text, typ="fact", ids=(1,): verify_claim(text, typ, list(ids), ev, "", flags)  # noqa: E731
    assert v("10월 18일 강수확률은 61%이다")["status"] == "verified"
    assert v("10월 18일 강수확률은 12%이다")["status"] == "unverified"  # 인용 증거에 없는 수치
    assert v("강수확률은 61%이다", ids=())["status"] == "unverified"  # 증거 인용 없음
    judged = v("10월 18일은 출사에 적합하다")  # 판단이 섞이면 사실이 아니라 해석
    assert judged["type"] == "interpretation" and judged["status"] == "interpretation"
    assert v("10월 18일은 비 올 확률이 낮아 출사에 적합하다")["status"] == "conflicted"
    assert v("출사 전에 장비를 점검하자", "proposal")["status"] == "proposal"
    assert v("아마 맑을 것이다", "opinion")["status"] == "assumption"
    assert numbers_missing("61%와 40%", "61") == ["40"]


def test_conclusion_conflicting_with_evidence_is_not_stated_as_fact(client, provider):
    client.app.state.svc.tools.get("weather.forecast").handler = lambda args: _async(WEATHER_61)
    provider.overrides["debate_turn:research"] = {
        "message": "예보를 요청합니다.", "claims": [{"text": "10월 18일 저녁 강수확률은 61%이다", "type": "fact", "evidence_ids": [1]}],
        "tool_requests": [{"tool": "weather.forecast", "args": {}}]}
    provider.overrides["debate_synthesis"] = {
        "summary": "10월 18일은 맑고 비 올 확률이 낮아 출사하기 좋습니다.", "decision": "adopt", "importance": 9,
        "ideas": [{"title": "10월 18일 출사", "description": "10월 18일은 비 올 확률이 낮아 출사에 적합합니다.", "status": "accepted",
                   "rationale": "날씨 양호", "evidence_ids": [1], "confidence": 0.9}]}
    d = run_and_wait(client, "이번 주말 은하수 출사 날짜를 정해야 할까?")
    res = d["result"]
    assert res["status"] == "needs_research" and res["decision"] == "revise"
    assert "⚠" in res["summary"] and "강수확률 61%" in res["summary"] + " ".join(res["warnings"])
    assert d["ideas"][0]["status"] == "needs_research" and "증거 경고와 충돌" in d["ideas"][0]["rationale"]
    assert d["importance"] <= 4  # 검증되지 않은 결과는 높은 중요도로 올리지 않는다
    assert any("강수확률 61%" in r for r in d["ideas"][0]["risks"])  # 아이디어의 위험 항목에도 증거 경고가 그대로 전달된다
    ev = d["evidence"][0]
    assert ev["status"] == "ok" and ev["flags"][0]["code"] == "high_precip"


def _async(value):
    async def inner():
        return value

    return inner()


# ---------- 4. 근거 없는 고유명사 ----------


def test_unverified_names_are_flagged_unless_known():
    text = "증도 천문대 근처가 촬영에 유리하고 캐논 EOS 6D와 Adobe Lightroom을 쓴다"
    ents = unverified_entities(text, "")
    assert {"증도 천문대", "EOS 6D", "캐논", "Adobe", "Lightroom"} <= set(ents)
    assert unverified_entities(text, "주제: 증도 천문대 EOS 6D 캐논 Adobe Lightroom") == []  # 주제·증거에 있으면 아는 이름
    assert unverified_entities("인근 천문대와 ISO 3200, E1 증거", "") == []  # 일반 표현은 제외
    v = verify_claim("증도 천문대 근처가 촬영에 좋다", "fact", [1], {1: {"tool": "t", "status": "ok", "summary": "x", "flags": []}}, "", [])
    assert v["status"] == "unverified" or v["type"] == "interpretation"
    assert any("증도 천문대" in n for n in v["notes"])


def test_idea_with_unverified_name_cannot_be_accepted(client, provider):
    provider.overrides["debate_synthesis"] = {
        "summary": "요약", "decision": "adopt", "importance": 9,
        "ideas": [{"title": "증도 천문대 근처 촬영", "description": "증도 천문대 근처가 촬영에 좋다", "status": "accepted",
                   "rationale": "추천됨", "evidence_ids": [], "confidence": 0.8}]}
    d = run_and_wait(client, "은하수 사진 촬영 장소 후보를 정리하는 아이디어")  # 사실 확인 불필요 주제: 증거 요건은 없지만 이름 검증은 적용
    idea = d["ideas"][0]
    assert idea["status"] == "needs_research" and "존재가 확인되지 않은 이름" in idea["rationale"]
    assert "존재 미확인: 증도 천문대" in idea["description"]
    assert any("증도 천문대" in q for q in d["result"]["open_questions"])
    assert d["result"]["status"] == "needs_research"


# ---------- 5·6. Critic 반박 검증과 타당한 주장 보존 ----------


def _ledger():
    led = Ledger("은하수 촬영", needs_facts=True)
    led.add_evidence(1, "weather.forecast", '{"max_precip_prob_pct": 61}', "ok", evidence_flags("weather.forecast", {"date": "2026-10-18", "max_precip_prob_pct": 61}))
    led.add_message(1, "idea", "10월 18일 저녁에 임진각에서 촬영하자고 제안합니다. 삼각대와 광각 렌즈가 필요합니다.")
    led.add_claims("idea", 1, [{"text": "10월 18일 강수확률은 61%이다", "type": "fact", "evidence_ids": [1]}])
    return led


GOOD = {"kind": "missing_condition", "target": "임진각에서 촬영하자고 제안합니다", "detail": "일몰 시각과 달 위치 조건이 빠져 있어 촬영 가능 시간을 알 수 없습니다.",
        "suggestion": "일몰과 월몰 시각을 확인해 촬영 가능 시간대를 명시하세요."}


@pytest.mark.parametrize("patch,expected", [
    ({"detail": "검증할 수 없는 일반화입니다."}, "detail이 너무 짧"),
    ({"detail": "이 주장은 검증할 수 없는 일반화이며 사람마다 다를 수 있다고 봅니다 정말로"}, "일반론적 반박"),
    ({"target": "전혀 다른 문장입니다 존재하지 않음"}, "target이 앞선 발언"),
    ({"suggestion": ""}, "suggestion"),
    ({"kind": "wrong"}, "kind는"),
    ({"kind": "evidence_conflict"}, "evidence_ids"),
])
def test_empty_or_generic_rebuttals_are_rejected(patch, expected):
    led = _ledger()
    valid, rejected = led.validate_rebuttals([{**GOOD, **patch}], 1)
    assert valid == [] and expected in rejected[0]["reason"]


def test_specific_rebuttal_is_accepted_and_repeats_are_rejected():
    led = _ledger()
    valid, _ = led.validate_rebuttals([GOOD], 1)
    assert [r.id for r in valid] == [1]
    again, rejected = led.validate_rebuttals([{**GOOD, "detail": GOOD["detail"] + " 그래서"}], 2)
    assert again == [] and "중복" in rejected[0]["reason"]


def test_rebutting_an_evidence_backed_fact_without_evidence_is_rejected():
    led = _ledger()
    bad = {"kind": "counterexample", "target": "10월 18일 강수확률은 61%이다", "detail": "다른 지역에서는 강수확률이 다르게 나타나는 사례가 존재합니다 반드시",
           "suggestion": "다른 지역 예보를 비교해서 확인해 보세요."}
    valid, rejected = led.validate_rebuttals([bad], 1)
    assert valid == [] and "검증된 사실" in rejected[0]["reason"]
    ok, _ = led.validate_rebuttals([{**bad, "kind": "evidence_conflict", "evidence_ids": [1]}], 1)
    assert len(ok) == 1  # 증거를 인용하면 검증된 사실도 반박할 수 있다


def test_empty_critic_turns_are_rejected_retried_within_limit_and_not_recorded(client, provider):
    provider.overrides["debate_turn:critic"] = {"message": "반박합니다.", "rebuttals": [], "resolved": False}
    client.app.state.svc.settings.debate_max_rounds = 2
    d = run_and_wait(client, "은하수 사진 구도를 개선하는 아이디어")
    assert all(m["agent_id"] != "critic" for m in d["messages"])  # 내용 없는 반박은 기록되지 않는다
    critic_calls = provider.calls.count("debate_turn:critic")
    assert critic_calls <= 2 + client.app.state.svc.settings.debate_critic_retries  # 재시도는 상한 이내
    assert critic_calls > 2  # 거부 후 재작성은 실제로 시도했다
    assert any(l["event"] == "critic.rejected" for l in client.get("/api/logs", params={"limit": 200}).json())


def test_valid_findings_are_preserved_even_if_an_agent_drops_them(client, provider):
    d = run_and_wait(client, "이번 주말 은하수 촬영 계획을 돕는 기능은 무엇이어야 할까?")  # 기본 가짜: Idea는 검증된 주장을 언급하지 않는다
    assert any(l["event"] == "preserved.dropped" for l in client.get("/api/logs", params={"limit": 200}).json())
    assert d["progress"][1]["regressions"] >= 1  # 2라운드에서 누락 감지
    assert [f["text"] for f in d["result"]["verified_facts"]] == ["달은 밝다"]  # 그래도 최종 결과에는 보존
    idea_r2 = [m for p, m in provider.prompts if p == "debate_turn:idea"][-1][-1]["content"]
    assert "[보존해야 할 검증 내용]\n- (verified) 달은 밝다" in idea_r2  # 다음 발언자에게 보존 대상으로 전달


# ---------- 7. 반복 반박 -> 정체 종료 ----------


def test_repeated_rebuttal_ends_debate_as_stagnation(client, provider):
    same = {"message": "다시 반박합니다.", "resolved": False, "endorsements": [], "rebuttals": [{
        "kind": "missing_condition", "target": "idea 의견", "detail": "관측 시각과 위치 조건이 빠져 있어 결과를 그대로 적용할 수 없습니다.",
        "suggestion": "관측 시각과 위치 조건을 명시해 다시 제시하세요."}]}
    provider.overrides["debate_turn:critic"] = same
    client.app.state.svc.settings.debate_max_rounds = 6
    d = run_and_wait(client, "은하수 사진 구도를 개선하는 아이디어")
    assert d["stop_reason"] == "stagnation" and d["rounds_done"] == 3  # 6라운드까지 끌지 않고 3라운드에 종료
    last = d["progress"][-1]["stop"]
    assert "중복" in last["detail"]
    assert d["progress"][-2]["duplicate_rebuttals"] >= 1


def test_needs_research_ending_when_facts_stay_unverified(client, provider):
    provider.overrides["debate_turn:research"] = {"message": "조사했지만 근거가 없습니다.", "claims": [{"text": "달은 밝다", "type": "fact", "evidence_ids": []}]}
    provider.overrides["debate_turn:critic"] = lambda m: {"message": "x", "resolved": False, "endorsements": [], "rebuttals": [{
        "kind": "missing_condition", "target": "조사했지만 근거가 없습니다", "detail": f"{round_of(m)}라운드 기준 근거가 되는 자료가 하나도 인용되지 않았습니다.",
        "suggestion": "도구로 확인한 증거를 인용하세요."}] if round_of(m) == 1 else []}
    client.app.state.svc.settings.debate_max_rounds = 5
    d = run_and_wait(client, "이번 주말 은하수 촬영 날씨는?")
    assert d["stop_reason"] == "needs_research" and d["rounds_done"] < 5
    assert d["result"]["status"] != "accepted"


def test_agreement_alone_is_not_consensus_without_verified_facts(client, provider):
    provider.overrides["debate_turn:research"] = {"message": "조사했지만 근거가 없습니다.", "claims": [{"text": "달은 밝다", "type": "fact", "evidence_ids": []}]}
    d = run_and_wait(client, "이번 주말 은하수 촬영 날씨는?")  # 기본 가짜 Critic은 2라운드에 resolved
    assert d["stop_reason"] != "consensus"
    assert any(l["event"] == "consensus.ignored" for l in client.get("/api/logs", params={"limit": 200}).json())


# ---------- 8. 폐기 아이디어 차단 ----------


def _three_ideas():
    base = {"feasibility": "medium", "confidence": 0.6, "risks": [], "next_steps": []}
    return {"summary": "요약", "decision": "adopt", "importance": 9, "ideas": [
        {**base, "title": "채택된 아이디어", "description": "삼각대로 고정해 촬영", "status": "accepted", "rationale": "검토 완료", "evidence_ids": [1]},
        {**base, "title": "추가조사 아이디어", "description": "새 방법 시도", "status": "needs_research", "rationale": "근거 필요"},
        {**base, "title": "폐기된 아이디어", "description": "비현실적 방법", "status": "discarded", "rationale": "증거와 충돌"}]}


def test_discarded_ideas_are_kept_for_audit_but_never_recommended(client, provider):
    provider.overrides["debate_synthesis"] = _three_ideas()
    d = run_and_wait(client, "이번 주말 은하수 촬영 계획을 돕는 기능은 무엇이어야 할까?")
    assert {i["status"] for i in d["ideas"]} == {"accepted", "needs_research", "discarded"}  # 감사 기록은 유지
    active = [i["title"] for i in client.get("/api/ideas").json()]
    assert "폐기된 아이디어" not in active and {"채택된 아이디어", "추가조사 아이디어"} <= set(active)
    assert [i["title"] for i in client.get("/api/ideas", params={"status": "discarded"}).json()] == ["폐기된 아이디어"]

    client.app.state.svc.settings.proactive_cooldown_minutes = 0
    asyncio.run(client.app.state.svc.proactive.deliver_debates()) if False else client.portal.call(client.app.state.svc.proactive.deliver_debates)
    msgs = [m for c in client.get("/api/conversations").json() for m in client.get(f"/api/conversations/{c['id']}/messages").json()]
    delivered = [m["content"] for m in msgs if m["proactive"]]
    assert delivered and all("폐기된 아이디어" not in t for t in delivered)

    client.post("/api/chat", json={"message": "안녕"})
    system = provider.last_chat_system
    assert "채택된 아이디어" in system and "폐기된 아이디어" not in system
    assert "추가 조사 필요(추천하지 말 것) ['추가조사 아이디어']" in system


def test_important_but_unverified_result_is_not_delivered(client, provider):
    d = _three_ideas()
    d["ideas"] = d["ideas"][1:]  # 채택된 아이디어 없음
    provider.overrides["debate_synthesis"] = d
    deb = run_and_wait(client, "이번 주말 은하수 촬영 계획을 돕는 기능은 무엇이어야 할까?")
    assert deb["result"]["status"] == "needs_research" and deb["importance"] <= 4  # LLM이 9를 줘도 낮춘다
    client.app.state.svc.settings.importance_threshold = 0
    client.portal.call(client.app.state.svc.proactive.deliver_debates)
    assert not any(m["proactive"] for c in client.get("/api/conversations").json() for m in client.get(f"/api/conversations/{c['id']}/messages").json())


def test_delivery_carries_warnings_and_drops_conflicting_text(client, provider):
    client.app.state.svc.tools.get("weather.forecast").handler = lambda args: _async(WEATHER_61)
    provider.overrides["debate_turn:research"] = {"message": "예보 요청", "claims": [], "tool_requests": [{"tool": "weather.forecast", "args": {}}]}
    provider.overrides["debate_synthesis"] = {**_three_ideas(), "summary": "삼각대 사용을 권장합니다.", "ideas": [
        {"title": "삼각대 촬영", "description": "삼각대로 고정해 장노출 촬영", "status": "accepted", "rationale": "검토 완료", "evidence_ids": [1],
         "feasibility": "high", "confidence": 0.8, "risks": [], "next_steps": []}]}
    provider.overrides["debate_delivery"] = "삼각대 촬영을 추천해요. 10월 18일은 비 올 확률이 낮아 날씨도 좋아요."  # 증거(61%)와 충돌
    run_and_wait(client, "이번 주말 은하수 출사 준비를 어떻게 할까?")
    client.portal.call(client.app.state.svc.proactive.deliver_debates)
    text = next(m["content"] for c in client.get("/api/conversations").json()
                for m in client.get(f"/api/conversations/{c['id']}/messages").json() if m["proactive"])
    assert "비 올 확률이 낮아" not in text  # 충돌하는 문장은 폐기하고
    assert "61%" in text and "삼각대 촬영" in text  # 경고를 포함한 결정적 문구로 대체한다


# ---------- 9. 도구 오류·경고의 전달 ----------


def test_tool_failure_and_warnings_reach_synthesis(client, provider):
    async def failing(args):
        raise ToolError("upstream 503", kind="http_503", attempts=3)

    client.app.state.svc.tools.get("weather.forecast").handler = failing
    provider.overrides["debate_turn:research"] = {"message": "예보 요청", "claims": [], "tool_requests": [
        {"tool": "weather.forecast", "args": {}}, {"tool": "astro.moon_phase", "args": {}}]}
    d = run_and_wait(client, "이번 주말 은하수 출사 날씨 조건은 어떨까?")
    by_tool = {e["tool"]: e for e in d["evidence"]}
    assert by_tool["weather.forecast"]["status"] == "error" and by_tool["weather.forecast"]["flags"][0]["code"] == "tool_failed"
    idea_prompt = [m for p, m in provider.prompts if p == "debate_turn:idea"][0][-1]["content"]
    assert "✖실패" in idea_prompt and "조회 실패(http_503)" in idea_prompt  # 다음 발언자에게 실패가 보인다
    synth = [m for p, m in provider.prompts if p == "debate_synthesis"][0][-1]["content"]
    assert "[증거 경고]" in synth and "weather.forecast 조회 실패(http_503)" in synth  # 종합 단계까지 전달
    assert any("조회 실패" in w for w in d["result"]["warnings"])  # 최종 결과에도 남는다


# ---------- 10. 토큰·예산 상한 ----------


def test_token_budget_includes_critic_retries_and_is_respected(client, provider):
    provider.overrides["debate_turn:critic"] = {"message": "x", "rebuttals": [], "resolved": False}
    client.app.state.svc.settings.debate_max_tokens = 5000 + 450
    d = run_and_wait(client, "은하수 사진 구도를 개선하는 아이디어")
    assert d["stop_reason"] == "token_budget" and d["tokens_used"] <= 5450 + 150
    usage = client.get("/api/health").json()
    assert usage["spent_today_usd"] >= 0


def test_daily_budget_stops_autonomous_debate(settings, provider):
    settings.daily_budget_usd = 0.0001  # 가짜 호출 1건 = 0.000045
    svc = build_services(settings, provider)
    svc.db.create_all()
    svc.orchestrator.register_agents()

    async def go():
        svc.orchestrator.start(trigger="schedule")
        await svc.orchestrator.wait()

    asyncio.run(go())
    from gyunexus.models import Debate

    with svc.db.session() as s:
        d = s.query(Debate).one()
        assert d.status == "completed" and d.stop_reason == "daily_budget"
        assert d.result["summary"].startswith("일일 예산 소진")  # 종합도 예산 때문에 생략되지만 기록은 남는다


# ---------- P2. 주제 발굴 ----------


def test_focus_rotates_across_memories_instead_of_sticking_to_one(settings, provider):
    svc = build_services(settings, provider)
    svc.db.create_all()
    svc.orchestrator.register_agents()
    for text, imp in [("사용자는 은하수 촬영을 즐긴다", 9), ("사용자는 로봇 청소기 자동화에 관심이 있다", 7), ("사용자는 재즈 음악 감상을 좋아한다", 5)]:
        svc.memory.add("interest", text, imp, source="manual")
    focuses = []

    def propose(messages):
        focus = re.search(r"\[이번에 중심으로 삼을 기억\]\n- (.+)", messages[-1]["content"]).group(1)
        focuses.append(focus)
        return {"title": f"{focus} 관련해서 새 질문 {len(focuses)}", "rationale": "테스트"}

    provider.overrides["topic_discovery"] = propose

    async def go():
        for _ in range(3):
            await svc.orchestrator.discover_topic("test")

    asyncio.run(go())
    assert len(set(focuses)) == 3  # 같은 관심사에 쏠리지 않고 한 번씩 다룬다


def test_semantic_duplicate_check_costs_one_call_only_when_a_neighbor_exists(settings, provider):
    svc = build_services(settings, provider)
    svc.db.create_all()
    svc.memory.add("interest", "사용자는 은하수 촬영을 즐긴다", 9, source="manual")
    first = svc.orchestrator.enqueue_topic("이번 주말의 천체 촬영을 위한 최적의 장소는 어디일까요?", source="manual")
    titles = iter(["은하수 찍기 좋은 이번 주말 촬영 지점을 추천해줘",  # 표현만 다른 같은 질문(문자 유사도 0.2: 규칙으로는 못 잡고 LLM 판정 대상)
                   "재즈 피아노 연습 루틴을 어떻게 짤까"])  # 완전히 다른 질문(문자 유사도 0 -> LLM 호출 없음)
    provider.overrides["topic_discovery"] = lambda m: {"title": next(titles), "rationale": "t"}
    provider.dedupe_response = first

    async def go():
        return await svc.orchestrator.discover_topic("test")

    topic_id = asyncio.run(go())
    assert provider.calls.count("topic_discovery") == 2  # 첫 후보는 의미 중복으로 거절되어 한 번 더 제안받음
    assert provider.calls.count("topic_dedupe") == 1  # 이웃이 있던 첫 후보에 대해서만 LLM 판정(두 번째는 유사 주제 없음 -> 호출 없음)
    from gyunexus.models import Topic

    with svc.db.session() as s:
        assert s.get(Topic, topic_id).title.startswith("재즈")


# ---------- 기존 DB 호환 ----------


def test_startup_adds_new_columns_to_an_old_database(settings):
    path = settings.data_dir / "gyunexus.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE evidence (id INTEGER PRIMARY KEY, debate_id INTEGER, tool VARCHAR(80), args JSON, source VARCHAR(500), summary TEXT, created_at DATETIME)")
    con.execute("CREATE TABLE ideas (id INTEGER PRIMARY KEY, debate_id INTEGER, title VARCHAR(300), description TEXT, feasibility VARCHAR(10), risks JSON, next_steps JSON, confidence FLOAT, created_at DATETIME)")
    con.execute("INSERT INTO ideas (debate_id, title, description) VALUES (1, '이전 아이디어', '설명')")
    con.commit()
    con.close()
    svc = build_services(settings)
    svc.db.create_all()  # 새 컬럼 추가
    cols = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(ideas)")}
    assert {"status", "rationale", "evidence_ids"} <= cols
    assert {"status", "flags"} <= {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(evidence)")}
