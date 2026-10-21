import unittest
from unittest.mock import patch

from game.character.servants import Servant
from game.map.map import Location
from game.map.movement import Encounter, MovementResolver, MovementState
from game.turn.Turn import TurnManager
from game.action.action import Action


def create_servant(name, flexibility=3):
    return Servant(
        name=name,
        strength=3,
        endurance=5,
        flexibility=flexibility,
        magic=3,
        fortune=3,
        servant_class="Saber",
        noble="A",
    )


def connect(left, right):
    left.add_connection(right)
    right.add_connection(left)


class ActionLayerTests(unittest.TestCase):
    def test_character_can_submit_only_one_action_per_layer(self):
        actor = create_servant("Actor")
        actor.position = Location("A")
        manager = TurnManager()
        manager.characters = [actor]
        manager.start_turn()

        manager.add_action(Action(actor, "perceive"), ap_layer=1)
        with self.assertRaises(ValueError):
            manager.add_action(Action(actor, "investigate"), ap_layer=1)

        self.assertTrue(
            manager.add_action(Action(actor, "investigate"), ap_layer=2)
        )

    def test_perception_reads_positions_at_ap1_checkpoint(self):
        nodes = [Location(str(index)) for index in range(7)]
        for left, right in zip(nodes, nodes[1:]):
            connect(left, right)

        observer = create_servant("Observer", flexibility=5)
        target = create_servant("Target", flexibility=3)
        observer.position = nodes[0]
        target.position = nodes[6]

        manager = TurnManager()
        manager.characters = [observer, target]
        manager.start_turn()
        target.movement_point = 1

        perceive_action = Action(observer, "perceive")
        manager.add_action(perceive_action, ap_layer=1)
        manager.add_action(Action(target, "move", nodes[5]), ap_layer=1)

        with patch("game.action.action.random.randint", side_effect=[10, 1]):
            manager.execute_action_layer(1)

        self.assertIs(target.position, nodes[5])
        self.assertIn(target, perceive_action.checkpoint_result["detected"])
        self.assertIn(target, observer.perceived)
        self.assertEqual(manager.completed_checkpoints, [1])
        self.assertEqual(manager.current_ap_layer, 2)

    def test_investigation_records_checkpoint_position_without_range_limit(self):
        nodes = [Location(str(index)) for index in range(8)]
        for left, right in zip(nodes, nodes[1:]):
            connect(left, right)

        investigator = create_servant("Investigator", flexibility=5)
        target = create_servant("Target", flexibility=3)
        investigator.position = nodes[0]
        target.position = nodes[7]

        manager = TurnManager()
        manager.characters = [investigator, target]
        manager.start_turn()
        target.movement_point = 1

        investigate_action = Action(investigator, "investigate")
        manager.add_action(investigate_action, ap_layer=1)
        manager.add_action(Action(target, "move", nodes[6]), ap_layer=1)
        manager.execute_action_layer(1)

        result = investigate_action.checkpoint_result
        self.assertIs(result["positions"][target], nodes[6])
        self.assertIs(investigator.revealed_positions[target], nodes[6])

    def test_checkpoint_investigation_reveals_normal_hidden_character(self):
        location = Location("Building", is_building=True)
        investigator = create_servant("Investigator", flexibility=5)
        hidden_target = create_servant("Target", flexibility=3)
        investigator.position = location
        hidden_target.position = location
        hidden_target.status_flags.add("hidden")

        manager = TurnManager()
        manager.characters = [investigator, hidden_target]
        manager.start_turn()
        investigate_action = Action(investigator, "investigate")
        manager.add_action(investigate_action, ap_layer=1)
        manager.execute_action_layer(1)

        result = investigate_action.checkpoint_result
        self.assertEqual(result["servants"], [hidden_target])
        self.assertEqual(result["positions"], {hidden_target: location})
        self.assertIn(hidden_target, investigator.revealed_positions)
        self.assertNotIn(hidden_target, investigator.perceived)


class BattleRequestCheckpointTests(unittest.TestCase):
    def create_hidden_encounter(self):
        location = Location("Building", is_building=True)
        ambusher = create_servant("Ambusher", flexibility=5)
        target = create_servant("Target", flexibility=3)
        ambusher.position = location
        target.position = location
        ambusher.status_flags.add("hidden")
        encounter = MovementResolver().check_encounter(
            [ambusher, target],
            [],
        )[0]
        return ambusher, target, encounter

    def test_same_ap_layer_perception_cancels_ambush(self):
        ambusher, target, encounter = self.create_hidden_encounter()
        manager = TurnManager()
        manager.characters = [ambusher, target]
        manager.start_turn()

        self.assertTrue(
            manager.declare_battle(encounter, ambusher, target)
        )
        perceive_action = Action(target, "perceive")
        manager.add_action(perceive_action, ap_layer=1)

        with patch("game.action.action.random.randint", side_effect=[10, 1]):
            manager.execute_action_layer(1)

        request = encounter.battle_requests[0]
        self.assertTrue(request.locked)
        self.assertFalse(request.is_ambush)
        self.assertTrue(encounter.pending_battle)
        self.assertEqual(encounter.get_ambush_pairs(), [])

        manager.execute_action_layer(2)
        manager.end_turn()
        manager.start_turn()
        self.assertEqual(len(manager.battles), 1)
        self.assertEqual(manager.battles[0].effects, [])

    def test_ap2_perception_does_not_change_ap1_ambush_lock(self):
        ambusher, target, encounter = self.create_hidden_encounter()
        manager = TurnManager()
        manager.characters = [ambusher, target]
        manager.start_turn()

        manager.declare_battle(encounter, ambusher, target)
        perceive_action = Action(target, "perceive")
        manager.add_action(perceive_action, ap_layer=2)

        manager.execute_action_layer(1)
        request = encounter.battle_requests[0]
        self.assertTrue(request.is_ambush)

        with patch("game.action.action.random.randint", side_effect=[10, 1]):
            manager.execute_action_layer(2)

        self.assertIn(ambusher, target.perceived)
        self.assertTrue(request.is_ambush)
        self.assertEqual(
            encounter.get_ambush_pairs(),
            [(ambusher, target)],
        )

        manager.end_turn()
        manager.start_turn()
        self.assertEqual(len(manager.battles), 1)
        self.assertEqual(len(manager.battles[0].effects), 1)
        self.assertTrue(manager.battles[0].effects[0].is_ambush)

    def test_ap2_request_locks_at_ap2_checkpoint(self):
        ambusher, target, encounter = self.create_hidden_encounter()
        manager = TurnManager()
        manager.characters = [ambusher, target]
        manager.start_turn()
        manager.execute_action_layer(1)

        manager.declare_battle(encounter, ambusher, target)
        request = encounter.battle_requests[0]
        self.assertEqual(request.submitted_layer, 2)
        self.assertFalse(request.locked)

        manager.execute_action_layer(2)
        self.assertTrue(request.locked)
        self.assertEqual(request.locked_layer, 2)

    def test_resolved_request_ignores_all_prequeued_later_moves(self):
        ambusher, target, encounter = self.create_hidden_encounter()
        start = ambusher.position
        exit_location = Location("Exit")
        connect(start, exit_location)

        manager = TurnManager()
        manager.characters = [ambusher, target]
        manager.start_turn()
        target.movement_point = 2
        ambusher.movement_point = 1

        ap1_move = Action(target, "move", exit_location)
        target_ap2_move = Action(target, "move", start)
        ambusher_ap2_move = Action(ambusher, "move", exit_location)
        manager.add_action(ap1_move, ap_layer=1)
        manager.add_action(target_ap2_move, ap_layer=2)
        manager.add_action(ambusher_ap2_move, ap_layer=2)
        manager.declare_battle(encounter, ambusher, target)

        manager.execute_action_layer(1)

        self.assertIs(target.position, start)
        self.assertTrue(ap1_move.ignored)
        self.assertTrue(target.movement_locked)
        self.assertTrue(ambusher.movement_locked)
        self.assertEqual(target.movement_lock_layer, 1)
        self.assertEqual(ambusher.movement_lock_layer, 1)

        results = manager.execute_action_layer(2)

        self.assertIs(target.position, start)
        self.assertIs(ambusher.position, start)
        self.assertTrue(target_ap2_move.ignored)
        self.assertTrue(ambusher_ap2_move.ignored)
        self.assertEqual(
            {result["reason"] for _, result in results},
            {"movement_locked_by_battle_request"},
        )


class EncounterPauseResumeTests(unittest.TestCase):
    def create_hidden_encounter(self):
        location = Location("Building", is_building=True)
        ambusher = create_servant("Ambusher", flexibility=5)
        target = create_servant("Target", flexibility=3)
        ambusher.position = location
        target.position = location
        ambusher.status_flags.add("hidden")
        encounter = MovementResolver().check_encounter(
            [ambusher, target],
            [],
        )[0]
        return ambusher, target, encounter

    def create_movement_encounter(self):
        start = Location("Start")
        encounter_location = Location("Encounter")
        destination = Location("Destination")
        connect(start, encounter_location)
        connect(encounter_location, destination)

        mover = create_servant("Mover", flexibility=5)
        opponent = create_servant("Opponent", flexibility=3)
        mover.position = start
        opponent.position = encounter_location

        manager = TurnManager()
        manager.characters = [mover, opponent]
        manager.start_turn()
        movement_action = manager.add_movement_action(
            mover,
            [start, encounter_location, destination],
            ap_layer=1,
        )
        return (
            manager,
            mover,
            opponent,
            movement_action,
            encounter_location,
            destination,
        )

    def test_all_continue_resumes_path_before_checkpoint(self):
        (
            manager,
            mover,
            opponent,
            movement_action,
            encounter_location,
            destination,
        ) = self.create_movement_encounter()

        result = manager.execute_action_layer(1)

        self.assertEqual(result["status"], "waiting_for_encounter")
        self.assertIs(mover.position, encounter_location)
        self.assertEqual(manager.completed_checkpoints, [])
        encounter = result["encounters"][0]
        manager.continue_encounter(encounter, mover)
        manager.continue_encounter(encounter, opponent)

        resumed_result = manager.resume_action_layer()

        self.assertIsInstance(resumed_result, list)
        self.assertIs(mover.position, destination)
        self.assertTrue(movement_action.movement_state.finished)
        self.assertEqual(manager.completed_checkpoints, [1])
        self.assertEqual(manager.current_ap_layer, 2)

    def test_declaration_stops_path_at_encounter_then_reaches_checkpoint(self):
        (
            manager,
            mover,
            opponent,
            movement_action,
            encounter_location,
            destination,
        ) = self.create_movement_encounter()
        ap2_move = manager.add_movement_action(
            mover,
            [encounter_location, destination],
            ap_layer=2,
        )

        result = manager.execute_action_layer(1)
        encounter = result["encounters"][0]
        manager.declare_battle(encounter, mover, opponent)
        manager.continue_encounter(encounter, opponent)

        resumed_result = manager.resume_action_layer()

        self.assertIsInstance(resumed_result, list)
        self.assertIs(mover.position, encounter_location)
        self.assertTrue(mover.movement_locked)
        self.assertTrue(opponent.movement_locked)
        self.assertTrue(movement_action.movement_state.finished)
        self.assertTrue(encounter.pending_battle)
        self.assertEqual(manager.completed_checkpoints, [1])

        ap2_result = manager.execute_action_layer(2)
        self.assertTrue(ap2_move.ignored)
        self.assertEqual(
            ap2_result[0][1]["reason"],
            "movement_locked_by_battle_request",
        )

    def test_unresolved_encounter_blocks_checkpoint_and_turn_end(self):
        manager, *_ = self.create_movement_encounter()

        result = manager.execute_action_layer(1)

        self.assertEqual(result["status"], "waiting_for_encounter")
        self.assertEqual(manager.completed_checkpoints, [])
        with self.assertRaises(RuntimeError):
            manager.end_turn()

    def test_checkpoint_lock_blocks_conversion_and_existing_movement_state(self):
        ambusher, target, encounter = self.create_hidden_encounter()
        start = target.position
        exit_location = Location("Exit")
        connect(start, exit_location)

        manager = TurnManager()
        manager.characters = [ambusher, target]
        manager.start_turn()
        manager.declare_battle(encounter, ambusher, target)
        manager.execute_action_layer(1)

        target.movement_point = 1
        state = MovementState(target, [start, exit_location])
        action_points_before = target.action_point
        resolver = MovementResolver()

        self.assertFalse(resolver.can_move(state))
        self.assertFalse(resolver.convert_movement(target))
        self.assertEqual(target.action_point, action_points_before)

    def test_multiple_targets_require_an_explicit_target(self):
        actor = create_servant("Actor")
        first = create_servant("First")
        second = create_servant("Second")
        encounter = Encounter(
            [actor, first, second],
            None,
            [],
            awareness={actor: [first, second]},
        )

        with self.assertRaises(ValueError):
            encounter.choose_battle(actor)

        self.assertTrue(encounter.choose_battle(actor, target=first))
        self.assertIs(encounter.battle_requests[0].target, first)


class EncounterMaintenanceTests(unittest.TestCase):
    def test_perceived_distance_is_cleaned_without_hostile_same_cell(self):
        nodes = [Location(str(index)) for index in range(7)]
        for left, right in zip(nodes, nodes[1:]):
            connect(left, right)
        observer = create_servant("Observer")
        target = create_servant("Target")
        observer.position = nodes[0]
        target.position = nodes[6]
        observer.own_perceived.append(target)

        encounters = MovementResolver().check_encounter(
            [observer, target],
            [],
        )

        self.assertEqual(encounters, [])
        self.assertNotIn(target, observer.perceived)


if __name__ == "__main__":
    unittest.main()
