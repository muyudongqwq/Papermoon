import unittest

from game.character.masters import Master
from game.game.game_manager import GameManager
from core.terminal_game_runner import (
    GameTerminalDecisionProvider,
    TerminalGameRunner,
)
from game.map.map import Location
from game.turn.decision import DecisionOption, DecisionRequest, ScriptedDecisionProvider


def create_master(name):
    return Master(name, 3, 3, 3, 3, 3, "C", 3)


class TerminalGameRunnerTests(unittest.TestCase):
    def test_free_protection_returns_to_same_ap_selection(self):
        location = Location("A")
        actor = create_master("Actor")
        target = create_master("Target")
        actor.position = target.position = location
        actor.load_basic_magic("protection")
        game = GameManager([actor, target], location)
        game.start_game()
        provider = ScriptedDecisionProvider([
            "防护",
            "Target",
            10,
            "pass",
            "pass",
            "pass",
            "pass",
        ])
        runner = TerminalGameRunner(game, provider)

        game.turn_manager.start_turn()
        game.turn_manager.non_battle_order = [actor, target]
        runner.collect_map_actions()

        self.assertEqual(target.shield, 15)
        self.assertEqual(actor.mp, actor.mpmax - 10)
        self.assertEqual(
            game.turn_manager._get_submitted_action(actor, 1).action_id,
            "pass",
        )

    def test_personal_active_skill_appears_and_executes_in_ap_terminal_flow(self):
        location = Location("A")
        actor = create_master("Actor")
        other = create_master("Other")
        actor.position = other.position = location
        actor.create_personal_skill({
            "skill_id": "self_enhancement",
            "name": "自我强化",
            "rank": "C",
            "components": [{
                "component_id": "active",
                "type": "active",
                "available_phases": ["AP1"],
                "target": "self",
                "cost": [{"resource": "action_point", "value": 1}],
                "effects": [{
                    "modifier_id": "terminal_skill_bonus",
                    "effect_type": "numeric_attribute_bonus",
                    "polarity": "buff",
                    "duration": 3,
                    "effect_data": {
                        "effect_target": "dice_bonus",
                        "value": 2,
                    },
                }],
            }],
        })
        game = GameManager([actor, other], location)
        game.start_game()
        provider = ScriptedDecisionProvider([
            "自我强化",
            "pass",
            "pass",
            "pass",
        ])
        runner = TerminalGameRunner(game, provider)

        game.turn_manager.start_turn()
        game.turn_manager.non_battle_order = [actor, other]
        runner.collect_map_actions()
        runner.execute_map_actions()

        self.assertEqual(actor.action_point, 0)
        self.assertEqual(actor.dice_bonus, 2)
        action_labels = [
            option.label
            for request in provider.requests
            for option in getattr(request, "options", [])
        ]
        self.assertIn("自我强化", action_labels)

    def test_two_ap_personal_skill_reserves_ap2_in_terminal_flow(self):
        location = Location("A")
        actor = create_master("Actor")
        other = create_master("Other")
        actor.position = other.position = location
        actor.create_personal_skill({
            "skill_id": "full_turn_skill",
            "name": "整回合强化",
            "rank": "B",
            "components": [{
                "component_id": "active",
                "type": "active",
                "available_phases": ["AP1"],
                "target": "self",
                "cost": [{"resource": "action_point", "value": 2}],
                "effects": [{
                    "modifier_id": "full_turn_bonus",
                    "effect_type": "numeric_attribute_bonus",
                    "polarity": "buff",
                    "duration": 3,
                    "effect_data": {
                        "effect_target": "dice_bonus",
                        "value": 3,
                    },
                }],
            }],
        })
        game = GameManager([actor, other], location)
        game.start_game()
        provider = ScriptedDecisionProvider([
            "整回合强化",
            "pass",
            "pass",
        ])
        runner = TerminalGameRunner(game, provider)

        game.turn_manager.start_turn()
        game.turn_manager.non_battle_order = [actor, other]
        runner.collect_map_actions()
        self.assertIn(actor, game.turn_manager.layer_actors[2])
        runner.execute_map_actions()

        self.assertEqual(actor.action_point, 0)
        self.assertEqual(actor.dice_bonus, 3)

    def test_runner_collects_both_ap_actions_and_reaches_turn_limit(self):
        location = Location("A")
        first = create_master("First")
        second = create_master("Second")
        first.position = second.position = location
        game = GameManager(
            [first, second],
            location,
            maximum_turns=1,
        )
        provider = ScriptedDecisionProvider([
            "pass",
            "pass",
            "pass",
            "pass",
        ])

        result = TerminalGameRunner(game, provider).run()

        self.assertEqual(result["reason"], "turn_limit")
        self.assertEqual(result["turn"], 1)
        self.assertEqual(len(provider.requests), 4)
        self.assertTrue(first.has_status("dead"))
        self.assertTrue(second.has_status("dead"))

    def test_status_command_does_not_consume_current_decision(self):
        location = Location("A")
        master = create_master("Master")
        master.position = location
        game = GameManager([master], location)
        game.start_game()
        commands = iter(["status", "1"])
        output = []
        provider = GameTerminalDecisionProvider(
            game,
            input_func=lambda _prompt: next(commands),
            output_func=output.append,
        )
        request = DecisionRequest(
            master,
            "AP1",
            "",
            (DecisionOption("空过", "pass", ("pass",)),),
        )

        self.assertEqual(provider.choose(request), "pass")
        self.assertTrue(any("HP" in line for line in output))
        self.assertGreaterEqual(output.count("可用行动："), 2)

    def test_position_command_returns_current_position(self):
        location = Location("住宅区A")
        master = create_master("Master")
        master.position = location
        game = GameManager([master], location)
        game.start_game()
        commands = iter(["position", "1"])
        output = []
        provider = GameTerminalDecisionProvider(
            game,
            input_func=lambda _prompt: next(commands),
            output_func=output.append,
        )
        request = DecisionRequest(
            master,
            "AP1",
            "",
            (DecisionOption("空过", "pass", ("pass",)),),
        )

        self.assertEqual(provider.choose(request), "pass")
        self.assertIn("位置：住宅区A", output)

    def test_target_back_returns_to_action_selection(self):
        location = Location("A")
        target_location = Location("B")
        actor = create_master("Actor")
        target = create_master("Target")
        actor.position = location
        target.position = target_location
        game = GameManager([actor, target], location)
        game.start_game()
        manager = game.turn_manager
        manager.turn = 1
        manager.start_action_layers()
        manager.non_battle_order = [actor, target]
        actor.update_visibility(game.characters)
        actor.own_visible = [target]
        provider = ScriptedDecisionProvider([
            "direct_attack",
            "back",
            "pass",
        ])
        runner = TerminalGameRunner(game, provider)

        action = runner.collect_character_action(actor, 1)

        self.assertEqual(action.action_id, "pass")
        self.assertEqual(len(manager.action_layers[1]), 1)

    def test_status_places_hostile_visibility_after_servant_class(self):
        from game.character.servants import Servant

        location = Location("A")
        actor = Servant("Saber", 3, 3, 3, 3, 3, "Saber", "A")
        visible = create_master("Visible")
        perceived = create_master("Perceived")
        actor.position = visible.position = perceived.position = location
        actor.any_visible = [visible, perceived]
        actor.perceived = [perceived]
        game = GameManager([actor, visible, perceived], location)
        output = []
        provider = GameTerminalDecisionProvider(
            game,
            input_func=lambda _prompt: "1",
            output_func=output.append,
        )

        provider.command_handler.show_character(actor)

        self.assertIn(
            "职介：Saber（可见：[Visible, Perceived]，感知：[Perceived]）",
            output[0],
        )

    def test_action_separator_outputs_blank_line(self):
        location = Location("A")
        master = create_master("Master")
        game = GameManager([master], location)
        output = []
        provider = GameTerminalDecisionProvider(
            game,
            input_func=lambda _prompt: "1",
            output_func=output.append,
        )

        provider.separate_action()

        self.assertEqual(output, [""])

    def test_game_end_outputs_reason_and_victory_winners(self):
        location = Location("Grail")
        master = create_master("Winner")
        game = GameManager([master], location)
        output = []
        provider = GameTerminalDecisionProvider(
            game,
            input_func=lambda _prompt: "quit",
            output_func=output.append,
        )
        runner = TerminalGameRunner(game, provider)
        game.start_game()
        game.end_game(reason="victory", winners=[master])

        runner.run()

        self.assertIn("游戏结束原因：victory", output)
        self.assertIn("胜利者：Winner", output)

    def test_manual_quit_outputs_reason_without_winner_line(self):
        location = Location("A")
        master = create_master("Master")
        master.position = location
        game = GameManager([master], location)
        output = []
        commands = iter(["quit"])
        provider = GameTerminalDecisionProvider(
            game,
            input_func=lambda _prompt: next(commands),
            output_func=output.append,
        )

        TerminalGameRunner(game, provider).run()

        self.assertIn("游戏结束原因：manual_quit", output)
        self.assertFalse(any(line.startswith("胜利者：") for line in output))

    def test_movement_path_prompt_omits_turn_and_character_header(self):
        location = Location("A")
        road = Location("道路AB")
        location.add_connection(road)
        road.add_connection(location)
        master = create_master("Master")
        master.position = location
        game = GameManager([master], location)
        output = []
        provider = GameTerminalDecisionProvider(
            game,
            input_func=lambda _prompt: "1",
            output_func=output.append,
        )
        request = DecisionRequest(
            master,
            "move_path",
            "",
            (DecisionOption(road.name, road),),
        )

        self.assertIs(provider.choose(request), road)
        self.assertEqual(output, ["可选道路：", "1.道路AB"])

    def test_escape_actor_plans_ap1_and_ap2_with_other_map_characters(self):
        start = Location("A")
        destination = Location("B")
        start.add_connection(destination)
        destination.add_connection(start)
        escaped = create_master("Escaped")
        other = create_master("Other")
        escaped.position = other.position = start
        game = GameManager([escaped, other], start)
        game.start_game()
        manager = game.turn_manager
        manager.turn = 3
        escaped.current_global_turn = 3
        escaped.forced_move_turn = 3
        manager.start_action_layers()
        manager.non_battle_order = [escaped, other]
        provider = ScriptedDecisionProvider([
            "move",
            "B",
            "finish",
            "pass",
            "pass",
            "pass",
        ])
        runner = TerminalGameRunner(game, provider)

        runner.collect_map_actions()

        self.assertEqual(len(manager.action_layers[1]), 2)
        self.assertEqual(len(manager.action_layers[2]), 2)
        self.assertEqual(manager.action_layers[1][0].action_id, "move")
        self.assertEqual(manager.action_layers[2][0].action_id, "pass")


if __name__ == "__main__":
    unittest.main()
