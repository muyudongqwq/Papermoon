import unittest

from game.map.map import Location, Map, Road


class RoadJunctionTests(unittest.TestCase):
    def test_map_can_create_a_three_way_road(self):
        game_map = Map()
        location_a = Location("A")
        location_b = Location("B")
        location_c = Location("C")

        for location in (location_a, location_b, location_c):
            game_map.add_location(location)

        road = game_map.add_road(location_a, location_b, location_c)

        self.assertEqual(road.connected_locations, [location_a, location_b, location_c])
        self.assertEqual(road.name, "道路:A-B-C")
        self.assertTrue(road.connects(location_a, location_c))
        self.assertTrue(road.connects(location_a, location_b, location_c))
        self.assertIn(road, location_a.connected_locations)
        self.assertIn(road, location_b.connected_locations)
        self.assertIn(road, location_c.connected_locations)

    def test_reordered_connections_do_not_create_a_duplicate(self):
        game_map = Map()
        location_a = Location("A")
        location_b = Location("B")
        location_c = Location("C")

        first = game_map.add_road(location_a, location_b, location_c)
        second = game_map.add_road(location_c, location_a, location_b)

        self.assertIs(first, second)
        self.assertEqual(len(game_map.roads), 1)

    def test_existing_road_can_gain_a_third_connection(self):
        location_a = Location("A")
        location_b = Location("B")
        location_c = Location("C")
        road = Road(location_a, location_b)

        self.assertTrue(road.add_connection(location_c))
        self.assertEqual(road.name, "道路:A-B-C")
        self.assertIn(road, location_c.connected_locations)

    def test_two_location_road_remains_supported(self):
        game_map = Map()
        location_a = Location("A")
        location_b = Location("B")

        road = game_map.add_road(location_a, location_b)

        self.assertTrue(game_map.has_road(location_a, location_b))
        self.assertEqual(road.location1, location_a)
        self.assertEqual(road.location2, location_b)


if __name__ == "__main__":
    unittest.main()
