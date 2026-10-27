import unittest

from core.catalog import CatalogProject, DEFAULT_CATALOG
from core.skill_test import create_skill_test_scenario
from core.terminal_commands import TerminalCommandHandler
from game.turn.battle import BattleManager


class SkillTestTerminalTests(unittest.TestCase):
    def setUp(self):
        self.project = CatalogProject(DEFAULT_CATALOG)
        self.activation = self.project.activate()
        self.activation.__enter__()
        self.game = create_skill_test_scenario(["master_test_0", "fixed"])
        self.game.start_game()
        self.output = []
        self.handler = TerminalCommandHandler(self.game, output_func=self.output.append)

    def tearDown(self):
        self.activation.__exit__(None, None, None)

    def test_test_side_has_ex_stats_debug_skill_and_death_guard(self):
        for role in ("master", "servant"):
            actor = self.game.skill_test_npcs[role]
            self.assertEqual(actor.endurance.base_value, 10)
            self.assertEqual(actor.magic.base_value, 10)
            self.assertTrue(actor.test_prevent_death)
            self.assertIn("class:测试程序", [skill.skill_id for skill in actor.class_skills])
            actor.brink_of_death_counter = 0
            actor.take_damage(actor.hp + 100)
            self.assertEqual(actor.hp, 1)
            self.assertTrue(actor.is_alive())

    def test_prevent_death_false_then_respawn_rebuilds_master_link(self):
        master = self.game.skill_test_npcs["master"]
        servant = self.game.skill_test_npcs["servant"]
        self.handler.handle("prevent_death master false")
        master.brink_of_death_counter = 0
        master.die()
        self.assertIsNone(servant.master)
        self.handler.handle("respawn master")
        replacement = self.game.skill_test_npcs["master"]
        self.assertIsNot(replacement, master)
        self.assertIs(servant.master, replacement)
        self.assertIs(replacement.position, self.game.locations["C"])

    def test_building_high_building_show_and_clear(self):
        self.handler.handle("building A")
        self.handler.handle("high_building")
        self.assertTrue(self.game.locations["A"].is_building)
        self.assertIsNotNone(self.game.locations["A"].high_level_location)
        self.assertTrue(self.handler.handle("show event"))

        master = self.game.skill_test_npcs["master"]
        servant = self.game.skill_test_npcs["servant"]
        resolver = self.game.turn_manager.movement_resolver
        self.game.turn_manager.battles.append(BattleManager([master, servant]))
        self.assertTrue(self.handler.handle("clear"))
        self.assertIn(resolver._contact_key(master, servant), resolver.suppressed_until_separated)
        master.position = self.game.locations["B"]
        resolver.check_encounter(self.game.characters, [])
        self.assertNotIn(resolver._contact_key(master, servant), resolver.suppressed_until_separated)

    def test_only_quit_can_end_skill_test(self):
        self.assertFalse(self.game.end_game("victory", [self.game.characters[0]]))
        self.assertFalse(self.game.ended)
        self.assertTrue(self.game.force_end_game("manual_quit"))
        self.assertTrue(self.game.ended)


if __name__ == "__main__":
    unittest.main()
