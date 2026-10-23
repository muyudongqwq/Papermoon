"""Reference content must track real schemas and existing dictionary sections."""

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from core.catalog import ROOT
from SkillEditorClient.effect_options import FORM_EFFECT_TYPES as EFFECT_TYPES
from SkillEditorClient.effect_reference import DICTIONARY_PATH, dictionary_sections, read_dictionary, reference_text
from game.skill.effect_validation import EFFECT_SCHEMAS


class EffectReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Full development documentation is maintained separately from the
        # user-editable display copy; wording checks belong to the former.
        cls.dictionary = (ROOT / "game" / "skill" / "代码数据规范.txt").read_text(encoding="utf-8-sig")

    def test_client_dictionary_resolves_beside_client_module(self):
        self.assertEqual(DICTIONARY_PATH, ROOT / "SkillEditorClient" / "effect_dictionary.txt")
        self.assertEqual(read_dictionary(), DICTIONARY_PATH.read_text(encoding="utf-8-sig"))

    def test_client_display_copy_can_be_simplified_and_saved_with_utf8_bom(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "effect_dictionary.txt"
            path.write_text("1. damage\n---------\n\n自定义伤害说明。\n", encoding="utf-8-sig")
            with patch("SkillEditorClient.effect_reference.DICTIONARY_PATH", path):
                text = read_dictionary()
        self.assertFalse(text.startswith("\ufeff"))
        self.assertIn("自定义伤害说明", reference_text("damage", text))
        self.assertIn("尚无独立说明", reference_text("summon", text))

    def test_every_registered_effect_has_its_own_dictionary_description(self):
        sections = dictionary_sections(self.dictionary)
        self.assertEqual(set(sections), set(EFFECT_TYPES))
        self.assertTrue(all(sections.values()))
        self.assertIn("状态仓库", sections["add_status"])
        self.assertIn("before_lethal_damage", sections["prevent_death"])

    def test_decimal_and_shared_headings_are_associated_with_the_correct_effect(self):
        sections = dictionary_sections(self.dictionary)
        self.assertIn("临时MP", sections["grant_temporary_mp"])
        self.assertIn("source_field", sections["perception_check"])
        self.assertIn("互斥技能组", sections["switch_skill_set"])
        self.assertEqual(sections["add_content"], sections["remove_content"])
        self.assertNotIn("set_workshop", sections)

    def test_all_allowed_parameters_and_required_labels_are_present(self):
        for kind, schema in EFFECT_SCHEMAS.items():
            with self.subTest(effect=kind):
                text = reference_text(kind, self.dictionary)
                self.assertNotIn("尚无独立说明", text)
                self.assertEqual(text.count("[必填]"), len(schema.required_data))
                for key in schema.allowed_data:
                    self.assertIn(f"  {key}", text)

    def test_modifier_public_fields_are_separate_from_effect_data(self):
        text = reference_text("shield", self.dictionary)
        self.assertIn("effect 顶层", text)
        self.assertIn("duration", text)
        self.assertIn("stacking", text)
        self.assertNotIn("effect 顶层", reference_text("damage", self.dictionary))

    def test_empty_parameters_and_project_specific_choices_are_described(self):
        self.assertIn("空对象 {}", reference_text("observe_location", self.dictionary))
        text = reference_text("add_status", self.dictionary, {"status": {"user_poison": {}}})
        self.assertIn("编辑器候选值：user_poison", text)
        self.assertIn("条件必填", reference_text("damage", self.dictionary))


if __name__ == "__main__":
    unittest.main()
