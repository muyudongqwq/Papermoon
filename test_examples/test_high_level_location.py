import unittest

from game.character.servants import Servant
from game.map.map import (
    HIGH_LEVEL_NAME_SUFFIX,
    Location,
    Map,
    get_area_occupants,
    get_area_positions,
    get_distance,
    is_same_area,
)
from game.map.movement import MovementResolver, MovementState


def create_servant(name):
    return Servant(name, 3, 3, 3, 3, 3, name, "A")


class HighLevelLocationTests(unittest.TestCase):
    def test_high_level_location_is_created_and_registered_with_its_location(self):
        ground = Location("Tower", high_level=True, is_building=True)
        game_map = Map()
        game_map.add_location(ground)
        upper = ground.high_level_location

        self.assertIsNotNone(upper)
        self.assertTrue(upper.is_high_level)
        self.assertIs(upper.area_root, ground)
        self.assertTrue(upper.is_building)
        self.assertIs(
            game_map.locations[f"Tower{HIGH_LEVEL_NAME_SUFFIX}"],
            upper,
        )

    def test_moving_up_and_down_each_costs_one_movement_point(self):
        ground = Location("Tower", high_level=True)
        upper = ground.high_level_location
        actor = create_servant("Assassin")
        actor.position = ground
        actor.movement_point = 2
        resolver = MovementResolver()

        moving_up = MovementState(actor, [ground, upper])
        self.assertTrue(resolver.step(moving_up))
        self.assertIs(actor.position, upper)
        self.assertEqual(moving_up.remaining_movement, 1)

        moving_down = MovementState(actor, [upper, ground])
        self.assertTrue(resolver.step(moving_down))
        self.assertIs(actor.position, ground)
        self.assertEqual(moving_down.remaining_movement, 1)
        self.assertEqual(get_distance(ground, upper), 1)
        self.assertEqual(get_distance(upper, ground), 1)

    def test_location_wide_area_includes_ground_and_high_level_occupants(self):
        ground = Location("Tower", high_level=True)
        upper = ground.high_level_location
        saber = create_servant("Saber")
        archer = create_servant("Archer")
        saber.position = ground
        archer.position = upper

        self.assertTrue(is_same_area(ground, upper))
        self.assertEqual(get_area_positions(upper), [ground, upper])
        self.assertEqual(get_area_occupants(ground), [saber, archer])
        self.assertEqual(upper.get_area_occupants(), [saber, archer])

    def test_locations_without_high_level_keep_existing_behavior(self):
        location = Location("Park")
        game_map = Map()
        game_map.add_location(location)

        self.assertIsNone(location.high_level_location)
        self.assertEqual(location.get_area_positions(), [location])
        self.assertEqual(game_map.locations, {"Park": location})


if __name__ == "__main__":
    unittest.main()
