import unittest

from game.action.action import Action
from game.character.masters import Master
from game.game.game_manager import GameManager
from game.map.map import Location, Map


def master(name):
    return Master(name, 3, 3, 3, 3, 3, "C", 3)


class BoatTransportTests(unittest.TestCase):
    def create_game(self, characters):
        origin = Location("出发码头", is_port=True)
        destination = Location("目的码头", is_port=True)
        game_map = Map()
        game_map.add_location(origin)
        game_map.add_location(destination)
        for character in characters:
            character.position = origin
        game = GameManager(characters, origin)
        game.game_map = game_map
        game.start_game()
        game.turn_manager.start_turn()
        return game, origin, destination

    def test_boarding_uses_all_ap_and_arrives_after_ap2(self):
        actor = master("乘客")
        game, origin, destination = self.create_game([actor])
        action = Action(actor, "board_boat", target=destination)
        game.turn_manager.add_action(action, ap_layer=1)

        game.turn_manager.execute_action_layer(1)
        boat = actor.position
        self.assertTrue(boat.is_boat)
        self.assertEqual(boat.origin, origin)
        self.assertEqual(actor.action_point, 0)
        self.assertEqual(game.turn_manager.current_ap_layer, 2)

        game.turn_manager.execute_action_layer(2)
        self.assertIs(actor.position, destination)
        self.assertEqual(game.boat_manager.active_boats, [])

    def test_same_route_same_turn_reuses_boat_and_different_route_does_not(self):
        first, second = master("A"), master("B")
        game, origin, destination = self.create_game([first, second])
        third_port = Location("第三码头", is_port=True)
        game.game_map.add_location(third_port)

        first_boat = game.boat_manager.get_or_create(origin, destination, 1)
        same_boat = game.boat_manager.get_or_create(origin, destination, 1)
        other_boat = game.boat_manager.get_or_create(origin, third_port, 1)
        self.assertIs(first_boat, same_boat)
        self.assertIsNot(first_boat, other_boat)
        self.assertEqual(first_boat.name, "boat_0")
        self.assertEqual(other_boat.name, "boat_1")

    def test_boat_is_removed_when_teleport_takes_last_passenger(self):
        actor = master("乘客")
        game, origin, destination = self.create_game([actor])
        boat = game.boat_manager.get_or_create(origin, destination, 1)
        actor.position = boat
        self.assertIn(boat, game.boat_manager.active_boats)
        actor.position = origin
        self.assertNotIn(boat, game.boat_manager.active_boats)

    def test_teleport_off_boat_cancels_only_that_passengers_arrival(self):
        first, second = master("A"), master("B")
        game, origin, destination = self.create_game([first, second])
        boat = game.boat_manager.get_or_create(origin, destination, 1)
        first.position = boat
        second.position = boat

        first.position = origin
        game.boat_manager.arrive_all(1)
        self.assertIs(first.position, origin)
        self.assertIs(second.position, destination)

    def test_boat_location_is_not_a_valid_engine_map_target(self):
        actor = master("乘客")
        game, origin, destination = self.create_game([actor])
        boat = game.boat_manager.get_or_create(origin, destination, 1)
        actor.position = boat
        self.assertNotIn(boat, game.get_map_nodes(merge_area_levels=False))
        self.assertNotIn(boat, actor.seen_locations)

    def test_same_boat_encounter_is_resolved_before_ap1_checkpoint(self):
        first, second = master("A"), master("B")
        game, _, destination = self.create_game([first, second])
        for actor in (first, second):
            game.turn_manager.add_action(
                Action(actor, "board_boat", target=destination),
                ap_layer=1,
            )

        waiting = game.turn_manager.execute_action_layer(1)
        self.assertEqual(waiting["status"], "waiting_for_encounter")
        self.assertIs(first.position, second.position)
        self.assertTrue(first.position.is_boat)
        encounter = waiting["encounters"][0]
        for actor in list(encounter.aware_characters):
            encounter.choose_continue(actor)
        game.turn_manager.resume_action_layer()
        self.assertEqual(game.turn_manager.current_ap_layer, 2)

        result = game.turn_manager.execute_action_layer(2)
        self.assertIsInstance(result, list)
        self.assertIs(first.position, destination)
        self.assertIs(second.position, destination)


if __name__ == "__main__":
    unittest.main()
