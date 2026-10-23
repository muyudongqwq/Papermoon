"""Canonical cost entries and the shared pricing/payment pipeline."""

from copy import deepcopy
from math import isfinite

COST_TIMINGS = {"activation", "casting_start", "maintenance"}
NOBLE_PHANTASM_MP_COSTS = {"C": 30, "B": 40, "A": 50}


def default_noble_costs(rank, range_type):
    if rank not in NOBLE_PHANTASM_MP_COSTS:
        raise ValueError("此宝具Rank没有默认消耗，请明确填写cost")
    return [{"resource": "mp", "value": NOBLE_PHANTASM_MP_COSTS[rank]
             * (2 if range_type == "anti_fortress" else 1), "timing": "casting_start"}]


class SkillUnavailableError(ValueError):
    """An action cannot pay its costs or satisfy its current requirements."""


class PaidCosts(dict):
    def __init__(self, *args, ledgers=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.ledgers = dict(ledgers or {})
        self.refunded_resources = set()


def costs_at(costs, timing="activation"):
    return [deepcopy(cost) for cost in costs if cost.get("timing", "activation") == timing]


def component_activation_costs(skill, component, *, prepaid=False):
    costs = costs_at(component.get("cost", []))
    if not prepaid:
        for cost in costs_at(component.get("cost", []), "casting_start"):
            cost.setdefault("cost_id", f"casting:{skill.skill_id}")
            costs.append(cost)
    return costs


def validate_costs(costs, *, path="cost", timings=("activation",), inputs=True):
    from game.skill.input_runtime import is_input_expression, validate_input_expression
    if not isinstance(costs, list):
        raise ValueError(f"{path}必须是消耗列表")
    for index, cost in enumerate(costs):
        where = f"{path}[{index}]"
        if not isinstance(cost, dict) or set(cost) - {"resource", "value", "cost_id", "timing"}:
            raise ValueError(f"{where}只允许resource、value、cost_id、timing")
        if not isinstance(cost.get("resource"), str) or not cost["resource"].strip():
            raise ValueError(f"{where}.resource必须是非空资源ID")
        timing = cost.get("timing", "activation")
        if timing not in timings:
            raise ValueError(f"{where}.timing只能使用：{', '.join(timings)}")
        if timing == "casting_start" and cost["resource"] != "mp":
            raise ValueError(f"{where}咏唱预付只支持MP，其他行动资源在发动时支付")
        value = cost.get("value")
        if inputs and timing != "casting_start" and is_input_expression(value):
            validate_input_expression(value, path=f"{where}.value")
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
            raise ValueError(f"{where}.value必须是非负有限数值")
        if "cost_id" in cost and (not isinstance(cost["cost_id"], str) or not cost["cost_id"].strip()):
            raise ValueError(f"{where}.cost_id必须是非空字符串")


def available_resource(actor, resource):
    if resource == "mp" and hasattr(actor, "get_available_mp"):
        return actor.get_available_mp()
    if getattr(actor, "has_resource", lambda _resource: False)(resource):
        return actor.get_available_resource(resource)
    return getattr(actor, resource, None)


def resolved_cost(actor, cost, default_cost_id=None):
    return actor.modifier_manager.calculate_cost(cost.get("value", 0), resource=cost["resource"],
                                                 cost_id=cost.get("cost_id", default_cost_id))


def cost_totals(actor, costs, default_cost_id=None):
    totals = {}
    for cost in costs:
        resource = cost["resource"]
        totals[resource] = totals.get(resource, 0) + resolved_cost(actor, cost, default_cost_id)
    return totals


def pay_costs(actor, costs, default_cost_id=None):
    totals = cost_totals(actor, costs, default_cost_id)
    for resource, required in totals.items():
        available = available_resource(actor, resource)
        if available is None:
            raise ValueError(f"未知的消耗资源：{resource}")
        if available < required:
            raise SkillUnavailableError(f"{resource}不足")
    ledgers = {}
    for resource, required in totals.items():
        if resource == "mp":
            ledger = actor.pay_mp_with_ledger(required)
            if ledger is None:
                raise SkillUnavailableError("mp不足")
            ledgers["mp"] = ledger
        elif getattr(actor, "has_resource", lambda _resource: False)(resource):
            if not actor.pay_resource(resource, required):
                raise SkillUnavailableError(f"{resource}不足")
        else:
            setattr(actor, resource, getattr(actor, resource) - required)
    return PaidCosts(totals, ledgers=ledgers)
