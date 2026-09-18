"""Small, data-first night-sky research PoC for GYUVIS.

The service deliberately keeps network collection, scoring and language
generation separate. Weather and astronomy values come only from public APIs;
an optional LLM can rewrite the already-calculated conclusion but never supply
facts or a score.
"""

from __future__ import annotations

import json
import logging
import math
import ssl
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ..config import Settings, get_settings
from ..domain.schemas import NightSkyBriefingData, NightSkyCheckResponse
from .night_sky_astronomy import calculate_astronomy, load_scoring_config


LOGGER = logging.getLogger(__name__)
OPEN_METEO_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MET_SUNRISE_URL = "https://api.met.no/weatherapi/sunrise/3.0"
MET_USER_AGENT = "GYUVIS-NightSky-PoC/1.0 (local personal assistant)"


class NightSkySourceError(RuntimeError):
    """A recoverable external data-source problem."""


@dataclass(frozen=True)
class ObservationLocation:
    name: str
    latitude: float
    longitude: float
    timezone: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "timezone": self.timezone,
        }


@dataclass(frozen=True)
class HourlyCondition:
    when: datetime
    cloud_cover: float | None
    precipitation_probability: float | None
    humidity: float | None
    wind_speed: float | None
    temperature: float | None


@dataclass(frozen=True)
class ScoredWindow:
    start: datetime
    end: datetime
    score: int
    condition: HourlyCondition


@dataclass(frozen=True)
class IntegratedHour:
    condition: HourlyCondition
    weather_score: int | None
    astronomy_hour_score: int | None
    hour_score: int | None
    moon_altitude_degrees: float | None
    moon_azimuth_degrees: float | None
    moon_impact: str | None
    galactic_center_altitude_degrees: float | None
    astronomical_dark: bool


@dataclass(frozen=True)
class RecommendationWindow:
    start: datetime
    end: datetime
    weather_score: int
    astronomy_score: int
    overall_score: int
    condition: HourlyCondition
    advisory: str | None = None


@dataclass(frozen=True)
class NightSkyPolicy:
    """Single home for tunable PoC scoring thresholds and weights."""

    cloud_weight: int = 50
    precipitation_weight: int = 25
    humidity_weight: int = 15
    wind_weight: int = 10
    good_score: int = 75
    fair_score: int = 50
    low_moon_illumination: int = 25
    medium_moon_illumination: int = 50
    high_moon_illumination: int = 75

    def weather_score(self, condition: HourlyCondition) -> int | None:
        """Score measured/forecast values without treating missing data as zero."""
        critical = [condition.cloud_cover, condition.precipitation_probability]
        if any(value is None for value in critical):
            return None

        parts: list[tuple[float, int]] = [
            (self._inverse(condition.cloud_cover, 25, 50, 100), self.cloud_weight),
            (self._inverse(condition.precipitation_probability, 10, 50, 100), self.precipitation_weight),
        ]
        if condition.humidity is not None:
            parts.append((self._inverse(condition.humidity, 70, 90, 100), self.humidity_weight))
        if condition.wind_speed is not None:
            parts.append((self._inverse(condition.wind_speed, 10, 25, 45), self.wind_weight))

        weighted = sum(value * weight for value, weight in parts)
        total_weight = sum(weight for _, weight in parts)
        return round(weighted / total_weight) if total_weight else None

    def moon_adjustment(self, illumination: float | None) -> int:
        if illumination is None:
            return 0
        if illumination <= self.low_moon_illumination:
            return 10
        if illumination <= self.medium_moon_illumination:
            return 3
        if illumination <= self.high_moon_illumination:
            return -6
        return -15

    def grade(self, score: int | None) -> str:
        if score is None:
            return "unknown"
        if score >= self.good_score:
            return "good"
        if score >= self.fair_score:
            return "fair"
        return "poor"

    @staticmethod
    def scoring_confidence(astronomy: dict[str, Any], *, weather_available: bool) -> dict[str, Any]:
        """Describe which calculated inputs support an overall suitability result."""
        sun = astronomy.get("sun") or {}
        moon = astronomy.get("moon") or {}
        missing: list[str] = []
        if not sun.get("astronomical_twilight_end") or not sun.get("astronomical_twilight_start"):
            missing.append("천문박명")
        if _as_float(moon.get("phase_degrees")) is None or _as_float(moon.get("illumination_percent")) is None or not astronomy.get("hourly"):
            missing.append("달 위상")
        if not isinstance(astronomy.get("galactic_center"), dict):
            missing.append("은하수 가시시간")

        available_components = 1 if weather_available else 0
        available_components += 1 if "달 위상" not in missing else 0
        available_components += 1 if "천문박명" not in missing else 0
        available_components += 1 if "은하수 가시시간" not in missing else 0
        percent = round(available_components / 4 * 100)
        return {
            "level": "complete" if not missing and weather_available else "limited",
            "percent": percent,
            "overall_score_available": not missing and weather_available,
            "missing": missing,
        }

    @staticmethod
    def _inverse(value: float, good: float, fair: float, poor: float) -> float:
        """Continuous inverse score so 6% cloud and 22% cloud are not tied."""
        if value <= good:
            # A value of zero is ideal; the desirable boundary remains strong
            # but no longer makes all clear forecasts indistinguishable.
            return 100.0 - (value / good * 10.0) if good else 100.0
        if value >= poor:
            return 0.0
        # The middle threshold gives a gentler degradation before bad weather.
        if value <= fair:
            return 90.0 - ((value - good) / (fair - good) * 30.0)
        return 60.0 - ((value - fair) / (poor - fair) * 60.0)


class NightSkyResearchService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        fetch_json: Callable[[str, dict[str, str], float], dict[str, Any]] | None = None,
        now_provider: Callable[[str], datetime] | None = None,
        llm_summarizer: Callable[[NightSkyBriefingData, Settings], str] | None = None,
        policy: NightSkyPolicy | None = None,
        scoring_config: dict[str, Any] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.fetch_json = fetch_json or _fetch_json
        self.now_provider = now_provider or _now_in_timezone
        self.llm_summarizer = llm_summarizer or _summarize_with_openai
        self.policy = policy or NightSkyPolicy()
        self.scoring_config = scoring_config or load_scoring_config()

    def check(self, query: str, location: str | None = None) -> NightSkyCheckResponse:
        requested_location = (location or self.settings.default_observation_location).strip()
        LOGGER.info("[NightSky] request received location=%s", requested_location)
        errors: list[str] = []

        try:
            observation = self._resolve_location(requested_location)
        except NightSkySourceError as error:
            LOGGER.warning("[NightSky] location resolve failed: %s", error)
            return self._unavailable_result(requested_location, [f"location: {error}"])

        return self.check_observation(query=query, observation=observation)

    def check_observation(self, query: str, observation: ObservationLocation) -> NightSkyCheckResponse:
        """Check a confirmed coordinate without doing a place-name lookup.

        Favorite-place comparison calls this method so every row uses the
        exact camera point the user configured, rather than a geocoder guess.
        """
        LOGGER.info("[NightSky] request received observation=%s", observation.name)
        errors: list[str] = []

        local_now = self.now_provider(observation.timezone)
        target_day = local_now.date()
        weather: dict[str, Any] = {}
        astronomy: dict[str, Any] = {}

        try:
            weather = self._fetch_weather(observation)
            LOGGER.info("[NightSky] weather fetch success")
        except NightSkySourceError as error:
            errors.append(f"weather: {error}")
            LOGGER.warning("[NightSky] weather fetch failed: %s", error)

        weather_points = _hourly_conditions(weather.get("hourly") or {}, observation.timezone)
        try:
            astronomy = self._fetch_astronomy(observation, target_day, weather_points)
            LOGGER.info("[NightSky] moon calculation success")
        except NightSkySourceError as error:
            errors.append(f"astronomy: {error}")
            LOGGER.warning("[NightSky] astronomy fetch failed: %s", error)

        weather_window = self._select_best_window(weather, target_day, local_now, observation.timezone)
        integrated = _integrate_hours(weather_points, astronomy, self.policy, self.scoring_config)
        recommended_window = _select_recommended_window(integrated, target_day, local_now, observation.timezone, self.scoring_config)
        weather_score = recommended_window.weather_score if recommended_window else (weather_window.score if weather_window else None)
        confidence = self.policy.scoring_confidence(astronomy, weather_available=weather_score is not None)
        astronomy_score = _astronomy_score(integrated, self.scoring_config) if confidence["overall_score_available"] else None
        overall_score = (
            round(weather_score * self.scoring_config["weather_weight"] + astronomy_score * self.scoring_config["astronomy_weight"])
            if weather_score is not None and astronomy_score is not None
            else None
        )
        score = overall_score if overall_score is not None else weather_score
        grade = self.policy.grade(score)

        data = self._build_data(
            observation=observation,
            weather=weather,
            astronomy=astronomy,
            window=recommended_window,
            weather_window=weather_window,
            integrated=integrated,
            local_now=local_now,
            score=score,
            weather_score=weather_score,
            astronomy_score=astronomy_score,
            overall_score=overall_score,
            grade=grade,
            scoring_confidence=confidence,
            source_errors=errors,
        )
        speech = self._build_speech(data)

        if self.settings.night_sky_use_llm_summary and self.settings.has_openai and data.score is not None:
            try:
                rewritten = self.llm_summarizer(data, self.settings).strip()
                if rewritten:
                    data.summary = rewritten
                    speech = rewritten
                    LOGGER.info("[NightSky] summary generated with OpenAI")
            except Exception as error:  # Summary is optional; facts and score stay usable.
                errors.append(f"llm: {type(error).__name__}")
                data.source_errors = errors
                LOGGER.warning("[NightSky] summary generation failed: %s", type(error).__name__)

        LOGGER.info("[NightSky] score calculated: %s", score if score is not None else "unavailable")
        return NightSkyCheckResponse(
            success=score is not None,
            data=data,
            speech=speech,
        )

    def _resolve_location(self, location_name: str) -> ObservationLocation:
        if not location_name:
            raise NightSkySourceError("관측 지역이 비어 있습니다.")
        url = f"{OPEN_METEO_GEOCODING_URL}?{urlencode({'name': location_name, 'count': 1, 'language': 'ko', 'format': 'json'})}"
        payload = self.fetch_json(url, {}, self.settings.night_sky_http_timeout_seconds)
        result = (payload.get("results") or [None])[0]
        if not isinstance(result, dict):
            raise NightSkySourceError("관측 지역을 찾지 못했습니다.")
        latitude, longitude = _as_float(result.get("latitude")), _as_float(result.get("longitude"))
        if latitude is None or longitude is None:
            raise NightSkySourceError("관측 지역 좌표가 올바르지 않습니다.")
        return ObservationLocation(
            name=str(result.get("name") or location_name),
            latitude=latitude,
            longitude=longitude,
            timezone=str(result.get("timezone") or "Asia/Seoul"),
        )

    def _fetch_weather(self, location: ObservationLocation) -> dict[str, Any]:
        params = {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "timezone": location.timezone,
            "forecast_days": 2,
            "hourly": "cloud_cover,precipitation_probability,relative_humidity_2m,wind_speed_10m,temperature_2m",
            "current": "weather_code,cloud_cover,precipitation,wind_speed_10m",
            "daily": "sunrise,sunset",
        }
        payload = self.fetch_json(f"{OPEN_METEO_FORECAST_URL}?{urlencode(params)}", {}, self.settings.night_sky_http_timeout_seconds)
        hourly = payload.get("hourly")
        if not isinstance(hourly, dict) or not hourly.get("time"):
            raise NightSkySourceError("시간대별 날씨 응답이 비어 있습니다.")
        return payload

    def _fetch_astronomy(self, location: ObservationLocation, target_day: date, weather_points: list[HourlyCondition]) -> dict[str, Any]:
        try:
            result = calculate_astronomy(
                latitude=location.latitude,
                longitude=location.longitude,
                timezone_name=location.timezone,
                target_day=target_day,
                hourly_times=[point.when for point in weather_points],
                config=self.scoring_config,
            )
        except Exception as error:
            raise NightSkySourceError(f"local astronomy calculation failed: {type(error).__name__}") from error
        sun = result["sun"]
        return {
            "sun": {**sun, "astronomical_twilight": sun.get("astronomical_twilight_end")},
            "moon": result["moon"],
            "galactic_center": result["galactic_center"],
            "hourly": result["hourly"],
        }

    def _select_best_window(
        self,
        weather: dict[str, Any],
        target_day: date,
        local_now: datetime,
        timezone_name: str,
    ) -> ScoredWindow | None:
        hourly = weather.get("hourly") if isinstance(weather, dict) else None
        if not isinstance(hourly, dict):
            return None
        points = _hourly_conditions(hourly, timezone_name)
        if not points:
            return None
        sunset = _daily_time(weather.get("daily"), "sunset", target_day, timezone_name)
        zone = _timezone_for(timezone_name)
        night_start = datetime.combine(target_day, time(20, 0), tzinfo=zone)
        if sunset is not None:
            night_start = max(night_start, sunset + timedelta(hours=2))
        night_start = max(night_start, local_now.replace(minute=0, second=0, microsecond=0))
        night_end = datetime.combine(target_day + timedelta(days=1), time(3, 0), tzinfo=zone)
        candidates = [point for point in points if night_start <= point.when <= night_end]
        scored = [(point, self.policy.weather_score(point)) for point in candidates]
        valid = [(point, score) for point, score in scored if score is not None]
        if not valid:
            return None

        # Prefer a stable three-hour period to one unusually clear hour.
        windows: list[ScoredWindow] = []
        for index, (point, score) in enumerate(valid):
            trio = valid[index:index + 3]
            if len(trio) == 3 and all(trio[position][0].when - trio[0][0].when == timedelta(hours=position) for position in range(3)):
                mean = round(sum(item_score for _, item_score in trio) / 3)
                windows.append(ScoredWindow(point.when, trio[-1][0].when + timedelta(hours=1), mean, _average_condition([item[0] for item in trio])))
            else:
                windows.append(ScoredWindow(point.when, point.when + timedelta(hours=1), score, point))
        return max(windows, key=lambda item: item.score)

    def _build_data(
        self,
        *,
        observation: ObservationLocation,
        weather: dict[str, Any],
        astronomy: dict[str, Any],
        window: RecommendationWindow | None,
        weather_window: ScoredWindow | None,
        integrated: list[IntegratedHour],
        local_now: datetime,
        score: int | None,
        weather_score: int | None,
        astronomy_score: int | None,
        overall_score: int | None,
        grade: str,
        scoring_confidence: dict[str, Any],
        source_errors: list[str],
    ) -> NightSkyBriefingData:
        sun = astronomy.get("sun", {})
        moon = astronomy.get("moon", {})
        best_time = _format_range(window.start, window.end) if window else None
        if best_time and window and window.advisory:
            best_time = f"{best_time} · {window.advisory}"
        condition = window.condition if window else (weather_window.condition if weather_window else None)
        weather_data = {
            "cloud_cover_percent": _round_or_none(condition.cloud_cover if condition else None),
            "precipitation_probability_percent": _round_or_none(condition.precipitation_probability if condition else None),
            "humidity_percent": _round_or_none(condition.humidity if condition else None),
            "wind_speed_kmh": _round_or_none(condition.wind_speed if condition else None),
            "temperature_celsius": _round_or_none(condition.temperature if condition else None),
            "current_weather_code": _round_or_none(_as_float((weather.get("current") or {}).get("weather_code"))),
            "sunset": sun.get("sunset") or _daily_raw_time(weather.get("daily"), "sunset"),
            "sunrise": sun.get("sunrise") or _daily_raw_time(weather.get("daily"), "sunrise"),
            "astronomical_twilight": sun.get("astronomical_twilight"),
            "civil_twilight_end": sun.get("civil_twilight_end"),
            "nautical_twilight_end": sun.get("nautical_twilight_end"),
            "astronomical_twilight_end": sun.get("astronomical_twilight_end"),
            "astronomical_twilight_start": sun.get("astronomical_twilight_start"),
        }
        moon_data = {
            "phase_degrees": _round_or_none(_as_float(moon.get("phase_degrees"))),
            "illumination_percent": _round_or_none(_as_float(moon.get("illumination_percent"))),
            "moonrise": moon.get("moonrise"),
            "moonset": moon.get("moonset"),
            "phase": moon.get("phase"),
        }
        if window is not None:
            selected_hour = next((item for item in integrated if item.condition.when == window.start), None)
            if selected_hour is not None:
                moon_data["impact"] = selected_hour.moon_impact
                moon_data["altitude_degrees"] = _round_or_none(selected_hour.moon_altitude_degrees)
        astronomy_data = {
            "engine": "PyEphem",
            "galactic_center": astronomy.get("galactic_center") or {},
        }
        reasons = _reasons(weather_data, moon_data, weather_score)
        warnings = _warnings(weather_data, moon_data, source_errors, scoring_confidence)
        summary = _deterministic_summary(observation.name, score, grade, best_time, reasons, source_errors)
        return NightSkyBriefingData(
            title="오늘 밤 은하수 촬영 조건",
            summary=summary,
            score=score,
            grade=grade,
            best_time=best_time,
            location=observation.as_dict(),
            weather=weather_data,
            moon=moon_data,
            astronomy=astronomy_data,
            hourly=[_integrated_hour_payload(item, moon_data.get("illumination_percent")) for item in integrated],
            score_breakdown={
                "weather_score": weather_score,
                "astronomy_score": astronomy_score,
                "overall_score": overall_score,
                "data_confidence_percent": scoring_confidence.get("percent", 0),
            },
            scoring_confidence=scoring_confidence,
            reasons=reasons,
            warnings=warnings,
            actions=[{"label": "자세히 보기", "action": "open_detail"}],
            source_errors=source_errors,
        )

    def _build_speech(self, data: NightSkyBriefingData) -> str:
        if data.score_breakdown.get("overall_score") is None or not data.best_time:
            return data.summary
        moon_impact_value = str(data.moon.get("impact") or "unknown")
        location = str(data.location.get("name") or "이 촬영지")
        if moon_impact_value == "high":
            return f"{location}은 기상 조건은 좋지만 {data.best_time} 사이 달빛 영향이 커질 수 있습니다. 더 이른 시간 촬영을 권합니다."
        return f"{location} 조건이 좋습니다. {data.best_time} 사이에 하늘이 충분히 어둡고 은하수 중심부 고도와 구름 상태가 좋습니다."

    def _unavailable_result(self, location: str, errors: list[str]) -> NightSkyCheckResponse:
        data = NightSkyBriefingData(
            title="오늘 밤 은하수 촬영 조건",
            summary="현재 관측 지역 또는 기상 데이터를 확인하지 못해 촬영 여부를 판단하기 어렵습니다.",
            score=None,
            grade="unknown",
            best_time=None,
            location={"name": location},
            weather={},
            moon={},
            hourly=[],
            score_breakdown={"weather_score": None, "astronomy_score": None, "overall_score": None, "data_confidence_percent": 0},
            scoring_confidence={"level": "unavailable", "percent": 0, "overall_score_available": False, "missing": ["기상 데이터", "천문 데이터"]},
            reasons=[],
            warnings=["확인 가능한 정보만으로는 촬영 여부를 판단하지 않습니다."],
            actions=[{"label": "다시 확인", "action": "retry"}],
            source_errors=errors,
        )
        return NightSkyCheckResponse(success=False, data=data, speech=data.summary)


def check_night_sky(query: str, location: str | None = None) -> NightSkyCheckResponse:
    return NightSkyResearchService().check(query=query, location=location)


def check_night_sky_at_coordinates(
    query: str,
    *,
    name: str,
    latitude: float,
    longitude: float,
    timezone_name: str = "Asia/Seoul",
) -> NightSkyCheckResponse:
    """Use a user-confirmed camera point without a geocoder fallback."""
    return NightSkyResearchService().check_observation(
        query=query,
        observation=ObservationLocation(name=name, latitude=latitude, longitude=longitude, timezone=timezone_name),
    )


def coordinate_required_night_sky_result(name: str, region: str) -> NightSkyCheckResponse:
    message = f"{name}의 실제 촬영 지점 좌표를 확인한 뒤 Night Sky 상세 조회를 할 수 있습니다."
    data = NightSkyBriefingData(
        title="은하수 촬영 조건",
        summary=message,
        score=None,
        grade="unknown",
        best_time=None,
        location={"name": name, "region": region},
        weather={},
        moon={},
        hourly=[],
        score_breakdown={"weather_score": None, "astronomy_score": None, "overall_score": None, "data_confidence_percent": 0},
        scoring_confidence={"level": "unavailable", "percent": 0, "overall_score_available": False, "missing": ["촬영 지점 좌표"]},
        reasons=[],
        warnings=["favorite_observation_spots.json에 확인한 위도와 경도를 입력해 주세요."],
        actions=[{"label": "좌표 설정", "action": "configure_coordinates"}],
        source_errors=["favorite spot coordinates require confirmation"],
    )
    return NightSkyCheckResponse(success=False, data=data, speech=message)


def is_night_sky_query(text: str) -> bool:
    compact = "".join(str(text or "").lower().split())
    return any(token in compact for token in ("은하수", "별찍", "별사진", "야간촬영", "천체사진", "별보러", "출사어디", "촬영지"))


def is_night_sky_comparison_query(text: str) -> bool:
    """Default every unqualified Night Sky request to favorite-spot comparison.

    Natural-language routing checks for an explicitly named favorite first.
    Everything else here is intentionally a comparison request so Seoul can
    never be silently substituted as the Night Sky default.
    """
    return is_night_sky_query(text)


def _fetch_json(url: str, headers: dict[str, str], timeout: float) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json", **headers})
    try:
        with urlopen(request, timeout=timeout, context=_https_context()) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        raise NightSkySourceError(type(error).__name__) from error
    if not isinstance(payload, dict):
        raise NightSkySourceError("잘못된 JSON 응답")
    return payload


def _now_in_timezone(timezone_name: str) -> datetime:
    return datetime.now(_timezone_for(timezone_name))


def _https_context():
    """Keep TLS verification on while supporting Windows venv certificate stores."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _timezone_for(timezone_name: str):
    """Use system zoneinfo when present, with a no-dependency fallback for the PoC."""
    try:
        return ZoneInfo(timezone_name)
    except Exception:
        # Windows Python installations may not include the IANA tzdata package.
        # The configured default is Seoul; common nearby/default zones keep their
        # correct standard offset rather than making night-window times UTC.
        offsets = {
            "Asia/Seoul": 9,
            "Asia/Tokyo": 9,
            "Asia/Shanghai": 8,
            "Asia/Singapore": 8,
            "UTC": 0,
            "Etc/UTC": 0,
        }
        return timezone(timedelta(hours=offsets.get(timezone_name, 0)), name=timezone_name)


def _offset_for(value: datetime) -> str:
    raw = value.strftime("%z") or "+0000"
    return f"{raw[:3]}:{raw[3:]}"


def _properties(payload: dict[str, Any]) -> dict[str, Any]:
    properties = payload.get("properties")
    return properties if isinstance(properties, dict) else {}


def _event_time(value: Any) -> str | None:
    return str(value.get("time")) if isinstance(value, dict) and value.get("time") else None


def _nested_number(payload: dict[str, Any], key: str, value_key: str) -> float | None:
    value = payload.get(key)
    # Sunrise 3.0 currently returns moonphase as a number; retain support for
    # the documented object form so a response-shape change stays recoverable.
    return _as_float(value.get(value_key)) if isinstance(value, dict) else _as_float(value)


def _moon_illumination(phase_degrees: float | None) -> float | None:
    if phase_degrees is None:
        return None
    return round((1 - math.cos(math.radians(phase_degrees))) * 50, 1)


def _hourly_conditions(hourly: dict[str, Any], timezone_name: str) -> list[HourlyCondition]:
    values = hourly.get("time") or []
    fields = {
        "cloud_cover": hourly.get("cloud_cover") or [],
        "precipitation_probability": hourly.get("precipitation_probability") or [],
        "humidity": hourly.get("relative_humidity_2m") or [],
        "wind_speed": hourly.get("wind_speed_10m") or [],
        "temperature": hourly.get("temperature_2m") or [],
    }
    zone = _timezone_for(timezone_name)
    result: list[HourlyCondition] = []
    for index, raw_time in enumerate(values):
        try:
            when = datetime.fromisoformat(str(raw_time)).replace(tzinfo=zone)
        except ValueError:
            continue
        result.append(HourlyCondition(
            when=when,
            cloud_cover=_item_number(fields["cloud_cover"], index),
            precipitation_probability=_item_number(fields["precipitation_probability"], index),
            humidity=_item_number(fields["humidity"], index),
            wind_speed=_item_number(fields["wind_speed"], index),
            temperature=_item_number(fields["temperature"], index),
        ))
    return result


def _integrate_hours(
    weather_points: list[HourlyCondition],
    astronomy: dict[str, Any],
    policy: NightSkyPolicy,
    config: dict[str, Any],
) -> list[IntegratedHour]:
    astronomy_by_time = {
        str(item.get("at")): item
        for item in astronomy.get("hourly") or []
        if isinstance(item, dict) and item.get("at")
    }
    illumination = _as_float((astronomy.get("moon") or {}).get("illumination_percent"))
    integrated: list[IntegratedHour] = []
    for point in weather_points:
        values = astronomy_by_time.get(point.when.isoformat())
        if not values:
            continue
        weather_score = policy.weather_score(point)
        moon_impact_value = str(values.get("moon_impact") or "unknown")
        gc_altitude = _as_float(values.get("galactic_center_altitude_degrees"))
        dark = bool(values.get("astronomical_dark"))
        astronomy_hour_score = _astronomy_hour_score(dark, gc_altitude, moon_impact_value, config)
        hour_score = (
            round(weather_score * config["weather_weight"] + astronomy_hour_score * config["astronomy_weight"])
            if weather_score is not None and astronomy_hour_score is not None
            else None
        )
        integrated.append(IntegratedHour(
            condition=point,
            weather_score=weather_score,
            astronomy_hour_score=astronomy_hour_score,
            hour_score=hour_score,
            moon_altitude_degrees=_as_float(values.get("moon_altitude_degrees")),
            moon_azimuth_degrees=_as_float(values.get("moon_azimuth_degrees")),
            moon_impact=moon_impact_value,
            galactic_center_altitude_degrees=gc_altitude,
            astronomical_dark=dark,
        ))
    return integrated


def _astronomy_hour_score(dark: bool, gc_altitude: float | None, moon_impact_value: str, config: dict[str, Any]) -> int | None:
    if gc_altitude is None or moon_impact_value == "unknown":
        return None
    points = config["astronomy_score"]
    score = points["darkness_points"] if dark else 0
    if gc_altitude >= config["good_galactic_center_altitude_degrees"]:
        score += points["good_galactic_center_points"]
    elif gc_altitude >= config["minimum_galactic_center_altitude_degrees"]:
        score += points["minimum_galactic_center_points"]
    score += points[f"{moon_impact_value}_moon_impact_points"]
    return min(100, int(score))


def _astronomy_score(integrated: list[IntegratedHour], config: dict[str, Any]) -> int | None:
    if not integrated:
        return None
    eligible = [
        item for item in integrated
        if item.astronomical_dark
        and item.galactic_center_altitude_degrees is not None
        and item.galactic_center_altitude_degrees >= config["minimum_galactic_center_altitude_degrees"]
    ]
    if not eligible:
        return 0
    points = config["astronomy_score"]
    max_gc = max(item.galactic_center_altitude_degrees or 0 for item in eligible)
    gc_points = points["good_galactic_center_points"] if max_gc >= config["good_galactic_center_altitude_degrees"] else points["minimum_galactic_center_points"]
    visible_hours = len(eligible)
    duration_points = (
        points["two_hour_visibility_points"] if visible_hours >= 2
        else points["one_hour_visibility_points"] if visible_hours >= 1
        else points["short_visibility_points"]
    )
    moon_points = round(sum(points[f"{item.moon_impact}_moon_impact_points"] for item in eligible) / visible_hours)
    return min(100, points["darkness_points"] + gc_points + duration_points + moon_points)


def _select_recommended_window(
    integrated: list[IntegratedHour],
    target_day: date,
    local_now: datetime,
    timezone_name: str,
    config: dict[str, Any],
) -> RecommendationWindow | None:
    zone = _timezone_for(timezone_name)
    night_start = max(
        datetime.combine(target_day, time(20), tzinfo=zone),
        local_now.replace(minute=0, second=0, microsecond=0),
    )
    night_end = datetime.combine(target_day + timedelta(days=1), time(4), tzinfo=zone)
    allowed_moon = {"low", "medium"} if config["allow_medium_moon_impact"] else {"low"}
    base_candidates = [
        item for item in integrated
        if night_start <= item.condition.when <= night_end
        and item.weather_score is not None
        and item.astronomy_hour_score is not None
        and item.astronomical_dark
        and (item.galactic_center_altitude_degrees or -90) >= config["minimum_galactic_center_altitude_degrees"]
        and item.condition.cloud_cover is not None and item.condition.cloud_cover <= config["maximum_recommended_cloud_percent"]
        and item.condition.precipitation_probability is not None and item.condition.precipitation_probability <= config["maximum_recommended_rain_percent"]
    ]
    candidates = [item for item in base_candidates if item.moon_impact in allowed_moon]
    advisory: str | None = None
    # If weather, darkness, and Galactic Center visibility are all valid but
    # moonlight is the only blocker, show the best *available* interval rather
    # than leaving the UI with an unexplained blank recommendation.
    if not candidates and base_candidates:
        candidates = base_candidates
        impacts = {item.moon_impact for item in candidates}
        advisory = "달 영향 높음" if "high" in impacts else "달 영향 보통"
    groups: list[list[IntegratedHour]] = []
    for item in candidates:
        if groups and item.condition.when - groups[-1][-1].condition.when == timedelta(hours=1):
            groups[-1].append(item)
        else:
            groups.append([item])
    if not groups:
        return None
    selected = max(groups, key=lambda group: (len(group), round(sum(item.hour_score or 0 for item in group) / len(group))))
    return RecommendationWindow(
        start=selected[0].condition.when,
        end=selected[-1].condition.when + timedelta(hours=1),
        weather_score=round(sum(item.weather_score or 0 for item in selected) / len(selected)),
        astronomy_score=round(sum(item.astronomy_hour_score or 0 for item in selected) / len(selected)),
        overall_score=round(sum(item.hour_score or 0 for item in selected) / len(selected)),
        condition=_average_condition([item.condition for item in selected]),
        advisory=advisory,
    )


def _integrated_hour_payload(item: IntegratedHour, illumination: float | None) -> dict[str, Any]:
    return {
        "time": f"{item.condition.when.hour:02d}시",
        "at": item.condition.when.isoformat(),
        "cloud_cover_percent": _round_or_none(item.condition.cloud_cover),
        "precipitation_probability_percent": _round_or_none(item.condition.precipitation_probability),
        "humidity_percent": _round_or_none(item.condition.humidity),
        "wind_speed_kmh": _round_or_none(item.condition.wind_speed),
        "moon_altitude_degrees": _round_or_none(item.moon_altitude_degrees),
        "moon_illumination_percent": _round_or_none(illumination),
        "moon_impact": item.moon_impact,
        "galactic_center_altitude_degrees": _round_or_none(item.galactic_center_altitude_degrees),
        "astronomical_dark": item.astronomical_dark,
        "weather_score": item.weather_score,
        "astronomy_hour_score": item.astronomy_hour_score,
        "hour_score": item.hour_score,
    }


def _night_timeline(hourly: Any, timezone_name: str, *, start_at: datetime | None = None) -> list[dict[str, Any]]:
    """Expose a compact read-only timeline for UI consumers; it never affects scoring."""
    if not isinstance(hourly, dict):
        return []
    zone = _timezone_for(timezone_name)
    reference = (start_at or datetime.now(zone)).astimezone(zone)
    # A night is one continuous datetime range, not a collection of matching
    # clock-hour strings.  This keeps midnight in the correct chronological
    # position and prevents the following evening from leaking into the row.
    night_date = reference.date() if reference.hour >= 4 else (reference - timedelta(days=1)).date()
    night_start = datetime.combine(night_date, time(20), tzinfo=zone)
    night_end = datetime.combine(night_date + timedelta(days=1), time(3, 59), tzinfo=zone)
    window_start = max(night_start, reference.replace(minute=0, second=0, microsecond=0))
    result = []
    for item in sorted(_hourly_conditions(hourly, timezone_name), key=lambda point: point.when):
        if window_start <= item.when <= night_end:
            result.append({
                "time": f"{item.when.hour:02d}시",
                "cloud_cover_percent": _round_or_none(item.cloud_cover),
                "precipitation_probability_percent": _round_or_none(item.precipitation_probability),
            })
    return result[:7]


def _daily_time(daily: Any, key: str, target_day: date, timezone_name: str) -> datetime | None:
    if not isinstance(daily, dict):
        return None
    for raw in daily.get(key) or []:
        try:
            moment = datetime.fromisoformat(str(raw)).replace(tzinfo=_timezone_for(timezone_name))
        except ValueError:
            continue
        if moment.date() == target_day:
            return moment
    return None


def _daily_raw_time(daily: Any, key: str) -> str | None:
    return str((daily or {}).get(key, [None])[0] or "") or None if isinstance(daily, dict) else None


def _average_condition(items: list[HourlyCondition]) -> HourlyCondition:
    first = items[0]
    return HourlyCondition(
        when=first.when,
        cloud_cover=_mean([item.cloud_cover for item in items]),
        precipitation_probability=_mean([item.precipitation_probability for item in items]),
        humidity=_mean([item.humidity for item in items]),
        wind_speed=_mean([item.wind_speed for item in items]),
        temperature=_mean([item.temperature for item in items]),
    )


def _mean(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None


def _item_number(values: list[Any], index: int) -> float | None:
    return _as_float(values[index]) if index < len(values) else None


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _round_or_none(value: float | None) -> int | float | None:
    if value is None:
        return None
    return int(round(value)) if float(value).is_integer() else round(value, 1)


def _format_range(start: datetime, end: datetime) -> str:
    return f"{start.strftime('%H:%M')} ~ {end.strftime('%H:%M')}"


def _reasons(weather: dict[str, Any], moon: dict[str, Any], score: int | None) -> list[str]:
    if score is None:
        return []
    reasons: list[str] = []
    cloud = weather.get("cloud_cover_percent")
    rain = weather.get("precipitation_probability_percent")
    illumination = moon.get("illumination_percent")
    if cloud is not None:
        reasons.append(f"예상 구름량이 {cloud}%입니다.")
    if rain is not None:
        reasons.append(f"강수 확률이 {rain}%입니다.")
    if illumination is not None:
        reasons.append(f"달 밝기는 약 {illumination}%입니다.")
    return reasons


def _warnings(
    weather: dict[str, Any],
    moon: dict[str, Any],
    source_errors: list[str],
    scoring_confidence: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []
    if (humidity := weather.get("humidity_percent")) is not None and humidity >= 90:
        warnings.append(f"습도가 {humidity}%로 높아 렌즈 결로에 주의하세요.")
    if (wind := weather.get("wind_speed_kmh")) is not None and wind >= 25:
        warnings.append(f"풍속이 {wind}km/h로 높아 삼각대가 흔들릴 수 있습니다.")
    if (illumination := moon.get("illumination_percent")) is not None and illumination > 75:
        warnings.append("달빛이 강해 은하수 대비가 낮아질 수 있습니다.")
    missing = scoring_confidence.get("missing") or []
    if missing:
        warnings.append(f"{', '.join(str(item) for item in missing)} 상태라 천문 조건과 종합 촬영 적합도는 확정하지 않습니다.")
    if source_errors:
        warnings.append("일부 데이터 소스를 가져오지 못해 확인 가능한 정보만 반영했습니다.")
    return warnings


def _deterministic_summary(location: str, score: int | None, grade: str, best_time: str | None, reasons: list[str], errors: list[str]) -> str:
    if score is None:
        return "현재 일부 기상 데이터를 가져오지 못했습니다. 확인 가능한 정보만으로는 촬영 여부를 판단하기 어렵습니다."
    verdict = {
        "good": "오늘 밤 기상 조건이 좋습니다.",
        "fair": "오늘 밤 기상 조건은 보통입니다. 천문 조건을 더 확인하는 편이 좋습니다.",
        "poor": "오늘 밤 기상 조건에서는 은하수 촬영을 추천하지 않습니다.",
    }[grade]
    timing = f" {location} 기준 가장 나은 시간은 {best_time}입니다." if best_time else ""
    detail = f" {reasons[0]}" if reasons else ""
    return f"{verdict}{timing}{detail}"


def _summarize_with_openai(data: NightSkyBriefingData, settings: Settings) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key, timeout=12)
    facts = json.dumps(data.model_dump(mode="json"), ensure_ascii=False)
    response = client.responses.create(
        model=settings.openai_model,
        input=(
            "You are a Korean personal assistant. Rewrite ONLY these supplied facts into a concise 2-3 sentence Korean night-sky recommendation. "
            "Do not invent weather, astronomy, locations, times, scores, or certainty. Preserve uncertainty and warnings.\n"
            f"FACTS: {facts}"
        ),
    )
    output = str(getattr(response, "output_text", "")).strip()
    return output[:500]
