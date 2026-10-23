"""Strict structural validation for executable skill effects.

Action effects belong to ``action.action_resolver`` and intentionally use a
different vocabulary.  This module validates only effects executed through
``skill.skill_runtime.apply_skill_effect``.
"""

from copy import deepcopy
from dataclasses import dataclass
from numbers import Real

from game.action.action_data import (
    ACTION_PHASES,
    ACTION_TYPE_CATEGORIES,
    RESOLUTION_TIMINGS,
    TARGET_TYPES,
)
from game.action.action_rules import validate_condition, validate_target_rules
from game.modifier.modifier import Modifier
from game.modifier.modifier_manager import ModifierManager
from game.resource.resource import VALID_RESOURCE_OPERATIONS
from game.skill.field_runtime import APPLICATION_MODES, FIELD_TYPES
from game.skill.component_runtime import COOLDOWN_UNITS, USAGE_LIMIT_SCOPES
from game.skill.input_runtime import (
    is_input_expression,
    validate_component_inputs,
    validate_input_expression,
)
from game.turn.damage_types import VALID_DAMAGE_TYPES


@dataclass(frozen=True)
class EffectSchema:
    required_data: frozenset = frozenset()
    optional_data: frozenset = frozenset()
    modifier: bool = False

    @property
    def allowed_data(self):
        return self.required_data | self.optional_data


def _schema(*, required=(), optional=(), modifier=False):
    return EffectSchema(frozenset(required), frozenset(optional), modifier)


_DAMAGE_VALUE_FIELDS = {
    "value",
    "value_source",
    "attribute",
    "multiplier",
    "flat",
}
_DAMAGE_EVENT_FIELDS = {
    "percentage_modifiers",
    "flat_modifiers",
    "action_id",
    "skill_id",
    "source_tags",
    "ignore_shield",
    "target_lock",
}


EFFECT_SCHEMAS = {
    "hp_floor": _schema(required={"value"}, modifier=True),
    "prevent_death": _schema(optional={"hp", "hp_floor_duration", "remove_skill_when_exhausted"}),
    "add_content": _schema(
        required={"content_type", "content_id"},
        optional={"permanent", "remove_with_source"},
    ),
    "add_simple_round": _schema(
        optional={
            "attacker_rule", "defender_rule", "trigger_phase",
            "trigger_target", "attack_mode", "consume_attack_phase",
            "enter_battle", "is_ambush", "attack_stat",
            "attack_roll_bonus", "damage_value", "damage_type",
            "damage_percentage_modifiers", "damage_flat_modifiers",
            "damage_value_source", "damage_attribute",
            "damage_multiplier", "damage_flat", "resolution_channel",
        },
    ),
    "add_resource": _schema(
        required={"resource_id"},
        optional={
            "name", "initial_value", "minimum", "maximum", "gain_rules",
            "reset",
        },
    ),
    "add_action": _schema(
        required={"action_definition"},
        optional={
            "duration", "duration_timing", "duplicate_policy",
            "remove_with_source",
        },
    ),
    "add_skill": _schema(
        optional={
            "skill_definition", "skill_ref", "collection",
            "duplicate_policy", "remove_with_source",
        },
    ),
    "add_status": _schema(required={"status_id"}, modifier=True),
    "attribute_bonus": _schema(
        required={"effect_target", "value"}, modifier=True,
    ),
    "attack_bonus": _schema(required={"value"}, modifier=True),
    "cancel_event": _schema(optional={"reason"}),
    "change_damage_type": _schema(required={"damage_type"}),
    "cost_modifier": _schema(
        required={"resource", "calculation", "value"},
        optional={"cost_id"},
        modifier=True,
    ),
    "create_attack_event": _schema(
        optional={
            "attack_stat", "attack_stat_multiplier", "attack_stat_flat",
            "attack_roll_bonus", "initial_die", "damage_type",
            "damage_value", "damage_segments", "resolution_channel",
            "ignore_block",
        } | _DAMAGE_VALUE_FIELDS | _DAMAGE_EVENT_FIELDS,
    ),
    "create_field": _schema(
        required={"field_id"},
        optional={
            "name", "field_type", "center", "center_rule", "radius", "duration",
            "include_area_levels", "remove_on_source_death",
            "remove_with_source",
            "exclusive_center", "owner_unique_key", "owner_vision",
            "center_target", "requirements", "maintenance",
            "selected_targets", "effects", "apply_once",
            "battle_bound", "exit_penalty",
        },
    ),
    "damage": _schema(
        required={"damage_type"},
        optional=_DAMAGE_VALUE_FIELDS | _DAMAGE_EVENT_FIELDS | {"is_hidden"},
    ),
    "damage_modifier": _schema(
        required={"direction", "calculation", "value"},
        optional={"damage_types", "action_ids", "skill_ids", "source_tags"},
        modifier=True,
    ),
    "deploy_reality_marble": _schema(
        required={"reality_marble_id"},
        optional={
            "name", "entrance", "capture_radius", "duration", "maintenance",
            "selected_targets", "interior", "remove_with_source",
        },
    ),
    "dice_bonus": _schema(
        required={"effect_target", "value"}, modifier=True,
    ),
    "gain_resource": _schema(
        required={"resource_id", "value"},
    ),
    "grant_temporary_mp": _schema(
        optional={"value", "value_source", "multiplier", "flat"},
    ),
    "growing": _schema(
        required={"growth_id", "value", "stages"},
        optional={"calculation", "initial_value", "minimum", "maximum"},
    ),
    "hidden": _schema(
        required={"value"},
        optional={
            "remove_on_position_change", "remove_on_battle_entry",
            "requires_building", "withdraw_from_battle",
            "rejoin_on_expire", "prevent_movement",
        },
        modifier=True,
    ),
    "magic_resistance": _schema(required={"value"}, modifier=True),
    "modify_event_value": _schema(
        optional={"calculation", "value", "minimum", "maximum"},
    ),
    "modify_resource": _schema(
        required={"resource_id", "value"}, optional={"calculation"},
    ),
    "movement_point_bonus": _schema(required={"value"}, modifier=True),
    "carry_capacity": _schema(required={"value"}, modifier=True),
    "numeric_attribute_bonus": _schema(
        required={"effect_target", "value"}, modifier=True,
    ),
    "observe_location": _schema(),
    "perception_check": _schema(
        optional={"scope", "attempts"},
    ),
    "order_change": _schema(
        required={"calculation", "duration"}, optional={"subject", "anchor"},
    ),
    "plus_bonus": _schema(
        required={"effect_target", "value"}, modifier=True,
    ),
    "purify": _schema(optional={"maximum"}),
    "recover_resource": _schema(
        required={"resource_id"},
        optional={"value", "value_source", "calculation"},
    ),
    "remove_content": _schema(
        required={"content_type", "content_id"},
        optional={"permanent"},
    ),
    "remove_skill": _schema(
        optional={"skill", "skill_id", "collection"},
    ),
    "restore_component": _schema(
        optional={
            "usage_amount", "cooldown_turns", "usage_scope", "maximum",
            "allow_other", "exclude_source", "skill_ids", "component_ids",
        },
    ),
    "shield": _schema(
        required={"value"}, optional={"damage_types"}, modifier=True,
    ),
    "summon": _schema(
        required={"template_id"},
        optional={
            "count", "placement_rule", "duration", "maximum_active",
            "limit_scope", "at_limit", "activate_immediately",
            "remove_with_source", "name_prefix",
        },
    ),
    "switch_skill_set": _schema(
        required={"group_id", "set_id", "skill_ids"},
    ),
    "trap": _schema(
        optional={"trap_id", "base_damage", "share_knowledge"},
    ),
    "visibility_bonus": _schema(required={"value"}, modifier=True),
    "presence_concealment": _schema(
        required={"rank", "value"},
        optional={
            "investigation_immunity",
            "active_hide_perception_immunity",
            "remove_when_revealed",
        },
        modifier=True,
    ),
}


IMPLEMENTED_EFFECT_TYPES = frozenset(EFFECT_SCHEMAS)
MODIFIER_EFFECT_TYPES = frozenset(
    effect_type
    for effect_type, schema in EFFECT_SCHEMAS.items()
    if schema.modifier
)


_IMMEDIATE_TOP_LEVEL_FIELDS = {
    "effect_type", "effect_data", "effect_target", "metadata",
}
_MODIFIER_TOP_LEVEL_FIELDS = _IMMEDIATE_TOP_LEVEL_FIELDS | {
    "modifier_id",
    "name",
    "polarity",
    "purifiable",
    "duration",
    "duration_timing",
    "phase_window",
    "persist_after_death",
    "stacking",
    "conditions",
    "application_scope",
    "consumption",
    "strength_priority",
}
_FIELD_WRAPPER_FIELDS = {"application_mode", "effect_target"}


def _error(path, message, error_type=ValueError):
    raise error_type(f"{path}：{message}")


def _mapping(value, path):
    if not isinstance(value, dict):
        _error(path, "必须是字典", TypeError)
    return value


def _list(value, path, *, nonempty=False):
    if not isinstance(value, (list, tuple)):
        _error(path, "必须是列表", TypeError)
    if nonempty and not value:
        _error(path, "不能为空")
    return value


def _keys(value, path, *, allowed, required=()):
    _mapping(value, path)
    unknown = set(value) - set(allowed)
    if unknown:
        _error(path, f"包含未知字段：{sorted(unknown)}")
    missing = set(required) - set(value)
    if missing:
        _error(path, f"缺少字段：{sorted(missing)}")


def _string(value, path, *, allow_none=False):
    if allow_none and value is None:
        return
    if not isinstance(value, str) or not value.strip():
        _error(path, "必须是非空字符串", TypeError)


def _boolean(value, path):
    if not isinstance(value, bool):
        _error(path, "必须是布尔值", TypeError)


def _number(value, path, *, minimum=None, positive=False):
    if is_input_expression(value):
        validate_input_expression(value, path=path)
        return
    if isinstance(value, bool) or not isinstance(value, Real):
        _error(path, "必须是数字", TypeError)
    if positive and value <= 0:
        _error(path, "必须大于0")
    if minimum is not None and value < minimum:
        _error(path, f"不能小于{minimum}")


def _integer(value, path, *, minimum=None, positive=False):
    if isinstance(value, bool) or not isinstance(value, int):
        _error(path, "必须是整数", TypeError)
    if positive and value <= 0:
        _error(path, "必须是正整数")
    if minimum is not None and value < minimum:
        _error(path, f"不能小于{minimum}")


def _enum(value, path, allowed):
    try:
        valid = value in allowed
    except TypeError:
        valid = False
    if not valid:
        _error(path, f"必须是以下值之一：{sorted(allowed)}")


def _string_list(value, path, *, nonempty=False):
    for index, item in enumerate(_list(value, path, nonempty=nonempty)):
        _string(item, f"{path}[{index}]")


def _number_list(value, path, *, nonempty=False):
    for index, item in enumerate(_list(value, path, nonempty=nonempty)):
        _number(item, f"{path}[{index}]")


def _validate_damage_type(value, path, *, allow_all=False):
    allowed = set(VALID_DAMAGE_TYPES)
    if allow_all:
        allowed.add("all")
    _enum(value, path, allowed)


def _validate_damage_types(value, path):
    items = _list(value, path, nonempty=True)
    for index, item in enumerate(items):
        _validate_damage_type(item, f"{path}[{index}]", allow_all=True)


def _validate_value_source(data, path, *, required=False):
    has_value = "value" in data
    has_source = "value_source" in data
    if required and not (has_value or has_source):
        _error(path, "必须提供value或value_source")
    if has_value and has_source:
        _error(path, "value与value_source不能同时提供")
    if has_value:
        _number(data["value"], f"{path}.value")
    if has_source:
        _string(data["value_source"], f"{path}.value_source")
        if data["value_source"] in {"actor_attribute", "target_attribute"}:
            if "attribute" not in data:
                _error(path, "属性数值来源必须同时提供attribute")
            _string(data["attribute"], f"{path}.attribute")
        elif "attribute" in data:
            _error(f"{path}.attribute", "只用于属性数值来源")
    elif "attribute" in data:
        _error(f"{path}.attribute", "必须与value_source同时提供")


def _validate_resource_definition(data, path):
    _string(data["resource_id"], f"{path}.resource_id")
    if "name" in data:
        _string(data["name"], f"{path}.name")
    for field in ("initial_value", "minimum"):
        if field in data:
            _number(data[field], f"{path}.{field}")
    if data.get("maximum") is not None:
        _number(data["maximum"], f"{path}.maximum")
        minimum = data.get("minimum", 0)
        if (
            not is_input_expression(data["maximum"])
            and not is_input_expression(minimum)
            and data["maximum"] < minimum
        ):
            _error(f"{path}.maximum", "不能小于minimum")
    if "gain_rules" in data:
        _list(data["gain_rules"], f"{path}.gain_rules")
    for index, rule in enumerate(data.get("gain_rules", [])):
        rule_path = f"{path}.gain_rules[{index}]"
        _keys(
            rule,
            rule_path,
            allowed={
                "trigger_event", "calculation", "value", "value_source",
                "condition",
            },
            required={"trigger_event"},
        )
        _string(rule["trigger_event"], f"{rule_path}.trigger_event")
        calculation = rule.get("calculation", "add")
        _enum(calculation, f"{rule_path}.calculation", VALID_RESOURCE_OPERATIONS)
        if "value" not in rule and "value_source" not in rule:
            _error(rule_path, "必须提供value或value_source")
        if "value" in rule and "value_source" in rule:
            _error(rule_path, "value与value_source不能同时提供")
        if "value" in rule:
            _number(rule["value"], f"{rule_path}.value")
        if "value_source" in rule:
            _string(rule["value_source"], f"{rule_path}.value_source")
        if "condition" in rule:
            _mapping(rule["condition"], f"{rule_path}.condition")
    if "reset" in data and data["reset"] is not None:
        reset_path = f"{path}.reset"
        _keys(
            data["reset"], reset_path,
            allowed={"timing", "value"}, required={"timing"},
        )
        _string(data["reset"]["timing"], f"{reset_path}.timing")
        if "value" in data["reset"]:
            value = data["reset"]["value"]
            if value != "initial_value":
                _number(value, f"{reset_path}.value")


def _validate_stacking(stacking, path):
    allowed = {
        "stack_group", "stack_scope", "stacking_rule", "max_stacks",
        "stack_count", "duration_refresh_rule", "at_max_stacks_rule",
        "strength_comparison", "strength_priority", "priority",
    }
    _keys(stacking, path, allowed=allowed)
    if "stack_group" in stacking:
        _string(stacking["stack_group"], f"{path}.stack_group")
    if "stack_scope" in stacking:
        _enum(
            stacking["stack_scope"], f"{path}.stack_scope",
            ModifierManager.VALID_STACK_SCOPES,
        )
    if "stacking_rule" in stacking:
        _enum(
            stacking["stacking_rule"], f"{path}.stacking_rule",
            ModifierManager.VALID_STACKING_RULES,
        )
    for field in ("max_stacks", "stack_count"):
        if field in stacking:
            _integer(stacking[field], f"{path}.{field}", positive=True)
    if (
        "max_stacks" in stacking
        and "stack_count" in stacking
        and stacking["stack_count"] > stacking["max_stacks"]
    ):
        _error(path, "stack_count不能大于max_stacks")
    if "duration_refresh_rule" in stacking:
        _enum(
            stacking["duration_refresh_rule"],
            f"{path}.duration_refresh_rule",
            ModifierManager.VALID_DURATION_REFRESH_RULES,
        )
    if "at_max_stacks_rule" in stacking:
        _enum(
            stacking["at_max_stacks_rule"],
            f"{path}.at_max_stacks_rule",
            ModifierManager.VALID_AT_MAX_STACKS_RULES,
        )
    if "strength_comparison" in stacking:
        _enum(
            stacking["strength_comparison"],
            f"{path}.strength_comparison",
            ModifierManager.VALID_STRENGTH_COMPARISONS,
        )
    for field in ("strength_priority", "priority"):
        if field in stacking and stacking[field] is not None:
            _number(stacking[field], f"{path}.{field}")
    if stacking.get("stacking_rule") == "strongest":
        if "strength_comparison" not in stacking:
            _error(path, "strongest规则必须提供strength_comparison")


def _validate_modifier_common(effect, path):
    if "modifier_id" in effect:
        _string(effect["modifier_id"], f"{path}.modifier_id")
    if "name" in effect:
        _string(effect["name"], f"{path}.name")
    if "polarity" in effect:
        _enum(effect["polarity"], f"{path}.polarity", Modifier.VALID_POLARITIES)
    for field in ("purifiable", "persist_after_death"):
        if field in effect:
            _boolean(effect[field], f"{path}.{field}")
    if "duration" in effect and effect["duration"] is not None:
        _integer(effect["duration"], f"{path}.duration", positive=True)
    if "duration_timing" in effect:
        _string(effect["duration_timing"], f"{path}.duration_timing")
    if "strength_priority" in effect and effect["strength_priority"] is not None:
        _number(effect["strength_priority"], f"{path}.strength_priority")
    if "stacking" in effect:
        _validate_stacking(effect["stacking"], f"{path}.stacking")

    if "phase_window" in effect:
        if effect.get("duration") is not None:
            _error(path, "duration与phase_window不能同时提供")
        window_path = f"{path}.phase_window"
        window = effect["phase_window"]
        _keys(
            window,
            window_path,
            allowed={"scope", "phase", "boundary", "owner", "occurrences"},
            required={"phase"},
        )
        _enum(
            window.get("scope", "formal_battle"), f"{window_path}.scope",
            Modifier.VALID_PHASE_WINDOW_SCOPES,
        )
        phase = Modifier.PHASE_WINDOW_PHASE_ALIASES.get(
            window["phase"], window["phase"],
        )
        _enum(phase, f"{window_path}.phase", Modifier.VALID_PHASE_WINDOW_PHASES)
        _enum(
            window.get("boundary", "phase_end"),
            f"{window_path}.boundary", Modifier.VALID_PHASE_WINDOW_BOUNDARIES,
        )
        _enum(
            window.get("owner", "target"), f"{window_path}.owner",
            Modifier.VALID_PHASE_WINDOW_OWNERS,
        )
        if "occurrences" in window:
            _integer(
                window["occurrences"], f"{window_path}.occurrences",
                positive=True,
            )

    conditions = effect.get("conditions")
    if conditions is not None:
        conditions_path = f"{path}.conditions"
        allowed = {
            "phase_scopes", "phases", "action_ids", "skill_ids",
            "component_ids", "damage_types", "actor_types", "target_types",
            "target_relations", "tags", "any_tags", "exclude_tags",
        }
        _keys(conditions, conditions_path, allowed=allowed)
        for field, value in conditions.items():
            values = [value] if isinstance(value, str) else value
            _string_list(values, f"{conditions_path}.{field}")
        if "target_relations" in conditions:
            for relation in (
                [conditions["target_relations"]]
                if isinstance(conditions["target_relations"], str)
                else conditions["target_relations"]
            ):
                _enum(
                    relation, f"{conditions_path}.target_relations",
                    {"self", "ally", "enemy"},
                )
        if "damage_types" in conditions:
            values = conditions["damage_types"]
            values = [values] if isinstance(values, str) else values
            for index, damage_type in enumerate(values):
                _validate_damage_type(
                    damage_type, f"{conditions_path}.damage_types[{index}]",
                    allow_all=True,
                )

    scope = effect.get("application_scope")
    if scope is not None:
        scope_path = f"{path}.application_scope"
        _keys(scope, scope_path, allowed={"phase_scopes"})
        scopes = scope.get("phase_scopes", ["all"])
        scopes = [scopes] if isinstance(scopes, str) else scopes
        _string_list(scopes, f"{scope_path}.phase_scopes")
        for item in scopes:
            _enum(
                item, f"{scope_path}.phase_scopes",
                {"all", "formal_battle", "simple_round", "non_battle"},
            )

    consumption = effect.get("consumption")
    if consumption is not None:
        consumption_path = f"{path}.consumption"
        _keys(
            consumption,
            consumption_path,
            allowed={
                "event", "mode", "uses", "remove_when_empty",
                "use_refresh_rule",
            },
            required={"event"},
        )
        _enum(
            consumption["event"], f"{consumption_path}.event",
            Modifier.VALID_CONSUMPTION_EVENTS,
        )
        _enum(
            consumption.get("mode", "automatic"),
            f"{consumption_path}.mode", Modifier.VALID_CONSUMPTION_MODES,
        )
        if "uses" in consumption:
            _integer(consumption["uses"], f"{consumption_path}.uses", positive=True)
        if "remove_when_empty" in consumption:
            _boolean(
                consumption["remove_when_empty"],
                f"{consumption_path}.remove_when_empty",
            )
        if "use_refresh_rule" in consumption:
            _enum(
                consumption["use_refresh_rule"],
                f"{consumption_path}.use_refresh_rule",
                Modifier.VALID_USE_REFRESH_RULES,
            )

    if (
        any(effect.get(field) for field in ("conditions", "application_scope"))
        or effect.get("consumption", {}).get("mode") == "optional"
    ) and effect["effect_type"] not in Modifier.CONTEXTUAL_EFFECT_TYPES:
        _error(path, f"{effect['effect_type']}不支持条件型Modifier")


def _validate_maintenance(value, path):
    _keys(
        value, path, allowed={"resource", "value", "cost_id"},
        required={"value"},
    )
    if "resource" in value:
        _string(value["resource"], f"{path}.resource")
    _number(value["value"], f"{path}.value", minimum=0)
    if "cost_id" in value:
        _string(value["cost_id"], f"{path}.cost_id")


def _validate_field_target(value, path):
    _keys(value, path, allowed={"scope", "relation"})
    if "scope" in value:
        _enum(
            value["scope"], f"{path}.scope",
            {"field_owner", "characters_in_field"},
        )
    if "relation" in value:
        _enum(
            value["relation"], f"{path}.relation",
            {"all", "self", "ally", "enemy", "selected"},
        )


def _validate_field_requirements(value, path):
    if isinstance(value, list):
        allowed = {
            "is_building", "building_only", "building_with_high_level",
            "not_road", "road_only", "high_level_only",
        }
        for index, requirement in enumerate(value):
            _enum(requirement, f"{path}[{index}]", allowed)
        return
    allowed = {
        "is_building", "building_only", "building_with_high_level",
        "not_road", "road_only", "high_level_only", "location_status",
        "owner_field_type",
    }
    _keys(value, path, allowed=allowed)
    for field, item in value.items():
        if field in {"location_status", "owner_field_type"}:
            _string(item, f"{path}.{field}")
        else:
            _boolean(item, f"{path}.{field}")


def _validate_field_effects(effects, path):
    _list(effects, path)
    for index, nested in enumerate(effects):
        nested_path = f"{path}[{index}]"
        validate_effect_definition(
            nested,
            path=nested_path,
            component_type="field",
            field_effect=True,
        )
        mode = nested.get("application_mode", "continuous")
        _enum(mode, f"{nested_path}.application_mode", APPLICATION_MODES)
        if mode == "continuous" and nested["effect_type"] not in MODIFIER_EFFECT_TYPES:
            _error(nested_path, "continuous场地效果必须是Modifier")
        if "effect_target" in nested:
            _validate_field_target(
                nested["effect_target"], f"{nested_path}.effect_target",
            )


def _validate_nested_skill_definition(definition, path):
    _mapping(definition, path)
    _keys(
        definition,
        path,
        allowed={
            "skill_id", "name", "rank", "components", "negative_skill",
            "skill_category", "casting", "rules_text",
        },
        required={"skill_id", "name", "rank", "components"},
    )
    for field in ("skill_id", "name", "rank"):
        _string(definition[field], f"{path}.{field}")
    if "negative_skill" in definition:
        _boolean(definition["negative_skill"], f"{path}.negative_skill")
    if "skill_category" in definition and definition["skill_category"] is not None:
        _string(definition["skill_category"], f"{path}.skill_category")
    if "casting" in definition:
        _mapping(definition["casting"], f"{path}.casting")
    components = _list(
        definition["components"],
        f"{path}.components",
        nonempty=True,
    )
    component_ids = []
    for index, component in enumerate(components):
        component_path = f"{path}.components[{index}]"
        _mapping(component, component_path)
        component_id = component.get("component_id")
        _string(component_id, f"{component_path}.component_id")
        component_ids.append(component_id)
        component_type = component.get("type")
        _enum(
            component_type,
            f"{component_path}.type",
            {"active", "passive", "trigger", "react"},
        )
        if not component.get("effects") and "choices" not in component:
            _error(component_path, "没有任何效果")
        validate_component_effects(component, path=component_path)
    if len(component_ids) != len(set(component_ids)):
        _error(f"{path}.components", "component_id不能重复")


def _validate_dynamic_action_definition(definition, path):
    _keys(
        definition,
        path,
        allowed={
            "action_id", "name", "description", "action_type",
            "available_phases", "resolution_timing", "target",
            "target_rules", "condition", "cost", "effects", "choices",
            "inputs",
            "display_order", "usage_limit", "cooldown",
        },
        required={"action_id", "name", "available_phases"},
    )
    _string(definition["action_id"], f"{path}.action_id")
    _string(definition["name"], f"{path}.name")
    if "description" in definition:
        _string(definition["description"], f"{path}.description")
    _enum(
        definition.get("action_type", "special"),
        f"{path}.action_type",
        ACTION_TYPE_CATEGORIES | {"skill"},
    )
    phases = _list(
        definition["available_phases"],
        f"{path}.available_phases",
        nonempty=True,
    )
    for index, phase in enumerate(phases):
        _enum(phase, f"{path}.available_phases[{index}]", ACTION_PHASES)
    _enum(
        definition.get("resolution_timing", "immediate"),
        f"{path}.resolution_timing",
        RESOLUTION_TIMINGS,
    )
    _enum(
        definition.get("target", "self"),
        f"{path}.target",
        TARGET_TYPES,
    )
    if "target_rules" in definition:
        validate_target_rules(
            definition["target_rules"], path=f"{path}.target_rules",
        )
    if "condition" in definition:
        validate_condition(definition["condition"], path=f"{path}.condition")
    if "cost" in definition:
        _list(definition["cost"], f"{path}.cost")
    if "display_order" in definition:
        _integer(definition["display_order"], f"{path}.display_order")
    component = deepcopy(definition)
    component.setdefault("effects", [])
    component["type"] = "active"
    component["component_id"] = f"dynamic_action:{definition['action_id']}"
    validate_component_effects(component, path=path)


def _validate_effect_data(effect_type, data, path, component_type=None):
    if effect_type in {"add_content", "remove_content"}:
        _enum(
            data["content_type"],
            f"{path}.content_type",
            {"personal_skill", "basic_magic", "noble_phantasm"},
        )
        _string(data["content_id"], f"{path}.content_id")
        if "permanent" in data:
            _boolean(data["permanent"], f"{path}.permanent")
        if "remove_with_source" in data:
            _boolean(
                data["remove_with_source"],
                f"{path}.remove_with_source",
            )
            if data.get("permanent", True) and data["remove_with_source"]:
                _error(path, "永久获得的内容不能设置remove_with_source=true")
    elif effect_type == "restore_component":
        if not {"usage_amount", "cooldown_turns"}.intersection(data):
            _error(path, "必须提供usage_amount或cooldown_turns")
        for field in ("usage_amount", "cooldown_turns", "maximum"):
            if field not in data:
                continue
            value = data[field]
            if value != "all":
                _integer(value, f"{path}.{field}", positive=True)
        if "usage_scope" in data:
            _enum(
                data["usage_scope"],
                f"{path}.usage_scope",
                USAGE_LIMIT_SCOPES,
            )
        for field in ("allow_other", "exclude_source"):
            if field in data:
                _boolean(data[field], f"{path}.{field}")
        for field in ("skill_ids", "component_ids"):
            if field in data:
                _string_list(data[field], f"{path}.{field}", nonempty=True)
    elif effect_type == "add_simple_round":
        _enum(
            data.get("attacker_rule", "actor"),
            f"{path}.attacker_rule",
            {"actor", "target"},
        )
        defender_rule = data.get("defender_rule", "all_targets")
        _enum(
            defender_rule,
            f"{path}.defender_rule",
            {"actor", "target", "all_targets"},
        )
        if data.get("attacker_rule", "actor") == "target" and defender_rule == "all_targets":
            _error(path, "attacker_rule=target时不能使用defender_rule=all_targets")
        _enum(
            data.get("trigger_phase", "immediate"),
            f"{path}.trigger_phase",
            {
                "immediate", "battle_start", "turn_start", "guard",
                "defense", "attack", "turn_end",
            },
        )
        if "trigger_target" in data:
            _enum(
                data["trigger_target"],
                f"{path}.trigger_target",
                {"actor", "target", "first_defender"},
            )
        attack_mode = data.get("attack_mode", "fixed")
        _enum(attack_mode, f"{path}.attack_mode", {"fixed", "select"})
        for field in ("consume_attack_phase", "enter_battle", "is_ambush"):
            if field in data:
                _boolean(data[field], f"{path}.{field}")
        if "attack_stat" in data:
            _string(data["attack_stat"], f"{path}.attack_stat")
        for field in (
            "attack_roll_bonus", "damage_value", "damage_multiplier", "damage_flat",
        ):
            if field in data and data[field] is not None:
                _number(data[field], f"{path}.{field}")
        if "damage_value_source" in data:
            _enum(
                data["damage_value_source"],
                f"{path}.damage_value_source",
                {"actor_attribute", "target_attribute"},
            )
            if "damage_attribute" not in data:
                _error(path, "damage_value_source必须提供damage_attribute")
        if "damage_attribute" in data:
            _string(data["damage_attribute"], f"{path}.damage_attribute")
        if "resolution_channel" in data:
            _enum(
                data["resolution_channel"],
                f"{path}.resolution_channel",
                {"attack", "release"},
            )
        if "damage_type" in data:
            _validate_damage_type(data["damage_type"], f"{path}.damage_type")
        for field in (
            "damage_percentage_modifiers", "damage_flat_modifiers",
        ):
            if field in data:
                _number_list(data[field], f"{path}.{field}")
        if attack_mode == "select":
            fixed_only = {
                "attack_stat", "attack_roll_bonus", "damage_value",
                "damage_type", "damage_percentage_modifiers",
                "damage_flat_modifiers", "damage_value_source",
                "damage_attribute", "damage_multiplier", "damage_flat",
                "resolution_channel",
            } & set(data)
            if fixed_only:
                _error(
                    path,
                    f"attack_mode=select不能定义固定攻击字段：{sorted(fixed_only)}",
                )
    elif effect_type == "add_action":
        _validate_dynamic_action_definition(
            data["action_definition"],
            f"{path}.action_definition",
        )
        if data.get("duration") is not None:
            _integer(data["duration"], f"{path}.duration", positive=True)
        _enum(
            data.get("duration_timing", "global_turn_end"),
            f"{path}.duration_timing",
            {"global_turn_end"},
        )
        _enum(
            data.get("duplicate_policy", "reject"),
            f"{path}.duplicate_policy",
            {"reject", "replace"},
        )
        if "remove_with_source" in data:
            _boolean(data["remove_with_source"], f"{path}.remove_with_source")
    elif effect_type == "add_skill":
        sources = {
            field for field in ("skill_definition", "skill_ref")
            if field in data
        }
        if len(sources) != 1:
            _error(path, "必须且只能提供skill_definition或skill_ref之一")
        if "skill_definition" in data:
            _validate_nested_skill_definition(
                data["skill_definition"],
                f"{path}.skill_definition",
            )
        if "skill_ref" in data:
            reference = data["skill_ref"]
            reference_path = f"{path}.skill_ref"
            _keys(
                reference,
                reference_path,
                allowed={"content_type", "skill_id"},
                required={"content_type", "skill_id"},
            )
            _enum(
                reference["content_type"],
                f"{reference_path}.content_type",
                {"personal_skill"},
            )
            _string(reference["skill_id"], f"{reference_path}.skill_id")
        if "collection" in data:
            _enum(
                data["collection"],
                f"{path}.collection",
                {"personal_skills"},
            )
        if "duplicate_policy" in data:
            _enum(
                data["duplicate_policy"],
                f"{path}.duplicate_policy",
                {"reject"},
            )
        if "remove_with_source" in data:
            _boolean(data["remove_with_source"], f"{path}.remove_with_source")
    elif effect_type == "remove_skill":
        selectors = {
            field for field in ("skill", "skill_id") if field in data
        }
        if len(selectors) != 1:
            _error(path, "必须且只能提供skill='self'或skill_id之一")
        if "skill" in data:
            _enum(data["skill"], f"{path}.skill", {"self"})
        if "skill_id" in data:
            _string(data["skill_id"], f"{path}.skill_id")
        if "collection" in data:
            _enum(
                data["collection"],
                f"{path}.collection",
                {"personal_skills"},
            )
    elif effect_type == "growing":
        _string(data["growth_id"], f"{path}.growth_id")
        _integer(data["value"], f"{path}.value")
        _enum(
            data.get("calculation", "add"),
            f"{path}.calculation",
            {"add", "subtract", "set"},
        )
        for field in ("initial_value", "minimum", "maximum"):
            if field in data and data[field] is not None:
                _integer(data[field], f"{path}.{field}")
        minimum = data.get("minimum", 0)
        maximum = data.get("maximum")
        if maximum is not None and maximum < minimum:
            _error(path, "maximum不能小于minimum")
        initial = data.get("initial_value", 0)
        if initial < minimum or (maximum is not None and initial > maximum):
            _error(path, "initial_value必须位于minimum与maximum之间")
        stages = _list(data["stages"], f"{path}.stages", nonempty=True)
        stage_ids = []
        reversible_types = MODIFIER_EFFECT_TYPES | {
            "add_skill", "summon", "create_field",
            "deploy_reality_marble",
        }
        for index, stage in enumerate(stages):
            stage_path = f"{path}.stages[{index}]"
            _keys(
                stage,
                stage_path,
                allowed={
                    "stage_id", "threshold", "entry_policy",
                    "enter_effects", "while_active_effects", "exit_effects",
                },
                required={"stage_id", "threshold"},
            )
            _string(stage["stage_id"], f"{stage_path}.stage_id")
            stage_ids.append(stage["stage_id"])
            _integer(stage["threshold"], f"{stage_path}.threshold")
            _enum(
                stage.get("entry_policy", "first_only"),
                f"{stage_path}.entry_policy",
                {"first_only", "each_entry"},
            )
            for field in (
                "enter_effects", "while_active_effects", "exit_effects",
            ):
                effects = _list(stage.get(field, []), f"{stage_path}.{field}")
                for effect_index, nested in enumerate(effects):
                    nested_path = f"{stage_path}.{field}[{effect_index}]"
                    validate_effect_definition(
                        nested,
                        path=nested_path,
                        component_type=component_type,
                    )
                    if (
                        field == "while_active_effects"
                        and nested["effect_type"] not in reversible_types
                    ):
                        _error(
                            nested_path,
                            "while_active_effects只能使用可自动撤销的效果",
                        )
                    if (
                        field == "while_active_effects"
                        and nested["effect_type"] in MODIFIER_EFFECT_TYPES
                        and any(
                            name in nested
                            for name in ("duration", "phase_window", "consumption")
                        )
                    ):
                        _error(
                            nested_path,
                            "while_active的Modifier由阶段控制生命周期，"
                            "不能另设duration、phase_window或consumption",
                        )
        if len(stage_ids) != len(set(stage_ids)):
            _error(f"{path}.stages", "stage_id不能重复")
    elif effect_type == "add_resource":
        _validate_resource_definition(data, path)
    elif effect_type in {
        "add_status", "attribute_bonus", "attack_bonus", "dice_bonus",
        "magic_resistance", "movement_point_bonus", "numeric_attribute_bonus",
        "carry_capacity",
        "plus_bonus", "shield", "visibility_bonus", "hp_floor",
    }:
        if "value" in data:
            if effect_type in {"add_status", "hidden"}:
                _string(data["value"], f"{path}.value")
            elif effect_type == "plus_bonus":
                _integer(data["value"], f"{path}.value")
            else:
                _number(data["value"], f"{path}.value")
        if "effect_target" in data:
            _string(data["effect_target"], f"{path}.effect_target")
        if effect_type == "shield":
            _number(data["value"], f"{path}.value", minimum=0)
            if "damage_types" in data:
                _validate_damage_types(data["damage_types"], f"{path}.damage_types")
        if effect_type == "hp_floor":
            _integer(data["value"], f"{path}.value", positive=True)
    elif effect_type == "prevent_death":
        _integer(data.get("hp", 1), f"{path}.hp", positive=True)
        if "hp_floor_duration" in data:
            _integer(data["hp_floor_duration"], f"{path}.hp_floor_duration", positive=True)
        if "remove_skill_when_exhausted" in data:
            _boolean(data["remove_skill_when_exhausted"], f"{path}.remove_skill_when_exhausted")
    elif effect_type == "hidden":
        _string(data["value"], f"{path}.value")
        for field in (
            "remove_on_position_change",
            "remove_on_battle_entry",
            "requires_building",
            "withdraw_from_battle",
            "rejoin_on_expire",
        ):
            if field in data:
                _boolean(data[field], f"{path}.{field}")
    elif effect_type == "presence_concealment":
        _enum(data["rank"], f"{path}.rank", {"C", "B", "A", "EX"})
        _number(data["value"], f"{path}.value", minimum=0)
        for field in (
            "investigation_immunity",
            "active_hide_perception_immunity",
        ):
            if field in data:
                _boolean(data[field], f"{path}.{field}")
    elif effect_type == "trap":
        if "trap_id" in data:
            _string(data["trap_id"], f"{path}.trap_id")
        if "base_damage" in data:
            _integer(data["base_damage"], f"{path}.base_damage", minimum=0)
        if "share_knowledge" in data:
            _boolean(data["share_knowledge"], f"{path}.share_knowledge")
    elif effect_type == "summon":
        _string(data["template_id"], f"{path}.template_id")
        count = data.get("count", 1)
        _integer(count, f"{path}.count", positive=True)
        if "placement_rule" in data:
            _enum(
                data["placement_rule"],
                f"{path}.placement_rule",
                {"current_position", "target_position"},
            )
        if data.get("duration") is not None:
            _integer(data["duration"], f"{path}.duration", positive=True)
        maximum = data.get("maximum_active")
        if maximum is not None:
            _integer(maximum, f"{path}.maximum_active", positive=True)
            if maximum < count:
                _error(f"{path}.maximum_active", "不能小于count")
        if "limit_scope" in data:
            _enum(
                data["limit_scope"],
                f"{path}.limit_scope",
                {"template", "skill", "summoner"},
            )
        if "at_limit" in data:
            _enum(
                data["at_limit"],
                f"{path}.at_limit",
                {"reject", "replace_oldest", "select"},
            )
        for field in ("activate_immediately", "remove_with_source"):
            if field in data:
                _boolean(data[field], f"{path}.{field}")
        if "name_prefix" in data:
            _string(data["name_prefix"], f"{path}.name_prefix")
    elif effect_type == "cost_modifier":
        _string(data["resource"], f"{path}.resource")
        if "cost_id" in data:
            _string(data["cost_id"], f"{path}.cost_id")
        _enum(
            data["calculation"], f"{path}.calculation",
            {"multiplier", "flat", "override"},
        )
        _number(data["value"], f"{path}.value")
    elif effect_type == "damage_modifier":
        _enum(data["direction"], f"{path}.direction", {"incoming", "outgoing"})
        _enum(data["calculation"], f"{path}.calculation", {"percentage", "flat"})
        _number(data["value"], f"{path}.value")
        if "damage_types" in data:
            _validate_damage_types(data["damage_types"], f"{path}.damage_types")
        for field in ("action_ids", "skill_ids", "source_tags"):
            if field in data:
                _string_list(data[field], f"{path}.{field}")
    elif effect_type == "damage":
        _validate_damage_type(data["damage_type"], f"{path}.damage_type")
        _validate_value_source(data, path, required=True)
        for field in ("multiplier", "flat"):
            if field in data:
                _number(data[field], f"{path}.{field}")
        for field in ("percentage_modifiers", "flat_modifiers"):
            if field in data:
                _number_list(data[field], f"{path}.{field}")
        for field in ("action_id", "skill_id"):
            if field in data and data[field] is not None:
                _string(data[field], f"{path}.{field}")
        if "source_tags" in data:
            _string_list(data["source_tags"], f"{path}.source_tags")
        for field in ("ignore_shield", "is_hidden"):
            if field in data:
                _boolean(data[field], f"{path}.{field}")
    elif effect_type == "create_attack_event":
        if "damage_type" in data:
            _validate_damage_type(data["damage_type"], f"{path}.damage_type")
        for field in (
            "attack_stat_multiplier", "attack_stat_flat", "attack_roll_bonus",
            "damage_value", "multiplier", "flat",
        ):
            if field in data:
                _number(data[field], f"{path}.{field}")
        if "attack_stat" in data:
            _string(data["attack_stat"], f"{path}.attack_stat")
        if "initial_die" in data:
            _integer(data["initial_die"], f"{path}.initial_die", minimum=1)
            if data["initial_die"] > 10:
                _error(f"{path}.initial_die", "不能大于10")
        if "damage_segments" in data:
            _number_list(data["damage_segments"], f"{path}.damage_segments", nonempty=True)
            if any(
                value < 0
                for value in data["damage_segments"]
                if not is_input_expression(value)
            ):
                _error(f"{path}.damage_segments", "伤害段不能小于0")
        source_fields = {
            field for field in ("damage_value", "damage_segments", "value", "value_source")
            if field in data
        }
        if "damage_segments" in source_fields and len(source_fields) > 1:
            _error(path, "damage_segments不能与其他伤害值来源同时提供")
        if "damage_value" in source_fields and source_fields & {"value", "value_source"}:
            _error(path, "damage_value不能与value或value_source同时提供")
        if "value" in data or "value_source" in data or "attribute" in data:
            _validate_value_source(data, path)
        for field in ("percentage_modifiers", "flat_modifiers"):
            if field in data:
                _number_list(data[field], f"{path}.{field}")
        for field in ("action_id", "skill_id"):
            if field in data and data[field] is not None:
                _string(data[field], f"{path}.{field}")
        if "source_tags" in data:
            _string_list(data["source_tags"], f"{path}.source_tags")
        for field in ("ignore_shield", "ignore_block", "target_lock"):
            if field in data:
                _boolean(data[field], f"{path}.{field}")
        if "resolution_channel" in data:
            _enum(data["resolution_channel"], f"{path}.resolution_channel", {"attack", "release"})
    elif effect_type in {"gain_resource", "modify_resource"}:
        _string(data["resource_id"], f"{path}.resource_id")
        _number(data["value"], f"{path}.value")
        if "calculation" in data:
            _enum(data["calculation"], f"{path}.calculation", VALID_RESOURCE_OPERATIONS)
            if data["calculation"] == "divide" and data["value"] == 0:
                _error(f"{path}.value", "divide操作不能使用0")
    elif effect_type == "grant_temporary_mp":
        _validate_value_source(data, path)
        if "value_source" in data:
            _enum(data["value_source"], f"{path}.value_source", {"event_value", "status_stack_count"})
        for field in ("multiplier", "flat"):
            if field in data:
                _number(data[field], f"{path}.{field}")
    elif effect_type == "recover_resource":
        _string(data["resource_id"], f"{path}.resource_id")
        _validate_value_source(data, path, required=True)
        if (
            "value" in data
            and not is_input_expression(data["value"])
            and data["value"] < 0
        ):
            _error(f"{path}.value", "回复量不能小于0")
        if "calculation" in data:
            _enum(
                data["calculation"], f"{path}.calculation",
                {"flat", "maximum_percentage", "maximum_ratio"},
            )
    elif effect_type == "purify":
        maximum = data.get("maximum", 1)
        if maximum != "all":
            _integer(maximum, f"{path}.maximum", positive=True)
    elif effect_type == "order_change":
        calculation = data["calculation"]
        _enum(
            calculation, f"{path}.calculation",
            {"move_first", "move_last", "move_before", "move_after"},
        )
        if data["duration"] is not None:
            _integer(data["duration"], f"{path}.duration", positive=True)
        if "subject" in data:
            _enum(data["subject"], f"{path}.subject", {"actor", "target"})
        if calculation in {"move_before", "move_after"}:
            if "anchor" not in data:
                _error(path, f"{calculation}必须提供anchor")
            _enum(data["anchor"], f"{path}.anchor", {"actor", "target"})
        elif "anchor" in data:
            _error(f"{path}.anchor", "只用于move_before或move_after")
    elif effect_type == "modify_event_value":
        if "calculation" in data:
            _enum(data["calculation"], f"{path}.calculation", {"add", "multiply", "set"})
        for field in ("value", "minimum", "maximum"):
            if field in data and data[field] is not None:
                _number(data[field], f"{path}.{field}")
        if data.get("minimum") is not None and data.get("maximum") is not None:
            if data["minimum"] > data["maximum"]:
                _error(path, "minimum不能大于maximum")
    elif effect_type == "cancel_event":
        if "reason" in data and data["reason"] is not None:
            _string(data["reason"], f"{path}.reason")
    elif effect_type == "change_damage_type":
        _validate_damage_type(data["damage_type"], f"{path}.damage_type")
    elif effect_type == "create_field":
        _validate_field_definition(data, path)
    elif effect_type == "deploy_reality_marble":
        _validate_reality_marble_definition(data, path)


def _validate_field_definition(data, path):
    _string(data["field_id"], f"{path}.field_id")
    if "name" in data:
        _string(data["name"], f"{path}.name")
    if "field_type" in data:
        _enum(data["field_type"], f"{path}.field_type", FIELD_TYPES)
    if "radius" in data:
        _integer(data["radius"], f"{path}.radius", minimum=0)
    if "duration" in data and data["duration"] is not None:
        _integer(data["duration"], f"{path}.duration", positive=True)
    for field in (
        "include_area_levels", "remove_on_source_death", "remove_with_source",
        "exclusive_center", "apply_once", "battle_bound",
    ):
        if field in data:
            _boolean(data[field], f"{path}.{field}")
    if "exit_penalty" in data:
        if not data.get("battle_bound", False):
            _error(path, "exit_penalty要求battle_bound=true")
        penalty = data["exit_penalty"]
        _keys(penalty, f"{path}.exit_penalty", allowed={"value", "damage_type"}, required={"value", "damage_type"})
        _number(penalty["value"], f"{path}.exit_penalty.value", minimum=0)
        _validate_damage_type(penalty["damage_type"], f"{path}.exit_penalty.damage_type")
    for field in ("owner_unique_key",):
        if field in data and data[field] is not None:
            _string(data[field], f"{path}.{field}")
    if "owner_vision" in data and data["owner_vision"] is not None:
        vision_path = f"{path}.owner_vision"
        _keys(
            data["owner_vision"], vision_path,
            allowed={"ignore_concealment", "share"},
        )
        for field, value in data["owner_vision"].items():
            _boolean(value, f"{vision_path}.{field}")
    if "center_target" in data:
        center_path = f"{path}.center_target"
        _keys(data["center_target"], center_path, allowed={"requirements"})
        if "requirements" in data["center_target"]:
            _validate_field_requirements(
                data["center_target"]["requirements"],
                f"{center_path}.requirements",
            )
    if "requirements" in data:
        _validate_field_requirements(data["requirements"], f"{path}.requirements")
    if "maintenance" in data and data["maintenance"] is not None:
        _validate_maintenance(data["maintenance"], f"{path}.maintenance")
    if "selected_targets" in data:
        _list(data["selected_targets"], f"{path}.selected_targets")
    if "effects" in data:
        _validate_field_effects(data["effects"], f"{path}.effects")


def _validate_reality_marble_definition(data, path):
    _string(data["reality_marble_id"], f"{path}.reality_marble_id")
    if "name" in data:
        _string(data["name"], f"{path}.name")
    if "capture_radius" in data:
        _integer(data["capture_radius"], f"{path}.capture_radius", minimum=0)
    if "duration" in data and data["duration"] is not None:
        _integer(data["duration"], f"{path}.duration", positive=True)
    if "remove_with_source" in data:
        _boolean(data["remove_with_source"], f"{path}.remove_with_source")
    if "maintenance" in data and data["maintenance"] is not None:
        _validate_maintenance(data["maintenance"], f"{path}.maintenance")
    if "selected_targets" in data:
        _list(data["selected_targets"], f"{path}.selected_targets")
    if "interior" in data:
        interior_path = f"{path}.interior"
        interior = data["interior"]
        _keys(
            interior,
            interior_path,
            allowed={"location_name", "is_building", "effects"},
        )
        if "location_name" in interior:
            _string(interior["location_name"], f"{interior_path}.location_name")
        if "is_building" in interior:
            _boolean(interior["is_building"], f"{interior_path}.is_building")
        if "effects" in interior:
            _validate_field_effects(interior["effects"], f"{interior_path}.effects")


def validate_effect_definition(
    effect,
    *,
    path="effect",
    component_type=None,
    field_effect=False,
):
    """Validate one canonical skill effect without mutating it."""
    _mapping(effect, path)
    effect_type = effect.get("effect_type")
    if effect_type not in EFFECT_SCHEMAS:
        _error(f"{path}.effect_type", f"效果关键词不存在：{effect_type}")
    schema = EFFECT_SCHEMAS[effect_type]
    allowed_top = (
        _MODIFIER_TOP_LEVEL_FIELDS
        if schema.modifier
        else _IMMEDIATE_TOP_LEVEL_FIELDS
    )
    if field_effect:
        allowed_top = allowed_top | _FIELD_WRAPPER_FIELDS
    _keys(
        effect,
        path,
        allowed=allowed_top,
        required={"effect_type", "effect_data"},
    )
    if "metadata" in effect:
        _mapping(effect["metadata"], f"{path}.metadata")
    if "effect_target" in effect and not (
        field_effect and isinstance(effect["effect_target"], dict)
    ):
        _enum(
            effect["effect_target"], f"{path}.effect_target",
            {"self", "attack_target"},
        )
    data_path = f"{path}.effect_data"
    data = _mapping(effect["effect_data"], data_path)
    _keys(
        data,
        data_path,
        allowed=schema.allowed_data,
        required=schema.required_data,
    )
    if schema.modifier:
        _validate_modifier_common(effect, path)
    if effect_type == "add_status":
        from game.status.registry import get_status_definition
        _string(data["status_id"], f"{data_path}.status_id")
        get_status_definition(data["status_id"])
        if effect.get("duration_timing", "global_turn_end") != "global_turn_end" or "phase_window" in effect:
            _error(path, "状态持续时间统一按global_turn_end扣减，不接受phase_window")
    if effect_type in {
        "modify_event_value", "cancel_event", "change_damage_type",
    } and component_type not in {
        None, "trigger", "react",
    }:
        _error(path, f"{effect_type}只能用于trigger或react组件")
    _validate_effect_data(
        effect_type,
        data,
        data_path,
        component_type=component_type,
    )
    return True


def validate_component_effects(component, *, path="component"):
    """Recursively validate direct and selectable effects in a component."""
    _mapping(component, path)
    component_type = component.get("type")
    validate_component_inputs(component, path=path)
    validate_condition(component.get("condition", {}), path=f"{path}.condition")
    validate_target_rules(
        component.get("target_rules", {}), path=f"{path}.target_rules",
    )
    if component.get("target") == "selectable_attribute":
        rules_path = f"{path}.target_rules"
        rules = component.get("target_rules", {})
        _keys(
            rules,
            rules_path,
            allowed={"allowed_attributes", "include_noble"},
        )
        if "allowed_attributes" in rules:
            _string_list(
                rules["allowed_attributes"],
                f"{rules_path}.allowed_attributes",
                nonempty=True,
            )
            allowed = {
                "strength", "endurance", "flexibility", "magic", "fortune",
                "noble",
            }
            for index, attribute in enumerate(rules["allowed_attributes"]):
                _enum(
                    attribute,
                    f"{rules_path}.allowed_attributes[{index}]",
                    allowed,
                )
        if "include_noble" in rules:
            _boolean(rules["include_noble"], f"{rules_path}.include_noble")
    usage_limit = component.get("usage_limit")
    cooldown = component.get("cooldown")
    if usage_limit is not None or cooldown is not None:
        if component_type not in {"active", "trigger", "react"}:
            _error(path, "usage_limit和cooldown只能用于active、trigger或react组件")
    if usage_limit is not None:
        usage_path = f"{path}.usage_limit"
        _keys(
            usage_limit,
            usage_path,
            allowed={"scope", "maximum"},
            required={"scope", "maximum"},
        )
        _enum(usage_limit["scope"], f"{usage_path}.scope", USAGE_LIMIT_SCOPES)
        _integer(usage_limit["maximum"], f"{usage_path}.maximum", positive=True)
    if cooldown is not None:
        cooldown_path = f"{path}.cooldown"
        _keys(
            cooldown,
            cooldown_path,
            allowed={"turns", "unit", "group"},
            required={"turns"},
        )
        _integer(cooldown["turns"], f"{cooldown_path}.turns", positive=True)
        if "group" in cooldown:
            _string(cooldown["group"], f"{cooldown_path}.group")
        _enum(
            cooldown.get("unit", "global_turn"),
            f"{cooldown_path}.unit",
            COOLDOWN_UNITS,
        )
    limit = component.get("limit", {})
    if isinstance(limit, dict):
        scope = limit.get("scope")
        if scope in {"until_triggered", "next_battle_start"} and component_type not in {
            "trigger", "react",
        }:
            _error(
                f"{path}.limit.scope",
                f"{scope}只能用于trigger或react组件",
            )
    effects = component.get("effects", [])
    _list(effects, f"{path}.effects")
    for index, effect in enumerate(effects):
        validate_effect_definition(
            effect,
            path=f"{path}.effects[{index}]",
            component_type=component_type,
        )
    choices = component.get("choices")
    if choices is None:
        return True
    options = choices.get("options", [])
    for option_index, option in enumerate(options):
        option_path = f"{path}.choices.options[{option_index}]"
        _mapping(option, option_path)
        validate_condition(
            option.get("condition", {}),
            path=f"{option_path}.condition",
        )
        option_effects = option.get("effects", [])
        _list(option_effects, f"{option_path}.effects")
        for effect_index, effect in enumerate(option_effects):
            validate_effect_definition(
                effect,
                path=f"{option_path}.effects[{effect_index}]",
                component_type=component_type,
            )
    return True


def validate_effect_registry(runtime_handlers):
    """Ensure validation and execution register exactly the same keywords."""
    runtime_types = set(runtime_handlers)
    schema_types = set(EFFECT_SCHEMAS)
    if runtime_types != schema_types:
        missing_schemas = sorted(runtime_types - schema_types)
        missing_handlers = sorted(schema_types - runtime_types)
        raise RuntimeError(
            "effect注册表不一致："
            f"缺少schema={missing_schemas}，缺少handler={missing_handlers}"
        )
    return True
