import asyncio
import html
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx

from .config import Settings

UA = {"User-Agent": "GyuNexus/0.1 (personal assistant)"}
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# 시간대 이름 -> (날짜 오프셋, 시작 시, 끝 시(미포함)) 구간. 밤은 자정을 넘긴다.
PERIOD_WINDOWS: dict[str | None, list[tuple[int, int, int]]] = {
    "새벽": [(0, 0, 5)],
    "아침": [(0, 6, 12)],
    "낮": [(0, 12, 18)],
    "저녁": [(0, 18, 22)],
    "밤": [(0, 22, 24), (1, 0, 3)],
    None: [(0, 0, 24)],
}
PERIOD_MID_HOUR: dict[str | None, int] = {"새벽": 3, "아침": 9, "낮": 15, "저녁": 20, "밤": 23, None: 12}


class ToolError(Exception):
    """도구 실패. kind는 실패 유형(timeout, network, http_503, no_data, unsupported_date ...)."""

    def __init__(self, message: str, kind: str = "error", attempts: int = 1):
        super().__init__(message)
        self.kind = kind
        self.attempts = attempts


@dataclass
class Tool:
    name: str
    description: str
    risk: str  # read | write | external  (read 외에는 사용자 승인 필요)
    params: dict[str, str]
    handler: Callable[[dict], Awaitable[dict]]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def describe(self, *, read_only: bool = False) -> str:
        lines = []
        for t in self._tools.values():
            if read_only and t.risk != "read":
                continue
            params = ", ".join(f"{k}: {v}" for k, v in t.params.items()) or "없음"
            lines.append(f"- {t.name}: {t.description} (args: {params})")
        return "\n".join(lines)

    async def execute(self, name: str, args: dict) -> dict:
        """도구를 실행한다. 허용 여부 판단은 호출자 책임이다(policy.py 참고)."""
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f"unknown tool: {name}", kind="unknown_tool")
        try:
            return await tool.handler(args)
        except ToolError:
            raise
        except httpx.HTTPError as e:
            raise ToolError(f"network error: {type(e).__name__}", kind="network") from e
        except (KeyError, ValueError, TypeError) as e:
            raise ToolError(f"invalid arguments: {e}", kind="invalid_args") from e


def moon_info(now: datetime) -> dict:
    """평균 삭망월로 달 위상을 계산한다(오차 약 1일)."""
    synodic = 29.530588853
    ref_new_moon = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
    age = ((now.astimezone(timezone.utc) - ref_new_moon).total_seconds() / 86400) % synodic
    illumination = (1 - math.cos(2 * math.pi * age / synodic)) / 2
    names = ["신월", "초승달", "상현달", "상현망간", "보름달", "하현망간", "하현달", "그믐달"]
    name = names[int((age / synodic * 8) + 0.5) % 8]
    return {
        "phase": name,
        "age_days": round(age, 1),
        "illumination_pct": round(illumination * 100),
        "days_to_next_new_moon": round(synodic - age, 1),
        "dark_sky_friendly": illumination < 0.25,
        "source": "computed:mean-synodic-month",
    }


def _parse_period(value: Any) -> str | None:
    if value in (None, "", "종일"):
        return None
    if value not in PERIOD_WINDOWS:
        raise ValueError(f"unknown period: {value}")
    return value


def _parse_date(value: Any) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as e:
        raise ToolError(f"invalid date: {value}", kind="invalid_args") from e


def build_registry(settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> ToolRegistry:
    """transport는 테스트에서 외부 HTTP를 대체하기 위한 주입 지점이다."""
    reg = ToolRegistry()
    tz = ZoneInfo(settings.timezone)

    async def get_json(url: str, params: dict) -> Any:
        """타임아웃 + 제한된 재시도(백오프). 429/5xx/타임아웃/네트워크 오류만 재시도한다."""
        host = urlparse(url).netloc
        attempts = len(settings.tool_retry_backoff) + 1
        kind, detail = "error", ""
        for n in range(1, attempts + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(settings.tool_timeout_seconds, connect=4.0), headers=UA, transport=transport
                ) as c:
                    r = await c.get(url, params=params)
            except httpx.TimeoutException:
                kind, detail = "timeout", "timeout"
            except httpx.TransportError as e:
                kind, detail = "network", type(e).__name__
            else:
                if r.status_code in RETRYABLE_STATUS:
                    kind, detail = f"http_{r.status_code}", f"HTTP {r.status_code}"
                elif r.status_code >= 400:
                    raise ToolError(f"{host} returned HTTP {r.status_code}", kind=f"http_{r.status_code}", attempts=n)
                else:
                    try:
                        return r.json()
                    except ValueError as e:
                        raise ToolError(f"{host} returned invalid JSON", kind="bad_response", attempts=n) from e
            if n < attempts:
                await asyncio.sleep(settings.tool_retry_backoff[n - 1])
        raise ToolError(f"{host} failed after {attempts} attempts ({detail})", kind=kind, attempts=attempts)

    async def moon_phase(args: dict) -> dict:
        if "date" not in args:
            return moon_info(datetime.now(timezone.utc))
        d, period = _parse_date(args["date"]), _parse_period(args.get("period"))
        moment = datetime.combine(d, time(PERIOD_MID_HOUR[period]), tzinfo=tz)
        return {**moon_info(moment), "for": {"date": d.isoformat(), "period": period}}

    async def weather(args: dict) -> dict:
        lat = args.get("latitude", settings.latitude)
        lon = args.get("longitude", settings.longitude)
        if lat is None or lon is None:
            raise ToolError("location not configured (GYUNEXUS_LATITUDE / GYUNEXUS_LONGITUDE)", kind="no_location")
        hourly = "cloud_cover,precipitation_probability,temperature_2m"
        today = datetime.now(tz).date()

        if "date" not in args:  # 예전 호출 방식: 앞으로 2~3일 밤(22~03시) 요약
            data = await get_json(
                "https://api.open-meteo.com/v1/forecast",
                {"latitude": lat, "longitude": lon, "hourly": hourly, "timezone": "auto", "forecast_days": 3},
            )
            times = data["hourly"]["time"]
            nights = []
            for i, d in enumerate(sorted({t[:10] for t in times})[:-1]):
                s = _summarize(data["hourly"], date.fromisoformat(d), PERIOD_WINDOWS["밤"])
                if s:
                    nights.append({"date": d, **{k: s[k] for k in ("avg_cloud_cover_pct", "max_precip_prob_pct")}})
            return {"nights_22_to_03": nights, "source": "https://open-meteo.com"}

        target, period = _parse_date(args["date"]), _parse_period(args.get("period"))
        if target < today or target > today + timedelta(days=settings.forecast_max_days):
            raise ToolError(
                f"date {target} outside supported range ({today} ~ +{settings.forecast_max_days}d)", kind="unsupported_date"
            )
        days_ahead = (target - today).days
        data = await get_json(
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": lat,
                "longitude": lon,
                "hourly": hourly,
                "timezone": "auto",
                "forecast_days": min(16, days_ahead + 2),
            },
        )
        windows = PERIOD_WINDOWS[period]
        s = _summarize(data["hourly"], target, windows)
        if not s:
            raise ToolError("forecast has no data for the requested window", kind="no_data")
        last_off, _, last_end = windows[-1]
        window_end = datetime.combine(target + timedelta(days=last_off), time(0)) + timedelta(hours=last_end)
        return {
            "date": target.isoformat(),
            "period": period or "종일",
            "location": args.get("location_name") or ("지정 좌표" if "latitude" in args else "기본 위치(설정값)"),
            **s,
            "window_passed": window_end < datetime.now(tz).replace(tzinfo=None),
            "source": "https://open-meteo.com",
        }

    def _summarize(h: dict, day: date, windows: list[tuple[int, int, int]]) -> dict | None:
        index = {t: i for i, t in enumerate(h["time"])}
        cloud, rain, temp = [], [], []
        for off, h0, h1 in windows:
            d = day + timedelta(days=off)
            for hour in range(h0, h1):
                i = index.get(f"{d.isoformat()}T{hour:02d}:00")
                if i is None:
                    continue
                for series, key in ((cloud, "cloud_cover"), (rain, "precipitation_probability"), (temp, "temperature_2m")):
                    v = h.get(key, [None] * len(h["time"]))[i]
                    if v is not None:
                        series.append(v)
        if not cloud:
            return None
        return {
            "avg_cloud_cover_pct": round(sum(cloud) / len(cloud)),
            "max_precip_prob_pct": max(rain) if rain else None,
            "avg_temp_c": round(sum(temp) / len(temp), 1) if temp else None,
            "hours_sampled": len(cloud),
        }

    async def wiki_search(args: dict) -> dict:
        query = str(args["query"]).strip()
        lang = args.get("lang", "ko")
        if lang not in ("ko", "en") or not query:
            raise ValueError("query required; lang must be ko or en")
        data = await get_json(
            f"https://{lang}.wikipedia.org/w/api.php",
            {"action": "query", "list": "search", "srsearch": query, "srlimit": 3, "format": "json"},
        )
        hits = data["query"]["search"]
        results = [
            {
                "title": h["title"],
                "snippet": html.unescape(re.sub(r"<[^>]+>", "", h["snippet"])),
                "url": f"https://{lang}.wikipedia.org/wiki/{h['title'].replace(' ', '_')}",
            }
            for h in hits
        ]
        # 검색어와 무관한 결과(예: "임진각 빛 공해" -> "서울특별시")는 증거로 쓰지 않는다: 질의 키워드 앞 2글자가 제목/요약에 있어야 함
        stems = {w[:2].lower() for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", query)}
        results = [r for r in results if any(s in f"{r['title']} {r['snippet']}".lower() for s in stems)]
        return {"results": results, "source": ", ".join(x["url"] for x in results)}

    async def notes_write(args: dict) -> dict:
        name = str(args["filename"])
        if not re.fullmatch(r"[\w가-힣.\- ]{1,100}\.md", name) or ".." in name:
            raise ValueError("filename must be a plain *.md name")
        settings.notes_dir.mkdir(parents=True, exist_ok=True)
        path = settings.notes_dir / name
        path.write_text(str(args["content"]), encoding="utf-8")
        return {"path": str(path)}

    reg.register(
        Tool(
            "astro.moon_phase",
            "달의 위상·밝기·그믐까지 남은 일수(별 촬영 적합성 포함). date를 주면 그 날짜 기준",
            "read",
            {"date": "YYYY-MM-DD(선택)", "period": "새벽|아침|낮|저녁|밤(선택)"},
            moon_phase,
        )
    )
    reg.register(
        Tool(
            "weather.forecast",
            "구름량·강수확률·기온 예보. date/period/latitude/longitude를 주면 그 조건, 없으면 설정 위치의 앞으로 2~3일 밤 요약",
            "read",
            {"date": "YYYY-MM-DD(선택)", "period": "새벽|아침|낮|저녁|밤(선택)", "latitude": "선택", "longitude": "선택"},
            weather,
        )
    )
    reg.register(
        Tool(
            "wiki.search",
            "위키백과 검색(상위 3건 요약과 URL). 출처가 있는 사실 확인용",
            "read",
            {"query": "검색어", "lang": "ko 또는 en"},
            wiki_search,
        )
    )
    reg.register(
        Tool(
            "notes.write",
            "data/notes 에 마크다운 노트 파일을 저장(파일 변경, 사용자 승인 필요)",
            "write",
            {"filename": "*.md 파일명", "content": "본문"},
            notes_write,
        )
    )
    return reg
