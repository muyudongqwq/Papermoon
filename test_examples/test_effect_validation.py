import copy
import unittest

from game.skill.content_registry import validate_content_catalogs
from game.skill.effect_validation import (
    EFFECT_SCHEMAS,
    validate_component_effects,
    validate_effect_definition,
    validate_effect_registry,
)
from game.skill.skill_runtime import EFFECT_HANDLERS, validate_skill_components
from game.action.action_rules import validate_condition, validate_target_rules


class EffectValidationTests(unittest.TestCase):
    def test_condition_and_target_rules_reject_unknown_fields(self):
        with self.assertRaisesRegex(ValueError, "未知字段"):
            validate_condition({"actor_alvie": True})
        with self.assertRaisesRegex(ValueError, "未知字段"):
            validate_target_rules({"allow_shared_visibility": False})

    def test_old_visible_collection_is_not_a_target_rule_alias(self):
        with self.assertRaisesRegex(ValueError, "标准视野字段"):
            validate_target_rules({"required_visibility": "visible"})

    def test_canonical_visibility_collections_are_valid_target_rules(self):
        for visibility in (
            "own_visible", "shared_visible", "own_perceived",
            "shared_perceived", "perceived", "any_visible",
        ):
            with self.subTest(visibility=visibility):
                self.assertTrue(validate_target_rules({
                    "required_visibility": visibility,
                }))

    def test_skill_input_reference_must_be_declared(self):
        component = {
            "component_id": "bad_input",
            "type": "active",
            "target": "self",
            "effects": [{
                "effect_type": "shield",
                "effect_data": {"value": {"input_id": "missing"}},
            }],
        }

        with self.assertRaisesRegex(ValueError, "未声明的input_id"):
            validate_component_effects(component)

    def test_variable_integer_input_requires_a_finite_maximum(self):
        component = {
            "component_id": "bad_range",
            "type": "active",
            "target": "self",
            "inputs": [{
                "input_id": "x",
                "input_type": "integer",
                "minimum": 0,
            }],
            "effects": [{
                "effect_type": "shield",
                "effect_data": {"value": 1},
            }],
        }

        with self.assertRaisesRegex(ValueError, "必须声明maximum"):
            validate_component_effects(component)

    def test_runtime_and_schema_registries_match(self):
        self.assertTrue(validate_effect_registry(EFFECT_HANDLERS))
        self.assertEqual(set(EFFECT_SCHEMAS), set(EFFECT_HANDLERS))

    def test_validation_does_not_mutate_definition(self):
        effect = {
            "modifier_id": "test_bonus",
            "effect_type": "dice_bonus",
            "duration": 2,
            "effect_data": {
                "effect_target": "physical_attack",
                "value": 2,
            },
        }
        original = copy.deepcopy(effect)

        self.assertTrue(validate_effect_definition(effect))
        self.assertEqual(effect, original)

    def test_unknown_effect_uses_missing_keyword_error(self):
        with self.assertRaisesRegex(ValueError, "效果关键词不存在"):
            validate_effect_definition({
                "effect_type": "does_not_exist",
                "effect_data": {},
            })

    def test_unknown_top_level_field_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "未知字段"):
            validate_effect_definition({
                "effect_type": "recover_resource",
                "effect_data": {"resource_id": "hp", "value": 10},
                "typo": True,
            })

    def test_unknown_effect_data_field_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "未知字段"):
            validate_effect_definition({
                "effect_type": "recover_resource",
                "effect_data": {
                    "resource_id": "hp",
                    "value": 10,
                    "ammount": 10,
                },
            })

    def test_old_recover_resource_fields_are_rejected(self):
        for old_field in ("resource", "value_type"):
            with self.subTest(old_field=old_field):
                data = {"resource_id": "hp", "value": 10}
                data[old_field] = "hp" if old_field == "resource" else "flat"
                with self.assertRaisesRegex(ValueError, "未知字段"):
                    validate_effect_definition({
                        "effect_type": "recover_resource",
                        "effect_data": data,
                    })

    def test_modifier_lifecycle_fields_must_be_top_level(self):
        with self.assertRaisesRegex(ValueError, "未知字段"):
            validate_effect_definition({
                "effect_type": "dice_bonus",
                "effect_data": {
                    "effect_target": "physical_attack",
                    "value": 2,
                    "duration": 1,
                },
            })

    def test_modifier_duration_must_be_positive(self):
        with self.assertRaisesRegex(ValueError, "正整数"):
            validate_effect_definition({
                "effect_type": "dice_bonus",
                "duration": 0,
                "effect_data": {
                    "effect_target": "physical_attack",
                    "value": 2,
                },
            })

    def test_dark_damage_alias_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "必须是以下值之一"):
            validate_effect_definition({
                "effect_type": "damage",
                "effect_data": {
                    "damage_type": "dark_damage",
                    "value": 10,
                },
            })

    def test_event_effects_are_rejected_from_active_components(self):
        component = {
            "type": "active",
            "effects": [{
                "effect_type": "cancel_event",
                "effect_data": {},
            }],
        }
        with self.assertRaisesRegex(ValueError, "trigger或react"):
            validate_component_effects(component)

    def test_change_damage_type_is_a_strict_event_effect(self):
        effect = {
            "effect_type": "change_damage_type",
            "effect_data": {"damage_type": "magic"},
        }
        self.assertTrue(validate_effect_definition(effect, component_type="trigger"))
        with self.assertRaisesRegex(ValueError, "trigger或react"):
            validate_effect_definition(effect, component_type="active")

    def test_nested_field_effects_are_validated(self):
        with self.assertRaisesRegex(ValueError, "效果关键词不存在"):
            validate_effect_definition({
                "effect_type": "create_field",
                "effect_data": {
                    "field_id": "test_field",
                    "effects": [{
                        "effect_type": "does_not_exist",
                        "effect_data": {},
                    }],
                },
            })

    def test_continuous_field_effect_must_be_modifier(self):
        with self.assertRaisesRegex(ValueError, "必须是Modifier"):
            validate_effect_definition({
                "effect_type": "create_field",
                "effect_data": {
                    "field_id": "test_field",
                    "effects": [{
                        "effect_type": "recover_resource",
                        "application_mode": "continuous",
                        "effect_target": {
                            "scope": "characters_in_field",
                            "relation": "all",
                        },
                        "effect_data": {
                            "resource_id": "hp",
                            "value": 5,
                        },
                    }],
                },
            })

    def test_current_content_catalogs_pass_strict_validation(self):
        validated = validate_content_catalogs()
        self.assertIn("basic_magic", validated)
        self.assertIn("class_skill", validated)
        self.assertTrue(validated["class_skill"])

    def test_next_battle_start_requires_battle_joined_event(self):
        component = {
            "component_id": "bad_wait",
            "type": "trigger",
            "trigger": {"event_type": "damage_received"},
            "limit": {"scope": "next_battle_start"},
            "effects": [{
                "effect_type": "recover_resource",
                "effect_data": {"resource_id": "hp", "value": 1},
            }],
        }
        with self.assertRaisesRegex(ValueError, "battle_joined"):
            validate_skill_components([component])

    def test_one_shot_lifecycle_maximum_is_fixed_to_one(self):
        component = {
            "component_id": "bad_maximum",
            "type": "trigger",
            "trigger": {"event_type": "test_event"},
            "limit": {"scope": "until_triggered", "maximum": 2},
            "effects": [{
                "effect_type": "recover_resource",
                "effect_data": {"resource_id": "hp", "value": 1},
            }],
        }
        with self.assertRaisesRegex(ValueError, "maximum必须为1"):
            validate_skill_components([component])


if __name__ == "__main__":
    unittest.main()
