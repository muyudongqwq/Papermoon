import unittest
from unittest.mock import patch

from game.character.masters import Master
from game.game.game_loop import GameLoop
from game.game.game_manager import GameManager
from core.terminal_game_runner import TerminalGameRunner
from game.map.map import Location
from game.turn.battle import BattleManager
from game.turn.decision import DecisionRefreshRequested, ScriptedDecisionProvider


def master(name, flexibility=3):
    return Master(name, 3, 3, flexibility, 3, 3, "C", 3)


class GameLoopTests(unittest.TestCase):
    def movement_game(self):
        start, meeting, destination = [Location(name) for name in ("A", "B", "C")]
        for left, right in ((start, meeting), (meeting, destination)):
            left.add_connection(right)
            right.add_connection(left)
        mover = master("Mover", flexibility=5)
        other = master("Other")
        mover.position = start
        other.position = meeting
        game = GameManager([mover, other], start)
        return game, mover, other, start, meeting, destination

    def test_scripted_loop_completes_game_without_terminal_input(self):
        location = Location("A")
        first, second = master("First", flexibility=5), master("Second")
        first.position = second.position = location
        game = GameManager([first, second], location, maximum_turns=1)
        provider = ScriptedDecisionProvider(["pass"] * 4)

        with patch("builtins.input", side_effect=AssertionError("terminal input")):
            result = GameLoop(game, provider).run()

        self.assertEqual(result, {"reason": "turn_limit", "winners": [], "turn": 1})
        self.assertIs(game.decision_provider, provider)
        self.assertEqual(
            [(request.character.name, request.phase) for request in provider.requests],
            [("First", "AP1"), ("First", "AP2"), ("Second", "AP1"), ("Second", "AP2")],
        )
        self.assertTrue(all(actor.has_status("dead") for actor in (first, second)))

    def test_encounter_resume_has_same_outcome_in_loop_and_terminal(self):
        outcomes = []
        for runner_type in (GameLoop, TerminalGameRunner):
            with self.subTest(runner=runner_type.__name__):
                game, mover, other, _, meeting, destination = self.movement_game()
                provider = ScriptedDecisionProvider([
                    "move", "B", "C", "pass",
                    "pass", "pass", "continue", "continue",
                ])
                runner = runner_type(game, provider)
                game.start_game()

                with patch("builtins.input", side_effect=AssertionError("terminal input")):
                    self.assertTrue(runner.run_global_turn())

                self.assertIs(mover.position, destination)
                self.assertIs(other.position, meeting)
                self.assertEqual(game.turn_manager.completed_checkpoints, [1, 2])
                self.assertEqual(mover.action_point, 0)
                self.assertEqual(other.action_point, 0)
                self.assertEqual(provider.command_index, len(provider.commands))
                encounter_requests = [
                    request for request in provider.requests
                    if any("continue" in option.aliases for option in request.options)
                ]
                self.assertEqual(len(encounter_requests), 2)
                outcomes.append([
                    (request.character.name, request.phase,
                     tuple(option.label for option in request.options))
                    for request in provider.requests
                ])
        self.assertEqual(len(outcomes), 2)
        self.assertEqual(outcomes[0], outcomes[1])

    def test_encounter_can_replace_preplanned_ap2_movement(self):
        game, mover, _, start, meeting, _ = self.movement_game()
        provider = ScriptedDecisionProvider([
            "move", "B", "C", "pass",
            "pass", "pass", "replan", "move", "A", "finish", "continue",
        ])
        loop = GameLoop(game, provider)
        game.start_game()

        game.turn_manager.start_turn()
        loop.collect_map_actions()
        loop.execute_map_actions()

        self.assertIs(mover.position, start)
        self.assertEqual(game.turn_manager.completed_checkpoints, [1, 2])
        replacement = game.turn_manager._get_submitted_action(mover, 2)
        self.assertEqual(replacement.action_id, "move")
        self.assertEqual(replacement.path, [meeting, start])
        self.assertEqual(provider.command_index, len(provider.commands))

    def test_battle_runs_before_map_and_all_stay_releases_only_ap2_next_turn(self):
        location = Location("A")
        first, second, observer = (
            master("First", flexibility=5),
            master("Second", flexibility=4),
            master("Observer"),
        )
        for actor in (first, second, observer):
            actor.position = location
        game = GameManager([first, second, observer], location)
        provider = ScriptedDecisionProvider(["stay", "stay"] + ["pass"] * 6)
        loop = GameLoop(game, provider)
        game.start_game()
        battle = BattleManager([first, second])
        game.turn_manager.battles.append(battle)
        battle.start_battle()

        loop.run_global_turn()

        self.assertTrue(battle.all_stayed_last_round)
        self.assertTrue(first.in_battle)
        first_round = [(request.character.name, request.phase) for request in provider.requests]
        self.assertEqual(first_round[-2:], [("Observer", "AP1"), ("Observer", "AP2")])
        self.assertFalse(any(phase.startswith("AP") for _, phase in first_round[:-2]))

        loop.run_global_turn()

        self.assertTrue(battle.ended)
        self.assertFalse(first.in_battle)
        self.assertFalse(second.in_battle)
        self.assertEqual(
            [(request.character.name, request.phase) for request in provider.requests[len(first_round):]],
            [("First", "AP2"), ("Second", "AP2"), ("Observer", "AP1"), ("Observer", "AP2")],
        )
        self.assertEqual(provider.command_index, len(provider.commands))

    def test_decision_refresh_rebuilds_legal_actions(self):
        location = Location("A")
        actor = master("Actor")
        actor.position = location
        actor.load_basic_magic("protection")
        actor.mp = 0
        game = GameManager([actor], location)

        class RefreshingProvider(ScriptedDecisionProvider):
            def choose(self, request):
                if not self.requests:
                    self.requests.append(request)
                    actor.grant_temporary_mp(90)
                    raise DecisionRefreshRequested()
                return super().choose(request)

        provider = RefreshingProvider(["防护", "Actor", 10, "pass"])
        loop = GameLoop(game, provider)
        game.start_game()
        game.turn_manager.start_turn()

        action = loop.collect_character_action(actor, 1)

        self.assertEqual(action.action_id, "pass")
        self.assertNotIn("防护", [option.label for option in provider.requests[0].options])
        self.assertIn("防护", [option.label for option in provider.requests[1].options])
        self.assertEqual(actor.shield, 15)
        self.assertEqual(actor.temporary_mp, 80)
        self.assertEqual(actor.mp, 0)

    def test_already_ended_game_preserves_result_without_new_decisions(self):
        location = Location("A")
        winner = master("Winner")
        game = GameManager([winner], location)
        game.start_game()
        game.end_game(reason="victory", winners=[winner])
        provider = ScriptedDecisionProvider([])
        loop = GameLoop(game, provider)

        result = loop.run()
        result["winners"].clear()

        self.assertEqual(loop.get_result(), {"reason": "victory", "winners": [winner], "turn": 0})
        self.assertFalse(loop.run_global_turn())
        self.assertEqual(provider.requests, [])


if __name__ == "__main__":
    unittest.main()
