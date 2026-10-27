"""行动与技能共用的条件、目标规则验证和运行时判定。"""

from numbers import Real

from game.map.map import Road, get_distance


VISIBILITY_COLLECTIONS = frozenset({
    "own_visible",
    "shared_visible",
    "own_perceived",
    "shared_perceived",
    "perceived",
    "any_visible",
})

CONDITION_FIELDS = frozenset({
    "all", "any", "not",
    "condition_id",
    "actor_alive",
    "actor_type",
    "at_grail_position",
    "attack_phase_count_at_least",
    "battle_state",
    "carry_capacity_available",
    "command_spell_at_least",
    "cooldown_ready",
    "damage_type",
    "event_actor",
    "event_actor_is_self",
    "event_source",
    "event_source_is_self",
    "event_target",
    "event_target_is_self",
    "event_value_at_least",
    "event_value_at_most",
    "forbidden_status",
    "grail_ready",
    "in_ride_group",
    "leader_transfer_available",
    "missing_hp_at_least",
    "movement_locked",
    "no_command_spell_transfer",
    "no_pending_travel_join",
    "not_in_travel_group",
    "pending_attacks_at_least",
    "player_character",
    "phase",
    "position_is_building",
    "position_is_port",
    "position_required",
    "release_available",
    "required_casting",
    "required_status",
    "servant_count",
    "travel_group_leader",
})

CONDITION_IDS = frozenset({"master_is_none"})

TARGET_RULE_FIELDS = frozenset({
    "all_members_mutual_allies",
    "allow_backtracking",
    "allow_early_stop",
    "allowed_attributes",
    "distance",
    "exclude_own_visible",
    "exclude_same_position",
    "exclude_self",
    "include_noble",
    "include_roads",
    "maximum",
    "maximum_steps_source",
    "maximum_targets_source",
    "merge_area_levels",
    "minimum",
    "minimum_steps",
    "must_be_alive",
    "must_be_hostile",
    "path_must_be_connected",
    "pending_attacks_at_least",
    "required_visibility",
    "requires_confirmation",
    "same_ap_start_position",
    "same_position",
    "selection",
    "target_battle_state",
    "target_group_leader_remains",
    "unlimited_targets",
})

_BOOLEAN_CONDITIONS = frozenset({
    "actor_alive", "at_grail_position", "battle_state",
    "carry_capacity_available", "grail_ready", "in_ride_group",
    "leader_transfer_available", "movement_locked",
    "no_command_spell_transfer", "no_pending_travel_join",
    "not_in_travel_group", "player_character", "position_is_building",
    "position_is_port",
    "position_required", "release_available", "required_casting",
    "travel_group_leader", "event_actor_is_self", "event_source_is_self",
    "event_target_is_self",
})
_INTEGER_CONDITIONS = frozenset({
    "attack_phase_count_at_least", "command_spell_at_least",
    "missing_hp_at_least", "pending_attacks_at_least", "servant_count",
})
_BOOLEAN_TARGET_RULES = frozenset({
    "all_members_mutual_allies", "allow_backtracking", "allow_early_stop",
    "exclude_own_visible", "exclude_same_position",
    "exclude_self", "include_noble", "include_roads", "merge_area_levels",
    "must_be_alive", "must_be_hostile", "path_must_be_connected",
    "requires_confirmation",
    "same_ap_start_position", "same_position", "target_group_leader_remains",
    "unlimited_targets",
})
_NONNEGATIVE_INTEGER_TARGET_RULES = frozenset({
    "distance", "maximum", "minimum", "minimum_steps",
    "pending_attacks_at_least",
})


def _context_value(context, name, default=None):
    if isinstance(context, dict):
        return context.get(name, default)
    return getattr(context, name, default)


def validate_condition(condition, *, path="condition", _depth=0):
    if _depth > 32:
        raise ValueError(f"{path}条件嵌套不能超过32层")
    if not isinstance(condition, dict):
        raise TypeError(f"{path}必须是字典")
    unknown = set(condition) - CONDITION_FIELDS
    if unknown:
        raise ValueError(f"{path}包含未知字段：{sorted(unknown)}")
    for operator in ("all", "any"):
        if operator in condition:
            children = condition[operator]
            if not isinstance(children, list) or not children:
                raise TypeError(f"{path}.{operator}必须是非空条件列表")
            for index, child in enumerate(children):
                validate_condition(child, path=f"{path}.{operator}[{index}]", _depth=_depth + 1)
    if "not" in condition:
        validate_condition(condition["not"], path=f"{path}.not", _depth=_depth + 1)
    condition_id = condition.get("condition_id")
    if condition_id is not None and condition_id not in CONDITION_IDS:
        raise ValueError(f"{path}.condition_id未知：{condition_id}")
    for field in _BOOLEAN_CONDITIONS & set(condition):
        if not isinstance(condition[field], bool):
            raise TypeError(f"{path}.{field}必须是布尔值")
    for field in _INTEGER_CONDITIONS & set(condition):
        value = condition[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise TypeError(f"{path}.{field}必须是非负整数")
    if "actor_type" in condition and not isinstance(condition["actor_type"], str):
        raise TypeError(f"{path}.actor_type必须是字符串")
    for field in ("damage_type", "phase"):
        if field in condition and not isinstance(condition[field], str):
            raise TypeError(f"{path}.{field}必须是字符串")
    for field in ("event_actor", "event_source", "event_target"):
        if field in condition and condition[field] not in {"self", "ally", "enemy"}:
            raise ValueError(f"{path}.{field}必须是self、ally或enemy")
    for field in ("event_value_at_least", "event_value_at_most"):
        if field in condition and (
            isinstance(condition[field], bool)
            or not isinstance(condition[field], Real)
        ):
            raise TypeError(f"{path}.{field}必须是数字")
    if "cooldown_ready" in condition and condition["cooldown_ready"] not in {
        "rest", "escape",
    }:
        raise ValueError(f"{path}.cooldown_ready未知：{condition['cooldown_ready']}")
    for field in ("forbidden_status", "required_status"):
        if field in condition and (
            not isinstance(condition[field], (list, tuple))
            or not all(isinstance(item, str) for item in condition[field])
        ):
            raise TypeError(f"{path}.{field}必须是字符串列表")
    return True


def validate_target_rules(rules, *, path="target_rules"):
    if not isinstance(rules, dict):
        raise TypeError(f"{path}必须是字典")
    unknown = set(rules) - TARGET_RULE_FIELDS
    if unknown:
        raise ValueError(f"{path}包含未知字段：{sorted(unknown)}")
    for field in _BOOLEAN_TARGET_RULES & set(rules):
        if not isinstance(rules[field], bool):
            raise TypeError(f"{path}.{field}必须是布尔值")
    for field in _NONNEGATIVE_INTEGER_TARGET_RULES & set(rules):
        value = rules[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise TypeError(f"{path}.{field}必须是非负整数")
    visibility = rules.get("required_visibility")
    if visibility is not None and visibility not in VISIBILITY_COLLECTIONS:
        raise ValueError(
            f"{path}.required_visibility必须使用标准视野字段："
            f"{sorted(VISIBILITY_COLLECTIONS)}"
        )
    if "allowed_attributes" in rules and (
        not isinstance(rules["allowed_attributes"], (list, tuple))
        or not all(isinstance(item, str) for item in rules["allowed_attributes"])
    ):
        raise TypeError(f"{path}.allowed_attributes必须是字符串列表")
    for field in (
        "maximum_steps_source", "maximum_targets_source", "selection",
    ):
        if field in rules and not isinstance(rules[field], str):
            raise TypeError(f"{path}.{field}必须是字符串")
    if (
        "minimum" in rules and "maximum" in rules
        and rules["minimum"] > rules["maximum"]
    ):
        raise ValueError(f"{path}.minimum不能大于maximum")
    return True


def get_condition_reasons(condition, actor, context=None):
    """返回未满足的标准原因；空列表表示全部条件满足。"""
    validate_condition(condition)
    context = context or {}
    reasons = []
    condition_id = condition.get("condition_id")
    if condition_id == "master_is_none" and getattr(actor, "master", None) is not None:
        reasons.append("master_exists")
    if condition.get("actor_alive") and not actor.is_alive():
        reasons.append("actor_not_alive")
    actor_type = condition.get("actor_type")
    if actor_type and actor.__class__.__name__ != actor_type:
        reasons.append("wrong_actor_type")
    minimum = condition.get("command_spell_at_least")
    if minimum is not None and getattr(actor, "command_spell", 0) < minimum:
        reasons.append("insufficient_command_spell")
    if condition.get("no_command_spell_transfer") and getattr(
        actor, "command_spell_transfer", None,
    ) is not None:
        reasons.append("command_spell_transfer_active")
    effective_battle_state = (
        True if _context_value(context, "virtual_attack_phase", False)
        else actor.in_battle
    )
    if "battle_state" in condition and effective_battle_state != condition["battle_state"]:
        reasons.append("wrong_battle_state")
    if condition.get("position_required") and actor.position is None:
        reasons.append("position_required")
    if condition.get("position_is_building") and (
        actor.position is None or not actor.position.is_building
    ):
        reasons.append("position_is_not_building")
    if condition.get("position_is_port") and (
        actor.position is None or not getattr(actor.position, "is_port", False)
    ):
        reasons.append("position_is_not_port")
    servant_count = condition.get("servant_count")
    if servant_count is not None and len(getattr(actor, "servants", [])) != servant_count:
        reasons.append("servant_count_mismatch")
    game_manager = _context_value(context, "game_manager") or getattr(
        actor, "game_manager", None,
    )
    if condition.get("player_character") and (
        game_manager is None or not game_manager.is_player_character(actor)
    ):
        reasons.append("not_player_character")
    if condition.get("grail_ready") and (
        game_manager is None or not game_manager.holy_grail.ready
    ):
        reasons.append("grail_not_ready")
    if condition.get("at_grail_position") and (
        game_manager is None or actor.position is not game_manager.holy_grail.position
    ):
        reasons.append("not_at_grail_position")
    if "movement_locked" in condition and actor.movement_locked != condition["movement_locked"]:
        reasons.append("movement_locked")
    if condition.get("not_in_travel_group") and getattr(actor, "travel_group", None) is not None:
        reasons.append("already_in_travel_group")
    turn_manager = _context_value(context, "turn_manager")
    phase = _context_value(context, "phase", "")
    if (
        condition.get("no_pending_travel_join")
        and turn_manager is not None
        and phase in {"AP1", "AP2"}
        and turn_manager.has_pending_travel_join(actor, int(phase[-1]))
    ):
        reasons.append("travel_join_already_submitted")
    travel_group = getattr(actor, "travel_group", None)
    if condition.get("travel_group_leader") and (
        travel_group is None or travel_group.leader is not actor
    ):
        reasons.append("not_travel_group_leader")
    turn_number = _context_value(
        context, "turn_number", getattr(actor, "current_global_turn", 0),
    )
    if condition.get("leader_transfer_available") and (
        travel_group is None or travel_group.last_leader_transfer_turn == turn_number
    ):
        reasons.append("leader_transfer_used")
    ride_group = getattr(actor, "ride_group", None) or getattr(actor, "carried_by", None)
    if condition.get("in_ride_group") and ride_group is None:
        reasons.append("not_in_ride_group")
    if condition.get("carry_capacity_available"):
        own_group = getattr(actor, "ride_group", None)
        passenger_count = len(own_group.passengers) if own_group is not None else 0
        if (
            getattr(actor, "carried_by", None) is not None
            or actor.get_carry_capacity() <= passenger_count
        ):
            reasons.append("carry_capacity_unavailable")
    if any(actor.has_status(item) for item in condition.get("forbidden_status", [])):
        reasons.append("forbidden_status")
    if any(not actor.has_status(item) for item in condition.get("required_status", [])):
        reasons.append("required_status_missing")
    minimum = condition.get("attack_phase_count_at_least")
    if minimum is not None and actor.attack_phase_count < minimum:
        reasons.append("attack_phase_unavailable")
    minimum = condition.get("missing_hp_at_least")
    if minimum is not None and actor.hpmax - actor.hp < minimum:
        reasons.append("hp_is_full")
    incoming = _context_value(context, "incoming_attacks", getattr(actor, "pending_attacks", []))
    minimum = condition.get("pending_attacks_at_least")
    if minimum is not None and len(incoming) < minimum:
        reasons.append("no_pending_attacks")
    cooldown = condition.get("cooldown_ready")
    if cooldown == "rest":
        can_start = getattr(actor, "can_start_rest", None)
        if can_start is None or not (getattr(actor, "resting", False) or can_start(turn_number)):
            reasons.append("rest_on_cooldown")
    if cooldown == "escape" and (
        actor.last_escape_turn is not None and turn_number - actor.last_escape_turn < 4
    ):
        reasons.append("escape_on_cooldown")
    if condition.get("required_casting") and getattr(actor, "casting_state", None) is None:
        reasons.append("not_casting")
    if condition.get("release_available"):
        from game.skill.casting import release_options
        if not release_options(actor):
            reasons.append("no_releasable_effect")
    event = _context_value(context, "event") or _context_value(context, "game_event")
    if event is not None:
        for field, actual in {
            "event_actor": event.actor,
            "event_source": event.source,
            "event_target": event.target,
        }.items():
            expected = condition.get(field)
            if expected is None:
                continue
            if expected == "self":
                matched = actual is actor
            elif expected == "ally":
                matched = actual is actor or (
                    actual is not None and actor.is_ally(actual)
                )
            else:
                matched = (
                    actual is not None
                    and actual is not actor
                    and not actor.is_ally(actual)
                )
            if not matched:
                reasons.append(f"{field}_relation_mismatch")
        for field, actual in {
            "event_actor_is_self": event.actor,
            "event_source_is_self": event.source,
            "event_target_is_self": event.target,
        }.items():
            if field in condition and ((actual is actor) != condition[field]):
                reasons.append(f"{field}_mismatch")
        if (
            "damage_type" in condition
            and event.payload.get("damage_type") != condition["damage_type"]
        ):
            reasons.append("damage_type_mismatch")
        if "phase" in condition and event.phase != condition["phase"]:
            reasons.append("phase_mismatch")
        minimum = condition.get("event_value_at_least")
        if minimum is not None and (event.value is None or event.value < minimum):
            reasons.append("event_value_too_small")
        maximum = condition.get("event_value_at_most")
        if maximum is not None and (event.value is None or event.value > maximum):
            reasons.append("event_value_too_large")
    for child in condition.get("all", []):
        reasons.extend(get_condition_reasons(child, actor, context))
    if "any" in condition and not any(
        not get_condition_reasons(child, actor, context) for child in condition["any"]
    ):
        reasons.append("any_condition_failed")
    if "not" in condition and not get_condition_reasons(condition["not"], actor, context):
        reasons.append("negated_condition_matched")
    return list(dict.fromkeys(reasons))


def condition_matches(condition, actor, context=None):
    return not get_condition_reasons(condition or {}, actor, context)


def _effective_position(character, context):
    overrides = _context_value(context, "position_overrides", {}) or {}
    return overrides.get(character, getattr(character, "position", None))


def get_target_rule_reasons(actor, target, rules, context=None, *, target_type=None):
    """对单个目标执行通用规则；候选来源仍由各target类型负责。"""
    validate_target_rules(rules)
    context = context or {}
    reasons = []
    if rules.get("exclude_self") and target is actor:
        reasons.append("self_excluded")
    if rules.get("must_be_alive") and not getattr(target, "is_alive", lambda: False)():
        reasons.append("target_not_alive")
    if rules.get("must_be_hostile") and (
        target is actor or getattr(actor, "is_ally", lambda _target: False)(target)
    ):
        reasons.append("ally_excluded")
    if target_type == "selectable_enemy" and (
        target is actor or getattr(actor, "is_ally", lambda _target: False)(target)
    ):
        reasons.append("not_selectable_enemy")
    if target_type == "selectable_ally" and not (
        target is actor or getattr(actor, "is_ally", lambda _target: False)(target)
    ):
        reasons.append("not_selectable_ally")
    required_visibility = rules.get("required_visibility")
    if required_visibility and target not in getattr(actor, required_visibility):
        reasons.append(f"not_in_{required_visibility}")
    actor_position = _effective_position(actor, context)
    target_position = _effective_position(target, context)
    if rules.get("same_position") and target_position is not actor_position:
        reasons.append("different_position")
    if rules.get("exclude_same_position") and target_position is actor_position:
        reasons.append("same_position_excluded")
    if rules.get("exclude_own_visible") and target in actor.own_visible:
        reasons.append("already_own_visible")
    target_battle_state = rules.get("target_battle_state")
    if (
        target_battle_state is not None
        and not _context_value(context, "virtual_attack_phase", False)
        and getattr(target, "in_battle", None) != target_battle_state
    ):
        reasons.append("wrong_target_battle_state")
    distance = rules.get("distance")
    if distance is not None and get_distance(actor_position, target_position, distance) is None:
        reasons.append("target_out_of_range")
    if target_type == "selectable_map_node":
        if not rules.get("include_roads", False) and isinstance(target, Road):
            reasons.append("road_excluded")
    return list(dict.fromkeys(reasons))


def target_matches_rules(actor, target, rules, context=None, *, target_type=None):
    return not get_target_rule_reasons(
        actor, target, rules or {}, context, target_type=target_type,
    )


def validate_target_count(targets, rules, *, path="targets"):
    count = len(targets)
    if count < rules.get("minimum", 0):
        raise ValueError(f"{path}数量少于minimum")
    maximum = rules.get("maximum")
    if maximum is not None and count > maximum:
        raise ValueError(f"{path}数量大于maximum")
    return True
