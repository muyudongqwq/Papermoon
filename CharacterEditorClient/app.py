"""Independent character editor; skills are referenced from a shared catalog."""

from copy import copy, deepcopy
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from core.catalog import CatalogProject, DEFAULT_CATALOG, BUILTINS
from skilleditor.documents import format_json
from SkillEditorClient.widgets import ScrollForm
from CharacterEditorClient import APPLICATION_NAME
from CharacterEditorClient.dialogs import ask_new_card
from CharacterEditorClient.forms import CharacterForm
from CharacterEditorClient.model import new_card, next_card_id


class CharacterEditorClient:
    def __init__(self, root, project=None):
        from skilleditor.display import configure_display
        self.root, self.project = root, project or CatalogProject()
        self.current, self.form, self.baseline, self.is_new = None, None, None, False
        self.items, self.loading = {}, False
        configure_display(root)
        root.title(f"Papermoon · {APPLICATION_NAME}")
        root.protocol("WM_DELETE_WINDOW", self.close)
        toolbar = ttk.Frame(root, padding=8)
        toolbar.pack(fill="x")
        for text, command in (("打开项目", self.open_project), ("保存角色卡", self.save),
                              ("校验", self.validate), ("刷新技能库", self.reload_library)):
            ttk.Button(toolbar, text=text, command=command).pack(side="left", padx=3)
        self.path_label = ttk.Label(root, text=f"项目：{self.project.path}", padding=8)
        self.path_label.pack(fill="x")
        pane = ttk.Panedwindow(root, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=10)
        left, right = ttk.Frame(pane, width=280), ttk.Frame(pane)
        pane.add(left, weight=1)
        pane.add(right, weight=3)
        self.search = tk.StringVar(root)
        ttk.Entry(left, textvariable=self.search).pack(fill="x", pady=4)
        tree_area = ttk.Frame(left)
        tree_area.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_area, show="tree", selectmode="browse")
        scroll = ttk.Scrollbar(tree_area, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.search.trace_add("write", lambda *_: self.refresh())
        tools = ttk.Frame(left)
        tools.pack(fill="x", pady=6)
        self.new_button = ttk.Button(tools, text="新建角色卡", command=self.new)
        self.new_button.pack(side="left", padx=4)
        ttk.Button(left, text="恢复内置 / 删除自定义角色卡", command=self.remove).pack(fill="x", pady=6)
        ttk.Label(left, text="* 表示本地覆盖，内置卡保留。\nID自动生成；技能编辑后先保存，再刷新技能库。", wraplength=270).pack(anchor="w", pady=5)
        self.notebook = ttk.Notebook(right)
        self.notebook.pack(fill="both", expand=True)
        self.form_tab, self.preview_tab = ttk.Frame(self.notebook), ttk.Frame(self.notebook)
        self.notebook.add(self.form_tab, text="角色卡编辑器")
        self.notebook.add(self.preview_tab, text="JSON预览（只读）")
        self.scroll = ScrollForm(self.form_tab)
        self.scroll.pack(fill="both", expand=True)
        self.message = ttk.Label(self.scroll.body, text="请选择已有角色卡，或新建Master / Servant。", padding=12)
        self.message.pack(anchor="w")
        self.preview = tk.Text(self.preview_tab, wrap="none", font=("Consolas", 11), state="disabled")
        self.preview.pack(fill="both", expand=True)
        self.notebook.bind("<<NotebookTabChanged>>", self.update_preview)
        self.status = tk.StringVar(root, value="角色ID自动分配；填写属性与技能后保存。")
        ttk.Label(root, textvariable=self.status, padding=8, wraplength=1150).pack(fill="x")
        root.bind("<Control-s>", lambda _: self.save())
        self.refresh()

    def error(self, error):
        self.status.set(f"未完成：{error}")
        messagebox.showerror("角色卡编辑器", str(error), parent=self.root)

    def refresh(self):
        self.loading = True
        try:
            self.items.clear()
            self.tree.delete(*self.tree.get_children())
            cards = self.project.effective()["character_card"]
            term = self.search.get().strip().casefold()
            for kind, title in (("master", "Master / 御主"), ("servant", "Servant / 从者")):
                group = self.tree.insert("", "end", text=title, open=True)
                for key, data in cards.items():
                    if data["character_type"] != kind or term not in f"{key} {data['name']}".casefold():
                        continue
                    local = "* " if key in self.project.data["character_card"] else ""
                    node = self.tree.insert(group, "end", text=f"{local}{data['name']}")
                    self.items[node] = key
                    if key == self.current:
                        self.tree.selection_set(node)
            self.path_label.configure(text=f"项目：{self.project.path}")
        finally:
            self.loading = False

    def load(self, key, definition=None, *, new=False):
        data = deepcopy(definition if definition is not None else self.project.effective()["character_card"][key])
        # Build before replacing the current form, so unsupported attributes
        # cannot destroy the current draft on an unsuccessful load.
        form = CharacterForm(self.scroll.body, data, self.project.effective(), new=new)
        if self.form is not None:
            self.form.destroy()
        self.form, self.current, self.is_new = form, key, new
        self.message.pack_forget()
        form.pack(fill="x")
        self.baseline = form.snapshot()
        self.notebook.select(self.form_tab)
        self.scroll.canvas.yview_moveto(0)

    def dirty(self):
        return self.form is not None and (self.is_new or self.form.snapshot() != self.baseline)

    def leave(self):
        if not self.dirty():
            return True
        answer = messagebox.askyesnocancel("未保存的角色卡", "先保存当前角色卡吗？\n选择“否”会放弃当前修改。", parent=self.root)
        return self.save() if answer is True else answer is False

    def on_select(self, _event=None):
        if self.loading:
            return
        selection = self.tree.selection()
        key = self.items.get(selection[0]) if selection else None
        if key is None or key == self.current:
            return
        if self.leave():
            try:
                self.load(key)
            except Exception as error:
                self.error(error)
        self.refresh()

    def new(self):
        if not self.leave():
            return
        result = ask_new_card(self.root)
        if result is None:
            return
        try:
            self.project = CatalogProject(self.project.path)
            data = new_card(*result, self.project.effective()["character_card"])
            self.load(data["card_id"], data, new=True)
            self.refresh()
        except Exception as error:
            self.error(error)

    def candidate(self):
        if self.form is None:
            raise ValueError("请先选择或新建角色卡")
        candidate = copy(self.project)
        candidate.data = deepcopy(self.project.data)
        candidate.put("character_card", self.current, self.form.read())
        return candidate

    def validate(self):
        try:
            self.candidate()
            self.status.set("校验通过，当前修改尚未保存。")
            return True
        except Exception as error:
            self.error(error)
            return False

    def save(self):
        try:
            candidate = self.candidate()
            candidate.save()
            self.project = candidate
            self.load(self.current)
            self.refresh()
            self.status.set("角色卡已保存；下次启动Core时加载，原文件保留为.bak。")
            return True
        except Exception as error:
            self.error(error)
            return False

    def reload_library(self):
        try:
            fresh = CatalogProject(self.project.path)
            cards = fresh.effective()["character_card"]
            if self.form is not None:
                if not self.is_new and cards.get(self.current) != self.form.original:
                    raise ValueError("当前角色卡已被其他窗口修改。草稿保留，请重新打开项目后再编辑")
                if self.is_new and self.current in cards:
                    data = self.form.original
                    key = next_card_id(data["character_type"], data.get("servant_class"), cards)
                    self.current = data["card_id"] = key
                self.form.update_catalogs(fresh.effective())
            self.project = fresh
            self.refresh()
            self.status.set("技能库已刷新；当前角色卡草稿保留。")
            return True
        except Exception as error:
            self.error(error)
            return False

    def open_project(self):
        if not self.leave():
            return
        path = filedialog.askopenfilename(title="打开内容项目", filetypes=[("JSON项目", "*.json")], parent=self.root)
        if not path:
            return
        try:
            project = CatalogProject(path)
            if self.form is not None:
                self.form.destroy()
            self.form, self.current, self.is_new = None, None, False
            self.project = project
            self.message.pack(anchor="w")
            self.refresh()
            self.update_preview()
        except Exception as error:
            self.error(error)

    def remove(self):
        if self.current is None or not self.leave():
            return
        key = self.current
        if key not in self.project.data["character_card"]:
            self.status.set("此角色卡没有已保存的自定义内容，无需恢复。")
            return
        title = "恢复内置角色卡" if key in BUILTINS["character_card"] else "删除自定义角色卡"
        if not messagebox.askyesno(title, f"{title}：{key}？", parent=self.root):
            return
        try:
            candidate = copy(self.project)
            candidate.data = deepcopy(self.project.data)
            candidate.remove_override("character_card", key)
            candidate.save()
            self.project = candidate
            if key in candidate.effective()["character_card"]:
                self.load(key)
            else:
                self.form.destroy()
                self.form, self.current = None, None
                self.message.pack(anchor="w")
            self.refresh()
            self.status.set(f"已{title}。")
            self.update_preview()
        except Exception as error:
            self.error(error)

    def update_preview(self, _event=None):
        if self.notebook.select() != str(self.preview_tab):
            return
        try:
            text = format_json(self.form.read()) if self.form is not None else "请选择角色卡。"
        except Exception as error:
            text = f"角色卡尚未填写完整：{error}"
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", text)
        self.preview.configure(state="disabled")

    def close(self):
        if self.leave():
            self.root.destroy()
