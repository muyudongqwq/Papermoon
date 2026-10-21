import unittest
from unittest.mock import patch

from game.character.servants import Servant
from game.map.map import Location
from game.turn.battle import BattleManager
from game.turn.decision import ScriptedDecisionProvider
from game.turn.roll import RollResolver


def create_servant(
    name="Saber",
    strength=3,
    endurance=3,
    flexibility=3,
    magic=3,
    fortune=3,
):
    return Servant(
        name,
        strength,
        endurance,
        flexibility,
        magic,
        fortune,
        "Saber",
        "A",
    )


class RollResolverTests(unittest.TestCase):
    def test_final_ten_adds_critical_success_bonus(self):
        character = create_servant(fortune=3)
        with patch("game.turn.roll.random.randint", return_value=10):
            result = RollResolver().roll(character, "physical_attack")

        self.assertTrue(result.critical_success)
        self.assertEqual(
            result.total,
            10 + character.physical_attack + character.dice_bonus + 15,
        )

    def test_final_one_adds_critical_failure_penalty_for_everyone(self):
        character = create_servant(strength=0, flexibility=0, fortune=0)
        with patch("game.turn.roll.random.randint", return_value=1):
            result = RollResolver().roll(character, "physical_attack")

        self.assertTrue(result.critical_failure)
        self.assertEqual(result.total, -14)

    def test_multiple_rerolls_and_flips_are_resolved_in_order(self):
        character = create_servant(fortune=(5, 2))
        character.start_battle()
        decisions = ScriptedDecisionProvider([
            "reroll",
            "flip",
            "reroll",
            "flip",
            "confirm",
        ])

        with patch("game.turn.roll.random.randint", side_effect=[2, 4, 8]):
            result = RollResolver().roll(
                character,
                "offset",
                decision_provider=decisions,
                phase="测试幸运",
            )

        self.assertEqual(result.history, [
            ("roll", 2),
            ("reroll", 4),
            ("flip", 7),
            ("reroll", 8),
            ("flip", 3),
        ])
        self.assertEqual(result.die, 3)
        self.assertEqual(result.rerolls_used, 2)
        self.assertEqual(result.flips_used, 2)
        self.assertEqual(character.luck_reroll, 1)
        self.assertEqual(character.fortune.plus, 0)
        self.assertFalse(result.critical_success)
        self.assertFalse(result.critical_failure)

    def test_two_flips_are_allowed_and_cancel_each_other(self):
        character = create_servant(fortune=(3, 2))
        character.start_battle()
        decisions = ScriptedDecisionProvider(["flip", "flip", "confirm"])
        with patch("game.turn.roll.random.randint", return_value=2):
            result = RollResolver().roll(
                character,
                "offset",
                decision_provider=decisions,
            )

        self.assertEqual(result.die, 2)
        self.assertEqual(result.flips_used, 2)
        self.assertEqual(character.fortune.plus, 0)

    def test_brink_halves_final_negative_roll_without_clamping(self):
        character = create_servant(
            strength=1,
            flexibility=0,
            fortune=0,
        )
        character.enter_brink()
        with patch("game.turn.roll.random.randint", return_value=1):
            result = RollResolver().roll(character, "physical_attack")

        self.assertEqual(result.total_before_final_multiplier, -13)
        self.assertEqual(result.final_multiplier, 0.5)
        self.assertEqual(result.total, -6)


class AttributePlusTests(unittest.TestCase):
    def test_strength_plus_uses_additive_multiplier_and_clears_at_turn_end(self):
        character = create_servant(strength=(3, 2))
        character.start_battle()

        self.assertTrue(character.use_attribute_plus("strength"))
        self.assertTrue(character.use_attribute_plus("strength"))
        self.assertEqual(character.strength.value, 9)
        self.assertEqual(character.atk, 90)

        character.update_modifiers("global_turn_end")
        self.assertEqual(character.strength.value, 3)
        self.assertEqual(character.strength.plus, 0)

    def test_endurance_and_magic_plus_raise_and_then_remove_resources(self):
        character = create_servant(endurance=(3, 1), magic=(3, 1))
        character.start_battle()

        self.assertTrue(character.use_attribute_plus("endurance"))
        self.assertTrue(character.use_attribute_plus("magic"))
        self.assertEqual((character.hpmax, character.hp), (150, 150))
        self.assertEqual((character.mpmax, character.mp), (150, 150))

        character.hp -= 10
        character.mp -= 20
        character.in_battle = False
        self.assertEqual((character.hpmax, character.hp), (90, 80))
        self.assertEqual((character.mpmax, character.mp), (90, 70))

    def test_reentering_battle_resets_uses_without_retaining_old_multiplier(self):
        character = create_servant(strength=(3, 1))
        character.start_battle()
        character.use_attribute_plus("strength")
        self.assertEqual(character.strength.value, 6)

        character.in_battle = False
        character.start_battle()
        self.assertEqual(character.strength.value, 3)
        self.assertEqual(character.strength.plus, 1)

    def test_attack_menu_shows_plus_until_non_luck_pluses_are_spent(self):
        character = create_servant(strength=(3, 1), flexibility=5)
        enemy = create_servant("Archer", flexibility=1)
        location = Location("Arena")
        character.position = enemy.position = location
        battle = BattleManager([character, enemy])
        battle.start_battle()
        decisions = ScriptedDecisionProvider([
            "use_plus",
            "strength",
            "stay",
            "stay",
        ])

        self.assertTrue(battle.run_battle_turn(decisions))
        attack_requests = [
            request
            for request in decisions.requests
            if request.phase == "攻击"
        ]
        self.assertEqual(
            [option.value for option in attack_requests[0].options][-1],
            "use_plus",
        )
        self.assertNotIn(
            "use_plus",
            [option.value for option in attack_requests[1].options],
        )


if __name__ == "__main__":
    unittest.main()
