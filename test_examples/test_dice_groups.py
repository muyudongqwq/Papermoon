"""Grouped dice bonuses share normal modifier lifecycle and scoped queries."""

import unittest

from game.character.servants import Servant
from game.modifier.dice_targets import DICE_TARGET_GROUPS
from game.modifier.modifier import create_modifier
from game.turn.roll import RollResolver


def actor():
    return Servant("Saber", 3, 3, 3, 3, 3, "Saber", "A")


def effect(target, value=9, **extras):
    return {"effect_type": "dice_bonus", "effect_data": {"effect_target": target, "value": value}, **extras}


class DiceGroupTests(unittest.TestCase):
    def test_group_affects_each_member_once_and_removal_restores_all_stats(self):
        for group, members in DICE_TARGET_GROUPS.items():
            with self.subTest(group=group):
                character = actor()
                stats = (*character.DERIVED_STAT_NAMES, "dice_bonus", "atk")
                baseline = {stat: getattr(character, stat) for stat in stats}
                modifier = create_modifier(effect(group), character)
                character.add_modifier(modifier)
                for stat in stats:
                    self.assertEqual(getattr(character, stat), baseline[stat] + (9 if stat in members else 0))
                for stat in character.DERIVED_STAT_NAMES:
                    roll = RollResolver().roll(character, stat, initial_die=5, allow_luck=False)
                    self.assertEqual(roll.total, 5 + baseline[stat] + (9 if stat in members else 0))
                character.remove_modifier(modifier)
                self.assertEqual({stat: getattr(character, stat) for stat in stats}, baseline)

    def test_group_stacking_and_expiration_do_not_leave_member_bonuses(self):
        for group, members in DICE_TARGET_GROUPS.items():
            with self.subTest(group=group):
                character = actor()
                baseline = {stat: getattr(character, stat) for stat in members}
                definition = effect(group, 3, duration=1, stacking={"stacking_rule": "stack", "max_stacks": 3})
                first = create_modifier(definition, character)
                character.add_modifier(first)
                character.add_modifier(create_modifier(definition, character))
                self.assertEqual(first.stack_count, 2)
                for stat in members:
                    self.assertEqual(getattr(character, stat), baseline[stat] + 6)
                first.change_stack_count(1)
                for stat in members:
                    self.assertEqual(getattr(character, stat), baseline[stat] + 3)
                character.update_modifiers("global_turn_end", turn_number=1)
                for stat in members:
                    self.assertEqual(getattr(character, stat), baseline[stat])

    def test_conditional_groups_obey_scope_and_do_not_double_count(self):
        for group, members in DICE_TARGET_GROUPS.items():
            with self.subTest(group=group):
                character = actor()
                baseline = {stat: getattr(character, stat) for stat in character.DERIVED_STAT_NAMES}
                modifier = create_modifier(effect(group, 6,
                    conditions={"phases": ["simple_round_defense"]},
                    application_scope={"phase_scopes": ["simple_round"]}), character)
                character.add_modifier(modifier)
                for stat in character.DERIVED_STAT_NAMES:
                    self.assertEqual(getattr(character, stat), baseline[stat])
                    for scope in ("simple_round", "formal_battle"):
                        roll = RollResolver().roll(character, stat, initial_die=5, allow_luck=False,
                            modifier_context={"phase_scope": scope, "phase": "simple_round_defense"})
                        bonus = 6 if scope == "simple_round" and stat in members else 0
                        self.assertEqual(roll.total, 5 + baseline[stat] + bonus)

    def test_group_and_single_stat_modifiers_can_be_combined_and_removed_independently(self):
        character = actor()
        physical, magic = character.physical_attack, character.magic_attack
        group = create_modifier(effect("attack", -2), character)
        single = create_modifier(effect("physical_attack", 5), character)
        character.add_modifier(group)
        character.add_modifier(single)
        self.assertEqual(character.physical_attack, physical + 3)
        self.assertEqual(character.magic_attack, magic - 2)
        character.remove_modifier(group)
        self.assertEqual(character.physical_attack, physical + 5)
        self.assertEqual(character.magic_attack, magic)
        character.remove_modifier(single)
        self.assertEqual(character.physical_attack, physical)
