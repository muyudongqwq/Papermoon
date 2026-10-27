"""Schema-driven parameter rows with an explicit, lossless advanced JSON mode."""

from copy import deepcopy
import json
import tkinter as tk
from tkinter import messagebox, ttk

from core.catalog import parse_json
from game.skill.effect_validation import EFFECT_SCHEMAS
from SkillEditorClient.effect_options import FIELD_NAMES, parameter_options, parameter_spec, parse_parameter
from SkillEditorClient.widgets import JsonBox, configure_gray_area, request_layout
from SkillEditorClient.cost_editor import CostRow
from SkillEditorClient.editor_documents import format_json


class ParameterRow(ttk.Frame):
    def __init__(self, parent, editor, key, value=None, *, empty=False):
        super().__init__(parent, style="PhaseArea.TFrame")
        self.editor, self.key = editor, key
        self.complex_value = not empty and isinstance(value, (dict, list))
        self.spec = parameter_spec(editor.effect_type, key, editor.catalogs)
        self.label = ttk.Label(self, width=25, anchor="w", style="PhaseArea.TLabel")
        self.label.pack(side="left", anchor="n")
        self.value = tk.StringVar(master=self, value="" if empty else (
            value if self.spec.kind == "string" and isinstance(value, str) else format_json(value).strip()))
        self.initial = deepcopy(value)
        if self.spec.kind == "tags" and isinstance(value, list):
            self.complex_value = False
            self.value.set(", ".join(value))
        self.initial_text = self.value.get()
        self.has_initial = not empty
        self.input = None
        self.remove_button = ttk.Button(self, text="删除", width=5, command=lambda: editor.remove_field(key))
        self.remove_button.pack(side="right", padx=(4, 0))
        self.refresh()
        if self.spec.kind == "tags":
            self.input.configure(width=25)

    def refresh(self):
        value = getattr(self, "choice_values", {}).get(self.value.get(), self.value.get())
        self.spec = parameter_spec(self.editor.effect_type, self.key, self.editor.catalogs)
        schema = EFFECT_SCHEMAS.get(self.editor.effect_type)
        required = schema is not None and self.key in schema.required_data
        unknown = self.key not in parameter_options(self.editor.effect_type)
        label = f"{FIELD_NAMES.get(self.key, self.key)}"
        if label != self.key:
            label += f" · {self.key}"
        label += " *" if required else ""
        label += "（当前类型不支持）" if unknown else ""
        self.label.configure(text=label)
        labels = dict(self.spec.choice_labels)
        self.choice_values = {label: key for key, label in labels.items()}
        choices = tuple(labels.get(choice, choice) for choice in self.spec.choices) if not self.complex_value else ()
        if self.input is None or isinstance(self.input, ttk.Combobox) != bool(choices):
            if self.input is not None:
                self.input.destroy()
            self.input = (ttk.Combobox(self, textvariable=self.value, state="normal") if choices else
                          ttk.Entry(self, textvariable=self.value))
            self.input.pack(side="left", fill="x", expand=True, before=self.remove_button)
            if choices:
                self.input.bind("<MouseWheel>", lambda _event: "break")
        if choices:
            self.input.configure(values=choices)
        if not self.complex_value:
            self.value.set(labels.get(value, value))

    def read(self):
        text = self.value.get()
        if self.has_initial and text == self.initial_text:
            return deepcopy(self.initial)
        text = self.choice_values.get(text, text)
        try:
            return parse_json(text) if self.complex_value else parse_parameter(text, self.spec)
        except (ValueError, TypeError) as error:
            raise ValueError(f"参数{self.key}：{error}") from error


class CostParameterRow(ttk.Frame):
    """Maintenance entries use the same cost controls as every skill."""
    def __init__(self, parent, editor, value):
        super().__init__(parent, style="PhaseArea.TFrame")
        self.editor, self.rows = editor, []
        self.has_initial = True
        header = ttk.Frame(self, style="PhaseArea.TFrame")
        header.pack(fill="x")
        self.label = ttk.Label(header, style="PhaseArea.TLabel")
        self.label.pack(side="left")
        ttk.Button(header, text="删除参数", command=lambda: editor.remove_field("cost")).pack(side="right")
        self.area = ttk.Frame(self, style="PhaseArea.TFrame")
        self.area.pack(fill="x")
        self.input = ttk.Button(self, text="添加维持消耗", command=lambda: self.add_cost({"resource": "mp", "value": 0, "timing": "maintenance"}))
        self.input.pack(anchor="w")
        for cost in value:
            self.add_cost(cost)
        self.refresh()

    def add_cost(self, value):
        row = CostRow(self.area, value, self.remove_cost, (), timings=("maintenance",))
        row.pack(fill="x", pady=3)
        self.rows.append(row)
        request_layout(self)
        return row

    def remove_cost(self, row):
        self.rows.remove(row)
        row.destroy()
        if not self.rows:
            self.area.configure(height=1)
        request_layout(self)

    def read(self):
        return [row.read() for row in self.rows]

    def snapshot(self):
        return tuple(row.snapshot() for row in self.rows)

    def refresh(self):
        supported = "cost" in parameter_options(self.editor.effect_type)
        self.label.configure(text="回合末维持消耗 · cost" + ("" if supported else "（当前类型不支持）"))


class EffectDataEditor(ttk.Frame):
    def __init__(self, parent, effect_type, value, catalogs=None):
        configure_gray_area(parent)
        super().__init__(parent, style="PhaseArea.TFrame")
        self.effect_type, self.catalogs = effect_type, catalogs
        self.rows = {}
        self.mode = "form"
        self.notebook = ttk.Notebook(self, style="EffectData.TNotebook")
        self.notebook.pack(fill="x")
        self.form = ttk.Frame(self.notebook, padding=5, style="PhaseArea.TFrame")
        self.raw = JsonBox(self.notebook, value, height=5)
        self.raw.configure(style="PhaseArea.TFrame")
        self.text = self.raw.text
        self.notebook.add(self.form, text="参数选择")
        self.notebook.add(self.raw, text="效果参数高级设置")
        self.notice = ttk.Label(self.form, wraplength=650, style="PhaseArea.TLabel")
        self.notice.pack(anchor="w", pady=(0, 4))
        self.fields = ttk.Frame(self.form, style="PhaseArea.TFrame")
        self.fields.pack(fill="x")
        controls = self.controls = ttk.Frame(self.form, style="PhaseArea.TFrame")
        controls.pack(fill="x", pady=4)
        self.field = tk.StringVar(master=self)
        self.field_box = ttk.Combobox(controls, textvariable=self.field, state="readonly", width=29)
        self.field_box.pack(side="left", fill="x", expand=True)
        self.field_box.bind("<MouseWheel>", lambda _event: "break")
        self.add_button = ttk.Button(controls, text="添加参数", command=self.add_selected)
        self.add_button.pack(side="left", padx=4)
        self.input_hint = ttk.Label(self.form, text="文本直接填写，数值填写数字。嵌套对象和列表可在效果参数高级设置中填写", wraplength=650, style="PhaseArea.TLabel")
        self.input_hint.pack(anchor="w")
        self.load_rows(value)
        self.notebook.bind("<<NotebookTabChanged>>", self.tab_changed)
        self.notebook.select(self.form if self.mode == "form" else self.raw)

    def load_rows(self, value):
        for row in self.rows.values():
            row.destroy()
        self.rows.clear()
        if not isinstance(value, dict):
            self.mode = "json"
            self.notebook.select(self.raw)
            self.refresh()
            return
        for key, item in value.items():
            self.add_field(key, item)
        self.fill_available_fields()
        self.refresh()

    def add_field(self, key, value=None, *, empty=False):
        if key in self.rows:
            row = self.rows[key]
            if empty or row.has_initial or not self.is_blank(row):
                return row
            # Programmatic fixture/import additions can fill an untouched
            # automatically displayed field without discarding a user's draft.
            self.rows.pop(key).destroy()
        if key == "cost" and self.effect_type in {"create_field", "deploy_reality_marble"} and (empty or (
                isinstance(value, list) and all(isinstance(cost, dict) for cost in value))):
            row = CostParameterRow(self.fields, self, [] if empty else value)
            row.has_initial = not empty
        else:
            row = ParameterRow(self.fields, self, key, value, empty=empty)
        row.pack(fill="x", pady=2)
        self.rows[key] = row
        self.refresh()
        return row

    @staticmethod
    def is_blank(row):
        return not row.rows if isinstance(row, CostParameterRow) else not row.value.get().strip()

    def fill_available_fields(self):
        options = parameter_options(self.effect_type)
        for key, row in list(self.rows.items()):
            if key not in options and not row.has_initial and self.is_blank(row):
                self.rows.pop(key).destroy()
        for key in options:
            self.add_field(key, empty=True)

    def remove_field(self, key):
        self.rows.pop(key).destroy()
        self.refresh()

    def add_selected(self):
        key = self.field_choices.get(self.field.get(), self.field.get())
        if key and key not in self.rows:
            self.add_field(key, empty=True).input.focus_set()

    def refresh(self):
        # resource_id is displayed as the resource name. Keep an older,
        # separate name losslessly in advanced JSON without a duplicate row.
        hidden_fields = {"name"} if self.effect_type == "add_resource" else set()
        options = [key for key in parameter_options(self.effect_type) if key not in self.rows and key not in hidden_fields]
        self.field_choices = {f"{key} · {FIELD_NAMES[key]}" if key in FIELD_NAMES else key: key for key in options}
        self.field_box.configure(values=tuple(self.field_choices))
        if self.field.get() not in self.field_choices:
            self.field.set("")
        self.add_button.configure(state="normal" if options else "disabled")
        if options:
            self.controls.pack(fill="x", before=self.input_hint, pady=4)
        else:
            self.controls.pack_forget()
        schema = EFFECT_SCHEMAS.get(self.effect_type)
        self.notice.configure(text="带*参数为必填。非必填参数可以留空。" if schema is not None else "")
        order = [key for key in parameter_options(self.effect_type) if key in self.rows]
        order.extend(key for key in self.rows if key not in order)
        if order != list(self.rows):
            self.rows = {key: self.rows[key] for key in order}
        visible = [row for key, row in self.rows.items() if key not in hidden_fields]
        if self.fields.pack_slaves() != visible:
            for row in self.rows.values():
                row.pack_forget()
            for row in visible:
                row.pack(fill="x", pady=2)
        for row in self.rows.values():
            row.refresh()
        request_layout(self)

    def set_effect_type(self, effect_type):
        self.effect_type = effect_type
        if self.mode == "form":
            self.fill_available_fields()
        self.refresh()

    def read_form(self):
        result = {}
        schema = EFFECT_SCHEMAS.get(self.effect_type)
        required = schema.required_data if schema is not None else ()
        for key, row in self.rows.items():
            if self.is_blank(row):
                if key in required:
                    if row.has_initial:
                        raise ValueError(f"请填写必填参数{key}")
                    # An untouched required field remains missing. Catalog
                    # validation rejects saving it, but the advanced JSON tab
                    # must stay accessible for entering nested required data.
                    continue
                if isinstance(row, CostParameterRow):
                    if not row.has_initial:
                        continue
                elif not (row.has_initial and row.value.get() == row.initial_text):
                    continue
            result[key] = row.read()
        return result

    def show_json(self):
        if self.mode != "json":
            text = format_json(self.read_form())
            self.text.delete("1.0", "end")
            self.text.insert("1.0", text)
            self.mode = "json"
        self.notebook.select(self.raw)

    def show_form(self):
        if self.mode != "form":
            value = parse_json(self.raw.get())
            if not isinstance(value, dict):
                raise ValueError("effect_data必须是JSON对象")
            self.load_rows(value)
            self.mode = "form"
        self.notebook.select(self.form)

    def tab_changed(self, _event=None):
        try:
            if self.notebook.select() == str(self.raw):
                self.show_json()
            else:
                self.show_form()
        except (ValueError, TypeError) as error:
            self.notebook.select(self.form if self.mode == "form" else self.raw)
            messagebox.showerror("参数尚未填写完整", str(error), parent=self.winfo_toplevel())

    def get(self):
        return self.raw.get() if self.mode == "json" else format_json(self.read_form())

    def snapshot(self):
        try:
            value = parse_json(self.get())
            # Mode/format changes alone do not count as changing a skill.
            return "value", json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        except (ValueError, TypeError):
            return ("draft", self.mode, self.raw.get() if self.mode == "json" else
                    tuple((key, row.snapshot() if isinstance(row, CostParameterRow) else row.value.get())
                          for key, row in self.rows.items()))
