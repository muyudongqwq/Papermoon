import unittest

from game.character.masters import Master
from game.game_manager import GameManager
from game.map.map import Location


def make_master(name="Caster"):
    return Master(name, 3, 3, 3, 3, 3, "C", 3)


def modifier_effect(modifier_id, value=2):
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


def skill_definition(skill_id, components, name=None):
    return {
        "skill_id": skill_id,
        "name": name or skill_id,
        "rank": "C",
        "components": components,
    }


def active_component(component_id, effects):
    return {
        "component_id": component_id,
        "type": "active",
        "target": "self",
        "effects": effects,
    }


def trigger_component(component_id, effects, priority=0):
    return {
        "component_id": component_id,
        "type": "trigger",
        "trigger": {
            "event_type": "test_pulse",
            "timing": "after",
            "priority": priority,
        },
        "target": "self",
        "effects": effects,
    }


class SkillMutationTests(unittest.TestCase):
    def setUp(self):
        self.actor = make_master()

    def test_add_nested_personal_skill(self):
        child = skill_definition("child", [
            active_component("child_active", [{
                "effect_type": "recover_resource",
                "effect_data": {"resource_id": "hp", "value": 1},
            }]),
        ])
        source = self.actor.create_personal_skill(skill_definition("source", [
            active_component("grant", [{
                "effect_type": "add_skill",
                "effect_data": {
                    "skill_definition": child,
                    "remove_with_source": True,
                },
            }]),
        ]))

        self.actor.resolve_skill_component("source", "grant")

        granted = next(skill for skill in self.actor.personal_skills
                       if skill.skill_id == "child")
        self.assertTrue(granted.dynamic)
        self.assertIs(granted.granted_by, source)
        self.assertTrue(granted.remove_with_source)

    def test_add_and_remove_same_id_replaces_atomically(self):
        old = self.actor.create_personal_skill(skill_definition("stance", [
            active_component("old", [{
                "effect_type": "recover_resource",
                "effect_data": {"resource_id": "hp", "value": 1},
            }]),
        ], name="Old"))
        replacement = skill_definition("stance", [
            active_component("new", [{
                "effect_type": "recover_resource",
                "effect_data": {"resource_id": "mp", "value": 1},
            }]),
        ], name="New")
        self.actor.create_personal_skill(skill_definition("evolve", [
            active_component("evolve", [
                {
                    "effect_type": "add_skill",
                    "effect_data": {"skill_definition": replacement},
                },
                {
                    "effect_type": "remove_skill",
                    "effect_data": {"skill_id": "stance"},
                },
            ]),
        ]))

        self.actor.resolve_skill_component("evolve", "evolve")

        matches = [skill for skill in self.actor.personal_skills
                   if skill.skill_id == "stance"]
        self.assertEqual([skill.name for skill in matches], ["New"])
        self.assertTrue(old.removed)

    def test_failed_preflight_does_not_remove_old_skill(self):
        old = self.actor.create_personal_skill(skill_definition("old", [
            active_component("old_active", [{
                "effect_type": "recover_resource",
                "effect_data": {"resource_id": "hp", "value": 1},
            }]),
        ]))
        self.actor.create_personal_skill(skill_definition("occupied", [
            active_component("occupied_active", [{
                "effect_type": "recover_resource",
                "effect_data": {"resource_id": "hp", "value": 1},
            }]),
        ]))
        self.actor.create_personal_skill(skill_definition("bad_evolve", [
            active_component("bad", [
                {
                    "effect_type": "remove_skill",
                    "effect_data": {"skill_id": "old"},
                },
                {
                    "effect_type": "add_skill",
                    "effect_data": {
                        "skill_definition": skill_definition("occupied", [
                            active_component("duplicate", [{
                                "effect_type": "recover_resource",
                                "effect_data": {
                                    "resource_id": "hp", "value": 1,
                                },
                            }]),
                        ]),
                    },
                },
            ]),
        ]))

        with self.assertRaises(ValueError):
            self.actor.resolve_skill_component("bad_evolve", "bad")

        self.assertIn(old, self.actor.personal_skills)
        self.assertFalse(old.removed)

    def test_remove_cleans_passive_modifier_and_linked_child(self):
        source = self.actor.create_personal_skill(skill_definition("source", [{
            "component_id": "passive",
            "type": "passive",
            "target": "self",
            "effects": [modifier_effect("source_bonus")],
        }]))
        child = self.actor.create_personal_skill(skill_definition("child", [
            active_component("child_active", [{
                "effect_type": "recover_resource",
                "effect_data": {"resource_id": "hp", "value": 1},
            }]),
        ]))
        child.dynamic = True
        child.granted_by = source
        child.remove_with_source = True
        self.assertEqual(self.actor.dice_bonus, 2)
        self.actor.create_personal_skill(skill_definition("remover", [
            active_component("remove", [{
                "effect_type": "remove_skill",
                "effect_data": {"skill_id": "source"},
            }]),
        ]))

        self.actor.resolve_skill_component("remover", "remove")

        self.assertEqual(self.actor.dice_bonus, 0)
        self.assertNotIn(source, self.actor.personal_skills)
        self.assertNotIn(child, self.actor.personal_skills)

    def test_removed_candidate_does_not_execute_from_event_snapshot(self):
        location = Location("A")
        self.actor.position = location
        game = GameManager([self.actor], location)
        game.start_game()
        victim = self.actor.create_personal_skill(skill_definition("victim", [
            trigger_component("late", [modifier_effect("must_not_apply")], 0),
        ]))
        self.actor.create_personal_skill(skill_definition("remover", [
            trigger_component("early", [{
                "effect_type": "remove_skill",
                "effect_data": {"skill_id": "victim"},
            }], 10),
        ]))

        game.event_manager.emit("test_pulse", actor=self.actor)

        self.assertNotIn(victim, self.actor.personal_skills)
        self.assertEqual(self.actor.dice_bonus, 0)

    def test_new_trigger_waits_until_next_event(self):
        location = Location("A")
        self.actor.position = location
        game = GameManager([self.actor], location)
        game.start_game()
        child = skill_definition("new_trigger", [
            trigger_component("react_later", [modifier_effect("later_bonus")]),
        ])
        self.actor.create_personal_skill(skill_definition("grant_once", [
            trigger_component("grant", [
                {
                    "effect_type": "add_skill",
                    "effect_data": {"skill_definition": child},
                },
                {
                    "effect_type": "remove_skill",
                    "effect_data": {"skill": "self"},
                },
            ], 10),
        ]))

        game.event_manager.emit("test_pulse", actor=self.actor)
        self.assertEqual(self.actor.dice_bonus, 0)

        game.event_manager.emit("test_pulse", actor=self.actor)
        self.assertEqual(self.actor.dice_bonus, 2)


if __name__ == "__main__":
    unittest.main()
