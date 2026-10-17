from conftest import wait_for


def run_and_wait(client, topic=None):
    r = client.post("/api/debates/run", json={"topic": topic} if topic else {})
    assert r.status_code == 202
    return wait_for(lambda: next((d for d in client.get("/api/debates").json() if d["status"] != "running"), None), 10)


def test_four_agents_registered(client):
    agents = client.get("/api/agents").json()
    assert {a["id"] for a in agents} == {"research", "idea", "developer", "critic"}
    assert all(a["status"] == "idle" for a in agents)
    assert all("system_prompt" not in a for a in agents)


def test_debate_runs_to_consensus_and_stores_structured_result(client):
    debate = run_and_wait(client, "이번 주말 은하수 촬영 계획을 돕는 기능은 무엇이어야 할까?")  # '이번 주말': 외부 사실 필요 -> Research 필수
    assert debate["status"] == "completed"
    assert debate["stop_reason"] == "consensus"  # 2라운드에서 Critic이 resolved
    assert debate["rounds_done"] == 2
    assert debate["participants"] == ["research", "idea", "critic"]  # Critic은 자동 추가, Developer는 불필요해서 제외
    assert debate["importance"] == 8

    detail = client.get(f"/api/debates/{debate['id']}").json()
    order = [(m["round"], m["agent_id"]) for m in detail["messages"]]
    assert order == [(1, "research"), (1, "idea"), (1, "critic"), (2, "research"), (2, "idea"), (2, "critic")]

    # 1라운드는 없는 증거 #99를 인용 -> unverified, 2라운드는 실제 증거 #1 인용 -> verified
    assert detail["messages"][0]["claims"][0]["status"] == "unverified"
    assert detail["messages"][3]["claims"][0]["status"] == "verified"
    assert len(detail["evidence"]) == 2  # Research 발언마다 달 위상을 조회, notes.write 요청은 무시됨

    result = detail["result"]
    assert [f["evidence_ids"] for f in result["verified_facts"]] == [[1]]
    assert "조작된 근거" in result["unverified_claims"]  # 존재하지 않는 증거 id는 미검증으로 강등
    assert detail["ideas"][0]["title"] == "아이디어 A"
    assert detail["tokens_used"] > 0 and detail["cost_usd"] > 0

    agents = client.get("/api/agents").json()
    assert all(a["status"] == "idle" for a in agents)
    assert any(l["event"] == "debate.completed" for l in client.get("/api/logs").json())


def test_dangerous_actions_wait_for_approval(client, settings):
    run_and_wait(client, "결과를 파일로 남겨야 할까?")
    pending = client.get("/api/approvals").json()
    assert [a["tool"] for a in pending] == ["notes.write"]  # 읽기 전용 제안은 승인 큐에 들어가지 않는다
    assert pending[0]["status"] == "pending"
    assert not (settings.notes_dir / "result.md").exists()

    done = client.post(f"/api/approvals/{pending[0]['id']}/approve").json()
    assert done["status"] == "executed"
    assert (settings.notes_dir / "result.md").read_text(encoding="utf-8") == "# 결과"
    assert client.post(f"/api/approvals/{pending[0]['id']}/approve").status_code == 409


def test_rejected_approval_does_not_execute(client, settings):
    run_and_wait(client, "결과를 파일로 남겨야 할까?")
    a = client.get("/api/approvals").json()[0]
    assert client.post(f"/api/approvals/{a['id']}/reject").json()["status"] == "rejected"
    assert not (settings.notes_dir / "result.md").exists()


def test_duplicate_topics_are_rejected(client):
    run_and_wait(client, "은하수 촬영 계획을 돕는 기능은 무엇이어야 할까?")
    r = client.post("/api/debates/run", json={"topic": "은하수 촬영 계획을 돕는 기능은 무엇이어야 할까"})
    assert r.status_code == 409


def test_discovery_picks_a_topic_when_none_given(client):
    debate = run_and_wait(client)
    assert debate["trigger"] == "manual"
    topics = client.get("/api/topics").json()
    assert topics[0]["source"] == "discovery" and topics[0]["status"] == "done"


def test_token_budget_stops_debate_early(settings, provider):
    from fastapi.testclient import TestClient

    from gyunexus.main import create_app

    settings.debate_max_tokens = 5000 + 200  # 종합 예비분을 빼면 두 번 발언할 여유뿐
    with TestClient(create_app(settings, provider, run_scheduler=False)) as c:
        c.post("/api/debates/run", json={"topic": "예산이 적은 토론은 어떻게 끝나야 할까?"})
        d = wait_for(lambda: next((d for d in c.get("/api/debates").json() if d["status"] != "running"), None), 10)
    assert d["status"] == "completed"
    assert d["stop_reason"] == "token_budget"


def test_deliver_important_debate_to_user(client, provider):
    run_and_wait(client, "결과를 사용자에게 알려야 할까?")
    svc = client.app_state
    import asyncio

    client.portal.call(svc.proactive.deliver_debates) if hasattr(client, "portal") else asyncio.run(svc.proactive.deliver_debates())
    conv = client.get("/api/conversations").json()
    msgs = client.get(f"/api/conversations/{conv[0]['id']}/messages").json()
    assert msgs[-1]["proactive"] and msgs[-1]["meta"]["kind"] == "debate"
    assert client.get("/api/debates").json()[0]["delivered_at"]


def test_scheduler_starts_due_debate_and_respects_toggle_and_budget(settings, provider):
    import asyncio
    from datetime import timedelta

    from gyunexus.main import build_services
    from gyunexus.models import utcnow

    svc = build_services(settings, provider)
    svc.db.create_all()
    svc.orchestrator.register_agents()

    async def scenario():
        await svc.scheduler.tick()  # 아직 주기가 지나지 않아 시작 안 함
        assert not svc.orchestrator.busy
        svc.scheduler._started = svc.scheduler._last_attempt = utcnow() - timedelta(hours=4)
        svc.settings.daily_budget_usd = 0.0
        await svc.scheduler.tick()  # 주기는 됐지만 자율 예산이 소진되어 시작 안 함
        assert not svc.orchestrator.busy
        svc.settings.daily_budget_usd = 1.0
        await svc.scheduler.tick()
        assert svc.orchestrator.busy
        await svc.orchestrator.wait()

    asyncio.run(scenario())
    with svc.db.session() as s:
        from gyunexus.models import Debate

        assert s.query(Debate).one().trigger == "schedule"
