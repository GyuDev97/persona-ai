import unittest

from app.services.favorite_observation_spot_service import find_favorite_observation_spot, list_favorite_observation_spots


class FavoriteObservationSpotServiceTests(unittest.TestCase):
    def test_coordinate_readiness_comes_only_from_configured_coordinate_pairs(self):
        spots = list_favorite_observation_spots()

        self.assertEqual(
            [spot.name for spot in spots],
            ["청옥산 육백마지기", "영월 접산활공장", "박달고치전망대", "도롱이연못", "만항재"],
        )
        for spot in spots:
            has_coordinates = spot.latitude is not None and spot.longitude is not None
            self.assertEqual(spot.coordinate_status == "ready", has_coordinates)

    def test_only_an_explicit_favorite_name_selects_a_single_spot(self):
        spot = find_favorite_observation_spot("오늘 만항재 은하수 어때?")

        self.assertIsNotNone(spot)
        self.assertEqual(spot.name, "만항재")
        self.assertIsNone(find_favorite_observation_spot("오늘 은하수 촬영 어때?"))


if __name__ == "__main__":
    unittest.main()
