"""Real Tk character forms, shared-library safety, and skill-editor integration."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from core.catalog import CatalogProject, BUILTINS
from game.character import create_character_from_card
from CharacterEditorClient.app import CharacterEditorClient
from CharacterEditorClient.dialogs import NewCardDialog
from CharacterEditorClient.model import new_card, display_attribute
from SkillEditorClient.app import SkillEditorClient
from SkillEditorClient.launcher import character_editor_command
from skilleditor.display import enable_high_dpi


class CharacterEditorSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        enable_high_dpi()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "catalog.json"
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.callbacks = Mock()
        self.root.report_callback_exception = self.callbacks
        self.addCleanup(self.callbacks.assert_not_called)
        error_patch = patch("CharacterEditorClient.app.messagebox.showerror")
        self.errors = error_patch.start()
        self.addCleanup(error_patch.stop)
        self.app = CharacterEditorClient(self.root, CatalogProject(self.path))
        self.root.update()

    def new(self, kind="master", servant_class=None):
        with patch("CharacterEditorClient.app.ask_new_card", return_value=(kind, servant_class)):
            self.app.new()
        form = self.app.form
        form.name.set("测试角色")
        for variable in form.attributes.values():
            variable.set("C")
        return form

    def test_existing_cards_round_trip_with_nobles_preserved(self):
        self.assertIn("beta 0.1", self.root.title())
        self.assertEqual(set(self.app.items.values()), set(BUILTINS["character_card"]))
        for key, data in BUILTINS["character_card"].items():
            self.app.load(key)
            self.assertEqual(self.app.form.read(), data)
            self.assertFalse(self.app.dirty())
            self.assertFalse(hasattr(self.app.form, "card_id_entry"))
            self.assertFalse(hasattr(self.app.form, "id_label"))
            self.assertFalse(hasattr(self.app.form, "command_spell"))
        self.assertTrue(all("[" not in self.app.tree.item(node, "text") for node in self.app.items))

    def test_new_master_has_generated_id_blank_attributes_and_default_command_spells(self):
        with patch("CharacterEditorClient.app.ask_new_card", return_value=("master", None)):
            self.app.new()
        self.assertEqual(self.app.current, "master10")
        self.assertTrue(all(value.get() == "" for value in self.app.form.attributes.values()))
        self.assertEqual(self.app.form.original["command_spell"], 3)
        self.assertFalse(self.app.save())
        self.assertFalse(self.path.exists())
        self.app.form.name.set("御主")
        for variable in self.app.form.attributes.values():
            variable.set("C")
        self.app.form.attributes["magic"].set("A++")
        self.assertTrue(self.app.save())
        with self.app.project.activate():
            actor = create_character_from_card("master10")
            self.assertEqual((actor.magic.base_value, actor.magic.base_plus), (5, 2))

    def test_new_servant_and_all_attribute_plus_values_save_and_create(self):
        form = self.new("servant", "Archer")
        self.assertEqual(self.app.current, "archer_10")
        form.attributes["strength"].set("C+")
        form.rank.set("A+")
        self.assertNotIn("GM", form.rank_box.cget("values"))
        self.assertTrue(self.app.save())
        with self.app.project.activate():
            actor = create_character_from_card("archer_10")
            self.assertEqual((actor.strength.base_value, actor.strength.base_plus), (3, 1))
            self.assertEqual(actor.servant_class, "Archer")
        form = self.new("servant", "Archer")
        self.assertEqual(self.app.current, "archer_11")

    def test_typed_gm_is_valid_for_talent_and_noble_but_not_basic_attributes(self):
        for kind, servant_class in (("master", None), ("servant", "Saber")):
            form = self.new(kind, servant_class)
            form.rank.set("GM")
            self.assertNotIn("GM", form.rank_box.cget("values"))
            self.assertTrue(self.app.save())
            for text in ("GM", "EX", "A+++", "7"):
                self.app.form.attributes["magic"].set(text)
                old = self.path.read_bytes()
                self.assertFalse(self.app.save())
                self.assertEqual(self.path.read_bytes(), old)
            self.app.form.attributes["magic"].set("C")
            self.assertTrue(self.app.save())

    def test_class_skill_library_shows_all_available_skills_and_limits_to_two(self):
        form = self.new("servant", "Archer")
        self.assertEqual(set(form.classes.rows), set(self.app.project.effective()["class_skill"]))
        keys = list(form.classes.rows)
        for key in keys[:2]:
            form.classes.rows[key]["button"].invoke()
        third = form.classes.rows[keys[2]]
        self.assertEqual(str(third["button"].cget("state")), "disabled")
        third["button"].invoke()
        self.assertEqual(len(form.classes.read()), 2)
        self.assertTrue(self.app.save())
        saved = self.app.form.read()["class_skills"]
        self.assertEqual(len(saved), 2)
        with self.app.project.activate():
            actor = create_character_from_card("archer_10")
            self.assertEqual(len(actor.class_skills), 2)

    def test_master_selects_basic_magic_instead_of_class_skills_and_saves_to_core(self):
        form = self.new()
        self.assertIsNone(form.classes)
        self.assertEqual(set(form.basic.rows), set(self.app.project.effective()["basic_magic"]))
        for key in ("healing", "workshop", "familiar"):
            form.basic.rows[key]["button"].invoke()
        self.assertTrue(self.app.save())
        self.assertEqual(self.app.form.basic.read(), ["healing", "workshop", "familiar"])
        self.assertEqual(self.app.form.read()["class_skills"], [])
        with self.app.project.activate():
            actor = create_character_from_card("master10")
            self.assertEqual({skill.skill_id for skill in actor.magic_skill},
                             {"basic_magic:healing", "basic_magic:workshop", "basic_magic:familiar"})

    def test_compact_rank_boxes_hidden_command_spells_and_kind_specific_placeholders(self):
        form = self.new()
        for box in [*form.attribute_boxes.values(), form.rank_box]:
            self.assertEqual(box.cget("width"), 7)
            self.assertFalse(int(box.pack_info()["expand"]))
        self.assertEqual(form.placeholder.cget("text"), "礼装（预留）")
        data = form.read()
        data["command_spell"] = 2
        self.app.load(data["card_id"], data)
        self.assertEqual(self.app.form.read()["command_spell"], 2)
        self.assertFalse(hasattr(self.app.form, "command_spell"))
        self.assertIs(self.app.new_button.master.master, self.app.tree.master.master)
        with patch.object(self.app, "leave", return_value=True):
            servant = self.new("servant", "Saber")
        self.assertEqual(servant.placeholder.cget("text"), "宝具（预留）")
        self.assertIsNone(servant.basic)

    def test_basic_magic_library_refresh_keeps_selection_and_incomplete_attributes(self):
        form = self.new()
        form.basic.rows["healing"]["button"].invoke()
        form.attributes["magic"].set("unfinished")
        fresh = CatalogProject(self.path)
        extra = deepcopy(fresh.effective()["basic_magic"]["healing"])
        extra.update(skill_id="basic_magic:extra", name="新增基础魔术")
        fresh.put("basic_magic", "extra", extra)
        fresh.save()
        self.assertTrue(self.app.reload_library())
        self.assertEqual(form.attributes["magic"].get(), "unfinished")
        self.assertEqual(form.basic.read(), ["healing"])
        self.assertIn("extra", form.basic.rows)
        form.attributes["magic"].set("B")
        self.assertTrue(self.app.save())

    def test_personal_skill_library_limits_to_three_and_model_catches_bypass(self):
        form = self.new()
        rows = list(form.personal.rows.values())
        for row in rows[:3]:
            row["button"].invoke()
        self.assertEqual(str(rows[3]["button"].cget("state")), "disabled")
        rows[3]["selected"].set(True)
        self.assertFalse(self.app.save())
        rows[3]["selected"].set(False)
        self.assertTrue(self.app.save())

    def test_new_dialog_requires_class_for_servant_and_never_asks_for_id(self):
        dialog = NewCardDialog(self.root)
        dialog.kind.set("Servant")
        with patch("CharacterEditorClient.dialogs.messagebox.showerror") as error:
            dialog.accept()
            self.assertTrue(dialog.winfo_exists())
            error.assert_called_once()
        dialog.servant_class.set("Caster")
        dialog.accept()
        self.assertEqual(dialog.result, ("servant", "Caster"))

    def test_reload_library_retains_incomplete_draft_and_selected_skills(self):
        form = self.new()
        first = next(iter(form.personal.rows))
        form.personal.rows[first]["button"].invoke()
        form.attributes["magic"].set("unfinished")
        fresh = CatalogProject(self.path)
        extra = deepcopy(next(iter(fresh.effective()["personal_skill"].values())))
        extra.update(skill_id="user_new_library_skill", name="新库技能")
        fresh.put("personal_skill", extra["skill_id"], extra)
        fresh.save()
        self.assertTrue(self.app.reload_library())
        self.assertEqual(form.attributes["magic"].get(), "unfinished")
        self.assertTrue(form.personal.rows[first]["selected"].get())
        self.assertIn(extra["skill_id"], form.personal.rows)
        form.attributes["magic"].set("B")
        self.assertTrue(self.app.save())
        self.assertIn(extra["skill_id"], CatalogProject(self.path).data["personal_skill"])

    def test_concurrent_changes_are_not_overwritten_and_reload_updates_new_ids(self):
        self.new()
        other = CatalogProject(self.path)
        card = new_card("master", None, other.effective()["character_card"])
        card["name"] = "另一张角色卡"
        other.put("character_card", "master10", card)
        other.save()
        self.assertFalse(self.app.save())
        self.assertTrue(self.app.reload_library())
        self.assertEqual(self.app.current, "master11")
        self.assertEqual(self.app.form.name.get(), "测试角色")
        self.assertTrue(self.app.save())
        cards = CatalogProject(self.path).data["character_card"]
        self.assertEqual(cards["master10"]["name"], "另一张角色卡")
        self.assertEqual(cards["master11"]["name"], "测试角色")

    def test_edit_conflict_on_current_card_keeps_draft_and_saved_bytes(self):
        form = self.new()
        self.assertTrue(self.app.save())
        self.app.form.name.set("我的草稿")
        other = CatalogProject(self.path)
        changed = other.effective()["character_card"]["master10"]
        changed["name"] = "其他窗口修改"
        other.put("character_card", "master10", changed)
        other.save()
        saved = self.path.read_bytes()
        self.assertFalse(self.app.reload_library())
        self.assertFalse(self.app.save())
        self.assertEqual(self.app.form.name.get(), "我的草稿")
        self.assertEqual(self.path.read_bytes(), saved)

    def test_save_backup_and_delete_custom_card(self):
        self.new()
        self.assertTrue(self.app.save())
        previous = self.path.read_bytes()
        self.app.form.name.set("修改后的角色")
        self.assertTrue(self.app.save())
        self.assertEqual(self.path.with_suffix(".json.bak").read_bytes(), previous)
        with patch("CharacterEditorClient.app.messagebox.askyesno", return_value=True):
            self.app.remove()
        self.assertIsNone(self.app.form)
        self.assertNotIn("master10", CatalogProject(self.path).effective()["character_card"])

    def test_skill_editor_hides_cards_and_launches_sibling_or_reports_missing(self):
        top = tk.Toplevel(self.root)
        top.withdraw()
        self.addCleanup(top.destroy)
        app = SkillEditorClient(top, CatalogProject(self.path))
        self.assertNotIn("试验", top.title())
        self.assertNotIn("试验", app.notebook.tab(app.form_tab, "text"))
        self.assertTrue(all(category != "character_card" for category, key in app.items.values()))
        self.assertNotIn("御主卡", app.kind.cget("values"))
        self.assertNotIn("从者卡", app.kind.cget("values"))
        with patch("SkillEditorClient.app.subprocess.Popen") as launch:
            app.character_editor_button.invoke()
            self.assertEqual(launch.call_args.args[0][-2:], ["--catalog", str(self.path)])
            self.assertEqual(launch.call_args.kwargs["creationflags"], subprocess.CREATE_NO_WINDOW)
        with patch("SkillEditorClient.launcher.character_editor_command", side_effect=FileNotFoundError("未找到角色卡编辑器")), patch("SkillEditorClient.app.subprocess.Popen") as launch:
            self.assertFalse(app.launch_character_editor())
            launch.assert_not_called()
            self.errors.assert_called()

    def test_source_child_runs_without_console_and_reports_version(self):
        output = Path(self.directory.name) / "installation.json"
        command = [*character_editor_command(self.path), "--check-installation", str(output)]
        result = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
        self.assertEqual(result.returncode, 0)
        diagnostic = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(diagnostic["version"], "beta 0.1")
        self.assertEqual(set(diagnostic["cards"]), set(BUILTINS["character_card"]))
        script_output = Path(self.directory.name) / "double click diagnostic.json"
        script = Path(__file__).resolve().parents[1] / "Start_CharacterEditorClient.vbs"
        result = subprocess.run(["cscript.exe", "//nologo", str(script), "--check-installation", str(script_output)],
                                cwd=Path(self.directory.name), creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
        self.assertEqual(result.returncode, 0)
        deadline = time.monotonic() + 10
        while not script_output.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(script_output.exists())
        self.assertEqual(json.loads(script_output.read_text(encoding="utf-8"))["version"], "beta 0.1")


if __name__ == "__main__":
    unittest.main()
