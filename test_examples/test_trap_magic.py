import unittest
from unittest.mock import patch

from game.character.masters import Master
from game.game.game_manager import GameManager
from game.map.map import Location
from game.map.movement import MovementResolver, MovementState
from game.turn.decision import ScriptedDecisionProvider


def master(name):
    return Master(name, 3, 3, 3, 3, 3, "C", 3)


class TrapMagicTests(unittest.TestCase):
    def setUp(self):
        self.a = Location("A")
        self.b = Location("B")
        self.a.add_connection(self.b)
        self.b.add_connection(self.a)
        self.caster = master("Caster")
        self.first = master("First")
        self.second = Master("Second", 3, 3, 4, 3, 3, "C", 3)
        self.caster.position = self.b
        self.first.position = self.a
        self.second.position = self.a
        self.game = GameManager(
            [self.caster, self.first, self.second],
            self.a,
        )
        self.game.start_game()
        self.game.turn_manager.turn = 1
        for character in self.game.characters:
            character.current_global_turn = 1

    def set_trap(self, *, share=False):
        skill = self.caster.load_basic_magic("trap")
        result = self.caster.resolve_skill_component(
            skill.skill_id,
            "set_trap",
            target=self.b,
            selected_choice_ids=["share" if share else "private"],
            phase="AP1",
        )
        return result["results"][0]["trap"]

    def test_movement_entry_triggers_and_deactivates_trap(self):
        trap = self.set_trap()
        self.caster.position = None
        self.first.movement_point = 1
        state = MovementState(self.first, [self.a, self.b])
        provider = ScriptedDecisionProvider(["block"])

        with (
            patch.object(
                self.game.trap_manager,
                "_attack_roll",
                return_value=(5, 10),
            ),
            patch("game.turn.defense.random.randint", return_value=5),
        ):
            encounters = MovementResolver().resolve(
                [state],
                [self.first, self.second, self.caster],
                self.game.characters,
                decision_provider=provider,
            )

        self.assertFalse(trap.active)
        self.assertEqual(self.first.hp, self.first.hpmax - 30)
        self.assertIsNone(encounters)

    def test_one_entering_formation_shares_damage_between_hit_members(self):
        trap = self.set_trap()
        self.first.position = self.second.position = self.b
        provider = ScriptedDecisionProvider(["block", "block"])

        with (
            patch.object(
                self.game.trap_manager,
                "_attack_roll",
                return_value=(5, 10),
            ),
            patch("game.turn.defense.random.randint", return_value=5),
        ):
            results = self.game.trap_manager.trigger_entry(
                [self.first, self.second],
                self.b,
                decision_provider=provider,
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["shared_damage"], 15)
        self.assertEqual(self.first.hp, self.first.hpmax - 15)
        self.assertEqual(self.second.hp, self.second.hpmax - 15)
        self.assertFalse(trap.active)

    def test_known_character_neither_triggers_nor_takes_damage(self):
        trap = self.set_trap()
        self.game.information_manager.learn_trap(
            self.first,
            trap.information,
        )
        self.first.position = self.b

        results = self.game.trap_manager.trigger_entry(
            [self.first],
            self.b,
            decision_provider=ScriptedDecisionProvider([]),
        )

        self.assertEqual(results, [])
        self.assertTrue(trap.active)
        self.assertEqual(self.first.hp, self.first.hpmax)

    def test_command_spell_style_teleport_triggers_trap(self):
        trap = self.set_trap()
        provider = ScriptedDecisionProvider(["block"])

        with (
            patch.object(
                self.game.trap_manager,
                "_attack_roll",
                return_value=(5, 10),
            ),
            patch("game.turn.defense.random.randint", return_value=5),
        ):
            result = self.game.resolve_command_spell_teleport(
                self.first,
                self.b,
                decision_provider=provider,
            )

        self.assertFalse(trap.active)
        self.assertEqual(len(result["trap_results"]), 1)
        self.assertEqual(self.first.hp, self.first.hpmax - 30)

    def test_owner_death_removes_every_active_trap_without_limits(self):
        first = self.set_trap()
        self.caster.action_point = 2
        second = self.caster.resolve_skill_component(
            "basic_magic:trap",
            "set_trap",
            target=self.b,
            selected_choice_ids=["private"],
            phase="AP2",
        )["results"][0]["trap"]

        self.assertNotEqual(first.trap_id, second.trap_id)
        self.caster.die()
        self.assertFalse(first.active)
        self.assertFalse(second.active)


if __name__ == "__main__":
    unittest.main()
