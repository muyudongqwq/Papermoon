"""Form views preserve unexposed fields in collapsed JSON sections."""

from copy import deepcopy
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from game.rank.rank import SkillRank
from SkillEditorClient.effect_editor import EffectDataEditor
from SkillEditorClient.effect_options import EFFECT_NAMES, EFFECT_TYPES, FORM_EFFECT_TYPES
from SkillEditorClient.effect_reference import show_effect_reference
from SkillEditorClient.model import (
    RANKS, TARGETS, TYPES, TYPE_DESCRIPTIONS, TARGET_DESCRIPTIONS, cost_value, merge_extras, object_value,
    optional_field, resource_options, validate_component_fields, validate_cost_fields,
)
from SkillEditorClient.widgets import (
    Collapsible, JsonBox, PhaseSelect, UNIT_FONT, configure_gray_area,
    configure_unit_style, entry_row, request_layout,
)
from skilleditor.documents import format_json


# Edit this text to change the note directly below the cost heading.
COST_HINT = "资源可下拉选择，也可填写自定义资源ID。无AP1/AP2时不提供action_point。"


def extras_box(parent, data, controlled, title="高级设置"):
    section = Collapsible(parent, title, expanded=False)
    section.pack(fill="x", pady=3)
    return JsonBox(section.body, {k: v for k, v in data.items() if k not in controlled}, height=3), section


class CostRow(ttk.Frame):
    fields = {"resource", "value"}

    def __init__(self, parent, data, remove, phases):
        super().__init__(parent)
        self.original = deepcopy(data)
        row = ttk.Frame(self)
        row.pack(fill="x")
        ttk.Label(row, text="资源 resource").pack(side="left")
        self.resource = tk.StringVar(master=self, value=data.get("resource", "mp"))
        self.resource_box = ttk.Combobox(row, textvariable=self.resource, values=resource_options(phases), width=20)
        self.resource_box.pack(side="left", padx=5)
        self.resource_box.bind("<MouseWheel>", lambda _event: "break")
        ttk.Label(row, text="数值 value").pack(side="left", padx=(8, 0))
        self.value = tk.StringVar(master=self, value=format_json(data.get("value", 0)).strip())
        ttk.Entry(row, textvariable=self.value, width=14).pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(row, text="删除", command=lambda: remove(self), width=5).pack(side="right")
        self.extras, section = extras_box(self, data, self.fields, "消耗高级设置（如cost_id）")
        self.extras.pack(fill="x")

    def update_phases(self, phases):
        options = resource_options(phases)
        self.resource_box.configure(values=options)
        if self.resource.get() == "action_point" and "action_point" not in options:
            self.resource.set("")

    def read(self):
        result = merge_extras(self.extras.get(), self.fields, "消耗高级设置")
        result.update(resource=self.resource.get().strip(), value=cost_value(self.value.get()))
        return result

    def snapshot(self):
        return self.resource.get(), self.value.get(), self.extras.get()


class EffectPanel(Collapsible):
    fields = {"effect_type", "effect_data"}

    def __init__(self, parent, data, remove, number, catalogs=None, *, allow_choices=False, phases=None):
        super().__init__(parent, f"效果 {number}")
        self.allow_choices = allow_choices
        ttk.Button(self.header, text="删除效果", command=lambda: remove(self)).pack(side="right")
        self.reference_button = ttk.Button(self.header, text="查看说明", command=lambda:
            show_effect_reference(self, self.effect_type.get().strip(), catalogs))
        self.reference_button.pack(side="right", padx=4)
        self.effect_type, self.type_box = entry_row(self.body, "效果类型 effect_type", data.get("effect_type", ""), choices=FORM_EFFECT_TYPES if allow_choices else EFFECT_TYPES)
        self.type_name = ttk.Label(self.body)
        self.type_name.pack(anchor="w")
        configure_gray_area(self)
        self.parameter_group = ttk.Frame(self.body, style="PhaseArea.TFrame", padding=(8, 6), borderwidth=1, relief="solid")
        ttk.Label(self.parameter_group, text="效果参数 effect_data", style="PhaseArea.TLabel").pack(anchor="w", pady=(6, 3))
        choices_data = data.get("effect_data", {}) if self.effect_type.get() == "choices" else None
        self.data = EffectDataEditor(self.parameter_group, self.effect_type.get(), {} if choices_data is not None else data.get("effect_data", {}), catalogs)
        self.data.pack(fill="x")
        self.extras, self.extras_section = extras_box(self.body, data, self.fields, "效果高级设置（持续时间、正负面、叠加等）")
        self.extras.pack(fill="x")
        self.choices = ChoicesEditor(self.body, choices_data, phases or (lambda: []), catalogs,
                                     parameter_parent=self.parameter_group) if allow_choices else None
        self.effect_type.trace_add("write", lambda *_: self.type_changed())
        self.type_changed()

    def type_changed(self):
        kind = self.effect_type.get().strip()
        self.type_name.configure(text=EFFECT_NAMES.get(kind, "请选择效果类型"))
        self.data.set_effect_type(kind)
        self.extras_section.pack(fill="x", pady=3)
        if self.choices is not None:
            if kind == "choices":
                self.data.pack_forget()
                self.choices.parameters.pack(fill="x")
                self.choices.pack(fill="x", before=self.extras_section, pady=4)
            else:
                self.choices.parameters.pack_forget()
                self.choices.pack_forget()
                self.data.pack(fill="x")
        if kind in EFFECT_TYPES or (kind == "choices" and self.allow_choices):
            self.parameter_group.pack(fill="x", before=self.choices if kind == "choices" else self.extras_section)
        else:
            self.parameter_group.pack_forget()
        if kind == "choices" and self.allow_choices:
            self.extras_section.pack_forget()
        request_layout(self)

    def read(self):
        kind = self.effect_type.get().strip()
        if not kind:
            raise ValueError("请填写effect_type，可在效果字典中查询效果关键词")
        if kind == "choices":
            if not self.allow_choices:
                raise ValueError("可选发动只能添加在技能单元的效果中，不能嵌套在分支效果内")
            return {"effect_type": kind, "effect_data": self.choices.read()}
        result = merge_extras(self.extras.get(), self.fields, "效果高级设置")
        result.update(effect_type=kind, effect_data=object_value(self.data.get(), f"{kind}的effect_data"))
        return result

    def snapshot(self):
        return (self.effect_type.get(), self.data.snapshot(), self.extras.get(),
                self.choices.snapshot() if self.choices is not None else None)


class ChoicePanel(Collapsible):
    fields = {"choice_id", "name", "effects", "additional_cost"}

    def __init__(self, parent, data, remove, number, phases, catalogs=None):
        super().__init__(parent, "")
        self.original = deepcopy(data)
        self.catalogs, self.phases = catalogs, phases
        self.choice_id = data["choice_id"]
        self.number = number
        self.effects, self.costs = [], []
        self.name, self.name_box = entry_row(self.body, "分支名称", data.get("name", ""), compact=True)
        self.name.trace_add("write", lambda *_: self.update_title())
        self.effect_group = Collapsible(self.body, "分支效果")
        self.effect_group.pack(fill="x", pady=4)
        self.effect_rows = ttk.Frame(self.effect_group.body)
        self.effect_rows.pack(fill="x")
        self.add_effect_button = ttk.Button(self.effect_group.body, text="新建效果", command=lambda: self.add_effect({"effect_type": "", "effect_data": {}}))
        self.add_effect_button.pack(anchor="w")
        for effect in data.get("effects", []):
            self.add_effect(effect)
        self.cost_group = Collapsible(self.body, "分支额外消耗")
        self.cost_group.pack(fill="x", pady=4)
        ttk.Label(self.cost_group.body, text="仅选中此分支时支付；同一分支重复选择时，每次分别支付。", wraplength=610).pack(anchor="w")
        self.cost_rows = ttk.Frame(self.cost_group.body)
        self.cost_rows.pack(fill="x", pady=5)
        self.add_cost_button = ttk.Button(self.cost_group.body, text="添加消耗", command=lambda: self.add_cost({"resource": "mp", "value": 0}))
        self.add_cost_button.pack(anchor="w")
        for cost in data.get("additional_cost", []):
            self.add_cost(cost)
        self.extras, section = extras_box(self.body, data, self.fields, "分支高级设置（条件等）")
        ttk.Label(section.body, text=f"内部标识 choice_id：{self.choice_id}", wraplength=650).pack(anchor="w")
        self.extras.pack(fill="x")
        self.delete_button = ttk.Button(self.body, text="删除此分支", command=lambda: remove(self))
        self.delete_button.pack(anchor="w", pady=(6, 2))
        self.update_title()

    def update_title(self):
        name = self.name.get().strip()
        self.label.configure(text=f"分支 {self.number}" + (f"：{name}" if name else ""))
        request_layout(self)

    def add_effect(self, data):
        panel = EffectPanel(self.effect_rows, data, self.remove_effect, len(self.effects) + 1, self.catalogs)
        panel.pack(fill="x", pady=3)
        self.effects.append(panel)
        request_layout(self)
        return panel

    def remove_effect(self, panel):
        self.effects.remove(panel)
        panel.destroy()
        if not self.effects:
            self.effect_rows.configure(height=1)
        for number, effect in enumerate(self.effects, 1):
            effect.label.configure(text=f"效果 {number}")
        request_layout(self)

    def add_cost(self, data):
        row = CostRow(self.cost_rows, data, self.remove_cost, self.phases())
        row.pack(fill="x", pady=4)
        self.costs.append(row)
        request_layout(self)
        return row

    def remove_cost(self, row):
        self.costs.remove(row)
        row.destroy()
        if not self.costs:
            self.cost_rows.configure(height=1)
        request_layout(self)

    def update_phases(self):
        for row in self.costs:
            row.update_phases(self.phases())

    def read(self):
        result = merge_extras(self.extras.get(), self.fields, "分支高级设置")
        result["choice_id"] = self.choice_id
        name = self.name.get().strip()
        if "name" in self.original and not name:
            raise ValueError(f"请填写分支{self.number}的名称")
        optional_field(result, self.original, "name", name, "")
        effects = [panel.read() for panel in self.effects]
        if not effects:
            raise ValueError(f"请为分支{self.number}添加至少一个效果")
        result["effects"] = effects
        costs = [row.read() for row in self.costs]
        validate_cost_fields(costs, self.phases())
        optional_field(result, self.original, "additional_cost", costs, [])
        return result

    def snapshot(self):
        return (self.choice_id, self.name.get(), [panel.snapshot() for panel in self.effects],
                [row.snapshot() for row in self.costs], self.extras.get())


class ChoicesEditor(Collapsible):
    fields = {"maximum_selections", "allow_duplicate", "options"}

    def __init__(self, parent, data, phases, catalogs=None, *, parameter_parent):
        super().__init__(parent, "可选分支")
        self.original = deepcopy(data)
        self.phases, self.catalogs = phases, catalogs
        self.options = []
        definition = data if data is not None else {}
        self.parameters = ttk.Frame(parameter_parent, style="PhaseArea.TFrame", padding=5)
        row = ttk.Frame(self.parameters, style="PhaseArea.TFrame")
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="每次最多选择几项", width=25, style="PhaseArea.TLabel").pack(side="left")
        self.maximum = tk.StringVar(master=self, value=definition.get("maximum_selections", 1))
        self.maximum_box = ttk.Entry(row, textvariable=self.maximum, width=14)
        self.maximum_box.pack(side="left", padx=5)
        self.allow_duplicate = tk.BooleanVar(master=self, value=definition.get("allow_duplicate", False))
        self.duplicate_box = ttk.Checkbutton(self.parameters, text="允许同一次发动重复选择同一分支", variable=self.allow_duplicate, style="PhaseArea.TCheckbutton")
        self.duplicate_box.pack(anchor="w", pady=3)
        self.option_rows = ttk.Frame(self.body)
        self.option_rows.pack(fill="x", pady=4)
        self.add_option_button = ttk.Button(self.body, text="新建可选分支", command=self.add_option)
        self.add_option_button.pack(anchor="w")
        for option in definition.get("options", []):
            self.add_option(option)
        self.extras, section = extras_box(self.body, definition, self.fields, "可选分支高级设置")
        self.extras.pack(fill="x")
        self.update_title()

    def update_title(self):
        self.label.configure(text=f"可选分支（{len(self.options)}项）")

    def add_option(self, data=None):
        if data is None:
            used = {panel.choice_id for panel in self.options}
            numbers = [int(key[7:]) for key in used if key.startswith("choice_") and key[7:].isascii() and key[7:].isdecimal()]
            number = max([-1, *numbers]) + 1
            data = {"choice_id": f"choice_{number}", "name": "", "effects": []}
        panel = ChoicePanel(self.option_rows, data, self.remove_option, len(self.options) + 1, self.phases, self.catalogs)
        panel.pack(fill="x", pady=4)
        self.options.append(panel)
        self.update_title()
        request_layout(self)
        return panel

    def remove_option(self, panel):
        self.options.remove(panel)
        panel.destroy()
        if not self.options:
            self.option_rows.configure(height=1)
        for number, option in enumerate(self.options, 1):
            option.number = number
            option.update_title()
        self.update_title()
        request_layout(self)

    def update_phases(self):
        for panel in self.options:
            panel.update_phases()

    def read(self):
        result = merge_extras(self.extras.get(), self.fields, "可选分支高级设置")
        text = str(self.maximum.get()).strip()
        if not text.isascii() or not text.isdecimal() or int(text) < 1:
            raise ValueError("可选分支的最多选择数量必须为正整数")
        maximum = int(text)
        if not self.options:
            raise ValueError("可选发动请至少新建一个分支；不再使用时请删除这条可选发动效果")
        original = self.original or {}
        optional_field(result, original, "maximum_selections", maximum, 1)
        optional_field(result, original, "allow_duplicate", self.allow_duplicate.get(), False)
        result["options"] = [panel.read() for panel in self.options]
        return result

    def snapshot(self):
        return (self.maximum.get(), self.allow_duplicate.get(), [panel.snapshot() for panel in self.options],
                self.extras.get())


class ComponentPanel(Collapsible):
    fields = {"component_id", "type", "available_phases", "target", "cost", "effects", "choices"}

    def __init__(self, parent, data, remove, number, catalogs=None, *, release_entry=False):
        configure_unit_style(parent)
        super().__init__(parent, f"技能单元 {number}", font=UNIT_FONT, button_style="NewSkillUnit.TButton")
        self.separator = tk.Frame(self, background="#000000", height=1, borderwidth=0, highlightthickness=0)
        self.original = deepcopy(data)
        self.catalogs = catalogs
        self.release_entry = release_entry
        self.costs, self.effects = [], []
        self.component_id = tk.StringVar(master=self, value=data.get("component_id", ""))
        self.kind, self.kind_box = entry_row(self.body, "技能类型", data.get("type", ""), choices=TYPES, editable=False, compact=True)
        self.type_notice = ttk.Label(self.body, wraplength=650)
        self.type_notice.pack(anchor="w", pady=2)
        self.phase_area = ttk.Frame(self.body, style="PhaseArea.TFrame", padding=(8, 6), borderwidth=1, relief="solid")
        self.phase_area.pack(fill="x", pady=(5, 8))
        row = ttk.Frame(self.phase_area, style="PhaseArea.TFrame")
        row.pack(fill="x")
        self.phases = PhaseSelect(row, data.get("available_phases", []), self.phases_changed)
        ttk.Label(row, text="可用阶段", width=22, style="PhaseArea.TLabel").pack(side="left")
        self.phases.pack(side="left", fill="x", expand=True)
        self.phase_notice = ttk.Label(self.phase_area, text="解放：通过“解放”入口发动，可用阶段由解放行动决定。", wraplength=650, style="PhaseArea.TLabel")
        self.target, self.target_box = entry_row(self.body, "目标 target", data.get("target", "self"), choices=TARGETS, editable=False)
        self.target_notice = ttk.Label(self.body, wraplength=650)
        self.target_notice.pack(anchor="w", pady=2)
        self.kind.trace_add("write", lambda *_: self.update_type())
        self.target.trace_add("write", lambda *_: self.update_target())

        self.effect_group = Collapsible(self.body, "效果 effects")
        self.effect_group.pack(fill="x", pady=4)
        self.effect_rows = ttk.Frame(self.effect_group.body)
        self.effect_rows.pack(fill="x")
        self.add_effect_button = ttk.Button(self.effect_group.body, text="新建效果", command=lambda: self.add_effect({"effect_type": "", "effect_data": {}}))
        self.add_effect_button.pack(anchor="w")
        for effect in data.get("effects", []):
            self.add_effect(effect)
        if "choices" in data:
            self.add_effect({"effect_type": "choices", "effect_data": data["choices"]})
        self.cost_group = Collapsible(self.body, "消耗 cost")
        self.cost_group.pack(fill="x", pady=4)
        self.cost_notice = ttk.Label(self.cost_group.body, text=COST_HINT, wraplength=610)
        self.cost_notice.pack(anchor="w")
        self.cost_rows = ttk.Frame(self.cost_group.body)
        self.cost_rows.pack(fill="x", pady=5)
        ttk.Button(self.cost_group.body, text="添加消耗", command=lambda: self.add_cost({"resource": "mp", "value": 0})).pack(anchor="w")
        for cost in data.get("cost", []):
            self.add_cost(cost)
        self.extras, section = extras_box(self.body, data, self.fields, "技能单元高级设置（条件、次数、触发等）")
        self.extras.pack(fill="x")
        self.delete_button = ttk.Button(self.body, text="删除此技能单元", command=lambda: remove(self), style="NewSkillUnit.TButton")
        self.delete_button.pack(anchor="w", pady=(6, 2))
        self.update_type()
        self.update_target()

    def update_type(self):
        values = TARGETS if self.kind.get() in {"", "active"} else (*TARGETS, "event_actor", "event_source", "event_target", "event_targets")
        self.target_box.configure(values=values)
        self.type_notice.configure(text=TYPE_DESCRIPTIONS.get(self.kind.get(), "选择技能类型"))
        if self.release_entry and self.kind.get() == "active":
            self.phase_notice.pack(anchor="w", pady=(6, 0))
        else:
            self.phase_notice.pack_forget()
        request_layout(self)

    def update_target(self):
        self.target_notice.configure(text=TARGET_DESCRIPTIONS.get(self.target.get(), "选择效果目标"))
        request_layout(self)

    def phases_changed(self):
        for row in self.costs:
            row.update_phases(self.phases.get())
        for panel in self.effects:
            panel.choices.update_phases()

    def add_cost(self, data):
        row = CostRow(self.cost_rows, data, self.remove_cost, self.phases.get())
        row.pack(fill="x", pady=4)
        self.costs.append(row)
        request_layout(self)
        return row

    def remove_cost(self, row):
        self.costs.remove(row)
        row.destroy()
        if not self.costs:
            self.cost_rows.configure(height=1)
        request_layout(self)

    def add_effect(self, data):
        panel = EffectPanel(self.effect_rows, data, self.remove_effect, len(self.effects) + 1, self.catalogs,
                            allow_choices=True, phases=self.phases.get)
        panel.pack(fill="x", pady=3)
        self.effects.append(panel)
        request_layout(self)
        return panel

    def remove_effect(self, panel):
        self.effects.remove(panel)
        panel.destroy()
        if not self.effects:
            self.effect_rows.configure(height=1)
        for number, effect in enumerate(self.effects, 1):
            effect.label.configure(text=f"效果 {number}")
        request_layout(self)

    def read(self):
        result = merge_extras(self.extras.get(), self.fields, "技能单元高级设置")
        result.update(component_id=self.component_id.get().strip(), type=self.kind.get())
        optional_field(result, self.original, "available_phases", self.phases.get(), [])
        optional_field(result, self.original, "target", self.target.get(), "self")
        optional_field(result, self.original, "cost", [row.read() for row in self.costs], [])
        effects, choices = [], []
        for panel in self.effects:
            effect = panel.read()
            if effect["effect_type"] == "choices":
                choices.append(effect["effect_data"])
            else:
                effects.append(effect)
        if len(choices) > 1:
            raise ValueError("每个技能单元只能配置一条可选发动效果；独立的选择请另建技能单元")
        optional_field(result, self.original, "effects", effects, [])
        if choices:
            result["choices"] = choices[0]
        return validate_component_fields(result)

    @property
    def choices(self):
        return next((panel.choices for panel in self.effects if panel.effect_type.get().strip() == "choices"), None)

    def snapshot(self):
        return (self.component_id.get(), self.kind.get(), self.phases.get(), self.target.get(),
                [row.snapshot() for row in self.costs], [panel.snapshot() for panel in self.effects], self.extras.get())


class SkillForm(ttk.Frame):
    fields = {"skill_id", "name", "description", "rank", "components"}

    def __init__(self, parent, data, catalogs=None):
        super().__init__(parent)
        self.original = deepcopy(data)
        self.catalogs = catalogs
        self.components = []
        self.name, self.name_box = entry_row(self, "名称 name", data.get("name", ""), compact=True, font=("Microsoft YaHei UI", 11))
        self.rank, self.rank_box = entry_row(self, "等级 rank", data.get("rank", ""), choices=RANKS, compact=True, font=("Microsoft YaHei UI", 11))
        ttk.Label(self, text="技能说明 description").pack(anchor="w", pady=(5, 3))
        self.description = ScrolledText(self, height=3, wrap="word", undo=True, font=("Microsoft YaHei UI", 10))
        self.description.pack(fill="x")
        self.description.insert("1.0", data.get("description", ""))
        self.component_rows = ttk.Frame(self)
        self.component_rows.pack(fill="x", pady=8)
        self.component_controls = ttk.Frame(self)
        self.component_controls.pack(fill="x", pady=5)
        configure_unit_style(self)
        self.add_component_button = ttk.Button(self.component_controls, text="新建技能单元", command=self.add_component, style="NewSkillUnit.TButton")
        self.add_component_button.pack(side="left")
        for definition in data.get("components", []):
            self.add_component(definition)
        self.extras, section = extras_box(self, data, self.fields, "技能高级设置（如咏唱、分类等）")
        ttk.Label(section.body, text=f"内部标识 skill_id：{data['skill_id']}", wraplength=650).pack(anchor="w")
        self.extras.pack(fill="x")

    def collapse_all(self):
        def collapse(widget):
            if isinstance(widget, Collapsible) and widget.expanded:
                widget.expanded = False
                widget.render()
            for child in widget.winfo_children():
                collapse(child)

        collapse(self)

    def add_component(self, data=None):
        if data is None:
            used = {panel.component_id.get().strip() for panel in self.components}
            numbers = [int(key[5:]) for key in used if key.startswith("unit_") and key[5:].isascii() and key[5:].isdecimal()]
            number = max([-1, *numbers]) + 1
            data = {"component_id": f"unit_{number}", "type": "", "available_phases": ["AP1", "AP2"],
                    "target": "", "cost": [], "effects": []}
        casting = self.original.get("casting", {})
        release_entry = bool(casting or self.original.get("noble_phantasm_type")) and casting.get("activation_mode", "release") == "release"
        panel = ComponentPanel(self.component_rows, data, self.remove_component, len(self.components) + 1, self.catalogs, release_entry=release_entry)
        panel.pack(fill="x", pady=5)
        self.components.append(panel)
        self.renumber_components()
        request_layout(self)
        return panel

    def renumber_components(self):
        labels = [f"技能单元 {number}" for number in range(1, len(self.components) + 1)]
        for panel, label in zip(self.components, labels):
            panel.label.configure(text=label)
            if panel is self.components[0]:
                panel.separator.pack_forget()
            else:
                panel.separator.pack(fill="x", before=panel.header, pady=(0, 8))

    def remove_component(self, panel):
        self.components.remove(panel)
        panel.destroy()
        if not self.components:
            # Tk's packer leaves the last requested size behind when its final
            # child disappears. Reset it so an empty row cannot occupy a page.
            self.component_rows.configure(height=1)
        self.renumber_components()
        request_layout(self)

    def read(self):
        result = merge_extras(self.extras.get(), self.fields, "技能高级设置")
        if not self.components:
            raise ValueError("请至少新建一个技能单元，并为它配置效果或可选分支。")
        result.update(skill_id=self.original["skill_id"], name=self.name.get().strip(),
                      components=[panel.read() for panel in self.components])
        if not result["name"]:
            raise ValueError("请填写技能名称name")
        rank = self.rank.get().strip()
        if rank:
            SkillRank(rank)
        optional_field(result, self.original, "rank", rank, "")
        optional_field(result, self.original, "description", self.description.get("1.0", "end-1c"), "")
        return result

    def snapshot(self):
        return (self.name.get(), self.rank.get(), self.description.get("1.0", "end-1c"),
                [panel.snapshot() for panel in self.components], self.extras.get())
