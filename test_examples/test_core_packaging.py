"""Executable packaging boundaries: shared rules, isolated editing, saved runs."""

import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import random
import tempfile
import unittest

from game.character import create_character_from_card
from game.character.card_data import CHARACTER_CARD_DATA
from core.catalog import BUILTINS, CatalogProject, LIVE_CATALOGS, parse_json
from core.__main__ import run_manual
from core.scenarios import create_manual_scenario
from skilleditor.documents import KINDS, copy_definition, format_json, new_definition, parse_entry


class CorePackagingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        self.project = CatalogProject(self.folder / "catalog.json")
        self.log = io.StringIO()
        self.redirect = contextlib.redirect_stdout(self.log)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)

    def skill(self, key="user_skill"):
        return new_definition("固有技能", key)

    def test_facade_reexports_same_rule_objects(self):
        from core import GameLoop, GameManager, GameSession
        from game.game.game_loop import GameLoop as OriginalLoop
        from game.game.game_manager import GameManager as OriginalManager
        from game.game.game_session import GameSession as OriginalSession
        self.assertIs(GameLoop, OriginalLoop)
        self.assertIs(GameManager, OriginalManager)
        self.assertIs(GameSession, OriginalSession)

    def test_missing_project_uses_builtins_without_creating_a_file(self):
        self.assertEqual(self.project.effective(), BUILTINS)
        self.assertEqual(self.project.validate()["character_card"], 2)
        self.assertFalse(self.project.path.exists())

    def test_each_editor_template_can_be_validated_and_loaded(self):
        for index, (kind, category) in enumerate(KINDS.items()):
            key = f"user_{index}"
            self.project.put(category, key, new_definition(kind, key))
        with self.project.activate():
            master = create_character_from_card("user_3")
            servant = create_character_from_card("user_4", master=master)
            master.load_content("basic_magic", "user_1")
            servant.load_content("noble_phantasm", "user_2")
            self.assertEqual(len(servant.noble_phantasms), 1)
            self.assertEqual(len(master.magic_skill), 1)

    def test_custom_skill_attached_to_card_uses_the_original_rule_runtime(self):
        self.project.put("personal_skill", "user_skill", self.skill())
        card = new_definition("御主卡", "user_card")
        card["personal_skills"] = ["user_skill"]
        self.project.put("character_card", "user_card", card)
        with self.project.activate():
            actor = create_character_from_card("user_card")
            atk, ap = actor.atk, actor.action_point
            actor.resolve_skill_component("user_skill", "active", target=actor, turn_number=1)
            self.assertEqual(actor.atk, atk + 5)
            self.assertEqual(actor.action_point, ap - 1)
        self.assertNotIn("user_card", CHARACTER_CARD_DATA)

    def test_invalid_effect_rolls_back_project_and_global_catalogs(self):
        old = deepcopy(self.project.data)
        catalogs = deepcopy(LIVE_CATALOGS)
        definition = self.skill()
        definition["components"][0]["effects"][0]["effect_type"] = "unknown_effect"
        with self.assertRaises(ValueError):
            self.project.put("personal_skill", "user_skill", definition)
        self.assertEqual(self.project.data, old)
        self.assertEqual(LIVE_CATALOGS, catalogs)
        self.assertFalse(self.project.path.exists())

    def test_referenced_custom_skill_cannot_be_deleted(self):
        self.project.put("personal_skill", "user_skill", self.skill())
        card = new_definition("御主卡", "user_card")
        card["personal_skills"] = ["user_skill"]
        self.project.put("character_card", "user_card", card)
        with self.assertRaises(ValueError):
            self.project.remove_override("personal_skill", "user_skill")
        self.assertIn("user_skill", self.project.data["personal_skill"])

    def test_builtin_override_is_scoped_and_exception_restores_globals(self):
        card = deepcopy(BUILTINS["character_card"]["master_test_0"])
        card["name"] = "Edited"
        self.project.put("character_card", "master_test_0", card)
        with self.assertRaisesRegex(RuntimeError, "test"):
            with self.project.activate():
                self.assertEqual(create_character_from_card("master_test_0").name, "Edited")
                raise RuntimeError("test")
        self.assertEqual(CHARACTER_CARD_DATA["master_test_0"], BUILTINS["character_card"]["master_test_0"])
        self.project.remove_override("character_card", "master_test_0")
        self.assertEqual(self.project.effective()["character_card"]["master_test_0"], BUILTINS["character_card"]["master_test_0"])

    def test_save_reload_and_backup_preserve_previous_valid_project(self):
        self.project.save()
        original = self.project.path.read_bytes()
        self.project.put("personal_skill", "user_skill", self.skill())
        self.project.save()
        self.assertEqual(self.project.path.with_suffix(".json.bak").read_bytes(), original)
        self.assertEqual(CatalogProject(self.project.path).data, self.project.data)
        self.assertEqual(list(self.folder.glob(".catalog-*.tmp")), [])

    def test_external_edit_conflict_is_detected_before_overwrite(self):
        self.project.save()
        other = CatalogProject(self.project.path)
        other.put("personal_skill", "user_skill", self.skill())
        other.save()
        written = self.project.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "其他程序"):
            self.project.save()
        self.assertEqual(self.project.path.read_bytes(), written)

    def test_invalid_saved_project_and_duplicate_json_fields_are_rejected(self):
        for text in ('{"key":1,"key":2}', '{"key":NaN}', '{"key":Infinity}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_json(text)
        self.project.path.write_text('{"format_version":1}', encoding="utf-8")
        with self.assertRaises(ValueError):
            CatalogProject(self.project.path)

    def test_id_mismatch_is_rejected_and_effective_data_is_detached(self):
        with self.assertRaises(ValueError):
            self.project.put("personal_skill", "different", self.skill())
        effective = self.project.effective()
        effective["character_card"]["master_test_0"]["name"] = "Mutated"
        self.assertNotEqual(self.project.effective(), effective)

    def test_export_and_copy_keep_template_identity_correct(self):
        data = copy_definition("basic_magic", "user_magic", new_definition("基础魔术", "source"))
        self.assertEqual(data["skill_id"], "basic_magic:user_magic")
        entry = {"category": "basic_magic", "entry_id": "user_magic", "definition": data}
        self.assertEqual(parse_entry(format_json(entry)), entry)
        with self.assertRaises(ValueError):
            parse_entry(format_json(data))

    def test_battle_and_map_presets_use_official_card_stats_and_relationships(self):
        for mode in ("battle", "map"):
            game = create_manual_scenario(mode)
            self.assertEqual(len(game.characters), 4)
            a, nero_a, b, nero_b = game.characters
            self.assertIs(nero_a.master, a)
            self.assertIs(nero_b.master, b)
            self.assertNotEqual(a.name, b.name)
            self.assertEqual(nero_a.hpmax, create_character_from_card("servant_test_0").hpmax)
            self.assertEqual(a.position is b.position, mode == "battle")
            self.assertEqual(len(game.game_map.locations), 3)

    def test_quit_creates_readable_transcript_journal_summary_and_catalog(self):
        random_state = random.getstate()
        result, folder = run_manual(self.project, log_root=self.folder / "runs", seed=42,
                                   input_func=lambda prompt: "quit")
        self.assertEqual(random_state, random.getstate())
        self.assertEqual(result["reason"], "manual_quit")
        summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["seed"], 42)
        self.assertEqual(len(summary["characters"]), 4)
        self.assertIn("quit", (folder / "terminal.txt").read_text(encoding="utf-8"))
        full = json.loads((folder / "reports.json").read_text(encoding="utf-8"))
        lines = [json.loads(line) for line in (folder / "reports.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(full, lines)
        CatalogProject(folder / "catalog.json").validate()

    def test_eof_and_keyboard_interrupt_are_clean_manual_exits(self):
        for exception, reason in ((EOFError, "end_of_input"), (KeyboardInterrupt, "manual_interrupt")):
            def command(_prompt):
                raise exception()
            result, folder = run_manual(self.project, scenario="map", log_root=self.folder / "runs", seed=1, input_func=command)
            self.assertEqual(result["reason"], reason)
            self.assertIsNone(json.loads((folder / "summary.json").read_text(encoding="utf-8"))["error"])

    def test_engine_failure_keeps_diagnostics_and_restores_catalog(self):
        def command(_prompt):
            raise RuntimeError("diagnostic marker")
        with self.assertRaisesRegex(RuntimeError, "diagnostic marker"):
            run_manual(self.project, log_root=self.folder / "runs", seed=1, input_func=command)
        folder = next((self.folder / "runs").iterdir())
        self.assertIn("diagnostic marker", (folder / "error.txt").read_text(encoding="utf-8"))
        self.assertTrue((folder / "summary.json").exists())
        self.assertEqual(LIVE_CATALOGS, {key: BUILTINS[key] for key in LIVE_CATALOGS})


if __name__ == "__main__":
    unittest.main()
