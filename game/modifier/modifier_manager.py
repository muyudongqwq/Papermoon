from dataclasses import dataclass
from numbers import Real

from game.modifier.context import ModifierContext
from game.modifier.dice_targets import dice_targets


@dataclass
class ModifierApplicationResult:
    outcome: str
    modifier: object
    replaced_modifier: object = None

    @property
    def success(self):
        return self.outcome not in {"rejected", "kept_stronger"}

    def __bool__(self):
        return self.success


class ModifierManager:
    """管理单个角色身上的Modifier施加、叠加、更新与移除。"""

    VALID_STACK_SCOPES = {"same_source", "all_sources", "independent"}
    VALID_STACKING_RULES = {
        "reject",
        "refresh",
        "replace",
        "stack",
        "independent",
        "strongest",
    }
    VALID_DURATION_REFRESH_RULES = {
        "reset",
        "keep_longer",
        "extend",
        "unchanged",
    }
    VALID_AT_MAX_STACKS_RULES = {"refresh", "reject", "replace"}
    VALID_STRENGTH_COMPARISONS = {"higher", "lower"}

    def __init__(self, owner):
        self.owner = owner
        self._next_application_order = 0
        self._capacity_transaction_depth = 0
        self._removing_modifiers = set()

    def find(self, **criteria):
        return [
            modifier
            for modifier in self.owner.modifiers
            if all(
                getattr(modifier, field, None) == value
                for field, value in criteria.items()
            )
        ]

    def _event_manager(self):
        game_manager = getattr(self.owner, "game_manager", None)
        return getattr(game_manager, "event_manager", None)

    def _refresh_visibility_if_needed(self, modifier):
        if modifier.effect_type not in {
            "visibility_bonus",
            "presence_concealment",
            "hidden",
        }:
            return
        game_manager = getattr(self.owner, "game_manager", None)
        turn_manager = getattr(game_manager, "turn_manager", None)
        if turn_manager is not None:
            turn_manager.update_visibility()

    @staticmethod
    def _state(modifier):
        result = {
            "duration": modifier.duration,
            "phase_window_remaining": modifier.phase_window_remaining,
            "stack_count": modifier.stack_count,
            "remaining_uses": modifier.remaining_uses,
        }
        if getattr(modifier, "status_runtime", None) is not None:
            from game.status.runtime import status_view
            result["status"] = status_view(modifier)
        return result

    def _resource_state(self):
        return {
            "hp": getattr(self.owner, "hp", None),
            "mp": getattr(self.owner, "mp", None),
        }

    def _capacity_state(self):
        return {
            "hpmax": getattr(self.owner, "hpmax", 1),
            "mpmax": getattr(self.owner, "mpmax", 1),
            "luck_reroll_max": getattr(self.owner, "luck_reroll_max", 0),
        }

    def _sync_capacity_state(self, before, modifier=None):
        if self._capacity_transaction_depth:
            return
        if modifier is not None and not (
            modifier.is_contextual
            and modifier.effect_type == "attribute_bonus"
        ):
            return
        sync = getattr(self.owner, "sync_contextual_capacities", None)
        if sync is None:
            return
        sync(
            before["hpmax"],
            before["mpmax"],
            before["luck_reroll_max"],
        )

    def _emit_resource_state_changes(self, before, *, reason):
        emit = getattr(self.owner, "_emit_builtin_resource_change", None)
        if emit is None:
            return
        for resource_id in ("hp", "mp"):
            old_value = before.get(resource_id)
            new_value = getattr(self.owner, resource_id, None)
            if old_value is None or new_value is None or old_value == new_value:
                continue
            emit(
                None,
                resource_id,
                old_value,
                new_value,
                requested_value=new_value - old_value,
                operation="add",
                reason=reason,
            )

    def _emit(self, event_type, modifier, *, payload=None):
        event_manager = self._event_manager()
        if event_manager is None:
            return None
        data = {
            "modifier_id": modifier.modifier_id,
            "effect_type": modifier.effect_type,
            "source_type": modifier.source_type,
            "source_id": modifier.source_id,
            "polarity": modifier.polarity,
        }
        if getattr(modifier, "status_runtime", None) is not None:
            from game.status.runtime import status_view
            data["status_instance"] = status_view(modifier)
        data.update(payload or {})
        return event_manager.emit(
            event_type,
            actor=modifier.source_actor,
            source=modifier,
            target=self.owner,
            phase=getattr(
                getattr(self.owner, "current_battle", None),
                "current_phase",
                None,
            ),
            battle=getattr(self.owner, "current_battle", None),
            position=getattr(self.owner, "position", None),
            payload=data,
        )

    def _emit_status(self, event_type, modifier, reason=None):
        status = getattr(modifier, "status", None)
        if status is None:
            return None
        return self._emit(
            event_type,
            modifier,
            payload={"status": status, "reason": reason},
        )

    def add(self, modifier):
        if modifier.target is not self.owner:
            raise ValueError("Modifier的target与Character不一致")
        self._validate_stacking(modifier)

        if modifier in self.owner.modifiers:
            return ModifierApplicationResult("rejected", modifier)

        if modifier.effect_type == "add_status" and self._block_status(modifier):
            return ModifierApplicationResult("rejected", modifier)

        # Buffs produced by a skill share the skill's stable id. A later use
        # replaces every buff from an earlier use of the same named skill,
        # while multiple effects belonging to the same use may coexist.
        if modifier.polarity == "buff" and modifier.buff_skill_id is not None and modifier.effect_type != "add_status":
            for existing_buff in self.owner.modifiers[:]:
                if (
                    existing_buff.polarity == "buff"
                    and existing_buff.buff_skill_id == modifier.buff_skill_id
                    and existing_buff.buff_application_id
                    != modifier.buff_application_id
                ):
                    self.remove(existing_buff)

        existing = self._find_stack_match(modifier)
        rule = modifier.stacking_rule
        if rule == "independent" or existing is None:
            return self._apply_new(modifier)
        if rule == "reject":
            return ModifierApplicationResult("rejected", existing)
        if rule == "refresh":
            before = self._state(existing)
            self._refresh_duration(existing, modifier)
            after = self._state(existing)
            if before != after:
                self._emit(
                    "modifier_refreshed",
                    existing,
                    payload={"old_state": before, "new_state": after},
                )
            return ModifierApplicationResult("refreshed", existing)
        if rule == "replace":
            return self._replace(existing, modifier)
        if rule == "stack":
            return self._stack(existing, modifier)
        if rule == "strongest":
            return self._keep_strongest(existing, modifier)
        raise ValueError(f"未知的Modifier叠加规则：{rule}")

    def _block_status(self, incoming):
        guards = sorted((item for item in self.owner.modifiers[:]
                         if item.effect_type == "status_immunity" and item.blocks(incoming)),
                        key=lambda item: (-getattr(item, "status_parent", item).priority,
                                          item.application_order if item.application_order is not None else float("inf")))
        if not guards:
            return False
        guard = guards[0]
        owner = getattr(guard, "status_parent", guard)
        previous = owner.remaining_uses
        consumed = owner.consume_use()
        # Reserve the charge and detach an exhausted parent before callbacks
        # can try another application in this same synchronous event chain.
        if consumed and owner.remaining_uses <= 0:
            if owner.remove_when_empty:
                self.remove(owner, reason="consumed")
            else:
                owner.remove()
        if consumed:
            self._emit("modifier_consumed", owner, payload={"consumption_event": "status_blocked",
                       "old_uses": previous, "remaining_uses": owner.remaining_uses})
        from game.game.rule_report import report
        report(self.owner, "status_blocked", actor=incoming.source_actor, targets=[self.owner], private=True,
               target_data={"status_id": incoming.status, "tags": sorted(incoming.tags),
                            "protection_status_id": getattr(owner, "status", None),
                            "remaining_uses": owner.remaining_uses})
        return True

    def remove(self, modifier, reason="removed"):
        if modifier not in self.owner.modifiers or modifier in self._removing_modifiers:
            return False
        status = getattr(modifier, "status", None)
        had_status = bool(status and self.owner.has_status(status))
        old_state = self._state(modifier)
        old_resources = self._resource_state()
        old_capacities = self._capacity_state()
        self._removing_modifiers.add(modifier)
        try:
            modifier.remove()
        finally:
            self._removing_modifiers.discard(modifier)
        self.owner.modifiers.remove(modifier)
        self._sync_capacity_state(old_capacities, modifier)
        self._refresh_visibility_if_needed(modifier)
        self._emit(
            "modifier_removed",
            modifier,
            payload={"reason": reason, "old_state": old_state},
        )
        self._emit_resource_state_changes(
            old_resources,
            reason=f"modifier_removed:{modifier.modifier_id}",
        )
        if had_status and not self.owner.has_status(status):
            self._emit_status("status_removed", modifier, reason=reason)
        if (
            modifier.effect_type == "carry_capacity"
            and self._capacity_transaction_depth == 0
        ):
            self.owner.validate_ride_group()
        return True

    def update(self, timing="global_turn_end", turn_number=None, duration_snapshot=None):
        removed = []
        for modifier in self.owner.modifiers[:]:
            if modifier not in self.owner.modifiers:
                continue
            if modifier.should_remove():
                self.remove(modifier, reason="condition_ended")
                removed.append(modifier)
                continue
            if duration_snapshot is not None and duration_snapshot.get(modifier) != modifier.duration_revision:
                continue
            if modifier.update(timing, turn_number=turn_number):
                self.remove(modifier, reason="expired")
                removed.append(modifier)
        return removed

    def update_phase_windows(
        self,
        *,
        scope,
        phase,
        boundary,
        phase_actor,
    ):
        removed = []
        for modifier in self.owner.modifiers[:]:
            if modifier.should_remove():
                self.remove(modifier, reason="condition_ended")
                removed.append(modifier)
                continue
            if modifier.update_phase_window(
                scope=scope,
                phase=phase,
                boundary=boundary,
                phase_actor=phase_actor,
            ):
                self.remove(modifier, reason="phase_window_expired")
                removed.append(modifier)
        return removed

    def remove_battle_phase_windows(self):
        removed = []
        for modifier in self.owner.modifiers[:]:
            if not modifier.is_battle_phase_window:
                continue
            if self.remove(modifier, reason="battle_left"):
                removed.append(modifier)
        return removed

    def remove_battle_phase_windows_owned_by(self, character):
        """Remove windows anchored to a character that left the battle."""
        removed = []
        for modifier in self.owner.modifiers[:]:
            if (
                not modifier.is_battle_phase_window
                or modifier.phase_window_owner != "source"
                or modifier.source is not character
            ):
                continue
            if self.remove(modifier, reason="phase_owner_left_battle"):
                removed.append(modifier)
        return removed

    def remove_for_death(self):
        removed = []
        for modifier in self.owner.modifiers[:]:
            if modifier.persist_after_death:
                continue
            if self.remove(modifier, reason="death"):
                removed.append(modifier)
        return removed

    def consume_event(
        self,
        event,
        context=None,
        *,
        optional_decider=None,
    ):
        """Consume all modifiers matching one committed runtime event."""
        raw_contexts = (
            list(context)
            if isinstance(context, (list, tuple))
            else [context]
        )
        contexts = [
            ModifierContext.coerce(item, actor=self.owner)
            for item in raw_contexts
        ]
        candidates = sorted(
            (
                modifier
                for modifier in self.owner.modifiers[:]
                if any(
                    modifier.matches_consumption(event, item)
                    for item in contexts
                )
            ),
            key=lambda modifier: (
                modifier.application_order
                if modifier.application_order is not None
                else float("inf")
            ),
        )
        consumed = []
        pending_optional = []
        for modifier in candidates:
            if modifier not in self.owner.modifiers:
                continue
            if (
                modifier.consumption_mode == "optional"
                and not modifier._optional_consumption_active
            ):
                matched_context = next(
                    item
                    for item in contexts
                    if modifier.matches_consumption(event, item)
                )
                if optional_decider is None:
                    pending_optional.append(modifier)
                    continue
                elif not optional_decider(modifier, event, matched_context):
                    pending_optional.append(modifier)
                    continue
            old_uses = modifier.remaining_uses
            if not modifier.consume_use():
                continue
            consumed.append(modifier)
            modifier._optional_consumption_active = False
            self._emit(
                "modifier_consumed",
                modifier,
                payload={
                    "consumption_event": event,
                    "old_uses": old_uses,
                    "remaining_uses": modifier.remaining_uses,
                },
            )
            if modifier.remaining_uses <= 0 and modifier.remove_when_empty:
                self.remove(modifier, reason="consumed")
            elif modifier.remaining_uses <= 0:
                modifier.remove()
        return {
            "consumed": consumed,
            "pending_optional": pending_optional,
        }

    def prepare_event(
        self,
        event,
        context=None,
        *,
        optional_decider=None,
    ):
        """Arm accepted optional modifiers before the event is snapshotted."""
        raw_contexts = (
            list(context)
            if isinstance(context, (list, tuple))
            else [context]
        )
        contexts = [
            ModifierContext.coerce(item, actor=self.owner)
            for item in raw_contexts
        ]
        accepted = []
        pending = []
        for modifier in self.owner.modifiers[:]:
            if modifier.consumption_mode != "optional":
                continue
            matched = next(
                (
                    item
                    for item in contexts
                    if modifier.matches_consumption(event, item)
                ),
                None,
            )
            if matched is None:
                continue
            if (
                optional_decider is not None
                and optional_decider(modifier, event, matched)
            ):
                modifier._optional_consumption_active = True
                accepted.append(modifier)
            else:
                modifier._optional_consumption_active = False
                pending.append(modifier)
        return {"accepted": accepted, "pending_optional": pending}

    def get_purifiable(self):
        """返回当前可被净化的负面Modifier，顺序与施加顺序一致。"""
        return [
            modifier
            for modifier in self.owner.modifiers
            if modifier.polarity == "debuff" and modifier.purifiable
        ]

    def purify(self, modifiers=None, maximum="all"):
        """移除至多指定数量的可净化负面Modifier。

        modifiers可传入单个Modifier或按选择顺序排列的可迭代对象；省略时
        使用当前施加顺序。一个有多层stack的Modifier仍作为一个整体移除。
        """
        if maximum != "all":
            if not isinstance(maximum, int) or isinstance(maximum, bool):
                raise TypeError("purify的maximum必须是正整数或'all'")
            if maximum < 1:
                raise ValueError("purify的maximum必须大于0")

        purifiable = self.get_purifiable()
        if modifiers is None:
            candidates = purifiable
        elif hasattr(modifiers, "effect_type"):
            candidates = [modifiers]
        else:
            candidates = list(modifiers)

        limit = len(candidates) if maximum == "all" else maximum
        removed = []
        seen = set()
        for modifier in candidates:
            if len(removed) >= limit:
                break
            marker = id(modifier)
            if marker in seen:
                continue
            seen.add(marker)
            if modifier not in purifiable:
                continue
            if self.remove(modifier):
                removed.append(modifier)
        return removed

    def get_damage_adjustments(
        self,
        direction,
        damage_type,
        action_id=None,
        skill_id=None,
        source_tags=None,
        context=None,
    ):
        percentages = []
        flats = []
        for modifier in self.owner.modifiers:
            matches = getattr(modifier, "matches", None)
            if matches is None or not matches(
                direction,
                damage_type,
                action_id=action_id,
                skill_id=skill_id,
                source_tags=source_tags,
                context=context,
            ):
                continue
            if modifier.calculation == "percentage":
                percentages.append(modifier.total_value)
            else:
                flats.append(modifier.total_value)
        return percentages, flats

    def calculate_cost(self, base_cost, resource, cost_id=None, context=None):
        """统一费用管线：乘算 -> 固定加减 -> 覆盖 -> 向零取整。"""
        if base_cost < 0:
            raise ValueError("基础消耗不能小于0")
        matched = [
            modifier
            for modifier in self.owner.modifiers
            if getattr(modifier, "matches_cost", lambda *_args: False)(
                resource,
                cost_id,
                context,
            )
        ]
        multipliers = [
            modifier.total_value
            for modifier in matched
            if modifier.calculation == "multiplier"
        ]
        flats = [
            modifier.total_value
            for modifier in matched
            if modifier.calculation == "flat"
        ]
        overrides = [
            modifier
            for modifier in matched
            if modifier.calculation == "override"
        ]

        cost = base_cost
        for multiplier in multipliers:
            cost *= multiplier
        cost += sum(flats)
        if overrides:
            overrides.sort(
                key=lambda modifier: (
                    modifier.priority,
                    modifier.application_order
                    if modifier.application_order is not None
                    else -1,
                )
            )
            cost = overrides[-1].total_value
        return max(0, int(cost))

    def get_contextual_bonus(
        self,
        effect_type,
        *,
        effect_target=None,
        context=None,
        **defaults,
    ):
        context = ModifierContext.coerce(
            context,
            actor=defaults.pop("actor", self.owner),
            **defaults,
        )
        total = 0
        for modifier in self.owner.modifiers:
            if (
                not modifier.applied
                or not modifier.is_contextual
                or modifier.effect_type != effect_type
            ):
                continue
            if effect_target is not None:
                target = getattr(modifier, "effect_target", None)
                if target != effect_target and (effect_type != "dice_bonus" or effect_target not in dice_targets(target)):
                    continue
            if modifier.matches_context(context):
                total += modifier.value * modifier.stack_count
        return total

    def absorb_damage(self, damage, damage_event):
        if (
            damage <= 0
            or getattr(damage_event, "ignore_shield", False)
            or getattr(damage_event, "damage_type", None) == "true_damage"
        ):
            return damage, []
        shields = [
            modifier
            for modifier in self.owner.modifiers
            if modifier.effect_type == "shield"
            and modifier.can_absorb(damage_event)
        ]
        shields.sort(
            key=lambda modifier: (
                -modifier.priority,
                (
                    modifier.application_order
                    if modifier.application_order is not None
                    else float("inf")
                ),
            )
        )
        remaining = damage
        absorptions = []
        for shield in shields:
            absorbed = shield.absorb(remaining, damage_event)
            if absorbed:
                absorptions.append((shield, absorbed))
                remaining -= absorbed
            if shield.remaining_value <= 0:
                self.remove(shield)
            if remaining <= 0:
                break
        return remaining, absorptions

    def _validate_stacking(self, modifier):
        if modifier.stack_scope not in self.VALID_STACK_SCOPES:
            raise ValueError(f"未知的stack_scope：{modifier.stack_scope}")
        if modifier.stacking_rule not in self.VALID_STACKING_RULES:
            raise ValueError(f"未知的stacking_rule：{modifier.stacking_rule}")
        if (
            modifier.duration_refresh_rule
            not in self.VALID_DURATION_REFRESH_RULES
        ):
            raise ValueError(
                "未知的duration_refresh_rule："
                f"{modifier.duration_refresh_rule}"
            )
        if modifier.at_max_stacks_rule not in self.VALID_AT_MAX_STACKS_RULES:
            raise ValueError(
                "未知的at_max_stacks_rule："
                f"{modifier.at_max_stacks_rule}"
            )
        if (
            modifier.strength_comparison is not None
            and modifier.strength_comparison
            not in self.VALID_STRENGTH_COMPARISONS
        ):
            raise ValueError(
                "未知的strength_comparison："
                f"{modifier.strength_comparison}"
            )
        if modifier.stacking_rule == "strongest":
            self._get_strength_rule(modifier)

    def _find_stack_match(self, modifier):
        if modifier.stack_scope == "independent":
            return None
        for existing in self.owner.modifiers:
            if existing.stack_group != modifier.stack_group:
                continue
            if modifier.stack_scope == "all_sources":
                return existing
            if self._has_same_source(existing, modifier):
                return existing
        return None

    @staticmethod
    def _has_same_source(existing, modifier):
        return (
            existing.source is modifier.source
            and existing.source_actor is modifier.source_actor
            and existing.source_type == modifier.source_type
            and existing.source_id == modifier.source_id
        )

    def _apply_new(self, modifier, index=None):
        if modifier.application_order is None:
            modifier.application_order = self._next_application_order
            self._next_application_order += 1
        status = getattr(modifier, "status", None)
        had_status = bool(status and self.owner.has_status(status))
        old_resources = self._resource_state()
        old_capacities = self._capacity_state()
        was_alive = self.owner.is_alive()
        provisional_status = modifier.effect_type == "add_status" and not modifier.applied
        if provisional_status:
            # Register the parent before installing its passive children.  A
            # child modifier_applied callback may immediately query or consume
            # the parent (notably status immunity).
            if index is None:
                self.owner.modifiers.append(modifier)
            else:
                self.owner.modifiers.insert(index, modifier)
        try:
            if not modifier.applied:
                modifier.apply()
        except BaseException:
            if provisional_status and modifier in self.owner.modifiers:
                self.owner.modifiers.remove(modifier)
            raise
        if provisional_status and (
            not modifier.applied or modifier not in self.owner.modifiers
        ):
            # It was consumed, killed or otherwise removed by a synchronous
            # callback during installation.  Children appended after that
            # removal must not survive as detached effects.
            modifier.status_runtime.remove_passives()
            if modifier in self.owner.modifiers:
                self.owner.modifiers.remove(modifier)
            return ModifierApplicationResult("rejected", modifier)
        # Applying a withdrawal can synchronously trigger a lethal field exit.
        # Death cleanup ran before this modifier could enter the owner's list.
        if was_alive and not self.owner.is_alive() and not modifier.persist_after_death:
            modifier.remove()
            return ModifierApplicationResult("rejected", modifier)
        if not provisional_status:
            if index is None:
                self.owner.modifiers.append(modifier)
            else:
                self.owner.modifiers.insert(index, modifier)
        self._sync_capacity_state(old_capacities, modifier)
        self._refresh_visibility_if_needed(modifier)
        self._emit(
            "modifier_applied",
            modifier,
            payload={"new_state": self._state(modifier)},
        )
        self._emit_resource_state_changes(
            old_resources,
            reason=f"modifier_applied:{modifier.modifier_id}",
        )
        if status and not had_status and self.owner.has_status(status):
            self._emit_status("status_added", modifier, reason="applied")
        return ModifierApplicationResult("applied", modifier)

    def _replace(self, existing, modifier):
        index = self.owner.modifiers.index(existing)
        old_state = self._state(existing)
        old_resources = self._resource_state()
        old_capacities = self._capacity_state()
        self._capacity_transaction_depth += 1
        try:
            self.remove(existing, reason="replaced")
            result = self._apply_new(modifier, index=index)
        finally:
            self._capacity_transaction_depth -= 1
        self._sync_capacity_state(old_capacities)
        if modifier.effect_type == "carry_capacity":
            self.owner.validate_ride_group()
        self._emit_resource_state_changes(
            old_resources,
            reason=f"modifier_replaced:{modifier.modifier_id}",
        )
        result.outcome = "replaced"
        result.replaced_modifier = existing
        self._emit(
            "modifier_replaced",
            modifier,
            payload={
                "replaced_modifier": existing,
                "old_state": old_state,
                "new_state": self._state(modifier),
            },
        )
        return result

    def _stack(self, existing, modifier):
        available = existing.max_stacks - existing.stack_count
        added_stacks = min(available, modifier.stack_count)
        if added_stacks > 0:
            old_count = existing.stack_count
            old_resources = self._resource_state()
            old_capacities = self._capacity_state()
            existing.change_stack_count(existing.stack_count + added_stacks)
            self._refresh_duration(existing, modifier)
            self._sync_capacity_state(old_capacities, existing)
            self._emit_resource_state_changes(
                old_resources,
                reason=f"modifier_stacked:{existing.modifier_id}",
            )
            self._refresh_visibility_if_needed(existing)
            self._emit(
                "modifier_stack_changed",
                existing,
                payload={
                    "old_stacks": old_count,
                    "new_stacks": existing.stack_count,
                },
            )
            return ModifierApplicationResult("stacked", existing)

        at_max_rule = modifier.at_max_stacks_rule
        if at_max_rule == "refresh":
            before = self._state(existing)
            self._refresh_duration(existing, modifier)
            after = self._state(existing)
            if before != after:
                self._emit(
                    "modifier_refreshed",
                    existing,
                    payload={"old_state": before, "new_state": after},
                )
            return ModifierApplicationResult("refreshed", existing)
        if at_max_rule == "reject":
            return ModifierApplicationResult("rejected", existing)
        if at_max_rule == "replace":
            return self._replace(existing, modifier)
        raise ValueError(f"未知的at_max_stacks_rule：{at_max_rule}")

    def _keep_strongest(self, existing, modifier):
        existing_value, existing_rule = self._get_strength_rule(existing)
        incoming_value, incoming_rule = self._get_strength_rule(modifier)
        if existing_rule != incoming_rule:
            raise ValueError(
                "同一strongest stack_group的strength_comparison必须一致；"
                "正面与负面效果应使用不同的stack_group"
            )

        incoming_is_at_least_as_strong = (
            incoming_value >= existing_value
            if incoming_rule == "higher"
            else incoming_value <= existing_value
        )
        if not incoming_is_at_least_as_strong:
            return ModifierApplicationResult("kept_stronger", existing)

        result = self._replace(existing, modifier)
        result.outcome = (
            "replaced_equal"
            if incoming_value == existing_value
            else "replaced_stronger"
        )
        return result

    def _get_strength_rule(self, modifier):
        uses_priority = modifier.strength_priority is not None
        if uses_priority:
            value = modifier.strength_priority
        else:
            value = getattr(modifier, "total_value", None)
            if value is None:
                raw_value = getattr(modifier, "value", None)
                if isinstance(raw_value, Real) and not isinstance(raw_value, bool):
                    value = raw_value * modifier.stack_count

        if not isinstance(value, Real) or isinstance(value, bool):
            raise ValueError(
                "strongest需要数值value/total_value，"
                "复杂效果必须提供strength_priority"
            )

        comparison = modifier.strength_comparison
        if comparison is None:
            if uses_priority:
                comparison = "higher"
            else:
                comparison = "lower" if value < 0 else "higher"
        return value, comparison

    @staticmethod
    def _refresh_duration(existing, modifier):
        ModifierManager._refresh_uses(existing, modifier)
        rule = modifier.duration_refresh_rule
        if rule != "unchanged":
            existing.duration_revision += 1
        if existing.phase_window is not None or modifier.phase_window is not None:
            if existing.phase_window_signature != modifier.phase_window_signature:
                raise ValueError(
                    "同一叠加组的阶段窗口定义必须一致"
                )
            incoming = modifier.phase_window_occurrences
            current = existing.phase_window_remaining
            if rule == "unchanged":
                return current
            if rule == "reset":
                existing.phase_window_remaining = incoming
            elif rule == "keep_longer":
                existing.phase_window_remaining = max(current, incoming)
            elif rule == "extend":
                existing.phase_window_remaining = current + incoming
            return existing.phase_window_remaining

        incoming = modifier.duration
        current = existing.duration

        if rule == "unchanged":
            return current
        if current is None:
            return None
        if incoming is None:
            existing.duration = None
        elif rule == "reset":
            existing.duration = incoming
        elif rule == "keep_longer":
            existing.duration = max(current, incoming)
        elif rule == "extend":
            existing.duration = current + incoming
        return existing.duration

    @staticmethod
    def _refresh_uses(existing, modifier):
        if existing.consumption is None and modifier.consumption is None:
            return None
        if (
            existing.consumption is None
            or modifier.consumption is None
            or existing.consumption_event != modifier.consumption_event
            or existing.consumption_mode != modifier.consumption_mode
        ):
            raise ValueError("同一叠加组的consumption定义必须一致")
        rule = modifier.use_refresh_rule
        incoming = modifier.max_uses
        current = existing.remaining_uses
        if rule == "unchanged":
            return current
        if rule == "reset":
            existing.remaining_uses = incoming
        elif rule == "keep_more":
            existing.remaining_uses = max(current, incoming)
        elif rule == "extend":
            existing.remaining_uses = current + incoming
        existing.max_uses = max(existing.max_uses, existing.remaining_uses)
        if existing.remaining_uses > 0 and not existing.applied:
            existing.apply()
        return existing.remaining_uses
