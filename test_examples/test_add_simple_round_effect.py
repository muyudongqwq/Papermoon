import unittest

from game.character.servants import Servant
from game.map.map import Location
from game.skill.effect_validation import validate_effect_definition
from game.turn.battle import BattleManager
from game.turn.decision import ScriptedDecisionProvider


def servant(name, flexibility=3):
    return Servant(name, 3, 5, flexibility, 3, 3, "Saber", "A")


def add_simple_round_skill(actor, effect_data):
    return actor.create_personal_skill({
        "skill_id": "simple_round_skill",
        "name": "简易轮测试技能",
        "rank": "C",
        "components": [{
            "component_id": "active",
            "type": "active",
            "target": "selectable_character",
            "effects": [{
                "effect_type": "add_simple_round",
                "effect_data": effect_data,
            }],
        }],
    })


class AddSimpleRoundValidationTests(unittest.TestCase):
    def test_canonical_fixed_definition_is_valid(self):
        self.assertTrue(validate_effect_definition({
            "effect_type": "add_simple_round",
            "effect_data": {
                "trigger_phase": "immediate",
                "attack_mode": "fixed",
                "damage_type": "magic",
                "damage_value": 30,
                "defender_rule": "all_targets",
            },
        }))

    def test_select_mode_rejects_ignored_fixed_attack_fields(self):
        with self.assertRaisesRegex(ValueError, "固定攻击字段"):
            validate_effect_definition({
                "effect_type": "add_simple_round",
                "effect_data": {
                    "attack_mode": "select",
                    "damage_value": 30,
                },
            })


class AddSimpleRoundRuntimeTests(unittest.TestCase):
    def test_multiple_effect_targets_share_one_simple_round(self):
        location = Location("Arena")
        actor = servant("Actor", flexibility=10)
        first = servant("First", flexibility=5)
        second = servant("Second", flexibility=4)
        for character in (actor, first, second):
            character.position = location
            character.dodge = 100
        add_simple_round_skill(actor, {
            "trigger_phase": "immediate",
            "damage_value": 20,
            "defender_rule": "all_targets",
        })

        resolved = actor.resolve_skill_component(
            "simple_round_skill",
            "active",
            targets=[first, second],
            decision_provider=ScriptedDecisionProvider(["dodge", "dodge"]),
        )

        self.assertEqual(len(resolved["results"]), 2)
        simple_round_result = resolved["results"][0]
        self.assertEqual(
            simple_round_result["defense_order"],
            [first, second],
        )
        self.assertTrue(resolved["results"][1]["skipped"])
        self.assertEqual(first.pending_attacks, [])
        self.assertEqual(second.pending_attacks, [])

    def test_delayed_effect_is_attached_to_existing_formal_battle(self):
        location = Location("Arena")
        actor = servant("Actor")
        target = servant("Target")
        actor.position = target.position = location
        battle = BattleManager([actor, target])
        battle.start_battle()
        add_simple_round_skill(actor, {
            "trigger_phase": "defense",
            "trigger_target": "target",
            "damage_value": 20,
        })

        resolved = actor.resolve_skill_component(
            "simple_round_skill",
            "active",
            target=target,
        )
        effect = resolved["results"][0]

        self.assertIs(effect.actor, actor)
        self.assertEqual(effect.targets, [target])
        self.assertEqual(battle.get_simple_rounds(target, "defense"), [effect])

    def test_consuming_simple_round_uses_one_real_attack_phase(self):
        location = Location("Arena")
        actor = servant("Actor")
        target = servant("Target")
        actor.position = target.position = location
        target.dodge = 100
        battle = BattleManager([actor, target])
        battle.start_battle()
        add_simple_round_skill(actor, {
            "trigger_phase": "immediate",
            "damage_value": 20,
            "consume_attack_phase": True,
        })
        self.assertEqual(actor.attack_phase_count, 1)

        actor.resolve_skill_component(
            "simple_round_skill",
            "active",
            target=target,
            decision_provider=ScriptedDecisionProvider(["dodge"]),
        )

        self.assertEqual(actor.attack_phase_count, 0)

    def test_enter_battle_creates_a_formal_battle_at_same_node(self):
        location = Location("Arena")
        actor = servant("Actor")
        target = servant("Target")
        actor.position = target.position = location
        target.dodge = 100
        add_simple_round_skill(actor, {
            "trigger_phase": "immediate",
            "damage_value": 20,
            "enter_battle": True,
        })

        actor.resolve_skill_component(
            "simple_round_skill",
            "active",
            target=target,
            decision_provider=ScriptedDecisionProvider(["dodge"]),
        )

        self.assertTrue(actor.in_battle)
        self.assertIs(actor.current_battle, target.current_battle)
        self.assertIn(target, actor.current_battle.participants)
        self.assertTrue(actor.current_battle.started)


if __name__ == "__main__":
    unittest.main()
