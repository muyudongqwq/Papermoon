import unittest

from game.action.action_list import ActionContext, ActionListBuilder
from game.action.action_resolver import ActionResolver
from game.character.masters import Master
from game.skill.effect_validation import validate_effect_definition
from game.skill.skill_action import SkillAction
from game.skill.skill_runtime import SkillUnavailableError


def make_master(name="Actor"):
    return Master(name, 3, 3, 3, 3, 3, "C", 3)


def dynamic_definition(action_id="focus", name="集中"):
    return {
        "action_id": action_id,
        "name": name,
        "available_phases": ["AP1", "AP2"],
        "resolution_timing": "immediate",
        "target": "self",
        "target_rules": {},
        "condition": {"actor_alive": True, "battle_state": False},
        "cost": [{"resource": "action_point", "value": 1}],
        "effects": [{
            "effect_type": "recover_resource",
            "effect_data": {"resource_id": "hp", "value": 5},
        }],
        "display_order": 25,
    }


def add_action_effect(definition=None, **data):
    payload = {"action_definition": definition or dynamic_definition()}
    payload.update(data)
    return {"effect_type": "add_action", "effect_data": payload}


def source_skill(actor, effects, skill_id="action_source"):
    return actor.create_personal_skill({
        "skill_id": skill_id,
        "name": skill_id,
        "rank": "C",
        "components": [{
            "component_id": "grant",
            "type": "active",
            "target": "self",
            "effects": effects,
        }],
    })


class AddActionEffectTests(unittest.TestCase):
    def setUp(self):
        self.actor = make_master()

    def grant(self, **data):
        skill = source_skill(self.actor, [add_action_effect(**data)])
        result = self.actor.resolve_skill_component(
            skill.skill_id, "grant", turn_number=1
        )
        return skill, result

    def test_granted_action_appears_and_executes_through_normal_pipeline(self):
        _source, _result = self.grant()
        self.actor.hp -= 10
        entries = ActionListBuilder().get_available_actions(ActionContext(
            actor=self.actor,
            phase="AP1",
            turn_number=1,
            characters=[self.actor],
        ))
        entry = next(item for item in entries if item.action_id == "focus")
        self.assertEqual(entry.name, "集中")
        starting_ap = self.actor.action_point

        action = SkillAction(
            self.actor,
            entry.skill,
            entry.skill_component,
            target=self.actor,
        )
        resolved = ActionResolver().resolve(action)

        self.assertTrue(resolved)
        self.assertEqual(self.actor.hp, self.actor.hpmax - 5)
        self.assertEqual(self.actor.action_point, starting_ap - 1)
        self.assertEqual(action.action_id, "focus")

    def test_duration_counts_full_global_turns(self):
        self.grant(duration=1)
        self.actor.update_modifiers("global_turn_end", turn_number=1)
        self.assertEqual(len(self.actor.dynamic_actions), 1)

        self.actor.update_modifiers("global_turn_end", turn_number=2)
        self.assertEqual(self.actor.dynamic_actions, [])
        self.assertEqual(self.actor.dynamic_action_skills, [])

    def test_duplicate_id_rejects_but_names_may_repeat(self):
        self.grant()
        other = source_skill(
            self.actor,
            [add_action_effect(dynamic_definition("other", "集中"))],
            skill_id="other_source",
        )
        self.actor.resolve_skill_component(other.skill_id, "grant")
        self.assertEqual(
            [grant.definition["name"] for grant in self.actor.dynamic_actions],
            ["集中", "集中"],
        )

        duplicate = source_skill(
            self.actor,
            [add_action_effect()],
            skill_id="duplicate_source",
        )
        with self.assertRaises(SkillUnavailableError):
            self.actor.resolve_skill_component(duplicate.skill_id, "grant")

    def test_replace_policy_replaces_existing_action(self):
        self.grant()
        replacement = dynamic_definition("focus", "深度集中")
        other = source_skill(
            self.actor,
            [add_action_effect(replacement, duplicate_policy="replace")],
            skill_id="replacement_source",
        )
        self.actor.resolve_skill_component(other.skill_id, "grant")

        self.assertEqual(len(self.actor.dynamic_actions), 1)
        self.assertEqual(self.actor.dynamic_actions[0].definition["name"], "深度集中")

    def test_source_removal_removes_granted_action(self):
        source, _result = self.grant()
        remover = source_skill(self.actor, [{
            "effect_type": "remove_skill",
            "effect_data": {"skill_id": source.skill_id},
        }], skill_id="remover")

        self.actor.resolve_skill_component(remover.skill_id, "grant")

        self.assertEqual(self.actor.dynamic_actions, [])

    def test_base_action_id_cannot_be_overridden(self):
        skill = source_skill(self.actor, [add_action_effect(
            dynamic_definition("move", "伪移动")
        )])
        with self.assertRaises(SkillUnavailableError):
            self.actor.resolve_skill_component(skill.skill_id, "grant")

    def test_validation_rejects_unknown_nested_effect(self):
        definition = dynamic_definition()
        definition["effects"] = [{
            "effect_type": "missing_keyword",
            "effect_data": {},
        }]
        with self.assertRaisesRegex(ValueError, "效果关键词不存在"):
            validate_effect_definition(add_action_effect(definition))

    def test_granted_action_supports_usage_limit_and_cooldown(self):
        definition = dynamic_definition()
        definition["usage_limit"] = {
            "scope": "global_turn",
            "maximum": 1,
        }
        definition["cooldown"] = {"turns": 1}
        self.grant(definition=definition)
        self.actor.hp -= 10

        entry = next(
            item for item in ActionListBuilder().get_available_actions(
                ActionContext(
                    actor=self.actor,
                    phase="AP1",
                    turn_number=1,
                    characters=[self.actor],
                )
            )
            if item.action_id == "focus"
        )
        action = SkillAction(
            self.actor,
            entry.skill,
            entry.skill_component,
            target=self.actor,
        )
        action.game_turn = 1
        ActionResolver().resolve(action)

        entries = ActionListBuilder().get_action_entries(ActionContext(
            actor=self.actor,
            phase="AP1",
            turn_number=1,
            characters=[self.actor],
        ))
        exhausted = next(item for item in entries if item.action_id == "focus")
        self.assertFalse(exhausted.available)
        self.assertIn(
            "global_turn_usage_exhausted",
            exhausted.unavailable_reasons,
        )


if __name__ == "__main__":
    unittest.main()
