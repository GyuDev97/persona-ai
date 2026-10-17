"""사후(post-hoc) 점검. PROTOCOL.md 이후에 추가한 것이며 결과 보고서에 '사후 점검'으로 표시한다.

1) union: 사실 주제에서 평가자에게 번들뿐 아니라 B/C가 직접 조회한 증거까지 합쳐 제공(번들과 다른 시간대를 조회한 B/C가 오류로 오판되는 문제 점검)
2) xjudge <model>: 다른 평가자 모델로 같은 후보를 다시 평가(평가자 의존성 점검)
"""

import asyncio
import json
import pathlib
import random
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import run_experiment as ex
from run_experiment import RAW, JUDGE_DIR, METER, MeteredProvider, judge_set, present, TOPICS, brief_for
from gyunexus.config import Settings

ex.PRICES["gpt-4.1"] = (2.0, 8.0)
ex.PRICES["gpt-4o-mini"] = (0.15, 0.60)
TOPIC = {t["id"]: t for t in TOPICS}


def load_cells():
    recs = {}
    for p in sorted(RAW.glob("*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        recs[(r["topic"], r["method"])] = r
    return recs


async def run(mode: str, model: str | None):
    key = Settings().openai_api_key
    recs = load_cells()
    if mode == "union":
        jp = MeteredProvider(ex.JUDGE_MODEL, key)
        targets = [t for t in TOPIC if TOPIC[t]["bundle"]]
    else:
        jp = MeteredProvider(model, key)
        targets = list(TOPIC)
    for tid in targets:
        out = JUDGE_DIR / (f"{tid}__compare_union.json" if mode == "union" else f"{tid}__compare_{model}.json")
        have = {m: recs[(tid, m)] for m in ["A", "B", "C"] if (tid, m) in recs and recs[(tid, m)]["ok"] and recs[(tid, m)]["norm"]}
        if out.exists() or len(have) < 2:
            continue
        if METER.spent >= ex.HARD_CAP:
            print("[중단] 예산 도달")
            break
        ex.LABEL.set(f"judge:{mode}:{tid}")
        bundle = recs[(tid, "A")].get("bundle", {}).get("text", "")
        extra = ""
        if mode == "union":
            seen = {bundle}
            for m in ("B", "C"):
                ev = recs[(tid, m)]["raw"].get("evidence", [])
                txt = "\n".join(f"[{m}가 직접 조회한 증거 E{e['id']}] ({e['tool']}) {e['summary']}" + "".join(f"\n   ⚠ {f['text']}" for f in e["flags"]) for e in ev)
                extra += ("\n" + txt) if txt else ""
            bundle = bundle + "\n(아래는 다중 에이전트 방식이 같은 도구로 직접 조회한 추가 증거입니다. 번들과 시간대·장소가 다를 수 있으나 모두 실제 도구 결과입니다)" + extra
        methods = list(have)
        rng = random.Random(f"order-{tid}")  # 원 평가와 같은 순서
        order1 = methods[:]
        rng.shuffle(order1)
        orders = [order1, order1[::-1]] if mode == "union" or model == "gpt-4o-mini" else [order1]
        cands = {m: present(have[m]["norm"]) for m in methods}
        res = []
        for order in orders:
            try:
                res.append({"order": order, "result": await judge_set(TOPIC[tid], cands, bundle, order, jp)})
            except Exception as e:
                res.append({"order": order, "error": str(e)[:200]})
        out.write_text(json.dumps({"topic": tid, "orders": res, "methods": methods, "mode": mode, "model": jp.model}, ensure_ascii=False, indent=1), encoding="utf-8")
        METER.save()
        print(f"{mode} {model or ''} {tid} done | 누적 ${METER.spent:.4f}", flush=True)
    METER.save()


if __name__ == "__main__":
    mode = sys.argv[1]
    asyncio.run(run(mode, sys.argv[2] if len(sys.argv) > 2 else None))
    print(f"누적 ${METER.spent:.4f}")
