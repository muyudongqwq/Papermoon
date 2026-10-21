"""HP、MP以外的角色资源及其统一读写入口。"""

from copy import deepcopy
from dataclasses import dataclass, field


VALID_RESOURCE_OPERATIONS = {
    "add",
    "subtract",
    "multiply",
    "divide",
    "set",
}


def _number(value, field_name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name}必须是数字")
    return int(value)


def _condition_matches(condition, context):
    """匹配资源获得条件；未提供条件时视为满足。"""
    if not condition:
        return True
    if not isinstance(condition, dict):
        raise TypeError("资源获得条件必须是字典")

    comparisons = (
        ("_at_least", lambda actual, expected: actual >= expected),
        ("_at_most", lambda actual, expected: actual <= expected),
        ("_greater_than", lambda actual, expected: actual > expected),
        ("_less_than", lambda actual, expected: actual < expected),
        ("_not", lambda actual, expected: actual != expected),
    )
    for condition_name, expected in condition.items():
        context_name = condition_name
        comparator = lambda actual, target: actual == target
        for suffix, candidate in comparisons:
            if condition_name.endswith(suffix):
                context_name = condition_name[:-len(suffix)]
                comparator = candidate
                break
        if context_name not in context:
            return False
        try:
            if not comparator(context[context_name], expected):
                return False
        except TypeError:
            return False
    return True


@dataclass
class CharacterResource:
    resource_id: str
    name: str
    initial_value: int = 0
    minimum: int = 0
    maximum: int | None = None
    gain_rules: list = field(default_factory=list)
    source: object = None
    source_type: str | None = None
    source_id: str | None = None
    reset: dict | None = None
    current_value: int = field(init=False)

    def __post_init__(self):
        if not isinstance(self.resource_id, str) or not self.resource_id.strip():
            raise ValueError("resource_id必须是非空字符串")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("资源name必须是非空字符串")
        self.initial_value = _number(self.initial_value, "initial_value")
        self.minimum = _number(self.minimum, "minimum")
        if self.maximum is not None:
            self.maximum = _number(self.maximum, "maximum")
            if self.maximum < self.minimum:
                raise ValueError("资源maximum不能小于minimum")
        if not isinstance(self.gain_rules, list):
            raise TypeError("gain_rules必须是列表")
        for rule in self.gain_rules:
            self._validate_gain_rule(rule)
        if self.reset is not None:
            if not isinstance(self.reset, dict) or not self.reset.get("timing"):
                raise ValueError("资源reset必须提供timing")
        self.current_value = self.clamp(self.initial_value)

    @staticmethod
    def _validate_gain_rule(rule):
        if not isinstance(rule, dict):
            raise TypeError("每条资源获得规则必须是字典")
        if not rule.get("trigger_event"):
            raise ValueError("资源获得规则必须提供trigger_event")
        operation = rule.get("operation", "add")
        if operation not in VALID_RESOURCE_OPERATIONS:
            raise ValueError(f"未知的资源运算：{operation}")
        if "value" not in rule and "value_source" not in rule:
            raise ValueError("资源获得规则必须提供value或value_source")
        if "value" in rule:
            _number(rule["value"], "gain_rule.value")

    @property
    def source_key(self):
        return self.source_type, self.source_id

    def clamp(self, value):
        value = int(value)
        value = max(self.minimum, value)
        if self.maximum is not None:
            value = min(self.maximum, value)
        return value

    def apply(self, operation, value):
        if operation not in VALID_RESOURCE_OPERATIONS:
            raise ValueError(f"未知的资源运算：{operation}")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("资源变化值必须是数字")
        if operation == "add":
            result = self.current_value + value
        elif operation == "subtract":
            result = self.current_value - value
        elif operation == "multiply":
            result = self.current_value * value
        elif operation == "divide":
            if value == 0:
                raise ZeroDivisionError("资源变化不能除以0")
            result = self.current_value / value
        else:
            result = value
        old_value = self.current_value
        # int()与现有全局规则一致：正负数都直接截去小数部分。
        result = max(self.minimum, int(result))
        # GM可以强制给予超过maximum的资源。之后的减少应从实际数量
        # 正常扣除，而不能在第一次消费时突然被截回maximum。
        preserves_existing_overcap = (
            self.maximum is not None
            and old_value > self.maximum
            and result <= old_value
        )
        if self.maximum is not None and not preserves_existing_overcap:
            result = min(self.maximum, result)
        self.current_value = result
        return self.current_value - old_value

    def reset_for(self, timing):
        if self.reset is None or self.reset.get("timing") != timing:
            return False
        value = self.reset.get("value", "initial_value")
        if value == "initial_value":
            value = self.initial_value
        old_value = self.current_value
        self.current_value = self.clamp(_number(value, "reset.value"))
        return self.current_value - old_value

    def definition_signature(self):
        return {
            "resource_id": self.resource_id,
            "name": self.name,
            "initial_value": self.initial_value,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "gain_rules": deepcopy(self.gain_rules),
            "reset": deepcopy(self.reset),
        }


class ResourceManager:
    def __init__(self, owner):
        self.owner = owner
        self.resources = {}

    def _emit_change(
        self,
        event_type,
        resource,
        old_value,
        *,
        operation,
        requested_value,
        reason=None,
    ):
        change = resource.current_value - old_value
        if change == 0:
            return None
        game_manager = getattr(self.owner, "game_manager", None)
        event_manager = getattr(game_manager, "event_manager", None)
        if event_manager is None:
            return None
        payload = {
            "resource_id": resource.resource_id,
            "old_value": old_value,
            "new_value": resource.current_value,
            "change": change,
            "operation": operation,
            "requested_value": requested_value,
            "reason": reason,
        }
        event_manager.emit(
            "resource_changed",
            actor=self.owner,
            source=resource,
            target=self.owner,
            value=change,
            phase=getattr(
                getattr(self.owner, "current_battle", None),
                "current_phase",
                None,
            ),
            battle=getattr(self.owner, "current_battle", None),
            position=getattr(self.owner, "position", None),
            payload=payload,
        )
        if event_type is None:
            return None
        return event_manager.emit(
            event_type,
            actor=self.owner,
            source=resource,
            target=self.owner,
            value=change,
            phase=getattr(
                getattr(self.owner, "current_battle", None),
                "current_phase",
                None,
            ),
            battle=getattr(self.owner, "current_battle", None),
            position=getattr(self.owner, "position", None),
            payload=payload,
        )

    def add(self, definition, *, source=None, source_type=None, source_id=None):
        if not isinstance(definition, dict):
            raise TypeError("资源定义必须是字典")
        resource = CharacterResource(
            resource_id=definition.get("resource_id"),
            name=definition.get("name", definition.get("resource_id")),
            initial_value=definition.get("initial_value", 0),
            minimum=definition.get("minimum", 0),
            maximum=definition.get("maximum"),
            gain_rules=deepcopy(definition.get("gain_rules", [])),
            source=source,
            source_type=source_type,
            source_id=source_id,
            reset=deepcopy(definition.get("reset")),
        )
        existing = self.resources.get(resource.resource_id)
        if existing is None:
            self.resources[resource.resource_id] = resource
            return resource
        if (
            existing.source_key == resource.source_key
            and existing.definition_signature() == resource.definition_signature()
        ):
            # 被动技能重复装载时保留当前资源数量。
            return existing
        raise ValueError(
            f"资源{resource.resource_id}已经由其他定义或来源建立"
        )

    def has(self, resource_id):
        return resource_id in self.resources

    def get(self, resource_id):
        try:
            return self.resources[resource_id]
        except KeyError as error:
            raise ValueError(f"未知的角色资源：{resource_id}") from error

    def value(self, resource_id):
        return self.get(resource_id).current_value

    def available(self, resource_id):
        resource = self.get(resource_id)
        return resource.current_value - resource.minimum

    def modify(self, resource_id, operation, value):
        resource = self.get(resource_id)
        old_value = resource.current_value
        change = resource.apply(operation, value)
        self._emit_change(
            None,
            resource,
            old_value,
            operation=operation,
            requested_value=value,
            reason="modify",
        )
        return change

    def gain(self, resource_id, value):
        resource = self.get(resource_id)
        old_value = resource.current_value
        change = resource.apply("add", value)
        self._emit_change(
            "resource_gained",
            resource,
            old_value,
            operation="add",
            requested_value=value,
            reason="gain",
        )
        return change

    def recover(self, resource_id, amount):
        resource = self.get(resource_id)
        if resource.maximum is None:
            raise ValueError(
                f"没有maximum的资源{resource_id}不能使用recover_resource"
            )
        amount = _number(amount, "资源回复量")
        if amount < 0:
            raise ValueError("资源回复量不能小于0")
        old_value = resource.current_value
        change = resource.apply("add", amount)
        self._emit_change(
            "resource_recovered",
            resource,
            old_value,
            operation="add",
            requested_value=amount,
            reason="recover",
        )
        return change

    def can_pay(self, resource_id, amount):
        amount = _number(amount, "资源消耗")
        if amount < 0:
            raise ValueError("资源消耗不能小于0")
        return self.available(resource_id) >= amount

    def pay(self, resource_id, amount):
        amount = _number(amount, "资源消耗")
        if not self.can_pay(resource_id, amount):
            return False
        resource = self.get(resource_id)
        old_value = resource.current_value
        resource.apply("subtract", amount)
        self._emit_change(
            "resource_paid",
            resource,
            old_value,
            operation="subtract",
            requested_value=amount,
            reason="pay",
        )
        return True

    def trigger(self, event_name, **context):
        if getattr(self.owner, "has_status", lambda _name: False)("dead"):
            return []
        results = []
        for resource in self.resources.values():
            for index, rule in enumerate(resource.gain_rules):
                if rule["trigger_event"] != event_name:
                    continue
                if not _condition_matches(rule.get("condition"), context):
                    continue
                if "value_source" in rule:
                    source_name = rule["value_source"]
                    if source_name not in context:
                        continue
                    value = context[source_name]
                else:
                    value = rule["value"]
                operation = rule.get("operation", "add")
                old_value = resource.current_value
                change = resource.apply(operation, value)
                self._emit_change(
                    "resource_gained",
                    resource,
                    old_value,
                    operation=operation,
                    requested_value=value,
                    reason=f"trigger:{event_name}",
                )
                results.append({
                    "resource_id": resource.resource_id,
                    "rule_index": index,
                    "operation": rule.get("operation", "add"),
                    "value": value,
                    "change": change,
                    "current_value": resource.current_value,
                })
        return results

    def reset(self, timing):
        results = {}
        for resource_id, resource in self.resources.items():
            old_value = resource.current_value
            result = resource.reset_for(timing)
            if result is not False:
                results[resource_id] = result
                self._emit_change(
                    "resource_reset",
                    resource,
                    old_value,
                    operation="set",
                    requested_value=resource.current_value,
                    reason=timing,
                )
        return results
