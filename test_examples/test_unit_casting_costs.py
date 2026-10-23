"""A chant is bound to one unit, with its own complete payment schedule."""
from copy import deepcopy
import unittest

from game.action.action import Action
from game.character.masters import Master
from game.game.character_state import character_state
from game.resource.costs import SkillUnavailableError
from game.skill.casting import CastingState, castable_options, release_options, start_or_continue_casting
from game.skill.skill_runtime import resolve_skill_component, validate_personal_skill_definition
from game.turn.decision import ScriptedDecisionProvider


def skill_data():
    return {"skill_id": "separate", "name": "Separate", "rank": "C", "casting": {"activation_mode": "release"},
            "components": [{"component_id": key, "name": key.upper(), "type": "active", "target": "self",
                "casting_requirement": rounds, "cost": [
                    {"resource": "mp", "value": prepaid, "timing": "casting_start"},
                    {"resource": "mp", "value": activation}],
                "effects": [{"effect_type": "attack_bonus", "effect_data": {"value": 1}}]}
                for key, rounds, prepaid, activation in (("a", 1, 10, 3), ("b", 2, 40, 7))]}


class UnitCastingCostTests(unittest.TestCase):
    def setUp(self):
        self.actor = Master("Actor", 3, 3, 3, 3, 3, "C", 3)
        self.skill = self.actor.create_personal_skill(skill_data())

    def test_chant_selects_unit_before_payment_and_only_releases_that_unit(self):
        mp = self.actor.mp
        action = Action(self.actor, "chant", self.skill)
        action.ap_layer, action.game_turn = 1, 1
        state = action.chant(ScriptedDecisionProvider(["b"]))
        self.assertEqual(state.component_id, "b")
        self.assertEqual(self.actor.mp, mp - 40)
        self.assertEqual(self.actor.action_point, 0)
        state.advance_at_global_turn_end(1)
        self.assertEqual(release_options(self.actor), [])
        state.continue_for_turn(2)
        state.advance_at_global_turn_end(2)
        self.assertEqual([component["component_id"] for _, component in release_options(self.actor)], ["b"])
        self.actor.reset_turn()
        release = Action(self.actor, "release")
        release.ap_layer, release.game_turn = 1, 3
        release.release(ScriptedDecisionProvider([]))
        self.assertEqual(self.actor.mp, mp - 47)
        self.assertIsNone(self.actor.casting_state)
        self.assertEqual(state.interrupt(), [])

    def test_start_requires_an_explicit_unit_when_several_are_available(self):
        mp = self.actor.mp
        with self.assertRaisesRegex(ValueError, "指定技能单元"):
            CastingState.start(self.actor, self.skill, 1)
        self.assertEqual(self.actor.mp, mp)
        self.assertIsNone(self.actor.casting_state)

    def test_cancel_at_unit_selection_does_not_pay_or_consume_actions(self):
        mp, ap = self.actor.mp, self.actor.action_point
        action = Action(self.actor, "chant", self.skill)
        action.ap_layer = 1
        self.assertFalse(action.chant(ScriptedDecisionProvider(["back"])))
        self.assertEqual((self.actor.mp, self.actor.action_point), (mp, ap))
        self.assertIsNone(self.actor.casting_state)

    def test_switch_requires_interruption_then_refunds_and_prices_the_new_unit(self):
        mp = self.actor.mp
        state = CastingState.start(self.actor, self.skill, 1, "b")
        with self.assertRaisesRegex(ValueError, "先中断"):
            start_or_continue_casting(self.actor, self.skill, 1, "a")
        self.assertIs(self.actor.casting_state, state)
        self.assertEqual(self.actor.mp, mp - 40)
        state.interrupt()
        self.assertEqual(self.actor.mp, mp)
        new = CastingState.start(self.actor, self.skill, 1, "a")
        self.assertEqual(new.component_id, "a")
        self.assertEqual(self.actor.mp, mp - 10)

    def test_direct_calls_cannot_use_another_units_prepayment_or_release_early(self):
        state = CastingState.start(self.actor, self.skill, 1, "b")
        mp = self.actor.mp
        for component_id in ("a", "b"):
            with self.subTest(component=component_id), self.assertRaises(SkillUnavailableError):
                resolve_skill_component(self.actor, self.skill, component_id, casting_release=True, casting_prepaid=True)
        state.advance_at_global_turn_end(1)
        state.continue_for_turn(2)
        state.advance_at_global_turn_end(2)
        with self.assertRaises(SkillUnavailableError):
            resolve_skill_component(self.actor, self.skill, "a", casting_release=True)
        self.assertEqual(self.actor.mp, mp)
        self.assertIs(self.actor.casting_state, state)

    def test_affordability_and_snapshot_are_per_unit(self):
        self.actor.mp = 15
        self.assertEqual([component["component_id"] for _, component in castable_options(self.actor)], ["a"])
        state = CastingState.start(self.actor, self.skill, 1, "a")
        view = character_state(self.actor)
        self.assertEqual(view["casting"]["component_id"], "a")
        self.assertEqual(view["casting"]["maximum_layers"], 1)
        self.assertIn("A", state.name)
        viewed_skill = next(item for item in view["skills"] if item["skill_id"] == self.skill.skill_id)
        self.assertNotIn("cost", viewed_skill)
        self.assertEqual([unit["casting_cost"] for unit in viewed_skill["components"]], [10, 40])

    def test_root_costs_are_rejected_and_unit_costs_are_independent(self):
        data = skill_data()
        data["cost"] = []
        with self.assertRaisesRegex(ValueError, "公共消耗"):
            validate_personal_skill_definition(data)
        original = deepcopy(self.skill.definitions[1]["cost"])
        self.skill.definitions[0]["cost"][0]["value"] = 1
        self.assertEqual(self.skill.definitions[1]["cost"], original)
