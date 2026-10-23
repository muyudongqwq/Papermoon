import unittest
from unittest.mock import patch

from game.character.servants import Servant
from game.character.masters import Master
from game.character.npc import Familiar, NPC
from game.game.game_manager import GameManager
from game.map.map import Location
from game.turn.initialivemanager import InitiativeManager


def servant(name):
    return Servant(name, 3, 3, 3, 3, 3, "Saber", "A")


def master(name, flexibility=3, fortune=3):
    return Master(
        name,
        3,
        3,
        flexibility,
        3,
        fortune,
        "C",
        3,
    )


class InitiativeTests(unittest.TestCase):
    def test_lower_roller_is_not_lost_when_highest_roll_is_tied(self):
        first = servant("First")
        second = servant("Second")
        third = servant("Third")

        # 首轮First与Second同为最高骰，Third较低；随后二人解平。
        with patch(
            "game.turn.initialivemanager.random.randint",
            side_effect=[10, 10, 5, 9, 8],
        ):
            order = InitiativeManager().determine_order([
                first,
                second,
                third,
            ])

        self.assertEqual(order, [first, second, third])
        self.assertEqual(set(order), {first, second, third})

    def test_multiple_tied_subgroups_all_remain_in_order(self):
        first = servant("First")
        second = servant("Second")
        third = servant("Third")
        fourth = servant("Fourth")

        # 首轮形成[First, Second]和[Third, Fourth]两个同骰组。
        with patch(
            "game.turn.initialivemanager.random.randint",
            side_effect=[10, 10, 5, 5, 8, 7, 6, 4],
        ):
            order = InitiativeManager().determine_order([
                first,
                second,
                third,
                fourth,
            ])

        self.assertEqual(order, [first, second, third, fourth])
        self.assertEqual(len(order), 4)

    def test_players_roll_and_tied_npc_is_always_after_them(self):
        first = servant("First")
        second = servant("Second")
        npc = NPC(
            "NPC",
            flexibility=3,
            fortune=3,
            move_conversion=1,
        )
        with patch(
            "game.turn.initialivemanager.random.randint",
            side_effect=[2, 9],
        ) as roller:
            order = InitiativeManager().determine_order([
                first,
                npc,
                second,
            ])
        self.assertEqual(order, [second, first, npc])
        self.assertEqual(roller.call_count, 2)

    def test_npc_with_higher_stats_still_precedes_player(self):
        player = servant("Player")
        npc = NPC(
            "Fast NPC",
            flexibility=4,
            fortune=1,
            move_conversion=1,
        )
        with patch(
            "game.turn.initialivemanager.random.randint",
            side_effect=AssertionError("不同属性组不应掷骰"),
        ):
            order = InitiativeManager().determine_order([player, npc])
        self.assertEqual(order, [npc, player])

    def test_npc_stats_are_locked_by_first_snapshot(self):
        npc = NPC(
            "NPC",
            flexibility=3,
            fortune=3,
            move_conversion=1,
        )
        slower = NPC(
            "Slower",
            flexibility=2,
            fortune=3,
            move_conversion=1,
        )
        manager = InitiativeManager()
        self.assertEqual(manager.determine_order([npc, slower]), [npc, slower])
        npc.flexibility.value = 1
        slower.flexibility.value = 10
        self.assertEqual(manager.determine_order([npc, slower]), [npc, slower])

    def test_familiar_snapshot_uses_summoner_current_order_then_stays_fixed(self):
        location = Location("Arena")
        first = master("First")
        second = master("Second")
        first.position = second.position = location
        game = GameManager([first, second], location)
        game.start_game()
        game.turn_manager.turn = 1
        game.turn_manager.global_action_order = [second, first]

        first_familiar = Familiar("First familiar", first)
        second_familiar = Familiar("Second familiar", second)
        game.register_character(first_familiar, location)
        game.register_character(second_familiar, location)
        manager = InitiativeManager()
        self.assertEqual(
            manager.determine_order([first_familiar, second_familiar]),
            [second_familiar, first_familiar],
        )

        game.turn_manager.global_action_order = [first, second]
        second_familiar.flexibility.value = 0
        self.assertEqual(
            manager.determine_order([first_familiar, second_familiar]),
            [second_familiar, first_familiar],
        )

    def test_same_summoner_familiars_use_registration_order(self):
        location = Location("Arena")
        owner = master("Owner")
        owner.position = location
        game = GameManager([owner], location)
        game.start_game()
        game.turn_manager.turn = 1
        game.turn_manager.global_action_order = [owner]
        early = Familiar("Early", owner)
        late = Familiar("Late", owner)
        game.register_character(early, location)
        game.register_character(late, location)

        self.assertEqual(
            InitiativeManager().determine_order([late, early]),
            [early, late],
        )


if __name__ == "__main__":
    unittest.main()
