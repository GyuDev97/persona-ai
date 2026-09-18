"""Best-effort publisher for the local Windows context-overlay client.

The overlay is deliberately a separate desktop process.  If it is not running,
Night Sky research and every existing API response continue normally.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from ..domain.schemas import FavoriteObservationSpotResponse, NightSkyCheckResponse, NightSkySpotComparisonResponse
from .night_sky_comparison_service import check_night_sky_comparison
from .night_sky_service import check_night_sky, check_night_sky_at_coordinates, coordinate_required_night_sky_result


OVERLAY_URL = os.getenv("GYUVIS_CONTEXT_OVERLAY_URL", "http://127.0.0.1:8766/context-card")
OVERLAY_TIMEOUT_SECONDS = 0.45
DETAIL_URL = os.getenv("GYUVIS_CONTEXT_OVERLAY_DETAIL_URL", "http://127.0.0.1:8000/gyuvis/standby-v3")


def check_night_sky_with_overlay(
    query: str,
    location: str | None = None,
    *,
    favorite_spot: FavoriteObservationSpotResponse | None = None,
) -> NightSkyCheckResponse:
    """Run the existing research unchanged, then publish its result if available."""
    publish_context_card({
        "type": "ambient_state",
        "state": "analyzing",
        "title": "조사 중입니다...",
        "transcript": query,
        "steps": ["날씨 정보 확인", "천문 데이터 조회", "촬영 조건 분석", "결과 정리"],
    })
    if favorite_spot is not None and favorite_spot.latitude is not None and favorite_spot.longitude is not None:
        result = check_night_sky_at_coordinates(
            query=query,
            name=favorite_spot.name,
            latitude=favorite_spot.latitude,
            longitude=favorite_spot.longitude,
            timezone_name=favorite_spot.timezone,
        )
        result.data.location.update({"name": favorite_spot.name, "region": favorite_spot.region})
    elif favorite_spot is not None:
        # Never let a fuzzy place-name lookup silently turn a favorite camera
        # point into an unrelated location.
        result = coordinate_required_night_sky_result(favorite_spot.name, favorite_spot.region)
    else:
        result = check_night_sky(query=query, location=location)
    publish_night_sky_overlay(result)
    return result


def publish_night_sky_overlay(result: NightSkyCheckResponse) -> bool:
    return publish_context_card(night_sky_card_payload(result))


def check_night_sky_comparison_with_overlay(query: str) -> NightSkySpotComparisonResponse:
    """Publish a small progress state, then the independently computed rows."""
    publish_context_card({
        "type": "ambient_state",
        "state": "analyzing",
        "title": "5곳 촬영지를 비교 중입니다...",
        "transcript": query,
        "steps": ["촬영지 좌표 확인", "기상 정보 조회", "달 조건 조회", "비교 결과 정리"],
    })
    result = check_night_sky_comparison(query=query)
    publish_night_sky_comparison_overlay(result)
    return result


def publish_night_sky_comparison_overlay(result: NightSkySpotComparisonResponse) -> bool:
    return publish_context_card(night_sky_comparison_card_payload(result))


def publish_test_night_sky_overlay() -> bool:
    """Exercise a running overlay without querying weather or astronomy sources."""
    return publish_context_card(
        {
            "type": "night_sky",
            "title": "오늘 밤 촬영 조건이 좋습니다",
            "summary": "22:40 ~ 00:30 · 구름량 낮음 · 달 영향 적음",
            "best_time": "22:40 ~ 00:30",
            "condition": "구름량 낮음 · 달 영향 적음",
            "score": 87,
            "grade": "good",
            "detail_url": DETAIL_URL,
        }
    )


def publish_test_night_sky_comparison_overlay() -> bool:
    """Mock-only UI check; it never calls weather or astronomy providers."""
    return publish_context_card(
        {
            "type": "night_sky_spot_comparison",
            "state": "comparison_detail",
            "title": "오늘 밤 출사 조건",
            "summary": "5곳 중 3곳이 비교 테스트에서 촬영하기 좋습니다.",
            "good_count": 3,
            "available_count": 5,
            "mock_data": True,
            "spots": _comparison_demo_spots(),
        }
    )


def night_sky_card_payload(result: NightSkyCheckResponse) -> dict[str, Any]:
    data = result.data
    weather = data.weather or {}
    moon = data.moon or {}
    cloud = weather.get("cloud_cover_percent")
    moon_illumination = moon.get("illumination_percent")
    condition_parts = []
    if cloud is not None:
        condition_parts.append(f"구름량 {cloud}%")
    if moon_illumination is not None:
        condition_parts.append(f"달 밝기 {moon_illumination}%")
    if not condition_parts:
        condition_parts.append("관측 데이터 확인 중")

    grade_titles = {
        "good": "오늘 밤 기상 조건이 좋습니다",
        "fair": "오늘 밤 기상 조건을 확인해보세요",
        "poor": "오늘 밤 기상 조건이 좋지 않습니다",
        "unknown": "오늘 밤 기상 조건을 판단하기 어렵습니다",
    }
    return {
        "type": "night_sky",
        "title": grade_titles.get(data.grade, data.title),
        "summary": data.summary,
        "state": "result_good" if data.grade == "good" else "result_bad",
        "best_time": data.best_time or "추천 시간 확인 불가",
        "condition": " · ".join(condition_parts),
        "score": data.score,
        "grade": data.grade,
        "weather": weather,
        "moon": moon,
        "astronomy": data.astronomy,
        "hourly": data.hourly,
        "score_breakdown": data.score_breakdown,
        "scoring_confidence": data.scoring_confidence,
        "location": data.location,
        "reasons": data.reasons,
        "warnings": data.warnings,
        "detail_url": DETAIL_URL,
    }


def night_sky_comparison_card_payload(result: NightSkySpotComparisonResponse) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for item in result.spots:
        row = {
            "id": item.spot.id,
            "name": item.spot.name,
            "region": item.spot.region,
            "coordinate_status": item.spot.coordinate_status,
            "available": item.available,
            "recommended": item.recommended,
            "error_message": item.error_message,
        }
        if item.data is not None:
            row.update(item.data.model_dump(mode="json"))
        rows.append(row)
    return {
        "type": "night_sky_spot_comparison",
        "state": "comparison_detail",
        "title": "오늘 밤 출사 조건",
        "summary": result.summary,
        "good_count": result.good_count,
        "available_count": result.available_count,
        "checked_at": result.checked_at.isoformat(),
        "mock_data": False,
        "spots": rows,
    }


def _comparison_demo_spots() -> list[dict[str, Any]]:
    rows = [
        ("청옥산 육백마지기", "강원특별자치도 평창군", 70, 12, "22:50 ~ 01:20", True),
        ("영월 접산활공장", "강원특별자치도 영월군", 66, 28, "23:20 ~ 01:00", False),
        ("박달고치전망대", "강원특별자치도 정선군", 70, 5, "22:40 ~ 01:30", False),
        ("도롱이연못", "강원특별자치도 평창군", 49, 45, "00:10 ~ 01:30", False),
        ("만항재", "강원특별자치도 정선군", 63, 20, "23:00 ~ 00:50", False),
    ]
    return [
        {
            "id": f"demo-{index}", "name": name, "region": region,
            "coordinate_status": "ready", "available": True, "recommended": recommended,
            "score": score, "grade": "good" if score >= 70 else "fair" if score >= 50 else "poor",
            "best_time": best_time,
            "weather": {"cloud_cover_percent": cloud, "precipitation_probability_percent": 0, "sunset": "18:30", "sunrise": "06:20"},
            "moon": {"illumination_percent": 18, "moonrise": "08:00", "moonset": "20:30"},
            "hourly": [{"time": hour, "cloud_cover_percent": cloud, "precipitation_probability_percent": 0} for hour in ("20시", "21시", "22시", "23시", "00시", "01시")],
            "warnings": ["데모 데이터입니다. 실제 API 결과가 아닙니다."],
            "reasons": ["UI 비교 패널 확인용 고정 데이터입니다."],
        }
        for index, (name, region, score, cloud, best_time, recommended) in enumerate(rows, start=1)
    ]
def publish_context_card(payload: dict[str, Any]) -> bool:
    """Deliver a local-only JSON card; failures are intentionally non-blocking."""
    try:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            OVERLAY_URL,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urlopen(request, timeout=OVERLAY_TIMEOUT_SECONDS) as response:
            return 200 <= response.status < 300
    except (URLError, TimeoutError, OSError):
        return False
