import unittest

from game.character.masters import Master


def make_master(name="Master"):
    return Master(name, 3, 3, 3, 3, 3, "C", 3)


class SameSkillBuffTests(unittest.TestCase):
    def test_later_use_of_same_skill_component_replaces_earlier_buff(self):
        actor = make_master()
        definition = {
            "skill_id": "reinforcement",
            "name": "强化",
            "rank": "C",
            "components": [{
                "component_id": "buff",
                "type": "active",
                "available_phases": ["AP1"],
                "target": "self",
                "cost": [],
                "effects": [{
                    "modifier_id": "reinforcement_dice",
                    "effect_type": "dice_bonus",
                    "polarity": "buff",
                    "duration": 3,
                    "effect_data": {"effect_target": "dice_bonus", "value": 2},
                }],
            }],
        }
        skill = actor.create_personal_skill(definition)
        actor.resolve_skill_component(skill.skill_id, "buff")
        self.assertEqual(actor.dice_bonus, 2)

        skill.definitions[0]["effects"][0]["effect_data"]["value"] = 5
        actor.resolve_skill_component(skill.skill_id, "buff")
        self.assertEqual(actor.dice_bonus, 5)
        matching = [
            modifier
            for modifier in actor.modifiers
            if modifier.buff_skill_id == "reinforcement:buff"
        ]
        self.assertEqual(len(matching), 1)


if __name__ == "__main__":
    unittest.main()
