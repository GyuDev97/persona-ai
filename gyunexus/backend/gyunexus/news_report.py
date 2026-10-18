"""뉴스 조사 보고서: 검색 결과 / 원문 / AI 해석을 구분하고, 검증 상태를 코드가 증거에서 계산한다.

모델이 쓰는 것은 '사실 문장·기술적 의미·블로그 제목 후보·추가 확인 필요'뿐이다. URL, 게시일, 수집 시각, 출처,
검증 상태, 과거 기사 여부는 도구 결과(증거)에서 코드가 채우므로 모델이 지어내거나 격상할 수 없다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .newstools import canonical_url

# 검증 상태(코드가 계산). 순서가 강할수록 신뢰가 높다.
V_FETCHED = "원문 확인"
V_OFFICIAL = "공식 피드 기준(원문 미확인)"
V_UNVERIFIED = "검색·피드 결과만(미검증)"
V_FETCH_FAILED = "원문 확인 실패(미검증)"
VERIFIED_STATES = {V_FETCHED}


@dataclass
class Record:
    url: str
    title: str = ""
    org: str = ""
    source: str = ""
    source_kind: str = ""  # official | news | community
    published_at: str | None = None  # 최초 게시일(UTC ISO). 원문 메타 > 피드/검색 순으로 채택
    published_basis: str = ""
    precision: str = "time"  # time | date(날짜만 알 수 있음)
    tz_assumed: bool = False
    seen_at: str | None = None
    collected_at: str | None = None  # 이 URL 이 수집된 시각(도구 호출 시각)
    fetched_at: str | None = None
    fetch_status: str = "none"  # none | ok | failed
    fetch_error: str = ""
    snippet: str = ""  # 검색·피드가 준 요약
    text: str = ""  # web.fetch 발췌(보고서·DB 에 저장하지 않고 검증에만 쓴다)
    feed_date: str | None = None
    date_conflict: bool = False
    injection: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)

    def status(self) -> str:
        if self.fetch_status == "ok":
            return V_FETCHED
        if self.fetch_status == "failed":
            return V_FETCH_FAILED
        return V_OFFICIAL if self.source_kind == "official" else V_UNVERIFIED


class NewsIndex:
    """도구 결과를 URL 별 기록으로 모은다. 모델이 고른 URL 이 실제로 수집된 것인지의 기준이다."""

    def __init__(self) -> None:
        self.by_key: dict[str, Record] = {}

    def _rec(self, url: str) -> Record:
        k = canonical_url(url)
        if k not in self.by_key:
            self.by_key[k] = Record(url=url)
        return self.by_key[k]

    def add_listing(self, tool: str, data: dict, evidence_id: str) -> None:
        collected = data.get("collected_at")
        for it in data.get("items", []):
            r = self._rec(it["url"])
            r.title = r.title or it.get("title", "")
            r.org = r.org or it.get("org", "")
            r.source = r.source or it.get("source", "")
            if it.get("source_kind") == "official" or not r.source_kind:
                r.source_kind = it.get("source_kind", r.source_kind)
            if it.get("published_at") and not r.published_at:
                r.published_at, r.published_basis, r.tz_assumed = it["published_at"], f"{tool} 피드/검색 결과", bool(it.get("published_tz_assumed"))
            r.feed_date = r.feed_date or it.get("published_at")
            r.seen_at = r.seen_at or it.get("seen_at")
            r.collected_at = r.collected_at or collected
            r.snippet = r.snippet or it.get("summary", "")
            r.evidence_ids.append(evidence_id)

    def add_fetch(self, args: dict, data: dict | None, evidence_id: str, error: str | None = None, error_kind: str | None = None) -> None:
        r = self._rec(args.get("url", ""))
        if data is None:
            r.fetch_status, r.fetch_error = "failed", f"{error_kind or 'error'}"
            return
        r.fetch_status, r.fetched_at, r.text = "ok", data.get("fetched_at"), data.get("text", "")
        r.injection = data.get("injection_suspected", [])
        r.title = r.title or data.get("title", "")
        r.source = r.source or data.get("site_name", "")
        if data.get("published_at"):
            meta_dt = _dt(data["published_at"])
            date_only = data.get("published_precision") == "date"
            gap = abs((_dt(r.published_at) - meta_dt).total_seconds()) if r.published_at else None
            if gap is not None and date_only and gap <= 36 * 3600:
                r.published_basis = "피드 게시 시각(원문 메타데이터의 날짜와 일치)"  # 원문은 날짜만 있어, 시각이 정확한 피드 값을 유지한다
            else:
                if gap is not None and gap > (36 if date_only else 24) * 3600:
                    r.date_conflict = True  # 피드와 원문의 게시일이 하루 이상 다르면 표시한다
                r.published_at, r.published_basis, r.tz_assumed = data["published_at"], f"원문 메타데이터({data.get('published_source')})", bool(data.get("published_tz_assumed"))
                r.precision = "date" if date_only else "time"
        r.evidence_ids.append(evidence_id)

    def find(self, url: str) -> Record | None:
        return self.by_key.get(canonical_url(url or ""))

    def urls(self) -> set[str]:
        return {r.url for r in self.by_key.values()}


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def kst(s: str | None, tz: str, date_only: bool = False) -> str:
    if not s:
        return "미확인"
    if date_only:
        return _dt(s).strftime("%Y-%m-%d") + " (날짜만 확인, 시각 미상)"
    return _dt(s).astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M") + f" ({tz.split('/')[-1] if tz != 'Asia/Seoul' else 'KST'})"


_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?%?")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9.+#-]{2,}|[가-힣]{2,}")


def _tokens(s: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9.+#-]{1,}|[가-힣]{2,}|\d+", s)}


def same_event(a: dict, b: dict) -> bool:
    """두 기사가 같은 사건인지: 같은 URL, 매우 비슷한 제목, 또는 제목·사실 문장의 핵심 단어가 크게 겹침."""
    from .textutil import similarity

    if canonical_url(a["url"]) == canonical_url(b["url"]):
        return True
    ta, tb = _tokens(a["title"]), _tokens(b["title"])
    title_j = len(ta & tb) / len(ta | tb) if ta | tb else 0.0
    if similarity(a["title"], b["title"]) >= 0.7 or title_j >= 0.5:
        return True
    fa, fb = _tokens(" ".join(a["facts"])), _tokens(" ".join(b["facts"]))
    facts_j = len(fa & fb) / len(fa | fb) if fa | fb else 0.0
    return title_j >= 0.3 and facts_j >= 0.5


def _overlap(fact: str, text: str) -> float:
    """사실 문장이 출처 텍스트로 뒷받침되는 정도(0~1). 출처에 없는 수치가 하나라도 있으면 0, 아니면 내용어가 출처에 들어 있는 비율.

    문자 bigram 은 긴 원문에 대해 우연히 높게 나오므로(지어낸 문장도 통과) 단어 단위로 비교한다.
    한국어는 조사 때문에 어간(끝 한 글자 제외)이 출처에 있으면 일치로 본다.
    """
    low = text.lower()
    digits = re.sub(r"[,\s]", "", text)
    for n in _NUM.findall(fact):
        d = n.replace(",", "")
        if (n.endswith("%") or "." in d or len(d) >= 2) and d.rstrip("%") not in digits:
            return 0.0
    words = _WORD.findall(fact)
    if not words:
        return 0.0
    hit = sum((w.lower() in low) if w[0].isascii() else (w[: max(2, len(w) - 1)] in text) for w in words)
    return hit / len(words)


def build_report(*, title: str, intro: str, items: list[dict], excluded: list[dict], idx: NewsIndex, now: datetime, tz: str, max_age_hours: int,
                 max_items: int = 5, min_overlap: float = 0.55, sections: list[str] | None = None, missing: list[str] | None = None) -> tuple[str, dict]:
    """모델의 구조화 초안을 검증·보정해 Markdown 을 만든다. (보고서, 메타) — 메타는 검증 검사와 단계 기록에 쓴다."""
    kept: list[dict] = []
    dropped: list[dict] = []
    notes: list[str] = []
    seen_keys: set[str] = set()
    for raw in items:
        url = str(raw.get("url", ""))
        rec = idx.find(url)
        if rec is None:  # 수집되지 않은 URL 은 보고서에 넣지 않는다(모델이 지어낸 출처 방지)
            dropped.append({"title": str(raw.get("title") or "(제목 없음)")[:80], "reason": "수집 결과에 없는 URL이라 제외(출처 불명)"})
            continue
        key = canonical_url(rec.url)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        # 날짜만 아는 기사는 그날의 마지막 시각으로 보아 나이를 계산한다(신선한 기사를 날짜 해상도 때문에 과거로 오판하지 않는다)
        age_h = ((now - _dt(rec.published_at)).total_seconds() / 3600 - (23.98 if rec.precision == "date" else 0)) if rec.published_at else None
        if age_h is not None and age_h > max_age_hours:
            dropped.append({"title": rec.title, "reason": f"과거 기사(게시 {kst(rec.published_at, tz)}, 기준 {max_age_hours}시간 초과)"})
            continue
        status = rec.status()
        source_text = rec.text or f"{rec.title} {rec.snippet}"
        facts_ok, facts_dropped = [], 0
        for f in raw.get("facts") or []:
            txt = str(f.get("text", "") if isinstance(f, dict) else f).strip()
            if not txt:
                continue
            if _overlap(txt, source_text) < min_overlap:  # 원문(또는 제목·요약)에서 뒷받침되지 않는 사실 문장은 버린다
                facts_dropped += 1
                continue
            facts_ok.append(txt)
        if facts_dropped:
            notes.append(f"'{rec.title[:40]}': 근거와 맞지 않는 사실 문장 {facts_dropped}건 제외")
        if not facts_ok:
            dropped.append({"title": rec.title, "reason": "근거로 뒷받침되는 사실 문장이 없어 제외"})
            continue
        kept.append({"rec": rec, "status": status, "facts": facts_ok, "significance": str(raw.get("significance", "")).strip(), "blog_titles": [str(t).strip() for t in raw.get("blog_titles") or [] if str(t).strip()][:3],
                     "open": [str(t).strip() for t in raw.get("open_questions") or [] if str(t).strip()], "age_h": age_h})
    # 같은 사건을 다룬 기사가 둘 이상 선정되면 검증 수준이 높은 쪽 하나만 남긴다(사건 식별: URL·제목·사실 문장의 핵심 단어 겹침)
    rank = {V_FETCHED: 0, V_OFFICIAL: 1, V_UNVERIFIED: 2, V_FETCH_FAILED: 3}
    uniq: list[dict] = []
    for k in kept:
        ev = {"url": k["rec"].url, "title": k["rec"].title, "facts": k["facts"]}
        hit = next((u for u in uniq if same_event(ev, {"url": u["rec"].url, "title": u["rec"].title, "facts": u["facts"]})), None)
        if hit is None:
            uniq.append(k)
            continue
        worse, better = (k, hit) if rank[k["status"]] >= rank[hit["status"]] else (hit, k)
        if better is k:
            uniq[uniq.index(hit)] = k
        dropped.append({"title": worse["rec"].title, "reason": f"동일 사건 중복(‘{better['rec'].title[:30]}’과 같은 사건이라 하나만 선정)"})
    kept = uniq[:max_items]
    for k in kept:  # 뉴스별 ‘추가 확인’ 목록: 모델이 보고한 항목 + 원문 미확인이라는 코드 판단
        k["open_final"] = ([] if k["status"] == V_FETCHED else ["원문(또는 공식 발표문)으로 사실 관계를 확인한 뒤 사용하세요"]) + k["open"]

    ex =[{"title": str(e.get("title", ""))[:100], "reason": str(e.get("reason", ""))[:160]} for e in excluded if isinstance(e, dict)] + dropped

    def sec_overview() -> list[str]:
        counts: dict[str, int] = {}
        for k in kept:
            counts[k["status"]] = counts.get(k["status"], 0) + 1
        out = [f"> 보고서 생성 기준: {kst(now.strftime('%Y-%m-%dT%H:%M:%SZ'), tz)}, 대상 기간 최근 {max_age_hours}시간. 날짜는 {tz} 기준이며 게시일과 수집 시각은 별도로 표기합니다.",
               "> 이 보고서의 URL·날짜·검증 상태는 도구 수집 결과에서 코드가 기록한 값이고, ‘기술적 의미’와 ‘블로그 제목 후보’만 AI의 해석입니다.", "",
               f"- 수집된 후보 {len(idx.by_key)}건 중 선정 {len(kept)}건, 제외·보류 {len(ex)}건",
               "- 선정 뉴스의 검증 상태: " + (", ".join(f"{s} {n}건" for s, n in counts.items()) if counts else "해당 없음(선정된 뉴스 없음)")]
        if intro.strip():
            out += ["", intro.strip()]
        return out

    def sec_selected() -> list[str]:
        L: list[str] = []
        if not kept:
            L.append("조건을 충족하는 뉴스를 선정하지 못했습니다. 수집된 기사가 없거나 근거를 확인하지 못했습니다.")
        for n, k in enumerate(kept, 1):
            r: Record = k["rec"]
            L.append(f"### {n}. {r.title}")
            L.append(f"- **발표 기업/기관**: {r.org or r.source or '미확인'}")
            L.append(f"- **출처 URL**: {r.url}  (출처 매체: {r.source or '미확인'}, 구분: {'공식 발표/기술 블로그' if r.source_kind == 'official' else '언론' if r.source_kind == 'news' else '커뮤니티 링크'})")
            L.append(f"- **최초 게시일**: {kst(r.published_at, tz, r.precision == 'date')}" + (f" — 근거: {r.published_basis}" if r.published_at else " — 게시일을 확인하지 못함") + (" (시간대 없는 날짜라 가정 시간대 적용)" if r.tz_assumed else ""))
            L.append(f"- **수집 시각**: {kst(r.collected_at or r.fetched_at, tz)}" + (f" / 원문 조회 {kst(r.fetched_at, tz)}" if r.fetched_at else ""))
            L.append(f"- **검증 상태**: **{k['status']}**" + (f" ({r.fetch_error})" if r.fetch_status == "failed" else ""))
            if r.date_conflict:
                L.append("- ⚠ 피드의 게시일과 원문 메타데이터의 게시일이 24시간 이상 다릅니다. 원문 기준 날짜를 표기했습니다.")
            if r.injection:
                L.append(f"- ⚠ 원문에 지시문처럼 보이는 문구가 있었으나 데이터로만 취급했습니다: {', '.join(r.injection)}")
            label = "확인된 사실(원문 대조)" if k["status"] in VERIFIED_STATES else "공식 피드 요약상 사실(원문 미확인)" if k["status"] == V_OFFICIAL else "미검증 — 검색·피드 제목/요약상의 주장(확정된 사실 아님)"
            L.append(f"- **{label}**:")
            L += [f"  - {t}" for t in k["facts"]]
            L.append(f"- **기술적 의미 (AI 해석)**: {k['significance'] or '작성되지 않음(추가 확인 필요)'}")
            if k["blog_titles"]:
                L.append("- **블로그 제목 후보 (AI 제안)**: " + " / ".join(k["blog_titles"]))
            L.append("- **추가 확인이 필요한 내용**: " + ("; ".join(k["open_final"]) if k["open_final"] else "해당 없음"))
            L.append("")
        return L

    def sec_excluded() -> list[str]:
        return [f"- {e['title']} — {e['reason']}" for e in ex] or ["- 해당 없음 (제외·보류한 뉴스가 없습니다)"]

    def sec_open() -> list[str]:
        out = []
        for k in kept:
            if k["status"] != V_FETCHED:
                out.append(f"- {k['rec'].title}: 원문(또는 공식 발표문)으로 사실 관계 확인 필요 ({k['status']})")
            out += [f"- {k['rec'].title}: {q}" for q in k["open"]]
        out += [f"- {m}" for m in (missing or []) if str(m).strip()]
        return out or ["- 해당 없음 — 추가 확인이 필요하다고 보고된 내용이 없습니다. 사용 전에 각 뉴스의 검증 상태를 확인하세요."]

    def sec_method() -> list[str]:
        out = ["- 검증 상태 ‘원문 확인’은 web.fetch로 원문을 조회해 사실 문장이 원문과 겹치는지 코드가 확인했다는 뜻입니다. 모든 주장이 사실임을 보증하지 않습니다.",
               "- ‘공식 피드 기준’·‘미검증’ 항목은 제목·요약만 본 것이며 확정된 사실로 쓰면 안 됩니다."]
        return out + [f"- {n_}" for n_ in notes]

    def sec_sources() -> list[str]:
        return [f"- [{n}] {k['rec'].title} — {k['rec'].url} ({k['rec'].source or '매체 미확인'}, 게시 {kst(k['rec'].published_at, tz, k['rec'].precision == 'date')}, 검증 상태: {k['status']})"
                for n, k in enumerate(kept, 1)] or ["- 해당 없음 (선정된 뉴스가 없어 출처 목록이 없습니다)"]

    def sec_significance() -> list[str]:
        if not kept:
            return ["- 해당 없음 (선정된 뉴스가 없습니다)"]
        return ["> 아래는 AI의 해석이며 사실로 확인된 내용이 아닙니다.", ""] + [f"- **{k['rec'].title}**: {k['significance'] or '작성되지 않음(추가 확인 필요)'}" for k in kept]

    def sec_empty() -> list[str]:
        return ["- 해당 없음 — 이 보고서는 이 섹션에 해당하는 내용을 수집·검증하지 않았습니다(추가 확인 필요)."]

    def kind_of(name: str) -> str:
        n = name.lstrip("# ").strip()
        if re.search(r"개요|요약|overview|summary", n, re.I):
            return "overview"
        if "선정" in n:
            return "selected"
        if re.search(r"제외|보류", n):
            return "excluded"
        if re.search(r"추가\s*확인|확인\s*필요|확인\s*사항|미확인", n):
            return "open"
        if re.search(r"출처|참고\s*자료|참고\s*링크|source", n, re.I):
            return "sources"
        if re.search(r"기술적\s*의미|해석|시사점|인사이트", n):
            return "significance"
        if re.search(r"검증|방법|한계", n):
            return "method"
        return "empty"

    builders = {"overview": sec_overview, "selected": sec_selected, "excluded": sec_excluded, "open": sec_open, "method": sec_method, "sources": sec_sources, "significance": sec_significance, "empty": sec_empty}
    plan = [(s, kind_of(s)) for s in (sections or []) if s.strip()]
    for default, kind in (("선정 뉴스", "selected"), ("제외·보류한 뉴스", "excluded"), ("검증 방법과 한계", "method")):
        if not any(k == kind for _, k in plan):  # 업무가 요구하지 않아도 핵심 섹션은 항상 포함한다
            plan.append((default, kind))
    L = [f"# {title}".strip(), ""]
    for name, kind in plan:  # 요구된 섹션은 이름 그대로, 요구된 순서대로 반드시 만든다(내용이 없으면 ‘해당 없음/추가 확인 필요’로 표기)
        heading = name.strip() if name.strip().startswith("#") else f"## {name.strip()}"
        if kind == "selected" and "건)" not in heading:
            heading += f" ({len(kept)}건)"
        L += [heading, ""] + builders[kind]() + [""]
    items_struct = [{"title": k["rec"].title, "url": k["rec"].url, "status": k["status"], "published_at": k["rec"].published_at, "org": k["rec"].org, "source": k["rec"].source,
                     "collected_at": k["rec"].collected_at or k["rec"].fetched_at, "facts": k["facts"], "significance": k["significance"], "blog_titles": k["blog_titles"], "open": k["open_final"]}
                    for k in kept]
    meta = {"items": items_struct, "kept": len(kept), "statuses": {k["rec"].url: k["status"] for k in kept}, "dropped": dropped, "notes": notes, "stale_kept": sum(1 for k in kept if k["age_h"] is not None and k["age_h"] > max_age_hours),
            "claims": [{"text": t, "evidence": k["rec"].evidence_ids[:3]} for k in kept for t in k["facts"]]}
    return "\n".join(L).strip() + "\n", meta
