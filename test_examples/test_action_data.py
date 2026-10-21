import unittest

from game.character.masters import Master
from game.map.map import Location
from game.map.movement import MovementAction
from game.action.action import Action
from game.action.action_data import (
    ACTION_DATA,
    get_action_definition,
    validate_action_data,
)


def create_master(name="Master"):
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


class ActionDataTests(unittest.TestCase):
    def test_all_first_batch_definitions_are_registered_and_valid(self):
        self.assertTrue(validate_action_data())
        self.assertEqual(
            set(ACTION_DATA),
            {
                "move",
                "join_travel_group",
                "invite_carry",
                "leave_carry",
                "join_battle",
                "transfer_travel_leader",
                "pass",
                "surrender",
                "wish",
                "investigate",
                "perceive",
                "battle_perceive",
                "hide",
                "stay",
                "attack",
                "direct_attack",
                "mend",
                "rest",
                "command_spell_transfer",
                "chant",
                "interrupt_casting",
                "release",
                "escape",
                "guard",
                "dodge",
                "block",
                "offset",
            },
        )

    def test_action_data_contains_only_plain_data(self):
        def assert_plain(value):
            self.assertFalse(callable(value))
            if isinstance(value, dict):
                for key, child in value.items():
                    self.assertIsInstance(key, str)
                    assert_plain(child)
            elif isinstance(value, list):
                for child in value:
                    assert_plain(child)
            else:
                self.assertIsInstance(
                    value,
                    (str, int, float, bool, type(None)),
                )

        assert_plain(ACTION_DATA)

    def test_definition_lookup_returns_an_independent_copy(self):
        definition = get_action_definition("attack")
        definition["name"] = "changed"
        definition["effects"][0]["effect_data"]["attack_stat"] = "magic"

        self.assertEqual(ACTION_DATA["attack"]["name"], "普通攻击")
        self.assertEqual(
            ACTION_DATA["attack"]["effects"][0]["effect_data"][
                "attack_stat"
            ],
            "physical_attack",
        )

    def test_runtime_action_uses_action_id_and_loads_its_definition(self):
        action = Action(create_master(), "perceive")

        self.assertEqual(action.action_id, "perceive")
        self.assertEqual(action.definition["action_id"], "perceive")
        self.assertFalse(hasattr(action, "action_type"))

    def test_path_movement_uses_public_move_action_definition(self):
        actor = create_master()
        start = Location("A")
        destination = Location("B")
        start.add_connection(destination)
        destination.add_connection(start)
        actor.position = start

        action = MovementAction(actor, [start, destination])

        self.assertEqual(action.action_id, "move")
        self.assertEqual(action.definition["action_type"], "movement")

    def test_resolution_timings_match_current_rules(self):
        self.assertEqual(
            ACTION_DATA["attack"]["resolution_timing"],
            "defense_phase",
        )
        self.assertEqual(
            ACTION_DATA["perceive"]["resolution_timing"],
            "ap_checkpoint",
        )
        self.assertEqual(
            ACTION_DATA["investigate"]["resolution_timing"],
            "ap_checkpoint",
        )
        self.assertEqual(
            ACTION_DATA["rest"]["resolution_timing"],
            "global_turn_end",
        )
        self.assertEqual(
            ACTION_DATA["direct_attack"]["resolution_timing"],
            "immediate",
        )
        self.assertFalse(
            ACTION_DATA["direct_attack"]["effects"][0]["effect_data"][
                "is_ambush"
            ]
        )


if __name__ == "__main__":
    unittest.main()
