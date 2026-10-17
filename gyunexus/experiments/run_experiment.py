"""멀티 에이전트 협업 품질 비교 실험 실행기. 단계: gen(생성) -> judge(평가) -> (analyze.py).

사용: python run_experiment.py gen [--only id1,id2]  /  python run_experiment.py judge
결과는 experiments/results/ 에 보존한다(raw/*.json, meter.json, judge/*.json).
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import logging
import pathlib
import random
import re
import sys
import tempfile
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.stdout.reconfigure(encoding="utf-8")
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from sqlalchemy import select  # noqa: E402

from gyunexus.agents.evidence import evidence_flags, evidence_summary, find_conflicts as rule_find_conflicts  # noqa: E402
from gyunexus.agents.ledger import Ledger  # noqa: E402
from gyunexus.config import Settings  # noqa: E402
from gyunexus.llm import Completion, LLMError, OpenAIProvider  # noqa: E402
from gyunexus.main import build_services  # noqa: E402
from gyunexus.models import ActivityLog, Debate, DebateMessage, Evidence, Idea, Topic  # noqa: E402

from hybrid import HybridOrchestrator, REVIEW_CONFLICT_SYSTEM, conflict_prompt, hybrid_patches  # noqa: E402
from topics import SEED_MEMORIES, TOPICS, brief_for  # noqa: E402

logging.disable(logging.CRITICAL)  # 키·내용이 콘솔 로그에 섞이지 않게 한다(기록은 결과 파일과 임시 DB)
RES = HERE / "results"
RAW = RES / "raw"
JUDGE_DIR = RES / "judge"
GEN_MODEL, JUDGE_MODEL = "gpt-4o-mini", "gpt-4.1-mini"
PRICES = {"gpt-4o-mini": (0.15, 0.60), "gpt-4.1-mini": (0.40, 1.60)}  # USD / 1M tokens (추정 단가)
HARD_CAP, GEN_CAP = 0.48, 0.30
LABEL: contextvars.ContextVar[str] = contextvars.ContextVar("label", default="unlabeled")
CRITERIA = ["accuracy", "specificity", "feasibility", "novelty", "value", "risk_review"]
METHODS = ["A", "B", "C"]


class BudgetStop(LLMError):
    pass


# ---------------------------------------------------------------- 계측

class Meter:
    def __init__(self):
        self.path = RES / "meter.json"
        self.spent, self.calls = 0.0, []
        if self.path.exists():
            d = json.loads(self.path.read_text(encoding="utf-8"))
            self.spent, self.calls = d["spent"], d["calls"]

    def save(self):
        RES.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"spent": self.spent, "calls": self.calls}, ensure_ascii=False), encoding="utf-8")

    def cell(self, label: str) -> dict:
        cs = [c for c in self.calls if c["label"] == label]
        return {"calls": len(cs), "prompt_tokens": sum(c["pt"] for c in cs), "completion_tokens": sum(c["ct"] for c in cs),
                "cost_usd": round(sum(c["cost"] for c in cs), 6), "llm_secs": round(sum(c["secs"] for c in cs), 2),
                "by_purpose": _count([c["purpose"] for c in cs])}


def _count(items):
    out = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return out


METER = Meter()


class MeteredProvider:
    def __init__(self, model: str, api_key: str):
        self.model = model
        self.inner = OpenAIProvider(api_key, model)

    async def complete(self, messages, *, json_mode, max_tokens, purpose) -> Completion:
        if METER.spent >= HARD_CAP:
            raise BudgetStop(f"예산 상한 ${HARD_CAP} 도달")
        t = time.perf_counter()
        c = await self.inner.complete(messages, json_mode=json_mode, max_tokens=max_tokens, purpose=purpose)
        pin, pout = PRICES[self.model]
        cost = (c.prompt_tokens * pin + c.completion_tokens * pout) / 1e6
        METER.spent += cost
        METER.calls.append({"label": LABEL.get(), "purpose": purpose, "model": self.model, "pt": c.prompt_tokens,
                            "ct": c.completion_tokens, "cost": cost, "secs": time.perf_counter() - t})
        return c


async def call_json(provider: MeteredProvider, system: str, user: str, purpose: str, max_tokens: int = 1500) -> dict:
    last = None
    for _ in range(2):
        c = await provider.complete([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                    json_mode=True, max_tokens=max_tokens, purpose=purpose)
        try:
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", c.text.strip())
            return json.loads(text)
        except json.JSONDecodeError as e:
            last = e
    raise LLMError(f"{purpose}: invalid JSON ({last})")


# ---------------------------------------------------------------- 서비스 구성

def make_svc(provider, hybrid: bool = False):
    d = pathlib.Path(tempfile.mkdtemp(prefix="gnx_exp_"))
    settings = Settings(data_dir=d, debate_max_rounds=3, debate_max_tokens=24000)
    svc = build_services(settings, provider)
    if hybrid:
        svc.orchestrator = HybridOrchestrator(settings, svc.db, svc.llm, svc.memory, svc.policy, svc.tools, svc.bus, svc.activity)
    svc.db.create_all()
    svc.orchestrator.register_agents()
    for kind, text, imp in SEED_MEMORIES:
        svc.memory.add(kind, text, imp, source="manual")
    return svc


def weekend_dates(today):
    if today.weekday() == 6:
        return [today, today]
    sat = today + timedelta(days=(5 - today.weekday()) % 7)
    return [sat, sat + timedelta(days=1)]


async def build_bundle(svc, topic: dict) -> Ledger | None:
    """사실 주제의 증거 번들: A에 제공하는 도구 결과(경고 포함). B/C의 Research가 쓰는 것과 같은 도구."""
    if not topic["bundle"]:
        return None
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    sat, sun = weekend_dates(today)
    led = Ledger("", False)
    for i, (tool, off, period) in enumerate(topic["bundle"], 1):
        day = sat if off == "SAT" else sun if off == "SUN" else today + timedelta(days=off)
        res = await svc.policy.invoke(tool, {"date": day.isoformat(), "period": period}, actor="experiment")
        if res.status == "ok":
            led.add_evidence(i, tool, evidence_summary(res.data), "ok", evidence_flags(tool, res.data))
        else:
            led.add_evidence(i, tool, f"조회 실패({res.error_kind}): {res.error}", "error", evidence_flags(tool, None, error=res.error, error_kind=res.error_kind))
    return led


# ---------------------------------------------------------------- A / A0

SINGLE_SYSTEM = """당신은 신중한 분석가입니다. 주어진 주제를 혼자서 분석하고 최종 결과를 작성합니다.
규칙:
- 배경 자료와 증거에 없는 사실·수치·제품·장소·기술 이름을 지어내지 않습니다. 근거가 부족하면 '확인 필요'로 표시합니다.
- 증거가 있으면 수치를 그대로 인용하고(증거 id 표기 [E1]), 증거의 경고(강수확률, 구름량, 달 밝기, 조회 실패 등)를 결론에 반영합니다. 경고와 모순되는 결론을 내지 않습니다.
- 배경 자료에 이미 구현된 기능은 새 아이디어로 제시하지 않습니다.
- 한국어로 간결하고 구체적으로 씁니다.
JSON만 출력: {"summary":"3~5문장","ideas":[{"title":"","description":"","feasibility":"low|medium|high","risks":[""],"next_steps":[""],"confidence":0.5}],
"open_questions":[""],"caveats":[""]}  ideas는 2~4개."""


async def run_single(topic: dict, with_evidence: bool, provider, ctx_svc, bundle: Ledger | None) -> dict:
    ctx = ctx_svc.orchestrator._context_block()
    ev = f"\n[증거 목록]\n{bundle.evidence_prompt()}\n" if (with_evidence and bundle is not None) else ""
    user = f"{ctx}\n주제: {topic['title']}\n\n{brief_for(topic)}\n{ev}\n위 자료만을 근거로 분석하고 JSON으로 최종 결과를 작성하세요."
    data = await call_json(provider, SINGLE_SYSTEM, user, "single", 2200)
    ideas = [{"title": str(i.get("title", "")), "description": str(i.get("description", "")), "risks": [str(x) for x in i.get("risks", [])],
              "next_steps": [str(x) for x in i.get("next_steps", [])]} for i in data.get("ideas", []) if isinstance(i, dict)]
    return {"summary": str(data.get("summary", "")), "ideas": ideas, "open_questions": [str(x) for x in data.get("open_questions", [])],
            "caveats": [str(x) for x in data.get("caveats", [])],
            "evidence_texts": [e["summary"] for e in bundle.evidence.values()] + [f["text"] for f in bundle.all_flags()] if (with_evidence and bundle) else []}


# ---------------------------------------------------------------- B / C

async def run_multi(topic: dict, hybrid: bool, provider) -> dict:
    svc = make_svc(provider, hybrid=hybrid)
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


def collect(svc) -> dict:
    with svc.db.session() as s:
        d = s.scalars(select(Debate)).first()
        if d is None:
            return {"debate": None}
        msgs = [{"round": m.round, "agent": m.agent_id, "content": m.content, "claims": m.claims}
                for m in s.scalars(select(DebateMessage).where(DebateMessage.debate_id == d.id).order_by(DebateMessage.id))]
        ev = [{"id": e.id, "tool": e.tool, "status": e.status, "summary": e.summary, "flags": e.flags or []}
              for e in s.scalars(select(Evidence).where(Evidence.debate_id == d.id))]
        ideas = [{"title": i.title, "description": i.description, "status": i.status, "rationale": i.rationale, "risks": i.risks,
                  "next_steps": i.next_steps, "feasibility": i.feasibility, "confidence": i.confidence, "evidence_ids": i.evidence_ids}
                 for i in s.scalars(select(Idea).where(Idea.debate_id == d.id))]
        events = _count([a.event for a in s.scalars(select(ActivityLog)) if a.event in
                         ("critic.retry", "critic.rejected", "preserved.dropped", "consensus.ignored", "review.rebuttal_rejected", "review.failed")])
        return {
            "debate": {"status": d.status, "stop_reason": d.stop_reason, "rounds": d.rounds_done, "error": d.error, "participants": d.participants,
                       "importance": d.importance, "plan": d.plan, "progress": d.progress},
            "messages": msgs, "evidence": ev, "ideas": ideas, "result": d.result, "events": events,
            "review_stats": getattr(svc.orchestrator, "review_stats", {}),
        }


def normalize_multi(raw: dict) -> dict:
    """B/C 결과를 A와 같은 형식으로. 폐기된 아이디어는 제외하고 방식·상태 라벨과 '증거 경고:' 접두어를 제거한다."""
    res = raw.get("result") or {}
    ideas = [{"title": i["title"], "description": re.sub(r"\s*\(존재 미확인: [^)]*\)", "", i["description"]),
              "risks": [re.sub(r"^증거 경고:\s*", "", r) for r in (i["risks"] or [])],
              "next_steps": i["next_steps"] or []} for i in raw.get("ideas", []) if i["status"] != "discarded"]
    ev_texts = [e["summary"] for e in raw.get("evidence", []) if e["status"] == "ok"] + [f["text"] for e in raw.get("evidence", []) for f in e["flags"]]
    return {"summary": re.sub(r"\s*⚠[^.]*\.?\s*$", "", res.get("summary", "")), "ideas": ideas, "open_questions": res.get("open_questions", []),
            "caveats": res.get("warnings", []), "evidence_texts": ev_texts}


def present(norm: dict) -> str:
    lines = [f"요약: {norm['summary']}", "아이디어:"]
    for n, i in enumerate(norm["ideas"], 1):
        lines.append(f"{n}) {i['title']} — {i['description']}")
        if i["risks"]:
            lines.append("   위험: " + "; ".join(i["risks"]))
        if i["next_steps"]:
            lines.append("   다음 단계: " + "; ".join(i["next_steps"]))
    if norm["open_questions"]:
        lines.append("열린 질문: " + "; ".join(norm["open_questions"]))
    if norm["caveats"]:
        lines.append("주의: " + "; ".join(norm["caveats"]))
    return "\n".join(lines)


# ---------------------------------------------------------------- 객관 지표

PCT = re.compile(r"(\d+(?:\.\d+)?)\s?%")


def objective_metrics(norm: dict, flags: list[dict]) -> dict:
    text = present(norm)
    have = {float(x) for t in norm.get("evidence_texts", []) for x in re.findall(r"\d+(?:\.\d+)?", t)}
    pcts = [float(p) for p in PCT.findall(text)]
    warn = [f for f in flags if f["severity"] != "info"]

    def mentioned(f):
        nums = re.findall(r"\d+", f["text"])
        return (bool(nums) and nums[0] + "%" in text.replace(" ", "")) or (f["code"] == "tool_failed" and "조회 실패" in text) or f["text"][:8] in text

    ideas = norm["ideas"]
    return {"chars": len(text), "n_ideas": len(ideas),
            "with_next_steps": round(sum(1 for i in ideas if i["next_steps"]) / max(1, len(ideas)), 2),
            "with_risks": round(sum(1 for i in ideas if i["risks"]) / max(1, len(ideas)), 2),
            "unsupported_pct": sum(1 for p in pcts if p not in have), "n_pct": len(pcts),
            "warning_coverage": round(sum(1 for f in warn if mentioned(f)) / len(warn), 2) if warn else None, "n_warnings": len(warn)}


# ---------------------------------------------------------------- 생성 단계

async def gen_cell(topic: dict, method: str, provider, bundle: Ledger | None, ctx_svc) -> dict:
    label = f"{topic['id']}:{method}"
    LABEL.set(label)
    t0 = time.perf_counter()
    rec = {"topic": topic["id"], "method": method, "ok": True, "error": None}
    flags: list[dict] = []
    try:
        if method in ("A", "A0"):
            norm = await run_single(topic, method == "A", provider, ctx_svc, bundle)
            raw = {}
            flags = bundle.all_flags() if (method == "A" and bundle) else []
        else:
            if method == "C":
                with hybrid_patches():
                    raw = await run_multi(topic, True, provider)
            else:
                raw = await run_multi(topic, False, provider)
            norm = normalize_multi(raw)
            flags = [f for e in raw.get("evidence", []) for f in e["flags"]]
            if raw.get("debate") is None or raw["debate"]["status"] != "completed":
                rec["ok"], rec["error"] = False, (raw.get("debate") or {}).get("error") or "debate not completed"
        rec.update(raw=raw, norm=norm, metrics=objective_metrics(norm, flags) if norm["ideas"] or norm["summary"] else None)
    except Exception as e:  # 실패도 제외하지 않고 기록한다
        rec.update(ok=False, error=f"{type(e).__name__}: {e}"[:300], raw={}, norm=None, metrics=None)
    rec["secs"] = round(time.perf_counter() - t0, 2)
    rec["usage"] = METER.cell(label)
    return rec


async def phase_gen(only: set[str] | None):
    RAW.mkdir(parents=True, exist_ok=True)
    key = Settings().openai_api_key
    provider = MeteredProvider(GEN_MODEL, key)
    ctx_svc = make_svc(provider)
    # 영역별로 번갈아 실행해 중단되어도 균형이 유지되게 한다
    areas: dict[str, list[dict]] = {}
    for t in TOPICS:
        areas.setdefault(t["area"], []).append(t)
    order = []
    while any(areas.values()):
        for a in list(areas):
            if areas[a]:
                order.append(areas[a].pop(0))
    for topic in order:
        if only and topic["id"] not in only:
            continue
        done = all((RAW / f"{topic['id']}__{m}.json").exists() for m in METHODS)
        if done:
            continue
        if METER.spent >= GEN_CAP:
            print(f"[중단] 생성 예산 ${GEN_CAP} 도달: {topic['id']} 이후 미실행 (누적 ${METER.spent:.4f})")
            break
        bundle = None
        if topic["bundle"]:
            LABEL.set(f"{topic['id']}:bundle")
            bundle = await build_bundle(ctx_svc, topic)
        methods = METHODS + (["A0"] if topic["bundle"] else [])
        for m in methods:
            path = RAW / f"{topic['id']}__{m}.json"
            if path.exists():
                continue
            rec = await gen_cell(topic, m, provider, bundle, ctx_svc)
            if bundle is not None:
                rec["bundle"] = {"text": bundle.evidence_prompt(), "flags": bundle.all_flags()}
            path.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
            METER.save()
            u = rec["usage"]
            print(f"{topic['id']:7s} {m:2s} ok={rec['ok']} {rec['secs']:6.1f}s calls={u['calls']:2d} tok={u['prompt_tokens'] + u['completion_tokens']:6d} ${u['cost_usd']:.4f} | 누적 ${METER.spent:.4f}"
                  + (f" ERR {rec['error']}" if rec["error"] else ""), flush=True)
    METER.save()


# ---------------------------------------------------------------- 평가 단계

RUBRIC_TEXT = """평가 기준(각 1~5점 정수):
1. accuracy 사실 정확성·증거 충실도: 5=모든 주장이 배경/증거와 일치하고 불확실한 것은 명시 / 3=사소한 근거 없는 주장·모호함 / 1=증거와 모순되거나 지어낸 사실·이름·수치가 있음
2. specificity 구체성: 5=누가·무엇을·어떻게·다음 단계가 구체적 / 3=일부만 구체적 / 1=일반론
3. feasibility 기술적 실현 가능성: 5=배경의 스택·제약에서 바로 구현·실행 가능하고 범위·난이도 현실적 / 3=가능하나 가정이 많음 / 1=비현실적이거나 제약 무시
4. novelty 차별성: 5=배경에 이미 있는 기능이나 뻔한 조언을 넘어서는 새 각도 / 3=일부 새롭고 일부 뻔함 / 1=이미 구현된 기능이거나 뻔한 조언
5. value 활용 가치: 5=사용자가 바로 활용할 가치가 큼 / 3=보통 / 1=거의 쓸모 없음
6. risk_review 반론·위험 검토의 적절성: 5=핵심 위험·한계·반례가 구체적으로 다뤄지고 과도한 비관 없음 / 3=형식적이거나 일부 누락 / 1=위험 검토가 없거나 허위·과장
지침: 글의 길이로 점수를 주지 마세요. 배경·증거에 없는 주장은 감점하세요. 후보를 만든 방식은 알 수 없고 순서와 무관합니다. 점수는 후보끼리 상대 평가가 아니라 각 후보를 기준표에 비춰 절대 평가하세요."""

JUDGE_SYSTEM = f"""당신은 엄격하고 공정한 평가자입니다. 같은 주제에 대한 여러 후보 결과를 기준표로 채점합니다.
{RUBRIC_TEXT}
JSON만 출력: {{"scores":{{"1":{{"accuracy":3,"specificity":3,"feasibility":3,"novelty":3,"value":3,"risk_review":3}}}},"notes":{{"1":"40단어 이내 근거"}}}} (후보 번호별로 모두 채점)"""

PAIR_SYSTEM = f"""당신은 엄격하고 공정한 평가자입니다. 같은 주제에 대한 두 글(글 1, 글 2)을 기준표로 각각 채점하고, 글 2가 글 1을 개선했는지 판단합니다.
{RUBRIC_TEXT}
추가 판단: 두 글 중 '나중 글'이 '앞 글'에 비해 타당한 내용을 잃거나 약화시켰는지 weakened_points에 적고, verdict는 나중 글 기준으로 improved|same|weakened 중 하나입니다. (아래 입력에 어느 쪽이 나중 글인지 표기됨)
JSON만 출력: {{"scores":{{"1":{{...6개 기준}},"2":{{...6개 기준}}}},"weakened_points":["..."],"verdict":"improved","note":"40단어 이내"}}"""

GOLD_SYSTEM = """증거 경고와 서술 사이의 '실제 모순'을 엄격하게 판정하는 평가자입니다.
- 모순: 서술이 경고가 가리키는 같은 날짜·조건에 대해 경고와 반대로 단정(예: 강수확률 61% 경고인데 '비 올 확률이 낮다', 달 밝기 경고인데 달빛이 유리하다고 단정).
- 모순 아님: 한계를 인정하는 서술('달이 밝지만 ~'), 다른 날짜·조건, 날짜 없는 일반 원칙·권고, 경고를 그대로 반영한 서술.
JSON만 출력: {"conflicts":[{"index":1,"reason":"한 문장"}]}"""


def _valid_scores(s: dict) -> bool:
    return isinstance(s, dict) and all(isinstance(s.get(c), (int, float)) and 1 <= s[c] <= 5 for c in CRITERIA)


async def judge_set(topic, cands: dict[str, str], bundle_text: str, order: list[str], provider) -> dict:
    body = "\n\n".join(f"=== 후보 {i} ===\n{cands[m]}" for i, m in enumerate(order, 1))
    ev = f"\n[증거 목록]\n{bundle_text}\n" if bundle_text else ""
    user = f"주제: {topic['title']}\n\n{brief_for(topic)}\n{ev}\n{body}"
    data = await call_json(provider, JUDGE_SYSTEM, user, "judge:set", 1800)
    out = {}
    for i, m in enumerate(order, 1):
        s = data.get("scores", {}).get(str(i))
        if _valid_scores(s):
            out[m] = {"scores": {c: float(s[c]) for c in CRITERIA}, "note": str(data.get("notes", {}).get(str(i), ""))}
    return out


async def phase_judge():
    JUDGE_DIR.mkdir(parents=True, exist_ok=True)
    key = Settings().openai_api_key
    jp = MeteredProvider(JUDGE_MODEL, key)
    gp = MeteredProvider(GEN_MODEL, key)
    recs = {}
    for p in sorted(RAW.glob("*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        recs[(r["topic"], r["method"])] = r
    topics = {t["id"]: t for t in TOPICS}
    # 1) 방식 비교 평가: 순서 2회
    for tid, topic in topics.items():
        out_path = JUDGE_DIR / f"{tid}__compare.json"
        have = {m: recs[(tid, m)] for m in ["A", "B", "C", "A0"] if (tid, m) in recs and recs[(tid, m)]["norm"] and recs[(tid, m)]["ok"]}
        if out_path.exists() or len(have) < 2:
            continue
        if METER.spent >= HARD_CAP:
            print("[중단] 평가 예산 도달"); break
        LABEL.set(f"judge:{tid}")
        bundle = next((r.get("bundle", {}).get("text", "") for r in recs.values() if r["topic"] == tid and r.get("bundle")), "")
        methods = list(have)
        rng = random.Random(f"order-{tid}")
        order1 = methods[:]
        rng.shuffle(order1)
        order2 = order1[::-1]
        cands = {m: present(have[m]["norm"]) for m in methods}
        res = []
        for order in (order1, order2):
            try:
                res.append({"order": order, "result": await judge_set(topic, cands, bundle, order, jp)})
            except LLMError as e:
                res.append({"order": order, "error": str(e)})
        out_path.write_text(json.dumps({"topic": tid, "orders": res, "methods": methods}, ensure_ascii=False, indent=1), encoding="utf-8")
        METER.save()
        print(f"judge {tid} done | 누적 ${METER.spent:.4f}", flush=True)
    # 2) 토론 전후(초안 vs 최종) 평가: B, C
    for tid, topic in topics.items():
        for m in ("B", "C"):
            out_path = JUDGE_DIR / f"{tid}__{m}__draft.json"
            r = recs.get((tid, m))
            if out_path.exists() or not r or not r["ok"] or not r["norm"]:
                continue
            draft = next((x for x in r["raw"]["messages"] if x["agent"] == "idea"), None)
            if not draft or METER.spent >= HARD_CAP:
                continue
            LABEL.set(f"judge:{tid}:{m}:draft")
            draft_text = draft["content"] + "\n" + "\n".join(f"- {c['text']}" for c in draft["claims"])
            final_text = present(r["norm"])
            flip = random.Random(f"pair-{tid}-{m}").random() < 0.5
            first, second = (final_text, draft_text) if flip else (draft_text, final_text)
            later = "글 1" if flip else "글 2"
            user = (f"주제: {topic['title']}\n\n{brief_for(topic)}\n\n[나중 글] {later}\n\n=== 글 1 ===\n{first}\n\n=== 글 2 ===\n{second}")
            try:
                d = await call_json(jp, PAIR_SYSTEM, user, "judge:pair", 1200)
                sc = d.get("scores", {})
                d_idx, f_idx = ("2", "1") if flip else ("1", "2")
                rec = {"topic": tid, "method": m, "draft_scores": sc.get(d_idx), "final_scores": sc.get(f_idx),
                       "verdict": d.get("verdict"), "weakened_points": d.get("weakened_points", []), "note": d.get("note", ""), "final_first": flip}
            except LLMError as e:
                rec = {"topic": tid, "method": m, "error": str(e)}
            out_path.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
            METER.save()
            print(f"pair {tid}:{m} | 누적 ${METER.spent:.4f}", flush=True)
    # 3) 충돌 탐지기 비교: 사실 주제의 B/C 실행
    for tid, topic in topics.items():
        if not topic["bundle"]:
            continue
        for m in ("B", "C"):
            out_path = JUDGE_DIR / f"{tid}__{m}__detector.json"
            r = recs.get((tid, m))
            if out_path.exists() or not r or not r["norm"] or METER.spent >= HARD_CAP:
                continue
            flags = [f for e in r["raw"]["evidence"] for f in e["flags"]]
            if not [f for f in flags if f["severity"] != "info"]:
                continue
            stmts = [c["text"] for x in r["raw"]["messages"] if x["agent"] != "critic" for c in x["claims"]]
            stmts += [i["description"] for i in r["raw"]["ideas"]]
            stmts += [s.strip() for s in re.split(r"[.!?\n]+", (r["raw"]["result"] or {}).get("summary", "")) if len(s.strip()) > 8]
            stmts = list(dict.fromkeys(stmts))[:30]
            LABEL.set(f"judge:{tid}:{m}:detector")
            ev_text = " ".join(e["summary"] for e in r["raw"]["evidence"] if e["status"] == "ok")
            user = conflict_prompt(stmts, flags, ev_text)
            try:
                llm = await call_json(gp, REVIEW_CONFLICT_SYSTEM, user, "detector:llm", 700)
                gold = await call_json(jp, GOLD_SYSTEM, user, "detector:gold", 700)
            except LLMError as e:
                out_path.write_text(json.dumps({"error": str(e)}), encoding="utf-8")
                continue
            idx = lambda d: sorted({c.get("index") for c in d.get("conflicts", []) if isinstance(c, dict)})  # noqa: E731
            rule = [i for i, s in enumerate(stmts, 1) if rule_find_conflicts(s, flags)]
            out_path.write_text(json.dumps({"topic": tid, "method": m, "statements": stmts, "rule": rule, "llm": idx(llm), "gold": idx(gold),
                                            "gold_reasons": gold.get("conflicts", [])}, ensure_ascii=False, indent=1), encoding="utf-8")
            METER.save()
            print(f"detector {tid}:{m} stmts={len(stmts)} | 누적 ${METER.spent:.4f}", flush=True)
    METER.save()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "gen"
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    sha = hashlib.sha256((HERE / "PROTOCOL.md").read_bytes()).hexdigest()
    print(f"PROTOCOL.md sha256={sha}  단계={cmd}  누적비용=${METER.spent:.4f}")
    if cmd == "gen":
        asyncio.run(phase_gen(only))
    elif cmd == "judge":
        asyncio.run(phase_judge())
    print(f"종료. 누적 비용 ${METER.spent:.4f} / 상한 $0.50")


if __name__ == "__main__":
    main()
