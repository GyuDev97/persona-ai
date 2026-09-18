"""Local, coordinate-based astronomy calculations for Night Sky.

PyEphem carries the calculation model in the installed package, so this module
does not download ephemeris files at request time and never asks an LLM to
invent a celestial value.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import ephem


SCORING_PATH = Path(__file__).resolve().parents[2] / "config" / "night_sky_scoring.json"
GC_RA = "17:45:40.04"  # Sagittarius A* / Galactic Center, J2000
GC_DEC = "-29:00:28.1"


def load_scoring_config(path: Path = SCORING_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def calculate_astronomy(
    *,
    latitude: float,
    longitude: float,
    timezone_name: str,
    target_day: date,
    hourly_times: Iterable[datetime],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Calculate darkness, Moon and Galactic Center values for one local night."""
    config = config or load_scoring_config()
    zone = _timezone_for(timezone_name)
    noon = datetime.combine(target_day, time(12), tzinfo=zone)
    observer = _observer(latitude, longitude)
    sun = ephem.Sun()
    moon = ephem.Moon()
    gc = _galactic_center()

    sunset = _next_event(observer, sun, noon, "setting", "-0:34", zone)
    sunrise = _next_event(observer, sun, noon, "rising", "-0:34", zone)
    civil_end = _next_event(observer, sun, noon, "setting", "-6", zone)
    nautical_end = _next_event(observer, sun, noon, "setting", "-12", zone)
    astronomical_end = _next_event(observer, sun, noon, "setting", "-18", zone)
    astronomical_start = _next_event(observer, sun, astronomical_end or noon, "rising", "-18", zone)

    night_start = astronomical_end or datetime.combine(target_day, time(20), tzinfo=zone)
    night_end = astronomical_start or datetime.combine(target_day + timedelta(days=1), time(4), tzinfo=zone)
    moonrise = _next_event(observer, moon, night_start, "rising", "0", zone)
    moonset = _next_event(observer, moon, night_start, "setting", "0", zone)

    observer.date = _ephem_date(night_start)
    moon.compute(observer)
    illumination = round(float(moon.phase), 1)
    phase_degrees = round(math.degrees(float(moon.elong)) % 360, 1)
    hourly: list[dict[str, Any]] = []
    for moment in sorted(hourly_times):
        if not (night_start <= moment <= night_end):
            continue
        observer.date = _ephem_date(moment)
        moon.compute(observer)
        gc.compute(observer)
        moon_altitude = round(math.degrees(float(moon.alt)), 1)
        gc_altitude = round(math.degrees(float(gc.alt)), 1)
        hourly.append({
            "at": moment.isoformat(),
            "moon_altitude_degrees": moon_altitude,
            "moon_azimuth_degrees": round(math.degrees(float(moon.az)) % 360, 1),
            "moon_impact": moon_impact(illumination, moon_altitude, config),
            "galactic_center_altitude_degrees": gc_altitude,
            "astronomical_dark": bool(astronomical_end and astronomical_start and astronomical_end <= moment < astronomical_start),
        })

    gc_rise = _event_covering_start(observer, gc, night_start, "rising", "0", zone)
    gc_set = _event_covering_start(observer, gc, night_start, "setting", "0", zone)
    gc_best_start = _event_covering_start(observer, gc, night_start, "rising", str(config["minimum_galactic_center_altitude_degrees"]), zone)
    gc_best_end = _event_covering_start(observer, gc, night_start, "setting", str(config["minimum_galactic_center_altitude_degrees"]), zone)
    visible = [item for item in hourly if item["galactic_center_altitude_degrees"] >= config["minimum_galactic_center_altitude_degrees"]]
    return {
        "sun": {
            "sunset": _iso(sunset),
            "civil_twilight_end": _iso(civil_end),
            "nautical_twilight_end": _iso(nautical_end),
            "astronomical_twilight_end": _iso(astronomical_end),
            "astronomical_twilight_start": _iso(astronomical_start),
            "sunrise": _iso(sunrise),
        },
        "moon": {
            "phase_degrees": phase_degrees,
            "illumination_percent": illumination,
            "phase": _moon_phase(illumination, phase_degrees),
            "moonrise": _iso(moonrise),
            "moonset": _iso(moonset),
        },
        "galactic_center": {
            "visible": bool(visible),
            "rise_time": _iso(gc_rise),
            "best_start": _iso(gc_best_start) if visible else None,
            "best_end": _iso(gc_best_end) if visible else None,
            "set_time": _iso(gc_set),
            "max_altitude_degrees": max((item["galactic_center_altitude_degrees"] for item in hourly), default=None),
        },
        "hourly": hourly,
    }


def moon_impact(illumination: float | None, altitude: float | None, config: dict[str, Any]) -> str:
    if illumination is None or altitude is None:
        return "unknown"
    if altitude < 0 or illumination <= config["moon_low_illumination_percent"]:
        return "low"
    if altitude < config["moon_low_altitude_degrees"] or illumination <= config["moon_medium_illumination_percent"]:
        return "medium"
    return "high"


def _observer(latitude: float, longitude: float) -> ephem.Observer:
    observer = ephem.Observer()
    observer.lat = str(latitude)
    observer.lon = str(longitude)
    observer.elevation = 0
    observer.pressure = 0
    return observer


def _galactic_center() -> ephem.FixedBody:
    body = ephem.FixedBody()
    body._ra = ephem.hours(GC_RA)
    body._dec = ephem.degrees(GC_DEC)
    body._epoch = ephem.J2000
    return body


def _next_event(observer: ephem.Observer, body: Any, start: datetime, event: str, horizon: str, zone: tzinfo) -> datetime | None:
    try:
        observer.date = _ephem_date(start)
        observer.horizon = horizon
        value = observer.next_rising(body) if event == "rising" else observer.next_setting(body)
        return _local_datetime(value, zone)
    except (ephem.AlwaysUpError, ephem.NeverUpError, ValueError):
        return None


def _event_covering_start(observer: ephem.Observer, body: Any, start: datetime, event: str, horizon: str, zone: tzinfo) -> datetime | None:
    """Return the rise/set belonging to the interval containing `start`."""
    try:
        observer.date = _ephem_date(start)
        observer.horizon = horizon
        body.compute(observer)
        is_above = float(body.alt) >= math.radians(float(horizon))
        if event == "rising":
            value = observer.previous_rising(body) if is_above else observer.next_rising(body)
        else:
            value = observer.next_setting(body) if is_above else observer.previous_setting(body)
        return _local_datetime(value, zone)
    except (ephem.AlwaysUpError, ephem.NeverUpError, ValueError):
        return None


def _ephem_date(value: datetime) -> ephem.Date:
    return ephem.Date(value.astimezone(timezone.utc).replace(tzinfo=None))


def _local_datetime(value: ephem.Date, zone: tzinfo) -> datetime:
    return value.datetime().replace(tzinfo=timezone.utc).astimezone(zone)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _moon_phase(illumination: float, phase_degrees: float) -> str:
    if illumination < 2:
        return "new_moon"
    if illumination < 50:
        return "waxing_crescent" if phase_degrees < 180 else "waning_crescent"
    if illumination < 98:
        return "waxing_gibbous" if phase_degrees < 180 else "waning_gibbous"
    return "full_moon"


def _timezone_for(timezone_name: str) -> tzinfo:
    try:
        return ZoneInfo(timezone_name)
    except Exception:
        # The Windows Python runtime used by GYUVIS may not bundle IANA tzdata.
        # Favorite observation spots currently use Asia/Seoul.
        offsets = {"Asia/Seoul": 9, "Asia/Tokyo": 9, "Asia/Shanghai": 8, "UTC": 0, "Etc/UTC": 0}
        return timezone(timedelta(hours=offsets.get(timezone_name, 0)), name=timezone_name)
