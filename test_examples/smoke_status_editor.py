"""Real Tk status forms, lossless JSON fallback, and engine integration."""

from copy import deepcopy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from core.catalog import CatalogProject
from game.character.masters import Master
from game.game.game_manager import GameManager
from game.map.map import Location
from game.skill.skill import Skill
from game.skill.skill_runtime import apply_skill_effect
from game.status.data import STATUS_DATA
from SkillEditorClient.app import SkillEditorClient
from SkillEditorClient.condition_model import CONDITION_NAMES
from SkillEditorClient.status_form import (
    StatusForm, STATUS_TYPES, SCOPES, STACK_RULES, REFRESH_RULES, can_use_status_form,
)
from SkillEditorClient.trigger_editor import EVENT_OPTIONS
from SkillEditorClient.widgets import Collapsible
from skilleditor.display import enable_high_dpi
from skilleditor.documents import format_json


class StatusEditorSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        enable_high_dpi()

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "catalog.json"
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.callbacks = Mock()
        self.root.report_callback_exception = self.callbacks
        self.app = SkillEditorClient(self.root, CatalogProject(self.path))
        self.dialog = patch("SkillEditorClient.app.messagebox.showerror").start()
        self.addCleanup(patch.stopall)
        self.addCleanup(self.callbacks.assert_not_called)
        self.root.update()

    @staticmethod
    def set_json(box, value):
        if hasattr(box, "show_json"):
            box.show_json()
        box.text.delete("1.0", "end")
        box.text.insert("1.0", format_json(value))

    def load_marker(self):
        self.app.load("status", "user_status", {"status_id": "user_status", "name": "测试状态", "components": []})
        return self.app.form

    def toggle(self, enabled):
        self.app.status_forms_enabled.set(enabled)
        self.app.toggle_status_forms()

    def test_all_builtins_round_trip_without_changes_and_start_collapsed(self):
        def groups(widget):
            for child in widget.winfo_children():
                if isinstance(child, Collapsible):
                    yield child
                yield from groups(child)
        for key, original in STATUS_DATA.items():
            with self.subTest(key=key):
                self.app.load("status", key)
                self.assertIsInstance(self.app.form, StatusForm)
                self.assertEqual(self.app.definition(), original)
                self.assertFalse(self.app.dirty())
                self.assertTrue(all(not group.expanded for group in groups(self.app.form)))
                self.assertFalse(hasattr(self.app.form, "rank"))
        self.app.load("status", "burning")
        window = self.app.open_effect_reference()
        self.assertEqual(window.current_effect, "damage")

    def test_new_status_is_an_unsaved_empty_marker_and_can_be_saved(self):
        self.app.kind.set("状态")
        with patch("SkillEditorClient.app.simpledialog.askstring", return_value="user_status"):
            self.app.new()
        self.assertIsInstance(self.app.form, StatusForm)
        self.assertEqual(self.app.form.components, [])
        self.assertTrue(self.app.dirty())
        self.assertFalse(self.path.exists())
        self.assertTrue(self.app.save())
        self.assertEqual(CatalogProject(self.path).data["status"]["user_status"]["components"], [])

    def test_burning_edits_save_reload_and_execute_per_source_stacks(self):
        self.app.load("status", "burning")
        form = self.app.form
        form.duration.set("2")
        form.stacking.maximum.set("4")
        effect = form.components[0].effects[0]
        self.set_json(effect.data, {"damage_type": "magic", "value_source": "status_stack_count", "multiplier": 14})
        self.assertTrue(self.app.save())
        project = CatalogProject(self.path)
        self.assertEqual(project.data["status"]["burning"]["duration"], 2)
        self.assertEqual(self.app.form.components[0].effects[0].read()["effect_data"]["multiplier"], 14)
        with project.activate(), contextlib.redirect_stdout(io.StringIO()):
            caster, target = [Master(name, 3, 3, 3, 3, 3, "C", 3) for name in ("Caster", "Target")]
            location = Location("A")
            caster.position = target.position = location
            game = GameManager([caster, target], location)
            game.start_game()
            source = Skill("Fire", "C", definitions=[], skill_id="fire")
            for _ in range(2):
                apply_skill_effect({"effect_type": "add_status", "effect_data": {"status_id": "burning"}}, target, source, actor=caster)
            hp = target.hp
            for turn in (1, 2):
                game.turn_manager.turn = turn
                game.resolve_turn_end_event(turn)
                self.assertEqual(target.hp, hp - 28 * turn)
            self.assertFalse(target.has_status("burning"))

    def test_passive_form_limits_effect_types_and_state_follows_outer_status(self):
        form = self.load_marker()
        form.stacking.rule.set(STACK_RULES["stack"])
        form.stacking.maximum.set("3")
        form.add_unit_button.invoke()
        unit = form.components[0]
        unit.kind.set(STATUS_TYPES["passive"])
        unit.add_effect_button.invoke()
        effect = unit.effects[0]
        self.assertNotIn("damage", effect.type_box.cget("values"))
        self.assertNotIn("hidden", effect.type_box.cget("values"))
        effect.effect_type.set("attack_bonus")
        self.set_json(effect.data, {"value": 4})
        self.assertEqual(unit.trigger_editor.winfo_manager(), "")
        self.assertTrue(self.app.save())
        with self.app.project.activate():
            actor = Master("Actor", 3, 3, 3, 3, 3, "C", 3)
            source = Skill("Aura", "C", definitions=[], skill_id="aura")
            effect = {"effect_type": "add_status", "effect_data": {"status_id": "user_status"}}
            baseline = actor.atk_bonus
            result = apply_skill_effect(effect, actor, source, actor=actor)
            apply_skill_effect(effect, actor, source, actor=actor)
            self.assertEqual(actor.atk_bonus, baseline + 8)
            actor.remove_modifier(result.modifier)
            self.assertEqual(actor.atk_bonus, baseline)

    def test_react_event_conditions_and_target_are_visible_and_saved(self):
        unit = self.load_marker().add_component()
        unit.kind.set(STATUS_TYPES["react"])
        unit.trigger_editor.selection.set(EVENT_OPTIONS["damage_received"][0])
        row = unit.conditions.rows[0]
        row.selection.set(CONDITION_NAMES["event_target_is_self"])
        unit.target.set("事件行动者")
        unit.add_effect({"effect_type": "damage", "effect_data": {"value": 3, "damage_type": "magic"}})
        self.assertEqual(unit.conditions.winfo_manager(), "pack")
        self.assertFalse(hasattr(unit, "costs"))
        self.assertIsNone(unit.choices)
        self.assertIn("共享", unit.type_notice.cget("text"))
        self.assertTrue(self.app.save())
        saved = self.app.definition()["components"][0]
        self.assertEqual(saved["trigger"], {"event_type": "damage_received"})
        self.assertEqual(saved["condition"], {"event_target_is_self": True})
        self.assertEqual(saved["target"], "event_actor")

    def test_json_fallback_preserves_unsaved_draft_and_backup(self):
        self.app.load("status", "burning")
        self.toggle(False)
        self.assertFalse(self.app.form_mode)
        self.assertFalse(self.app.dirty())
        self.toggle(True)
        self.assertFalse(self.app.dirty())
        self.app.form.name.set("燃烧测试")
        self.toggle(False)
        self.assertTrue(self.app.dirty())
        self.assertEqual(json.loads(self.app.text.get("1.0", "end-1c"))["name"], "燃烧测试")
        draft = self.app.definition()
        draft["description"] = "JSON中修改的说明"
        self.app.text.delete("1.0", "end")
        self.app.text.insert("1.0", format_json(draft))
        self.toggle(True)
        self.assertTrue(self.app.dirty())
        self.assertEqual(self.app.definition(), draft)
        self.assertTrue(self.app.save())
        previous = self.path.read_bytes()
        self.app.form.name.set("再次修改")
        self.assertTrue(self.app.save())
        self.assertEqual(self.path.with_suffix(".json.bak").read_bytes(), previous)

    def test_invalid_json_and_invalid_form_cannot_be_lost_during_switch(self):
        self.app.load("status", "burning")
        self.app.form.duration.set("bad")
        self.toggle(False)
        self.assertTrue(self.app.status_forms_enabled.get())
        self.assertTrue(self.app.form_mode)
        self.assertEqual(self.app.form.duration.get(), "bad")
        self.app.form.duration.set("3")
        self.toggle(False)
        self.app.text.insert("1.0", "invalid")
        draft = self.app.text.get("1.0", "end-1c")
        self.toggle(True)
        self.assertFalse(self.app.status_forms_enabled.get())
        self.assertEqual(self.app.text.get("1.0", "end-1c"), draft)

    def test_invalid_status_import_keeps_original_json_editable(self):
        definition = deepcopy(STATUS_DATA["burning"])
        definition["components"][0]["cost"] = []
        self.app.load("status", "burning", definition)
        self.assertFalse(self.app.form_mode)
        self.assertEqual(self.app.definition(), definition)
        self.assertEqual(self.app.text.cget("state"), "normal")
        self.assertFalse(can_use_status_form(definition))

    def test_invalid_values_and_effect_lifecycle_do_not_overwrite_saved_project(self):
        self.app.load("status", "burning")
        self.assertTrue(self.app.save())
        previous = self.path.read_bytes()
        form = self.app.form
        for value in ("0", "-1", "1.5", "", "abc"):
            form.duration.set(value)
            self.assertFalse(self.app.save())
            self.assertEqual(self.path.read_bytes(), previous)
        form.duration.set("3")
        form.stacking.initial.set("5")
        self.assertFalse(self.app.save())
        form.stacking.initial.set("1")
        unit = form.components[0]
        unit.kind.set(STATUS_TYPES["passive"])
        effect = unit.effects[0]
        effect.effect_type.set("attack_bonus")
        self.set_json(effect.data, {"value": 3})
        self.set_json(effect.extras, {"duration": 1})
        self.assertFalse(self.app.save())
        self.assertEqual(self.path.read_bytes(), previous)
        self.set_json(effect.extras, {})
        self.assertTrue(self.app.save())

    def test_type_switch_retains_event_draft_and_excludes_it_from_passive_output(self):
        unit = self.load_marker().add_component()
        unit.kind.set(STATUS_TYPES["trigger"])
        unit.trigger_editor.selection.set(EVENT_OPTIONS["global_turn_end"][0])
        unit.add_effect({"effect_type": "attack_bonus", "effect_data": {"value": 2}})
        expected = unit.read()["trigger"]
        unit.kind.set(STATUS_TYPES["passive"])
        self.assertNotIn("trigger", unit.read())
        unit.kind.set(STATUS_TYPES["trigger"])
        self.assertEqual(unit.read()["trigger"], expected)
        self.assertTrue(self.app.save())

    def test_delete_units_leaves_valid_marker_and_reclaims_space(self):
        self.root.geometry("1300x900")
        self.root.deiconify()
        form = self.load_marker()
        first, second = form.add_component(), form.add_component()
        self.assertEqual(second.separator.winfo_manager(), "pack")
        first.toggle()
        second.toggle()
        self.root.update()
        first.delete_button.invoke()
        second.delete_button.invoke()
        self.root.update()
        self.assertEqual(form.components, [])
        self.assertLess(form.unit_rows.winfo_height(), 10)
        self.assertEqual(form.marker_notice.winfo_manager(), "pack")
        self.assertTrue(self.app.save())

    def test_all_stacking_modes_preserve_hidden_fields_and_advanced_options(self):
        form = self.load_marker()
        form.stacking.maximum.set("3")
        self.set_json(form.stacking.extras, {"stack_group": "custom_group", "strength_priority": 5, "strength_comparison": "higher"})
        for scope in SCOPES.values():
            for rule in STACK_RULES.values():
                with self.subTest(scope=scope, rule=rule):
                    form.stacking.scope.set(scope)
                    form.stacking.rule.set(rule)
                    form.stacking.refresh.set(REFRESH_RULES["extend"])
                    definition = form.read()
                    self.assertEqual(definition["stacking"]["max_stacks"], 3)
                    self.assertEqual(definition["stacking"]["stack_group"], "custom_group")
                    self.assertTrue(can_use_status_form(definition))

    def test_status_export_import_remains_plain_catalog_json(self):
        self.app.load("status", "burning")
        export = Path(self.folder.name) / "status.json"
        with patch("skilleditor.app.filedialog.asksaveasfilename", return_value=str(export)):
            self.app.export_entry()
        exported = json.loads(export.read_text(encoding="utf-8"))
        self.assertEqual(exported["definition"], STATUS_DATA["burning"])
        self.assertNotIn("experimental", exported["definition"])
        with patch("SkillEditorClient.app.filedialog.askopenfilename", return_value=str(export)):
            self.app.import_entry()
        self.assertTrue(self.app.form_mode)
        self.assertTrue(self.app.dirty())
        self.assertEqual(self.app.definition(), STATUS_DATA["burning"])

    def test_immunity_tags_charges_duration_and_json_fallback_are_editable(self):
        self.app.load("status", "debuff_immunity")
        form = self.app.form
        self.assertEqual(form.uses_mode.get(), "指定次数")
        form.uses.set("3")
        form.duration.set("4")
        form.tags.set("protection, mental")
        effect = form.components[0].effects[0]
        effect.data.rows["tags"].value.set("poison，mental")
        self.assertTrue(self.app.save())
        saved = self.app.definition()
        self.assertEqual(saved["tags"], ["protection", "mental"])
        self.assertEqual(saved["consumption"], {"event": "status_blocked", "uses": 3})
        self.assertEqual(saved["components"][0]["effects"][0]["effect_data"]["tags"], ["poison", "mental"])
        self.assertEqual(saved["duration"], 4)
        self.toggle(False)
        self.assertEqual(self.app.definition(), saved)
        self.toggle(True)
        self.assertEqual(self.app.definition(), saved)
        window = self.app.open_effect_reference()
        self.assertEqual(window.current_effect, "status_immunity")

    def test_immunity_count_validation_and_switching_to_unlimited(self):
        self.app.load("status", "debuff_immunity")
        self.assertTrue(self.app.save())
        saved = self.path.read_bytes()
        for value in ("0", "-1", "1.5", "bad"):
            self.app.form.uses.set(value)
            self.assertFalse(self.app.save())
            self.assertEqual(self.path.read_bytes(), saved)
        self.app.form.uses_mode.set("不限")
        self.assertTrue(self.app.save())
        self.assertNotIn("consumption", self.app.definition())
        self.app.form.duration_mode.set("永久")
        self.assertTrue(self.app.save())
        self.assertIsNone(self.app.definition()["duration"])

    def test_immunity_count_and_use_refresh_policy_are_lossless(self):
        data = deepcopy(STATUS_DATA["debuff_immunity"])
        data["consumption"].update(uses=5, mode="automatic", remove_when_empty=True, use_refresh_rule="keep_more")
        self.app.load("status", "debuff_immunity", data)
        self.assertEqual(self.app.definition(), data)
        self.app.form.uses.set("6")
        self.assertTrue(self.app.save())
        self.assertEqual(self.app.definition()["consumption"]["use_refresh_rule"], "keep_more")

    def test_immunity_tag_parameter_accepts_list_or_plain_tags_but_blocks_bad_json(self):
        self.app.load("status", "debuff_immunity")
        row = self.app.form.components[0].effects[0].data.rows["tags"]
        for text, expected in (("", []), ('["poison", "mental"]', ["poison", "mental"]),
                               ("poison,poison", ["poison"])):
            row.value.set(text)
            self.assertEqual(row.read(), expected)
        row.value.set("[1]")
        self.assertFalse(self.app.save())


if __name__ == "__main__":
    unittest.main()
