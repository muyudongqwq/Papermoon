import unittest
from unittest.mock import patch

from game.action.action import Action
from game.action.action_list import ActionContext, ActionListBuilder
from game.character.masters import Master
from game.map.map import Location
from game.modifier.modifier import create_modifier
from game.turn.battle import BattleManager


def master(name):
    return Master(name, 3, 3, 3, 3, 3, "C", 3)


def battle_hidden(target, duration=1):
    return create_modifier(
        {
            "effect_type": "hidden",
            "modifier_id": "battle_hidden_test",
            "duration": duration,
            "duration_timing": "global_turn_end",
            "effect_data": {
                "value": "hidden",
                "requires_building": False,
                "remove_on_position_change": False,
                "remove_on_battle_entry": False,
                "withdraw_from_battle": True,
                "rejoin_on_expire": True,
            },
        },
        target,
        source=target,
        source_actor=target,
        applied_turn=1,
        applied_phase="attack_phase",
    )


class BattleHiddenTests(unittest.TestCase):
    def setUp(self):
        self.location = Location("A")
        self.hidden = master("Hidden")
        self.observer = master("Observer")
        self.other = master("Other")
        for character in (self.hidden, self.observer, self.other):
            character.position = self.location
        self.battle = BattleManager([
            self.hidden,
            self.observer,
            self.other,
        ])
        self.battle.start_battle()

    def test_hidden_withdraws_without_moving_and_rejoins_at_end(self):
        position = self.hidden.position
        self.assertTrue(self.hidden.add_modifier(battle_hidden(self.hidden)))

        self.assertIs(self.hidden.position, position)
        self.assertFalse(self.hidden.in_battle)
        self.assertNotIn(self.hidden, self.battle.participants)
        self.assertTrue(self.hidden.has_status("hidden"))

        self.hidden.update_modifiers("global_turn_end", turn_number=2)

        self.assertTrue(self.hidden.in_battle)
        self.assertIn(self.hidden, self.battle.participants)
        self.assertIs(self.hidden.current_battle, self.battle)
        self.assertIs(self.battle.current_order[-1], self.hidden)
        self.assertFalse(self.hidden.has_status("hidden"))

    def test_moving_while_hidden_prevents_automatic_rejoin(self):
        elsewhere = Location("B")
        self.hidden.add_modifier(battle_hidden(self.hidden))
        self.hidden.position = elsewhere
        self.hidden.update_modifiers("global_turn_end", turn_number=2)

        self.assertFalse(self.hidden.in_battle)
        self.assertNotIn(self.hidden, self.battle.participants)
        self.assertIs(self.hidden.position, elsewhere)

    def test_battle_perception_consumes_attack_phase_and_reveals_hidden(self):
        self.hidden.add_modifier(battle_hidden(self.hidden, duration=2))
        self.observer.attack_phase_count = 1
        action = Action(
            self.observer,
            "battle_perceive",
            characters=[self.hidden, self.observer, self.other],
        )
        with patch("game.action.action.random.randint", side_effect=[10, 1]):
            result = action.battle_perceive()

        self.assertEqual(self.observer.attack_phase_count, 0)
        self.assertIn(self.hidden, result["detected"])
        self.assertIn(self.hidden, self.observer.own_visible)
        self.assertFalse(self.hidden.in_battle)

    def test_battle_perception_is_a_formal_attack_phase_action(self):
        context = ActionContext(
            actor=self.observer,
            phase="attack_phase",
            battle=self.battle,
            characters=list(self.battle.participants),
        )
        action_ids = {
            entry.action_id
            for entry in ActionListBuilder().get_available_actions(context)
        }
        self.assertIn("battle_perceive", action_ids)


if __name__ == "__main__":
    unittest.main()
