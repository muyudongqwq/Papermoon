"""Real Tk widget smoke checks. Run on a desktop: python -m test_examples.smoke_skill_editor.

Kept separate from headless rule discovery because Tcl needs desktop access.
No dialogs or testing subprocesses are opened by these checks.
"""

import json
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import font as tkfont
import unittest
from unittest.mock import patch

from core.catalog import CatalogProject
from skilleditor.app import SkillEditor
from skilleditor.documents import format_json
from skilleditor.display import enable_high_dpi


class SkillEditorSmokeTests(unittest.TestCase):
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
        self.original_ui_font = tkfont.nametofont("TkDefaultFont", root=self.root).actual()
        from tkinter import ttk
        self.original_rowheight = int(ttk.Style(self.root).lookup("Treeview", "rowheight") or 20)
        self.app = SkillEditor(self.root, CatalogProject(self.path))
        self.error = self.enter_patch("skilleditor.app.messagebox.showerror")
        self.root.update()

    def enter_patch(self, name, **kwargs):
        manager = patch(name, **kwargs)
        mocked = manager.start()
        self.addCleanup(manager.stop)
        return mocked

    def edit(self, transform):
        data = json.loads(self.app.text.get("1.0", "end-1c"))
        transform(data)
        self.app.text.delete("1.0", "end")
        self.app.text.insert("1.0", format_json(data))

    def test_window_load_search_and_clean_document(self):
        self.assertEqual(len(self.app.items), sum(len(entries) for entries in self.app.project.effective().values()))
        self.app.load("personal_skill", "master_test_0:unblemished_person")
        self.root.update_idletasks()
        self.assertFalse(self.app.dirty())
        self.app.search.set("unblemished")
        self.assertEqual(len(self.app.items), 1)
        self.assertEqual(self.app.current[1], "master_test_0:unblemished_person")

    def test_validation_save_and_reopen_use_same_project(self):
        self.app.load("personal_skill", "master_test_0:unblemished_person")
        self.edit(lambda data: data.update(name="Edited name"))
        self.assertTrue(self.app.dirty())
        self.assertTrue(self.app.validate())
        self.assertFalse(self.path.exists())
        self.assertTrue(self.app.save())
        self.assertFalse(self.app.dirty())
        reloaded = CatalogProject(self.path)
        self.assertEqual(reloaded.data["personal_skill"][self.app.current[1]]["name"], "Edited name")

    def test_invalid_document_cannot_overwrite_saved_project(self):
        self.app.load("personal_skill", "master_test_0:unblemished_person")
        self.assertTrue(self.app.save())
        original = self.path.read_bytes()
        self.app.text.insert("1.0", "invalid-json")
        self.assertFalse(self.app.save())
        self.assertEqual(self.path.read_bytes(), original)
        self.error.assert_called_once()

    def test_new_and_duplicate_entries_get_their_own_ids(self):
        dialog = self.enter_patch("skilleditor.app.simpledialog.askstring", return_value="user_new")
        self.app.new()
        self.assertTrue(self.app.dirty())
        self.assertTrue(self.app.save())
        dialog.return_value = "user_copy"
        self.app.duplicate()
        self.assertEqual(self.app.current, ("personal_skill", "user_copy"))
        self.assertEqual(json.loads(self.app.text.get("1.0", "end-1c"))["skill_id"], "user_copy")
        self.assertTrue(self.app.save())
        self.assertEqual(set(self.app.project.data["personal_skill"]), {"user_new", "user_copy"})

    def test_restore_builtin_and_delete_custom_entry(self):
        self.enter_patch("skilleditor.app.messagebox.askyesno", return_value=True)
        self.app.load("personal_skill", "master_test_0:unblemished_person")
        self.edit(lambda data: data.update(name="Edited"))
        self.app.save()
        self.app.remove()
        self.assertEqual(self.app.project.data["personal_skill"], {})
        self.enter_patch("skilleditor.app.simpledialog.askstring", return_value="user_delete")
        self.app.new()
        self.app.save()
        self.app.remove()
        self.assertIsNone(self.app.current)
        self.assertEqual(self.app.project.data["personal_skill"], {})

    def test_saving_during_selection_change_keeps_clicked_entry_selected(self):
        self.app.refresh(select=("personal_skill", "master_test_0:unblemished_person"))
        self.edit(lambda data: data.update(name="Edited"))
        self.enter_patch("skilleditor.app.messagebox.askyesnocancel", return_value=True)
        target = ("character_card", "master_test_0")
        node = next(node for node, entry in self.app.items.items() if entry == target)
        self.app.tree.selection_set(node)
        self.root.update()
        self.assertEqual(self.app.current, target)
        self.assertEqual(self.app.items[self.app.tree.selection()[0]], target)
        self.assertEqual(self.app.project.data["personal_skill"]["master_test_0:unblemished_person"]["name"], "Edited")

    def test_cancel_selection_keeps_unsaved_document(self):
        initial = ("personal_skill", "master_test_0:unblemished_person")
        self.app.refresh(select=initial)
        self.edit(lambda data: data.update(name="Unsaved"))
        self.enter_patch("skilleditor.app.messagebox.askyesnocancel", return_value=None)
        node = next(node for node, entry in self.app.items.items() if entry == ("character_card", "master_test_0"))
        self.app.tree.selection_set(node)
        self.root.update()
        self.assertEqual(self.app.current, initial)
        self.assertTrue(self.app.dirty())
        self.assertIn("Unsaved", self.app.text.get("1.0", "end-1c"))

    def test_launch_uses_saved_project_in_separate_core_process(self):
        popen = self.enter_patch("skilleditor.app.subprocess.Popen")
        self.app.launch_core()
        args, kwargs = popen.call_args
        self.assertIn("core", args[0])
        self.assertIn(str(self.path), args[0])
        self.assertIn("--pause-on-exit", args[0])
        self.assertTrue(Path(kwargs["cwd"]).is_dir())

    def test_class_skill_can_be_created_copied_and_reopened(self):
        self.app.kind.set("职介技能")
        dialog = self.enter_patch("skilleditor.app.simpledialog.askstring", return_value="测试职介能力")
        self.app.new()
        self.assertEqual(self.app.current, ("class_skill", "测试职介能力"))
        self.assertTrue(self.app.validate())
        self.assertTrue(self.app.save())
        dialog.return_value = "测试职介能力副本"
        self.app.duplicate()
        self.assertTrue(self.app.save())
        reopened = CatalogProject(self.path)
        copied = reopened.data["class_skill"]["测试职介能力副本"]
        self.assertEqual(copied["name"], "测试职介能力副本")
        self.assertIn("C", copied["ranks"])

    def test_class_skill_import_export_and_restore_use_same_schema(self):
        self.app.refresh(select=("class_skill", "对魔力"))
        self.edit(lambda data: data["ranks"]["C"][0]["effects"][0]["effect_data"].update(value=0.9))
        self.assertTrue(self.app.save())
        exported = self.path.parent / "export.json"
        self.enter_patch("skilleditor.app.filedialog.asksaveasfilename", return_value=str(exported))
        self.app.export_entry()
        self.assertEqual(json.loads(exported.read_text(encoding="utf-8"))["category"], "class_skill")
        self.enter_patch("skilleditor.app.messagebox.askyesno", return_value=True)
        self.app.remove()
        self.assertEqual(self.app.project.data["class_skill"], {})
        self.enter_patch("skilleditor.app.filedialog.askopenfilename", return_value=str(exported))
        self.app.import_entry()
        self.assertTrue(self.app.dirty())
        self.assertTrue(self.app.save())
        self.assertIn("对魔力", self.app.project.data["class_skill"])

    def test_original_fonts_and_spacing_are_preserved_with_native_dpi(self):
        text_font = tkfont.Font(root=self.root, font=self.app.text.cget("font"))
        self.assertEqual(text_font.actual("family"), "Consolas")
        self.assertEqual(text_font.actual("size"), 11)
        ui_font = tkfont.nametofont("TkDefaultFont", root=self.root)
        self.assertEqual(ui_font.actual(), self.original_ui_font)
        self.assertGreater(text_font.measure("职介技能"), 0)
        for option in ("spacing1", "spacing2", "spacing3"):
            self.assertEqual(int(self.app.text.cget(option)), 0)
        from tkinter import ttk
        row_height = ttk.Style(self.root).lookup("Treeview", "rowheight")
        scale = max(1.0, self.root.winfo_fpixels("1i") / 96)
        self.assertAlmostEqual(int(row_height) / scale, self.original_rowheight, delta=1)
        if __import__("sys").platform == "win32":
            import ctypes
            awareness = ctypes.c_int()
            self.assertEqual(ctypes.windll.shcore.GetProcessDpiAwareness(None, ctypes.byref(awareness)), 0)
            self.assertEqual(awareness.value, 2)

    def test_status_can_be_created_copied_saved_and_deleted(self):
        self.app.kind.set("状态")
        dialog = self.enter_patch("skilleditor.app.simpledialog.askstring", return_value="my_burning")
        self.app.new()
        self.assertEqual(self.app.current, ("status", "my_burning"))
        self.assertTrue(self.app.validate())
        self.assertTrue(self.app.save())
        dialog.return_value = "other_burning"
        self.app.duplicate()
        self.assertTrue(self.app.save())
        loaded = CatalogProject(self.path)
        self.assertEqual(loaded.data["status"]["other_burning"]["status_id"], "other_burning")
        self.enter_patch("skilleditor.app.messagebox.askyesno", return_value=True)
        self.app.remove()
        self.assertNotIn("other_burning", CatalogProject(self.path).data["status"])

    def test_status_export_import_and_builtin_restore(self):
        self.app.refresh(select=("status", "burning"))
        self.edit(lambda data: data.update(duration=7))
        self.assertTrue(self.app.save())
        exported = self.path.parent / "status.json"
        self.enter_patch("skilleditor.app.filedialog.asksaveasfilename", return_value=str(exported))
        self.app.export_entry()
        self.assertEqual(json.loads(exported.read_text(encoding="utf-8"))["category"], "status")
        self.enter_patch("skilleditor.app.messagebox.askyesno", return_value=True)
        self.app.remove()
        self.assertEqual(self.app.project.effective()["status"]["burning"]["duration"], 3)
        self.enter_patch("skilleditor.app.filedialog.askopenfilename", return_value=str(exported))
        self.app.import_entry()
        self.assertTrue(self.app.save())
        self.assertEqual(self.app.project.data["status"]["burning"]["duration"], 7)

    def test_status_stack_formula_can_be_edited_validated_and_saved(self):
        self.app.refresh(select=("status", "burning"))
        self.assertIn("status_stack_count", self.app.status.get())
        def change(data):
            data["stacking"]["max_stacks"] = 4
            data["components"][0]["effects"][0]["effect_data"].update(multiplier=6, flat=2)
        self.edit(change)
        self.assertTrue(self.app.validate())
        self.assertTrue(self.app.save())
        saved = CatalogProject(self.path).data["status"]["burning"]
        self.assertEqual(saved["stacking"]["max_stacks"], 4)
        formula = saved["components"][0]["effects"][0]["effect_data"]
        self.assertEqual((formula["value_source"], formula["multiplier"], formula["flat"]),
                         ("status_stack_count", 6, 2))


if __name__ == "__main__":
    unittest.main()
