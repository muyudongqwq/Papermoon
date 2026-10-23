"""The shared calculation field must reach every effect's actual resolver."""

from copy import deepcopy
import unittest

from game.character.masters import Master
from game.skill.effect_validation import EFFECT_SCHEMAS, validate_effect_definition
from game.skill.event_runtime import GameEvent
from game.skill.skill import Skill
from game.skill.skill_runtime import apply_skill_effect


EXAMPLES = {
    "modify_resource": {"resource_id": "charges", "calculation": "set", "value": 3},
    "modify_event_value": {"calculation": "multiply", "value": 0.5},
    "growing": {"growth_id": "growth", "calculation": "set", "value": 3,
                "stages": [{"stage_id": "first", "threshold": 2}]},
    "order_change": {"calculation": "move_first", "duration": 1},
    "cost_modifier": {"resource": "mp", "calculation": "multiplier", "value": 0.5},
    "damage_modifier": {"direction": "incoming", "calculation": "percentage", "value": -20},
    "recover_resource": {"resource_id": "hp", "calculation": "flat", "value": 3},
}


class CalculationKeywordTests(unittest.TestCase):
    def setUp(self):
        self.actor = Master("Actor", 3, 3, 3, 3, 3, "C", 3)
        self.actor.add_resource({"resource_id": "charges", "initial_value": 5, "maximum": 100})
        self.skill = Skill("Source", "C", definitions=[], skill_id="source")

    def apply(self, kind, **data):
        return apply_skill_effect({"effect_type": kind, "effect_data": data}, self.actor,
                                  self.skill, actor=self.actor)

    def test_all_effect_schemas_use_one_field(self):
        for kind, schema in EFFECT_SCHEMAS.items():
            with self.subTest(effect=kind):
                self.assertNotIn("operation", schema.allowed_data)
        for kind in EXAMPLES:
            self.assertIn("calculation", EFFECT_SCHEMAS[kind].allowed_data)

    def test_new_definitions_validate_and_old_name_is_rejected(self):
        for kind, data in EXAMPLES.items():
            with self.subTest(effect=kind):
                self.assertTrue(validate_effect_definition({"effect_type": kind, "effect_data": data}))
                for keep_new in (False, True):
                    legacy = deepcopy(data)
                    legacy["operation"] = legacy["calculation"]
                    if not keep_new:
                        legacy.pop("calculation")
                    with self.assertRaises(ValueError):
                        validate_effect_definition({"effect_type": kind, "effect_data": legacy})

    def test_low_level_effect_call_rejects_old_key_before_mutation(self):
        with self.assertRaisesRegex(ValueError, "calculation"):
            self.apply("modify_resource", resource_id="charges", operation="multiply", value=2)
        self.assertEqual(self.actor.get_resource_value("charges"), 5)

    def test_resource_calculations_reach_arithmetic_and_omitted_field_keeps_add_default(self):
        for calculation, value, expected in (("add", 2, 7), ("subtract", 3, 4),
                                              ("multiply", 2, 8), ("divide", 3, 2), ("set", 9, 9)):
            with self.subTest(calculation=calculation):
                self.apply("modify_resource", resource_id="charges", calculation=calculation, value=value)
                self.assertEqual(self.actor.get_resource_value("charges"), expected)
        self.apply("modify_resource", resource_id="charges", value=1)
        self.assertEqual(self.actor.get_resource_value("charges"), 10)

    def test_resource_gain_rule_set_does_not_fall_back_to_add(self):
        self.actor.add_resource({"resource_id": "progress", "initial_value": 10,
            "gain_rules": [{"trigger_event": "test_gain", "calculation": "set", "value": 3}]})
        self.actor.trigger_resource_event("test_gain")
        self.assertEqual(self.actor.get_resource_value("progress"), 3)

    def test_nested_old_rule_is_rejected_by_schema_and_resource_api(self):
        data = {"resource_id": "progress", "gain_rules": [
            {"trigger_event": "test_gain", "operation": "set", "value": 3}]}
        with self.assertRaises(ValueError):
            validate_effect_definition({"effect_type": "add_resource", "effect_data": data})
        with self.assertRaisesRegex(ValueError, "calculation"):
            self.actor.add_resource(data)
        self.assertFalse(self.actor.has_resource("progress"))

    def test_event_calculation_and_replay_keep_existing_result(self):
        event = GameEvent("before_damage", timing="before", value=100)
        result = apply_skill_effect({"effect_type": "modify_event_value",
            "effect_data": {"calculation": "multiply", "value": 0.5}}, self.actor,
            self.skill, actor=self.actor, game_event=event)
        self.assertEqual(result, 50)
        self.assertEqual(event.replay_value_operations(200), 100)

    def test_growth_set_and_subtract_do_not_fall_back_to_add(self):
        data = deepcopy(EXAMPLES["growing"])
        data["initial_value"] = 10
        first = self.apply("growing", **data)
        self.assertEqual(first["new_value"], 3)
        data.update(calculation="subtract", value=2)
        second = self.apply("growing", **data)
        self.assertEqual(second["new_value"], 1)
        self.assertFalse(second["growth_state"].active_stage_ids)

    def test_effects_still_reject_other_effects_calculation_names(self):
        for kind, data in EXAMPLES.items():
            with self.subTest(effect=kind):
                invalid = {**data, "calculation": "not_a_calculation"}
                with self.assertRaises(ValueError):
                    validate_effect_definition({"effect_type": kind, "effect_data": invalid})


if __name__ == "__main__":
    unittest.main()
