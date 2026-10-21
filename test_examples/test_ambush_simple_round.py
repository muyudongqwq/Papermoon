import unittest
from unittest.mock import patch

from game.character.servants import Servant
from game.map.map import Location
from game.map.movement import MovementResolver
from game.turn.Turn import TurnManager
from game.turn.battle import BattleManager
from game.turn.decision import ScriptedDecisionProvider


def create_servant(name, flexibility=3, fortune=3, strength=3):
    return Servant(
        name=name,
        strength=strength,
        endurance=5,
        flexibility=flexibility,
        magic=3,
        fortune=fortune,
        servant_class="Saber",
        noble="A",
    )


class DirectionalEncounterTests(unittest.TestCase):
    def test_only_observer_can_decide_and_declaration_creates_ambush_pair(self):
        location = Location("Building", is_building=True)
        ambusher = create_servant("Assassin")
        target = create_servant("Saber")
        ambusher.position = location
        target.position = location
        ambusher.status_flags.add("hidden")

        encounter = MovementResolver().check_encounter(
            [ambusher, target],
            [],
        )[0]

        self.assertEqual(encounter.aware_characters, [ambusher])
        self.assertFalse(encounter.choose_continue(target))
        self.assertFalse(encounter.choose_battle(target))
        self.assertTrue(encounter.choose_battle(ambusher))
        self.assertEqual(encounter.get_ambush_pairs(), [(ambusher, target)])

    def test_battle_waits_for_every_aware_character(self):
        first = create_servant("First")
        second = create_servant("Second")
        target = create_servant("Target")
        from game.map.movement import Encounter

        encounter = Encounter(
            [first, second, target],
            None,
            [],
            awareness={
                first: [target],
                second: [target],
            },
        )
        first.own_visible = [target]

        self.assertTrue(encounter.choose_battle(first))
        self.assertFalse(encounter.resolved)
        self.assertFalse(encounter.pending_battle)
        self.assertTrue(encounter.choose_continue(second))
        self.assertTrue(encounter.resolved)
        self.assertTrue(encounter.pending_battle)
        self.assertEqual(encounter.get_ambush_pairs(), [(first, target)])


class AmbushSimpleRoundTests(unittest.TestCase):
    def test_ambush_adds_five_and_does_not_consume_attack_phase(self):
        location = Location("Building", is_building=True)
        ambusher = create_servant("Assassin", flexibility=5)
        target = create_servant("Saber", flexibility=3)
        ambusher.position = location
        target.position = location
        ambusher.status_flags.add("hidden")
        target.dodge = 100

        encounter = MovementResolver().check_encounter(
            [ambusher, target],
            [],
        )[0]
        encounter.choose_battle(ambusher)

        manager = TurnManager()
        manager.characters = [ambusher, target]
        manager.add_pending_encounter(encounter)
        manager.start_turn()
        battle = manager.battles[0]

        self.assertTrue(target.has_status("ambushed"))
        decisions = ScriptedDecisionProvider([
            "dodge",
            "stay",
            "stay",
        ])
        with patch("game.turn.defense.random.randint", return_value=10):
            self.assertTrue(battle.run_battle_turn(decisions))

        effect = battle.simple_round_history[0]
        expected_roll = (
            effect.attack_event.attack_die
            + ambusher.physical_attack
            + ambusher.dice_bonus
            + 5
            + 15  # 最终骰面10触发大成功。
        )
        self.assertEqual(effect.effect_type, "add_simple_round")
        self.assertEqual(effect.attack_event.attack_roll_bonus, 5)
        self.assertEqual(effect.attack_event.attack_roll, expected_roll)
        # 额外攻防轮不消耗攻击阶段；随后明确选择stay会消耗它。
        self.assertEqual(ambusher.attack_phase_count, 0)
        self.assertFalse(target.has_status("ambushed"))

    def test_multiple_and_reverse_ambushes_use_initiative_actor_order(self):
        target = create_servant("Target", flexibility=1)
        slow = create_servant("Slow", flexibility=2)
        fast = create_servant("Fast", flexibility=5)
        counter = create_servant("Counter", flexibility=4)
        battle = BattleManager([target, slow, fast, counter])
        battle.start_battle()

        for actor, victim in (
            (slow, target),
            (fast, target),
            (counter, fast),
        ):
            battle.add_effect(
                {
                    "effect_type": "add_simple_round",
                    "effect_data": {
                        "trigger_phase": "battle_start",
                        "attack_roll_bonus": 5,
                        "is_ambush": True,
                    },
                },
                actor,
                victim,
            )

        ordered = battle.order_simple_rounds(
            battle.get_simple_rounds(None, "battle_start")
        )
        self.assertEqual(
            [effect.actor.name for effect in ordered],
            ["Fast", "Counter", "Slow"],
        )
        self.assertEqual(
            [effect.target.name for effect in ordered],
            ["Target", "Fast", "Target"],
        )

    def test_skill_can_schedule_a_simple_round_before_a_target_phase(self):
        actor = create_servant("Caster", flexibility=5)
        target = create_servant("Saber", flexibility=3)
        location = Location("Arena")
        actor.position = location
        target.position = location
        target.dodge = 100
        battle = BattleManager([actor, target])
        battle.start_battle()
        effect = battle.add_effect(
            {
                "effect_type": "add_simple_round",
                "effect_data": {
                    "trigger_phase": "attack",
                    "attack_stat": "magic_attack",
                    "damage_value": 20,
                    "damage_type": "magic",
                },
            },
            actor,
            target,
        )

        self.assertEqual(
            battle.get_simple_rounds(target, "attack"),
            [effect],
        )
        self.assertEqual(
            battle.get_simple_rounds(actor, "attack"),
            [],
        )

        decisions = ScriptedDecisionProvider([
            "stay",    # actor待机并结束自己的常规攻击阶段
            "dodge",   # 插入轮中的target防御
            "stay",    # target继续原攻击阶段并待机
        ])
        self.assertTrue(battle.run_battle_turn(decisions))
        self.assertTrue(effect.resolved)
        self.assertEqual(effect.attack_event.damage_type, "magic")
        self.assertEqual(effect.attack_event.value, 20)
        self.assertEqual(actor.attack_phase_count, 0)
        self.assertEqual(
            [request.phase for request in decisions.requests],
            ["攻击", "防御", "攻击"],
        )


class BattleDeathTests(unittest.TestCase):
    def test_die_removes_character_from_battle_and_initiative(self):
        first = create_servant("First", flexibility=5)
        defeated = create_servant("Defeated", flexibility=4)
        third = create_servant("Third", flexibility=3)
        battle = BattleManager([first, defeated, third])
        battle.start_battle()

        defeated.die()

        self.assertNotIn(defeated, battle.participants)
        self.assertNotIn(defeated, battle.current_order)
        self.assertFalse(defeated.in_battle)
        self.assertIsNone(defeated.current_battle)
        self.assertFalse(battle.ended)

    def test_damage_at_exactly_zero_runs_death_chain(self):
        attacker = create_servant("Attacker")
        defeated = create_servant("Defeated")
        battle = BattleManager([attacker, defeated])
        battle.start_battle()
        defeated.brink_of_death_counter = 0
        defeated.hp = 10

        defeated.take_damage(10)

        self.assertTrue(defeated.has_status("dead"))
        self.assertNotIn(defeated, battle.participants)
        self.assertTrue(battle.ended)


class HostileSideBattleEndTests(unittest.TestCase):
    def test_battle_ends_when_only_allies_remain(self):
        first = create_servant("First")
        ally = create_servant("Ally")
        enemy = create_servant("Enemy")
        first.add_ally(ally)
        battle = BattleManager([first, ally, enemy])
        battle.start_battle()

        battle.remove_participant(enemy)

        self.assertTrue(battle.ended)
        self.assertFalse(first.in_battle)
        self.assertFalse(ally.in_battle)

    def test_battle_continues_while_any_hostile_pair_remains(self):
        first = create_servant("First")
        second = create_servant("Second")
        third = create_servant("Third")
        battle = BattleManager([first, second, third])
        battle.start_battle()

        battle.remove_participant(third)

        self.assertFalse(battle.ended)
        self.assertTrue(first.in_battle)
        self.assertTrue(second.in_battle)

    def test_allied_only_battle_ends_during_startup(self):
        first = create_servant("First")
        ally = create_servant("Ally")
        first.add_ally(ally)
        battle = BattleManager([first, ally])

        battle.start_battle()

        self.assertTrue(battle.ended)


if __name__ == "__main__":
    unittest.main()
