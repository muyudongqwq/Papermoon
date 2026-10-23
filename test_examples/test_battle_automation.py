import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from game.action.action import Action
from game.character.servants import Servant
from game.map.map import Location
from game.modifier.modifier import create_modifier
from game.turn.battle import BattleManager
from game.turn.damage import AttackEvent, DamageEvent, DamageResolver
from game.turn.defense import DefenseResolver
from game.turn.decision import (
    DecisionOption,
    DecisionRequest,
    ScriptedDecisionProvider,
    TerminalDecisionProvider,
)


def create_servant(name, strength, endurance, flexibility):
    return Servant(
        name=name,
        strength=strength,
        endurance=endurance,
        flexibility=flexibility,
        magic=3,
        fortune=3,
        servant_class=name,
        noble="A",
    )


def damage_modifier_effect(
    modifier_id,
    direction,
    calculation,
    value,
    **filters,
):
    effect_data = {
        "direction": direction,
        "calculation": calculation,
        "value": value,
    }
    effect_data.update(filters)
    return {
        "modifier_id": modifier_id,
        "effect_type": "damage_modifier",
        "stacking": {
            "stack_group": modifier_id,
            "stack_scope": "all_sources",
            "stacking_rule": "replace",
        },
        "effect_data": effect_data,
    }


def shield_effect(modifier_id, value, priority=0, damage_types=None):
    effect_data = {"value": value}
    if damage_types is not None:
        effect_data["damage_types"] = damage_types
    return {
        "modifier_id": modifier_id,
        "effect_type": "shield",
        "stacking": {"priority": priority},
        "effect_data": effect_data,
    }


class DecisionRequestTests(unittest.TestCase):
    def test_option_can_hold_an_arbitrary_effect_object(self):
        effect = {"effect_type": "damage", "effect_data": {"value": 30}}
        request = DecisionRequest(
            character="Caster",
            phase="技能效果选择",
            prompt="请选择效果",
            options=(DecisionOption("魔弹效果", effect),),
        )

        self.assertIs(request.resolve("1"), effect)
        self.assertIs(request.resolve("魔弹效果"), effect)

    def test_terminal_provider_prints_character_phase_and_options(self):
        saber = create_servant("Saber", 10, 5, 4)
        request = DecisionRequest(
            character=saber,
            phase="攻击",
            prompt="请选择行动。",
            options=(
                DecisionOption("普通攻击", "attack"),
                DecisionOption("结束攻击阶段", "end"),
            ),
        )
        output = StringIO()

        with patch("builtins.input", return_value="1"), redirect_stdout(output):
            result = TerminalDecisionProvider().choose(request)

        self.assertEqual(result, "attack")
        terminal_text = output.getvalue()
        self.assertIn("Saber", terminal_text)
        self.assertIn("处于：攻击阶段", terminal_text)
        self.assertIn("1.普通攻击", terminal_text)
        self.assertIn("2.结束攻击阶段", terminal_text)


class BattleAutomationTests(unittest.TestCase):
    def test_true_damage_uses_canonical_name_and_bypasses_mitigation(self):
        attacker = create_servant("Caster", 3, 5, 3)
        defender = create_servant("Saber", 3, 20, 3)
        defender.magic_resistance = 0.9
        defender.add_modifier(create_modifier(
            damage_modifier_effect(
                "universal_reduction",
                "incoming",
                "percentage",
                -0.75,
                damage_types=["all"],
            ),
            defender,
        ))
        shield = create_modifier(shield_effect("barrier", 100), defender)
        defender.add_modifier(shield)
        starting_hp = defender.hp
        event = DamageEvent(attacker, defender, 30, "true_damage")

        self.assertEqual(event.damage_type, "true_damage")
        self.assertEqual(DamageResolver().resolve(event), 30)
        self.assertEqual(defender.hp, starting_hp - 30)
        self.assertEqual(shield.remaining_value, 100)

    def test_true_damage_is_still_prevented_by_brink_of_death(self):
        attacker = create_servant("Caster", 3, 5, 3)
        defender = create_servant("Saber", 3, 20, 3)
        defender.enter_brink()

        self.assertEqual(
            DamageResolver().resolve(
                DamageEvent(attacker, defender, 30, "true_damage")
            ),
            0,
        )

    def test_healing_is_not_a_damage_type(self):
        attacker = create_servant("Caster", 3, 5, 3)
        defender = create_servant("Saber", 3, 20, 3)
        with self.assertRaises(ValueError):
            DamageEvent(attacker, defender, 30, "healing")

    def test_brink_prevents_all_incoming_damage_without_consuming_shield(self):
        attacker = create_servant("Saber", 5, 5, 5)
        defender = create_servant("Archer", 3, 5, 3)
        defender.enter_brink()
        shield = create_modifier(shield_effect("barrier", 10), defender)
        defender.add_modifier(shield)
        starting_hp = defender.hp
        event = DamageEvent(attacker, defender, 100, "physical")

        self.assertEqual(DamageResolver().resolve(event), 0)
        self.assertEqual(defender.hp, starting_hp)
        self.assertEqual(shield.remaining_value, 10)

    def test_brink_outgoing_half_is_combined_before_flat_damage(self):
        attacker = create_servant("Saber", 5, 5, 5)
        defender = create_servant("Archer", 3, 20, 3)
        attacker.enter_brink()
        event = DamageEvent(
            attacker,
            defender,
            100,
            "physical",
            percentage_modifiers=[0.25],
            flat_modifiers=[10],
        )

        # +25%与濒死-50%先合并为-25%，之后再加固定值10。
        self.assertEqual(DamageResolver().calculate(event), 85)

    def test_attack_snapshots_brink_outgoing_penalty_until_defense(self):
        attacker = create_servant("Saber", 5, 5, 5)
        defender = create_servant("Archer", 3, 20, 3)
        location = Location("Arena")
        attacker.position = defender.position = location
        attacker.update_visibility([attacker, defender])
        attacker.enter_brink()
        action = Action(
            attacker,
            "attack",
            defender,
            damage_value=100,
            ignore_attack_phase_count=True,
        )

        self.assertTrue(action.attack())
        attacker.remove_status_modifiers("brink_of_death")
        event = DefenseResolver().create_damage_event(
            defender,
            action.created_attack_event,
        )
        self.assertEqual(DamageResolver().calculate(event), 50)

    def test_damage_calculation_combines_percentages_before_flat_modifiers(self):
        attacker = create_servant("Saber", 5, 5, 5)
        defender = create_servant("Archer", 3, 3, 3)
        event = DamageEvent(
            source=attacker,
            target=defender,
            value=101,
            damage_type="physical",
            percentage_modifiers=[0.5, -0.25],
            flat_modifiers=[-0.5],
        )

        self.assertEqual(DamageResolver().calculate(event), 125)

    def test_calculated_values_truncate_toward_zero(self):
        character = create_servant("Saber", 3, 3, 3)
        character.hp = 1
        character.mp = 1

        character.heal(6.9)
        character.recover_mp(6.9)

        self.assertEqual(character.hp, 7)
        self.assertEqual(character.mp, 7)

    def test_outgoing_damage_is_snapshotted_and_incoming_is_read_on_resolution(self):
        attacker = create_servant("Saber", 5, 5, 5)
        defender = create_servant("Archer", 3, 20, 3)
        location = Location("Arena")
        attacker.position = defender.position = location
        attacker.update_visibility([attacker, defender])

        outgoing = create_modifier(
            damage_modifier_effect(
                "outgoing_boost",
                "outgoing",
                "percentage",
                0.5,
            ),
            attacker,
        )
        attacker.add_modifier(outgoing)
        action = Action(
            attacker,
            "attack",
            target=defender,
            damage_value=30,
            ignore_attack_phase_count=True,
        )
        self.assertTrue(action.attack())

        attacker.remove_modifier(outgoing)
        defender.add_modifier(create_modifier(
            damage_modifier_effect(
                "incoming_reduction",
                "incoming",
                "percentage",
                -0.25,
            ),
            defender,
        ))
        result = DefenseResolver().finish_attack(
            defender,
            action.created_attack_event,
            hit=True,
        )

        self.assertEqual(result["damage"], 37)
        self.assertEqual(action.created_attack_event.percentage_modifiers, [0.5])

    def test_damage_modifier_filters_and_flat_modifiers_apply_after_percentage(self):
        attacker = create_servant("Caster", 3, 5, 3)
        defender = create_servant("Saber", 3, 20, 3)
        matching = damage_modifier_effect(
            "matching",
            "incoming",
            "percentage",
            -0.25,
            damage_types=["magic"],
            action_ids=["spell"],
            skill_ids=["fireball"],
            source_tags=["flame"],
        )
        defender.add_modifier(create_modifier(matching, defender))
        defender.add_modifier(create_modifier(
            damage_modifier_effect(
                "flat_ward",
                "incoming",
                "flat",
                -5,
                damage_types=["magic"],
            ),
            defender,
        ))

        matched = DamageEvent(
            attacker,
            defender,
            101,
            "magic",
            action_id="spell",
            skill_id="fireball",
            source_tags={"flame"},
        )
        unmatched = DamageEvent(
            attacker,
            defender,
            101,
            "magic",
            action_id="attack",
            skill_id="fireball",
            source_tags={"flame"},
        )

        self.assertEqual(DamageResolver().calculate(matched), 70)
        self.assertEqual(DamageResolver().calculate(unmatched), 96)

    def test_shields_absorb_by_priority_then_application_order(self):
        attacker = create_servant("Saber", 3, 3, 3)
        defender = create_servant("Archer", 3, 20, 3)
        oldest = create_modifier(shield_effect("oldest", 10), defender)
        newest = create_modifier(shield_effect("newest", 10), defender)
        priority = create_modifier(shield_effect("priority", 5, priority=1), defender)
        defender.add_modifier(oldest)
        defender.add_modifier(newest)
        defender.add_modifier(priority)
        starting_hp = defender.hp
        event = DamageEvent(attacker, defender, 12, "physical")

        self.assertEqual(DamageResolver().resolve(event), 0)
        self.assertEqual(defender.hp, starting_hp)
        self.assertEqual(
            [(shield.modifier_id, amount) for shield, amount in event.shield_absorptions],
            [("priority", 5), ("oldest", 7)],
        )
        self.assertEqual(oldest.remaining_value, 3)
        self.assertEqual(newest.remaining_value, 10)

    def test_reapplying_same_shield_id_replaces_remaining_shield(self):
        defender = create_servant("Saber", 3, 20, 3)
        attacker = create_servant("Archer", 3, 3, 3)
        original = create_modifier(shield_effect("barrier", 10), defender)
        defender.add_modifier(original)
        DamageResolver().resolve(DamageEvent(attacker, defender, 6, "physical"))
        self.assertEqual(original.remaining_value, 4)

        replacement = create_modifier(shield_effect("barrier", 8), defender)
        result = defender.add_modifier(replacement)

        self.assertEqual(result.outcome, "replaced")
        self.assertEqual(defender.shield, 8)
        self.assertEqual(replacement.remaining_value, 8)
        self.assertNotIn(original, defender.modifiers)
        self.assertEqual(
            [modifier for modifier in defender.modifiers if modifier.modifier_id == "barrier"],
            [replacement],
        )

    def test_shield_damage_type_and_ignore_shield_are_respected(self):
        attacker = create_servant("Saber", 3, 3, 3)
        defender = create_servant("Archer", 3, 20, 3)
        physical_shield = create_modifier(
            shield_effect("physical_barrier", 10, damage_types=["physical"]),
            defender,
        )
        defender.add_modifier(physical_shield)
        starting_hp = defender.hp

        magic_event = DamageEvent(attacker, defender, 4, "magic")
        self.assertEqual(DamageResolver().resolve(magic_event), 4)
        self.assertEqual(physical_shield.remaining_value, 10)
        bypass_event = DamageEvent(
            attacker,
            defender,
            4,
            "physical",
            ignore_shield=True,
        )
        self.assertEqual(DamageResolver().resolve(bypass_event), 4)
        self.assertEqual(physical_shield.remaining_value, 10)
        self.assertEqual(defender.hp, starting_hp - 8)

    def test_magic_damage_uses_magic_rank_and_magic_resistance(self):
        attacker = create_servant("Caster", 3, 5, 3)
        defender = create_servant("Saber", 3, 5, 3)
        location = Location("Arena")
        attacker.position = defender.position = location
        attacker.update_visibility([attacker, defender])
        defender.magic_resistance = 0.25

        action = Action.create_magic_attack(
            attacker,
            defender,
            ignore_attack_phase_count=True,
        )
        self.assertTrue(action.attack())
        event = action.created_attack_event
        self.assertEqual(event.value, attacker.magic.value * 10)
        self.assertEqual(event.damage_type, "magic")
        self.assertEqual(DamageResolver().calculate(DamageEvent(
            source=attacker,
            target=defender,
            value=event.value,
            damage_type=event.damage_type,
        )), 22)

    def test_each_pending_attack_requests_its_own_defense_in_list_order(self):
        defender = create_servant("Saber", 3, 10, 10)
        attacker = create_servant("Archer", 3, 10, 3)
        location = Location("Arena")
        defender.position = attacker.position = location
        battle = BattleManager([defender, attacker])
        battle.start_battle()
        defender.pending_attacks.extend([
            AttackEvent(attacker, defender, 1, "physical", 100, None),
            AttackEvent(attacker, defender, 1, "physical", 100, None),
        ])
        decisions = ScriptedDecisionProvider([
            "dodge",
            "block",
            "stay",
            "stay",
        ])

        self.assertTrue(battle.run_battle_turn(decisions))
        self.assertEqual(
            [request.phase for request in decisions.requests[:2]],
            ["防御", "防御"],
        )
        self.assertEqual(defender.pending_attacks, [])
        self.assertEqual(defender.last_defense_attack_count, 2)

    def test_random_defense_only_chooses_dodge_or_block(self):
        defender = create_servant("Berserker", 3, 10, 3)
        attacker = create_servant("Archer", 3, 3, 3)
        location = Location("Arena")
        defender.position = attacker.position = location
        battle = BattleManager([defender, attacker])
        battle.start_battle()
        defender.pending_attacks.append(
            AttackEvent(attacker, defender, 1, "physical", 100, None)
        )
        defender.attack_phase_count = 1
        defender.add_modifier(create_modifier(
            {
                "modifier_id": "random_defense",
                "effect_type": "add_status",
                "effect_data": {"status_id": "random_defense"},
            },
            defender,
        ))
        decisions = ScriptedDecisionProvider(["dodge"])

        with patch(
            "game.turn.battle.random.choice",
            side_effect=lambda entries: entries[-1],
        ) as random_choice:
            defense_type = battle.request_defense(defender, decisions)

        self.assertIn(defense_type, {"dodge", "block"})
        self.assertNotEqual(defense_type, "offset")
        self.assertEqual(len(decisions.requests), 1)
        self.assertTrue(random_choice.called)

    def test_defense_phase_announces_new_brink_state_once(self):
        attacker = create_servant("Saber", 5, 5, 5)
        defender = create_servant("Archer", 3, 3, 3)
        defender.hp = 10
        attack = AttackEvent(
            source=attacker,
            target=defender,
            value=50,
            damage_type="physical",
            attack_roll=100,
            skill=None,
        )
        output = StringIO()

        with patch("game.turn.defense.random.randint", return_value=1), redirect_stdout(output):
            DefenseResolver().resolve_phase(
                defender,
                "dodge",
                attacks=[attack],
            )

        self.assertTrue(defender.has_status("brink_of_death"))
        self.assertEqual(
            output.getvalue().count("Archer进入了濒死状态。"),
            1,
        )

    def test_attack_target_back_returns_to_attack_action_selection(self):
        saber = create_servant("Saber", 5, 5, 5)
        archer = create_servant("Archer", 3, 3, 3)
        location = Location("Arena")
        saber.position = archer.position = location
        battle = BattleManager([saber, archer])
        battle.start_battle()
        decisions = ScriptedDecisionProvider([
            "attack",
            "back",
            "stay",
            "stay",
        ])

        self.assertTrue(battle.run_battle_turn(decisions))
        self.assertEqual(
            [request.phase for request in decisions.requests],
            ["攻击", "攻击目标选择", "攻击", "攻击"],
        )
        self.assertEqual(archer.pending_attacks, [])

    def test_round_advances_and_accepts_number_or_character_name(self):
        saber = create_servant("Saber", 10, 5, 4)
        archer = create_servant("Archer", 3, 3, 3)
        location = Location("Arena")
        saber.position = location
        archer.position = location
        archer.block = 100

        battle = BattleManager([archer, saber])
        battle.start_battle()

        self.assertEqual([character.name for character in battle.current_order], ["Saber", "Archer"])

        decisions = ScriptedDecisionProvider(
            [
                "1",       # Saber选择普通攻击
                "Archer",  # 直接用名字选择目标
                "格挡",    # Archer选择防御方式
                "结束",    # Archer结束自己的攻击阶段（受伤后菜单含修补）
            ]
        )

        self.assertTrue(battle.run_battle_turn(decisions))
        self.assertEqual(battle.current_phase, "round_ended")
        self.assertEqual(archer.pending_attacks, [])
        self.assertLess(archer.hp, archer.hpmax)
        self.assertEqual(
            [request.phase for request in decisions.requests],
            ["攻击", "攻击目标选择", "防御", "攻击"],
        )


if __name__ == "__main__":
    unittest.main()
