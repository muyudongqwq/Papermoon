"""Presentation and lossless linear editing of shared skill conditions."""

from copy import deepcopy

from core.catalog import parse_json
from game.action.action_rules import _BOOLEAN_CONDITIONS, _INTEGER_CONDITIONS, validate_condition
from SkillEditorClient.model import PHASE_LABELS


CONDITION_NAMES = {
    "condition_id": "没有御主", "actor_alive": "角色存活", "actor_type": "角色类型",
    "at_grail_position": "位于圣杯所在地点", "attack_phase_count_at_least": "可用攻击阶段至少为",
    "battle_state": "是否处于战斗中", "carry_capacity_available": "仍可携带乘客",
    "command_spell_at_least": "持有令咒至少为", "cooldown_ready": "指定行动冷却已结束",
    "damage_type": "事件伤害类型", "event_actor": "事件行动者与自身的关系",
    "event_actor_is_self": "事件行动者是否为自身", "event_source": "事件来源与自身的关系",
    "event_source_is_self": "事件来源是否为自身", "event_target": "事件目标与自身的关系",
    "event_target_is_self": "事件目标是否为自身", "event_value_at_least": "事件数值至少为",
    "event_value_at_most": "事件数值至多为", "forbidden_status": "不具有指定状态",
    "grail_ready": "圣杯已经就绪", "in_ride_group": "处于同乘关系中",
    "leader_transfer_available": "本回合仍可转交队长", "missing_hp_at_least": "缺失HP至少为",
    "movement_locked": "移动是否被锁定", "no_command_spell_transfer": "没有正在进行的令咒转移",
    "no_pending_travel_join": "未提交本阶段的同行申请", "not_in_travel_group": "不在同行队伍中",
    "pending_attacks_at_least": "待防御攻击数量至少为", "player_character": "是玩家控制的角色",
    "phase": "事件发生阶段", "position_is_building": "当前地点为建筑",
    "position_required": "角色有地图位置", "release_available": "存在可解放的效果",
    "required_casting": "正在咏唱", "required_status": "具有指定状态",
    "servant_count": "拥有的从者数量等于", "travel_group_leader": "是同行队伍的队长",
}
CONDITION_HELP = {
    "condition_id": "角色当前没有御主。",
    "battle_state": "匹配角色是否处于战斗中；是表示战斗中，否表示战斗外。",
    "event_actor_is_self": "判断事件的行动者是不是技能持有者。",
    "event_source_is_self": "判断事件来源对象是不是技能持有者；来源有时是伤害或行动对象。",
    "event_target_is_self": "判断当前事件的单个目标是不是技能持有者。",
    "event_actor": "筛选事件行动者；己方包含自身，非己方不包含自身。",
    "event_source": "筛选事件来源对象的关系；来源不一定是角色。",
    "event_target": "筛选事件目标；己方包含自身，非己方不包含自身。",
    "event_value_at_least": "事件携带的数值不小于此值；事件没有数值时不满足。",
    "event_value_at_most": "事件携带的数值不大于此值；事件没有数值时不满足。",
    "damage_type": "匹配事件记录的伤害类型。",
    "phase": "匹配事件记录的阶段值；伤害前事件通常使用 damage_resolution。也可手填阶段ID。",
    "required_status": "要求列出的状态全部存在；可选择状态或用逗号分隔多个状态ID。",
    "forbidden_status": "要求列出的状态全部不存在；可选择状态或用逗号分隔多个状态ID。",
    "missing_hp_at_least": "按HP上限减去当前HP计算缺失量。",
    "servant_count": "从者数量必须恰好等于填写的整数。",
    "movement_locked": "匹配角色当前的移动锁定状态。",
    "cooldown_ready": "检查休息或撤退的既有冷却规则。",
}
EQUALITY_BOOLEANS = {"battle_state", "movement_locked", "event_actor_is_self", "event_source_is_self", "event_target_is_self"}
RELATION_LABELS = {"self": "自身", "ally": "己方（含自身）", "enemy": "非己方（不含自身）"}


def value_labels(field):
    if field in _BOOLEAN_CONDITIONS:
        return {"true": "是", "false": "否"} if field in EQUALITY_BOOLEANS else {"true": "要求满足", "false": "不作要求"}
    if field in {"event_actor", "event_source", "event_target"}:
        return RELATION_LABELS
    if field == "damage_type":
        return {"physical": "物理", "magic": "魔术", "true_damage": "真实"}
    if field == "cooldown_ready":
        return {"rest": "休息", "escape": "撤退"}
    if field == "phase":
        return {**PHASE_LABELS, "damage_resolution": "伤害结算（damage_resolution）", "release": "解放（release）"}
    return {}


def condition_help(field):
    if not field:
        return "请选择条件。"
    if field in CONDITION_HELP:
        return CONDITION_HELP[field]
    if field in _BOOLEAN_CONDITIONS:
        return CONDITION_NAMES[field] + "；“不作要求”关闭这项检查，反向判断请使用“非”。"
    if field in _INTEGER_CONDITIONS:
        return CONDITION_NAMES[field] + "所填写的非负整数。"
    return "填写要匹配的角色类型名称，例如 Master、Servant。"


def display_value(field, value):
    if field in _BOOLEAN_CONDITIONS:
        raw = "true" if value else "false"
    elif field in {"required_status", "forbidden_status"}:
        return ", ".join(value)
    else:
        raw = str(value)
    return value_labels(field).get(raw, raw)


def parse_value(field, text):
    if field == "condition_id":
        return "master_is_none"
    labels = value_labels(field)
    text = {label: key for key, label in labels.items()}.get(text, text).strip()
    if field in _BOOLEAN_CONDITIONS:
        if text not in {"true", "false"}:
            raise ValueError("请选择条件是否成立")
        return text == "true"
    if field in {"required_status", "forbidden_status"}:
        values = list(dict.fromkeys(part.strip() for part in text.replace("，", ",").split(",") if part.strip()))
        if not values:
            raise ValueError("请选择至少一个状态")
        return values
    if not text:
        raise ValueError("请填写条件的取值")
    if field in _INTEGER_CONDITIONS or field in {"event_value_at_least", "event_value_at_most"}:
        value = parse_json(text)
    else:
        value = text
    validate_condition({field: value})
    return value


def linear_conditions(condition):
    """Return rows for a left-to-right expression, or None for grouped JSON."""
    def atom(node):
        if isinstance(node, dict) and len(node) == 1 and next(iter(node)) in CONDITION_NAMES:
            field, value = next(iter(node.items()))
            return {"field": field, "value": deepcopy(value), "join": "与", "negated": False}
        return None

    def split(node):
        if not isinstance(node, dict):
            return None
        if not node:
            return []
        if all(key in CONDITION_NAMES for key in node):
            return [atom({key: value}) for key, value in node.items()]
        if set(node) == {"not"}:
            row = atom(node["not"])
            if row is not None:
                row["negated"] = True
                return [row]
            return None
        if len(node) != 1 or next(iter(node)) not in {"all", "any"}:
            return None
        key, children = next(iter(node.items()))
        if not isinstance(children, list) or not children:
            return None
        rows = split(children[0])
        if not rows:
            return None
        for child in children[1:]:
            row = atom(child)
            if row is None and isinstance(child, dict) and set(child) == {"not"}:
                row = atom(child["not"])
                if row is not None:
                    row["join"] = "与" if key == "all" else "或"
                    row["negated"] = True
            elif row is not None:
                row["join"] = "与" if key == "all" else "或"
            if row is None:
                return None
            rows.append(row)
        return rows

    try:
        validate_condition(condition)
    except (ValueError, TypeError):
        return None
    return split(condition)


def combine_conditions(rows):
    if not rows:
        return {}
    nodes = [{row["field"]: deepcopy(row["value"])} for row in rows]
    result = {"not": nodes[0]} if rows[0].get("negated") else nodes[0]
    for row, node in zip(rows[1:], nodes[1:]):
        join = row["join"]
        if join not in {"与", "或"}:
            raise ValueError("请选择“与”或“或”")
        if row.get("negated"):
            node = {"not": node}
        key = "any" if join == "或" else "all"
        if set(result) == {key}:
            result[key].append(node)
        else:
            result = {key: [result, node]}
    validate_condition(result)
    return result
