"""魔术与宝具共用的咏唱状态、进度和退款逻辑。"""

from copy import deepcopy
from dataclasses import dataclass, field

from game.modifier.modifier import create_modifier
from game.action.action_rules import target_matches_rules


NOBLE_PHANTASM_MP_COSTS = {"C": 30, "B": 40, "A": 50}
MAGIC_NOBLE_PHANTASM_DAMAGE = {"C": 90, "B": 120, "A": 150}
AREA_RANGE_TYPES = {"anti_army", "anti_fortress"}
POSITION_REVEAL_RANGE_TYPES = {"anti_fortress"}


def noble_damage_multiplier(skill):
    return 2 if (getattr(skill, "source_type", None) == "noble_phantasm"
                 and get_casting_config(skill).get("range_type") == "anti_fortress") else 1


def component_casting_requirement(component):
    value = component.get("casting_requirement", 0)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("casting_requirement必须是非负整数")
    return value


def get_casting_config(skill):
    return deepcopy(getattr(skill, "casting", {}) or {})


def uses_release_action(skill):
    config = get_casting_config(skill)
    return bool(config and config.get("activation_mode", "release") == "release")


def get_base_casting_mp_cost(skill):
    config = get_casting_config(skill)
    value = config.get("mp_cost")
    if value is None and getattr(skill, "source_type", None) == "noble_phantasm":
        value = NOBLE_PHANTASM_MP_COSTS.get(skill.rank_name)
    if value is None:
        raise ValueError(f"{skill.name}的咏唱没有定义mp_cost")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("咏唱mp_cost必须是数字")
    if value < 0:
        raise ValueError("咏唱mp_cost不能小于0")
    if (
        getattr(skill, "source_type", None) == "noble_phantasm"
        and config.get("range_type") == "anti_fortress"
    ):
        value *= 2
    return value


def get_casting_mp_cost(actor, skill):
    config = get_casting_config(skill)
    value = get_base_casting_mp_cost(skill)
    return actor.modifier_manager.calculate_cost(
        value,
        resource="mp",
        cost_id=config.get("cost_id", f"casting:{skill.skill_id}"),
    )


def iter_casting_sources(character):
    seen = set()
    for collection_name in (
        "personal_skills",
        "class_skills",
        "magic_skill",
        "noble_phantasms",
    ):
        for skill in getattr(character, collection_name, []):
            if id(skill) in seen or not get_casting_config(skill):
                continue
            seen.add(id(skill))
            yield skill


def castable_sources(character):
    from game.skill.component_runtime import component_runtime_reasons
    from game.skill.skill_runtime import condition_matches
    result = []
    for skill in iter_casting_sources(character):
        if not any(
            component.get("type") == "active"
            and component_casting_requirement(component) > 0
            and condition_matches(component.get("condition"), character, {
                "battle": getattr(character, "current_battle", None),
                "turn_number": getattr(character, "current_global_turn", 0),
            })
            and not component_runtime_reasons(character, skill, component)
            for component in skill.definitions
        ):
            continue
        try:
            cost = get_casting_mp_cost(character, skill)
        except (TypeError, ValueError):
            continue
        if character.get_available_mp() >= cost:
            result.append(skill)
    return result


def zero_cast_release_options(character):
    result = []
    for skill in iter_casting_sources(character):
        if not uses_release_action(skill):
            continue
        try:
            cost = get_casting_mp_cost(character, skill)
        except (TypeError, ValueError):
            continue
        if character.get_available_mp() < cost:
            continue
        for component in skill.definitions:
            if (
                component.get("type") == "active"
                and component_casting_requirement(component) == 0
            ):
                result.append((skill, component))
    return result


def release_options(character):
    state = getattr(character, "casting_state", None)
    if state is not None:
        options = [
            (state.skill, component)
            for component in state.eligible_components()
        ]
    else:
        options = zero_cast_release_options(character)
    return [
        (skill, component)
        for skill, component in options
        if release_component_is_usable(character, skill, component)
    ]


def release_component_is_usable(actor, skill, component):
    from game.skill.skill_runtime import skill_component_is_usable

    candidates = get_release_target_candidates(actor, skill, component)
    return any(
        skill_component_is_usable(
            component,
            actor,
            target,
            skill=skill,
            phase="release",
            casting_release=True,
            turn_number=getattr(actor, "current_global_turn", 0),
            battle=getattr(actor, "current_battle", None),
        )
        for target in candidates
    )


def release_option_label(skill, component):
    component_name = component.get("name", component.get("component_id"))
    requirement = component_casting_requirement(component)
    return f"{skill.name}：{component_name}（需求{requirement}层）"


def get_release_target_candidates(actor, skill, component):
    target_type = component.get("target", "self")
    if target_type in {"self", "none"}:
        return [actor]
    battle = getattr(actor, "current_battle", None)
    game_manager = getattr(actor, "game_manager", None)
    if actor.in_battle and battle is not None:
        candidates = list(battle.participants)
    elif game_manager is not None:
        candidates = list(game_manager.characters)
    else:
        candidates = [actor]

    rules = deepcopy(component.get("target_rules", {}))
    config = get_casting_config(skill)
    if config.get("range_type") in AREA_RANGE_TYPES:
        rules.setdefault("exclude_self", True)
        rules.setdefault("unlimited_targets", True)

    result = []
    for target in candidates:
        effective_rules = deepcopy(rules)
        effective_rules.setdefault("must_be_alive", True)
        if not target_matches_rules(
            actor,
            target,
            effective_rules,
            {"battle": battle},
            target_type=target_type,
        ):
            continue
        result.append(target)
    return result


def select_release_option(actor, decision_provider):
    from game.turn.decision import DecisionOption, DecisionRequest

    options = release_options(actor)
    if not options:
        return None
    if len(options) == 1:
        return options[0]
    return decision_provider.choose(DecisionRequest(
        character=actor,
        phase="解放效果选择",
        prompt="请选择要解放的效果。",
        options=tuple(
            DecisionOption(
                release_option_label(skill, component),
                (skill, component),
                (component.get("component_id"),),
            )
            for skill, component in options
        ) + (
            DecisionOption("返回行动选择", None, ("back", "返回")),
        ),
    ))


def select_release_targets(actor, skill, component, decision_provider):
    from game.turn.decision import DecisionOption, DecisionRequest

    candidates = get_release_target_candidates(actor, skill, component)
    target_type = component.get("target", "self")
    if target_type in {"self", "none"}:
        return [actor]
    if not candidates:
        return None
    rules = deepcopy(component.get("target_rules", {}))
    config = get_casting_config(skill)
    unlimited = rules.get("unlimited_targets", False)
    if config.get("range_type") in AREA_RANGE_TYPES:
        unlimited = rules.get("unlimited_targets", True)
    if not unlimited:
        chosen = decision_provider.choose(DecisionRequest(
            character=actor,
            phase="解放目标选择",
            prompt="请选择目标。",
            options=tuple(
                DecisionOption(target.name, target, (target.name,))
                for target in candidates
            ) + (
                DecisionOption("返回行动选择", None, ("back", "返回")),
            ),
        ))
        return None if chosen is None else [chosen]

    selected = []
    remaining = list(candidates)
    while remaining:
        options = [
            DecisionOption(target.name, target, (target.name,))
            for target in remaining
        ]
        if selected:
            options.append(DecisionOption(
                "完成选择",
                None,
                ("confirm", "完成"),
            ))
        chosen = decision_provider.choose(DecisionRequest(
            character=actor,
            phase="解放目标选择",
            prompt="可选择任意数量的目标。",
            options=tuple(options),
        ))
        if chosen is None:
            break
        selected.append(chosen)
        remaining.remove(chosen)
    return selected or None


def _casting_status_effect():
    return {
        "modifier_id": "casting",
        "name": "咏唱",
        "effect_type": "add_status",
        "polarity": "neutral",
        "purifiable": False,
        "stacking": {
            "stack_group": "casting",
            "stack_scope": "all_sources",
            "stacking_rule": "refresh",
            "max_stacks": 1,
            "duration_refresh_rule": "reset",
        },
        "duration": 2,
        "effect_data": {
            "value": "casting",
        },
    }


@dataclass
class CastingState:
    actor: object
    skill: object
    payment_ledger: list
    started_turn: int
    layers: int = 0
    continued_turn: int | None = None
    modifier: object = None
    released: bool = False
    interrupted: bool = False
    refund_results: list = field(default_factory=list)
    position_reveal_recipients: set = field(default_factory=set)
    position_reveal_location: object = None

    @classmethod
    def start(cls, actor, skill, turn_number):
        if getattr(actor, "casting_state", None) is not None:
            raise ValueError("角色已经处于咏唱状态")
        cost = get_casting_mp_cost(actor, skill)
        ledger = actor.pay_mp_with_ledger(cost)
        if ledger is None:
            return None
        state = cls(actor, skill, ledger, turn_number)
        modifier = create_modifier(
            _casting_status_effect(),
            actor,
            source=skill,
            source_type="casting",
            source_id=f"casting:{skill.skill_id}",
            applied_turn=turn_number,
            applied_phase="chant",
        )
        result = actor.add_modifier(modifier)
        if not result:
            actor.refund_mp_ledger(ledger)
            return None
        state.modifier = result.modifier
        actor.casting_state = state
        state.continue_for_turn(turn_number)
        from game.rule_report import report
        report(actor, "casting_started", actor=actor, private=True,
               actor_data={"skill_id": skill.skill_id, "skill_name": skill.name,
                           "paid_mp": sum(item["amount"] for item in ledger)})
        return state

    @property
    def name(self):
        return self.skill.name

    def continue_for_turn(self, turn_number):
        self.continued_turn = turn_number
        if self.modifier in self.actor.modifiers:
            self.modifier.duration = 2
        self.refresh_position_reveal()
        return True

    def reveals_position(self):
        config = get_casting_config(self.skill)
        return bool(
            getattr(self.skill, "source_type", None) == "noble_phantasm"
            and config.get("range_type") in POSITION_REVEAL_RANGE_TYPES
        )

    def refresh_position_reveal(self):
        self.position_reveal_recipients.clear()
        self.position_reveal_location = None
        if not self.reveals_position() or self.actor.position is None:
            return set()
        game_manager = getattr(self.actor, "game_manager", None)
        if game_manager is None:
            return set()
        from game.map.map import get_nodes_within_distance

        nodes = get_nodes_within_distance(self.actor.position, 5)
        self.position_reveal_location = self.actor.position
        self.position_reveal_recipients.update(
            character
            for character in game_manager.characters
            if character is not self.actor
            and character.is_alive()
            and character.position in nodes
        )
        return set(self.position_reveal_recipients)

    def is_revealed_to(self, observer):
        return bool(
            not self.released
            and not self.interrupted
            and observer in self.position_reveal_recipients
        )

    def eligible_components(self):
        return [
            component
            for component in self.skill.definitions
            if component.get("type") == "active"
            and component_casting_requirement(component) <= self.layers
        ]

    def advance_at_global_turn_end(self, turn_number, decision_provider=None):
        if self.continued_turn != turn_number:
            self.interrupt(reason="not_continued")
            return False
        requirements = [
            component_casting_requirement(component)
            for component in self.skill.definitions
            if component.get("type") == "active"
        ]
        maximum = max(requirements, default=self.layers + 1)
        self.layers = min(self.layers + 1, maximum)
        from game.rule_report import report
        report(self.actor, "casting_progressed", actor=self.actor, private=True,
               actor_data={"skill_id": self.skill.skill_id, "layers": self.layers,
                           "maximum_layers": maximum})
        if self.modifier in self.actor.modifiers:
            self.modifier.duration = 2
        config = get_casting_config(self.skill)
        component_id = config.get("auto_activate_component_id")
        if component_id is not None:
            component = next((
                item for item in self.skill.definitions
                if item.get("component_id") == component_id
            ), None)
            if component is None:
                raise ValueError(f"自动咏唱完成效果不存在：{component_id}")
            if component_casting_requirement(component) <= self.layers:
                from game.skill.skill_runtime import resolve_skill_component, skill_component_is_usable

                if not skill_component_is_usable(
                    component, self.actor, self.actor, skill=self.skill,
                    turn_number=turn_number,
                    battle=getattr(self.actor, "current_battle", None),
                    phase="automatic_release", casting_release=True,
                ):
                    self.interrupt(reason="automatic_component_unavailable")
                    return False

                result = resolve_skill_component(
                    self.actor,
                    self.skill,
                    component_id,
                    target=self.actor,
                    decision_provider=decision_provider,
                    casting_prepaid=True,
                    casting_release=True,
                    turn_number=turn_number,
                    phase="automatic_release",
                    battle=getattr(self.actor, "current_battle", None),
                )
                self.finish_release()
                return {"auto_activated": True, "result": result}
        return self.layers

    def interrupt(self, reason="manual"):
        if self.released or self.interrupted:
            return []
        self.interrupted = True
        self.refund_results = self.actor.refund_mp_ledger(
            self.payment_ledger
        )
        self._clear()
        from game.rule_report import report
        report(self.actor, "casting_interrupted", actor=self.actor, private=True,
               actor_data={"skill_id": self.skill.skill_id, "reason": reason,
                           "refunded_mp": sum(item["refunded"] for item in self.refund_results)})
        return list(self.refund_results)

    def finish_release(self):
        if self.released or self.interrupted:
            return False
        self.released = True
        self._clear()
        from game.rule_report import report
        report(self.actor, "casting_released", actor=self.actor, private=True,
               actor_data={"skill_id": self.skill.skill_id, "layers": self.layers})
        return True

    def _clear(self):
        self.position_reveal_recipients.clear()
        self.position_reveal_location = None
        if self.modifier in self.actor.modifiers:
            self.actor.remove_modifier(self.modifier)
        else:
            self.actor.remove_status_modifiers("casting")
        if getattr(self.actor, "casting_state", None) is self:
            self.actor.casting_state = None


def start_or_continue_casting(actor, skill=None, turn_number=0):
    state = getattr(actor, "casting_state", None)
    if state is not None:
        state.continue_for_turn(turn_number)
        return state
    if skill is None:
        raise ValueError("开始咏唱时必须指定魔术或宝具")
    return CastingState.start(actor, skill, turn_number)


def interrupt_casting(actor, reason="manual"):
    state = getattr(actor, "casting_state", None)
    if state is None:
        return False
    return state.interrupt(reason=reason)
