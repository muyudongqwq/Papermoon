"""First graphical editor for trigger conditions and boolean composition."""

from copy import deepcopy
import json
import tkinter as tk
from tkinter import messagebox, ttk

from core.catalog import parse_json
from game.action.action_rules import _BOOLEAN_CONDITIONS, validate_condition
from game.status.data import STATUS_DATA
from SkillEditorClient.condition_model import (
    CONDITION_NAMES, combine_conditions, condition_help, display_value,
    linear_conditions, parse_value, value_labels,
)
from SkillEditorClient.widgets import JsonBox, configure_gray_area, request_layout
from SkillEditorClient.editor_documents import format_json


class ConditionRow(ttk.Frame):
    def __init__(self, parent, editor, data=None):
        super().__init__(parent, style="PhaseArea.TFrame", padding=(0, 4))
        self.editor = editor
        data = data or {}
        self.join = tk.StringVar(master=self, value=data.get("join", "与"))
        self.connector = ttk.Frame(self, style="PhaseArea.TFrame")
        self.connector.pack(fill="x", pady=(4, 6))
        self.join_box = ttk.Combobox(self.connector, textvariable=self.join, values=("与", "或"), state="readonly", width=8)
        self.join_box.pack(side="left")
        self.join_box.bind("<MouseWheel>", lambda _event: "break")
        self.line = ttk.Frame(self, style="PhaseArea.TFrame")
        self.line.pack(fill="x")
        self.caption = ttk.Label(self.line, width=9, style="PhaseArea.TLabel")
        self.caption.pack(side="left")
        self.selection = tk.StringVar(master=self, value=CONDITION_NAMES.get(data.get("field"), ""))
        self.type_box = ttk.Combobox(self.line, textvariable=self.selection, values=tuple(CONDITION_NAMES.values()), state="readonly")
        self.type_box.pack(side="left", fill="x", expand=True)
        self.type_box.bind("<MouseWheel>", lambda _event: "break")
        self.description = ttk.Label(self, style="PhaseArea.TLabel", wraplength=650)
        self.description.pack(anchor="w", pady=(3, 2))
        self.value_line = ttk.Frame(self, style="PhaseArea.TFrame")
        ttk.Label(self.value_line, text="取值", width=9, style="PhaseArea.TLabel").pack(side="left")
        self.value = tk.StringVar(master=self)
        self.value_box = ttk.Combobox(self.value_line, textvariable=self.value)
        self.value_box.pack(side="left", fill="x", expand=True)
        self.value_box.bind("<MouseWheel>", lambda _event: "break")
        self.negated = tk.BooleanVar(master=self, value=data.get("negated", False))
        self.negate_box = ttk.Checkbutton(self, text="非：要求此条件的判定结果为 False", variable=self.negated, style="PhaseArea.TCheckbutton")
        self.negate_box.pack(anchor="w", pady=(2, 4))
        self.delete_button = ttk.Button(self, text="删除此条件", style="NewSkillUnit.TButton", command=lambda: editor.remove_row(self))
        self.add_button = ttk.Button(self, text="新增条件", command=lambda: editor.add_row(after=self))
        self.add_button.pack(anchor="w")
        self.selection.trace_add("write", lambda *_: self.update_field())
        self.update_field()
        if "field" in data:
            self.value.set(display_value(data["field"], data["value"]))

    @property
    def field(self):
        return {label: key for key, label in CONDITION_NAMES.items()}.get(self.selection.get(), "")

    def update_field(self):
        field = self.field
        if getattr(self, "current_field", None) == field:
            return
        self.current_field = field
        self.description.configure(text=condition_help(field))
        labels = value_labels(field)
        choices = tuple(labels.values())
        if field in {"required_status", "forbidden_status"}:
            choices = tuple(sorted((self.editor.catalogs or {}).get("status", STATUS_DATA)))
        elif field == "actor_type":
            choices = ("Master", "Servant", "Familiar")
        self.value_box.configure(values=choices, state="readonly" if labels and field != "phase" else "normal")
        self.value.set(display_value(field, True) if field in _BOOLEAN_CONDITIONS else "")
        if field and field != "condition_id":
            self.value_line.pack(fill="x", before=self.negate_box, pady=2)
        else:
            self.value_line.pack_forget()
        request_layout(self)

    def renumber(self, number):
        self.caption.configure(text=f"条件{number}：")
        if len(self.editor.rows) > 1:
            self.delete_button.pack(anchor="w", before=self.add_button, pady=(0, 4))
        else:
            self.delete_button.pack_forget()
        if number == 1:
            self.connector.pack_forget()
        else:
            self.connector.pack(fill="x", before=self.line, pady=(4, 6))

    def read(self):
        if not self.field:
            raise ValueError("请选择每一行的条件，或删除多余的空白行")
        return {"field": self.field, "value": parse_value(self.field, self.value.get()),
                "join": self.join.get(), "negated": self.negated.get()}

    def snapshot(self):
        return self.selection.get(), self.value.get(), self.join.get(), self.negated.get()


class ConditionEditor(ttk.Frame):
    def __init__(self, parent, value, catalogs=None):
        configure_gray_area(parent)
        super().__init__(parent, style="PhaseArea.TFrame", padding=(8, 6), borderwidth=1, relief="solid")
        self.catalogs = catalogs
        self.rows = []
        self.loading = False
        ttk.Label(self, text="发动条件 condition", style="PhaseArea.TLabel").pack(anchor="w", pady=(0, 4))
        self.notebook = ttk.Notebook(self, style="EffectData.TNotebook")
        self.notebook.pack(fill="x")
        self.form = ttk.Frame(self.notebook, style="PhaseArea.TFrame", padding=5)
        self.row_area = ttk.Frame(self.form, style="PhaseArea.TFrame")
        self.row_area.pack(fill="x")
        ttk.Label(self.form, text="从上到下依次组合，连接菜单选择“与”或“或”；勾选“非”表示此条件为False。", wraplength=650, style="PhaseArea.TLabel").pack(anchor="w", pady=(5, 0))
        self.raw = JsonBox(self.notebook, value, height=5)
        self.notebook.add(self.form, text="条件选择")
        self.notebook.add(self.raw, text="条件高级设置")
        self.load(value)
        self.notebook.bind("<<NotebookTabChanged>>", self.tab_changed)

    def load(self, value):
        self.loading = True
        try:
            self.original = deepcopy(value)
            self.raw.text.delete("1.0", "end")
            self.raw.text.insert("1.0", format_json(value))
            for row in self.rows:
                row.destroy()
            self.rows.clear()
            self.row_area.configure(height=1)
            rows = linear_conditions(value)
            self.representable = rows is not None
            for data in rows or [None]:
                self.add_row(data)
            self.baseline = self.form_snapshot()
            self.mode = "form" if self.representable else "json"
            self.notebook.select(self.form if self.mode == "form" else self.raw)
        finally:
            self.loading = False
        request_layout(self)

    def add_row(self, data=None, *, after=None):
        index = self.rows.index(after) + 1 if after is not None else len(self.rows)
        row = ConditionRow(self.row_area, self, data)
        if index < len(self.rows):
            row.pack(fill="x", before=self.rows[index])
        else:
            row.pack(fill="x")
        self.rows.insert(index, row)
        self.renumber()
        request_layout(self)
        return row

    def remove_row(self, row):
        if len(self.rows) <= 1:
            return
        self.rows.remove(row)
        row.destroy()
        self.renumber()
        request_layout(self)

    def renumber(self):
        for number, row in enumerate(self.rows, 1):
            row.renumber(number)

    def form_snapshot(self):
        return tuple(row.snapshot() for row in self.rows)

    def read_form(self):
        if self.form_snapshot() == self.baseline and self.representable:
            return deepcopy(self.original)
        if len(self.rows) == 1 and not self.rows[0].field and not self.rows[0].negated.get():
            return {}
        return combine_conditions([row.read() for row in self.rows])

    def show_json(self):
        if self.mode != "json":
            value = self.read_form()
            self.raw.text.delete("1.0", "end")
            self.raw.text.insert("1.0", format_json(value))
            self.mode = "json"
        self.notebook.select(self.raw)

    def show_form(self):
        if self.mode != "form":
            value = parse_json(self.raw.get())
            if linear_conditions(value) is None:
                raise ValueError("该条件含嵌套分组或尚未完成，请继续在条件高级设置中编辑")
            self.load(value)
        self.notebook.select(self.form)

    def tab_changed(self, _event=None):
        if self.loading:
            return
        try:
            if self.notebook.select() == str(self.raw):
                self.show_json()
            else:
                self.show_form()
        except (ValueError, TypeError) as error:
            self.notebook.select(self.form if self.mode == "form" else self.raw)
            messagebox.showerror("条件尚未填写完整", str(error), parent=self.winfo_toplevel())

    def get(self):
        value = parse_json(self.raw.get()) if self.mode == "json" else self.read_form()
        validate_condition(value)
        return value

    def snapshot(self):
        try:
            return "value", json.dumps(self.get(), sort_keys=True, ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError):
            return "draft", self.mode, self.raw.get() if self.mode == "json" else self.form_snapshot()
