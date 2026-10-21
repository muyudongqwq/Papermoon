import unittest

from game.action.action_list import ActionContext, ActionListBuilder
from game.action.action import Action
from game.character.masters import Master
from game.character.servants import Servant
from game.game_manager import GameManager
from game.map.map import Location, Map
from game.map.movement import MovementResolver, MovementState


def make_master(name):
    return Master(name, 3, 3, 3, 4, 3, "C", 3)


def make_servant(name, servant_class="Saber"):
    return Servant(name, 3, 3, 3, 3, 3, servant_class, "C")


class InsightWorkshopMagicTests(unittest.TestCase):
    def setUp(self):
        self.game_map = Map()
        self.a = Location("A", is_building=True)
        self.b = Location("B", high_level=True, is_building=True)
        self.c = Location("C", is_building=True)
        for location in (self.a, self.b, self.c):
            self.game_map.add_location(location)
        self.ab = self.game_map.add_road(self.a, self.b)
        self.bc = self.game_map.add_road(self.b, self.c)

        self.caster = make_master("Caster")
        self.servant = make_servant("Scout", "Archer")
        self.target = make_servant("Hidden", "Assassin")
        self.other = make_master("Other")
        self.caster.add_servant(self.servant)
        self.caster.position = self.a
        self.servant.position = self.a
        self.target.position = self.b.high_level_location
        self.other.position = self.c
        self.game = GameManager(
            [self.caster, self.servant, self.target, self.other],
            self.a,
        )
        self.game.game_map = self.game_map
        self.game.start_game()
        self.game.turn_manager.turn = 1
        self.game.turn_manager.current_ap_layer = 1
        for character in self.game.characters:
            character.current_global_turn = 1

    def test_basic_magics_are_loadable_and_have_correct_ap_phases(self):
        insight = self.caster.load_basic_magic("insight")
        workshop = self.caster.load_basic_magic("workshop")
        builder = ActionListBuilder()

        ap1 = builder.get_available_actions(ActionContext(
            actor=self.caster,
            phase="AP1",
            turn_number=1,
            turn_manager=self.game.turn_manager,
        ))
        ap2 = builder.get_available_actions(ActionContext(
            actor=self.caster,
            phase="AP2",
            turn_number=1,
            turn_manager=self.game.turn_manager,
        ))
        self.assertIn(
            f"skill:{insight.skill_id}:observe",
            [entry.action_id for entry in ap1],
        )
        self.assertIn(
            f"skill:{workshop.skill_id}:establish",
            [entry.action_id for entry in ap1],
        )
        self.assertIn(
            f"skill:{insight.skill_id}:observe",
            [entry.action_id for entry in ap2],
        )
        self.assertNotIn(
            f"skill:{workshop.skill_id}:establish",
            [entry.action_id for entry in ap2],
        )

    def test_insight_ignores_hidden_shares_vision_and_records_first_step(self):
        insight = self.caster.load_basic_magic("insight")
        self.target.status_flags.add("hidden")
        result = self.caster.resolve_skill_component(
            insight.skill_id,
            "observe",
            target=self.b,
            phase="AP1—洞悉",
            ap_layer=1,
            turn_number=1,
        )
        self.assertIn(self.target, result["results"][0]["occupants"])
        self.assertIn(self.target, self.caster.own_visible)
        self.assertIn(self.target, self.servant.shared_visible)
        self.assertIn(self.b, self.caster.seen_locations)
        self.assertIn(self.b.high_level_location, self.servant.seen_locations)

        self.target.movement_point = 1
        state = MovementState(
            self.target,
            [self.b.high_level_location, self.b, self.ab],
        )
        state.remaining_movement = 2
        resolver = MovementResolver()
        self.assertTrue(resolver.step(state))  # 高低层属于同一观测区域。
        self.assertFalse(any(
            report["type"] == "insight_first_step"
            for report in self.caster.insight_reports
        ))
        self.assertTrue(resolver.step(state))
        reports = [
            report
            for report in self.caster.insight_reports
            if report["type"] == "insight_first_step"
        ]
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["class_name"], "Assassin")
        self.assertIs(reports[0]["destination"], self.ab)
        self.assertIn(reports[0], self.servant.insight_reports)

        self.game.observation_manager.end_turn(1)
        self.game.turn_manager.update_visibility()
        self.assertNotIn(self.target, self.caster.own_visible)

    def test_workshop_covers_levels_replaces_only_after_success_and_dies_with_owner(self):
        workshop = self.caster.load_basic_magic("workshop")
        first = self.caster.resolve_skill_component(
            workshop.skill_id,
            "establish",
            target=self.a,
            turn_number=1,
        )["results"][0]["field"]
        self.assertIn(self.a, first.covered_nodes)

        self.caster.position = self.b
        self.caster.action_point = 2
        self.target.position = self.b.high_level_location
        self.target.status_flags.add("hidden")
        second_result = self.caster.resolve_skill_component(
            workshop.skill_id,
            "establish",
            target=self.b,
            turn_number=1,
        )["results"][0]
        second = second_result["field"]
        self.assertTrue(second_result["created"])
        self.assertNotIn(first, self.game.field_effects)
        self.assertIn(self.b, second.covered_nodes)
        self.assertIn(self.b.high_level_location, second.covered_nodes)
        self.game.turn_manager.update_visibility()
        self.assertNotIn(self.target, self.caster.own_visible)
        self.caster.position = self.b.high_level_location
        self.game.turn_manager.update_visibility()
        self.assertIn(self.target, self.caster.own_visible)

        other_workshop = self.other.load_basic_magic("workshop")
        self.other.position = self.c
        blocking = self.other.resolve_skill_component(
            other_workshop.skill_id,
            "establish",
            target=self.c,
            turn_number=1,
        )["results"][0]["field"]
        self.caster.position = self.c
        self.caster.action_point = 2
        blocked = self.caster.resolve_skill_component(
            workshop.skill_id,
            "establish",
            target=self.c,
            turn_number=1,
        )["results"][0]
        self.assertFalse(blocked["created"])
        self.assertEqual(blocked["reason"], "center_occupied")
        self.assertIn(second, self.game.field_effects)
        self.assertIn(blocking, self.game.field_effects)

        self.caster.die()
        self.assertNotIn(second, self.game.field_effects)

    def test_insight_prevents_hidden_enemy_ambush_after_ap2_movement(self):
        a = Location("A", is_building=True)
        b = Location("B")
        c = Location("C", is_building=True)
        a.add_connection(b)
        b.add_connection(a)
        b.add_connection(c)
        c.add_connection(b)
        master_a = make_master("御主a")
        master_c = make_master("御主c")
        master_a.position = a
        master_c.position = c
        game = GameManager([master_a, master_c], a)
        game.start_game()
        game.turn_manager.turn = 1
        game.turn_manager.current_ap_layer = 1
        for character in game.characters:
            character.current_global_turn = 1

        insight = master_a.load_basic_magic("insight")
        master_a.resolve_skill_component(
            insight.skill_id,
            "observe",
            target=c,
            phase="AP1—洞悉",
            ap_layer=1,
            turn_number=1,
        )
        hide = Action(master_c, "hide", characters=game.characters)
        hide.ap_layer = 1
        hide.game_turn = 1
        self.assertTrue(hide.hide())
        self.assertTrue(master_c.has_status("hidden"))
        self.assertIn(master_c, master_a.own_visible)

        game.turn_manager.current_ap_layer = 2
        master_a.movement_point = 2
        state = MovementState(master_a, [a, b, c])
        encounters = MovementResolver().resolve(
            [state],
            [master_a, master_c],
            game.characters,
        )
        self.assertEqual(len(encounters), 1)
        encounter = encounters[0]
        self.assertIn(master_c, encounter.awareness[master_a])
        self.assertIn(master_a, encounter.awareness[master_c])

        self.assertTrue(encounter.choose_battle(
            master_c,
            target=master_a,
            ap_layer=2,
        ))
        self.assertTrue(encounter.choose_continue(
            master_a,
            target=master_c,
        ))
        encounter.lock_battle_requests(2)
        request = encounter.battle_requests[0]
        self.assertFalse(request.is_ambush)
        self.assertEqual(encounter.get_ambush_pairs(), [])


if __name__ == "__main__":
    unittest.main()
