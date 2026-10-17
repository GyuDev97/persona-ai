import unittest

from app.domain.schemas import FavoriteObservationSpotResponse, NightSkyBriefingData, NightSkyCheckResponse
from app.services.night_sky_comparison_service import NightSkyComparisonService


def spot(identifier: str, *, latitude=37.0, longitude=128.0):
    return FavoriteObservationSpotResponse(
        id=identifier,
        name=identifier,
        region="테스트 지역",
        latitude=latitude,
        longitude=longitude,
        coordinate_status="ready",
    )


def result_for(name: str, score: int):
    return NightSkyCheckResponse(
        success=True,
        speech=name,
        data=NightSkyBriefingData(
            title="테스트", summary=name, score=score, grade="fair", best_time="22:00 ~ 23:00",
            location={"name": name}, weather={}, moon={}, hourly=[], reasons=[], warnings=[], actions=[],
        ),
    )


class FakeResearch:
    def check_observation(self, query, observation):
        if observation.name == "failure":
            raise RuntimeError("per-row failure")
        return result_for(observation.name, {"low": 54, "high": 70}.get(observation.name, 63))


class NightSkyComparisonServiceTests(unittest.TestCase):
    def test_rows_sort_by_score_and_one_failure_does_not_cancel_others(self):
        service = NightSkyComparisonService(
            spots=[spot("low"), spot("failure"), spot("high")],
            research_factory=FakeResearch,
        )

        comparison = service.check("오늘 은하수 어디가 좋아?")

        self.assertTrue(comparison.success)
        self.assertEqual([row.spot.name for row in comparison.spots], ["high", "low", "failure"])
        self.assertTrue(comparison.spots[0].recommended)
        self.assertFalse(comparison.spots[-1].available)
        self.assertEqual(comparison.available_count, 2)

    def test_missing_coordinates_never_start_live_research(self):
        pending = FavoriteObservationSpotResponse(
            id="pending", name="pending", region="테스트 지역", coordinate_status="requires_confirmation",
        )
        comparison = NightSkyComparisonService(spots=[pending], research_factory=lambda: (_ for _ in ()).throw(AssertionError())).check("5곳 비교")

        self.assertFalse(comparison.success)
        self.assertEqual(comparison.spots[0].error_message, "촬영 지점 좌표 확인 필요")

    def test_same_score_preserves_the_configured_spot_order(self):
        service = NightSkyComparisonService(spots=[spot("first"), spot("second")], research_factory=FakeResearch)

        comparison = service.check("5곳 비교")

        self.assertEqual([row.spot.id for row in comparison.spots], ["first", "second"])


if __name__ == "__main__":
    unittest.main()
