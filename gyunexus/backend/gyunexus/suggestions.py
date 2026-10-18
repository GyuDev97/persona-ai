"""능동 제안의 저장소, 사용자 설정, 사용자 반응 분류.

판단 로직(후보 생성·점수·전달)은 proactive.py 가 맡고, 이 모듈은 DB 접근과 규칙 기반 분류만 한다(LLM 호출 없음).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select

from .config import Settings
from .db import Database
from .models import Reminder, Suggestion
from .routing import detect_topic, parse_date, parse_period
from .runtime_settings import get_value, set_value
from .textutil import similarity

TOPIC_LABELS = {"sky": "은하수·출사", "idea": "GyuNexus 아이디어", "worker": "AI 직원 업무 알림"}
TOPIC_KEYS = tuple(TOPIC_LABELS)


# ---------------------------------------------------------------- 사용자 설정(기존 런타임 설정 저장소 재사용)

QUIET_RE = re.compile(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$")


def parse_quiet(spec: str) -> tuple[int, int] | None:
    """'23:00-07:00' -> (시작 분, 끝 분). 빈 문자열이거나 형식이 틀리면 None(조용한 시간 없음)."""
    m = QUIET_RE.match((spec or "").strip())
    if not m:
        return None
    a, b, c, d = map(int, m.groups())
    if not (0 <= a < 24 and 0 <= c < 24 and 0 <= b < 60 and 0 <= d < 60):
        return None
    return a * 60 + b, c * 60 + d


def in_quiet_hours(spec: str, local: datetime) -> bool:
    q = parse_quiet(spec)
    if q is None or q[0] == q[1]:
        return False
    now = local.hour * 60 + local.minute
    start, end = q
    return start <= now < end if start < end else (now >= start or now < end)  # 자정을 넘는 구간 지원


def get_prefs(db: Database, settings: Settings) -> dict:
    with db.session() as s:
        enabled = get_value(s, "proactive_enabled", settings.proactive_enabled)
        daily = get_value(s, "proactive_daily_max", settings.proactive_daily_max)
        quiet = get_value(s, "proactive_quiet_hours", settings.proactive_quiet_hours)
        topics = get_value(s, "proactive_topics", {}) or {}
    return {
        "enabled": bool(enabled),
        "daily_max": int(daily),
        "quiet_hours": str(quiet or ""),
        "topics": {k: bool(topics.get(k, True)) for k in TOPIC_KEYS},
    }


def set_prefs(db: Database, *, enabled=None, daily_max=None, quiet_hours=None, topics=None) -> None:
    with db.session() as s:
        if enabled is not None:
            set_value(s, "proactive_enabled", bool(enabled))
        if daily_max is not None:
            set_value(s, "proactive_daily_max", int(daily_max))
        if quiet_hours is not None:
            set_value(s, "proactive_quiet_hours", quiet_hours.strip())
        if topics:
            cur = dict(get_value(s, "proactive_topics", {}) or {})
            cur.update({k: bool(v) for k, v in topics.items() if k in TOPIC_KEYS})
            set_value(s, "proactive_topics", cur)


# ---------------------------------------------------------------- 후보

@dataclass
class Candidate:
    type: str
    topic_key: str
    dedupe_key: str
    event: str
    title: str
    reason: str
    needed_action: str
    params: dict
    evidence: dict
    confidence: str  # high | medium | low
    valid_until: datetime | None
    components: dict  # relevance, usefulness, time_sensitivity, evidence  (각 0~1)
    user_requested: bool = False
    skip_reason: str | None = None  # 생성 단계에서 이미 쓸 수 없다고 판단된 이유(조회 실패 등). 기록만 남기고 폐기한다.


class SuggestionStore:
    def __init__(self, db: Database):
        self.db = db

    def upsert(self, c: Candidate, now: datetime, reuse_dropped_within: timedelta = timedelta(0)) -> int:
        """같은 dedupe_key 의 후보/보류 행(최근 폐기 행 포함)이 있으면 갱신하고, 없으면 새로 만든다(재평가 때 행이 불어나지 않게)."""
        with self.db.session() as s:
            rows = s.scalars(select(Suggestion).where(Suggestion.dedupe_key == c.dedupe_key).order_by(Suggestion.id.desc()))
            row = next((r for r in rows if r.status in ("candidate", "held")
                        or (r.status == "dropped" and now - r.created_at <= reuse_dropped_within)), None)
            if row is not None:
                row.status = "candidate"
            if row is None:
                row = Suggestion(type=c.type, topic_key=c.topic_key, dedupe_key=c.dedupe_key, event=c.event, created_at=now)
                s.add(row)
            row.title, row.reason, row.needed_action = c.title[:300], c.reason, c.needed_action
            row.params, row.evidence, row.confidence = c.params, c.evidence, c.confidence
            row.valid_until, row.user_requested, row.event = c.valid_until, c.user_requested, c.event
            row.score_detail = {"components": c.components}
            s.flush()
            return row.id

    def get(self, sid: int) -> Suggestion | None:
        with self.db.session() as s:
            return s.get(Suggestion, sid)

    def update(self, sid: int, **fields: Any) -> None:
        with self.db.session() as s:
            row = s.get(Suggestion, sid)
            for k, v in fields.items():
                setattr(row, k, v)

    def delivered_since(self, since: datetime, *, include_requested: bool = False) -> list[Suggestion]:
        with self.db.session() as s:
            q = select(Suggestion).where(Suggestion.status == "delivered", Suggestion.delivered_at >= since)
            return [r for r in s.scalars(q) if include_requested or not r.user_requested]

    def delivered_with_key(self, dedupe_key: str, since: datetime) -> bool:
        with self.db.session() as s:
            return s.scalars(select(Suggestion).where(Suggestion.dedupe_key == dedupe_key, Suggestion.status == "delivered",
                                                      Suggestion.delivered_at >= since)).first() is not None

    def active_block(self, topic_key: str, now: datetime) -> Suggestion | None:
        """거절·연기로 아직 같은 주제를 제안하면 안 되는 상태인 가장 최근 제안."""
        with self.db.session() as s:
            return s.scalars(select(Suggestion).where(Suggestion.topic_key == topic_key, Suggestion.blocked_until > now)
                             .order_by(Suggestion.blocked_until.desc())).first()

    def reactions(self, topic_key: str, kind: str, since: datetime) -> list[Suggestion]:
        with self.db.session() as s:
            return list(s.scalars(select(Suggestion).where(Suggestion.topic_key == topic_key, Suggestion.reaction == kind,
                                                           Suggestion.reaction_at >= since)))

    def delivered_idea_titles(self, since: datetime) -> list[str]:
        with self.db.session() as s:
            rows = s.scalars(select(Suggestion).where(Suggestion.type == "idea", Suggestion.status == "delivered", Suggestion.delivered_at >= since))
            return [t for r in rows for t in (r.evidence or {}).get("titles", [])]

    def expire(self, now: datetime) -> int:
        """유효 기간이 지난 후보·보류 항목을 만료 처리한다. 만료된 정보로는 절대 제안하지 않는다."""
        n = 0
        with self.db.session() as s:
            for r in s.scalars(select(Suggestion).where(Suggestion.status.in_(("candidate", "held")), Suggestion.valid_until.is_not(None),
                                                        Suggestion.valid_until <= now)):
                r.status, r.decision_reason = "expired", (r.decision_reason + " / 유효 기간 만료").strip(" /")
                n += 1
        return n

    # ---- 재알림
    def add_reminder(self, topic_key: str, due: datetime, suggestion_id: int | None, note: str, now: datetime) -> tuple[Reminder, bool]:
        """같은 주제에 같은 날(±12시간) 대기 중인 재알림이 있으면 새로 만들지 않는다. (재알림, 새로 생성 여부)"""
        with self.db.session() as s:
            for r in s.scalars(select(Reminder).where(Reminder.topic_key == topic_key, Reminder.status == "pending")):
                if abs((r.due_at - due).total_seconds()) <= 12 * 3600:
                    return r, False
            r = Reminder(topic_key=topic_key, due_at=due, suggestion_id=suggestion_id, note=note, created_at=now)
            s.add(r)
            s.flush()
            return r, True

    def pending_reminders(self) -> list[Reminder]:
        with self.db.session() as s:
            return list(s.scalars(select(Reminder).where(Reminder.status == "pending").order_by(Reminder.due_at)))

    def due_reminders(self, now: datetime) -> list[Reminder]:
        with self.db.session() as s:
            return list(s.scalars(select(Reminder).where(Reminder.status == "pending", Reminder.due_at <= now).order_by(Reminder.due_at)))

    def update_reminder(self, rid: int, **fields: Any) -> None:
        with self.db.session() as s:
            row = s.get(Reminder, rid)
            for k, v in fields.items():
                setattr(row, k, v)


def similar_titles(title: str, existing: list[str], threshold: float = 0.8) -> bool:
    return any(similarity(title, t) >= threshold for t in existing)


# ---------------------------------------------------------------- 사용자 반응 분류(규칙 기반)

@dataclass
class Reaction:
    kind: str  # interested | details | declined | snoozed | muted | chat
    due_date: date | None = None  # snoozed: 재알림 날짜
    hour: int | None = None  # snoozed: 재알림 시각(현지)
    delay_hours: float | None = None  # snoozed: 날짜 없이 '나중에'
    block_until_date: date | None = None  # declined: 이 날짜까지 같은 주제 제안 금지(없으면 오늘)
    scope: str = "topic"  # muted: topic | all
    notes: list[str] = field(default_factory=list)


MUTE = re.compile(r"(그만|더 이상|다시는|이제).{0,8}(알려|말 ?걸|알림|제안|연락|얘기|이야기|보내)|알림.{0,6}(꺼|끄|중지|그만|필요 ?없)|(말 ?걸지|제안하지|알리지)\s?(마|말)")
MUTE_ALL = re.compile(r"(모든|전부|다)\s?(알림|제안)|말 ?걸지\s?마")
DELAY = re.compile(r"나중|이따|있다가|잠시 ?후|조금 ?뒤|조금 ?있다|몇 ?시간|다음에")
REMIND = re.compile(r"다시|또|리마인드|알려|알림|말해|물어")
DECLINE = re.compile(r"안\s?갈|안\s?가|못\s?갈|못\s?가|싫|됐어|됐다|패스|피곤|바빠|바쁘|귀찮|별로|관심\s?없|필요\s?없|괜찮아요?\s*$|쉬고\s?싶|쉴래")
INTEREST = re.compile(r"좋아|좋네|^응|^네|^그래|알려\s?줘|확인해|궁금|해볼|가볼|가자|갈래|가고\s?싶|관심\s?있|보여\s?줘|부탁")
DETAILS = re.compile(r"어디|언제|왜|어떻게|자세히|더 알려|근거|이유|조건|날씨|구름|달\s?(밝|위상|빛)|준비물|장소|몇\s?시")
WORKER_DETAILS = re.compile(r"어떤|내용|요약|보여|뭐야|뭔데|뭐라고|열어|읽어|핵심|제목|초안|결과|문서|검토|승인|출처|근거|이유|왜|어디|자세히|더 알려|실패|원인|자료")
PERIOD_HOURS = {"새벽": 6, "아침": 8, "낮": 13, "저녁": 19, "밤": 21}


def classify_reaction(text: str, today: date, topic_key: str) -> Reaction:
    t = text.strip()
    if MUTE.search(t):
        return Reaction("muted", scope="all" if MUTE_ALL.search(t) else "topic")
    d = parse_date(t, today)
    future = d.date is not None and d.date > today
    if (REMIND.search(t) and (future or DELAY.search(t))) or (DELAY.search(t) and re.search(r"알려|알림|말해|물어", t)):
        hour = None
        m = re.search(r"(\d{1,2})\s?시", t)
        if m:
            hour = int(m.group(1))
            if hour < 12 and re.search(r"오후|저녁|밤", t):
                hour += 12
        else:
            p = parse_period(t)
            hour = PERIOD_HOURS.get(p) if p else None
        if future:
            return Reaction("snoozed", due_date=d.date, hour=hour if hour is not None else 19)
        delay = 24.0 if "다음에" in t else 3.0
        return Reaction("snoozed", delay_hours=delay)
    if DECLINE.search(t):
        block = d.date if (d.date and d.date > today) else None
        return Reaction("declined", block_until_date=block)
    if topic_key == "worker" and WORKER_DETAILS.search(t):  # "어떤 내용인데?" 같은 질문은 결과물에 대한 후속 질문이다
        return Reaction("details")
    detected = detect_topic(t)
    off_topic = detected is not None and not (topic_key == "sky" and detected in ("sky_observation", "weather"))
    if off_topic:
        return Reaction("chat", notes=["다른 주제로 전환"])
    if DETAILS.search(t):
        return Reaction("details")
    if INTEREST.search(t):
        return Reaction("interested")
    return Reaction("chat")
