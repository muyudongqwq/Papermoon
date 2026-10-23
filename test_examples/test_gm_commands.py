import unittest

from game.character.masters import Master
from game.game.game_manager import GameManager
from game.game.gm_commands import GMCommandService
from core.terminal_commands import TerminalCommandHandler
from game.map.map import Location, Map


def create_master(name="Hero"):
    return Master(name, 3, 3, 3, 3, 3, "C", 3)


class GMCommandTests(unittest.TestCase):
    def setUp(self):
        self.a = Location("Site A")
        self.b = Location("Site B")
        self.game_map = Map()
        self.game_map.add_location(self.a)
        self.game_map.add_location(self.b)
        self.game_map.add_road(self.a, self.b)
        self.actor = create_master("Hero One")
        self.actor.position = self.a
        self.game = GameManager([self.actor], self.a)
        self.game.game_map = self.game_map
        self.game.start_game()
        self.service = GMCommandService(self.game)

    def test_add_resource_ignores_builtin_and_custom_maximum(self):
        self.actor.add_resource({
            "resource_id": "charges",
            "name": "充能",
            "initial_value": 4,
            "minimum": 0,
            "maximum": 5,
        })

        hp_result = self.service.add_resource(
            "Hero One",
            "hp",
            10,
        )
        custom_result = self.service.add_resource(
            "Hero One",
            "充能",
            3,
        )

        self.assertEqual(self.actor.hp, self.actor.hpmax + 10)
        self.assertEqual(hp_result["new_value"], self.actor.hp)
        self.assertEqual(custom_result["new_value"], 7)
        self.assertTrue(self.actor.resource_manager.pay("charges", 2))
        self.assertEqual(self.actor.get_resource_value("charges"), 5)

    def test_damage_is_immediate_sourceless_and_not_pending(self):
        hp_before = self.actor.hp

        result = self.service.damage("Hero One", 0, 10)

        self.assertEqual(result["damage_type"], "true_damage")
        self.assertEqual(result["final_damage"], 10)
        self.assertIsNone(result["event"].source)
        self.assertEqual(self.actor.hp, hp_before - 10)
        self.assertEqual(self.actor.pending_attacks, [])

    def test_teleport_reuses_command_spell_movement_without_cost(self):
        command_spells = self.actor.command_spell

        result = self.service.teleport("Hero One", "Site B")

        self.assertIs(self.actor.position, self.b)
        self.assertIs(result["destination"], self.b)
        self.assertEqual(self.actor.command_spell, command_spells)

    def test_kill_uses_normal_death_cleanup(self):
        result = self.service.kill("Hero One")

        self.assertIs(result["target"], self.actor)
        self.assertTrue(self.actor.has_status("dead"))
        self.assertNotIn(self.actor, self.game.characters)
        self.assertIn(self.actor, self.game.dead_characters)

    def test_terminal_parser_supports_quoted_names(self):
        output = []
        handler = TerminalCommandHandler(
            self.game,
            output_func=output.append,
        )

        self.assertTrue(handler.handle(
            'teleport "Hero One" "Site B"',
            self.actor,
        ))
        self.assertIs(self.actor.position, self.b)
        self.assertIn("Hero One", output[-1])

    def test_invalid_or_missing_parameters_raise_value_error(self):
        handler = TerminalCommandHandler(
            self.game,
            output_func=lambda _message: None,
        )

        invalid_commands = (
            "add_resource Hero",
            'add_resource "Hero One" hp -1',
            'add_resource "Hero One" hp 1.5',
            'add_resource "Hero One" unknown 1',
            'damage "Hero One" 3 10',
            'damage "Hero One" 1 -1',
            'teleport "Hero One" Missing',
            "kill Missing",
        )
        for command in invalid_commands:
            with self.subTest(command=command):
                with self.assertRaises(ValueError):
                    handler.handle(command, self.actor)


if __name__ == "__main__":
    unittest.main()
