"""Read-only presentation data for controlled characters, never legality rules."""

from copy import deepcopy

from game.skill.casting import get_casting_config, noble_damage_multiplier
from game.skill.component_runtime import component_runtime_reasons, component_use_count, get_component_state


_STATS = {"attack": "攻击骰", "defense": "防御骰", "physical_attack": "物理攻击骰", "magic_attack": "魔术攻击骰", "dice_bonus": "判定骰",
          "dodge": "闪避骰", "block": "格挡骰", "offset": "抵消骰", "hide": "隐蔽骰",
          "perceive": "感知骰", "strength": "筋力", "endurance": "耐久", "flexibility": "敏捷",
          "magic": "魔力", "fortune": "幸运"}
_EFFECTS = {
    "damage": "直接伤害", "create_attack_event": "攻击", "attack_bonus": "基础攻击伤害",
    "dice_bonus": "判定加成", "attribute_bonus": "属性加成", "numeric_attribute_bonus": "数值加成",
    "magic_resistance": "对魔力", "shield": "护盾", "hp_floor": "HP下限",
    "recover_resource": "回复资源", "gain_resource": "获得资源", "modify_resource": "调整资源",
    "modify_event_value": "调整本次结算数值", "prevent_death": "致命伤时保留HP",
    "create_field": "建立场地", "switch_skill_set": "切换能力", "presence_concealment": "气息遮断",
    "add_status": "附加状态", "hidden": "隐蔽", "add_skill": "获得技能", "remove_skill": "移除技能",
    "summon": "召唤", "add_resource": "建立资源", "add_action": "获得行动",
    "visibility_bonus": "视野变化", "perception_check": "感知检定", "cancel_event": "取消本次事件",
    "plus_bonus": "加符容量", "carry_capacity": "载员容量", "cost_modifier": "消耗修正",
    "damage_modifier": "伤害修正", "movement_point_bonus": "移动力变化",
    "change_damage_type": "改变伤害类型", "deploy_reality_marble": "展开固有结界",
    "trap": "设置陷阱", "add_simple_round": "进行简易战斗轮", "extra_attack_phase": "额外攻击阶段",
    "restore_component": "恢复次数或冷却", "add_content": "获得能力", "remove_content": "失去能力",
    "growth_system": "成长效果", "order_change": "调整行动顺序",
}


def effect_view(effect, skill=None):
    kind, data = effect["effect_type"], effect.get("effect_data", {})
    label = _EFFECTS.get(kind, "特殊效果")
    if kind in {"dice_bonus", "attribute_bonus", "numeric_attribute_bonus"}:
        label = _STATS.get(data.get("effect_target"), label)
    value = data.get("damage_value", data.get("value", data.get("hp")))
    if kind in {"damage", "create_attack_event"} and isinstance(value, (int, float)):
        value *= noble_damage_multiplier(skill)
    description = label
    if data.get("value_source") == "status_stack_count":
        description += f"：状态层数×{data.get('multiplier', 1):g}"
        if data.get("flat", 0):
            description += f"{data['flat']:+g}"
    if kind == "add_status":
        from game.status.registry import get_status_definition
        status = get_status_definition(data["status_id"])
        description += f"：{status['name']}"
    if isinstance(value, (int, float)):
        description += f"{value:+g}" if kind.endswith("bonus") else f"：{value:g}"
    if kind == "prevent_death":
        description = f"致命伤时保留至少{data.get('hp', 1)}HP"
        if data.get("hp_floor_duration"):
            description += f"，HP下限持续至第{data['hp_floor_duration']}次全局回合结束"
    if kind == "create_field":
        description = f"建立{data.get('name', '场地')}"
        if data.get("battle_bound"):
            description += "，持续至本场战斗结束"
        if data.get("exit_penalty"):
            description += f"；未经许可离场受到{data['exit_penalty']['value']}点直接伤害"
    if kind == "create_attack_event":
        if data.get("damage_type") == "magic":
            description += "点魔术伤害"
        if data.get("ignore_block"):
            description += "，忽略格挡减伤"
        if data.get("ignore_shield"):
            description += "，忽略护盾"
    if "mental" in effect.get("conditions", {}).get("tags", []):
        description += "（仅精神判定）"
    if effect.get("duration") is not None:
        description += f"，持续{effect['duration']}回合"
    return {"effect_type": kind, "name": effect.get("name", label), "description": description}


def component_view(actor, skill, component, component_index=0):
    component_id = component.get("component_id", f"component_{component_index}")
    state = get_component_state(skill, component_id, create=False)
    reasons = component_runtime_reasons(actor, skill, component)
    active = skill.is_component_active(component_id)
    if not active:
        reasons.append("component_expired")
    usage = component.get("usage_limit")
    usage_view = None
    if usage:
        applicable = usage["scope"] != "battle" or actor.current_battle is not None
        used = component_use_count(actor, skill, component) if applicable else None
        usage_view = {**usage, "used": used,
                      "remaining": None if used is None else max(0, usage["maximum"] - used)}
    cooldown = component.get("cooldown")
    cooldown_view = None
    if cooldown:
        ready = state.cooldown_ready_turn if state else None
        group = cooldown.get("group")
        group_ready = getattr(skill, "cooldown_group_ready_turns", {}).get(group) if group else None
        ready = max((item for item in (ready, group_ready) if item is not None), default=None)
        cooldown_view = {**cooldown, "ready_turn": ready,
                         "turns_remaining": max(0, (ready or 0) - actor.current_global_turn)}
    effects = [effect_view(effect, skill) for effect in component.get("effects", [])]
    choices = [{"choice_id": choice["choice_id"], "name": choice.get("name", choice["choice_id"]),
                "effects": [effect_view(effect, skill) for effect in choice.get("effects", [])]}
               for choice in component.get("choices", {}).get("options", [])]
    descriptions = [effect["description"] for effect in effects]
    if choices:
        descriptions.append("选择：" + "、".join(choice["name"] for choice in choices))
    events = getattr(getattr(actor, "game_manager", None), "event_manager", None)
    return {
        "component_id": component_id, "name": component.get("name", skill.name),
        "type": component["type"], "active": active,
        "runtime_available": not reasons, "runtime_reasons": reasons,
        "usage": usage_view, "cooldown": cooldown_view,
        "casting_requirement": component.get("casting_requirement", 0),
        "available_phases": list(component.get("available_phases", [])),
        "trigger": deepcopy(component.get("trigger", {})), "limit": deepcopy(component.get("limit")),
        "event_limit": events.component_limit_view(actor, skill, component, component_index=component_index) if events else None,
        "last_used_turn": state.last_used_turn if state else None,
        "costs": deepcopy(component.get("cost", [])), "inputs": deepcopy(component.get("inputs", [])),
        "effects": effects, "choices": choices,
        "description": "；".join(descriptions),
    }


def skill_view(actor, skill, category):
    components = [component_view(actor, skill, component, index) for index, component in enumerate(skill.definitions)]
    casting = get_casting_config(skill)
    cost = None
    if casting:
        from game.skill.casting import get_casting_mp_cost
        cost = get_casting_mp_cost(actor, skill)
    return {"skill_id": skill.skill_id, "name": skill.name, "rank": skill.rank_name,
            "category": category, "negative": skill.negative_skill,
            "casting": {"activation_mode": casting.get("activation_mode", "release"),
                        "range_type": casting.get("range_type"), "mp_cost": cost} if casting else None,
            "components": components,
            "description": (skill.description or "；".join(component["description"]
                            for component in components if component["description"]))}


def character_state(character):
    from game.status.runtime import iter_status_runtimes, status_view
    skills = []
    for collection, category in (("class_skills", "class_skill"), ("personal_skills", "personal_skill"),
                                 ("magic_skill", "basic_magic"), ("noble_phantasms", "noble_phantasm")):
        skills.extend(skill_view(character, skill, category) for skill in getattr(character, collection, []))
    state = character.casting_state
    casting = None if state is None else {
        "skill_id": state.skill.skill_id, "name": state.skill.name, "layers": state.layers,
        "started_turn": state.started_turn, "continued_turn": state.continued_turn,
        "maximum_layers": max((component.get("casting_requirement", 0)
                               for component in state.skill.definitions), default=0),
        "paid_mp": sum(item["amount"] for item in state.payment_ledger),
        "activation_mode": get_casting_config(state.skill).get("activation_mode", "release"),
    }
    return {
        "status_instances": [status_view(runtime.status_modifier) for runtime in iter_status_runtimes(character)],
        "card_id": getattr(character, "card_id", None),
        "servant_class": getattr(character, "servant_class", None),
        "skills": skills, "casting": casting,
        "attribute_details": {name: {"value": getattr(character, name).value,
                                     "base_value": getattr(character, name).base_value,
                                     "rank": str(getattr(character, name)),
                                     "plus": getattr(character, name).plus,
                                     "plus_capacity": getattr(character, name).plus_capacity}
                              for name in character.ATTRIBUTE_NAMES},
        "combat": {"attack": character.atk, "attack_phase_count": character.attack_phase_count,
                   "movement_point": character.movement_point, "shield": character.shield,
                   "magic_resistance": character.magic_resistance,
                   "luck_reroll": character.luck_reroll, "luck_reroll_max": character.luck_reroll_max,
                   "brink_uses_remaining": character.brink_of_death_counter,
                   **{name: getattr(character, name) for name in ("physical_attack", "magic_attack", "dodge", "block", "offset")}},
        "incoming_attacks": [{"attack_id": attack.attack_id, "damage_type": attack.damage_type,
                              "attack_roll": attack.attack_roll, "channel": attack.resolution_channel}
                             for attack in character.pending_attacks if not attack.resolved],
        "resource_details": [{"resource_id": resource.resource_id, "name": resource.name,
                              "value": resource.current_value, "minimum": resource.minimum, "maximum": resource.maximum}
                             for resource in character.resources.values()],
        "modifiers": [{"modifier_id": modifier.modifier_id, "name": modifier.name,
                       "effect_type": modifier.effect_type, "polarity": modifier.polarity,
                       "description": effect_view(modifier.effect)["description"],
                       "value": getattr(modifier, "remaining_value", modifier.effect_data.get("value")),
                       "duration": modifier.duration, "duration_timing": modifier.duration_timing,
                       "remaining_uses": modifier.remaining_uses, "stack_count": modifier.stack_count,
                       "phase_window_remaining": modifier.phase_window_remaining,
                       "purifiable": modifier.purifiable}
                      for modifier in character.modifiers],
        "skill_sets": [{"group_id": group_id, "current_set": group.get("current"),
                        "sets": [{"set_id": set_id, "active": set_id == group.get("current"),
                                  "skills": [skill_view(character, skill, "personal_skill") for skill in cached]}
                                 for set_id, cached in group.get("sets", {}).items()]}
                       for group_id, group in getattr(character, "switchable_skill_sets", {}).items()],
    }
