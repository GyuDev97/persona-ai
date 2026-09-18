import unittest
from unittest.mock import patch

from app.domain.schemas import FavoriteObservationSpotResponse, NightSkyBriefingData, NightSkyCheckResponse, NightSkyComparisonSpotResponse, NightSkySpotComparisonResponse
from app.services.context_overlay_service import (
    check_night_sky_with_overlay,
    night_sky_card_payload,
    night_sky_comparison_card_payload,
    publish_context_card,
)


def sample_result(*, grade="good", score=87):
    return NightSkyCheckResponse(
        success=score is not None,
        speech="오늘 밤 촬영 조건이 좋습니다.",
        data=NightSkyBriefingData(
            title="오늘 밤 은하수 촬영 조건",
            summary="오늘 밤 촬영 조건이 좋습니다.",
            score=score,
            grade=grade,
            best_time="22:40 ~ 00:30",
            location={"name": "서울"},
            weather={"cloud_cover_percent": 12},
            moon={"illumination_percent": 18},
            hourly=[{"time": "22시", "cloud_cover_percent": 12, "precipitation_probability_percent": 0}],
            reasons=[],
            warnings=[],
            actions=[],
        ),
    )


class ContextOverlayServiceTests(unittest.TestCase):
    def test_builds_minimal_card_from_real_night_sky_shape(self):
        card = night_sky_card_payload(sample_result())

        self.assertEqual(card["type"], "night_sky")
        self.assertEqual(card["score"], 87)
        self.assertEqual(card["best_time"], "22:40 ~ 00:30")
        self.assertIn("구름량 12%", card["condition"])
        self.assertIn("달 밝기 18%", card["condition"])
        self.assertEqual(card["hourly"][0]["time"], "22시")
        self.assertEqual(card["score_breakdown"], {})

    def test_comparison_card_marks_actual_data_and_uses_json_safe_times(self):
        result = NightSkySpotComparisonResponse(
            success=True, query="5곳 비교", summary="테스트", good_count=1, available_count=1,
            checked_at="2026-09-18T12:00:00Z",
            spots=[NightSkyComparisonSpotResponse(
                spot=FavoriteObservationSpotResponse(id="spot", name="촬영지", region="테스트", latitude=37.0, longitude=128.0, coordinate_status="ready"),
                available=True, recommended=True, data=sample_result().data,
            )],
        )
        card = night_sky_comparison_card_payload(result)

        self.assertFalse(card["mock_data"])
        self.assertEqual(card["state"], "comparison_detail")
        self.assertTrue(card["spots"][0]["recommended"])
        self.assertEqual(card["spots"][0]["name"], "촬영지")

    @patch("app.services.context_overlay_service.urlopen", side_effect=OSError("not running"))
    def test_missing_overlay_is_non_blocking(self, _urlopen):
        self.assertFalse(publish_context_card({"title": "test"}))

    @patch("app.services.context_overlay_service.publish_night_sky_overlay")
    @patch("app.services.context_overlay_service.check_night_sky")
    def test_actual_research_result_is_published_after_research(self, research, publish):
        result = sample_result()
        research.return_value = result

        returned = check_night_sky_with_overlay("오늘 밤 별 찍기 괜찮아?")

        self.assertIs(returned, result)
        research.assert_called_once_with(query="오늘 밤 별 찍기 괜찮아?", location=None)
        publish.assert_called_once_with(result)

    @patch("app.services.context_overlay_service.publish_night_sky_overlay")
    @patch("app.services.context_overlay_service.check_night_sky")
    @patch("app.services.context_overlay_service.coordinate_required_night_sky_result")
    def test_unconfirmed_favorite_never_uses_place_name_geocoding(self, unavailable, research, publish):
        result = sample_result(grade="unknown", score=None)
        unavailable.return_value = result
        favorite = FavoriteObservationSpotResponse(
            id="manhangjae", name="만항재", region="강원특별자치도 정선군", coordinate_status="requires_confirmation",
        )

        returned = check_night_sky_with_overlay("오늘 만항재 은하수 어때?", location="만항재", favorite_spot=favorite)

        self.assertIs(returned, result)
        unavailable.assert_called_once_with("만항재", "강원특별자치도 정선군")
        research.assert_not_called()
        publish.assert_called_once_with(result)


if __name__ == "__main__":
    unittest.main()
