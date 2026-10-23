"""Experimental forms layered on the unchanged original editor's catalog UI."""

from copy import copy
from pathlib import Path
import os
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import traceback

from core.catalog import CatalogProject, DEFAULT_CATALOG, DATA_ROOT, parse_json
from skilleditor.app import SkillEditor
from skilleditor.display import enable_high_dpi
from skilleditor.documents import KINDS, format_json, parse_entry
from SkillEditorClient import VERSION
from SkillEditorClient.dialogs import ask_new_skill
from SkillEditorClient.forms import SkillForm
from SkillEditorClient.effect_reference import read_dictionary, show_effect_reference
from SkillEditorClient.model import FORM_CATEGORIES, can_use_form, new_client_definition, new_skill_key, new_personal_skill_key
from SkillEditorClient.widgets import ScrollForm


class SkillEditorClient(SkillEditor):
    def __init__(self, root, project=None):
        self.form = None
        self.form_mode = False
        self.force_dirty = False
        self.loaded_snapshot = None
        super().__init__(root, project)
        self.root.title(f"Papermoon · SkillEditorClient {VERSION}（表单试验版）")

    def _build(self):
        # Keep the original toolbar, left catalog and class editor unchanged.
        super()._build()
        next(widget for widget in self.path_label.master.winfo_children()[0].winfo_children()
             if isinstance(widget, ttk.Button) and widget.cget("text") == "整理JSON").destroy()
        toolbar = self.path_label.master.winfo_children()[0]
        ttk.Button(toolbar, text="效果字典", command=self.open_effect_reference).pack(side="left", padx=3)
        self.json_tab = self.entry_label.master
        self.notebook = self.json_tab.master
        self.form_tab = ttk.Frame(self.notebook)
        self.notebook.insert(0, self.form_tab, text="技能编辑器 · 试验版")
        self.notebook.tab(self.json_tab, text="条目高级设置")
        self.scroll_form = ScrollForm(self.form_tab)
        self.scroll_form.pack(fill="both", expand=True)
        self.form_message = ttk.Label(self.scroll_form.body, text="请选择一个技能，或新建主动技能。", padding=10)
        self.form_message.pack(anchor="w")
        self.notebook.bind("<<NotebookTabChanged>>", self.tab_changed)
        self.notebook.select(self.form_tab)
        self.status.set("先填写名称和Rank，再按需新建技能单元与效果；复杂结构可在相应高级设置中编辑。")

    def load(self, category, key, definition=None):
        self.text.configure(state="normal")
        super().load(category, key, definition)
        definition = parse_json(self.loaded_text)
        if self.form is not None:
            self.form.destroy()
            self.form = None
        self.form_mode = category in FORM_CATEGORIES and can_use_form(definition)
        self.force_dirty = False
        if self.form_mode:
            self.form_message.pack_forget()
            self.form = SkillForm(self.scroll_form.body, definition, self.project.effective())
            self.form.pack(fill="x")
            self.form.collapse_all()
            self.loaded_snapshot = self.form.snapshot()
            self.text.configure(state="disabled")
            self.notebook.tab(self.json_tab, text="JSON预览（只读）")
            self.notebook.select(self.form_tab)
            self.status.set("按需新建技能单元和效果，编辑完成后保存；触发事件可直接选择，复杂参数可在相应高级设置中配置。")
            self.scroll_form.canvas.yview_moveto(0)
        else:
            self.form_message.configure(text="该类型或条目结构本轮沿用JSON编辑方式；新建主动技能可使用表单。")
            self.form_message.pack(anchor="w")
            self.notebook.tab(self.json_tab, text="条目高级设置")
            self.notebook.select(self.json_tab)

    def on_select(self, event=None):
        if self._loading:
            return
        selection = self.tree.selection()
        selected = self.items.get(selection[0]) if selection else None
        if selected == self.current and self.form_mode:
            # Re-selecting a skill resets its view without reloading or
            # discarding the current draft, including incomplete JSON.
            self.form.collapse_all()
            self.notebook.select(self.form_tab)
            self.scroll_form.canvas.yview_moveto(0)
            return
        super().on_select(event)

    def refresh(self, select=None, *, keep_document=False):
        super().refresh(select, keep_document=keep_document)
        for group in self.tree.get_children():
            nodes = self.tree.get_children(group)
            if not nodes or self.items.get(nodes[0], (None,))[0] != "personal_skill":
                continue
            def order(item):
                index, node = item
                key = self.items[node][1]
                return (0, int(key)) if key.isascii() and key.isdecimal() else (1, index)
            for index, (_, node) in enumerate(sorted(enumerate(nodes), key=order)):
                self.tree.move(node, group, index)
        selection = self.tree.selection()
        if selection:
            self.tree.see(selection[0])

    def open_effect_reference(self):
        kind = None
        if self.form_mode:
            kind = next((effect.effect_type.get().strip() for component in self.form.components
                         for group in (component, *(component.choices.options if component.choices is not None else ()))
                         for effect in group.effects if effect.effect_type.get().strip()), None)
        return show_effect_reference(self.root, kind, self.project.effective())

    def read_reference_dictionary(self):
        return read_dictionary()

    def dirty(self):
        if self.current is None:
            return False
        if self.force_dirty or self.current[1] not in self.project.effective()[self.current[0]]:
            return True
        if self.form_mode:
            return self.form.snapshot() != self.loaded_snapshot
        return super().dirty()

    def definition(self):
        return self.form.read() if self.form_mode else parse_json(self.text.get("1.0", "end-1c"))

    def candidate(self):
        if self.current is None:
            raise ValueError("请先选择或新建条目")
        candidate = copy(self.project)
        candidate.data = parse_json(format_json(self.project.data))
        candidate.put(*self.current, self.definition())
        return candidate

    def update_preview(self):
        try:
            text = format_json(self.definition())
        except (ValueError, TypeError) as error:
            text = f"表单尚未填写完整：{error}\n请返回技能表单继续编辑。"
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", text)
        self.text.configure(state="disabled")

    def tab_changed(self, _event=None):
        if self.form_mode and self.notebook.select() == str(self.json_tab):
            self.update_preview()

    def format(self):
        if self.form_mode:
            self.update_preview()
            self.notebook.select(self.json_tab)
            self.status.set("已刷新只读JSON预览，表单草稿尚未保存。")
        else:
            super().format()

    def new(self):
        if not self.leave():
            return
        kind = self.kind.get()
        category = KINDS[kind]
        if category in FORM_CATEGORIES:
            details = ask_new_skill(self.root)
            if details is None:
                return
            name, rank = details
            existing = self.project.effective()[category]
            key = new_personal_skill_key(existing) if category == "personal_skill" else new_skill_key(name, rank, existing)
            self.load(category, key, new_client_definition(kind, key, name=name, rank=rank))
            return
        prompt = "请输入职介技能名称（角色卡使用此名称引用）：" if category == "class_skill" else "请输入不重复的新ID（技能使用skill_id）："
        initial = "自定义职介技能" if category == "class_skill" else "user_new_card" if category == "character_card" else "user_new_status" if category == "status" else "user_new_skill"
        key = simpledialog.askstring("新建条目", prompt, initialvalue=initial, parent=self.root)
        if not key:
            return
        if key in self.project.effective()[category]:
            self.error("该ID已存在，请另取一个ID或直接编辑已有条目")
            return
        self.load(category, key, new_client_definition(kind, key))

    def import_entry(self):
        if not self.leave():
            return
        path = filedialog.askopenfilename(title="导入单个条目", filetypes=[("JSON条目", "*.json")])
        if not path:
            return
        try:
            data = parse_entry(Path(path).read_text(encoding="utf-8-sig"))
            self.load(data["category"], data["entry_id"], data["definition"])
            self.force_dirty = True
            self.status.set("已导入草稿，请校验并保存。")
        except Exception as error:
            self.error(error)

    def clear_form(self):
        if self.form is not None:
            self.form.destroy()
            self.form = None
        self.form_mode = False
        self.force_dirty = False
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.form_message.configure(text="请选择一个技能，或新建主动技能。")
        self.form_message.pack(anchor="w")
        self.notebook.tab(self.json_tab, text="条目高级设置")

    def remove(self):
        super().remove()
        if self.current is None:
            self.clear_form()

    def open_project(self):
        super().open_project()
        if self.current is None:
            self.clear_form()

    def launch_core(self):
        if not self.leave():
            return
        try:
            from SkillEditorClient.launcher import core_command
            self.project.validate()
            flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
            # A second one-file process must own its extraction directory so
            # Core keeps working even when the editor is closed first.
            subprocess.Popen(core_command(self.project.path), cwd=DATA_ROOT, creationflags=flags,
                             env={**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"})
            self.status.set("Core已在独立终端启动；已运行的游戏不受后续编辑影响。")
        except Exception as error:
            self.error(error)


def main(path=DEFAULT_CATALOG):
    enable_high_dpi()
    root = tk.Tk()
    root.withdraw()
    try:
        app = SkillEditorClient(root, CatalogProject(path))
    except Exception as error:
        messagebox.showerror("无法打开SkillEditorClient", str(error), parent=root)
        root.destroy()
        return 1

    def callback_error(exc, value, tb):
        folder = DATA_ROOT / "userdata"
        try:
            folder.mkdir(exist_ok=True)
            with (folder / "SkillEditorClient_error.log").open("a", encoding="utf-8") as stream:
                traceback.print_exception(exc, value, tb, file=stream)
        finally:
            app.error(value)
    root.report_callback_exception = callback_error
    root.deiconify()
    root.mainloop()
    return 0
