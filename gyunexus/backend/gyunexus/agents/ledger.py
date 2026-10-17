"""토론 장부: 증거, 검증된 주장, 반박, 라운드별 진행 상황을 한곳에 모아 에이전트가 서로의 결과를 실제로 이어받게 한다.

Critic 반박의 품질 검증(형식적 반박 거부)과 정체 판단에 쓰는 순수 로직이라 LLM 호출이 없다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..textutil import similarity
from .evidence import flags_text, verify_claim

REBUTTAL_KINDS = ("error", "missing_condition", "evidence_conflict", "counterexample", "execution_risk")
KIND_LABELS = {
    "error": "확인 가능한 오류",
    "missing_condition": "누락된 조건",
    "evidence_conflict": "주장과 증거의 모순",
    "counterexample": "실질적 반례",
    "execution_risk": "실행상 위험",
}
# 근거 없이 쓸 수 있는 상투적 반박 표현
_GENERIC = re.compile(
    r"검증할 수 없|검증되지 않|일반화|주관적|개인(의)?\s?(경험|취향)|(사용자|사람).{0,8}따라|상황에 따라|다를 수 있|단정할 수 없|구체적(인)?\s?(데이터|정보|근거)가\s?(없|부족)"
)
_CONCRETE = re.compile(r"\d|\bE\d+|\[E|[A-Za-z]{3,}")
DUPLICATE_SIMILARITY = 0.55
TARGET_MATCH_SIMILARITY = 0.3


@dataclass
class Claim:
    id: int
    round: int
    agent: str
    text: str
    type: str
    status: str
    evidence_ids: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    def public(self) -> dict:
        return {"text": self.text, "type": self.type, "status": self.status, "evidence_ids": self.evidence_ids,
                "notes": self.notes, "entities": self.entities}


@dataclass
class Rebuttal:
    id: int
    round: int
    kind: str
    target: str
    detail: str
    suggestion: str
    evidence_ids: list[int] = field(default_factory=list)
    status: str = "open"  # open | addressed
    resolution: str | None = None


class Ledger:
    def __init__(self, known_text: str, needs_facts: bool):
        self.known_text = known_text
        self.needs_facts = needs_facts
        self.evidence: dict[int, dict] = {}
        self.claims: list[Claim] = []
        self.rebuttals: list[Rebuttal] = []
        self.messages: list[dict] = []  # {"round","agent","text"}
        self.progress: list[dict] = []

    # ---------- 증거 ----------

    def add_evidence(self, ev_id: int, tool: str, summary: str, status: str, flags: list[dict]) -> None:
        self.evidence[ev_id] = {"tool": tool, "summary": summary, "status": status, "flags": flags}

    def all_flags(self) -> list[dict]:
        return [f for e in self.evidence.values() for f in e["flags"]]

    def evidence_dates(self) -> set[str]:
        return {d for e in self.evidence.values() if e["status"] == "ok" for d in re.findall(r"\d{4}-\d{2}-\d{2}", e["summary"])}

    def evidence_known_text(self) -> str:
        return self.known_text + " " + " ".join(e["summary"] for e in self.evidence.values() if e["status"] == "ok")

    def evidence_prompt(self) -> str:
        lines = []
        for i, e in self.evidence.items():
            head = f"[E{i}] ({e['tool']})" + (" ✖실패" if e["status"] != "ok" else "")
            lines.append(f"{head} {e['summary']}" + (f"\n     {flags_text(e['flags'])}" if e["flags"] else ""))
        return "\n".join(lines) or "(없음)"

    # ---------- 주장 ----------

    def add_message(self, rnd: int, agent: str, text: str) -> None:
        self.messages.append({"round": rnd, "agent": agent, "text": text})

    def add_claims(self, agent: str, rnd: int, raw_claims) -> list[Claim]:
        out: list[Claim] = []
        for c in (raw_claims if isinstance(raw_claims, list) else [])[:8]:
            if not isinstance(c, dict) or not str(c.get("text", "")).strip():
                continue
            text = str(c["text"]).strip()
            v = verify_claim(text, c.get("type"), c.get("evidence_ids"), self.evidence, self.known_text, self.all_flags())
            claim = Claim(len(self.claims) + 1, rnd, agent, text, v["type"], v["status"], v["evidence_ids"], v["notes"],
                          v["entities"], v["conflicts"])
            self.claims.append(claim)
            out.append(claim)
        return out

    def by_status(self, status: str) -> list[Claim]:
        seen: list[Claim] = []
        for c in self.claims:
            if c.status == status and not any(similarity(c.text, s.text) >= 0.6 for s in seen):
                seen.append(c)
        return seen

    def preserved(self) -> list[Claim]:
        """보존해야 할 검증된 내용: 증거가 직접 뒷받침한 사실과, 증거 경고와 충돌하지 않는 해석."""
        return self.by_status("verified") + self.by_status("interpretation")

    def missing_preserved(self, response_texts: list[str]) -> list[Claim]:
        missing = []
        for c in self.preserved():
            nums = re.findall(r"\d+(?:\.\d+)?", c.text)  # 말을 바꿔 다시 써도 같은 수치를 다시 언급하면 보존한 것으로 본다
            if not any(
                c.text.lower() in t.lower() or similarity(c.text, t) >= 0.35 or (bool(nums) and all(n in t for n in nums))
                for t in response_texts
            ):
                missing.append(c)
        return missing

    # ---------- 반박 ----------

    def _prior_texts(self) -> list[str]:
        texts = [m["text"] for m in self.messages if m["agent"] != "critic"]
        texts += [c.text for c in self.claims if c.agent != "critic"]
        return texts

    def _check(self, r: dict) -> str | None:
        kind, target = r.get("kind"), str(r.get("target", "")).strip()
        detail, suggestion = str(r.get("detail", "")).strip(), str(r.get("suggestion", "")).strip()
        if kind not in REBUTTAL_KINDS:
            return f"kind는 {', '.join(REBUTTAL_KINDS)} 중 하나여야 합니다"
        if len(target) < 4 or not any(target.lower() in t.lower() or similarity(target, t) >= TARGET_MATCH_SIMILARITY
                                      for t in self._prior_texts()):
            return "target이 앞선 발언/주장과 일치하지 않습니다(반박 대상을 그대로 인용하세요)"
        if len(detail) < 25:
            return "detail이 너무 짧습니다(무엇이 왜 틀렸거나 빠졌는지 구체적으로)"
        if len(suggestion) < 10:
            return "suggestion(대안 또는 확인 방법)이 필요합니다"
        ev_ids = [i for i in (r.get("evidence_ids") or []) if isinstance(i, int) and i in self.evidence and self.evidence[i]["status"] == "ok"]
        if kind == "evidence_conflict" and not ev_ids:
            return "evidence_conflict는 충돌하는 증거 id(evidence_ids)를 인용해야 합니다"
        if _GENERIC.search(detail) and not _CONCRETE.search(detail) and not ev_ids:
            return "일반론적 반박입니다(구체적 수치·조건·증거 없이 '검증 불가/상황에 따라 다름'만 말함)"
        for old in self.rebuttals:
            if similarity(f"{target} {detail}", f"{old.target} {old.detail}") >= DUPLICATE_SIMILARITY or (
                old.kind == kind and similarity(target, old.target) >= 0.7
            ):
                return f"이미 제기한 반박(B{old.id})과 중복입니다"
        best = max(self.claims, key=lambda c: similarity(target, c.text), default=None)
        if best is not None and best.status == "verified" and similarity(target, best.text) >= 0.5 and not ev_ids:
            return "증거로 검증된 사실에 대해 증거 없이 반박했습니다"
        return None

    def validate_rebuttals(self, raw, rnd: int) -> tuple[list[Rebuttal], list[dict]]:
        """유효한 반박만 장부에 등록한다. (유효 반박, [{"raw","reason"}...])"""
        valid: list[Rebuttal] = []
        rejected: list[dict] = []
        for r in (raw if isinstance(raw, list) else [])[:5]:
            if not isinstance(r, dict):
                continue
            reason = self._check(r)
            if reason:
                rejected.append({"raw": {k: str(v)[:80] for k, v in r.items()}, "reason": reason})
                continue
            reb = Rebuttal(len(self.rebuttals) + 1, rnd, r["kind"], str(r["target"]).strip(), str(r["detail"]).strip(),
                           str(r["suggestion"]).strip(),
                           [i for i in (r.get("evidence_ids") or []) if isinstance(i, int) and i in self.evidence])
            self.rebuttals.append(reb)
            valid.append(reb)
        return valid, rejected

    def open_rebuttals(self) -> list[Rebuttal]:
        return [r for r in self.rebuttals if r.status == "open"]

    def apply_responses(self, raw) -> int:
        """Idea/Developer가 열린 반박에 응답하면(수용·수정·근거 있는 거절) 해당 반박을 처리된 것으로 표시한다."""
        n = 0
        for resp in (raw if isinstance(raw, list) else [])[:8]:
            if not isinstance(resp, dict):
                continue
            rid = resp.get("rebuttal_id")
            if isinstance(rid, str):
                rid = int(rid.lstrip("B")) if rid.lstrip("B").isdigit() else None
            action = resp.get("action")
            if action not in ("accept", "revise", "reject") or len(str(resp.get("reason", "")).strip()) < 10:
                continue
            for r in self.rebuttals:
                if r.id == rid and r.status == "open":
                    r.status, r.resolution = "addressed", f"{action}: {str(resp['reason']).strip()[:120]}"
                    n += 1
        return n

    # ---------- 프롬프트용 요약 ----------

    def preserved_prompt(self) -> str:
        items = self.preserved()
        return "\n".join(f"- ({c.status}) {c.text} [{', '.join('E' + str(i) for i in c.evidence_ids)}]" for c in items) or "(아직 없음)"

    def open_prompt(self) -> str:
        return "\n".join(
            f"- [B{r.id}] ({KIND_LABELS[r.kind]}) 대상: \"{r.target}\" / {r.detail} / 제안: {r.suggestion}" for r in self.open_rebuttals()
        ) or "(없음)"

    def warnings(self) -> list[str]:
        """최종 종합과 사용자 전달까지 반드시 이어져야 할 경고(증거의 경고·실패, 충돌한 주장, 존재 미확인 이름)."""
        out: list[str] = []
        for f in self.all_flags():
            if f["severity"] != "info" and f["text"] not in out:
                out.append(f["text"])
        for c in self.claims:
            if c.status == "conflicted":
                msg = f"증거와 충돌하는 주장: {c.text} ({'; '.join(c.conflicts)})"
                if msg not in out:
                    out.append(msg)
        ents = sorted({e for c in self.claims for e in c.entities})
        if ents:
            out.append("존재가 확인되지 않은 이름: " + ", ".join(ents))
        return out
