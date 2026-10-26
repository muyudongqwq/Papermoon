"""Presentation hints for existing engine schemas; no effect execution rules."""

from dataclasses import dataclass

from core.catalog import parse_json
from game.character.familiar import FAMILIAR_TEMPLATE_DATA
from game.modifier.dice_targets import DICE_TARGET_GROUPS
from game.skill.effect_validation import EFFECT_SCHEMAS, EffectSchema
from game.status.data import STATUS_DATA
from game.turn.damage_types import VALID_DAMAGE_TYPES


EFFECT_NAMES = {
    "action_restriction": "行动限制",
    "status_immunity": "弱体无效",
    "choices": "可选发动",
    "hp_floor": "设置生命下限", "prevent_death": "死亡免疫", "add_content": "获得已入库技能",
    "add_simple_round": "追加简易战斗轮", "add_resource": "创建自定义资源",
    "add_action": "增加行动", "add_skill": "增加技能", "add_status": "施加状态",
    "attribute_bonus": "属性增减", "attack_bonus": "基础攻击增减", "cancel_event": "取消事件",
    "change_damage_type": "改变伤害类型", "cost_modifier": "消耗增减",
    "create_attack_event": "生成攻击（可防御）", "create_field": "创建阵地", "damage": "直接伤害",
    "delay_attack": "延迟既有攻击", "delay_effect": "延迟执行效果",
    "damage_modifier": "伤害增减", "defense_flow_modifier": "改变防御流程",
    "deploy_reality_marble": "展开固有结界",
    "dice_bonus": "判定骰值增减", "gain_resource": "增加自定义资源", "grant_temporary_mp": "获得临时MP",
    "growing": "成长型效果", "hidden": "隐蔽", "magic_resistance": "对魔力",
    "modify_event_value": "修改事件数值", "modify_resource": "修改自定义资源",
    "movement_point_bonus": "移动力增减", "carry_capacity": "可携带人数增减",
    "numeric_attribute_bonus": "数值属性增减", "observe_location": "获得地点视野",
    "perception_check": "感知判定", "order_change": "先手顺序调整",
    "plus_bonus": "属性加符增减", "purify": "净化", "recover_resource": "资源回复",
    "remove_content": "移除已入库技能", "remove_skill": "移除技能",
    "redirect_event": "重定向攻击或伤害",
    "restore_component": "恢复技能单元次数或冷却", "shield": "护盾", "summon": "召唤",
    "switch_skill_set": "切换技能组", "trap": "设置陷阱", "visibility_bonus": "视野调整",
    "presence_concealment": "气息遮断",
}
EFFECT_TYPES = tuple(sorted(EFFECT_SCHEMAS))
# choices is an editor-only structural entry mapped to component.choices.
FORM_EFFECT_TYPES = tuple(sorted((*EFFECT_TYPES, "choices")))
CHOICES_SCHEMA = EffectSchema(optional_data=frozenset({"maximum_selections", "allow_duplicate"}))


def editor_effect_schema(effect_type):
    return CHOICES_SCHEMA if effect_type == "choices" else EFFECT_SCHEMAS.get(effect_type)

BOOLEAN_FIELDS = {
    "all_actions",
    "permanent", "remove_with_source", "consume_attack_phase", "enter_battle", "is_ambush",
    "ignore_shield", "ignore_block", "target_lock", "is_hidden", "include_area_levels",
    "remove_on_source_death", "exclusive_center", "apply_once", "battle_bound",
    "remove_on_position_change", "remove_on_battle_entry", "requires_building",
    "withdraw_from_battle", "rejoin_on_expire", "prevent_movement", "allow_other",
    "exclude_source", "activate_immediately", "share_knowledge", "investigation_immunity",
    "active_hide_perception_immunity", "remove_when_revealed", "remove_skill_when_exhausted",
}
NUMBER_FIELDS = {
    "value", "hp", "hp_floor_duration", "duration", "radius", "capture_radius", "initial_value",
    "minimum", "maximum", "multiplier", "flat", "attack_stat_multiplier", "attack_stat_flat",
    "attack_roll_bonus", "damage_value", "damage_multiplier", "damage_flat", "initial_die",
    "attempts", "count", "maximum_active", "base_damage", "usage_amount", "cooldown_turns",
    "delay_turns",
}
STRING_FIELDS = {
    "match_mode",
    "name", "resource", "subject", "anchor", "attacker_rule", "defender_rule", "trigger_target",
    "trigger_phase", "attack_mode", "attack_stat", "damage_type", "resolution_channel",
    "field_type", "center_rule", "duration_timing", "direction", "calculation", "value_source",
    "damage_value_source", "attribute", "damage_attribute", "effect_target", "reason", "rank",
    "scope", "usage_scope", "collection", "skill", "content_type", "duplicate_policy",
    "placement_rule", "limit_scope", "at_limit", "name_prefix", "owner_unique_key",
    "redirect_type", "new_target",
}
FIELD_NAMES = {
    "all_actions": "限制全部行动", "action_ids": "行动ID列表",
    "action_types": "行动类别列表", "skill_ids": "技能ID列表",
    "component_ids": "技能单元ID列表", "phases": "生效阶段列表",
    "phase_scopes": "阶段范围列表", "match_mode": "匹配方式",
    "exclude_action_ids": "排除的行动ID", "exclude_skill_ids": "排除的技能ID",
    "tags": "匹配状态标签",
    "cost": "维持消耗",
    "maximum_selections": "每次最多选择几项", "allow_duplicate": "允许同一次发动重复选择同一分支",
    "resolution_channel": "解放或一般攻击",
    "value": "数值", "value_source": "数值来源", "damage_type": "伤害类型",
    "damage_types": "适用伤害类型", "resource_id": "资源名称", "status_id": "状态ID",
    "multiplier": "倍率", "flat": "额外数值",
    "calculation": "计算方式", "direction": "生效方向", "effect_target": "调整的属性",
    "attribute": "来源属性", "ignore_shield": "忽略护盾", "ignore_block": "忽略格挡减伤",
    "maximum": "数量上限", "duration": "持续回合", "template_id": "召唤模板",
    "count": "数量", "damage_value": "伤害数值", "attack_stat": "攻击判定属性",
    "rank": "等级", "scope": "范围", "name": "名称",
    "delay_turns": "延迟同名阶段数", "effects": "到期执行的效果列表",
    "steps": "有序防御步骤",
}


@dataclass(frozen=True)
class ParameterSpec:
    kind: str = "json"
    choices: tuple = ()
    choice_labels: tuple = ()


def parameter_options(effect_type):
    schema = editor_effect_schema(effect_type)
    if schema is None:
        return ()
    return (*sorted(schema.required_data), *sorted(schema.optional_data))


def parameter_spec(effect_type, field, catalogs=None):
    if effect_type == "status_immunity" and field == "tags":
        tags = {tag for status in (catalogs or {}).get("status", {}).values() for tag in status.get("tags", [])}
        return ParameterSpec("tags", tuple(sorted(tags)))
    if effect_type == "choices":
        return ParameterSpec("json", ("true", "false") if field == "allow_duplicate" else ())
    if effect_type == "dice_bonus" and field == "effect_target":
        choices = (*DICE_TARGET_GROUPS, "physical_attack", "magic_attack", "dodge", "block", "offset", "hide", "perceive", "escape", "dice_bonus")
        return ParameterSpec("string", choices, (("attack", "攻击骰（物理与魔术）"), ("defense", "防御骰（闪避、格挡、抵消）")))
    if field in BOOLEAN_FIELDS:
        return ParameterSpec("json", ("true", "false"))
    if field == "status_id":
        statuses = STATUS_DATA if catalogs is None else catalogs["status"]
        return ParameterSpec("string", tuple(sorted(statuses)))
    if field == "template_id":
        return ParameterSpec("string", tuple(sorted(FAMILIAR_TEMPLATE_DATA)))
    if field == "damage_type":
        return ParameterSpec("string", tuple(sorted(VALID_DAMAGE_TYPES)))
    choices = {
        "match_mode": ("any", "all"),
        "content_type": ("personal_skill", "basic_magic", "noble_phantasm"),
        "resolution_channel": ("attack", "release"),
        "direction": ("incoming", "outgoing"),
        "field_type": ("workshop", "territory", "bounded_field"),
        "center_rule": ("actor_position",), "subject": ("actor", "target"),
        "anchor": ("actor", "target"), "attacker_rule": ("actor", "target"),
        "defender_rule": ("actor", "target", "all_targets"),
        "trigger_target": ("actor", "target", "first_defender"),
        "trigger_phase": ("immediate", "battle_start", "turn_start", "guard", "defense", "attack", "turn_end"),
        "attack_mode": ("fixed", "select"), "duration_timing": ("global_turn_end",),
        "placement_rule": ("current_position", "target_position"),
        "limit_scope": ("template", "skill", "summoner"),
        "at_limit": ("reject", "replace_oldest", "select"),
        "usage_scope": ("global_turn", "battle", "game"),
        "collection": ("personal_skills",), "skill": ("self",),
        "redirect_type": ("attack", "damage"),
        "new_target": (
            "self", "event_actor", "event_source", "event_target",
            "selected_target",
        ),
    }.get(field, ())
    if field == "calculation":
        choices = {
            "order_change": ("move_first", "move_last", "move_before", "move_after"),
            "modify_resource": ("add", "subtract", "multiply", "divide", "set"),
            "modify_event_value": ("add", "multiply", "set"),
            "growing": ("add", "subtract", "set"),
            "cost_modifier": ("multiplier", "flat", "override"),
            "damage_modifier": ("percentage", "flat"),
            "defense_flow_modifier": ("append", "prepend", "replace"),
            "recover_resource": ("flat", "maximum_percentage", "maximum_ratio"),
        }.get(effect_type, ())
    elif field == "duplicate_policy":
        choices = ("reject", "replace") if effect_type == "add_action" else ("reject",)
    elif field == "rank" and effect_type == "presence_concealment":
        choices = ("C", "B", "A", "EX")
    elif field == "scope" and effect_type == "perception_check":
        choices = ("current_area", "source_field")
    elif field == "value_source":
        choices = {
            "grant_temporary_mp": ("event_value", "status_stack_count"),
            "recover_resource": ("actual_mp_cost", "event_value", "status_stack_count"),
        }.get(effect_type, ("actor_attribute", "target_attribute", "event_value", "actual_mp_cost", "status_stack_count"))
    elif field == "damage_value_source":
        choices = ("actor_attribute", "target_attribute")
    if choices:
        return ParameterSpec("string", choices)
    if field == "value" and effect_type == "hidden":
        return ParameterSpec("string")
    if field in {"maximum", "usage_amount", "cooldown_turns"} and effect_type in {"purify", "restore_component"}:
        return ParameterSpec("number_or_all", ("1", "all"))
    if field in NUMBER_FIELDS:
        return ParameterSpec("json")
    if field in STRING_FIELDS or field.endswith("_id"):
        return ParameterSpec("string")
    return ParameterSpec()


def parse_parameter(text, spec):
    if spec.kind == "tags":
        if text.strip().startswith("["):
            value = parse_json(text)
            if not isinstance(value, list) or any(not isinstance(tag, str) or not tag.strip() for tag in value):
                raise ValueError("标签必须是非空文本组成的列表")
            return value
        return list(dict.fromkeys(tag.strip() for tag in text.replace("，", ",").split(",") if tag.strip()))
    if spec.kind == "string":
        return text
    if spec.kind == "number_or_all" and text.strip() == "all":
        return "all"
    try:
        return parse_json(text)
    except (ValueError, TypeError) as error:
        raise ValueError("请填写数字、true/false、null或合法JSON；文本参数可直接填写") from error
