"""Generic fatal-damage ordering, after shields and before HP/death cleanup."""

from game.modifier.modifier import create_modifier


def prepare_survival_damage(target, damage, *, decision_provider=None, damage_event=None):
    floors = [modifier.value for modifier in target.modifiers if modifier.effect_type == "hp_floor"]
    if floors:
        damage = min(damage, max(0, target.hp - max(floors)))
    if damage < target.hp or target.brink_of_death_counter > 0 or target.hp <= 0:
        return damage
    manager = getattr(target, "game_manager", None)
    events = getattr(manager, "event_manager", None)
    if events is None:
        return damage
    provider = decision_provider or getattr(manager, "decision_provider", None)
    for event_type in ("before_battle_continuation", "before_lethal_damage"):
        event = events.emit(
            event_type, timing="before", actor=target, source=damage_event,
            target=target, value=damage, phase="fatal_damage",
            battle=target.current_battle, position=target.position,
            decision_provider=provider,
        )
        damage = max(0, int(event.value))
        if damage < target.hp:
            break
    return damage


def resolve_prevent_death_effect(effect, target, skill, **context):
    event = context.get("event")
    if event is None or event.event_type not in {"before_battle_continuation", "before_lethal_damage"}:
        raise ValueError("prevent_death只能用于致命伤事件")
    if event.target is not target or event.payload.get("survival_resolved"):
        raise ValueError("保命效果的目标或事件无效")
    data = effect["effect_data"]
    hp = min(target.hpmax, data.get("hp", 1))
    event.value = max(0, target.hp - hp)
    event.payload["survival_resolved"] = True
    duration = data.get("hp_floor_duration")
    if duration is not None:
        # The lock must survive removal of its exhausted granting skill.
        target.add_modifier(create_modifier({
            "modifier_id": f"hp_floor:{skill.skill_id}",
            "effect_type": "hp_floor", "polarity": "buff", "purifiable": False,
            "duration": duration, "duration_timing": "global_turn_end",
            "effect_data": {"value": hp},
        }, target, source=target, source_actor=target, source_type="survival",
            source_id=skill.skill_id, applied_turn=event.global_turn))
    if data.get("remove_skill_when_exhausted", False):
        from game.skill.component_runtime import component_use_count
        from game.skill.skill_runtime import remove_personal_skill
        component = next(item for item in skill.definitions
                         if item["component_id"] == context["skill_component_id"])
        usage = component.get("usage_limit", {})
        if usage and component_use_count(target, skill, component, turn_number=event.global_turn,
                                         battle=event.battle) + 1 >= usage["maximum"]:
            remove_personal_skill(target, skill, reason="survival_exhausted")
    return {"hp": hp, "hp_floor_duration": duration}
