"""Shared graphical cost entries for skills, branches and maintained effects."""
from copy import deepcopy
import tkinter as tk
from tkinter import ttk
from game.resource.costs import validate_costs
from SkillEditorClient.model import cost_value, merge_extras, optional_field, resource_options
from SkillEditorClient.widgets import Collapsible, JsonBox, entry_row
from skilleditor.documents import format_json

COST_TIMING_NAMES = {"activation": "技能发动时", "casting_start": "开始咏唱时预付（无需咏唱则发动时支付）", "maintenance": "回合末维持时"}


class CostRow(ttk.Frame):
    fields = {"resource", "value", "timing"}

    def __init__(self, parent, data, remove, phases, *, timings=("activation",)):
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
        self.timing, self.timing_box = entry_row(self, "支付时机", COST_TIMING_NAMES.get(data.get("timing", "activation"), ""),
            choices=tuple(COST_TIMING_NAMES[timing] for timing in timings), editable=False)
        self.timings = timings
        self.phases = tuple(phases)
        self.timing.trace_add("write", lambda *_: self.update_options())
        self.update_options()
        section = Collapsible(self, "消耗高级设置（如cost_id）")
        section.pack(fill="x", pady=3)
        self.extras = JsonBox(section.body, {k: v for k, v in data.items() if k not in self.fields}, height=3)
        self.extras.pack(fill="x")

    def update_phases(self, phases):
        self.phases = tuple(phases)
        self.update_options(clear_ap=True)

    def update_options(self, *, clear_ap=False):
        options = ["mp"] if self.timing.get() == COST_TIMING_NAMES["casting_start"] else resource_options(self.phases)
        self.resource_box.configure(values=options)
        if clear_ap and self.resource.get() == "action_point" and "action_point" not in options:
            self.resource.set("")

    def read(self):
        result = merge_extras(self.extras.get(), self.fields, "消耗高级设置")
        result.update(resource=self.resource.get().strip(), value=cost_value(self.value.get()))
        timing = {label: key for key, label in COST_TIMING_NAMES.items()}.get(self.timing.get())
        if timing not in self.timings:
            raise ValueError("请选择有效的支付时机")
        optional_field(result, self.original, "timing", timing, "activation")
        validate_costs([result], timings=self.timings)
        return result

    def snapshot(self):
        return self.resource.get(), self.value.get(), self.timing.get(), self.extras.get()
