"""角色持续效果的基础生命周期与现有Modifier实现。"""

from game.turn.damage_types import normalize_damage_types
from game.modifier.context import ModifierContext
from game.modifier.dice_targets import dice_targets


class Modifier:
    DEFAULT_DURATION_TIMING = "global_turn_end"
    VALID_POLARITIES = {"buff", "debuff", "neutral"}
    VALID_PHASE_WINDOW_SCOPES = {"formal_battle"}
    VALID_PHASE_WINDOW_PHASES = {
        "turn_start",
        "guard",
        "defense",
        "attack",
        "turn_end",
    }
    PHASE_WINDOW_PHASE_ALIASES = {
        "guard_phase": "guard",
        "defense_phase": "defense",
        "attack_phase": "attack",
    }
    VALID_PHASE_WINDOW_BOUNDARIES = {"phase_end"}
    VALID_PHASE_WINDOW_OWNERS = {"target", "source"}
    CONTEXTUAL_EFFECT_TYPES = {
        "attribute_bonus",
        "attack_bonus",
        "dice_bonus",
        "damage_modifier",
        "cost_modifier",
        "magic_resistance",
        "movement_point_bonus",
        "visibility_bonus",
    }
    VALID_CONSUMPTION_EVENTS = {
        "action_committed",
        "attack_committed",
        "roll_committed",
        "defense_committed",
        "damage_resolved",
        "damage_received",
        "attack_resolved",
    }
    VALID_CONSUMPTION_MODES = {"automatic", "optional"}
    VALID_USE_REFRESH_RULES = {
        "reset",
        "keep_more",
        "extend",
        "unchanged",
    }

    def __init__(
        self,
        effect,
        target,
        source=None,
        source_actor=None,
        source_type=None,
        source_id=None,
        applied_turn=None,
        applied_phase=None,
        application_order=None,
    ):
        self.effect = effect
        self.effect_type = effect["effect_type"]
        self.effect_data = effect.get("effect_data", {})
        self.target = target
        self.conditions = dict(effect.get("conditions", {}))
        self.application_scope = dict(effect.get("application_scope", {}))
        consumption = effect.get(
            "consumption",
            self.effect_data.get("consumption"),
        )
        self.consumption = (
            dict(consumption) if consumption is not None else None
        )
        if self.consumption is None:
            self.consumption_event = None
            self.consumption_mode = None
            self.max_uses = None
            self.remaining_uses = None
            self.remove_when_empty = False
            self.use_refresh_rule = None
        else:
            self.consumption_event = self.consumption["event"]
            self.consumption_mode = self.consumption.get(
                "mode",
                "automatic",
            )
            self.max_uses = self.consumption.get("uses", 1)
            self.remaining_uses = self.max_uses
            self.remove_when_empty = self.consumption.get(
                "remove_when_empty",
                True,
            )
            self.use_refresh_rule = self.consumption.get(
                "use_refresh_rule",
                "reset",
            )
        self._optional_consumption_active = False

        self.source = source
        self.source_actor = source_actor
        self.source_type = (
            source_type
            if source_type is not None
            else effect.get("source_type")
        )
        self.source_id = (
            source_id
            if source_id is not None
            else effect.get("source_id")
        )
        self.applied_turn = applied_turn
        self.applied_phase = applied_phase
        self.application_order = application_order

        self.modifier_id = effect.get(
            "modifier_id",
            self._build_default_modifier_id(),
        )
        self.name = effect.get(
            "name",
            self.effect_data.get("name", self.modifier_id),
        )
        self.duration = effect.get(
            "duration",
            self.effect_data.get("duration"),
        )
        self.duration_timing = effect.get(
            "duration_timing",
            self.effect_data.get(
                "duration_timing",
                self.DEFAULT_DURATION_TIMING,
            ),
        )
        phase_window = effect.get(
            "phase_window",
            self.effect_data.get("phase_window"),
        )
        self.phase_window = (
            dict(phase_window) if phase_window is not None else None
        )
        if self.phase_window is None:
            self.phase_window_scope = None
            self.phase_window_phase = None
            self.phase_window_boundary = None
            self.phase_window_owner = None
            self.phase_window_occurrences = None
            self.phase_window_remaining = None
        else:
            self.phase_window_scope = self.phase_window.get(
                "scope",
                "formal_battle",
            )
            raw_phase = self.phase_window["phase"]
            self.phase_window_phase = self.PHASE_WINDOW_PHASE_ALIASES.get(
                raw_phase,
                raw_phase,
            )
            self.phase_window_boundary = self.phase_window.get(
                "boundary",
                "phase_end",
            )
            self.phase_window_owner = self.phase_window.get(
                "owner",
                "target",
            )
            self.phase_window_occurrences = self.phase_window.get(
                "occurrences",
                1,
            )
            self.phase_window_remaining = self.phase_window_occurrences

        stacking = effect.get("stacking", {})
        self.stack_group = stacking.get(
            "stack_group",
            self.modifier_id,
        )
        self.stack_scope = stacking.get("stack_scope", "same_source")
        self.stacking_rule = stacking.get("stacking_rule", "refresh")
        self.max_stacks = stacking.get("max_stacks", 1)
        self.stack_count = stacking.get("stack_count", 1)
        self.duration_refresh_rule = stacking.get(
            "duration_refresh_rule",
            "reset",
        )
        self.at_max_stacks_rule = stacking.get(
            "at_max_stacks_rule",
            "refresh",
        )
        self.strength_comparison = stacking.get("strength_comparison")
        self.strength_priority = stacking.get(
            "strength_priority",
            effect.get(
                "strength_priority",
                self.effect_data.get("strength_priority"),
            ),
        )
        self.priority = stacking.get("priority", 0)
        self.persist_after_death = effect.get(
            "persist_after_death",
            self.effect_data.get("persist_after_death", False),
        )
        self.polarity = effect.get(
            "polarity",
            self.effect_data.get("polarity", "neutral"),
        )
        purifiable = effect.get(
            "purifiable",
            self.effect_data.get("purifiable"),
        )
        self.purifiable = (
            self.polarity == "debuff"
            if purifiable is None
            else purifiable
        )
        self.buff_skill_id = None
        self.buff_application_id = None
        self.last_duration_update_turn = None
        self.duration_revision = 0
        self.applied = False

        self._validate_definition()

    @property
    def is_contextual(self):
        return bool(
            self.conditions
            or self.application_scope
            or self.consumption_mode == "optional"
        )

    def matches_context(
        self,
        context=None,
        *,
        include_pending_optional=False,
        **defaults,
    ):
        if not self.has_uses:
            return False
        if (
            self.consumption_mode == "optional"
            and not self._optional_consumption_active
            and not include_pending_optional
        ):
            return False
        context = ModifierContext.coerce(context, **defaults)
        def values(name, default=None):
            raw = self.conditions.get(name, default)
            if raw is None:
                return None
            if isinstance(raw, str):
                return {raw}
            return set(raw)

        scopes = self.application_scope.get("phase_scopes", ["all"])
        if isinstance(scopes, str):
            scopes = [scopes]
        if "all" not in scopes and context.phase_scope not in scopes:
            return False

        conditions = self.conditions
        field_rules = {
            "phase_scopes": context.phase_scope,
            "phases": context.phase,
            "action_ids": context.action_id,
            "skill_ids": context.skill_id,
            "component_ids": context.component_id,
            "damage_types": context.damage_type,
        }
        for name, actual in field_rules.items():
            expected = values(name)
            if expected is None:
                continue
            if actual is None or actual not in expected:
                return False
        type_rules = {
            "actor_types": context.actor,
            "target_types": context.target,
        }
        for name, subject in type_rules.items():
            expected = values(name)
            if expected is None:
                continue
            actual = getattr(subject, "entity_type", None)
            if actual is None or actual not in expected:
                return False
        relations = values("target_relations")
        if relations is not None:
            if context.actor is None or context.target is None:
                return False
            if context.actor is context.target:
                relation = "self"
            elif getattr(context.actor, "is_ally", lambda _target: False)(
                context.target
            ):
                relation = "ally"
            else:
                relation = "enemy"
            if relation not in relations:
                return False
        required_tags = values("tags", [])
        if not required_tags.issubset(context.tags):
            return False
        any_tags = values("any_tags", [])
        if any_tags and not any_tags.intersection(context.tags):
            return False
        excluded_tags = values("exclude_tags", [])
        if excluded_tags.intersection(context.tags):
            return False
        return True

    def _build_default_modifier_id(self):
        discriminator = self.effect_data.get(
            "effect_target",
            self.effect_data.get("value"),
        )
        if discriminator is None:
            return self.effect_type
        return f"{self.effect_type}:{discriminator}"

    def _validate_definition(self):
        if self.polarity not in self.VALID_POLARITIES:
            raise ValueError(f"未知的Modifier类型：{self.polarity}")
        if not isinstance(self.purifiable, bool):
            raise TypeError("Modifier的purifiable必须是布尔值")
        if not isinstance(self.conditions, dict):
            raise TypeError("Modifier的conditions必须是字典")
        if not isinstance(self.application_scope, dict):
            raise TypeError("Modifier的application_scope必须是字典")
        if self.is_contextual and self.effect_type not in self.CONTEXTUAL_EFFECT_TYPES:
            raise ValueError(
                f"{self.effect_type}尚不支持条件型Modifier"
            )
        if self.duration is not None and self.duration < 0:
            raise ValueError("Modifier持续时间不能小于0")
        if self.consumption is not None:
            if self.consumption_event not in self.VALID_CONSUMPTION_EVENTS:
                raise ValueError(
                    f"未知的Modifier消耗事件：{self.consumption_event}"
                )
            if self.consumption_mode not in self.VALID_CONSUMPTION_MODES:
                raise ValueError(
                    f"未知的Modifier消耗模式：{self.consumption_mode}"
                )
            if (
                not isinstance(self.max_uses, int)
                or isinstance(self.max_uses, bool)
                or self.max_uses < 1
            ):
                raise ValueError("Modifier的consumption.uses必须是正整数")
            if not isinstance(self.remove_when_empty, bool):
                raise TypeError("remove_when_empty必须是布尔值")
            if self.use_refresh_rule not in self.VALID_USE_REFRESH_RULES:
                raise ValueError(
                    f"未知的use_refresh_rule：{self.use_refresh_rule}"
                )
        if self.phase_window is not None:
            if self.duration is not None:
                raise ValueError(
                    "Modifier不能同时定义duration和phase_window"
                )
            if self.phase_window_scope not in self.VALID_PHASE_WINDOW_SCOPES:
                raise ValueError(
                    f"未知的阶段窗口scope：{self.phase_window_scope}"
                )
            if self.phase_window_phase not in self.VALID_PHASE_WINDOW_PHASES:
                raise ValueError(
                    f"未知的正式战斗阶段：{self.phase_window_phase}"
                )
            if (
                self.phase_window_boundary
                not in self.VALID_PHASE_WINDOW_BOUNDARIES
            ):
                raise ValueError(
                    "阶段窗口目前只支持在phase_end到期"
                )
            if self.phase_window_owner not in self.VALID_PHASE_WINDOW_OWNERS:
                raise ValueError(
                    f"未知的阶段窗口owner：{self.phase_window_owner}"
                )
            if self.phase_window_owner == "source" and self.source is None:
                raise ValueError(
                    "owner为source的阶段窗口必须提供Modifier来源"
                )
            if (
                not isinstance(self.phase_window_occurrences, int)
                or isinstance(self.phase_window_occurrences, bool)
                or self.phase_window_occurrences < 1
            ):
                raise ValueError(
                    "阶段窗口occurrences必须是正整数"
                )
        if not isinstance(self.max_stacks, int) or self.max_stacks < 1:
            raise ValueError("Modifier的max_stacks必须是正整数")
        if not isinstance(self.stack_count, int):
            raise TypeError("Modifier的stack_count必须是整数")
        if not 1 <= self.stack_count <= self.max_stacks:
            raise ValueError("Modifier的stack_count超出允许范围")

    def apply(self):
        if self.applied:
            return False
        self._apply_effect()
        self.applied = True
        return True

    def remove(self):
        if not self.applied:
            return False
        self._remove_effect()
        self.applied = False
        return True

    def _apply_effect(self):
        """由子类实现实际效果。"""

    def _remove_effect(self):
        """由子类实现实际撤销。"""

    def update(self, timing=DEFAULT_DURATION_TIMING, turn_number=None):
        if self.phase_window is not None:
            return False
        is_scheduled_timing = timing == self.duration_timing
        is_battle_turn_substitute = (
            timing == "battle_turn_end"
            and self.duration_timing == self.DEFAULT_DURATION_TIMING
        )
        if (
            self.duration is None
            or not (is_scheduled_timing or is_battle_turn_substitute)
        ):
            return False
        if (
            turn_number is not None
            and self.last_duration_update_turn == turn_number
        ):
            return False
        self.duration -= 1
        self.last_duration_update_turn = turn_number
        return self.duration <= 0

    @property
    def is_battle_phase_window(self):
        return self.phase_window_scope == "formal_battle"

    @property
    def phase_window_signature(self):
        if self.phase_window is None:
            return None
        return (
            self.phase_window_scope,
            self.phase_window_phase,
            self.phase_window_boundary,
            self.phase_window_owner,
        )

    def update_phase_window(
        self,
        *,
        scope,
        phase,
        boundary,
        phase_actor,
    ):
        """Advance a phase window only at a matching formal phase boundary."""
        if self.phase_window is None:
            return False
        owner = self.target if self.phase_window_owner == "target" else self.source
        if (
            scope != self.phase_window_scope
            or phase != self.phase_window_phase
            or boundary != self.phase_window_boundary
            or phase_actor is not owner
        ):
            return False
        self.phase_window_remaining -= 1
        return self.phase_window_remaining <= 0

    def should_remove(self):
        return False

    @property
    def has_uses(self):
        return self.consumption is None or self.remaining_uses > 0

    def matches_consumption(self, event, context=None):
        return (
            self.applied
            and self.consumption_event == event
            and self.remaining_uses > 0
            and self.matches_context(
                context,
                include_pending_optional=True,
            )
        )

    def consume_use(self, amount=1):
        if self.consumption is None:
            return False
        if (
            not isinstance(amount, int)
            or isinstance(amount, bool)
            or amount < 1
        ):
            raise ValueError("Modifier消耗次数必须是正整数")
        if self.remaining_uses <= 0:
            return False
        self.remaining_uses = max(0, self.remaining_uses - amount)
        return True

    def change_stack_count(self, new_count):
        if not isinstance(new_count, int):
            raise TypeError("Modifier层数必须是整数")
        if not 1 <= new_count <= self.max_stacks:
            raise ValueError("Modifier层数超出允许范围")
        difference = new_count - self.stack_count
        if difference == 0:
            return False
        if self.applied:
            self._change_stack_effect(difference)
        self.stack_count = new_count
        return True

    def _change_stack_effect(self, difference):
        """只有数值型Modifier需要响应层数变化。"""


class BonusModifier(Modifier):
    def __init__(self, effect, target, **kwargs):
        super().__init__(effect, target, **kwargs)
        self.value = self.effect_data["value"]


class AttributeModifier(BonusModifier):
    """修改AttributeRank的持续效果加成，并同步相关派生资源。"""

    def __init__(self, effect, target, **kwargs):
        super().__init__(effect, target, **kwargs)
        self.effect_target = self.effect_data["effect_target"]

    def modify(self, amount):
        if self.applied:
            self.target.adjust_attribute_modifier(
                self.effect_target,
                amount * self.stack_count,
            )
        self.value += amount

    def _apply_effect(self):
        if self.is_contextual:
            return
        self.target.adjust_attribute_modifier(
            self.effect_target,
            self.value * self.stack_count,
        )

    def _remove_effect(self):
        if self.is_contextual:
            return
        self.target.adjust_attribute_modifier(
            self.effect_target,
            -self.value * self.stack_count,
        )

    def _change_stack_effect(self, difference):
        if self.is_contextual:
            return
        self.target.adjust_attribute_modifier(
            self.effect_target,
            self.value * difference,
        )


class AttackModifier(BonusModifier):
    def _apply_effect(self):
        if self.is_contextual:
            return
        self.target.atk_bonus += self.value * self.stack_count

    def _remove_effect(self):
        if self.is_contextual:
            return
        self.target.atk_bonus -= self.value * self.stack_count

    def _change_stack_effect(self, difference):
        if self.is_contextual:
            return
        self.target.atk_bonus += self.value * difference


class DiceModifier(BonusModifier):
    def __init__(self, effect, target, **kwargs):
        super().__init__(effect, target, **kwargs)
        self.effect_target = self.effect_data["effect_target"]

    def _adjust_targets(self, amount):
        for stat in dice_targets(self.effect_target):
            if stat in getattr(self.target, "DERIVED_STAT_NAMES", ()):
                self.target.adjust_derived_modifier(stat, amount)
            else:
                setattr(self.target, stat, getattr(self.target, stat) + amount)

    def _apply_effect(self):
        if self.is_contextual:
            return
        self._adjust_targets(self.value * self.stack_count)

    def _remove_effect(self):
        if self.is_contextual:
            return
        self._adjust_targets(-self.value * self.stack_count)

    def _change_stack_effect(self, difference):
        if self.is_contextual:
            return
        self._adjust_targets(self.value * difference)


class PlusModifier(Modifier):
    """修改属性的加符容量，而不改写角色创建时的固有加符。"""

    def __init__(self, effect, target, **kwargs):
        super().__init__(effect, target, **kwargs)
        self.effect_target = self.effect_data["effect_target"]
        self.value = self.effect_data["value"]
        if not isinstance(self.value, int):
            raise TypeError("加符修正值必须是整数")
        attribute = getattr(self.target, self.effect_target)
        if not hasattr(attribute, "adjust_plus_bonus"):
            raise TypeError("plus_bonus只能作用于具有加符容量的属性")

    def add_plus(self, amount):
        if not isinstance(amount, int):
            raise TypeError("加符修正值必须是整数")
        if self.applied:
            attribute = getattr(self.target, self.effect_target)
            attribute.adjust_plus_bonus(amount * self.stack_count)
        self.value += amount

    def _apply_effect(self):
        attribute = getattr(self.target, self.effect_target)
        attribute.adjust_plus_bonus(self.value * self.stack_count)

    def _remove_effect(self):
        attribute = getattr(self.target, self.effect_target)
        attribute.adjust_plus_bonus(-self.value * self.stack_count)

    def _change_stack_effect(self, difference):
        attribute = getattr(self.target, self.effect_target)
        attribute.adjust_plus_bonus(self.value * difference)


class NumericAttributeModifier(BonusModifier):
    """对角色身上的普通数值字段施加可恢复的临时修正。"""

    def __init__(self, effect, target, **kwargs):
        super().__init__(effect, target, **kwargs)
        self.effect_target = self.effect_data["effect_target"]

    def _apply_effect(self):
        current_value = getattr(self.target, self.effect_target)
        setattr(
            self.target,
            self.effect_target,
            current_value + self.value * self.stack_count,
        )

    def _remove_effect(self):
        current_value = getattr(self.target, self.effect_target)
        setattr(
            self.target,
            self.effect_target,
            current_value - self.value * self.stack_count,
        )

    def _change_stack_effect(self, difference):
        current_value = getattr(self.target, self.effect_target)
        setattr(
            self.target,
            self.effect_target,
            current_value + self.value * difference,
        )


class MagicResistanceModifier(BonusModifier):
    """修改角色受到魔术伤害时使用的对魔力比例。"""

    def _apply_effect(self):
        if self.is_contextual:
            return
        self.target.magic_resistance += self.value * self.stack_count

    def _remove_effect(self):
        if self.is_contextual:
            return
        self.target.magic_resistance -= self.value * self.stack_count

    def _change_stack_effect(self, difference):
        if self.is_contextual:
            return
        self.target.magic_resistance += self.value * difference


class MovementPointModifier(BonusModifier):
    """修改角色每次消耗AP转换得到的移动力。"""

    def _apply_effect(self):
        if self.is_contextual:
            return
        self.target.move_conversion += self.value * self.stack_count

    def _remove_effect(self):
        if self.is_contextual:
            return
        self.target.move_conversion -= self.value * self.stack_count

    def _change_stack_effect(self, difference):
        if self.is_contextual:
            return
        self.target.move_conversion += self.value * difference


class VisibilityModifier(BonusModifier):
    """修改角色常时视野距离。"""

    def _apply_effect(self):
        if self.is_contextual:
            return
        self.target.visibility += self.value * self.stack_count

    def _remove_effect(self):
        if self.is_contextual:
            return
        self.target.visibility -= self.value * self.stack_count

    def _change_stack_effect(self, difference):
        if self.is_contextual:
            return
        self.target.visibility += self.value * difference


class DamageModifier(Modifier):
    """在伤害管线中按条件提供百分比或固定值修正。"""

    VALID_DIRECTIONS = {"outgoing", "incoming"}
    VALID_CALCULATIONS = {"percentage", "flat"}

    def __init__(self, effect, target, **kwargs):
        super().__init__(effect, target, **kwargs)
        self.direction = self.effect_data["direction"]
        self.calculation = self.effect_data["calculation"]
        self.value = self.effect_data["value"]
        self.damage_types = normalize_damage_types(
            self.effect_data.get("damage_types", ["all"])
        )
        self.action_ids = set(self.effect_data.get("action_ids", []))
        self.skill_ids = set(self.effect_data.get("skill_ids", []))
        self.source_tags = set(self.effect_data.get("source_tags", []))
        if self.direction not in self.VALID_DIRECTIONS:
            raise ValueError(f"未知的伤害修正方向：{self.direction}")
        if self.calculation not in self.VALID_CALCULATIONS:
            raise ValueError(f"未知的伤害修正计算类型：{self.calculation}")

    def matches(
        self,
        direction,
        damage_type,
        action_id=None,
        skill_id=None,
        source_tags=None,
        context=None,
    ):
        if not self.applied or self.direction != direction:
            return False
        if "all" not in self.damage_types and damage_type not in self.damage_types:
            return False
        if self.action_ids and action_id not in self.action_ids:
            return False
        if self.skill_ids and skill_id not in self.skill_ids:
            return False
        if self.source_tags and not self.source_tags.intersection(source_tags or []):
            return False
        if not self.matches_context(
            context,
            action_id=action_id,
            skill_id=skill_id,
            damage_type=damage_type,
            tags=set(source_tags or []),
        ):
            return False
        return True

    @property
    def total_value(self):
        return self.value * self.stack_count


class CostModifier(Modifier):
    """按资源与消耗来源修改一次费用。"""

    VALID_CALCULATIONS = {"multiplier", "flat", "override"}

    def __init__(self, effect, target, **kwargs):
        super().__init__(effect, target, **kwargs)
        self.resource = self.effect_data["resource"]
        self.cost_id = self.effect_data.get("cost_id")
        self.calculation = self.effect_data["calculation"]
        self.value = self.effect_data["value"]
        if self.calculation not in self.VALID_CALCULATIONS:
            raise ValueError(f"未知的费用修正计算类型：{self.calculation}")
        if not isinstance(self.value, (int, float)) or isinstance(
            self.value,
            bool,
        ):
            raise TypeError("费用修正值必须是数值")

    def matches_cost(self, resource, cost_id=None, context=None):
        return (
            self.applied
            and self.resource == resource
            and (self.cost_id is None or self.cost_id == cost_id)
            and self.matches_context(context, action_id=cost_id)
        )

    @property
    def total_value(self):
        return self.value * self.stack_count


class ShieldModifier(Modifier):
    """保存独立护盾池；相同modifier_id默认互相替换。"""

    def __init__(self, effect, target, **kwargs):
        super().__init__(effect, target, **kwargs)
        stacking = effect.get("stacking", {})
        if "stack_scope" not in stacking:
            self.stack_scope = "all_sources"
        if "stacking_rule" not in stacking:
            self.stacking_rule = "replace"
        self.value = self.effect_data["value"]
        if self.value < 0:
            raise ValueError("护盾值不能小于0")
        self.remaining_value = 0
        self.damage_types = normalize_damage_types(
            self.effect_data.get("damage_types", ["physical", "magic"])
        )
        self.name = effect.get(
            "name",
            self.effect_data.get("name", self.modifier_id),
        )

    def can_absorb(self, damage_event):
        return (
            self.applied
            and self.remaining_value > 0
            and (
                "all" in self.damage_types
                or damage_event.damage_type in self.damage_types
            )
        )

    def absorb(self, damage, damage_event):
        if damage <= 0 or not self.can_absorb(damage_event):
            return 0
        absorbed = min(damage, self.remaining_value)
        self.remaining_value -= absorbed
        self.target.shield -= absorbed
        return absorbed

    def _apply_effect(self):
        self.remaining_value = self.value * self.stack_count
        self.target.shield += self.remaining_value

    def _remove_effect(self):
        self.target.shield -= self.remaining_value
        self.remaining_value = 0

    def _change_stack_effect(self, difference):
        added_capacity = self.value * difference
        self.remaining_value += added_capacity
        self.target.shield += added_capacity


class StatusModifier(Modifier):
    def __init__(self, effect, target, **kwargs):
        super().__init__(effect, target, **kwargs)
        self.status = self.effect_data["status_id"]
        self.value = self.status
        from game.status.registry import get_status_definition
        from game.status.runtime import StatusRuntime
        self.status_runtime = StatusRuntime(self, get_status_definition(self.status))

    def _apply_effect(self):
        register = getattr(self.target, "_register_status_source", None)
        if register is None:
            self.target.status_flags.add(self.status)
        else:
            register(self.status, self)
        try:
            self.status_runtime.apply_passives()
        except Exception:
            self.target._unregister_status_source(self.status, self)
            raise

    def _remove_effect(self):
        self.status_runtime.remove_passives()
        unregister = getattr(self.target, "_unregister_status_source", None)
        if unregister is None:
            self.target.status_flags.discard(self.status)
        else:
            unregister(self.status, self)

    def _change_stack_effect(self, difference):
        self.status_runtime.change_stacks(difference)

    def update(self, timing=Modifier.DEFAULT_DURATION_TIMING, turn_number=None):
        if timing != "global_turn_end":
            return False
        return super().update(timing, turn_number)


class HiddenModifier(StatusModifier):
    def __init__(self, effect, target, **kwargs):
        # Hidden has its own specialized lifecycle; it is not a catalog status.
        Modifier.__init__(self, effect, target, **kwargs)
        self.status = self.effect_data["value"]
        self.value = self.status
        self.hidden_position = target.position
        self.remove_on_position_change = self.effect_data.get(
            "remove_on_position_change",
            True,
        )
        self.remove_on_battle_entry = self.effect_data.get(
            "remove_on_battle_entry",
            True,
        )
        self.requires_building = self.effect_data.get(
            "requires_building",
            True,
        )
        self.withdraw_from_battle = self.effect_data.get(
            "withdraw_from_battle",
            False,
        )
        self.rejoin_on_expire = self.effect_data.get(
            "rejoin_on_expire",
            self.withdraw_from_battle,
        )
        self.prevent_movement = self.effect_data.get("prevent_movement", False)
        self.revealed_to = set()
        self.withdrawn_battle = None
        self.withdrawn_position = None

    def _apply_effect(self):
        self.target._register_status_source(self.status, self)
        if self.prevent_movement:
            self.target._register_status_source("cannot_move", self)
        if not self.withdraw_from_battle:
            return
        battle = getattr(self.target, "current_battle", None)
        if battle is None or getattr(battle, "ended", False):
            return
        self.withdrawn_battle = battle
        self.withdrawn_position = self.target.position
        battle.remove_participant(
            self.target,
            preserve_target_locked_attacks=True,
        )

    def _remove_effect(self):
        self.target._unregister_status_source(self.status, self)
        if self.prevent_movement:
            self.target._unregister_status_source("cannot_move", self)
        battle = self.withdrawn_battle
        if (
            not self.rejoin_on_expire
            or battle is None
            or getattr(battle, "ended", False)
            or not self.target.is_alive()
            or self.target.in_battle
            or self.target.position is not self.withdrawn_position
        ):
            return
        battle.add_participant(self.target)
        battle.queue_late_participant(self.target)

    def update(self, timing=Modifier.DEFAULT_DURATION_TIMING, turn_number=None):
        return Modifier.update(self, timing, turn_number)

    def _change_stack_effect(self, difference):
        pass

    def conceals_from(self, observer):
        return observer is not self.target and observer not in self.revealed_to

    def reveal_to(self, observer):
        if observer is None or observer is self.target:
            return False
        before = len(self.revealed_to)
        self.revealed_to.add(observer)
        return len(self.revealed_to) != before

    def should_remove(self):
        if not self.remove_on_position_change:
            return False
        if self.target.position is not self.hidden_position:
            return True
        return bool(
            self.requires_building
            and (
                self.target.position is None
                or not self.target.position.is_building
            )
        )


class PresenceConcealmentModifier(BonusModifier):
    """Observer-relative concealment supplied by the Assassin class skill."""

    VALID_RANKS = {"C", "B", "A", "EX"}

    def __init__(self, effect, target, **kwargs):
        super().__init__(effect, target, **kwargs)
        self.rank = str(self.effect_data["rank"]).upper()
        if self.rank not in self.VALID_RANKS:
            raise ValueError(f"未知的气息遮断Rank：{self.rank}")
        self.investigation_immunity = bool(
            self.effect_data.get("investigation_immunity", False)
        )
        self.active_hide_perception_immunity = bool(
            self.effect_data.get("active_hide_perception_immunity", False)
        )
        self.remove_when_revealed = bool(
            self.effect_data.get("remove_when_revealed", False)
        )

    def _apply_effect(self):
        self.target.adjust_derived_modifier(
            "hide",
            self.value * self.stack_count,
        )

    def _remove_effect(self):
        self.target.adjust_derived_modifier(
            "hide",
            -self.value * self.stack_count,
        )

    def _change_stack_effect(self, difference):
        self.target.adjust_derived_modifier("hide", self.value * difference)


class CarryCapacityModifier(BonusModifier):
    """How many passengers the target may carry as one ride unit."""

    def __init__(self, effect, target, **kwargs):
        super().__init__(effect, target, **kwargs)
        if (
            not isinstance(self.value, int)
            or isinstance(self.value, bool)
            or self.value < 0
        ):
            raise ValueError("携带容量必须是非负整数")

    def _apply_effect(self):
        self.target.carry_capacity += self.value * self.stack_count
        self.target._register_status_source("carriable", self)

    def _remove_effect(self):
        self.target.carry_capacity = max(
            0,
            self.target.carry_capacity - self.value * self.stack_count,
        )
        self.target._unregister_status_source("carriable", self)

    def _change_stack_effect(self, difference):
        self.target.carry_capacity = max(
            0,
            self.target.carry_capacity + self.value * difference,
        )


class HPFloorModifier(BonusModifier):
    def update(self, timing=Modifier.DEFAULT_DURATION_TIMING, turn_number=None):
        if timing == "battle_turn_end":
            return False
        return super().update(timing, turn_number)


class WeaknessModifier(StatusModifier):
    def _remove_effect(self):
        super()._remove_effect()
        if not self.target.has_status(self.status):
            refresh = getattr(
                self.target,
                "refresh_brink_of_death_availability",
                None,
            )
            if refresh is not None:
                refresh()


MODIFIER_TYPES = {
    "attribute_bonus": AttributeModifier,
    "attack_bonus": AttackModifier,
    "dice_bonus": DiceModifier,
    "plus_bonus": PlusModifier,
    "numeric_attribute_bonus": NumericAttributeModifier,
    "magic_resistance": MagicResistanceModifier,
    "movement_point_bonus": MovementPointModifier,
    "visibility_bonus": VisibilityModifier,
    "damage_modifier": DamageModifier,
    "cost_modifier": CostModifier,
    "shield": ShieldModifier,
    "hidden": HiddenModifier,
    "presence_concealment": PresenceConcealmentModifier,
    "carry_capacity": CarryCapacityModifier,
    "hp_floor": HPFloorModifier,
}


def create_modifier(effect, target, **kwargs):
    effect_type = effect["effect_type"]
    if effect_type == "add_status":
        from copy import deepcopy
        from game.status.registry import get_status_definition, validate_status_definition
        from game.skill.effect_validation import validate_effect_definition
        validate_effect_definition(effect)
        definition = get_status_definition(effect["effect_data"]["status_id"])
        validate_status_definition(definition)
        defaults = {key: deepcopy(value) for key, value in definition.items()
                    if key not in {"status_id", "description", "components"}}
        defaults.setdefault("modifier_id", definition["status_id"])
        defaults.update(deepcopy(effect))
        effect = defaults
        modifier_class = (
            WeaknessModifier
            if effect["effect_data"]["status_id"] == "weakness"
            else StatusModifier
        )
    else:
        modifier_class = MODIFIER_TYPES.get(effect_type)

    if modifier_class is None:
        raise ValueError(f"未知的Modifier效果类型：{effect_type}")
    return modifier_class(effect, target, **kwargs)
