"""대화 상태(주제·조건) 관리와 도구 라우팅.

후속 질문("그럼 토요일 새벽은?", "강원도에서 보면?")이 들어오면 이전 대화 상태를 바탕으로 바뀐 조건만 갱신하고,
현재 조건에 맞는 도구 호출 계획을 세운다. 규칙으로 확정되는 경우에는 LLM을 호출하지 않고,
규칙만으로 판단이 어려운 후속 발화에만 짧은 의도 해석 호출을 한 번 사용한다.

새 주제는 TOPICS 와 PLANNERS 에 항목을 추가하면 된다. 은하수 전용 필드는 상태(slots)에 강제되지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete

from .activity import Activity
from .config import Settings
from .db import Database
from .llm import LLMError, LLMGateway
from .models import ConversationState as StateRow
from .models import utcnow

STATE_TTL = timedelta(hours=6)  # 이 시간 넘게 대화가 없으면 이전 주제를 이어가지 않는다
VALID_PERIODS = ("새벽", "아침", "낮", "저녁", "밤")
NOT_COVERED_SKY = ["월출·월몰 시각", "관측 장소의 광해(빛공해) 수준과 시야"]

# ---------------------------------------------------------------------------
# 지명 사전: 별칭 -> (표준 이름, 위도, 경도, 정밀도). 도 단위는 대표 도시 좌표를 쓰고 precision="province"로 표시한다.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Place:
    name: str
    lat: float
    lon: float
    precision: str  # city | province | coordinates | configured


def _build_places() -> dict[str, Place]:
    rows = [
        # (별칭들, 이름, 위도, 경도, 정밀도)
        (("서울", "서울시", "서울특별시"), "서울", 37.5665, 126.9780, "city"),
        (("부산", "부산시", "부산광역시"), "부산", 35.1796, 129.0756, "city"),
        (("대구", "대구시", "대구광역시"), "대구", 35.8714, 128.6014, "city"),
        (("인천", "인천시", "인천광역시"), "인천", 37.4563, 126.7052, "city"),
        (("대전", "대전시", "대전광역시"), "대전", 36.3504, 127.3845, "city"),
        (("울산", "울산시", "울산광역시"), "울산", 35.5384, 129.3114, "city"),
        (("세종", "세종시", "세종특별자치시"), "세종", 36.4800, 127.2890, "city"),
        (("광주광역시",), "광주광역시", 35.1595, 126.8526, "city"),
        (("경기 광주", "경기도 광주", "광주시"), "경기 광주", 37.4296, 127.2551, "city"),
        (("강원 고성", "강원도 고성"), "강원 고성", 38.3806, 128.4678, "city"),
        (("경남 고성", "경상남도 고성"), "경남 고성", 34.9731, 128.3228, "city"),
        (("춘천",), "춘천", 37.8813, 127.7298, "city"),
        (("강릉",), "강릉", 37.7519, 128.8761, "city"),
        (("속초",), "속초", 38.2070, 128.5918, "city"),
        (("양양",), "양양", 38.0754, 128.6190, "city"),
        (("평창",), "평창", 37.3705, 128.3901, "city"),
        (("영월",), "영월", 37.1837, 128.4617, "city"),
        (("태백",), "태백", 37.1641, 128.9856, "city"),
        (("정선",), "정선", 37.3807, 128.6608, "city"),
        (("홍천",), "홍천", 37.6971, 127.8885, "city"),
        (("인제",), "인제", 38.0697, 128.1708, "city"),
        (("삼척",), "삼척", 37.4499, 129.1651, "city"),
        (("원주",), "원주", 37.3422, 127.9202, "city"),
        (("수원",), "수원", 37.2636, 127.0286, "city"),
        (("청주",), "청주", 36.6424, 127.4890, "city"),
        (("전주",), "전주", 35.8242, 127.1480, "city"),
        (("안동",), "안동", 36.5684, 128.7294, "city"),
        (("창원",), "창원", 35.2279, 128.6811, "city"),
        (("포항",), "포항", 36.0190, 129.3435, "city"),
        (("경주",), "경주", 35.8562, 129.2247, "city"),
        (("여수",), "여수", 34.7604, 127.6622, "city"),
        (("목포",), "목포", 34.8118, 126.3922, "city"),
        (("청송",), "청송", 36.4360, 129.0572, "city"),
        (("합천",), "합천", 35.5667, 128.1658, "city"),
        (("무주",), "무주", 35.9074, 127.6608, "city"),
        (("제주시",), "제주시", 33.4996, 126.5312, "city"),
        (("강원도", "강원특별자치도", "강원"), "강원도", 37.8813, 127.7298, "province"),  # 대표 지점: 춘천
        (("경기도", "경기"), "경기도", 37.2636, 127.0286, "province"),  # 수원
        (("충청북도", "충북"), "충청북도", 36.6424, 127.4890, "province"),  # 청주
        (("충청남도", "충남"), "충청남도", 36.6013, 126.6608, "province"),  # 홍성
        (("전라북도", "전북", "전북특별자치도"), "전라북도", 35.8242, 127.1480, "province"),  # 전주
        (("전라남도", "전남"), "전라남도", 34.9900, 126.4817, "province"),  # 무안
        (("경상북도", "경북"), "경상북도", 36.5684, 128.7294, "province"),  # 안동
        (("경상남도", "경남"), "경상남도", 35.2279, 128.6811, "province"),  # 창원
        (("제주도", "제주특별자치도", "제주"), "제주도", 33.4996, 126.5312, "province"),  # 제주시
    ]
    out: dict[str, Place] = {}
    for aliases, name, lat, lon, precision in rows:
        for a in aliases:
            out[a] = Place(name, lat, lon, precision)
    return out


PLACES = _build_places()
# 단독으로 쓰면 여러 곳을 가리키는 지명
AMBIGUOUS = {"광주": ["광주광역시", "경기 광주"], "고성": ["강원 고성", "경남 고성"]}
_ALIASES = sorted(set(PLACES) | set(AMBIGUOUS), key=len, reverse=True)
NON_PLACE = {"오늘", "내일", "모레", "지금", "새벽", "아침", "저녁", "오후", "오전", "여기", "거기", "집", "베란다", "옥상", "하늘", "밤", "낮"}
UNRESOLVED_PLACE = re.compile(r"([가-힣]{2,7})\s?(?:에서|에선|기준으로|기준|쪽에서|근처에서|근처)")
COORDS = re.compile(r"(\d{2}\.\d+)\s*[, ]\s*(\d{3}\.\d+)")


@dataclass
class PlaceSignal:
    place: Place | None = None
    ambiguous: list[str] | None = None
    unresolved: str | None = None

    @property
    def any(self) -> bool:
        return bool(self.place or self.ambiguous or self.unresolved)


def find_place(text: str) -> PlaceSignal:
    """문장에서 장소를 찾는다. 여러 개면 가장 마지막에 말한 것을 채택한다(정정 발화 "A 말고 B")."""
    m = COORDS.search(text)
    if m:
        return PlaceSignal(place=Place("지정 좌표", float(m.group(1)), float(m.group(2)), "coordinates"))
    spans: list[tuple[int, int, str]] = []
    for alias in _ALIASES:
        for hit in re.finditer(re.escape(alias), text):
            if not any(hit.start() < e and hit.end() > s for s, e, _ in spans):
                spans.append((hit.start(), hit.end(), alias))
    if spans:
        alias = max(spans)[2]
        if alias in AMBIGUOUS:
            return PlaceSignal(ambiguous=AMBIGUOUS[alias])
        return PlaceSignal(place=PLACES[alias])
    for tok in UNRESOLVED_PLACE.findall(text):
        if tok not in NON_PLACE and not re.search(r"요일$|^\d", tok):
            return PlaceSignal(unresolved=tok)
    return PlaceSignal()


# ---------------------------------------------------------------------------
# 날짜·시간대 해석
# ---------------------------------------------------------------------------

WEEKDAY_IDX = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
WEEKDAY_KO = "월화수목금토일"
RELATIVE_DAYS = [("그저께", -2), ("그제", -2), ("어제", -1), ("오늘", 0), ("내일모레", 2), ("내일", 1), ("모레", 2), ("글피", 3)]
PERIOD_TOKENS = [("한밤", "밤"), ("심야", "밤"), ("새벽", "새벽"), ("아침", "아침"), ("오전", "아침"), ("점심", "낮"),
                 ("낮", "낮"), ("오후", "낮"), ("저녁", "저녁"), ("밤(?!하늘)", "밤")]


@dataclass
class DateSignal:
    date: date | None = None
    beyond: bool = False  # "다음 달"처럼 날짜로 못 바꾸는 먼 미래 표현
    mentioned: bool = False


def parse_date(text: str, today: date) -> DateSignal:
    if re.search(r"다음\s?달|내년|\d+\s?(?:개월|달)\s?(?:뒤|후)", text):
        return DateSignal(beyond=True, mentioned=True)
    m = re.search(r"(\d{1,2})\s?월\s?(\d{1,2})\s?일", text)
    if m:
        try:
            d = date(today.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return DateSignal(mentioned=True)
        if (today - d).days > 180:
            d = d.replace(year=d.year + 1)
        return DateSignal(date=d, mentioned=True)
    m = re.search(r"(\d{1,3})\s?일\s?(?:뒤|후)", text)
    if m:
        return DateSignal(date=today + timedelta(days=int(m.group(1))), mentioned=True)
    for word, offset in RELATIVE_DAYS:
        if word in text:
            return DateSignal(date=today + timedelta(days=offset), mentioned=True)
    m = re.search(r"(다음\s?주|담주|이번\s?주)?\s?([월화수목금토일])요일", text)
    if m:
        w = WEEKDAY_IDX[m.group(2)]
        qualifier = (m.group(1) or "").replace(" ", "")
        monday = today - timedelta(days=today.weekday())
        if qualifier in ("다음주", "담주"):
            d = monday + timedelta(days=7 + w)
        elif qualifier == "이번주":
            d = monday + timedelta(days=w)
        else:
            d = today + timedelta(days=(w - today.weekday()) % 7)
        return DateSignal(date=d, mentioned=True)
    if "주말" in text:
        return DateSignal(date=today + timedelta(days=(5 - today.weekday()) % 7 if today.weekday() < 5 else 0), mentioned=True)
    m = re.search(r"(?<![\d월])(\d{1,2})\s?일(?!\s?(?:뒤|후|간|동안))", text)
    if m and 1 <= int(m.group(1)) <= 31:
        day = int(m.group(1))
        try:
            d = date(today.year, today.month, day)
            if d < today:
                d = date(today.year + (today.month == 12), today.month % 12 + 1, day)
        except ValueError:
            return DateSignal(mentioned=True)
        return DateSignal(date=d, mentioned=True)
    return DateSignal()


def parse_period(text: str) -> str | None:
    """가장 마지막에 언급한 시간대를 채택한다."""
    best: tuple[int, str] | None = None
    for pattern, period in PERIOD_TOKENS:
        for m in re.finditer(pattern, text):
            if best is None or m.start() > best[0]:
                best = (m.start(), period)
    return best[1] if best else None


# ---------------------------------------------------------------------------
# 주제 정의 / 감지
# ---------------------------------------------------------------------------

# 조건(slot) 그룹: 하나의 조건이 여러 저장 키로 이뤄진다
SLOT_GROUPS = {
    "target_date": ("target_date", "date_issue"),
    "time_period": ("time_period",),
    "location": ("location", "location_precision", "latitude", "longitude", "location_candidates", "location_unresolved"),
}
# 주제마다 사용하는 조건만 선언한다. 선언하지 않은 조건은 상태에 저장되지 않는다(예: 뉴스에는 장소가 없다).
TOPICS: dict[str, dict] = {
    "sky_observation": {"label": "은하수·별 관측", "slots": ("target_date", "time_period", "location"),
                        "defaults": {"time_period": "밤"}, "carry_from": {"weather"}},
    "weather": {"label": "날씨", "slots": ("target_date", "time_period", "location"), "defaults": {}, "carry_from": {"sky_observation"}},
    "news": {"label": "뉴스", "slots": ("target_date",), "defaults": {}, "carry_from": set()},
}
TOPIC_PATTERNS = [
    ("news", re.compile(r"뉴스|속보|헤드라인|기사")),
    ("sky_observation", re.compile(r"은하수|별자리|천체|출사|밤하늘|월령|보름달|초승달|그믐|별\s?(보|촬영|사진)")),
    ("weather", re.compile(r"날씨|기온|온도|구름|비\s?(와|올|오)|눈\s?(와|올)|우산|맑")),
]
FOLLOWUP_MARKER = re.compile(r"^\s*(그럼|그러면|그렇다면|아니|그건|그거|거기|그쪽|그날|그때|다른|그리고|근데)")


ASKING = re.compile(r"\?|어때|어떨|어떻|될까|있을까|알려|보면|기준|말고|아니|좋아|괜찮|보여")


def detect_topic(text: str) -> str | None:
    for topic, pattern in TOPIC_PATTERNS:
        if pattern.search(text):
            return topic
    return None


def is_followup_marker(text: str) -> bool:
    t = text.strip()
    return len(t) <= 30 and bool(FOLLOWUP_MARKER.match(t) or t.endswith(("는?", "은?", "면?", "도?")))


# ---------------------------------------------------------------------------
# 상태
# ---------------------------------------------------------------------------

CARRY_KEYS = ("target_date", "time_period", "location", "location_precision", "latitude", "longitude",
              "location_candidates", "location_unresolved", "date_issue")
PRIVATE_KEYS = ("latitude", "longitude")  # 추적 정보/로그에는 좌표를 남기지 않는다


@dataclass
class ConversationState:
    topic: str | None = None
    slots: dict = field(default_factory=dict)  # target_date, time_period, location, location_precision, ...
    missing_fields: list[str] = field(default_factory=list)

    def public(self) -> dict:
        return {
            "topic": self.topic,
            "slots": {k: v for k, v in self.slots.items() if k not in PRIVATE_KEYS and v is not None},
            "missing_fields": self.missing_fields,
        }


@dataclass
class Routing:
    intent: str  # new_topic | followup | chat
    interpreted_by: str  # rules | llm
    reason: str
    prior: dict | None
    state: ConversationState | None = None  # 병합된 최종 상태(저장 대상). chat이면 None
    changes: dict = field(default_factory=dict)
    plan: list[dict] = field(default_factory=list)  # {"tool","args","reason"}
    skipped: list[dict] = field(default_factory=list)  # {"tool","reason"}
    advice: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)  # 프롬프트에 넣을 "조회하지 못한 데이터" 설명

    def trace(self) -> dict:
        return {
            "intent": self.intent,
            "interpreted_by": self.interpreted_by,
            "reason": self.reason,
            "prior_state": self.prior,
            "changes": self.changes,
            "merged_state": self.state.public() if self.state else None,
            "tools_selected": [
                {"tool": p["tool"], "reason": p["reason"], "args": {k: v for k, v in p["args"].items() if k not in PRIVATE_KEYS}}
                for p in self.plan
            ],
            "tools_skipped": self.skipped,
            "missing_fields": self.state.missing_fields if self.state else [],
            "advice": self.advice,
        }


def describe_conditions(state: ConversationState) -> str:
    s = state.slots
    parts = [f"주제: {TOPICS[state.topic]['label']}"]
    if s.get("target_date"):
        d = date.fromisoformat(s["target_date"])
        parts.append(f"날짜: {d.isoformat()}({WEEKDAY_KO[d.weekday()]})")
    if s.get("time_period"):
        parts.append(f"시간대: {s['time_period']}")
    if s.get("location"):
        extra = {"province": "광역 단위, 대표 지점 기준", "coordinates": "사용자 지정 좌표", "configured": "설정된 기본 위치"}.get(
            s.get("location_precision") or "", ""
        )
        parts.append(f"장소: {s['location']}" + (f" ({extra})" if extra else ""))
    return " / ".join(parts)


# ---------------------------------------------------------------------------
# 병합과 계획
# ---------------------------------------------------------------------------


def merge_state(prior: ConversationState | None, topic: str, d: DateSignal, period: str | None, pl: PlaceSignal,
                today: date, settings: Settings) -> tuple[ConversationState, dict]:
    """이번 발화에서 바뀐 조건만 갱신하고 나머지는 유지한다. 주제가 바뀌면 연관 주제일 때만 조건을 이어받는다."""
    topic_changed = prior is None or prior.topic != topic
    if prior is not None and not topic_changed:
        slots = dict(prior.slots)
    elif prior is not None and prior.topic in TOPICS[topic]["carry_from"]:
        slots = {k: v for k, v in prior.slots.items() if k in CARRY_KEYS}
    else:
        slots = {}

    if d.date:
        slots["target_date"] = d.date.isoformat()
        slots.pop("date_issue", None)
    elif d.beyond:
        slots["target_date"] = None
        slots["date_issue"] = "beyond"
    if period:
        slots["time_period"] = period
    if pl.place:
        slots.update(location=pl.place.name, location_precision=pl.place.precision, latitude=pl.place.lat, longitude=pl.place.lon)
        slots.pop("location_candidates", None)
        slots.pop("location_unresolved", None)
    elif pl.ambiguous or pl.unresolved:
        slots.update(location=None, location_precision=None, latitude=None, longitude=None)
        slots.pop("location_candidates", None)
        slots.pop("location_unresolved", None)
        if pl.ambiguous:
            slots["location_candidates"] = pl.ambiguous
        else:
            slots["location_unresolved"] = pl.unresolved

    used = TOPICS[topic]["slots"]
    allowed = {k for group in used for k in SLOT_GROUPS[group]}
    slots = {k: v for k, v in slots.items() if k in allowed}  # 이 주제가 쓰지 않는 조건은 버린다

    for key, value in TOPICS[topic]["defaults"].items():
        slots.setdefault(key, value)
    if "target_date" in used and not slots.get("target_date") and not slots.get("date_issue"):
        slots["target_date"] = today.isoformat()
    if ("location" in used and not slots.get("location") and settings.latitude is not None and settings.longitude is not None
            and not slots.get("location_candidates") and not slots.get("location_unresolved")):
        slots.update(location="기본 위치(설정값)", location_precision="configured", latitude=settings.latitude, longitude=settings.longitude)

    changes = {}
    if prior is None or prior.topic != topic:
        changes["topic"] = {"from": prior.topic if prior else None, "to": topic}
    for key in used:
        old = prior.slots.get(key) if prior else None
        if old != slots.get(key):
            changes[key] = {"from": old, "to": slots.get(key)}
    return ConversationState(topic=topic, slots=slots), changes


@dataclass
class Plan:
    tools: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    advice: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)


def _date_status(s: dict, today: date, settings: Settings) -> tuple[str, date | None]:
    target = date.fromisoformat(s["target_date"]) if s.get("target_date") else None
    if s.get("date_issue") == "beyond" or (target and target > today + timedelta(days=settings.forecast_max_days)):
        return "beyond", target
    if target and target < today:
        return "past", target
    return "ok", target


def _plan_location(s: dict, plan: Plan, weather_args: dict, weather_reason: str) -> None:
    if s.get("latitude") is not None:
        plan.tools.append({"tool": "weather.forecast", "args": weather_args, "reason": weather_reason})
        if s.get("location_precision") == "province":
            plan.advice.append(f"{s['location']}는 넓은 지역이라 대표 지점 기준입니다. 시·군 단위로 알려주면 더 정확합니다.")
        return
    plan.missing.append("location")
    if s.get("location_candidates"):
        c = ", ".join(s["location_candidates"])
        plan.skipped.append({"tool": "weather.forecast", "reason": f"장소가 모호함({c})"})
        plan.unavailable.append(f"장소가 모호합니다: 여러 지역({c})을 가리킬 수 있어 날씨를 조회하지 않았습니다. 어느 곳인지 물어보세요.")
    elif s.get("location_unresolved"):
        plan.skipped.append({"tool": "weather.forecast", "reason": f"장소 인식 실패({s['location_unresolved']})"})
        plan.unavailable.append(
            f"'{s['location_unresolved']}' 위치를 인식하지 못해 날씨를 조회하지 않았습니다. 시·군 이름이나 위도/경도를 알려달라고 안내하세요."
        )
    else:
        plan.skipped.append({"tool": "weather.forecast", "reason": "위치 미설정"})
        plan.unavailable.append(
            "날씨 예보(구름량·강수확률): 장소를 알 수 없어 조회하지 못했습니다. 장소를 알려주거나 "
            ".env에 GYUNEXUS_LATITUDE, GYUNEXUS_LONGITUDE를 설정해야 합니다."
        )


def plan_forecast_topic(state: ConversationState, today: date, settings: Settings, *, with_moon: bool) -> Plan:
    s = state.slots
    plan = Plan()
    status, target = _date_status(s, today, settings)
    period = s.get("time_period")
    horizon = settings.forecast_max_days
    if status == "past":
        plan.missing.append("target_date")
        plan.skipped += [{"tool": "weather.forecast", "reason": "지난 날짜"}] + ([{"tool": "astro.moon_phase", "reason": "지난 날짜"}] if with_moon else [])
        plan.unavailable.append(f"지난 날짜({target})는 예보를 조회할 수 없습니다. 오늘부터 {horizon}일 이내 날짜를 물어보세요.")
    else:
        if with_moon and target:
            plan.tools.append({"tool": "astro.moon_phase", "args": {"date": target.isoformat(), "period": period},
                               "reason": "달빛은 은하수 관측에 영향 - 해당 날짜의 달 위상을 계산"})
        if status == "beyond":
            plan.missing.append("target_date")
            plan.skipped.append({"tool": "weather.forecast", "reason": f"예보 범위({horizon}일) 초과"})
            plan.unavailable.append(
                f"예보는 오늘부터 {horizon}일 이내만 조회할 수 있어 해당 날짜의 날씨는 확인할 수 없습니다"
                + ("(달 위상은 계산으로 제공). " if with_moon and target else ". ")
                + f"{horizon}일 이내 날짜를 알려달라고 안내하세요."
            )
        else:
            args = {"date": target.isoformat(), "period": period, "latitude": s.get("latitude"),
                    "longitude": s.get("longitude"), "location_name": s.get("location")}
            _plan_location(s, plan, args, f"{s.get('location') or '장소 미정'} {target} {period or '종일'} 예보 - 조건이 바뀌었으므로 항상 재조회")
    if with_moon:
        plan.unavailable.append("그 외 조회 불가 데이터: " + ", ".join(NOT_COVERED_SKY))
    return plan


def plan_sky(state: ConversationState, today: date, settings: Settings) -> Plan:
    return plan_forecast_topic(state, today, settings, with_moon=True)


def plan_weather(state: ConversationState, today: date, settings: Settings) -> Plan:
    return plan_forecast_topic(state, today, settings, with_moon=False)


def plan_news(state: ConversationState, today: date, settings: Settings) -> Plan:
    plan = Plan()
    plan.skipped.append({"tool": "news.search", "reason": "뉴스 조회 도구가 연결되어 있지 않음"})
    plan.unavailable.append("뉴스: 뉴스 조회 도구가 아직 연결되어 있지 않아 오늘의 뉴스를 확인할 수 없습니다. 지어내지 말고 그 사실을 알리세요.")
    plan.advice.append("뉴스 조회를 쓰려면 뉴스/검색 도구 연결이 필요합니다.")
    return plan


PLANNERS = {"sky_observation": plan_sky, "weather": plan_weather, "news": plan_news}

INTENT_SYSTEM = """사용자의 후속 발화를 해석합니다. 직전 대화 상태와 최근 대화를 보고 JSON만 출력합니다.
- followup: 활성 주제의 조건(날짜/시간대/장소)을 바꾸거나 같은 주제를 이어서 묻는 경우
- new_topic: 다른 주제로 전환 (topic: sky_observation | weather | news)
- chat: 도구 조회가 필요 없는 일반 대화
날짜는 오늘 날짜를 기준으로 YYYY-MM-DD, 바뀌지 않았으면 null. 시간대는 새벽|아침|낮|저녁|밤 중 하나, 바뀌지 않았으면 null.
장소는 사용자가 말한 지명 그대로, 바뀌지 않았으면 null.
{"intent":"followup","topic":"sky_observation","target_date":null,"time_period":null,"location":null}"""


class ConversationRouter:
    def __init__(self, db: Database, llm: LLMGateway, settings: Settings, activity: Activity):
        self.db, self.llm, self.settings, self.activity = db, llm, settings, activity
        self.tz = ZoneInfo(settings.timezone)

    # --- 영속화 ---

    def load_state(self, conversation_id: int | None) -> ConversationState | None:
        if conversation_id is None:
            return None
        with self.db.session() as s:
            row = s.get(StateRow, conversation_id)
            if row is None or not row.topic or utcnow() - row.updated_at > STATE_TTL:
                return None
            return ConversationState(row.topic, dict(row.slots), list(row.missing_fields))

    def save_state(self, conversation_id: int, state: ConversationState) -> None:
        with self.db.session() as s:
            row = s.get(StateRow, conversation_id)
            if row is None:
                row = StateRow(conversation_id=conversation_id)
                s.add(row)
            row.topic, row.slots, row.missing_fields, row.updated_at = state.topic, state.slots, state.missing_fields, utcnow()

    def clear_state(self, conversation_id: int) -> None:
        with self.db.session() as s:
            s.execute(delete(StateRow).where(StateRow.conversation_id == conversation_id))

    # --- 해석 ---

    async def _interpret_with_llm(self, text: str, prior: ConversationState, history: list[dict], today: date) -> dict | None:
        recent = "\n".join(f"{m['role']}: {m['content'][:160]}" for m in history[-4:])
        user = (
            f"오늘: {today.isoformat()}({WEEKDAY_KO[today.weekday()]}요일)\n직전 상태: {prior.public()}\n"
            f"최근 대화:\n{recent or '(없음)'}\n\n사용자 발화: {text}"
        )
        try:
            data, _ = await self.llm.json("intent", [{"role": "system", "content": INTENT_SYSTEM}, {"role": "user", "content": user}], max_tokens=200)
            return data
        except LLMError as e:
            self.activity.record("gyuvis", "intent.failed", level="warn", error=str(e))
            return None

    async def route(self, text: str, prior: ConversationState | None, history: list[dict]) -> Routing:
        today = datetime.now(self.tz).date()
        prior_public = prior.public() if prior else None
        d, period, pl = parse_date(text, today), parse_period(text), find_place(text)
        asks = bool(ASKING.search(text)) or is_followup_marker(text)  # 조건을 바꿔 다시 묻는 말투인가
        # 장소 후보 중 인식 실패(unresolved)는 오탐이 많아 질문 형태일 때만 단서로 인정한다
        has_cue = d.mentioned or bool(period) or bool(pl.place or pl.ambiguous) or bool(pl.unresolved and asks)
        topic_kw = detect_topic(text)
        interpreted_by = "rules"

        if topic_kw:
            topic = topic_kw
            intent = "followup" if prior and prior.topic == topic else "new_topic"
            reason = f"주제 키워드로 '{topic}' 확정" + ("(이전 주제와 동일, 조건 병합)" if intent == "followup" else "")
        elif prior and has_cue and asks:
            topic, intent = prior.topic, "followup"
            reason = "활성 주제가 있고 날짜/시간대/장소 표현이 있어 후속 질문으로 판단"
        elif prior and is_followup_marker(text):
            interpreted_by = "llm"
            r = await self._interpret_with_llm(text, prior, history, today)
            intent = (r or {}).get("intent", "chat")
            topic = (r or {}).get("topic") if intent == "new_topic" else prior.topic
            if intent not in ("followup", "new_topic") or topic not in TOPICS:
                return Routing("chat", "llm", "규칙으로 판단 불가 -> LLM 해석 결과 도구 조회가 필요 없는 대화" if r else "LLM 해석 실패 -> 일반 대화로 처리", prior_public)
            try:
                d = DateSignal(date=date.fromisoformat(r["target_date"]), mentioned=True) if r.get("target_date") else d
            except (ValueError, TypeError):
                pass
            period = r.get("time_period") if r.get("time_period") in VALID_PERIODS else period
            if r.get("location"):
                pl = find_place(str(r["location"])) if find_place(str(r["location"])).any else PlaceSignal(unresolved=str(r["location"])[:20])
            reason = "규칙으로 판단하기 어려운 후속 발화 -> LLM이 의도·바뀐 조건을 해석"
        else:
            return Routing("chat", "rules", "활성 주제의 조건 변경이나 새 주제 키워드가 없어 일반 대화로 처리", prior_public)

        state, changes = merge_state(prior, topic, d, period, pl, today, self.settings)
        plan = PLANNERS[topic](state, today, self.settings)
        state.missing_fields = plan.missing
        return Routing(intent, interpreted_by, reason, prior_public, state, changes, plan.tools, plan.skipped, plan.advice, plan.unavailable)
