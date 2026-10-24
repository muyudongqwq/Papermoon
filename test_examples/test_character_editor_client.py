"""Strict rank input, card identity allocation and standalone launch contracts."""

from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from core.catalog import BUILTINS, CatalogProject
from CharacterEditorClient.model import (
    parse_attribute, display_attribute, parse_fixed_rank, FIXED_RANK_CHOICES,
    next_card_id, new_card, validate_editor_card,
)
from game.character.servants import VALID_SERVANT_CLASSES
from SkillEditorClient.launcher import character_editor_command


class CharacterEditorModelTests(unittest.TestCase):
    def test_all_attribute_ranks_and_plus_counts_translate_exactly(self):
        for value, rank in enumerate(("E", "D", "C", "B", "A"), 1):
            for plus in range(3):
                text = rank + "+" * plus
                expected = {"value": value, "plus": plus} if plus else value
                self.assertEqual(parse_attribute(text), expected)
                self.assertEqual(display_attribute(expected), text)

    def test_invalid_attributes_are_rejected(self):
        for text in ("", "EX", "GM", "A+++", "C-", "3", "B +", "a", "F", "A＋"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_attribute(text)
        for value in (0, 6, 10, True, {"value": 3, "plus": 3}):
            with self.assertRaises(ValueError):
                display_attribute(value)

    def test_master_ids_start_at_ten_and_append_without_reusing_gaps(self):
        self.assertEqual(next_card_id("master", None, {}), "master10")
        self.assertEqual(next_card_id("master", None, {"master0": {}, "master10": {}, "master12": {}, "master_test_0": {}}), "master13")

    def test_servant_ids_use_all_current_legal_classes_and_independent_counters(self):
        for kind in VALID_SERVANT_CLASSES:
            prefix = kind.lower() + "_"
            self.assertEqual(next_card_id("servant", kind, {prefix + "12": {}, "master30": {}}), prefix + "13")
        with self.assertRaises(ValueError):
            next_card_id("servant", "Shielder", {})

    def test_fixed_ranks_allow_typed_gm_but_never_offer_it_in_the_dropdown(self):
        self.assertNotIn("GM", FIXED_RANK_CHOICES)
        self.assertEqual(parse_fixed_rank("GM", allow_plus=False), "GM")
        self.assertEqual(parse_fixed_rank("GM", allow_plus=True), "GM")
        self.assertEqual(parse_fixed_rank("A+", allow_plus=True), {"rank": "A", "plus": 1})
        for text, allow_plus in (("A+", False), ("A++", True), ("EX+", True), ("D", False)):
            with self.assertRaises(ValueError):
                parse_fixed_rank(text, allow_plus=allow_plus)

    def test_editor_limits_do_not_narrow_existing_engine_card_data(self):
        cards = deepcopy(BUILTINS["character_card"])
        catalogs = deepcopy(BUILTINS)
        data = new_card("master", None, cards)
        data["name"] = "Test"
        data["personal_skills"] = list(catalogs["personal_skill"])[:4]
        with self.assertRaises(ValueError):
            validate_editor_card(data, catalogs)
        data["personal_skills"] = data["personal_skills"][:3]
        self.assertEqual(validate_editor_card(data, catalogs), data)
        data["class_skills"] = [{"name": key, "rank": next(rank for rank, value in item["ranks"].items() if value)}
                                for key, item in list(catalogs["class_skill"].items())[:3]]
        with self.assertRaises(ValueError):
            validate_editor_card(data, catalogs)

    def test_source_launch_requires_the_sibling_editor_entry(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(sys, "frozen", False, create=True), patch("core.catalog.DATA_ROOT", Path(folder)):
            with self.assertRaises(FileNotFoundError):
                character_editor_command(Path(folder) / "catalog.json")
            entry = Path(folder) / "CharacterEditorClient" / "__main__.py"
            entry.parent.mkdir()
            entry.write_text("", encoding="utf-8")
            command = character_editor_command(Path(folder) / "catalog.json")
            self.assertEqual(command[1:3], ["-m", "CharacterEditorClient"])
            self.assertEqual(command[-2:], ["--catalog", str((Path(folder) / "catalog.json").resolve())])

    def test_master_rejects_class_skills_and_validates_basic_magic_references(self):
        data = new_card("master", None, {})
        data["name"] = "御主"
        data["class_skills"] = [{"name": "对魔力", "rank": "C"}]
        with self.assertRaisesRegex(ValueError, "御主没有职介技能"):
            validate_editor_card(data, BUILTINS)
        data["class_skills"] = []
        data["basic_magics"] = list(BUILTINS["basic_magic"])
        self.assertEqual(validate_editor_card(data, BUILTINS), data)
        data["basic_magics"] = ["healing", "healing"]
        with self.assertRaisesRegex(ValueError, "重复"):
            validate_editor_card(data, BUILTINS)
        data["basic_magics"] = ["missing"]
        with self.assertRaisesRegex(ValueError, "不在技能库"):
            validate_editor_card(data, BUILTINS)

    def test_frozen_launch_requires_sibling_exe_and_does_not_fall_back_to_python(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(Path(folder) / "SkillEditorClient.exe")):
            with self.assertRaises(FileNotFoundError):
                character_editor_command(Path(folder) / "catalog.json")
            executable = Path(folder) / "CharacterEditorClient beta 0.1.exe"
            executable.write_bytes(b"test-only-placeholder")
            command = character_editor_command(Path(folder) / "catalog.json")
            self.assertEqual(command[0], str(executable))
            self.assertNotIn("-m", command)


if __name__ == "__main__":
    unittest.main()
