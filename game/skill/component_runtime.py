"""Runtime usage limits and cooldowns for active, trigger and react components."""

from dataclasses import dataclass, field


USAGE_LIMIT_SCOPES = {"global_turn", "battle", "game"}
COOLDOWN_UNITS = {"global_turn"}


@dataclass
class ComponentRuntimeState:
    game_uses: int = 0
    turn_uses: dict = field(default_factory=dict)
    battle_uses: dict = field(default_factory=dict)
    cooldown_ready_turn: int | None = None
    last_used_turn: int | None = None


def get_component_state(skill, component_id, *, create=True):
    states = skill.component_runtime_states
    state = states.get(component_id)
    if state is None and create:
        state = ComponentRuntimeState()
        states[component_id] = state
    return state


def _current_turn(actor, turn_number=None):
    if turn_number is None:
        turn_number = getattr(actor, "current_global_turn", 0)
    return int(turn_number or 0)


def _current_battle(actor, battle=None):
    return battle if battle is not None else getattr(actor, "current_battle", None)


def component_use_count(
    actor,
    skill,
    component,
    *,
    turn_number=None,
    battle=None,
):
    usage = component.get("usage_limit")
    if not usage:
        return 0
    state = get_component_state(
        skill,
        component["component_id"],
        create=False,
    )
    if state is None:
        return 0
    scope = usage["scope"]
    if scope == "game":
        return state.game_uses
    if scope == "global_turn":
        return state.turn_uses.get(_current_turn(actor, turn_number), 0)
    current_battle = _current_battle(actor, battle)
    if current_battle is None:
        return 0
    return state.battle_uses.get(current_battle, 0)


def component_runtime_reasons(
    actor,
    skill,
    component,
    *,
    turn_number=None,
    battle=None,
):
    """Return stable machine-readable reasons for an unavailable component."""
    reasons = []
    turn_number = _current_turn(actor, turn_number)
    current_battle = _current_battle(actor, battle)
    usage = component.get("usage_limit")
    if usage:
        if usage["scope"] == "battle" and current_battle is None:
            reasons.append("battle_usage_requires_battle")
        elif component_use_count(
            actor,
            skill,
            component,
            turn_number=turn_number,
            battle=current_battle,
        ) >= usage["maximum"]:
            reasons.append(f"{usage['scope']}_usage_exhausted")

    cooldown = component.get("cooldown")
    if cooldown:
        group = cooldown.get("group")
        group_ready = getattr(skill, "cooldown_group_ready_turns", {}).get(group)
        if group is not None and group_ready is not None and turn_number < group_ready:
            reasons.append("component_on_cooldown")
        state = get_component_state(
            skill,
            component["component_id"],
            create=False,
        )
        if (
            state is not None
            and state.cooldown_ready_turn is not None
            and turn_number < state.cooldown_ready_turn
        ):
            if "component_on_cooldown" not in reasons:
                reasons.append("component_on_cooldown")
    return reasons


def record_component_use(
    actor,
    skill,
    component,
    *,
    turn_number=None,
    battle=None,
):
    """Commit one successful use after every component effect resolves."""
    usage = component.get("usage_limit")
    cooldown = component.get("cooldown")
    if not usage and not cooldown:
        return None
    turn_number = _current_turn(actor, turn_number)
    current_battle = _current_battle(actor, battle)
    state = get_component_state(skill, component["component_id"])
    if usage:
        scope = usage["scope"]
        if scope == "game":
            state.game_uses += 1
        elif scope == "global_turn":
            state.turn_uses[turn_number] = state.turn_uses.get(turn_number, 0) + 1
        else:
            if current_battle is None:
                raise ValueError("battle范围的使用次数只能在正式战斗中记录")
            state.battle_uses[current_battle] = (
                state.battle_uses.get(current_battle, 0) + 1
            )

    if cooldown:
        # T回合发动，turns=1时完整封锁T+1，于T+2恢复。
        state.cooldown_ready_turn = turn_number + cooldown["turns"] + 1
        group = cooldown.get("group")
        if group is not None:
            ready = getattr(skill, "cooldown_group_ready_turns", None)
            if ready is None:
                ready = {}
                skill.cooldown_group_ready_turns = ready
            ready[group] = state.cooldown_ready_turn
    state.last_used_turn = turn_number
    return state


def reset_component_runtime(
    skill,
    component_id,
    *,
    usage_scope=None,
    turn_number=None,
    battle=None,
    reset_cooldown=False,
):
    """Public reset hook for future recovery effects and GM operations."""
    state = get_component_state(skill, component_id, create=False)
    if state is None:
        return False
    if usage_scope is not None:
        if usage_scope not in USAGE_LIMIT_SCOPES:
            raise ValueError(f"未知的使用次数scope：{usage_scope}")
        if usage_scope == "game":
            state.game_uses = 0
        elif usage_scope == "global_turn":
            if turn_number is None:
                state.turn_uses.clear()
            else:
                state.turn_uses.pop(int(turn_number), None)
        elif battle is None:
            state.battle_uses.clear()
        else:
            state.battle_uses.pop(battle, None)
    if reset_cooldown:
        state.cooldown_ready_turn = None
    return True


def restore_component_runtime(
    actor,
    skill,
    component,
    *,
    usage_amount=None,
    cooldown_turns=None,
    usage_scope=None,
    turn_number=None,
    battle=None,
):
    """Restore a component's spent uses and/or remaining cooldown.

    ``"all"`` clears the selected counter. Integer values reduce it without
    ever creating extra uses or a negative cooldown. The operation returns a
    structured before/after record so card effects and GM tooling can report
    exactly what changed.
    """
    component_id = component["component_id"]
    state = get_component_state(skill, component_id, create=False)
    if state is None:
        return None
    turn_number = _current_turn(actor, turn_number)
    current_battle = _current_battle(actor, battle)
    usage = component.get("usage_limit")
    changed = False
    result = {
        "skill": skill,
        "component": component,
        "usage_before": None,
        "usage_after": None,
        "cooldown_before": state.cooldown_ready_turn,
        "cooldown_after": state.cooldown_ready_turn,
    }

    if usage_amount is not None and usage is not None:
        scope = usage_scope or usage["scope"]
        if scope != usage["scope"]:
            raise ValueError("restore_component的usage_scope必须匹配组件定义")
        if scope == "game":
            before = state.game_uses
            after = 0 if usage_amount == "all" else max(0, before - usage_amount)
            state.game_uses = after
        elif scope == "global_turn":
            before = state.turn_uses.get(turn_number, 0)
            after = 0 if usage_amount == "all" else max(0, before - usage_amount)
            if after:
                state.turn_uses[turn_number] = after
            else:
                state.turn_uses.pop(turn_number, None)
        else:
            if current_battle is None:
                return None
            before = state.battle_uses.get(current_battle, 0)
            after = 0 if usage_amount == "all" else max(0, before - usage_amount)
            if after:
                state.battle_uses[current_battle] = after
            else:
                state.battle_uses.pop(current_battle, None)
        result["usage_before"] = before
        result["usage_after"] = after
        changed = changed or after != before

    if cooldown_turns is not None and state.cooldown_ready_turn is not None:
        before = state.cooldown_ready_turn
        if cooldown_turns == "all":
            state.cooldown_ready_turn = None
        else:
            restored = before - cooldown_turns
            state.cooldown_ready_turn = None if restored <= turn_number else restored
        result["cooldown_before"] = before
        result["cooldown_after"] = state.cooldown_ready_turn
        changed = changed or state.cooldown_ready_turn != before

    return result if changed else None
