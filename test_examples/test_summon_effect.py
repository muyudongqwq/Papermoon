import unittest

from game.character.masters import Master
from game.game_manager import GameManager
from game.map.map import Location
from game.skill.effect_validation import validate_effect_definition
from game.turn.battle import BattleManager


def master(name):
    return Master(name, 3, 3, 3, 3, 3, "C", 3)


def summon_skill(actor, **effect_data):
    data = {"template_id": "amber_elder"}
    data.update(effect_data)
    return actor.create_personal_skill({
        "skill_id": f"summon_test:{len(actor.personal_skills)}",
        "name": "召唤测试",
        "rank": "C",
        "components": [{
            "component_id": "summon",
            "type": "active",
            "available_phases": ["AP1"],
            "resolution_timing": "immediate",
            "target": "current_position",
            "effects": [{
                "effect_type": "summon",
                "effect_data": data,
            }],
        }],
    })


class SummonEffectTests(unittest.TestCase):
    def setUp(self):
        self.location = Location("Workshop", is_building=True)
        self.summoner = master("Summoner")
        self.enemy = master("Enemy")
        self.summoner.position = self.location
        self.enemy.position = self.location
        self.game = GameManager(
            [self.summoner, self.enemy],
            self.location,
        )
        self.game.start_game()
        self.game.turn_manager.turn = 1

    def resolve(self, skill):
        return self.summoner.resolve_skill_component(
            skill.skill_id,
            "summon",
            target=self.location,
            phase="AP1",
        )["results"][0]

    def test_summon_registers_familiar_with_delayed_activation(self):
        skill = summon_skill(self.summoner)
        result = self.resolve(skill)
        familiar = result["records"][0].familiar

        self.assertIn(familiar, self.game.characters)
        self.assertIn(familiar, self.summoner.familiars)
        self.assertIs(familiar.position, self.location)
        self.assertEqual(familiar.activation_turn, 2)
        self.assertEqual(familiar.attack_phase_count, 0)

    def test_count_has_no_implicit_limit(self):
        skill = summon_skill(self.summoner, count=2)
        result = self.resolve(skill)

        self.assertEqual(len(result["records"]), 2)
        self.assertEqual(len(self.summoner.familiars), 2)

    def test_explicit_limit_can_replace_oldest(self):
        skill = summon_skill(
            self.summoner,
            maximum_active=1,
            at_limit="replace_oldest",
        )
        first = self.resolve(skill)["records"][0]
        second_result = self.resolve(skill)
        second = second_result["records"][0]

        self.assertFalse(first.active)
        self.assertEqual(first.removal_reason, "summon_replaced")
        self.assertNotIn(first.familiar, self.game.characters)
        self.assertIn(second.familiar, self.game.characters)
        self.assertEqual(second_result["replaced"], [first])

    def test_duration_expires_at_global_turn_end(self):
        skill = summon_skill(self.summoner, duration=1)
        record = self.resolve(skill)["records"][0]

        self.game.on_turn_end(1)

        self.assertFalse(record.active)
        self.assertEqual(record.removal_reason, "summon_expired")
        self.assertNotIn(record.familiar, self.game.characters)

    def test_summon_at_active_battle_is_forced_to_join(self):
        battle = BattleManager([self.summoner, self.enemy])
        self.game.turn_manager.battles.append(battle)
        battle.start_battle()
        skill = summon_skill(self.summoner)

        familiar = self.resolve(skill)["records"][0].familiar

        self.assertIn(familiar, battle.participants)
        self.assertIs(familiar.current_battle, battle)
        self.assertEqual(familiar.attack_phase_count, 0)

    def test_schema_rejects_impossible_count_limit(self):
        with self.assertRaisesRegex(ValueError, "不能小于count"):
            validate_effect_definition({
                "effect_type": "summon",
                "effect_data": {
                    "template_id": "amber_elder",
                    "count": 2,
                    "maximum_active": 1,
                },
            })


if __name__ == "__main__":
    unittest.main()
