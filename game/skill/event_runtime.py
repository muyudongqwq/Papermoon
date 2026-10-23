"""Unified trigger/react event queue for skill components."""

from dataclasses import dataclass, field
from itertools import count

from game.turn.decision import DecisionOption, DecisionRequest


_EVENT_IDS = count(1)
NO_EVENT_TARGET = "__no_event_target__"


@dataclass
class GameEvent:
    event_type: str
    timing: str = "after"
    actor: object = None
    source: object = None
    target: object = None
    targets: list = field(default_factory=list)
    value: object = None
    phase: str = None
    global_turn: int = 0
    battle: object = None
    position: object = None
    payload: dict = field(default_factory=dict)
    parent: object = None
    chain_id: int = None
    depth: int = 0
    event_id: int = field(default_factory=lambda: next(_EVENT_IDS))
    cancelled: bool = False
    completed: bool = False
    stopped: bool = False
    stop_reason: str = None
    records: list = field(default_factory=list)
    value_operations: list = field(default_factory=list)

    def __post_init__(self):
        if not isinstance(self.event_type, str) or not self.event_type:
            raise ValueError("event_type必须是非空字符串")
        if self.timing not in {"before", "after"}:
            raise ValueError("事件timing必须是before或after")
        self.targets = list(self.targets or ([] if self.target is None else [self.target]))
        if self.target is None and self.targets:
            self.target = self.targets[0]
        if self.chain_id is None:
            self.chain_id = self.event_id

    def cancel(self, reason=None):
        self.cancelled = True
        if reason is not None:
            self.payload["cancel_reason"] = reason
        return True

    def modify_value(self, operation, value, *, minimum=None, maximum=None):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("事件数值修正必须是数字")
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise TypeError("当前事件没有可修改的数值")
        if operation == "add":
            result = self.value + value
        elif operation == "multiply":
            result = self.value * value
        elif operation == "set":
            result = value
        else:
            raise ValueError("事件数值操作必须是add、multiply或set")
        if minimum is not None:
            result = max(minimum, result)
        if maximum is not None:
            result = min(maximum, result)
        self.value = int(result)
        self.value_operations.append({
            "operation": operation,
            "value": value,
            "minimum": minimum,
            "maximum": maximum,
        })
        return self.value

    def replay_value_operations(self, base_value):
        """Reapply earlier value edits when an event's base value changes."""
        result = base_value
        for item in self.value_operations:
            if item["operation"] == "add":
                result += item["value"]
            elif item["operation"] == "multiply":
                result *= item["value"]
            else:
                result = item["value"]
            if item["minimum"] is not None:
                result = max(item["minimum"], result)
            if item["maximum"] is not None:
                result = min(item["maximum"], result)
            result = int(result)
        return int(result)


@dataclass(frozen=True)
class EventCandidate:
    owner: object
    skill: object
    component: dict
    component_index: int
    skill_index: int
    priority: int
    kind: str

    @property
    def component_id(self):
        return self.component.get(
            "component_id",
            f"component_{self.component_index}",
        )

    @property
    def key(self):
        return id(self.owner), self.skill.skill_id, self.component_id

    @property
    def label(self):
        component_name = self.component.get("name")
        return (
            f"{self.skill.name}：{component_name}"
            if component_name
            else self.skill.name
        )


class EventManager:
    """Resolve automatic triggers and optional reactions deterministically."""

    MAX_CHAIN_DEPTH = 32

    def __init__(self, game_manager):
        self.game_manager = game_manager
        self.history = []
        self._stack = []
        self._event_uses = set()
        self._turn_uses = {}
        self._chain_uses = set()
        self._lifecycle_reservations = set()
        self._status_uses = set()

    @property
    def current_event(self):
        return self._stack[-1] if self._stack else None

    def component_limit_view(self, owner, skill, component, *, component_index=0):
        """Read event quotas without inventing a target outside its context."""
        if component["type"] not in {"trigger", "react"}:
            return None
        candidate = EventCandidate(owner, skill, component, component_index, 0, 0, component["type"])
        limit = self._limit(candidate)
        result = {**limit, "remaining": None, "context_required": True}
        if limit["scope"] in {"until_triggered", "next_battle_start"}:
            result.update(remaining=int(skill.is_component_active(candidate.component_id)), context_required=False)
            return result
        event = self.current_event
        trigger = self._trigger_config(component)
        if event is not None and (trigger["event_type"], trigger["timing"]) == (event.event_type, event.timing):
            result.update(remaining=max(
                max(0, limit["maximum"] - self._usage_count(candidate, event, target))
                for target in self._usage_targets(candidate, event)
            ), context_required=False)
        return result

    def clear_turn_usage(self, turn_number=None):
        self._status_uses = {key for key in self._status_uses if key[0] == turn_number}
        if turn_number is None:
            self._turn_uses.clear()
            self._chain_uses.clear()
        else:
            self._turn_uses = {
                key: value
                for key, value in self._turn_uses.items()
                if key[0] == turn_number
            }

    def emit(
        self,
        event_type,
        *,
        timing="after",
        actor=None,
        source=None,
        target=None,
        targets=None,
        value=None,
        phase=None,
        battle=None,
        position=None,
        payload=None,
        decision_provider=None,
        parent=None,
    ):
        if decision_provider is None:
            decision_provider = getattr(
                self.game_manager,
                "decision_provider",
                None,
            )
        parent = self.current_event if parent is None else parent
        event = GameEvent(
            event_type=event_type,
            timing=timing,
            actor=actor,
            source=source,
            target=target,
            targets=list(targets or ([] if target is None else [target])),
            value=value,
            phase=phase,
            global_turn=getattr(self.game_manager.turn_manager, "turn", 0),
            battle=battle or getattr(actor, "current_battle", None),
            position=position,
            payload=dict(payload or {}),
            parent=parent,
            chain_id=(parent.chain_id if parent is not None else None),
            depth=(parent.depth + 1 if parent is not None else 0),
        )
        if event.depth >= self.MAX_CHAIN_DEPTH:
            event.stopped = True
            event.stop_reason = "maximum_chain_depth"
            event.completed = True
            self.history.append(event)
            return event

        self._stack.append(event)
        try:
            candidates = self._collect_candidates(event)
            priorities = sorted(
                {candidate.priority for candidate in candidates},
                reverse=True,
            )
            for priority in priorities:
                tier = [
                    candidate
                    for candidate in candidates
                    if candidate.priority == priority
                ]
                for candidate in tier:
                    if candidate.kind != "trigger":
                        continue
                    if (
                        candidate.component.get("choices") is not None
                        and decision_provider is None
                    ):
                        continue
                    if self._candidate_usable(candidate, event):
                        self._execute(candidate, event, decision_provider)
                self._resolve_react_tier(
                    [candidate for candidate in tier if candidate.kind == "react"],
                    event,
                    decision_provider,
                )
            event.completed = True
            return event
        finally:
            self._stack.pop()
            self.history.append(event)
            reports = getattr(self.game_manager, "rule_reports", None)
            if reports is not None:
                reports.record_game_event(event)
            if parent is None:
                self._chain_uses = {
                    marker
                    for marker in self._chain_uses
                    if marker[0] != event.chain_id
                }

    def _characters(self, event):
        result = []
        for character in self.game_manager.all_characters:
            if character not in result:
                result.append(character)
        for character in (event.actor, event.target):
            if character is not None and hasattr(character, "is_alive") and character not in result:
                result.append(character)
        return result

    @staticmethod
    def _trigger_config(component):
        config = dict(component.get("trigger", {}))
        if "event_type" not in config and component.get("trigger_event"):
            config["event_type"] = component["trigger_event"]
        config.setdefault("timing", "after")
        config.setdefault("priority", component.get("priority", 0))
        return config

    def _collect_candidates(self, event):
        from game.skill.skill_runtime import iter_character_skills
        from game.status.runtime import iter_status_runtimes

        candidates = []
        for owner in self._characters(event):
            sources = [*iter_character_skills(owner), *iter_status_runtimes(owner)]
            for skill_index, skill in enumerate(sources):
                for component_index, component in enumerate(skill.definitions):
                    kind = component.get("type")
                    if kind not in {"trigger", "react"}:
                        continue
                    config = self._trigger_config(component)
                    if config.get("event_type") != event.event_type:
                        continue
                    if config.get("timing", "after") != event.timing:
                        continue
                    allow_when_dead = component.get(
                        "allow_when_dead",
                        config.get("allow_when_dead", False),
                    )
                    if not owner.is_alive() and not allow_when_dead:
                        continue
                    candidates.append(EventCandidate(
                        owner=owner,
                        skill=skill,
                        component=component,
                        component_index=component_index,
                        skill_index=skill_index,
                        priority=int(config.get("priority", 0)),
                        kind=kind,
                    ))
        return sorted(candidates, key=lambda item: self._candidate_sort_key(item, event))

    def _owner_order(self, owner, event):
        battle = event.battle or getattr(owner, "current_battle", None)
        if battle is not None:
            order = list(
                getattr(battle, "current_order", [])
                or getattr(battle, "initial_order", [])
                or []
            )
            if owner in order:
                return 0, order.index(owner)
        global_order = list(
            getattr(self.game_manager.turn_manager, "global_action_order", [])
            or getattr(self.game_manager.turn_manager, "non_battle_order", [])
            or []
        )
        if owner in global_order:
            return 1, global_order.index(owner)
        return 2, getattr(owner, "registration_index", 10**9) or 0

    def _candidate_sort_key(self, candidate, event):
        return (
            -candidate.priority,
            *self._owner_order(candidate.owner, event),
            candidate.skill_index,
            candidate.component_index,
        )

    def _event_condition_matches(self, candidate, event):
        from game.skill.skill_runtime import condition_matches

        owner = candidate.owner
        condition = candidate.component.get("condition", {})
        return condition_matches(condition, owner, {"event": event})

    def _effect_targets(self, candidate, event):
        selector = candidate.component.get("target", "self")
        if selector in {"self", "none"}:
            targets = [candidate.owner]
        elif selector == "event_actor":
            targets = [event.actor]
        elif selector == "event_source":
            targets = [event.source]
        elif selector == "event_target":
            targets = [event.target]
        elif selector == "event_targets":
            targets = list(event.targets)
        else:
            targets = [event.target]
        return [target for target in targets if target is not None]

    def _limit(self, candidate):
        if candidate.kind == "react":
            default = {"scope": "global_turn", "per_target": True, "maximum": 1}
        else:
            default = {"scope": "event", "per_target": True, "maximum": 1}
        default.update(candidate.component.get("limit", {}))
        return default

    def _usage_targets(self, candidate, event):
        # Per-target limits belong to the event's actual target snapshot, not
        # to the object receiving a self-buff as part of the reaction.
        targets = list(event.targets)
        if not targets and event.target is not None:
            targets = [event.target]
        return targets or [NO_EVENT_TARGET]

    def _usage_count(self, candidate, event, target):
        limit = self._limit(candidate)
        if limit["scope"] in {"until_triggered", "next_battle_start"}:
            return int(not candidate.skill.is_component_active(
                candidate.component_id
            ))
        marker = id(target) if target != NO_EVENT_TARGET else NO_EVENT_TARGET
        if not limit.get("per_target", True):
            marker = "__all_targets__"
        if limit["scope"] == "event":
            key = (event.event_id, *candidate.key, marker)
            return int(key in self._event_uses)
        if limit["scope"] == "global_turn":
            key = (event.global_turn, *candidate.key, marker)
            return self._turn_uses.get(key, 0)
        raise ValueError(
            "触发次数scope必须是event、global_turn、until_triggered"
            "或next_battle_start"
        )

    def _record_usage(self, candidate, event, targets):
        limit = self._limit(candidate)
        for target in targets or [NO_EVENT_TARGET]:
            marker = id(target) if target != NO_EVENT_TARGET else NO_EVENT_TARGET
            if not limit.get("per_target", True):
                marker = "__all_targets__"
            if limit["scope"] == "event":
                self._event_uses.add((event.event_id, *candidate.key, marker))
            elif limit["scope"] == "global_turn":
                key = (event.global_turn, *candidate.key, marker)
                self._turn_uses[key] = self._turn_uses.get(key, 0) + 1
            if candidate.kind == "trigger" and candidate.component.get(
                "limit",
                {},
            ).get("per_chain", True):
                self._chain_uses.add((
                    event.chain_id,
                    event.event_type,
                    *candidate.key,
                    marker,
                ))

    def _can_pay(self, candidate):
        from game.skill.input_runtime import is_input_expression
        from game.skill.skill_runtime import _available_resource, _resolved_cost

        totals = {}
        for cost in candidate.component.get("cost", []):
            # 可变输入要到反应真正发动、玩家给出数值后才能结算。
            if is_input_expression(cost.get("value")):
                continue
            value = _resolved_cost(candidate.owner, cost, candidate.skill)
            resource = cost["resource"]
            totals[resource] = totals.get(resource, 0) + value
        return all(
            _available_resource(candidate.owner, resource) is not None
            and _available_resource(candidate.owner, resource) >= required
            for resource, required in totals.items()
        )

    def _candidate_usable(self, candidate, event):
        from game.skill.input_runtime import component_input_reasons
        from game.skill.skill_runtime import character_owns_skill
        from game.skill.component_runtime import component_runtime_reasons

        if event.payload.get("survival_resolved"):
            return False
        if candidate.skill.source_type == "status":
            key = (event.global_turn, *candidate.skill.quota_key(candidate.owner, candidate.component))
            if key in self._status_uses:
                return False
        if component_runtime_reasons(candidate.owner, candidate.skill, candidate.component,
                                     turn_number=event.global_turn, battle=event.battle):
            return False

        # Candidate discovery is a snapshot. A skill removed by an earlier
        # reaction in the same queue must not execute from that stale snapshot.
        if not character_owns_skill(candidate.owner, candidate.skill):
            return False
        if not candidate.skill.is_component_active(candidate.component_id):
            return False
        if candidate.key in self._lifecycle_reservations:
            return False
        lifecycle_scope = self._limit(candidate)["scope"]
        if lifecycle_scope == "next_battle_start" and event.actor is not candidate.owner:
            return False
        if (event.event_id, *candidate.key) in self._event_uses:
            return False
        if not self._event_condition_matches(candidate, event):
            return False
        if component_input_reasons(
            candidate.component,
            candidate.owner,
            {"event": event, "event_value": event.value},
        ):
            return False
        selector = candidate.component.get("target", "self")
        if selector in {
            "event_actor", "event_source", "event_target", "event_targets",
        } and not self._effect_targets(candidate, event):
            return False
        targets = self._usage_targets(candidate, event)
        chain_limit = candidate.component.get("limit", {})
        if candidate.kind == "trigger" and chain_limit.get("per_chain", True):
            per_target = self._limit(candidate).get("per_target", True)
            if all(
                (
                    event.chain_id,
                    event.event_type,
                    *candidate.key,
                    (
                        id(target)
                        if per_target and target != NO_EVENT_TARGET
                        else "__all_targets__"
                        if not per_target
                        else NO_EVENT_TARGET
                    ),
                ) in self._chain_uses
                for target in targets
            ):
                return False
        maximum = self._limit(candidate).get("maximum", 1)
        if not isinstance(maximum, int) or maximum < 1:
            raise ValueError("触发次数maximum必须是正整数")
        if all(
            self._usage_count(candidate, event, target) >= maximum
            for target in targets
        ):
            return False
        return self._can_pay(candidate)

    def _execute(self, candidate, event, decision_provider):
        from game.skill.input_runtime import (
            collect_skill_inputs,
            resolve_input_expressions,
        )
        from game.skill.skill_runtime import (
            SKILL_MUTATION_EFFECT_TYPES,
            _SKILL_APPLICATION_SEQUENCE,
            _pay_component_costs,
            apply_skill_effect,
            select_skill_choices,
        )

        lifecycle_scope = self._limit(candidate)["scope"]
        one_shot = lifecycle_scope in {
            "until_triggered", "next_battle_start",
        }
        if one_shot:
            self._lifecycle_reservations.add(candidate.key)
        usage_targets = [
            target
            for target in self._usage_targets(candidate, event)
            if self._usage_count(candidate, event, target)
            < self._limit(candidate)["maximum"]
        ]
        # Reserve usage before executing effects.  Nested events are emitted
        # synchronously, so recording afterward would allow a trigger to
        # re-enter itself before the recursion guard existed.
        try:
            if candidate.skill.source_type == "status":
                self._status_uses.add((event.global_turn, *candidate.skill.quota_key(candidate.owner, candidate.component)))
            self._event_uses.add((event.event_id, *candidate.key))
            self._record_usage(candidate, event, usage_targets)
            targets = self._effect_targets(candidate, event)
            if candidate.component.get("target") == "event_targets":
                targets = [target for target in targets if target in usage_targets]
            if not targets:
                targets = [candidate.owner]
            selected = select_skill_choices(
                candidate.component,
                candidate.owner,
                targets[0] if targets else candidate.owner,
                decision_provider=decision_provider,
                phase=f"触发：{event.event_type}",
                event=event,
            )
            input_context = {
                "event": event,
                "event_value": event.value,
                "phase": f"反应：{event.event_type}",
            }
            resolved_inputs = collect_skill_inputs(
                candidate.component,
                candidate.owner,
                decision_provider=decision_provider,
                context=input_context,
            )
            costs = resolve_input_expressions(
                list(candidate.component.get("cost", [])),
                resolved_inputs,
            )
            for option in selected:
                costs.extend(resolve_input_expressions(
                    option.get("cost", []),
                    resolved_inputs,
                ))
            paid = _pay_component_costs(candidate.owner, costs, candidate.skill)
            effects = resolve_input_expressions(
                list(candidate.component.get("effects", [])),
                resolved_inputs,
            )
            for option in selected:
                effects.extend(resolve_input_expressions(
                    option.get("effects", []),
                    resolved_inputs,
                ))
            skill_mutation_batches = {}
            for target in targets or [candidate.owner]:
                batch = [
                    effect for effect in effects
                    if effect.get("effect_type") in SKILL_MUTATION_EFFECT_TYPES
                ]
                if batch:
                    skill_mutation_batches[target] = batch
            skill_mutation_state = {}
            application_id = next(_SKILL_APPLICATION_SEQUENCE)
            results = []
            for target in targets or [candidate.owner]:
                for effect in effects:
                    if candidate.skill.source_type == "status" and not candidate.skill.status_modifier.applied:
                        break
                    results.append(apply_skill_effect(
                        effect,
                        target,
                        candidate.skill,
                        actor=(candidate.skill.status_modifier.source_actor or candidate.owner
                               if candidate.skill.source_type == "status" else candidate.owner),
                        decision_provider=decision_provider,
                        turn_number=event.global_turn,
                        phase=event.event_type,
                        game_event=event,
                        event=event,
                        paid_costs=paid,
                        actual_mp_cost=paid.get("mp", 0),
                        skill_application_id=application_id,
                        skill_component_id=candidate.component_id,
                        skill_mutation_batches=skill_mutation_batches,
                        skill_mutation_state=skill_mutation_state,
                    ))
            component_expired = (
                candidate.skill.expire_component(candidate.component_id)
                if one_shot else False
            )
            from game.skill.component_runtime import record_component_use
            record_component_use(candidate.owner, candidate.skill, candidate.component,
                                 turn_number=event.global_turn, battle=event.battle)
            record = {
                "kind": candidate.kind,
                "owner": candidate.owner,
                "skill": candidate.skill,
                "component": candidate.component,
                "targets": targets,
                "paid_costs": paid,
                "input_values": resolved_inputs,
                "results": results,
                "component_expired": component_expired,
            }
            event.records.append(record)
            from game.game.rule_report import report_skill_use, report_status_use
            if candidate.skill.source_type == "status":
                report_status_use(candidate.owner, candidate.skill, candidate.component, targets, phase=event.event_type)
            else:
                report_skill_use(candidate.owner, candidate.skill, candidate.component, targets,
                                 paid=paid, inputs=resolved_inputs, phase=event.event_type)
            return record
        finally:
            if one_shot:
                self._lifecycle_reservations.discard(candidate.key)

    def _resolve_react_tier(self, candidates, event, decision_provider):
        if not candidates or decision_provider is None:
            return []
        actors = []
        for candidate in candidates:
            if candidate.owner not in actors:
                actors.append(candidate.owner)
        records = []
        while True:
            reacted = False
            for actor in actors:
                available = [
                    candidate
                    for candidate in candidates
                    if candidate.owner is actor
                    and self._candidate_usable(candidate, event)
                ]
                if not available:
                    continue
                choice = decision_provider.choose(DecisionRequest(
                    character=actor,
                    phase=f"反应：{event.event_type}",
                    prompt="请选择一个反应；所有人连续放弃后事件继续结算。",
                    options=tuple(
                        DecisionOption(
                            candidate.label,
                            candidate,
                            (candidate.component_id,),
                        )
                        for candidate in available
                    ) + (
                        DecisionOption(
                            "不发动反应",
                            None,
                            ("pass", "skip", "不发动"),
                        ),
                    ),
                ))
                if choice is None:
                    continue
                records.append(self._execute(choice, event, decision_provider))
                reacted = True
            if not reacted:
                return records
