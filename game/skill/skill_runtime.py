"""技能条件、触发关键词和效果关键词的统一运行入口。"""

from copy import deepcopy
from itertools import count
import random

from game.action.action_rules import (
    condition_matches,
    target_matches_rules,
    validate_target_count,
)
from game.skill.input_runtime import (
    collect_skill_inputs,
    component_input_reasons,
    resolve_input_expressions,
)

from game.modifier.modifier import create_modifier
from game.skill.class_skill_data import CLASS_SKILL_DATA
from game.skill.effect_validation import (
    validate_component_effects,
    validate_effect_registry,
)
from game.skill.skill import Skill
from game.turn.damage import AttackProfile, DamageEvent, DamageResolver
from game.turn.damage_types import normalize_damage_type
from game.turn.roll import RollResolver
from game.turn.decision import (
    DecisionOption,
    DecisionRequest,
    TerminalDecisionProvider,
)
from game.skill.survival_runtime import resolve_prevent_death_effect


class SkillUnavailableError(ValueError):
    """技能或技能组件在当前状态下不能发动。"""


class PaidCosts(dict):
    """Public cost totals plus private refundable payment ledgers."""

    def __init__(self, *args, ledgers=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.ledgers = dict(ledgers or {})
        self.refunded_resources = set()


_SKILL_APPLICATION_SEQUENCE = count()


def apply_modifier_effect(
    effect,
    target,
    skill,
    **context,
):
    modifier = create_modifier(
        deepcopy(effect),
        target,
        source=skill,
        source_actor=context.get("actor"),
        source_type=getattr(skill, "source_type", "skill"),
        source_id=f"{skill.skill_id}:{skill.rank_name}",
        applied_turn=context.get("turn_number"),
        applied_phase=context.get("phase"),
    )
    if modifier.polarity == "buff":
        component_id = context.get("skill_component_id")
        modifier.buff_skill_id = (
            f"{skill.skill_id}:{component_id}"
            if component_id is not None
            else skill.skill_id
        )
        application_id = context.get("skill_application_id")
        if application_id is None:
            application_id = next(_SKILL_APPLICATION_SEQUENCE)
        modifier.buff_application_id = application_id
    return target.add_modifier(modifier)


def resolve_order_change_effect(effect, target, skill, **context):
    """Queue a neutral order operation for the next formal battle round.

    ``subject`` and ``anchor`` are selectors whose supported values are
    ``actor`` and ``target``.  This lets a normal one-target skill express
    both "move myself before the selected target" and "move the selected
    target before me" without storing unstable numeric positions.
    """
    data = effect.get("effect_data", {})
    if "duration" not in data:
        raise ValueError("order_change必须由效果提供duration")

    actor = context.get("actor") or target
    objects = {
        "actor": actor,
        "target": target,
    }
    subject_selector = data.get("subject", "target")
    if subject_selector not in objects:
        raise ValueError("order_change的subject必须是'actor'或'target'")
    subject = objects[subject_selector]

    operation = data.get("operation")
    anchor = None
    if operation in {"move_before", "move_after"}:
        anchor_selector = data.get("anchor")
        if anchor_selector not in objects:
            raise ValueError(
                "move_before和move_after的anchor必须是'actor'或'target'"
            )
        anchor = objects[anchor_selector]

    battle = getattr(subject, "current_battle", None)
    if (
        battle is None
        or battle.ended
        or not getattr(subject, "in_battle", False)
    ):
        raise SkillUnavailableError("order_change只能影响正式战斗")
    if anchor is not None and getattr(anchor, "current_battle", None) is not battle:
        raise SkillUnavailableError("order_change的subject与anchor必须属于同一场战斗")

    return battle.queue_order_change(
        operation,
        subject,
        anchor=anchor,
        duration=data["duration"],
        source=skill,
    )


def resolve_modify_event_value_effect(effect, target, skill, **context):
    event = context.get("game_event") or context.get("event")
    if event is None:
        raise SkillUnavailableError("modify_event_value只能在事件结算中使用")
    data = effect.get("effect_data", {})
    return event.modify_value(
        data.get("operation", "add"),
        data.get("value", 0),
        minimum=data.get("minimum"),
        maximum=data.get("maximum"),
    )


def resolve_grant_temporary_mp_effect(effect, target, skill, **context):
    data = effect.get("effect_data", {})
    value = data.get("value", 0)
    if data.get("value_source") == "event_value":
        event = context.get("game_event") or context.get("event")
        if event is None or event.value is None:
            raise SkillUnavailableError("临时MP效果缺少事件数值")
        value = event.value
    value = int(value * data.get("multiplier", 1) + data.get("flat", 0))
    if value <= 0:
        return 0
    before = target.temporary_mp
    target.grant_temporary_mp(value)
    return target.temporary_mp - before


def resolve_perception_check_effect(effect, target, skill, **context):
    """Run normal perception contests against concealed characters in a scope."""
    from game.map.map import get_area_positions

    actor = context.get("actor") or target
    manager = getattr(actor, "game_manager", None)
    if manager is None:
        raise SkillUnavailableError("感知效果需要已加入游戏的角色")
    data = effect.get("effect_data", {})
    scope = data.get("scope", "current_area")
    if scope == "current_area":
        nodes = set(get_area_positions(actor.position))
    elif scope == "source_field":
        nodes = set(getattr(skill, "covered_nodes", ()))
    else:
        raise ValueError(f"未知的感知范围：{scope}")
    attempts = int(data.get("attempts", 1))
    checks = []
    detected = []
    for candidate in manager.characters:
        if (
            candidate is actor
            or not candidate.is_alive()
            or candidate.position not in nodes
            or not candidate.is_concealed_from(actor)
        ):
            continue
        success = False
        attempt_results = []
        if candidate.blocks_perception_while_actively_hidden():
            attempt_results.append({"success": False, "blocked_by": "presence_concealment"})
        else:
            for _index in range(attempts):
                perceive_die = random.randint(1, 10)
                hide_die = random.randint(1, 10)
                perceive_total = perceive_die + actor.perceive
                hide_total = hide_die + candidate.hide
                current = hide_total <= perceive_total
                attempt_results.append({
                    "perceive_die": perceive_die,
                    "hide_die": hide_die,
                    "perceive_total": perceive_total,
                    "hide_total": hide_total,
                    "success": current,
                })
                success = success or current
        checks.append({
            "target": candidate,
            "attempts": attempt_results,
            "success": success,
        })
        if success:
            if candidate not in actor.own_perceived:
                actor.own_perceived.append(candidate)
            candidate.reveal_hidden_to(actor)
            candidate.reveal_presence_to(actor)
            detected.append(candidate)
    actor.update_visibility(manager.characters)
    return {"checks": checks, "detected": detected}


def resolve_switch_skill_set_effect(effect, target, skill, **context):
    """Switch one named, mutually-exclusive skill bundle while retaining cooldowns."""
    data = effect.get("effect_data", {})
    actor = context.get("actor") or target
    group_id = data["group_id"]
    set_id = data["set_id"]
    skill_ids = tuple(data.get("skill_ids", ()))
    runtime = getattr(actor, "switchable_skill_sets", None)
    if runtime is None:
        runtime = {}
        actor.switchable_skill_sets = runtime
    group = runtime.setdefault(group_id, {
        "current": None,
        "sets": {},
    })
    if group["current"] == set_id:
        return {"group_id": group_id, "set_id": set_id, "changed": False}

    from game.skill.content_registry import load_content

    current = group.get("current")
    if current is not None:
        for old_skill in group["sets"].get(current, []):
            if old_skill in actor.personal_skills:
                remove_personal_skill(
                    actor, old_skill, reason="switch_skill_set", emit=False,
                )

    cached = group["sets"].get(set_id)
    if cached is None:
        cached = [load_content(actor, "personal_skill", skill_id) for skill_id in skill_ids]
        group["sets"][set_id] = cached
    else:
        for cached_skill in cached:
            cached_skill.removed = False
            actor.personal_skills.append(cached_skill)
            _apply_passive_skill_components(actor, cached_skill, phase="skill_set_restored")
    group["current"] = set_id
    return {
        "group_id": group_id,
        "set_id": set_id,
        "changed": True,
        "skills": list(cached),
    }


def resolve_cancel_event_effect(effect, target, skill, **context):
    event = context.get("game_event") or context.get("event")
    if event is None:
        raise SkillUnavailableError("cancel_event只能在事件结算中使用")
    return event.cancel(effect.get("effect_data", {}).get("reason"))


def resolve_change_damage_type_effect(effect, target, skill, **context):
    game_event = context.get("game_event") or context.get("event")
    if (
        game_event is None
        or getattr(game_event, "event_type", None) != "before_damage"
        or getattr(game_event, "timing", None) != "before"
    ):
        raise SkillUnavailableError(
            "change_damage_type只能在before_damage的before时机使用"
        )
    damage_event = game_event.payload.get("damage_event")
    if damage_event is None or not hasattr(damage_event, "damage_type"):
        raise SkillUnavailableError("当前事件没有可修改的伤害类型")

    previous = damage_event.damage_type
    current = normalize_damage_type(
        effect.get("effect_data", {})["damage_type"]
    )
    damage_event.damage_type = current
    game_event.payload["damage_type"] = current
    recalculated = DamageResolver().calculate(damage_event)
    damage_event.calculated_value = recalculated
    game_event.value = game_event.replay_value_operations(recalculated)
    return {
        "damage_event": damage_event,
        "previous_damage_type": previous,
        "damage_type": current,
        "value": game_event.value,
    }


SKILL_MUTATION_EFFECT_TYPES = {"add_skill", "remove_skill"}


def resolve_skill_mutation_effect(effect, target, skill, **context):
    batches = context.get("skill_mutation_batches") or {
        target: [effect]
    }
    state = context.get("skill_mutation_state")
    if state is None:
        state = {}
    key = id(target)
    if key in state:
        return {
            "skipped": True,
            "reason": "committed_in_skill_mutation_transaction",
            "transaction": state[key],
        }
    result = execute_skill_mutation_transaction(
        target,
        batches.get(target, [effect]),
        source_skill=skill,
        actor=context.get("actor"),
        turn_number=context.get("turn_number"),
        phase=context.get("phase"),
    )
    state[key] = result
    return result


def resolve_growing_effect(effect, target, skill, **context):
    from game.skill.growth_runtime import apply_growth_effect

    return apply_growth_effect(effect, target, skill, **context)


def resolve_add_action_effect(effect, target, skill, **context):
    from game.action.dynamic_action import grant_dynamic_action

    data = effect["effect_data"]
    definition = deepcopy(data["action_definition"])
    definition.setdefault("resolution_timing", "immediate")
    definition.setdefault("target", "self")
    definition.setdefault("target_rules", {})
    definition.setdefault("condition", {})
    definition.setdefault("cost", [])
    definition.setdefault("effects", [])
    definition.setdefault("choices", None)
    if definition["choices"] is None:
        definition.pop("choices")
    definition.setdefault("display_order", 50)
    definition.setdefault("action_type", "special")
    definition.setdefault("description", "")

    component = deepcopy(definition)
    component["component_id"] = f"dynamic_action:{definition['action_id']}"
    component["type"] = "active"
    validate_skill_components(
        [component],
        path=f"add_action:{definition['action_id']}",
        label="动态行动",
    )
    return grant_dynamic_action(
        target,
        skill,
        definition,
        duration=data.get("duration"),
        duplicate_policy=data.get("duplicate_policy", "reject"),
        applied_turn=(
            context.get("turn_number")
            or getattr(target, "current_global_turn", 0)
        ),
        remove_with_source=data.get("remove_with_source", True),
    )


def _modifier_choice_label(modifier):
    name = getattr(modifier, "name", None) or modifier.modifier_id
    source = getattr(modifier.source, "name", None)
    if source is None:
        source = modifier.source_id or modifier.source_type or "未知来源"
    duration = "永久" if modifier.duration is None else str(modifier.duration)
    return (
        f"{name}（来源：{source}；层数：{modifier.stack_count}；"
        f"剩余：{duration}）"
    )


def resolve_purify_effect(effect, target, skill, **context):
    data = effect.get("effect_data", {})
    maximum = data.get("maximum", 1)
    if maximum != "all" and (
        not isinstance(maximum, int)
        or isinstance(maximum, bool)
        or maximum < 1
    ):
        raise ValueError("purify的maximum必须是正整数或'all'")
    candidates = target.get_purifiable_modifiers()
    if not candidates:
        return []

    selected = context.get("selected_modifiers")
    if selected is not None:
        return target.purify_modifiers(selected, maximum=maximum)
    if maximum == "all" or len(candidates) <= maximum:
        return target.purify_modifiers(candidates, maximum=maximum)

    decision_provider = context.get("decision_provider")
    if decision_provider is None:
        decision_provider = TerminalDecisionProvider()
    actor = context.get("actor") or target
    selected = []
    remaining = list(candidates)
    selection_count = min(maximum, len(remaining))
    for index in range(selection_count):
        request = DecisionRequest(
            character=actor,
            phase=context.get("phase", "技能效果选择"),
            prompt=(
                f"请选择要从{target.name}身上净化的效果"
                f"（{index + 1}/{selection_count}）。"
            ),
            options=tuple(
                DecisionOption(_modifier_choice_label(modifier), modifier)
                for modifier in remaining
            ),
        )
        chosen = decision_provider.choose(request)
        selected.append(chosen)
        remaining.remove(chosen)
    return target.purify_modifiers(selected, maximum=maximum)


def resolve_add_resource_effect(effect, target, skill, **_context):
    data = deepcopy(effect.get("effect_data", {}))
    return target.add_resource(
        data,
        source=skill,
        source_type=getattr(skill, "source_type", "skill"),
        source_id=f"{skill.skill_id}:{skill.rank_name}",
    )


def _resource_change_data(effect):
    data = effect.get("effect_data", {})
    resource_id = data.get("resource_id")
    if not resource_id:
        raise ValueError("资源变化效果必须提供resource_id")
    if "value" not in data:
        raise ValueError("资源变化效果必须提供value")
    return data, resource_id


def resolve_gain_resource_effect(effect, target, skill, **context):
    data, resource_id = _resource_change_data(effect)
    return target.gain_resource(resource_id, data["value"])


def resolve_modify_resource_effect(effect, target, skill, **context):
    data, resource_id = _resource_change_data(effect)
    return target.modify_resource(
        resource_id,
        data.get("operation", "add"),
        data["value"],
    )


def _recover_resource_id(data):
    resource_id = data.get("resource_id")
    if not resource_id:
        raise ValueError("recover_resource必须提供resource_id")
    return resource_id


def _recover_effect_value(data, context):
    value_source = data.get("value_source")
    if value_source is None:
        if "value" not in data:
            raise ValueError("recover_resource必须提供value或value_source")
        return data["value"]
    if value_source in context:
        return context[value_source]
    if value_source == "actual_mp_cost":
        return context.get("paid_costs", {}).get("mp", 0)
    raise ValueError(f"recover_resource缺少数值来源：{value_source}")


def resolve_recover_resource_effect(effect, target, skill, **context):
    data = effect.get("effect_data", {})
    resource_id = _recover_resource_id(data)
    value = _recover_effect_value(data, context)
    calculation = data.get("calculation", "flat")
    if calculation in {"maximum_percentage", "maximum_ratio"}:
        maximum = target.get_resource_maximum(resource_id)
        if maximum is None:
            raise ValueError(
                f"没有maximum的资源{resource_id}不能按上限比例回复"
            )
        value = maximum * value
    elif calculation != "flat":
        raise ValueError(f"未知的资源回复计算方式：{calculation}")
    return target.recover_resource(resource_id, value)


def _damage_effect_value(data, actor, target, context):
    if "value" in data:
        value = data["value"]
    else:
        value_source = data.get("value_source")
        if not value_source:
            raise ValueError("damage必须提供value或value_source")
        if value_source in context:
            value = context[value_source]
        elif value_source in {"actor_attribute", "target_attribute"}:
            attribute = data.get("attribute")
            if not attribute:
                raise ValueError(
                    f"{value_source}必须同时提供attribute"
                )
            source = actor if value_source == "actor_attribute" else target
            if not hasattr(source, attribute):
                raise ValueError(f"伤害数值来源不存在属性：{attribute}")
            value = getattr(source, attribute)
            # AttributeRank/FixedRank等等级对象使用其当前有效数值。
            value = getattr(value, "value", value)
        else:
            raise ValueError(f"damage缺少数值来源：{value_source}")

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("damage的伤害值必须是数字")
    multiplier = data.get("multiplier", 1)
    flat = data.get("flat", 0)
    for field_name, adjustment in (
        ("multiplier", multiplier),
        ("flat", flat),
    ):
        if isinstance(adjustment, bool) or not isinstance(
            adjustment,
            (int, float),
        ):
            raise TypeError(f"damage的{field_name}必须是数字")
    value = value * multiplier + flat
    if value < 0:
        raise ValueError("damage的基础伤害不能小于0")
    return value


def resolve_damage_effect(effect, target, skill, **context):
    data = effect.get("effect_data", {})
    damage_type = data.get("damage_type")
    if not damage_type:
        raise ValueError("damage必须提供damage_type")
    actor = context.get("actor") or target
    value = _damage_effect_value(data, actor, target, context)
    from game.skill.casting import noble_damage_multiplier
    value *= noble_damage_multiplier(skill)
    skill_id = data.get("skill_id", getattr(skill, "skill_id", None))
    action_id = data.get(
        "action_id",
        context.get("action_id", f"skill:{skill_id}"),
    )
    source_tags = set(data.get("source_tags", []))
    source_tags.add("skill")
    if getattr(skill, "source_type", None) == "noble_phantasm":
        source_tags.add("noble_phantasm")
    event = DamageEvent(
        source=actor,
        target=target,
        value=value,
        damage_type=damage_type,
        is_hidden=data.get("is_hidden", False),
        skill=skill,
        percentage_modifiers=list(data.get("percentage_modifiers", [])),
        flat_modifiers=list(data.get("flat_modifiers", [])),
        action_id=action_id,
        skill_id=skill_id,
        source_tags=source_tags,
        ignore_shield=data.get("ignore_shield", False),
    )
    modifier_manager = getattr(actor, "modifier_manager", None)
    if modifier_manager is not None:
        percentages, flats = modifier_manager.get_damage_adjustments(
            "outgoing",
            event.damage_type,
            action_id=event.action_id,
            skill_id=event.skill_id,
            source_tags=event.source_tags,
        )
        event.percentage_modifiers.extend(percentages)
        event.flat_modifiers.extend(flats)

    was_in_brink = target.has_status("brink_of_death")
    final_damage = DamageResolver().resolve(
        event,
        decision_provider=context.get("decision_provider"),
    )
    return {
        "event": event,
        "damage": final_damage,
        "entered_brink_of_death": (
            not was_in_brink and target.has_status("brink_of_death")
        ),
        "target_defeated": not target.is_alive(),
    }


def resolve_create_field_effect(effect, target, skill, **context):
    from game.skill.field_runtime import FieldEffect

    actor = context.get("actor") or target
    game_manager = getattr(actor, "game_manager", None)
    if game_manager is None:
        raise ValueError("create_field需要已加入游戏的创建者")
    data = deepcopy(effect.get("effect_data", {}))
    if "selected_targets" not in data:
        data["selected_targets"] = list(context.get("effect_targets", []))
    center_rule = data.pop("center_rule", None)
    if data.get("center") is None:
        data["center"] = (
            actor.position if center_rule == "actor_position"
            else getattr(target, "position", None) or actor.position
        )
    field = FieldEffect(
        data,
        actor,
        skill,
        turn_number=context.get("turn_number", 0),
    )
    if getattr(field.center, "is_reality_marble_interior", False):
        return {
            "created": False,
            "reason": "reality_marble_forbids_field",
            "field": field,
            "refunded_mp": 0,
        }
    if not field.validate_location_requirements():
        return {
            "created": False,
            "reason": "location_requirements_failed",
            "field": field,
            "refunded_mp": 0,
        }
    conflict = next((
        existing
        for existing in game_manager.field_manager.fields
        if (
            not existing.removed
            and not field.replaces(existing)
            and field.conflicts_with(existing)
        )
    ), None)
    if conflict is not None:
        paid = context.get("paid_costs")
        refunded = 0
        refunded_resources = getattr(paid, "refunded_resources", set())
        if paid is not None and "mp" not in refunded_resources:
            ledger = getattr(paid, "ledgers", {}).get("mp", [])
            refunded = sum(
                item["refunded"]
                for item in actor.refund_mp_ledger(ledger)
            )
            refunded_resources.add("mp")
        return {
            "created": False,
            "reason": "center_occupied",
            "blocking_field": conflict,
            "field": field,
            "refunded_mp": refunded,
        }
    created = game_manager.create_field(field)
    return {
        "created": bool(created),
        "reason": None if created else "registration_failed",
        "field": field,
        "refunded_mp": 0,
    }


def resolve_observe_location_effect(effect, target, skill, **context):
    actor = context.get("actor")
    game_manager = getattr(actor, "game_manager", None)
    if game_manager is None:
        raise ValueError("observe_location需要已加入游戏的施术者")
    ap_layer = context.get("ap_layer")
    if ap_layer is None:
        phase = str(context.get("phase", ""))
        if phase.startswith("AP1"):
            ap_layer = 1
        elif phase.startswith("AP2"):
            ap_layer = 2
        else:
            ap_layer = game_manager.turn_manager.current_ap_layer
    observation = game_manager.observation_manager.create(
        actor,
        target,
        context.get("turn_number", game_manager.turn_manager.turn),
        ap_layer,
    )
    occupants = observation.visible_characters(game_manager.characters)
    reports = []
    recipients = actor.get_shared_vision_group()
    for character in occupants:
        from game.skill.observation_runtime import character_class_name

        report = {
            "type": "insight_occupant",
            "turn": observation.turn_number,
            "ap_layer": observation.ap_layer,
            "observer": actor,
            "character": character,
            "class_name": character_class_name(character),
            "position": character.position,
            "recipients": list(recipients),
        }
        for recipient in recipients:
            recipient.insight_reports.append(report)
        reports.append(report)
        print(
            f"洞悉：{character.name}（{report['class_name']}）位于"
            f"{character.position.name}。"
        )
    game_manager.turn_manager.update_visibility()
    return {
        "observation": observation,
        "occupants": occupants,
        "reports": reports,
    }


def resolve_trap_effect(effect, target, skill, **context):
    actor = context.get("actor")
    game_manager = getattr(actor, "game_manager", None)
    if game_manager is None:
        raise ValueError("trap需要已加入游戏的设置者")
    if target is not actor.position:
        raise ValueError("trap只能设置在施术者当前节点")
    position = target
    data = effect.get("effect_data", {})
    trap = game_manager.trap_manager.register(
        actor,
        position,
        base_damage=data.get("base_damage", 30),
        share_knowledge=data.get("share_knowledge", True),
        skill=skill,
        trap_id=data.get("trap_id"),
    )
    return {"trap": trap, "created": True}


def resolve_summon_effect(effect, target, skill, **context):
    actor = context.get("actor")
    game_manager = getattr(actor, "game_manager", None)
    if game_manager is None:
        raise ValueError("summon需要已加入游戏的召唤者")
    data = effect.get("effect_data", {})
    placement_rule = data.get("placement_rule", "current_position")
    if placement_rule == "current_position":
        position = actor.position
    else:
        position = target
        if not hasattr(position, "connected_locations"):
            position = getattr(target, "position", None)
    return game_manager.summon_manager.summon(
        actor,
        data["template_id"],
        position,
        skill=skill,
        count=data.get("count", 1),
        duration=data.get("duration"),
        maximum_active=data.get("maximum_active"),
        limit_scope=data.get("limit_scope", "template"),
        at_limit=data.get("at_limit", "reject"),
        activate_immediately=data.get("activate_immediately", False),
        remove_with_source=data.get("remove_with_source", True),
        name_prefix=data.get("name_prefix"),
        decision_provider=context.get("decision_provider"),
    )


def resolve_deploy_reality_marble_effect(effect, target, skill, **context):
    from game.skill.reality_marble_runtime import RealityMarble

    actor = context.get("actor") or target
    game_manager = getattr(actor, "game_manager", None)
    if game_manager is None:
        raise ValueError("deploy_reality_marble需要已加入游戏的创建者")
    raw_data = effect.get("effect_data", {})
    entrance = raw_data.get("entrance")
    selected_targets = list(raw_data.get("selected_targets", []))
    data = deepcopy(raw_data)
    if entrance is not None:
        data["entrance"] = entrance
    data["selected_targets"] = selected_targets
    data.setdefault("entrance", actor.position)
    marble = RealityMarble(
        data,
        actor,
        skill,
        turn_number=context.get("turn_number", 0),
    )
    if game_manager.deploy_reality_marble(marble):
        return {
            "created": True,
            "reason": None,
            "reality_marble": marble,
            "captured_characters": list(marble.captured_characters),
            "refunded_mp": 0,
        }

    paid = context.get("paid_costs")
    refunded = 0
    refunded_resources = getattr(paid, "refunded_resources", set())
    if paid is not None and "mp" not in refunded_resources:
        ledger = getattr(paid, "ledgers", {}).get("mp", [])
        refunded = sum(
            item["refunded"]
            for item in actor.refund_mp_ledger(ledger)
        )
        refunded_resources.add("mp")
    return {
        "created": False,
        "reason": "reality_marble_unavailable",
        "reality_marble": marble,
        "captured_characters": [],
        "refunded_mp": refunded,
    }


def build_attack_profile_from_effect(effect, skill, target=None, **context):
    """Generate a skill attack without assigning or queuing a target."""
    data = effect.get("effect_data", {})
    actor = context.get("actor")
    if actor is None:
        raise ValueError("create_attack_event缺少攻击者")
    casting = getattr(skill, "casting", {}) or {}
    noble_type = casting.get("noble_phantasm_type")
    default_attack_stat = (
        "magic_attack" if noble_type == "magic" else "physical_attack"
    )
    default_damage_type = "magic" if noble_type == "magic" else "physical"
    roll_profile = casting.get("roll_profile", "default")
    custom_roll = roll_profile if isinstance(roll_profile, dict) else {}
    attack_stat = data.get(
        "attack_stat",
        custom_roll.get("attribute", default_attack_stat),
    )
    if not hasattr(actor, attack_stat):
        raise ValueError(f"未知的攻击骰属性：{attack_stat}")

    stat_value = getattr(actor, attack_stat)
    stat_value = getattr(stat_value, "value", stat_value)
    stat_multiplier = data.get(
        "attack_stat_multiplier",
        custom_roll.get("multiplier", 1),
    )
    stat_flat = data.get(
        "attack_stat_flat",
        custom_roll.get("flat", 0),
    )
    situational_bonus = (
        stat_value * (stat_multiplier - 1)
        + stat_flat
        + data.get("attack_roll_bonus", 0)
    )
    for_offset = context.get("for_offset", False)
    skill_id = data.get("skill_id", getattr(skill, "skill_id", None))
    action_id = data.get(
        "action_id",
        context.get("action_id", f"skill:{skill_id}"),
    )
    damage_type = normalize_damage_type(
        data.get("damage_type", default_damage_type)
    )
    source_tags = set(data.get("source_tags", []))
    source_tags.add("skill")
    if getattr(skill, "source_type", None) == "noble_phantasm":
        source_tags.add("noble_phantasm")
    if for_offset:
        source_tags.add("offset")
    modifier_context = {
        "actor": actor,
        "source": skill,
        "target": target,
        "phase": context.get("phase"),
        "action_id": action_id,
        "skill_id": skill_id,
        "component_id": context.get("skill_component_id"),
        "damage_type": damage_type,
        "tags": source_tags,
    }
    shared_rolls = context.get("shared_attack_rolls")
    shared_roll_key = id(effect)
    roll_result = None if for_offset else (
        shared_rolls.get(shared_roll_key)
        if shared_rolls is not None
        else None
    )
    if roll_result is None and not for_offset:
        roll_result = RollResolver().roll(
            actor,
            attack_stat,
            decision_provider=context.get("decision_provider"),
            phase="攻击—幸运",
            situational_bonus=situational_bonus,
            initial_die=data.get("initial_die"),
            roller=lambda: random.randint(1, 10),
            modifier_context=modifier_context,
        )
        if shared_rolls is not None:
            shared_rolls[shared_roll_key] = roll_result

    raw_segments = data.get("damage_segments")
    if raw_segments is not None:
        if not isinstance(raw_segments, (list, tuple)) or not raw_segments:
            raise ValueError("damage_segments必须是非空列表")
        damage_segments = list(raw_segments)
        damage_value = sum(damage_segments)
    else:
        damage_data = deepcopy(data)
        if "damage_value" in damage_data:
            damage_data["value"] = damage_data["damage_value"]
        if (
            damage_data.get("value_source") == "target_attribute"
            and target is None
        ):
            raise SkillUnavailableError("该攻击的伤害依赖具体目标")
        damage_segments = None

    if raw_segments is None and (
        "value" not in damage_data and "value_source" not in damage_data
    ):
        if (
            getattr(skill, "source_type", None) == "noble_phantasm"
            and noble_type == "magic"
        ):
            from game.skill.casting import MAGIC_NOBLE_PHANTASM_DAMAGE

            try:
                damage_value = MAGIC_NOBLE_PHANTASM_DAMAGE[skill.rank_name]
            except KeyError as error:
                raise ValueError(
                    f"没有定义{skill.rank_name}级魔术宝具的固定伤害"
                ) from error
        elif getattr(skill, "source_type", None) == "noble_phantasm":
            raise ValueError("物理宝具必须在录卡时定义damage_value")
        else:
            damage_value = actor.get_effective_atk(modifier_context)
    elif raw_segments is None:
        damage_value = _damage_effect_value(
            damage_data,
            actor,
            target,
            context,
        )
    from game.skill.casting import noble_damage_multiplier
    damage_multiplier = noble_damage_multiplier(skill)
    damage_value *= damage_multiplier
    if damage_segments is not None:
        damage_segments = [value * damage_multiplier for value in damage_segments]
    percentages, flats = actor.modifier_manager.get_damage_adjustments(
        "outgoing",
        damage_type,
        action_id=action_id,
        skill_id=skill_id,
        source_tags=source_tags,
        context=modifier_context,
    )
    command_spell_bonus = 0
    if context.get("command_spell_bonus_effect_id") == id(effect):
        command_spell_bonus = context.get("command_spell_damage_bonus", 0)
    source_type = getattr(skill, "source_type", None)
    default_channel = (
        "release"
        if source_type in {"magic", "noble_phantasm"}
        else "attack"
    )
    profile = AttackProfile(
        source=actor,
        value=damage_value,
        damage_type=damage_type,
        attack_roll=None if roll_result is None else roll_result.total,
        attack_die=None if roll_result is None else roll_result.die,
        attack_roll_bonus=data.get("attack_roll_bonus", 0),
        skill=skill,
        percentage_modifiers=(
            list(data.get("percentage_modifiers", [])) + percentages
        ),
        flat_modifiers=(
            list(data.get("flat_modifiers", []))
            + flats
            + ([command_spell_bonus] if command_spell_bonus else [])
        ),
        action_id=action_id,
        skill_id=skill_id,
        source_tags=source_tags,
        ignore_shield=data.get("ignore_shield", False),
        target_lock=data.get("target_lock", False),
        ignore_block=data.get("ignore_block", False),
        roll_result=roll_result,
        resolution_channel=data.get(
            "resolution_channel",
            context.get("resolution_channel", default_channel),
        ),
        damage_segments=damage_segments,
    )
    profile.modifier_context = {**modifier_context, "event": profile}
    if not context.get("defer_attack_commit_consumption", False):
        actor.modifier_manager.consume_event(
            "attack_committed",
            profile.modifier_context,
        )
    return profile


def resolve_create_attack_event_effect(effect, target, skill, **context):
    profile = build_attack_profile_from_effect(
        effect,
        skill,
        target=target,
        **context,
    )
    attack = profile.assign_target(target)
    declared_positions = context.get("declared_target_positions", {})
    if (
        target in declared_positions
        and target.position is not declared_positions[target]
        and not attack.target_lock
    ):
        attack.miss_because_target_moved()
    else:
        manager = getattr(profile.source, "game_manager", None)
        relationships = getattr(manager, "relationship_manager", None)
        if relationships is not None:
            relationships.resolve_attack_attitude(
                profile.source,
                target,
                context.get("decision_provider"),
            )
        target.pending_attacks.append(attack)
    return attack


def _active_battle(character):
    battle = getattr(character, "current_battle", None)
    if battle is None or getattr(battle, "ended", False):
        return None
    return battle


def _register_skill_created_battle(battle, attacker):
    manager = getattr(attacker, "game_manager", None)
    turn_manager = getattr(manager, "turn_manager", None)
    if turn_manager is not None and battle not in turn_manager.battles:
        turn_manager.battles.append(battle)


def _get_simple_round_battle(attacker, defenders, *, enter_battle):
    """Return a formal shared battle or an isolated simple-round resolver."""
    from game.turn.battle import BattleManager

    characters = list(dict.fromkeys([attacker, *defenders]))
    active_battles = list(dict.fromkeys(
        battle
        for battle in (_active_battle(character) for character in characters)
        if battle is not None
    ))

    if enter_battle:
        if len(active_battles) > 1:
            raise SkillUnavailableError("不能用一次简易战斗轮合并两场战斗")
        positions = {character.position for character in characters}
        if None in positions or len(positions) != 1:
            raise SkillUnavailableError("进入正式战斗的角色必须位于同一地图节点")
        if active_battles:
            battle = active_battles[0]
            battle.add_participants(characters)
            for defender in defenders:
                battle.add_combat_link(
                    attacker,
                    defender,
                    source="add_simple_round",
                )
        else:
            battle = BattleManager(characters, auto_link=False)
            for defender in defenders:
                battle.add_combat_link(
                    attacker,
                    defender,
                    source="add_simple_round",
                )
            battle.start_battle()
            _register_skill_created_battle(battle, attacker)
        battle.refresh_participant_order()
        return battle

    if (
        len(active_battles) == 1
        and all(character in active_battles[0].participants for character in characters)
    ):
        return active_battles[0]
    return BattleManager(characters, auto_link=False)


def resolve_add_simple_round_effect(effect, target, skill, **context):
    """Bridge a skill effect into the existing multi-defender round engine."""
    data = effect.get("effect_data", {})
    all_targets = list(context.get("effect_targets") or [target])
    attacker = (
        target
        if data.get("attacker_rule", "actor") == "target"
        else context.get("actor")
    )
    if attacker is None:
        raise ValueError("add_simple_round缺少攻击方")

    defender_rule = data.get("defender_rule", "all_targets")
    if defender_rule == "actor":
        defenders = [context.get("actor")]
    elif defender_rule == "target":
        defenders = [target]
    else:
        defenders = all_targets
    defenders = [
        defender
        for defender in dict.fromkeys(defenders)
        if defender is not None and defender is not attacker and defender.is_alive()
    ]
    if not defenders:
        raise SkillUnavailableError("add_simple_round没有存活的合法防守方")

    grouped_results = context.setdefault("grouped_effect_results", {})
    group_key = id(effect)
    if defender_rule == "all_targets" and group_key in grouped_results:
        return {
            "skipped": True,
            "reason": "grouped_with_previous_target",
            "simple_round": grouped_results[group_key],
        }
    effect_definition = deepcopy(effect)
    runtime_data = effect_definition["effect_data"]
    runtime_data.setdefault("trigger_phase", "immediate")
    runtime_data["targets"] = defenders
    runtime_data["skill"] = skill
    runtime_data.setdefault("source", getattr(skill, "skill_id", skill))
    decision_provider = context.get("decision_provider")
    if runtime_data["trigger_phase"] == "immediate" and decision_provider is None:
        raise ValueError("即时add_simple_round需要DecisionProvider处理攻击与防御选择")
    battle = _get_simple_round_battle(
        attacker,
        defenders,
        enter_battle=runtime_data.get("enter_battle", False),
    )
    if runtime_data.get("enter_battle", False):
        manager = getattr(attacker, "game_manager", None)
        relationships = getattr(manager, "relationship_manager", None)
        if relationships is not None:
            for defender in defenders:
                if not attacker.is_ally(defender):
                    relationships.force_mutual_hostile(attacker, defender)
    simple_round = battle.add_effect(
        effect_definition,
        attacker,
        defenders,
    )
    if simple_round.trigger_phase == "immediate":
        result = battle.resolve_simple_round(simple_round, decision_provider)
    else:
        if not battle.started:
            raise SkillUnavailableError(
                "延迟简易战斗轮必须依附于正式战斗，或设置enter_battle=true"
            )
        result = simple_round
    if defender_rule == "all_targets":
        grouped_results[group_key] = result
    return result


def _restorable_components(target, data, source_skill=None, **context):
    from game.skill.component_runtime import component_use_count, get_component_state

    candidates = []
    turn_number = context.get(
        "turn_number", getattr(target, "current_global_turn", 0)
    )
    battle = context.get("battle") or getattr(target, "current_battle", None)
    skill_ids = set(data.get("skill_ids", []))
    component_ids = set(data.get("component_ids", []))
    for candidate_skill in iter_character_skills(target):
        if data.get("exclude_source", True) and candidate_skill is source_skill:
            continue
        if skill_ids and candidate_skill.skill_id not in skill_ids:
            continue
        for component in candidate_skill.definitions:
            if component.get("type") != "active":
                continue
            if component_ids and component.get("component_id") not in component_ids:
                continue
            restorable = False
            usage = component.get("usage_limit")
            if data.get("usage_amount") is not None and usage:
                requested_scope = data.get("usage_scope")
                if requested_scope in {None, usage["scope"]}:
                    restorable = component_use_count(
                        target,
                        candidate_skill,
                        component,
                        turn_number=turn_number,
                        battle=battle,
                    ) > 0
            if data.get("cooldown_turns") is not None:
                state = get_component_state(
                    candidate_skill,
                    component["component_id"],
                    create=False,
                )
                restorable = restorable or bool(
                    state is not None
                    and state.cooldown_ready_turn is not None
                    and state.cooldown_ready_turn > int(turn_number or 0)
                )
            if restorable:
                candidates.append((candidate_skill, component))
    return candidates


def resolve_restore_component_effect(effect, target, skill, **context):
    data = effect.get("effect_data", {})
    actor = context.get("actor") or target
    if target is not actor and not data.get("allow_other", False):
        raise SkillUnavailableError("restore_component默认只能作用于自身")
    candidates = _restorable_components(
        target, data, source_skill=skill, **context
    )
    if not candidates:
        raise SkillUnavailableError("没有可恢复的技能组件")

    maximum = data.get("maximum", 1)
    selection_count = (
        len(candidates)
        if maximum == "all"
        else min(maximum, len(candidates))
    )
    selected = []
    remaining = list(candidates)
    provider = context.get("decision_provider")
    while len(selected) < selection_count:
        if len(remaining) == 1:
            chosen = remaining[0]
        else:
            if provider is None:
                raise ValueError("多个可恢复组件需要DecisionProvider进行选择")
            chosen = provider.choose(DecisionRequest(
                character=actor,
                phase=context.get("phase", "恢复技能组件"),
                prompt="选择要恢复的技能组件。",
                options=tuple(
                    DecisionOption(
                        f"{candidate_skill.name}：{component.get('name', component['component_id'])}",
                        (candidate_skill, component),
                        (f"{candidate_skill.skill_id}:{component['component_id']}",),
                    )
                    for candidate_skill, component in remaining
                ),
            ))
        selected.append(chosen)
        remaining.remove(chosen)

    from game.skill.component_runtime import restore_component_runtime

    restored = []
    for candidate_skill, component in selected:
        result = restore_component_runtime(
            target,
            candidate_skill,
            component,
            usage_amount=data.get("usage_amount"),
            cooldown_turns=data.get("cooldown_turns"),
            usage_scope=data.get("usage_scope"),
            turn_number=context.get("turn_number"),
            battle=context.get("battle"),
        )
        if result is not None:
            restored.append(result)
    return {"target": target, "restored": restored}


def resolve_add_content_effect(effect, target, skill, **context):
    data = effect["effect_data"]
    content_type = data["content_type"]
    content_id = data["content_id"]
    key = (content_type, content_id)
    if not target.is_alive():
        raise SkillUnavailableError("不能向死亡角色添加卡面内容")
    if key in target.permanently_lost_content:
        raise SkillUnavailableError("该内容已经被永久移除，不能再次获得")
    if get_owned_content(target, content_type, content_id) is not None:
        raise SkillUnavailableError("目标已经持有该内容")
    from game.skill.content_registry import load_content

    loaded = load_content(target, content_type, content_id)
    loaded.dynamic = True
    loaded.granted_by = skill
    permanent = data.get("permanent", True)
    loaded.remove_with_source = bool(
        data.get("remove_with_source", False) and not permanent
    )
    if permanent:
        target.permanently_gained_content.add(key)
    _emit_skill_lifecycle(
        target,
        "skill_added",
        loaded,
        granted_by=getattr(skill, "skill_id", None),
        permanent=permanent,
    )
    return {"target": target, "content": loaded, "permanent": permanent}


def resolve_remove_content_effect(effect, target, skill, **context):
    data = effect["effect_data"]
    content_type = data["content_type"]
    content_id = data["content_id"]
    key = (content_type, content_id)
    content = get_owned_content(target, content_type, content_id)
    if content is None:
        raise SkillUnavailableError("目标没有该卡面内容")
    canonical_key = (
        content_type,
        getattr(content, "content_catalog_id", content_id),
    )
    if (
        key in target.permanently_gained_content
        or canonical_key in target.permanently_gained_content
    ):
        raise SkillUnavailableError("永久获得的内容不能再次失去")
    permanent = data.get("permanent", True)
    result = remove_owned_content(
        target, content_type, content, reason="remove_content"
    )
    if permanent:
        target.permanently_lost_content.add(canonical_key)
    return {"target": target, "removed": result, "permanent": permanent}


EFFECT_HANDLERS = {
    "hp_floor": apply_modifier_effect,
    "prevent_death": resolve_prevent_death_effect,
    "add_action": resolve_add_action_effect,
    "add_content": resolve_add_content_effect,
    "add_simple_round": resolve_add_simple_round_effect,
    "add_resource": resolve_add_resource_effect,
    "add_skill": resolve_skill_mutation_effect,
    "add_status": apply_modifier_effect,
    "attribute_bonus": apply_modifier_effect,
    "attack_bonus": apply_modifier_effect,
    "cancel_event": resolve_cancel_event_effect,
    "change_damage_type": resolve_change_damage_type_effect,
    "cost_modifier": apply_modifier_effect,
    "create_field": resolve_create_field_effect,
    "deploy_reality_marble": resolve_deploy_reality_marble_effect,
    "create_attack_event": resolve_create_attack_event_effect,
    "damage": resolve_damage_effect,
    "damage_modifier": apply_modifier_effect,
    "dice_bonus": apply_modifier_effect,
    "hidden": apply_modifier_effect,
    "magic_resistance": apply_modifier_effect,
    "modify_event_value": resolve_modify_event_value_effect,
    "movement_point_bonus": apply_modifier_effect,
    "carry_capacity": apply_modifier_effect,
    "gain_resource": resolve_gain_resource_effect,
    "grant_temporary_mp": resolve_grant_temporary_mp_effect,
    "growing": resolve_growing_effect,
    "modify_resource": resolve_modify_resource_effect,
    "numeric_attribute_bonus": apply_modifier_effect,
    "order_change": resolve_order_change_effect,
    "observe_location": resolve_observe_location_effect,
    "perception_check": resolve_perception_check_effect,
    "plus_bonus": apply_modifier_effect,
    "purify": resolve_purify_effect,
    "recover_resource": resolve_recover_resource_effect,
    "remove_content": resolve_remove_content_effect,
    "remove_skill": resolve_skill_mutation_effect,
    "restore_component": resolve_restore_component_effect,
    "shield": apply_modifier_effect,
    "summon": resolve_summon_effect,
    "switch_skill_set": resolve_switch_skill_set_effect,
    "trap": resolve_trap_effect,
    "visibility_bonus": apply_modifier_effect,
    "presence_concealment": apply_modifier_effect,
}

validate_effect_registry(EFFECT_HANDLERS)


def apply_skill_effect(effect, target, skill, **context):
    effect_type = effect.get("effect_type")
    try:
        handler = EFFECT_HANDLERS[effect_type]
    except KeyError as error:
        raise ValueError(f"未知的技能效果关键词：{effect_type}") from error
    return handler(effect, target, skill, **context)


SKILL_COLLECTIONS = (
    "class_skills",
    "personal_skills",
    "magic_skill",
    "noble_phantasms",
    "dynamic_action_skills",
)


def iter_character_skills(character):
    """Yield every loaded skill-like object once, regardless of its source."""
    seen = set()
    for collection_name in SKILL_COLLECTIONS:
        for skill in getattr(character, collection_name, []):
            if id(skill) in seen:
                continue
            seen.add(id(skill))
            yield skill


# 兼容现有内部调用；新代码应使用公开的iter_character_skills。
_iter_character_skills = iter_character_skills


def _validate_choice_definition(choices):
    if not isinstance(choices, dict):
        raise TypeError("choices必须是字典")
    maximum = choices.get("maximum_selections", 1)
    if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 1:
        raise ValueError("maximum_selections必须是正整数")
    allow_duplicate = choices.get("allow_duplicate", False)
    if not isinstance(allow_duplicate, bool):
        raise TypeError("allow_duplicate必须是布尔值")
    options = choices.get("options", [])
    if not options:
        raise ValueError("可选效果至少需要一个option")
    choice_ids = [option.get("choice_id") for option in options]
    if any(not choice_id for choice_id in choice_ids):
        raise ValueError("每个可选效果都必须提供choice_id")
    if len(choice_ids) != len(set(choice_ids)):
        raise ValueError("同一choices中的choice_id不能重复")


def validate_skill_components(components, *, path="skill", label="技能"):
    """Validate the shared component format used by every skill source."""
    if not isinstance(components, list) or not components:
        raise ValueError(f"{label}至少需要一个component")

    component_ids = []
    for component_index, component in enumerate(components):
        component_path = f"{path}.components[{component_index}]"
        if not isinstance(component, dict):
            raise TypeError(f"{component_path}必须是字典")
        component_id = component.get("component_id")
        if not isinstance(component_id, str) or not component_id.strip():
            raise ValueError(f"{component_path}必须提供component_id")
        component_ids.append(component_id)
        component_type = component.get("type")
        if component_type not in {"active", "passive", "trigger", "react"}:
            raise ValueError(f"未知的技能组件类型：{component_type}")
        if component_type in {"trigger", "react"}:
            trigger = component.get("trigger", {})
            if not isinstance(trigger, dict):
                raise TypeError(f"{component_path}.trigger必须是字典")
            if not component.get("trigger_event") and not trigger.get("event_type"):
                raise ValueError(f"{component_type}组件必须声明event_type")
            if "priority" in trigger and (
                not isinstance(trigger["priority"], int)
                or isinstance(trigger["priority"], bool)
            ):
                raise TypeError("触发priority必须是整数")
            limit = component.get("limit", {})
            if not isinstance(limit, dict):
                raise TypeError(f"{component_path}.limit必须是字典")
            if limit:
                scope = limit.get("scope", "global_turn")
                if scope not in {
                    "event", "global_turn", "until_triggered",
                    "next_battle_start",
                }:
                    raise ValueError(
                        "触发limit.scope必须是event、global_turn、"
                        "until_triggered或next_battle_start"
                    )
                maximum = limit.get("maximum", 1)
                if (
                    not isinstance(maximum, int)
                    or isinstance(maximum, bool)
                    or maximum < 1
                ):
                    raise ValueError("触发limit.maximum必须是正整数")
                if scope in {"until_triggered", "next_battle_start"} and maximum != 1:
                    raise ValueError(f"{scope}的limit.maximum必须为1")
                if scope == "next_battle_start":
                    event_type = (
                        trigger.get("event_type")
                        or component.get("trigger_event")
                    )
                    if event_type != "battle_joined":
                        raise ValueError(
                            "next_battle_start只能监听battle_joined事件"
                        )
        if "choices" in component:
            _validate_choice_definition(component["choices"])
        if not component.get("effects") and "choices" not in component:
            raise ValueError(f"技能组件{component_id}没有任何效果")
        validate_component_effects(component, path=component_path)
    if len(component_ids) != len(set(component_ids)):
        raise ValueError(f"{label}中的component_id不能重复")
    return True


def validate_personal_skill_definition(definition):
    required = {"skill_id", "name", "rank", "components"}
    missing = required - set(definition)
    if missing:
        raise ValueError(f"固有技能缺少字段：{sorted(missing)}")
    casting = definition.get("casting", {})
    if not isinstance(casting, dict):
        raise ValueError("casting必须是字典")
    mode = casting.get("activation_mode", "release")
    if mode not in {"release", "instant", "automatic"}:
        raise ValueError("casting.activation_mode必须是release、instant或automatic")
    if mode == "automatic" and not casting.get("auto_activate_component_id"):
        raise ValueError("automatic发动需要auto_activate_component_id")
    if mode == "instant" and any(component.get("casting_requirement", 0)
                                 for component in definition["components"]):
        raise ValueError("instant发动不能要求咏唱层数")
    skill_path = f"skill[{definition.get('skill_id', '?')}]"
    return validate_skill_components(
        definition["components"],
        path=skill_path,
        label="固有技能",
    )


def _instantiate_personal_skill(definition):
    skill = Skill(
        name=definition["name"],
        rank=definition["rank"],
        definitions=definition["components"],
        negative_skill=definition.get("negative_skill", False),
        skill_id=definition["skill_id"],
        casting=definition.get("casting"),
        skill_category=definition.get("skill_category"),
        description=definition.get("description"),
    )
    skill.source_type = "personal_skill"
    return skill


def _apply_passive_skill_components(character, skill, *, phase="skill_load"):
    results = []
    for component in skill.definitions:
        if component["type"] != "passive":
            continue
        if not condition_matches(component.get("condition"), character):
            continue
        application_id = next(_SKILL_APPLICATION_SEQUENCE)
        for effect in component.get("effects", []):
            results.append(apply_skill_effect(
                effect,
                character,
                skill,
                actor=character,
                turn_number=getattr(character, "current_global_turn", None),
                phase=phase,
                skill_application_id=application_id,
                skill_component_id=component.get("component_id"),
            ))
    return results


def character_owns_skill(character, skill):
    return any(
        candidate is skill
        for candidate in iter_character_skills(character)
    )


def _emit_skill_lifecycle(character, event_type, skill, **payload):
    manager = getattr(character, "game_manager", None)
    event_manager = getattr(manager, "event_manager", None)
    if event_manager is None:
        return None
    data = {
        "skill_id": skill.skill_id,
        "skill_name": skill.name,
        "source_type": skill.source_type,
    }
    data.update(payload)
    return event_manager.emit(
        event_type,
        actor=character,
        source=skill,
        target=character,
        phase=event_type,
        battle=getattr(character, "current_battle", None),
        position=getattr(character, "position", None),
        payload=data,
    )


def _cleanup_skill_sources(character, skill):
    removed_modifiers = []
    manager = getattr(character, "game_manager", None)
    modifier_targets = [character]
    if manager is not None:
        for candidate in (
            list(getattr(manager, "characters", []))
            + list(getattr(manager, "dead_characters", []))
        ):
            if candidate not in modifier_targets:
                modifier_targets.append(candidate)
    for target in modifier_targets:
        for modifier in list(target.modifiers):
            if getattr(modifier, "source", None) is skill:
                if target.remove_modifier(modifier):
                    removed_modifiers.append(modifier)

    removed_summons = []
    removed_fields = []
    collapsed_reality_marble = False
    if manager is not None:
        summon_manager = getattr(manager, "summon_manager", None)
        if summon_manager is not None:
            removed_summons = summon_manager.remove_for_source(skill)
        field_manager = getattr(manager, "field_manager", None)
        if field_manager is not None:
            removed_fields = field_manager.remove_for_source(skill)
        reality_manager = getattr(manager, "reality_marble_manager", None)
        active = getattr(reality_manager, "active", None)
        if (
            active is not None
            and getattr(active, "skill", None) is skill
            and getattr(active, "remove_with_source", False)
        ):
            reality_manager.collapse(reason="skill_source_removed")
            collapsed_reality_marble = True
    return {
        "modifiers": removed_modifiers,
        "summons": removed_summons,
        "fields": removed_fields,
        "reality_marble": collapsed_reality_marble,
    }


def remove_personal_skill(
    character,
    skill,
    *,
    reason="remove_skill",
    emit=True,
    _removing=None,
):
    collection = character.personal_skills
    if skill not in collection:
        raise ValueError(f"{character.name}没有固有技能{skill.skill_id}")
    removing = set() if _removing is None else _removing
    if id(skill) in removing:
        return None
    removing.add(id(skill))

    casting_state = getattr(character, "casting_state", None)
    casting_refunds = []
    if casting_state is not None and casting_state.skill is skill:
        casting_refunds = casting_state.interrupt(reason="skill_removed")

    children = [
        candidate
        for candidate in list(collection)
        if candidate is not skill
        and getattr(candidate, "granted_by", None) is skill
        and getattr(candidate, "remove_with_source", False)
    ]
    collection.remove(skill)
    skill.removed = True
    from game.action.dynamic_action import remove_dynamic_actions_for_source
    from game.skill.growth_runtime import remove_growth_states_for_source

    removed_dynamic_actions = remove_dynamic_actions_for_source(character, skill)
    removed_growth_states = remove_growth_states_for_source(character, skill)
    cleanup = _cleanup_skill_sources(character, skill)
    removed_children = []
    for child in children:
        result = remove_personal_skill(
            character,
            child,
            reason="grant_source_removed",
            emit=emit,
            _removing=removing,
        )
        if result is not None:
            removed_children.append(result)
    for child_type, child in _granted_content_children(
        character,
        skill,
        exclude_types={"personal_skill"},
    ):
        removed_children.append(remove_owned_content(
            character,
            child_type,
            child,
            reason="grant_source_removed",
        ))
    if emit:
        _emit_skill_lifecycle(
            character,
            "skill_removed",
            skill,
            reason=reason,
        )
    return {
        "skill": skill,
        "cleanup": cleanup,
        "casting_refunds": casting_refunds,
        "removed_children": removed_children,
        "removed_dynamic_actions": removed_dynamic_actions,
        "removed_growth_states": removed_growth_states,
    }


CONTENT_COLLECTIONS = {
    "personal_skill": "personal_skills",
    "basic_magic": "magic_skill",
    "noble_phantasm": "noble_phantasms",
}


def _granted_content_children(character, source, *, exclude_types=()):
    children = []
    for content_type, collection_name in CONTENT_COLLECTIONS.items():
        if content_type in exclude_types:
            continue
        for candidate in list(getattr(character, collection_name, [])):
            if (
                candidate is not source
                and getattr(candidate, "granted_by", None) is source
                and getattr(candidate, "remove_with_source", False)
            ):
                children.append((content_type, candidate))
    return children


def get_owned_content(character, content_type, content_id):
    try:
        collection_name = CONTENT_COLLECTIONS[content_type]
    except KeyError as error:
        raise ValueError(f"不支持动态增删的内容类型：{content_type}") from error
    return next(
        (
            item for item in getattr(character, collection_name, [])
            if item.skill_id == content_id
            or getattr(item, "content_catalog_id", None) == content_id
        ),
        None,
    )


def remove_owned_content(character, content_type, content, *, reason="remove_content"):
    """Remove any supported card-content object with full source cleanup."""
    collection_name = CONTENT_COLLECTIONS[content_type]
    collection = getattr(character, collection_name, [])
    if content not in collection:
        raise ValueError(f"{character.name}没有内容{content.skill_id}")
    if content_type == "personal_skill":
        return remove_personal_skill(character, content, reason=reason)

    children = _granted_content_children(character, content)

    casting_state = getattr(character, "casting_state", None)
    casting_refunds = []
    if casting_state is not None and casting_state.skill is content:
        casting_refunds = casting_state.interrupt(reason="content_removed")
    collection.remove(content)
    content.removed = True
    from game.action.dynamic_action import remove_dynamic_actions_for_source
    from game.skill.growth_runtime import remove_growth_states_for_source

    result = {
        "skill": content,
        "cleanup": _cleanup_skill_sources(character, content),
        "casting_refunds": casting_refunds,
        "removed_dynamic_actions": remove_dynamic_actions_for_source(
            character,
            content,
        ),
        "removed_growth_states": remove_growth_states_for_source(
            character,
            content,
        ),
        "removed_children": [],
    }
    for child_type, child in children:
        result["removed_children"].append(remove_owned_content(
            character,
            child_type,
            child,
            reason="grant_source_removed",
        ))
    _emit_skill_lifecycle(character, "skill_removed", content, reason=reason)
    return result


def _definition_from_add_skill_effect(effect):
    data = effect["effect_data"]
    if "skill_definition" in data:
        return deepcopy(data["skill_definition"])
    from game.skill.content_data import PERSONAL_SKILL_DATA

    reference = data["skill_ref"]
    try:
        return deepcopy(PERSONAL_SKILL_DATA[reference["skill_id"]])
    except KeyError as error:
        raise ValueError(
            f"未知的固有技能仓库引用：{reference['skill_id']}"
        ) from error


def _resolve_remove_skill_effect(character, effect, source_skill):
    data = effect["effect_data"]
    if data.get("skill") == "self":
        if source_skill not in character.personal_skills:
            raise SkillUnavailableError(
                "remove_skill的self必须是目标当前持有的固有技能"
            )
        return source_skill
    skill_id = data["skill_id"]
    try:
        return next(
            skill
            for skill in character.personal_skills
            if skill.skill_id == skill_id
        )
    except StopIteration as error:
        raise SkillUnavailableError(
            f"{character.name}没有固有技能{skill_id}"
        ) from error


def execute_skill_mutation_transaction(
    character,
    effects,
    *,
    source_skill,
    actor=None,
    turn_number=None,
    phase=None,
):
    """Preflight and commit one target's add/remove skill effects together."""
    effects = list(effects)
    additions = [
        effect for effect in effects if effect.get("effect_type") == "add_skill"
    ]
    removals = [
        effect for effect in effects if effect.get("effect_type") == "remove_skill"
    ]
    if additions and not character.is_alive():
        raise SkillUnavailableError("不能向死亡角色添加技能")

    removal_skills = []
    for effect in removals:
        skill = _resolve_remove_skill_effect(character, effect, source_skill)
        if skill not in removal_skills:
            removal_skills.append(skill)

    definitions = []
    for effect in additions:
        data = effect["effect_data"]
        if data.get("collection", "personal_skills") != "personal_skills":
            raise ValueError("add_skill当前只允许加入personal_skills")
        if data.get("duplicate_policy", "reject") != "reject":
            raise ValueError("add_skill当前只支持duplicate_policy=reject")
        definition = _definition_from_add_skill_effect(effect)
        validate_personal_skill_definition(definition)
        definitions.append((definition, effect))

    remaining_ids = {
        skill.skill_id
        for skill in character.personal_skills
        if skill not in removal_skills
    }
    addition_ids = [definition["skill_id"] for definition, _effect in definitions]
    if len(addition_ids) != len(set(addition_ids)):
        raise SkillUnavailableError("同一技能变更事务不能添加重复skill_id")
    conflicts = remaining_ids.intersection(addition_ids)
    if conflicts:
        raise SkillUnavailableError(f"角色已经持有技能：{sorted(conflicts)}")

    new_skills = []
    for definition, effect in definitions:
        new_skill = _instantiate_personal_skill(definition)
        new_skill.dynamic = True
        new_skill.granted_by = source_skill
        new_skill.remove_with_source = bool(
            effect["effect_data"].get("remove_with_source", False)
        )
        new_skills.append(new_skill)

    removed = [
        remove_personal_skill(
            character,
            skill,
            reason="skill_mutation",
        )
        for skill in removal_skills
    ]
    added = []
    for skill in new_skills:
        character.personal_skills.append(skill)
        passive_results = _apply_passive_skill_components(
            character,
            skill,
            phase="skill_added",
        )
        _emit_skill_lifecycle(
            character,
            "skill_added",
            skill,
            granted_by=getattr(source_skill, "skill_id", None),
        )
        added.append({"skill": skill, "passive_results": passive_results})
    return {
        "target": character,
        "added": added,
        "removed": removed,
        "source_skill": source_skill,
    }


def _create_defined_skill(
    character,
    definition,
    *,
    collection_name,
    source_type,
    content_label,
):
    validate_personal_skill_definition(definition)
    collection = getattr(character, collection_name, None)
    if collection is None:
        collection = []
        setattr(character, collection_name, collection)
    if any(skill.skill_id == definition["skill_id"] for skill in collection):
        raise ValueError(
            f"{character.name}已经拥有{content_label}{definition['skill_id']}"
        )

    skill = _instantiate_personal_skill(definition)
    skill.source_type = source_type
    collection.append(skill)
    _apply_passive_skill_components(character, skill)
    return skill


def create_personal_skill(character, definition):
    return _create_defined_skill(
        character,
        definition,
        collection_name="personal_skills",
        source_type="personal_skill",
        content_label="固有技能",
    )


def create_magic(character, definition):
    """Create one magic entry using the shared component schema."""
    return _create_defined_skill(
        character,
        definition,
        collection_name="magic_skill",
        source_type="magic",
        content_label="魔术",
    )


def load_basic_magic(character, magic_id):
    """Load an executable basic-magic definition from the data catalog."""
    from game.skill.basic_magic_data import get_basic_magic_definition

    definition = deepcopy(get_basic_magic_definition(magic_id))
    skill = create_magic(character, definition)
    skill.content_catalog_id = magic_id
    return skill


def _effect_is_usable(effect, target, actor=None, source_skill=None):
    if effect.get("effect_type") == "restore_component":
        data = effect.get("effect_data", {})
        if target is not actor and not data.get("allow_other", False):
            return False
        return bool(_restorable_components(
            target,
            data,
            source_skill=source_skill,
        ))
    if effect.get("effect_type") == "add_content":
        data = effect.get("effect_data", {})
        key = (data.get("content_type"), data.get("content_id"))
        return bool(
            target is not None
            and target.is_alive()
            and key not in getattr(target, "permanently_lost_content", set())
            and get_owned_content(target, *key) is None
        )
    if effect.get("effect_type") == "remove_content":
        data = effect.get("effect_data", {})
        key = (data.get("content_type"), data.get("content_id"))
        owned = get_owned_content(target, *key)
        if owned is None:
            return False
        canonical_key = (
            key[0], getattr(owned, "content_catalog_id", key[1])
        )
        permanent = getattr(target, "permanently_gained_content", set())
        return key not in permanent and canonical_key not in permanent
    if effect.get("effect_type") == "create_field":
        data = effect.get("effect_data", {})
        return bool(
            actor is not None
            and actor.position is not None
            and data.get("field_id")
        )
    if effect.get("effect_type") == "deploy_reality_marble":
        data = effect.get("effect_data", {})
        game_manager = getattr(actor, "game_manager", None)
        return bool(
            actor is not None
            and actor.position is not None
            and data.get("reality_marble_id", data.get("field_id"))
            and game_manager is not None
            and game_manager.active_reality_marble is None
            and not getattr(
                actor.position,
                "is_reality_marble_interior",
                False,
            )
        )
    if effect.get("effect_type") == "order_change":
        data = effect.get("effect_data", {})
        if "duration" not in data:
            return False
        duration = data["duration"]
        if duration is not None and (
            not isinstance(duration, int)
            or isinstance(duration, bool)
            or duration < 1
        ):
            return False
        objects = {"actor": actor or target, "target": target}
        subject = objects.get(data.get("subject", "target"))
        anchor = objects.get(data.get("anchor"))
        battle = getattr(subject, "current_battle", None)
        if (
            subject is None
            or battle is None
            or battle.ended
            or not getattr(subject, "in_battle", False)
        ):
            return False
        if data.get("operation") in {"move_before", "move_after"}:
            return bool(
                anchor is not None
                and anchor is not subject
                and getattr(anchor, "current_battle", None) is battle
            )
        return data.get("operation") in {"move_first", "move_last"}
    if effect.get("effect_type") == "purify":
        return bool(target.get_purifiable_modifiers())
    if effect.get("effect_type") in {"gain_resource", "modify_resource"}:
        resource_id = effect.get("effect_data", {}).get("resource_id")
        return bool(
            resource_id
            and getattr(target, "has_resource", lambda _resource: False)(
                resource_id
            )
        )
    if effect.get("effect_type") == "recover_resource":
        data = effect.get("effect_data", {})
        resource_id = data.get("resource_id", data.get("resource"))
        if not resource_id:
            return False
        try:
            recoverable = target.get_recoverable_resource_amount(resource_id)
        except ValueError:
            return False
        return recoverable is not None and recoverable > 0
    if effect.get("effect_type") == "damage":
        return bool(
            target is not None
            and getattr(target, "is_alive", lambda: False)()
        )
    if effect.get("effect_type") == "create_attack_event":
        return bool(
            target is not None
            and getattr(target, "is_alive", lambda: False)()
        )
    return effect.get("effect_type") in EFFECT_HANDLERS


def _replace_selected_attribute(value, attribute):
    if isinstance(value, dict):
        return {
            key: _replace_selected_attribute(item, attribute)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_replace_selected_attribute(item, attribute) for item in value]
    if isinstance(value, tuple):
        return tuple(
            _replace_selected_attribute(item, attribute) for item in value
        )
    return attribute if value == "selected_attribute" else value


def _choice_is_usable(option, actor, target, context):
    if not condition_matches(option.get("condition"), actor, context):
        return False
    option_target = option.get("target_object", target)
    if option_target is None:
        return False
    return any(
        _effect_is_usable(
            effect,
            option_target,
            actor=actor,
            source_skill=context.get("skill"),
        )
        for effect in option.get("effects", [])
    )


def skill_component_is_usable(component, actor, target, *, skill=None, **context):
    if target is None:
        return False
    if skill is not None:
        from game.skill.component_runtime import component_runtime_reasons

        if component_runtime_reasons(
            actor,
            skill,
            component,
            turn_number=context.get("turn_number"),
            battle=context.get("battle"),
        ):
            return False
    if not condition_matches(component.get("condition"), actor, context):
        return False
    if component_input_reasons(component, actor, context):
        return False
    if not target_matches_rules(
        actor,
        target,
        component.get("target_rules", {}),
        context,
        target_type=component.get("target", "self"),
    ):
        return False
    choices = component.get("choices")
    if choices is not None:
        return any(
            _choice_is_usable(option, actor, target, context)
            for option in choices.get("options", [])
        )
    return any(
        _effect_is_usable(
            effect,
            target,
            actor=actor,
            source_skill=skill,
        )
        for effect in component.get("effects", [])
    )


def select_skill_choices(
    component,
    actor,
    target,
    decision_provider=None,
    selected_choice_ids=None,
    **context,
):
    choices = component.get("choices")
    if choices is None:
        return []
    _validate_choice_definition(choices)
    maximum = choices.get("maximum_selections", 1)
    allow_duplicate = choices.get("allow_duplicate", False)
    usable = [
        option
        for option in choices["options"]
        if _choice_is_usable(option, actor, target, context)
    ]
    if not usable:
        raise SkillUnavailableError("所有可选技能效果均无法使用")

    selected = []
    if selected_choice_ids is not None:
        option_by_id = {option["choice_id"]: option for option in usable}
        for choice_id in selected_choice_ids:
            if len(selected) >= maximum:
                raise ValueError("选择数量超过maximum_selections")
            if choice_id not in option_by_id:
                raise SkillUnavailableError(f"技能效果{choice_id}当前不可用")
            option = option_by_id[choice_id]
            if not allow_duplicate and option in selected:
                raise ValueError("该技能不允许重复选择同一效果")
            selected.append(option)
        if not selected:
            raise SkillUnavailableError("至少需要选择一个技能效果")
        return selected

    if decision_provider is None:
        decision_provider = TerminalDecisionProvider()
    available = list(usable)
    while len(selected) < maximum and available:
        options = [
            DecisionOption(
                option.get("name", option["choice_id"]),
                option,
                (option["choice_id"],),
            )
            for option in available
        ]
        if selected:
            options.append(DecisionOption(
                "完成选择",
                None,
                ("confirm", "完成", "结束"),
            ))
        chosen = decision_provider.choose(DecisionRequest(
            character=actor,
            phase=context.get("phase", "技能效果选择"),
            prompt=f"已选择{len(selected)}项，最多选择{maximum}项。",
            options=tuple(options),
        ))
        if chosen is None:
            break
        selected.append(chosen)
        if not allow_duplicate:
            available.remove(chosen)
    return selected


def _collect_component_costs(component, selected_options):
    costs = list(component.get("cost", []))
    for option in selected_options:
        costs.extend(option.get("additional_cost", []))
    return costs


def _resolved_cost(actor, cost, skill):
    value = cost.get("value", 0)
    return actor.modifier_manager.calculate_cost(
        value,
        resource=cost["resource"],
        cost_id=cost.get("cost_id", f"skill:{skill.skill_id}"),
    )


def _available_resource(actor, resource):
    if resource == "mp" and hasattr(actor, "get_available_mp"):
        return actor.get_available_mp()
    if getattr(actor, "has_resource", lambda _resource: False)(resource):
        return actor.get_available_resource(resource)
    return getattr(actor, resource, None)


def _pay_component_costs(actor, costs, skill):
    resolved = [(_resolved_cost(actor, cost, skill), cost) for cost in costs]
    required_by_resource = {}
    for value, cost in resolved:
        resource = cost["resource"]
        required_by_resource[resource] = (
            required_by_resource.get(resource, 0) + value
        )
    for resource, required in required_by_resource.items():
        available = _available_resource(actor, resource)
        if available is None:
            raise ValueError(f"未知的技能消耗资源：{resource}")
        if available < required:
            raise SkillUnavailableError(f"{resource}不足")

    ledgers = {}
    for resource, required in required_by_resource.items():
        if resource == "mp":
            ledger = actor.pay_mp_with_ledger(required)
            if ledger is None:
                raise SkillUnavailableError("mp不足")
            ledgers["mp"] = ledger
        elif getattr(actor, "has_resource", lambda _resource: False)(
            resource
        ):
            if not actor.pay_resource(resource, required):
                raise SkillUnavailableError(f"{resource}不足")
        else:
            setattr(actor, resource, getattr(actor, resource) - required)
    return PaidCosts(required_by_resource, ledgers=ledgers)


def resolve_skill_component(
    actor,
    skill,
    component_id,
    target=None,
    targets=None,
    decision_provider=None,
    selected_choice_ids=None,
    input_values=None,
    casting_prepaid=False,
    casting_release=False,
    **context,
):
    component = next(
        (
            definition
            for definition in skill.definitions
            if definition.get("component_id") == component_id
        ),
        None,
    )
    if component is None:
        raise ValueError(f"未知的技能组件：{component_id}")
    if component["type"] != "active":
        raise ValueError("只有active组件可以被主动发动")
    from game.skill.component_runtime import (
        component_runtime_reasons,
        record_component_use,
    )

    runtime_reasons = component_runtime_reasons(
        actor,
        skill,
        component,
        turn_number=context.get("turn_number"),
        battle=context.get("battle"),
    )
    if runtime_reasons:
        raise SkillUnavailableError(
            f"技能组件当前不可用：{','.join(runtime_reasons)}"
        )
    target_type = component.get("target", "self")
    selected_attributes = []
    if target_type in {"self", "none"}:
        effect_targets = [actor]
    elif targets is not None:
        effect_targets = list(targets)
    elif target is not None:
        effect_targets = [target]
    else:
        effect_targets = []
    if not effect_targets:
        raise SkillUnavailableError("技能缺少合法目标")
    try:
        validate_target_count(
            effect_targets,
            component.get("target_rules", {}),
            path="技能目标",
        )
        for selected_target in effect_targets:
            if not target_matches_rules(
                actor,
                selected_target,
                component.get("target_rules", {}),
                context,
                target_type=target_type,
            ):
                raise SkillUnavailableError("技能选择了不满足目标规则的目标")
    except ValueError as error:
        if isinstance(error, SkillUnavailableError):
            raise
        raise SkillUnavailableError(str(error)) from error
    target = effect_targets[0]
    if target_type == "selectable_attribute":
        selected_attributes = [
            getattr(choice, "value", choice) for choice in effect_targets
        ]
        if any(
            not isinstance(attribute, str)
            or not hasattr(actor, attribute)
            for attribute in selected_attributes
        ):
            raise SkillUnavailableError("技能选择了非法属性")
        effect_targets = [actor for _attribute in selected_attributes]
    if not condition_matches(component.get("condition"), actor, context):
        raise SkillUnavailableError("技能发动条件不满足")

    resolved_inputs = collect_skill_inputs(
        component,
        actor,
        decision_provider=decision_provider,
        input_values=input_values,
        context=context,
    )
    context = {
        **context,
        "input_values": dict(resolved_inputs),
        **{
            f"input:{input_id}": value
            for input_id, value in resolved_inputs.items()
        },
    }

    choice_context = dict(context)
    choice_context["skill"] = skill
    selected = select_skill_choices(
        component,
        actor,
        target,
        decision_provider=decision_provider,
        selected_choice_ids=selected_choice_ids,
        **choice_context,
    )
    direct_effects = resolve_input_expressions(
        component.get("effects", []),
        resolved_inputs,
    )
    direct_effect_pairs = None
    if selected_attributes:
        direct_effect_pairs = [
            (
                _replace_selected_attribute(effect, attribute),
                actor,
            )
            for attribute in selected_attributes
            for effect in component.get("effects", [])
        ]
        direct_effects = [effect for effect, _target in direct_effect_pairs]
    if not selected and not any(
        _effect_is_usable(
            effect,
            effect_target,
            actor=actor,
            source_skill=skill,
        )
        for effect in direct_effects
        for effect_target in effect_targets
    ):
        raise SkillUnavailableError("技能没有当前可用的效果")

    costs = resolve_input_expressions(
        _collect_component_costs(component, selected),
        resolved_inputs,
    )
    if casting_release:
        costs = [
            cost
            for cost in costs
            if cost.get("resource")
            not in {"action_point", "attack_phase_count"}
        ]
    casting = getattr(skill, "casting", {}) or {}
    if casting and not casting_prepaid:
        from game.skill.casting import get_base_casting_mp_cost

        costs.append({
            "resource": "mp",
            "value": get_base_casting_mp_cost(skill),
            "cost_id": casting.get(
                "cost_id",
                f"casting:{skill.skill_id}",
            ),
        })
    paid = _pay_component_costs(
        actor,
        costs,
        skill,
    )
    results = []
    if selected_attributes:
        effects = direct_effect_pairs
    else:
        effects = []
        for effect in direct_effects:
            application_targets = effect_targets
            if effect.get("effect_data", {}).get("apply_once", False):
                application_targets = effect_targets[:1]
            effects.extend(
                (effect, effect_target)
                for effect_target in application_targets
            )
    for option in selected:
        option_target = option.get("target_object")
        option_targets = (
            [option_target] if option_target is not None else effect_targets
        )
        option_effects = resolve_input_expressions(
            option.get("effects", []),
            resolved_inputs,
        )
        if selected_attributes:
            option_effects = [
                _replace_selected_attribute(effect, selected_attributes[0])
                for effect in option_effects
            ]
        effects.extend(
            (effect, current_target)
            for effect in option_effects
            for current_target in option_targets
        )
    declared_target_positions = {
        effect_target: getattr(effect_target, "position", None)
        for _effect, effect_target in effects
    }
    # One command-spell boost belongs to one attack action.  Every target of
    # its first attack effect receives the bonus; later attack effects are
    # treated as later hits and do not.
    first_attack_effect = next((
        effect
        for effect, effect_target in effects
        if effect.get("effect_type") == "create_attack_event"
        and _effect_is_usable(
            effect,
            effect_target,
            actor=actor,
            source_skill=skill,
        )
    ), None)
    command_spell_damage_bonus = (
        actor.consume_command_spell_damage()
        if first_attack_effect is not None
        else 0
    )
    shared_attack_rolls = {}
    grouped_effect_results = {}
    skill_application_id = next(_SKILL_APPLICATION_SEQUENCE)
    attack_occurrences = {}
    for effect, effect_target in effects:
        if (
            effect.get("effect_type") == "create_attack_event"
            and _effect_is_usable(
                effect,
                effect_target,
                actor=actor,
                source_skill=skill,
            )
        ):
            marker = id(effect)
            attack_occurrences[marker] = attack_occurrences.get(marker, 0) + 1
    attack_contexts = {}
    skill_mutation_batches = {}
    for mutation_effect, mutation_target in effects:
        if mutation_effect.get("effect_type") in SKILL_MUTATION_EFFECT_TYPES:
            skill_mutation_batches.setdefault(mutation_target, []).append(
                mutation_effect
            )
    skill_mutation_state = {}
    for effect, effect_target in effects:
        if not _effect_is_usable(
            effect,
            effect_target,
            actor=actor,
            source_skill=skill,
        ):
            results.append({"effect": effect, "skipped": True})
            continue
        effect_context = dict(context)
        effect_context.setdefault("paid_costs", paid)
        effect_context.setdefault("actual_mp_cost", paid.get("mp", 0))
        effect_context.setdefault(
            "shared_attack_rolls",
            shared_attack_rolls,
        )
        effect_context.setdefault("effect_targets", effect_targets)
        effect_context.setdefault(
            "grouped_effect_results",
            grouped_effect_results,
        )
        effect_context.setdefault(
            "command_spell_damage_bonus",
            command_spell_damage_bonus,
        )
        effect_context.setdefault(
            "command_spell_bonus_effect_id",
            id(first_attack_effect) if first_attack_effect is not None else None,
        )
        effect_context.setdefault(
            "declared_target_positions",
            declared_target_positions,
        )
        effect_context.setdefault(
            "skill_application_id",
            skill_application_id,
        )
        effect_context.setdefault(
            "skill_component_id",
            component.get("component_id"),
        )
        effect_context.setdefault(
            "defer_attack_commit_consumption",
            True,
        )
        effect_context.setdefault(
            "skill_mutation_batches",
            skill_mutation_batches,
        )
        effect_context.setdefault(
            "skill_mutation_state",
            skill_mutation_state,
        )
        effect_result = apply_skill_effect(
            effect,
            effect_target,
            skill,
            actor=actor,
            decision_provider=decision_provider,
            **effect_context,
        )
        results.append(effect_result)
        if effect.get("effect_type") == "create_attack_event":
            marker = id(effect)
            profile = getattr(effect_result, "attack_profile", None)
            if profile is not None:
                attack_contexts.setdefault(marker, []).append(
                    profile.modifier_context
                )
            attack_occurrences[marker] -= 1
            if attack_occurrences[marker] == 0:
                actor.modifier_manager.consume_event(
                    "attack_committed",
                    attack_contexts.get(marker, []),
                )
    runtime_state = record_component_use(
        actor,
        skill,
        component,
        turn_number=context.get("turn_number"),
        battle=context.get("battle"),
    )
    from game.rule_report import report_skill_use
    report_skill_use(actor, skill, component, effect_targets, paid=paid,
                     inputs=resolved_inputs, phase=context.get("phase"))
    return {
        "skill": skill,
        "component": component,
        "selected_choices": selected,
        "targets": effect_targets,
        "selected_attributes": selected_attributes,
        "input_values": resolved_inputs,
        "paid_costs": paid,
        "results": results,
        "component_runtime_state": runtime_state,
    }


def load_class_skill(character, name, rank):
    try:
        definitions = CLASS_SKILL_DATA[name][rank]
    except KeyError as error:
        raise ValueError(f"未知的职介技能或等级：{name} {rank}") from error
    if not definitions:
        raise ValueError(f"职介技能{name}的{rank}级尚未定义")
    validate_skill_components(
        definitions,
        path=f"class_skill[{name}][{rank}]",
        label=f"职介技能{name} {rank}",
    )
    if any(skill.name == name for skill in character.class_skills):
        raise ValueError(f"{character.name}已经装载了职介技能{name}")

    skill = Skill(
        name,
        rank,
        definitions=definitions,
        skill_id=f"class:{name}",
    )
    skill.source_type = "class_skill"
    character.class_skills.append(skill)
    for definition in skill.definitions:
        if definition["type"] != "passive":
            continue
        if not condition_matches(definition.get("condition"), character):
            continue
        application_id = next(_SKILL_APPLICATION_SEQUENCE)
        for effect in definition.get("effects", []):
            apply_skill_effect(
                effect,
                character,
                skill,
                turn_number=getattr(character, "current_global_turn", None),
                phase="skill_load",
                skill_application_id=application_id,
                skill_component_id=definition.get("component_id"),
            )
    return skill


def create_noble_phantasm(character, definition):
    from game.skill.casting import (
        AREA_RANGE_TYPES,
        component_casting_requirement,
    )

    required = {
        "skill_id",
        "name",
        "noble_phantasm_type",
        "range_type",
        "components",
    }
    missing = required - set(definition)
    if missing:
        raise ValueError(f"宝具缺少字段：{sorted(missing)}")
    noble_type = definition["noble_phantasm_type"]
    if noble_type not in {"physical", "magic", "support"}:
        raise ValueError(f"未知的宝具类型：{noble_type}")
    range_type = definition["range_type"]
    if range_type not in {"anti_unit", "anti_army", "anti_fortress", "bounded_field"}:
        raise ValueError(f"未知的宝具范围类型：{range_type}")
    if any(
        noble.skill_id == definition["skill_id"]
        for noble in character.noble_phantasms
    ):
        raise ValueError(f"已经持有宝具{definition['skill_id']}")
    limit = 3 if character.noble.plus == 1 else 2
    if len(character.noble_phantasms) >= limit:
        raise ValueError("宝具持有数量超过上限")

    default_requirement = 0 if range_type == "anti_unit" else 1
    components = deepcopy(definition["components"])
    for component in components:
        component.setdefault("casting_requirement", default_requirement)
        component_casting_requirement(component)
        component.setdefault("type", "active")
        component.setdefault("target_rules", {})
        if range_type in AREA_RANGE_TYPES:
            component["target_rules"].setdefault("exclude_self", True)
            component["target_rules"].setdefault(
                "unlimited_targets",
                True,
            )
        attack_effects = [
            effect
            for effect in component.get("effects", [])
            if effect.get("effect_type") == "create_attack_event"
        ]
        if noble_type == "support" and attack_effects:
            raise ValueError(
                "辅助宝具不会进行命中检定；请使用buff、debuff或直接效果"
            )
        if noble_type == "physical" and any(
            not any(
                field in effect.get("effect_data", {})
                for field in ("damage_value", "value", "value_source")
            )
            for effect in attack_effects
        ):
            raise ValueError("物理宝具必须在录卡时定义damage_value")

    casting = deepcopy(definition.get("casting", {}))
    casting["noble_phantasm_type"] = noble_type
    casting["range_type"] = range_type
    if "mp_cost" in definition:
        casting["mp_cost"] = definition["mp_cost"]
    if "roll_profile" in definition:
        casting["roll_profile"] = deepcopy(definition["roll_profile"])
    skill = Skill(
        name=definition["name"],
        rank=definition.get("rank", character.noble.rank),
        definitions=components,
        skill_id=definition["skill_id"],
        casting=casting,
        description=definition.get("description"),
    )
    skill.source_type = "noble_phantasm"
    character.noble_phantasms.append(skill)
    return skill


def trigger_skill_event(character, event_name, **context):
    game_manager = getattr(character, "game_manager", None)
    event_manager = getattr(game_manager, "event_manager", None)
    if event_manager is not None:
        decision_provider = context.pop("decision_provider", None)
        event = event_manager.emit(
            event_name,
            timing=context.pop("timing", "after"),
            actor=context.pop("actor", character),
            source=context.pop("source", character),
            target=context.pop("target", character),
            targets=context.pop("targets", None),
            value=context.pop("value", None),
            phase=context.pop("phase", event_name),
            battle=context.pop(
                "battle",
                getattr(character, "current_battle", None),
            ),
            position=context.pop(
                "position",
                getattr(character, "position", None),
            ),
            payload=context,
            decision_provider=decision_provider,
        )
        return event.records
    results = []
    for skill in iter_character_skills(character):
        for definition in skill.definitions:
            if definition["type"] != "trigger":
                continue
            if definition.get("trigger_event") != event_name:
                continue
            if not condition_matches(
                definition.get("condition"),
                character,
                context,
            ):
                continue
            application_id = next(_SKILL_APPLICATION_SEQUENCE)
            for effect in definition.get("effects", []):
                results.append(
                    apply_skill_effect(
                        effect,
                        character,
                        skill,
                        phase=event_name,
                        skill_application_id=application_id,
                        skill_component_id=definition.get("component_id"),
                        **context,
                    )
                )
    return results
