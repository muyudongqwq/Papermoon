from dataclasses import dataclass, field
import random

from game.modifier.context import ModifierContext
from game.turn.decision import DecisionOption, DecisionRequest


@dataclass
class RollResult:
    character: object
    stat_name: str
    initial_die: int
    die: int
    stat_bonus: int | float
    dice_bonus: int | float
    situational_bonus: int | float
    critical_modifier: int = 0
    total_before_final_multiplier: int | float = 0
    final_multiplier: int | float = 1
    total: int | float = 0
    rerolls_used: int = 0
    flips_used: int = 0
    history: list = field(default_factory=list)
    critical_success: bool = False
    critical_failure: bool = False


class RollResolver:
    """Resolve a battle d10, including optional luck choices and final-face criticals."""

    @staticmethod
    def _emit_raw_die(
        character,
        stat_name,
        die,
        *,
        phase,
        reason,
        roll_index,
        decision_provider=None,
    ):
        game_manager = getattr(character, "game_manager", None)
        event_manager = getattr(game_manager, "event_manager", None)
        if event_manager is None:
            return None
        return event_manager.emit(
            "raw_die_generated",
            actor=character,
            source=character,
            target=character,
            value=die,
            phase=phase,
            battle=getattr(character, "current_battle", None),
            position=getattr(character, "position", None),
            payload={
                "stat_name": stat_name,
                "die": die,
                "reason": reason,
                "roll_index": roll_index,
            },
            decision_provider=decision_provider,
        )

    def roll(
        self,
        character,
        stat_name,
        decision_provider=None,
        phase="掷骰",
        situational_bonus=0,
        allow_luck=True,
        initial_die=None,
        roller=None,
        modifier_context=None,
    ):
        roller = roller or (lambda: random.randint(1, 10))
        first_die = roller() if initial_die is None else initial_die
        die = first_die
        history = [("roll", die)]
        rerolls_used = 0
        flips_used = 0
        self._emit_raw_die(
            character,
            stat_name,
            die,
            phase=phase,
            reason="initial",
            roll_index=0,
            decision_provider=decision_provider,
        )

        if allow_luck and character.in_battle and decision_provider is not None:
            while character.luck_reroll > 0 or character.fortune.plus > 0:
                options = [DecisionOption("确认当前骰面", "confirm", ("确认", "confirm"))]
                if character.luck_reroll > 0:
                    used = character.luck_reroll_max - character.luck_reroll
                    options.append(DecisionOption(
                        f"幸运重骰（已使用{used}，剩余{character.luck_reroll}）",
                        "reroll",
                        ("重骰", "reroll"),
                    ))
                if character.fortune.plus > 0:
                    used = character.fortune.plus_capacity - character.fortune.plus
                    options.append(DecisionOption(
                        f"幸运加符翻转（已使用{used}，剩余{character.fortune.plus}）",
                        "flip",
                        ("翻转", "flip"),
                    ))
                request = DecisionRequest(
                    character=character,
                    phase=phase,
                    prompt=f"当前1d10骰面：{die}",
                    options=tuple(options),
                )
                if hasattr(decision_provider, "choose_optional"):
                    choice = decision_provider.choose_optional(request)
                else:
                    choice = decision_provider.choose(request)
                if choice == "confirm":
                    break
                if choice == "reroll":
                    if not character.use_luck_reroll():
                        continue
                    die = roller()
                    rerolls_used += 1
                    history.append(("reroll", die))
                    self._emit_raw_die(
                        character,
                        stat_name,
                        die,
                        phase=phase,
                        reason="reroll",
                        roll_index=rerolls_used,
                        decision_provider=decision_provider,
                    )
                    continue
                if choice == "flip":
                    if not character.consume_attribute_plus("fortune"):
                        continue
                    die = 11 - die
                    flips_used += 1
                    history.append(("flip", die))

        effective_fortune = character.get_effective_attribute_value(
            "fortune",
            modifier_context,
        )
        critical_success = die == 10 and effective_fortune >= 2
        critical_failure = die == 1 and character.can_critical_failure
        critical_modifier = 15 if critical_success else (-15 if critical_failure else 0)
        if stat_name in getattr(character, "ATTRIBUTE_NAMES", ()):
            stat_bonus = character.get_effective_attribute_value(
                stat_name,
                modifier_context,
            )
        elif stat_name in getattr(character, "DERIVED_STAT_NAMES", ()):
            stat_bonus = character.get_effective_derived_stat(
                stat_name,
                modifier_context,
            )
        else:
            stat_bonus = getattr(character, stat_name)
            stat_bonus = getattr(stat_bonus, "value", stat_bonus)
        contextual_bonus = character.modifier_manager.get_contextual_bonus(
            "dice_bonus",
            effect_target=stat_name,
            context=modifier_context,
            actor=character,
        )
        contextual_bonus += character.modifier_manager.get_contextual_bonus(
            "dice_bonus",
            effect_target="dice_bonus",
            context=modifier_context,
            actor=character,
        )
        dice_bonus = character.dice_bonus + contextual_bonus
        total_before_final_multiplier = (
            die
            + stat_bonus
            + dice_bonus
            + situational_bonus
            + critical_modifier
        )
        final_multiplier = 1
        if character.has_status("brink_of_death"):
            final_multiplier *= 0.5
        if (
            character.has_status("casting")
            and stat_name in {"dodge", "block", "offset"}
        ):
            final_multiplier *= 0.5
        total = int(total_before_final_multiplier * final_multiplier)
        result = RollResult(
            character=character,
            stat_name=stat_name,
            initial_die=first_die,
            die=die,
            stat_bonus=stat_bonus,
            dice_bonus=dice_bonus,
            situational_bonus=situational_bonus,
            critical_modifier=critical_modifier,
            total_before_final_multiplier=total_before_final_multiplier,
            final_multiplier=final_multiplier,
            total=total,
            rerolls_used=rerolls_used,
            flips_used=flips_used,
            history=history,
            critical_success=critical_success,
            critical_failure=critical_failure,
        )
        context = ModifierContext.coerce(
            modifier_context,
            actor=character,
        )
        context.event = result
        context.tags |= {"roll", stat_name}
        character.modifier_manager.consume_event(
            "roll_committed",
            context,
        )
        game_manager = getattr(character, "game_manager", None)
        event_manager = getattr(game_manager, "event_manager", None)
        if event_manager is not None:
            event_manager.emit(
                "roll_resolved",
                actor=character,
                source=result,
                target=character,
                value=total,
                phase=phase,
                battle=getattr(character, "current_battle", None),
                position=getattr(character, "position", None),
                payload={
                    "stat_name": stat_name,
                    "initial_die": first_die,
                    "die": die,
                    "total": total,
                    "critical_success": critical_success,
                    "critical_failure": critical_failure,
                    "rerolls_used": rerolls_used,
                    "flips_used": flips_used,
                    "roll_result": result,
                },
                decision_provider=decision_provider,
            )
        from game.game.rule_report import report
        report(character, "roll_resolved", actor=character, private=True, phase=phase,
               actor_data={"stat_name": stat_name, "initial_die": first_die, "die": die,
                           "stat_bonus": stat_bonus, "dice_bonus": dice_bonus,
                           "situational_bonus": situational_bonus, "total": total,
                           "critical_modifier": critical_modifier, "final_multiplier": final_multiplier,
                           "critical_success": critical_success, "critical_failure": critical_failure,
                           "rerolls_used": rerolls_used, "flips_used": flips_used,
                           "history": history})
        return result
