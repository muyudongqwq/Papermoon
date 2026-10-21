"""Editable class catalogs keep ranked loading and old projects compatible."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from game.character import create_character_from_card
from core.catalog import BUILTINS, CatalogProject, empty_project
from game.skill.class_skill_data import CLASS_SKILL_DATA
from skilleditor.documents import copy_definition, format_json, new_definition, parse_entry


class ClassSkillEditorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "catalog.json"
        self.project = CatalogProject(self.path)
        self.original_classes = deepcopy(CLASS_SKILL_DATA)

    def add_class(self):
        definition = new_definition("职介技能", "测试职介")
        definition["ranks"]["A"] = deepcopy(definition["ranks"]["C"])
        definition["ranks"]["A"][0]["effects"][0]["effect_data"]["value"] = 15
        self.project.put("class_skill", "测试职介", definition)

    def add_card(self, rank="C", *, kind="从者卡"):
        card = new_definition(kind, "test_class_card")
        card["class_skills"] = [{"name": "测试职介", "rank": rank}]
        self.project.put("character_card", "test_class_card", card)

    def test_ranked_passive_is_loaded_as_class_skill_and_applied_once(self):
        self.add_class()
        self.add_card("A")
        with self.project.activate():
            actor = create_character_from_card("test_class_card")
            self.assertEqual(len(actor.class_skills), 1)
            self.assertEqual(actor.class_skills[0].skill_id, "class:测试职介")
            self.assertEqual(actor.class_skills[0].rank_name, "A")
            # A blank card has strength C, hence base ATK 30.
            self.assertEqual(actor.atk, 45)
            self.assertEqual(len([modifier for modifier in actor.modifiers if modifier.effect_type == "attack_bonus"]), 1)
        self.assertEqual(CLASS_SKILL_DATA, self.original_classes)

    def test_master_card_can_also_load_ranked_class_content(self):
        self.add_class()
        self.add_card(kind="御主卡")
        with self.project.activate():
            actor = create_character_from_card("test_class_card")
            self.assertEqual(actor.class_skills[0].source_type, "class_skill")
            self.assertEqual(actor.atk, 35)

    def test_old_four_directory_project_upgrades_without_writing_until_save(self):
        legacy = empty_project()
        del legacy["class_skill"]
        self.path.write_text(format_json(legacy), encoding="utf-8")
        original = self.path.read_bytes()
        loaded = CatalogProject(self.path)
        self.assertEqual(loaded.data["class_skill"], {})
        self.assertEqual(self.path.read_bytes(), original)
        loaded.save()
        self.assertEqual(self.path.with_suffix(".json.bak").read_bytes(), original)
        self.assertEqual(CatalogProject(self.path).data, loaded.data)

    def test_save_reopen_and_export_preserve_all_ranks(self):
        self.add_class()
        self.add_card("A")
        self.project.save()
        loaded = CatalogProject(self.path)
        self.assertEqual(loaded.data, self.project.data)
        definition = loaded.data["class_skill"]["测试职介"]
        entry = {"category": "class_skill", "entry_id": "测试职介", "definition": definition}
        self.assertEqual(parse_entry(format_json(entry)), entry)
        copied = copy_definition("class_skill", "另一个职介", definition)
        self.assertEqual(copied["name"], "另一个职介")
        loaded.put("class_skill", "另一个职介", copied)

    def test_referenced_class_or_rank_cannot_be_removed(self):
        self.add_class()
        self.add_card("A")
        previous = deepcopy(self.project.data)
        with self.assertRaises(ValueError):
            self.project.remove_override("class_skill", "测试职介")
        definition = deepcopy(previous["class_skill"]["测试职介"])
        del definition["ranks"]["A"]
        with self.assertRaises(ValueError):
            self.project.put("class_skill", "测试职介", definition)
        self.assertEqual(self.project.data, previous)

    def test_invalid_name_rank_components_or_effects_do_not_change_global_rules(self):
        valid = new_definition("职介技能", "测试职介")
        mutations = [lambda data: data.update(name="另一个名字"),
                     lambda data: data.update(ranks={}),
                     lambda data: data.update(ranks={"A+": data["ranks"]["C"]}),
                     lambda data: data.update(ranks={"C": []}),
                     lambda data: data.update(ranks={"C": "invalid"}),
                     lambda data: data["ranks"]["C"][0]["effects"][0].update(effect_type="unknown")]
        for mutation in mutations:
            definition = deepcopy(valid)
            mutation(definition)
            with self.subTest(definition=definition), self.assertRaises((TypeError, ValueError)):
                self.project.put("class_skill", "测试职介", definition)
            self.assertEqual(CLASS_SKILL_DATA, self.original_classes)
            self.assertEqual(self.project.data["class_skill"], {})

    def test_builtin_override_restore_and_exception_leave_no_catalog_changes(self):
        definition = deepcopy(BUILTINS["class_skill"]["对魔力"])
        definition["ranks"]["C"][0]["effects"][0]["effect_data"]["value"] = 0.9
        self.project.put("class_skill", "对魔力", definition)
        with self.assertRaises(RuntimeError):
            with self.project.activate():
                actor = create_character_from_card("servant_test_0")
                actor.add_class_skill("对魔力", "C")
                self.assertEqual(actor.magic_resistance, 0.9)
                raise RuntimeError("test")
        self.assertEqual(CLASS_SKILL_DATA, self.original_classes)
        self.project.remove_override("class_skill", "对魔力")
        self.assertEqual(self.project.effective()["class_skill"]["对魔力"], BUILTINS["class_skill"]["对魔力"])


if __name__ == "__main__":
    unittest.main()
