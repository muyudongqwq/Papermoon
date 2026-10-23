import unittest

from game.action.action import Action
from game.action.action_list import ActionContext, ActionListBuilder
from game.character.masters import Master
from game.game.game_manager import GameManager
from core.terminal_game_runner import TerminalGameRunner
from game.map.map import Location
from game.map.movement import MovementAction
from game.turn.Turn import TurnManager
from game.turn.battle import BattleManager
from game.turn.decision import ScriptedDecisionProvider


def create_master(name, move_conversion=2):
    character = Master(name, 3, 3, 3, 3, 3, "C", 3)
    character.move_conversion = move_conversion
    return character


def connect(left, right):
    left.add_connection(right)
    right.add_connection(left)


class TravelGroupTests(unittest.TestCase):
    def setUp(self):
        self.a = Location("A")
        self.b = Location("B")
        self.c = Location("C")
        connect(self.a, self.b)
        connect(self.b, self.c)

    def create_manager(self, *characters):
        manager = TurnManager()
        manager.characters = list(characters)
        manager.start_turn()
        manager.non_battle_order = list(characters)
        return manager

    def test_ap1_join_uses_joined_side_as_leader_and_clears_ap2_plan(self):
        leader = create_master("Leader")
        joiner = create_master("Joiner")
        leader.add_ally(joiner)
        leader.position = joiner.position = self.a
        manager = self.create_manager(leader, joiner)
        manager.add_action(Action(joiner, "pass"), ap_layer=2)

        request = manager.submit_travel_join(joiner, leader, 1)
        manager.resolve_travel_joins(1)

        self.assertTrue(request.success)
        self.assertIs(joiner.travel_group, leader.travel_group)
        self.assertIs(leader.travel_group.leader, leader)
        self.assertNotIn(joiner, manager.layer_actors[2])

    def test_join_requires_same_actual_ap_start_position(self):
        leader = create_master("Leader")
        joiner = create_master("Joiner")
        leader.add_ally(joiner)
        leader.position = self.a
        joiner.position = self.b
        manager = self.create_manager(leader, joiner)

        request = manager.submit_travel_join(joiner, leader, 1)
        manager.resolve_travel_joins(1)

        self.assertFalse(request.success)
        self.assertEqual(request.reason, "different_ap_start_position")
        self.assertIsNone(joiner.travel_group)

    def test_leader_can_transfer_only_once_per_global_turn(self):
        leader = create_master("Leader")
        second = create_master("Second")
        third = create_master("Third")
        for first, other in (
            (leader, second),
            (leader, third),
            (second, third),
        ):
            first.add_ally(other)
        leader.position = second.position = third.position = self.a
        manager = self.create_manager(leader, second, third)
        manager.submit_travel_join(second, leader, 1)
        manager.submit_travel_join(third, leader, 1)
        manager.resolve_travel_joins(1)

        self.assertTrue(manager.transfer_travel_leader(leader, second))
        self.assertFalse(manager.transfer_travel_leader(second, third))
        self.assertIs(second.travel_group.leader, second)

    def test_leader_movement_moves_every_member_at_lowest_speed_and_costs_ap(self):
        leader = create_master("Leader", move_conversion=3)
        follower = create_master("Follower", move_conversion=1)
        leader.add_ally(follower)
        leader.position = follower.position = self.a
        manager = self.create_manager(leader, follower)
        manager.submit_travel_join(follower, leader, 1)
        manager.add_action(
            MovementAction(leader, [self.a, self.b]),
            ap_layer=1,
        )

        manager.execute_action_layer(1)

        self.assertIs(leader.position, self.b)
        self.assertIs(follower.position, self.b)
        self.assertEqual(leader.action_point, 1)
        self.assertEqual(follower.action_point, 1)

    def test_join_fails_freely_if_it_would_invalidate_leader_route(self):
        leader = create_master("Leader", move_conversion=3)
        joiner = create_master("Joiner", move_conversion=1)
        leader.add_ally(joiner)
        leader.position = joiner.position = self.a
        manager = self.create_manager(leader, joiner)
        manager.add_movement_action(
            leader,
            [self.a, self.b, self.c],
            ap_layer=1,
        )

        request = manager.submit_travel_join(joiner, leader, 1)
        manager.resolve_travel_joins(1)

        self.assertFalse(request.success)
        self.assertEqual(
            request.reason,
            "leader_route_exceeds_group_movement",
        )
        self.assertIsNone(joiner.travel_group)

    def test_follower_action_is_ignored_when_leader_moves(self):
        leader = create_master("Leader")
        follower = create_master("Follower")
        leader.add_ally(follower)
        leader.position = follower.position = self.a
        manager = self.create_manager(leader, follower)
        manager.submit_travel_join(follower, leader, 1)
        leader_move = manager.add_movement_action(
            leader,
            [self.a, self.b],
            ap_layer=1,
        )
        fallback = Action(follower, "pass")
        manager.add_action(fallback, ap_layer=1)

        manager.execute_action_layer(1)

        self.assertTrue(fallback.ignored)
        self.assertEqual(
            fallback.ignored_reason,
            "following_travel_group",
        )
        self.assertIs(leader.position, self.b)
        self.assertIs(follower.position, self.b)
        self.assertIsNotNone(leader_move.movement_state)

    def test_ignored_two_ap_fallback_does_not_keep_ap2_reserved(self):
        leader = create_master("Leader")
        follower = create_master("Follower")
        leader.add_ally(follower)
        leader.position = follower.position = self.a
        manager = self.create_manager(leader, follower)
        manager.submit_travel_join(follower, leader, 1)
        manager.add_movement_action(leader, [self.a, self.b], ap_layer=1)
        fallback = Action(follower, "rest")
        manager.add_action(fallback, ap_layer=1)

        manager.execute_action_layer(1)

        self.assertTrue(fallback.ignored)
        self.assertNotIn(follower, manager.layer_actors[2])

    def test_independent_follower_move_detaches_when_leader_does_not_move(self):
        leader = create_master("Leader")
        follower = create_master("Follower")
        leader.add_ally(follower)
        leader.position = follower.position = self.a
        manager = self.create_manager(leader, follower)
        manager.submit_travel_join(follower, leader, 1)
        manager.resolve_travel_joins(1)
        manager.add_action(Action(leader, "pass"), ap_layer=2)
        manager.add_movement_action(follower, [self.a, self.b], ap_layer=2)

        manager.execute_action_layer(1)
        manager.execute_action_layer(2)

        self.assertIsNone(leader.travel_group)
        self.assertIsNone(follower.travel_group)
        self.assertIs(follower.position, self.b)

    def test_travel_group_shares_vision(self):
        leader = create_master("Leader")
        scout = create_master("Scout")
        enemy = create_master("Enemy")
        leader.add_ally(scout)
        leader.visibility = 0
        scout.visibility = 1
        leader.position = scout.position = self.a
        enemy.position = self.b
        manager = self.create_manager(leader, scout, enemy)
        manager.submit_travel_join(scout, leader, 1)
        manager.resolve_travel_joins(1)

        manager.update_visibility()

        self.assertIn(enemy, scout.own_visible)
        self.assertIn(enemy, leader.shared_visible)
        self.assertIn(enemy, leader.any_visible)

    def test_entering_battle_dissolves_the_whole_group(self):
        leader = create_master("Leader")
        follower = create_master("Follower")
        enemy = create_master("Enemy")
        leader.add_ally(follower)
        leader.position = follower.position = enemy.position = self.a
        manager = self.create_manager(leader, follower, enemy)
        manager.submit_travel_join(follower, leader, 1)
        manager.resolve_travel_joins(1)

        BattleManager([leader, enemy]).start_battle()

        self.assertIsNone(leader.travel_group)
        self.assertIsNone(follower.travel_group)

    def test_action_list_uses_distinct_join_ids(self):
        leader = create_master("Leader")
        joiner = create_master("Joiner")
        leader.add_ally(joiner)
        leader.position = joiner.position = self.a
        manager = self.create_manager(leader, joiner)
        entries = ActionListBuilder().get_available_actions(ActionContext(
            actor=joiner,
            phase="AP1",
            turn_manager=manager,
            characters=[leader, joiner],
        ))

        self.assertIn("join_travel_group", [entry.action_id for entry in entries])
        self.assertNotIn("join_battle", [entry.action_id for entry in entries])

    def test_terminal_join_is_free_and_ap2_is_collected_after_join(self):
        leader = create_master("Leader")
        joiner = create_master("Joiner")
        leader.add_ally(joiner)
        leader.position = joiner.position = self.a
        game = GameManager([leader, joiner], self.a)
        game.start_game()
        game.turn_manager.start_turn()
        game.turn_manager.non_battle_order = [leader, joiner]
        provider = ScriptedDecisionProvider([
            "move",
            "B",
            "finish",
            "pass",
            "join_travel_group",
            "Leader",
            "pass",
            "pass",
        ])
        runner = TerminalGameRunner(game, provider)

        runner.collect_map_actions()
        runner.execute_map_actions()

        self.assertIs(joiner.travel_group, leader.travel_group)
        self.assertIs(leader.position, self.b)
        self.assertIs(joiner.position, self.b)
        self.assertEqual(leader.action_point, 0)
        self.assertEqual(joiner.action_point, 0)

    def test_join_battle_creates_request_without_an_encounter(self):
        joining = create_master("Joining")
        target = create_master("Target")
        enemy = create_master("Enemy")
        joining.position = target.position = enemy.position = self.a
        game = GameManager([joining, target, enemy], self.a)
        game.start_game()
        battle = BattleManager([target, enemy])
        battle.start_battle()
        game.turn_manager.battles.append(battle)
        game.turn_manager.current_ap_layer = 1
        action = Action(joining, "join_battle", target=target)
        game.turn_manager.add_action(action, ap_layer=1)

        game.turn_manager.execute_action_layer(1)

        self.assertEqual(len(game.turn_manager.pending_battle_requests), 1)
        request = game.turn_manager.pending_battle_requests[0]
        self.assertIsNone(request.encounter)
        self.assertTrue(request.locked)
        self.assertTrue(joining.movement_locked)

        game.turn_manager.start_pending_battles()

        self.assertIn(joining, battle.participants)
        self.assertTrue(joining.in_battle)


if __name__ == "__main__":
    unittest.main()
