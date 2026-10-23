"""Strict status schemas; reference checking never recursively expands statuses."""

from copy import deepcopy
import re

from game.status.data import STATUS_DATA


STATUS_FIELDS = {"status_id", "name", "description", "polarity", "purifiable", "duration",
                 "duration_timing", "persist_after_death", "stacking", "components"}


def get_status_definition(status_id):
    if not isinstance(status_id, str) or status_id not in STATUS_DATA:
        raise ValueError(f"未知的状态status_id：{status_id}")
    return deepcopy(STATUS_DATA[status_id])


def validate_status_definition(definition):
    from game.modifier.modifier import MODIFIER_TYPES
    from game.skill.effect_validation import _validate_modifier_common
    from game.skill.skill_runtime import validate_skill_components

    if not isinstance(definition, dict):
        raise ValueError("状态定义必须是对象")
    required = {"status_id", "name", "components"}
    if required - definition.keys() or definition.keys() - STATUS_FIELDS:
        raise ValueError("状态定义字段错误；必须包含status_id、name和components")
    status_id = definition["status_id"]
    if not isinstance(status_id, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", status_id):
        raise ValueError("status_id必须以小写字母开头，只含小写字母、数字及下划线")
    if not isinstance(definition["name"], str) or not definition["name"].strip():
        raise ValueError("状态name必须是非空字符串")
    if "description" in definition and not isinstance(definition["description"], str):
        raise ValueError("状态description必须是字符串")
    _validate_modifier_common(definition, f"status[{status_id}]")
    if definition.get("duration_timing", "global_turn_end") != "global_turn_end":
        raise ValueError("状态持续时间统一按global_turn_end扣减")
    components = definition["components"]
    if not isinstance(components, list):
        raise ValueError("状态components必须是列表")
    if components:
        validate_skill_components(components, path=f"status[{status_id}]", label="状态")
    for component in components:
        allowed = {"component_id", "name", "type", "target", "trigger", "condition", "effects"}
        if component.keys() - allowed:
            raise ValueError("状态组件只接受component_id、name、type、target、trigger、condition和effects；次数由状态运行层统一管理")
        kind = component["type"]
        if kind not in {"passive", "trigger", "react"}:
            raise ValueError("状态只支持passive、trigger和react组件")
        if component.get("target", "self") not in {"self", "event_actor", "event_source", "event_target", "event_targets"}:
            raise ValueError("状态target必须是self或事件目标选择器")
        trigger = component.get("trigger", {})
        if trigger.keys() - {"event_type", "timing", "priority"}:
            raise ValueError("状态trigger只接受event_type、timing和priority")
        if trigger.get("timing", "after") not in {"before", "after"}:
            raise ValueError("状态trigger.timing必须是before或after")
        if kind == "passive":
            if component.get("target", "self") != "self" or component.get("condition") or trigger:
                raise ValueError("状态passive只能无条件作用于self；效果条件请使用conditions")
            for effect in component["effects"]:
                if effect["effect_type"] not in MODIFIER_TYPES or effect["effect_type"] == "hidden":
                    raise ValueError("状态passive只支持持续数值修正；即时效果请使用trigger或react")
                if set(effect) & {"duration", "duration_timing", "phase_window", "stacking", "consumption", "persist_after_death", "purifiable"}:
                    raise ValueError("状态passive的生命周期、净化和叠层统一由外层状态管理")
    return True


def validate_status_catalog():
    for key, definition in STATUS_DATA.items():
        if definition.get("status_id") != key:
            raise ValueError(f"状态目录ID与status_id不一致：{key}")
        validate_status_definition(definition)
    return list(STATUS_DATA)
