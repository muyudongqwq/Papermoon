import unittest

from game.action.action import Action
from game.character.servants import Servant
from game.map.map import Location
from game.skill.skill_runtime import (
    SkillUnavailableError,
    build_attack_profile_from_effect,
)
from game.turn.damage import AttackProfile


def create_servant(name="Servant"):
    return Servant(name, 3, 3, 3, 3, 3, "Saber", "A")


class AttackProfileTests(unittest.TestCase):
    def test_normal_attack_generation_is_separate_from_target_assignment(self):
        actor = create_servant("Actor")
        target = create_servant("Target")
        location = Location("Arena")
        actor.position = target.position = location
        action = Action(actor, "attack", damage_value=25)

        profile = action.build_attack_profile()

        self.assertIsInstance(profile, AttackProfile)
        self.assertEqual(profile.resolution_channel, "attack")
        self.assertEqual(profile.total_base_damage, 25)
        self.assertEqual(target.pending_attacks, [])

        event = action.assign_attack_target(profile, target)

        self.assertIs(event.attack_profile, profile)
        self.assertEqual(event.resolution_channel, "attack")
        self.assertEqual(target.pending_attacks, [event])

    def test_profile_combines_all_damage_segments(self):
        actor = create_servant("Actor")

        profile = AttackProfile(
            source=actor,
            value=0,
            damage_segments=[20, 30, 40],
            damage_type="physical",
            attack_roll=10,
        )

        self.assertEqual(profile.total_base_damage, 90)
        self.assertEqual(profile.damage_segments, [20, 30, 40])

    def test_magic_and_noble_attacks_use_release_channel(self):
        actor = create_servant("Caster")
        skill = actor.create_magic({
            "skill_id": "test_magic",
            "name": "测试魔术",
            "rank": "C",
             "casting": {"activation_mode": "release"},
            "components": [{"cost": [{"resource": "mp", "value": 10, "timing": "casting_start"}],
                "component_id": "attack",
                "type": "active",
                "casting_requirement": 0,
                "target": "selectable_character",
                "effects": [{
                    "effect_type": "create_attack_event",
                    "effect_data": {
                        "damage_value": 30,
                        "damage_type": "magic",
                    },
                }],
            }],
        })
        effect = skill.definitions[0]["effects"][0]

        profile = build_attack_profile_from_effect(
            effect,
            skill,
            actor=actor,
        )

        self.assertEqual(profile.resolution_channel, "release")

    def test_target_dependent_damage_cannot_generate_targetless_profile(self):
        actor = create_servant("Caster")
        skill = actor.create_personal_skill({
            "skill_id": "target_damage",
            "name": "目标依赖攻击",
            "rank": "C",
            "components": [{
                "component_id": "attack",
                "type": "active",
                "target": "selectable_character",
                "effects": [{
                    "effect_type": "create_attack_event",
                    "effect_data": {
                        "value_source": "target_attribute",
                        "attribute": "endurance",
                        "multiplier": 10,
                    },
                }],
            }],
        })
        effect = skill.definitions[0]["effects"][0]

        with self.assertRaisesRegex(
            SkillUnavailableError,
            "伤害依赖具体目标",
        ):
            build_attack_profile_from_effect(
                effect,
                skill,
                actor=actor,
            )


if __name__ == "__main__":
    unittest.main()
