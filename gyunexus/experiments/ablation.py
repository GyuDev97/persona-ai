"""사후 절제 실험(post-hoc): D = B 파이프라인에서 Critic만 뺀 것. Critic의 기여를 분리해 보기 위한 소규모 점검.

플래너 결과에서 critic을 제거하는 것 외에는 B와 같다(같은 모델, 같은 배경 자료, 같은 종료 로직). 소프트웨어/비사실 주제 8개만 실행한다.
"""

import asyncio
import json
import pathlib
import random
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import run_experiment as ex
from run_experiment import (JUDGE_DIR, METER, RAW, MeteredProvider, collect, judge_set, make_svc, normalize_multi, objective_metrics, present,
                            TOPICS, brief_for)
from gyunexus.agents import orchestrator as orch_mod
from gyunexus.config import Settings

ex.PRICES["gpt-4.1-mini"] = (0.40, 1.60)
IDS = ["arch1", "arch2", "collab1", "collab2", "dev1", "asst1", "proj1", "proj3"]
TOPIC = {t["id"]: t for t in TOPICS}


def no_critic_plan(real):
    def plan(title, rationale, llm_data, enabled):
        p = real(title, rationale, llm_data, enabled)
        p["participants"] = [a for a in p["participants"] if a != "critic"]
        p["reasons"]["critic"] = {"selected": False, "reason": "[절제 실험] Critic 제거", "by": "ablation"}
        return p

    return plan


async def run_D(topic, provider):
    real = orch_mod.plan_participants
    orch_mod.plan_participants = no_critic_plan(real)
    try:
        svc = make_svc(provider)
        brief = brief_for(topic)
        orig_plan = svc.orchestrator._plan

        async def plan(title, rationale, autonomous):
            p = await orig_plan(title, rationale, autonomous)
            p["goal"] = f"{p['goal']}\n\n[배경 자료]\n{brief}"
            return p

        svc.orchestrator._plan = plan
        tid = svc.orchestrator.enqueue_topic(topic["title"], source="manual")
        svc.orchestrator.start(trigger="manual", topic_id=tid)
        await asyncio.wait_for(svc.orchestrator.wait(), 900)
        return collect(svc)
    finally:
        orch_mod.plan_participants = real


async def main():
    key = Settings().openai_api_key
    gp, jp = MeteredProvider(ex.GEN_MODEL, key), MeteredProvider(ex.JUDGE_MODEL, key)
    for tid in IDS:
        path = RAW / f"{tid}__D.json"
        if path.exists():
            continue
        if METER.spent >= ex.HARD_CAP - 0.06:
            print("[중단] 예산")
            break
        ex.LABEL.set(f"{tid}:D")
        t0 = time.perf_counter()
        rec = {"topic": tid, "method": "D", "ok": True, "error": None}
        try:
            raw = await run_D(TOPIC[tid], gp)
            norm = normalize_multi(raw)
            rec.update(raw=raw, norm=norm, metrics=objective_metrics(norm, []))
            if raw.get("debate") is None or raw["debate"]["status"] != "completed":
                rec["ok"], rec["error"] = False, (raw.get("debate") or {}).get("error") or "not completed"
        except Exception as e:
            rec.update(ok=False, error=f"{type(e).__name__}: {e}"[:300], raw={}, norm=None, metrics=None)
        rec["secs"] = round(time.perf_counter() - t0, 2)
        rec["usage"] = METER.cell(f"{tid}:D")
        path.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        METER.save()
        print(f"{tid} D ok={rec['ok']} {rec['secs']}s ${rec['usage']['cost_usd']:.4f} | 누적 ${METER.spent:.4f}", flush=True)
    # 평가: A, B, D 블라인드 2순서
    for tid in IDS:
        out = JUDGE_DIR / f"{tid}__compare_ablation.json"
        cells = {}
        for m in ("A", "B", "D"):
            p = RAW / f"{tid}__{m}.json"
            if p.exists():
                r = json.loads(p.read_text(encoding="utf-8"))
                if r["ok"] and r["norm"]:
                    cells[m] = r
        if out.exists() or len(cells) < 3 or METER.spent >= ex.HARD_CAP:
            continue
        ex.LABEL.set(f"judge:ablation:{tid}")
        methods = list(cells)
        order1 = methods[:]
        random.Random(f"abl-{tid}").shuffle(order1)
        cands = {m: present(cells[m]["norm"]) for m in methods}
        res = []
        for order in (order1, order1[::-1]):
            try:
                res.append({"order": order, "result": await judge_set(TOPIC[tid], cands, "", order, jp)})
            except Exception as e:
                res.append({"order": order, "error": str(e)[:200]})
        out.write_text(json.dumps({"topic": tid, "orders": res, "methods": methods, "mode": "ablation"}, ensure_ascii=False, indent=1), encoding="utf-8")
        METER.save()
        print(f"judge ablation {tid} | 누적 ${METER.spent:.4f}", flush=True)
    METER.save()


if __name__ == "__main__":
    asyncio.run(main())
    print(f"누적 ${METER.spent:.4f}")
