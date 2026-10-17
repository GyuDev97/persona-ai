"""토론 참가자 선택. 필수 여부는 규칙이 결정하고, LLM의 제안은 참고만 한다.

모든 에이전트에 대해 선택/제외 여부와 이유를 남긴다(Debate.plan, 활동 로그).
"""

from __future__ import annotations

import re

from .definitions import ORDER

# 외부 사실·수치·최신 정보가 필요한 표현
NEEDS_FACTS = re.compile(
    r"이번\s?주|오늘|내일|모레|주말|지금|현재|최신|올해|\d{4}년|날씨|구름|강수|기온|월령|달\s?(위상|밝기)|시세|가격|환율|통계|수치"
    r"|몇|언제|어디|장소|명소|위치|스팟|출사지|규정|법률|스펙|사양|인기|순위|뉴스|사실인|검증"
)
VERIFY_ONLY = re.compile(r"사실인가|맞는가|맞나요|사실인지|진위")
SOFTWARE = re.compile(
    r"구현|개발|코드|프로그램|API|서버|데이터베이스|\bDB\b|앱\b|소프트웨어|시스템|알고리즘|자동화|아키텍처|FastAPI|React|Python|"
    r"GyuNexus|임베딩|LLM|프롬프트|에이전트|스크립트|배포"
)


def plan_participants(title: str, rationale: str, llm_data: dict, enabled: set[str]) -> dict:
    """반환: participants(순서 고정), reasons(에이전트별 선택 여부·이유), needs_facts."""
    text = title  # 선정 근거(rationale)에는 기억에서 따온 단어가 섞여 오판을 부르므로 주제 제목만 본다
    suggested = {p for p in llm_data.get("participants", []) if isinstance(p, str)}
    reasons: dict[str, dict] = {}

    def decide(agent: str, selected: bool, reason: str, by: str) -> None:
        if agent not in enabled:
            reasons[agent] = {"selected": False, "reason": f"{reason} (에이전트가 비활성화되어 제외)", "by": by}
        else:
            reasons[agent] = {"selected": selected, "reason": reason, "by": by}

    m = NEEDS_FACTS.search(text)
    needs_facts = bool(m)
    if m:
        note = "" if "research" in suggested else " (LLM은 제외를 제안했으나 규칙이 우선)"
        decide("research", True, f"외부 사실·수치·최신 정보가 필요한 표현 '{m.group(0)}' -> 조사 필수{note}", "rule")
    elif "research" in suggested:
        decide("research", False, "LLM이 제안했지만 외부 사실이 필요한 표현이 없어 제외", "rule")
    else:
        decide("research", False, "외부 사실·수치·최신 정보가 필요한 표현이 없어 제외", "rule")

    if VERIFY_ONLY.search(text):
        decide("idea", False, "사실 여부 검증이 목적이라 새 아이디어 발굴은 불필요", "rule")
    else:
        decide("idea", True, "아이디어·방안 도출이 목적이므로 참여", "rule+llm" if "idea" in suggested else "rule")

    s = SOFTWARE.search(text)
    if s:
        decide("developer", True, f"소프트웨어 구현 검토가 필요한 표현 '{s.group(0)}'", "rule")
    elif "developer" in suggested:
        decide("developer", False, "LLM이 제안했지만 소프트웨어 구현 주제가 아니라 전문성이 맞지 않아 제외", "rule")
    else:
        decide("developer", False, "소프트웨어 구현과 무관한 주제라 제외", "rule")

    decide("critic", True, "주장과 결론에 대한 검토는 항상 필요", "rule")

    chosen = [a for a in ORDER if reasons[a]["selected"]]
    if len(chosen) < 2 and "idea" in enabled and "idea" not in chosen:
        reasons["idea"] = {"selected": True, "reason": "최소 2명 구성을 위해 포함", "by": "rule"}
        chosen = [a for a in ORDER if reasons[a]["selected"]]
    return {"participants": chosen, "reasons": reasons, "needs_facts": needs_facts and "research" in chosen}
