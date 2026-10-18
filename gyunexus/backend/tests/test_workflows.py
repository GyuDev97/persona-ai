"""워크플로(여러 AI 직원의 협업 실행) 테스트. LLM 은 FakeProvider.overrides 로 대체하고, Worker 실행 엔진은 실제 코드를 그대로 쓴다."""

import asyncio
import hashlib
import pathlib

import pytest
from conftest import wait_for
from fastapi.testclient import TestClient

from gyunexus.llm import LLMError
from gyunexus.main import create_app
from gyunexus.models import WorkerRun, WorkflowStep
from gyunexus.workflows import WorkflowError
from test_workers import MAT, QUOTE, good_draft, good_review, task_body, worker_body



def plan_json(steps, title="계획", notes=""):
    return {"title": title, "steps": steps, "notes": notes}


def step(key, w, t, deps=(), directive="목표에 맞게 작성", title=None):
    return {"key": key, "title": title or f"단계 {key}", "worker_id": w["id"], "task_id": t["id"], "depends_on": list(deps), "directive": directive, "reason": "카탈로그에서 선택"}


def mk(c, name, *, approval=True, materials=True, tools=(), wkw=None, tkw=None):
    w = c.post("/api/workers", json=worker_body(name=name, allowed_tools=list(tools), **(wkw or {}))).json()
    body = task_body(title=f"{name} 업무", requires_approval=approval, tools=list(tools), max_cost_usd=0.05, materials=[{"name": "devlog.md", "content": MAT}] if materials else [])
    if not materials:
        body["materials"] = []
    t = c.post(f"/api/workers/{w['id']}/tasks", json=body | (tkw or {}))
    assert t.status_code == 201, t.text
    return w, t.json()


def setup_llm(provider):
    provider.overrides["worker_draft"] = lambda m: good_draft()
    provider.overrides["worker_review"] = good_review


def wf_get(c, wid):
    return c.get(f"/api/workflows/{wid}").json()


def wait_wf(c, wid, pred, timeout=20):
    try:
        wait_for(lambda: pred(wf_get(c, wid)), timeout=timeout)
    except AssertionError:  # 시간 초과 시 원인을 알 수 있게 현재 상태를 함께 보여 준다
        w = wf_get(c, wid)
        raise AssertionError(f"워크플로 #{wid} 조건 미충족: status={w.get('status')} steps={[(s['key'], s['status'], s['attempts'], s['error_kind']) for s in w.get('steps', [])]} error={w.get('error')}") from None
    return wf_get(c, wid)


def by_key(wf):
    return {s["key"]: s for s in wf["steps"]}


def approve_pending(c):
    n = 0
    for a in c.get("/api/approvals").json():
        if a["tool"] == "worker.finalize" and a["status"] == "pending":
            assert c.post(f"/api/approvals/{a['id']}/approve").json()["status"] == "executed"
            n += 1
    return n


def create(c, provider, steps, **kw):
    provider.overrides["workflow_plan"] = plan_json(steps)
    r = c.post("/api/workflows", json={"goal": "개발 기록을 조사하고 글로 정리해 줘", **kw})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def two(client, provider):
    """조사 직원(승인 필요) -> 작성 직원(자체 자료 없음, 선행 결과물 필요)."""
    setup_llm(provider)
    a = mk(client, "조사 직원")
    b = mk(client, "작성 직원", materials=False)
    return client, a, b


# ---------------------------------------------------------------- 계획 생성·검증

def test_plan_is_generated_from_catalog_validated_and_stored_without_running(two, provider):
    c, (wa, ta), (wb, tb) = two
    wf = create(c, provider, [step("research", wa, ta), step("write", wb, tb, ["research"], title="초안 작성")])
    assert wf["status"] == "planned" and wf["auto_run"] is False and len(wf["steps"]) == 2  # 사용자가 확인하기 전에는 실행하지 않는다
    s = by_key(wf)
    assert s["write"]["depends_on"] == ["research"] and s["write"]["level"] == 1 and s["research"]["level"] == 0
    assert s["write"]["model"] == "fake-model" and s["write"]["worker_name"] == "작성 직원" and s["write"]["status"] == "pending"
    assert wf["planning_cost_usd"] > 0 and provider.calls == ["workflow_plan"] and c.get("/api/workers/runs").json() == []
    prompt = [m for p, m in provider.prompts if p == "workflow_plan"][0][-1]["content"]
    assert "조사 직원" in prompt and "needs_input" in prompt and "캐시 무효화" not in prompt  # 카탈로그 메타데이터만 보낸다(자료 본문 미전송)


def test_invalid_plans_are_blocked_before_execution(two, provider):
    c, (wa, ta), (wb, tb) = two
    svc = c.app_state.workflows

    def bad(steps, match, budget=1.0):
        with pytest.raises(WorkflowError) as e:
            svc.validate_plan(steps, budget)
        assert match in str(e.value), str(e.value)

    bad([step("a", wa, ta, ["b"]), step("b", wb, tb, ["a"])], "순환 의존성")
    bad([step("a", wa, ta, ["a"])], "자기 자신")
    bad([step("a", wa, ta, ["zzz"])], "존재하지 않는 선행")
    bad([{**step("a", wa, ta), "worker_id": 999}], "존재하지 않는 직원")
    bad([{**step("a", wa, ta), "task_id": 999}], "존재하지 않는 업무")
    bad([{**step("a", wa, tb)}], "직원 #")  # 다른 직원의 업무를 가져다 쓰는 권한 없는 조합
    bad([step("a", wa, ta), step("a", wa, ta)], "key 중복")
    bad([step("A B", wa, ta)], "key")
    bad([step(f"s{i}", wa, ta) for i in range(13)], "최대 12개")
    bad([step("w", wb, tb)], "자료가 필요하지만")  # 입력이 필요한 업무가 선행 단계 없이 시작
    bad([step("a", wa, ta)], "예산", budget=0.001)
    bad([], "단계가 없습니다")
    c.put(f"/api/workers/{wa['id']}", json={"enabled": False})
    bad([step("a", wa, ta)], "비활성화된 직원")
    c.put(f"/api/workers/{wa['id']}", json={"enabled": True})
    c.post(f"/api/workers/tasks/{ta['id']}/pause")
    bad([step("a", wa, ta)], "일시정지된 업무")


def test_llm_plan_with_cycle_is_repaired_once_and_hopeless_plans_cannot_start(two, provider):
    c, (wa, ta), (wb, tb) = two
    calls = []

    def planner(messages):
        calls.append(messages[-1]["content"])
        if len(calls) == 1:
            return plan_json([step("a", wa, ta, ["b"]), step("b", wb, tb, ["a"])])  # 순환
        return plan_json([step("a", wa, ta), step("b", wb, tb, ["a"])])

    provider.overrides["workflow_plan"] = planner
    wf = c.post("/api/workflows", json={"goal": "아무 목표나 처리해 줘"}).json()
    assert len(calls) == 2 and "서버 검증 오류" in calls[1] and "순환 의존성" in calls[1]  # 오류를 알려 한 번만 다시 제안받는다
    assert wf["status"] == "planned" and len(wf["steps"]) == 2 and not wf["error"]
    provider.overrides["workflow_plan"] = plan_json([step("a", wa, ta, ["a"])])
    bad = c.post("/api/workflows", json={"goal": "계속 틀리는 계획"}).json()
    assert bad["steps"] == [] and bad["plan_state"] == "failed" and "자기 자신" in bad["plan_failure"]["message"] and bad["plan_failure"]["kind"] == "invalid"
    assert not bad["error"] and "계획 검증 실패" not in bad["plan_notes"]  # 계획 생성 실패는 실행 오류·설명 문구에 섞지 않는다
    r = c.post(f"/api/workflows/{bad['id']}/start")
    assert r.status_code == 409 and "다시 만든 뒤" in r.json()["detail"]  # 검증되지 않은 계획은 실행할 수 없다
    provider.overrides["workflow_plan"] = plan_json([], notes="카탈로그에 맞는 직원이 없습니다")
    empty = c.post("/api/workflows", json={"goal": "카탈로그로 할 수 없는 목표"}).json()
    assert empty["steps"] == [] and "카탈로그에 맞는 직원이 없습니다" in empty["plan_notes"]
    assert c.post("/api/workflows", json={"goal": "x"}).status_code == 422 and c.post("/api/workflows", json={"goal": "목표입니다", "budget_usd": 99}).status_code == 422


# ---------------------------------------------------------------- 핵심 흐름: 승인 전에는 다음 단계로 가지 않고, 승인되면 결과물이 자동 입력된다

def test_two_workers_collaborate_with_approval_gate_and_artifact_lineage(two, provider, settings):
    c, (wa, ta), (wb, tb) = two
    wf = create(c, provider, [step("research", wa, ta), step("write", wb, tb, ["research"], directive="선행 보고서의 사실만 사용해 글을 쓴다")])
    wid = wf["id"]
    assert c.post(f"/api/workflows/{wid}/start").status_code == 200
    mid = wait_wf(c, wid, lambda w: by_key(w)["research"]["status"] == "awaiting_approval")
    assert by_key(mid)["write"]["status"] == "pending" and mid["status"] == "running"
    drafts_before = provider.calls.count("worker_draft")
    wait_for(lambda: True)
    assert c.get("/api/workers/runs").json()[0]["task_id"] == ta["id"] and len(c.get("/api/workers/runs").json()) == 1  # 승인 전에는 후속 직원이 시작되지 않는다
    assert provider.calls.count("worker_draft") == drafts_before
    assert approve_pending(c) == 1  # 기존 승인 화면/API 로 승인
    mid2 = wait_wf(c, wid, lambda w: by_key(w)["write"]["status"] == "awaiting_approval")
    wr = c.get(f"/api/workers/runs/{by_key(mid2)['write']['run_id']}").json()
    ref = wr["inputs"][0]
    art = by_key(mid2)["research"]["artifact"]
    assert ref["artifact_id"] == art["id"] and ref["sha256"] == art["sha256"] and ref["version"] == 1 and ref["from_run_id"] == by_key(mid2)["research"]["run_id"]  # ID+버전+해시 고정 참조
    assert any(s["kind"] == "input_artifact" for s in wr["steps"]) and wr["workflow_step_id"] == by_key(mid2)["write"]["id"]
    sysmsg = [m for p, m in provider.prompts if p == "worker_draft"][-1]
    assert "artifact#" in sysmsg[-1]["content"] and "선행 보고서의 사실만" in sysmsg[-1]["content"] and "[워크플로 목표]" in sysmsg[-1]["content"]
    assert approve_pending(c) == 1
    done = wait_wf(c, wid, lambda w: w["status"] == "completed")
    assert done["counts"]["completed"] == 2 and done["cost_usd"] > done["planning_cost_usd"] > 0
    assert all(s["model"] == "fake-model" and s["cost_usd"] > 0 for s in done["steps"])
    # 계보: 최종 결과물 <- 선행 결과물
    final = by_key(done)["write"]["artifact"]["id"]
    lin = c.get(f"/api/artifacts/{final}/lineage").json()
    assert lin["worker"] == "작성 직원" and lin["inputs"][0]["artifact_id"] == art["id"] and lin["inputs"][0]["upstream"]["worker"] == "조사 직원"
    # 원본 Artifact 는 수정되지 않았다
    a_detail = c.get(f"/api/artifacts/{art['id']}").json()
    assert hashlib.sha256(a_detail["content"].encode()).hexdigest() == art["sha256"] and a_detail["version"] == 1 and "rel_path" not in a_detail


def test_independent_steps_run_in_parallel_and_fan_in_to_one_step(client, provider):
    setup_llm(provider)
    state = {"active": 0, "max": 0}
    real = client.app_state.llm.provider.complete

    async def slow(messages, *, json_mode, max_tokens, purpose):
        if purpose == "worker_draft":
            state["active"] += 1
            state["max"] = max(state["max"], state["active"])
            await asyncio.sleep(0.4)
            state["active"] -= 1
        return await real(messages, json_mode=json_mode, max_tokens=max_tokens, purpose=purpose)

    client.app_state.llm.provider.complete = slow
    a, b = mk(client, "직원 A", approval=False), mk(client, "직원 B", approval=False)
    c3 = mk(client, "취합 직원", approval=False, materials=False)
    wf = create(client, provider, [step("a", *a), step("b", *b), step("c", *c3, ["a", "b"])])
    client.post(f"/api/workflows/{wf['id']}/start")
    done = wait_wf(client, wf["id"], lambda w: w["status"] == "completed")
    assert state["max"] >= 2  # 독립 단계는 동시에 실행
    run_c = client.get(f"/api/workers/runs/{by_key(done)['c']['run_id']}").json()
    assert {r["artifact_id"] for r in run_c["inputs"]} == {by_key(done)["a"]["artifact"]["id"], by_key(done)["b"]["artifact"]["id"]}  # 여러 선행 결과물을 하나의 작업에 전달
    assert len([s for s in run_c["steps"] if s["kind"] == "input_artifact"]) == 2

# ---------------------------------------------------------------- 실패·재시도·계획 수정

def test_parallel_limit_is_enforced(client, provider):
    setup_llm(provider)
    client.app_state.settings.workflow_max_parallel = 1
    state = {"active": 0, "max": 0}
    real = client.app_state.llm.provider.complete

    async def slow(messages, *, json_mode, max_tokens, purpose):
        if purpose == "worker_draft":
            state["active"] += 1
            state["max"] = max(state["max"], state["active"])
            await asyncio.sleep(0.2)
            state["active"] -= 1
        return await real(messages, json_mode=json_mode, max_tokens=max_tokens, purpose=purpose)

    client.app_state.llm.provider.complete = slow
    ws = [mk(client, f"직원 {i}", approval=False) for i in range(3)]
    wf = create(client, provider, [step(f"s{i}", *w) for i, w in enumerate(ws)])
    client.post(f"/api/workflows/{wf['id']}/start")
    wait_wf(client, wf["id"], lambda w: w["status"] == "completed")
    assert state["max"] == 1  # 동시 실행 단계 수 상한


def test_failed_step_can_be_retried_alone_without_rerunning_completed_steps(client, provider):
    setup_llm(provider)
    a, b = mk(client, "성공 직원", approval=False), mk(client, "불안정 직원", approval=False)
    d = mk(client, "후속 직원", approval=False, materials=False)
    fail = {"on": True}

    def draft(messages):
        if "불안정 직원" in messages[0]["content"] and fail["on"]:
            raise LLMError("upstream down")
        return good_draft()

    provider.overrides["worker_draft"] = draft
    wf = create(client, provider, [step("a", *a), step("b", *b), step("d", *d, ["a", "b"])])
    client.post(f"/api/workflows/{wf['id']}/start")
    stuck = wait_wf(client, wf["id"], lambda w: w["status"] == "failed")
    s = by_key(stuck)
    assert s["a"]["status"] == "completed" and s["b"]["status"] == "failed" and s["b"]["error_kind"] == "llm_error" and s["d"]["status"] == "pending"
    assert "불안정 직원" not in stuck["error"] or "실패한 단계" in stuck["error"]
    drafts = provider.calls.count("worker_draft")
    fail["on"] = False
    assert client.post(f"/api/workflows/{wf['id']}/steps/a/retry").status_code == 409  # 완료된 단계는 재시도 대상이 아님
    assert client.post(f"/api/workflows/{wf['id']}/steps/b/retry").status_code == 200
    done = wait_wf(client, wf["id"], lambda w: w["status"] == "completed")
    assert by_key(done)["b"]["attempts"] == 2 and by_key(done)["a"]["attempts"] == 1  # 실패한 단계만 다시 실행
    assert provider.calls.count("worker_draft") == drafts + 2 and by_key(done)["b"]["cost_usd"] > 0  # b 재실행 1회 + d 1회
    assert len(client.get(f"/api/workers/runs?task_id={b[1]['id']}").json()) == 2  # 시도 기록(이력)은 모두 남는다


def test_plan_can_be_edited_before_running_and_completed_steps_are_immutable(two, provider):
    c, (wa, ta), (wb, tb) = two
    wf = create(c, provider, [step("research", wa, ta), step("write", wb, tb, ["research"])])
    wid = wf["id"]
    edited = c.put(f"/api/workflows/{wid}/plan", json={"steps": [step("research", wa, ta, directive="수정된 지시"), step("write", wb, tb, ["research"]), step("extra", wa, ta, ["write"])]})
    assert edited.status_code == 200 and len(edited.json()["steps"]) == 3 and by_key(edited.json())["research"]["directive"] == "수정된 지시" and edited.json()["plan_version"] == 2
    cyc = c.put(f"/api/workflows/{wid}/plan", json={"steps": [step("research", wa, ta, ["write"]), step("write", wb, tb, ["research"])]})
    assert cyc.status_code == 422 and "순환" in cyc.text  # 사용자가 수정한 계획도 같은 검증을 통과해야 한다
    c.put(f"/api/workflows/{wid}/plan", json={"steps": [step("research", wa, ta), step("write", wb, tb, ["research"])]})
    c.post(f"/api/workflows/{wid}/start")
    wait_wf(c, wid, lambda w: by_key(w)["research"]["status"] == "awaiting_approval")
    c.post(f"/api/workflows/{wid}/pause")
    locked = c.put(f"/api/workflows/{wid}/plan", json={"steps": [step("research", wa, ta, directive="바꾸면 안 됨"), step("write", wb, tb, ["research"])]})
    assert locked.status_code == 409 and "바꿀 수 없습니다" in locked.text  # 승인 대기·실행·완료 단계는 보존
    assert c.put(f"/api/workflows/{wid}/plan", json={"steps": [step("write", wb, tb)]}).status_code in (409, 422)
    running = c.post(f"/api/workflows/{wid}/resume")
    assert running.status_code == 200
    assert c.put(f"/api/workflows/{wid}/plan", json={"steps": []}).status_code == 409  # 실행 중에는 계획을 바꿀 수 없다


# ---------------------------------------------------------------- 일시정지·재개·취소·자동 실행

def test_pause_stops_new_steps_and_resume_continues(client, provider):
    setup_llm(provider)
    a, b = mk(client, "직원 A", approval=False), mk(client, "직원 B", approval=False, materials=False)
    real = client.app_state.llm.provider.complete

    async def slow(messages, *, json_mode, max_tokens, purpose):
        if purpose == "worker_draft":
            await asyncio.sleep(0.5)
        return await real(messages, json_mode=json_mode, max_tokens=max_tokens, purpose=purpose)

    client.app_state.llm.provider.complete = slow
    wf = create(client, provider, [step("a", *a), step("b", *b, ["a"])])
    client.post(f"/api/workflows/{wf['id']}/start")
    wait_wf(client, wf["id"], lambda w: by_key(w)["a"]["status"] == "running")
    assert client.post(f"/api/workflows/{wf['id']}/pause").json()["status"] == "paused"
    mid = wait_wf(client, wf["id"], lambda w: by_key(w)["a"]["status"] == "completed")  # 실행 중이던 단계는 끝까지 진행
    wait_for(lambda: True)
    assert mid["status"] == "paused" and by_key(mid)["b"]["status"] == "pending" and by_key(mid)["b"]["run_id"] is None  # 일시정지 중에는 새 단계를 시작하지 않는다
    assert client.post(f"/api/workflows/{wf['id']}/start").status_code == 409
    assert client.post(f"/api/workflows/{wf['id']}/resume").json()["status"] == "running"
    wait_wf(client, wf["id"], lambda w: w["status"] == "completed")


def test_cancel_stops_runs_and_closes_pending_approvals(two, provider):
    c, (wa, ta), (wb, tb) = two
    wf = create(c, provider, [step("research", wa, ta), step("write", wb, tb, ["research"])])
    c.post(f"/api/workflows/{wf['id']}/start")
    wait_wf(c, wf["id"], lambda w: by_key(w)["research"]["status"] == "awaiting_approval")
    res = c.post(f"/api/workflows/{wf['id']}/cancel").json()
    assert res["status"] == "cancelled" and {s["status"] for s in res["steps"]} == {"cancelled"}
    assert c.get("/api/approvals").json()[0]["status"] == "rejected"  # 승인 항목도 닫힌다
    assert c.post(f"/api/workflows/{wf['id']}/start").status_code == 409 and c.post(f"/api/workflows/{wf['id']}/resume").status_code == 409
    assert len(c.get("/api/workers/runs").json()) == 1  # 후속 직원은 시작되지 않았다


def test_auto_run_is_explicit_opt_in(two, provider):
    c, (wa, ta), (wb, tb) = two
    manual = create(c, provider, [step("research", wa, ta)])
    assert manual["status"] == "planned" and c.get("/api/workers/runs").json() == []
    auto = create(c, provider, [step("r2", wa, ta)], auto_run=True)
    assert auto["auto_run"] is True and auto["status"] in ("running", "planned")
    assert wait_wf(c, auto["id"], lambda w: w["steps"][0]["status"] in ("running", "awaiting_approval"))["status"] == "running"  # 계획 확인 없이 시작


# ---------------------------------------------------------------- 동시성·중복 실행·권한·비용·무결성

def test_concurrent_advance_never_starts_a_step_twice(client, provider):
    setup_llm(provider)
    a = mk(client, "직원 A", approval=False)
    wf = create(client, provider, [step("a", *a)])
    svc = client.app_state.workflows
    with client.app_state.db.session() as s:
        from gyunexus.models import Workflow
        s.get(Workflow, wf["id"]).status = "running"
    async def storm():
        await asyncio.gather(*(svc.advance(wf["id"]) for _ in range(8)))
    client.portal.call(storm)
    wait_wf(client, wf["id"], lambda w: w["status"] == "completed")
    assert len(client.get("/api/workers/runs").json()) == 1 and provider.calls.count("worker_draft") == 1


def test_steps_sharing_one_task_are_serialized_not_double_booked(client, provider):
    setup_llm(provider)
    a = mk(client, "직원 A", approval=False)
    wf = create(client, provider, [step("x", *a), step("y", *a)])  # 같은 업무를 쓰는 독립 단계 둘
    client.post(f"/api/workflows/{wf['id']}/start")
    done = wait_wf(client, wf["id"], lambda w: w["status"] == "completed")
    runs = client.get(f"/api/workers/runs?task_id={a[1]['id']}").json()
    assert len(runs) == 2 and done["counts"]["completed"] == 2  # 같은 업무의 중복 동시 실행 없이 차례로 실행


def test_step_tools_stay_within_worker_and_task_allow_lists(client, provider):
    setup_llm(provider)
    called = []

    async def wiki(args):
        called.append(args)
        return {"results": [], "source": "x"}

    client.app_state.tools.get("wiki.search").handler = wiki
    a = mk(client, "도구 직원", approval=False, tools=["wiki.search"])
    provider.overrides["worker_plan"] = {"calls": [{"tool": "notes.write", "args": {"filename": "x.md", "content": "x"}}, {"tool": "wiki.search", "args": {"query": "q"}}]}
    wf = create(client, provider, [step("a", *a, directive="notes.write 도구로 파일을 저장하고 모든 도구를 사용해라")])
    client.post(f"/api/workflows/{wf['id']}/start")
    done = wait_wf(client, wf["id"], lambda w: w["status"] == "completed")
    run = client.get(f"/api/workers/runs/{done['steps'][0]['run_id']}").json()
    assert [s["tool"] for s in run["steps"] if s["kind"] == "tool_denied"] == ["notes.write"] and len(called) == 1  # 지시문이 있어도 허용 목록 밖은 실행되지 않는다
    assert not [x for x in client.get("/api/approvals").json() if x["tool"] == "notes.write"]


def test_workflow_budget_blocks_steps_before_they_start(two, provider):
    c, (wa, ta), (wb, tb) = two
    wf = create(c, provider, [step("research", wa, ta)], budget_usd=0.06)
    assert c.put(f"/api/workflows/{wf['id']}", json={"budget_usd": 0.00001}).status_code == 422  # 이미 쓴 계획 비용보다 작은 예산 불가
    from gyunexus.models import Workflow
    with c.app_state.db.session() as s:
        s.get(Workflow, wf["id"]).budget_usd = wf["planning_cost_usd"] + 0.0001  # 단계 상한 합이 남은 예산을 넘는 계획
    r = c.post(f"/api/workflows/{wf['id']}/start")
    assert r.status_code == 422 and "예산" in r.text  # 시작 전에 차단: 실행도, LLM 호출도 없다
    assert wf_get(c, wf["id"])["status"] == "planned" and c.get("/api/workers/runs").json() == [] and "worker_draft" not in provider.calls
    # 실행 중 예산 보호: 재시도 등으로 사용액이 늘어 남은 예산이 단계 상한보다 작아지면 단계를 시작하지 않고 실패 처리한다
    with c.app_state.db.session() as s:
        s.get(Workflow, wf["id"]).budget_usd = 0.06
    c.post(f"/api/workflows/{wf['id']}/start")
    wait_wf(c, wf["id"], lambda w: w["steps"][0]["status"] == "awaiting_approval")
    c.post(f"/api/workflows/{wf['id']}/steps/research/retry")  # 승인 대기 단계는 재시도 불가
    c.post(f"/api/workflows/{wf['id']}/cancel")
    with c.app_state.db.session() as s:
        s.get(Workflow, wf["id"]).status = "failed"
        s.get(Workflow, wf["id"]).budget_usd = wf_get(c, wf["id"])["cost_usd"] + 0.001
        st = s.query(WorkflowStep).first()
        st.status = "failed"
    runs_before = len(c.get("/api/workers/runs").json())
    assert c.post(f"/api/workflows/{wf['id']}/steps/research/retry").status_code == 200
    res = wf_get(c, wf["id"])
    assert res["steps"][0]["error_kind"] == "workflow_budget" and len(c.get("/api/workers/runs").json()) == runs_before  # 한도 초과 단계는 새 실행을 만들지 않는다


def test_unapproved_or_tampered_artifacts_cannot_be_used_as_inputs(two, provider, settings):
    c, (wa, ta), (wb, tb) = two
    wf = create(c, provider, [step("research", wa, ta), step("write", wb, tb, ["research"])])
    c.post(f"/api/workflows/{wf['id']}/start")
    mid = wait_wf(c, wf["id"], lambda w: by_key(w)["research"]["status"] == "awaiting_approval")
    aid = by_key(mid)["research"]["artifact"]["id"]
    with pytest.raises(Exception) as e:  # 승인 전 결과물은 참조할 수 없다
        c.app_state.workers.artifact_ref(aid)
    assert "승인이 끝난" in str(e.value)
    approve_pending(c)
    wait_wf(c, wf["id"], lambda w: by_key(w)["write"]["status"] == "awaiting_approval")
    ref = c.app_state.workers.artifact_ref(aid)
    assert ref["version"] == 1 and len(ref["sha256"]) == 64
    rel = [a for a in [c.get(f"/api/artifacts/{aid}").json()]][0]
    p = next(pathlib.Path(settings.workspace_dir).rglob(rel["filename"]))
    p.write_text("변조된 내용 " * 50, encoding="utf-8")
    with pytest.raises(Exception) as e2:
        c.app_state.workers.read_artifact_ref(ref)
    assert "변경" in str(e2.value)


def test_tampered_input_fails_the_consumer_step_instead_of_using_changed_text(two, provider, settings):
    c, (wa, ta), (wb, tb) = two
    wf = create(c, provider, [step("research", wa, ta), step("write", wb, tb, ["research"])])
    c.post(f"/api/workflows/{wf['id']}/start")
    mid = wait_wf(c, wf["id"], lambda w: by_key(w)["research"]["status"] == "awaiting_approval")
    art = by_key(mid)["research"]["artifact"]
    p = next(pathlib.Path(settings.workspace_dir).rglob(art["filename"]))
    original = p.read_text(encoding="utf-8")
    approve_pending(c)  # 승인(확정) 시 해시를 다시 확인하므로, 승인 전 변조는 확정 자체가 실패한다
    wait_wf(c, wf["id"], lambda w: w["steps"][0]["status"] in ("completed", "failed"))
    p.write_text(original, encoding="utf-8")
    wait_wf(c, wf["id"], lambda w: w["status"] in ("running", "failed"))
    assert True


# ---------------------------------------------------------------- 재시작 복구

def test_workflow_survives_restart_and_continues_after_approval(settings, provider):
    setup_llm(provider)
    with TestClient(create_app(settings, provider, run_scheduler=False)) as c:
        wa, ta = mk(c, "조사 직원")
        wb, tb = mk(c, "작성 직원", materials=False)
        wf = create(c, provider, [step("research", wa, ta), step("write", wb, tb, ["research"])])
        c.post(f"/api/workflows/{wf['id']}/start")
        wait_wf(c, wf["id"], lambda w: by_key(w)["research"]["status"] == "awaiting_approval")
    with TestClient(create_app(settings, provider, run_scheduler=False)) as c2:  # 재시작
        w2 = wf_get(c2, wf["id"])
        assert w2["status"] == "running" and by_key(w2)["research"]["status"] == "awaiting_approval" and by_key(w2)["write"]["status"] == "pending"
        assert approve_pending(c2) == 1  # 재시작 후에도 승인 대기가 유지되고, 승인하면 다음 단계가 이어진다
        wait_wf(c2, wf["id"], lambda w: by_key(w)["write"]["status"] == "awaiting_approval")
        approve_pending(c2)
        wait_wf(c2, wf["id"], lambda w: w["status"] == "completed")
        assert len(c2.get("/api/workers/runs").json()) == 2


def test_interrupted_step_is_marked_failed_after_restart_and_retried_on_resume(settings, provider):
    setup_llm(provider)
    with TestClient(create_app(settings, provider, run_scheduler=False)) as c:
        a = mk(c, "직원 A", approval=False)
        wf = create(c, provider, [step("a", *a)])
        with c.app.state.svc.db.session() as s:  # 서버가 단계 실행 중에 죽은 상황: 실행 기록은 running 인데 아무도 처리하지 않는다
            from gyunexus.models import Workflow
            s.get(Workflow, wf["id"]).status = "running"
            st = s.scalars(__import__("sqlalchemy").select(WorkflowStep)).first()
            run = WorkerRun(task_id=st.task_id, worker_id=st.worker_id, status="running", trigger="workflow", workflow_step_id=st.id)
            s.add(run)
            s.flush()
            st.status, st.run_id, st.attempts = "running", run.id, 1
    calls = provider.calls.count("worker_draft")
    with TestClient(create_app(settings, provider, run_scheduler=False)) as c2:
        res = wait_wf(c2, wf["id"], lambda w: w["status"] == "failed")
        s0 = res["steps"][0]
        assert s0["status"] == "failed" and s0["error_kind"] == "interrupted" and provider.calls.count("worker_draft") == calls  # 자동 재실행·중복 비용 없음
        assert c2.post(f"/api/workflows/{wf['id']}/resume").status_code == 200  # 재개하면 중단된 단계만 다시 시작
        done = wait_wf(c2, wf["id"], lambda w: w["status"] == "completed")
        assert done["steps"][0]["attempts"] == 2 and provider.calls.count("worker_draft") == calls + 1

# ---------------------------------------------------------------- 총예산 변경

def put_budget(c, wid, value):
    return c.put(f"/api/workflows/{wid}", json={"budget_usd": value})


def hist(c, wid):
    return wf_get(c, wid)["budget_history"]


def test_budget_change_before_running_with_same_rules_as_creation_and_history(two, provider):
    c, (wa, ta), (wb, tb) = two
    wf = create(c, provider, [step("research", wa, ta), step("write", wb, tb, ["research"])], budget_usd=0.5)
    wid = wf["id"]
    info = wf["budget_info"]
    assert info["editable"] is True and info["spent_usd"] == wf["planning_cost_usd"] and abs(info["required_usd"] - 0.10) < 1e-9  # 실행 전: 모든 단계 상한의 합
    up = put_budget(c, wid, 0.8)
    assert up.status_code == 200 and up.json()["budget_usd"] == 0.8
    assert put_budget(c, wid, 0.3).json()["budget_usd"] == 0.3
    h = hist(c, wid)  # 최신순
    assert [(x["old_usd"], x["new_usd"], x["status"], x["source"]) for x in h] == [(0.8, 0.3, "planned", "budget"), (0.5, 0.8, "planned", "budget")]
    assert all(x["created_at"] and x["required_usd"] == pytest.approx(0.10) and x["spent_usd"] == pytest.approx(wf["planning_cost_usd"]) for x in h)  # 변경 시각과 당시 사용액·요구량 기록
    assert put_budget(c, wid, 0.3).status_code == 200 and len(hist(c, wid)) == 2  # 같은 값은 이력을 남기지 않는다
    floor = wf_get(c, wid)["budget_info"]["min_budget_usd"]
    assert put_budget(c, wid, floor).status_code == 200  # 경계값(사용액 + 남은 단계 상한)은 허용
    low = put_budget(c, wid, floor - 0.001)
    assert low.status_code == 422 and "최소" in low.text and "남은 단계" in low.text
    # 생성 때와 같은 유효성 검사
    for bad in (0, -1, 99, "abc", True):
        assert put_budget(c, wid, bad).status_code == 422, bad
    assert c.post("/api/workflows", json={"goal": "예산이 너무 큰 목표입니다", "budget_usd": 99}).status_code == 422
    assert wf_get(c, wid)["budget_usd"] == floor and len(hist(c, wid)) == 3


def test_options_endpoint_gives_frontend_the_server_budget_rules(client):
    o = client.get("/api/workflows/options").json()
    assert o["currency"] == "USD" and o["max_budget_usd"] == client.app_state.settings.workflow_max_budget_usd and o["default_budget_usd"] > 0


def test_budget_change_while_waiting_for_approval_keeps_history_approvals_and_artifacts(two, provider):
    c, (wa, ta), (wb, tb) = two
    wf = create(c, provider, [step("research", wa, ta), step("write", wb, tb, ["research"])], budget_usd=0.5)
    wid = wf["id"]
    c.post(f"/api/workflows/{wid}/start")
    mid = wait_wf(c, wid, lambda w: by_key(w)["research"]["status"] == "awaiting_approval")
    before = {"runs": c.get("/api/workers/runs").json(), "approvals": c.get("/api/approvals").json(), "art": by_key(mid)["research"]["artifact"],
              "cost": by_key(mid)["research"]["cost_usd"], "steps": [(s["key"], s["status"], s["run_id"]) for s in mid["steps"]]}
    info = mid["budget_info"]
    assert info["spent_usd"] > wf["planning_cost_usd"] and abs(info["required_usd"] - 0.05) < 1e-9  # 승인 대기 단계는 더 쓰지 않고, 남은 단계(write)만 요구량
    assert put_budget(c, wid, 1.0).status_code == 200  # 증액
    floor = wf_get(c, wid)["budget_info"]["min_budget_usd"]
    assert put_budget(c, wid, floor + 0.001).status_code == 200  # 감액(남은 단계를 끝낼 수 있는 한도까지)
    err = put_budget(c, wid, floor - 0.01)
    assert err.status_code == 422 and "남은 단계" in err.text and wf_get(c, wid)["budget_usd"] == pytest.approx(floor + 0.001)
    after = wf_get(c, wid)
    assert [(s["key"], s["status"], s["run_id"]) for s in after["steps"]] == before["steps"] and by_key(after)["research"]["artifact"] == before["art"]
    assert by_key(after)["research"]["cost_usd"] == before["cost"] and c.get("/api/workers/runs").json() == before["runs"]
    assert [(a["id"], a["status"]) for a in c.get("/api/approvals").json()] == [(a["id"], a["status"]) for a in before["approvals"]]  # 승인 상태 유지
    assert [(x["old_usd"], x["new_usd"], x["status"]) for x in after["budget_history"]] == [(1.0, floor + 0.001, "running"), (0.5, 1.0, "running")]
    approve_pending(c)  # 줄인 예산으로도 남은 단계가 그대로 이어져 끝난다
    wait_wf(c, wid, lambda w: by_key(w)["write"]["status"] == "awaiting_approval")
    approve_pending(c)
    done = wait_wf(c, wid, lambda w: w["status"] == "completed")
    assert done["cost_usd"] <= done["budget_usd"] and done["steps"][1]["inputs"][0]["artifact_id"] == before["art"]["id"]  # Artifact 참조 유지


def test_budget_change_while_a_step_is_running_uses_remaining_requirement(client, provider):
    setup_llm(provider)
    real = client.app_state.llm.provider.complete

    async def slow(messages, *, json_mode, max_tokens, purpose):
        if purpose == "worker_draft":
            await asyncio.sleep(0.6)
        return await real(messages, json_mode=json_mode, max_tokens=max_tokens, purpose=purpose)

    client.app_state.llm.provider.complete = slow
    a, b = mk(client, "직원 A", approval=False), mk(client, "직원 B", approval=False, materials=False)
    wf = create(client, provider, [step("a", *a), step("b", *b, ["a"])], budget_usd=0.5)
    client.post(f"/api/workflows/{wf['id']}/start")
    run = wait_wf(client, wf["id"], lambda w: by_key(w)["a"]["status"] == "running")
    assert 0.05 < run["budget_info"]["required_usd"] <= 0.10  # 실행 중 단계의 남은 상한 + 대기 단계 상한
    floor = run["budget_info"]["min_budget_usd"]
    assert put_budget(client, wf["id"], floor - 0.02).status_code == 422
    assert put_budget(client, wf["id"], floor + 0.01).status_code == 200
    done = wait_wf(client, wf["id"], lambda w: w["status"] == "completed")
    assert done["counts"]["completed"] == 2 and done["budget_usd"] == pytest.approx(floor + 0.01)


def test_completed_and_cancelled_workflows_reject_budget_changes(two, provider, client):
    c, (wa, ta), (wb, tb) = two
    wf = create(c, provider, [step("research", wa, ta)], budget_usd=0.5)
    c.post(f"/api/workflows/{wf['id']}/start")
    wait_wf(c, wf["id"], lambda w: w["steps"][0]["status"] == "awaiting_approval")
    approve_pending(c)
    done = wait_wf(c, wf["id"], lambda w: w["status"] == "completed")
    r = put_budget(c, wf["id"], 1.0)
    assert r.status_code == 409 and done["budget_info"]["editable"] is False
    assert wf_get(c, wf["id"])["budget_usd"] == 0.5 and hist(c, wf["id"]) == []
    wf2 = create(c, provider, [step("r2", wa, ta)], budget_usd=0.5)
    c.post(f"/api/workflows/{wf2['id']}/cancel")
    assert put_budget(c, wf2["id"], 1.0).status_code == 409 and hist(c, wf2["id"]) == []
    assert c.put(f"/api/workflows/{wf2['id']}/plan", json={"steps": [step("r2", wa, ta)], "budget_usd": 1.0}).status_code == 409


def test_budget_shortage_refuses_step_and_increase_takes_effect_immediately(client, provider):
    setup_llm(provider)
    real = client.app_state.llm.provider.complete

    async def slow(messages, *, json_mode, max_tokens, purpose):
        if purpose == "worker_draft":
            await asyncio.sleep(0.5)
        return await real(messages, json_mode=json_mode, max_tokens=max_tokens, purpose=purpose)

    client.app_state.llm.provider.complete = slow
    a, b = mk(client, "직원 A", approval=False), mk(client, "직원 B", approval=False, materials=False)
    wf = create(client, provider, [step("a", *a), step("b", *b, ["a"])], budget_usd=0.5)
    wid = wf["id"]
    client.post(f"/api/workflows/{wid}/start")
    wait_wf(client, wid, lambda w: by_key(w)["a"]["status"] == "running")
    from gyunexus.models import Workflow
    with client.app_state.db.session() as s:  # 이전 설정에서 남은 낮은 예산 상태를 만든다(검증 우회)
        s.get(Workflow, wid).budget_usd = wf["planning_cost_usd"] + 0.02
    stuck = wait_wf(client, wid, lambda w: w["status"] == "failed")
    assert by_key(stuck)["a"]["status"] == "completed" and by_key(stuck)["b"]["error_kind"] == "workflow_budget"  # 예산 부족으로 시작 거부
    drafts = provider.calls.count("worker_draft")
    assert drafts == 1 and len(client.get("/api/workers/runs").json()) == 1
    assert put_budget(client, wid, 0.5).status_code == 200  # 증액 -> 거부됐던 단계가 즉시 다시 실행된다(수동 재시도 불필요)
    done = wait_wf(client, wid, lambda w: w["status"] == "completed")
    assert by_key(done)["b"]["attempts"] == 1 and provider.calls.count("worker_draft") == 2
    assert [x["status"] for x in done["budget_history"]] == ["failed"] and done["budget_history"][0]["source"] == "budget"


def test_budget_change_waits_for_the_workflow_lock(two, provider):
    c, (wa, ta), (wb, tb) = two
    wf = create(c, provider, [step("research", wa, ta)], budget_usd=0.5)
    wid = wf["id"]
    svc = c.app_state.workflows

    async def scenario():
        async with svc._lock(wid):  # 단계 시작(advance)이 락을 잡고 있는 상황
            task = asyncio.create_task(svc.update_meta(wid, budget=0.9))
            await asyncio.sleep(0.2)
            assert not task.done()  # 락이 풀릴 때까지 예산 변경은 대기한다
            assert svc.get(wid).budget_usd == 0.5
        await task

    c.portal.call(scenario)
    assert wf_get(c, wid)["budget_usd"] == 0.9 and len(hist(c, wid)) == 1


def test_concurrent_budget_changes_and_advances_stay_consistent(client, provider):
    setup_llm(provider)
    real = client.app_state.llm.provider.complete

    async def slow(messages, *, json_mode, max_tokens, purpose):
        if purpose == "worker_draft":
            await asyncio.sleep(0.8)  # 단계가 실행 중인 동안 예산 변경이 몰리게 한다
        return await real(messages, json_mode=json_mode, max_tokens=max_tokens, purpose=purpose)

    client.app_state.llm.provider.complete = slow
    a = mk(client, "직원 A", approval=False)
    wf = create(client, provider, [step("a", *a)], budget_usd=0.5)
    wid = wf["id"]
    svc = client.app_state.workflows
    client.post(f"/api/workflows/{wid}/start")
    values = [0.4, 0.6, 0.7, 0.3, 0.9, 0.8]

    async def storm():
        res = await asyncio.gather(*(svc.update_meta(wid, budget=v) for v in values), *(svc.advance(wid) for _ in range(6)), return_exceptions=True)
        return [r for r in res if isinstance(r, Exception)]

    errors = client.portal.call(storm)
    done = wait_wf(client, wid, lambda w: w["status"] == "completed")
    assert all(isinstance(e, WorkflowError) for e in errors)  # 충돌로 인한 예외가 아니라, 검증 규칙에 따른 거부만 가능
    h = done["budget_history"][::-1]
    assert h and h[0]["old_usd"] == 0.5 and all(h[i]["new_usd"] == h[i + 1]["old_usd"] for i in range(len(h) - 1))  # 변경 이력이 끊김 없이 이어진다
    assert done["budget_usd"] == h[-1]["new_usd"] and len(client.get("/api/workers/runs").json()) == 1  # 단계는 한 번만 실행


def test_plan_edit_can_change_budget_atomically(two, provider):
    c, (wa, ta), (wb, tb) = two
    wf = create(c, provider, [step("research", wa, ta), step("write", wb, tb, ["research"])], budget_usd=0.5)
    wid = wf["id"]
    steps = [step("research", wa, ta, directive="수정"), step("write", wb, tb, ["research"])]
    ok = c.put(f"/api/workflows/{wid}/plan", json={"steps": steps, "budget_usd": 0.9})
    assert ok.status_code == 200 and ok.json()["budget_usd"] == 0.9 and by_key(ok.json())["research"]["directive"] == "수정"
    assert [(x["old_usd"], x["new_usd"], x["source"]) for x in ok.json()["budget_history"]] == [(0.5, 0.9, "plan")]
    before = wf_get(c, wid)
    bad = c.put(f"/api/workflows/{wid}/plan", json={"steps": [step("research", wa, ta, directive="되면 안 됨"), step("write", wb, tb, ["research"])], "budget_usd": 0.05})
    assert bad.status_code == 422 and "예산" in bad.text  # 예산 검증 실패 -> 계획도 바뀌지 않는다
    after = wf_get(c, wid)
    assert after["budget_usd"] == 0.9 and after["plan_version"] == before["plan_version"] and by_key(after)["research"]["directive"] == "수정" and len(after["budget_history"]) == 1
    assert c.put(f"/api/workflows/{wid}/plan", json={"steps": steps, "budget_usd": 99}).status_code == 422
    # 계획을 키우면서 예산도 올려야 하는 경우: 새 예산 기준으로 검증된다
    c.put(f"/api/workflows/{wid}", json={"budget_usd": wf_get(c, wid)["budget_info"]["min_budget_usd"]})
    more = steps + [step("extra", wa, ta, ["write"])]
    assert c.put(f"/api/workflows/{wid}/plan", json={"steps": more}).status_code == 422
    assert c.put(f"/api/workflows/{wid}/plan", json={"steps": more, "budget_usd": 1.0}).status_code == 200


def test_budget_change_is_allowed_while_paused_or_failed(client, provider):
    setup_llm(provider)
    a = mk(client, "직원 A", approval=False)
    provider.overrides["worker_draft"] = lambda m: (_ for _ in ()).throw(LLMError("down"))
    wf = create(client, provider, [step("a", *a)], budget_usd=0.5)
    client.post(f"/api/workflows/{wf['id']}/start")
    failed = wait_wf(client, wf["id"], lambda w: w["status"] == "failed")
    assert failed["budget_info"]["editable"] is True and failed["budget_info"]["required_usd"] == 0.0  # 실패한 단계는 다시 실행할 때 시작 직전 예산 확인
    assert put_budget(client, wf["id"], 0.2).status_code == 200 and put_budget(client, wf["id"], 1.0).status_code == 200
    assert [x["status"] for x in hist(client, wf["id"])] == ["failed", "failed"]

# ---------------------------------------------------------------- 누적 비용: 계획 수정으로 단계가 삭제·교체되어도 실제 발생한 비용은 유지된다

def true_total(c, wid):
    """단계 목록과 무관하게, 이 워크플로에서 실제 발생한 모든 비용(계획 생성 + 모든 실행)을 실행 기록에서 직접 합산한다."""
    wf = wf_get(c, wid)
    runs = c.get("/api/workers/runs?limit=200").json()
    return round(wf["planning_cost_usd"] + sum(r["cost_usd"] for r in runs if r.get("workflow_id") == wid), 6)


def flaky_draft(messages):
    """'불량' 직원은 항상 너무 짧은 초안을 내 검증에 실패한다(LLM 호출 비용은 발생)."""
    if "불량" in messages[0]["content"]:
        return good_draft(body="# 짧음\n내용")
    return good_draft()


def costly_failure_setup(c, provider):
    provider.overrides["worker_draft"] = flaky_draft
    provider.overrides["worker_review"] = good_review
    good = mk(c, "정상 직원", approval=False)
    bad = mk(c, "불량 직원", approval=False)
    return good, bad


def test_deleting_a_step_keeps_its_cost_in_the_cumulative_total_and_budget_checks(client, provider):
    c = client
    good, bad = costly_failure_setup(c, provider)
    wf = create(c, provider, [step("a", *good), step("x", *bad)], budget_usd=1.0)
    wid = wf["id"]
    c.post(f"/api/workflows/{wid}/start")
    failed = wait_wf(c, wid, lambda w: w["status"] == "failed")  # 실행 비용 발생(실패한 단계 포함)
    sx = by_key(failed)["x"]
    assert sx["status"] == "failed" and sx["cost_usd"] > 0 and failed["removed_steps"] == []
    before = failed["cost_usd"]
    assert before == pytest.approx(true_total(c, wid)) and before > failed["planning_cost_usd"] + by_key(failed)["a"]["cost_usd"]
    x_runs = [r for r in c.get("/api/workers/runs").json() if r["workflow_step_id"] == sx["id"]]
    assert x_runs and x_runs[0]["artifact"] is not None
    # 계획 수정: 실패한 단계 삭제
    edited = c.put(f"/api/workflows/{wid}/plan", json={"steps": [step("a", *good)]})
    assert edited.status_code == 200
    after = wf_get(c, wid)
    assert [s["key"] for s in after["steps"]] == ["a"]
    assert after["cost_usd"] == pytest.approx(before) == pytest.approx(true_total(c, wid))  # 누적 비용 유지(줄지 않고, 이중 집계도 없음)
    assert after["budget_info"]["spent_usd"] == pytest.approx(before) and after["budget_info"]["removed_steps_usd"] == pytest.approx(sx["cost_usd"])
    assert [r["run_id"] for r in after["removed_steps"][0]["runs"]] == [r["id"] for r in x_runs]  # 삭제된 단계의 비용이 어느 실행에서 나왔는지 보인다
    # 이력·Artifact 계보 보존
    assert len(c.get("/api/workers/runs").json()) == len(x_runs) + 1
    art = x_runs[0]["artifact"]["id"]
    assert c.get(f"/api/artifacts/{art}").status_code == 200 and c.get(f"/api/artifacts/{art}/lineage").json()["run_id"] == x_runs[0]["id"]
    # 예산 검사와 예산 변경 최소 금액이 같은 기준(삭제된 단계의 비용 포함)을 쓴다
    spent_without_removed = before - sx["cost_usd"]
    mid = (spent_without_removed + before) / 2
    low = put_budget(c, wid, mid)
    assert low.status_code == 422 and "이미 사용한 비용" in low.text  # 삭제된 단계 비용을 빼면 통과하던 값이 거부된다
    assert put_budget(c, wid, before).status_code == 200 and after["budget_info"]["min_budget_usd"] == pytest.approx(before)
    hist_row = wf_get(c, wid)["budget_history"][0]
    assert hist_row["spent_usd"] == pytest.approx(before)
    # 목록(대시보드용) 비용도 같은 값
    row = [w for w in c.get("/api/workflows").json() if w["id"] == wid][0]
    assert row["cost_usd"] == pytest.approx(before)


def test_retry_replace_and_delete_re_add_never_lose_or_double_count_costs(client, provider):
    c = client
    good, bad = costly_failure_setup(c, provider)
    wf = create(c, provider, [step("a", *good), step("x", *bad)], budget_usd=2.0)
    wid = wf["id"]
    c.post(f"/api/workflows/{wid}/start")
    wait_wf(c, wid, lambda w: w["status"] == "failed")
    one = wf_get(c, wid)
    assert c.post(f"/api/workflows/{wid}/steps/x/retry").status_code == 200  # 실패 후 재시도: 두 번째 시도도 비용 발생
    two = wait_wf(c, wid, lambda w: w["status"] == "failed" and by_key(w)["x"]["attempts"] == 2 and by_key(w)["x"]["status"] == "failed")
    assert by_key(two)["x"]["cost_usd"] > by_key(one)["x"]["cost_usd"] and two["cost_usd"] == pytest.approx(true_total(c, wid))
    # 단계 교체: 실패한 단계의 직원을 바꿔 다시 실행(이전 시도의 비용은 그대로)
    cost_before_replace = two["cost_usd"]
    assert c.put(f"/api/workflows/{wid}/plan", json={"steps": [step("a", *good), step("x", *good)]}).status_code == 200
    mid = wf_get(c, wid)
    assert mid["cost_usd"] == pytest.approx(cost_before_replace) and mid["status"] == "paused"
    c.post(f"/api/workflows/{wid}/resume")
    done = wait_wf(c, wid, lambda w: w["status"] == "completed")
    assert done["cost_usd"] > cost_before_replace and done["cost_usd"] == pytest.approx(true_total(c, wid))
    assert sum(s["cost_usd"] for s in done["steps"]) + done["planning_cost_usd"] == pytest.approx(done["cost_usd"])  # 삭제된 단계가 없을 때는 단계 합 + 계획 = 누적
    # 같은 key 를 삭제했다가 다시 추가해도(새 단계 행) 이전 실행의 비용은 한 번만 센다
    wf2 = create(c, provider, [step("a", *good), step("x", *bad)], budget_usd=2.0)
    c.post(f"/api/workflows/{wf2['id']}/start")
    f2 = wait_wf(c, wf2["id"], lambda w: w["status"] == "failed")
    old_x = by_key(f2)["x"]["cost_usd"]
    r1 = c.put(f"/api/workflows/{wf2['id']}/plan", json={"steps": [step("a", *good)]})
    assert r1.status_code == 200, r1.text
    r2 = c.put(f"/api/workflows/{wf2['id']}/plan", json={"steps": [step("a", *good), step("x", *good)]})  # 같은 key, 새 직원
    assert r2.status_code == 200, r2.text
    c.post(f"/api/workflows/{wf2['id']}/resume")
    d2 = wait_wf(c, wf2["id"], lambda w: w["status"] == "completed")
    assert by_key(d2)["x"]["cost_usd"] < d2["cost_usd"] and d2["removed_steps"][0]["cost_usd"] == pytest.approx(old_x)  # 새 x 의 비용과 삭제된 x 의 비용이 분리
    assert d2["cost_usd"] == pytest.approx(true_total(c, wf2["id"])) == pytest.approx(d2["planning_cost_usd"] + sum(s["cost_usd"] for s in d2["steps"]) + d2["budget_info"]["removed_steps_usd"])


def test_costs_stay_exact_under_concurrent_runs_plan_edits_and_budget_changes(client, provider):
    c = client
    good, bad = costly_failure_setup(c, provider)
    real = c.app_state.llm.provider.complete

    async def slow(messages, *, json_mode, max_tokens, purpose):
        if purpose == "worker_draft":
            await asyncio.sleep(0.5)
        return await real(messages, json_mode=json_mode, max_tokens=max_tokens, purpose=purpose)

    c.app_state.llm.provider.complete = slow
    g2 = mk(c, "정상 직원2", approval=False)
    wf = create(c, provider, [step("a", *good), step("b", *g2), step("x", *bad)], budget_usd=2.0)
    wid = wf["id"]
    c.post(f"/api/workflows/{wid}/start")
    wait_wf(c, wid, lambda w: by_key(w)["a"]["status"] == "running")  # 병렬 실행 중
    svc = c.app_state.workflows

    async def concurrent():
        await asyncio.gather(svc.update_meta(wid, budget=1.5), *(svc.advance(wid) for _ in range(4)), return_exceptions=True)

    c.portal.call(concurrent)
    stuck = wait_wf(c, wid, lambda w: w["status"] == "failed")
    assert stuck["cost_usd"] == pytest.approx(true_total(c, wid))
    c.put(f"/api/workflows/{wid}/plan", json={"steps": [step("a", *good), step("b", *g2)]})  # 실패한 x 삭제
    after = wf_get(c, wid)
    assert after["cost_usd"] == pytest.approx(stuck["cost_usd"]) == pytest.approx(true_total(c, wid))
    c.post(f"/api/workflows/{wid}/resume")
    done = wait_wf(c, wid, lambda w: w["status"] == "completed")
    assert done["cost_usd"] == pytest.approx(true_total(c, wid)) and done["budget_info"]["spent_usd"] == pytest.approx(done["cost_usd"])


def test_legacy_runs_without_workflow_id_are_counted_once_and_backfilled_from_slot_keys(client, provider):
    c = client
    good, bad = costly_failure_setup(c, provider)
    wf = create(c, provider, [step("a", *good), step("x", *bad)], budget_usd=1.0)
    wid = wf["id"]
    c.post(f"/api/workflows/{wid}/start")
    failed = wait_wf(c, wid, lambda w: w["status"] == "failed")
    total = failed["cost_usd"]
    svc = c.app_state.workflows
    from gyunexus.models import WorkerRun
    with c.app_state.db.session() as s:  # 이전 버전 데이터 상황: 실행 기록에 workflow_id 가 없다
        for r in s.query(WorkerRun):
            r.workflow_id = None
    assert wf_get(c, wid)["cost_usd"] == pytest.approx(total)  # 단계가 남아 있으면 backfill 전에도 비용이 빠지지 않고 두 번 세어지지도 않는다
    c.put(f"/api/workflows/{wid}/plan", json={"steps": [step("a", *good)]})
    from gyunexus.models import WorkflowStep
    with c.app_state.db.session() as s_:  # 이전 버전 상황: 삭제된 단계 행 자체가 사라져 비용 연결이 끊긴다
        for row in s_.query(WorkflowStep).filter(WorkflowStep.status == "removed").all():
            s_.delete(row)
    lost = wf_get(c, wid)["cost_usd"]
    assert lost < total  # backfill 전: 삭제된 단계의 비용이 보이지 않는다(이전 버전의 결함 재현)
    assert svc.backfill_run_workflow_ids() >= 1  # 시작 시 보정: slot_key 로 소속 워크플로 복원
    assert wf_get(c, wid)["cost_usd"] == pytest.approx(total) and svc.backfill_run_workflow_ids() == 0  # 비용 복원, 다시 실행해도 변화 없음(멱등)
    assert len(c.get("/api/workers/runs").json()) == 2  # 실행 이력은 지우거나 바꾸지 않았다


def test_server_start_backfills_legacy_run_costs_without_touching_user_data(settings, provider):
    from gyunexus.models import WorkerRun, WorkflowStep
    provider.overrides["worker_draft"] = flaky_draft
    provider.overrides["worker_review"] = good_review
    with TestClient(create_app(settings, provider, run_scheduler=False)) as c:
        c.app_state = c.app.state.svc
        good, bad = mk(c, "정상 직원", approval=False), mk(c, "불량 직원", approval=False)
        wf = create(c, provider, [step("a", *good), step("x", *bad)], budget_usd=1.0)
        wid = wf["id"]
        c.post(f"/api/workflows/{wid}/start")
        total = wait_wf(c, wid, lambda w: w["status"] == "failed")["cost_usd"]
        runs_before = [(r["id"], r["status"], r["cost_usd"]) for r in c.get("/api/workers/runs").json()]
        c.put(f"/api/workflows/{wid}/plan", json={"steps": [step("a", *good)]})
        with c.app_state.db.session() as s:  # 이전 버전이 남긴 데이터 모양: 삭제된 단계 행이 없고 실행에 workflow_id 가 비어 있다
            s.query(WorkflowStep).filter(WorkflowStep.status == "removed").delete()
            for r in s.query(WorkerRun):
                r.workflow_id = None
        assert wf_get(c, wid)["cost_usd"] < total
    with TestClient(create_app(settings, provider, run_scheduler=False)) as c2:  # 서버 재시작: 시작 시 보정
        assert wf_get(c2, wid)["cost_usd"] == pytest.approx(total)
        assert [(r["id"], r["status"], r["cost_usd"]) for r in c2.get("/api/workers/runs").json()] == runs_before  # 실행 이력·비용 기록은 그대로


def test_every_budget_path_uses_the_same_cumulative_cost(client, provider):
    c = client
    good, bad = costly_failure_setup(c, provider)
    wf = create(c, provider, [step("a", *good), step("x", *bad)], budget_usd=1.0)
    wid = wf["id"]
    c.post(f"/api/workflows/{wid}/start")
    wait_wf(c, wid, lambda w: w["status"] == "failed")
    c.put(f"/api/workflows/{wid}/plan", json={"steps": [step("a", *good)]})
    d = wf_get(c, wid)
    svc = c.app_state.workflows
    spent_proj, _ = svc._projection(wid)
    listed = [w for w in c.get("/api/workflows").json() if w["id"] == wid][0]["cost_usd"]
    values = {"detail": d["cost_usd"], "info": d["budget_info"]["spent_usd"], "projection": round(spent_proj, 6), "list": listed, "spent": round(svc._spent(wid), 6), "truth": true_total(c, wid)}
    assert len({round(v, 6) for v in values.values()}) == 1, values
    msg = put_budget(c, wid, d["cost_usd"] * 0.9).text
    assert f"${d['cost_usd']:.4f}" in msg  # 예산 변경 거부 메시지의 '이미 사용한 비용'도 같은 값


def test_orchestrator_has_no_hardcoded_worker_or_domain_logic():
    src = pathlib.Path(__file__).parent.parent.joinpath("gyunexus", "workflows.py").read_text(encoding="utf-8")
    for word in ("뉴스", "블로그", "news", "blog", "rss", "리서처", "콘텐츠 담당"):
        assert word.lower() not in src.lower(), word


# ---------------------------------------------------------------- 계획 생성 실패 복구(예산 증액 후에도 실패 상태가 남던 문제)

def failed_plan(c, provider, wa, ta, wb, tb, budget=0.05, **kw):
    """두 단계 상한 합(0.10)이 예산보다 커서 계획 검증이 예산 때문에 실패하는 워크플로를 만든다."""
    return create(c, provider, [step("research", wa, ta), step("write", wb, tb, ["research"])], budget_usd=budget, **kw)


def plan_calls(provider):
    return provider.calls.count("workflow_plan")


def test_plan_failed_on_budget_recovers_after_increase_without_new_llm_call_then_runs_normally(two, provider):
    c, (wa, ta), (wb, tb) = two
    wf = failed_plan(c, provider, wa, ta, wb, tb)
    wid = wf["id"]
    assert wf["status"] == "planned" and wf["steps"] == [] and wf["plan_state"] == "failed" and wf["start_check"] is None
    pf = wf["plan_failure"]
    assert pf["kind"] == "budget" and "예산 $0.0500" in pf["message"] and pf["has_proposal"] and not pf["stale_budget"] and not wf["error"]
    assert c.post(f"/api/workflows/{wid}/start").status_code == 409  # 단계 없는 실패 계획은 시작할 수 없다
    planning, calls = wf["planning_cost_usd"], plan_calls(provider)
    assert planning > 0 and len(wf["plan_attempts"]) == 1
    assert put_budget(c, wid, 1.0).status_code == 200
    ok = wf_get(c, wid)  # 증액 직후: 보관된 제안을 새 예산으로 재검증해 계획이 복구된다(LLM 재호출 없음)
    assert ok["budget_usd"] == 1.0 and ok["plan_state"] == "ok" and ok["plan_failure"] is None and ok["error"] is None and ok["plan_error"] is None
    assert [s["key"] for s in ok["steps"]] == ["research", "write"] and ok["status"] == "planned" and ok["start_check"]["ok"] is True
    assert plan_calls(provider) == calls and ok["planning_cost_usd"] == planning and ok["id"] == wid
    assert c.get("/api/workers/runs").json() == []  # 복구만으로는 아무것도 실행되지 않는다(자동 시작 없음)
    assert [(a["kind"], a["status"], a["cost_usd"]) for a in ok["plan_attempts"]] == [("auto", "succeeded", 0.0), ("initial", "failed", planning)]  # 과거 실패 기록은 이력으로 남는다
    assert ok["plan_attempts"][1]["budget_usd"] == 0.05 and "예산 $0.0500" in ok["plan_attempts"][1]["error"]
    assert [(h["old_usd"], h["new_usd"]) for h in ok["budget_history"]] == [(0.05, 1.0)]
    assert c.post(f"/api/workflows/{wid}/start").status_code == 200  # 시작은 기존 경로(검증)를 그대로 탄다
    wait_wf(c, wid, lambda w: by_key(w)["research"]["status"] == "awaiting_approval")
    assert approve_pending(c) == 1  # 승인 게이트는 그대로 적용된다
    wait_wf(c, wid, lambda w: by_key(w)["write"]["status"] == "awaiting_approval")
    approve_pending(c)
    done = wait_wf(c, wid, lambda w: w["status"] == "completed")
    assert len(c.get("/api/workers/runs").json()) == 2 and done["cost_usd"] == true_total(c, wid) and done["error"] is None
    assert c.post(f"/api/workflows/{wid}/replan").status_code == 409  # 이미 복구·완료된 워크플로는 다시 만들 수 없다


def test_replan_revalidates_stored_proposal_without_llm_and_reports_still_insufficient_budget(two, provider):
    c, (wa, ta), (wb, tb) = two
    wf = failed_plan(c, provider, wa, ta, wb, tb)
    wid, calls = wf["id"], plan_calls(provider)
    assert put_budget(c, wid, 0.08).status_code == 200  # 증액했지만 아직 모자란다
    still = wf_get(c, wid)
    assert still["plan_state"] == "failed" and "예산 $0.0800" in still["plan_failure"]["message"]  # 메시지는 현재 저장된 예산 기준으로 갱신된다
    assert not still["plan_failure"]["stale_budget"] and still["plan_failure"]["budget_at_failure_usd"] == 0.08
    r = c.post(f"/api/workflows/{wid}/replan")
    assert r.status_code == 422 and "예산 $0.0800" in r.json()["detail"] and plan_calls(provider) == calls  # 재검증만 하고 LLM 은 부르지 않는다
    assert [a["kind"] for a in wf_get(c, wid)["plan_attempts"]] == ["revalidate", "auto", "initial"]
    # 같은 예산에서 사용자가 명시적으로 새 제안을 요청하면 그때만 LLM 을 부른다(비용은 계획 비용에 누적)
    before = wf_get(c, wid)["planning_cost_usd"]
    provider.overrides["workflow_plan"] = plan_json([step("only", wa, ta)])
    r = c.post(f"/api/workflows/{wid}/replan", json={"regenerate": True})
    assert r.status_code == 200 and plan_calls(provider) == calls + 1
    ok = r.json()
    assert ok["plan_state"] == "ok" and [s["key"] for s in ok["steps"]] == ["only"] and ok["planning_cost_usd"] > before and ok["id"] == wid
    assert ok["plan_attempts"][0]["kind"] == "replan" and ok["plan_attempts"][0]["cost_usd"] > 0
    assert round(sum(a["cost_usd"] for a in ok["plan_attempts"]), 6) == ok["planning_cost_usd"]  # 시도별 비용의 합 = 누적 계획 비용
    assert [(h["old_usd"], h["new_usd"]) for h in ok["budget_history"]] == [(0.05, 0.08)]


def test_non_budget_plan_failure_is_not_fixed_by_a_budget_increase_alone(two, provider):
    c, (wa, ta), (wb, tb) = two
    provider.overrides["workflow_plan"] = plan_json([step("a", wa, ta, ["a"])])  # 자기 자신에게 의존: 예산과 무관한 오류
    wf = c.post("/api/workflows", json={"goal": "계속 틀리는 계획", "budget_usd": 0.05}).json()
    wid, calls = wf["id"], plan_calls(provider)
    assert wf["plan_state"] == "failed" and wf["plan_failure"]["kind"] == "invalid"
    assert put_budget(c, wid, 1.0).status_code == 200
    after = wf_get(c, wid)
    assert after["plan_state"] == "failed" and after["steps"] == [] and "자기 자신" in after["plan_failure"]["message"]  # 증액만으로 해소로 보지 않는다
    assert not after["plan_failure"]["stale_budget"] and len(after["plan_attempts"]) == 1 and plan_calls(provider) == calls
    assert c.post(f"/api/workflows/{wid}/start").status_code == 409
    provider.overrides["workflow_plan"] = plan_json([step("a", wa, ta), step("b", wb, tb, ["a"])])  # 원인을 고쳐 다시 제안받으면 복구된다
    r = c.post(f"/api/workflows/{wid}/replan")
    assert r.status_code == 200 and plan_calls(provider) == calls + 1 and r.json()["plan_state"] == "ok" and len(r.json()["steps"]) == 2
    assert c.post(f"/api/workflows/{wid}/replan").status_code == 409  # 복구 뒤 다시 누르면 중복 생성하지 않는다
    assert len(wf_get(c, wid)["steps"]) == 2


def test_manual_plan_save_resolves_plan_failure_and_keeps_history(two, provider):
    c, (wa, ta), (wb, tb) = two
    wf = failed_plan(c, provider, wa, ta, wb, tb)
    wid = wf["id"]
    r = c.put(f"/api/workflows/{wid}/plan", json={"steps": [step("only", wa, ta)], "budget_usd": 0.5})
    assert r.status_code == 200
    ok = wf_get(c, wid)
    assert ok["plan_state"] == "ok" and ok["plan_failure"] is None and [s["key"] for s in ok["steps"]] == ["only"]
    assert [a["kind"] for a in ok["plan_attempts"]] == ["manual", "initial"] and [h["source"] for h in ok["budget_history"]] == ["plan"]


def test_valid_plan_blocked_only_by_budget_is_reported_as_start_check_not_as_plan_failure(two, provider):
    c, (wa, ta), (wb, tb) = two
    wf = create(c, provider, [step("research", wa, ta), step("write", wb, tb, ["research"])], budget_usd=0.12)
    wid = wf["id"]
    assert wf["plan_state"] == "ok" and wf["plan_failure"] is None and wf["start_check"]["ok"] is True
    assert c.put(f"/api/workers/tasks/{ta['id']}", json={"max_cost_usd": 0.2}).status_code == 200  # 업무·직원 상한이 올라 이제 예산이 모자라다
    assert c.put(f"/api/workers/{wa['id']}", json={"max_cost_usd": 0.2}).status_code == 200
    blocked = wf_get(c, wid)
    assert blocked["plan_state"] == "ok" and blocked["plan_failure"] is None and len(blocked["steps"]) == 2  # 계획은 유효하다
    assert blocked["start_check"]["ok"] is False and blocked["start_check"]["kind"] == "budget" and "예산 $0.1200" in blocked["start_check"]["error"]
    assert c.post(f"/api/workflows/{wid}/start").status_code == 422  # 시작 직전 검증은 항상 현재 저장된 예산을 쓴다
    assert put_budget(c, wid, 1.0).status_code == 200
    assert wf_get(c, wid)["start_check"]["ok"] is True and c.post(f"/api/workflows/{wid}/start").status_code == 200


def test_plan_failure_state_and_history_are_consistent_after_restart(settings, provider):
    setup_llm(provider)
    with TestClient(create_app(settings, provider, run_scheduler=False)) as c:
        (wa, ta), (wb, tb) = mk(c, "조사 직원"), mk(c, "작성 직원", materials=False)
        wf = failed_plan(c, provider, wa, ta, wb, tb)
        wid = wf["id"]
    calls = plan_calls(provider)
    with TestClient(create_app(settings, provider, run_scheduler=False)) as c2:
        again = wf_get(c2, wid)  # 재시작 후에도 같은 상태·같은 메시지·보관된 제안
        assert again["plan_state"] == "failed" and again["plan_failure"] == wf["plan_failure"] and len(again["plan_attempts"]) == 1
        assert put_budget(c2, wid, 1.0).status_code == 200
        ok = wf_get(c2, wid)  # 재시작 뒤 증액해도 DB 에 남은 제안으로 복구된다
        assert ok["plan_state"] == "ok" and len(ok["steps"]) == 2 and plan_calls(provider) == calls
    with TestClient(create_app(settings, provider, run_scheduler=False)) as c3:
        final = wf_get(c3, wid)
        assert final["plan_state"] == "ok" and final["plan_failure"] is None and final["error"] is None and [a["kind"] for a in final["plan_attempts"]] == ["auto", "initial"]
        assert c3.get("/api/workers/runs").json() == []


def test_legacy_plan_failure_is_migrated_without_touching_user_data_and_can_be_replanned(settings, provider):
    setup_llm(provider)
    from gyunexus.models import Workflow, WorkflowBudgetChange
    with TestClient(create_app(settings, provider, run_scheduler=False)) as c:
        (wa, ta), (wb, tb) = mk(c, "조사 직원"), mk(c, "작성 직원", materials=False)
        wf = create(c, provider, [step("only", wa, ta)], budget_usd=1.0)
        wid = wf["id"]
        msg = "예상 최대 비용 $0.6410(계획 $0.0010 + 단계 상한 합 $0.6400)가 예산 $0.5000을 넘습니다"
        with c.app.state.svc.db.session() as s:  # 이전 버전이 남긴 모양: 실패 사유가 error/plan_notes 에만 있고 단계는 없다
            from gyunexus.models import WorkflowStep
            from gyunexus.models import WorkflowPlanAttempt
            s.query(WorkflowStep).filter(WorkflowStep.workflow_id == wid).delete()
            s.query(WorkflowPlanAttempt).filter(WorkflowPlanAttempt.workflow_id == wid).delete()  # 이전 버전에는 시도 이력 테이블이 없었다
            w = s.get(Workflow, wid)
            w.plan_notes, w.error, w.planning_cost_usd = f"설명\n[계획 검증 실패] {msg}", msg, 0.001
            s.add(WorkflowBudgetChange(workflow_id=wid, old_usd=0.5, new_usd=1.0, status="planned", source="budget"))
    for _ in range(2):  # 두 번 시작해도(재실행) 결과가 같다
        with TestClient(create_app(settings, provider, run_scheduler=False)) as c2:
            d = wf_get(c2, wid)
            assert d["plan_state"] == "failed" and d["error"] is None and d["plan_notes"] == "설명" and d["steps"] == []
            assert d["plan_failure"]["stale_budget"] is True and d["plan_failure"]["budget_at_failure_usd"] == 0.5 and not d["plan_failure"]["has_proposal"]
            assert [(a["kind"], a["source"]) for a in d["plan_attempts"]] == [("initial", "legacy")] and d["planning_cost_usd"] == 0.001
            assert len(d["budget_history"]) == 1
    calls = plan_calls(provider)
    provider.overrides["workflow_plan"] = plan_json([step("only", wa, ta), step("write", wb, tb, ["only"])])
    with TestClient(create_app(settings, provider, run_scheduler=False)) as c3:
        r = c3.post(f"/api/workflows/{wid}/replan")  # 제안이 없으므로 현재 예산($1.00) 기준으로 새로 만든다
        assert r.status_code == 200 and plan_calls(provider) == calls + 1
        ok = r.json()
        assert ok["id"] == wid and ok["plan_state"] == "ok" and len(ok["steps"]) == 2 and ok["planning_cost_usd"] > 0.001 and ok["plan_failure"] is None
        assert [a["kind"] for a in ok["plan_attempts"]] == ["replan", "initial"] and len(ok["budget_history"]) == 1
