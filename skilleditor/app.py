"""Tk desktop JSON editor using the core's own validators and catalogs."""

from copy import copy
import os
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter.scrolledtext import ScrolledText

from core.catalog import BUILTINS, CATEGORIES, CatalogProject, DEFAULT_CATALOG, ROOT, parse_json
from skilleditor.documents import KINDS, LABELS, copy_definition, format_json, new_definition, parse_entry
from skilleditor.display import configure_display, enable_high_dpi


class SkillEditor:
    def __init__(self, root, project=None):
        self.root = root
        self.project = project or CatalogProject()
        self.current = None
        self.loaded_text = ""
        self.items = {}
        self._loading = False
        self.root.title("Papermoon · Skill Editor")
        configure_display(root)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self.refresh()

    def _build(self):
        toolbar = ttk.Frame(self.root, padding=8)
        toolbar.pack(fill="x")
        for label, command in (("打开项目", self.open_project), ("保存条目", self.save),
                               ("校验", self.validate), ("整理JSON", self.format),
                               ("导入条目", self.import_entry), ("导出条目", self.export_entry),
                               ("启动Core测试", self.launch_core)):
            ttk.Button(toolbar, text=label, command=command).pack(side="left", padx=3)
        self.path_label = ttk.Label(self.root, padding=(12, 0, 12, 6))
        self.path_label.pack(fill="x")
        pane = ttk.Panedwindow(self.root, orient="horizontal")
        pane.pack(fill="both", expand=True, padx=10)
        left = ttk.Frame(pane, width=310)
        right = ttk.Frame(pane)
        pane.add(left, weight=1)
        pane.add(right, weight=3)
        self.search = tk.StringVar()
        ttk.Entry(left, textvariable=self.search).pack(fill="x", pady=(0, 6))
        self.search.trace_add("write", lambda *_: self.refresh(keep_document=True))
        tree_frame = ttk.Frame(left)
        tree_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(tree_frame, show="tree", selectmode="browse")
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        tools = ttk.Frame(left)
        tools.pack(fill="x", pady=6)
        self.kind = ttk.Combobox(tools, values=list(KINDS), state="readonly", width=10)
        self.kind.set("固有技能")
        self.kind.pack(side="left")
        ttk.Button(tools, text="新建", command=self.new).pack(side="left", padx=4)
        ttk.Button(left, text="复制为新条目", command=self.duplicate).pack(fill="x", pady=2)
        ttk.Button(left, text="恢复内置 / 删除自定义条目", command=self.remove).pack(fill="x", pady=2)
        ttk.Label(left, text="* 表示本地覆盖；内置定义保留。\n职介技能按名称引用，在ranks中定义各等级。", wraplength=300).pack(fill="x", pady=8)
        notebook = ttk.Notebook(right)
        notebook.pack(fill="both", expand=True)
        edit = ttk.Frame(notebook)
        reference = ttk.Frame(notebook)
        notebook.add(edit, text="条目定义 · JSON")
        notebook.add(reference, text="效果字典与格式参考")
        self.entry_label = ttk.Label(edit, text="选择左侧条目，或新建 / 导入。", padding=6)
        self.entry_label.pack(fill="x")
        self.text = ScrolledText(edit, wrap="none", undo=True, font=("Consolas", 11))
        self.text.pack(fill="both", expand=True)
        horizontal = ttk.Scrollbar(edit, orient="horizontal", command=self.text.xview)
        self.text.configure(xscrollcommand=horizontal.set)
        horizontal.pack(fill="x")
        ttk.Label(edit, text="保存会校验整个项目及角色引用；修改在下次启动Core时生效。", padding=6).pack(fill="x")
        reference_text = ScrolledText(reference, wrap="word", font=("Microsoft YaHei UI", 10))
        reference_text.pack(fill="both", expand=True)
        reference_text.insert("1.0", (ROOT / "game" / "skill" / "effect_dictionary.txt").read_text(encoding="utf-8"))
        reference_text.configure(state="disabled")
        self.status = tk.StringVar(value="就绪。选择条目后可直接编辑JSON，保存为独立的本地内容。")
        ttk.Label(self.root, textvariable=self.status, padding=8, wraplength=1140).pack(fill="x")
        self.root.bind("<Control-s>", lambda _event: self.save())

    def error(self, error):
        self.status.set(f"未完成：{error}")
        messagebox.showerror("Papermoon", str(error), parent=self.root)

    def refresh(self, select=None, *, keep_document=False):
        self._loading = True
        try:
            self.items.clear()
            self.tree.delete(*self.tree.get_children())
            term = self.search.get().strip().casefold()
            selected_node = None
            for category, entries in self.project.effective().items():
                group = self.tree.insert("", "end", text=LABELS[category], open=True)
                for key, definition in entries.items():
                    name = definition.get("name", key)
                    if term and term not in f"{key} {name}".casefold():
                        continue
                    local = "* " if key in self.project.data[category] else ""
                    node = self.tree.insert(group, "end", text=f"{local}{name} [{key}]")
                    self.items[node] = (category, key)
                    if (category, key) == (select or self.current):
                        selected_node = node
            if selected_node:
                self.tree.selection_set(selected_node)
                self.tree.see(selected_node)
            self.path_label.configure(text=f"项目：{self.project.path}")
            if select is not None and not keep_document:
                self.load(*select)
        finally:
            self._loading = False

    def load(self, category, key, definition=None):
        self.current = (category, key)
        if definition is None:
            definition = self.project.effective()[category][key]
        self.loaded_text = format_json(definition)
        self.text.delete("1.0", "end")
        self.text.insert("1.0", self.loaded_text)
        self.text.edit_reset()
        self.entry_label.configure(text=f"{LABELS[category]} · {key}")
        self.status.set("职介技能按名称与等级引用；更名请使用“复制为新条目”。" if category == "class_skill"
                        else "编辑完成后点击保存；ID需要更换时请使用“复制为新条目”。")

    def dirty(self):
        return self.current is not None and (self.text.get("1.0", "end-1c") != self.loaded_text
            or self.current[1] not in self.project.effective()[self.current[0]])

    def leave(self):
        if not self.dirty():
            return True
        answer = messagebox.askyesnocancel("未保存的修改", "先保存当前条目吗？\n选择“否”会放弃当前修改。", parent=self.root)
        return self.save() if answer is True else answer is False

    def on_select(self, _event=None):
        if self._loading:
            return
        selection = self.tree.selection()
        selected = self.items.get(selection[0]) if selection else None
        if selected is None or selected == self.current:
            return
        if self.leave():
            self.refresh(select=selected)
        else:
            self.refresh(keep_document=True)

    def candidate(self):
        if self.current is None:
            raise ValueError("请先选择或新建条目")
        candidate = copy(self.project)
        candidate.data = parse_json(format_json(self.project.data))
        candidate.put(*self.current, parse_json(self.text.get("1.0", "end-1c")))
        return candidate

    def validate(self):
        try:
            candidate = self.candidate()
            self.status.set(f"校验通过：{candidate.validate()}。当前修改尚未保存。")
            return True
        except Exception as error:
            self.error(error)
            return False

    def save(self):
        try:
            candidate = self.candidate()
            candidate.save()
            self.project = candidate
            self.refresh(select=self.current)
            self.status.set(f"已保存：{self.project.path}。下次启动Core时加载；原文件保留为.bak。")
            return True
        except Exception as error:
            self.error(error)
            return False

    def format(self):
        try:
            formatted = format_json(parse_json(self.text.get("1.0", "end-1c")))
            self.text.delete("1.0", "end")
            self.text.insert("1.0", formatted)
        except Exception as error:
            self.error(error)

    def new(self):
        if not self.leave():
            return
        kind = self.kind.get()
        category = KINDS[kind]
        prompt = "请输入职介技能名称（角色卡使用此名称引用）：" if category == "class_skill" else "请输入不重复的新ID："
        initial = "自定义职介技能" if category == "class_skill" else "user_new_card" if category == "character_card" else "user_new_skill"
        key = simpledialog.askstring("新建条目", prompt, initialvalue=initial, parent=self.root)
        if not key:
            return
        if key in self.project.effective()[category]:
            self.error("该ID已存在，请另取一个ID或直接编辑已有条目")
            return
        self.load(category, key, new_definition(kind, key))

    def duplicate(self):
        if self.current is None:
            return
        if self.current[1] not in self.project.effective()[self.current[0]]:
            self.error("请先保存新条目，再复制为另一个条目")
            return
        if not self.leave():
            return
        category, old_key = self.current
        key = simpledialog.askstring("复制条目", "请输入新的职介技能名称：" if category == "class_skill" else "请输入新ID：",
                                     initialvalue=old_key + "_copy", parent=self.root)
        if not key:
            return
        if key in self.project.effective()[category]:
            self.error("该ID已存在")
            return
        data = copy_definition(category, key, self.project.effective()[category][old_key])
        if category != "class_skill":
            data["name"] = data.get("name", key) + "（副本）"
        self.load(category, key, data)

    def remove(self):
        if self.current is None or not self.leave():
            return
        category, key = self.current
        if key not in self.project.data[category]:
            self.status.set("这是未修改的内置条目，无需恢复。")
            return
        action = "恢复内置定义" if key in BUILTINS[category] else "删除自定义条目"
        if not messagebox.askyesno(action, f"{action}：{key}？", parent=self.root):
            return
        try:
            candidate = copy(self.project)
            candidate.data = parse_json(format_json(self.project.data))
            candidate.remove_override(category, key)
            candidate.save()
            self.project = candidate
            if key not in candidate.effective()[category]:
                self.current = None
                self.loaded_text = ""
                self.text.delete("1.0", "end")
                self.entry_label.configure(text="条目已删除。")
                self.refresh()
            else:
                self.refresh(select=(category, key))
            self.status.set(f"已{action}并保存。")
        except Exception as error:
            self.error(error)

    def open_project(self):
        if not self.leave():
            return
        path = filedialog.askopenfilename(title="打开内容项目", initialdir=self.project.path.parent, filetypes=[("JSON项目", "*.json")])
        if not path:
            return
        try:
            project = CatalogProject(path)
            self.project = project
            self.current = None
            self.loaded_text = ""
            self.text.delete("1.0", "end")
            self.entry_label.configure(text="请选择新项目中的条目。")
            self.refresh()
        except Exception as error:
            self.error(error)

    def import_entry(self):
        if not self.leave():
            return
        path = filedialog.askopenfilename(title="导入单个条目", filetypes=[("JSON条目", "*.json")])
        if not path:
            return
        try:
            data = parse_entry(Path(path).read_text(encoding="utf-8-sig"))
            self.load(data["category"], data["entry_id"], data["definition"])
            # Importing is a draft. Saving performs full project validation.
            self.loaded_text = ""
            self.status.set("已导入草稿，请校验并保存。")
        except Exception as error:
            self.error(error)

    def export_entry(self):
        try:
            candidate = self.candidate()
            category, key = self.current
            path = filedialog.asksaveasfilename(title="导出条目", initialfile=key.replace(":", "_") + ".json",
                                               defaultextension=".json", filetypes=[("JSON条目", "*.json")])
            if path:
                Path(path).write_text(format_json({"category": category, "entry_id": key,
                    "definition": candidate.data[category][key]}), encoding="utf-8")
                self.status.set(f"已导出：{path}。导出不会自动保存到当前项目。")
        except Exception as error:
            self.error(error)

    def launch_core(self):
        if not self.leave():
            return
        try:
            self.project.validate()
            python = Path(sys.executable)
            if python.name.casefold() == "pythonw.exe":
                python = python.with_name("python.exe")
            flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
            subprocess.Popen([str(python), "-m", "core", "--menu", "--pause-on-exit", "--catalog", str(self.project.path)],
                             cwd=ROOT, creationflags=flags)
            self.status.set("Core已在独立终端启动；已运行的游戏不受后续编辑影响。")
        except Exception as error:
            self.error(error)

    def close(self):
        if self.leave():
            self.root.destroy()


def main(path=DEFAULT_CATALOG):
    enable_high_dpi()
    root = tk.Tk()
    root.withdraw()
    try:
        app = SkillEditor(root, CatalogProject(path))
    except Exception as error:
        messagebox.showerror("无法打开Skill Editor", str(error), parent=root)
        root.destroy()
        return 1
    root.deiconify()
    root.mainloop()
    return 0
