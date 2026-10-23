"""Boolean condition semantics and linear form conversion."""

from itertools import product
import unittest

from game.action.action_rules import CONDITION_FIELDS, condition_matches, get_condition_reasons, validate_condition
from game.character.masters import Master
from game.skill.event_runtime import GameEvent
from SkillEditorClient.condition_model import CONDITION_NAMES, combine_conditions, linear_conditions


class ConditionLogicTests(unittest.TestCase):
    def setUp(self):
        self.actor = Master("Actor", 3, 3, 3, 3, 3, "C", 3)

    def test_all_any_not_follow_boolean_truth_tables(self):
        for battle, own_target in product((False, True), repeat=2):
            self.actor.in_battle = battle
            event = GameEvent("example", target=self.actor if own_target else object())
            first, second = {"battle_state": True}, {"event_target_is_self": True}
            for condition, expected in (({"all": [first, second]}, battle and own_target),
                                        ({"any": [first, second]}, battle or own_target),
                                        ({"not": first}, not battle),
                                        ({"all": [first, {"not": second}]}, battle and not own_target)):
                with self.subTest(battle=battle, own_target=own_target, condition=condition):
                    self.assertEqual(condition_matches(condition, self.actor, {"event": event}), expected)

    def test_not_negates_the_result_instead_of_rewriting_boolean_values(self):
        self.actor.in_battle = True
        self.assertTrue(condition_matches({"not": {"battle_state": False}}, self.actor))
        self.assertFalse(condition_matches({"not": {"actor_alive": True}}, self.actor))
        self.assertEqual(get_condition_reasons({"battle_state": False}, self.actor), ["wrong_battle_state"])

    def test_invalid_logical_nodes_and_excessive_nesting_are_rejected(self):
        for condition in ({"all": []}, {"any": {}}, {"not": True}, {"all": [None]}, {"any": [{"unknown": 1}]}):
            with self.subTest(condition=condition), self.assertRaises((ValueError, TypeError)):
                validate_condition(condition)
        condition = {}
        for _ in range(34):
            condition = {"not": condition}
        with self.assertRaisesRegex(ValueError, "32"):
            validate_condition(condition)

    def test_form_expression_is_evaluated_top_to_bottom_and_round_trips(self):
        rows = [
            {"field": "battle_state", "value": True, "join": "与", "negated": False},
            {"field": "event_target_is_self", "value": True, "join": "或", "negated": False},
            {"field": "event_value_at_least", "value": 20, "join": "与", "negated": True},
        ]
        expression = combine_conditions(rows)
        rebuilt = linear_conditions(expression)
        self.assertEqual(rebuilt, rows)
        self.assertEqual(combine_conditions(rebuilt), expression)
        for battle, own_target, value in product((False, True), (False, True), (10, 30)):
            self.actor.in_battle = battle
            event = GameEvent("example", target=self.actor if own_target else object(), value=value)
            self.assertEqual(condition_matches(expression, self.actor, {"event": event}),
                             (battle or own_target) and value < 20)

    def test_grouped_right_branches_use_advanced_json_instead_of_flattening(self):
        condition = {"all": [{"battle_state": True}, {"any": [{"actor_alive": True}, {"event_target_is_self": True}]}]}
        self.assertIsNone(linear_conditions(condition))
        self.assertEqual(set(CONDITION_NAMES), CONDITION_FIELDS - {"all", "any", "not"})

    def test_negation_combines_with_or_and_consecutive_and_stays_shallow(self):
        rows = [{"field": "battle_state", "value": True, "join": "与", "negated": True},
                {"field": "actor_alive", "value": True, "join": "或", "negated": True}]
        expression = combine_conditions(rows)
        self.assertEqual(combine_conditions(linear_conditions(expression)), expression)
        self.assertTrue(condition_matches(expression, self.actor))
        many = [{"field": "actor_alive", "value": True, "join": "与", "negated": False} for _ in range(40)]
        self.assertEqual(len(combine_conditions(many)["all"]), 40)
