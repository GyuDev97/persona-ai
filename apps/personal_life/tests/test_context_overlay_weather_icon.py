import unittest

from desktop_context_overlay import _condition_status, _weather_icon, _wrap_overlay_text


class ContextOverlayWeatherIconTests(unittest.TestCase):
    def test_wmo_codes_map_to_clear_cloud_rain_and_snow_icons(self):
        self.assertEqual(_weather_icon({"current_weather_code": 0}), "☀")
        self.assertEqual(_weather_icon({"current_weather_code": 3}), "☁")
        self.assertEqual(_weather_icon({"current_weather_code": 61}), "☂")
        self.assertEqual(_weather_icon({"current_weather_code": 71}), "❄")

    def test_missing_current_code_falls_back_to_real_forecast_conditions(self):
        self.assertEqual(_weather_icon({"cloud_cover_percent": 10, "precipitation_probability_percent": 0}), "☀")
        self.assertEqual(_weather_icon({"cloud_cover_percent": 80, "precipitation_probability_percent": 70}), "☂")

    def test_long_judgement_copy_wraps_within_the_detail_column(self):
        lines = _wrap_overlay_text("천문박명, 은하수 가시시간 미계산 상태라 촬영 적합도에 신뢰도 제한이 적용됩니다.", 20)

        self.assertGreater(len(lines), 1)
        self.assertTrue(all(len(line) <= 20 for line in lines))

    def test_weather_status_uses_weather_score_not_missing_overall_score(self):
        label, color = _condition_status({"score_breakdown": {"weather_score": 86, "overall_score": None}})

        self.assertEqual(label, "매우 좋음")
        self.assertNotEqual(color, "#455361")


if __name__ == "__main__":
    unittest.main()
