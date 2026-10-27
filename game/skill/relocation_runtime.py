"""Skill-driven spatial transfer with freely selected map destinations."""

from game.map.map import get_distance
from game.resource.costs import SkillUnavailableError
from game.turn.decision import DecisionOption, DecisionRequest, TerminalDecisionProvider


def relocation_destinations(target, data):
    """Return map nodes within the recipient's optional distance limit."""
    manager = getattr(target, "game_manager", None)
    if (
        manager is None
        or target not in manager.characters
        or not target.is_alive()
        or target.position is None
    ):
        return []
    distance = data.get("distance")
    return sorted(
        (
            node
            for node in manager.get_map_nodes(merge_area_levels=False)
            if node is not target.position
            and (
                distance is None
                or get_distance(target.position, node, distance) is not None
            )
        ),
        key=lambda node: str(node.name),
    )


def resolve_relocate_effect(effect, target, skill, **context):
    data = effect.get("effect_data", {})
    destinations = relocation_destinations(target, data)
    if not destinations:
        raise SkillUnavailableError("relocate没有合法的转移目的地")
    manager = target.game_manager
    actor = context.get("actor") or target
    provider = (
        context.get("decision_provider")
        or getattr(manager, "decision_provider", None)
        or TerminalDecisionProvider()
    )
    destination = provider.choose(DecisionRequest(
        character=actor,
        phase="技能转移—选择目的地",
        prompt=f"请选择{target.name}的转移目的地。",
        options=[DecisionOption(node.name, node) for node in destinations],
    ))
    # Immediate actions in a decision window can change the map or recipient.
    if destination not in relocation_destinations(target, data):
        raise SkillUnavailableError("relocate选择的目的地不再合法")

    guard_target = None
    battle = manager.get_battle_at(destination)
    if battle is not None:
        guard_targets = battle.get_emergency_guard_targets(
            target,
            position=destination,
        )
        if guard_targets:
            guard_target = provider.choose(DecisionRequest(
                character=target,
                phase="技能转移—紧急援护目标",
                prompt="是否在到达后进行紧急援护？",
                options=[DecisionOption(character.name, character)
                         for character in guard_targets]
                + [DecisionOption("不援护", None, ("skip", "pass"))],
            ))
            if guard_target is not None and guard_target not in guard_targets:
                raise SkillUnavailableError("relocate选择了非法的紧急援护目标")
    # The optional guard decision is another immediate-action window.
    if destination not in relocation_destinations(target, data):
        raise SkillUnavailableError("relocate选择的目的地不再合法")
    releasing = context.get("releasing_casting_state")
    if (
        releasing is not None
        and releasing is getattr(target, "casting_state", None)
        and releasing.skill is skill
    ):
        # This transfer is the spell's successful release, not an external
        # interruption. Commit its prepaid casting cost before moving.
        releasing.finish_release()
    return manager.resolve_relocation(
        target,
        destination,
        emergency_guard_target=guard_target,
        decision_provider=provider,
    )
