import unittest

from game.character.servants import Servant
from game.map.map import Location
from game.modifier.modifier import create_modifier
from game.skill.skill_runtime import SkillUnavailableError
from game.turn.battle import BattleManager
from game.turn.decision import ScriptedDecisionProvider


def create_servant(name="Caster"):
    return Servant(name, 3, 3, 3, 5, 3, "Caster", "A")


def dice_effect(modifier_id, value):
    return {
        "modifier_id": modifier_id,
        "name": modifier_id,
        "effect_type": "numeric_attribute_bonus",
        "polarity": "buff" if value >= 0 else "debuff",
        "stacking": {
            "stack_group": modifier_id,
            "stack_scope": "same_source",
            "stacking_rule": "refresh",
        },
        "duration": 3,
        "effect_data": {
            "effect_target": "dice_bonus",
            "value": value,
        },
    }


def damage_modifier_effect(modifier_id, direction, value, **filters):
    effect_data = {
        "direction": direction,
        "calculation": "percentage",
        "value": value,
    }
    effect_data.update(filters)
    return {
        "modifier_id": modifier_id,
        "effect_type": "damage_modifier",
        "stacking": {
            "stack_group": modifier_id,
            "stack_scope": "all_sources",
            "stacking_rule": "replace",
        },
        "effect_data": effect_data,
    }


class PersonalSkillRuntimeTests(unittest.TestCase):
    def test_variable_resource_input_drives_cost_and_effect_value(self):
        actor = create_servant()
        actor.create_personal_skill({
            "skill_id": "variable_barrier",
            "name": "可变防护",
            "rank": "C",
            "components": [{
                "component_id": "active",
                "type": "active",
                "target": "self",
                "inputs": [{
                    "input_id": "x",
                    "input_type": "resource_amount",
                    "resource": "mp",
                    "minimum": 1,
                    "maximum": {
                        "source": "actor_attribute",
                        "attribute": "magic",
                        "multiplier": 10,
                    },
                    "prompt": "请输入防护消耗的MP。",
                }],
                "cost": [{
                    "resource": "mp",
                    "value": {"input_id": "x"},
                }],
                "effects": [{
                    "modifier_id": "variable_barrier",
                    "effect_type": "shield",
                    "effect_data": {
                        "value": {"input_id": "x", "multiplier": 1.5},
                    },
                }],
            }],
        })
        starting_mp = actor.mp

        result = actor.resolve_skill_component(
            "variable_barrier",
            "active",
            input_values={"x": 11},
        )

        self.assertEqual(result["input_values"], {"x": 11})
        self.assertEqual(result["paid_costs"], {"mp": 11})
        self.assertEqual(actor.mp, starting_mp - 11)
        self.assertEqual(actor.shield, 16)

    def test_variable_input_can_be_collected_from_decision_provider(self):
        actor = create_servant()
        actor.create_personal_skill({
            "skill_id": "variable_recovery",
            "name": "可变回复",
            "rank": "C",
            "components": [{
                "component_id": "active",
                "type": "active",
                "target": "self",
                "inputs": [{
                    "input_id": "amount",
                    "input_type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                }],
                "effects": [{
                    "effect_type": "recover_resource",
                    "effect_data": {
                        "resource_id": "hp",
                        "value": {"input_id": "amount"},
                    },
                }],
            }],
        })
        actor.hp -= 20
        provider = ScriptedDecisionProvider(["7"])

        result = actor.resolve_skill_component(
            "variable_recovery",
            "active",
            decision_provider=provider,
        )

        self.assertEqual(result["input_values"], {"amount": 7})
        self.assertEqual(actor.hp, actor.hpmax - 13)
        self.assertEqual(provider.requests[0].minimum, 1)
        self.assertEqual(provider.requests[0].maximum, 20)

    def test_variable_input_is_validated_before_cost_payment(self):
        actor = create_servant()
        actor.create_personal_skill({
            "skill_id": "bounded_input",
            "name": "范围输入",
            "rank": "C",
            "components": [{
                "component_id": "active",
                "type": "active",
                "target": "self",
                "inputs": [{
                    "input_id": "x",
                    "input_type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                }],
                "cost": [{
                    "resource": "mp",
                    "value": {"input_id": "x"},
                }],
                "effects": [dice_effect("bounded_bonus", 1)],
            }],
        })
        starting_mp = actor.mp

        with self.assertRaises(ValueError):
            actor.resolve_skill_component(
                "bounded_input",
                "active",
                input_values={"x": 6},
            )

        self.assertEqual(actor.mp, starting_mp)

    def test_damage_effect_skips_defense_and_uses_damage_pipeline(self):
        actor = create_servant("Caster")
        target = Servant("Target", 3, 10, 3, 3, 3, "Saber", "A")
        actor.add_modifier(create_modifier(
            damage_modifier_effect(
                "skill_damage_up",
                "outgoing",
                0.5,
                skill_ids=["direct_damage_skill"],
            ),
            actor,
        ))
        target.add_modifier(create_modifier(
            damage_modifier_effect(
                "physical_reduction",
                "incoming",
                -0.25,
                damage_types=["physical"],
            ),
            target,
        ))
        target.add_modifier(create_modifier({
            "modifier_id": "barrier",
            "effect_type": "shield",
            "effect_data": {"value": 10},
        }, target))
        actor.create_personal_skill({
            "skill_id": "direct_damage_skill",
            "name": "直接伤害",
            "rank": "C",
            "components": [{
                "component_id": "active",
                "type": "active",
                "target": "selectable_character",
                "effects": [{
                    "effect_type": "damage",
                    "effect_data": {
                        "damage_type": "physical",
                        "value": 40,
                    },
                }],
            }],
        })
        starting_hp = target.hp

        result = actor.resolve_skill_component(
            "direct_damage_skill",
            "active",
            target=target,
        )["results"][0]

        # 40 * (1 + 50% - 25%) = 50，再由护盾吸收10。
        self.assertEqual(result["damage"], 40)
        self.assertEqual(target.hp, starting_hp - 40)
        self.assertEqual(target.pending_attacks, [])
        self.assertEqual(result["event"].shield_absorptions[0][1], 10)

    def test_true_direct_damage_bypasses_incoming_reduction_and_shield(self):
        actor = create_servant("Caster")
        target = Servant("Target", 3, 10, 3, 3, 3, "Saber", "A")
        target.add_modifier(create_modifier(
            damage_modifier_effect(
                "all_reduction",
                "incoming",
                -0.9,
                damage_types=["all"],
            ),
            target,
        ))
        target.add_modifier(create_modifier({
            "modifier_id": "barrier",
            "effect_type": "shield",
            "effect_data": {"value": 100},
        }, target))
        actor.create_personal_skill({
            "skill_id": "true_damage_skill",
            "name": "真实伤害",
            "rank": "C",
            "components": [{
                "component_id": "active",
                "type": "active",
                "target": "selectable_character",
                "effects": [{
                    "effect_type": "damage",
                    "effect_data": {
                        "damage_type": "true_damage",
                        "value": 30,
                    },
                }],
            }],
        })
        starting_hp = target.hp

        result = actor.resolve_skill_component(
            "true_damage_skill",
            "active",
            target=target,
        )["results"][0]

        self.assertEqual(result["damage"], 30)
        self.assertEqual(target.hp, starting_hp - 30)
        self.assertEqual(result["event"].shield_absorptions, [])
        self.assertEqual(target.shield, 100)

    def test_damage_effect_can_read_actor_attribute_as_value(self):
        actor = create_servant("Caster")
        target = Servant("Target", 3, 10, 3, 3, 3, "Saber", "A")
        actor.create_personal_skill({
            "skill_id": "attribute_damage",
            "name": "属性伤害",
            "rank": "C",
            "components": [{
                "component_id": "active",
                "type": "active",
                "target": "selectable_character",
                "effects": [{
                    "effect_type": "damage",
                    "effect_data": {
                        "damage_type": "magic",
                        "value_source": "actor_attribute",
                        "attribute": "magic",
                        "multiplier": 10,
                    },
                }],
            }],
        })
        starting_hp = target.hp

        result = actor.resolve_skill_component(
            "attribute_damage",
            "active",
            target=target,
        )["results"][0]

        self.assertEqual(result["damage"], actor.magic.value * 10)
        self.assertEqual(target.hp, starting_hp - actor.magic.value * 10)

    def test_active_skill_appears_and_executes_in_battle_attack_phase(self):
        actor = Servant("Actor", 3, 3, 10, 5, 10, "Caster", "A")
        target = Servant("Target", 3, 3, 0, 3, 0, "Saber", "A")
        location = Location("Arena")
        actor.position = target.position = location
        actor.create_personal_skill({
            "skill_id": "battle_enhancement",
            "name": "战斗强化",
            "rank": "C",
            "components": [{
                "component_id": "active",
                "type": "active",
                "available_phases": ["attack_phase"],
                "target": "self",
                "cost": [{
                    "resource": "attack_phase_count",
                    "value": 1,
                }],
                "effects": [dice_effect("battle_skill_bonus", 2)],
            }],
        })
        battle = BattleManager([actor, target])
        battle.start_battle()
        provider = ScriptedDecisionProvider(["战斗强化", "stay"])

        self.assertTrue(battle.run_battle_turn(provider))
        self.assertEqual(actor.dice_bonus, 2)
        self.assertEqual(actor.attack_phase_count, 0)
        labels = [
            option.label
            for request in provider.requests
            for option in getattr(request, "options", [])
        ]
        self.assertIn("战斗强化", labels)

    def test_compound_skill_applies_passive_and_keeps_active_component(self):
        actor = create_servant()
        skill = actor.create_personal_skill({
            "skill_id": "compound",
            "name": "复合技能",
            "rank": "C",
            "components": [
                {
                    "component_id": "passive",
                    "type": "passive",
                    "effects": [dice_effect("passive_bonus", 1)],
                },
                {
                    "component_id": "active",
                    "type": "active",
                    "target": "self",
                    "cost": [{"resource": "action_point", "value": 1}],
                    "effects": [dice_effect("active_bonus", 2)],
                },
            ],
        })

        self.assertEqual(actor.dice_bonus, 1)
        self.assertEqual(skill.skill_id, "compound")
        result = actor.resolve_skill_component("compound", "active")
        self.assertEqual(actor.action_point, 1)
        self.assertEqual(actor.dice_bonus, 3)
        self.assertEqual(result["paid_costs"], {"action_point": 1})

    def test_choice_can_finish_after_one_below_configured_maximum(self):
        actor = create_servant()
        actor.create_personal_skill({
            "skill_id": "selectable",
            "name": "可选强化",
            "rank": "B",
            "components": [{
                "component_id": "active",
                "type": "active",
                "target": "self",
                "cost": [{"resource": "mp", "value": 20}],
                "choices": {
                    "maximum_selections": 3,
                    "options": [
                        {
                            "choice_id": "first",
                            "name": "第一效果",
                            "effects": [dice_effect("first", 1)],
                        },
                        {
                            "choice_id": "second",
                            "name": "第二效果",
                            "effects": [dice_effect("second", 2)],
                        },
                        {
                            "choice_id": "third",
                            "name": "第三效果",
                            "effects": [dice_effect("third", 3)],
                        },
                    ],
                },
            }],
        })
        starting_mp = actor.mp
        provider = ScriptedDecisionProvider(["1", "完成"])

        result = actor.resolve_skill_component(
            "selectable",
            "active",
            decision_provider=provider,
        )

        self.assertEqual(
            [choice["choice_id"] for choice in result["selected_choices"]],
            ["first"],
        )
        self.assertEqual(actor.mp, starting_mp - 20)
        self.assertEqual(actor.dice_bonus, 1)
        self.assertEqual(len(provider.requests), 2)

    def test_multiple_choices_use_selection_order_and_pay_base_cost_once(self):
        actor = create_servant()
        actor.create_personal_skill({
            "skill_id": "two_choices",
            "name": "二重选择",
            "rank": "A",
            "components": [{
                "component_id": "active",
                "type": "active",
                "target": "self",
                "cost": [{"resource": "mp", "value": 30}],
                "choices": {
                    "maximum_selections": 2,
                    "options": [
                        {
                            "choice_id": "small",
                            "effects": [dice_effect("small", 1)],
                        },
                        {
                            "choice_id": "large",
                            "effects": [dice_effect("large", 3)],
                        },
                    ],
                },
            }],
        })
        starting_mp = actor.mp

        result = actor.resolve_skill_component(
            "two_choices",
            "active",
            selected_choice_ids=["large", "small"],
        )

        self.assertEqual(
            [choice["choice_id"] for choice in result["selected_choices"]],
            ["large", "small"],
        )
        self.assertEqual(actor.mp, starting_mp - 30)
        self.assertEqual(actor.dice_bonus, 4)

    def test_duplicate_choice_is_rejected_before_cost_payment(self):
        actor = create_servant()
        actor.create_personal_skill({
            "skill_id": "no_repeat",
            "name": "不可重复",
            "rank": "C",
            "components": [{
                "component_id": "active",
                "type": "active",
                "target": "self",
                "cost": [{"resource": "mp", "value": 20}],
                "choices": {
                    "maximum_selections": 2,
                    "options": [{
                        "choice_id": "only",
                        "effects": [dice_effect("only", 1)],
                    }],
                },
            }],
        })
        starting_mp = actor.mp

        with self.assertRaises(ValueError):
            actor.resolve_skill_component(
                "no_repeat",
                "active",
                selected_choice_ids=["only", "only"],
            )
        self.assertEqual(actor.mp, starting_mp)

    def test_all_unusable_choices_prevent_activation_without_cost(self):
        actor = create_servant()
        actor.create_personal_skill({
            "skill_id": "purification",
            "name": "净化选择",
            "rank": "C",
            "components": [{
                "component_id": "active",
                "type": "active",
                "target": "self",
                "cost": [{"resource": "mp", "value": 20}],
                "choices": {
                    "maximum_selections": 2,
                    "options": [{
                        "choice_id": "purify",
                        "effects": [{
                            "effect_type": "purify",
                            "effect_data": {"maximum": 1},
                        }],
                    }],
                },
            }],
        })
        starting_mp = actor.mp

        with self.assertRaises(SkillUnavailableError):
            actor.resolve_skill_component("purification", "active")
        self.assertEqual(actor.mp, starting_mp)

    def test_later_invalid_effect_is_skipped_without_refund_or_rollback(self):
        actor = create_servant()
        debuff_effect = dice_effect("temporary_debuff", -1)
        debuff_effect["purifiable"] = True
        actor.add_modifier(create_modifier(debuff_effect, actor))
        actor.create_personal_skill({
            "skill_id": "purify_then_buff",
            "name": "净化与强化",
            "rank": "A",
            "components": [{
                "component_id": "active",
                "type": "active",
                "target": "self",
                "cost": [{"resource": "mp", "value": 20}],
                "effects": [
                    {
                        "effect_type": "purify",
                        "effect_data": {"maximum": "all"},
                    },
                    {
                        "effect_type": "purify",
                        "effect_data": {"maximum": 1},
                    },
                    dice_effect("final_buff", 3),
                ],
            }],
        })
        starting_mp = actor.mp

        result = actor.resolve_skill_component(
            "purify_then_buff",
            "active",
        )

        self.assertEqual(actor.mp, starting_mp - 20)
        self.assertEqual(actor.dice_bonus, 3)
        self.assertTrue(result["results"][1]["skipped"])


if __name__ == "__main__":
    unittest.main()
