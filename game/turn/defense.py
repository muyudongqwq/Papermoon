"""Defense selection and resolution for dodge, block, and offset."""

import math
import random
from dataclasses import dataclass
from itertools import chain

from game.action.action import Action
from game.action.action_data import get_action_definition
from game.action.action_restriction import restriction_reasons
from game.resource.costs import component_activation_costs
from game.skill.casting import (
    component_casting_requirement,
    get_casting_config,
)
from game.skill.skill_runtime import (
    SkillUnavailableError,
    _SKILL_APPLICATION_SEQUENCE,
    _available_resource,
    _collect_component_costs,
    _pay_component_costs,
    _resolved_cost,
    apply_skill_effect,
    build_attack_profile_from_effect,
    iter_character_skills,
    select_skill_choices,
)
from game.turn.damage import DamageEvent, DamageResolver, report_discarded_attacks
from game.turn.roll import RollResolver
from game.turn.decision import DecisionOption, DecisionRequest
from game.action.action_rules import condition_matches
from game.skill.component_runtime import component_runtime_reasons, record_component_use


@dataclass
class OffsetAttackOption:
    option_id: str
    name: str
    resolution_channel: str
    kind: str
    skill: object = None
    component: dict = None


@dataclass
class OffsetAttempt:
    """One targetless attack used to reduce one incoming attack."""

    defender: object
    incoming_attack: object
    attack_profiles: list
    roll_result: object
    success: bool
    reduction: int
    incoming_damage_before_offset: int = 0
    incoming_damage_after_offset: int = 0
    remaining_hit_segments: int = 0

    @property
    def total_power(self):
        return sum(profile.offset_power for profile in self.attack_profiles)


def _all_component_effects(component):
    yield from component.get("effects", [])
    for option in component.get("choices", {}).get("options", []):
        yield from option.get("effects", [])


def attack_effect_is_targetless(effect):
    if effect.get("effect_type") != "create_attack_event":
        return False
    data = effect.get("effect_data", {})
    return data.get("value_source") != "target_attribute"


def component_has_offset_attack(component):
    return any(
        attack_effect_is_targetless(effect)
        for effect in _all_component_effects(component)
    )


def component_resolution_channel(skill, component):
    explicit = component.get("resolution_channel")
    if explicit is not None:
        return explicit
    if (
        getattr(skill, "source_type", None) in {"magic", "noble_phantasm"}
        or get_casting_config(skill)
    ):
        return "release"
    return "attack"


def _casting_component_ready(character, skill, component):
    requirement = component_casting_requirement(component)
    if requirement == 0:
        return True
    state = getattr(character, "casting_state", None)
    return bool(
        state is not None
        and state.skill is skill
        and state.component_id == component["component_id"]
        and state.layers >= requirement
    )


def _offset_component_available(character, skill, component, turn_number=None):
    return (
        skill.is_component_active(component["component_id"])
        and not component_runtime_reasons(character, skill, component, turn_number=turn_number)
        and condition_matches(component.get("condition"), character, {
            "phase": "offset", "battle": character.current_battle,
            "turn_number": character.current_global_turn if turn_number is None else turn_number,
        })
    )


def _prospective_refund(character, skill, component=None):
    state = getattr(character, "casting_state", None)
    if state is None or (state.skill is skill and (component is None or state.component_id == component["component_id"])):
        return 0
    # Refunds return to their original payer. A dead or former master does
    # not fund the replacement action, and ordinary MP cannot exceed mpmax.
    accessible = {character}
    master = getattr(character, "master", None)
    if master is not None and master.is_alive():
        accessible.add(master)
    refunds = {}
    for payment in state.payment_ledger:
        payer = payment["payer"]
        if payer not in accessible:
            continue
        key = (payer, payment.get("pool", "mp"))
        refunds[key] = refunds.get(key, 0) + payment.get("amount", 0)
    return sum(amount if pool == "temporary_mp" else min(amount, max(0, payer.mpmax - payer.mp))
               for (payer, pool), amount in refunds.items())


def _component_base_costs(character, skill, component):
    state = getattr(character, "casting_state", None)
    prepaid = state is not None and state.skill is skill and state.component_id == component["component_id"]
    costs = component_activation_costs(skill, component, prepaid=prepaid)
    costs = [cost for cost in costs if cost.get("resource") != "attack_phase_count"]
    return costs


def _can_pay_costs(character, costs, skill, *, prospective_mp=0):
    totals = {}
    for cost in costs:
        value = _resolved_cost(character, cost, skill)
        resource = cost["resource"]
        totals[resource] = totals.get(resource, 0) + value
    for resource, required in totals.items():
        available = _available_resource(character, resource)
        if available is None:
            return False
        if resource == "mp":
            available += prospective_mp
        if available < required:
            return False
    return True


def get_offset_attack_options(character, incoming_attack):
    channel = incoming_attack.resolution_channel
    options = []
    allows_action = getattr(character, "allows_action", None)
    if allows_action is not None and not allows_action("offset"):
        return options
    normal_attack_allowed = (
        allows_action is None or allows_action("attack")
    )
    if channel == "attack" and normal_attack_allowed:
        options.append(OffsetAttackOption(
            option_id="normal_attack",
            name="普通攻击",
            resolution_channel="attack",
            kind="normal_attack",
        ))

    for skill in iter_character_skills(character):
        for component in skill.definitions:
            if component.get("type") != "active":
                continue
            if not _offset_component_available(character, skill, component):
                continue
            action_id = f"skill:{skill.skill_id}:{component['component_id']}"
            if allows_action is not None and not allows_action(
                action_id,
                skill_action=True,
            ):
                continue
            if component_resolution_channel(skill, component) != channel:
                continue
            if not component_has_offset_attack(component):
                continue
            if channel == "attack" and "attack_phase" not in component.get(
                "available_phases",
                [],
            ):
                continue
            if channel == "release" and not _casting_component_ready(
                character,
                skill,
                component,
            ):
                continue
            try:
                costs = _component_base_costs(character, skill, component)
            except (TypeError, ValueError):
                continue
            if not _can_pay_costs(
                character,
                costs,
                skill,
                prospective_mp=_prospective_refund(character, skill, component),
            ):
                continue
            component_name = component.get("name")
            name = (
                f"{skill.name}：{component_name}"
                if component_name
                else skill.name
            )
            options.append(OffsetAttackOption(
                option_id=action_id,
                name=name,
                resolution_channel=channel,
                kind="skill",
                skill=skill,
                component=component,
            ))
    return options


def _selected_effects(component, selected):
    return list(chain(
        component.get("effects", []),
        *(option.get("effects", []) for option in selected),
    ))


def _effect_target_for_offset(effect, component, actor):
    selector = effect.get("effect_target")
    if selector == "self":
        return actor
    if selector == "attack_target":
        return None
    if component.get("target", "self") in {"self", "none"}:
        return actor
    return None


def resolve_offset_attack_option(
    character,
    option,
    decision_provider=None,
    *,
    turn_number=None,
):
    if turn_number is None:
        turn_number = character.current_global_turn
    if option.kind == "normal_attack":
        profile = Action(character, "attack").build_attack_profile(
            decision_provider,
            for_offset=True,
        )
        if getattr(character, "casting_state", None) is not None:
            character.interrupt_casting(reason="other_action:offset")
        return {
            "option": option,
            "profiles": [profile],
            "paid_costs": {},
            "effect_results": [],
        }

    skill = option.skill
    component = option.component
    if (skill not in iter_character_skills(character)
            or not _offset_component_available(character, skill, component, turn_number)
            or not _casting_component_ready(character, skill, component)):
        raise SkillUnavailableError("抵消组件已移除、次数耗尽、冷却中或条件不满足")
    selected = select_skill_choices(
        component,
        character,
        character,
        decision_provider=decision_provider,
        phase="抵消攻击效果选择",
    )
    effects = _selected_effects(component, selected)
    attack_effects = [
        effect for effect in effects if attack_effect_is_targetless(effect)
    ]
    if not attack_effects:
        raise SkillUnavailableError("该行动没有可用于抵消的无目标攻击")

    costs = _collect_component_costs(component, selected)
    costs = [
        cost
        for cost in costs
        if cost.get("resource") != "attack_phase_count"
    ]
    state = getattr(character, "casting_state", None)
    casting_prepaid = bool(state is not None and state.skill is skill and state.component_id == component["component_id"])
    costs.extend(cost for cost in component_activation_costs(skill, component, prepaid=casting_prepaid)
                 if cost.get("timing") == "casting_start")

    switching_cast = state is not None and (state.skill is not skill or state.component_id != component["component_id"])
    if not _can_pay_costs(
        character,
        costs,
        skill,
        prospective_mp=(
            _prospective_refund(character, skill, component) if switching_cast else 0
        ),
    ):
        raise SkillUnavailableError("抵消攻击的资源不足")
    if switching_cast:
        character.interrupt_casting(reason="other_action:offset")

    paid = _pay_component_costs(character, costs, skill)
    command_spell_bonus = character.consume_command_spell_damage()
    profiles = []
    for index, effect in enumerate(attack_effects):
        profiles.append(build_attack_profile_from_effect(
            effect,
            skill,
            actor=character,
            decision_provider=decision_provider,
            phase="offset",
            action_id=option.option_id,
            for_offset=True,
            command_spell_damage_bonus=(
                command_spell_bonus if index == 0 else 0
            ),
            command_spell_bonus_effect_id=id(effect),
            resolution_channel=option.resolution_channel,
        ))

    effect_results = []
    application_id = next(_SKILL_APPLICATION_SEQUENCE)
    for effect in effects:
        if effect.get("effect_type") == "create_attack_event":
            continue
        target = _effect_target_for_offset(effect, component, character)
        if target is None:
            effect_results.append({"effect": effect, "skipped": True})
            continue
        effect_results.append(apply_skill_effect(
            effect,
            target,
            skill,
            actor=character,
            decision_provider=decision_provider,
            turn_number=turn_number,
            phase="offset",
            paid_costs=paid,
            actual_mp_cost=paid.get("mp", 0),
            skill_application_id=application_id,
            skill_component_id=component.get("component_id"),
        ))

    record_component_use(character, skill, component, turn_number=turn_number,
                         battle=character.current_battle)
    if casting_prepaid:
        state.finish_release()
    from game.game.rule_report import report_skill_use
    report_skill_use(character, skill, component, [character], paid=paid, phase="offset")
    return {
        "option": option,
        "profiles": profiles,
        "paid_costs": paid,
        "effect_results": effect_results,
        "selected_choices": selected,
    }


class DefenseResolver:
    VALID_DEFENSE_TYPES = {"dodge", "block", "offset", "unopposed"}

    def resolve_phase(
        self,
        defender,
        defense_type=None,
        attacks=None,
        decision_provider=None,
    ):
        attacks = (
            defender.pending_attacks.copy()
            if attacks is None
            else list(attacks)
        )
        if (
            not isinstance(defense_type, OffsetAttempt)
            and defense_type not in self.VALID_DEFENSE_TYPES
        ):
            raise ValueError(f"未知的防御指令：{defense_type}")
        if (
            isinstance(defense_type, str)
            and defense_type != "unopposed"
            and self.defense_is_restricted(defender, defense_type)
        ):
            defense_type = "unopposed"

        attack_count = len(attacks)
        hit_count = 0
        total_damage = 0
        for attack in attacks:
            if not defender.is_alive():
                break
            result = self.resolve_attack(
                defender,
                attack,
                defense_type,
                decision_provider,
            )
            if result["hit"]:
                hit_count += 1
            total_damage += result["damage"]

        defender.last_defense_attack_count = attack_count
        defender.last_defense_hit_count = hit_count
        defender.last_defense_total_damage = total_damage
        for attack in attacks:
            if attack in defender.pending_attacks:
                report_discarded_attacks([attack], "defense_ended_without_resolution")
                defender.pending_attacks.remove(attack)
        defense_name = (
            "offset"
            if isinstance(defense_type, OffsetAttempt)
            else defense_type
        )
        defense_contexts = []
        for attack in attacks:
            flow = getattr(attack, "defense_flow", None)
            names = (
                [step["defense_type"] for step in flow]
                if flow
                else [defense_name]
            )
            for name in names:
                defense_contexts.append({
                    "actor": defender,
                    "source": attack,
                    "target": attack.source,
                    "action_id": name,
                    "skill_id": attack.skill_id,
                    "damage_type": attack.damage_type,
                    "tags": set(attack.source_tags) | {"defense", name},
                    "event": attack,
                })
        if any(
            context["action_id"] != "unopposed"
            for context in defense_contexts
        ):
            defender.modifier_manager.consume_event(
                "defense_committed",
                defense_contexts,
            )
        return {
            "attack_count": attack_count,
            "hit_count": hit_count,
            "total_damage": total_damage,
        }

    @staticmethod
    def defense_is_restricted(defender, defense_type):
        battle = getattr(defender, "current_battle", None)
        phase = getattr(battle, "current_phase", "defense_phase")
        if phase == "defense":
            phase = "defense_phase"

        class DefenseContext:
            pass

        context = DefenseContext()
        context.phase = phase
        context.battle = battle
        return bool(restriction_reasons(
            defender,
            get_action_definition(defense_type),
            context,
        ))

    def resolve_attack(
        self,
        defender,
        attack,
        defense_type=None,
        decision_provider=None,
    ):
        flow = self.build_defense_flow(defender, attack, defense_type)
        if flow is not None:
            return self.resolve_attack_flow(
                defender,
                attack,
                flow,
                decision_provider=decision_provider,
            )
        cancelled = self.emit_before_attack_defense(
            defender,
            attack,
            decision_provider=decision_provider,
        )
        if cancelled is not None:
            return cancelled
        return self._resolve_attack_legacy(
            defender,
            attack,
            defense_type,
            decision_provider=decision_provider,
        )

    @staticmethod
    def emit_before_attack_defense(defender, attack, decision_provider=None):
        game_manager = getattr(defender, "game_manager", None)
        event_manager = getattr(game_manager, "event_manager", None)
        if event_manager is not None:
            before_event = event_manager.emit(
                "before_attack_defense",
                timing="before",
                actor=attack.source,
                source=attack,
                target=defender,
                phase=getattr(
                    getattr(defender, "current_battle", None),
                    "current_phase",
                    "defense",
                ),
                battle=getattr(defender, "current_battle", None),
                position=getattr(defender, "position", None),
                payload={
                    "attack_event": attack,
                    "attack_group_id": attack.attack_group_id,
                },
                decision_provider=decision_provider,
            )
            if before_event.cancelled:
                return {
                    "hit": False,
                    "damage": 0,
                    "redirected": (
                        before_event.payload.get("cancel_reason")
                        == "attack_redirected"
                    ),
                }
        return None

    def _resolve_attack_legacy(
        self,
        defender,
        attack,
        defense_type=None,
        decision_provider=None,
    ):
        attack.defense_roll_started = True
        attack.defense_type = "offset" if isinstance(defense_type, OffsetAttempt) else defense_type
        previous_roll = getattr(defender, "last_defense_roll_result", None)
        if isinstance(defense_type, OffsetAttempt):
            result = self.resolve_offset_attempt(
                defender,
                attack,
                defense_type,
                decision_provider,
            )
        elif defense_type == "dodge":
            result = self.resolve_dodge(defender, attack, decision_provider)
        elif defense_type == "block":
            result = self.resolve_block(defender, attack, decision_provider)
        elif defense_type == "offset":
            result = self.resolve_legacy_offset(
                defender,
                attack,
                decision_provider,
            )
        elif defense_type == "unopposed":
            result = self.finish_attack(
                defender,
                attack,
                hit=True,
                damage=attack.value,
                decision_provider=decision_provider,
            )
        else:
            raise ValueError(f"未知的防御指令：{defense_type}")
        self._emit_defense_resolved(
            defender,
            attack,
            defense_type,
            result,
            previous_roll=previous_roll,
            decision_provider=decision_provider,
        )
        return result

    @staticmethod
    def _phase_scope(defender):
        battle = getattr(defender, "current_battle", None)
        phase = getattr(battle, "current_phase", "defense_phase")
        if str(phase).startswith("simple_round"):
            return phase, "simple_round"
        return phase, "formal_battle" if battle is not None else "non_battle"

    def build_defense_flow(self, defender, attack, defense_type):
        """Return a modified ordered defense plan, or ``None`` for legacy."""
        if getattr(attack, "forced_guard_defense", False):
            return None
        phase, phase_scope = self._phase_scope(defender)
        modifiers = sorted(
            (
                modifier
                for modifier in getattr(defender, "modifiers", ())
                if (
                    getattr(modifier, "effect_type", None)
                    == "defense_flow_modifier"
                    and modifier.matches_attack(
                        attack,
                        phase=phase,
                        phase_scope=phase_scope,
                    )
                )
            ),
            key=lambda modifier: (
                modifier.application_order
                if modifier.application_order is not None
                else float("inf")
            ),
        )
        if not modifiers:
            return None
        flow = [{
            "selection_mode": "preselected",
            "selected": defense_type,
            "defense_types": ["dodge", "block", "offset"],
            "continue_on": "always",
            "on_unavailable": "end",
        }]
        for modifier in modifiers:
            steps = [dict(step) for step in modifier.steps]
            for step in steps:
                step.setdefault("continue_on", "always")
                step.setdefault("on_unavailable", "skip")
                step["modifier"] = modifier
            if modifier.operation == "append":
                flow.extend(steps)
            elif modifier.operation == "prepend":
                flow[0:0] = steps
            else:
                flow = steps
        return flow

    def replaces_default_defense(self, defender, attack):
        """Whether the effective flow removes the ordinary defense choice."""
        if getattr(attack, "forced_guard_defense", False):
            return False
        phase, phase_scope = self._phase_scope(defender)
        return any(
            getattr(modifier, "effect_type", None) == "defense_flow_modifier"
            and modifier.operation == "replace"
            and modifier.matches_attack(
                attack,
                phase=phase,
                phase_scope=phase_scope,
            )
            for modifier in getattr(defender, "modifiers", ())
        )

    def resolve_attack_flow(
        self,
        defender,
        attack,
        flow,
        *,
        decision_provider=None,
    ):
        cancelled = self.emit_before_attack_defense(
            defender,
            attack,
            decision_provider=decision_provider,
        )
        if cancelled is not None:
            return cancelled
        attack.defense_roll_started = True
        percentages = []
        flats = []
        step_results = []
        hit = True
        offset_used = False

        for index, step in enumerate(flow):
            selected = self.select_flow_step(
                defender,
                attack,
                step,
                decision_provider=decision_provider,
            )
            if selected is None:
                if step.get("on_unavailable", "skip") == "end":
                    break
                continue
            result = self.resolve_flow_step(
                defender,
                attack,
                selected,
                percentages=percentages,
                flats=flats,
                decision_provider=decision_provider,
            )
            result["index"] = index
            result["continue_on"] = step.get("continue_on", "always")
            step_results.append(result)
            percentages.extend(result.get("percentage_modifiers", ()))
            flats.extend(result.get("flat_modifiers", ()))
            offset_used = offset_used or isinstance(selected, OffsetAttempt)
            self.emit_defense_step_resolved(
                defender,
                attack,
                result,
                decision_provider=decision_provider,
            )
            if result.get("ends_attack"):
                hit = False
                break
            remaining = self.preview_damage(
                defender,
                attack,
                percentage_modifiers=percentages,
                flat_modifiers=flats,
            )
            if remaining <= 0:
                break
            if not self.should_continue_flow(
                step.get("continue_on", "always"),
                result,
                remaining,
            ):
                break

        attack.defense_flow = step_results
        attack.defense_type = "+".join(
            item["defense_type"] for item in step_results
        ) or "unopposed"
        if offset_used:
            remaining_damage = self.preview_damage(
                defender,
                attack,
                percentage_modifiers=percentages,
                flat_modifiers=flats,
            )
            base_damage = self.preview_damage(
                defender,
                attack,
                percentage_modifiers=percentages,
            )
            if remaining_damage <= 0 or base_damage <= 0:
                attack.final_hit_segments = 0
            else:
                per_segment = base_damage / max(1, attack.original_hit_segments)
                attack.final_hit_segments = min(
                    attack.original_hit_segments,
                    math.ceil(remaining_damage / per_segment),
                )
        result = self.finish_attack(
            defender,
            attack,
            hit=hit,
            percentage_modifiers=percentages,
            flat_modifiers=flats,
            decision_provider=decision_provider,
        )
        self.emit_flow_defense_resolved(
            defender,
            attack,
            result,
            step_results,
            decision_provider=decision_provider,
        )
        return result

    def select_flow_step(
        self,
        defender,
        attack,
        step,
        *,
        decision_provider=None,
    ):
        mode = step["selection_mode"]
        allowed = [
            defense_type
            for defense_type in step.get("defense_types", ())
            if not self.defense_is_restricted(defender, defense_type)
        ]
        battle = getattr(defender, "current_battle", None)
        if mode == "preselected":
            selected = step.get("selected")
            if isinstance(selected, OffsetAttempt):
                return selected
            return selected if selected in allowed or selected == "unopposed" else None
        if not allowed:
            return None
        if mode == "fixed":
            selected = allowed[0]
        elif mode == "random":
            selected = random.choice(allowed)
        else:
            if battle is not None and hasattr(battle, "request_defense_step"):
                return battle.request_defense_step(
                    defender,
                    attack,
                    decision_provider,
                    allowed_types=allowed,
                )
            if decision_provider is None:
                return None
            selected = decision_provider.choose(DecisionRequest(
                character=defender,
                phase="追加防御",
                prompt="请选择追加的防御方式。",
                options=tuple(
                    DecisionOption(
                        {"dodge": "闪避", "block": "格挡", "offset": "抵消"}[item],
                        item,
                        (item,),
                    )
                    for item in allowed
                ),
            ))
        if selected == "offset":
            if battle is None or not hasattr(battle, "request_offset_attempt"):
                return None
            return battle.request_offset_attempt(
                defender,
                attack,
                decision_provider,
            )
        return selected

    def resolve_flow_step(
        self,
        defender,
        attack,
        defense,
        *,
        percentages,
        flats,
        decision_provider=None,
    ):
        if isinstance(defense, OffsetAttempt):
            if defense.defender is not defender or defense.incoming_attack is not attack:
                raise ValueError("抵消记录与当前攻击不匹配")
            attack.offset_attempt = defense
            attempts = getattr(attack, "offset_attempts", None)
            if attempts is None:
                attempts = attack.offset_attempts = []
            attempts.append(defense)
            return {
                "defense_type": "offset",
                "success": bool(defense.success),
                "defense_roll": getattr(defense.roll_result, "total", None),
                "percentage_modifiers": [],
                "flat_modifiers": [-defense.reduction],
                "ends_attack": False,
            }
        if defense == "unopposed":
            return {
                "defense_type": "unopposed",
                "success": False,
                "defense_roll": None,
                "percentage_modifiers": [],
                "flat_modifiers": [],
                "ends_attack": False,
            }
        dice, defense_roll = self.roll_defense(
            defender,
            defense,
            decision_provider,
        )
        success = defense_roll >= attack.attack_roll
        label = "闪避" if defense == "dodge" else "格挡"
        print(f"{label}骰 1d10 = {dice}")
        percentage_modifiers = []
        if defense == "block":
            if not success and not defender.has_status(
                "retain_attack_phase_on_failed_defense"
            ):
                defender.attack_phase_count = 0
            if not getattr(attack, "ignore_block", False):
                percentage_modifiers.append(-defender.block_resistance)
        return {
            "defense_type": defense,
            "success": success,
            "defense_roll": defense_roll,
            "percentage_modifiers": percentage_modifiers,
            "flat_modifiers": [],
            "ends_attack": defense == "dodge" and success,
        }

    @staticmethod
    def should_continue_flow(rule, result, remaining_damage):
        if rule == "always":
            return True
        if rule == "success":
            return bool(result["success"])
        if rule == "failure":
            return not result["success"]
        if rule in {"damage_remaining", "attack_remaining"}:
            return remaining_damage > 0 and not result.get("ends_attack", False)
        return False

    @staticmethod
    def emit_defense_step_resolved(
        defender,
        attack,
        result,
        *,
        decision_provider=None,
    ):
        manager = getattr(getattr(defender, "game_manager", None), "event_manager", None)
        if manager is None:
            return None
        battle = getattr(defender, "current_battle", None)
        return manager.emit(
            "defense_step_resolved",
            actor=defender,
            source=attack,
            target=defender,
            phase=getattr(battle, "current_phase", "defense"),
            battle=battle,
            position=getattr(defender, "position", None),
            payload={
                "attack_id": attack.attack_id,
                "step_index": result["index"],
                "defense_type": result["defense_type"],
                "success": result["success"],
                "attack_roll": attack.attack_roll,
                "defense_roll": result["defense_roll"],
            },
            decision_provider=decision_provider,
        )

    @staticmethod
    def emit_flow_defense_resolved(
        defender,
        attack,
        result,
        steps,
        *,
        decision_provider=None,
    ):
        manager = getattr(getattr(defender, "game_manager", None), "event_manager", None)
        if manager is None:
            return None
        battle = getattr(defender, "current_battle", None)
        return manager.emit(
            "defense_resolved",
            actor=defender,
            source=attack,
            target=defender,
            value=result["damage"],
            phase=getattr(battle, "current_phase", "defense"),
            battle=battle,
            position=getattr(defender, "position", None),
            payload={
                "attack_id": attack.attack_id,
                "defense_type": attack.defense_type,
                "defense_flow": [dict(item) for item in steps],
                "success": not result["hit"],
                "hit": result["hit"],
                "damage": result["damage"],
                "attack_roll": attack.attack_roll,
                "attacker_id": getattr(attack.source, "character_id", None),
                "attacker_name": getattr(attack.source, "name", None),
            },
            decision_provider=decision_provider,
        )

    @staticmethod
    def _emit_defense_resolved(
        defender,
        attack,
        defense_type,
        result,
        *,
        previous_roll=None,
        decision_provider=None,
    ):
        game_manager = getattr(defender, "game_manager", None)
        event_manager = getattr(game_manager, "event_manager", None)
        if event_manager is None:
            return None
        defense_name = (
            "offset" if isinstance(defense_type, OffsetAttempt) else defense_type
        )
        roll_result = getattr(defender, "last_defense_roll_result", None)
        if isinstance(defense_type, OffsetAttempt):
            success = bool(defense_type.success)
            roll_result = defense_type.roll_result
        elif roll_result is not None and roll_result is not previous_roll:
            success = roll_result.total >= attack.attack_roll
        else:
            success = False
            roll_result = None
        battle = getattr(defender, "current_battle", None)
        return event_manager.emit(
            "defense_resolved",
            actor=defender,
            source=attack,
            target=defender,
            value=result["damage"],
            phase=getattr(battle, "current_phase", "defense"),
            battle=battle,
            position=getattr(defender, "position", None),
            payload={
                "attack_id": attack.attack_id,
                "defense_type": defense_name,
                "success": success,
                "hit": result["hit"],
                "damage": result["damage"],
                "attack_roll": attack.attack_roll,
                "defense_roll": (
                    None if roll_result is None else roll_result.total
                ),
                "attacker_id": getattr(attack.source, "character_id", None),
                "attacker_name": getattr(attack.source, "name", None),
            },
            decision_provider=decision_provider,
        )

    def resolve_offset_attempt(
        self,
        defender,
        attack,
        attempt,
        decision_provider=None,
    ):
        if attempt.defender is not defender or attempt.incoming_attack is not attack:
            raise ValueError("抵消记录与当前攻击不匹配")
        attack.offset_attempt = attempt
        damage_before_offset = self.preview_damage(defender, attack)
        final_damage = self.preview_damage(
            defender,
            attack,
            flat_modifiers=[-attempt.reduction],
        )
        attempt.incoming_damage_before_offset = damage_before_offset
        attempt.incoming_damage_after_offset = final_damage
        if final_damage <= 0 or damage_before_offset <= 0:
            remaining_segments = 0
        else:
            per_segment_damage = (
                damage_before_offset / max(1, attack.original_hit_segments)
            )
            remaining_segments = min(
                attack.original_hit_segments,
                math.ceil(final_damage / per_segment_damage),
            )
        attempt.remaining_hit_segments = remaining_segments
        attack.final_hit_segments = remaining_segments
        if final_damage <= 0:
            return self.finish_attack(
                defender,
                attack,
                hit=bool(getattr(attack, "counts_offset_as_hit", False)),
                damage=0,
                decision_provider=decision_provider,
            )
        return self.finish_attack(
            defender,
            attack,
            hit=True,
            flat_modifiers=[-attempt.reduction],
            decision_provider=decision_provider,
        )

    def roll_defense(self, defender, defense_stat, decision_provider=None):
        result = RollResolver().roll(
            defender,
            defense_stat,
            decision_provider=decision_provider,
            phase="防御—幸运",
            initial_die=random.randint(1, 10),
            roller=lambda: random.randint(1, 10),
        )
        defender.last_defense_roll_result = result
        return result.die, result.total

    def resolve_dodge(self, defender, attack, decision_provider=None):
        dice, defense_roll = self.roll_defense(
            defender,
            "dodge",
            decision_provider,
        )
        success = defense_roll >= attack.attack_roll
        print(f"闪避骰 1d10 = {dice}")
        if success:
            return self.finish_attack(
                defender,
                attack,
                hit=False,
                damage=0,
                decision_provider=decision_provider,
            )
        return self.finish_attack(
            defender,
            attack,
            hit=True,
            damage=attack.value,
            decision_provider=decision_provider,
        )

    def resolve_block(self, defender, attack, decision_provider=None):
        dice, defense_roll = self.roll_defense(
            defender,
            "block",
            decision_provider,
        )
        success = defense_roll >= attack.attack_roll
        print(f"格挡骰 1d10= {dice}")
        if not success and not defender.has_status("retain_attack_phase_on_failed_defense"):
            defender.attack_phase_count = 0
        return self.finish_attack(
            defender,
            attack,
            hit=True,
            percentage_modifiers=([] if getattr(attack, "ignore_block", False)
                                  else [-defender.block_resistance]),
            decision_provider=decision_provider,
        )

    def resolve_legacy_offset(self, defender, attack, decision_provider=None):
        """Compatibility path for callers which still pass the string offset."""
        if defender.attack_phase_count <= 0:
            print(f"{defender.name}没有可用的攻击阶段")
            return self.finish_attack(
                defender,
                attack,
                hit=True,
                damage=attack.value,
                decision_provider=decision_provider,
            )
        dice, defense_roll = self.roll_defense(
            defender,
            "offset",
            decision_provider,
        )
        success = defense_roll >= attack.attack_roll
        offset_damage = defender.atk
        defender.attack_phase_count -= 1
        print(f"抵消骰 1d10 ={dice}")
        if success:
            final_damage = self.preview_damage(
                defender,
                attack,
                flat_modifiers=[-offset_damage],
            )
            if final_damage <= 0:
                return self.finish_attack(
                    defender,
                    attack,
                    hit=bool(getattr(attack, "counts_offset_as_hit", False)),
                    damage=0,
                    decision_provider=decision_provider,
                )
            return self.finish_attack(
                defender,
                attack,
                hit=True,
                flat_modifiers=[-offset_damage],
                decision_provider=decision_provider,
            )
        actual_reduction = min(offset_damage, attack.value * 0.5)
        return self.finish_attack(
            defender,
            attack,
            hit=True,
            flat_modifiers=[-actual_reduction],
            decision_provider=decision_provider,
        )

    def create_damage_event(
        self,
        defender,
        attack,
        damage=None,
        percentage_modifiers=None,
        flat_modifiers=None,
    ):
        is_true_damage = attack.damage_type == "true_damage"
        return DamageEvent(
            source=attack.source,
            target=defender,
            value=attack.value if damage is None else damage,
            damage_type=attack.damage_type,
            skill=attack.skill,
            percentage_modifiers=(
                list(attack.percentage_modifiers)
                + ([] if is_true_damage else list(percentage_modifiers or []))
            ),
            flat_modifiers=(
                list(attack.flat_modifiers)
                + ([] if is_true_damage else list(flat_modifiers or []))
            ),
            action_id=attack.action_id,
            skill_id=attack.skill_id,
            source_tags=attack.source_tags,
            ignore_shield=attack.ignore_shield,
            source_statuses_snapshotted=True,
            attack_id=attack.attack_id,
            target_type=attack.target_type,
            target_rules=attack.target_rules,
        )

    def preview_damage(
        self,
        defender,
        attack,
        damage=None,
        percentage_modifiers=None,
        flat_modifiers=None,
    ):
        event = self.create_damage_event(
            defender,
            attack,
            damage=damage,
            percentage_modifiers=percentage_modifiers,
            flat_modifiers=flat_modifiers,
        )
        return DamageResolver().calculate(event)

    def finish_attack(
        self,
        defender,
        attack,
        hit,
        damage=None,
        percentage_modifiers=None,
        flat_modifiers=None,
        decision_provider=None,
    ):
        attack.hit = hit
        attack.resolved = True
        if not hit:
            attack.final_damage = 0
            attack.final_hit_segments = 0
            print("未命中")
            self.consume_attack_resolved(defender, attack)
            return {"hit": False, "damage": 0}

        if getattr(attack, "defer_damage", False):
            # Trap-like attacks finish every defense first, then calculate one
            # shared damage pool from the final hit list.
            attack.final_damage = 0
            self.consume_attack_resolved(defender, attack)
            return {"hit": True, "damage": 0}

        damage_event = self.create_damage_event(
            defender,
            attack,
            damage=damage,
            percentage_modifiers=percentage_modifiers,
            flat_modifiers=flat_modifiers,
        )
        final_damage = DamageResolver().resolve(
            damage_event,
            decision_provider=decision_provider,
        )
        resolved_target = damage_event.target
        attack.final_damage = final_damage
        for shield, absorbed in damage_event.shield_absorptions:
            print(f"{resolved_target.name}的{shield.name}吸收了{absorbed}点伤害。")
        print(f"{attack.source.name}对{resolved_target.name}造成了{final_damage}点HP伤害")
        if (
            not getattr(damage_event, "target_was_in_brink", False)
            and resolved_target.has_status("brink_of_death")
        ):
            print(f"{resolved_target.name}进入了濒死状态。")
        self.consume_attack_resolved(defender, attack)
        return {"hit": True, "damage": final_damage}

    @staticmethod
    def consume_attack_resolved(defender, attack):
        attack.change_target(defender, reason="defense_resolution")
        attack.consume_resolution_modifiers()
