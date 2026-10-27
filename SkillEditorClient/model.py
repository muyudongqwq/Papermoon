"""Small, lossless conversions between form fields and canonical skill data."""

from copy import deepcopy
from numbers import Real

from core.catalog import parse_json
from game.action.action_data import ACTION_PHASES, TARGET_TYPES
from game.rank.rank import SkillRank
from game.skill.input_runtime import validate_input_expression
from SkillEditorClient.editor_documents import new_definition


PHASES = tuple(p for p in (
    "AP1", "AP2", "battle_start", "turn_start", "guard_phase", "defense_phase",
    "attack_phase", "turn_end", "battle_end", "simple_round_attack", "simple_round_guard",
    "simple_round_defense") if p in ACTION_PHASES)
# Change the values to edit checkbox captions; keep the engine IDs on the left.
PHASE_LABELS = {
    "AP1": "AP1",
    "AP2": "AP2",
    "battle_start": "战斗开始时",
    "turn_start": "回合开始时",
    "guard_phase": "援护阶段",
    "defense_phase": "防御阶段",
    "attack_phase": "攻击阶段",
    "turn_end": "回合结束",
    "battle_end": "战斗结束",
    "simple_round_attack": "简易战斗攻击阶段",
    "simple_round_guard": "简易战斗援护阶段",
    "simple_round_defense": "简易战斗防御阶段",
}
TARGETS = tuple(sorted(TARGET_TYPES))
TYPES = ("active", "passive", "trigger", "react")
RANKS = tuple(rank for rank in ("E", "D", "C", "B", "A", "EX") if rank in SkillRank.valid_rank)
FORM_CATEGORIES = {"personal_skill", "basic_magic", "noble_phantasm"}
TYPE_DESCRIPTIONS = {
    "active": "在选定的可用阶段，由玩家主动选择发动。",
    "passive": "技能装载后自动生效，适用于常驻效果。",
    "react": "指定事件发生且条件满足时，由玩家选择是否发动。",
    "trigger": "指定事件发生且条件满足时，自动触发并结算。",
}
TARGET_DESCRIPTIONS = {
    "none": "不需要选择外部目标，通常由发动者自身承载效果。",
    "self": "以发动技能的角色自身为目标。",
    "current_position": "以发动者当前所在的地图节点为目标。",
    "selectable_character": "选择符合目标规则的角色，敌我、距离和视野限制由具体规则决定。",
    "selectable_enemy": "选择可攻击的角色，实际候选受关系、距离和目标规则限制。",
    "selectable_ally": "从自身或盟友中选择符合条件的目标。",
    "selectable_map_node": "选择符合规则的地图节点。",
    "selectable_port": "选择除当前位置以外的码头。",
    "selectable_path": "选择符合规则的移动路径。",
    "selectable_battle_participant": "从当前战斗的正式参战角色中选择目标。",
    "guardable_battle_participant": "选择当前可以被援护的战斗参与者。",
    "characters_within_distance": "以指定距离内、符合规则的角色为目标。",
    "incoming_attacks": "以当前待处理的攻击为目标。",
    "delayed_attacks": "选择自己延迟、由自己发动或以自己为目标的延迟攻击。",
    "selectable_attribute": "选择一项属性供效果使用，具体允许选择哪些属性由目标规则决定。",
    "selectable_travel_group": "选择符合条件的同行队伍。",
    "travel_group_members": "以同行队伍中的成员为目标。",
    "selectable_command_spell_recipient": "选择符合令咒转移条件的接收者。",
    "carry_candidate": "选择符合携带条件的角色。",
    "event_actor": "以触发事件的行动者为目标。",
    "event_source": "以触发事件的来源为目标。",
    "event_target": "以触发事件的单个目标为目标。",
    "event_targets": "以触发事件的目标列表为目标。",
}


def can_use_form(definition):
    """Malformed imports remain repairable in the original JSON editor."""
    if not isinstance(definition.get("skill_id"), str) or not isinstance(definition.get("components"), list):
        return False
    if "cost" in definition:
        return False
    for field in ("name", "rank", "description"):
        if field in definition and not isinstance(definition[field], str):
            return False
    for component in definition["components"]:
        if not isinstance(component, dict):
            return False
        if not isinstance(component.get("component_id"), str) or not component["component_id"].strip():
            return False
        for field in ("component_id", "type", "target"):
            if field in component and not isinstance(component[field], str):
                return False
        if "casting_requirement" in component and (type(component["casting_requirement"]) is not int or component["casting_requirement"] < 0):
            return False
        phases = component.get("available_phases", [])
        if not isinstance(phases, list) or not all(isinstance(phase, str) for phase in phases):
            return False
        for field in ("cost", "effects"):
            values = component.get(field, [])
            if not isinstance(values, list) or not all(isinstance(value, dict) for value in values):
                return False
        if "choices" in component:
            choices = component["choices"]
            if not isinstance(choices, dict) or not isinstance(choices.get("options", []), list):
                return False
            if "allow_duplicate" in choices and not isinstance(choices["allow_duplicate"], bool):
                return False
            for option in choices.get("options", []):
                if not isinstance(option, dict) or not isinstance(option.get("choice_id"), str) or not option["choice_id"].strip():
                    return False
                if "name" in option and not isinstance(option["name"], str):
                    return False
                for field in ("effects", "cost"):
                    values = option.get(field, [])
                    if not isinstance(values, list) or not all(isinstance(value, dict) for value in values):
                        return False
        if "trigger" in component and not isinstance(component["trigger"], dict):
            return False
    return True


def resource_options(phases):
    values = ["mp", "hp", "attack_phase_count", "command_spell", "luck_reroll"]
    if {"AP1", "AP2"}.intersection(phases):
        values.insert(2, "action_point")
    return tuple(values)


def new_skill_key(name, rank, existing):
    """Generate a readable, stable catalog ID without asking the GM for code."""
    base = f"user_{name.strip()}_{rank.strip()}"
    key, suffix = base, 2
    while key in existing:
        key = f"{base}_{suffix}"
        suffix += 1
    return key


def new_personal_skill_key(existing):
    """Reserve IDs 0-9 and append after the highest existing numeric ID."""
    numbers = [int(key) for key in existing if isinstance(key, str) and key.isascii() and key.isdecimal()]
    return str(max([9, *numbers]) + 1)


def new_client_definition(kind, key, *, name=None, rank=None):
    result = new_definition(kind, key)
    if kind in {"固有技能", "基础魔术", "宝具"}:
        result.update(components=[], description="")
        if name is not None:
            result["name"] = name
        if rank is not None:
            result["rank"] = rank
    return result


def object_value(text, label):
    try:
        value = parse_json(text)
    except (ValueError, TypeError) as error:
        raise ValueError(f"{label}的JSON格式有误：{error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label}必须是JSON对象（用花括号包围）")
    return value


def merge_extras(text, controlled, label):
    result = object_value(text, label)
    conflicts = result.keys() & set(controlled)
    if conflicts:
        raise ValueError(f"{label}中的{', '.join(sorted(conflicts))}请使用上方表单填写")
    return deepcopy(result)


def cost_value(text):
    try:
        value = parse_json(text.strip())
    except ValueError as error:
        raise ValueError("消耗值请填写数字，例如10；高级输入表达式需使用JSON对象") from error
    if isinstance(value, dict):
        validate_input_expression(value, path="消耗值")
        return value
    if isinstance(value, bool) or not isinstance(value, Real) or value < 0:
        raise ValueError("消耗值必须是大于或等于0的数字")
    return value


def validate_component_fields(component):
    from game.skill.casting import component_casting_requirement
    requirement = component_casting_requirement(component)
    if not component["component_id"].strip():
        raise ValueError("请填写component_id，每个技能单元需要一个不重复的标识")
    if component["type"] not in TYPES:
        raise ValueError("请选择合法的技能单元type")
    phases = component.get("available_phases", [])
    if set(phases) - ACTION_PHASES:
        raise ValueError("available_phases包含不支持的阶段")
    if component["type"] == "active" and not requirement and "available_phases" in component and not phases:
        raise ValueError("主动技能单元请至少选择一个available_phases阶段")
    targets = set(TARGETS) | {"event_actor", "event_source", "event_target", "event_targets"}
    if component.get("target", "self") not in targets:
        raise ValueError("请选择合法的target")
    validate_cost_fields(component.get("cost", []), phases)
    return component


def validate_cost_fields(costs, phases):
    for cost in costs:
        if not cost["resource"].strip():
            raise ValueError("请选择消耗resource；action_point仅可用于包含AP1或AP2的技能单元")
        if cost["resource"] == "action_point" and not {"AP1", "AP2"}.intersection(phases):
            raise ValueError("不包含AP1或AP2时不能使用action_point消耗")


def optional_field(result, original, key, value, default):
    if key in original or value != default:
        result[key] = value
