"""Schedule effects and attacks for the next matching resolution checkpoint."""

from dataclasses import dataclass, field
from itertools import count


_DELAY_IDS = count(1)


@dataclass
class DelayedResolution:
    kind: str
    actor: object
    target: object
    skill: object
    created_turn: int
    due_turn: int
    delay_turns: int
    checkpoint: str
    checkpoint_owner: object
    remaining_checkpoints: int
    fallback_rounds_remaining: int
    effects: tuple = ()
    attack: object = None
    context: dict = field(default_factory=dict)
    delay_id: int = field(default_factory=lambda: next(_DELAY_IDS))
    resolved: bool = False
    cancelled: bool = False
    result: object = None
    resolved_checkpoint: str = None
    used_turn_end_fallback: bool = False
    origin_simple_round_token: object = None
    last_fallback_global_turn: int = None


class DelayManager:
    """Keep target snapshots and release them at the same later checkpoint."""

    def __init__(self, game_manager):
        self.game_manager = game_manager
        self.entries = []
        self.history = []

    @staticmethod
    def _validate_delay_turns(delay_turns):
        if (
            not isinstance(delay_turns, int)
            or isinstance(delay_turns, bool)
            or delay_turns < 1
        ):
            raise ValueError("delay_turns必须是正整数")
        return delay_turns

    @property
    def current_turn(self):
        return int(getattr(self.game_manager.turn_manager, "turn", 0))

    @staticmethod
    def normalize_checkpoint(phase):
        """Map UI/action phase labels to stable engine checkpoints."""
        if phase is None:
            return None
        value = str(phase).strip()
        lowered = value.lower()
        if lowered.startswith("ap1"):
            return "AP1"
        if lowered.startswith("ap2"):
            return "AP2"
        aliases = {
            "defense_phase": "defense",
            "attack_phase": "attack",
            "guard_phase": "guard",
            "battle_turn_start": "turn_start",
            "battle_turn_end": "turn_end",
            "simple_round_attack": "attack",
            "simple_round_guard": "guard",
            "simple_round_defense": "defense",
        }
        return aliases.get(lowered, lowered)

    def _checkpoint_from_context(self, actor, target, context):
        context = context or {}
        battle = context.get("battle")
        explicit_raw = context.get("phase")
        explicit_raw = (
            str(explicit_raw).strip().lower()
            if explicit_raw is not None
            else None
        )
        battle_phase_raw = getattr(battle, "current_phase", None)
        battle_phase_raw = (
            str(battle_phase_raw).strip().lower()
            if battle_phase_raw is not None
            else None
        )
        explicit = self.normalize_checkpoint(explicit_raw)
        battle_phase = self.normalize_checkpoint(battle_phase_raw)
        if battle_phase_raw in {
            "turn_start", "guard", "defense", "attack", "turn_end",
            "simple_round_attack", "simple_round_guard",
            "simple_round_defense",
        }:
            original_checkpoint = battle_phase_raw
        else:
            original_checkpoint = (
                explicit_raw
                if explicit_raw in {
                    "simple_round_attack",
                    "simple_round_guard",
                    "simple_round_defense",
                }
                else explicit
            )
        if original_checkpoint is None:
            # Direct/runtime calls without a phase still receive deterministic
            # semantics.  Their corresponding checkpoint is global turn end.
            original_checkpoint = "global_turn_end"

        checkpoint = {
            "simple_round_attack": "attack",
            "simple_round_guard": "guard",
            "simple_round_defense": "defense",
        }.get(original_checkpoint, original_checkpoint)

        owner = actor
        if battle is not None and original_checkpoint in {
            "turn_start", "guard", "defense", "attack", "turn_end",
        }:
            owner = getattr(battle, "current_character", None) or actor
        elif original_checkpoint == "simple_round_defense":
            owner = target
        return checkpoint, owner

    @staticmethod
    def _simple_round_token(context):
        battle = (context or {}).get("battle")
        return getattr(battle, "_active_simple_round_token", None)

    def _emit(
        self,
        event_type,
        entry,
        *,
        result=None,
        decision_provider=None,
        phase=None,
    ):
        target = entry.target
        return self.game_manager.event_manager.emit(
            event_type,
            actor=entry.actor,
            source=entry,
            target=target,
            phase=phase or entry.checkpoint,
            position=getattr(target, "position", None),
            payload={
                "delay_id": entry.delay_id,
                "delay_kind": entry.kind,
                "created_turn": entry.created_turn,
                "due_turn": entry.due_turn,
                "delay_turns": entry.delay_turns,
                "checkpoint": entry.checkpoint,
                "checkpoint_owner": getattr(
                    entry.checkpoint_owner,
                    "name",
                    None,
                ),
                "remaining_checkpoints": entry.remaining_checkpoints,
                "fallback_rounds_remaining": entry.fallback_rounds_remaining,
                "used_turn_end_fallback": entry.used_turn_end_fallback,
                "result": result,
            },
            decision_provider=decision_provider,
        )

    def schedule_effects(
        self,
        *,
        actor,
        target,
        skill,
        effects,
        delay_turns,
        context=None,
        decision_provider=None,
    ):
        delay_turns = self._validate_delay_turns(delay_turns)
        effects = tuple(effects or ())
        if not effects:
            raise ValueError("delay_effect至少需要一个嵌套效果")
        checkpoint, checkpoint_owner = self._checkpoint_from_context(
            actor,
            target,
            context,
        )
        entry = DelayedResolution(
            kind="effect",
            actor=actor,
            target=target,
            skill=skill,
            created_turn=self.current_turn,
            due_turn=self.current_turn + delay_turns,
            delay_turns=delay_turns,
            checkpoint=checkpoint,
            checkpoint_owner=checkpoint_owner,
            remaining_checkpoints=delay_turns,
            fallback_rounds_remaining=delay_turns,
            effects=effects,
            context=dict(context or {}),
            origin_simple_round_token=self._simple_round_token(context),
        )
        self.entries.append(entry)
        self._emit(
            "delayed_effect_scheduled",
            entry,
            decision_provider=decision_provider,
        )
        return entry

    def schedule_attack(
        self,
        attack,
        *,
        actor,
        skill,
        delay_turns,
        context=None,
        decision_provider=None,
    ):
        from game.turn.damage import AttackEvent

        delay_turns = self._validate_delay_turns(delay_turns)
        if not isinstance(attack, AttackEvent):
            raise TypeError("delay_attack的目标必须是尚未结算的AttackEvent")
        if attack.resolved or attack.defense_roll_started:
            raise ValueError("已经结算或开始防御的攻击不能延迟")

        existing = next((
            entry
            for entry in self.entries
            if entry.kind == "attack"
            and entry.attack is attack
            and not entry.resolved
            and not entry.cancelled
        ), None)
        if existing is not None:
            existing.due_turn += delay_turns
            existing.delay_turns += delay_turns
            existing.remaining_checkpoints += delay_turns
            existing.fallback_rounds_remaining += delay_turns
            self._emit(
                "delayed_attack_scheduled",
                existing,
                decision_provider=decision_provider,
            )
            return existing

        target = attack.target
        if target is None:
            raise ValueError("delay_attack的攻击没有目标")
        if attack in getattr(target, "pending_attacks", []):
            target.pending_attacks.remove(attack)
        checkpoint, checkpoint_owner = self._checkpoint_from_context(
            actor,
            target,
            context,
        )
        # An attack always waits for the target's next defense checkpoint.
        # Formal and simple-round defense phases use the same normalized name.
        checkpoint = "defense"
        checkpoint_owner = target
        entry = DelayedResolution(
            kind="attack",
            actor=actor,
            target=target,
            skill=skill,
            created_turn=self.current_turn,
            due_turn=self.current_turn + delay_turns,
            delay_turns=delay_turns,
            checkpoint=checkpoint,
            checkpoint_owner=checkpoint_owner,
            remaining_checkpoints=delay_turns,
            fallback_rounds_remaining=delay_turns,
            attack=attack,
            context=dict(context or {}),
            origin_simple_round_token=self._simple_round_token(context),
        )
        self.entries.append(entry)
        self._emit(
            "delayed_attack_scheduled",
            entry,
            decision_provider=decision_provider,
        )
        return entry

    def _target_available(self, target):
        if target is None:
            return False
        is_alive = getattr(target, "is_alive", None)
        if callable(is_alive) and not is_alive():
            return False
        return True

    def _battle_for_delayed_attack(self, attack):
        from game.turn.battle import BattleManager

        target = attack.target
        battle = getattr(target, "current_battle", None)
        if battle is not None and not battle.ended:
            return battle
        participants = [
            character
            for character in self.game_manager.characters
            if character.is_alive()
            and (
                character is attack.source
                or character.position is target.position
            )
        ]
        if target not in participants:
            participants.append(target)
        if attack.source not in participants:
            participants.insert(0, attack.source)
        battle = BattleManager(participants, auto_link=False)
        battle.global_turn = self.current_turn
        return battle

    def _resolve_attack(self, attack, decision_provider):
        if attack.resolved:
            return {"skipped": True, "reason": "attack_already_resolved"}
        if not self._target_available(attack.target):
            attack.report_cancelled("delayed_target_unavailable")
            return {"skipped": True, "reason": "target_unavailable"}
        if attack not in attack.target.pending_attacks:
            attack.target.pending_attacks.append(attack)
        if decision_provider is None:
            from game.turn.decision import TerminalDecisionProvider

            decision_provider = TerminalDecisionProvider()
        battle = self._battle_for_delayed_attack(attack)
        return battle.resolve_simple_round_attack_event(
            attack,
            decision_provider,
        )

    @staticmethod
    def _resolution_context(entry, turn_number, decision_provider):
        context = dict(entry.context)
        context.update({
            "actor": entry.actor,
            "decision_provider": decision_provider,
            "turn_number": turn_number,
            "phase": entry.checkpoint,
            "effect_targets": [entry.target],
        })
        for key in (
            "event",
            "game_event",
            "paid_costs",
            "shared_attack_rolls",
            "grouped_effect_results",
            "declared_target_positions",
            "skill_mutation_batches",
            "skill_mutation_state",
        ):
            context.pop(key, None)
        return context

    def _resolve_effects(self, entry, turn_number, decision_provider):
        from game.resource.costs import SkillUnavailableError
        from game.skill.skill_runtime import apply_skill_effect
        from game.turn.damage import AttackEvent

        if not self._target_available(entry.target):
            return [{"skipped": True, "reason": "target_unavailable"}]
        context = self._resolution_context(
            entry,
            turn_number,
            decision_provider,
        )
        results = []
        for effect in entry.effects:
            try:
                result = apply_skill_effect(
                    effect,
                    entry.target,
                    entry.skill,
                    **context,
                )
                if isinstance(result, AttackEvent):
                    result = {
                        "attack": result,
                        "resolution": self._resolve_attack(
                            result,
                            decision_provider,
                        ),
                    }
                results.append(result)
            except SkillUnavailableError as error:
                results.append({
                    "skipped": True,
                    "reason": "effect_unavailable",
                    "message": str(error),
                })
        return results

    def _resolve_entries(
        self,
        entries,
        turn_number,
        decision_provider,
        *,
        resolved_checkpoint,
        fallback=False,
    ):
        if decision_provider is None:
            decision_provider = getattr(
                self.game_manager,
                "decision_provider",
                None,
            )
        due = sorted(
            entries,
            key=lambda entry: (entry.due_turn, entry.delay_id),
        )
        results = []
        for entry in due:
            if entry in self.entries:
                self.entries.remove(entry)
            if entry.kind == "attack":
                result = self._resolve_attack(
                    entry.attack,
                    decision_provider,
                )
                event_type = "delayed_attack_resolved"
            else:
                result = self._resolve_effects(
                    entry,
                    turn_number,
                    decision_provider,
                )
                event_type = "delayed_effect_resolved"
            entry.result = result
            entry.resolved = True
            entry.resolved_checkpoint = resolved_checkpoint
            entry.used_turn_end_fallback = fallback
            self.history.append(entry)
            self._emit(
                event_type,
                entry,
                result=result,
                decision_provider=decision_provider,
                phase=resolved_checkpoint,
            )
            results.append(entry)
        return results

    def resolve_checkpoint(
        self,
        turn_number,
        checkpoint,
        *,
        character=None,
        decision_provider=None,
    ):
        """Advance one matching-stage count and resolve entries reaching zero."""
        checkpoint = self.normalize_checkpoint(checkpoint)
        matching = [
            entry
            for entry in self.entries
            if not entry.resolved
            and not entry.cancelled
            and entry.checkpoint == checkpoint
            and (
                entry.checkpoint_owner is None
                or entry.checkpoint_owner is character
            )
        ]
        for entry in matching:
            entry.remaining_checkpoints -= 1
        due = [
            entry for entry in matching
            if entry.remaining_checkpoints <= 0
        ]
        return self._resolve_entries(
            due,
            turn_number,
            decision_provider,
            resolved_checkpoint=checkpoint,
        )

    def advance_round_fallback(
        self,
        turn_number,
        *,
        round_kind,
        round_token=None,
        decision_provider=None,
    ):
        """Advance the independent safety clock by one completed round."""
        due = []
        for entry in list(self.entries):
            if entry.resolved or entry.cancelled:
                continue
            if (
                round_kind == "simple_round"
                and round_token is not None
                and entry.origin_simple_round_token is round_token
            ):
                # The simple round that created the delay is not a later round.
                continue
            if round_kind == "global_turn":
                if entry.last_fallback_global_turn == turn_number:
                    continue
                entry.last_fallback_global_turn = turn_number
            entry.fallback_rounds_remaining -= 1
            if entry.fallback_rounds_remaining <= 0:
                due.append(entry)
        checkpoint = (
            "simple_round_end"
            if round_kind == "simple_round"
            else "global_turn_end"
        )
        return self._resolve_entries(
            due,
            turn_number,
            decision_provider,
            resolved_checkpoint=checkpoint,
            fallback=True,
        )

    def resolve_turn_end_fallback(self, turn_number, decision_provider=None):
        """Count a global round end, using it only as the safety fallback."""
        # global_turn_end can itself be the saved matching checkpoint.
        results = self.resolve_checkpoint(
            turn_number,
            "global_turn_end",
            decision_provider=decision_provider,
        )
        results.extend(self.advance_round_fallback(
            turn_number,
            round_kind="global_turn",
            decision_provider=decision_provider,
        ))
        return results

    def resolve_turn_start(self, turn_number, decision_provider=None):
        """Backward-compatible no-op; delays no longer resolve at turn start."""
        return []
