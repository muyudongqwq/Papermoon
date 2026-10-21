import unittest

from game.character.masters import Master
from game.character.npc import Familiar, NPC
from game.character.servants import Servant
from game.game_manager import GameManager
from game.map.map import Location
from game.turn.battle import BattleManager


def make_master(name):
    return Master(name, 3, 3, 3, 3, 3, "C", 3)


def make_servant(name):
    return Servant(name, 3, 3, 3, 3, 3, "Saber", "C")


class DynamicEntityTests(unittest.TestCase):
    def setUp(self):
        self.a = Location("A", is_building=True)
        self.b = Location("B", is_building=True)
        self.a.add_connection(self.b)
        self.b.add_connection(self.a)
        self.summoner = make_master("Summoner")
        self.enemy = make_servant("Enemy")
        self.summoner.position = self.a
        self.enemy.position = self.b
        self.game = GameManager([self.summoner, self.enemy], self.a)
        self.game.start_game()
        self.game.turn_manager.turn = 1

    def test_npc_and_familiar_defaults(self):
        npc = NPC("Guard", move_conversion=2)
        familiar = Familiar("Scout", self.summoner)
        self.assertTrue(npc.is_npc)
        self.assertEqual(npc.controller, "gm")
        self.assertTrue(familiar.is_npc)
        self.assertTrue(familiar.is_familiar)
        self.assertIs(familiar.initiative_anchor, self.summoner)
        self.assertIs(familiar.controller, self.summoner.controller)
        self.assertEqual(familiar.mpmax, 0)
        self.assertEqual(familiar.mp, 0)
        self.assertEqual(familiar.move_conversion, 1)
        for dice_name in (
            "physical_attack",
            "magic_attack",
            "dodge",
            "block",
            "offset",
        ):
            self.assertEqual(getattr(familiar, dice_name), 0)

    def test_registration_delays_actions_and_links_only_summoner(self):
        ally = make_master("Ally")
        ally.position = self.a
        self.summoner.add_ally(ally)
        self.game.register_character(ally, self.a, activate_immediately=True)
        familiar = Familiar("Scout", self.summoner, move_conversion=3)

        registered = self.game.register_character(familiar, self.b)
        self.assertIs(registered, familiar)
        self.assertIn(familiar, self.game.characters)
        self.assertIn(familiar, self.game.turn_manager.characters)
        self.assertNotIn(familiar, self.game.player_characters)
        self.assertEqual(familiar.activation_turn, 2)
        self.assertEqual(familiar.action_point, 0)
        self.assertFalse(familiar.can_act_on_turn(1))
        self.assertTrue(familiar.can_act_on_turn(2))
        self.assertTrue(familiar.is_ally(self.summoner))
        self.assertTrue(self.summoner.is_ally(familiar))
        self.assertFalse(familiar.is_ally(ally))
        self.assertFalse(ally.is_ally(familiar))

        self.game.turn_manager.update_visibility()
        self.assertIn(self.enemy, familiar.own_visible)
        self.assertIn(self.enemy, self.summoner.shared_visible)
        self.assertIn(familiar, self.summoner.familiars)

    def test_familiar_spawned_at_battle_is_forced_into_it_without_attack(self):
        self.summoner.position = self.enemy.position = self.a
        battle = BattleManager([self.summoner, self.enemy])
        self.game.turn_manager.battles.append(battle)
        battle.start_battle()
        familiar = Familiar("Battle familiar", self.summoner)

        self.game.register_character(familiar, self.a)
        self.assertIn(familiar, battle.participants)
        self.assertIs(familiar.current_battle, battle)
        self.assertTrue(familiar.in_battle)
        self.assertEqual(familiar.attack_phase_count, 0)
        self.assertIn(familiar, battle.late_participants)
        self.assertIs(battle.initial_order[-1], familiar)

    def test_summoner_death_despawns_familiar_and_keeps_record(self):
        familiar = Familiar("Scout", self.summoner)
        self.game.register_character(familiar, self.a)
        self.summoner.die()

        self.assertNotIn(familiar, self.game.characters)
        self.assertNotIn(familiar, self.game.dead_characters)
        self.assertNotIn(familiar, self.game.turn_manager.characters)
        self.assertIsNone(familiar.position)
        self.assertEqual(familiar.despawn_reason, "summoner_exit")
        self.assertNotIn(familiar, self.summoner.familiars)
        record = self.game.removed_characters[-1]
        self.assertIs(record["character"], familiar)
        self.assertEqual(record["reason"], "summoner_exit")
        self.assertIs(record["last_position"], self.a)
        self.assertFalse(self.game.register_character(familiar, self.a))

    def test_familiar_has_no_brink_and_destruction_is_not_death(self):
        familiar = Familiar("Fragile", self.summoner)
        self.game.register_character(familiar, self.a)
        familiar.take_damage(familiar.hpmax)

        self.assertEqual(familiar.hp, 0)
        self.assertFalse(familiar.has_status("brink_of_death"))
        self.assertFalse(familiar.has_status("dead"))
        self.assertTrue(familiar.has_status("despawned"))
        self.assertNotIn(familiar, self.game.dead_characters)
        self.assertEqual(
            self.game.removed_characters[-1]["reason"],
            "destroyed",
        )

    def test_npc_cannot_be_registered_as_player_character(self):
        npc = NPC("NPC")
        npc.position = self.a
        with self.assertRaisesRegex(ValueError, "NPC与使魔"):
            GameManager(
                [self.summoner, npc],
                self.a,
                player_characters=[self.summoner, npc],
            )


if __name__ == "__main__":
    unittest.main()
