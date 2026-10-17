"""Parallel, failure-isolated comparison for confirmed favorite locations."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Callable

from ..domain.schemas import (
    FavoriteObservationSpotResponse,
    NightSkyComparisonSpotResponse,
    NightSkySpotComparisonResponse,
)
from .favorite_observation_spot_service import list_favorite_observation_spots
from .night_sky_service import NightSkyResearchService, ObservationLocation


class NightSkyComparisonService:
    def __init__(
        self,
        *,
        spots: list[FavoriteObservationSpotResponse] | None = None,
        research_factory: Callable[[], NightSkyResearchService] = NightSkyResearchService,
    ) -> None:
        self.spots = spots
        self.research_factory = research_factory

    def check(self, query: str) -> NightSkySpotComparisonResponse:
        configured_spots = self.spots if self.spots is not None else list_favorite_observation_spots()
        configured_order = {spot.id: index for index, spot in enumerate(configured_spots)}
        results: list[NightSkyComparisonSpotResponse] = []
        ready_spots = [spot for spot in configured_spots if spot.coordinate_status == "ready"]
        for spot in configured_spots:
            if spot.coordinate_status != "ready":
                results.append(
                    NightSkyComparisonSpotResponse(
                        spot=spot,
                        available=False,
                        error_message="촬영 지점 좌표 확인 필요",
                    )
                )

        # A source failure must only affect the row being fetched.  Five calls
        # run independently so one slow place does not make a comparison wait
        # for the other locations unnecessarily.
        with ThreadPoolExecutor(max_workers=max(1, min(5, len(ready_spots)))) as executor:
            futures = {executor.submit(self._check_one, query, spot): spot for spot in ready_spots}
            for future in as_completed(futures):
                spot = futures[future]
                try:
                    results.append(future.result())
                except Exception:
                    results.append(
                        NightSkyComparisonSpotResponse(
                            spot=spot,
                            available=False,
                            error_message="해당 촬영지 데이터를 확인하지 못했습니다.",
                        )
                    )

        results.sort(key=lambda item: _sort_key(item, configured_order))
        for index, item in enumerate(results):
            # The top usable row is a weather-based recommendation.  It does
            # not imply that the uncalculated astronomy inputs are confirmed.
            item.recommended = index == 0 and item.available and item.data is not None and item.data.score is not None

        available = [item for item in results if item.available and item.data and item.data.score is not None]
        good_count = sum(1 for item in available if item.data and item.data.score >= 70)
        best = available[0] if available else None
        recommended = [item for item in available if item.data and item.data.score >= 70][:2]
        if best and best.data:
            weather = best.data.weather
            moon_impact = str(best.data.moon.get("impact") or "unknown")
            if moon_impact == "high":
                detail = "기상 조건은 좋지만 추천 시간에는 달빛 영향이 커질 수 있습니다."
            else:
                detail = f"{best.data.best_time or '추천 시간'}에는 하늘이 충분히 어둡고 은하수 중심부 고도와 구름 상태가 가장 좋습니다."
            if len(recommended) >= 2 and recommended[1].data:
                second = recommended[1]
                summary = f"오늘은 {best.spot.name} 조건이 가장 좋습니다. {detail} {second.spot.name}은 {second.data.best_time or '추천 시간'}에 조건이 좋아집니다."
            else:
                summary = f"오늘은 {best.spot.name} 조건이 가장 좋습니다. {detail}"
        elif configured_spots:
            summary = "촬영지 좌표를 확인한 뒤 5곳의 실제 기상과 달 조건을 비교할 수 있습니다."
        else:
            summary = "비교할 촬영지가 설정되어 있지 않습니다."

        return NightSkySpotComparisonResponse(
            success=bool(available),
            checked_at=datetime.now(timezone.utc),
            query=query,
            summary=summary,
            good_count=good_count,
            available_count=len(available),
            spots=results,
        )

    def _check_one(self, query: str, spot: FavoriteObservationSpotResponse) -> NightSkyComparisonSpotResponse:
        if spot.latitude is None or spot.longitude is None:
            return NightSkyComparisonSpotResponse(spot=spot, available=False, error_message="촬영 지점 좌표 확인 필요")
        result = self.research_factory().check_observation(
            query=query,
            observation=ObservationLocation(
                name=spot.name,
                latitude=spot.latitude,
                longitude=spot.longitude,
                timezone=spot.timezone,
            ),
        )
        return NightSkyComparisonSpotResponse(
            spot=spot,
            available=result.success,
            data=result.data,
            error_message=None if result.success else "해당 촬영지 데이터를 확인하지 못했습니다.",
        )


def check_night_sky_comparison(query: str) -> NightSkySpotComparisonResponse:
    return NightSkyComparisonService().check(query)


def _sort_key(item: NightSkyComparisonSpotResponse, configured_order: dict[str, int]) -> tuple[int, int, int]:
    score = item.data.score if item.available and item.data and item.data.score is not None else -1
    return (-score, 0 if item.available else 1, configured_order.get(item.spot.id, 99))
