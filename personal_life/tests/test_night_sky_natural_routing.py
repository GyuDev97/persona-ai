import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.domain.schemas import (
    FavoriteObservationSpotResponse,
    NaturalCommandCreate,
    NightSkyBriefingData,
    NightSkyCheckResponse,
    NightSkySpotComparisonResponse,
)
from app.services.natural_language_service import process_natural_command


def comparison_response():
    return NightSkySpotComparisonResponse(
        success=False, checked_at=datetime.now(timezone.utc), query="오늘 은하수 어때?",
        summary="촬영지 좌표를 확인한 뒤 5곳의 실제 기상과 달 조건을 비교할 수 있습니다.",
        good_count=0, available_count=0, spots=[],
    )


def single_response():
    return NightSkyCheckResponse(
        success=True, speech="만항재 결과",
        data=NightSkyBriefingData(
            title="오늘 밤 은하수 촬영 조건", summary="만항재 결과", score=60, grade="fair",
            best_time="22:00 ~ 23:00", location={"name": "만항재"}, weather={}, moon={}, hourly=[],
            reasons=[], warnings=[], actions=[],
        ),
    )


class NightSkyNaturalRoutingTests(unittest.TestCase):
    @patch("app.services.natural_language_service.log_conversation")
    @patch("app.services.natural_language_service.get_settings")
    @patch("app.services.natural_language_service.check_night_sky_with_overlay")
    @patch("app.services.natural_language_service.check_night_sky_comparison_with_overlay")
    def test_unqualified_night_sky_question_uses_comparison_not_default_location(self, compare, single, _settings, _log):
        compare.return_value = comparison_response()

        response = process_natural_command(NaturalCommandCreate(text="오늘 은하수 찍으러 갈 만해?"))

        self.assertEqual(response.interpreted_as, "night_sky_comparison")
        compare.assert_called_once()
        single.assert_not_called()

    @patch("app.services.natural_language_service.log_conversation")
    @patch("app.services.natural_language_service.get_settings")
    @patch("app.services.natural_language_service.check_night_sky_with_overlay")
    @patch("app.services.natural_language_service.check_night_sky_comparison_with_overlay")
    def test_explicit_favorite_uses_its_single_location_detail(self, compare, single, _settings, _log):
        single.return_value = single_response()

        response = process_natural_command(NaturalCommandCreate(text="오늘 만항재 은하수 어때?"))

        self.assertEqual(response.interpreted_as, "night_sky")
        compare.assert_not_called()
        kwargs = single.call_args.kwargs
        self.assertEqual(kwargs["location"], "만항재")
        self.assertEqual(kwargs["favorite_spot"].region, "강원특별자치도 정선군")


if __name__ == "__main__":
    unittest.main()
