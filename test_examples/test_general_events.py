import unittest
from unittest.mock import patch

from game.character.masters import Master
from game.game.game_manager import GameManager
from game.map.map import Location
from game.map.movement import MovementResolver, MovementState
from game.turn.damage import AttackProfile
from game.turn.decision import ScriptedDecisionProvider
from game.turn.defense import DefenseResolver
from game.turn.roll import RollResolver


def make_master(name, *, fortune=3):
    return Master(name, 3, 3, 3, 3, fortune, "C", 3)


class GeneralEventTests(unittest.TestCase):
    def setUp(self):
        self.a = Location("A")
        self.b = Location("B")
        self.a.add_connection(self.b)
        self.b.add_connection(self.a)
        self.actor = make_master("Actor", fortune=5)
        self.target = make_master("Target")
        self.actor.position = self.a
        self.target.position = self.b
        self.game = GameManager([self.actor, self.target], self.a)
        self.game.start_game()
        self.game.turn_manager.turn = 1
        self.game.event_manager.history.clear()

    def events(self, event_type):
        return [
            event
            for event in self.game.event_manager.history
            if event.event_type == event_type
        ]

    def test_path_movement_emits_step_and_completion(self):
        self.actor.movement_point = 1
        state = MovementState(self.actor, [self.a, self.b])

        self.assertTrue(MovementResolver().step(state))

        step = self.events("movement_step")[-1]
        completed = self.events("movement_completed")[-1]
        self.assertIs(step.target, self.actor)
        self.assertEqual(step.value, 1)
        self.assertEqual(step.payload["origin_name"], "A")
        self.assertEqual(step.payload["destination_name"], "B")
        self.assertEqual(completed.value, 1)
        self.assertEqual(completed.payload["step_index"], 1)

    def test_roll_emits_each_raw_die_and_final_result(self):
        self.actor.start_battle()
        decisions = ScriptedDecisionProvider(["reroll", "confirm"])
        rolls = iter([2, 7])

        result = RollResolver().roll(
            self.actor,
            "physical_attack",
            decision_provider=decisions,
            roller=lambda: next(rolls),
        )

        raw = self.events("raw_die_generated")
        self.assertEqual([event.value for event in raw], [2, 7])
        self.assertEqual(
            [event.payload["reason"] for event in raw],
            ["initial", "reroll"],
        )
        resolved = self.events("roll_resolved")[-1]
        self.assertEqual(resolved.value, result.total)
        self.assertEqual(resolved.payload["die"], 7)

    def test_defense_emits_one_resolved_event_per_attack(self):
        profile = AttackProfile(
            source=self.actor,
            value=20,
            damage_type="physical",
            attack_roll=10,
        )
        attack = profile.assign_target(self.target)

        with patch("game.turn.defense.random.randint", return_value=5):
            result = DefenseResolver().resolve_attack(
                self.target,
                attack,
                "dodge",
            )

        event = self.events("defense_resolved")[-1]
        self.assertIs(event.target, self.target)
        self.assertEqual(event.value, result["damage"])
        self.assertEqual(event.payload["defense_type"], "dodge")
        self.assertEqual(event.payload["hit"], result["hit"])

    def test_attack_target_change_records_old_and_new_target(self):
        profile = AttackProfile(
            source=self.actor,
            value=20,
            damage_type="physical",
            attack_roll=10,
        )
        attack = profile.assign_target(self.target)

        self.assertTrue(attack.change_target(self.actor, reason="test_redirect"))

        event = self.events("attack_target_changed")[-1]
        self.assertIs(event.target, self.actor)
        self.assertIs(event.payload["old_target"], self.target)
        self.assertIs(event.payload["new_target"], self.actor)
        self.assertEqual(event.payload["reason"], "test_redirect")


if __name__ == "__main__":
    unittest.main()
