import unittest

from game.character.masters import Master


def make_master(name="Master"):
    return Master(name, 3, 3, 3, 3, 3, "C", 3)


class BrinkLifecycleTests(unittest.TestCase):
    def trigger_brink(self, character):
        character.in_battle = True
        character.take_damage(character.hp)
        self.assertTrue(character.has_status("brink_of_death"))
        self.assertTrue(character.has_status("weakness"))
        self.assertEqual(character.brink_of_death_counter, 0)

    @staticmethod
    def remove_weakness(character):
        weakness = next(
            modifier
            for modifier in character.modifiers
            if getattr(modifier, "status", None) == "weakness"
        )
        character.remove_modifier(weakness)

    def test_weakness_ending_inside_same_battle_does_not_restore_brink(self):
        character = make_master()
        self.trigger_brink(character)
        self.remove_weakness(character)
        self.assertFalse(character.has_status("weakness"))
        self.assertEqual(character.brink_of_death_counter, 0)

        character.hp = 20
        character.take_damage(20)
        self.assertTrue(character.has_status("dead"))

    def test_brink_returns_only_after_battle_and_weakness_are_both_gone(self):
        character = make_master()
        self.trigger_brink(character)

        character.in_battle = False
        self.assertEqual(character.brink_of_death_counter, 0)
        self.remove_weakness(character)
        self.assertEqual(character.brink_of_death_counter, 1)

    def test_leaving_after_weakness_ends_restores_brink(self):
        character = make_master()
        self.trigger_brink(character)

        self.remove_weakness(character)
        self.assertEqual(character.brink_of_death_counter, 0)
        character.in_battle = False
        self.assertEqual(character.brink_of_death_counter, 1)


if __name__ == "__main__":
    unittest.main()
