import unittest

from game.action.action import Action
from game.action.action_list import ActionContext, ActionListBuilder
from game.character.masters import Master
from game.character.servants import Servant
from game.game_manager import GameManager
from game.map.map import Location
from game.map.movement import Encounter
from game.turn.damage import AttackEvent
from game.turn.decision import ScriptedDecisionProvider


def create_master(name="Master"):
    return Master(name, 3, 3, 3, 3, 3, "C", 3)


def create_servant(name="Servant"):
    return Servant(name, 3, 3, 3, 3, 3, "Saber", "A")


class HolyGrailGameTests(unittest.TestCase):
    def test_death_moves_character_and_clears_pending_game_state(self):
        location = Location("Arena")
        defeated = create_master("Defeated")
        survivor = create_servant("Survivor")
        defeated.position = survivor.position = location
        game = GameManager([defeated, survivor], Location("Grail"))
        game.start_game()
        game.turn_manager.start_turn()

        queued_action = Action(defeated, "pass")
        game.turn_manager.add_action(queued_action, ap_layer=1)
        survivor.pending_attacks.append(AttackEvent(
            defeated,
            survivor,
            10,
            "physical",
            10,
            None,
        ))
        encounter = Encounter(
            [defeated, survivor],
            location,
            [],
            awareness={defeated: [survivor]},
        )
        encounter.choose_battle(defeated, survivor, ap_layer=1)
        game.turn_manager.add_encounter(encounter)

        defeated.die()

        self.assertNotIn(defeated, location.occupants)
        self.assertNotIn(defeated, game.characters)
        self.assertIn(defeated, game.dead_characters)
        self.assertNotIn(defeated, game.turn_manager.characters)
        self.assertNotIn(queued_action, game.turn_manager.action_layers[1])
        self.assertEqual(survivor.pending_attacks, [])
        self.assertNotIn(encounter, game.turn_manager.pending_encounters)

    def test_thresholds_are_configurable_and_ready_cannot_precede_appearance(self):
        game = GameManager(
            [create_master()],
            Location("Grail"),
            grail_appearance_deaths=2,
            grail_ready_deaths=3,
        )
        self.assertEqual(game.holy_grail.appearance_servant_deaths, 2)
        self.assertEqual(game.holy_grail.ready_servant_deaths, 3)
        with self.assertRaises(ValueError):
            game.configure_grail_thresholds(4, 3)

    def test_grail_appears_becomes_ready_and_announces_only_to_players(self):
        location = Location("Temple")
        player = create_master("Player")
        npc = create_master("NPC")
        servants = [create_servant(str(index)) for index in range(3)]
        game = GameManager(
            [player, npc, *servants],
            location,
            player_characters=[player],
            grail_appearance_deaths=2,
            grail_ready_deaths=3,
        )
        game.start_game()

        servants[0].die()
        self.assertFalse(game.refresh_grail_state())
        servants[1].die()
        self.assertTrue(game.refresh_grail_state())
        self.assertIs(game.holy_grail.position, location)
        self.assertFalse(game.holy_grail.ready)
        self.assertEqual(game.announce_grail_position(1), [player])

        servants[2].die()
        game.refresh_grail_state()
        self.assertTrue(game.holy_grail.ready)

    def test_investigate_can_pick_up_and_drop_grail(self):
        location = Location("Temple")
        master = create_master()
        master.position = location
        game = GameManager(
            [master],
            location,
            player_characters=[master],
            grail_appearance_deaths=0,
            grail_ready_deaths=0,
        )
        game.start_game()

        pick = game.handle_grail_investigation(
            master,
            ScriptedDecisionProvider(["1"]),
        )
        self.assertEqual(pick["action"], "picked_up")
        self.assertIs(game.holy_grail.carrier, master)

        other = Location("Other")
        master.position = other
        drop = game.handle_grail_investigation(
            master,
            ScriptedDecisionProvider(["1"]),
        )
        self.assertEqual(drop["action"], "dropped")
        self.assertIs(game.holy_grail.position, other)

    def test_dead_carrier_leaves_grail_at_death_location(self):
        location = Location("Temple")
        master = create_master()
        master.position = location
        game = GameManager(
            [master],
            location,
            grail_appearance_deaths=0,
            grail_ready_deaths=0,
        )
        game.start_game()
        self.assertTrue(game.holy_grail.pick_up(master))
        master.die()
        game.refresh_grail_state()
        self.assertIsNone(game.holy_grail.position)
        game.on_ap_checkpoint(1)
        self.assertIsNone(game.holy_grail.carrier)
        self.assertIs(game.holy_grail.position, location)

    def test_surrender_is_available_only_to_master_without_servants(self):
        location = Location("A")
        master = create_master()
        master.position = location
        context = ActionContext(actor=master, phase="AP1")
        entries = {
            entry.action_id: entry
            for entry in ActionListBuilder().get_action_entries(context)
        }
        self.assertTrue(entries["surrender"].available)

        servant = create_servant()
        master.add_servant(servant)
        entries = {
            entry.action_id: entry
            for entry in ActionListBuilder().get_action_entries(context)
        }
        self.assertFalse(entries["surrender"].available)
        master.remove_servant(servant)
        self.assertTrue(Action(master, "surrender").surrender())
        self.assertTrue(master.has_status("dead"))

    def test_wish_wins_for_master_and_living_servant(self):
        location = Location("Temple")
        master = create_master()
        servant = create_servant()
        master.add_servant(servant)
        master.position = servant.position = location
        game = GameManager(
            [master, servant],
            location,
            player_characters=[master, servant],
            grail_appearance_deaths=0,
            grail_ready_deaths=0,
        )
        game.start_game()
        game.turn_manager.start_turn()
        wish = Action(master, "wish")
        game.turn_manager.add_action(wish, ap_layer=1)
        game.turn_manager.execute_action_layer(1)

        self.assertTrue(game.ended)
        self.assertEqual(game.end_reason, "victory")
        self.assertEqual(game.winners, [master, servant])
        self.assertTrue(master.has_status("Victory"))
        self.assertTrue(servant.has_status("Victory"))

    def test_battle_request_cancels_wish_without_refunding_ap(self):
        location = Location("Temple")
        master = create_master()
        enemy = create_servant("Enemy")
        master.position = enemy.position = location
        game = GameManager(
            [master, enemy],
            location,
            player_characters=[master],
            grail_appearance_deaths=0,
            grail_ready_deaths=0,
        )
        game.start_game()
        game.turn_manager.start_turn()
        wish = Action(master, "wish")
        game.turn_manager.add_action(wish, ap_layer=1)

        encounter = Encounter(
            [master, enemy],
            location,
            [],
            awareness={enemy: [master]},
        )
        self.assertTrue(encounter.choose_battle(enemy, master, ap_layer=1))
        game.turn_manager.add_encounter(encounter)
        game.turn_manager.execute_action_layer(1)

        self.assertFalse(game.ended)
        self.assertEqual(master.action_point, 1)
        self.assertTrue(wish.checkpoint_result["cancelled_by_battle_request"])

    def test_turn_limit_kills_everyone_and_direct_end_interface_is_available(self):
        first = create_master("First")
        second = create_servant("Second")
        game = GameManager(
            [first, second],
            Location("Grail"),
            maximum_turns=1,
        )
        game.start_game()
        game.turn_manager.start_turn()
        game.turn_manager.end_turn()
        self.assertTrue(game.ended)
        self.assertEqual(game.end_reason, "turn_limit")
        self.assertTrue(first.has_status("dead"))
        self.assertTrue(second.has_status("dead"))

        other = GameManager([create_master()], Location("Other"))
        other.start_game()
        self.assertTrue(other.force_end_game("special"))
        self.assertEqual(other.end_reason, "special")


if __name__ == "__main__":
    unittest.main()
