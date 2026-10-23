"""Headless form conversion checks; real widgets are tested separately."""

import unittest
from pathlib import Path
import sys
from unittest.mock import patch

from SkillEditorClient.launcher import core_command

from SkillEditorClient.model import (
    PHASES, PHASE_LABELS, TARGETS, TARGET_DESCRIPTIONS, can_use_form, cost_value, merge_extras, new_client_definition,
    resource_options, validate_component_fields, new_skill_key, new_personal_skill_key,
)
from game.action.action_data import ACTION_PHASES, TARGET_TYPES


class SkillEditorClientModelTests(unittest.TestCase):
    def test_frozen_core_uses_executable_dispatch_instead_of_python_switches(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", "C:/Papermoon/SkillEditorClient.exe"):
            command = core_command(Path("C:/Papermoon/userdata/catalog.json"))
        self.assertEqual(command[:2], ["C:/Papermoon/SkillEditorClient.exe", "--run-core"])
        self.assertNotIn("-m", command)
        self.assertIn("--pause-on-exit", command)

    def test_source_core_uses_console_python(self):
        with patch.object(sys, "frozen", False, create=True), patch.object(sys, "executable", "C:/Python/pythonw.exe"):
            command = core_command(Path("catalog.json"))
        self.assertEqual(Path(command[0]).name, "python.exe")
        self.assertEqual(command[1:3], ["-m", "core"])

    def test_phase_and_target_options_match_engine(self):
        self.assertEqual(set(PHASES), ACTION_PHASES)
        self.assertEqual(set(TARGETS), TARGET_TYPES)

    def test_chinese_phase_labels_and_target_explanations_cover_engine_options(self):
        self.assertEqual(set(PHASE_LABELS), set(PHASES))
        self.assertTrue(all(isinstance(text, str) and text for text in PHASE_LABELS.values()))
        self.assertEqual(set(TARGET_DESCRIPTIONS), set(TARGETS) | {"event_actor", "event_source", "event_target", "event_targets"})

    def test_new_skills_start_without_units_costs_or_effects(self):
        for kind in ("固有技能", "基础魔术", "宝具"):
            with self.subTest(kind=kind):
                definition = new_client_definition(kind, "user_example", name="火焰", rank="B")
                self.assertEqual(definition["skill_id"], "basic_magic:user_example" if kind == "基础魔术" else "user_example")
                self.assertEqual(definition["components"], [])
                self.assertEqual(definition["name"], "火焰")
                self.assertEqual(definition["rank"], "B")
                self.assertEqual(definition["description"], "")

    def test_generated_skill_ids_handle_same_names_without_overwriting(self):
        self.assertEqual(new_skill_key(" 火焰 ", " B ", {}), "user_火焰_B")
        self.assertEqual(new_skill_key("火焰", "B", {"user_火焰_B": {}, "user_火焰_B_2": {}}), "user_火焰_B_3")

    def test_personal_skill_numbers_reserve_tests_and_append_after_maximum(self):
        self.assertEqual(new_personal_skill_key({}), "10")
        self.assertEqual(new_personal_skill_key({"0": {}, "9": {}, "master_test_0:test": {}}), "10")
        self.assertEqual(new_personal_skill_key({"10": {}, "100": {}, "12": {}}), "101")
        self.assertEqual(new_personal_skill_key({"10": {}, "12": {}}), "13")

    def test_class_template_is_unchanged(self):
        from skilleditor.documents import new_definition
        self.assertEqual(new_client_definition("职介技能", "测试"), new_definition("职介技能", "测试"))

    def test_ap_resource_requires_either_map_phase(self):
        for phases in ([], ["attack_phase"], ["defense_phase", "turn_end"]):
            self.assertNotIn("action_point", resource_options(phases))
        for phases in (["AP1"], ["AP2"], ["attack_phase", "AP1"]):
            self.assertIn("action_point", resource_options(phases))

    def test_cost_numbers_and_input_expression_survive(self):
        self.assertEqual(cost_value("10"), 10)
        self.assertEqual(cost_value("1.5"), 1.5)
        self.assertEqual(cost_value('{"input_id":"x","multiplier":2}'), {"input_id": "x", "multiplier": 2})

    def test_bad_cost_cannot_be_saved_as_text(self):
        for value in ("", "ten", "true", "-1", "[]", '"10"', "NaN", '{"wrong":1}'):
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                cost_value(value)

    def test_advanced_fields_cannot_override_a_form_field(self):
        self.assertEqual(merge_extras('{"cost_id":"skill:example"}', {"resource", "value"}, "消耗"),
                         {"cost_id": "skill:example"})
        with self.assertRaises(ValueError):
            merge_extras('{"value":99}', {"resource", "value"}, "消耗")

    def test_typed_ap_resource_is_rejected_without_ap_phase(self):
        component = {"component_id": "active", "type": "active", "available_phases": ["attack_phase"],
                     "target": "self", "cost": [{"resource": "action_point", "value": 1}]}
        with self.assertRaisesRegex(ValueError, "action_point"):
            validate_component_fields(component)

    def test_blank_component_id_needs_user_input(self):
        component = {"component_id": "", "type": "active"}
        with self.assertRaisesRegex(ValueError, "component_id"):
            validate_component_fields(component)

    def test_malformed_imports_fall_back_to_json(self):
        for definition in ({}, {"skill_id": "x", "components": None},
                           {"skill_id": "x", "components": [None]},
                           {"skill_id": "x", "components": [{"component_id": ""}]},
                           {"skill_id": "x", "components": [{"available_phases": "AP1"}]},
                           {"skill_id": "x", "components": [{"cost": [None]}]}):
            with self.subTest(definition=definition):
                self.assertFalse(can_use_form(definition))
        self.assertTrue(can_use_form(new_client_definition("固有技能", "example")))

    def test_malformed_choice_structures_remain_repairable_in_json(self):
        for choices in (None, [], {"options": {}}, {"allow_duplicate": "false"},
                        {"options": [None]}, {"options": [{"choice_id": ""}]},
                        {"options": [{"choice_id": "x", "effects": [None]}]},
                        {"options": [{"choice_id": "x", "name": 1}]},
                        {"options": [{"choice_id": "x", "additional_cost": {}}]}):
            with self.subTest(choices=choices):
                definition = {"skill_id": "x", "components": [{"component_id": "unit_0", "choices": choices}]}
                self.assertFalse(can_use_form(definition))
