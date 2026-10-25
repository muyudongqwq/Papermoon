"""Target redirection for attacks and pre-resolution damage events."""

from game.action.action_rules import target_matches_rules, validate_target_count
from game.resource.costs import SkillUnavailableError
from game.turn.damage import AttackEvent, DamageEvent, DamageResolver


def _selected_target(selector, effect_target, actor, event):
    values = {
        "self": actor,
        "event_actor": event.actor,
        "event_source": event.source,
        "event_target": event.target,
        "selected_target": effect_target,
    }
    if selector not in values:
        raise ValueError(f"未知的redirect_event.new_target：{selector}")
    target = values[selector]
    if isinstance(target, (AttackEvent, DamageEvent)):
        target = target.target
    return target


def _legal_target(source, target, target_type, rules, event):
    return (
        target is not None
        and getattr(target, "is_alive", lambda: False)()
        and target_matches_rules(
            source,
            target,
            rules,
            {"event": event, "battle": event.battle},
            target_type=target_type,
        )
    )


def _attack_group(game_manager, attack):
    result = []
    for character in game_manager.all_characters:
        for pending in list(getattr(character, "pending_attacks", [])):
            if (
                pending.attack_group_id == attack.attack_group_id
                and not pending.resolved
                and pending not in result
            ):
                result.append(pending)
    if not attack.resolved and attack not in result:
        result.insert(0, attack)
    return result


def _redirect_targets(
    source,
    selected_target,
    attacks,
    context,
    event,
):
    exemplar = attacks[0]
    rules = dict(exemplar.target_rules)
    target_type = exemplar.target_type
    explicit = context.get("redirect_targets")
    if explicit is not None:
        targets = list(dict.fromkeys(explicit))
    elif len(attacks) == 1:
        targets = [selected_target]
    else:
        game_manager = getattr(source, "game_manager", None)
        candidates = [
            character
            for character in game_manager.characters
            if _legal_target(source, character, target_type, rules, event)
        ]
        if selected_target not in candidates:
            return []
        # Area attacks are reconstructed from the same target rules.  Put the
        # explicitly selected target first, then preserve game registration
        # order for the remaining legal recipients.
        candidates.remove(selected_target)
        targets = [selected_target, *candidates]
        if not rules.get("unlimited_targets", False):
            # Re-launch the same range shape: absent an explicit target list,
            # preserve the number of AttackEvents in the original group.
            maximum = rules.get("maximum", len(attacks))
            targets = targets[:min(maximum, len(attacks))]
    targets = [
        target
        for target in targets
        if _legal_target(source, target, target_type, rules, event)
    ]
    try:
        validate_target_count(targets, rules, path="重定向攻击目标")
    except ValueError:
        return []
    return targets


def redirect_attack(event, actor, effect_target, data, context):
    attack = event.source if isinstance(event.source, AttackEvent) else None
    if attack is None:
        attack = event.payload.get("attack_event")
    if not isinstance(attack, AttackEvent):
        raise SkillUnavailableError("当前事件不包含可重定向攻击")
    game_manager = getattr(actor, "game_manager", None)
    if game_manager is None:
        raise SkillUnavailableError("重定向者尚未加入游戏")
    attacks = _attack_group(game_manager, attack)
    if not attacks or any(item.defense_roll_started for item in attacks):
        raise SkillUnavailableError("攻击组已经开始防御，不能重定向")

    selected = _selected_target(
        data.get("new_target", "self"),
        effect_target,
        actor,
        event,
    )
    targets = _redirect_targets(actor, selected, attacks, context, event)
    if not targets:
        raise SkillUnavailableError("没有满足原攻击规则的重定向目标")

    exemplar = attacks[0]
    profile = exemplar.attack_profile
    if profile is None:
        raise SkillUnavailableError("旧攻击没有可供重建的攻击快照")
    reason = data.get("reason", "redirect_event")
    history_item = {
        "actor": actor,
        "old_source": exemplar.source,
        "old_targets": [item.target for item in attacks],
        "new_targets": list(targets),
        "reason": reason,
    }
    redirected_profile = profile.redirected_copy(actor)
    redirected_profile.redirect_history.append(history_item)

    for old_attack in attacks:
        pending = getattr(old_attack.target, "pending_attacks", [])
        if old_attack in pending:
            pending.remove(old_attack)
        old_attack.report_cancelled("redirected")
        old_attack.resolved = True
        old_attack.resolution_reason = "redirected"

    new_attacks = []
    relationships = getattr(game_manager, "relationship_manager", None)
    for target in targets:
        new_attack = redirected_profile.assign_target(target)
        target.pending_attacks.append(new_attack)
        new_attacks.append(new_attack)
        if relationships is not None:
            relationships.resolve_attack_attitude(
                actor,
                target,
                context.get("decision_provider"),
            )

    event.source = new_attacks[0]
    event.actor = actor
    event.target = new_attacks[0].target
    event.targets = [item.target for item in new_attacks]
    event.payload["attack_event"] = new_attacks[0]
    event.payload["attack_events"] = new_attacks
    event.payload["redirect_history"] = list(
        redirected_profile.redirect_history
    )
    game_manager.event_manager.emit(
        "attack_group_redirected",
        actor=actor,
        source=new_attacks[0],
        target=new_attacks[0].target,
        targets=[item.target for item in new_attacks],
        phase=event.phase,
        battle=event.battle,
        position=getattr(actor, "position", None),
        payload={
            "attack_group_id": exemplar.attack_group_id,
            "reason": reason,
            "old_source": getattr(exemplar.source, "character_id", None),
            "new_source": getattr(actor, "character_id", None),
            "old_targets": [
                getattr(item.target, "character_id", None)
                for item in attacks
            ],
            "new_targets": [
                getattr(item.target, "character_id", None)
                for item in new_attacks
            ],
        },
        decision_provider=context.get("decision_provider"),
    )
    event.cancel("attack_redirected")
    return {
        "redirect_type": "attack",
        "old_attacks": attacks,
        "attacks": new_attacks,
        "targets": targets,
    }


def redirect_damage(event, actor, effect_target, data, context):
    if event.event_type != "before_damage" or event.timing != "before":
        raise SkillUnavailableError(
            "damage重定向只能用于before_damage的before时机"
        )
    damage_event = event.source if isinstance(event.source, DamageEvent) else None
    if damage_event is None:
        damage_event = event.payload.get("damage_event")
    if not isinstance(damage_event, DamageEvent):
        raise SkillUnavailableError("当前事件不包含可重定向伤害")
    target = _selected_target(
        data.get("new_target", "self"),
        effect_target,
        actor,
        event,
    )
    if not _legal_target(
        damage_event.source,
        target,
        damage_event.target_type,
        damage_event.target_rules,
        event,
    ):
        raise SkillUnavailableError("新目标不满足原伤害的目标规则")

    old_target = damage_event.target
    reason = data.get("reason", "redirect_event")
    history_item = {
        "actor": actor,
        "old_target": old_target,
        "new_target": target,
        "reason": reason,
    }
    damage_event.target = target
    damage_event.redirect_history.append(history_item)
    event.target = target
    event.targets = [target]
    event.position = getattr(target, "position", None)
    event.payload["redirect_history"] = list(damage_event.redirect_history)
    recalculated = DamageResolver().calculate(damage_event)
    damage_event.calculated_value = recalculated
    event.value = event.replay_value_operations(recalculated)
    return {
        "redirect_type": "damage",
        "damage_event": damage_event,
        "old_target": old_target,
        "target": target,
    }


def resolve_redirect_event(effect, target, skill, **context):
    event = context.get("game_event") or context.get("event")
    if event is None:
        raise SkillUnavailableError("redirect_event只能在事件结算中使用")
    actor = context.get("actor") or target
    data = effect.get("effect_data", {})
    redirect_type = data["redirect_type"]
    try:
        if redirect_type == "attack":
            return redirect_attack(event, actor, target, data, context)
        if redirect_type == "damage":
            return redirect_damage(event, actor, target, data, context)
    except SkillUnavailableError as error:
        # Invalid later redirects do not roll back an earlier legal redirect.
        return {
            "skipped": True,
            "reason": "illegal_redirect",
            "message": str(error),
        }
    raise ValueError(f"未知的redirect_type：{redirect_type}")
