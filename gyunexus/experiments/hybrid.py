"""실험용 Hybrid 오케스트레이터(C). GyuNexus 소스를 바꾸지 않고 상속과 모듈 속성 대체로만 구성한다.

B(현재 구조)와 같은 에이전트·플래너·장부·종료 로직을 쓰되, 의미 판단 세 가지를 정규식 대신 별도 LLM 검토로 처리한다.
수치·날짜·증거 ID·형식·중복 검증은 기존 코드 그대로 둔다.
"""

from __future__ import annotations

import contextlib
import json
import re

from sqlalchemy import select

from gyunexus.agents import evidence as ev_mod
from gyunexus.agents import ledger as ledger_mod
from gyunexus.agents import orchestrator as orch_mod
from gyunexus.agents.orchestrator import AgentOrchestrator, _clamp
from gyunexus.llm import LLMError
from gyunexus.models import DebateMessage, Idea

REVIEW_CONFLICT_SYSTEM = """증거 경고와 서술 사이의 '실제 모순'을 판정합니다.
- 모순: 서술이 경고가 가리키는 같은 날짜·조건에 대해 경고와 반대로 단정하는 경우(예: 강수확률 61% 경고인데 '비 올 확률이 낮다', 달 밝기 경고인데 '달빛 때문에 오히려 유리').
- 모순 아님: 한계를 인정하며 말하는 경우('달이 밝지만 날씨가 좋다'), 다른 날짜·조건에 대한 서술, 날짜 없는 일반 원칙·권고, 경고를 그대로 옮긴 서술, 부정문으로 경고와 일치하는 서술.
엄격하게 판단하세요. 확실한 모순만 conflicts에 넣습니다.
JSON만 출력: {"conflicts":[{"index":1,"reason":"한 문장"}]}"""

REVIEW_REBUTTAL_SYSTEM = """Critic 반박의 타당성을 판정합니다.
- 타당: 대상 발언에 실제로 오류·누락된 조건·증거와의 모순·실행 위험이 있고, 반박이 증거와 맥락을 올바르게 읽었다.
- 무효: 대상을 오해했거나, 증거를 잘못 읽었거나(날짜·조건 혼동), 이미 반영된 내용을 다시 지적했거나, 타당한 주장을 근거 없이 약화시키려는 반박.
JSON만 출력: {"verdicts":[{"id":1,"valid":true,"reason":"한 문장"}]}"""

REVIEW_RESULT_SYSTEM = """토론의 최종 결과를 검토합니다. 입력: 주제, 배경 자료, 증거(경고 포함), 요약, 아이디어 목록.
아이디어마다 판단하세요.
- genuine_conflict: 증거 경고와 실제로 모순되는 확정적 서술이 있는가(한계를 인정한 서술은 모순 아님)
- already_exists: 배경 자료상 이미 구현된 기능을 새 아이디어처럼 제시했는가
- value: 1~5, 사용자에게 구체적이고 새롭고 실행 가능한 가치(뻔한 일반 조언은 2 이하)
- status: accepted(충분히 검토되어 추천 가능) | needs_research(유망하지만 근거가 부족) | discarded(가치 없음, 이미 존재, 증거와 모순)
요약에 대해 summary_conflict(증거 경고와 실제로 모순되는 확정적 서술이 있는가)도 판단하세요.
JSON만 출력: {"ideas":[{"index":1,"genuine_conflict":false,"already_exists":false,"value":3,"status":"needs_research","reason":"한 문장"}],"summary_conflict":false,"summary_reason":""}"""

STATUS_RANK = {"accepted": 2, "needs_research": 1, "discarded": 0}


def conflict_prompt(statements: list[str], flags: list[dict], evidence_text: str = "") -> str:
    fl = "\n".join(f"- {f['text']}" + (f" [날짜 {f['date']}]" if f.get("date") else "") for f in flags if f["severity"] != "info") or "(없음)"
    st = "\n".join(f"{i}. {s}" for i, s in enumerate(statements, 1))
    return f"[증거 경고]\n{fl}\n\n[증거 요약]\n{evidence_text[:1200] or '(없음)'}\n\n[서술]\n{st}"


def _never():
    return re.compile(r"(?!x)x")


@contextlib.contextmanager
def hybrid_patches():
    """C 실행 중에만: 의미 판단용 정규식(충돌 탐지, 상투적 반박 탐지)을 끈다."""
    saved = (ev_mod.find_conflicts, orch_mod.find_conflicts, ledger_mod._GENERIC)
    ev_mod.find_conflicts = lambda text, flags: []
    orch_mod.find_conflicts = lambda text, flags: []
    ledger_mod._GENERIC = _never()
    try:
        yield
    finally:
        ev_mod.find_conflicts, orch_mod.find_conflicts, ledger_mod._GENERIC = saved


class HybridOrchestrator(AgentOrchestrator):
    review_stats: dict

    async def _json(self, purpose: str, system: str, user: str, ctx: dict, max_tokens: int = 700):
        try:
            data, res = await self.llm.json(
                purpose, [{"role": "system", "content": system}, {"role": "user", "content": user}],
                autonomous=False, debate_id=ctx["debate_id"], max_tokens=max_tokens,
            )
            return data, res.tokens, res.cost_usd
        except LLMError as e:
            self.activity.record("agent", "review.failed", level="warn", error=str(e))
            return None, 0, 0.0

    def _bump(self, key: str, n: int = 1) -> None:
        if not hasattr(self, "review_stats"):
            self.review_stats = {}
        self.review_stats[key] = self.review_stats.get(key, 0) + n

    def _sync_message_claims(self, debate_id: int, rnd: int, aid: str, ledger) -> None:
        claims = [c.public() for c in ledger.claims if c.round == rnd and c.agent == aid]
        with self.db.session() as s:
            row = s.scalars(select(DebateMessage).where(DebateMessage.debate_id == debate_id, DebateMessage.round == rnd,
                                                        DebateMessage.agent_id == aid).order_by(DebateMessage.id.desc())).first()
            if row is not None:
                row.claims = claims

    async def _agent_turn(self, aid, rnd, ctx, ledger, stats, retries_left, tokens_left):
        n_claims, n_reb = len(ledger.claims), len(ledger.rebuttals)
        out = await super()._agent_turn(aid, rnd, ctx, ledger, stats, retries_left, tokens_left)
        extra_tokens, extra_cost = 0, 0.0
        if aid == "critic":
            new = ledger.rebuttals[n_reb:]
            if new:
                body = "\n".join(
                    f"[{r.id}] 대상: \"{r.target}\" / 종류: {r.kind} / 내용: {r.detail} / 인용 증거: {r.evidence_ids}" for r in new
                )
                user = f"주제: {ctx['title']}\n\n[증거]\n{ledger.evidence_prompt()}\n\n[토론 기록]\n{self._transcript(ledger)[-2500:]}\n\n[검토할 반박]\n{body}"
                data, tk, cs = await self._json("review:rebuttal", REVIEW_REBUTTAL_SYSTEM, user, ctx)
                extra_tokens, extra_cost = tk, cs
                invalid = {v.get("id") for v in (data or {}).get("verdicts", []) if isinstance(v, dict) and v.get("valid") is False}
                removed = [r for r in new if r.id in invalid]
                for r in removed:
                    r.status = "rejected_semantic"  # open이 아니므로 이후 합의/처리 판단에서 제외, 중복 판정에는 계속 쓰인다
                if removed:
                    stats["valid_rebuttals"] -= len(removed)
                    stats["rejected_rebuttals"] += len(removed)
                    self._bump("rebuttals_rejected", len(removed))
                    self.activity.record("agent", "review.rebuttal_rejected", agent_id="critic", debate_id=ctx["debate_id"], ids=[r.id for r in removed])
                self._bump("rebuttals_reviewed", len(new))
        else:
            new_claims = ledger.claims[n_claims:]
            flags = [f for f in ledger.all_flags() if f["severity"] != "info"]
            if new_claims and flags:
                user = conflict_prompt([c.text for c in new_claims], ledger.all_flags(),
                                       " ".join(e["summary"] for e in ledger.evidence.values() if e["status"] == "ok"))
                data, tk, cs = await self._json("review:claims", REVIEW_CONFLICT_SYSTEM, user, ctx, 500)
                extra_tokens, extra_cost = tk, cs
                hit = {c.get("index") for c in (data or {}).get("conflicts", []) if isinstance(c, dict)}
                changed = False
                for i, c in enumerate(new_claims, 1):
                    if i in hit and c.status in ("verified", "interpretation", "proposal"):
                        c.status = "conflicted"
                        c.notes.append("의미 검토: 증거 경고와 모순")
                        changed = True
                        self._bump("claims_flagged")
                self._bump("claims_reviewed", len(new_claims))
                if changed:
                    self._sync_message_claims(ctx["debate_id"], rnd, aid, ledger)
        out["tokens"] += extra_tokens
        out["cost"] += extra_cost
        return out

    async def _synthesize(self, debate_id, ctx, ledger, autonomous):
        result = await super()._synthesize(debate_id, ctx, ledger, autonomous)
        ideas = result["ideas"]
        if not ideas:
            return result
        flags = ledger.all_flags()
        listing = "\n".join(f"{i}. {x['title']} — {x['description']} (현재 상태: {x['status']})" for i, x in enumerate(ideas, 1))
        user = (f"주제: {ctx['title']}\n\n[배경 자료]\n{ctx['goal']}\n\n[증거]\n{ledger.evidence_prompt()}\n\n"
                f"[요약]\n{result['summary']}\n\n[아이디어]\n{listing}")
        data, tk, cs = await self._json("review:result", REVIEW_RESULT_SYSTEM, user, ctx, 900)
        result["_tokens"] += tk
        result["_cost"] += cs
        if not data:
            return result
        by_index = {r.get("index"): r for r in data.get("ideas", []) if isinstance(r, dict)}
        conflicts = []
        for i, idea in enumerate(ideas, 1):
            rv = by_index.get(i)
            if not rv:
                continue
            target = idea["status"]
            note = []
            if rv.get("genuine_conflict"):
                target = min(target, "needs_research", key=STATUS_RANK.get)
                note.append("의미 검토: 증거와 모순")
                conflicts.append(idea["title"])
                self._bump("ideas_conflict")
            if rv.get("already_exists"):
                target = "discarded"
                note.append("의미 검토: 이미 구현된 기능")
            if _clamp(rv.get("value"), 1, 5, 3) <= 2:
                target = "discarded"
                note.append(f"의미 검토: 가치 낮음({rv.get('value')})")
            rv_status = rv.get("status") if rv.get("status") in STATUS_RANK else target
            final = min(idea["status"], target, rv_status, key=STATUS_RANK.get)  # 코드 검증 결과와 검토 결과 중 보수적인 쪽
            if final != idea["status"]:
                self._bump("ideas_status_changed")
            idea["status"] = final
            idea["rationale"] = " / ".join(filter(None, [idea["rationale"], *note, str(rv.get("reason", ""))]))
        summary_conflict = bool(data.get("summary_conflict"))
        if summary_conflict:
            result["summary"] += " ⚠ 의미 검토: 요약에 증거 경고와 모순되는 서술이 있어 확정하지 않습니다. " + str(data.get("summary_reason", ""))
            conflicts.append("summary")
            self._bump("summary_conflict")
        counts = {s: sum(1 for i in ideas if i["status"] == s) for s in STATUS_RANK}
        status = "needs_research" if summary_conflict else "accepted" if counts["accepted"] else "needs_research" if counts["needs_research"] else "discarded"
        result["status"] = status
        result["conflicts"] = conflicts
        if status != "accepted":
            result["importance"] = min(result["importance"], 4)
        result["recommendation"] = {"accepted": [i["title"] for i in ideas if i["status"] == "accepted"],
                                    "needs_research": [i["title"] for i in ideas if i["status"] == "needs_research"]}
        with self.db.session() as s:
            rows = {r.title: r for r in s.scalars(select(Idea).where(Idea.debate_id == debate_id))}
            for idea in ideas:
                if idea["title"] in rows:
                    rows[idea["title"]].status, rows[idea["title"]].rationale = idea["status"], idea["rationale"]
        return result
