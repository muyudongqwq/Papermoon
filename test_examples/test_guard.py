import unittest

from game.character.servants import Servant
from game.map.map import Location
from game.turn.battle import BattleManager
from game.turn.damage import AttackEvent
from game.turn.decision import ScriptedDecisionProvider


def create_servant(name, strength=3, endurance=3, flexibility=3):
    return Servant(
        name=name,
        strength=strength,
        endurance=endurance,
        flexibility=flexibility,
        magic=3,
        fortune=3,
        servant_class="Saber",
        noble="A",
    )


def create_battle(*characters):
    location = Location("Arena")
    for character in characters:
        character.position = location
    battle = BattleManager(list(characters))
    battle.start_battle()
    return battle


def pending_attack(source, target, value, attack_roll=100):
    return AttackEvent(
        source=source,
        target=target,
        value=value,
        damage_type="physical",
        attack_roll=attack_roll,
        skill=None,
    )


class GuardTests(unittest.TestCase):
    def test_guard_phase_runs_before_own_defense_phase(self):
        guarder = create_servant("Guarder", flexibility=10)
        target = create_servant("Target", flexibility=5)
        attacker = create_servant("Attacker", flexibility=3)
        battle = create_battle(guarder, target, attacker)
        target.pending_attacks.append(
            pending_attack(attacker, target, 10, attack_roll=0)
        )
        decisions = ScriptedDecisionProvider([
            "Target",
            "stay",
            "stay",
            "stay",
        ])

        self.assertTrue(battle.run_battle_turn(decisions))

        self.assertEqual(target.pending_attacks, [])
        self.assertEqual(
            [request.phase for request in decisions.requests[:2]],
            ["援护目标选择", "攻击"],
        )
        self.assertIs(battle.guard_history[0]["guarder"], guarder)
        self.assertIs(battle.guard_history[0]["target"], target)

    def test_default_guard_target_limit_is_one_and_can_be_modified(self):
        guarder = create_servant("Guarder")
        first = create_servant("First")
        second = create_servant("Second")
        attacker = create_servant("Attacker")
        battle = create_battle(guarder, first, second, attacker)
        first.pending_attacks.append(pending_attack(attacker, first, 10))
        second.pending_attacks.append(pending_attack(attacker, second, 10))

        self.assertEqual(guarder.guard_target_limit, 1)
        selected = battle.request_guard_targets(
            guarder,
            ScriptedDecisionProvider(["First"]),
        )
        self.assertEqual(selected, [first])

        guarder.guard_target_limit = 2
        selected = battle.request_guard_targets(
            guarder,
            ScriptedDecisionProvider(["First", "Second"]),
        )
        self.assertEqual(selected, [first, second])

    def test_guard_resolves_attacks_in_queue_order(self):
        guarder = create_servant("Guarder", flexibility=10)
        target = create_servant("Target")
        attacker = create_servant("Attacker")
        battle = create_battle(guarder, target, attacker)
        first = pending_attack(attacker, target, 10, attack_roll=0)
        second = pending_attack(attacker, target, 20, attack_roll=0)
        target.pending_attacks.extend([first, second])

        record = battle.resolve_guard(
            guarder,
            target,
            ScriptedDecisionProvider([]),
        )

        self.assertEqual(
            [item["attack"] for item in record["results"]],
            [first, second],
        )
        self.assertEqual(target.pending_attacks, [])
        self.assertTrue(all(
            item["defense"] == "block"
            for item in record["results"]
        ))

    def test_new_brink_stops_guard_and_leaves_residual_at_queue_front(self):
        guarder = create_servant("Guarder")
        target = create_servant("Target")
        attacker = create_servant("Attacker")
        battle = create_battle(guarder, target, attacker)
        guarder.hp = 10
        first = pending_attack(attacker, target, 50)
        second = pending_attack(attacker, target, 20)
        target.pending_attacks.extend([first, second])

        record = battle.resolve_guard(
            guarder,
            target,
            ScriptedDecisionProvider([]),
        )

        self.assertTrue(guarder.has_status("brink_of_death"))
        self.assertEqual(len(record["results"]), 1)
        self.assertEqual(first.value, 16)
        self.assertFalse(first.resolved)
        self.assertEqual(target.pending_attacks, [first, second])

    def test_next_guard_can_continue_the_remaining_queue(self):
        first_guard = create_servant("FirstGuard")
        second_guard = create_servant("SecondGuard", flexibility=10)
        target = create_servant("Target")
        attacker = create_servant("Attacker")
        battle = create_battle(first_guard, second_guard, target, attacker)
        first_guard.hp = 10
        first = pending_attack(attacker, target, 50)
        second = pending_attack(attacker, target, 20)
        target.pending_attacks.extend([first, second])

        battle.resolve_guard(
            first_guard,
            target,
            ScriptedDecisionProvider([]),
        )
        battle.resolve_guard(
            second_guard,
            target,
            ScriptedDecisionProvider([]),
        )

        self.assertEqual(target.pending_attacks, [])

    def test_existing_brink_status_forbids_guard(self):
        guarder = create_servant("Guarder")
        target = create_servant("Target")
        attacker = create_servant("Attacker")
        battle = create_battle(guarder, target, attacker)
        target.pending_attacks.append(pending_attack(attacker, target, 10))
        guarder.status_flags.add("brink_of_death")

        self.assertEqual(battle.get_guard_targets(guarder), [])
        self.assertIsNone(
            battle.resolve_guard(
                guarder,
                target,
                ScriptedDecisionProvider([]),
            )
        )

    def test_guard_block_overrides_random_defense(self):
        guarder = create_servant("Guarder")
        target = create_servant("Target")
        attacker = create_servant("Attacker")
        battle = create_battle(guarder, target, attacker)
        target.pending_attacks.append(pending_attack(attacker, target, 10))
        guarder.status_flags.add("random_defense")

        record = battle.resolve_guard(
            guarder,
            target,
            ScriptedDecisionProvider([]),
        )

        self.assertEqual(record["results"][0]["defense"], "block")


if __name__ == "__main__":
    unittest.main()
