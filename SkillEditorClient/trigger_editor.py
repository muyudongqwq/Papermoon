"""Chinese event selection for the engine's existing trigger configuration."""

from copy import deepcopy
import tkinter as tk
from tkinter import ttk

from SkillEditorClient.model import merge_extras, optional_field
from SkillEditorClient.widgets import Collapsible, JsonBox, configure_gray_area, request_layout
from skilleditor.documents import format_json


# Only events emitted by the current engine are offered here. Keep IDs stable;
# edit the Chinese names and explanations to change the visible text.
EVENT_OPTIONS = {
    "global_turn_start": ("全局回合开始", "after", "每个全局回合开始时通知。皇帝特权使用此事件；该事件没有单个角色目标。"),
    "global_turn_end": ("全局回合结束", "after", "全局回合结束时通知，在状态持续时间扣减之前结算。"),
    "ap_checkpoint": ("行动阶段检查点", "after", "到达行动阶段的检查点时通知，可结合事件阶段或上下文筛选。"),
    "personal_turn_start": ("战斗中角色回合开始", "after", "战斗中某角色的回合开始时通知，事件目标为该角色。"),
    "personal_turn_end": ("战斗中角色回合结束", "after", "战斗中某角色的回合结束时通知，事件目标为该角色。"),
    "battle_round_end": ("战斗轮结束", "after", "普通战斗轮结束时通知，包含本轮参与角色及魔力支付记录。"),
    "battle_declared": ("宣战", "after", "地图上的交战请求被宣布时通知，目标为被宣战者。"),
    "battle_joined": ("加入战斗", "after", "角色加入战斗时通知，事件目标为加入的角色。"),
    "battle_left": ("离开战斗", "after", "角色离开战斗时通知，事件目标为离开的角色。"),
    "action_declared": ("行动结算前", "before", "统一行动宣布后、执行前通知；可结合行动ID等附加条件筛选。"),
    "action_resolved": ("行动结算后", "after", "统一行动执行完成后通知，包含行动ID和执行结果。"),
    "before_damage": ("伤害结算前", "before", "伤害应用前通知，可修改或取消本次伤害；事件目标为受伤角色。"),
    "damage_received": ("受到伤害后", "after", "角色实际受到伤害后通知，事件目标为受伤角色；可用附加条件限定为自身。"),
    "damage_dealt": ("造成伤害后", "after", "伤害结算后通知，事件行动者为伤害来源、目标为受伤角色。"),
    "before_battle_continuation": ("战斗续行判定前", "before", "通用濒死不可用时，在战斗续行的保命顺序处通知。"),
    "before_lethal_damage": ("其他保命技能判定前", "before", "战斗续行后仍为致命伤时通知，供其他保命技能结算。"),
    "brink_entered": ("进入濒死", "after", "角色进入通用濒死状态时通知，事件目标为该角色。"),
    "resource_changed": ("资源发生变化", "after", "资源当前值发生变化后通知；可用资源ID等附加条件筛选。"),
    "resource_paid": ("支付资源后", "after", "成功支付资源后通知，事件数值记录实际变化量。"),
    "resource_recovered": ("恢复资源后", "after", "恢复资源后通知，包含资源ID及实际变化量。"),
    "resource_gained": ("获得资源后", "after", "获得资源后通知，包含资源ID及实际变化量。"),
    "status_added": ("施加状态后", "after", "状态施加后通知，事件目标为状态承受者。"),
    "status_removed": ("移除状态后", "after", "状态移除后通知，包含状态ID及移除原因。"),
    "modifier_applied": ("修正效果施加后", "after", "修正效果成功施加后通知，包含新效果状态。"),
    "modifier_removed": ("修正效果移除后", "after", "修正效果移除后通知，包含旧效果状态及移除原因。"),
    "modifier_replaced": ("修正效果替换后", "after", "修正效果被替换后通知，包含替换前后的效果状态。"),
    "modifier_refreshed": ("修正效果刷新后", "after", "修正效果刷新后通知，包含刷新前后的效果状态。"),
    "modifier_stack_changed": ("修正效果层数变化", "after", "修正效果叠层后通知，包含原层数和新层数。"),
    "modifier_consumed": ("修正效果次数消耗后", "after", "修正效果的可用次数被消耗后通知。"),
    "skill_added": ("获得技能后", "after", "角色获得技能后通知，包含技能ID及来源类型。"),
    "skill_removed": ("移除技能后", "after", "角色失去技能后通知，包含技能ID及移除原因。"),
    "character_registered": ("角色加入游戏", "after", "角色注册进游戏后通知，事件目标为该角色。"),
    "character_despawned": ("角色退场", "after", "角色从游戏移除后通知，包含退场原因。"),
    "character_died": ("角色死亡", "after", "角色死亡时通知；死亡角色自身是否仍可触发由allow_when_dead决定。"),
    "position_left": ("离开地点", "after", "角色离开地点时通知，包含原地点和新地点。"),
    "position_entered": ("进入地点", "after", "角色进入地点时通知，包含原地点和新地点。"),
}
TIMING_NAMES = {"before": "事件发生前", "after": "事件发生后"}


class TriggerEditor(ttk.Frame):
    fields = {"event_type", "timing"}

    def __init__(self, parent, value, *, fallback_event="", fallback_priority=0):
        configure_gray_area(parent)
        super().__init__(parent, style="PhaseArea.TFrame", padding=(8, 6), borderwidth=1, relief="solid")
        self.loading = False
        ttk.Label(self, text="触发事件 trigger", style="PhaseArea.TLabel").pack(anchor="w", pady=(0, 4))
        row = ttk.Frame(self, style="PhaseArea.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="事件", width=9, style="PhaseArea.TLabel").pack(side="left")
        self.selection = tk.StringVar(master=self)
        self.event_box = ttk.Combobox(row, textvariable=self.selection, values=tuple(v[0] for v in EVENT_OPTIONS.values()))
        self.event_box.pack(side="left", fill="x", expand=True)
        self.event_box.bind("<MouseWheel>", lambda _event: "break")
        self.description = ttk.Label(self, style="PhaseArea.TLabel", wraplength=650)
        self.description.pack(anchor="w", pady=(4, 2))
        row = ttk.Frame(self, style="PhaseArea.TFrame")
        row.pack(fill="x", pady=3)
        ttk.Label(row, text="触发时机", width=9, style="PhaseArea.TLabel").pack(side="left")
        self.timing = tk.StringVar(master=self)
        self.timing_box = ttk.Combobox(row, textvariable=self.timing, values=tuple(TIMING_NAMES.values()), state="readonly", width=18)
        self.timing_box.pack(side="left")
        self.timing_box.bind("<MouseWheel>", lambda _event: "break")
        self.advanced = Collapsible(self, "触发事件高级设置（优先级等）")
        self.advanced.pack(fill="x", pady=3)
        self.extras = JsonBox(self.advanced.body, {}, height=3)
        self.extras.pack(fill="x")
        self.selection.trace_add("write", lambda *_: self.update_event())
        self.load(value, fallback_event=fallback_event, fallback_priority=fallback_priority)

    @property
    def event_type(self):
        return {v[0]: k for k, v in EVENT_OPTIONS.items()}.get(self.selection.get(), self.selection.get().strip())

    def load(self, value, *, fallback_event="", fallback_priority=0):
        if not isinstance(value, dict):
            raise ValueError("触发事件必须是对象")
        self.loading = True
        try:
            self.original = deepcopy(value)
            self.fallback_priority = fallback_priority
            event = value.get("event_type", fallback_event)
            self.selection.set(EVENT_OPTIONS[event][0] if event in EVENT_OPTIONS else event)
            timing = value.get("timing", "after")
            self.timing.set(TIMING_NAMES.get(timing, timing))
            self.extras.text.delete("1.0", "end")
            self.extras.text.insert("1.0", format_json({k: v for k, v in value.items() if k not in self.fields}))
            self.baseline = self.snapshot()
        finally:
            self.loading = False
        self.update_event(reset_timing=False)

    def update_event(self, *, reset_timing=True):
        option = EVENT_OPTIONS.get(self.event_type)
        self.description.configure(text=option[2] if option else (
            "自定义事件ID；只有对应事件实际发送时才会触发。" if self.event_type else "选择触发事件"))
        if option and not self.loading and reset_timing:
            self.timing.set(TIMING_NAMES[option[1]])
        # Built-in events only emit at the stated timing. Keep an existing
        # unusual timing visible for repair, without silently changing a card.
        current = self.timing.get()
        choices = (TIMING_NAMES[option[1]],) if option else tuple(TIMING_NAMES.values())
        self.timing_box.configure(values=tuple(dict.fromkeys((*choices, current))) if current else choices)
        request_layout(self)

    def get(self):
        if self.snapshot() == self.baseline:
            return deepcopy(self.original)
        result = merge_extras(self.extras.get(), self.fields, "触发事件高级设置")
        if not self.event_type:
            raise ValueError("请选择触发事件")
        timing = {v: k for k, v in TIMING_NAMES.items()}.get(self.timing.get(), self.timing.get())
        if timing not in TIMING_NAMES:
            raise ValueError("请选择有效的触发时机")
        priority = result.get("priority", self.fallback_priority)
        if type(priority) is not int:
            raise ValueError("触发事件优先级必须是整数")
        result["event_type"] = self.event_type
        optional_field(result, self.original, "timing", timing, "after")
        return result

    def snapshot(self):
        return self.selection.get(), self.timing.get(), self.extras.get()
