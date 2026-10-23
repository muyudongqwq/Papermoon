"""Payment timing, canonical data and unchanged ledger/refund behavior."""
from copy import deepcopy
import unittest

from game.character.masters import Master
from game.character.servants import Servant
from game.modifier.modifier import create_modifier
from game.resource.costs import costs_at, pay_costs, validate_costs, SkillUnavailableError
from game.skill.casting import CastingState, get_casting_mp_cost
from game.skill.skill_runtime import resolve_skill_component, validate_personal_skill_definition


def entry(value, timing="activation", **extra):
    return {"resource": "mp", "value": value, "timing": timing, **extra}


def definition(cost=None, *, choices=None):
    component = {"component_id": "unit", "type": "active", "target": "self", "casting_requirement": 1,
                 "cost": cost or [], "effects": [{"effect_type": "attack_bonus", "effect_data": {"value": 1}}]}
    if choices:
        component["choices"] = choices
    return {"skill_id": "unified", "name": "Unified", "rank": "C",
            "casting": {"activation_mode": "release"}, "components": [component]}


class UnifiedCostTests(unittest.TestCase):
    def setUp(self):
        self.actor = Master("Actor", 3, 3, 3, 3, 3, "C", 3)

    def test_prepaid_cost_is_paid_once_and_activation_and_selected_branches_are_additive(self):
        data = definition([entry(20, "casting_start"), entry(3)], choices={"options": [
            {"choice_id": "x", "cost": [entry(4)], "effects": [{"effect_type": "attack_bonus", "effect_data": {"value": 2}}]}]})
        data["components"][0]["cost"].append(entry(5))
        skill = self.actor.create_personal_skill(data)
        mp = self.actor.mp
        state = CastingState.start(self.actor, skill, 1)
        self.assertEqual(self.actor.mp, mp - 20)
        state.advance_at_global_turn_end(1)
        state.continue_for_turn(2)
        self.assertEqual(self.actor.mp, mp - 20)
        result = resolve_skill_component(self.actor, skill, "unit", selected_choice_ids=["x"], casting_prepaid=True, casting_release=True)
        self.assertEqual(result["paid_costs"]["mp"], 12)
        self.assertEqual(self.actor.mp, mp - 32)
        state.finish_release()
        self.assertEqual(state.interrupt(), [])

    def test_unpaid_direct_activation_also_pays_start_cost_exactly_once(self):
        data = definition([entry(20, "casting_start"), entry(3)])
        data["components"][0]["casting_requirement"] = 0
        skill = self.actor.create_personal_skill(data)
        mp = self.actor.mp
        result = resolve_skill_component(self.actor, skill, "unit", casting_release=True)
        self.assertEqual(result["paid_costs"]["mp"], 23)
        self.assertEqual(self.actor.mp, mp - 23)

    def test_multiple_start_cost_ids_receive_modifiers_once_before_pool_payment(self):
        skill = self.actor.create_personal_skill(definition([
            entry(10, "casting_start", cost_id="first"), entry(20, "casting_start", cost_id="second")]))
        self.actor.add_modifier(create_modifier({"effect_type": "cost_modifier", "effect_data": {
            "resource": "mp", "cost_id": "first", "calculation": "flat", "value": -5}}, self.actor))
        self.assertEqual(get_casting_mp_cost(self.actor, skill), 25)
        mp = self.actor.mp
        state = CastingState.start(self.actor, skill, 1)
        self.assertEqual(self.actor.mp, mp - 25)
        state.interrupt()
        self.assertEqual(self.actor.mp, mp)

    def test_refund_restores_original_servant_master_and_temporary_pools(self):
        servant = Servant("Servant", 3, 3, 3, 3, 3, "Saber", "A")
        servant.set_master(self.actor)
        servant.mp, servant.temporary_mp = 5, 7
        self.actor.mp = 50
        skill = servant.create_personal_skill(definition([entry(30, "casting_start")]))
        state = CastingState.start(servant, skill, 1)
        self.assertEqual((servant.temporary_mp, servant.mp, self.actor.mp), (0, 0, 32))
        state.interrupt()
        self.assertEqual((servant.temporary_mp, servant.mp, self.actor.mp), (7, 5, 50))
        state.interrupt()
        self.assertEqual((servant.temporary_mp, servant.mp, self.actor.mp), (7, 5, 50))

    def test_refund_is_capped_for_ordinary_mp_and_does_not_restore_action_resources(self):
        skill = self.actor.create_personal_skill(definition([entry(10, "casting_start")]))
        state = CastingState.start(self.actor, skill, 1)
        self.actor.mp = self.actor.mpmax - 2
        self.actor.action_point = 0
        refunds = state.interrupt()
        self.assertEqual(sum(item["refunded"] for item in refunds), 2)
        self.assertEqual(self.actor.action_point, 0)

    def test_insufficient_combined_resources_fail_before_payment(self):
        mp = self.actor.mp
        with self.assertRaises(SkillUnavailableError):
            pay_costs(self.actor, [entry(5), {"resource": "action_point", "value": 999}])
        self.assertEqual(self.actor.mp, mp)

    def test_cost_shape_and_context_are_validated_strictly(self):
        for cost in ([entry(-1)], [entry(True)], [entry(float("nan"))], [entry(1, "unknown")],
                     [{"resource": "hp", "value": 1, "timing": "casting_start"}],
                     [{"resource": "mp", "value": 1, "refund": True}]):
            with self.subTest(cost=cost), self.assertRaises(ValueError):
                validate_costs(cost, timings=("activation", "casting_start"))
        valid = definition([entry(1, "casting_start")])
        for where in ("root", "casting", "choice"):
            data = deepcopy(valid)
            if where == "root": data["mp_cost"] = 10
            elif where == "casting": data["casting"]["mp_cost"] = 10
            else: data["components"][0]["choices"] = {"options": [{"choice_id": "x", "additional_cost": []}]}
            with self.subTest(where=where), self.assertRaises(ValueError):
                validate_personal_skill_definition(data)

    def test_builtin_noble_costs_are_explicit_final_amounts(self):
        from game.skill.content_data import NOBLE_PHANTASM_DATA
        self.assertEqual(costs_at(NOBLE_PHANTASM_DATA["servant_test_0:laus_saint_claudius"]["components"][0]["cost"], "casting_start")[0]["value"], 100)
        self.assertEqual(costs_at(NOBLE_PHANTASM_DATA["servant_test_0:golden_theatre"]["components"][0]["cost"], "casting_start")[0]["value"], 40)

    def test_unit_activation_cost_is_paid_for_automatic_triggers(self):
        from game.game.game_manager import GameManager
        from game.map.map import Location
        data = definition([entry(4)])
        data["components"][0].update(type="trigger", trigger={"event_type": "cost_test"})
        data["components"][0].pop("casting_requirement")
        data.pop("casting")
        self.actor.create_personal_skill(data)
        location = Location("A")
        self.actor.position = location
        game = GameManager([self.actor], location)
        game.start_game()
        mp = self.actor.mp
        game.event_manager.emit("cost_test", target=self.actor)
        self.assertEqual(self.actor.mp, mp - 4)
