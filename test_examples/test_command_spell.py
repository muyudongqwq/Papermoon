import unittest
from unittest.mock import patch

from game.action.action import Action
from game.character.masters import Master
from game.character.servants import Servant
from game.game.command_spell import CommandSpellService
from game.game.game_manager import GameManager
from core.terminal_game_runner import GameTerminalDecisionProvider
from game.map.map import Location
from game.turn.battle import BattleManager
from game.turn.decision import DecisionOption, DecisionRequest
from game.turn.damage import AttackEvent


def master(name="Master"):
    return Master(name, 3, 3, 3, 3, 3, "C", 3)


def servant(name="Servant"):
    return Servant(name, 3, 3, 3, 3, 3, "Saber", "A")


class CommandSpellTests(unittest.TestCase):
    def setUp(self):
        self.a = Location("A")
        self.b = Location("B")
        self.a.add_connection(self.b)
        self.b.add_connection(self.a)
        self.master = master()
        self.servant = servant()
        self.master.add_servant(self.servant)
        self.master.position = self.servant.position = self.a
        self.game = GameManager([self.master, self.servant], self.a)
        self.game.start_game()
        self.service = CommandSpellService(self.game)

    def test_temporary_mp_is_spent_before_ordinary_mp(self):
        self.servant.mp = 10
        self.assertTrue(self.service.grant_temporary_mp(
            self.master,
            self.servant,
        ))
        ledger = self.servant.pay_mp_with_ledger(50)
        self.assertEqual(self.servant.temporary_mp, 40)
        self.assertEqual(self.servant.mp, 10)
        self.assertEqual(ledger[0]["pool"], "temporary_mp")

    def test_damage_bonus_stacks_and_is_consumed_by_next_attack(self):
        enemy = master("Enemy")
        enemy.position = self.a
        self.game.characters.append(enemy)
        self.game.turn_manager.characters.append(enemy)
        self.servant.update_visibility(self.game.characters)
        self.assertTrue(self.service.grant_damage_bonus(self.master, self.servant))
        self.assertTrue(self.service.grant_damage_bonus(self.master, self.servant))
        action = Action(self.servant, "attack", enemy)
        action.ignore_attack_phase_count = True
        self.assertTrue(action.attack())
        self.assertIn(180, action.created_attack_event.flat_modifiers)
        self.assertEqual(self.servant.command_spell_damage_bonus, 0)

    def test_seen_locations_are_shared_but_perception_is_not_required(self):
        self.servant.position = self.b
        self.master.update_visibility(self.game.characters)
        self.assertIn(self.b, self.master.seen_locations)
        self.assertIn(self.a, self.servant.seen_locations)

    def test_teleport_out_of_battle_converts_remaining_attack_phase(self):
        enemy = master("Enemy")
        enemy.position = self.a
        self.game.characters.append(enemy)
        self.game.turn_manager.characters.append(enemy)
        battle = BattleManager([self.servant, enemy])
        self.game.turn_manager.battles.append(battle)
        battle.start_battle()
        self.servant.seen_locations.add(self.b)
        self.assertTrue(self.service.teleport(self.master, self.servant, self.b))
        self.assertFalse(self.servant.in_battle)
        self.assertEqual(self.servant.action_point, 2)
        self.assertIs(self.servant.position, self.b)

    def test_teleport_interrupts_casting(self):
        class FakeCastingState:
            def __init__(state, actor):
                state.actor = actor
                state.reason = None

            def interrupt(state, reason="manual"):
                state.reason = reason
                state.actor.casting_state = None
                return []

        state = FakeCastingState(self.servant)
        self.servant.casting_state = state
        self.servant.seen_locations.add(self.b)

        self.assertTrue(self.service.teleport(
            self.master,
            self.servant,
            self.b,
        ))
        self.assertIsNone(self.servant.casting_state)
        self.assertEqual(state.reason, "command_spell_teleport")

    def test_any_master_can_use_command_spell_during_another_turn(self):
        observer = master("Observer")
        observer.position = self.a
        self.game.characters.append(observer)
        commands = iter(["commandspell", "1", "1", "1", "1"])
        provider = GameTerminalDecisionProvider(
            self.game,
            input_func=lambda _prompt: next(commands),
            output_func=lambda _message: None,
        )
        result = provider.choose(DecisionRequest(
            character=observer,
            phase="测试",
            prompt="",
            options=(DecisionOption("继续", "ok", ("continue",)),),
        ))
        self.assertEqual(result, "ok")
        self.assertEqual(self.master.command_spell, 2)
        self.assertEqual(self.master.temporary_mp, 90)

    def test_teleported_non_attacker_still_gets_guard_phase(self):
        enemy = master("Enemy")
        ally = master("Ally")
        enemy.position = ally.position = self.b
        ally.add_ally(self.servant)
        self.game.characters.extend([enemy, ally])
        self.game.turn_manager.characters.extend([enemy, ally])
        destination_battle = BattleManager([enemy, ally])
        self.game.turn_manager.battles.append(destination_battle)
        destination_battle.start_battle()
        destination_battle.current_character = None
        destination_battle.current_phase = "round_ended"

        self.game.turn_manager.map_phase_started = True
        self.game.turn_manager.current_ap_layer = 2
        self.game.turn_manager.completed_checkpoints = [1]
        self.servant.seen_locations.add(self.b)

        self.assertTrue(self.service.teleport(self.master, self.servant, self.b))
        self.assertEqual(self.servant.attack_phase_count, 0)
        self.assertIs(destination_battle.current_character, self.servant)
        self.assertEqual(destination_battle.current_phase, "turn_start")
        self.assertIn(self.servant, destination_battle.late_participants)

    def test_teleport_forces_emergency_guard_for_all_pending_attacks(self):
        enemy = master("Enemy")
        self.master.position = enemy.position = self.b
        self.game.characters.append(enemy)
        self.game.turn_manager.characters.append(enemy)
        battle = BattleManager([self.master, enemy])
        self.game.turn_manager.battles.append(battle)
        battle.start_battle()
        attacks = [
            AttackEvent(enemy, self.master, 10, "physical", 100, None),
            AttackEvent(enemy, self.master, 10, "physical", 100, None),
        ]
        self.master.pending_attacks.extend(attacks)
        self.servant.seen_locations.add(self.b)
        hp_before = self.servant.hp

        self.assertTrue(self.service.teleport(
            self.master,
            self.servant,
            self.b,
            emergency_guard_target=self.master,
        ))
        self.assertFalse(self.servant.guard_opportunity_available)
        self.assertIn(self.servant, battle.guarded_this_round)
        self.assertEqual(self.master.pending_attacks, [])
        self.assertEqual(self.servant.hp, hp_before - 10)
        self.assertTrue(all(attack.resolved for attack in attacks))

    def test_teleport_can_decline_emergency_guard(self):
        enemy = master("Enemy")
        self.master.position = enemy.position = self.b
        self.game.characters.append(enemy)
        self.game.turn_manager.characters.append(enemy)
        battle = BattleManager([self.master, enemy])
        self.game.turn_manager.battles.append(battle)
        battle.start_battle()
        attack = AttackEvent(
            enemy,
            self.master,
            10,
            "physical",
            100,
            None,
        )
        self.master.pending_attacks.append(attack)
        self.servant.seen_locations.add(self.b)

        self.assertTrue(self.service.teleport(self.master, self.servant, self.b))
        self.assertIn(attack, self.master.pending_attacks)
        self.assertTrue(self.servant.guard_opportunity_available)
        self.assertNotIn(self.servant, battle.guarded_this_round)

    def test_target_locked_attack_follows_command_spell_teleport(self):
        enemy = master("Enemy")
        enemy.position = self.a
        self.game.characters.append(enemy)
        self.game.turn_manager.characters.append(enemy)
        battle = BattleManager([self.servant, enemy])
        self.game.turn_manager.battles.append(battle)
        battle.start_battle()
        attack = AttackEvent(
            enemy,
            self.servant,
            10,
            "physical",
            100,
            None,
            target_lock=True,
        )
        self.servant.pending_attacks.append(attack)
        self.servant.seen_locations.add(self.b)

        with patch.object(
            battle,
            "resolve_simple_round_attack_events",
            return_value={"results": []},
        ) as resolve:
            self.assertTrue(self.service.teleport(
                self.master,
                self.servant,
                self.b,
            ))

        self.assertFalse(attack.resolved)
        self.assertIn(attack, self.servant.pending_attacks)
        resolve.assert_called_once_with([attack], None)


if __name__ == "__main__":
    unittest.main()
