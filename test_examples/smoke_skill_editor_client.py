"""Real, hidden Tk controls for SkillEditorClient; no dialogs or game windows.

Run: python -m test_examples.smoke_skill_editor_client
"""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk, font
import subprocess
import sys
import unittest
from unittest.mock import patch

from core.catalog import CatalogProject
from game.character.masters import Master
from game.character import create_character_from_card
from SkillEditorClient.app import SkillEditorClient
from SkillEditorClient.model import FORM_CATEGORIES, PHASE_LABELS, TYPE_DESCRIPTIONS, TARGET_DESCRIPTIONS, new_client_definition
from SkillEditorClient.dialogs import NewSkillDialog
from SkillEditorClient.condition_model import CONDITION_NAMES
from SkillEditorClient.cost_editor import COST_TIMING_NAMES
from SkillEditorClient.trigger_editor import EVENT_OPTIONS
from SkillEditorClient.widgets import Collapsible
from SkillEditorClient.effect_options import EFFECT_TYPES, FORM_EFFECT_TYPES, parameter_options
from game.status.data import STATUS_DATA
from skilleditor.display import enable_high_dpi
from skilleditor.documents import format_json, new_definition


class SkillEditorClientSmokeTests(unittest.TestCase):
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
        self.app = SkillEditorClient(self.root, CatalogProject(self.path))
        self.error = self.mock("SkillEditorClient.app.messagebox.showerror")
        self.root.update()

    def mock(self, name, **kwargs):
        context = patch(name, **kwargs)
        value = context.start()
        self.addCleanup(context.stop)
        return value

    def new(self):
        # Most interaction checks need a complete skill. Build that fixture
        # explicitly; separate tests exercise the genuinely empty new flow.
        self.app.load("personal_skill", "user_example", new_client_definition("固有技能", "user_example"))
        self.app.form.add_component(new_definition("固有技能", "user_example")["components"][0])
        return self.app.form

    @staticmethod
    def set_json(box, value):
        if hasattr(box, "show_json"):
            box.show_json()
        box.text.delete("1.0", "end")
        box.text.insert("1.0", format_json(value))

    @staticmethod
    def set_phases(component, phases):
        for phase, variable in component.phases.variables.items():
            variable.set(phase in phases)
        component.phases.selected(component.phases_changed)

    def test_left_catalog_matches_original_project_and_classes_stay_json(self):
        self.assertEqual(set(self.app.items.values()), {
            (category, key) for category, entries in self.app.project.effective().items() if category != "character_card" for key in entries})
        self.app.load("class_skill", "对魔力")
        self.assertFalse(self.app.form_mode)
        self.assertEqual(parse(self.app.text), self.app.project.effective()["class_skill"]["对魔力"])

    def test_both_reference_views_read_the_client_copy(self):
        dictionary = Path(self.directory.name) / "effect_dictionary.txt"
        content = "1. damage\n---------\n\n客户端专用说明，保留自定义文字。\n"
        dictionary.write_text(content, encoding="utf-8-sig")
        with patch("SkillEditorClient.effect_reference.DICTIONARY_PATH", dictionary):
            top = tk.Toplevel(self.root)
            top.withdraw()
            self.addCleanup(top.destroy)
            app = SkillEditorClient(top, CatalogProject(self.path))
            page = app.notebook.nametowidget(app.notebook.tabs()[-1])

            def text_widgets(widget):
                if isinstance(widget, tk.Text):
                    yield widget
                for child in widget.winfo_children():
                    yield from text_widgets(child)

            full_reference, = text_widgets(page)
            self.assertEqual(full_reference.get("1.0", "end-1c"), content)
            self.assertEqual(str(full_reference.cget("state")), "disabled")
            window = app.open_effect_reference()
            window.select_effect("damage")
            self.assertEqual(window.dictionary, content)
            self.assertIn("客户端专用说明", window.text.get("1.0", "end-1c"))
            self.assertFalse(self.path.exists())
            self.assertFalse(app.dirty())

    def test_effect_reference_is_readonly_and_searches_types_and_parameters(self):
        self.new()
        window = self.app.open_effect_reference()
        self.assertEqual(len(window.visible_effects), len(FORM_EFFECT_TYPES))
        self.assertEqual(window.current_effect, "attack_bonus")
        before = window.text.get("1.0", "end-1c")
        window.text.insert("1.0", "must not be inserted")
        self.assertEqual(window.text.get("1.0", "end-1c"), before)
        self.assertEqual(str(window.text.cget("state")), "disabled")
        window.search.set("直接伤害")
        self.assertIn("damage", window.visible_effects)
        window.search.set("status_id")
        self.assertIn("add_status", window.visible_effects)
        window.search.set("effect_not_present_9384")
        self.assertEqual(window.visible_effects, [])
        self.assertIn("没有找到", window.text.get("1.0", "end-1c"))
        self.assertIsNone(self.root.grab_current())

    def test_effect_panel_reference_button_selects_type_and_reuses_window(self):
        effect = self.new().components[0].effects[0]
        effect.effect_type.set("damage")
        before = self.app.form.snapshot()
        effect.reference_button.invoke()
        window = self.root._effect_reference_window
        self.assertEqual(window.current_effect, "damage")
        effect.effect_type.set("add_status")
        effect.reference_button.invoke()
        self.assertIs(self.root._effect_reference_window, window)
        self.assertEqual(window.current_effect, "add_status")
        effect.effect_type.set("damage")
        self.assertEqual(self.app.form.snapshot(), before)
        self.assertFalse(self.path.exists())
        window.destroy()
        self.assertIsNot(self.app.open_effect_reference(), window)

    def test_reference_does_not_change_saved_project_or_dirty_state(self):
        self.new()
        self.assertTrue(self.app.save())
        saved = self.path.read_bytes()
        window = self.app.open_effect_reference()
        window.select_effect("create_field")
        window.search.set("护盾")
        window.destroy()
        self.assertEqual(self.path.read_bytes(), saved)
        self.assertFalse(self.app.dirty())

    def test_reference_can_open_while_numeric_parameter_draft_is_incomplete(self):
        effect = self.new().components[0].effects[0]
        effect.data.rows["value"].value.set("")
        window = self.app.open_effect_reference()
        self.assertEqual(window.current_effect, "attack_bonus")
        self.assertEqual(effect.data.rows["value"].value.get(), "")
        self.assertTrue(self.app.dirty())
        self.error.assert_not_called()

    def test_new_dialog_creates_numbered_empty_skill_without_duplicate_heading(self):
        self.app.kind.set("固有技能")
        self.mock("SkillEditorClient.app.ask_new_skill", return_value=("火焰护盾", "B"))
        self.app.new()
        form = self.app.form
        self.assertEqual(self.app.current, ("personal_skill", "10"))
        self.assertEqual(form.components, [])
        self.assertEqual(form.name.get(), "火焰护盾")
        self.assertEqual(form.rank.get(), "B")
        self.assertFalse(hasattr(form, "heading"))
        form.name.set("新护盾")
        form.rank.set("A")
        self.assertEqual(self.app.current[1], "10")
        self.assertEqual(str(form.rank_box.cget("state")), "normal")
        self.assertFalse(self.app.save())
        self.assertFalse(self.path.exists())

    def test_numeric_ids_sort_save_reload_and_work_in_character_references(self):
        for key in ("100", "12", "0", "10", "9"):
            self.app.project.put("personal_skill", key, new_definition("固有技能", key))
        self.app.project.save()
        self.app.refresh()

        def numeric_entries():
            for group in self.app.tree.get_children():
                nodes = self.app.tree.get_children(group)
                if nodes and self.app.items[nodes[0]][0] == "personal_skill":
                    return [self.app.items[node][1] for node in nodes if self.app.items[node][1].isdecimal()]

        self.assertEqual(numeric_entries(), ["0", "9", "10", "12", "100"])
        self.app.kind.set("固有技能")
        self.mock("SkillEditorClient.app.ask_new_skill", return_value=("数字编号技能", "B"))
        self.app.new()
        self.assertEqual(self.app.current, ("personal_skill", "101"))
        unit = self.app.form.add_component()
        self.assertEqual(unit.component_id.get(), "unit_0")
        unit.kind.set("active")
        unit.target.set("self")
        unit.add_effect({"effect_type": "attack_bonus", "effect_data": {"value": 5}})
        self.assertTrue(self.app.save())
        self.assertEqual(numeric_entries(), ["0", "9", "10", "12", "100", "101"])
        project = CatalogProject(self.path)
        self.assertEqual(project.data["personal_skill"]["101"]["skill_id"], "101")
        card = new_definition("御主卡", "numeric_reference")
        card["personal_skills"] = ["101"]
        project.put("character_card", "numeric_reference", card)
        project.save()
        with CatalogProject(self.path).activate():
            actor = create_character_from_card("numeric_reference")
            attack = actor.atk
            actor.resolve_skill_component("101", "unit_0", target=actor, turn_number=1)
            self.assertEqual(actor.atk, attack + 5)

    def test_new_units_and_effects_expand_with_unsaved_placeholder_hints(self):
        self.app.kind.set("固有技能")
        self.mock("SkillEditorClient.app.ask_new_skill", return_value=("火焰护盾", "B"))
        self.app.new()
        form = self.app.form
        self.assertEqual(form.components, [])
        self.assertFalse(hasattr(form, "remove_component_button"))
        self.assertFalse(hasattr(form, "component_selector"))
        form.add_component_button.invoke()
        panel, = form.components
        self.assertEqual(panel.costs, [])
        self.assertEqual(panel.effects, [])
        self.assertEqual(panel.kind.get(), "")
        self.assertEqual(panel.type_notice.cget("text"), "")
        self.assertEqual(panel.kind_box.get(), "（在这里选择技能类型）")
        self.assertEqual(panel.target.get(), "")
        self.assertEqual(panel.target_notice.cget("text"), "")
        self.assertEqual(panel.target_box.get(), "（在这里选择效果目标）")
        self.assertTrue(panel.expanded)
        self.assertFalse(panel.effect_group.expanded)
        panel.effect_group.toggle()
        panel.add_effect_button.invoke()
        self.assertEqual(len(panel.effects), 1)
        self.assertTrue(panel.effects[0].expanded)
        self.assertEqual(panel.effects[0].effect_type.get(), "")
        self.assertEqual(panel.effects[0].type_box.get(), "（在这里选择效果类型）")
        self.assertEqual(panel.effects[0].type_name.cget("text"), "")
        self.assertFalse(self.app.save())
        panel.effects[0].effect_type.set("attack_bonus")
        panel.effects[0].data.add_field("value", 5)
        panel.kind.set("active")
        panel.target.set("self")
        self.assertTrue(self.app.save())
        key = "10"
        project = CatalogProject(self.path)
        self.assertEqual(len(project.data["personal_skill"][key]["components"]), 1)
        with project.activate():
            actor = Master("Actor", 3, 3, 3, 3, 3, "C", 3)
            actor.load_content("personal_skill", key)
            attack = actor.atk
            actor.resolve_skill_component(key, "unit_0", target=actor, turn_number=1)
            self.assertEqual(actor.atk, attack + 5)

    def test_unit_footer_deletes_only_its_own_unit_and_preserves_other_ids(self):
        form = self.new()
        other = form.add_component()
        third = form.add_component()
        original_ids = [panel.component_id.get() for panel in form.components]
        self.assertEqual(len(set(original_ids)), 3)
        self.assertFalse(hasattr(form, "remove_component_button"))
        self.assertFalse(hasattr(form, "component_selector"))
        self.assertEqual(other.body.pack_slaves()[-1], other.delete_button)
        other.delete_button.invoke()
        self.assertEqual(form.components, [form.components[0], third])
        self.assertEqual([panel.component_id.get() for panel in form.components], [original_ids[0], original_ids[2]])
        third.delete_button.invoke()
        form.components[0].delete_button.invoke()
        self.assertEqual(form.components, [])
        self.assertFalse(self.app.save())
        self.assertFalse(self.path.exists())

    def test_removing_last_expanded_unit_reclaims_space_without_adding_another(self):
        form = self.new()
        panel = form.components[0]
        panel.toggle()
        panel.effect_group.toggle()
        for _ in range(4):
            effect = panel.add_effect({"effect_type": "attack_bonus", "effect_data": {"value": 5}})
            effect.toggle()
        self.root.deiconify()
        self.root.update()
        scroll = self.app.scroll_form
        scroll.canvas.yview_moveto(1)
        self.root.update()
        previous_height = form.component_rows.winfo_height()
        self.assertGreater(previous_height, scroll.canvas.winfo_height())
        panel.delete_button.invoke()
        self.root.update()
        self.assertEqual(form.components, [])
        self.assertLess(form.component_rows.winfo_height(), 10)
        self.assertGreaterEqual(form.add_component_button.winfo_rooty(), scroll.canvas.winfo_rooty(), {
            "form": (form.winfo_height(), form.winfo_reqheight()),
            "body": (scroll.body.winfo_height(), scroll.body.winfo_reqheight()),
            "canvas": (scroll.canvas.winfo_height(), scroll.canvas.yview(), scroll.canvas.canvasy(0), scroll.canvas.bbox("all")),
            "controls": (form.component_controls.winfo_y(), form.component_controls.winfo_height()),
        })
        self.assertLess(form.add_component_button.winfo_rooty(), scroll.canvas.winfo_rooty() + scroll.canvas.winfo_height())
        self.assertLessEqual(scroll.canvas.canvasy(0), 0)

    def test_cancel_new_skill_keeps_current_draft_and_same_name_does_not_overwrite(self):
        form = self.new()
        self.mock("SkillEditorClient.app.messagebox.askyesnocancel", return_value=False)
        dialog = self.mock("SkillEditorClient.app.ask_new_skill", return_value=None)
        self.app.kind.set("固有技能")
        self.app.new()
        self.assertIs(self.app.form, form)
        dialog.return_value = ("火焰", "C")
        self.app.project.put("personal_skill", "20", new_definition("固有技能", "20"))
        original = deepcopy(self.app.project.data)
        self.app.new()
        self.assertEqual(self.app.current[1], "21")
        self.assertEqual(self.app.project.data, original)

    def test_localized_creation_dialog_validates_name_and_rank(self):
        failures = []
        showerror = self.mock("SkillEditorClient.dialogs.messagebox.showerror")

        def complete():
            dialog = next(child for child in self.root.winfo_children() if isinstance(child, NewSkillDialog))
            try:
                self.assertEqual(dialog.start_button.cget("text"), "开始")
                self.assertEqual(dialog.cancel_button.cget("text"), "取消")
                self.assertLessEqual(int(dialog.name_box.cget("width")), 20)
                self.assertNotIn("GM", dialog.rank_box.cget("values"))
                dialog.start_button.invoke()
                self.assertTrue(dialog.winfo_exists())
                dialog.name.set("中文名称")
                dialog.rank.set("INVALID")
                dialog.start_button.invoke()
                self.assertTrue(dialog.winfo_exists())
                dialog.rank.set("GM")
                dialog.start_button.invoke()
            except Exception as error:
                failures.append(error)
                dialog.cancel()

        self.root.after(30, complete)
        dialog = NewSkillDialog(self.root)
        if failures:
            raise failures[0]
        self.assertEqual(dialog.result, ("中文名称", "GM"))
        self.assertEqual(showerror.call_count, 2)

    def test_name_rank_fields_use_half_width_and_advanced_sections_are_named(self):
        form = self.new()
        panel = form.components[0]
        panel.toggle()
        self.root.geometry("1200x800")
        self.root.deiconify()
        self.root.update()
        for widget in (form.name_box, form.rank_box, panel.kind_box):
            self.assertAlmostEqual(widget.winfo_width() / widget.master.winfo_width(), 0.5, delta=0.03)
        self.assertFalse(hasattr(panel, "id_box"))
        for widget in (form.name_box, form.rank_box):
            self.assertEqual(font.Font(root=self.root, font=widget.cget("font")).actual()["size"], 12)
        self.assertEqual(font.Font(root=self.root, font=form.description.cget("font")).actual()["size"], 11)
        button_font = ttk.Style(self.root).lookup(form.add_component_button.cget("style"), "font")
        self.assertEqual(font.Font(root=self.root, font=button_font).actual()["size"], 12)
        for button in (panel.toggle_button, panel.delete_button):
            self.assertEqual(ttk.Style(self.root).lookup(button.cget("style"), "font"), button_font)
        self.assertEqual(font.Font(root=self.root, font=panel.label.cget("font")).actual()["size"], 12)
        self.assertIs(form.description.frame.master, form)
        self.assertTrue(form.description.winfo_ismapped())
        for kind in ("active", "passive", "react", "trigger"):
            panel.kind.set(kind)
            self.assertEqual(panel.type_notice.cget("text"), TYPE_DESCRIPTIONS[kind])
        self.assertGreater(panel.type_notice.winfo_y(), panel.kind_box.master.master.winfo_y())
        self.assertIn("高级设置", form.extras.master.master.label.cget("text"))
        self.assertEqual(form.components[0].effects[0].data.notebook.tab(1, "text"), "效果参数高级设置")

    def test_new_unit_requires_explicit_type_and_target_and_shows_target_help(self):
        form = self.new()
        panel = form.add_component()
        panel.add_effect({"effect_type": "attack_bonus", "effect_data": {"value": 5}})
        self.assertFalse(self.app.save())
        self.assertFalse(self.path.exists())
        panel.kind.set("active")
        self.assertEqual(panel.type_notice.cget("text"), TYPE_DESCRIPTIONS["active"])
        self.assertFalse(self.app.save())
        panel.target.set("self")
        self.assertEqual(panel.target_notice.cget("text"), TARGET_DESCRIPTIONS["self"])
        panel.kind.set("react")
        panel.target.set("event_target")
        self.assertEqual(panel.target_notice.cget("text"), TARGET_DESCRIPTIONS["event_target"])
        panel.kind.set("active")
        panel.target.set("self")
        self.assertTrue(self.app.save())
        saved = self.app.project.data["personal_skill"]["user_example"]["components"]
        self.assertEqual(saved[1]["type"], "active")
        self.assertEqual(saved[1]["target"], "self")

    def test_gm_can_be_typed_and_saved_but_is_not_a_dropdown_choice(self):
        form = self.new()
        self.assertNotIn("GM", form.rank_box.cget("values"))
        form.rank.set("GM")
        self.assertTrue(self.app.save())
        self.assertEqual(CatalogProject(self.path).data["personal_skill"]["user_example"]["rank"], "GM")

    def test_phase_checkboxes_update_cost_options_and_preserve_other_selections(self):
        panel = self.new().components[0]
        self.assertTrue(all(isinstance(button, ttk.Checkbutton) for button in panel.phases.buttons.values()))
        for phase, button in panel.phases.buttons.items():
            self.assertEqual(button.cget("text"), PHASE_LABELS[phase])
        panel.phases.buttons["AP1"].invoke()
        self.assertEqual(panel.phases.get(), ["AP2"])
        self.assertEqual(panel.costs[0].resource.get(), "action_point")
        panel.phases.buttons["AP2"].invoke()
        panel.phases.buttons["attack_phase"].invoke()
        self.assertEqual(panel.phases.get(), ["attack_phase"])
        self.assertNotIn("action_point", panel.costs[0].resource_box.cget("values"))
        self.assertEqual(panel.costs[0].resource.get(), "")
        self.assertEqual(panel.costs[0].value.get(), "1")
        self.assertFalse(self.app.save())
        panel.costs[0].resource.set("attack_phase_count")
        self.assertTrue(self.app.save())
        self.assertEqual(self.app.project.data["personal_skill"]["user_example"]["components"][0]["available_phases"], ["attack_phase"])

    def test_effect_parameters_wait_for_type_and_hidden_values_remain_repairable(self):
        panel = self.new().components[0]
        effect = panel.add_effect({"effect_type": "", "effect_data": {}})
        self.assertEqual(effect.parameter_group.winfo_manager(), "")
        self.assertEqual(effect.type_name.cget("text"), "")
        effect.effect_type.set("damage")
        self.assertEqual(effect.parameter_group.winfo_manager(), "pack")
        style = ttk.Style(self.root)
        phase_gray = style.lookup(panel.phase_area.cget("style"), "background")
        self.assertEqual(style.lookup(effect.parameter_group.cget("style"), "background"), phase_gray)
        self.assertEqual(style.lookup(effect.data.form.cget("style"), "background"), phase_gray)
        self.assertLess(panel.body.pack_slaves().index(panel.effect_group), panel.body.pack_slaves().index(panel.cost_group))
        effect.data.add_field("damage_type", "magic")
        effect.data.add_field("value", 30)
        effect.effect_type.set("")
        self.assertEqual(effect.parameter_group.winfo_manager(), "")
        self.assertFalse(self.app.save())
        effect.effect_type.set("damage")
        self.assertEqual(json.loads(effect.data.get()), {"damage_type": "magic", "value": 30})
        self.assertEqual(effect.parameter_group.winfo_manager(), "pack")
        self.assertTrue(self.app.save())

    def test_every_existing_skill_round_trips_without_losing_unknown_fields(self):
        for category in FORM_CATEGORIES:
            for key, definition in self.app.project.effective()[category].items():
                with self.subTest(key=key):
                    self.app.load(category, key)
                    self.assertEqual(self.app.definition(), definition)
                    self.assertFalse(self.app.dirty())
        self.root.update_idletasks()

    def test_left_selection_collapses_existing_skill_and_reselection_preserves_draft(self):
        def sections(widget):
            if isinstance(widget, Collapsible):
                yield widget
            for child in widget.winfo_children():
                yield from sections(child)

        def select(key):
            node = next(node for node, value in self.app.items.items() if value == ("personal_skill", key))
            self.app.tree.selection_set(node)
            self.root.update()

        select("master_test_0:unblemished_person")
        form = self.app.form
        for section in sections(form):
            self.assertFalse(section.expanded)
            section.toggle()
        effect = form.components[0].effects[0]
        effect.data.show_json()
        effect.data.text.insert("1.0", "unfinished")
        before = form.snapshot()
        self.assertTrue(self.app.dirty())
        confirm = self.mock("SkillEditorClient.app.messagebox.askyesnocancel", return_value=False)
        self.app.tree.event_generate("<<TreeviewSelect>>")
        self.root.update()
        self.assertIs(self.app.form, form)
        self.assertEqual(form.snapshot(), before)
        self.assertTrue(self.app.dirty())
        confirm.assert_not_called()
        for section in sections(form):
            self.assertFalse(section.expanded)
            self.assertEqual(section.body.winfo_manager(), "")
        select("master_test_0:starfire")
        self.assertIsNot(self.app.form, form)
        self.assertTrue(all(not section.expanded for section in sections(self.app.form)))
        self.assertFalse(self.app.dirty())

    def test_form_save_reopen_and_original_rule_execution(self):
        form = self.new()
        form.name.set("表单技能")
        form.rank.set("B")
        self.assertTrue(self.app.save())
        project = CatalogProject(self.path)
        self.assertEqual(project.data["personal_skill"]["user_example"]["name"], "表单技能")
        with project.activate():
            actor = Master("Actor", 3, 3, 3, 3, 3, "C", 3)
            actor.load_content("personal_skill", "user_example")
            attack, ap = actor.atk, actor.action_point
            actor.resolve_skill_component("user_example", "active", target=actor, turn_number=1)
            self.assertEqual(actor.atk, attack + 5)
            self.assertEqual(actor.action_point, ap - 1)
        self.assertFalse(self.app.dirty())

    def test_invalid_or_blank_component_does_not_write_file(self):
        self.new().components[0].component_id.set("")
        self.assertFalse(self.app.save())
        self.assertFalse(self.path.exists())
        self.assertTrue(self.app.dirty())

    def test_phase_dropdown_clears_unavailable_ap_choice_and_preserves_value(self):
        panel = self.new().components[0]
        self.set_phases(panel, ["attack_phase"])
        row = panel.costs[0]
        self.assertNotIn("action_point", row.resource_box.cget("values"))
        self.assertEqual(row.resource.get(), "")
        self.assertEqual(row.value.get(), "1")
        self.assertFalse(self.app.save())
        row.resource.set("attack_phase_count")
        self.assertTrue(self.app.save())
        panel = self.app.form.components[0]
        self.set_phases(panel, ["AP2", "attack_phase"])
        self.assertIn("action_point", panel.costs[0].resource_box.cget("values"))

    def test_effect_type_dropdown_and_parameter_choices_match_engine(self):
        effect = self.new().components[0].effects[0]
        self.assertEqual(tuple(effect.type_box.cget("values")), FORM_EFFECT_TYPES)
        effect.effect_type.set("damage")
        self.assertEqual(set(effect.data.rows), set(parameter_options("damage")))
        self.assertEqual(effect.data.field_choices, {})
        self.assertEqual(next(iter(effect.data.rows)), "damage_type")
        self.assertIn("*", effect.data.rows["damage_type"].label.cget("text"))
        self.assertEqual(set(effect.data.rows["damage_type"].input.cget("values")), {"physical", "magic", "true_damage"})
        self.assertNotIn("damage_type", effect.data.field_choices.values())

    def test_all_effect_parameters_are_displayed_required_first_without_creating_values(self):
        from game.skill.effect_validation import EFFECT_SCHEMAS
        from SkillEditorClient.effect_editor import EffectDataEditor
        for kind, schema in EFFECT_SCHEMAS.items():
            with self.subTest(kind=kind):
                editor = EffectDataEditor(self.root, kind, {}, self.app.project.effective())
                try:
                    self.assertEqual(list(editor.rows), list(parameter_options(kind)))
                    for key in schema.required_data:
                        self.assertIn("*", editor.rows[key].label.cget("text"))
                    self.assertEqual(json.loads(editor.get()), {})
                    editor.show_json()
                    editor.show_form()
                    self.assertEqual(json.loads(editor.get()), {})
                    self.assertEqual(editor.notice.cget("text"), "带*参数为必填。非必填参数可以留空。")
                    self.assertEqual(editor.input_hint.cget("text"), "文本直接填写，数值填写数字。嵌套对象和列表可在效果参数高级设置中填写")
                finally:
                    editor.destroy()

    def test_optional_blanks_are_omitted_but_zero_false_and_empty_lists_are_saved(self):
        component = self.new().components[0]
        component.remove_effect(component.effects[0])
        effect = component.add_effect({"effect_type": "damage", "effect_data": {}})
        for key, value in {"damage_type": "magic", "value": "0", "ignore_shield": "false", "source_tags": "[]"}.items():
            effect.data.rows[key].value.set(value)
        self.assertTrue(self.app.save())
        effect = self.app.form.components[0].effects[0]
        expected = {"damage_type": "magic", "value": 0, "ignore_shield": False, "source_tags": []}
        self.assertEqual(json.loads(effect.data.get()), expected)
        self.assertFalse(self.app.dirty())
        effect.data.rows["flat"].value.set("bad-number")
        original = self.path.read_bytes()
        self.assertFalse(self.app.save())
        self.assertEqual(self.path.read_bytes(), original)
        effect.data.rows["flat"].value.set("")
        effect.data.rows["ignore_shield"].value.set("")
        self.assertTrue(self.app.save())
        self.assertNotIn("ignore_shield", json.loads(self.app.form.components[0].effects[0].data.get()))

    def test_new_resource_uses_one_chinese_name_and_plain_numeric_inputs(self):
        component = self.new().components[0]
        component.remove_effect(component.effects[0])
        effect = component.add_effect({"effect_type": "add_resource", "effect_data": {}})
        self.assertEqual(effect.data.rows["name"].winfo_manager(), "")
        self.assertNotIn("name", effect.data.field_choices.values())
        for key, value in {"resource_id": "怒气", "initial_value": "3", "maximum": "10"}.items():
            row = effect.data.rows[key]
            self.assertIsInstance(row.input, ttk.Entry)
            self.assertNotIsInstance(row.input, ttk.Combobox)
            row.value.set(value)
        self.assertIn("资源名称", effect.data.rows["resource_id"].label.cget("text"))
        self.assertTrue(self.app.save())
        saved = self.app.definition()["components"][0]["effects"][0]["effect_data"]
        self.assertEqual(saved, {"resource_id": "怒气", "initial_value": 3, "maximum": 10})
        with CatalogProject(self.path).activate():
            actor = Master("Actor", 3, 3, 3, 3, 3, "C", 3)
            actor.load_content("personal_skill", "user_example")
            actor.resolve_skill_component("user_example", "active", target=actor, turn_number=1)
            self.assertEqual(actor.get_resource("怒气").name, "怒气")
            self.assertEqual(actor.get_resource_value("怒气"), 3)

    def test_choice_inputs_change_to_plain_entries_without_losing_drafts(self):
        effect = self.new().components[0].effects[0]
        effect.effect_type.set("hidden")
        row = effect.data.rows["value"]
        self.assertNotIsInstance(row.input, ttk.Combobox)
        row.value.set("自定义状态")
        effect.effect_type.set("presence_concealment")
        rank = effect.data.rows["rank"]
        self.assertIsInstance(rank.input, ttk.Combobox)
        rank.value.set("A")
        effect.effect_type.set("add_resource")
        self.assertNotIsInstance(rank.input, ttk.Combobox)
        self.assertEqual(rank.value.get(), "A")
        effect.effect_type.set("presence_concealment")
        self.assertIsInstance(rank.input, ttk.Combobox)
        self.assertEqual(rank.value.get(), "A")
        self.assertEqual(row.value.get(), "自定义状态")

    def test_old_separate_resource_name_is_preserved_in_advanced_json(self):
        component = self.new().components[0]
        definition = {"resource_id": "charges", "name": "原资源名", "initial_value": 3}
        effect = component.add_effect({"effect_type": "add_resource", "effect_data": definition})
        self.assertEqual(effect.data.rows["name"].winfo_manager(), "")
        self.assertEqual(json.loads(effect.data.get()), definition)
        effect.data.show_json()
        effect.data.show_form()
        self.assertEqual(effect.data.rows["name"].winfo_manager(), "")
        self.assertTrue(self.app.save())
        self.assertEqual(self.app.definition()["components"][0]["effects"][-1]["effect_data"], definition)
        effect = self.app.form.components[0].effects[-1]
        effect.effect_type.set("create_field")
        self.assertEqual(effect.data.rows["name"].winfo_manager(), "pack")
        self.assertEqual(effect.data.rows["name"].value.get(), "原资源名")

    def test_placeholder_display_does_not_enter_data_and_combobox_selection_updates_values(self):
        form = self.new()
        panel = form.add_component()
        panel.kind_box.set("active")
        panel.target_box.set("self")
        self.assertEqual(panel.kind.get(), "active")
        self.assertEqual(panel.target.get(), "self")
        panel.add_effect_button.invoke()
        effect = panel.effects[0]
        effect.type_box.set("damage")
        self.assertEqual(effect.effect_type.get(), "damage")
        self.assertFalse(self.app.save())
        effect.data.show_json()
        effect.data.text.delete("1.0", "end")
        effect.data.text.insert("1.0", '{"damage_type": "magic", "value": 3}')
        effect.data.show_form()
        self.assertTrue(self.app.save())
        saved = self.path.read_text(encoding="utf-8")
        self.assertNotIn("在这里选择", saved)
        self.assertEqual(self.app.definition()["components"][-1]["type"], "active")

    def test_blank_placeholder_comboboxes_can_open_popdown_without_callback_errors(self):
        panel = self.new().add_component()
        panel.effect_group.toggle()
        panel.add_effect_button.invoke()
        effect = panel.effects[0]
        errors = []
        self.root.report_callback_exception = lambda *error: errors.append(error)
        self.root.deiconify()
        self.root.update()
        for box, variable in ((panel.kind_box, panel.kind), (panel.target_box, panel.target),
                              (effect.type_box, effect.effect_type)):
            with self.subTest(box=box):
                try:
                    box.focus_force()
                    self.root.update()
                    box.tk.call("ttk::combobox::Post", str(box))
                    popdown = box.tk.call("ttk::combobox::PopdownWindow", str(box))
                    box.tk.call("focus", "-force", f"{popdown}.f.l")
                    self.root.update()
                    self.assertTrue(str(box.tk.call("focus")).startswith(str(popdown)))
                    self.assertEqual(variable.get(), "")
                    self.assertFalse(errors, [(kind.__name__, str(error)) for kind, error, tb in errors])
                finally:
                    box.tk.call("ttk::combobox::Unpost", str(box))
                    self.root.focus_force()
                    self.root.update()
                box.current(0)
                self.assertEqual(variable.get(), box.cget("values")[0])
                variable.set("")

    def test_damage_created_with_dropdown_fields_saves_and_executes(self):
        component = self.new().components[0]
        component.remove_effect(component.effects[0])
        effect = component.add_effect({"effect_type": "damage", "effect_data": {}})
        effect.data.add_field("value", empty=True).value.set("30")
        effect.data.add_field("damage_type", empty=True).value.set("magic")
        effect.data.add_field("ignore_shield", empty=True).value.set("false")
        self.assertTrue(self.app.save())
        definition = CatalogProject(self.path).data["personal_skill"]["user_example"]
        self.assertIs(definition["components"][0]["effects"][0]["effect_data"]["ignore_shield"], False)
        with CatalogProject(self.path).activate():
            actor = Master("Actor", 3, 3, 3, 3, 3, "C", 3)
            actor.load_content("personal_skill", "user_example")
            hp = actor.hp
            actor.resolve_skill_component("user_example", "active", target=actor, turn_number=1)
            self.assertEqual(actor.hp, hp - 30)

    def test_unified_calculation_dropdown_saves_and_executes_nondefault_option(self):
        component = self.new().components[0]
        effect = component.add_effect({"effect_type": "modify_resource", "effect_data": {
            "resource_id": "charges", "value": 3}})
        self.assertIn("calculation", effect.data.rows)
        self.assertNotIn("operation", effect.data.field_choices.values())
        row = effect.data.add_field("calculation", empty=True)
        self.assertIn("set", row.input.cget("values"))
        row.value.set("set")
        self.assertTrue(self.app.save())
        with CatalogProject(self.path).activate():
            actor = Master("Actor", 3, 3, 3, 3, 3, "C", 3)
            actor.add_resource({"resource_id": "charges", "initial_value": 9})
            actor.load_content("personal_skill", "user_example")
            actor.resolve_skill_component("user_example", "active", target=actor, turn_number=1)
            self.assertEqual(actor.get_resource_value("charges"), 3)
        window = self.app.open_effect_reference()
        window.select_effect("modify_resource")
        text = window.text.get("1.0", "end-1c")
        self.assertIn("effect_data.calculation", text)
        self.assertNotIn("effect_data.operation", text)

    def test_legacy_operation_is_preserved_as_repairable_draft_but_cannot_save(self):
        component = self.new().components[0]
        effect = component.add_effect({"effect_type": "modify_resource", "effect_data": {
            "resource_id": "charges", "operation": "set", "value": 3}})
        self.assertIn("当前类型不支持", effect.data.rows["operation"].label.cget("text"))
        self.assertFalse(self.app.save())
        self.assertFalse(self.path.exists())
        self.assertEqual(json.loads(effect.data.get())["operation"], "set")

    def test_type_switch_preserves_old_fields_and_explicit_removal_works(self):
        effect = self.new().components[0].effects[0]
        effect.data.rows["value"].value.set("9")
        effect.effect_type.set("observe_location")
        self.assertEqual(json.loads(effect.data.get()), {"value": 9})
        self.assertIn("当前类型不支持", effect.data.rows["value"].label.cget("text"))
        effect.data.remove_field("value")
        self.assertEqual(json.loads(effect.data.get()), {})
        self.assertEqual(str(effect.data.add_button.cget("state")), "disabled")

    def test_parameter_form_json_switches_keep_drafts_and_do_not_mark_clean_data_dirty(self):
        effect = self.new().components[0].effects[0]
        self.assertTrue(self.app.save())
        effect = self.app.form.components[0].effects[0]
        before = effect.data.snapshot()
        effect.data.show_json()
        effect.data.show_form()
        self.assertEqual(before, effect.data.snapshot())
        self.assertFalse(self.app.dirty())
        effect.data.rows["value"].value.set("17")
        effect.data.show_json()
        self.assertEqual(json.loads(effect.data.raw.get()), {"value": 17})
        self.set_json(effect.data, {"value": 19})
        effect.data.show_form()
        self.assertEqual(effect.data.rows["value"].value.get(), "19")
        self.assertTrue(self.app.dirty())

    def test_blank_numeric_parameter_is_dirty_and_cannot_save_or_erase_on_mode_switch(self):
        effect = self.new().components[0].effects[0]
        effect.data.rows["value"].value.set("")
        self.assertTrue(self.app.dirty())
        self.assertFalse(self.app.save())
        with self.assertRaises(ValueError):
            effect.data.show_json()
        self.assertEqual(effect.data.mode, "form")
        self.assertEqual(effect.data.rows["value"].value.get(), "")
        self.assertFalse(self.path.exists())

    def test_invalid_advanced_json_kept_when_return_to_form_is_rejected(self):
        effect = self.new().components[0].effects[0]
        effect.data.show_json()
        effect.data.text.insert("1.0", "invalid")
        text = effect.data.raw.get()
        with self.assertRaises(ValueError):
            effect.data.show_form()
        self.assertEqual(effect.data.mode, "json")
        self.assertEqual(effect.data.get(), text)

    def test_clicking_parameter_tabs_synchronizes_and_preserves_invalid_json(self):
        effect = self.new().components[0].effects[0]
        effect.data.notebook.select(effect.data.raw)
        self.root.update()
        self.assertEqual(effect.data.mode, "json")
        effect.data.text.insert("1.0", "invalid")
        effect.data.notebook.select(effect.data.form)
        self.root.update()
        self.assertEqual(effect.data.mode, "json")
        self.assertEqual(effect.data.notebook.select(), str(effect.data.raw))
        self.error.assert_called_once()

    def test_project_status_dropdown_includes_custom_status(self):
        status = deepcopy(STATUS_DATA["burning"])
        status["status_id"] = "user_poison"
        self.app.project.put("status", "user_poison", status)
        effect = self.new().components[0].effects[0]
        effect.effect_type.set("add_status")
        row = effect.data.add_field("status_id", empty=True)
        self.assertIn("user_poison", row.input.cget("values"))

    def test_boolean_and_number_difference_marks_parameter_draft_dirty(self):
        effect = self.new().components[0].effects[0]
        effect.data.rows["value"].value.set("1")
        self.assertTrue(self.app.save())
        effect = self.app.form.components[0].effects[0]
        effect.data.rows["value"].value.set("true")
        self.assertTrue(self.app.dirty())
        self.assertFalse(self.app.save())

    def test_invalid_json_is_dirty_and_cannot_overwrite_saved_file(self):
        self.new()
        self.assertTrue(self.app.save())
        original = self.path.read_bytes()
        data = self.app.form.components[0].effects[0].data
        data.show_json()
        data.text.insert("1.0", "invalid")
        self.assertTrue(self.app.dirty())
        self.assertFalse(self.app.save())
        self.assertEqual(self.path.read_bytes(), original)

    def test_collapsing_sections_does_not_change_data(self):
        self.new()
        definition = self.app.definition()
        panel = self.app.form.components[0]
        panel.toggle()
        panel.cost_group.toggle()
        panel.effect_group.toggle()
        self.assertEqual(self.app.definition(), definition)

    def test_multiple_components_costs_and_effects_round_trip(self):
        form = self.new()
        panel = form.components[0]
        panel.add_cost({"resource": "mp", "value": 10, "cost_id": "extra"})
        panel.add_effect({"effect_type": "recover_resource", "effect_data": {"resource_id": "hp", "value": 5}})
        other = form.add_component({"component_id": "second", "type": "active", "available_phases": ["AP2"],
            "target": "self", "effects": [{"effect_type": "recover_resource", "effect_data": {"resource_id": "hp", "value": 5}}]})
        self.assertTrue(self.app.save())
        value = self.app.project.data["personal_skill"]["user_example"]
        self.assertEqual(len(value["components"]), 2)
        self.assertEqual(len(value["components"][0]["cost"]), 2)
        self.assertEqual(len(value["components"][0]["effects"]), 2)
        self.assertEqual(value["components"][0]["cost"][1]["cost_id"], "extra")

    def test_unsaved_invalid_form_can_be_discarded(self):
        self.new()
        self.app.form.components[0].costs[0].value.set("bad")
        confirm = self.mock("SkillEditorClient.app.messagebox.askyesnocancel", return_value=False)
        self.assertTrue(self.app.leave())
        confirm.assert_called_once()

    def test_import_is_draft_and_export_uses_current_form(self):
        form = self.new()
        form.name.set("待导出")
        exported = self.path.parent / "entry.json"
        self.mock("SkillEditorClient.app.filedialog.asksaveasfilename", return_value=str(exported))
        self.app.export_entry()
        self.assertEqual(json.loads(exported.read_text(encoding="utf-8"))["definition"]["name"], "待导出")
        self.assertFalse(self.path.exists())
        self.mock("SkillEditorClient.app.messagebox.askyesnocancel", return_value=False)
        self.mock("SkillEditorClient.app.filedialog.askopenfilename", return_value=str(exported))
        self.app.import_entry()
        self.assertTrue(self.app.dirty())
        self.assertTrue(self.app.save())

    def test_preview_is_readonly_and_does_not_discard_invalid_form(self):
        self.new()
        self.app.form.components[0].component_id.set("")
        self.app.notebook.select(self.app.json_tab)
        self.root.update()
        toolbar = self.app.path_label.master.winfo_children()[0]
        captions = [child.cget("text") for child in toolbar.winfo_children() if isinstance(child, ttk.Button)]
        self.assertNotIn("查看JSON", captions)
        self.assertNotIn("整理JSON", captions)
        self.assertIn("component_id", self.app.text.get("1.0", "end-1c"))
        self.assertEqual(self.app.text.cget("state"), "disabled")
        self.assertTrue(self.app.dirty())

    def test_remove_saved_custom_entry_clears_form(self):
        self.new()
        self.assertTrue(self.app.save())
        self.mock("SkillEditorClient.app.messagebox.askyesno", return_value=True)
        self.app.remove()
        self.assertIsNone(self.app.current)
        self.assertIsNone(self.app.form)
        self.assertNotIn("user_example", CatalogProject(self.path).data["personal_skill"])

    def test_duplicate_changes_only_identity_and_keeps_form_data(self):
        self.new()
        self.assertTrue(self.app.save())
        original = deepcopy(self.app.definition())
        with patch("SkillEditorClient.app.simpledialog.askstring", return_value="user_copy"):
            self.app.duplicate()
        self.assertEqual(self.app.current, ("personal_skill", "user_copy"))
        self.assertEqual(self.app.definition()["components"], original["components"])
        self.assertTrue(self.app.save())
        self.assertIn("user_copy", CatalogProject(self.path).data["personal_skill"])

    def test_class_rank_edit_keeps_original_schema(self):
        self.app.load("class_skill", "对魔力")
        original = parse(self.app.text)
        original["ranks"]["C"][0]["effects"][0]["effect_data"]["value"] = 0.6
        self.app.text.delete("1.0", "end")
        self.app.text.insert("1.0", format_json(original))
        self.assertTrue(self.app.save())
        self.assertFalse(self.app.form_mode)
        self.assertEqual(CatalogProject(self.path).data["class_skill"]["对魔力"], original)

    def test_debug_class_skill_uses_form_and_round_trips_without_schema_changes(self):
        original = deepcopy(self.app.project.effective()["class_skill"]["测试程序"])
        self.app.load("class_skill", "测试程序")
        self.assertTrue(self.app.form_mode)
        self.assertEqual(set(self.app.form.rank_forms), {"GM"})
        self.assertEqual(self.app.definition(), original)
        self.assertFalse(self.app.dirty())
        self.assertTrue(all(not panel.expanded for panel in self.app.form.components))
        self.app.update_preview()
        self.assertEqual(parse(self.app.text), original)
        reference = self.app.open_effect_reference()
        self.addCleanup(reference.destroy)
        self.assertEqual(reference.current_effect, "add_status")

    def test_debug_class_skill_effect_edit_saves_reopens_and_loads_in_core(self):
        self.app.load("class_skill", "测试程序")
        component = self.app.form.components[0]
        component.add_effect({"effect_type": "attack_bonus", "effect_data": {"value": 9}})
        self.assertTrue(self.app.dirty())
        self.assertTrue(self.app.save())
        saved = CatalogProject(self.path).data["class_skill"]["测试程序"]
        self.assertEqual(set(saved), {"name", "ranks"})
        self.assertEqual(saved["ranks"]["GM"][0]["effects"][-1]["effect_data"], {"value": 9})
        self.assertEqual(self.app.definition(), saved)
        self.assertFalse(self.app.dirty())
        project = CatalogProject(self.path)
        card = deepcopy(project.effective()["character_card"]["servant_test_0"])
        card["class_skills"] = [{"name": "测试程序", "rank": "GM"}]
        project.put("character_card", "servant_test_0", card)
        with project.activate():
            actor = create_character_from_card("servant_test_0")
            self.assertEqual(len(actor.class_skills), 1)
            self.assertEqual(actor.get_effective_atk(), actor.strength.value * 10 + 9)

    def test_debug_class_skill_empty_rank_is_preserved_and_other_classes_stay_json(self):
        original = deepcopy(self.app.project.effective()["class_skill"]["测试程序"])
        original["ranks"]["C"] = []
        self.app.load("class_skill", "测试程序", original)
        self.assertEqual(self.app.definition(), original)
        self.assertTrue(self.app.save())
        self.app.load("class_skill", "对魔力")
        self.assertFalse(self.app.form_mode)

    def test_debug_class_skill_invalid_draft_stays_in_form(self):
        self.app.load("class_skill", "测试程序")
        self.app.form.components[0].kind.set("")
        self.assertFalse(self.app.save())
        self.assertTrue(self.app.dirty())
        self.assertFalse(self.path.exists())
        self.app.update_preview()
        self.assertIn("表单尚未填写完整", self.app.text.get("1.0", "end"))

    def test_deleting_optional_rows_is_preserved(self):
        form = self.new()
        panel = form.components[0]
        panel.remove_cost(panel.costs[0])
        extra = panel.add_effect({"effect_type": "recover_resource", "effect_data": {"resource_id": "hp", "value": 1}})
        panel.remove_effect(extra)
        self.assertTrue(self.app.save())
        saved = self.app.project.data["personal_skill"]["user_example"]["components"][0]
        self.assertEqual(saved["cost"], [])
        self.assertEqual(len(saved["effects"]), 1)

    def test_external_changes_are_not_overwritten(self):
        self.new()
        self.assertTrue(self.app.save())
        self.app.form.name.set("编辑中")
        self.path.write_text(self.path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        previous = self.path.read_bytes()
        self.assertFalse(self.app.save())
        self.assertEqual(self.path.read_bytes(), previous)

    def test_core_launch_uses_current_catalog_and_independent_bundle_lifetime(self):
        launch = self.mock("SkillEditorClient.app.subprocess.Popen")
        self.app.launch_core()
        self.assertEqual(launch.call_args.args[0][-2:], ["--catalog", str(self.path)])
        self.assertEqual(launch.call_args.kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")
        self.assertIsNotNone(launch.call_args.kwargs["cwd"])

    @unittest.skipUnless(sys.platform == "win32", "Windows windowed launcher")
    def test_windowed_entry_starts_without_console(self):
        result = self.path.parent / "windowed.json"
        root_path = Path(__file__).resolve().parents[1]
        code = f'''
import ctypes, json, sys
from pathlib import Path
import tkinter as tk
import SkillEditorClient.app as client
from core.catalog import CatalogProject
def probe(path):
    root = tk.Tk()
    root.withdraw()
    app = client.SkillEditorClient(root, CatalogProject({str(self.path)!r}))
    root.update()
    ctypes.windll.kernel32.GetConsoleWindow.restype = ctypes.c_void_p
    Path({str(result)!r}).write_text(json.dumps({{"console": ctypes.windll.kernel32.GetConsoleWindow(), "executable": sys.executable, "title": root.title()}}), encoding="utf-8")
    root.destroy()
    return 0
client.main = probe
sys.argv = ["SkillEditorClient"]
from SkillEditorClient.launcher import main
raise SystemExit(main())
'''
        subprocess.run([str(Path(sys.executable).with_name("pythonw.exe")), "-c", code], cwd=root_path, timeout=15, check=True)
        value = json.loads(result.read_text(encoding="utf-8"))
        self.assertIsNone(value["console"])
        self.assertTrue(value["executable"].lower().endswith("pythonw.exe"))
        self.assertIn("SkillEditorClient", value["title"])

    def test_builtin_choice_skills_display_and_round_trip_without_extra_defaults(self):
        for key in ("servant_test_0:swordsmanship", "master_test_0:starfire", "servant_test_0:imperial_privilege"):
            with self.subTest(key=key):
                original = deepcopy(self.app.project.effective()["personal_skill"][key])
                self.app.load("personal_skill", key)
                self.assertFalse(self.app.dirty())
                self.assertEqual(self.app.definition(), original)
                panel = self.app.form.components[0]
                choices = panel.choices
                options = original["components"][0]["choices"]["options"]
                self.assertEqual([row.choice_id for row in choices.options], [item["choice_id"] for item in options])
                self.assertEqual([row.name.get() for row in choices.options], [item["name"] for item in options])
                self.assertNotIn("choices", json.loads(panel.extras.get()))
                self.assertFalse(choices.expanded)
                for row, option in zip(choices.options, options):
                    self.assertFalse(row.expanded)
                    self.assertEqual([effect.read() for effect in row.effects], option["effects"])
                    self.assertTrue(all(not effect.expanded for effect in row.effects))

    def test_swordsmanship_branch_edit_save_reload_and_reference(self):
        self.app.load("personal_skill", "servant_test_0:swordsmanship")
        original = self.app.definition()
        branch = self.app.form.components[0].choices.options[0]
        branch.name.set("攻击强化")
        branch.effects[0].data.rows["value"].value.set("12")
        self.assertIn("攻击强化", branch.label.cget("text"))
        self.assertTrue(self.app.dirty())
        self.assertTrue(self.app.save())
        saved = CatalogProject(self.path).data["personal_skill"]["servant_test_0:swordsmanship"]
        options = saved["components"][0]["choices"]["options"]
        self.assertEqual(options[0]["choice_id"], "attack")
        self.assertEqual(options[0]["effects"][0]["effect_data"]["value"], 12)
        self.assertEqual(options[1], original["components"][0]["choices"]["options"][1])
        self.assertEqual(saved["components"][0]["usage_limit"], {"scope": "battle", "maximum": 3})
        self.app.load("personal_skill", "servant_test_0:swordsmanship")
        self.assertEqual(self.app.definition(), saved)
        self.assertEqual(self.app.open_effect_reference().current_effect, "choices")

    def test_grouped_dice_targets_display_chinese_and_save_canonical_ids(self):
        self.app.load("personal_skill", "servant_test_0:swordsmanship")
        branches = self.app.form.components[0].choices.options
        self.assertEqual([len(branch.effects) for branch in branches], [1, 1])
        row = branches[0].effects[0].data.rows["effect_target"]
        attack_label = "攻击骰（物理与魔术）"
        defense_label = "防御骰（闪避、格挡、抵消）"
        self.assertEqual(row.value.get(), attack_label)
        self.assertIn(defense_label, row.input.cget("values"))
        self.assertFalse(self.app.dirty())
        row.value.set(defense_label)
        self.assertTrue(self.app.save())
        saved = CatalogProject(self.path).data["personal_skill"]["servant_test_0:swordsmanship"]
        self.assertEqual(saved["components"][0]["choices"]["options"][0]["effects"][0]["effect_data"]["effect_target"], "defense")
        data = self.app.form.components[0].choices.options[0].effects[0].data
        data.set_effect_type("attribute_bonus")
        self.assertEqual(json.loads(data.get())["effect_target"], "defense")
        data.set_effect_type("dice_bonus")
        self.assertEqual(data.rows["effect_target"].value.get(), defense_label)
        self.assertEqual(json.loads(data.get())["effect_target"], "defense")

    def test_new_choices_extra_costs_and_repeat_selection_execute_after_reload(self):
        panel = self.new().components[0]
        panel.remove_effect(panel.effects[0])
        choices = panel.add_effect({"effect_type": "choices", "effect_data": {}}).choices
        choices.maximum.set("2")
        choices.allow_duplicate.set(True)
        option = choices.add_option()
        option.name.set("回复生命")
        option.add_effect({"effect_type": "recover_resource", "effect_data": {"resource_id": "hp", "value": 5}})
        option.add_cost({"resource": "mp", "value": 2, "cost_id": "branch_mp"})
        self.set_json(option.extras, {"condition": {"actor_alive": True}})
        other = choices.add_option()
        other.name.set("攻击强化")
        other.add_effect({"effect_type": "attack_bonus", "effect_data": {"value": 7}})
        self.assertTrue(self.app.save())
        project = CatalogProject(self.path)
        saved = project.data["personal_skill"]["user_example"]
        self.assertEqual(saved["components"][0]["choices"]["maximum_selections"], 2)
        self.assertTrue(saved["components"][0]["choices"]["allow_duplicate"])
        with project.activate():
            actor = Master("Actor", 3, 3, 3, 3, 3, "C", 3)
            actor.create_personal_skill(saved)
            actor.hp -= 20
            hp, mp = actor.hp, actor.mp
            actor.resolve_skill_component("user_example", "active", target=actor, turn_number=1,
                                          selected_choice_ids=[option.choice_id, option.choice_id])
            self.assertEqual(actor.hp, hp + 10)
            self.assertEqual(actor.mp, mp - 4)

    def test_choice_add_cost_button_saves_activation_cost_with_or_without_chant(self):
        for needs_chant in ("否", "是"):
            with self.subTest(needs_chant=needs_chant):
                panel = self.new().components[0]
                panel.chant_choice.set(needs_chant)
                option = panel.add_effect({"effect_type": "choices", "effect_data": {}}).choices.add_option()
                option.name.set("攻击强化")
                option.add_effect({"effect_type": "attack_bonus", "effect_data": {"value": 3}})
                with patch.object(self.root, "report_callback_exception") as callback_error:
                    option.add_cost_button.invoke()
                callback_error.assert_not_called()
                self.assertEqual(len(option.costs), 1)
                cost = option.costs[0]
                self.assertEqual(cost.timing.get(), COST_TIMING_NAMES["activation"])
                self.assertEqual(tuple(cost.timing_box.cget("values")), (COST_TIMING_NAMES["activation"],))
                cost.value.set("7")
                self.assertTrue(self.app.save())
                saved = CatalogProject(self.path).data["personal_skill"]["user_example"]
                self.assertEqual(saved["components"][0]["choices"]["options"][0]["cost"],
                                 [{"resource": "mp", "value": 7, "timing": "activation"}])
                self.app.load("personal_skill", "user_example", saved)
                self.assertEqual(self.app.form.components[0].choices.options[0].costs[0].read(),
                                 {"resource": "mp", "value": 7, "timing": "activation"})

    def test_deleting_choices_preserves_surviving_ids_and_can_remove_the_structure(self):
        panel = self.new().components[0]
        choices = panel.add_effect({"effect_type": "choices", "effect_data": {}}).choices
        first = choices.add_option()
        first.name.set("第一项")
        first.add_effect({"effect_type": "attack_bonus", "effect_data": {"value": 3}})
        second = choices.add_option()
        second.name.set("第二项")
        second.add_effect({"effect_type": "attack_bonus", "effect_data": {"value": 4}})
        self.assertEqual((first.choice_id, second.choice_id), ("choice_0", "choice_1"))
        first.delete_button.invoke()
        self.assertEqual(choices.options, [second])
        self.assertEqual(second.choice_id, "choice_1")
        self.assertIn("分支 1", second.label.cget("text"))
        third = choices.add_option()
        self.assertEqual(third.choice_id, "choice_2")
        third.delete_button.invoke()
        self.assertTrue(self.app.save())
        choices = self.app.form.components[0].choices
        choices.options[0].delete_button.invoke()
        self.assertFalse(self.app.save())
        panel = self.app.form.components[0]
        panel.remove_effect(next(effect for effect in panel.effects if effect.effect_type.get() == "choices"))
        self.assertTrue(self.app.save())
        self.assertNotIn("choices", CatalogProject(self.path).data["personal_skill"]["user_example"]["components"][0])

    def test_incomplete_choices_and_invalid_nested_json_cannot_overwrite_saved_file(self):
        self.new()
        self.assertTrue(self.app.save())
        saved = self.path.read_bytes()
        choices = self.app.form.components[0].add_effect({"effect_type": "choices", "effect_data": {}}).choices
        option = choices.add_option()
        self.assertTrue(self.app.dirty())
        self.assertFalse(self.app.save())
        option.name.set("测试分支")
        effect = option.add_effect({"effect_type": "attack_bonus", "effect_data": {"value": 3}})
        for value in ("", "0", "-1", "1.5", "true"):
            choices.maximum.set(value)
            self.assertFalse(self.app.save())
            self.assertEqual(self.path.read_bytes(), saved)
        choices.maximum.set("1")
        effect.data.show_json()
        effect.data.text.insert("1.0", "invalid")
        self.assertFalse(self.app.save())
        self.assertEqual(self.path.read_bytes(), saved)
        self.assertIn("invalid", effect.data.raw.get())
        self.assertTrue(self.app.dirty())

    def test_choice_costs_follow_component_phase_restrictions(self):
        panel = self.new().components[0]
        option = panel.add_effect({"effect_type": "choices", "effect_data": {}}).choices.add_option()
        option.name.set("测试分支")
        option.add_effect({"effect_type": "attack_bonus", "effect_data": {"value": 3}})
        cost = option.add_cost({"resource": "action_point", "value": 1})
        self.assertIn("action_point", cost.resource_box.cget("values"))
        panel.remove_cost(panel.costs[0])
        self.set_phases(panel, ["attack_phase"])
        self.assertEqual(cost.resource.get(), "")
        self.assertNotIn("action_point", cost.resource_box.cget("values"))
        cost.resource.set("action_point")
        self.assertFalse(self.app.save())
        cost.resource.set("mp")
        self.assertTrue(self.app.save())

    def test_choice_deletion_reclaims_space_and_leaves_no_phantom_options(self):
        form = self.new()
        panel = form.components[0]
        panel.toggle()
        choices_effect = panel.add_effect({"effect_type": "choices", "effect_data": {}})
        panel.effect_group.toggle()
        choices_effect.toggle()
        choices = choices_effect.choices
        choices.toggle()
        option = choices.add_option()
        option.toggle()
        option.effect_group.toggle()
        for _ in range(3):
            effect = option.add_effect({"effect_type": "attack_bonus", "effect_data": {"value": 3}})
            effect.toggle()
        self.root.deiconify()
        self.root.update()
        self.app.scroll_form.canvas.yview_moveto(1)
        option.delete_button.invoke()
        self.root.update()
        self.assertLess(choices.option_rows.winfo_height(), 10)
        self.assertEqual(choices.options, [])
        with self.assertRaisesRegex(ValueError, "至少新建一个分支"):
            self.app.definition()
        panel.remove_effect(choices_effect)
        self.assertEqual(self.app.definition()["components"][0].get("choices"), None)
        self.assertLessEqual(self.app.scroll_form.canvas.canvasy(0),
                             max(0, self.app.scroll_form.body.winfo_height() - self.app.scroll_form.canvas.winfo_height()))

    def test_choices_entry_owns_parameters_and_only_shows_branches_when_selected(self):
        panel = self.new().components[0]
        effect = panel.add_effect({"effect_type": "", "effect_data": {}})
        self.assertIsNone(panel.choices)
        self.assertEqual(effect.choices.winfo_manager(), "")
        effect.effect_type.set("choices")
        self.assertEqual(effect.type_name.cget("text"), "可选发动")
        self.assertIs(panel.choices, effect.choices)
        self.assertEqual(effect.choices.winfo_manager(), "pack")
        self.assertIs(effect.choices.master, effect.body)
        self.assertIs(effect.choices.parameters.master, effect.parameter_group)
        self.assertTrue(str(effect.choices.maximum_box).startswith(str(effect.parameter_group)))
        self.assertTrue(str(effect.choices.duplicate_box).startswith(str(effect.parameter_group)))
        self.assertFalse(str(effect.choices.maximum_box).startswith(str(effect.choices.body)))
        self.assertEqual(effect.data.winfo_manager(), "")
        self.assertLess(effect.body.pack_slaves().index(effect.parameter_group), effect.body.pack_slaves().index(effect.choices))
        option = effect.choices.add_option()
        self.assertEqual(option.label.cget("text"), "分支 1")
        self.assertNotIn("choice_0", option.label.cget("text"))
        option.name.set("测试选项")
        option.add_effect({"effect_type": "attack_bonus", "effect_data": {"value": 3}})
        effect.choices.maximum.set("2")
        effect.choices.allow_duplicate.set(True)
        before = effect.choices.snapshot()
        effect.effect_type.set("")
        self.assertIsNone(panel.choices)
        self.assertEqual(effect.choices.winfo_manager(), "")
        self.assertEqual(effect.choices.parameters.winfo_manager(), "")
        effect.effect_type.set("choices")
        self.assertEqual(effect.choices.snapshot(), before)
        self.assertTrue(self.app.save())
        saved = CatalogProject(self.path).data["personal_skill"]["user_example"]["components"][0]
        self.assertEqual(saved["choices"]["maximum_selections"], 2)
        self.assertTrue(saved["choices"]["allow_duplicate"])
        self.assertTrue(all(item["effect_type"] != "choices" for item in saved["effects"]))

    def test_duplicate_choices_and_nested_choices_cannot_overwrite_saved_file(self):
        panel = self.new().components[0]
        first = panel.add_effect({"effect_type": "choices", "effect_data": {}})
        option = first.choices.add_option()
        option.name.set("第一项")
        nested = option.add_effect({"effect_type": "attack_bonus", "effect_data": {"value": 3}})
        self.assertNotIn("choices", nested.type_box.cget("values"))
        self.assertTrue(self.app.save())
        saved = self.path.read_bytes()
        panel = self.app.form.components[0]
        second = panel.add_effect({"effect_type": "choices", "effect_data": {}})
        option = second.choices.add_option()
        option.name.set("第二项")
        nested = option.add_effect({"effect_type": "attack_bonus", "effect_data": {"value": 4}})
        self.assertFalse(self.app.save())
        self.assertEqual(self.path.read_bytes(), saved)
        panel.remove_effect(second)
        nested = panel.choices.options[0].effects[0]
        nested.effect_type.set("choices")
        self.assertFalse(self.app.save())
        self.assertEqual(self.path.read_bytes(), saved)

    def test_choices_type_switch_retains_other_effect_drafts_and_branch_drafts(self):
        effect = self.new().components[0].effects[0]
        original = effect.read()
        effect.effect_type.set("choices")
        option = effect.choices.add_option()
        option.name.set("待保留分支")
        option.add_effect({"effect_type": "attack_bonus", "effect_data": {"value": 4}})
        choices = effect.read()
        effect.effect_type.set("attack_bonus")
        self.assertEqual(effect.read(), original)
        effect.effect_type.set("choices")
        self.assertEqual(effect.read(), choices)
        effect.reference_button.invoke()
        window = self.root._effect_reference_window
        self.assertEqual(window.current_effect, "choices")
        self.assertIn("maximum_selections", window.text.get("1.0", "end-1c"))
        self.assertIn("allow_duplicate", window.text.get("1.0", "end-1c"))

    def test_phase_area_only_shows_for_active_and_preserves_selected_phases(self):
        panel = self.new().components[0]
        phases = panel.phases.get()
        for kind in ("trigger", "react", "passive", ""):
            panel.kind.set(kind)
            self.assertEqual(panel.phase_area.winfo_manager(), "")
            self.assertEqual(panel.phases.get(), phases)
        panel.kind.set("active")
        self.assertEqual(panel.phase_area.winfo_manager(), "pack")
        self.assertEqual(panel.phases.get(), phases)

    def test_active_chant_controls_default_to_no_and_preserve_hidden_drafts(self):
        panel = self.new().components[0]
        self.assertEqual(panel.chant_choice.get(), "否")
        self.assertEqual(tuple(panel.chant_box.cget("values")), ("否", "是"))
        self.assertEqual(panel.chant_area.winfo_manager(), "pack")
        self.assertEqual(panel.chant_rounds_row.winfo_manager(), "")
        phases = panel.phases.get()
        panel.chant_choice.set("是")
        panel.chant_rounds.set("2")
        self.assertEqual(panel.chant_rounds_row.winfo_manager(), "pack")
        self.assertEqual(panel.phase_area.winfo_manager(), "")
        self.assertEqual(panel.phases.get(), phases)
        self.assertEqual(panel.read()["casting_requirement"], 2)
        for kind in ("trigger", "react", "passive", ""):
            panel.kind.set(kind)
            self.assertEqual(panel.chant_area.winfo_manager(), "")
        panel.kind.set("active")
        self.assertEqual(panel.chant_rounds.get(), "2")
        panel.chant_choice.set("否")
        self.assertEqual(panel.phase_area.winfo_manager(), "pack")
        self.assertEqual(panel.chant_rounds_row.winfo_manager(), "")
        self.assertNotIn("casting_requirement", panel.read())

    def test_new_chant_setting_saves_reopens_and_runs_the_existing_casting_flow(self):
        panel = self.new().components[0]
        panel.remove_cost(panel.costs[0])
        panel.chant_choice.set("是")
        panel.chant_rounds.set("2")
        self.set_phases(panel, [])
        self.assertTrue(self.app.save())
        saved = self.app.project.data["personal_skill"]["user_example"]
        self.assertEqual(saved["casting"], {"activation_mode": "release"})
        self.assertEqual(saved["components"][0]["casting_requirement"], 2)
        self.app.load("personal_skill", "user_example")
        panel = self.app.form.components[0]
        self.assertEqual(panel.chant_choice.get(), "是")
        self.assertEqual(panel.chant_rounds.get(), "2")
        self.assertEqual(panel.phase_area.winfo_manager(), "")
        self.assertFalse(self.app.dirty())
        from game.action.action_list import ActionContext, ActionListBuilder
        from game.skill.casting import CastingState
        actor = Master("Chanter", 3, 3, 3, 3, 3, "C", 3)
        skill = actor.create_personal_skill(saved)
        actions = ActionListBuilder()
        self.assertIn("chant", {a.action_id for a in actions.get_available_actions(ActionContext(actor, "AP1"))})
        state = CastingState.start(actor, skill, 1)
        self.assertEqual(state.eligible_components(), [])
        state.advance_at_global_turn_end(1)
        self.assertEqual(state.eligible_components(), [])
        state.continue_for_turn(2)
        state.advance_at_global_turn_end(2)
        self.assertEqual(state.eligible_components()[0]["component_id"], panel.component_id.get())

    def test_existing_chant_skills_load_requirements_and_keep_casting_configuration(self):
        for category in ("personal_skill", "noble_phantasm"):
            for key, saved in self.app.project.effective()[category].items():
                self.app.load(category, key)
                for data, panel in zip(saved["components"], self.app.form.components):
                    if data.get("type") == "active" and data.get("casting_requirement", 0) > 0:
                        self.assertEqual(panel.chant_choice.get(), "是")
                        self.assertEqual(panel.chant_rounds.get(), str(data["casting_requirement"]))
                        self.assertEqual(panel.phase_area.winfo_manager(), "")
                self.assertEqual(self.app.definition(), saved)
        self.app.load("noble_phantasm", "servant_test_0:golden_theatre")
        self.app.form.components[0].chant_rounds.set("2")
        saved = self.app.definition()
        self.assertEqual(saved["casting"]["activation_mode"], "automatic")
        self.assertEqual(saved["casting"]["auto_activate_component_id"], "open_theatre")

    def test_invalid_chant_rounds_do_not_overwrite_saved_data_and_instant_mode_can_be_changed(self):
        panel = self.new().components[0]
        self.assertTrue(self.app.save())
        saved_bytes = self.path.read_bytes()
        panel = self.app.form.components[0]
        panel.chant_choice.set("是")
        for value in ("", "0", "-1", "1.5", "true"):
            panel.chant_rounds.set(value)
            self.assertFalse(self.app.save())
            self.assertEqual(self.path.read_bytes(), saved_bytes)
        panel.chant_rounds.set("1")
        self.set_json(self.app.form.extras, {"casting": {"activation_mode": "instant"}})
        self.assertTrue(self.app.save())
        self.assertEqual(self.app.project.data["personal_skill"]["user_example"]["casting"],
                         {"activation_mode": "release"})

    def test_inherited_noble_chant_requirement_is_visible_and_new_units_default_to_no(self):
        data = new_client_definition("宝具", "chant_noble")
        data["range_type"] = "anti_army"
        data["components"] = [{"component_id": "implicit", "type": "active", "target": "self",
                               "effects": [{"effect_type": "attack_bonus", "effect_data": {"value": 5}}]}]
        self.app.load("noble_phantasm", "chant_noble", data)
        panel = self.app.form.components[0]
        self.assertEqual(panel.chant_choice.get(), "是")
        self.assertEqual(panel.chant_rounds.get(), "1")
        data["components"][0]["cost"] = [{"resource": "mp", "value": 30, "timing": "casting_start"}]
        self.assertEqual(self.app.definition(), data)
        second = self.app.form.add_component()
        self.assertEqual(second.chant_choice.get(), "否")
        second.kind.set("active")
        second.target.set("self")
        self.assertEqual(second.read()["casting_requirement"], 0)

    def test_trigger_condition_form_saves_reloads_and_executes_boolean_filters(self):
        panel = self.new().components[0]
        panel.remove_cost(panel.costs[0])
        panel.remove_effect(panel.effects[0])
        panel.add_effect({"effect_type": "recover_resource", "effect_data": {"resource_id": "hp", "value": 5}})
        panel.kind.set("trigger")
        panel.trigger_editor.load({"event_type": "damage_received", "timing": "after"})
        editor = panel.condition_editor
        self.assertEqual(editor.winfo_manager(), "pack")
        first, = editor.rows
        self.assertEqual(first.selection.get(), "")
        first.selection.set(CONDITION_NAMES["event_target_is_self"])
        first.add_button.invoke()
        second = editor.rows[1]
        second.selection.set(CONDITION_NAMES["event_value_at_least"])
        second.value.set("20")
        second.join.set("或")
        second.add_button.invoke()
        third = editor.rows[2]
        third.selection.set(CONDITION_NAMES["damage_type"])
        third.value.set("魔术")
        third.negated.set(True)
        self.assertEqual(str(second.join_box.cget("state")), "readonly")
        self.assertEqual(tuple(second.join_box.cget("values")), ("与", "或"))
        self.assertIn("事件", first.description.cget("text"))
        self.assertEqual(ttk.Style(self.root).lookup(editor.cget("style"), "background"),
                         ttk.Style(self.root).lookup(panel.phase_area.cget("style"), "background"))
        self.assertTrue(self.app.save())
        saved = CatalogProject(self.path).data["personal_skill"]["user_example"]
        condition = saved["components"][0]["condition"]
        self.assertEqual(condition, {"all": [
            {"any": [{"event_target_is_self": True}, {"event_value_at_least": 20}]},
            {"not": {"damage_type": "magic"}},
        ]})
        self.app.load("personal_skill", "user_example")
        panel = self.app.form.components[0]
        self.assertEqual(len(panel.condition_editor.rows), 3)
        self.assertEqual(self.app.definition(), saved)
        self.assertEqual(panel.condition_editor.rows[2].join.get(), "与")
        self.assertTrue(panel.condition_editor.rows[2].negated.get())
        self.assertNotIn("condition", json.loads(panel.extras.get()))
        from game.game.game_manager import GameManager
        from game.map.map import Location
        actor = Master("Actor", 3, 3, 3, 3, 3, "C", 3)
        source = Master("Source", 3, 3, 3, 3, 3, "C", 3)
        actor.create_personal_skill(saved)
        location = Location("A")
        actor.position = source.position = location
        game = GameManager([actor, source], location)
        game.start_game()
        actor.hp -= 20
        hp = actor.hp
        game.event_manager.emit("damage_received", actor=source, target=actor, value=10, payload={"damage_type": "physical"})
        self.assertEqual(actor.hp, hp + 5)
        game.event_manager.emit("damage_received", actor=source, target=actor, value=30, payload={"damage_type": "magic"})
        self.assertEqual(actor.hp, hp + 5)

    def test_condition_delete_buttons_follow_their_rows_and_hide_for_last_row(self):
        panel = self.new().components[0]
        panel.kind.set("trigger")
        editor = panel.condition_editor
        first = editor.rows[0]
        first.selection.set(CONDITION_NAMES["battle_state"])
        self.assertEqual(first.delete_button.winfo_manager(), "")
        first.add_button.invoke()
        second = editor.rows[1]
        second.selection.set(CONDITION_NAMES["actor_alive"])
        second.negated.set(True)
        for row in editor.rows:
            self.assertEqual(row.pack_slaves()[-2:], [row.delete_button, row.add_button])
            self.assertEqual(row.delete_button.cget("text"), "删除此条件")
            self.assertEqual(row.delete_button.cget("style"), panel.delete_button.cget("style"))
        first.delete_button.invoke()
        self.assertEqual(editor.rows, [second])
        self.assertEqual(second.caption.cget("text"), "条件1：")
        self.assertEqual(second.delete_button.winfo_manager(), "")
        self.assertEqual(editor.get(), {"not": {"actor_alive": True}})
        editor.remove_row(second)
        self.assertEqual(editor.rows, [second])

    def test_condition_type_switch_preserves_flat_advanced_and_form_changes(self):
        panel = self.new().components[0]
        original = {"battle_state": True, "event_target_is_self": True}
        self.set_json(panel.extras, {"condition": original, "trigger": {"event_type": "damage_received"}})
        panel.kind.set("trigger")
        self.assertEqual(panel.condition_editor.get(), original)
        panel.condition_editor.rows[1].value.set("否")
        changed = panel.condition_editor.get()
        panel.kind.set("active")
        self.assertEqual(panel.condition_editor.winfo_manager(), "")
        self.assertEqual(json.loads(panel.extras.get())["condition"], changed)
        panel.kind.set("trigger")
        self.assertEqual(panel.condition_editor.get(), changed)
        self.assertEqual(panel.condition_editor.rows[1].value.get(), "否")

    def test_invalid_condition_drafts_and_blank_added_rows_do_not_overwrite_file(self):
        panel = self.new().components[0]
        panel.kind.set("trigger")
        panel.trigger_editor.load({"event_type": "damage_received"})
        self.assertTrue(self.app.save())
        saved = self.path.read_bytes()
        editor = self.app.form.components[0].condition_editor
        first = editor.rows[0]
        first.selection.set(CONDITION_NAMES["event_target_is_self"])
        first.add_button.invoke()
        self.assertFalse(self.app.save())
        self.assertEqual(self.path.read_bytes(), saved)
        editor.remove_row(editor.rows[1])
        editor.show_json()
        editor.raw.text.insert("1.0", "invalid")
        self.assertFalse(self.app.save())
        self.assertEqual(self.path.read_bytes(), saved)
        self.assertTrue(self.app.dirty())
        panel = self.app.form.components[0]
        panel.kind.set("active")
        self.assertTrue(panel.condition_sync_notice.winfo_manager())
        self.assertIn("invalid", editor.raw.get())

    def test_imperial_privilege_event_is_visible_and_round_trips_without_changes(self):
        key = "servant_test_0:imperial_privilege"
        self.app.load("personal_skill", key)
        panel = self.app.form.components[0]
        event = panel.trigger_editor
        self.assertEqual(event.winfo_manager(), "pack")
        self.assertEqual(event.selection.get(), "全局回合开始")
        self.assertIn("皇帝特权", event.description.cget("text"))
        self.assertEqual(event.timing.get(), "事件发生后")
        self.assertEqual(event.get()["priority"], 100)
        children = panel.body.pack_slaves()
        self.assertLess(children.index(event), children.index(panel.condition_editor))
        self.assertEqual(self.app.definition(), self.app.project.effective()["personal_skill"][key])
        self.assertNotIn("trigger", json.loads(panel.extras.get()))
        self.assertFalse(self.app.dirty())

    def test_unit_cost_form_edits_prepaid_and_activation_costs_without_public_costs(self):
        key = "servant_test_0:golden_theatre"
        self.app.load("noble_phantasm", key)
        form = self.app.form.components[0]
        self.assertFalse(hasattr(self.app.form, "cost_group"))
        self.assertFalse(form.cost_group.expanded)
        first = form.costs[0]
        self.assertEqual(first.value.get(), "40")
        self.assertEqual(first.timing.get(), COST_TIMING_NAMES["casting_start"])
        self.assertEqual(tuple(first.resource_box.cget("values")), ("mp",))
        first.value.set("45")
        second = form.add_cost({"resource": "mp", "value": 3})
        self.assertEqual(second.timing.get(), COST_TIMING_NAMES["activation"])
        self.assertEqual(str(second.timing_box.cget("state")), "readonly")
        self.set_json(second.extras, {"cost_id": "extra_release"})
        self.assertTrue(self.app.save())
        saved = self.app.project.data["noble_phantasm"][key]
        self.assertEqual(saved["components"][0]["cost"], [
            {"resource": "mp", "value": 45, "timing": "casting_start"},
            {"resource": "mp", "value": 3, "cost_id": "extra_release"}])
        self.assertEqual(saved["casting"]["activation_mode"], "automatic")
        self.app.load("noble_phantasm", key)
        self.assertEqual([row.read() for row in self.app.form.components[0].costs], saved["components"][0]["cost"])
        self.assertNotIn("cost", saved)
        self.assertFalse(self.app.dirty())

    def test_invalid_unit_cost_keeps_saved_file_and_draft_then_can_be_deleted(self):
        panel = self.new().components[0]
        panel.remove_cost(panel.costs[0])
        self.assertTrue(self.app.save())
        saved = self.path.read_bytes()
        form = self.app.form.components[0]
        row = form.add_cost({"resource": "hp", "value": 1, "timing": "casting_start"})
        self.assertFalse(self.app.save())
        self.assertEqual(self.path.read_bytes(), saved)
        self.assertTrue(self.app.dirty())
        row.resource.set("mp")
        row.value.set("invalid")
        self.assertFalse(self.app.save())
        self.assertEqual(row.value.get(), "invalid")
        form.remove_cost(row)
        self.assertEqual(form.cost_rows.cget("height"), 1)
        self.assertTrue(self.app.save())

    def test_two_units_save_independent_complete_costs_without_a_public_cost_area(self):
        form = self.new()
        first = form.components[0]
        first.remove_cost(first.costs[0])
        first.chant_choice.set("是")
        first.add_cost({"resource": "mp", "value": 10, "timing": "casting_start"})
        second = form.add_component()
        second.kind.set("active")
        second.target.set("self")
        second.chant_choice.set("是")
        second.chant_rounds.set("2")
        second.add_cost({"resource": "mp", "value": 40, "timing": "casting_start"})
        second.add_effect({"effect_type": "attack_bonus", "effect_data": {"value": 3}})
        self.assertFalse(hasattr(form, "cost_group"))
        self.assertTrue(self.app.save())
        saved = self.app.project.data["personal_skill"]["user_example"]
        self.assertNotIn("cost", saved)
        self.assertEqual([unit["cost"][0]["value"] for unit in saved["components"]], [10, 40])
        self.app.load("personal_skill", "user_example")
        self.app.form.components[0].costs[0].value.set("12")
        self.assertTrue(self.app.save())
        saved = self.app.project.data["personal_skill"]["user_example"]
        self.assertEqual([unit["cost"][0]["value"] for unit in saved["components"]], [12, 40])

    def test_field_maintenance_uses_graphical_cost_rows_and_preserves_type_switch_drafts(self):
        panel = self.new().components[0]
        effect = panel.effects[0]
        effect.effect_type.set("create_field")
        self.set_json(effect.extras, {})
        self.set_json(effect.data, {"field_id": "cost_field"})
        effect.data.show_form()
        costs = effect.data.add_field("cost", empty=True)
        costs.input.invoke()
        row = costs.rows[0]
        row.value.set("5")
        self.assertEqual(row.timing.get(), COST_TIMING_NAMES["maintenance"])
        self.assertEqual(tuple(row.timing_box.cget("values")), (COST_TIMING_NAMES["maintenance"],))
        self.assertTrue(self.app.save())
        saved = self.path.read_bytes()
        effect = self.app.form.components[0].effects[0]
        self.assertEqual(effect.data.rows["cost"].read(), [{"resource": "mp", "value": 5, "timing": "maintenance"}])
        effect.effect_type.set("attack_bonus")
        self.assertIn("当前类型不支持", effect.data.rows["cost"].label.cget("text"))
        self.assertFalse(self.app.save())
        self.assertEqual(self.path.read_bytes(), saved)
        effect.effect_type.set("create_field")
        self.assertTrue(self.app.save())

    def test_noble_implicit_rank_cost_is_shown_and_saved_explicitly(self):
        key = "servant_test_0:laus_saint_claudius"
        data = deepcopy(self.app.project.effective()["noble_phantasm"][key])
        data["components"][0].pop("cost")
        self.app.load("noble_phantasm", key, data)
        self.assertEqual(self.app.form.components[0].costs[0].value.get(), "100")
        self.assertEqual(self.app.form.components[0].costs[0].timing.get(), COST_TIMING_NAMES["casting_start"])
        self.assertTrue(self.app.save())
        self.assertEqual(self.app.project.data["noble_phantasm"][key]["components"][0]["cost"],
                         [{"resource": "mp", "value": 100, "timing": "casting_start"}])

    def test_trigger_event_selection_saves_timing_and_preserves_extra_configuration(self):
        panel = self.new().components[0]
        panel.kind.set("trigger")
        event = panel.trigger_editor
        self.assertEqual(event.selection.get(), "")
        self.assertEqual(event.description.cget("text"), "选择触发事件")
        event.load({"event_type": "global_turn_start", "priority": 20, "allow_when_dead": True})
        event.selection.set("伤害结算前")
        self.assertEqual(event.timing.get(), "事件发生前")
        self.assertEqual(tuple(event.timing_box.cget("values")), ("事件发生前",))
        self.assertTrue(self.app.save())
        saved = self.app.project.data["personal_skill"]["user_example"]
        self.assertEqual(saved["components"][0]["trigger"], {
            "event_type": "before_damage", "timing": "before", "priority": 20, "allow_when_dead": True})
        self.app.load("personal_skill", "user_example")
        event = self.app.form.components[0].trigger_editor
        self.assertEqual(event.selection.get(), "伤害结算前")
        self.assertEqual(event.get(), saved["components"][0]["trigger"])
        self.assertFalse(self.app.dirty())

    def test_trigger_event_switching_types_and_invalid_drafts_preserve_data(self):
        panel = self.new().components[0]
        self.set_json(panel.extras, {"trigger": {"event_type": "custom_event", "timing": "before", "priority": 3}, "tag": "keep"})
        panel.kind.set("trigger")
        event = panel.trigger_editor
        self.assertEqual(event.selection.get(), "custom_event")
        self.assertEqual(event.timing.get(), "事件发生前")
        self.assertIn("自定义", event.description.cget("text"))
        panel.kind.set("react")
        self.assertEqual(event.winfo_manager(), "pack")
        event.selection.set("受到伤害后")
        panel.kind.set("active")
        self.assertEqual(event.winfo_manager(), "")
        self.assertEqual(json.loads(panel.extras.get()), {
            "trigger": {"event_type": "damage_received", "timing": "after", "priority": 3}, "tag": "keep"})
        panel.kind.set("trigger")
        self.assertEqual(event.selection.get(), "受到伤害后")
        self.assertTrue(self.app.save())
        saved = self.path.read_bytes()
        event = self.app.form.components[0].trigger_editor
        event.extras.text.insert("1.0", "invalid")
        self.app.form.components[0].kind.set("passive")
        self.assertTrue(self.app.form.components[0].trigger_sync_notice.winfo_manager())
        self.assertEqual(event.winfo_manager(), "pack")
        self.assertFalse(self.app.save())
        self.assertEqual(self.path.read_bytes(), saved)
        self.assertIn("invalid", event.extras.get())

    def test_builtin_events_and_legacy_event_ids_preserve_canonical_definitions(self):
        self.assertEqual(len({v[0] for v in EVENT_OPTIONS.values()}), len(EVENT_OPTIONS))
        for key, value in self.app.project.effective()["personal_skill"].items():
            self.app.load("personal_skill", key)
            self.assertEqual(self.app.definition(), value)
        value = self.new().read()
        value["components"][0].update(type="trigger", trigger_event="custom_legacy", priority=15)
        self.app.load("personal_skill", "user_example", value)
        event = self.app.form.components[0].trigger_editor
        self.assertEqual(event.selection.get(), "custom_legacy")
        self.assertEqual(self.app.definition(), value)
        event.selection.set("全局回合开始")
        self.assertEqual(event.get(), {"event_type": "global_turn_start"})
        self.assertEqual(self.app.definition()["components"][0]["priority"], 15)

    def test_grouped_conditions_use_advanced_json_without_flattening(self):
        original = self.new().read()
        condition = {"all": [{"battle_state": True}, {"any": [{"actor_alive": True}, {"event_target_is_self": True}]}]}
        original["components"][0].update(type="trigger", condition=condition, trigger={"event_type": "damage_received"})
        self.app.project.put("personal_skill", "user_example", original)
        self.app.load("personal_skill", "user_example", original)
        editor = self.app.form.components[0].condition_editor
        self.assertEqual(editor.mode, "json")
        self.assertEqual(self.app.definition(), original)
        self.assertFalse(self.app.dirty())
        with self.assertRaisesRegex(ValueError, "嵌套分组"):
            editor.show_form()
        self.assertEqual(editor.get(), condition)

    def test_malformed_import_remains_repairable_and_can_be_left(self):
        self.app.load("personal_skill", "broken", {"skill_id": "broken", "components": [None]})
        self.assertFalse(self.app.form_mode)
        self.assertTrue(self.app.dirty())
        self.mock("SkillEditorClient.app.messagebox.askyesnocancel", return_value=False)
        self.assertTrue(self.app.leave())
        self.app.load("personal_skill", "master_test_0:starfire")
        self.assertTrue(self.app.form_mode)


def parse(text):
    return json.loads(text.get("1.0", "end-1c"))


if __name__ == "__main__":
    unittest.main()
