"""Editor hints follow engine schemas without adding a second rules registry."""

import unittest

from SkillEditorClient.effect_options import (
    EFFECT_NAMES, EFFECT_TYPES, FORM_EFFECT_TYPES, parameter_options, parameter_spec, parse_parameter,
)
from game.skill.effect_validation import EFFECT_SCHEMAS, validate_effect_definition


class EffectEditorOptionTests(unittest.TestCase):
    def test_effects_match_engine_and_all_have_chinese_names(self):
        self.assertEqual(set(EFFECT_TYPES), set(EFFECT_SCHEMAS))
        self.assertEqual(set(EFFECT_NAMES), set(FORM_EFFECT_TYPES))
        self.assertEqual(set(FORM_EFFECT_TYPES) - set(EFFECT_TYPES), {"choices"})

    def test_choices_is_a_form_entry_without_changing_the_engine_registry(self):
        self.assertNotIn("choices", EFFECT_SCHEMAS)
        self.assertEqual(set(parameter_options("choices")), {"maximum_selections", "allow_duplicate"})
        self.assertEqual(EFFECT_NAMES["choices"], "可选发动")

    def test_parameters_match_every_schema_with_required_first(self):
        for key, schema in EFFECT_SCHEMAS.items():
            with self.subTest(effect=key):
                options = parameter_options(key)
                self.assertEqual(set(options), schema.allowed_data)
                self.assertEqual(len(options), len(set(options)))
                self.assertEqual(set(options[:len(schema.required_data)]), schema.required_data)

    def test_no_parameter_effect_and_unknown_type_have_empty_options(self):
        self.assertEqual(parameter_options("observe_location"), ())
        self.assertEqual(parameter_options("not_implemented"), ())

    def test_calculation_options_depend_on_type(self):
        self.assertIn("move_first", parameter_spec("order_change", "calculation").choices)
        self.assertNotIn("move_first", parameter_spec("modify_resource", "calculation").choices)
        self.assertIn("divide", parameter_spec("modify_resource", "calculation").choices)
        self.assertEqual(parameter_spec("modify_event_value", "calculation").choices, ("add", "multiply", "set"))
        self.assertNotIn("override", parameter_spec("damage_modifier", "calculation").choices)

    def test_fixed_options_produce_values_accepted_by_engine(self):
        examples = {
            ("damage", "damage_type"): {"value": 5},
            ("cost_modifier", "calculation"): {"resource": "mp", "value": 1},
            ("damage_modifier", "direction"): {"calculation": "flat", "value": 1},
            ("damage_modifier", "calculation"): {"direction": "incoming", "value": 1},
            ("modify_event_value", "calculation"): {"value": 1},
            ("presence_concealment", "rank"): {"value": 1},
            ("grant_temporary_mp", "value_source"): {},
            ("hidden", "remove_on_position_change"): {"value": "hidden"},
        }
        for (kind, field), other in examples.items():
            spec = parameter_spec(kind, field)
            for text in spec.choices:
                with self.subTest(effect=kind, field=field, choice=text):
                    self.assertTrue(validate_effect_definition({"effect_type": kind,
                        "effect_data": {**other, field: parse_parameter(text, spec)}}))

    def test_ids_include_current_project_custom_statuses(self):
        choices = parameter_spec("add_status", "status_id", {"status": {"burning": {}, "user_poison": {}}}).choices
        self.assertEqual(choices, ("burning", "user_poison"))

    def test_numbers_booleans_and_input_expressions_keep_types(self):
        number = parameter_spec("damage", "value")
        for text, value in (("10", 10), ("2.5", 2.5), ('{"input_id":"x"}', {"input_id": "x"})):
            self.assertEqual(parse_parameter(text, number), value)
        boolean = parameter_spec("damage", "ignore_shield")
        self.assertIs(parse_parameter("false", boolean), False)
        self.assertIs(parse_parameter("true", boolean), True)

    def test_text_all_and_null_do_not_get_confused(self):
        self.assertEqual(parse_parameter("null", parameter_spec("add_status", "status_id")), "null")
        self.assertIsNone(parse_parameter("null", parameter_spec("summon", "duration")))
        self.assertEqual(parse_parameter("all", parameter_spec("purify", "maximum")), "all")
        self.assertEqual(parse_parameter("2", parameter_spec("purify", "maximum")), 2)

    def test_hidden_value_is_text_and_bad_numeric_text_is_rejected(self):
        self.assertEqual(parse_parameter("hidden", parameter_spec("hidden", "value")), "hidden")
        with self.assertRaises(ValueError):
            parse_parameter("not a number", parameter_spec("damage", "value"))


if __name__ == "__main__":
    unittest.main()
