from copy import copy
from dataclasses import dataclass
from itertools import count
from uuid import uuid4

from game.turn.defense import (
    DefenseResolver,
    OffsetAttempt,
    get_offset_attack_options,
    resolve_offset_attack_option,
)
from game.action.action import Action
from game.action.action_resolver import ActionResolver
from game.turn.decision import (
    DecisionOption,
    DecisionRefreshRequested,
    DecisionRequest,
    NumericDecisionRequest,
)
from game.turn.effects import create_battle_effect
from game.turn.initialivemanager import InitiativeManager
from game.action.action_list import (
    ActionContext,
    ActionListBuilder,
    is_free_immediate_skill_entry,
)
from game.skill.skill_action import SkillAction
from game.skill.skill_runtime import SkillUnavailableError
from game.turn.roll import RollResolver
import random
from game.turn.damage import report_discarded_attacks


_ORDER_CHANGE_SEQUENCE = count()


@dataclass(eq=False)
class CombatLink:
    """One explicit reason why two participants remain in a formal battle."""

    actor: object
    target: object
    source: object = None
    active: bool = True

    def involves(self, character):
        return character is self.actor or character is self.target

    def is_live(self, participants):
        return (
            self.active
            and self.actor in participants
            and self.target in participants
            and self.actor.is_alive()
            and self.target.is_alive()
        )


@dataclass
class OrderChange:
    """A delayed transformation of one formal battle's round order."""

    operation: str
    subject: object
    anchor: object = None
    duration: object = 1
    source: object = None
    sequence: int = 0
    polarity: str = "neutral"
    purifiable: bool = False

    def __post_init__(self):
        if self.operation not in {
            "move_first",
            "move_last",
            "move_before",
            "move_after",
        }:
            raise ValueError(f"未知的order_change操作：{self.operation}")
        if self.duration is not None and (
            not isinstance(self.duration, int)
            or isinstance(self.duration, bool)
            or self.duration < 1
        ):
            raise ValueError("order_change的duration必须是正整数或None")
        if self.operation in {"move_before", "move_after"}:
            if self.anchor is None:
                raise ValueError(f"{self.operation}必须指定anchor")
            if self.anchor is self.subject:
                raise ValueError("order_change的subject与anchor不能相同")


class BattleManager:
    FORMAL_PHASES = {
        "turn_start",
        "guard",
        "defense",
        "attack",
        "turn_end",
    }

    @property
    def current_phase(self):
        return getattr(self, "_current_phase", None)

    @current_phase.setter
    def current_phase(self, value):
        participants = list(getattr(self, "participants", []))
        capacity_snapshots = {
            character: (
                character.hpmax,
                character.mpmax,
                character.luck_reroll_max,
            )
            for character in participants
        }
        self._current_phase = value
        for character, snapshot in capacity_snapshots.items():
            character.sync_contextual_capacities(*snapshot)

    def __init__(self, participants, *, auto_link=True):
        self.participants = participants.copy()

        self.combat_links = []
        if auto_link:
            for index, actor in enumerate(self.participants):
                for target in self.participants[index + 1:]:
                    # Legacy/direct construction has no request object from
                    # which to infer intent.  Preserve only its old inference;
                    # real game creation supplies explicit request links.
                    if not actor.is_ally(target):
                        self.add_combat_link(actor, target, source="initial")

        self.battle_id = uuid4().hex
        self.initial_order = []
        self.current_order = []
        self.round_order_snapshot = []
        self.pending_order_changes = []
        self.active_order_changes = []
        self.ended= False
        self.current_phase = None
        self.current_character = None
        self.current_index = 0
        self.started = False
        self.effects = []
        self.simple_round_history = []
        self.global_turn = 0
        self.round_participants = set()
        self.stayed_this_round = set()
        self.guarded_this_round = set()
        self.guard_history = []
        self.all_stayed_last_round = False
        self.round_mp_paid_total = 0
        self.round_mp_payments = []
        self.end_reason = None
        self.late_participants = []
        # 兼容此前短暂使用过的内部名称。
        self.late_attackers = self.late_participants

    def add_combat_link(self, actor, target, source=None):
        if actor is target:
            raise ValueError("CombatLink的双方不能是同一角色")
        for link in self.combat_links:
            if (
                link.active
                and {link.actor, link.target} == {actor, target}
                and link.source is source
            ):
                return link
        link = CombatLink(actor, target, source=source)
        self.combat_links.append(link)
        return link

    def absorb_combat_links(self, other):
        for link in getattr(other, "combat_links", []):
            if link.active:
                self.add_combat_link(link.actor, link.target, link.source)
        return True

    def start_battle(self):
        travel_groups = {
            character.travel_group
            for character in self.participants
            if getattr(character, "travel_group", None) is not None
        }
        for travel_group in travel_groups:
            travel_group.dissolve()
        for character in self.participants:
            character.in_battle = True
            character.current_battle = self
            character.start_battle()
        for character in self.participants:
            character.update_visibility(self.participants)

        self.initial_order = InitiativeManager().determine_order(self.participants)
        self.current_order = self.initial_order.copy()
        self.started = True
        for character in self.participants:
            manager = getattr(character, "game_manager", None)
            event_manager = getattr(manager, "event_manager", None)
            if event_manager is not None:
                event_manager.emit(
                    "battle_joined",
                    actor=character,
                    source=self,
                    target=character,
                    battle=self,
                    position=character.position,
                )
        self.check_battle_end()
        return self.current_order
    #开始战斗

    def remove_participant(
        self,
        character,
        *,
        preserve_target_locked_attacks=False,
        decision_provider=None,
    ):
        checking = getattr(self, "_checking_field_exits", None)
        if checking is None:
            checking = self._checking_field_exits = set()
        if character in self.participants and character.is_alive() and character not in checking:
            manager = getattr(character, "game_manager", None)
            fields = getattr(manager, "field_manager", None)
            if fields is not None:
                checking.add(character)
                try:
                    fields.resolve_battle_exit(self, character, decision_provider)
                finally:
                    checking.discard(character)
                if character not in self.participants:
                    return
        old_position = character.position
        if character in self.participants:
            self.participants.remove(character)
        if character in self.current_order:
            self.current_order.remove(character)
        if character in self.initial_order:
            self.initial_order.remove(character)
        if character in self.round_order_snapshot:
            self.round_order_snapshot.remove(character)
        for link in self.combat_links:
            if link.involves(character):
                link.active = False
        self.pending_order_changes[:] = [
            change
            for change in self.pending_order_changes
            if change.subject is not character and change.anchor is not character
        ]
        self.active_order_changes[:] = [
            change
            for change in self.active_order_changes
            if change.subject is not character and change.anchor is not character
        ]

        character.in_battle = False
        character.current_battle = None

        if preserve_target_locked_attacks:
            report_discarded_attacks([
                attack for attack in character.pending_attacks
                if not (attack.target is character and getattr(attack, "target_lock", False) and not attack.resolved)
            ], "target_left_battle")
            character.pending_attacks[:] = [
                attack
                for attack in character.pending_attacks
                if attack.target is character
                and getattr(attack, "target_lock", False)
                and not attack.resolved
            ]
        else:
            report_discarded_attacks(character.pending_attacks, "target_left_battle")
            character.pending_attacks.clear()
        for participant in self.participants:
            report_discarded_attacks([
                attack for attack in participant.pending_attacks
                if attack.source is character or attack.target is character
            ], "participant_left_battle")
            participant.pending_attacks[:] = [
                attack
                for attack in participant.pending_attacks
                if attack.source is not character
                and attack.target is not character
            ]
        self.effects[:] = [
            effect
            for effect in self.effects
            if effect.resolved
            or (
                effect.actor is not character
                and effect.target is not character
            )
        ]

        manager = getattr(character, "game_manager", None)
        event_manager = getattr(manager, "event_manager", None)
        if event_manager is not None:
            event_manager.emit(
                "battle_left",
                actor=character,
                source=self,
                target=character,
                battle=self,
                position=old_position,
            )

        self.check_battle_end()
    #角色退出战斗

    def add_participant(self, character):
        return bool(self.add_participants([character]))

    def add_participants(self, characters):
        """Append one newcomer batch after all established battle members.

        Members of the newcomer batch determine their order among themselves,
        but never reroll or displace an existing participant.
        """
        newcomers = []
        for character in characters:
            if character in self.participants or character in newcomers:
                continue
            newcomers.append(character)
        if not newcomers:
            return []

        for character in newcomers:
            if getattr(character, "travel_group", None) is not None:
                character.travel_group.dissolve()
            self.participants.append(character)
            character.current_battle = self
            character.start_battle()
            manager = getattr(character, "game_manager", None)
            event_manager = getattr(manager, "event_manager", None)
            if event_manager is not None:
                event_manager.emit(
                    "battle_joined",
                    actor=character,
                    source=self,
                    target=character,
                    battle=self,
                    position=character.position,
                )

        living_newcomers = [
            character for character in newcomers if character.is_alive()
        ]
        newcomer_order = InitiativeManager().determine_order(living_newcomers)
        for character in newcomer_order:
            if character not in self.initial_order:
                self.initial_order.append(character)
            if character not in self.current_order:
                self.current_order.append(character)
        return newcomer_order

    def queue_late_participant(self, character):
        """Ensure a teleported newcomer still receives non-attack phases.

        A newcomer with no remaining attack phase must still reach guard and
        defense.  The ordinary attack-phase check will skip only their attack.
        """
        if (
            character in self.participants
            and character not in self.late_participants
        ):
            self.late_participants.append(character)
            if character not in self.current_order:
                self.current_order.append(character)
            if self.current_phase == "round_ended":
                self.current_index = self.current_order.index(character)
                self.start_character_turn(character)
        return character in self.late_participants

    # Compatibility for callers/tests using the old internal name.
    def queue_late_attacker(self, character):
        return self.queue_late_participant(character)

    def refresh_participant_order(self):
        """Synchronize battle order without rerolling established members."""
        living = [
            character
            for character in self.participants
            if character.is_alive()
        ]
        self.initial_order[:] = [
            character for character in self.initial_order if character in living
        ]
        missing = [
            character for character in living if character not in self.initial_order
        ]
        if missing:
            self.initial_order.extend(
                InitiativeManager().determine_order(missing)
            )
        self.current_order = self.initial_order.copy()
        self.ended = False
        self.end_reason = None
        return self.current_order

    def queue_order_change(
        self,
        operation,
        subject,
        *,
        anchor=None,
        duration=1,
        source=None,
    ):
        if subject not in self.participants or not subject.is_alive():
            raise ValueError("order_change的subject必须是存活的正式参战者")
        if operation in {"move_before", "move_after"} and (
            anchor not in self.participants or not anchor.is_alive()
        ):
            raise ValueError("order_change的anchor必须是存活的正式参战者")
        change = OrderChange(
            operation=operation,
            subject=subject,
            anchor=anchor,
            duration=duration,
            source=source,
            sequence=next(_ORDER_CHANGE_SEQUENCE),
        )
        self.pending_order_changes.append(change)
        return change

    @staticmethod
    def apply_order_change(order, change):
        subject = change.subject
        anchor = change.anchor
        if subject not in order:
            return False
        if change.operation in {"move_before", "move_after"} and (
            anchor not in order or anchor is subject
        ):
            return False

        order.remove(subject)
        if change.operation == "move_first":
            destination = 0
        elif change.operation == "move_last":
            destination = len(order)
        elif change.operation == "move_before":
            destination = order.index(anchor)
        else:
            destination = order.index(anchor) + 1
        order.insert(destination, subject)
        return True

    def prepare_round_order(self):
        """Build and lock this formal battle round's action order."""
        living = [
            character
            for character in self.participants
            if character.is_alive()
        ]
        self.initial_order[:] = [
            character for character in self.initial_order if character in living
        ]
        # Defensive compatibility for callers that directly edited participants.
        missing = [
            character for character in living if character not in self.initial_order
        ]
        if missing:
            self.initial_order.extend(
                InitiativeManager().determine_order(missing)
            )

        self.active_order_changes.extend(self.pending_order_changes)
        self.pending_order_changes.clear()
        self.active_order_changes.sort(key=lambda change: change.sequence)

        order = self.initial_order.copy()
        remaining_changes = []
        for change in self.active_order_changes:
            if change.subject not in living:
                continue
            if (
                change.operation in {"move_before", "move_after"}
                and change.anchor not in living
            ):
                continue
            self.apply_order_change(order, change)
            if change.duration is None:
                remaining_changes.append(change)
            elif change.duration > 1:
                change.duration -= 1
                remaining_changes.append(change)
        self.active_order_changes = remaining_changes
        self.current_order = order
        self.round_order_snapshot = order.copy()
        return self.current_order

    def check_battle_end(self):
        living_participants = [
            character
            for character in self.participants
            if character.is_alive()
        ]
        has_live_link = any(
            link.is_live(living_participants)
            for link in self.combat_links
        )
        if not has_live_link:
            self.end_battle(reason="no_combat_links")
            return True
        return False
    #战斗结束检查

    def end_battle(self, reason=None):
        if self.ended:
            return False
        self.ended = True
        self.end_reason = reason
        self.current_character = None
        self.current_phase = "battle_ended"
        managers = {getattr(character, "game_manager", None) for character in self.participants}
        for manager in managers:
            if manager is not None:
                manager.field_manager.on_battle_end(self)
                manager.rule_reports.record("battle_ended", targets=list(self.participants),
                                            battle=self, public={"reason": reason})
        self.pending_order_changes.clear()
        self.active_order_changes.clear()
        for character in self.participants:
            manager = getattr(character, "game_manager", None)
            event_manager = getattr(manager, "event_manager", None)
            if event_manager is not None:
                event_manager.emit(
                    "battle_left",
                    actor=character,
                    source=self,
                    target=character,
                    battle=self,
                    position=character.position,
                    payload={"reason": reason},
                )
            character.in_battle = False
            character.current_battle = None
            character.temporary_mp_waits_for_personal_turn_end = False
        return True
    #战斗结束

    def start_battle_turn(self):
        if self.ended: return False
        if self.all_stayed_last_round:
            self.end_battle(reason="all_stayed")
            return False
        self.prepare_round_order()
        if not self.current_order:return False

        self.round_participants = {
            character
            for character in self.participants
            if character.is_alive()
        }
        self.stayed_this_round = set()
        self.guarded_this_round = set()
        self.all_stayed_last_round = False

        self.current_index = 0
        if self.get_simple_rounds(None, "battle_start"):
            self.current_character = None
            self.current_phase = "battle_start"
            return True
        self.current_character = (self.current_order[0])
        self.start_character_turn(self.current_character)
        return True
    #开始战斗轮

    def add_effect(self, effect, actor, target):
        battle_effect = create_battle_effect(effect, actor, target)
        self.effects.append(battle_effect)
        if battle_effect.is_ambush and battle_effect.attack_mode == "fixed":
            for defender in battle_effect.targets:
                defender.status_flags.add("ambushed")
        return battle_effect

    def get_simple_rounds(self, target, phase):
        return [
            effect
            for effect in self.effects
            if not effect.resolved
            and effect.trigger_phase == phase
            and (phase == "battle_start" or effect.target is target)
        ]

    def order_simple_rounds(self, effects):
        actors = []
        for effect in effects:
            if effect.actor not in actors:
                actors.append(effect.actor)
        actor_order = InitiativeManager().determine_order(actors)
        actor_index = {
            actor: index
            for index, actor in enumerate(actor_order)
        }
        return sorted(effects, key=lambda effect: actor_index[effect.actor])

    def run_simple_rounds_before(self, target, phase, decision_provider):
        effects = self.order_simple_rounds(
            self.get_simple_rounds(target, phase)
        )
        results = []
        for effect in effects:
            results.append(
                self.resolve_simple_round(effect, decision_provider)
            )
        return results

    def resolve_simple_round(self, effect, decision_provider):
        saved_character = self.current_character
        saved_phase = self.current_phase
        actor = effect.actor

        try:
            defenders = [
                defender
                for defender in effect.targets
                if defender in self.participants and defender.is_alive()
            ]
            if actor not in self.participants or not actor.is_alive() or not defenders:
                return None

            if effect.consume_attack_phase:
                if actor.attack_phase_count <= 0:
                    return {
                        "skipped": True,
                        "reason": "no_attack_phase",
                    }
                actor.attack_phase_count -= 1

            self.current_character = actor
            self.current_phase = "simple_round_attack"
            print(f"{actor.name}进行额外攻击阶段")
            if effect.attack_mode == "select":
                return self.run_virtual_attack_phase(
                    actor,
                    decision_provider,
                    characters=list(dict.fromkeys([actor, *defenders])),
                    preferred_target=defenders[0],
                    preserve_attack_phase_count=True,
                    simple_round_effect=effect,
                )

            attacks = self.create_fixed_simple_round_attacks(
                effect,
                defenders,
                decision_provider,
            )
            effect.attack_events = attacks
            effect.attack_event = attacks[0] if attacks else None
            return self.resolve_simple_round_attack_events(
                attacks,
                decision_provider,
                effect=effect,
            )
        finally:
            effect.resolved = True
            self.simple_round_history.append(effect)
            if effect.is_ambush:
                for defender in effect.targets:
                    self.clear_resolved_ambush_status(defender, effect)
            self.current_character = saved_character
            self.current_phase = saved_phase

    def create_fixed_simple_round_attacks(
        self,
        effect,
        defenders,
        decision_provider,
    ):
        """Create one shared-roll attack event for every fixed-mode defender."""
        self.request_battle_plus_actions(
            effect.actor,
            "额外攻击",
            decision_provider,
        )
        first_target = defenders[0]
        damage_value = effect.damage_value
        if effect.damage_value_source in {"actor_attribute", "target_attribute"}:
            source = (
                effect.actor
                if effect.damage_value_source == "actor_attribute"
                else first_target
            )
            attribute = getattr(source, effect.damage_attribute)
            attribute = getattr(attribute, "value", attribute)
            damage_value = int(
                attribute * effect.damage_multiplier + effect.damage_flat
            )
        action = Action(
            effect.actor,
            "attack",
            first_target,
            attack_stat=effect.attack_stat,
            attack_roll_bonus=effect.attack_roll_bonus,
            damage_value=damage_value,
            damage_type=effect.damage_type,
            damage_percentage_modifiers=effect.damage_percentage_modifiers,
            damage_flat_modifiers=effect.damage_flat_modifiers,
            damage_action_id=(
                effect.source
                if isinstance(effect.source, str)
                else "attack"
            ),
            skill=effect.skill,
            ignore_attack_phase_count=True,
            # The skill/ambush effect already selected its legal defenders.
            # Do not run the ordinary attack command's vision check again.
            ignore_target_visibility=True,
        )
        if not ActionResolver().resolve(action, decision_provider):
            raise RuntimeError(f"{effect.actor.name}的额外攻击未能执行")

        first = action.created_attack_event
        first.resolution_channel = effect.resolution_channel
        attacks = [first]
        for defender in defenders[1:]:
            attack = copy(first)
            attack.target = defender
            attack.percentage_modifiers = list(first.percentage_modifiers)
            attack.flat_modifiers = list(first.flat_modifiers)
            attack.source_tags = set(first.source_tags)
            attack.damage_segments = list(first.damage_segments)
            attack.resolved = False
            attack.hit = None
            attack.final_damage = 0
            manager = getattr(effect.actor, "game_manager", None)
            relationships = getattr(manager, "relationship_manager", None)
            if relationships is not None:
                relationships.resolve_attack_attitude(
                    effect.actor,
                    defender,
                    decision_provider,
                )
            defender.pending_attacks.append(attack)
            attacks.append(attack)
        return attacks

    def clear_resolved_ambush_status(self, defender, current_effect=None):
        unresolved = any(
            effect is not current_effect
            and effect.is_ambush
            and not effect.resolved
            and defender in effect.targets
            for effect in self.effects
        )
        if not unresolved:
            defender.status_flags.discard("ambushed")

    @staticmethod
    def _simple_round_defender_still_present(state, defender):
        return (
            defender.is_alive()
            and defender.position is not None
            and defender.position is state["defender_positions"].get(defender)
        )

    def resolve_simple_round_attack_events(
        self,
        attacks,
        decision_provider,
        *,
        effect=None,
    ):
        """Resolve one multi-defender simple round in initiative order."""
        attacks = [attack for attack in attacks if attack is not None]
        if not attacks:
            return {
                "defense_order": [],
                "results": [],
                "completed_defenders": set(),
                "used_guarders": set(),
            }

        actor = attacks[0].source
        attacks_by_defender = {}
        for attack in attacks:
            attacks_by_defender.setdefault(attack.target, []).append(attack)
        defenders = list(attacks_by_defender)
        defense_order = self.get_simple_round_defense_order(defenders)
        state = {
            "actor": actor,
            "defenders": set(defenders),
            "attacks_by_defender": attacks_by_defender,
            "defense_order": defense_order,
            "completed_defenders": set(),
            "used_guarders": set(),
            "defender_positions": {
                defender: defender.position for defender in defenders
            },
            "effect": effect,
        }
        if effect is not None:
            effect.targets = list(defenders)
            effect.attack_events = attacks
            effect.attack_event = attacks[0]
            effect.defense_order = list(defense_order)
            effect.completed_defenders = state["completed_defenders"]
            effect.used_guarders = state["used_guarders"]
            effect.defender_positions = dict(state["defender_positions"])
            if effect.is_ambush:
                for defender in defenders:
                    defender.status_flags.add("ambushed")

        results = []
        for defender in defense_order:
            defender_attacks = attacks_by_defender[defender]
            if not self._simple_round_defender_still_present(state, defender):
                report_discarded_attacks(defender_attacks, "defender_dead_or_left")
                for attack in defender_attacks:
                    if attack in defender.pending_attacks:
                        defender.pending_attacks.remove(attack)
                results.append({
                    "defender": defender,
                    "skipped": True,
                    "reason": "defender_dead_or_left",
                })
                if effect is not None and effect.is_ambush:
                    self.clear_resolved_ambush_status(defender, effect)
                continue

            self.current_phase = "simple_round_guard"
            self.resolve_simple_round_guard(
                state,
                defender,
                defender_attacks,
                decision_provider,
            )

            if not self._simple_round_defender_still_present(state, defender):
                report_discarded_attacks(defender_attacks, "defender_dead_or_left_during_guard")
                for attack in defender_attacks:
                    if attack in defender.pending_attacks:
                        defender.pending_attacks.remove(attack)
                results.append({
                    "defender": defender,
                    "skipped": True,
                    "reason": "defender_dead_or_left_during_guard",
                })
                if effect is not None and effect.is_ambush:
                    self.clear_resolved_ambush_status(defender, effect)
                continue

            pending = [
                attack
                for attack in defender_attacks
                if attack in defender.pending_attacks
            ]
            if not pending:
                defense_result = {
                    "attack_count": len(defender_attacks),
                    "hit_count": sum(
                        int(bool(attack.hit))
                        for attack in defender_attacks
                    ),
                    "total_damage": sum(
                        attack.final_damage
                        for attack in defender_attacks
                    ),
                    "guarded": True,
                    "defense_skipped": True,
                }
            else:
                self.current_character = defender
                self.current_phase = "simple_round_defense"
                print(f"{defender.name}的额外防御阶段")
                self.request_battle_plus_actions(
                    defender,
                    "额外防御",
                    decision_provider,
                )
                defense_result = {
                    "attack_count": 0,
                    "hit_count": 0,
                    "total_damage": 0,
                }
                for attack in pending:
                    if not defender.is_alive():
                        break
                    defense_type = self.request_defense(
                        defender,
                        decision_provider,
                        attacks=[attack],
                        phase="simple_round_defense",
                    )
                    current_result = DefenseResolver().resolve_phase(
                        defender,
                        defense_type,
                        attacks=[attack],
                        decision_provider=decision_provider,
                    )
                    for key in defense_result:
                        defense_result[key] += current_result[key]

            if self._simple_round_defender_still_present(state, defender):
                state["completed_defenders"].add(defender)
            results.append({
                "defender": defender,
                "skipped": False,
                "result": defense_result,
            })
            if effect is not None and effect.is_ambush:
                self.clear_resolved_ambush_status(defender, effect)

        return {
            "defense_order": defense_order,
            "results": results,
            "completed_defenders": state["completed_defenders"],
            "used_guarders": state["used_guarders"],
        }

    def resolve_simple_round_attack_event(self, attack, decision_provider):
        """Backward-compatible single-defender entry point."""
        return self.resolve_simple_round_attack_events(
            [attack],
            decision_provider,
        )

    def get_attack_targets(self, character):
        return [
            target
            for target in self.participants
            if target is not character
            and target.in_battle
            and target.is_alive()
            and target in character.own_visible
        ]

    def get_guard_targets(self, character):
        """Return current legal guard targets in battle participant order."""
        context = ActionContext(
            actor=character,
            phase="guard_phase",
            turn_number=self.global_turn,
            battle=self,
            characters=list(self.participants),
        )
        entries = [
            entry
            for entry in ActionListBuilder().get_available_actions(context)
            if entry.skill is None
        ]
        guard_entry = next(
            (entry for entry in entries if entry.action_id == "guard"),
            None,
        )
        return [] if guard_entry is None else list(guard_entry.valid_targets)

    def get_emergency_guard_targets(self, guarder, *, position=None):
        """Return mandatory arrival-guard targets at one exact map node."""
        position = guarder.position if position is None else position
        if (
            not guarder.is_alive()
            or guarder.has_status("brink_of_death")
            or not guarder.guard_opportunity_available
        ):
            return []
        return [
            target
            for target in self.participants
            if target is not guarder
            and target.is_alive()
            and target.position is position
            and guarder.is_ally(target)
            and target.is_ally(guarder)
            and any(
                not attack.resolved
                and not getattr(attack, "defense_roll_started", False)
                for attack in target.pending_attacks
            )
        ]

    def resolve_emergency_guard(
        self,
        guarder,
        original_target,
        decision_provider,
    ):
        """Immediately block every not-yet-judged attack on one ally."""
        if original_target not in self.get_emergency_guard_targets(guarder):
            return None

        guarder.guard_opportunity_available = False
        self.guarded_this_round.add(guarder)
        records = []
        attacks = [
            attack
            for attack in list(original_target.pending_attacks)
            if not attack.resolved
            and not getattr(attack, "defense_roll_started", False)
        ]
        for attack in attacks:
            if (
                not guarder.is_alive()
                or guarder.has_status("brink_of_death")
            ):
                break
            record = self.resolve_guard_attack(
                guarder,
                original_target,
                attack,
                decision_provider,
                guard_kind="emergency",
            )
            if record is None:
                break
            records.append(record)
            detail = record["results"][0]
            if detail["entered_brink_of_death"] or detail["guarder_defeated"]:
                break
        if not records:
            return None
        summary = {
            "round": self.global_turn,
            "guarder": guarder,
            "target": original_target,
            "guard_kind": "emergency",
            "results": [
                detail
                for record in records
                for detail in record["results"]
            ],
        }
        del self.guard_history[-len(records):]
        self.guard_history.append(summary)
        return summary

    def is_attack_guardable(self, attack):
        """偷袭、超距攻击和普通攻击均可进入援护流程。"""
        return not getattr(attack, "resolved", False)

    def get_simple_round_guard_candidates(self, state, target):
        """Return allies allowed to guard this simple-round defender."""
        game_manager = getattr(target, "game_manager", None)
        characters = (
            list(game_manager.characters)
            if game_manager is not None
            else list(self.participants)
        )
        return [
            character
            for character in characters
            if character is not target
            and character is not state["actor"]
            and character not in state["used_guarders"]
            and character.is_alive()
            and not character.has_status("brink_of_death")
            and character.is_ally(target)
            and target.is_ally(character)
            # 简易援护的“同位置”严格指同一地图节点；高层与地面不同。
            and character.position is target.position
            and (
                character not in state["defenders"]
                or character in state["completed_defenders"]
            )
            and getattr(character, "current_battle", None) in {
                None,
                self,
                getattr(target, "current_battle", None),
            }
        ]

    def get_global_action_order(self, characters):
        """Order characters by this turn's map order, with a safe fallback."""
        if not characters:
            return []
        game_manager = next(
            (
                getattr(character, "game_manager", None)
                for character in characters
                if getattr(character, "game_manager", None) is not None
            ),
            None,
        )
        turn_manager = getattr(game_manager, "turn_manager", None)
        global_order = list(
            getattr(turn_manager, "global_action_order", []) or []
        )
        ordered = [
            character for character in global_order
            if character in characters
        ]
        missing = [
            character for character in characters
            if character not in ordered
        ]
        if missing:
            ordered.extend(InitiativeManager().determine_order(missing))
        return ordered

    def get_simple_round_defense_order(self, defenders):
        """Use formal round order first, then map order for outsiders."""
        defenders = list(dict.fromkeys(defenders))
        battle_groups = []
        outsiders = []
        for defender in defenders:
            battle = getattr(defender, "current_battle", None)
            if (
                battle is None
                or battle.ended
                or defender not in battle.participants
            ):
                outsiders.append(defender)
                continue
            group = next(
                (item for item in battle_groups if item[0] is battle),
                None,
            )
            if group is None:
                group = [battle, []]
                battle_groups.append(group)
            group[1].append(defender)

        ordered = []
        for battle, members in battle_groups:
            formal_order = (
                battle.round_order_snapshot
                or battle.current_order
                or battle.initial_order
            )
            ordered.extend(
                character
                for character in formal_order
                if character in members and character not in ordered
            )
            missing = [
                character
                for character in members
                if character not in ordered
            ]
            ordered.extend(self.get_global_action_order(missing))

        ordered.extend(self.get_global_action_order(outsiders))
        return ordered

    def request_simple_round_guards(self, state, target, decision_provider):
        """Collect and lock every ally's answer before resolving any guard."""
        selected = []
        for character in self.get_simple_round_guard_candidates(state, target):
            choice = decision_provider.choose(DecisionRequest(
                character=character,
                phase="简易战斗轮—援护",
                prompt=f"是否援护{target.name}？",
                options=(
                    DecisionOption("援护", True, ("guard",)),
                    DecisionOption("不援护", False, ("skip", "pass")),
                ),
            ))
            if choice:
                selected.append(character)
        return self.get_global_action_order(selected)

    @staticmethod
    def _instant_skill_is_free(entry):
        return is_free_immediate_skill_entry(entry)

    def get_phase_instant_skills(self, character, phase):
        game_manager = getattr(character, "game_manager", None)
        characters = (
            list(game_manager.characters)
            if game_manager is not None
            else list(self.participants)
        )
        context = ActionContext(
            actor=character,
            phase=phase,
            turn_number=self.global_turn,
            battle=self,
            characters=characters,
            game_manager=game_manager,
            incoming_attacks=list(character.pending_attacks),
        )
        return [
            entry
            for entry in ActionListBuilder().get_available_actions(context)
            if is_free_immediate_skill_entry(entry)
        ]

    @staticmethod
    def request_skill_target(character, entry, decision_provider):
        target_type = entry.definition.get("target", "self")
        if target_type in {"self", "none"}:
            return character
        if target_type == "current_position":
            return character.position
        if not entry.valid_targets:
            return None
        return decision_provider.choose(DecisionRequest(
            character=character,
            phase="即时技能目标选择",
            prompt="请选择技能目标。",
            options=tuple(
                DecisionOption(target.name, target, (str(target.name),))
                for target in entry.valid_targets
            ) + (
                DecisionOption("返回", None, ("back", "返回")),
            ),
        ))

    def request_phase_instant_actions(
        self,
        character,
        phase,
        decision_provider,
    ):
        """Resolve free skills and then return to the same battle phase."""
        while True:
            entries = self.get_phase_instant_skills(character, phase)
            if not entries:
                return
            choice = decision_provider.choose(DecisionRequest(
                character=character,
                phase=f"{phase}—即时技能",
                prompt="可以使用不占用本阶段的即时技能。",
                options=(
                    DecisionOption(
                        "继续本阶段",
                        None,
                        ("confirm", "继续", "完成"),
                    ),
                ) + tuple(
                    DecisionOption(entry.name, entry, (entry.action_id,))
                    for entry in entries
                ),
            ))
            if choice is None:
                return
            target = self.request_skill_target(
                character,
                choice,
                decision_provider,
            )
            if target is None:
                continue
            action = SkillAction(
                character,
                choice.skill,
                choice.skill_component,
                target=target,
            )
            action.game_turn = self.global_turn
            if not ActionResolver().resolve(action, decision_provider):
                raise RuntimeError(
                    f"{character.name}的即时技能{choice.name}未能执行"
                )

    def get_simple_guard_instant_skills(self, character):
        """Expose free immediate skills declared for guard/defense windows."""
        game_manager = getattr(character, "game_manager", None)
        characters = (
            list(game_manager.characters)
            if game_manager is not None
            else list(self.participants)
        )
        entries = []
        seen = set()
        for phase in ("simple_round_guard", "simple_round_defense"):
            context = ActionContext(
                actor=character,
                phase=phase,
                turn_number=self.global_turn,
                battle=self,
                characters=characters,
                game_manager=game_manager,
            )
            for entry in ActionListBuilder().get_available_actions(context):
                if (
                    self._instant_skill_is_free(entry)
                    and entry.action_id not in seen
                ):
                    entries.append(entry)
                    seen.add(entry.action_id)
        return entries

    def request_simple_guard_instant_actions(
        self,
        character,
        decision_provider,
    ):
        """Allow attribute plus and free immediate skills before forced block."""
        while True:
            skills = self.get_simple_guard_instant_skills(character)
            options = [DecisionOption(
                "完成即时操作",
                None,
                ("confirm", "完成"),
            )]
            if self.has_usable_battle_plus(character):
                options.append(DecisionOption(
                    "使用加符",
                    "use_plus",
                    ("加符", "use_plus"),
                ))
            options.extend(
                DecisionOption(entry.name, entry, (entry.action_id,))
                for entry in skills
            )
            if len(options) == 1:
                return
            request = DecisionRequest(
                character=character,
                phase="简易战斗轮—援护即时操作",
                prompt="援护格挡前可以使用加符或即时技能。",
                options=tuple(options),
            )
            choice = (
                decision_provider.choose_optional(request, default=None)
                if hasattr(decision_provider, "choose_optional")
                else decision_provider.choose(request)
            )
            if choice is None:
                return
            if choice == "use_plus":
                self.request_battle_plus_actions(
                    character,
                    "简易战斗轮援护",
                    decision_provider,
                    allow_out_of_battle=True,
                )
                continue
            entry = choice
            target = character
            if entry.definition.get("target") not in {"self", "none"}:
                target = self.request_attack_target(
                    character,
                    entry.valid_targets,
                    decision_provider,
                )
                if target is None:
                    continue
            action = SkillAction(
                character,
                entry.skill,
                entry.skill_component,
                target=target,
            )
            action.game_turn = self.global_turn
            if not ActionResolver().resolve(action, decision_provider):
                raise RuntimeError(
                    f"{character.name}的即时技能{entry.name}未能执行"
                )

    def resolve_simple_round_guard(
        self,
        state,
        target,
        attacks,
        decision_provider,
    ):
        attacks = list(attacks)
        for attack in attacks:
            if attack.value > 0:
                continue
            attack.resolved = True
            attack.hit = False
            attack.final_damage = 0
            attack.consume_resolution_modifiers()
            if attack in target.pending_attacks:
                target.pending_attacks.remove(attack)
        if not any(attack in target.pending_attacks for attack in attacks):
            return []
        selected = self.request_simple_round_guards(
            state,
            target,
            decision_provider,
        )
        records = []
        for guarder in selected:
            # 前一名援护者已将攻击完全结算时，后续选择不视为执行援护。
            pending = [
                attack
                for attack in attacks
                if attack in target.pending_attacks
                and not attack.resolved
                and attack.value > 0
            ]
            if not pending:
                break
            self.current_character = guarder
            self.request_simple_guard_instant_actions(
                guarder,
                decision_provider,
            )
            guarder_records = []
            for attack in pending:
                if (
                    not guarder.is_alive()
                    or guarder.has_status("brink_of_death")
                ):
                    break
                record = self.resolve_guard_attack(
                    guarder,
                    target,
                    attack,
                    decision_provider,
                    allow_external=True,
                    guard_kind="simple_round",
                )
                if record is None:
                    break
                guarder_records.append(record)
                detail = record["results"][0]
                if (
                    detail["entered_brink_of_death"]
                    or detail["guarder_defeated"]
                ):
                    break
            if guarder_records:
                # 只有真正开始援护才消耗本简易战斗轮的援护机会。
                state["used_guarders"].add(guarder)
                summary = {
                    "round": self.global_turn,
                    "guarder": guarder,
                    "target": target,
                    "guard_kind": "simple_round",
                    "results": [
                        detail
                        for record in guarder_records
                        for detail in record["results"]
                    ],
                }
                del self.guard_history[-len(guarder_records):]
                self.guard_history.append(summary)
                records.append(summary)
        return records

    def get_guardable_attacks(self, target):
        return [
            attack
            for attack in target.pending_attacks
            if self.is_attack_guardable(attack)
        ]

    def request_guard_targets(self, character, decision_provider):
        maximum = max(0, int(getattr(character, "guard_target_limit", 1)))
        remaining = self.get_guard_targets(character)
        if maximum <= 0 or not remaining:
            return []

        selected = []
        while remaining and len(selected) < maximum:
            finish_label = "不进行援护" if not selected else "完成选择"
            finish_aliases = (
                ("skip", "不援护", "跳过")
                if not selected
                else ("confirm", "完成")
            )
            options = tuple(
                DecisionOption(target.name, target, (str(target.name),))
                for target in remaining
            ) + (
                DecisionOption(finish_label, None, finish_aliases),
            )
            chosen = decision_provider.choose(DecisionRequest(
                character=character,
                phase="援护目标选择",
                prompt=f"最多可选择{maximum}名援护目标。",
                options=options,
            ))
            if chosen is None:
                break
            selected.append(chosen)
            remaining.remove(chosen)
        return selected

    @staticmethod
    def _prepare_guard_residual(attack, residual_damage):
        """Keep only damage not absorbed before the guard fell into brink/death."""
        attack.value = residual_damage
        # 攻击方修正已经参与过首次伤害结算，剩余伤害不能重复应用。
        attack.percentage_modifiers = []
        attack.flat_modifiers = []
        attack.resolved = False
        attack.hit = None
        attack.final_damage = 0
        attack.defense_roll_started = False
        attack.resolution_reason = None
        attack.source_tags.add("guard_residual")

    def resolve_guard_attack(
        self,
        guarder,
        original_target,
        attack,
        decision_provider,
        *,
        allow_external=False,
        guard_kind="battle",
    ):
        """Resolve one queued attack with forced block and preserve residual."""
        if (
            guarder is original_target
            or (not allow_external and guarder not in self.participants)
            or original_target not in self.participants
            or not guarder.is_alive()
            or not original_target.is_alive()
            or guarder.has_status("brink_of_death")
            or attack not in original_target.pending_attacks
            or not self.is_attack_guardable(attack)
        ):
            return None

        print(f"{guarder.name}开始援护{original_target.name}。")
        from game.game.rule_report import report
        report(guarder, "guard_started", actor=guarder, targets=[original_target],
               involved={"guard_kind": guard_kind})
        hp_before = guarder.hp
        was_in_brink = guarder.has_status("brink_of_death")
        # 援护只能使用格挡；此限制高于random_defense等防御选择效果。
        defense_type = "block"
        result = DefenseResolver().resolve_phase(
            guarder,
            defense_type,
            attacks=[attack],
            decision_provider=decision_provider,
        )
        entered_brink = (
            not was_in_brink
            and guarder.has_status("brink_of_death")
        )
        guarder_fell = entered_brink or not guarder.is_alive()
        residual_damage = 0
        if guarder_fell:
            hp_absorbed = max(0, hp_before - max(guarder.hp, 0))
            residual_damage = max(
                0,
                result["total_damage"] - hp_absorbed,
            )

        if residual_damage > 0:
            self._prepare_guard_residual(attack, residual_damage)
        elif attack in original_target.pending_attacks:
            original_target.pending_attacks.remove(attack)

        detail = {
            "attack": attack,
            "defense": defense_type,
            "damage_to_guarder": result["total_damage"],
            "residual_damage": residual_damage,
            "entered_brink_of_death": entered_brink,
            "guarder_defeated": not guarder.is_alive(),
        }
        record = {
            "round": self.global_turn,
            "guarder": guarder,
            "target": original_target,
            "guard_kind": guard_kind,
            "results": [detail],
        }
        self.guard_history.append(record)
        return record

    def resolve_guard(self, guarder, original_target, decision_provider):
        """Resolve the target's queue in order until exhausted or guarder falls."""
        if (
            guarder is original_target
            or guarder not in self.participants
            or original_target not in self.participants
            or not guarder.is_alive()
            or not original_target.is_alive()
            or guarder.has_status("brink_of_death")
        ):
            return None

        records = []
        while original_target.pending_attacks and guarder.is_alive():
            attack = original_target.pending_attacks[0]
            if not self.is_attack_guardable(attack):
                break
            record = self.resolve_guard_attack(
                guarder,
                original_target,
                attack,
                decision_provider,
            )
            if record is None:
                break
            records.append(record)
            detail = record["results"][0]
            if (
                detail["entered_brink_of_death"]
                or detail["guarder_defeated"]
            ):
                break
        if not records:
            return None
        # 保持既有公开返回结构：一次常规援护对应一个汇总记录。
        summary = {
            "round": self.global_turn,
            "guarder": guarder,
            "target": original_target,
            "guard_kind": "battle",
            "results": [
                detail
                for record in records
                for detail in record["results"]
            ],
        }
        # 单次记录已写入历史，替换成一个常规援护汇总，避免重复触发语义。
        del self.guard_history[-len(records):]
        self.guard_history.append(summary)
        return summary

    def request_defense(
        self,
        character,
        decision_provider,
        attacks=None,
        *,
        phase="defense_phase",
    ):
        incoming = list(attacks or character.pending_attacks)
        self.request_phase_instant_actions(
            character,
            phase,
            decision_provider,
        )
        context = ActionContext(
            actor=character,
            phase=phase,
            turn_number=self.global_turn,
            battle=self,
            characters=list(self.participants),
            incoming_attacks=incoming,
        )
        entries = [
            entry
            for entry in ActionListBuilder().get_available_actions(context)
            if entry.skill is None
        ]
        offset_options = (
            get_offset_attack_options(character, incoming[0])
            if incoming
            else []
        )
        if not offset_options:
            entries = [
                entry for entry in entries if entry.action_id != "offset"
            ]
        request = DecisionRequest(
            character=character,
            phase="防御",
            prompt="请选择本阶段使用的防御方式。",
            allow_refresh=True,
            options=tuple(
                DecisionOption(
                    entry.name,
                    entry.action_id,
                    (entry.action_id,),
                )
                for entry in entries
            ),
        )
        try:
            selected = decision_provider.choose(request)
            if selected == "offset":
                attempt = self.request_offset_attempt(
                    character,
                    incoming[0],
                    decision_provider,
                    options=offset_options,
                )
                if attempt is None:
                    return self.request_defense(
                        character,
                        decision_provider,
                        attacks=incoming,
                        phase=phase,
                    )
                return attempt
        except DecisionRefreshRequested:
            if character not in self.participants or not character.pending_attacks:
                return None
            return self.request_defense(
                character,
                decision_provider,
                phase=phase,
            )
        if character.has_status("random_defense") and selected in {
            "dodge", "block"
        }:
            actual = random.choice(("dodge", "block"))
            label = "闪避" if actual == "dodge" else "格挡"
            print(f"{character.name}的实际防御方式随机为{label}。")
            return actual
        return selected

    def request_offset_attempt(
        self,
        character,
        incoming_attack,
        decision_provider,
        *,
        options=None,
    ):
        """Select and pay one targetless attack, then roll offset once."""
        while True:
            options = list(
                options
                if options is not None
                else get_offset_attack_options(character, incoming_attack)
            )
            if not options:
                return None
            selected = decision_provider.choose(DecisionRequest(
                character=character,
                phase="抵消攻击选择",
                prompt="请选择用于抵消的攻击。",
                options=tuple(
                    DecisionOption(
                        option.name,
                        option,
                        (option.option_id,),
                    )
                    for option in options
                ) + (
                    DecisionOption(
                        "返回防御选择",
                        None,
                        ("back", "返回"),
                    ),
                ),
            ))
            if selected is None:
                return None
            try:
                resolved = resolve_offset_attack_option(
                    character,
                    selected,
                    decision_provider,
                    turn_number=self.global_turn,
                )
            except SkillUnavailableError:
                options = None
                continue

            roll_result = RollResolver().roll(
                character,
                "offset",
                decision_provider=decision_provider,
                phase="抵消—幸运",
            )
            success = roll_result.total >= incoming_attack.attack_roll
            total_power = sum(
                profile.offset_power
                for profile in resolved["profiles"]
            )
            reduction = (
                total_power
                if success
                else min(total_power, incoming_attack.value * 0.5)
            )
            return OffsetAttempt(
                defender=character,
                incoming_attack=incoming_attack,
                attack_profiles=resolved["profiles"],
                roll_result=roll_result,
                success=success,
                reduction=int(reduction),
            )

    def request_attack_action(
        self,
        character,
        targets,
        decision_provider,
        *,
        virtual_attack_phase=False,
        characters=None,
        remote_only=False,
    ):
        context_characters = list(characters or self.participants)
        if remote_only:
            context_characters = [
                candidate
                for candidate in context_characters
                if candidate is character
                or candidate.position is not character.position
            ]
        context = ActionContext(
            actor=character,
            phase="attack_phase",
            turn_number=self.global_turn,
            battle=self,
            characters=context_characters,
            game_manager=getattr(character, "game_manager", None),
            virtual_attack_phase=virtual_attack_phase,
        )
        entries = ActionListBuilder().get_available_actions(context)
        if virtual_attack_phase:
            # 撤退依赖真实战斗状态，不属于战斗外的虚拟攻击阶段。
            entries = [
                entry for entry in entries
                if entry.action_id not in {"escape", "battle_perceive"}
            ]
        options = [
            DecisionOption(
                entry.name,
                entry if entry.skill is not None else entry.action_id,
                (
                    entry.action_id,
                    *(('结束',) if entry.action_id == "stay" else ()),
                ),
            )
            for entry in entries
        ]
        if self.has_usable_battle_plus(character):
            options.append(DecisionOption(
                "使用加符",
                "use_plus",
                ("加符", "use_plus"),
            ))
        request = DecisionRequest(
            character=character,
            phase="攻击",
            prompt="请选择行动。",
            allow_refresh=True,
            options=tuple(options),
        )
        try:
            return decision_provider.choose(request)
        except DecisionRefreshRequested:
            if (
                not virtual_attack_phase
                and character not in self.participants
            ):
                return "command_spell_teleported"
            return self.request_attack_action(
                character,
                self.get_attack_targets(character),
                decision_provider,
                virtual_attack_phase=virtual_attack_phase,
                characters=characters,
                remote_only=remote_only,
            )

    @staticmethod
    def _pending_attack_snapshot(characters):
        return {
            id(attack)
            for character in characters
            for attack in character.pending_attacks
        }

    @staticmethod
    def _new_attack_events(characters, previous, actor):
        return [
            attack
            for character in characters
            for attack in list(character.pending_attacks)
            if id(attack) not in previous and attack.source is actor
        ]

    def run_virtual_attack_phase(
        self,
        actor,
        decision_provider,
        *,
        characters,
        preferred_target=None,
        preserve_attack_phase_count=False,
        simple_round_effect=None,
        remote_only=False,
        reveal_direct_attack_source=False,
    ):
        """Run one attack phase without placing the actor into battle."""
        saved_character = self.current_character
        saved_phase = self.current_phase
        self.current_character = actor
        self.current_phase = "simple_round_attack"
        self.global_turn = getattr(actor, "current_global_turn", 0)
        saved_attack_phase_count = actor.attack_phase_count
        actor.attack_phase_count = 1
        action_results = []
        defense_results = []

        try:
            while actor.is_alive() and actor.attack_phase_count > 0:
                targets = [
                    target
                    for target in characters
                    if target is not actor
                    and target.is_alive()
                    and not actor.is_ally(target)
                    and target in actor.own_visible
                    and (
                        not remote_only
                        or target.position is not actor.position
                    )
                ]
                command = self.request_attack_action(
                    actor,
                    targets,
                    decision_provider,
                    virtual_attack_phase=True,
                    characters=characters,
                    remote_only=remote_only,
                )
                if command == "use_plus":
                    self.request_battle_plus_actions(
                        actor,
                        "虚拟攻击阶段",
                        decision_provider,
                        allow_out_of_battle=True,
                    )
                    continue

                before = self._pending_attack_snapshot(characters)
                if getattr(command, "skill", None) is not None:
                    entry = command
                    if entry.definition["target"] in {"self", "none"}:
                        target = actor
                    else:
                        target = self.request_attack_target(
                            actor,
                            entry.valid_targets,
                            decision_provider,
                        )
                        if target is None:
                            continue
                        if remote_only and target.position is actor.position:
                            continue
                    action = SkillAction(
                        actor,
                        entry.skill,
                        entry.skill_component,
                        target=target,
                    )
                elif command == "stay":
                    # 战斗外仅结束这次虚拟阶段，不添加stay状态。
                    if actor.casting_state is not None:
                        actor.interrupt_casting(
                            reason="other_action:virtual_stay"
                        )
                    actor.attack_phase_count = 0
                    action_results.append({"action_id": "stay"})
                    continue
                elif command == "interrupt_casting":
                    action = Action(actor, "interrupt_casting")
                elif command == "chant":
                    action = Action(actor, "chant")
                elif command == "release":
                    action = Action(actor, "release")
                elif command == "attack":
                    target = (
                        preferred_target
                        if preferred_target in targets
                        else self.request_attack_target(
                            actor,
                            targets,
                            decision_provider,
                        )
                    )
                    preferred_target = None
                    if target is None:
                        continue
                    if remote_only and target.position is actor.position:
                        continue
                    action = Action(actor, "attack", target)
                elif command == "mend":
                    amount = self.request_mend_amount(
                        actor,
                        decision_provider,
                    )
                    action = Action(actor, "mend", amount=amount)
                else:
                    raise RuntimeError(f"虚拟攻击阶段不支持行动：{command}")

                action.game_turn = self.global_turn
                action.virtual_attack_phase = True
                result = ActionResolver().resolve(action, decision_provider)
                if not result:
                    continue
                action_results.append(result)

                new_attacks = self._new_attack_events(
                    characters,
                    before,
                    actor,
                )
                if new_attacks:
                    if reveal_direct_attack_source:
                        information_manager = getattr(
                            getattr(actor, "game_manager", None),
                            "information_manager",
                            None,
                        )
                        recipients = list(dict.fromkeys(
                            attack.target for attack in new_attacks
                        ))
                        for recipient in recipients:
                            source_position = actor.position
                            if information_manager is not None:
                                information_manager.record_direct_attack_source(
                                    actor,
                                    recipient,
                                    source_position,
                                )
                            notify = getattr(decision_provider, "notify", None)
                            if callable(notify):
                                location_name = getattr(
                                    source_position,
                                    "name",
                                    str(source_position),
                                )
                                notify(
                                    f"你受到来自{location_name}的超距打击。",
                                    recipient=recipient,
                                )
                    defense_results.append(
                        self.resolve_simple_round_attack_events(
                            new_attacks,
                            decision_provider,
                            effect=simple_round_effect,
                        )
                    )
                    self.current_character = actor
                    self.current_phase = "simple_round_attack"

            return {
                "action_results": action_results,
                "defense_results": defense_results,
                "ended_without_refund": True,
            }
        finally:
            if preserve_attack_phase_count:
                actor.attack_phase_count = saved_attack_phase_count
            self.current_character = saved_character
            self.current_phase = saved_phase

    @staticmethod
    def has_usable_battle_plus(character):
        return any(
            getattr(character, name).plus > 0
            for name in ("strength", "endurance", "flexibility", "magic")
        )

    def request_battle_plus_actions(
        self,
        character,
        phase,
        decision_provider,
        *,
        allow_out_of_battle=False,
    ):
        """Offer repeatable, phase-free attribute-plus use before stats are read."""
        labels = {
            "strength": "筋力加符",
            "endurance": "耐久加符",
            "flexibility": "敏捷加符",
            "magic": "魔力加符",
        }
        while True:
            available = [
                name for name in labels
                if getattr(character, name).plus > 0
            ]
            if not available:
                return
            options = [DecisionOption("结束加符使用", "confirm", ("确认",))]
            for name in available:
                attribute = getattr(character, name)
                used = character._active_attribute_plus_uses[name]
                options.append(DecisionOption(
                    f"{labels[name]}（本回合已使用{used}，剩余{attribute.plus}）",
                    name,
                    (name,),
                ))
            request = DecisionRequest(
                character=character,
                phase=f"{phase}—加符",
                prompt="加符不占用攻击阶段；可以连续使用。",
                options=tuple(options),
            )
            if hasattr(decision_provider, "choose_optional"):
                choice = decision_provider.choose_optional(request)
            else:
                choice = decision_provider.choose(request)
            if choice == "confirm":
                return
            character.use_attribute_plus(
                choice,
                allow_out_of_battle=allow_out_of_battle,
            )

    def request_mend_amount(self, character, decision_provider):
        maximum = int(min(
            character.hpmax - character.hp,
            character.get_available_mp(),
        ))
        request = NumericDecisionRequest(
            character=character,
            phase="修补",
            prompt="请输入要消耗并回复的MP/HP数量。",
            minimum=1,
            maximum=maximum,
        )
        return decision_provider.choose(request)

    def request_attack_target(self, character, targets, decision_provider):
        request = DecisionRequest(
            character=character,
            phase="攻击目标选择",
            prompt="可以输入编号，也可以直接输入角色名。",
            allow_refresh=True,
            options=tuple(
                DecisionOption(target.name, target, (str(target.name),))
                for target in targets
            ) + (
                DecisionOption(
                    "返回行动选择",
                    None,
                    ("back", "返回"),
                ),
            ),
        )
        try:
            return decision_provider.choose(request)
        except DecisionRefreshRequested:
            refreshed = [
                target
                for target in targets
                if target.is_alive()
                and target in character.own_visible
                and not character.is_ally(target)
            ]
            if not refreshed:
                return None
            return self.request_attack_target(
                character,
                refreshed,
                decision_provider,
            )

    def run_battle_turn(self, decision_provider):
        """Advance automatically until this battle round ends.

        Only choices that require a player are delegated to decision_provider.
        This keeps the rules usable by a terminal today and an EXE/UI later.
        """
        if self.ended:
            return False
        if self.current_character is None and self.current_phase != "battle_start":
            if not self.start_battle_turn():
                return False

        if self.current_phase == "battle_start":
            self.run_simple_rounds_before(
                None,
                "battle_start",
                decision_provider,
            )
            if self.ended or not self.current_order:
                return False
            self.current_index = 0
            self.current_character = self.current_order[0]
            self.start_character_turn(self.current_character)

        while not self.ended and self.current_character is not None:
            character = self.current_character
            if character not in self.participants or not character.is_alive():
                self.continue_after_current_removed()
                continue
            self.run_simple_rounds_before(
                character,
                self.current_phase,
                decision_provider,
            )
            if character not in self.participants or not character.is_alive():
                self.continue_after_current_removed()
                continue

            if self.current_phase == "turn_start":
                self.request_battle_plus_actions(
                    character,
                    "防御",
                    decision_provider,
                )
                self.advance_formal_phase("guard")
                continue

            if self.current_phase == "guard":
                self.request_phase_instant_actions(
                    character,
                    "guard_phase",
                    decision_provider,
                )
                if (
                    character not in self.guarded_this_round
                    and character.guard_opportunity_available
                ):
                    self.guarded_this_round.add(character)
                    character.guard_opportunity_available = False
                    for target in self.request_guard_targets(
                        character,
                        decision_provider,
                    ):
                        if self.ended or not character.is_alive():
                            break
                        self.resolve_guard(
                            character,
                            target,
                            decision_provider,
                        )
                self.advance_formal_phase("defense")
                continue

            if self.current_phase == "defense":
                if character.pending_attacks:
                    attack_count = 0
                    hit_count = 0
                    total_damage = 0
                    while character.pending_attacks and character.is_alive():
                        attack = character.pending_attacks[0]
                        defense_type = self.request_defense(
                            character,
                            decision_provider,
                        )
                        if character not in self.participants:
                            self.continue_after_current_removed()
                            break
                        if defense_type is None:
                            break
                        result = self.defense_phase(
                            character,
                            defense_type,
                            attacks=[attack],
                            decision_provider=decision_provider,
                        )
                        attack_count += result["attack_count"]
                        hit_count += result["hit_count"]
                        total_damage += result["total_damage"]
                    character.last_defense_attack_count = attack_count
                    character.last_defense_hit_count = hit_count
                    character.last_defense_total_damage = total_damage
                else:
                    print(f"{character.name}无攻击，跳过防御阶段")
                self.advance_formal_phase("attack")
                continue

            if self.current_phase == "attack":
                targets = self.get_attack_targets(character)
                if character.attack_phase_count <= 0:
                    self.advance_formal_phase("turn_end")
                    continue

                command = self.request_attack_action(
                    character,
                    targets,
                    decision_provider,
                )
                if command == "command_spell_teleported":
                    self.continue_after_current_removed()
                    continue
                if command == "use_plus":
                    self.request_battle_plus_actions(
                        character,
                        "攻击",
                        decision_provider,
                    )
                    continue
                if getattr(command, "skill", None) is not None:
                    entry = command
                    if entry.definition["target"] == "self":
                        target = character
                    else:
                        target = self.request_attack_target(
                            character,
                            entry.valid_targets,
                            decision_provider,
                        )
                        if target is None:
                            continue
                    action = SkillAction(
                        character,
                        entry.skill,
                        entry.skill_component,
                        target=target,
                    )
                    action.game_turn = self.global_turn
                    if not ActionResolver().resolve(action, decision_provider):
                        raise RuntimeError(
                            f"{character.name}的技能{entry.name}未能执行"
                        )
                    continue
                if command == "stay":
                    action = Action(character, "stay")
                    action.game_turn = self.global_turn
                    if not ActionResolver().resolve(action, decision_provider):
                        raise RuntimeError(f"{character.name}的待机未能执行")
                    self.advance_formal_phase("turn_end")
                    continue

                if command == "interrupt_casting":
                    action = Action(character, "interrupt_casting")
                    action.game_turn = self.global_turn
                    if not ActionResolver().resolve(action):
                        raise RuntimeError(
                            f"{character.name}的中断咏唱未能执行"
                        )
                    continue

                if command == "chant":
                    action = Action(character, "chant")
                    action.game_turn = self.global_turn
                    if not ActionResolver().resolve(
                        action,
                        decision_provider,
                    ):
                        raise RuntimeError(f"{character.name}的咏唱未能执行")
                    continue

                if command == "release":
                    action = Action(character, "release")
                    action.game_turn = self.global_turn
                    if not ActionResolver().resolve(
                        action,
                        decision_provider,
                    ):
                        continue
                    continue

                if command == "attack":
                    target = self.request_attack_target(
                        character,
                        targets,
                        decision_provider,
                    )
                    if target is None:
                        continue
                    action = Action(character, "attack", target)
                    action.game_turn = self.global_turn
                    if not ActionResolver().resolve(action, decision_provider):
                        raise RuntimeError(f"{character.name}的攻击未能执行")
                    continue

                if command == "battle_perceive":
                    action = Action(
                        character,
                        "battle_perceive",
                        characters=getattr(
                            getattr(character, "game_manager", None),
                            "characters",
                            self.participants,
                        ),
                    )
                    action.game_turn = self.global_turn
                    if not ActionResolver().resolve(action, decision_provider):
                        raise RuntimeError(f"{character.name}的感知未能执行")
                    continue

                if command == "mend":
                    amount = self.request_mend_amount(
                        character,
                        decision_provider,
                    )
                    action = Action(
                        character,
                        "mend",
                        amount=amount,
                    )
                    action.game_turn = self.global_turn
                    if not ActionResolver().resolve(action):
                        raise RuntimeError(f"{character.name}的修补未能执行")
                    continue

                if command == "escape":
                    action = Action(character, "escape")
                    action.game_turn = self.global_turn
                    if not ActionResolver().resolve(action):
                        raise RuntimeError(f"{character.name}的撤退未能执行")
                    if character not in self.participants:
                        self.continue_after_current_removed()
                    continue

                raise ValueError(f"未实现的攻击阶段指令：{command}")

            if self.current_phase == "turn_end":
                self.finish_current_character()
                continue

            if self.current_phase == "round_ended":
                break

            raise RuntimeError(f"未知的战斗阶段：{self.current_phase}")

        return self.current_phase == "round_ended"

    def continue_after_current_removed(self):
        removed_character = self.current_character
        if removed_character is not None:
            removed_character.update_modifiers(
                "battle_turn_end",
                turn_number=self.global_turn,
            )
        if self.ended:
            self.current_character = None
            return False
        if self.current_index >= len(self.current_order):
            self.current_character = None
            self.current_phase = "round_ended"
            self.finish_battle_round()
            print("本回合的战斗行动结束")
            return False

        self.current_character = self.current_order[self.current_index]
        self.start_character_turn(self.current_character)
        return True

    def next_phase(self):
        if self.current_character is None: return False
        if self.current_phase == "turn_start":
            self.advance_formal_phase("guard")
            return "guard"

        if self.current_phase == "guard":
            self.advance_formal_phase("defense")
            return "defense"

        if self.current_phase == "defense":
            self.advance_formal_phase("attack")
            return "attack"

        if self.current_phase == "attack":
            self.advance_formal_phase("turn_end")
            return "turn_end"

        if self.current_phase == "turn_end":
            return self.finish_current_character()
        return False
    #按顺序推进一个角色的战斗轮

    def finish_formal_phase(self, phase=None, character=None):
        """Close one outer battle phase and advance matching Modifier windows.

        Simple-round phases never call this method, so an inserted simple
        round cannot consume the enclosing formal battle phase window.
        """
        phase = self.current_phase if phase is None else phase
        character = self.current_character if character is None else character
        if phase not in self.FORMAL_PHASES or character is None:
            return []
        removed = []
        for participant in self.participants[:]:
            removed.extend(
                participant.update_phase_window_modifiers(
                    scope="formal_battle",
                    phase=phase,
                    boundary="phase_end",
                    phase_actor=character,
                )
            )
        return removed

    def advance_formal_phase(self, next_phase):
        if next_phase not in self.FORMAL_PHASES:
            raise ValueError(f"未知的正式战斗阶段：{next_phase}")
        self.finish_formal_phase()
        self.current_phase = next_phase
        for participant in self.participants:
            participant.update_visibility(self.participants)
        return next_phase

    def finish_current_character(self):
        character = self.current_character
        self.end_character_turn(character)

        self.current_index += 1
        if self.current_index >= len(self.current_order):
            self.current_character = None
            self.current_phase = "round_ended"
            self.finish_battle_round()
            print("本回合的战斗行动结束")

            return False

        self.current_character = (self.current_order[self.current_index])
        self.start_character_turn(self.current_character)
        return True
#结束一个角色回合/如果没有下一个角色，就结束本轮

    def mark_stayed(self, character):
        if character in self.participants:
            self.stayed_this_round.add(character)

    def finish_battle_round(self):
        remaining = {
            character
            for character in self.round_participants
            if character in self.participants and character.is_alive()
        }
        self.all_stayed_last_round = bool(remaining) and remaining.issubset(
            self.stayed_this_round
        )
        manager = getattr(self, "game_manager", None)
        if manager is None and self.participants:
            manager = getattr(self.participants[0], "game_manager", None)
        event_manager = getattr(manager, "event_manager", None)
        if event_manager is not None:
            event_manager.emit(
                "battle_round_end",
                source=self,
                targets=list(self.round_participants),
                battle=self,
                phase="round_ended",
                value=getattr(self, "round_mp_paid_total", 0),
                payload={
                    "mp_paid_total": getattr(self, "round_mp_paid_total", 0),
                    "mp_payments": list(getattr(self, "round_mp_payments", [])),
                    "is_ambush": False,
                    "is_simple_round": False,
                },
            )
        self.round_mp_paid_total = 0
        self.round_mp_payments = []
        return self.all_stayed_last_round

    def record_mp_payment(self, payer, amount, pool="mp"):
        amount = int(amount)
        if amount <= 0:
            return 0
        if not hasattr(self, "round_mp_payments"):
            self.round_mp_payments = []
            self.round_mp_paid_total = 0
        self.round_mp_payments.append({
            "payer": payer,
            "amount": amount,
            "pool": pool,
        })
        self.round_mp_paid_total += amount
        return amount

    def disband_if_all_stayed(self):
        if self.ended or not self.all_stayed_last_round:
            return []
        released = [
            character
            for character in self.participants
            if character.is_alive()
        ]
        self.end_battle(reason="all_stayed")
        return released

    def start_character_turn(self, character):
        self.current_character = character
        self.current_phase = "turn_start"
        print(
            f"{character.name}的回合"
        )
        manager = getattr(character, "game_manager", None)
        event_manager = getattr(manager, "event_manager", None)
        if event_manager is not None:
            event_manager.emit(
                "personal_turn_start",
                actor=character,
                source=self,
                target=character,
                phase="turn_start",
                battle=self,
                position=character.position,
            )
    #角色回合开始

    def defense_phase(
        self,
        character,
        defense_type=None,
        attacks=None,
        decision_provider=None,
    ):
        self.current_phase = "defense"
        if attacks is None:
            attacks = character.pending_attacks.copy()
        if not attacks:
            print(f"{character.name}无攻击，跳过防御阶段")
            return None

        print(f"{character.name}的防御阶段")
        result = DefenseResolver().resolve_phase(
            character,
            defense_type,
            attacks=attacks,
            decision_provider=decision_provider,
        )
        return result
    #防御阶段

    def attack_phase(self, character):
        self.current_phase = "attack"
        if character.attack_phase_count <= 0:
            print(f"结束{character.name}的攻击阶段")
            return False
        
        print(f"{character.name}的攻击阶段")
        return True
    #攻击阶段
    def end_character_turn(self, character):
        self.current_phase = "turn_end"
        manager = getattr(character, "game_manager", None)
        event_manager = getattr(manager, "event_manager", None)
        if event_manager is not None:
            event_manager.emit(
                "personal_turn_end",
                actor=character,
                source=self,
                target=character,
                phase="turn_end",
                battle=self,
                position=character.position,
            )
        self.finish_formal_phase("turn_end", character)
        character.update_modifiers(
            "battle_turn_end",
            turn_number=self.global_turn,
        )
        if character.temporary_mp_waits_for_personal_turn_end:
            character.clear_temporary_mp()
        print(f"{character.name}的回合结束")
        self.current_character = None
    #回合结束阶段

    

    
            
