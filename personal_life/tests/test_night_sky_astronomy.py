import unittest
from datetime import date, datetime, timedelta, timezone

from app.services.night_sky_astronomy import calculate_astronomy, load_scoring_config, moon_impact
from app.services.night_sky_service import HourlyCondition, IntegratedHour, _astronomy_score, _select_recommended_window


SEOUL = timezone(timedelta(hours=9))


def integrated(at, *, cloud=10, rain=0, weather_score=90, astronomy_score=80, moon="low", gc=15, dark=True):
    return IntegratedHour(
        condition=HourlyCondition(at, cloud, rain, 55, 4, 12),
        weather_score=weather_score,
        astronomy_hour_score=astronomy_score,
        hour_score=round(weather_score * 0.55 + astronomy_score * 0.45),
        moon_altitude_degrees=-4 if moon == "low" else 15,
        moon_azimuth_degrees=180,
        moon_impact=moon,
        galactic_center_altitude_degrees=gc,
        astronomical_dark=dark,
    )


class NightSkyAstronomyTests(unittest.TestCase):
    def setUp(self):
        self.config = load_scoring_config()

    def test_coordinate_based_twilight_moon_and_gc_values_are_local(self):
        hours = [datetime(2026, 9, 18, 20, tzinfo=SEOUL) + timedelta(hours=index) for index in range(8)]
        result = calculate_astronomy(
            latitude=37.3746488547,
            longitude=128.4905563972,
            timezone_name="Asia/Seoul",
            target_day=date(2026, 9, 18),
            hourly_times=hours,
            config=self.config,
        )

        self.assertLess(result["sun"]["astronomical_twilight_end"], result["sun"]["astronomical_twilight_start"])
        self.assertIsNotNone(result["moon"]["moonset"])
        self.assertIsNotNone(result["moon"]["illumination_percent"])
        self.assertIsNotNone(result["galactic_center"]["max_altitude_degrees"])
        self.assertEqual([row["at"] for row in result["hourly"]], sorted(row["at"] for row in result["hourly"]))

    def test_moon_impact_accounts_for_altitude_and_illumination(self):
        self.assertEqual(moon_impact(90, -1, self.config), "low")
        self.assertEqual(moon_impact(15, 40, self.config), "low")
        self.assertEqual(moon_impact(40, 4, self.config), "medium")
        self.assertEqual(moon_impact(80, 35, self.config), "high")

    def test_recommendation_uses_continuous_cross_midnight_intersection(self):
        rows = [
            integrated(datetime(2026, 9, 18, 22, tzinfo=SEOUL), moon="high"),
            integrated(datetime(2026, 9, 18, 23, tzinfo=SEOUL)),
            integrated(datetime(2026, 9, 19, 0, tzinfo=SEOUL)),
            integrated(datetime(2026, 9, 19, 1, tzinfo=SEOUL)),
        ]
        window = _select_recommended_window(rows, date(2026, 9, 18), datetime(2026, 9, 18, 21, tzinfo=SEOUL), "Asia/Seoul", self.config)

        self.assertIsNotNone(window)
        self.assertEqual(window.start.hour, 23)
        self.assertEqual(window.end.hour, 2)

    def test_good_weather_without_visible_gc_has_no_recommendation(self):
        rows = [integrated(datetime(2026, 9, 18, 23, tzinfo=SEOUL), gc=4)]

        self.assertIsNone(_select_recommended_window(rows, date(2026, 9, 18), datetime(2026, 9, 18, 21, tzinfo=SEOUL), "Asia/Seoul", self.config))
        self.assertEqual(_astronomy_score(rows, self.config), 0)

    def test_good_astronomy_with_heavy_cloud_is_not_recommended(self):
        rows = [integrated(datetime(2026, 9, 18, 23, tzinfo=SEOUL), cloud=70)]

        self.assertIsNone(_select_recommended_window(rows, date(2026, 9, 18), datetime(2026, 9, 18, 21, tzinfo=SEOUL), "Asia/Seoul", self.config))


if __name__ == "__main__":
    unittest.main()
