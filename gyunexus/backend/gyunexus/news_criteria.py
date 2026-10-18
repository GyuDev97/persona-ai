"""뉴스 조사 업무의 '구조적' 완료 기준을 구조화된 데이터에서 코드로 검사한다.

자연어 완료 기준 중 데이터 구조로 판정할 수 있는 것(중복 사건 제거, 필수 필드 포함, 사실/해석 구분, 건수, 언어·형식, 미검증 표기)은
LLM 의 '본문 인용' 검수에 맡기지 않는다. 집합 전체의 성질(예: '중복이 없다')이나 부재는 한 문장 인용으로 증명할 수 없기 때문이다.
의미적 정확성·해석의 적절성처럼 코드로 판별할 수 없는 기준은 인식하지 않고(None) 기존 LLM 검수로 넘긴다.
검사 조건은 완화하지 않으며, 보고서에 증명용 문장을 덧붙이지도 않는다.
"""

from __future__ import annotations

import re

from .news_report import V_FETCHED, same_event

# 의미 판단이 섞인 기준은 코드로 판정할 수 없으므로 통째로 LLM 검수에 맡긴다
SEMANTIC = re.compile(r"정확|적절|타당|충실|명확|논리|자연스|품질|신뢰할|올바|오류가\s*없|일치|근거가\s*충분|설득|유용|흥미|가치|참신|균형|공정|편향")
FIELDS = {
    "제목": r"제목(?!\s*후보)", "게시일": r"발표일|게시일|게시\s*일시|발행일|날짜", "출처 URL": r"URL|링크|출처\s*주소", "검증 상태": r"검증\s*상태",
    "발표 기업/기관": r"발표\s*기업|기관|회사", "수집 시각": r"수집\s*시각|수집일",
}
_NUM = r"(\d+)\s*(?:건|개)"


def classify(text: str) -> list[str] | None:
    """기준 문장에서 코드로 검사할 규칙 목록을 뽑는다. 하나라도 인식되지 않는 의미 판단이 섞여 있으면 None(LLM 검수)."""
    if SEMANTIC.search(text):
        return None
    rules: list[str] = []
    if "중복" in text:
        rules.append("dedupe")
    rules += [f"field:{name}" for name, pat in FIELDS.items() if re.search(pat, text)]
    if re.search(r"블로그\s*제목", text):
        rules.append("blog_titles")
    if re.search(r"추가\s*확인|확인\s*사항|확인이\s*필요", text):
        rules.append("open_items")
    if re.search(r"사실", text) and re.search(r"해석|의미", text) and re.search(r"구분|분리", text):
        rules.append("fact_vs_interpretation")
    if "한국어" in text:
        rules.append("korean")
    if re.search(r"markdown|마크다운", text, re.I):
        rules.append("markdown")
    if re.search(_NUM + r"\s*(이하|이내)|최대\s*" + _NUM, text):
        rules.append("count_max")
    if re.search(_NUM + r"\s*이상|최소\s*" + _NUM, text):
        rules.append("count_min")
    if re.search(r"미검증|검증되지\s*않|확인하지\s*못한|원문을\s*확인", text) and re.search(r"표시|표기|구분", text):
        rules.append("unverified_labeled")
    return rules or None


def _hangul_ratio(content: str) -> float:
    text = re.sub(r"https?://\S+", "", content)
    ko, en = len(re.findall(r"[가-힣]", text)), len(re.findall(r"[A-Za-z]", text))
    return ko / (ko + en) if ko + en else 0.0


def evaluate(rules: list[str], text: str, items: list[dict], content: str) -> tuple[bool, str]:
    """(통과 여부, 근거 설명). items 는 build_report 가 만든 뉴스별 구조화 데이터다."""
    fails: list[str] = []
    notes: list[str] = []
    for rule in rules:
        if rule == "dedupe":
            pairs = [(a["title"][:30], b["title"][:30]) for i, a in enumerate(items) for b in items[i + 1:] if same_event(a, b)]
            (fails if pairs else notes).append(f"같은 사건으로 보이는 선정 기사 쌍 {pairs[:2]}" if pairs else f"선정 {len(items)}건 사이에 같은 URL·같은 사건 없음")
        elif rule.startswith("field:"):
            name = rule[6:]
            key = {"제목": "title", "게시일": "published_at", "출처 URL": "url", "검증 상태": "status", "발표 기업/기관": "org", "수집 시각": "collected_at"}[name]
            miss = [it["title"][:25] for it in items if not (it.get(key) or (key == "org" and it.get("source")))]
            (fails if miss else notes).append(f"{name} 누락 {miss[:3]}" if miss else f"모든 기사에 {name} 있음")
        elif rule == "blog_titles":
            miss = [it["title"][:25] for it in items if not it["blog_titles"]]
            (fails if miss else notes).append(f"블로그 제목 후보 없는 기사 {miss[:3]}" if miss else "모든 기사에 블로그 제목 후보 있음")
        elif rule == "open_items":
            miss = [it["title"][:25] for it in items if not it["open"]]
            (fails if miss else notes).append(f"추가 확인 사항이 비어 있는 기사 {miss[:3]}" if miss else "모든 기사에 추가 확인 사항 있음")
        elif rule == "fact_vs_interpretation":
            miss = [it["title"][:25] for it in items if not it["facts"] or not it["significance"]]
            (fails if miss else notes).append(f"사실 또는 AI 해석이 비어 있는 기사 {miss[:3]}" if miss else "모든 기사에 사실과 AI 해석이 별도 필드로 있음")
        elif rule == "korean":
            r = _hangul_ratio(content)
            (fails if r < 0.3 else notes).append(f"한글 비율 {r:.0%}")
        elif rule == "markdown":
            ok = bool(re.search(r"^#\s+\S", content, re.M)) and bool(re.search(r"^##\s+\S", content, re.M))
            (notes if ok else fails).append("Markdown 제목 구조 " + ("있음" if ok else "없음"))
        elif rule == "count_max":
            m = re.search(_NUM + r"\s*(?:이하|이내)", text) or re.search(r"최대\s*" + _NUM, text)
            n = int(m.group(1)) if m else 5
            (fails if len(items) > n else notes).append(f"선정 {len(items)}건 (최대 {n}건)")
        elif rule == "count_min":
            m = re.search(_NUM + r"\s*이상", text) or re.search(r"최소\s*" + _NUM, text)
            n = int(m.group(1)) if m else 1
            (fails if len(items) < n else notes).append(f"선정 {len(items)}건 (최소 {n}건)")
        elif rule == "unverified_labeled":
            bad = []
            for it in items:
                if it["status"] != V_FETCHED:
                    at = content.find(it["url"])
                    block = content[at: at + 1500] if at >= 0 else ""
                    if not any(k in block for k in ("미검증", "원문 미확인", "원문 확인 실패")):
                        bad.append(it["title"][:25])
            (fails if bad else notes).append(f"미검증 표기가 없는 기사 {bad[:3]}" if bad else "원문 미확인 기사는 모두 미검증으로 표기됨")
    return (not fails), "; ".join(fails or notes)
