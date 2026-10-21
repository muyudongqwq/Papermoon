"""Stateful threshold progression for the ``growing`` effect."""

from copy import deepcopy


REVERSIBLE_EFFECT_TYPES = {
    "add_skill",
    "summon",
    "create_field",
    "deploy_reality_marble",
}


class GrowthStageSource:
    """Stable source identity for effects that live only while a stage is active."""

    def __init__(self, state, stage):
        original = state.source_skill
        self.growth_state = state
        self.original_skill = original
        self.stage_id = stage["stage_id"]
        self.skill_id = (
            f"{original.skill_id}:growth:{state.growth_id}:{self.stage_id}"
        )
        self.name = f"{original.name}：{self.stage_id}"
        self.rank_name = getattr(original, "rank_name", None)
        self.rank = getattr(original, "rank", None)
        self.source_type = "growth_stage"


def _state_key(source_skill, growth_id):
    return id(source_skill), growth_id


def _normalized_persistent_effect(effect):
    """Force stage-bound created objects to opt into automatic cleanup."""
    result = deepcopy(effect)
    effect_type = result.get("effect_type")
    if effect_type in REVERSIBLE_EFFECT_TYPES:
        result.setdefault("effect_data", {})["remove_with_source"] = True
    return result


def _result_failed(result):
    return bool(
        isinstance(result, dict)
        and (
            result.get("created") is False
            or result.get("success") is False
        )
    )


def _apply_effects(effects, target, source, context, *, persistent=False):
    """Apply a stage list, skipping expected runtime unavailability."""
    from game.skill.skill_runtime import (
        SKILL_MUTATION_EFFECT_TYPES,
        SkillUnavailableError,
        apply_skill_effect,
    )

    prepared = [
        _normalized_persistent_effect(effect) if persistent else deepcopy(effect)
        for effect in effects
    ]
    mutation_batch = [
        effect for effect in prepared
        if effect.get("effect_type") in SKILL_MUTATION_EFFECT_TYPES
    ]
    mutation_batches = {target: mutation_batch} if mutation_batch else {}
    mutation_state = {}
    records = []
    for effect in prepared:
        try:
            effect_context = dict(context)
            effect_context["skill_mutation_batches"] = mutation_batches
            effect_context["skill_mutation_state"] = mutation_state
            result = apply_skill_effect(
                effect,
                target,
                source,
                **effect_context,
            )
        except SkillUnavailableError as error:
            records.append({
                "effect": effect,
                "status": "skipped",
                "reason": str(error),
            })
            continue
        records.append({
            "effect": effect,
            "status": "skipped" if _result_failed(result) else "resolved",
            "result": result,
            "reason": result.get("reason") if _result_failed(result) else None,
        })
    return records


class GrowthState:
    def __init__(self, target, source_skill, definition, *, actor=None):
        self.target = target
        self.source_skill = source_skill
        self.actor = actor or target
        self.growth_id = definition["growth_id"]
        self.value = definition.get("initial_value", 0)
        self.minimum = definition.get("minimum", 0)
        self.maximum = definition.get("maximum")
        self.stages = deepcopy(definition["stages"])
        self._definition_signature = {
            "initial_value": definition.get("initial_value", 0),
            "minimum": self.minimum,
            "maximum": self.maximum,
            "stages": deepcopy(definition["stages"]),
        }
        self.active_stage_ids = set()
        self.entered_stage_ids = set()
        self.stage_sources = {}
        self.history = []
        self._updating = False
        self._pending_updates = []

    def matches_definition(self, definition):
        return self._definition_signature == {
            "initial_value": definition.get("initial_value", 0),
            "minimum": definition.get("minimum", 0),
            "maximum": definition.get("maximum"),
            "stages": definition["stages"],
        }

    def _ordered_stages(self, *, reverse=False):
        indexed = list(enumerate(self.stages))
        indexed.sort(
            key=lambda item: (item[1]["threshold"], item[0]),
            reverse=reverse,
        )
        return [stage for _index, stage in indexed]

    def _cleanup_stage_source(self, stage_source):
        from game.skill.skill_runtime import _cleanup_skill_sources, remove_personal_skill

        removed_skills = []
        for skill in list(self.target.personal_skills):
            if (
                getattr(skill, "granted_by", None) is stage_source
                and getattr(skill, "remove_with_source", False)
            ):
                removed_skills.append(remove_personal_skill(
                    self.target,
                    skill,
                    reason="growth_stage_exited",
                ))
        cleanup = _cleanup_skill_sources(self.target, stage_source)
        cleanup["skills"] = removed_skills
        return cleanup

    def _enter_stage(self, stage, context):
        stage_id = stage["stage_id"]
        source = self.stage_sources.get(stage_id)
        if source is None:
            source = GrowthStageSource(self, stage)
            self.stage_sources[stage_id] = source
        should_trigger = (
            stage.get("entry_policy", "first_only") == "each_entry"
            or stage_id not in self.entered_stage_ids
        )
        # Mark the transition before nested effects because they may emit a
        # synchronous event that advances this same growth state again.
        self.active_stage_ids.add(stage_id)
        self.entered_stage_ids.add(stage_id)
        persistent = _apply_effects(
            stage.get("while_active_effects", []),
            self.target,
            source,
            context,
            persistent=True,
        )
        entered = []
        if should_trigger:
            entered = _apply_effects(
                stage.get("enter_effects", []),
                self.target,
                self.source_skill,
                context,
            )
        record = {
            "transition": "enter",
            "stage_id": stage_id,
            "entry_triggered": should_trigger,
            "while_active_effects": persistent,
            "enter_effects": entered,
        }
        self.history.append(record)
        return record

    def _exit_stage(self, stage, context):
        stage_id = stage["stage_id"]
        self.active_stage_ids.discard(stage_id)
        source = self.stage_sources.get(stage_id)
        cleanup = self._cleanup_stage_source(source) if source is not None else {}
        exited = _apply_effects(
            stage.get("exit_effects", []),
            self.target,
            self.source_skill,
            context,
        )
        record = {
            "transition": "exit",
            "stage_id": stage_id,
            "cleanup": cleanup,
            "exit_effects": exited,
        }
        self.history.append(record)
        return record

    def _perform_update(self, operation, amount, context):
        old_value = self.value
        if operation == "add":
            new_value = old_value + amount
        elif operation == "subtract":
            new_value = old_value - amount
        elif operation == "set":
            new_value = amount
        else:
            raise ValueError(f"未知的成长值操作：{operation}")
        new_value = max(self.minimum, new_value)
        if self.maximum is not None:
            new_value = min(self.maximum, new_value)

        desired = {
            stage["stage_id"]
            for stage in self.stages
            if new_value >= stage["threshold"]
        }
        # Commit progress before nested effects. Those effects may emit events
        # that inspect or advance this same growth state synchronously.
        self.value = new_value
        transitions = []
        for stage in self._ordered_stages(reverse=True):
            if (
                stage["stage_id"] in self.active_stage_ids
                and stage["stage_id"] not in desired
            ):
                transitions.append(self._exit_stage(stage, context))
        for stage in self._ordered_stages():
            if (
                stage["stage_id"] in desired
                and stage["stage_id"] not in self.active_stage_ids
            ):
                transitions.append(self._enter_stage(stage, context))
        return {
            "growth_state": self,
            "growth_id": self.growth_id,
            "old_value": old_value,
            "new_value": new_value,
            "transitions": transitions,
        }

    def update(self, operation, amount, context):
        if self._updating:
            self._pending_updates.append((operation, amount, dict(context)))
            return {
                "growth_state": self,
                "growth_id": self.growth_id,
                "old_value": self.value,
                "new_value": self.value,
                "transitions": [],
                "queued": True,
            }
        self._updating = True
        try:
            result = self._perform_update(operation, amount, context)
        finally:
            self._updating = False
        queued_results = []
        while self._pending_updates:
            queued_operation, queued_amount, queued_context = (
                self._pending_updates.pop(0)
            )
            queued_results.append(self.update(
                queued_operation,
                queued_amount,
                queued_context,
            ))
        result["queued_updates"] = queued_results
        return result

    def remove(self, context=None):
        context = dict(context or {})
        transitions = []
        for stage in self._ordered_stages(reverse=True):
            if stage["stage_id"] in self.active_stage_ids:
                transitions.append(self._exit_stage(stage, context))
        return transitions


def apply_growth_effect(effect, target, source_skill, **context):
    data = effect["effect_data"]
    key = _state_key(source_skill, data["growth_id"])
    state = target.growth_states.get(key)
    if state is None:
        state = GrowthState(
            target,
            source_skill,
            data,
            actor=context.get("actor"),
        )
        target.growth_states[key] = state
    elif not state.matches_definition(data):
        raise ValueError(
            f"成长状态{data['growth_id']}被同一来源以不同阶段定义重复使用"
        )
    runtime_context = dict(context)
    runtime_context.setdefault("actor", state.actor)
    return state.update(data.get("operation", "add"), data["value"], runtime_context)


def remove_growth_states_for_source(owner, source_skill):
    manager = getattr(owner, "game_manager", None)
    targets = [owner]
    if manager is not None:
        for character in (
            list(getattr(manager, "characters", []))
            + list(getattr(manager, "dead_characters", []))
        ):
            if character not in targets:
                targets.append(character)
    removed = []
    for target in targets:
        for key, state in list(getattr(target, "growth_states", {}).items()):
            if state.source_skill is not source_skill:
                continue
            transitions = state.remove({
                "actor": state.actor,
                "phase": "growth_source_removed",
                "turn_number": getattr(target, "current_global_turn", 0),
            })
            del target.growth_states[key]
            removed.append({
                "target": target,
                "state": state,
                "transitions": transitions,
            })
    return removed
