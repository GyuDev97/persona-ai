"""통합 자율 실행 테스트(요청형 자동 실행 + 상시 자율 운영).

임시 DB 와 FakeProvider 만 쓴다. 실제 LLM·외부 서비스·사용자 DB 에는 어떤 요청도 가지 않는다.
Worker 실행 엔진·워크플로 엔진은 실제 코드를 그대로 쓴다(이 테스트는 그 위의 정책 계층을 검증한다).
"""

import asyncio
from datetime import timedelta

from conftest import wait_for
from fastapi.testclient import TestClient
from sqlalchemy import select

from gyunexus.llm import LLMError
from gyunexus.main import create_app
from gyunexus.models import Approval, AutonomyRun, Message, Workflow, WorkerRun, utcnow
from test_workers import good_draft
from test_workflows import approve_pending, by_key, create, mk, plan_json, setup_llm, step, wait_wf, wf_get

GOAL = "개발 기록을 조사하고 글로 정리해 줘"


class Clock:
    """자율 운영 서비스의 시계. 테스트가 시간을 앞으로 돌린다."""

    def __init__(self):
        self.t = utcnow()

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


def svc(c):
    return c.app.state.svc


def run(c, coro_fn, *a):
    return c.portal.call(coro_fn, *a)


def enable(c, **kw):
    r = c.put("/api/autonomy/settings", json={"enabled": True, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def trig(c, **kw):
    body = {"name": "정기 점검", "kind": "interval", "goal": GOAL, "config": {"minutes": 5}, "exec_mode": "supervised", "budget_usd": 0.3,
            "cooldown_minutes": 0, "daily_cost_cap_usd": 0.5, "max_retries": 1} | kw
    r = c.post("/api/autonomy/triggers", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def runs(c):
    return c.get("/api/autonomy/runs").json()


def wf_ids(c):
    return [w["id"] for w in c.get("/api/workflows").json()]


def chat(c, text, **kw):
    r = c.post("/api/chat", json={"message": text, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def conv_messages(c, cid):
    return c.get(f"/api/conversations/{cid}/messages").json()


def prep(client, provider, *, approval=False, n=1, wkw=None, tools=()):
    setup_llm(provider)
    ws = [mk(client, f"직원{i}", approval=approval, materials=i == 0, wkw=wkw, tools=tools) for i in range(n)]
    return ws


# ---------------------------------------------------------------- 1. 요청형 자동 실행 전체 흐름 + 4. Artifact 전달·해시 + 3. 순차 실행

def test_request_flow_chat_delegate_autonomous_runs_to_the_end_and_reports_in_chat(client, provider):
    setup_llm(provider)
    a = mk(client, "조사 직원")  # 승인 필요 업무
    b = mk(client, "작성 직원", materials=False)
    enable(client, max_mode="autonomous")
    provider.overrides["workflow_plan"] = plan_json([step("research", *a), step("write", *b, ["research"])])
    out = chat(client, GOAL, delegate=True, mode="autonomous")
    cid = out["conversation_id"]
    reply = out["reply"]
    assert reply["meta"]["kind"] == "workflow" and "자동 실행을 시작했습니다" in reply["content"] and "조사 직원" in reply["content"]
    wid = reply["meta"]["workflow_id"]
    done = wait_wf(client, wid, lambda w: w["status"] == "completed")
    assert done["exec_mode"] == "autonomous" and done["origin"] == "chat" and done["autonomy"]["auto_started"] is True
    # 승인 게이트는 우회되지 않고 같은 경로로 처리되며, 누가 결정했는지 남는다
    aps = [x for x in client.get("/api/approvals").json() if x["tool"] == "worker.finalize"]
    assert len(aps) == 2 and all(x["status"] == "executed" and x["decided_by"] == "autonomy:policy" for x in aps)
    # Artifact 고정 참조(ID+버전+해시)로 후속 직원에게 전달됐다
    s = by_key(done)
    run_b = client.get(f"/api/workers/runs/{s['write']['run_id']}").json()
    ref = run_b["inputs"][0]
    assert ref["artifact_id"] == s["research"]["artifact"]["id"] and ref["sha256"] == s["research"]["artifact"]["sha256"] and ref["version"] == 1
    assert s["research"]["artifact"]["verified"] and s["write"]["artifact"]["verified"]
    # 결과가 GYUVIS 대화에 표시된다(검증 상태와 해시 앞부분 포함)
    msgs = wait_for(lambda: [m for m in conv_messages(client, cid) if m["meta"].get("state") == "completed"])
    assert len(msgs) == 1 and "최종 결과물" in msgs[0]["content"] and "검증됨" in msgs[0]["content"] and s["write"]["artifact"]["sha256"][:8] in msgs[0]["content"]
    # 대화에서 진행 상황을 DB 사실로 물어볼 수 있다(LLM 호출 없음)
    before = provider.calls.count("chat")
    st = chat(client, "/상태", conversation_id=cid)
    assert "2/2단계 완료" in st["reply"]["content"] and provider.calls.count("chat") == before


def test_supervised_starts_automatically_but_keeps_the_approval_gate(client, provider):
    setup_llm(provider)
    a = mk(client, "조사 직원")
    b = mk(client, "작성 직원", materials=False)
    provider.overrides["workflow_plan"] = plan_json([step("research", *a), step("write", *b, ["research"])])
    out = chat(client, GOAL, delegate=True, mode="supervised")
    wid = out["reply"]["meta"]["workflow_id"]
    mid = wait_wf(client, wid, lambda w: by_key(w)["research"]["status"] == "awaiting_approval")
    assert mid["status"] == "running" and by_key(mid)["write"]["status"] == "pending"
    # 자동 승인하지 않는다: 승인 대기가 유지되고 사유가 설명된다
    ap = [x for x in client.get("/api/approvals").json() if x["status"] == "pending"]
    assert len(ap) == 1 and ap[0]["decided_by"] is None
    assert any("자동 승인하지 않습니다" in t for t in mid["autonomy"]["attention"])
    msg = wait_for(lambda: [m for m in conv_messages(client, out["conversation_id"]) if m["meta"].get("state") == "approval"])
    assert "승인을 기다립니다" in msg[0]["content"] and "supervised" in msg[0]["content"]
    approve_pending(client)  # 사용자가 기존 승인 경로로 승인
    wait_wf(client, wid, lambda w: by_key(w)["write"]["status"] == "awaiting_approval")
    approve_pending(client)
    wait_wf(client, wid, lambda w: w["status"] == "completed")
    assert all(x["decided_by"] is None for x in client.get("/api/approvals").json())


def test_default_policy_is_manual_and_existing_manual_flow_is_unchanged(client, provider):
    setup_llm(provider)
    a = mk(client, "직원", approval=False)
    wf = create(client, provider, [step("a", *a)])
    assert wf["exec_mode"] == "manual" and wf["origin"] == "user" and wf["status"] == "planned" and wf["autonomy"]["auto_started"] is False
    assert client.get("/api/workers/runs").json() == []  # 사용자가 시작하기 전에는 아무것도 실행하지 않는다
    assert client.post(f"/api/workflows/{wf['id']}/start").status_code == 200
    wait_wf(client, wf["id"], lambda w: w["status"] == "completed")
    # exec_mode 를 주지 않은 화면 요청도 manual: 기존 auto_run 의미는 그대로
    r = client.post("/api/workflows", json={"goal": "일반 수동 목표입니다", "exec_mode": "manual"})
    assert r.status_code == 201 and r.json()["status"] == "planned"


def test_delegate_with_unplannable_goal_reports_failure_without_running_anything(client, provider):
    setup_llm(provider)
    mk(client, "직원", approval=False)
    provider.overrides["workflow_plan"] = plan_json([], notes="카탈로그에 맞는 직원이 없습니다")
    out = chat(client, "달 탐사선을 만들어 줘", delegate=True, mode="supervised")
    assert "계획을 만들지 못했습니다" in out["reply"]["content"] and "아무것도 실행하지 않았습니다" in out["reply"]["content"]
    assert client.get("/api/workers/runs").json() == []


def test_requested_mode_cannot_exceed_allowed_scope(client, provider):
    setup_llm(provider)
    a = mk(client, "직원", approval=False)
    provider.overrides["workflow_plan"] = plan_json([step("a", *a)])
    assert client.get("/api/autonomy/settings").json()["max_mode"] == "supervised"
    r = client.post("/api/workflows", json={"goal": GOAL, "exec_mode": "autonomous"})
    assert r.status_code == 422 and "허용된 자동 실행 범위" in r.json()["detail"]
    out = chat(client, GOAL, delegate=True, mode="autonomous")
    assert "허용된 자동 실행 범위" in out["reply"]["content"] and client.get("/api/workers/runs").json() == []


# ---------------------------------------------------------------- 5. 승인이 필요한 작업의 자동 실행 차단

def test_write_capable_worker_is_never_auto_started_or_auto_approved(client, provider):
    setup_llm(provider)
    w = mk(client, "쓰기 직원", wkw={"permission_level": "write_with_approval"}, tools=["notes.write"])
    enable(client, max_mode="autonomous")
    provider.overrides["worker_plan"] = {"calls": []}  # 도구를 호출하지 않는 계획
    provider.overrides["workflow_plan"] = plan_json([step("w", *w)])
    out = chat(client, GOAL, delegate=True, mode="autonomous")
    wid = out["reply"]["meta"]["workflow_id"]
    d = wf_get(client, wid)
    assert d["status"] == "planned" and d["autonomy"]["auto_started"] is False
    assert any("쓰기 권한" in b for b in d["autonomy"]["decision"]["blockers"]) and any("notes.write" in b for b in d["autonomy"]["decision"]["blockers"])
    assert "시작하지 않았습니다" in out["reply"]["content"]
    assert client.get("/api/workers/runs").json() == [] and "worker_draft" not in provider.calls
    # 사용자가 직접 시작하면 기존 경로로 실행되지만, 그래도 자동 승인되지는 않는다
    assert client.post(f"/api/workflows/{wid}/start").status_code == 200
    mid = wait_wf(client, wid, lambda w: by_key(w)["w"]["status"] == "awaiting_approval")
    assert mid["status"] == "running"
    run(client, svc(client).autonomy.on_progress, wid)
    assert [x["status"] for x in client.get("/api/approvals").json() if x["tool"] == "worker.finalize"] == ["pending"]
    assert any("쓰기 권한" in t for t in wf_get(client, wid)["autonomy"]["attention"])


def test_verification_warnings_block_auto_approval(client, provider):
    setup_llm(provider)
    provider.overrides["worker_draft"] = lambda m: {**good_draft(), "missing": ["배포 일정 자료"]}  # 작성자가 자료 부족을 보고함
    a = mk(client, "조사 직원")
    enable(client, max_mode="autonomous")
    provider.overrides["workflow_plan"] = plan_json([step("r", *a)])
    out = chat(client, GOAL, delegate=True, mode="autonomous")
    wid = out["reply"]["meta"]["workflow_id"]
    mid = wait_wf(client, wid, lambda w: by_key(w)["r"]["status"] == "awaiting_approval")
    assert mid["status"] == "running" and any("검증 경고" in t for t in mid["autonomy"]["attention"])  # 자료 부족을 승인 성공으로 취급하지 않는다
    assert [x["status"] for x in client.get("/api/approvals").json()] == ["pending"]


def test_auto_approval_still_fails_when_the_artifact_was_tampered(client, provider, settings):
    setup_llm(provider)
    a = mk(client, "조사 직원")
    provider.overrides["workflow_plan"] = plan_json([step("r", *a)])
    enable(client, max_mode="autonomous")
    wid = chat(client, GOAL, delegate=True, mode="supervised")["reply"]["meta"]["workflow_id"]
    mid = wait_wf(client, wid, lambda w: by_key(w)["r"]["status"] == "awaiting_approval")
    art = by_key(mid)["r"]["artifact"]
    from gyunexus.models import WorkerArtifact
    with svc(client).db.session() as s:
        rel = s.get(WorkerArtifact, art["id"]).rel_path
    (settings.workspace_dir / rel).write_text("변조된 내용", encoding="utf-8")  # 승인 대기 중 결과물이 바뀜
    assert client.put(f"/api/autonomy/workflows/{wid}/mode", json={"exec_mode": "autonomous"}).status_code == 200
    d = wait_wf(client, wid, lambda w: w["status"] == "failed")
    assert by_key(d)["r"]["error_kind"] == "artifact_changed"  # 해시 불일치 -> 승인 실패(성공으로 처리되지 않는다)
    assert [x["status"] for x in client.get("/api/approvals").json()] == ["failed"]


# ---------------------------------------------------------------- 2. 예약 트리거 자동 시작 + 12. OFF 상태 차단

def test_scheduled_trigger_starts_workflow_automatically_with_reason(client, provider):
    a = prep(client, provider)[0]
    provider.overrides["workflow_plan"] = plan_json([step("a", *a)])
    clock = Clock()
    svc(client).autonomy.now = clock
    enable(client)
    t = trig(client)
    assert t["next_fire_at"] is not None
    run(client, svc(client).autonomy.tick)
    assert runs(client) == []  # 아직 예정 시각 전
    clock.advance(minutes=6)
    run(client, svc(client).autonomy.tick)
    rr = runs(client)
    assert len(rr) == 1 and rr[0]["status"] in ("starting", "started", "completed") and "예약 일정 도래" in rr[0]["reason"]
    wid = rr[0]["workflow_id"]
    done = wait_wf(client, wid, lambda w: w["status"] == "completed")
    assert done["origin"] == "schedule" and done["trigger_id"] == t["id"] and "5분 간격" in done["trigger_reason"] and done["exec_mode"] == "supervised"
    wait_for(lambda: runs(client)[0]["status"] == "completed")
    # 다음 일정은 앞으로 넘어갔고 같은 일정이 다시 실행되지 않는다
    run(client, svc(client).autonomy.tick)
    assert len(runs(client)) == 1 and client.get("/api/autonomy/triggers").json()[0]["next_fire_at"] > clock().isoformat()


def test_autonomy_off_blocks_every_automatic_start(client, provider):
    a = prep(client, provider)[0]
    provider.overrides["workflow_plan"] = plan_json([step("a", *a)])
    clock = Clock()
    svc(client).autonomy.now = clock
    assert client.get("/api/autonomy/settings").json()["enabled"] is False  # 기본값은 꺼짐
    ev = trig(client, name="이벤트", kind="event", config={"event": "my_event"})
    t = trig(client)
    clock.advance(minutes=6)
    run(client, svc(client).autonomy.tick)
    assert client.post("/api/autonomy/events", json={"name": "my_event"}).json()["results"][0]["code"] == "disabled"
    assert client.post(f"/api/autonomy/triggers/{t['id']}/fire").json()["code"] == "disabled"
    assert wf_ids(client) == [] and "workflow_plan" not in provider.calls  # 계획 생성 LLM 호출조차 하지 않는다
    assert {r["skip_reason"] for r in runs(client)} == {"disabled"} and all(r["slot_key"] is None for r in runs(client))
    assert ev["enabled"]


def test_turning_autonomy_off_pauses_running_trigger_workflows(client, provider):
    a = prep(client, provider, approval=True)[0]
    provider.overrides["workflow_plan"] = plan_json([step("a", *a)])
    enable(client)
    t = trig(client)
    r = client.post(f"/api/autonomy/triggers/{t['id']}/fire").json()
    assert r["status"] == "started"
    wid = r["workflow_id"]
    wait_wf(client, wid, lambda w: by_key(w)["a"]["status"] == "awaiting_approval")
    assert client.put("/api/autonomy/settings", json={"enabled": False}).json()["enabled"] is False
    d = wf_get(client, wid)
    assert d["status"] == "paused" and d["autonomy"]["decision"]["paused_by"] == "autonomy_off"
    assert any("꺼져" in x for x in d["autonomy"]["attention"])
    # 이미 끝난 기록은 유지되고, 재개는 사용자의 선택이다
    assert client.post(f"/api/workflows/{wid}/resume").status_code == 200


def test_trigger_mode_is_capped_to_the_allowed_scope_not_expanded(client, provider):
    a = prep(client, provider, approval=True)[0]
    provider.overrides["workflow_plan"] = plan_json([step("a", *a)])
    enable(client)  # max_mode = supervised
    t = trig(client, exec_mode="autonomous")
    r = client.post(f"/api/autonomy/triggers/{t['id']}/fire").json()
    d = wait_wf(client, r["workflow_id"], lambda w: by_key(w)["a"]["status"] == "awaiting_approval")
    assert d["exec_mode"] == "supervised"  # 트리거가 요청한 autonomous 는 허용 범위(supervised)로 낮춰진다
    assert [x["status"] for x in client.get("/api/approvals").json()] == ["pending"]


# ---------------------------------------------------------------- 3. 병렬·순차

def test_parallel_workers_fan_in_through_triggered_autonomous_run(client, provider):
    setup_llm(provider)
    state = {"active": 0, "max": 0}
    real = svc(client).llm.provider.complete

    async def slow(messages, *, json_mode, max_tokens, purpose):
        if purpose == "worker_draft":
            state["active"] += 1
            state["max"] = max(state["max"], state["active"])
            await asyncio.sleep(0.3)
            state["active"] -= 1
        return await real(messages, json_mode=json_mode, max_tokens=max_tokens, purpose=purpose)

    svc(client).llm.provider.complete = slow
    a, b = mk(client, "A", approval=False), mk(client, "B", approval=False)
    c3 = mk(client, "취합", approval=False, materials=False)
    provider.overrides["workflow_plan"] = plan_json([step("a", *a), step("b", *b), step("c", *c3, ["a", "b"])])
    enable(client, max_mode="autonomous")
    t = trig(client, exec_mode="autonomous")
    r = client.post(f"/api/autonomy/triggers/{t['id']}/fire").json()
    done = wait_wf(client, r["workflow_id"], lambda w: w["status"] == "completed")
    assert state["max"] >= 2  # 독립 직원은 동시에
    run_c = client.get(f"/api/workers/runs/{by_key(done)['c']['run_id']}").json()
    assert {x["artifact_id"] for x in run_c["inputs"]} == {by_key(done)["a"]["artifact"]["id"], by_key(done)["b"]["artifact"]["id"]}


# ---------------------------------------------------------------- 6. 예산

def test_budget_too_small_for_plan_is_reported_and_nothing_runs(client, provider):
    a = prep(client, provider)[0]
    provider.overrides["workflow_plan"] = plan_json([step("a", *a)])
    out = chat(client, GOAL, delegate=True, mode="supervised", budget_usd=0.01)  # 단계 상한(0.05)이 예산보다 크다
    wid = out["reply"]["meta"]["workflow_id"]
    d = wf_get(client, wid)
    assert d["plan_state"] == "failed" and d["status"] == "planned" and client.get("/api/workers/runs").json() == []
    assert "실행 계획을 만들지 못했습니다" in out["reply"]["content"] and "넘습니다" in out["reply"]["content"]


def test_daily_cost_caps_block_new_autonomous_starts(client, provider):
    a = prep(client, provider)[0]
    provider.overrides["workflow_plan"] = plan_json([step("a", *a)])
    enable(client, daily_cost_cap_usd=0.3)
    t = trig(client, budget_usd=0.3, daily_cost_cap_usd=0.5)
    first = client.post(f"/api/autonomy/triggers/{t['id']}/fire").json()
    assert first["status"] == "started"
    wait_wf(client, first["workflow_id"], lambda w: w["status"] == "completed")
    spent = client.get("/api/autonomy/settings").json()["spent_today_usd"]
    assert spent > 0
    second = client.post(f"/api/autonomy/triggers/{t['id']}/fire").json()  # 오늘 사용액 + 실행 예산이 전체 한도(0.3)를 넘을 수 있다
    assert second["status"] == "skipped" and second["code"] == "daily_budget"
    t2 = trig(client, name="다른", goal="완전히 다른 목표를 처리해 줘", budget_usd=0.35, daily_cost_cap_usd=0.36)
    assert client.post(f"/api/autonomy/triggers/{t2['id']}/fire").json()["code"] in ("daily_budget", "trigger_budget")
    assert len(wf_ids(client)) == 1


def test_trigger_validation_rejects_bad_limits(client):
    for bad in ({"budget_usd": 9}, {"budget_usd": 0.6, "daily_cost_cap_usd": 0.5}, {"config": {"minutes": 1}}, {"max_retries": 99}, {"exec_mode": "root"}):
        body = {"name": "x", "kind": "interval", "goal": GOAL, "config": {"minutes": 5}, "exec_mode": "supervised"} | bad
        assert client.post("/api/autonomy/triggers", json=body).status_code == 422, bad
    assert client.post("/api/autonomy/triggers", json={"name": "x", "kind": "daily", "goal": GOAL, "config": {"time": "25:00"}}).status_code == 422
    assert client.post("/api/autonomy/triggers", json={"name": "x", "kind": "once", "goal": GOAL, "config": {"run_at": "2020-01-01T00:00"}}).status_code == 422


# ---------------------------------------------------------------- 7. 중복 실행 방지 + 반복·무한 루프 방지

def test_same_trigger_never_runs_twice_slot_cooldown_and_live_workflow(client, provider):
    a = prep(client, provider, approval=True)[0]  # 승인 대기로 워크플로가 계속 살아 있다
    provider.overrides["workflow_plan"] = plan_json([step("a", *a)])
    enable(client)
    t = trig(client)
    tid = t["id"]
    a1 = run(client, lambda: svc(client).autonomy.fire(tid, reason="테스트", slot="same-slot"))
    assert a1["status"] == "started"
    a2 = run(client, lambda: svc(client).autonomy.fire(tid, reason="테스트", slot="same-slot"))
    assert a2["status"] == "duplicate"  # 같은 슬롯
    a3 = run(client, lambda: svc(client).autonomy.fire(tid, reason="테스트", slot="other-slot"))
    assert a3["status"] == "skipped" and a3["code"] == "already_running"  # 이 트리거의 워크플로가 아직 진행 중
    assert len(wf_ids(client)) == 1
    # 같은 목표의 다른 트리거도 진행 중인 동일 목표를 중복 시작하지 못한다
    t2 = trig(client, name="복제")
    assert client.post(f"/api/autonomy/triggers/{t2['id']}/fire").json()["code"] == "duplicate_goal"
    assert len(wf_ids(client)) == 1


def test_cooldown_and_daily_run_limit(client, provider):
    a = prep(client, provider)[0]
    provider.overrides["workflow_plan"] = plan_json([step("a", *a)])
    enable(client)
    clock = Clock()
    svc(client).autonomy.now = clock
    t = trig(client, cooldown_minutes=30, max_runs_per_day=2)
    r1 = client.post(f"/api/autonomy/triggers/{t['id']}/fire").json()
    wait_wf(client, r1["workflow_id"], lambda w: w["status"] == "completed")
    assert client.post(f"/api/autonomy/triggers/{t['id']}/fire").json()["code"] == "cooldown"
    clock.advance(minutes=31)
    r3 = client.post(f"/api/autonomy/triggers/{t['id']}/fire").json()
    assert r3["status"] == "started"
    wait_wf(client, r3["workflow_id"], lambda w: w["status"] == "completed")
    clock.advance(minutes=31)
    assert client.post(f"/api/autonomy/triggers/{t['id']}/fire").json()["code"] == "daily_limit"


def test_concurrency_limit(client, provider):
    a = prep(client, provider, approval=True)[0]
    provider.overrides["workflow_plan"] = plan_json([step("a", *a)])
    enable(client, max_concurrent=1)
    t1 = trig(client, name="하나", goal="첫 번째 자율 목표를 처리해 줘")
    t2 = trig(client, name="둘", goal="두 번째 자율 목표를 처리해 줘")
    r1 = client.post(f"/api/autonomy/triggers/{t1['id']}/fire").json()
    wait_wf(client, r1["workflow_id"], lambda w: w["status"] == "running")
    r2 = client.post(f"/api/autonomy/triggers/{t2['id']}/fire").json()
    assert r2["status"] == "skipped" and r2["code"] == "concurrency"


def test_chain_trigger_runs_after_predecessor_and_cycles_are_rejected(client, provider):
    a = prep(client, provider)[0]
    provider.overrides["workflow_plan"] = plan_json([step("a", *a)])
    enable(client)
    first = trig(client, name="선행", goal="선행 목표를 처리해 줘")
    after = trig(client, name="후행", kind="chain", goal="후행 목표를 처리해 줘", config={"after_trigger_id": first["id"]})
    assert after["next_fire_at"] is None
    r = client.post(f"/api/autonomy/triggers/{first['id']}/fire").json()
    wait_wf(client, r["workflow_id"], lambda w: w["status"] == "completed")
    follow = wait_for(lambda: [x for x in runs(client) if x["trigger_id"] == after["id"] and x["workflow_id"]])
    assert "선행 업무 완료" in follow[0]["reason"]
    d = wait_wf(client, follow[0]["workflow_id"], lambda w: w["status"] == "completed")
    assert d["origin"] == "chain" and d["chain_depth"] == 1
    # 순환: 선행 트리거를 후행에 다시 걸 수 없고, 자기 자신도 안 된다
    assert client.put(f"/api/autonomy/triggers/{after['id']}", json={"config": {"after_trigger_id": after["id"]}}).status_code == 422
    assert client.delete(f"/api/autonomy/triggers/{first['id']}").status_code == 409  # 연결된 후행이 조용히 끊기지 않게
    # 연쇄 깊이 상한
    t = svc(client).autonomy.get_trigger(first["id"])
    assert svc(client).autonomy.gate(t, chain_depth=svc(client).settings.autonomy_max_chain_depth + 1)[0] == "loop_guard"


def test_event_and_proactive_triggers_fire_with_reason_and_dedupe(client, provider):
    a = prep(client, provider)[0]
    provider.overrides["workflow_plan"] = plan_json([step("a", *a)])
    enable(client)
    ev = trig(client, name="이벤트", kind="event", config={"event": "report_ready"}, goal="이벤트 목표를 처리해 줘")
    pr = trig(client, name="능동", kind="proactive", config={"topic_key": "sky"}, goal="능동 제안 목표를 처리해 줘")
    res = client.post("/api/autonomy/events", json={"name": "report_ready", "key": "k1"}).json()["results"]
    assert res[0]["status"] == "started"
    wait_wf(client, res[0]["workflow_id"], lambda w: w["status"] == "completed")
    assert client.post("/api/autonomy/events", json={"name": "report_ready", "key": "k1"}).json()["results"][0]["status"] == "duplicate"  # 같은 이벤트 키는 한 번만
    assert client.post("/api/autonomy/events", json={"name": "BAD NAME"}).status_code == 422
    # 능동 제안 전달 -> 트리거 (다른 주제는 무시)
    async def deliver(sid, topic, title):  # 서버 이벤트 루프 안에서 호출(제안 전달은 항상 루프 안에서 일어난다)
        svc(client).proactive.on_delivered(sid, topic, title)
        await asyncio.sleep(0.3)
    run(client, deliver, 1, "idea", "무관한 제안")
    assert [x for x in runs(client) if x["trigger_id"] == pr["id"]] == []
    run(client, deliver, 7, "sky", "이번 주말 은하수 관측 적기")
    got = wait_for(lambda: [x for x in runs(client) if x["trigger_id"] == pr["id"] and x["workflow_id"]])
    assert "능동 제안 #7" in got[0]["reason"] and "은하수" in got[0]["reason"]
    assert ev["kind"] == "event"


# ---------------------------------------------------------------- 8. 실패 후 재시도

def flaky_draft(provider, fail_times):
    state = {"n": 0}

    def draft(messages):
        state["n"] += 1
        if state["n"] <= fail_times:
            raise LLMError("일시적인 LLM 오류")
        return good_draft()

    provider.overrides["worker_draft"] = draft
    return state


def test_transient_failure_is_retried_automatically_within_the_limit(client, provider):
    setup_llm(provider)
    state = flaky_draft(provider, 1)
    a = mk(client, "직원", approval=False)
    provider.overrides["workflow_plan"] = plan_json([step("a", *a)])
    svc(client).settings.autonomy_retry_delay_minutes = 0
    enable(client)
    t = trig(client, max_retries=1)
    r = client.post(f"/api/autonomy/triggers/{t['id']}/fire").json()
    failed = wait_wf(client, r["workflow_id"], lambda w: w["status"] == "failed")
    assert by_key(failed)["a"]["error_kind"] == "llm_error" and failed["auto_retries"] == 0
    run(client, svc(client).autonomy.tick)
    done = wait_wf(client, r["workflow_id"], lambda w: w["status"] == "completed")
    assert done["auto_retries"] == 1 and by_key(done)["a"]["attempts"] == 2 and state["n"] >= 2
    wait_for(lambda: runs(client)[0]["status"] == "completed")


def test_retry_limit_is_enforced_and_non_transient_failures_are_not_retried(client, provider):
    setup_llm(provider)
    flaky_draft(provider, 99)  # 계속 실패
    a = mk(client, "직원", approval=False)
    provider.overrides["workflow_plan"] = plan_json([step("a", *a)])
    svc(client).settings.autonomy_retry_delay_minutes = 0
    enable(client)
    t = trig(client, max_retries=1)
    r = client.post(f"/api/autonomy/triggers/{t['id']}/fire").json()
    wait_wf(client, r["workflow_id"], lambda w: w["status"] == "failed")
    run(client, svc(client).autonomy.tick)  # 1회 재시도
    wait_for(lambda: wf_get(client, r["workflow_id"])["auto_retries"] == 1)
    wait_wf(client, r["workflow_id"], lambda w: w["status"] == "failed" and by_key(w)["a"]["attempts"] == 2)
    calls = provider.calls.count("worker_draft")
    for _ in range(3):
        run(client, svc(client).autonomy.tick)  # 상한(1회)에 도달: 더는 재시도하지 않는다
    client.portal.call(asyncio.sleep, 0.3)
    assert provider.calls.count("worker_draft") == calls and wf_get(client, r["workflow_id"])["auto_retries"] == 1
    assert wf_get(client, r["workflow_id"])["status"] == "failed"  # 실패를 숨기지 않는다
    # 검증 실패 같은 사용자 판단이 필요한 실패는 자동 재시도 대상이 아니다
    with svc(client).db.session() as s:
        from gyunexus.models import WorkflowStep
        st = s.scalars(select(WorkflowStep)).first()
        st.error_kind = "verification_failed"
        s.get(Workflow, r["workflow_id"]).auto_retries = 0
    run(client, svc(client).autonomy.tick)
    client.portal.call(asyncio.sleep, 0.2)
    assert provider.calls.count("worker_draft") == calls


# ---------------------------------------------------------------- 9. 서버 재시작 복구 + 11. 중지·재개

def test_restart_recovers_state_and_does_not_refire_the_same_trigger(settings, provider):
    setup_llm(provider)
    clock = Clock()
    with TestClient(create_app(settings, provider, run_scheduler=False)) as c:
        svc(c).autonomy.now = clock
        a = mk(c, "조사 직원")
        provider.overrides["workflow_plan"] = plan_json([step("a", *a)])
        enable(c)
        t = trig(c)
        clock.advance(minutes=6)
        run(c, svc(c).autonomy.tick)
        rr = runs(c)
        assert len(rr) == 1
        wid = rr[0]["workflow_id"]
        wait_wf(c, wid, lambda w: by_key(w)["a"]["status"] == "awaiting_approval")
        next_fire = c.get("/api/autonomy/triggers").json()[0]["next_fire_at"]
        # 시작 도중 끊긴 발동(슬롯만 점유): 재시작 후 정리되고 다시 실행되지 않는다
        with svc(c).db.session() as s:
            s.add(AutonomyRun(trigger_id=t["id"], slot_key="t1:crashed", reason="끊긴 발동", status="starting", created_at=utcnow() + timedelta(days=1), updated_at=utcnow()))
    with TestClient(create_app(settings, provider, run_scheduler=False)) as c2:
        svc(c2).autonomy.now = clock
        d = wf_get(c2, wid)
        assert d["status"] == "running" and by_key(d)["a"]["status"] == "awaiting_approval" and d["origin"] == "schedule"  # 상태 복구
        assert c2.get("/api/autonomy/triggers").json()[0]["next_fire_at"] == next_fire  # 일정 유지
        st = {x["slot_key"]: x for x in runs(c2)}
        assert st["t1:crashed"]["status"] == "failed" and "재시작" in st["t1:crashed"]["detail"]["error"]
        assert c2.get("/api/autonomy/settings").json()["enabled"] is True
        calls = provider.calls.count("workflow_plan")
        run(c2, svc(c2).autonomy.tick)  # 예정 시각 전: 아무것도 시작하지 않는다
        assert provider.calls.count("workflow_plan") == calls and len([x for x in runs(c2) if x["workflow_id"]]) == 1
        # 이미 사용된 슬롯은 재시작 후에도 중복으로 막힌다
        slot = [x["slot_key"] for x in runs(c2) if x["workflow_id"]][0]
        again = run(c2, lambda: svc(c2).autonomy.fire(t["id"], reason="재시도", slot=slot))
        assert again["status"] == "duplicate"
        assert approve_pending(c2) == 1
        wait_wf(c2, wid, lambda w: w["status"] == "completed")


def test_pause_and_resume_keep_mode_and_stop_new_steps(client, provider):
    setup_llm(provider)
    a, b = mk(client, "A", approval=True), mk(client, "B", approval=False, materials=False)
    provider.overrides["workflow_plan"] = plan_json([step("a", *a), step("b", *b, ["a"])])
    out = chat(client, GOAL, delegate=True, mode="supervised")
    wid = out["reply"]["meta"]["workflow_id"]
    wait_wf(client, wid, lambda w: by_key(w)["a"]["status"] == "awaiting_approval")
    assert client.post(f"/api/workflows/{wid}/pause").json()["status"] == "paused"
    approve_pending(client)  # 일시정지 중 승인해도 다음 단계는 시작되지 않는다
    client.portal.call(asyncio.sleep, 0.4)
    mid = wf_get(client, wid)
    assert mid["status"] == "paused" and by_key(mid)["b"]["status"] == "pending" and mid["exec_mode"] == "supervised"
    assert client.post(f"/api/workflows/{wid}/resume").json()["status"] == "running"
    wait_wf(client, wid, lambda w: w["status"] == "completed")
    # 취소도 기존 경로 그대로
    provider.overrides["workflow_plan"] = plan_json([step("a", *a)])
    w2 = chat(client, "다른 목표를 맡길게요", delegate=True, mode="supervised")["reply"]["meta"]["workflow_id"]
    wait_wf(client, w2, lambda w: by_key(w)["a"]["status"] == "awaiting_approval")
    assert client.post(f"/api/workflows/{w2}/cancel").json()["status"] == "cancelled"


# ---------------------------------------------------------------- 정책·기록·개요

def test_schema_migration_keeps_existing_workflow_rows_working(settings, provider):
    """이전 버전 DB(자율 실행 컬럼 없음)를 열어도 기존 워크플로·승인 기록이 그대로 읽히고 manual 로 간주된다."""
    from sqlalchemy import create_engine, text
    setup_llm(provider)
    with TestClient(create_app(settings, provider, run_scheduler=False)) as c:
        a = mk(c, "직원", approval=False)
        wf = create(c, provider, [step("a", *a)])
    eng = create_engine(settings.db_url)
    with eng.begin() as conn:  # 이전 스키마를 흉내: 새 컬럼과 새 테이블을 제거
        conn.execute(text("DROP INDEX ix_workflows_trigger_id"))
        for col in ("exec_mode", "origin", "trigger_id", "trigger_reason", "conversation_id", "chain_depth", "auto_retries", "policy_decision", "notified_state"):
            conn.execute(text(f"ALTER TABLE workflows DROP COLUMN {col}"))
        conn.execute(text("ALTER TABLE approvals DROP COLUMN decided_by"))
        conn.execute(text("DROP TABLE autonomy_runs"))
        conn.execute(text("DROP TABLE autonomy_triggers"))
    eng.dispose()
    with TestClient(create_app(settings, provider, run_scheduler=False)) as c2:
        d = wf_get(c2, wf["id"])
        assert d["id"] == wf["id"] and d["exec_mode"] == "manual" and d["origin"] == "user" and d["chain_depth"] == 0 and len(d["steps"]) == 1
        assert c2.get("/api/autonomy/triggers").json() == [] and c2.post(f"/api/workflows/{wf['id']}/start").status_code == 200
        wait_wf(c2, wf["id"], lambda w: w["status"] == "completed")


def test_overview_lists_running_upcoming_completed_and_attention(client, provider):
    setup_llm(provider)
    a = mk(client, "조사 직원")
    w = mk(client, "쓰기 직원", wkw={"permission_level": "write_with_approval"}, tools=["notes.write"])
    enable(client)
    provider.overrides["workflow_plan"] = plan_json([step("a", *a)])
    running = chat(client, GOAL, delegate=True, mode="supervised")["reply"]["meta"]["workflow_id"]
    wait_wf(client, running, lambda w: by_key(w)["a"]["status"] == "awaiting_approval")
    provider.overrides["workflow_plan"] = plan_json([step("w", *w)])
    blocked = chat(client, "쓰기 작업을 맡길게요", delegate=True, mode="supervised")["reply"]["meta"]["workflow_id"]
    trig(client, name="다음 예약")
    ov = client.get("/api/autonomy/overview").json()
    assert [x["id"] for x in ov["running"]] == [running] and ov["running"][0]["current"][0]["worker"] == "조사 직원"
    need = {x["id"]: x for x in ov["needs_attention"]}
    assert running in need and blocked in need and any("쓰기 권한" in t for t in need[blocked]["attention"])
    assert ov["upcoming"][0]["name"] == "다음 예약" and ov["config"]["enabled"] is True
    approve_pending(client)
    wait_wf(client, running, lambda w: w["status"] == "completed")
    assert client.get("/api/autonomy/overview").json()["completed"][0]["id"] == running


def test_decisions_are_logged_with_reasons(client, provider):
    setup_llm(provider)
    a = mk(client, "직원", approval=False)
    provider.overrides["workflow_plan"] = plan_json([step("a", *a)])
    enable(client)
    t = trig(client)
    client.post(f"/api/autonomy/triggers/{t['id']}/fire")
    logs = client.get("/api/logs?limit=200").json()
    events = {x["event"] for x in logs}
    assert {"autonomy.config_changed", "autonomy.trigger_created", "autonomy.goal_submitted", "autonomy.auto_started", "autonomy.fire_started"} <= events


def test_manual_fire_contract_used_by_the_run_now_button(client, provider):
    a = prep(client, provider)[0]
    provider.overrides["workflow_plan"] = plan_json([step("a", *a)])
    t = trig(client)
    assert client.post("/api/autonomy/triggers/999/fire").status_code == 404
    off = client.post(f"/api/autonomy/triggers/{t['id']}/fire").json()  # 자율 운영 OFF: 실제 차단 사유를 돌려준다
    assert off["status"] == "skipped" and off["code"] == "disabled" and "꺼져" in off["message"]
    enable(client)
    ok = client.post(f"/api/autonomy/triggers/{t['id']}/fire").json()
    assert ok["status"] == "started" and isinstance(ok["workflow_id"], int)
    wait_wf(client, ok["workflow_id"], lambda w: w["status"] == "completed")
    rr = runs(client)  # 실행 기록 탭이 쓰는 목록: 차단 1건 + 수동 발동 1건(사유·워크플로 연결 포함)
    assert [x["status"] for x in rr][-1] == "skipped" or {x["status"] for x in rr} >= {"skipped"}
    started = [x for x in rr if x["workflow_id"] == ok["workflow_id"]][0]
    assert started["reason"] == "사용자가 수동으로 발동" and started["trigger_name"] == t["name"] and started["slot_key"].startswith(f"t{t['id']}:manual:")
    assert client.get("/api/autonomy/triggers").json()[0]["next_fire_at"] == t["next_fire_at"]  # 예약 일정은 바뀌지 않는다
