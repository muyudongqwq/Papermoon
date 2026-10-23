"""魔术与宝具共用的咏唱状态、进度和退款逻辑。"""

from copy import deepcopy
from dataclasses import dataclass, field

from game.modifier.modifier import create_modifier
from game.action.action_rules import target_matches_rules
from game.resource.costs import NOBLE_PHANTASM_MP_COSTS


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


def casting_component(skill, component_id=None):
    options = [item for item in skill.definitions if item.get("type") == "active"
               and component_casting_requirement(item) > 0]
    if component_id is not None:
        selected = next((item for item in options if item["component_id"] == component_id), None)
        if selected is None:
            raise ValueError("请选择该技能中需要咏唱的active单元")
        return selected
    if len(options) != 1:
        raise ValueError("请在开始咏唱时指定技能单元")
    return options[0]


def get_casting_mp_cost(actor, skill, component=None):
    from game.resource.costs import cost_totals, costs_at
    component = casting_component(skill) if component is None else component
    return cost_totals(actor, costs_at(component.get("cost", []), "casting_start"),
                       f"casting:{skill.skill_id}").get("mp", 0)


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


def castable_options(character, skill=None):
    from game.skill.component_runtime import component_runtime_reasons
    from game.skill.skill_runtime import condition_matches
    result = []
    for source in iter_casting_sources(character):
        if skill is not None and source is not skill:
            continue
        config = get_casting_config(source)
        for component in source.definitions:
            if component.get("type") != "active" or component_casting_requirement(component) <= 0:
                continue
            if config.get("activation_mode") == "automatic" and component["component_id"] != config.get("auto_activate_component_id"):
                continue
            if not condition_matches(component.get("condition"), character, {
                    "battle": getattr(character, "current_battle", None),
                    "turn_number": getattr(character, "current_global_turn", 0)}):
                continue
            if component_runtime_reasons(character, source, component):
                continue
            if character.get_available_mp() >= get_casting_mp_cost(character, source, component):
                result.append((source, component))
    return result


def castable_sources(character):
    return list(dict.fromkeys(skill for skill, component in castable_options(character)))


def zero_cast_release_options(character):
    result = []
    for skill in iter_casting_sources(character):
        if not uses_release_action(skill):
            continue
        for component in skill.definitions:
            if (component.get("type") == "active" and component_casting_requirement(component) == 0
                    and character.get_available_mp() >= get_casting_mp_cost(character, skill, component)):
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
            "status_id": "casting",
        },
    }


@dataclass
class CastingState:
    actor: object
    skill: object
    payment_ledger: list
    started_turn: int
    component_id: str
    layers: int = 0
    continued_turn: int | None = None
    modifier: object = None
    released: bool = False
    interrupted: bool = False
    refund_results: list = field(default_factory=list)
    position_reveal_recipients: set = field(default_factory=set)
    position_reveal_location: object = None

    @classmethod
    def start(cls, actor, skill, turn_number, component_id=None):
        if getattr(actor, "casting_state", None) is not None:
            raise ValueError("角色已经处于咏唱状态")
        component = casting_component(skill, component_id)
        from game.resource.costs import costs_at, pay_costs, SkillUnavailableError
        try:
            paid = pay_costs(actor, costs_at(component.get("cost", []), "casting_start"), f"casting:{skill.skill_id}")
        except SkillUnavailableError:
            return None
        ledger = paid.ledgers.get("mp", [])
        state = cls(actor, skill, ledger, turn_number, component["component_id"])
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
        from game.game.rule_report import report
        report(actor, "casting_started", actor=actor, private=True,
               actor_data={"skill_id": skill.skill_id, "skill_name": skill.name, "component_id": state.component_id,
                           "paid_mp": sum(item["amount"] for item in ledger)})
        return state

    @property
    def name(self):
        if len([item for item in self.skill.definitions if item.get("type") == "active"]) > 1:
            component = self.component or {}
            return f"{self.skill.name}：{component.get('name', self.component_id)}"
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

    @property
    def component(self):
        return next((item for item in self.skill.definitions if item["component_id"] == self.component_id), None)

    def eligible_components(self):
        return [
            component
            for component in self.skill.definitions
            if component.get("type") == "active"
            and component["component_id"] == self.component_id
            and component_casting_requirement(component) <= self.layers
        ]

    def advance_at_global_turn_end(self, turn_number, decision_provider=None):
        if self.continued_turn != turn_number:
            self.interrupt(reason="not_continued")
            return False
        if self.component is None or not self.skill.is_component_active(self.component_id):
            self.interrupt(reason="component_removed")
            return False
        maximum = component_casting_requirement(self.component)
        self.layers = min(self.layers + 1, maximum)
        from game.game.rule_report import report
        report(self.actor, "casting_progressed", actor=self.actor, private=True,
               actor_data={"skill_id": self.skill.skill_id, "component_id": self.component_id, "layers": self.layers,
                           "maximum_layers": maximum})
        if self.modifier in self.actor.modifiers:
            self.modifier.duration = 2
        config = get_casting_config(self.skill)
        component_id = config.get("auto_activate_component_id")
        if component_id == self.component_id:
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
        from game.game.rule_report import report
        report(self.actor, "casting_interrupted", actor=self.actor, private=True,
               actor_data={"skill_id": self.skill.skill_id, "reason": reason,
                           "refunded_mp": sum(item["refunded"] for item in self.refund_results)})
        return list(self.refund_results)

    def finish_release(self):
        if self.released or self.interrupted:
            return False
        self.released = True
        self._clear()
        from game.game.rule_report import report
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


def start_or_continue_casting(actor, skill=None, turn_number=0, component_id=None):
    state = getattr(actor, "casting_state", None)
    if state is not None:
        if (skill is not None and state.skill is not skill) or (component_id is not None and state.component_id != component_id):
            raise ValueError("更换咏唱单元前请先中断当前咏唱")
        state.continue_for_turn(turn_number)
        return state
    if skill is None:
        raise ValueError("开始咏唱时必须指定魔术或宝具")
    return CastingState.start(actor, skill, turn_number, component_id)


def interrupt_casting(actor, reason="manual"):
    state = getattr(actor, "casting_state", None)
    if state is None:
        return False
    return state.interrupt(reason=reason)
