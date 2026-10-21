import unittest

from game.action.action import Action
from game.character.servants import Servant
from game.character.masters import Master
from game.game_manager import GameManager
from game.map.map import Location
from game.modifier.modifier import create_modifier
from game.modifier.context import ModifierContext
from game.skill.class_skill_data import CLASS_SKILL_DATA
from game.skill.skill import Skill
from game.skill.skill_runtime import apply_skill_effect
from game.turn.battle import BattleManager
from game.turn.decision import ScriptedDecisionProvider
from game.turn.roll import RollResolver
from game.turn.damage import DamageEvent, DamageResolver
from game.map.movement import MovementAction, MovementResolver


def create_servant(name="Saber"):
    return Servant(name, 3, 3, 3, 3, 3, "Saber", "A")


def create_master(name="Master"):
    return Master(name, 3, 3, 3, 3, 3, "C", 3)


def numeric_effect(
    modifier_id,
    value,
    rule="refresh",
    scope="same_source",
    duration=3,
    max_stacks=1,
    at_max="refresh",
):
    return {
        "modifier_id": modifier_id,
        "effect_type": "numeric_attribute_bonus",
        "duration": duration,
        "stacking": {
            "stack_group": modifier_id,
            "stack_scope": scope,
            "stacking_rule": rule,
            "max_stacks": max_stacks,
            "at_max_stacks_rule": at_max,
            "duration_refresh_rule": "reset",
        },
        "effect_data": {
            "effect_target": "dice_bonus",
            "value": value,
        },
    }


class ModifierLifecycleTests(unittest.TestCase):
    def test_contextual_attribute_affects_all_derived_values_and_attack_damage(self):
        target = create_servant("Target")
        effect = {
            "modifier_id": "simple_strength",
            "effect_type": "attribute_bonus",
            "conditions": {"phases": ["simple_round_attack"]},
            "application_scope": {"phase_scopes": ["simple_round"]},
            "effect_data": {
                "effect_target": "strength",
                "value": 2,
            },
        }
        target.add_modifier(create_modifier(effect, target))
        context = {
            "actor": target,
            "phase_scope": "simple_round",
            "phase": "simple_round_attack",
            "action_id": "attack",
        }

        self.assertEqual(target.strength.value, 3)
        self.assertEqual(target.get_effective_attribute_value("strength", context), 5)
        self.assertEqual(target.get_effective_derived_stat("physical_attack", context), 8)
        self.assertEqual(target.get_effective_derived_stat("block", context), 10)
        self.assertEqual(target.get_effective_atk(context), 50)

    def test_contextual_endurance_and_magic_change_caps_and_remove_safely(self):
        target = create_servant("Target")
        endurance = {
            "modifier_id": "temporary_endurance",
            "effect_type": "attribute_bonus",
            "conditions": {"phase_scopes": ["non_battle"]},
            "effect_data": {"effect_target": "endurance", "value": 2},
        }
        magic = {
            "modifier_id": "temporary_magic",
            "effect_type": "attribute_bonus",
            "conditions": {"phase_scopes": ["non_battle"]},
            "effect_data": {"effect_target": "magic", "value": 2},
        }
        hp_modifier = create_modifier(endurance, target)
        mp_modifier = create_modifier(magic, target)
        target.add_modifier(hp_modifier)
        target.add_modifier(mp_modifier)

        self.assertEqual(target.hpmax, 150)
        self.assertEqual(target.mpmax, 150)
        target.hp = 10
        target.mp = 10
        target.remove_modifier(hp_modifier)
        target.remove_modifier(mp_modifier)

        self.assertEqual(target.hpmax, 90)
        self.assertEqual(target.mpmax, 90)
        self.assertEqual(target.hp, 1)
        self.assertEqual(target.mp, 1)
        self.assertFalse(target.has_status("brink_of_death"))

    def test_contextual_resource_caps_never_drop_below_one(self):
        target = create_servant("Target")
        for attribute in ("endurance", "magic"):
            effect = {
                "modifier_id": f"negative_{attribute}",
                "effect_type": "attribute_bonus",
                "conditions": {"phase_scopes": ["non_battle"]},
                "effect_data": {"effect_target": attribute, "value": -10},
            }
            target.add_modifier(create_modifier(effect, target))

        self.assertEqual(target.hpmax, 1)
        self.assertEqual(target.mpmax, 1)
        self.assertEqual(target.hp, 1)
        self.assertEqual(target.mp, 1)

    def test_contextual_resource_cap_activates_and_ends_with_phase(self):
        target = create_servant("Target")
        other = create_servant("Other")
        battle = BattleManager([target, other])
        target.current_battle = battle
        other.current_battle = battle
        target.in_battle = True
        other.in_battle = True
        effect = {
            "modifier_id": "defense_endurance",
            "effect_type": "attribute_bonus",
            "conditions": {"phases": ["defense"]},
            "application_scope": {"phase_scopes": ["formal_battle"]},
            "effect_data": {"effect_target": "endurance", "value": 1},
        }
        modifier = create_modifier(effect, target)
        target.add_modifier(modifier)
        self.assertEqual(target.hpmax, 90)

        battle.current_character = target
        battle.current_phase = "defense"
        self.assertEqual(target.hpmax, 120)
        self.assertEqual(target.hp, 120)

        target.hp = 10
        battle.current_phase = "attack"
        self.assertEqual(target.hpmax, 90)
        self.assertEqual(target.hp, 1)
        self.assertFalse(target.has_status("brink_of_death"))

    def test_replacing_contextual_capacity_does_not_heal_through_intermediate_floor(self):
        target = create_servant("Target")
        effect = {
            "modifier_id": "replace_endurance",
            "effect_type": "attribute_bonus",
            "conditions": {"phase_scopes": ["non_battle"]},
            "stacking": {
                "stack_group": "replace_endurance",
                "stack_scope": "all_sources",
                "stacking_rule": "replace",
            },
            "effect_data": {"effect_target": "endurance", "value": 1},
        }
        target.add_modifier(create_modifier(effect, target))
        target.hp = 10

        target.add_modifier(create_modifier(effect, target))

        self.assertEqual(target.hpmax, 120)
        self.assertEqual(target.hp, 10)

    def test_movement_bonus_is_locked_when_ap_movement_starts(self):
        actor = create_servant("Mover")
        start = Location("Start")
        end = Location("End")
        start.add_connection(end)
        end.add_connection(start)
        actor.position = start
        effect = {
            "modifier_id": "ap1_speed",
            "effect_type": "movement_point_bonus",
            "conditions": {"phases": ["AP1"]},
            "effect_data": {"value": 2},
        }
        modifier = create_modifier(effect, actor)
        actor.add_modifier(modifier)
        action = MovementAction(actor, [start, end], ap_layer=1)
        action.ap_layer = 1

        self.assertTrue(action.prepare(MovementResolver()))
        actor.remove_modifier(modifier)

        self.assertEqual(action.movement_limit, 5)
        self.assertEqual(action.movement_state.remaining_movement, 5)

    def test_contextual_visibility_updates_dynamically(self):
        observer = create_servant("Observer")
        target = create_servant("Target")
        first = Location("First")
        second = Location("Second")
        first.add_connection(second)
        second.add_connection(first)
        observer.position = first
        target.position = second
        effect = {
            "modifier_id": "map_visibility",
            "effect_type": "visibility_bonus",
            "application_scope": {"phase_scopes": ["non_battle"]},
            "effect_data": {"value": 1},
        }
        modifier = create_modifier(effect, observer)
        observer.add_modifier(modifier)
        observer.update_visibility([observer, target])
        self.assertIn(target, observer.own_visible)

        observer.remove_modifier(modifier)
        observer.update_visibility([observer, target])
        self.assertNotIn(target, observer.own_visible)

    def test_conditional_status_is_rejected_until_contextual_status_exists(self):
        target = create_servant("Target")
        with self.assertRaises(ValueError):
            create_modifier(
                {
                    "modifier_id": "conditional_status",
                    "effect_type": "add_status",
                    "conditions": {"phases": ["defense"]},
                    "effect_data": {"value": "cannot_dodge"},
                },
                target,
            )

    def test_conditional_dice_modifier_uses_runtime_context(self):
        target = create_servant("Target")
        base_block = target.block
        effect = {
            "modifier_id": "simple_round_block",
            "effect_type": "dice_bonus",
            "conditions": {"phases": ["simple_round_defense"]},
            "application_scope": {"phase_scopes": ["simple_round"]},
            "effect_data": {
                "effect_target": "block",
                "value": 5,
            },
        }
        modifier = create_modifier(effect, target)
        target.add_modifier(modifier)

        self.assertEqual(target.block, base_block)
        simple = RollResolver().roll(
            target,
            "block",
            allow_luck=False,
            initial_die=5,
            modifier_context=ModifierContext(
                actor=target,
                phase_scope="simple_round",
                phase="simple_round_defense",
            ),
        )
        formal = RollResolver().roll(
            target,
            "block",
            allow_luck=False,
            initial_die=5,
            modifier_context=ModifierContext(
                actor=target,
                phase_scope="formal_battle",
                phase="defense",
            ),
        )

        self.assertEqual(simple.dice_bonus, 5)
        self.assertEqual(formal.dice_bonus, 0)

    def test_unscoped_phase_window_modifier_applies_in_simple_round(self):
        target = create_servant("Target")
        effect = {
            "modifier_id": "non_consuming_simple_round_bonus",
            "effect_type": "dice_bonus",
            "phase_window": {
                "scope": "formal_battle",
                "phase": "defense",
                "boundary": "phase_end",
                "owner": "target",
            },
            "conditions": {"phases": ["simple_round_defense"]},
            "effect_data": {
                "effect_target": "block",
                "value": 3,
            },
        }
        modifier = create_modifier(effect, target)
        target.add_modifier(modifier)

        result = RollResolver().roll(
            target,
            "block",
            allow_luck=False,
            initial_die=5,
            modifier_context={
                "actor": target,
                "phase_scope": "simple_round",
                "phase": "simple_round_defense",
            },
        )
        target.update_phase_window_modifiers(
            scope="simple_round",
            phase="defense",
            boundary="phase_end",
            phase_actor=target,
        )

        self.assertEqual(result.dice_bonus, 3)
        self.assertIn(modifier, target.modifiers)

    def test_modifier_and_aggregated_status_events_are_emitted(self):
        source = create_servant("Source")
        target = create_servant("Target")
        game = GameManager([source, target], Location("Grail"))
        source.game_manager = game
        target.game_manager = game
        effect = {
            "modifier_id": "marked",
            "effect_type": "add_status",
            "stacking": {
                "stack_group": "marked",
                "stack_scope": "same_source",
                "stacking_rule": "independent",
            },
            "effect_data": {"value": "marked"},
        }
        first = create_modifier(
            effect,
            target,
            source=source,
            source_actor=source,
        )
        second = create_modifier(
            effect,
            target,
            source=object(),
            source_actor=source,
        )

        target.add_modifier(first)
        target.add_modifier(second)
        target.remove_modifier(first)
        target.remove_modifier(second)

        event_types = [event.event_type for event in game.event_manager.history]
        self.assertEqual(event_types.count("modifier_applied"), 2)
        self.assertEqual(event_types.count("modifier_removed"), 2)
        self.assertEqual(event_types.count("status_added"), 1)
        self.assertEqual(event_types.count("status_removed"), 1)

    def test_purify_effect_lets_actor_select_multiple_debuffs(self):
        actor = create_servant("Caster")
        target = create_servant("Target")
        sources = [create_servant("First"), create_servant("Second")]
        modifiers = []
        for index, source in enumerate(sources, start=1):
            effect = numeric_effect(
                f"debuff_{index}",
                -index,
                rule="independent",
                scope="independent",
            )
            effect.update({"polarity": "debuff", "name": f"弱化{index}"})
            modifier = create_modifier(effect, target, source=source)
            target.add_modifier(modifier)
            modifiers.append(modifier)
        third_effect = numeric_effect(
            "debuff_3",
            -3,
            rule="independent",
            scope="independent",
        )
        third_effect["polarity"] = "debuff"
        third = create_modifier(third_effect, target)
        target.add_modifier(third)
        protected_effect = numeric_effect("protected", -5)
        protected_effect.update({
            "polarity": "debuff",
            "purifiable": False,
        })
        protected = create_modifier(protected_effect, target)
        target.add_modifier(protected)
        provider = ScriptedDecisionProvider(["2", "1"])
        skill = Skill("净化术", "C", "active", {})

        removed = apply_skill_effect(
            {
                "effect_type": "purify",
                "effect_data": {"maximum": 2},
            },
            target,
            skill,
            actor=actor,
            decision_provider=provider,
            phase="技能效果选择",
        )

        self.assertEqual(removed, [modifiers[1], modifiers[0]])
        self.assertIn(third, target.modifiers)
        self.assertIn(protected, target.modifiers)
        self.assertEqual(len(provider.requests), 2)
        first_labels = [
            option.label for option in provider.requests[0].options
        ]
        self.assertTrue(any("来源：First" in label for label in first_labels))
        self.assertTrue(any("层数：1" in label for label in first_labels))
        self.assertTrue(any("剩余：3" in label for label in first_labels))

    def test_purify_all_removes_only_purifiable_debuffs_without_prompt(self):
        target = create_servant("Target")
        removable_effect = numeric_effect("removable", -1)
        removable_effect["polarity"] = "debuff"
        removable = create_modifier(removable_effect, target)
        protected_effect = numeric_effect("protected", -1)
        protected_effect.update({
            "polarity": "debuff",
            "purifiable": False,
        })
        protected = create_modifier(protected_effect, target)
        target.add_modifier(removable)
        target.add_modifier(protected)
        skill = Skill("大净化", "A", "active", {})

        removed = apply_skill_effect(
            {
                "effect_type": "purify",
                "effect_data": {"maximum": "all"},
            },
            target,
            skill,
        )

        self.assertEqual(removed, [removable])
        self.assertIn(protected, target.modifiers)

    def test_berserker_cannot_investigate_is_an_unpurifiable_debuff(self):
        for rank in ("C", "B", "A"):
            effects = CLASS_SKILL_DATA["狂化"][rank][0]["effects"]
            definition = next(
                effect
                for effect in effects
                if effect.get("effect_data", {}).get("value")
                == "cannot_investigate"
            )
            self.assertEqual(definition["polarity"], "debuff")
            self.assertFalse(definition["purifiable"])

    def test_modifier_polarity_and_default_purifiability(self):
        target = create_servant()
        neutral = create_modifier(numeric_effect("neutral", 1), target)
        debuff_effect = numeric_effect("debuff", -1)
        debuff_effect["polarity"] = "debuff"
        debuff = create_modifier(debuff_effect, target)
        protected_effect = numeric_effect("protected", -1)
        protected_effect.update({
            "polarity": "debuff",
            "purifiable": False,
        })
        protected = create_modifier(protected_effect, target)

        self.assertEqual(neutral.polarity, "neutral")
        self.assertFalse(neutral.purifiable)
        self.assertTrue(debuff.purifiable)
        self.assertFalse(protected.purifiable)

    def test_purify_removes_selected_count_and_keeps_protected_sources(self):
        target = create_servant()
        source_a = create_servant("SourceA")
        source_b = create_servant("SourceB")
        base_effect = {
            "modifier_id": "cannot_escape",
            "effect_type": "add_status",
            "polarity": "debuff",
            "stacking": {
                "stack_group": "cannot_escape",
                "stack_scope": "same_source",
                "stacking_rule": "refresh",
            },
            "effect_data": {"value": "cannot_escape"},
        }
        protected_effect = dict(base_effect, purifiable=False)
        purifiable_effect = dict(base_effect, purifiable=True)
        protected = create_modifier(
            protected_effect,
            target,
            source=source_a,
            source_type="class_skill",
            source_id="current_rule_source",
        )
        purifiable = create_modifier(
            purifiable_effect,
            target,
            source=source_b,
            source_type="skill",
            source_id="other_source",
        )
        another_effect = numeric_effect("slow", -1)
        another_effect["polarity"] = "debuff"
        another = create_modifier(another_effect, target)
        target.add_modifier(protected)
        target.add_modifier(purifiable)
        target.add_modifier(another)

        self.assertEqual(target.get_purifiable_modifiers(), [purifiable, another])
        self.assertEqual(
            target.purify_modifiers([another, purifiable], maximum=1),
            [another],
        )
        self.assertIn(protected, target.modifiers)
        self.assertIn(purifiable, target.modifiers)
        self.assertTrue(target.has_status("cannot_escape"))
        self.assertEqual(target.purify_modifiers(maximum="all"), [purifiable])
        self.assertTrue(target.has_status("cannot_escape"))

    def test_purify_removes_a_stacked_modifier_as_one_whole_effect(self):
        target = create_servant()
        effect = numeric_effect(
            "stacked_debuff",
            -1,
            rule="stack",
            max_stacks=3,
        )
        effect["polarity"] = "debuff"
        first = create_modifier(effect, target, source=target)
        target.add_modifier(first)
        target.add_modifier(create_modifier(effect, target, source=target))

        self.assertEqual(first.stack_count, 2)
        self.assertEqual(target.purify_modifiers(maximum=1), [first])
        self.assertNotIn(first, target.modifiers)
        self.assertEqual(target.dice_bonus, 0)

    def test_invalid_modifier_polarity_is_rejected(self):
        target = create_servant()
        effect = numeric_effect("invalid", 1)
        effect["polarity"] = "harmful"
        with self.assertRaises(ValueError):
            create_modifier(effect, target)

    def test_modifier_records_source_and_stacking_metadata(self):
        target = create_servant()
        source = create_servant("Caster")
        effect = {
            "modifier_id": "test_dice_bonus",
            "effect_type": "numeric_attribute_bonus",
            "effect_data": {
                "effect_target": "dice_bonus",
                "value": 2,
                "duration": 3,
            },
            "stacking": {
                "stack_group": "dice_bonus",
                "stack_scope": "same_source",
                "stacking_rule": "stack",
                "max_stacks": 3,
            },
        }

        modifier = create_modifier(
            effect,
            target,
            source=source,
            source_type="skill",
            source_id="test_skill",
            applied_turn=2,
            applied_phase="AP1",
        )

        self.assertEqual(modifier.modifier_id, "test_dice_bonus")
        self.assertIs(modifier.source, source)
        self.assertIs(modifier.target, target)
        self.assertEqual(modifier.source_type, "skill")
        self.assertEqual(modifier.source_id, "test_skill")
        self.assertEqual(modifier.stack_group, "dice_bonus")
        self.assertEqual(modifier.stacking_rule, "stack")
        self.assertEqual(modifier.max_stacks, 3)
        self.assertEqual(modifier.stack_count, 1)

    def test_apply_and_remove_are_idempotent(self):
        target = create_servant()
        effect = {
            "effect_type": "numeric_attribute_bonus",
            "effect_data": {
                "effect_target": "dice_bonus",
                "value": 2,
            },
        }
        modifier = create_modifier(effect, target)

        self.assertTrue(modifier.apply())
        self.assertFalse(modifier.apply())
        self.assertEqual(target.dice_bonus, 2)
        self.assertTrue(modifier.remove())
        self.assertFalse(modifier.remove())
        self.assertEqual(target.dice_bonus, 0)

    def test_duration_only_ticks_at_its_configured_timing(self):
        target = create_servant()
        effect = {
            "effect_type": "numeric_attribute_bonus",
            "duration": 2,
            "duration_timing": "AP1_checkpoint",
            "effect_data": {
                "effect_target": "dice_bonus",
                "value": 1,
            },
        }
        modifier = create_modifier(effect, target)
        modifier.apply()
        target.modifiers.append(modifier)

        target.update_modifiers("global_turn_end")
        self.assertEqual(modifier.duration, 2)
        target.update_modifiers("AP1_checkpoint")
        self.assertEqual(modifier.duration, 1)
        target.update_modifiers("AP1_checkpoint")
        self.assertNotIn(modifier, target.modifiers)
        self.assertEqual(target.dice_bonus, 0)

    def test_existing_modifier_subclasses_share_the_same_interface(self):
        target = create_servant()
        original_strength = target.strength.value
        original_plus = target.strength.plus
        original_dodge = target.dodge
        effects = [
            {
                "effect_type": "attribute_bonus",
                "effect_data": {
                    "effect_target": "strength",
                    "value": 1,
                },
            },
            {
                "effect_type": "plus_bonus",
                "effect_data": {
                    "effect_target": "strength",
                    "value": 1,
                },
            },
            {
                "effect_type": "dice_bonus",
                "effect_data": {
                    "effect_target": "dodge",
                    "value": 2,
                },
            },
        ]
        modifiers = [create_modifier(effect, target) for effect in effects]

        for modifier in modifiers:
            self.assertTrue(modifier.apply())
        self.assertEqual(target.strength.value, original_strength + 1)
        self.assertEqual(target.strength.plus, original_plus + 1)
        self.assertEqual(target.dodge, original_dodge + 2)

        for modifier in modifiers:
            self.assertTrue(modifier.remove())
        self.assertEqual(target.strength.value, original_strength)
        self.assertEqual(target.strength.plus, original_plus)
        self.assertEqual(target.dodge, original_dodge)

    def test_unknown_modifier_type_fails_immediately(self):
        with self.assertRaises(ValueError):
            create_modifier(
                {"effect_type": "not_a_modifier", "effect_data": {}},
                create_servant(),
            )

    def test_plus_bonus_is_capped_and_reallocated_after_removal(self):
        target = create_servant()
        first = create_modifier(
            {
                "modifier_id": "first_plus",
                "effect_type": "plus_bonus",
                "stacking": {"stack_scope": "independent"},
                "effect_data": {"effect_target": "strength", "value": 2},
            },
            target,
        )
        second = create_modifier(
            {
                "modifier_id": "second_plus",
                "effect_type": "plus_bonus",
                "stacking": {"stack_scope": "independent"},
                "effect_data": {"effect_target": "strength", "value": 1},
            },
            target,
        )

        target.add_modifier(first)
        target.add_modifier(second)
        self.assertEqual(target.strength.plus, 2)
        self.assertEqual(target.strength.plus_capacity, 2)
        self.assertEqual(target.strength.plus_bonus, 3)

        target.remove_modifier(first)
        self.assertEqual(target.strength.plus, 1)
        self.assertEqual(target.strength.plus_capacity, 1)
        self.assertEqual(target.strength.plus_bonus, 1)

    def test_plus_bonus_uses_separate_innate_capacity_and_battle_uses(self):
        target = Servant(
            "Saber",
            (3, 1),
            3,
            3,
            3,
            3,
            "Saber",
            "A",
        )
        self.assertEqual(target.strength.base_plus, 1)
        self.assertEqual(target.strength.plus_capacity, 1)
        self.assertTrue(target.consume_attribute_plus("strength"))
        self.assertEqual(target.strength.plus, 0)

        first_bonus = create_modifier(
            {
                "modifier_id": "battle_plus",
                "effect_type": "plus_bonus",
                "effect_data": {"effect_target": "strength", "value": 1},
            },
            target,
        )
        target.add_modifier(first_bonus)
        self.assertEqual(target.strength.base_plus, 1)
        self.assertEqual(target.strength.plus_capacity, 2)
        self.assertEqual(target.strength.plus, 1)

        capped_bonus = create_modifier(
            {
                "modifier_id": "capped_plus",
                "effect_type": "plus_bonus",
                "stacking": {"stack_scope": "independent"},
                "effect_data": {"effect_target": "strength", "value": 1},
            },
            target,
        )
        target.add_modifier(capped_bonus)
        self.assertEqual(target.strength.plus_capacity, 2)
        self.assertEqual(target.strength.plus, 1)

        target.start_battle()
        self.assertEqual(target.strength.plus, 2)
        self.assertTrue(target.consume_attribute_plus("strength", 2))
        self.assertEqual(target.strength.plus, 0)
        target.add_modifier(create_modifier(
            {
                "modifier_id": "over_cap_after_spending",
                "effect_type": "plus_bonus",
                "stacking": {"stack_scope": "independent"},
                "effect_data": {"effect_target": "strength", "value": 1},
            },
            target,
        ))
        self.assertEqual(target.strength.plus_capacity, 2)
        self.assertEqual(target.strength.plus, 0)
        target.start_battle()
        self.assertEqual(target.strength.plus, 2)

    def test_movement_and_visibility_bonus_apply_and_restore(self):
        target = create_servant()
        original_movement = target.move_conversion
        movement = create_modifier(
            {
                "effect_type": "movement_point_bonus",
                "effect_data": {"value": 1},
            },
            target,
        )
        visibility = create_modifier(
            {
                "effect_type": "visibility_bonus",
                "effect_data": {"value": 2},
            },
            target,
        )

        target.add_modifier(movement)
        target.add_modifier(visibility)
        self.assertEqual(target.move_conversion, original_movement + 1)
        self.assertEqual(target.visibility, 2)

        target.remove_modifier(movement)
        target.remove_modifier(visibility)
        self.assertEqual(target.move_conversion, original_movement)
        self.assertEqual(target.visibility, 0)

    def test_attribute_bonus_updates_all_dependent_stats_dynamically(self):
        target = create_servant()
        original = {
            "atk": target.atk,
            "physical_attack": target.physical_attack,
            "block": target.block,
            "escape": target.escape,
        }
        modifier = create_modifier(
            {
                "modifier_id": "strength_up",
                "effect_type": "attribute_bonus",
                "effect_data": {
                    "effect_target": "strength",
                    "value": 1,
                },
            },
            target,
        )

        target.add_modifier(modifier)
        self.assertEqual(target.atk, original["atk"] + 10)
        self.assertEqual(
            target.physical_attack,
            original["physical_attack"] + 1,
        )
        self.assertEqual(target.block, original["block"] + 2)
        self.assertEqual(target.escape, original["escape"] + 2)

        target.remove_modifier(modifier)
        for name, value in original.items():
            self.assertEqual(getattr(target, name), value)

    def test_manual_derived_assignment_survives_attribute_recalculation(self):
        target = create_servant()
        target.block = 100
        modifier = create_modifier(
            {
                "modifier_id": "manual_compatible_strength",
                "effect_type": "attribute_bonus",
                "effect_data": {
                    "effect_target": "strength",
                    "value": 1,
                },
            },
            target,
        )

        target.add_modifier(modifier)
        self.assertEqual(target.block, 102)
        target.remove_modifier(modifier)
        self.assertEqual(target.block, 100)

    def test_attribute_and_dice_modifiers_do_not_overwrite_each_other(self):
        target = create_servant()
        original_dodge = target.dodge
        dice = create_modifier(
            {
                "modifier_id": "dodge_dice_up",
                "effect_type": "dice_bonus",
                "effect_data": {
                    "effect_target": "dodge",
                    "value": 2,
                },
            },
            target,
        )
        flexibility = create_modifier(
            {
                "modifier_id": "flexibility_up",
                "effect_type": "attribute_bonus",
                "effect_data": {
                    "effect_target": "flexibility",
                    "value": 1,
                },
            },
            target,
        )

        target.add_modifier(dice)
        target.add_modifier(flexibility)
        self.assertEqual(target.dodge, original_dodge + 4)
        target.remove_modifier(dice)
        self.assertEqual(target.dodge, original_dodge + 2)
        target.remove_modifier(flexibility)
        self.assertEqual(target.dodge, original_dodge)

    def test_endurance_bonus_adds_and_removes_hp_without_damage_flow(self):
        target = create_servant()
        target.hp = 10
        modifier = create_modifier(
            {
                "modifier_id": "endurance_up",
                "effect_type": "attribute_bonus",
                "effect_data": {
                    "effect_target": "endurance",
                    "value": 1,
                },
            },
            target,
        )

        target.add_modifier(modifier)
        self.assertEqual(target.hpmax, 120)
        self.assertEqual(target.hp, 40)
        target.hp = 5
        target.remove_modifier(modifier)

        self.assertEqual(target.hpmax, 90)
        self.assertEqual(target.hp, 1)
        self.assertFalse(target.has_status("brink_of_death"))
        self.assertTrue(target.is_alive())

    def test_magic_bonus_adds_and_removes_mp_with_zero_floor(self):
        target = create_servant()
        target.mp = 10
        modifier = create_modifier(
            {
                "modifier_id": "magic_up",
                "effect_type": "attribute_bonus",
                "effect_data": {
                    "effect_target": "magic",
                    "value": 1,
                },
            },
            target,
        )

        target.add_modifier(modifier)
        self.assertEqual(target.mpmax, 120)
        self.assertEqual(target.mp, 40)
        target.mp = 5
        target.remove_modifier(modifier)

        self.assertEqual(target.mpmax, 90)
        self.assertEqual(target.mp, 0)

    def test_negative_endurance_modifier_changes_hp_symmetrically(self):
        target = create_servant()
        target.hp = 50
        modifier = create_modifier(
            {
                "modifier_id": "endurance_down",
                "effect_type": "attribute_bonus",
                "effect_data": {
                    "effect_target": "endurance",
                    "value": -1,
                },
            },
            target,
        )

        target.add_modifier(modifier)
        self.assertEqual(target.hpmax, 60)
        self.assertEqual(target.hp, 20)
        target.remove_modifier(modifier)
        self.assertEqual(target.hpmax, 90)
        self.assertEqual(target.hp, 50)

    def test_fortune_bonus_updates_rerolls_and_critical_qualifications(self):
        target = Servant("LowLuck", 3, 3, 3, 1, 1, "Saber", "A")
        self.assertEqual(target.luck_reroll_max, 0)
        self.assertFalse(target.can_critical_success)
        self.assertTrue(target.can_critical_failure)
        modifier = create_modifier(
            {
                "modifier_id": "fortune_up",
                "effect_type": "attribute_bonus",
                "effect_data": {
                    "effect_target": "fortune",
                    "value": 2,
                },
            },
            target,
        )

        target.add_modifier(modifier)
        self.assertEqual(target.luck_reroll_max, 1)
        self.assertEqual(target.luck_reroll, 1)
        self.assertTrue(target.can_critical_success)
        self.assertTrue(target.can_critical_failure)
        self.assertTrue(target.use_luck_reroll())
        target.remove_modifier(modifier)

        self.assertEqual(target.luck_reroll_max, 0)
        self.assertEqual(target.luck_reroll, 0)
        self.assertFalse(target.can_critical_success)
        self.assertTrue(target.can_critical_failure)


class ModifierManagerTests(unittest.TestCase):
    @staticmethod
    def phase_window_effect(
        modifier_id,
        *,
        phase,
        owner="target",
        occurrences=1,
    ):
        effect = numeric_effect(modifier_id, 4, duration=None)
        effect["phase_window"] = {
            "scope": "formal_battle",
            "phase": phase,
            "boundary": "phase_end",
            "owner": owner,
            "occurrences": occurrences,
        }
        return effect

    def test_phase_window_from_attack_expires_after_next_defense(self):
        target = create_servant("Target")
        other = create_servant("Other")
        battle = BattleManager([target, other])
        battle.current_character = target
        battle.current_phase = "attack"
        modifier = create_modifier(
            self.phase_window_effect("through_next_defense", phase="defense"),
            target,
        )
        target.add_modifier(modifier)

        battle.finish_formal_phase("attack", target)
        self.assertIn(modifier, target.modifiers)
        battle.finish_formal_phase("defense", other)
        self.assertIn(modifier, target.modifiers)
        battle.finish_formal_phase("defense", target)

        self.assertNotIn(modifier, target.modifiers)
        self.assertEqual(target.dice_bonus, 0)


class ModifierConsumptionTests(unittest.TestCase):
    @staticmethod
    def attack_bonus_effect(
        modifier_id="next_attack",
        *,
        uses=1,
        mode="automatic",
        remove_when_empty=True,
        use_refresh_rule="reset",
        conditions=None,
    ):
        return {
            "modifier_id": modifier_id,
            "effect_type": "attack_bonus",
            "conditions": dict(conditions or {}),
            "consumption": {
                "event": "attack_committed",
                "uses": uses,
                "mode": mode,
                "remove_when_empty": remove_when_empty,
                "use_refresh_rule": use_refresh_rule,
            },
            "effect_data": {"value": 20},
        }

    def test_attack_committed_snapshots_bonus_then_consumes_it(self):
        actor = create_servant("Actor")
        modifier = create_modifier(self.attack_bonus_effect(), actor)
        actor.add_modifier(modifier)

        profile = Action(actor, "attack").build_attack_profile(for_offset=True)

        self.assertEqual(profile.value, 50)
        self.assertNotIn(modifier, actor.modifiers)
        later = Action(actor, "attack").build_attack_profile(for_offset=True)
        self.assertEqual(later.value, 30)

    def test_offset_counts_as_next_attack_unless_explicitly_excluded(self):
        actor = create_servant("Actor")
        included = create_modifier(
            self.attack_bonus_effect("included"),
            actor,
        )
        excluded = create_modifier(
            self.attack_bonus_effect(
                "excluded",
                conditions={"exclude_tags": ["offset"]},
            ),
            actor,
        )
        actor.add_modifier(included)
        actor.add_modifier(excluded)

        profile = Action(actor, "attack").build_attack_profile(for_offset=True)

        self.assertEqual(profile.value, 50)
        self.assertNotIn(included, actor.modifiers)
        self.assertIn(excluded, actor.modifiers)

    def test_optional_refusal_waits_and_acceptance_consumes(self):
        actor = create_servant("Actor")
        modifier = create_modifier(
            self.attack_bonus_effect("optional", mode="optional"),
            actor,
        )
        actor.add_modifier(modifier)
        context = {"actor": actor, "action_id": "attack"}

        refused = actor.modifier_manager.consume_event(
            "attack_committed",
            context,
        )
        self.assertEqual(refused["pending_optional"], [modifier])
        self.assertIn(modifier, actor.modifiers)

        accepted = actor.modifier_manager.consume_event(
            "attack_committed",
            context,
            optional_decider=lambda *_args: True,
        )
        self.assertEqual(accepted["consumed"], [modifier])
        self.assertNotIn(modifier, actor.modifiers)

    def test_optional_modifier_is_inert_until_prepared(self):
        actor = create_servant("Actor")
        modifier = create_modifier(
            self.attack_bonus_effect("optional", mode="optional"),
            actor,
        )
        actor.add_modifier(modifier)
        waiting = Action(actor, "attack").build_attack_profile(for_offset=True)
        self.assertEqual(waiting.value, 30)
        self.assertIn(modifier, actor.modifiers)

        context = {
            "actor": actor,
            "action_id": "attack",
            "tags": {"offset"},
        }
        actor.modifier_manager.prepare_event(
            "attack_committed",
            context,
            optional_decider=lambda *_args: True,
        )
        accepted = Action(actor, "attack").build_attack_profile(for_offset=True)

        self.assertEqual(accepted.value, 50)
        self.assertNotIn(modifier, actor.modifiers)

    def test_use_refresh_rules_are_independent_from_stack_count(self):
        for rule, expected in (
            ("reset", 2),
            ("keep_more", 2),
            ("extend", 3),
            ("unchanged", 1),
        ):
            with self.subTest(rule=rule):
                actor = create_servant(rule)
                effect = self.attack_bonus_effect(
                    f"refresh_{rule}",
                    uses=2,
                    use_refresh_rule=rule,
                )
                current = create_modifier(effect, actor)
                actor.add_modifier(current)
                current.consume_use()
                actor.add_modifier(create_modifier(effect, actor))
                self.assertEqual(current.remaining_uses, expected)
                self.assertEqual(current.stack_count, 1)

    def test_remove_when_empty_false_keeps_inert_record(self):
        actor = create_servant("Actor")
        modifier = create_modifier(
            self.attack_bonus_effect(
                "inert_record",
                remove_when_empty=False,
            ),
            actor,
        )
        actor.add_modifier(modifier)

        first = Action(actor, "attack").build_attack_profile(for_offset=True)
        second = Action(actor, "attack").build_attack_profile(for_offset=True)

        self.assertEqual(first.value, 50)
        self.assertEqual(second.value, 30)
        self.assertIn(modifier, actor.modifiers)
        self.assertFalse(modifier.applied)

    def test_damage_received_only_consumes_on_positive_final_damage(self):
        actor = create_servant("Actor")
        target = create_servant("Target")
        effect = numeric_effect("on_damage", 2)
        effect["consumption"] = {
            "event": "damage_received",
            "uses": 1,
        }
        modifier = create_modifier(effect, target)
        target.add_modifier(modifier)

        DamageResolver().resolve(DamageEvent(actor, target, 0, "physical"))
        self.assertIn(modifier, target.modifiers)
        DamageResolver().resolve(DamageEvent(actor, target, 1, "physical"))
        self.assertNotIn(modifier, target.modifiers)

    def test_multi_target_context_union_consumes_once(self):
        actor = create_servant("Actor")
        ally = create_servant("Ally")
        enemy = create_servant("Enemy")
        actor.add_ally(ally)
        effect = self.attack_bonus_effect(
            "enemy_only",
            uses=2,
            conditions={"target_relations": ["enemy"]},
        )
        modifier = create_modifier(effect, actor)
        actor.add_modifier(modifier)

        actor.modifier_manager.consume_event(
            "attack_committed",
            [
                {"actor": actor, "target": ally},
                {"actor": actor, "target": enemy},
            ],
        )

        self.assertEqual(modifier.remaining_uses, 1)

    def test_multi_target_skill_snapshots_one_use_for_every_target(self):
        actor = create_servant("Actor")
        first = create_servant("First")
        second = create_servant("Second")
        skill = actor.create_personal_skill({
            "skill_id": "area_attack",
            "name": "范围攻击",
            "rank": "C",
            "components": [{
                "component_id": "attack",
                "type": "active",
                "target": "selectable_character",
                "effects": [{
                    "effect_type": "create_attack_event",
                    "effect_data": {"damage_type": "physical"},
                }],
            }],
        })
        modifier = create_modifier(self.attack_bonus_effect(), actor)
        actor.add_modifier(modifier)

        result = actor.resolve_skill_component(
            skill.skill_id,
            "attack",
            targets=[first, second],
        )
        profiles = [
            attack.attack_profile
            for attack in result["results"]
        ]

        self.assertEqual([profile.value for profile in profiles], [50, 50])
        self.assertNotIn(modifier, actor.modifiers)


class ModifierManagerContinuationTests(unittest.TestCase):
    phase_window_effect = staticmethod(
        ModifierManagerTests.phase_window_effect
    )

    def test_current_phase_window_expires_at_current_formal_phase_end(self):
        target = create_servant("Target")
        other = create_servant("Other")
        battle = BattleManager([target, other])
        battle.current_character = target
        battle.current_phase = "defense"
        modifier = create_modifier(
            self.phase_window_effect("one_defense", phase="defense"),
            target,
        )
        target.add_modifier(modifier)

        battle.finish_formal_phase()

        self.assertNotIn(modifier, target.modifiers)

    def test_simple_round_phase_does_not_consume_formal_phase_window(self):
        target = create_servant("Target")
        other = create_servant("Other")
        modifier = create_modifier(
            self.phase_window_effect("formal_only", phase="defense"),
            target,
        )
        target.add_modifier(modifier)

        target.update_phase_window_modifiers(
            scope="simple_round",
            phase="defense",
            boundary="phase_end",
            phase_actor=target,
        )

        self.assertIn(modifier, target.modifiers)
        battle = BattleManager([target, other])
        battle.finish_formal_phase("defense", target)
        self.assertNotIn(modifier, target.modifiers)

    def test_source_owned_window_uses_source_phase(self):
        source = create_servant("Source")
        target = create_servant("Target")
        battle = BattleManager([source, target])
        modifier = create_modifier(
            self.phase_window_effect(
                "source_attack",
                phase="attack",
                owner="source",
            ),
            target,
            source=source,
        )
        target.add_modifier(modifier)

        battle.finish_formal_phase("attack", target)
        self.assertIn(modifier, target.modifiers)
        battle.finish_formal_phase("attack", source)
        self.assertNotIn(modifier, target.modifiers)

    def test_leaving_battle_clears_only_battle_phase_windows(self):
        target = create_servant("Target")
        target.in_battle = True
        window = create_modifier(
            self.phase_window_effect("battle_window", phase="defense"),
            target,
        )
        ordinary = create_modifier(
            numeric_effect("ordinary", 2, duration=3),
            target,
        )
        target.add_modifier(window)
        target.add_modifier(ordinary)

        target.in_battle = False

        self.assertNotIn(window, target.modifiers)
        self.assertIn(ordinary, target.modifiers)

    def test_source_leaving_clears_source_owned_window_on_another_character(self):
        source = create_servant("Source")
        target = create_servant("Target")
        battle = BattleManager([source, target])
        source.current_battle = battle
        target.current_battle = battle
        source.in_battle = True
        target.in_battle = True
        window = create_modifier(
            self.phase_window_effect(
                "source_owned",
                phase="attack_phase",
                owner="source",
            ),
            target,
            source=source,
        )
        target.add_modifier(window)

        battle.remove_participant(source)

        self.assertNotIn(window, target.modifiers)

    def test_phase_window_refresh_resets_remaining_occurrences(self):
        target = create_servant("Target")
        other = create_servant("Other")
        battle = BattleManager([target, other])
        effect = self.phase_window_effect(
            "refreshing_window",
            phase="defense",
            occurrences=2,
        )
        first = create_modifier(effect, target, source=target)
        target.add_modifier(first)
        battle.finish_formal_phase("defense", target)
        self.assertEqual(first.phase_window_remaining, 1)

        result = target.add_modifier(
            create_modifier(effect, target, source=target)
        )

        self.assertEqual(result.outcome, "refreshed")
        self.assertEqual(first.phase_window_remaining, 2)

    def test_strongest_higher_replaces_stronger_and_equal_incoming_effects(self):
        target = create_servant()
        first = numeric_effect(
            "strongest_buff",
            2,
            rule="strongest",
            scope="all_sources",
            duration=5,
        )
        stronger = numeric_effect(
            "strongest_buff",
            5,
            rule="strongest",
            scope="all_sources",
            duration=2,
        )
        equal = numeric_effect(
            "strongest_buff",
            5,
            rule="strongest",
            scope="all_sources",
            duration=4,
        )
        first["stacking"]["strength_comparison"] = "higher"
        stronger["stacking"]["strength_comparison"] = "higher"
        equal["stacking"]["strength_comparison"] = "higher"
        first_modifier = create_modifier(first, target, source_id="first")
        stronger_modifier = create_modifier(stronger, target, source_id="stronger")
        equal_modifier = create_modifier(equal, target, source_id="equal")

        target.add_modifier(first_modifier)
        stronger_result = target.add_modifier(stronger_modifier)
        equal_result = target.add_modifier(equal_modifier)

        self.assertEqual(stronger_result.outcome, "replaced_stronger")
        self.assertIs(stronger_result.replaced_modifier, first_modifier)
        self.assertEqual(equal_result.outcome, "replaced_equal")
        self.assertIs(equal_result.replaced_modifier, stronger_modifier)
        self.assertEqual(target.modifiers, [equal_modifier])
        self.assertEqual(equal_modifier.duration, 4)
        self.assertEqual(target.dice_bonus, 5)

    def test_strongest_weaker_is_rejected_without_refreshing_duration(self):
        target = create_servant()
        strong = numeric_effect(
            "strongest_buff",
            5,
            rule="strongest",
            scope="all_sources",
            duration=3,
        )
        weak = numeric_effect(
            "strongest_buff",
            2,
            rule="strongest",
            scope="all_sources",
            duration=9,
        )
        strong["stacking"]["strength_comparison"] = "higher"
        weak["stacking"]["strength_comparison"] = "higher"
        strong_modifier = create_modifier(strong, target)
        target.add_modifier(strong_modifier)
        target.update_modifiers()

        result = target.add_modifier(create_modifier(weak, target))

        self.assertEqual(result.outcome, "kept_stronger")
        self.assertIs(result.modifier, strong_modifier)
        self.assertEqual(strong_modifier.duration, 2)
        self.assertEqual(target.dice_bonus, 5)

    def test_strongest_lower_uses_more_negative_total_value(self):
        target = create_servant()
        weak = numeric_effect(
            "strongest_debuff",
            -2,
            rule="strongest",
            scope="all_sources",
        )
        strong = numeric_effect(
            "strongest_debuff",
            -6,
            rule="strongest",
            scope="all_sources",
        )
        weak["stacking"]["strength_comparison"] = "lower"
        strong["stacking"]["strength_comparison"] = "lower"

        target.add_modifier(create_modifier(weak, target))
        result = target.add_modifier(create_modifier(strong, target))

        self.assertEqual(result.outcome, "replaced_stronger")
        self.assertEqual(target.dice_bonus, -6)

    def test_strongest_complex_effect_requires_and_uses_priority(self):
        target = create_servant()
        low = {
            "modifier_id": "strongest_status",
            "effect_type": "add_status",
            "stacking": {
                "stack_group": "strongest_status",
                "stack_scope": "all_sources",
                "stacking_rule": "strongest",
                "strength_priority": 1,
            },
            "effect_data": {"value": "marked", "duration": 2},
        }
        high = {
            **low,
            "stacking": {
                **low["stacking"],
                "strength_priority": 3,
            },
            "effect_data": {"value": "marked", "duration": 4},
        }

        low_modifier = create_modifier(low, target)
        high_modifier = create_modifier(high, target)
        target.add_modifier(low_modifier)
        result = target.add_modifier(high_modifier)

        self.assertEqual(result.outcome, "replaced_stronger")
        self.assertEqual(target.modifiers, [high_modifier])
        self.assertTrue(target.has_status("marked"))

    def test_battle_turn_end_ticks_duration_before_later_characters_act(self):
        target = create_servant("Target")
        later = create_servant("Later")
        target.current_global_turn = 3
        later.current_global_turn = 3
        modifier = create_modifier(
            numeric_effect("battle_tick", 2, duration=2),
            target,
        )
        target.add_modifier(modifier)
        battle = BattleManager([target, later])
        battle.global_turn = 3
        battle.current_order = [target, later]
        battle.current_character = target
        battle.current_index = 0
        battle.current_phase = "turn_end"

        self.assertTrue(battle.finish_current_character())
        self.assertEqual(modifier.duration, 1)
        self.assertIs(battle.current_character, later)

        target.update_modifiers("global_turn_end", turn_number=3)
        self.assertEqual(modifier.duration, 1)
        self.assertIn(modifier, target.modifiers)

        target.update_modifiers("battle_turn_end", turn_number=4)
        self.assertNotIn(modifier, target.modifiers)

    def test_modifier_applied_after_battle_tick_still_ticks_at_global_end(self):
        target = create_servant("Target")
        first = create_modifier(
            numeric_effect("first", 1, duration=2),
            target,
        )
        target.add_modifier(first)
        target.update_modifiers("battle_turn_end", turn_number=5)

        late = create_modifier(
            numeric_effect("late", 1, duration=2),
            target,
        )
        target.add_modifier(late)
        target.update_modifiers("global_turn_end", turn_number=5)

        self.assertEqual(first.duration, 1)
        self.assertEqual(late.duration, 1)

    def test_reject_keeps_the_existing_modifier(self):
        target = create_servant()
        first = create_modifier(
            numeric_effect("unique", 2, rule="reject", scope="all_sources"),
            target,
        )
        second = create_modifier(
            numeric_effect("unique", 5, rule="reject", scope="all_sources"),
            target,
        )

        self.assertEqual(target.add_modifier(first).outcome, "applied")
        result = target.add_modifier(second)
        self.assertEqual(result.outcome, "rejected")
        self.assertIs(result.modifier, first)
        self.assertEqual(target.dice_bonus, 2)
        self.assertEqual(target.modifiers, [first])

    def test_refresh_updates_duration_without_reapplying_value(self):
        target = create_servant()
        effect = numeric_effect("refreshing", 2, duration=3)
        first = create_modifier(effect, target, source=target)
        target.add_modifier(first)
        target.update_modifiers()
        self.assertEqual(first.duration, 2)

        second = create_modifier(effect, target, source=target)
        result = target.add_modifier(second)
        self.assertEqual(result.outcome, "refreshed")
        self.assertIs(result.modifier, first)
        self.assertEqual(first.duration, 3)
        self.assertEqual(target.dice_bonus, 2)
        self.assertEqual(len(target.modifiers), 1)

    def test_replace_removes_old_value_and_keeps_list_position(self):
        target = create_servant()
        first = create_modifier(
            numeric_effect("replaceable", 2, rule="replace"),
            target,
        )
        second = create_modifier(
            numeric_effect("replaceable", 5, rule="replace"),
            target,
        )
        target.add_modifier(first)

        result = target.add_modifier(second)
        self.assertEqual(result.outcome, "replaced")
        self.assertIs(result.replaced_modifier, first)
        self.assertFalse(first.applied)
        self.assertEqual(target.modifiers, [second])
        self.assertEqual(target.dice_bonus, 5)

    def test_stack_uses_value_per_stack_and_refreshes_at_maximum(self):
        target = create_servant()
        effect = numeric_effect(
            "stacking",
            2,
            rule="stack",
            duration=3,
            max_stacks=3,
        )
        first = create_modifier(effect, target, source=target)
        target.add_modifier(first)
        target.update_modifiers()

        self.assertEqual(target.add_modifier(
            create_modifier(effect, target, source=target)
        ).outcome, "stacked")
        self.assertEqual(target.add_modifier(
            create_modifier(effect, target, source=target)
        ).outcome, "stacked")
        self.assertEqual(first.stack_count, 3)
        self.assertEqual(target.dice_bonus, 6)

        target.update_modifiers()
        result = target.add_modifier(
            create_modifier(effect, target, source=target)
        )
        self.assertEqual(result.outcome, "refreshed")
        self.assertEqual(first.stack_count, 3)
        self.assertEqual(first.duration, 3)
        self.assertEqual(target.dice_bonus, 6)

    def test_independent_modifiers_coexist(self):
        target = create_servant()
        effect = numeric_effect(
            "independent",
            2,
            rule="independent",
            scope="independent",
        )
        first = create_modifier(effect, target)
        second = create_modifier(effect, target)
        target.add_modifier(first)
        target.add_modifier(second)

        self.assertEqual(target.modifiers, [first, second])
        self.assertEqual(target.dice_bonus, 4)

    def test_status_remains_until_its_last_modifier_source_is_removed(self):
        target = create_servant()
        first_source = create_servant("First")
        second_source = create_servant("Second")
        effect = {
            "modifier_id": "marked",
            "effect_type": "add_status",
            "stacking": {
                "stack_group": "marked",
                "stack_scope": "same_source",
                "stacking_rule": "refresh",
                "max_stacks": 1,
            },
            "effect_data": {"value": "marked", "duration": 3},
        }
        first = create_modifier(effect, target, source=first_source)
        second = create_modifier(effect, target, source=second_source)
        target.add_modifier(first)
        target.add_modifier(second)

        self.assertTrue(target.has_status("marked"))
        self.assertEqual(target.status_sources["marked"], {first, second})
        target.remove_modifier(first)
        self.assertTrue(target.has_status("marked"))
        target.remove_modifier(second)
        self.assertFalse(target.has_status("marked"))

    def test_death_removes_normal_modifiers_but_persistent_ones_keep_ticking(self):
        target = create_master("Target")
        survivor = create_master("Survivor")
        normal = create_modifier(
            numeric_effect("normal", 2, rule="independent"),
            target,
        )
        persistent_effect = numeric_effect(
            "persistent",
            3,
            rule="independent",
            duration=2,
        )
        persistent_effect["persist_after_death"] = True
        persistent = create_modifier(persistent_effect, target)
        target.add_modifier(normal)
        target.add_modifier(persistent)

        game = GameManager([target, survivor], Location("Grail"))
        game.start_game()
        target.die()

        self.assertNotIn(normal, target.modifiers)
        self.assertIn(persistent, target.modifiers)
        self.assertEqual(target.dice_bonus, 3)

        game.turn_manager.start_turn()
        game.turn_manager.end_turn()
        self.assertEqual(persistent.duration, 1)
        game.turn_manager.start_turn()
        game.turn_manager.end_turn()
        self.assertNotIn(persistent, target.modifiers)
        self.assertEqual(target.dice_bonus, 0)


if __name__ == "__main__":
    unittest.main()
