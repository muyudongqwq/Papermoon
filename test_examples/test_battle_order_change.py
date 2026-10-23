import unittest
from types import SimpleNamespace
from unittest.mock import patch

from game.character.servants import Servant
from game.skill.skill import Skill
from game.skill.skill_runtime import apply_skill_effect
from game.turn.battle import BattleManager
from game.turn.battle_request import BattleRequest
from game.turn.Turn import TurnManager


def servant(name, flexibility, fortune=3):
    return Servant(
        name,
        3,
        3,
        flexibility,
        3,
        fortune,
        "Saber",
        "A",
    )


class BattleOrderChangeTests(unittest.TestCase):
    def setUp(self):
        self.a = servant("A", 10)
        self.b = servant("B", 8)
        self.c = servant("C", 6)
        self.d = servant("D", 4)
        self.battle = BattleManager([self.a, self.b, self.c, self.d])
        self.battle.start_battle()

    def test_newcomer_batch_rolls_internally_then_appends_to_old_order(self):
        old_order = list(self.battle.initial_order)
        first_new = servant("FirstNew", 3, fortune=3)
        second_new = servant("SecondNew", 3, fortune=3)

        with patch(
            "game.turn.initialivemanager.random.randint",
            side_effect=[2, 9],
        ):
            newcomer_order = self.battle.add_participants([
                first_new,
                second_new,
            ])

        self.assertEqual(newcomer_order, [second_new, first_new])
        self.assertEqual(
            self.battle.initial_order,
            old_order + [second_new, first_new],
        )
        self.assertEqual(
            self.battle.current_order,
            old_order + [second_new, first_new],
        )

    def test_simultaneous_join_requests_form_one_newcomer_batch(self):
        first_new = servant("FirstNew", 3, fortune=3)
        second_new = servant("SecondNew", 3, fortune=3)
        manager = TurnManager()
        manager.battles.append(self.battle)
        first_request = BattleRequest(first_new, self.a)
        second_request = BattleRequest(second_new, self.b)
        first_request.is_ambush = False
        second_request.is_ambush = False
        manager.pending_battle_requests.extend([
            first_request,
            second_request,
        ])
        old_order = list(self.battle.initial_order)

        with patch(
            "game.turn.initialivemanager.random.randint",
            side_effect=[2, 9],
        ):
            manager.start_pending_battles()

        self.assertEqual(
            self.battle.initial_order,
            old_order + [second_new, first_new],
        )
        self.assertEqual(manager.pending_battle_requests, [])

    def test_refresh_does_not_reroll_established_order(self):
        self.battle.initial_order = [self.d, self.b, self.a, self.c]

        with patch(
            "game.turn.initialivemanager.random.randint",
            side_effect=AssertionError("不应重掷已有角色的先手"),
        ):
            self.battle.refresh_participant_order()

        self.assertEqual(
            self.battle.current_order,
            [self.d, self.b, self.a, self.c],
        )

    def test_order_changes_apply_in_queue_order_and_expire_by_duration(self):
        first = self.battle.queue_order_change(
            "move_first",
            self.c,
            duration=2,
        )
        second = self.battle.queue_order_change(
            "move_before",
            self.d,
            anchor=self.a,
            duration=1,
        )

        self.assertEqual(first.polarity, "neutral")
        self.assertFalse(first.purifiable)
        self.assertLess(first.sequence, second.sequence)
        self.assertEqual(
            self.battle.current_order,
            [self.a, self.b, self.c, self.d],
        )

        self.battle.prepare_round_order()
        self.assertEqual(
            self.battle.round_order_snapshot,
            [self.c, self.d, self.a, self.b],
        )

        self.battle.prepare_round_order()
        self.assertEqual(
            self.battle.round_order_snapshot,
            [self.c, self.a, self.b, self.d],
        )

        self.battle.prepare_round_order()
        self.assertEqual(
            self.battle.round_order_snapshot,
            [self.a, self.b, self.c, self.d],
        )

    def test_move_last_and_move_after_use_post_removal_indexes(self):
        self.battle.queue_order_change(
            "move_after",
            self.a,
            anchor=self.c,
            duration=1,
        )
        self.battle.queue_order_change(
            "move_last",
            self.b,
            duration=1,
        )

        self.battle.prepare_round_order()

        self.assertEqual(
            self.battle.current_order,
            [self.c, self.a, self.d, self.b],
        )

    def test_removed_participant_is_removed_from_every_order_and_change(self):
        self.battle.prepare_round_order()
        self.battle.queue_order_change(
            "move_before",
            self.c,
            anchor=self.b,
            duration=2,
        )

        self.battle.remove_participant(self.b)

        self.assertNotIn(self.b, self.battle.participants)
        self.assertNotIn(self.b, self.battle.initial_order)
        self.assertNotIn(self.b, self.battle.current_order)
        self.assertNotIn(self.b, self.battle.round_order_snapshot)
        self.assertEqual(self.battle.pending_order_changes, [])

    def test_simple_round_defense_uses_formal_round_snapshot(self):
        self.battle.round_order_snapshot = [self.d, self.b, self.c, self.a]

        self.assertEqual(
            self.battle.get_simple_round_defense_order([self.a, self.d, self.b]),
            [self.d, self.b, self.a],
        )

    def test_simple_round_without_formal_battle_uses_global_order(self):
        first = servant("First", 1)
        second = servant("Second", 10)
        turn_manager = SimpleNamespace(global_action_order=[first, second])
        game_manager = SimpleNamespace(turn_manager=turn_manager)
        first.game_manager = game_manager
        second.game_manager = game_manager
        resolver = BattleManager([first, second])

        self.assertEqual(
            resolver.get_simple_round_defense_order([second, first]),
            [first, second],
        )

    def test_skill_keyword_queues_neutral_change_for_next_round(self):
        skill = Skill(
            name="换位",
            rank="C",
            definitions=[],
            skill_id="test_order_change",
        )
        effect = {
            "effect_type": "order_change",
            "polarity": "buff",  # 输入值不会改变关键词固定的neutral属性。
            "effect_data": {
                "calculation": "move_before",
                "subject": "actor",
                "anchor": "target",
                "duration": 1,
            },
        }

        change = apply_skill_effect(
            effect,
            self.b,
            skill,
            actor=self.d,
        )

        self.assertIs(change.subject, self.d)
        self.assertIs(change.anchor, self.b)
        self.assertEqual(change.polarity, "neutral")
        self.assertEqual(self.battle.current_order, [self.a, self.b, self.c, self.d])
        self.battle.prepare_round_order()
        self.assertEqual(
            self.battle.current_order,
            [self.a, self.d, self.b, self.c],
        )


if __name__ == "__main__":
    unittest.main()
