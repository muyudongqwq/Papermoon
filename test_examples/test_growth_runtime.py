import unittest

from game.character.masters import Master
from game.skill.effect_validation import validate_effect_definition


def make_master(name="Grower"):
    return Master(name, 3, 3, 3, 3, 3, "C", 3)


def modifier_effect(modifier_id, value):
    return {
        "modifier_id": modifier_id,
        "effect_type": "numeric_attribute_bonus",
        "polarity": "buff",
        "stacking": {
            "stack_group": modifier_id,
            "stack_scope": "same_source",
            "stacking_rule": "refresh",
        },
        "effect_data": {
            "effect_target": "dice_bonus",
            "value": value,
        },
    }


def gain_mark(value=1):
    return {
        "effect_type": "gain_resource",
        "effect_data": {"resource_id": "marks", "value": value},
    }


def growth_effect(value, stages, operation="add"):
    return {
        "effect_type": "growing",
        "effect_data": {
            "growth_id": "evolution",
            "operation": operation,
            "value": value,
            "minimum": 0,
            "stages": stages,
        },
    }


def make_growth_skill(actor, effects):
    return actor.create_personal_skill({
        "skill_id": "growth_source",
        "name": "成长源",
        "rank": "C",
        "components": [{
            "component_id": "advance",
            "type": "active",
            "target": "self",
            "effects": effects,
        }],
    })


class GrowthRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.actor = make_master()
        self.actor.add_resource({
            "resource_id": "marks",
            "name": "标记",
            "initial_value": 0,
        })

    def test_crosses_every_stage_in_threshold_order(self):
        stages = [
            {"stage_id": "five", "threshold": 5},
            {"stage_id": "three", "threshold": 3},
            {"stage_id": "seven", "threshold": 7},
        ]
        make_growth_skill(self.actor, [growth_effect(8, stages)])

        result = self.actor.resolve_skill_component(
            "growth_source", "advance"
        )["results"][0]

        self.assertEqual(result["new_value"], 8)
        self.assertEqual(
            [item["stage_id"] for item in result["transitions"]],
            ["three", "five", "seven"],
        )

    def test_while_active_effect_is_removed_and_reapplied(self):
        stages = [{
            "stage_id": "power",
            "threshold": 2,
            "while_active_effects": [modifier_effect("growth_power", 4)],
        }]
        skill = make_growth_skill(self.actor, [growth_effect(2, stages)])
        self.actor.resolve_skill_component(skill.skill_id, "advance")
        self.assertEqual(self.actor.dice_bonus, 4)

        skill.definitions[0]["effects"] = [growth_effect(2, stages, "subtract")]
        self.actor.resolve_skill_component(skill.skill_id, "advance")
        self.assertEqual(self.actor.dice_bonus, 0)

        skill.definitions[0]["effects"] = [growth_effect(2, stages)]
        self.actor.resolve_skill_component(skill.skill_id, "advance")
        self.assertEqual(self.actor.dice_bonus, 4)

    def test_first_only_and_each_entry_are_distinct(self):
        first_stage = [{
            "stage_id": "first",
            "threshold": 1,
            "entry_policy": "first_only",
            "enter_effects": [gain_mark()],
        }]
        skill = make_growth_skill(self.actor, [growth_effect(1, first_stage)])
        self.actor.resolve_skill_component(skill.skill_id, "advance")
        skill.definitions[0]["effects"] = [growth_effect(1, first_stage, "subtract")]
        self.actor.resolve_skill_component(skill.skill_id, "advance")
        skill.definitions[0]["effects"] = [growth_effect(1, first_stage)]
        self.actor.resolve_skill_component(skill.skill_id, "advance")
        self.assertEqual(self.actor.get_resource_value("marks"), 1)

        repeat_stage = [{
            "stage_id": "repeat",
            "threshold": 1,
            "entry_policy": "each_entry",
            "enter_effects": [gain_mark()],
        }]
        other = make_master("Repeat")
        other.add_resource({
            "resource_id": "marks", "name": "标记", "initial_value": 0,
        })
        repeated = make_growth_skill(other, [growth_effect(1, repeat_stage)])
        other.resolve_skill_component(repeated.skill_id, "advance")
        repeated.definitions[0]["effects"] = [
            growth_effect(1, repeat_stage, "subtract")
        ]
        other.resolve_skill_component(repeated.skill_id, "advance")
        repeated.definitions[0]["effects"] = [growth_effect(1, repeat_stage)]
        other.resolve_skill_component(repeated.skill_id, "advance")
        self.assertEqual(other.get_resource_value("marks"), 2)

    def test_runtime_unavailable_effect_is_skipped_but_later_effect_runs(self):
        occupied = {
            "skill_id": "occupied",
            "name": "已有技能",
            "rank": "C",
            "components": [{
                "component_id": "noop",
                "type": "active",
                "target": "self",
                "effects": [gain_mark(0)],
            }],
        }
        self.actor.create_personal_skill(occupied)
        stages = [{
            "stage_id": "conflict",
            "threshold": 1,
            "enter_effects": [
                {
                    "effect_type": "add_skill",
                    "effect_data": {"skill_definition": occupied},
                },
                gain_mark(),
            ],
        }]
        skill = make_growth_skill(self.actor, [growth_effect(1, stages)])

        result = self.actor.resolve_skill_component(
            skill.skill_id, "advance"
        )["results"][0]

        records = result["transitions"][0]["enter_effects"]
        self.assertEqual(records[0]["status"], "skipped")
        self.assertEqual(records[1]["status"], "resolved")
        self.assertEqual(self.actor.get_resource_value("marks"), 1)

    def test_removing_source_clears_state_and_active_effects(self):
        stages = [{
            "stage_id": "power",
            "threshold": 1,
            "while_active_effects": [modifier_effect("temporary_growth", 3)],
        }]
        source = make_growth_skill(self.actor, [growth_effect(1, stages)])
        self.actor.resolve_skill_component(source.skill_id, "advance")
        self.assertTrue(self.actor.growth_states)
        self.assertEqual(self.actor.dice_bonus, 3)
        self.actor.create_personal_skill({
            "skill_id": "remove_growth",
            "name": "消除成长",
            "rank": "C",
            "components": [{
                "component_id": "remove",
                "type": "active",
                "target": "self",
                "effects": [{
                    "effect_type": "remove_skill",
                    "effect_data": {"skill_id": source.skill_id},
                }],
            }],
        })

        self.actor.resolve_skill_component("remove_growth", "remove")

        self.assertFalse(self.actor.growth_states)
        self.assertEqual(self.actor.dice_bonus, 0)

    def test_stage_bound_skill_is_removed_when_stage_exits(self):
        granted = {
            "skill_id": "stage_skill",
            "name": "阶段技能",
            "rank": "C",
            "components": [{
                "component_id": "noop",
                "type": "active",
                "target": "self",
                "effects": [gain_mark(0)],
            }],
        }
        stages = [{
            "stage_id": "grant",
            "threshold": 1,
            "while_active_effects": [{
                "effect_type": "add_skill",
                "effect_data": {"skill_definition": granted},
            }],
        }]
        source = make_growth_skill(self.actor, [growth_effect(1, stages)])
        self.actor.resolve_skill_component(source.skill_id, "advance")
        self.assertTrue(any(
            skill.skill_id == "stage_skill"
            for skill in self.actor.personal_skills
        ))

        source.definitions[0]["effects"] = [
            growth_effect(1, stages, "subtract")
        ]
        self.actor.resolve_skill_component(source.skill_id, "advance")

        self.assertFalse(any(
            skill.skill_id == "stage_skill"
            for skill in self.actor.personal_skills
        ))

    def test_irreversible_effect_is_rejected_from_while_active(self):
        with self.assertRaisesRegex(ValueError, "可自动撤销"):
            validate_effect_definition(growth_effect(1, [{
                "stage_id": "bad",
                "threshold": 1,
                "while_active_effects": [gain_mark()],
            }]))


if __name__ == "__main__":
    unittest.main()
