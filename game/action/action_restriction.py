"""Shared availability and execution checks for action restrictions."""

from game.modifier.context import ModifierContext


_PHASE_ALIASES = {
    "attack": "attack_phase",
    "defense": "defense_phase",
    "guard": "guard_phase",
}


def normalize_action_phase(phase):
    return _PHASE_ALIASES.get(phase, phase)


def action_phase_scope(*, phase, battle=None):
    phase = normalize_action_phase(phase)
    if phase and str(phase).startswith("simple_round_"):
        return "simple_round"
    if battle is not None:
        return "formal_battle"
    return "non_battle"


def restriction_reasons(actor, definition, context, *, skill=None, component=None):
    """Return every active restriction which blocks this action definition."""
    action_id = definition.get("action_id")
    if action_id in {"pass", "stay"}:
        return []
    phase = normalize_action_phase(getattr(context, "phase", None))
    battle = getattr(context, "battle", None)
    phase_scope = action_phase_scope(phase=phase, battle=battle)
    skill_id = getattr(skill, "skill_id", None)
    component_id = None if component is None else component.get("component_id")
    action_type = definition.get("action_type") or (
        "skill" if skill is not None else None
    )
    modifier_context = ModifierContext(
        actor=actor,
        target=actor,
        phase_scope=phase_scope,
        phase=phase,
        action_id=action_id,
        skill_id=skill_id,
        component_id=component_id,
        battle=battle,
        position=getattr(actor, "position", None),
        tags={"action", action_type} if action_type else {"action"},
    )
    reasons = []
    for modifier in list(getattr(actor, "modifiers", [])):
        if (
            getattr(modifier, "effect_type", None) == "action_restriction"
            and modifier.blocks_action(
                action_id=action_id,
                action_type=action_type,
                skill_id=skill_id,
                component_id=component_id,
                phase=phase,
                phase_scope=phase_scope,
                context=modifier_context,
            )
            and modifier.reason not in reasons
        ):
            reasons.append(modifier.reason)
    return reasons


def action_restriction_reasons(action, *, phase=None, battle=None):
    """Build a current runtime context and recheck a submitted action."""
    if phase is None:
        if getattr(action, "ap_layer", None) is not None:
            phase = f"AP{action.ap_layer}"
        else:
            battle = battle or getattr(action.actor, "current_battle", None)
            phase = getattr(battle, "current_phase", None)
            phase = normalize_action_phase(phase)
    if battle is None:
        battle = getattr(action.actor, "current_battle", None)

    class RuntimeContext:
        pass

    context = RuntimeContext()
    context.phase = phase
    context.battle = battle
    skill = getattr(action, "skill", None)
    component = getattr(action, "component", None)
    definition = dict(action.definition)
    definition.setdefault("action_id", action.action_id)
    return restriction_reasons(
        action.actor,
        definition,
        context,
        skill=skill,
        component=component,
    )
