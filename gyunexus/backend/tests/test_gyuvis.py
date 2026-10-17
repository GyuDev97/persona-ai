from conftest import wait_for


def test_chat_persists_history_and_learns_memory(client, provider):
    r = client.post("/api/chat", json={"message": "나는 주말마다 은하수 사진 찍으러 다녀"})
    assert r.status_code == 200
    body = r.json()
    assert body["reply"]["content"].startswith("안녕하세요")

    msgs = client.get(f"/api/conversations/{body['conversation_id']}/messages").json()
    assert [m["role"] for m in msgs] == ["user", "assistant"]

    mems = wait_for(lambda: client.get("/api/memories").json())
    assert "은하수" in mems[0]["content"]

    # 새로 학습한 관심사는 에이전트용 이벤트 주제를 만든다
    topics = wait_for(lambda: client.get("/api/topics").json())
    assert topics[0]["source"] == "event"

    # 같은 사실이 또 나오면 중복 저장 대신 기존 기억을 강화한다
    client.post("/api/chat", json={"message": "나는 주말마다 은하수 사진 찍으러 다녀", "conversation_id": body["conversation_id"]})
    wait_for(lambda: provider.calls.count("memory_extract") == 2)
    assert len(client.get("/api/memories").json()) == 1


def test_sky_question_without_location_does_not_invent_weather(client, provider):
    client.post("/api/memories", json={"kind": "interest", "content": "사용자는 은하수 촬영을 즐긴다", "importance": 9})
    body = client.post("/api/chat", json={"message": "오늘 은하수 어때?"}).json()
    trace = body["reply"]["meta"]["trace"]

    assert trace["llm"]["called"] is True and trace["llm"]["tokens"] > 0
    assert [m["content"] for m in trace["memories"]] == ["사용자는 은하수 촬영을 즐긴다"]
    tools = {t["name"]: t for t in trace["tools"]}
    assert tools["astro.moon_phase"]["status"] == "ok"
    assert tools["weather.forecast"]["status"] == "skipped"  # 위치 미설정이라 호출하지 않음
    assert any("GYUNEXUS_LATITUDE" in d for d in trace["missing_data"])

    # LLM에는 실제 조회한 값과 '조회하지 못한 데이터' 안내가 전달된다
    system = provider.last_chat_system
    assert "[조회한 사실] (이번 질문" in system and "illumination_pct" in system
    assert "[조회하지 못한 데이터]\n" in system and "추측하거나" in system
    facts_section = system.split("[조회한 사실] (이번 질문")[1].split("[조회하지 못한 데이터]\n")[0]
    assert "weather" not in facts_section and "cloud" not in facts_section  # 날씨 값이 지어지지 않았다

    logs = client.get("/api/logs").json()
    assert any(l["event"] == "chat.trace" and "weather.forecast:skipped" in l["detail"]["tools"] for l in logs)


def test_sky_question_with_location_passes_weather_facts(client, provider):
    async def fake_weather(_):
        return {"nights_22_to_03": [{"date": "2026-10-17", "avg_cloud_cover_pct": 12}], "source": "test"}

    client.app_state.settings.latitude, client.app_state.settings.longitude = 37.5, 127.0
    client.app_state.tools.get("weather.forecast").handler = fake_weather
    trace = client.post("/api/chat", json={"message": "오늘 은하수 어때?"}).json()["reply"]["meta"]["trace"]

    assert {t["name"]: t["status"] for t in trace["tools"]} == {"astro.moon_phase": "ok", "weather.forecast": "ok"}
    assert all("날씨 예보" not in d for d in trace["missing_data"])
    assert "avg_cloud_cover_pct" in provider.last_chat_system


def test_plain_question_calls_no_tools(client, provider):
    trace = client.post("/api/chat", json={"message": "안녕, 자기소개 해줘"}).json()["reply"]["meta"]["trace"]
    assert trace["tools"] == [] and trace["sky_intent"] is False
    assert "[조회한 사실] (이번 질문" not in provider.last_chat_system  # 사실 섹션 자체가 붙지 않는다


def test_chat_without_llm_returns_503(settings):
    from fastapi.testclient import TestClient

    from gyunexus.main import create_app

    with TestClient(create_app(settings, None, run_scheduler=False)) as c:
        assert c.get("/api/health").json()["llm_configured"] is False
        assert c.post("/api/chat", json={"message": "hi"}).status_code == 503
        assert c.get("/api/conversations").json() == []


def test_unknown_conversation_404(client):
    assert client.post("/api/chat", json={"message": "hi", "conversation_id": 999}).status_code == 404


def test_proactive_suggestion_requires_presence_and_respects_cooldown(client, provider):
    client.post("/api/memories", json={"kind": "interest", "content": "사용자는 은하수 촬영을 즐긴다", "importance": 9})

    assert client.post("/api/proactive/check").json()["suggested"] is False  # 아직 사용자가 접속하지 않음
    assert "proactive" not in provider.calls

    # 사용자가 PC 앞에 앉으면 제안이 스스로 시작된다
    assert client.post("/api/context/activity").json()["returned"] is True
    conv = wait_for(lambda: client.get("/api/conversations").json())[0]
    msgs = client.get(f"/api/conversations/{conv['id']}/messages").json()
    assert msgs[-1]["proactive"] is True and msgs[-1]["meta"]["trigger"] == "user_returned"
    assert "moon" in msgs[-1]["meta"]["facts"]

    assert client.post("/api/context/activity").json()["returned"] is False  # 같은 세션
    assert client.post("/api/proactive/check").json()["suggested"] is False  # 쿨다운
    assert provider.calls.count("proactive") == 1


def test_proactive_declines_when_model_says_no(client, provider):
    provider.proactive_speak = False
    client.post("/api/memories", json={"kind": "interest", "content": "사용자는 은하수 촬영을 즐긴다"})
    client.post("/api/context/activity")
    assert client.post("/api/proactive/check").json()["suggested"] is False
