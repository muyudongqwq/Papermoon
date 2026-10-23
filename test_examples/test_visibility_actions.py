import unittest
from unittest.mock import patch

from game.character.masters import Master
from game.character.servants import Servant
from game.map.map import Location, Map, get_distance, get_nodes_within_distance
from game.map.movement import MovementResolver
from game.turn.Turn import TurnManager
from game.action.action import Action
from game.action.action_list import ActionContext, ActionListBuilder
from game.action.action_resolver import ActionResolver
from game.modifier.modifier import create_modifier


def create_servant(name="Saber", flexibility=3, fortune=3):
    return Servant(
        name=name,
        strength=3,
        endurance=3,
        flexibility=flexibility,
        magic=3,
        fortune=fortune,
        servant_class="Saber" if name == "Saber" else "Archer",
        noble="A",
    )


def create_master(name):
    return Master(
        name=name,
        strength=3,
        endurance=3,
        flexibility=3,
        magic=3,
        fortune=3,
        talent="C",
        command_spell=3,
    )


class VisibilityMapTests(unittest.TestCase):
    def test_visibility_uses_movement_distance(self):
        game_map = Map()
        location_a = Location("A")
        location_b = Location("B")
        road = game_map.add_road(location_a, location_b)

        self.assertEqual(get_distance(location_a, road), 1)
        self.assertEqual(get_distance(location_a, location_b), 2)
        self.assertEqual(get_nodes_within_distance(location_a, 0), {location_a})
        self.assertEqual(
            get_nodes_within_distance(location_a, 2),
            {location_a, road, location_b},
        )

    def test_visibility_zero_only_sees_non_hidden_characters_on_same_node(self):
        building = Location("Building", is_building=True)
        other_location = Location("Outside")
        Map().add_road(building, other_location)
        observer = create_servant("Saber")
        visible_target = create_servant("Archer")
        far_target = create_master("Far Master")
        hidden_target = create_master("Hidden Master")
        characters = [observer, visible_target, far_target, hidden_target]

        observer.position = building
        visible_target.position = building
        hidden_target.position = building
        far_target.position = other_location
        self.assertTrue(Action(hidden_target, "hide", characters=characters).hide())

        observer.update_visibility(characters)

        self.assertIn(visible_target, observer.any_visible)
        self.assertNotIn(hidden_target, observer.any_visible)
        self.assertNotIn(far_target, observer.any_visible)

    def test_turn_end_refreshes_visible_lists(self):
        location = Location("A")
        saber = create_servant("Saber")
        archer = create_servant("Archer")
        saber.position = location
        archer.position = location
        turn_manager = TurnManager()
        turn_manager.characters = [saber, archer]
        create_master("Saber Master").add_servant(saber)
        create_master("Archer Master").add_servant(archer)

        turn_manager.end_turn()

        self.assertEqual(saber.any_visible, [archer])
        self.assertEqual(archer.any_visible, [saber])


class GeneralActionTests(unittest.TestCase):
    def test_investigate_reveals_status_and_all_nearest_ties_by_type(self):
        game_map = Map()
        origin = Location("Origin")
        master_left_location = Location("Master Left")
        master_right_location = Location("Master Right")
        servant_location = Location("Servant")
        for location in (
            origin,
            master_left_location,
            master_right_location,
            servant_location,
        ):
            game_map.add_location(location)

        game_map.add_road(origin, master_left_location, master_right_location)
        game_map.add_road(master_left_location, servant_location)
        origin.add_status("workshop")

        actor = create_servant("Saber")
        master_left = create_master("Master Left")
        master_right = create_master("Master Right")
        other_servant = create_servant("Archer")
        characters = [actor, master_left, master_right, other_servant]
        actor.position = origin
        master_left.position = master_left_location
        master_right.position = master_right_location
        other_servant.position = servant_location

        result = Action(
            actor,
            "investigate",
            characters=characters,
        ).investigate()

        self.assertEqual(result["statuses"], {"workshop"})
        self.assertEqual(result["masters"], [master_left, master_right])
        self.assertEqual(result["servants"], [other_servant])
        self.assertEqual(actor.action_point, 1)
        self.assertEqual(actor.investigated_statuses[origin], {"workshop"})
        self.assertEqual(actor.revealed_positions[master_left], master_left_location)
        self.assertEqual(actor.revealed_positions[other_servant], servant_location)

    def test_cannot_investigate_blocks_listing_and_direct_execution(self):
        actor = create_servant()
        actor.position = Location("Library")
        actor.add_modifier(create_modifier(
            {
                "modifier_id": "cannot_investigate",
                "effect_type": "add_status",
                "effect_data": {"status_id": "cannot_investigate"},
            },
            actor,
        ))
        context = ActionContext(
            actor=actor,
            phase="AP1",
            characters=[actor],
        )
        investigate = next(
            entry
            for entry in ActionListBuilder().get_action_entries(context)
            if entry.action_id == "investigate"
        )

        self.assertFalse(investigate.available)
        self.assertIn("forbidden_status", investigate.unavailable_reasons)
        starting_ap = actor.action_point
        self.assertFalse(Action(actor, "investigate", characters=[actor]).investigate())
        self.assertEqual(actor.action_point, starting_ap)

    def test_visibility_bonus_expands_real_visibility(self):
        nodes = [Location(str(index)) for index in range(3)]
        for left, right in zip(nodes, nodes[1:]):
            left.add_connection(right)
            right.add_connection(left)
        actor = create_servant("Saber")
        target = create_servant("Archer")
        actor.position = nodes[0]
        target.position = nodes[2]
        actor.add_modifier(create_modifier(
            {
                "effect_type": "visibility_bonus",
                "effect_data": {"value": 2},
            },
            actor,
        ))

        actor.update_visibility([actor, target])

        self.assertIn(target, actor.own_visible)

    def test_investigate_reveals_nearest_normally_hidden_character(self):
        origin = Location("Origin")
        near = Location("Near", is_building=True)
        far = Location("Far")
        origin.add_connection(near)
        near.add_connection(origin)
        near.add_connection(far)
        far.add_connection(near)

        actor = create_servant("Saber")
        hidden_target = create_servant("Archer")
        visible_target = create_servant("Archer")
        actor.position = origin
        hidden_target.position = near
        visible_target.position = far
        hidden_target.status_flags.add("hidden")

        result = Action(
            actor,
            "investigate",
            characters=[actor, hidden_target, visible_target],
        ).investigate()

        self.assertEqual(result["servants"], [hidden_target])
        self.assertIn(hidden_target, result["positions"])
        self.assertIn(hidden_target, actor.revealed_positions)
        self.assertNotIn(hidden_target, actor.perceived)
        self.assertNotIn(hidden_target, actor.any_visible)

    def test_hide_requires_building_and_breaks_immediately_on_leaving(self):
        building = Location("Building", is_building=True)
        outside = Location("Outside")
        road = Map().add_road(building, outside)
        actor = create_servant("Saber")
        actor.position = outside

        self.assertFalse(Action(actor, "hide", characters=[actor]).hide())
        self.assertEqual(actor.action_point, 2)

        actor.position = building
        self.assertTrue(Action(actor, "hide", characters=[actor]).hide())
        self.assertEqual(actor.action_point, 1)
        self.assertTrue(actor.has_status("hidden"))

        actor.position = road

        self.assertFalse(actor.has_status("hidden"))
        self.assertNotIn(actor, building.occupants)
        self.assertIn(actor, road.occupants)

    def test_perceive_adds_successes_and_removes_them_beyond_range_five(self):
        game_map = Map()
        location_a = Location("A")
        location_b = Location("B")
        location_c = Location("C", is_building=True)
        location_d = Location("D")
        game_map.add_road(location_a, location_b)
        game_map.add_road(location_b, location_c)
        game_map.add_road(location_c, location_d)

        actor = create_servant("Saber")
        hidden_target = create_servant("Archer")
        actor.position = location_a
        hidden_target.position = location_c
        actor.perceive = 10
        hidden_target.hide = 5
        characters = [actor, hidden_target]
        Action(hidden_target, "hide", characters=characters).hide()

        with patch("game.action.action.random.randint", side_effect=[5, 4]):
            result = Action(
                actor,
                "perceive",
                characters=characters,
            ).perceive()

        self.assertEqual(result["detected"], [hidden_target])
        self.assertEqual(actor.action_point, 1)
        self.assertIn(hidden_target, actor.own_perceived)
        self.assertIn(hidden_target, actor.perceived)
        self.assertNotIn(hidden_target, actor.own_visible)
        self.assertIn(hidden_target, actor.any_visible)
        self.assertFalse(hasattr(actor, "visible"))

        hidden_target.position = location_d
        actor.update_visibility(characters)

        self.assertNotIn(hidden_target, actor.perceived)
        self.assertNotIn(hidden_target, actor.any_visible)

    def test_perceived_target_without_real_visibility_cannot_be_attacked(self):
        location = Location("A")
        actor = create_servant("Saber")
        target = create_servant("Archer")
        actor.position = target.position = location
        actor.own_perceived = [target]
        actor.perceived = [target]
        actor.own_visible = []
        actor.any_visible = [target]

        self.assertFalse(
            Action(
                actor,
                "attack",
                target,
                ignore_attack_phase_count=True,
            ).attack()
        )
        self.assertFalse(Action(actor, "direct_attack", target).direct_attack())

    def test_all_three_actions_are_unavailable_in_battle(self):
        building = Location("Building", is_building=True)
        actor = create_servant("Saber")
        actor.position = building
        actor.in_battle = True
        characters = [actor]

        self.assertFalse(Action(actor, "investigate", characters=characters).investigate())
        self.assertFalse(Action(actor, "hide", characters=characters).hide())
        self.assertFalse(Action(actor, "perceive", characters=characters).perceive())
        self.assertEqual(actor.action_point, 2)

    def test_new_map_actions_require_one_action_point(self):
        building = Location("Building", is_building=True)
        actor = create_servant("Saber")
        actor.position = building
        actor.action_point = 0
        characters = [actor]

        self.assertFalse(Action(actor, "investigate", characters=characters).investigate())
        self.assertFalse(Action(actor, "hide", characters=characters).hide())
        self.assertFalse(Action(actor, "perceive", characters=characters).perceive())
        self.assertFalse(actor.has_status("hidden"))

    def test_action_resolver_dispatches_the_new_actions(self):
        building = Location("Building", is_building=True)
        actor = create_servant("Saber")
        actor.position = building

        result = ActionResolver().resolve(
            Action(actor, "hide", characters=[actor])
        )

        self.assertTrue(result)
        self.assertTrue(actor.has_status("hidden"))


class EncounterVisibilityTests(unittest.TestCase):
    def test_perception_grants_any_visibility_for_encounter(self):
        building = Location("Building", is_building=True)
        observer = create_servant("Saber")
        hidden_target = create_servant("Archer")
        observer.position = building
        hidden_target.position = building
        observer.perceive = 10
        hidden_target.hide = 5
        characters = [observer, hidden_target]
        resolver = MovementResolver()
        Action(hidden_target, "hide", characters=characters).hide()

        encounters = resolver.check_encounter(characters, [])

        self.assertEqual(len(encounters), 1)
        encounter = encounters[0]
        self.assertEqual(encounter.aware_characters, [hidden_target])
        self.assertFalse(encounter.choose_battle(observer))

        with patch("game.action.action.random.randint", side_effect=[5, 4]):
            Action(observer, "perceive", characters=characters).perceive()

        encounters = resolver.check_encounter(characters, [])

        self.assertEqual(len(encounters), 1)
        self.assertEqual(
            set(encounters[0].characters),
            {hidden_target, observer},
        )
        self.assertEqual(
            set(encounters[0].aware_characters),
            {hidden_target, observer},
        )
        self.assertIn(hidden_target, observer.perceived)
        self.assertIn(hidden_target, observer.any_visible)


if __name__ == "__main__":
    unittest.main()
