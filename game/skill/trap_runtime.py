"""Persistent trap entities and their movement-triggered attack runtime."""

from dataclasses import dataclass
from itertools import count
import random

from game.turn.damage import AttackProfile, DamageEvent, DamageResolver


_TRAP_SEQUENCE = count(1)


@dataclass(eq=False)
class Trap:
    trap_id: str
    owner: object
    position: object
    magic_attack_bonus: int
    base_damage: int = 30
    share_knowledge: bool = True
    critical_success_eligible: bool = False
    critical_failure_eligible: bool = True
    skill: object = None
    active: bool = True
    information: object = None


class TrapManager:
    """Own every active trap in stable placement order."""

    def __init__(self, game_manager):
        self.game_manager = game_manager
        self.traps = []
        self.history = []

    @staticmethod
    def _snapshot_magic_attack(owner, skill=None):
        context = {
            "actor": owner,
            "source": skill,
            "target": None,
            "action_id": "trap",
            "skill_id": getattr(skill, "skill_id", None),
            "damage_type": "magic",
            "tags": {"trap", "skill", "magic"},
        }
        bonus = owner.get_effective_derived_stat("magic_attack", context)
        bonus += owner.dice_bonus
        bonus += owner.modifier_manager.get_contextual_bonus(
            "dice_bonus",
            effect_target="magic_attack",
            context=context,
            actor=owner,
        )
        bonus += owner.modifier_manager.get_contextual_bonus(
            "dice_bonus",
            effect_target="dice_bonus",
            context=context,
            actor=owner,
        )
        return int(bonus)

    def register(
        self,
        owner,
        position,
        *,
        base_damage=30,
        share_knowledge=True,
        skill=None,
        trap_id=None,
    ):
        if owner not in self.game_manager.characters or not owner.is_alive():
            raise ValueError("只有本局存活角色可以设置陷阱")
        if position is None or owner.position is not position:
            raise ValueError("陷阱只能设置在角色当前节点")
        if isinstance(base_damage, bool) or not isinstance(base_damage, int):
            raise TypeError("陷阱伤害必须是整数")
        if base_damage < 0:
            raise ValueError("陷阱伤害不能小于0")

        instance_id = trap_id or f"trap:{next(_TRAP_SEQUENCE)}"
        if any(trap.trap_id == instance_id for trap in self.traps):
            raise ValueError(f"陷阱ID已存在：{instance_id}")
        fortune = owner.get_effective_attribute_value("fortune")
        trap = Trap(
            trap_id=instance_id,
            owner=owner,
            position=position,
            magic_attack_bonus=self._snapshot_magic_attack(owner, skill),
            base_damage=base_damage,
            share_knowledge=bool(share_knowledge),
            critical_success_eligible=fortune >= 2,
            critical_failure_eligible=bool(owner.can_critical_failure),
            skill=skill,
        )
        trap.information = self.game_manager.information_manager.register_trap_information(
            trap.trap_id,
            owner,
            position,
            share_with_links=trap.share_knowledge,
        )
        self.traps.append(trap)
        return trap

    def deactivate(self, trap, reason="resolved"):
        if trap not in self.traps or not trap.active:
            return False
        trap.active = False
        if trap.information is not None:
            self.game_manager.information_manager.deactivate_trap(
                trap.information,
            )
        self.history.append({"trap": trap, "reason": reason})
        return True

    def remove_owner_traps(self, owner, reason="owner_exit"):
        removed = []
        for trap in self.traps:
            if trap.active and trap.owner is owner:
                self.deactivate(trap, reason=reason)
                removed.append(trap)
        return removed

    def active_at(self, position):
        return [
            trap
            for trap in self.traps
            if trap.active and trap.position is position
        ]

    def _eligible_targets(self, trap, entrants):
        return [
            character
            for character in dict.fromkeys(entrants)
            if character in self.game_manager.characters
            and character.is_alive()
            and character.position is trap.position
            and not self.game_manager.information_manager.knows_trap(
                character,
                trap.information,
            )
        ]

    @staticmethod
    def _attack_roll(trap):
        die = random.randint(1, 10)
        critical = 0
        if die == 10 and trap.critical_success_eligible:
            critical = 15
        elif die == 1 and trap.critical_failure_eligible:
            critical = -15
        return die, int(die + trap.magic_attack_bonus + critical)

    def trigger_entry(self, entrants, position, decision_provider=None):
        """Resolve every trap at one node against one entering movement unit."""
        results = []
        for trap in list(self.active_at(position)):
            if not trap.active or not trap.owner.is_alive():
                self.deactivate(trap, reason="owner_exit")
                continue
            targets = self._eligible_targets(trap, entrants)
            if not targets:
                continue
            # A trap is removed at the end of its attack stage regardless of hit.
            # Mark it inactive before nested decisions so it cannot re-trigger.
            self.deactivate(trap, reason="triggered")
            results.append(
                self._resolve_attack(trap, targets, decision_provider)
            )
        return results

    def _resolve_attack(self, trap, targets, decision_provider):
        from game.turn.battle import BattleManager

        die, attack_roll = self._attack_roll(trap)
        profile = AttackProfile(
            source=trap.owner,
            value=trap.base_damage,
            damage_type="magic",
            attack_roll=attack_roll,
            attack_die=die,
            action_id="trap",
            skill_id=getattr(trap.skill, "skill_id", None),
            skill=trap.skill,
            source_tags={"trap", "magic", "simple_round"},
            resolution_channel="release",
        )
        attacks = []
        relationships = self.game_manager.relationship_manager
        for target in targets:
            attack = profile.assign_target(target)
            attack.defer_damage = True
            attack.counts_offset_as_hit = True
            target.pending_attacks.append(attack)
            relationships.resolve_attack_attitude(
                trap.owner,
                target,
                decision_provider,
            )
            attacks.append(attack)

        participants = list(dict.fromkeys([trap.owner, *targets]))
        simple_round = BattleManager(participants, auto_link=False)
        simple_round.global_turn = self.game_manager.turn_manager.turn
        defense_result = simple_round.resolve_simple_round_attack_events(
            attacks,
            decision_provider,
        )

        hit_targets = []
        for attack in attacks:
            if attack.hit and attack.target not in hit_targets:
                hit_targets.append(attack.target)

        shared_damage = (
            int(trap.base_damage / len(hit_targets))
            if hit_targets
            else 0
        )
        damage_results = []
        for target in hit_targets:
            if not target.is_alive():
                continue
            event = DamageEvent(
                source=trap.owner,
                target=target,
                value=shared_damage,
                damage_type="magic",
                skill=trap.skill,
                action_id="trap",
                skill_id=getattr(trap.skill, "skill_id", None),
                source_tags={"trap", "magic", "simple_round"},
            )
            final_damage = DamageResolver().resolve(
                event,
                decision_provider=decision_provider,
            )
            print(
                f"{trap.owner.name}的陷阱对{target.name}造成了"
                f"{final_damage}点HP伤害"
            )
            damage_results.append({
                "target": target,
                "event": event,
                "damage": final_damage,
            })

        return {
            "trap": trap,
            "targets": list(targets),
            "attacks": attacks,
            "defense_result": defense_result,
            "hit_targets": hit_targets,
            "shared_damage": shared_damage,
            "damage_results": damage_results,
        }
