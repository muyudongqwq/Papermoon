"""Built-in status catalog. Editors may override these definitions."""


def marker(status_id, name, *, polarity="neutral", purifiable=False):
    return {"status_id": status_id, "name": name, "description": "由对应规则读取的状态标记。",
            "polarity": polarity, "purifiable": purifiable, "duration": None,
            "stacking": {"stack_scope": "same_source", "stacking_rule": "refresh"},
            "components": []}


STATUS_DATA = {key: marker(key, name, polarity=polarity) for key, name, polarity in (
    ("cannot_investigate", "无法调查", "debuff"), ("cannot_escape", "无法撤退", "debuff"),
    ("random_defense", "随机防御", "debuff"), ("brink_of_death", "濒死", "neutral"),
    ("weakness", "虚弱", "debuff"), ("stay", "留守", "neutral"),
    ("casting", "咏唱", "neutral"), ("cannot_dodge", "无法闪避", "debuff"),
    ("retain_attack_phase_on_failed_defense", "防御失败保留攻击阶段", "buff"),
    ("carriable", "可骑乘", "neutral"),
    ("debug_mode_on", "调试模式", "neutral"),
)}
STATUS_DATA["burning"] = {
    "status_id": "burning", "name": "燃烧",
    "description": "示例状态：每个全局回合末每层造成10点基础魔术伤害，最多3层，持续3次回合末。同来源重施叠层并刷新时间，不同施加者分别记录。",
    "polarity": "debuff", "purifiable": True, "duration": 3,
    "stacking": {"stack_scope": "same_source", "stacking_rule": "stack", "max_stacks": 3,
                 "duration_refresh_rule": "reset"},
    "components": [{"component_id": "burning_tick", "type": "trigger", "target": "self",
                    "trigger": {"event_type": "global_turn_end", "timing": "after"},
                    "effects": [{"effect_type": "damage",
                                 "effect_data": {"damage_type": "magic", "value_source": "status_stack_count",
                                                 "multiplier": 10}}]}],
}
STATUS_DATA["debuff_immunity"] = {
    "status_id": "debuff_immunity", "name": "弱体无效", "polarity": "buff", "purifiable": False,
    "description": "阻止新施加的负面状态，不清除已有状态。默认1次、1回合，任一耗尽即移除；标签可限定免疫范围。",
    "duration": 1, "consumption": {"event": "status_blocked", "uses": 1},
    "components": [{"component_id": "immunity", "type": "passive", "target": "self",
                    "effects": [{"effect_type": "status_immunity", "effect_data": {"tags": []}}]}],
}
