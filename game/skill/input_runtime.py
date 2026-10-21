"""主动技能的可变整数输入、数值表达式和UI无关收集入口。"""

from copy import deepcopy
from numbers import Real


INPUT_TYPES = frozenset({"integer", "resource_amount"})
INPUT_EXPRESSION_FIELDS = frozenset({
    "input_id", "multiplier", "flat", "minimum", "maximum",
})
BOUND_SOURCE_TYPES = frozenset({
    "constant", "actor_attribute", "resource_current",
    "resource_maximum", "resource_missing", "context",
})
BOUND_EXPRESSION_FIELDS = frozenset({
    "source", "value", "attribute", "resource", "key",
    "multiplier", "flat", "minimum", "maximum",
})
INPUT_DEFINITION_FIELDS = frozenset({
    "input_id", "input_type", "prompt", "minimum", "maximum", "resource",
})


def is_input_expression(value):
    return (
        isinstance(value, dict)
        and "input_id" in value
        and set(value) <= INPUT_EXPRESSION_FIELDS
    )


def validate_input_expression(value, *, path="input_expression"):
    if not is_input_expression(value):
        raise TypeError(f"{path}必须是input数值表达式")
    input_id = value["input_id"]
    if not isinstance(input_id, str) or not input_id.strip():
        raise TypeError(f"{path}.input_id必须是非空字符串")
    for field in ("multiplier", "flat", "minimum", "maximum"):
        if field in value and (
            isinstance(value[field], bool) or not isinstance(value[field], Real)
        ):
            raise TypeError(f"{path}.{field}必须是数字")
    if (
        "minimum" in value and "maximum" in value
        and value["minimum"] > value["maximum"]
    ):
        raise ValueError(f"{path}.minimum不能大于maximum")
    return True


def _validate_bound(value, *, path):
    if isinstance(value, bool):
        raise TypeError(f"{path}必须是整数或边界表达式")
    if isinstance(value, int):
        return True
    if not isinstance(value, dict):
        raise TypeError(f"{path}必须是整数或边界表达式")
    unknown = set(value) - BOUND_EXPRESSION_FIELDS
    if unknown:
        raise ValueError(f"{path}包含未知字段：{sorted(unknown)}")
    source = value.get("source")
    if source not in BOUND_SOURCE_TYPES:
        raise ValueError(f"{path}.source未知：{source}")
    required = {
        "constant": "value",
        "actor_attribute": "attribute",
        "resource_current": "resource",
        "resource_maximum": "resource",
        "resource_missing": "resource",
        "context": "key",
    }[source]
    if required not in value:
        raise ValueError(f"{path}缺少字段：{required}")
    if source == "constant":
        if isinstance(value["value"], bool) or not isinstance(value["value"], Real):
            raise TypeError(f"{path}.value必须是数字")
    elif not isinstance(value[required], str) or not value[required].strip():
        raise TypeError(f"{path}.{required}必须是非空字符串")
    for field in ("multiplier", "flat", "minimum", "maximum"):
        if field in value and (
            isinstance(value[field], bool) or not isinstance(value[field], Real)
        ):
            raise TypeError(f"{path}.{field}必须是数字")
    return True


def validate_input_definitions(inputs, *, path="inputs"):
    if not isinstance(inputs, list):
        raise TypeError(f"{path}必须是列表")
    input_ids = []
    for index, definition in enumerate(inputs):
        item_path = f"{path}[{index}]"
        if not isinstance(definition, dict):
            raise TypeError(f"{item_path}必须是字典")
        unknown = set(definition) - INPUT_DEFINITION_FIELDS
        if unknown:
            raise ValueError(f"{item_path}包含未知字段：{sorted(unknown)}")
        input_id = definition.get("input_id")
        if not isinstance(input_id, str) or not input_id.strip():
            raise TypeError(f"{item_path}.input_id必须是非空字符串")
        input_ids.append(input_id)
        input_type = definition.get("input_type")
        if input_type not in INPUT_TYPES:
            raise ValueError(f"{item_path}.input_type未知：{input_type}")
        if "prompt" in definition and not isinstance(definition["prompt"], str):
            raise TypeError(f"{item_path}.prompt必须是字符串")
        if input_type == "integer" and "maximum" not in definition:
            raise ValueError(f"{item_path}的integer输入必须声明maximum")
        if input_type == "resource_amount" and not isinstance(
            definition.get("resource"), str,
        ):
            raise ValueError(f"{item_path}的resource_amount必须声明resource")
        for field in ("minimum", "maximum"):
            if field in definition:
                _validate_bound(definition[field], path=f"{item_path}.{field}")
    if len(input_ids) != len(set(input_ids)):
        raise ValueError(f"{path}中的input_id不能重复")
    return True


def _iter_input_references(value):
    if is_input_expression(value):
        yield value["input_id"]
        return
    if isinstance(value, dict):
        for child in value.values():
            yield from _iter_input_references(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _iter_input_references(child)


def validate_component_inputs(component, *, path="component"):
    inputs = component.get("inputs", [])
    validate_input_definitions(inputs, path=f"{path}.inputs")
    if inputs and component.get("type") not in {"active", "react"}:
        raise ValueError(f"{path}.inputs只能用于active或react组件")
    declared = {definition["input_id"] for definition in inputs}
    references = set()
    for field in ("cost", "effects", "choices"):
        references.update(_iter_input_references(component.get(field)))
    unknown = references - declared
    if unknown:
        raise ValueError(f"{path}引用了未声明的input_id：{sorted(unknown)}")
    return True


def _numeric_value(value):
    value = getattr(value, "value", value)
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError("输入边界来源必须得到数字")
    return value


def _available_resource(actor, resource):
    if resource == "mp" and hasattr(actor, "get_available_mp"):
        return actor.get_available_mp()
    if resource == "hp":
        return actor.hp
    if getattr(actor, "has_resource", lambda _resource: False)(resource):
        return actor.get_available_resource(resource)
    value = getattr(actor, resource, None)
    if value is None:
        raise ValueError(f"未知的角色资源：{resource}")
    return value


def resolve_bound(expression, actor, context=None):
    context = context or {}
    if isinstance(expression, int) and not isinstance(expression, bool):
        return expression
    _validate_bound(expression, path="input_bound")
    source = expression["source"]
    if source == "constant":
        value = expression["value"]
    elif source == "actor_attribute":
        attribute = expression["attribute"]
        if not hasattr(actor, attribute):
            raise ValueError(f"角色不存在输入边界属性：{attribute}")
        value = getattr(actor, attribute)
    elif source == "resource_current":
        value = _available_resource(actor, expression["resource"])
    elif source == "resource_maximum":
        value = actor.get_resource_maximum(expression["resource"])
    elif source == "resource_missing":
        resource = expression["resource"]
        maximum = actor.get_resource_maximum(resource)
        current = _available_resource(actor, resource)
        if maximum is None:
            raise ValueError(f"资源{resource}没有maximum")
        value = maximum - current
    else:
        key = expression["key"]
        if key not in context:
            raise ValueError(f"输入边界缺少上下文：{key}")
        value = context[key]
    value = _numeric_value(value)
    value = value * expression.get("multiplier", 1) + expression.get("flat", 0)
    if "minimum" in expression:
        value = max(value, expression["minimum"])
    if "maximum" in expression:
        value = min(value, expression["maximum"])
    return int(value)


def get_input_bounds(definition, actor, context=None):
    context = context or {}
    minimum = resolve_bound(definition.get("minimum", 0), actor, context)
    maximum = (
        resolve_bound(definition["maximum"], actor, context)
        if "maximum" in definition else None
    )
    if definition["input_type"] == "resource_amount":
        resource = definition["resource"]
        available = _available_resource(actor, resource)
        maximum = available if maximum is None else min(maximum, available)
    if maximum is None:
        raise ValueError(f"输入{definition['input_id']}缺少maximum")
    return int(minimum), int(maximum)


def component_input_reasons(component, actor, context=None):
    reasons = []
    for definition in component.get("inputs", []):
        try:
            minimum, maximum = get_input_bounds(definition, actor, context)
        except (TypeError, ValueError):
            reasons.append(f"input_bound_unavailable:{definition['input_id']}")
            continue
        if maximum < minimum:
            reasons.append(f"input_range_empty:{definition['input_id']}")
    return reasons


def collect_skill_inputs(
    component,
    actor,
    *,
    decision_provider=None,
    input_values=None,
    context=None,
):
    from game.turn.decision import NumericDecisionRequest, TerminalDecisionProvider

    context = context or {}
    definitions = component.get("inputs", [])
    provided = dict(input_values or {})
    declared = {definition["input_id"] for definition in definitions}
    unknown = set(provided) - declared
    if unknown:
        raise ValueError(f"提供了未知的input_id：{sorted(unknown)}")
    if decision_provider is None and len(provided) < len(definitions):
        decision_provider = TerminalDecisionProvider()
    resolved = {}
    for definition in definitions:
        input_id = definition["input_id"]
        minimum, maximum = get_input_bounds(definition, actor, context)
        if maximum < minimum:
            raise ValueError(f"输入{input_id}没有合法取值")
        if input_id in provided:
            value = provided[input_id]
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"输入{input_id}必须是整数")
            if not minimum <= value <= maximum:
                raise ValueError(f"输入{input_id}必须位于{minimum}至{maximum}之间")
        else:
            value = decision_provider.choose(NumericDecisionRequest(
                character=actor,
                phase=context.get("phase", "技能输入"),
                prompt=definition.get("prompt", f"请输入{input_id}。"),
                minimum=minimum,
                maximum=maximum,
            ))
        resolved[input_id] = value
    return resolved


def resolve_input_expression(expression, input_values):
    validate_input_expression(expression)
    input_id = expression["input_id"]
    if input_id not in input_values:
        raise ValueError(f"缺少技能输入：{input_id}")
    value = _numeric_value(input_values[input_id])
    value = value * expression.get("multiplier", 1) + expression.get("flat", 0)
    if "minimum" in expression:
        value = max(value, expression["minimum"])
    if "maximum" in expression:
        value = min(value, expression["maximum"])
    return int(value)


def resolve_input_expressions(value, input_values):
    if is_input_expression(value):
        return resolve_input_expression(value, input_values)
    if isinstance(value, dict):
        return {
            key: resolve_input_expressions(child, input_values)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [resolve_input_expressions(child, input_values) for child in value]
    if isinstance(value, tuple):
        return tuple(resolve_input_expressions(child, input_values) for child in value)
    return deepcopy(value)
