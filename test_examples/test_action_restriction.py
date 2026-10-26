import unittest
from unittest.mock import patch

from game.action.action import Action
from game.action.action_list import ActionContext, ActionListBuilder
from game.action.action_resolver import ActionResolver
from game.character.servants import Servant
from game.map.map import Location
from game.modifier.modifier import create_modifier
from game.skill.effect_validation import validate_effect_definition
from game.turn.battle import BattleManager
from game.turn.damage import AttackEvent
from game.turn.defense import DefenseResolver
from game.turn.decision import ScriptedDecisionProvider


def servant(name):
    return Servant(name, 3, 3, 3, 3, 3, "Saber", "A")


def restriction(data, *, duration=2):
    return {
        "modifier_id": "test_action_restriction",
        "effect_type": "action_restriction",
        "polarity": "debuff",
        "duration": duration,
        "effect_data": data,
    }


class ActionRestrictionTests(unittest.TestCase):
    def apply(self, character, data):
        modifier = create_modifier(restriction(data), character)
        character.add_modifier(modifier)
        return modifier

    def test_validation_requires_a_positive_selector(self):
        with self.assertRaisesRegex(ValueError, "至少需要"):
            validate_effect_definition(restriction({"phases": ["AP1"]}))

        self.assertTrue(validate_effect_definition(restriction({
            "action_types": ["defense"],
            "phase_scopes": ["formal_battle", "simple_round"],
        })))

    def test_action_list_marks_restricted_entry_but_keeps_pass(self):
        actor = servant("Actor")
        actor.position = Location("A")
        self.apply(actor, {
            "all_actions": True,
            "phases": ["AP1"],
            "reason": "本阶段不能行动",
        })

        entries = ActionListBuilder().get_action_entries(
            ActionContext(actor, "AP1", characters=[actor])
        )
        by_id = {entry.action_id: entry for entry in entries}

        self.assertTrue(by_id["pass"].available)
        self.assertFalse(by_id["investigate"].available)
        self.assertIn("本阶段不能行动", by_id["investigate"].unavailable_reasons)

    def test_stay_is_always_a_safe_battle_exit(self):
        actor = servant("Actor")
        enemy = servant("Enemy")
        location = Location("Arena")
        actor.position = enemy.position = location
        battle = BattleManager([actor, enemy])
        battle.start_battle()
        self.apply(actor, {
            "all_actions": True,
            "phase_scopes": ["formal_battle"],
        })

        entries = ActionListBuilder().get_available_actions(
            ActionContext(actor, "attack_phase", battle=battle)
        )

        self.assertEqual([entry.action_id for entry in entries], ["stay"])

    def test_execution_recheck_ignores_previously_submitted_action(self):
        actor = servant("Actor")
        start = Location("A")
        destination = Location("B")
        start.add_connection(destination)
        destination.add_connection(start)
        actor.position = start
        action = Action(actor, "move", target=destination)
        action.ap_layer = 1
        starting_ap = actor.action_point
        self.apply(actor, {"action_ids": ["move"]})

        self.assertFalse(ActionResolver().resolve(action))
        self.assertIs(actor.position, start)
        self.assertEqual(actor.action_point, starting_ap)
        self.assertTrue(action.ignored)
        self.assertIn("action_restricted", action.ignored_reason)

    def test_all_defenses_restricted_resolves_damage_without_prompt(self):
        attacker = servant("Attacker")
        defender = servant("Defender")
        location = Location("Arena")
        attacker.position = defender.position = location
        battle = BattleManager([attacker, defender])
        battle.start_battle()
        battle.current_phase = "defense"
        self.apply(defender, {
            "action_ids": ["dodge", "block", "offset"],
            "phases": ["defense_phase"],
        })
        attack = AttackEvent(
            source=attacker,
            target=defender,
            value=20,
            damage_type="physical",
            attack_roll=100,
            skill=None,
        )
        defender.pending_attacks.append(attack)
        starting_hp = defender.hp
        provider = ScriptedDecisionProvider([])

        defense_type = battle.request_defense(defender, provider)
        result = DefenseResolver().resolve_phase(
            defender,
            defense_type,
            attacks=[attack],
            decision_provider=provider,
        )

        self.assertEqual(defense_type, "unopposed")
        self.assertEqual(provider.requests, [])
        self.assertEqual(result["total_damage"], 20)
        self.assertEqual(defender.hp, starting_hp - 20)
        self.assertEqual(defender.pending_attacks, [])

    def test_random_defense_uses_only_remaining_legal_choice(self):
        attacker = servant("Attacker")
        defender = servant("Defender")
        location = Location("Arena")
        attacker.position = defender.position = location
        battle = BattleManager([attacker, defender])
        battle.start_battle()
        battle.current_phase = "defense"
        defender.status_flags.add("random_defense")
        self.apply(defender, {
            "action_ids": ["dodge"],
            "phases": ["defense_phase"],
        })
        attack = AttackEvent(attacker, defender, 20, "physical", 100, None)
        defender.pending_attacks.append(attack)
        provider = ScriptedDecisionProvider(["block"])

        with patch("game.turn.battle.random.choice") as choose:
            choose.side_effect = lambda choices: choices[0]
            selected = battle.request_defense(defender, provider)

        self.assertEqual(selected, "block")
        choose.assert_called_once_with(("block",))

    def test_simple_round_guard_candidates_respect_guard_restriction(self):
        attacker = servant("Attacker")
        defender = servant("Defender")
        guarder = servant("Guarder")
        location = Location("Arena")
        for character in (attacker, defender, guarder):
            character.position = location
        defender.add_ally(guarder, source="test")
        guarder.add_ally(defender, source="test")
        battle = BattleManager([attacker, defender, guarder])
        battle.start_battle()
        self.apply(guarder, {
            "action_ids": ["guard"],
            "phases": ["simple_round_guard"],
        })
        state = {
            "actor": attacker,
            "defenders": {defender},
            "completed_defenders": set(),
            "used_guarders": set(),
        }

        self.assertNotIn(
            guarder,
            battle.get_simple_round_guard_candidates(state, defender),
        )


if __name__ == "__main__":
    unittest.main()
