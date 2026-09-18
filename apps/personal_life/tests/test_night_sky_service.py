import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import unquote_plus

from app.services.night_sky_service import HourlyCondition, NightSkyPolicy, NightSkyResearchService, NightSkySourceError, _night_timeline, is_night_sky_comparison_query, is_night_sky_query


TARGET_DAY = "2026-09-18"


def make_settings(*, use_llm: bool = False):
    return SimpleNamespace(
        default_observation_location="Default Place",
        night_sky_http_timeout_seconds=1.0,
        night_sky_use_llm_summary=use_llm,
        has_openai=use_llm,
        openai_api_key="test-key" if use_llm else None,
        openai_model="test-model",
    )


def weather_payload(*, cloud: int, precipitation: int):
    hours = [
        "2026-09-18T18:00", "2026-09-18T19:00", "2026-09-18T20:00", "2026-09-18T21:00",
        "2026-09-18T22:00", "2026-09-18T23:00", "2026-09-19T00:00", "2026-09-19T01:00",
        "2026-09-19T02:00", "2026-09-19T03:00",
    ]
    return {
        "hourly": {
            "time": hours,
            "cloud_cover": [cloud] * len(hours),
            "precipitation_probability": [precipitation] * len(hours),
            "relative_humidity_2m": [55] * len(hours),
            "wind_speed_10m": [6] * len(hours),
            "temperature_2m": [14] * len(hours),
        },
        "daily": {"sunrise": ["2026-09-18T06:20"], "sunset": ["2026-09-18T18:30"]},
        "current": {"weather_code": 2},
    }


def fetcher_for(*, cloud: int = 5, precipitation: int = 0, fail_weather: bool = False, seen: list[str] | None = None):
    def fetch(url, headers, timeout):
        if seen is not None:
            seen.append(unquote_plus(url))
        if "geocoding-api" in url:
            return {"results": [{"name": "서울", "latitude": 37.5665, "longitude": 126.978, "timezone": "Asia/Seoul"}]}
        if "api.open-meteo.com" in url:
            if fail_weather:
                raise NightSkySourceError("URLError")
            return weather_payload(cloud=cloud, precipitation=precipitation)
        if "/sun?" in url:
            return {"properties": {"sunrise": {"time": "2026-09-18T06:20:00+09:00"}, "sunset": {"time": "2026-09-18T18:30:00+09:00"}}}
        if "/moon?" in url:
            return {"properties": {"moonphase": 15, "moonrise": {"time": "2026-09-18T08:00:00+09:00"}, "moonset": {"time": "2026-09-18T20:30:00+09:00"}}}
        raise AssertionError(url)
    return fetch


def fixed_now(timezone_name: str):
    return datetime(2026, 9, 18, 10, 0, tzinfo=timezone(timedelta(hours=9)))


class NightSkyResearchTests(unittest.TestCase):
    def make_service(self, **kwargs):
        return NightSkyResearchService(settings=make_settings(), now_provider=fixed_now, **kwargs)

    def test_clear_weather_combines_with_locally_calculated_astronomy(self):
        result = self.make_service(fetch_json=fetcher_for()).check("오늘 은하수 찍으러 갈 만해?")

        self.assertTrue(result.success)
        self.assertEqual(result.type, "night_sky_briefing")
        self.assertEqual(result.data.grade, "good")
        self.assertGreater(result.data.score, 70)
        self.assertGreater(result.data.score_breakdown["weather_score"], result.data.score_breakdown["astronomy_score"])
        self.assertEqual(result.data.score_breakdown["overall_score"], result.data.score)
        self.assertEqual(result.data.score_breakdown["data_confidence_percent"], 100)
        self.assertEqual(result.data.scoring_confidence["level"], "complete")
        self.assertFalse(result.data.scoring_confidence["missing"])
        self.assertEqual(result.data.location["name"], "서울")
        self.assertEqual(result.data.weather["cloud_cover_percent"], 5)
        self.assertEqual(result.data.weather["current_weather_code"], 2)
        self.assertIsNotNone(result.data.moon["moonset"])
        self.assertIsNotNone(result.data.weather["astronomical_twilight_end"])
        self.assertIn("galactic_center", result.data.astronomy)
        self.assertTrue(result.data.hourly)
        self.assertEqual(result.data.hourly[0]["time"], "21시")
        self.assertTrue(result.data.actions)

    def test_cloud_and_rain_return_poor_recommendation(self):
        result = self.make_service(fetch_json=fetcher_for(cloud=95, precipitation=85)).check("오늘 밤 별 찍기 괜찮아?")

        self.assertTrue(result.success)
        self.assertEqual(result.data.grade, "poor")
        self.assertLess(result.data.score, 50)
        self.assertIn("추천하지", result.speech)

    def test_weather_score_distinguishes_clear_cloudy_and_rain_risk(self):
        policy = NightSkyPolicy()

        def score(cloud, rain):
            return policy.weather_score(HourlyCondition(
                when=datetime(2026, 9, 18, 22, tzinfo=timezone(timedelta(hours=9))),
                cloud_cover=cloud, precipitation_probability=rain, humidity=55, wind_speed=6, temperature=14,
            ))

        cheongoksan = score(6, 0)
        dorongi = score(22, 0)
        manhangjae = score(26, 35)
        self.assertGreater(cheongoksan, dorongi)
        self.assertGreater(dorongi, manhangjae)

    def test_weather_failure_returns_unknown_without_crashing(self):
        result = self.make_service(fetch_json=fetcher_for(fail_weather=True)).check("오늘 출사 어디로 갈까?")

        self.assertFalse(result.success)
        self.assertEqual(result.data.grade, "unknown")
        self.assertIsNone(result.data.score)
        self.assertEqual(result.data.scoring_confidence["level"], "limited")
        self.assertTrue(any(error.startswith("weather:") for error in result.data.source_errors))

    def test_missing_location_uses_configured_default(self):
        seen = []
        result = self.make_service(fetch_json=fetcher_for(seen=seen)).check("은하수 볼 수 있어?", location=None)

        self.assertTrue(result.success)
        self.assertTrue(any("name=Default Place" in url for url in seen))

    def test_llm_failure_keeps_calculated_result(self):
        def llm_failure(data, settings):
            raise RuntimeError("simulated")

        service = NightSkyResearchService(
            settings=make_settings(use_llm=True),
            fetch_json=fetcher_for(),
            now_provider=fixed_now,
            llm_summarizer=llm_failure,
        )
        result = service.check("오늘 은하수 찍으러 갈 만해?")

        self.assertTrue(result.success)
        self.assertIsNotNone(result.data.score)
        self.assertTrue(any(error == "llm: RuntimeError" for error in result.data.source_errors))

    def test_night_sky_intent_examples(self):
        self.assertTrue(is_night_sky_query("오늘 밤 별 찍기 괜찮아?"))
        self.assertTrue(is_night_sky_query("오늘 출사 어디로 갈까?"))
        self.assertFalse(is_night_sky_query("오늘 일정 알려줘"))

    def test_comparison_intent_examples_are_checked_before_single_location(self):
        self.assertTrue(is_night_sky_comparison_query("규비스, 오늘 은하수 어디가 좋아?"))
        self.assertTrue(is_night_sky_comparison_query("오늘 밤 촬영지는 어디가 제일 괜찮아?"))
        self.assertTrue(is_night_sky_comparison_query("오늘 출사 어디로 갈까?"))
        self.assertTrue(is_night_sky_comparison_query("오늘 은하수 어때?"))
        self.assertTrue(is_night_sky_comparison_query("오늘 은하수 촬영 어때?"))
        self.assertTrue(is_night_sky_comparison_query("오늘 은하수 찍으러 갈 만해?"))

    def test_night_timeline_is_future_first_across_midnight(self):
        timeline = _night_timeline(
            {"time": ["2026-09-19T00:00", "2026-09-18T22:00", "2026-09-19T01:00", "2026-09-18T23:00"], "cloud_cover": [1, 2, 3, 4], "precipitation_probability": [0, 0, 0, 0]},
            "Asia/Seoul",
            start_at=datetime(2026, 9, 18, 21, 30, tzinfo=timezone(timedelta(hours=9))),
        )
        self.assertEqual([item["time"] for item in timeline], ["22시", "23시", "00시", "01시"])

    def test_night_timeline_keeps_one_continuous_night(self):
        times = [
            "2026-09-18T20:00", "2026-09-18T21:00", "2026-09-18T22:00", "2026-09-18T23:00",
            "2026-09-19T00:00", "2026-09-19T01:00", "2026-09-19T02:00", "2026-09-19T03:00",
            "2026-09-19T20:00",
        ]
        timeline = _night_timeline(
            {"time": times, "cloud_cover": [5] * len(times), "precipitation_probability": [0] * len(times)},
            "Asia/Seoul",
            start_at=datetime(2026, 9, 18, 20, 15, tzinfo=timezone(timedelta(hours=9))),
        )
        self.assertEqual([item["time"] for item in timeline], ["20시", "21시", "22시", "23시", "00시", "01시", "02시"])


if __name__ == "__main__":
    unittest.main()
