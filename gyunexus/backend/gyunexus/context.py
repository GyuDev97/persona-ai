from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import Settings
from .db import Database
from .models import utcnow
from .runtime_settings import get_value, set_value

WEEKDAYS = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
RETURN_GAP = timedelta(minutes=30)


class ContextManager:
    """사용자의 현재 상황(접속 여부, 시간대)을 GYUVIS와 Proactive Engine에 제공한다."""

    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings
        self.tz = ZoneInfo(settings.timezone)
        self._clock = utcnow  # 능동 제안 판단이 쓰는 단일 시계(테스트에서 고정 가능)

    def now(self) -> datetime:
        return self._clock()

    def heartbeat(self) -> dict:
        """사용자가 활동 중일 때 대시보드가 호출한다. 새 세션 시작 여부를 반환한다."""
        now = self.now()
        with self.db.session() as s:
            last = get_value(s, "last_activity")
            last_dt = datetime.fromisoformat(last) if last else None
            returned = last_dt is None or now - last_dt > RETURN_GAP
            set_value(s, "last_activity", now.isoformat())
            if returned:
                set_value(s, "session_started", now.isoformat())
        return {"returned": returned}

    def snapshot(self) -> dict:
        now_utc = self.now()
        local = now_utc.replace(tzinfo=timezone.utc).astimezone(self.tz)
        with self.db.session() as s:
            last = get_value(s, "last_activity")
            started = get_value(s, "session_started")
        idle = (now_utc - datetime.fromisoformat(last)).total_seconds() if last else None
        present = idle is not None and idle <= self.settings.presence_timeout_seconds
        weekend = local.weekday() >= 5
        hour = local.hour + local.minute / 60
        if hour < 6:
            part = "새벽"
        elif hour < 12:
            part = "오전"
        elif hour < 18:
            part = "오후"
        elif hour < 22:
            part = "저녁"
        else:
            part = "밤"
        snap = {
            "local_time": local.strftime("%Y-%m-%d %H:%M"),
            "weekday": WEEKDAYS[local.weekday()],
            "part_of_day": part,
            "is_weekend": weekend,
            "after_work_hours": weekend or hour >= 17.5,  # 추정값(아래 inferred 참고): 실제 퇴근 여부가 아니다
            "user_present": present,
            "idle_seconds": int(idle) if idle is not None else None,
            "session_minutes": int((now_utc - datetime.fromisoformat(started)).total_seconds() // 60)
            if started and present
            else 0,
            "location_configured": self.settings.latitude is not None,
            "weekday_index": local.weekday(),
            "local_hour": local.hour,
        }
        # 관측된 사실과 추정을 분리한다: 대시보드 접속은 퇴근·귀가의 증거가 아니다
        snap["observed"] = {k: snap[k] for k in ("local_time", "weekday", "part_of_day", "user_present", "idle_seconds", "session_minutes")}
        snap["inferred"] = {
            "likely_free_time": snap["after_work_hours"],
            "basis": "요일·시각만으로 짐작한 값(실제 퇴근/귀가 여부는 알 수 없음)",
            "confidence": "low",
        }
        return snap
