"""증거·주장 검증. 모두 규칙 기반이라 LLM 호출이 없고 결과가 결정적이다.

- 도구 결과에서 경고·제약(flags)을 코드가 직접 계산한다(강수확률, 구름량, 달빛, 조회 실패 등).
- 주장을 사실(fact) / 해석(interpretation) / 추정(assumption) / 제안(proposal)으로 나누고,
  `verified`는 인용한 증거가 직접 뒷받침하는 사실 주장에만 부여한다.
- 증거와 충돌하는 서술, 근거 없는 장소·제품·브랜드 이름을 탐지한다.
"""

from __future__ import annotations

import json
import re
from datetime import date

CLAIM_TYPES = ("fact", "interpretation", "assumption", "proposal")
PRECIP_WARN_PCT = 40
CLOUD_WARN_PCT = 60

# ---------------------------------------------------------------------------
# 도구 결과 -> 경고/제약
# ---------------------------------------------------------------------------


def _flag(code: str, text: str, severity: str = "warn", date_: str | None = None, period: str | None = None,
          location: str | None = None) -> dict:
    return {"code": code, "severity": severity, "text": text, "date": date_, "period": period, "location": location}


def _weather_flags(d: dict, date_: str | None, period: str | None, location: str | None) -> list[dict]:
    flags = []
    where = f"{date_ or ''} {period or ''} {location or ''}".strip()
    precip, cloud = d.get("max_precip_prob_pct"), d.get("avg_cloud_cover_pct")
    if precip is not None and precip >= PRECIP_WARN_PCT:
        flags.append(_flag("high_precip", f"강수확률 {precip}% ({where}): 비·강수 위험이 높음", date_=date_, period=period, location=location))
    if cloud is not None and cloud >= CLOUD_WARN_PCT:
        flags.append(_flag("cloudy", f"평균 구름량 {cloud}% ({where}): 하늘이 가려질 가능성이 높음", date_=date_, period=period, location=location))
    if d.get("window_passed"):
        flags.append(_flag("window_passed", f"요청 시간대({where})는 이미 지남", date_=date_, period=period, location=location))
    return flags


def evidence_flags(tool: str, data: dict | None, error: str | None = None, error_kind: str | None = None) -> list[dict]:
    """도구 결과(또는 실패)에서 최종 결론까지 전달해야 할 경고·제약을 계산한다."""
    if error is not None:
        return [_flag("tool_failed", f"{tool} 조회 실패({error_kind or 'error'}): 이 데이터는 확인할 수 없음", severity="error")]
    data = data or {}
    flags: list[dict] = []
    if tool == "weather.forecast":
        if "nights_22_to_03" in data:
            for n in data["nights_22_to_03"]:
                flags += _weather_flags(n, n.get("date"), "밤", None)
        else:
            flags += _weather_flags(data, data.get("date"), data.get("period"), data.get("location"))
    elif tool == "astro.moon_phase":
        if data.get("dark_sky_friendly") is False:
            when = (data.get("for") or {}).get("date")
            flags.append(_flag(
                "moon_bright",
                f"달 밝기 {data.get('illumination_pct')}%({data.get('phase')}): 어두운 하늘 조건이 아님(dark_sky_friendly=false), 은하수 촬영에 불리",
                date_=when,
            ))
    elif tool == "wiki.search" and not data.get("results"):
        flags.append(_flag("no_results", "관련 있는 검색 결과가 없음", severity="info"))
    return flags


def flags_text(flags: list[dict]) -> str:
    return " / ".join(f"{'⚠' if f['severity'] != 'info' else 'ℹ'} {f['text']}" for f in flags)


# ---------------------------------------------------------------------------
# 증거와 충돌하는 서술 탐지
# ---------------------------------------------------------------------------

_DATE_REF = re.compile(r"\d{1,2}\s?월\s?\d{1,2}\s?일|(?<![\d월])\d{1,2}\s?일|\d{4}-\d{2}-\d{2}|[월화수목금토일]요일")
_WEEKDAYS = "월화수목금토일"


def _mentions(text: str, iso: str) -> bool:
    d = date.fromisoformat(iso)
    return bool(
        re.search(rf"{d.month}\s?월\s?{d.day}\s?일|(?<![\d월]){d.day}\s?일|{iso}|{_WEEKDAYS[d.weekday()]}요일", text)
    )


def _date_keys(text: str) -> set[str]:
    """글에 언급된 서로 다른 날짜 수를 세기 위한 키(일 숫자 또는 요일)."""
    keys = {m.group(1) for m in re.finditer(r"\d{4}-\d{2}-(\d{2})", text)}
    keys |= {m.group(1).lstrip("0") for m in re.finditer(r"(?<![\d-])(\d{1,2})\s?일", text)}
    keys |= {m.group(1) for m in re.finditer(r"([월화수목금토일])요일", text)}
    return {k.lstrip("0") for k in keys}


def _applies(sentence: str, whole: str, flag: dict) -> bool:
    """경고가 가리키는 날짜와 서술이 같은 날짜를 말하는지. 날짜 없는 일반론은 글 전체가 그 날짜 하나만 다룰 때만 적용한다."""
    if not flag.get("date"):
        return True
    if _mentions(sentence, flag["date"]):
        return True
    if _DATE_REF.search(sentence):
        return False
    keys = _date_keys(whole)
    return not keys or (_mentions(whole, flag["date"]) and len(keys) == 1)


def _precip_low(s: str) -> bool:
    return bool(re.search(r"강수|비\s?(발생|올|오|확률|가)|우천|소나기", s)) and bool(
        re.search(r"낮|적은|적고|적다|적어|적습|없|오지\s?않|안\s?옵", s)
    ) and not re.search(r"높|위험|주의|올 수|낮지\s?않|적지\s?않", s)


def _sky_clear(s: str) -> bool:
    return bool(re.search(r"맑|청명|구름.{0,8}(적은|적고|적다|적어|적습|없|낮|거의)", s)) and not re.search(
        r"흐|많|높|가려|불리|맑지\s?않|아니|않", s
    )


def _moon_ok(s: str) -> bool:
    return bool(re.search(r"달|월령|달빛", s)) and bool(re.search(r"유리|적합|좋|어두|문제\s?없|영향\s?없|괜찮", s)) and not re.search(
        r"불리|부적합|좋지\s?않|방해|어렵|밝아|밝은|밝지만|밝으나|밝긴|영향을\s?(줄|미칠|받)|아니|않|못", s  # '밝지만 ~'은 한계를 인정한 서술
    )


_CONFLICT_RULES = {"high_precip": _precip_low, "cloudy": _sky_clear, "moon_bright": _moon_ok}
# 날짜 없이 "~하는 것이 좋다/구름이 적은 장소를 찾아야 한다"처럼 일반 원칙·권고를 말하는 문장은 특정 날짜의 사실 서술이 아니다
_NORMATIVE = re.compile(r"해야|필요|바람직|선택|찾|이동|조사|고려|권장|장소|지역|곳")


def find_conflicts(text: str, flags: list[dict]) -> list[dict]:
    """서술이 증거의 경고와 충돌하면 해당 경고를 돌려준다(같은 날짜를 말할 때만)."""
    out: list[dict] = []
    sentences = [s.strip() for s in re.split(r"[.!?\n]+", text) if s.strip()]
    for flag in flags:
        rule = _CONFLICT_RULES.get(flag["code"])
        if rule is None or flag["severity"] == "info":
            continue
        for s in sentences:
            if _NORMATIVE.search(s) and not _DATE_REF.search(s):
                continue
            if rule(s) and _applies(s, text, flag):
                out.append({**flag, "sentence": s[:120]})
                break
    return out


# ---------------------------------------------------------------------------
# 수치 / 고유명사
# ---------------------------------------------------------------------------

_NUM = re.compile(r"\d+(?:\.\d+)?")
_PLACE_RE = re.compile(
    r"[가-힣]{2,8}(?:\s?(?:천문대|폭포|국립공원|전망대|해수욕장|일출봉)|(?:공원|호수|해변|계곡|휴게소|산|섬|봉|대교|마을))"
)
_GENERIC_PREFIX = {"인근", "주변", "근처", "가까운", "유명한", "해당", "어떤", "특정", "국내", "현지", "지역", "근교", "인접"}
_MODEL_RE = re.compile(r"[A-Z][A-Za-z]*\s?\d+[A-Za-z]*(?:\s?(?:II|III|IV))?")
_BRANDS = ("캐논", "소니", "니콘", "후지필름", "시그마", "삼양", "Adobe", "Lightroom", "Photoshop", "GIMP", "Stellarium")
# 제품·라이브러리·서비스 이름처럼 보이는 영문 토큰(CamelCase, 첫 글자 대문자 단어, 3~5자 대문자 약어). 일반 약어는 제외한다.
_TECH_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Z][a-z]+[A-Z][A-Za-z0-9]*|[a-z]+[A-Z][A-Za-z0-9]*|[A-Z][a-z]{2,}(?:\s[A-Z][a-z]+)*|[A-Z]{3,5})(?![A-Za-z0-9])"
)  # 한글 조사가 바로 붙어도(예: spaCy와) 잡도록 ASCII 기준 경계를 쓴다
_GENERIC_ACRONYMS = {"API", "NLP", "GPU", "CPU", "SQL", "HTTP", "JSON", "REST", "URL", "LLM", "ISO", "DSLR", "RAW", "GPS", "UTC", "KST",
                     "SSE", "HTML", "CSS", "OCR", "TTS", "STT", "RAM", "USB", "PDF", "CSV", "XML"}
_GENERIC_PLACES = {"도시공원", "근린공원", "자연공원", "테마공원", "국립공원", "생산", "관측소"}


def numbers_missing(text: str, evidence_text: str) -> list[str]:
    have = {float(n) for n in _NUM.findall(evidence_text)}
    return [n for n in _NUM.findall(text) if float(n) not in have]


def unverified_entities(text: str, known_text: str) -> list[str]:
    """주제·기억·증거 어디에도 나오지 않는 장소/제품/브랜드 이름(존재를 확인할 수 없는 이름)."""
    found = {m.group(0).strip() for m in _PLACE_RE.finditer(text)} | {m.group(0).strip() for m in _MODEL_RE.finditer(text)}
    found |= {b for b in _BRANDS if b.lower() in text.lower()}
    found |= {m.group(0) for m in _TECH_RE.finditer(text) if m.group(0) not in _GENERIC_ACRONYMS}
    low = known_text.lower()
    return sorted(
        e for e in found
        if e not in _GENERIC_PLACES and e.split()[0] not in _GENERIC_PREFIX and e.lower() not in low
        and not (" " in e and re.search(r"(은|는|운|한|인|의|적|높|낮|큰)$", e.split()[0]))  # '적은 국립공원' 같은 수식어 + 일반명사
        and not re.fullmatch(r"[EBR]\d+", e)  # 증거·반박·라운드 번호(E1, B2, R3)
        and re.split(r"\d", e)[0].strip() not in {"ISO", "EV", "Lv", "UTC", "KST"}  # 일반 단위/설정 용어
    )


# ---------------------------------------------------------------------------
# 주장 분류·검증
# ---------------------------------------------------------------------------

_JUDGMENT = re.compile(r"적합|유리|불리|좋|최적|추천|바람직|가능성|것으로\s?(보|예상)|예상|될 것|괜찮|충분|무난|위험")


def normalize_type(raw, text: str) -> str:
    t = raw if raw in CLAIM_TYPES else "assumption"  # opinion 등 알 수 없는 값은 추정으로 취급
    if t == "fact" and _JUDGMENT.search(text):
        return "interpretation"  # 판단이 섞인 문장은 사실이 아니라 해석이다
    return t


def verify_claim(text: str, raw_type, evidence_ids, evidence: dict[int, dict], known_text: str, flags: list[dict]) -> dict:
    """주장 하나를 분류하고 검증한다. evidence: id -> {"tool","summary","flags","status"}."""
    ctype = normalize_type(raw_type, text)
    ids = []
    for i in evidence_ids or []:
        try:
            if int(i) in evidence and (evidence[int(i)].get("status") or "ok") == "ok":
                ids.append(int(i))
        except (TypeError, ValueError):
            pass
    cited = " ".join(f"{evidence[i]['summary']} {flags_text(evidence[i].get('flags') or [])}" for i in ids)
    notes: list[str] = []
    ents = unverified_entities(text, f"{known_text} {cited}")
    conflicts = find_conflicts(text, flags)

    if ctype == "fact":
        if not ids:
            status, notes = "unverified", ["증거 인용 없음"]
        else:
            missing = numbers_missing(text, cited)
            if missing:
                status, notes = "unverified", [f"인용한 증거에 없는 수치: {', '.join(missing)}"]
            elif ents:
                status, notes = "unverified", [f"근거 없는 이름: {', '.join(ents)}"]
            else:
                status = "verified"
    elif ctype == "interpretation":
        status = "interpretation" if ids else "assumption"
        if not ids:
            notes.append("해석의 근거 증거 없음")
    elif ctype == "proposal":
        status = "proposal"
    else:
        status = "assumption"
    if ents and status != "verified":
        notes.append(f"존재 미확인: {', '.join(ents)}")
    if conflicts and status in ("verified", "interpretation", "proposal"):
        status = "conflicted"
        notes.append("증거 경고와 충돌: " + "; ".join(c["text"] for c in conflicts))
    return {"type": ctype, "status": status, "evidence_ids": ids, "notes": notes, "entities": ents,
            "conflicts": [c["text"] for c in conflicts]}


def uncovered_dates(text: str, evidence_dates: set[str]) -> list[str]:
    """글이 언급한 날짜/월 중 어떤 증거도 다루지 않은 것(예: 예보를 조회한 적 없는 '11월 초')."""
    have_md = {(int(d[5:7]), int(d[8:10])) for d in evidence_dates}
    have_m = {m for m, _ in have_md}
    out: list[str] = []
    for iso in re.findall(r"\d{4}-\d{2}-\d{2}", text):
        if (int(iso[5:7]), int(iso[8:10])) not in have_md:
            out.append(iso)
    for m, d in re.findall(r"(\d{1,2})\s?월\s?(\d{1,2})\s?일", text):
        if (int(m), int(d)) not in have_md:
            out.append(f"{m}월 {d}일")
    for m in re.findall(r"(\d{1,2})\s?월\s?(?:초|중순|중|말|경)", text):
        if int(m) not in have_m:
            out.append(f"{m}월 초/중/말")
    return sorted(set(out))


def evidence_summary(data) -> str:
    return json.dumps(data, ensure_ascii=False)[:900]
