import unittest
from unittest.mock import patch

from game.character.masters import Master
from game.character.servants import Servant
from game.map.map import Location
from game.skill.casting import CastingState
from game.turn.battle import BattleManager
from game.turn.damage import AttackEvent
from game.turn.defense import (
    DefenseResolver,
    OffsetAttempt,
    get_offset_attack_options,
    resolve_offset_attack_option,
)
from game.turn.decision import ScriptedDecisionProvider


def servant(name, strength=3):
    return Servant(name, strength, 3, 3, 3, 3, "Saber", "A")


def master(name):
    return Master(name, 3, 3, 3, 5, 3, "C", 3)


def incoming_attack(source, target, *, value=30, roll=0, channel="attack"):
    attack = AttackEvent(
        source=source,
        target=target,
        value=value,
        damage_type="physical",
        attack_roll=roll,
        skill=None,
        resolution_channel=channel,
    )
    target.pending_attacks.append(attack)
    return attack


class OffsetAttackTests(unittest.TestCase):
    def setUp(self):
        self.location = Location("Arena")

    def start_battle(self, *characters):
        for character in characters:
            character.position = self.location
        battle = BattleManager(list(characters))
        battle.start_battle()
        return battle

    def test_normal_attack_offsets_attack_without_attack_phase(self):
        attacker = servant("Attacker")
        defender = servant("Defender", strength=5)
        battle = self.start_battle(attacker, defender)
        defender.attack_phase_count = 0
        attack = incoming_attack(attacker, defender, value=20, roll=0)
        starting_hp = defender.hp
        provider = ScriptedDecisionProvider(["offset", "normal_attack"])

        with patch("game.turn.roll.random.randint", return_value=5):
            defense = battle.request_defense(
                defender,
                provider,
                attacks=[attack],
            )
        result = DefenseResolver().resolve_phase(
            defender,
            defense,
            attacks=[attack],
            decision_provider=provider,
        )

        self.assertIsInstance(defense, OffsetAttempt)
        self.assertTrue(defense.success)
        self.assertEqual(defender.attack_phase_count, 0)
        self.assertEqual(result["total_damage"], 0)
        self.assertEqual(defender.hp, starting_hp)

    def test_release_can_only_be_offset_by_attack_release(self):
        attacker = servant("Attacker")
        defender = master("Caster")
        defender.load_basic_magic("magic_bullet")
        battle = self.start_battle(attacker, defender)
        attack = incoming_attack(
            attacker,
            defender,
            value=50,
            roll=0,
            channel="release",
        )
        starting_mp = defender.mp
        provider = ScriptedDecisionProvider(["offset", "魔弹"])

        with patch("game.turn.roll.random.randint", return_value=5):
            attempt = battle.request_defense(
                defender,
                provider,
                attacks=[attack],
            )
        result = DefenseResolver().resolve_phase(
            defender,
            attempt,
            attacks=[attack],
            decision_provider=provider,
        )

        self.assertEqual(attempt.attack_profiles[0].resolution_channel, "release")
        self.assertEqual(attempt.total_power, 30)
        self.assertEqual(defender.mp, starting_mp - 10)
        self.assertEqual(result["total_damage"], 20)

    def test_back_returns_to_defense_selection_without_payment(self):
        attacker = servant("Attacker")
        defender = servant("Defender")
        battle = self.start_battle(attacker, defender)
        attack = incoming_attack(attacker, defender)
        provider = ScriptedDecisionProvider(["offset", "back", "block"])

        selected = battle.request_defense(
            defender,
            provider,
            attacks=[attack],
        )

        self.assertEqual(selected, "block")

    def test_attack_components_combine_all_profile_damage(self):
        attacker = servant("Attacker")
        defender = servant("Defender")
        defender.create_personal_skill({
            "skill_id": "multi_attack",
            "name": "多段攻击",
            "rank": "C",
            "components": [{
                "component_id": "attack",
                "type": "active",
                "available_phases": ["attack_phase"],
                "target": "selectable_enemy",
                "effects": [
                    {
                        "effect_type": "create_attack_event",
                        "effect_data": {"damage_value": 20},
                    },
                    {
                        "effect_type": "create_attack_event",
                        "effect_data": {"damage_value": 30},
                    },
                ],
            }],
        })
        incoming = incoming_attack(attacker, defender)
        option = next(
            option
            for option in get_offset_attack_options(defender, incoming)
            if option.option_id.startswith("skill:multi_attack")
        )

        resolved = resolve_offset_attack_option(defender, option)

        self.assertEqual(len(resolved["profiles"]), 2)
        self.assertEqual(
            sum(profile.offset_power for profile in resolved["profiles"]),
            50,
        )

    def test_ready_casting_release_finishes_when_used_for_offset(self):
        attacker = servant("Attacker")
        defender = master("Caster")
        skill = defender.create_magic({
            "skill_id": "cast_attack",
            "name": "咏唱攻击",
            "rank": "C",
            "casting": {"mp_cost": 40},
            "components": [{
                "component_id": "release",
                "type": "active",
                "casting_requirement": 1,
                "target": "selectable_enemy",
                "effects": [{
                    "effect_type": "create_attack_event",
                    "effect_data": {"damage_value": 60},
                }],
            }],
        })
        state = CastingState.start(defender, skill, 1)
        state.layers = 1
        mp_after_chant = defender.mp
        incoming = incoming_attack(
            attacker,
            defender,
            channel="release",
        )
        option = next(
            option
            for option in get_offset_attack_options(defender, incoming)
            if option.skill is skill
        )

        resolved = resolve_offset_attack_option(defender, option)

        self.assertEqual(resolved["profiles"][0].offset_power, 60)
        self.assertEqual(defender.mp, mp_after_chant)
        self.assertIsNone(defender.casting_state)
        self.assertTrue(state.released)

    def test_command_spell_damage_is_consumed_by_offset_attack(self):
        attacker = servant("Attacker")
        defender = servant("Defender", strength=3)
        self.start_battle(attacker, defender)
        incoming = incoming_attack(attacker, defender)
        defender.grant_command_spell_damage(90)
        option = next(
            option
            for option in get_offset_attack_options(defender, incoming)
            if option.kind == "normal_attack"
        )

        resolved = resolve_offset_attack_option(defender, option)

        self.assertEqual(resolved["profiles"][0].offset_power, defender.atk + 90)
        self.assertEqual(defender.command_spell_damage_bonus, 0)

    def test_switching_release_refunds_old_chant_before_paying_new_magic(self):
        attacker = servant("Attacker")
        defender = master("Caster")
        old_skill = defender.create_magic({
            "skill_id": "old_chant",
            "name": "旧咏唱",
            "rank": "C",
            "casting": {"mp_cost": 40},
            "components": [{
                "component_id": "release",
                "type": "active",
                "casting_requirement": 1,
                "target": "selectable_enemy",
                "effects": [{
                    "effect_type": "create_attack_event",
                    "effect_data": {"damage_value": 60},
                }],
            }],
        })
        defender.load_basic_magic("magic_bullet")
        starting_mp = defender.mp
        old_state = CastingState.start(defender, old_skill, 1)
        incoming = incoming_attack(
            attacker,
            defender,
            channel="release",
        )
        option = next(
            option
            for option in get_offset_attack_options(defender, incoming)
            if option.skill.skill_id == "basic_magic:magic_bullet"
        )

        resolved = resolve_offset_attack_option(defender, option)

        self.assertEqual(resolved["profiles"][0].offset_power, 30)
        self.assertEqual(defender.mp, starting_mp - 10)
        self.assertTrue(old_state.interrupted)
        self.assertIsNone(defender.casting_state)

    def test_target_effect_is_skipped_but_self_effect_resolves(self):
        attacker = servant("Attacker")
        defender = servant("Defender")
        defender.hp -= 10
        skill = defender.create_personal_skill({
            "skill_id": "offset_with_side_effects",
            "name": "攻防一体",
            "rank": "C",
            "components": [{
                "component_id": "attack",
                "type": "active",
                "available_phases": ["attack_phase"],
                "target": "selectable_enemy",
                "effects": [
                    {
                        "effect_type": "create_attack_event",
                        "effect_data": {"damage_value": 20},
                    },
                    {
                        "effect_type": "recover_resource",
                        "effect_target": "self",
                        "effect_data": {"resource_id": "hp", "value": 5},
                    },
                    {
                        "effect_type": "recover_resource",
                        "effect_target": "attack_target",
                        "effect_data": {"resource_id": "hp", "value": 99},
                    },
                ],
            }],
        })
        incoming = incoming_attack(attacker, defender)
        option = next(
            option
            for option in get_offset_attack_options(defender, incoming)
            if option.skill is skill
        )
        hp_before = defender.hp

        resolved = resolve_offset_attack_option(defender, option)

        self.assertEqual(defender.hp, hp_before + 5)
        self.assertEqual(len(resolved["effect_results"]), 2)
        self.assertTrue(resolved["effect_results"][1]["skipped"])

    def test_release_options_are_not_offered_against_attack_channel(self):
        attacker = servant("Attacker")
        defender = master("Caster")
        defender.load_basic_magic("magic_bullet")
        incoming = incoming_attack(attacker, defender, channel="attack")

        options = get_offset_attack_options(defender, incoming)

        self.assertEqual([option.kind for option in options], ["normal_attack"])

    def test_offset_records_remaining_segments_after_flat_reduction(self):
        attacker = servant("Attacker")
        defender = servant("Defender")
        attack = AttackEvent(
            source=attacker,
            target=defender,
            value=60,
            damage_type="physical",
            attack_roll=0,
            skill=None,
            damage_segments=[20, 20, 20],
        )
        attempt = OffsetAttempt(
            defender=defender,
            incoming_attack=attack,
            attack_profiles=[],
            roll_result=None,
            success=True,
            reduction=35,
        )

        result = DefenseResolver().resolve_phase(
            defender,
            attempt,
            attacks=[attack],
        )

        self.assertEqual(result["total_damage"], 25)
        self.assertEqual(attempt.remaining_hit_segments, 2)
        self.assertEqual(attack.final_hit_segments, 2)


if __name__ == "__main__":
    unittest.main()
