import unittest
from unittest.mock import patch

from game.character.servants import Servant
from game.map.map import Location
from game.modifier.modifier import create_modifier
from game.skill.effect_validation import validate_effect_definition
from game.turn.battle import BattleManager
from game.turn.damage import AttackEvent
from game.turn.decision import ScriptedDecisionProvider
from game.turn.defense import DefenseResolver, OffsetAttempt


def servant(name):
    return Servant(name, 3, 3, 3, 3, 3, "Saber", "A")


def flow_effect(steps, operation="append"):
    return {
        "modifier_id": "test_defense_flow",
        "effect_type": "defense_flow_modifier",
        "polarity": "buff",
        "duration": 2,
        "effect_data": {
            "calculation": operation,
            "steps": steps,
        },
    }


class DefenseFlowModifierTests(unittest.TestCase):
    def prepare(self, steps, operation="append"):
        attacker = servant("Attacker")
        defender = servant("Defender")
        location = Location("Arena")
        attacker.position = defender.position = location
        battle = BattleManager([attacker, defender])
        battle.start_battle()
        battle.current_phase = "defense"
        effect = flow_effect(steps, operation)
        defender.add_modifier(create_modifier(effect, defender))
        attack = AttackEvent(
            attacker,
            defender,
            30,
            "physical",
            50,
            None,
        )
        defender.pending_attacks.append(attack)
        return attacker, defender, battle, attack

    def test_validation_accepts_ordered_steps(self):
        effect = flow_effect([
            {
                "selection_mode": "fixed",
                "defense_types": ["block"],
                "continue_on": "always",
            },
            {
                "selection_mode": "defender_choice",
                "defense_types": ["dodge", "offset"],
                "on_unavailable": "skip",
            },
        ], operation="replace")

        self.assertTrue(validate_effect_definition(effect))

    def test_validation_rejects_fixed_step_with_multiple_types(self):
        effect = flow_effect([{
            "selection_mode": "fixed",
            "defense_types": ["block", "dodge"],
        }])

        with self.assertRaisesRegex(ValueError, "fixed步骤"):
            validate_effect_definition(effect)

    def test_failed_block_can_continue_to_successful_dodge(self):
        _, defender, battle, attack = self.prepare([
            {
                "selection_mode": "fixed",
                "defense_types": ["block"],
            },
            {
                "selection_mode": "fixed",
                "defense_types": ["dodge"],
            },
        ], operation="replace")
        defender.attack_phase_count = 1

        self.assertEqual(
            battle.request_defense(defender, ScriptedDecisionProvider([])),
            "unopposed",
        )

        with patch.object(
            DefenseResolver,
            "roll_defense",
            side_effect=[(1, 0), (10, 100)],
        ):
            result = DefenseResolver().resolve_phase(
                defender,
                "block",
                attacks=[attack],
            )

        self.assertEqual(result["total_damage"], 0)
        self.assertFalse(attack.hit)
        self.assertEqual(defender.attack_phase_count, 0)
        self.assertEqual(
            [step["defense_type"] for step in attack.defense_flow],
            ["block", "dodge"],
        )

    def test_appended_choice_is_requested_after_initial_defense(self):
        _, defender, _, attack = self.prepare([{
            "selection_mode": "defender_choice",
            "defense_types": ["dodge", "block"],
        }])
        provider = ScriptedDecisionProvider(["dodge"])

        with patch.object(
            DefenseResolver,
            "roll_defense",
            side_effect=[(1, 0), (10, 100)],
        ):
            result = DefenseResolver().resolve_phase(
                defender,
                "block",
                attacks=[attack],
                decision_provider=provider,
            )

        self.assertEqual(result["total_damage"], 0)
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(
            [step["defense_type"] for step in attack.defense_flow],
            ["block", "dodge"],
        )

    def test_repeated_offset_pays_and_reduces_independently(self):
        _, defender, battle, attack = self.prepare([
            {
                "selection_mode": "fixed",
                "defense_types": ["offset"],
            },
            {
                "selection_mode": "fixed",
                "defense_types": ["offset"],
            },
        ], operation="replace")
        attempts = [
            OffsetAttempt(defender, attack, [], None, True, 5),
            OffsetAttempt(defender, attack, [], None, True, 7),
        ]

        with patch.object(
            battle,
            "request_offset_attempt",
            side_effect=attempts,
        ) as request:
            result = DefenseResolver().resolve_phase(
                defender,
                "unopposed",
                attacks=[attack],
                decision_provider=ScriptedDecisionProvider([]),
            )

        self.assertEqual(request.call_count, 2)
        self.assertEqual(result["total_damage"], 18)
        self.assertEqual(attack.offset_attempts, attempts)

    def test_forced_guard_remains_block_only(self):
        _, defender, _, attack = self.prepare([{
            "selection_mode": "fixed",
            "defense_types": ["dodge"],
        }])
        attack.forced_guard_defense = True

        with patch.object(
            DefenseResolver,
            "roll_defense",
            return_value=(1, 0),
        ) as roll:
            DefenseResolver().resolve_phase(
                defender,
                "block",
                attacks=[attack],
            )

        roll.assert_called_once_with(defender, "block", None)
        self.assertFalse(hasattr(attack, "defense_flow"))


if __name__ == "__main__":
    unittest.main()
