import unittest
from unittest.mock import patch

from game.character.masters import Master
from game.action.action_list import ActionContext, ActionListBuilder
from game.game.game_manager import GameManager
from game.map.map import Location
from game.skill.effect_validation import validate_effect_definition
from game.turn.damage import AttackProfile
from game.turn.decision import ScriptedDecisionProvider
from game.turn.defense import DefenseResolver


def make_master(name):
    return Master(name, 3, 3, 3, 3, 3, "C", 3)


def delay_effect_definition(delay_turns=2):
    return {
        "effect_type": "delay_effect",
        "effect_data": {
            "delay_turns": delay_turns,
            "effects": [{
                "effect_type": "damage",
                "effect_data": {
                    "damage_type": "physical",
                    "value": 20,
                },
            }],
        },
    }


class DelayEffectTests(unittest.TestCase):
    def setUp(self):
        self.location = Location("Arena")
        self.actor = make_master("Actor")
        self.target = make_master("Target")
        self.actor.position = self.target.position = self.location
        self.game = GameManager(
            [self.actor, self.target],
            self.location,
        )
        self.game.start_game()
        self.game.turn_manager.start_turn()

    def make_skill(self, effect, *, target="selectable_character"):
        return self.actor.create_personal_skill({
            "skill_id": f"test_{effect['effect_type']}",
            "name": effect["effect_type"],
            "rank": "C",
            "components": [{
                "component_id": "use",
                "type": "active",
                "target": target,
                "effects": [effect],
            }],
        })

    def test_delay_turns_must_be_integer_greater_than_one(self):
        for invalid in (True, 0, 1):
            with self.subTest(invalid=invalid):
                with self.assertRaises((TypeError, ValueError)):
                    validate_effect_definition(
                        delay_effect_definition(invalid)
                    )

    def test_delay_effect_rejects_nested_delays_and_target_override(self):
        for nested in (
            {
                "effect_type": "delay_attack",
                "effect_data": {"delay_turns": 2},
            },
            {
                "effect_type": "damage",
                "effect_target": "self",
                "effect_data": {
                    "damage_type": "physical",
                    "value": 1,
                },
            },
        ):
            effect = delay_effect_definition()
            effect["effect_data"]["effects"] = [nested]
            with self.subTest(nested=nested["effect_type"]):
                with self.assertRaises(ValueError):
                    validate_effect_definition(effect)

    def test_delay_effect_uses_target_snapshot_at_same_due_checkpoint(self):
        skill = self.make_skill(delay_effect_definition())
        hp_before = self.target.hp

        self.actor.resolve_skill_component(
            skill.skill_id,
            "use",
            target=self.target,
            turn_number=1,
            phase="AP1",
        )
        self.game.turn_manager.start_turn()
        self.assertEqual(self.target.hp, hp_before)
        self.game.turn_manager.start_turn()
        self.assertEqual(self.target.hp, hp_before)
        self.game.delay_manager.resolve_checkpoint(
            3,
            "AP1",
            character=self.actor,
        )

        self.assertEqual(self.target.hp, hp_before - 20)
        self.assertEqual(len(self.game.delay_manager.entries), 0)
        self.assertEqual(len(self.game.delay_manager.history), 1)

    def test_delay_attack_removes_pending_attack_and_resolves_when_due(self):
        effect = {
            "effect_type": "delay_attack",
            "effect_data": {"delay_turns": 2},
        }
        skill = self.make_skill(effect, target="incoming_attacks")
        attack = AttackProfile(
            source=self.actor,
            value=20,
            damage_type="physical",
            attack_roll=100,
        ).assign_target(self.target)
        self.target.pending_attacks.append(attack)
        hp_before = self.target.hp

        self.actor.resolve_skill_component(
            skill.skill_id,
            "use",
            target=attack,
            turn_number=1,
        )
        self.assertNotIn(attack, self.target.pending_attacks)
        self.game.decision_provider = ScriptedDecisionProvider(["block"])
        self.game.turn_manager.start_turn()
        self.assertEqual(self.target.hp, hp_before)
        with patch.object(
            DefenseResolver,
            "roll_defense",
            return_value=(10, 100),
        ):
            self.game.turn_manager.start_turn()
            self.game.delay_manager.resolve_checkpoint(
                3,
                "defense",
                character=self.target,
                decision_provider=self.game.decision_provider,
            )

        self.assertTrue(attack.resolved)
        self.assertEqual(self.target.hp, hp_before - 10)
        self.assertEqual(len(self.game.delay_manager.history), 1)

    def test_due_delay_falls_back_at_turn_end_when_checkpoint_is_absent(self):
        skill = self.make_skill(delay_effect_definition())
        hp_before = self.target.hp
        self.actor.resolve_skill_component(
            skill.skill_id,
            "use",
            target=self.target,
            turn_number=1,
            phase="attack_phase",
        )
        self.game.turn_manager.start_turn()
        self.game.turn_manager.start_turn()

        self.assertEqual(self.target.hp, hp_before)
        self.game.delay_manager.resolve_turn_end_fallback(3)

        self.assertEqual(self.target.hp, hp_before - 20)
        entry = self.game.delay_manager.history[-1]
        self.assertEqual(entry.resolved_checkpoint, "global_turn_end")
        self.assertTrue(entry.used_turn_end_fallback)

    def test_event_checkpoint_can_release_a_delayed_effect(self):
        skill = self.make_skill(delay_effect_definition())
        hp_before = self.target.hp
        self.actor.resolve_skill_component(
            skill.skill_id,
            "use",
            target=self.target,
            turn_number=1,
            phase="raw_die_generated",
        )
        self.game.turn_manager.start_turn()
        self.game.turn_manager.start_turn()

        self.game.event_manager.emit(
            "raw_die_generated",
            actor=self.actor,
            target=self.target,
        )

        self.assertEqual(self.target.hp, hp_before - 20)
        entry = self.game.delay_manager.history[-1]
        self.assertEqual(entry.resolved_checkpoint, "raw_die_generated")
        self.assertFalse(entry.used_turn_end_fallback)

    def test_simple_round_checkpoints_map_to_formal_battle_phases(self):
        skill = self.make_skill(delay_effect_definition())
        expected = {
            "simple_round_attack": ("attack", self.actor),
            "simple_round_guard": ("guard", self.actor),
            "simple_round_defense": ("defense", self.target),
        }
        for phase, (checkpoint, owner) in expected.items():
            with self.subTest(phase=phase):
                entry = self.game.delay_manager.schedule_effects(
                    actor=self.actor,
                    target=self.target,
                    skill=skill,
                    effects=delay_effect_definition()["effect_data"]["effects"],
                    delay_turns=2,
                    context={"phase": phase},
                )
                self.assertEqual(entry.checkpoint, checkpoint)
                self.assertIs(entry.checkpoint_owner, owner)

    def test_delaying_same_attack_again_extends_original_due_turn(self):
        effect = {
            "effect_type": "delay_attack",
            "effect_data": {"delay_turns": 2},
        }
        skill = self.make_skill(effect, target="incoming_attacks")
        attack = AttackProfile(
            source=self.actor,
            value=20,
            damage_type="physical",
            attack_roll=10,
        ).assign_target(self.target)
        self.target.pending_attacks.append(attack)

        first = self.game.delay_manager.schedule_attack(
            attack,
            actor=self.actor,
            skill=skill,
            delay_turns=2,
        )
        second = self.game.delay_manager.schedule_attack(
            attack,
            actor=self.actor,
            skill=skill,
            delay_turns=2,
        )

        self.assertIs(first, second)
        self.assertEqual(first.due_turn, 5)
        self.assertEqual(first.delay_turns, 4)

        definition = dict(skill.definitions[0])
        definition["target"] = "delayed_attacks"
        definition.setdefault("target_rules", {})
        context = ActionContext(
            actor=self.actor,
            phase="defense_phase",
            turn_number=1,
            characters=list(self.game.characters),
            game_manager=self.game,
        )
        candidates = ActionListBuilder()._get_target_candidates(
            definition,
            context,
        )
        self.assertEqual(candidates, [attack])


if __name__ == "__main__":
    unittest.main()
