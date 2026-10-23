import unittest

from game.game.basic_game_scenario import (
    create_basic_game_scenario,
)


class BasicGameScenarioTests(unittest.TestCase):
    def test_two_teams_and_map_are_initialized(self):
        game = create_basic_game_scenario()
        saber_master, saber, archer_master, archer = game.characters

        self.assertEqual(
            [
                saber_master.strength.value,
                saber_master.endurance.value,
                saber_master.flexibility.value,
                saber_master.magic.value,
                saber_master.fortune.value,
            ],
            [3, 3, 3, 3, 5],
        )
        self.assertEqual(
            [
                archer_master.strength.value,
                archer_master.endurance.value,
                archer_master.flexibility.value,
                archer_master.magic.value,
                archer_master.fortune.value,
            ],
            [3, 3, 4, 3, 3],
        )
        self.assertEqual(
            [
                saber.strength.value,
                saber.endurance.value,
                saber.flexibility.value,
                saber.magic.value,
                saber.fortune.value,
            ],
            [5, 5, 5, 5, 5],
        )
        self.assertEqual(
            [
                archer.strength.value,
                archer.endurance.value,
                archer.flexibility.value,
                archer.magic.value,
                archer.fortune.value,
            ],
            [5, 5, 5, 5, 4],
        )
        self.assertIs(saber.master, saber_master)
        self.assertIs(archer.master, archer_master)
        self.assertTrue(saber_master.is_ally(saber))
        self.assertTrue(archer_master.is_ally(archer))
        self.assertFalse(saber.is_ally(archer))
        self.assertEqual(saber.position.name, "住宅区A")
        self.assertEqual(archer.position.name, "教会C")
        self.assertEqual(game.holy_grail.position, None)
        self.assertEqual(game.holy_grail.designated_location.name, "商业区B")
        self.assertEqual(game.holy_grail.appearance_servant_deaths, 1)
        self.assertEqual(game.holy_grail.ready_servant_deaths, 1)
        self.assertEqual(game.maximum_turns, 120)

    def test_grail_location_can_be_selected_from_the_simple_map(self):
        game = create_basic_game_scenario("教会C")
        self.assertEqual(game.holy_grail.designated_location.name, "教会C")


if __name__ == "__main__":
    unittest.main()
