"""Experimental status forms; no catalog migration or engine changes required."""

from copy import deepcopy
import tkinter as tk
from tkinter import ttk

from game.modifier.modifier import MODIFIER_TYPES
from game.status.registry import validate_status_definition
from SkillEditorClient.condition_editor import ConditionEditor
from SkillEditorClient.forms import EffectPanel, extras_box
from SkillEditorClient.model import merge_extras, optional_field
from SkillEditorClient.trigger_editor import TriggerEditor
from SkillEditorClient.widgets import (
    Collapsible, SECTION_SEPARATOR_COLOR, SECTION_SEPARATOR_HEIGHT, UNIT_FONT,
    configure_gray_area, configure_unit_style, entry_row, request_layout,
)


# Turn this off to return status entries to the original JSON editor by default.
ENABLE_STATUS_FORM = True
POLARITIES = {"buff": "正面", "debuff": "负面", "neutral": "中性"}
STATUS_TYPES = {"passive": "持续生效", "trigger": "自动触发", "react": "可选反应"}
STATUS_TARGETS = {"self": "状态持有者", "event_actor": "事件行动者", "event_source": "事件来源",
                  "event_target": "事件目标", "event_targets": "事件全部目标"}
SCOPES = {"same_source": "同来源", "all_sources": "所有来源", "independent": "每次独立"}
STACK_RULES = {"reject": "拒绝再次施加", "refresh": "刷新", "replace": "替换", "stack": "叠层",
               "independent": "独立保留", "strongest": "保留较强者"}
REFRESH_RULES = {"reset": "重置", "keep_longer": "保留较长时间", "extend": "累加", "unchanged": "不变"}
MAX_RULES = {"refresh": "刷新", "reject": "拒绝", "replace": "替换"}
TYPE_HELP = {"passive": "状态持有期间持续生效；随状态叠层，并在状态移除时一并撤销。",
             "trigger": "指定事件发生且条件满足时自动执行；按持有者、状态、施加者、原技能和单元，每全局回合最多一次。",
             "react": "指定事件发生且条件满足时，由状态持有者选择是否发动；同一持有者的同ID状态，多来源、多单元共享每全局回合一次。"}


def can_use_status_form(definition):
    try:
        validate_status_definition(definition)
        return True
    except (TypeError, ValueError, KeyError):
        return False


def selected(variable, labels, label):
    value = {text: key for key, text in labels.items()}.get(variable.get())
    if value is None:
        raise ValueError(f"请选择{label}")
    return value


def positive_integer(text, label):
    if not text.isascii() or not text.isdecimal() or int(text) < 1:
        raise ValueError(f"{label}必须是正整数")
    return int(text)


class StackingForm(Collapsible):
    fields = {"stack_scope", "stacking_rule", "stack_count", "max_stacks", "duration_refresh_rule", "at_max_stacks_rule"}

    def __init__(self, parent, data):
        super().__init__(parent, "叠加规则")
        self.original = deepcopy(data)
        self.scope, _ = entry_row(self.body, "哪些来源一起处理", SCOPES[data.get("stack_scope", "same_source")], choices=tuple(SCOPES.values()), editable=False)
        ttk.Label(self.body, text="同来源会核对施加者与原技能等来源信息；不同施加者分别记录。每次独立时不合并实例。", wraplength=650).pack(anchor="w", pady=2)
        self.rule, self.rule_box = entry_row(self.body, "再次施加时", STACK_RULES[data.get("stacking_rule", "refresh")], choices=tuple(STACK_RULES.values()), editable=False)
        self.layers = ttk.Frame(self.body)
        self.initial, _ = entry_row(self.layers, "初始层数", str(data.get("stack_count", 1)), compact=True)
        self.maximum, _ = entry_row(self.layers, "层数上限", str(data.get("max_stacks", 1)), compact=True)
        self.at_max, _ = entry_row(self.layers, "满层后再次施加", MAX_RULES[data.get("at_max_stacks_rule", "refresh")], choices=tuple(MAX_RULES.values()), editable=False)
        self.refresh, self.refresh_box = entry_row(self.body, "持续时间更新方式", REFRESH_RULES[data.get("duration_refresh_rule", "reset")], choices=tuple(REFRESH_RULES.values()), editable=False)
        self.extras, self.advanced = extras_box(self.body, data, self.fields, "叠加高级设置（分组、强度比较等）")
        self.extras.pack(fill="x")
        self.strongest_notice = ttk.Label(self.body, text="状态本身没有数值强度；保留较强者时，请在叠加高级设置提供 strength_priority（数值）与 strength_comparison（higher或lower）。", wraplength=650)
        for variable in (self.rule, self.scope):
            variable.trace_add("write", lambda *_: self.update_controls())
        self.update_controls()

    def update_controls(self):
        layered = self.rule.get() == STACK_RULES["stack"]
        if layered:
            self.layers.pack(fill="x", before=self.refresh_box.master)
        else:
            self.layers.pack_forget()
        if self.rule.get() == STACK_RULES["strongest"]:
            self.strongest_notice.pack(anchor="w", before=self.advanced, pady=3)
        else:
            self.strongest_notice.pack_forget()
        request_layout(self)

    def read(self):
        result = merge_extras(self.extras.get(), self.fields, "叠加高级设置")
        values = {"stack_scope": selected(self.scope, SCOPES, "来源范围"),
                  "stacking_rule": selected(self.rule, STACK_RULES, "重施方式"),
                  "stack_count": positive_integer(self.initial.get().strip(), "初始层数"),
                  "max_stacks": positive_integer(self.maximum.get().strip(), "层数上限"),
                  "duration_refresh_rule": selected(self.refresh, REFRESH_RULES, "时间更新方式"),
                  "at_max_stacks_rule": selected(self.at_max, MAX_RULES, "满层处理方式")}
        defaults = {"stack_scope": "same_source", "stacking_rule": "refresh", "stack_count": 1,
                    "max_stacks": 1, "duration_refresh_rule": "reset", "at_max_stacks_rule": "refresh"}
        for key, value in values.items():
            optional_field(result, self.original, key, value, defaults[key])
        if values["stacking_rule"] == "strongest" and "strength_priority" not in result:
            raise ValueError("状态保留较强者时，请在叠加高级设置填写数值strength_priority")
        return result

    def snapshot(self):
        return tuple(variable.get() for variable in (self.scope, self.rule, self.initial, self.maximum, self.at_max, self.refresh)), self.extras.get()


class StatusUnit(Collapsible):
    fields = {"component_id", "type", "target", "trigger", "condition", "effects"}

    def __init__(self, parent, data, remove, number, catalogs):
        configure_unit_style(parent)
        super().__init__(parent, f"状态单元 {number}", font=UNIT_FONT, button_style="NewSkillUnit.TButton")
        self.original = deepcopy(data)
        self.component_id = data["component_id"]
        self.catalogs, self.effects = catalogs, []
        self.choices = None  # Shared reference-window traversal; statuses have no choices.
        self.separator = tk.Frame(self, background=SECTION_SEPARATOR_COLOR,
                                  height=SECTION_SEPARATOR_HEIGHT, borderwidth=0, highlightthickness=0)
        self.kind, _ = entry_row(self.body, "状态单元类型", STATUS_TYPES.get(data.get("type"), ""), choices=tuple(STATUS_TYPES.values()), editable=False, compact=True)
        self.type_notice = ttk.Label(self.body, wraplength=650)
        self.type_notice.pack(anchor="w", pady=3)
        self.trigger_editor = TriggerEditor(self.body, data.get("trigger", {}))
        self.conditions = ConditionEditor(self.body, data.get("condition", {}), catalogs)
        self.target, self.target_box = entry_row(self.body, "效果目标", STATUS_TARGETS.get(data.get("target", "self"), ""), choices=tuple(STATUS_TARGETS.values()), editable=False)
        self.target_notice = ttk.Label(self.body, text="状态持有者是承受此状态的角色；持续伤害的来源仍为原施加者。", wraplength=650)
        self.target_notice.pack(anchor="w", pady=3)
        self.effect_group = Collapsible(self.body, "状态效果")
        self.effect_group.pack(fill="x", pady=4)
        self.effect_rows = ttk.Frame(self.effect_group.body)
        self.effect_rows.pack(fill="x")
        self.add_effect_button = ttk.Button(self.effect_group.body, text="新建效果", command=self.add_effect)
        self.add_effect_button.pack(anchor="w")
        for effect in data.get("effects", []):
            self.add_effect(effect)
        self.extras, section = extras_box(self.body, data, self.fields, "状态单元高级设置（名称等）")
        self.extras.pack(fill="x")
        ttk.Label(section.body, text=f"内部标识：{self.component_id}").pack(anchor="w")
        self.delete_button = ttk.Button(self.body, text="删除此状态单元", command=lambda: remove(self), style="NewSkillUnit.TButton")
        self.delete_button.pack(anchor="w", pady=5)
        self.kind.trace_add("write", lambda *_: self.update_type())
        self.update_type()

    @property
    def type_id(self):
        return {text: key for key, text in STATUS_TYPES.items()}.get(self.kind.get(), "")

    def update_type(self):
        kind = self.type_id
        self.type_notice.configure(text=TYPE_HELP.get(kind, "选择状态单元类型"))
        if kind in {"trigger", "react"}:
            self.trigger_editor.pack(fill="x", before=self.target_box.master, pady=4)
            self.conditions.pack(fill="x", before=self.target_box.master, pady=4)
        else:
            self.trigger_editor.pack_forget()
            self.conditions.pack_forget()
        self.target_box.configure(values=(STATUS_TARGETS["self"],) if kind == "passive" else tuple(STATUS_TARGETS.values()))
        allowed = tuple(sorted(set(MODIFIER_TYPES) - {"hidden"})) if kind == "passive" else None
        for effect in self.effects:
            if allowed is not None:
                effect.type_box.configure(values=allowed)
            else:
                from SkillEditorClient.effect_options import EFFECT_TYPES
                effect.type_box.configure(values=EFFECT_TYPES)
        request_layout(self)

    def add_effect(self, data=None):
        is_new = data is None
        panel = EffectPanel(self.effect_rows, data or {"effect_type": "", "effect_data": {}}, self.remove_effect, len(self.effects) + 1, self.catalogs)
        panel.pack(fill="x", pady=3)
        self.effects.append(panel)
        if is_new:
            panel.toggle()
        self.update_type()
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
        result = merge_extras(self.extras.get(), self.fields, "状态单元高级设置")
        result.update(component_id=self.component_id, type=selected(self.kind, STATUS_TYPES, "状态单元类型"))
        optional_field(result, self.original, "target", selected(self.target, STATUS_TARGETS, "效果目标"), "self")
        # Keep hidden drafts for switching back, but passive units own no event
        # or unit condition. Saving only serializes the currently selected type.
        trigger, condition = ({}, {}) if result["type"] == "passive" else (self.trigger_editor.get(), self.conditions.get())
        optional_field(result, self.original, "trigger", trigger, {})
        optional_field(result, self.original, "condition", condition, {})
        result["effects"] = [effect.read() for effect in self.effects]
        return result

    def snapshot(self):
        return self.kind.get(), self.target.get(), self.trigger_editor.snapshot(), self.conditions.snapshot(), tuple(effect.snapshot() for effect in self.effects), self.extras.get()


class StatusForm(ttk.Frame):
    fields = {"status_id", "name", "description", "polarity", "purifiable", "duration", "persist_after_death", "stacking", "components", "tags", "consumption"}

    def __init__(self, parent, data, catalogs=None):
        super().__init__(parent)
        configure_gray_area(self)
        configure_unit_style(self)
        self.original, self.catalogs, self.components = deepcopy(data), catalogs, []
        ttk.Label(self, text=f"状态标识 status_id：{data['status_id']}").pack(anchor="w", pady=3)
        self.name, _ = entry_row(self, "名称 name", data["name"], compact=True, font=UNIT_FONT)
        ttk.Label(self, text="状态说明 description").pack(anchor="w", pady=3)
        self.description = tk.Text(self, height=4, wrap="word", undo=True, font=("Microsoft YaHei UI", 11))
        self.description.pack(fill="x")
        self.description.insert("1.0", data.get("description", ""))
        self.tags, _ = entry_row(self, "状态标签 tags", ", ".join(data.get("tags", [])))
        ttk.Label(self, text="多个标签用逗号分隔；弱体无效按状态本身的标签筛选，不读取角色标签。", wraplength=650).pack(anchor="w", pady=2)
        self.life = Collapsible(self, "存续规则")
        self.life.pack(fill="x", pady=5)
        self.polarity, _ = entry_row(self.life.body, "状态性质", POLARITIES[data.get("polarity", "neutral")], choices=tuple(POLARITIES.values()), editable=False)
        self.purifiable = tk.BooleanVar(self, value=data.get("purifiable", data.get("polarity") == "debuff"))
        ttk.Checkbutton(self.life.body, text="可以净化", variable=self.purifiable).pack(anchor="w")
        self.duration_mode, _ = entry_row(self.life.body, "持续方式", "永久" if data.get("duration") is None else "指定回合数", choices=("永久", "指定回合数"), editable=False)
        self.duration, self.duration_box = entry_row(self.life.body, "持续回合数", str(data.get("duration") or 1), compact=True)
        self.persist = tk.BooleanVar(self, value=data.get("persist_after_death", False))
        self.death_box = ttk.Checkbutton(self.life.body, text="持有者死亡后保留", variable=self.persist)
        self.death_box.pack(anchor="w")
        consumption = data.get("consumption", {})
        self.uses_mode, _ = entry_row(self.life.body, "次数限制", "指定次数" if consumption else "不限", choices=("不限", "指定次数"), editable=False)
        self.uses, self.uses_box = entry_row(self.life.body, "可阻止次数", str(consumption.get("uses", 1)), compact=True)
        self.uses_notice = ttk.Label(self.life.body, text="每阻止一次匹配的负面状态扣1次；次数耗尽或持续时间到期，任一满足即移除状态。", wraplength=650)
        self.uses_notice.pack(anchor="w", pady=3)
        ttk.Label(self.life.body, text="先结算全局回合结束事件，再扣减持续时间。这里设置仓库默认值，施加状态的技能仍可覆盖。", wraplength=650).pack(anchor="w", pady=3)
        self.duration_mode.trace_add("write", lambda *_: self.update_duration())
        self.uses_mode.trace_add("write", lambda *_: self.update_uses())
        self.update_uses()
        self.update_duration()
        self.stacking = StackingForm(self, data.get("stacking", {}))
        self.stacking.pack(fill="x", pady=4)
        self.marker_notice = ttk.Label(self, text="尚无状态单元：这是标记状态。只有被其他规则读取时才产生相应作用。", wraplength=650)
        self.marker_notice.pack(anchor="w", pady=5)
        self.unit_rows = ttk.Frame(self)
        self.unit_rows.pack(fill="x")
        self.add_unit_button = ttk.Button(self, text="新建状态单元", command=self.add_component, style="NewSkillUnit.TButton")
        self.add_unit_button.pack(anchor="w", pady=5)
        for component in data["components"]:
            self.add_component(component)
        self.extras, _ = extras_box(self, data, self.fields, "状态高级设置（计时规则等）")
        self.extras.pack(fill="x")

    def update_duration(self):
        if self.duration_mode.get() == "指定回合数":
            self.duration_box.master.master.pack(fill="x", before=self.death_box)
        else:
            self.duration_box.master.master.pack_forget()
        request_layout(self)

    def update_uses(self):
        row = self.uses_box.master.master
        if self.uses_mode.get() == "指定次数":
            row.pack(fill="x", before=self.uses_notice)
        else:
            row.pack_forget()
        request_layout(self)

    def add_component(self, data=None):
        if data is None:
            used = {unit.component_id for unit in self.components}
            index = 0
            while f"unit_{index}" in used:
                index += 1
            data = {"component_id": f"unit_{index}", "effects": []}
        unit = StatusUnit(self.unit_rows, data, self.remove_component, len(self.components) + 1, self.catalogs)
        unit.pack(fill="x", pady=5)
        self.components.append(unit)
        self.renumber()
        return unit

    def remove_component(self, unit):
        self.components.remove(unit)
        unit.destroy()
        if not self.components:
            self.unit_rows.configure(height=1)
        self.renumber()

    def renumber(self):
        for index, unit in enumerate(self.components):
            unit.label.configure(text=f"状态单元 {index + 1}")
            unit.separator.pack_forget()
            if index:
                unit.separator.pack(fill="x", before=unit.header, pady=(4, 7))
        if self.components:
            self.marker_notice.pack_forget()
        else:
            self.marker_notice.pack(anchor="w", before=self.unit_rows, pady=5)
        request_layout(self)

    def collapse_all(self):
        def visit(widget):
            if isinstance(widget, Collapsible) and widget.expanded:
                widget.expanded = False
                widget.render()
            for child in widget.winfo_children():
                visit(child)
        visit(self)

    def read(self):
        result = merge_extras(self.extras.get(), self.fields, "状态高级设置")
        polarity = selected(self.polarity, POLARITIES, "状态性质")
        result.update(status_id=self.original["status_id"], name=self.name.get().strip(), components=[unit.read() for unit in self.components])
        duration = None if self.duration_mode.get() == "永久" else positive_integer(self.duration.get().strip(), "持续回合数")
        values = {"description": (self.description.get("1.0", "end-1c"), ""), "polarity": (polarity, "neutral"),
                  "purifiable": (self.purifiable.get(), polarity == "debuff"), "duration": (duration, None),
                  "persist_after_death": (self.persist.get(), False), "stacking": (self.stacking.read(), {})}
        for key, (value, default) in values.items():
            optional_field(result, self.original, key, value, default)
        raw_tags = self.tags.get()
        tags = (deepcopy(self.original.get("tags", [])) if raw_tags == ", ".join(self.original.get("tags", [])) else
                list(dict.fromkeys(tag.strip() for tag in raw_tags.replace("，", ",").split(",") if tag.strip())))
        optional_field(result, self.original, "tags", tags, [])
        if self.uses_mode.get() == "指定次数":
            consumption = deepcopy(self.original.get("consumption", {}))
            consumption["event"] = "status_blocked"
            optional_field(consumption, self.original.get("consumption", {}), "uses",
                           positive_integer(self.uses.get().strip(), "可阻止次数"), 1)
            result["consumption"] = consumption
        validate_status_definition(result)
        return result

    def snapshot(self):
        return (self.name.get(), self.description.get("1.0", "end-1c"), self.tags.get(), self.uses_mode.get(), self.uses.get(), self.polarity.get(), self.purifiable.get(),
                self.duration_mode.get(), self.duration.get(), self.persist.get(), self.stacking.snapshot(),
                tuple(unit.snapshot() for unit in self.components), self.extras.get())
