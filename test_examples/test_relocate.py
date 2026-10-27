import unittest
from unittest.mock import patch

from game.character.masters import Master
from game.character.servants import Servant
from game.game.command_spell import CommandSpellService
from game.game.game_manager import GameManager
from game.map.map import Location, Map
from game.resource.costs import SkillUnavailableError
from game.skill.effect_validation import validate_effect_definition
from game.skill.casting import start_or_continue_casting
from game.skill.relocation_runtime import relocation_destinations
from game.skill.skill_runtime import apply_skill_effect, skill_component_is_usable
from game.turn.battle import BattleManager
from game.turn.damage import AttackEvent, DamageEvent, DamageResolver
from game.turn.decision import ScriptedDecisionProvider


class RelocateTests(unittest.TestCase):
    def setUp(self):
        self.nodes = [Location(name) for name in "ABCDEFGH"]
        for first, second in zip(self.nodes, self.nodes[1:]):
            first.add_connection(second)
            second.add_connection(first)
        self.a, self.b, self.c, self.d, self.e, self.f, self.g, self.h = self.nodes
        self.island = Location("Island")
        self.actor = Master("Caster", 3, 3, 3, 3, 3, "C", 3)
        self.target = Servant("Rider", 3, 3, 3, 3, 3, "Rider", "A")
        self.actor.add_servant(self.target)
        self.actor.position = self.target.position = self.a
        self.game = GameManager([self.actor, self.target], self.a)
        self.game.game_map = Map()
        for node in [*self.nodes, self.island]:
            self.game.game_map.add_location(node)
        self.game.start_game()

    @staticmethod
    def effect(distance=None):
        return {"effect_type": "relocate", "effect_data": (
            {} if distance is None else {"distance": distance}
        )}

    def skill(self, *, target="self", distance=None):
        return self.actor.create_personal_skill({
            "skill_id": "test_relocate", "name": "转移", "rank": "C",
            "components": [{
                "component_id": "unit_0", "type": "active", "target": target,
                "available_phases": ["AP1", "AP2"],
                "cost": [{"resource": "mp", "value": 3}],
                "effects": [self.effect(distance)],
            }],
        })

    def test_distance_schema_rejects_non_positive_or_non_integer_values(self):
        self.assertTrue(validate_effect_definition(self.effect()))
        self.assertTrue(validate_effect_definition(self.effect(5)))
        for distance in (True, 0, -1, 1.5, "5", None):
            with self.subTest(distance=distance), self.assertRaises((ValueError, TypeError)):
                validate_effect_definition({
                    "effect_type": "relocate", "effect_data": {"distance": distance},
                })

    def test_free_selection_does_not_require_visited_or_connected_nodes(self):
        self.assertNotIn(self.island, self.actor.seen_locations)
        skill = self.skill()
        mp, seals = self.actor.mp, self.actor.command_spell
        provider = ScriptedDecisionProvider(["Island"])
        result = self.actor.resolve_skill_component(
            skill.skill_id, "unit_0", phase="AP1", decision_provider=provider,
        )
        self.assertIs(self.actor.position, self.island)
        self.assertEqual(self.actor.mp, mp - 3)
        self.assertEqual(self.actor.command_spell, seals)
        self.assertEqual(result["paid_costs"]["mp"], 3)
        self.assertNotIn(self.a, [option.value for option in provider.requests[0].options])

    def test_range_is_measured_from_recipient_and_includes_exact_boundary(self):
        self.actor.position = self.h
        skill = self.skill(target="selectable_character", distance=5)
        self.assertNotIn(self.f, self.target.seen_locations)
        provider = ScriptedDecisionProvider(["F"])
        result = self.actor.resolve_skill_component(
            skill.skill_id, "unit_0", target=self.target,
            decision_provider=provider, phase="AP1",
        )
        choices = {option.value for option in provider.requests[0].options}
        self.assertEqual(choices, {self.b, self.c, self.d, self.e, self.f})
        self.assertIs(self.target.position, self.f)
        self.assertIs(self.actor.position, self.h)
        self.assertEqual(result["targets"], [self.target])

    def test_no_destinations_is_unusable_before_paying(self):
        self.game.game_map.locations = {self.a.name: self.a}
        skill = self.skill(distance=1)
        mp = self.actor.mp
        self.assertFalse(skill_component_is_usable(
            skill.definitions[0], self.actor, self.actor, skill=skill,
        ))
        with self.assertRaises(SkillUnavailableError):
            self.actor.resolve_skill_component(skill.skill_id, "unit_0")
        self.assertEqual(self.actor.mp, mp)

    def test_destination_is_rechecked_after_decision(self):
        class ChangedMapProvider:
            def choose(provider, request):
                self.actor.position = self.h
                return self.b
        with self.assertRaises(SkillUnavailableError):
            apply_skill_effect(self.effect(1), self.actor, None,
                               actor=self.actor, decision_provider=ChangedMapProvider())
        self.assertIs(self.actor.position, self.h)

    def test_exiting_battle_uses_command_spell_ap_and_attack_rules(self):
        enemy = Master("Enemy", 3, 3, 3, 3, 3, "C", 3)
        enemy.position = self.a
        self.game.register_character(enemy)
        battle = BattleManager([self.actor, enemy])
        self.game.turn_manager.battles.append(battle)
        battle.start_battle()
        self.actor.attack_phase_count = 1
        ordinary = AttackEvent(enemy, self.actor, 10, "physical", 20, None)
        locked = AttackEvent(enemy, self.actor, 10, "physical", 20, None,
                             target_lock=True)
        self.actor.pending_attacks.extend([ordinary, locked])
        with patch.object(battle, "resolve_simple_round_attack_events") as resolve:
            apply_skill_effect(self.effect(5), self.actor, None, actor=self.actor,
                               decision_provider=ScriptedDecisionProvider(["F"]))
        self.assertIs(self.actor.position, self.f)
        self.assertFalse(self.actor.in_battle)
        self.assertEqual(self.actor.action_point, 2)
        self.assertTrue(ordinary.resolved)
        self.assertEqual(ordinary.resolution_reason, "target_teleported")
        self.assertFalse(locked.resolved)
        self.assertIn(locked, self.actor.pending_attacks)
        self.assertEqual(resolve.call_args.args[0], [locked])

    def test_casting_is_interrupted_through_shared_resolution(self):
        class CastingState:
            reason = None
            def interrupt(state, reason="manual"):
                state.reason = reason
                self.actor.casting_state = None
                return []
        state = CastingState()
        self.actor.casting_state = state
        apply_skill_effect(self.effect(5), self.actor, None, actor=self.actor,
                           decision_provider=ScriptedDecisionProvider(["F"]))
        self.assertIsNone(self.actor.casting_state)
        self.assertEqual(state.reason, "relocate")

    def casting_skill(self):
        return self.actor.create_personal_skill({
            "skill_id": "test_cast_relocate", "name": "咏唱转移", "rank": "C",
            "casting": {"activation_mode": "release"},
            "components": [{
                "component_id": "unit_0", "type": "active", "target": "self",
                "casting_requirement": 1,
                "cost": [{"resource": "mp", "value": 12, "timing": "casting_start"}],
                "effects": [self.effect(5)],
            }],
        })

    def test_successful_release_does_not_refund_its_own_casting_payment(self):
        skill = self.casting_skill()
        mp = self.actor.mp
        state = start_or_continue_casting(self.actor, skill, turn_number=1)
        state.advance_at_global_turn_end(1)
        self.actor.resolve_skill_component(
            skill.skill_id, "unit_0", casting_release=True,
            decision_provider=ScriptedDecisionProvider(["F"]),
        )
        state.finish_release()
        self.assertTrue(state.released)
        self.assertFalse(state.interrupted)
        self.assertEqual(self.actor.mp, mp - 12)
        self.assertEqual(state.refund_results, [])

    def test_external_transfer_still_refunds_interrupted_casting(self):
        skill = self.casting_skill()
        mp = self.actor.mp
        state = start_or_continue_casting(self.actor, skill, turn_number=1)
        apply_skill_effect(self.effect(5), self.actor, None, actor=self.actor,
                           decision_provider=ScriptedDecisionProvider(["F"]))
        self.assertTrue(state.interrupted)
        self.assertFalse(state.released)
        self.assertEqual(self.actor.mp, mp)

    def test_arrival_joins_battle_and_can_decline_emergency_guard(self):
        enemy = Master("Enemy", 3, 3, 3, 3, 3, "C", 3)
        enemy.position = self.f
        self.game.register_character(enemy)
        enemy.position = self.target.position = self.f
        self.actor.add_ally(self.target)
        self.target.add_ally(self.actor)
        battle = BattleManager([self.target, enemy])
        self.game.turn_manager.battles.append(battle)
        battle.start_battle()
        attack = AttackEvent(enemy, self.target, 10, "physical", 20, None)
        self.target.pending_attacks.append(attack)
        provider = ScriptedDecisionProvider(["F", "skip"])
        apply_skill_effect(self.effect(5), self.actor, None, actor=self.actor,
                           decision_provider=provider)
        self.assertIs(self.actor.current_battle, battle)
        self.assertIn(self.actor, battle.late_participants)
        self.assertIn(attack, self.target.pending_attacks)
        self.assertEqual(len(provider.requests), 2)

    def test_arrival_traps_trigger_without_path_movement_events(self):
        caster = Master("Enemy", 3, 3, 3, 3, 3, "C", 3)
        caster.position = self.f
        self.game.register_character(caster)
        caster.action_point = 2
        trap_skill = caster.load_basic_magic("trap")
        trap = caster.resolve_skill_component(
            trap_skill.skill_id, "set_trap", target=self.f,
            selected_choice_ids=["private"], phase="AP1",
        )["results"][0]["trap"]
        hp = self.actor.hp
        with patch.object(self.game.trap_manager, "_attack_roll", return_value=(5, 100)), \
                patch("game.turn.defense.random.randint", return_value=5):
            result = apply_skill_effect(
                self.effect(5), self.actor, None, actor=self.actor,
                decision_provider=ScriptedDecisionProvider(["F", "block"]),
            )
        self.assertFalse(trap.active)
        self.assertEqual(len(result["trap_results"]), 1)
        self.assertLess(self.actor.hp, hp)
        self.assertFalse(any(event.event_type in {"movement_step", "movement_completed"}
                             for event in self.game.event_manager.history))

    def test_arrival_can_select_and_resolve_emergency_guard(self):
        enemy = Master("Enemy", 3, 3, 3, 3, 3, "C", 3)
        enemy.position = self.target.position = self.f
        self.game.register_character(enemy)
        battle = BattleManager([self.target, enemy])
        self.game.turn_manager.battles.append(battle)
        battle.start_battle()
        attack = AttackEvent(enemy, self.target, 10, "physical", 100, None)
        self.target.pending_attacks.append(attack)
        hp = self.target.hp
        with patch("game.turn.defense.random.randint", return_value=5):
            apply_skill_effect(
                self.effect(5), self.actor, None, actor=self.actor,
                decision_provider=ScriptedDecisionProvider(["F", "Rider"]),
            )
        self.assertTrue(attack.resolved)
        self.assertFalse(self.actor.guard_opportunity_available)
        self.assertEqual(self.target.hp, hp)

    def escape_skill(self):
        return self.target.create_personal_skill({
            "skill_id": "test_escape", "name": "濒死转移", "rank": "A",
            "components": [{
                "component_id": "unit_0", "type": "trigger", "target": "self",
                "trigger": {"event_type": "brink_entered"},
                "cost": [{"resource": "mp", "value": 5}],
                "effects": [self.effect(5)],
            }],
        })

    def test_automatic_brink_trigger_can_relocate_an_incapacitated_character(self):
        self.escape_skill()
        self.game.decision_provider = ScriptedDecisionProvider(["F"])
        mp = self.target.mp
        self.target.take_damage(self.target.hp)
        self.assertTrue(self.target.has_status("brink_of_death"))
        self.assertEqual(self.target.hp, 1)
        self.assertIs(self.target.position, self.f)
        self.assertEqual(self.target.mp, mp - 5)

    def test_lethal_damage_in_battle_triggers_escape_and_finishes_damage_resolution(self):
        self.escape_skill()
        enemy = Master("Enemy", 3, 3, 3, 3, 3, "C", 3)
        enemy.position = self.a
        self.game.register_character(enemy)
        battle = BattleManager([self.target, enemy])
        self.game.turn_manager.battles.append(battle)
        battle.start_battle()
        self.target.attack_phase_count = 0
        damage = DamageEvent(enemy, self.target, self.target.hp, "true_damage")
        value = DamageResolver().resolve(
            damage, decision_provider=ScriptedDecisionProvider(["F"]),
        )
        self.assertEqual(value, damage.final_value)
        self.assertTrue(self.target.has_status("brink_of_death"))
        self.assertEqual(self.target.hp, 1)
        self.assertIs(self.target.position, self.f)
        self.assertFalse(self.target.in_battle)
        self.assertEqual(self.target.action_point, 0)

    def test_command_spell_destinations_keep_their_existing_seen_location_rule(self):
        service = CommandSpellService(self.game)
        self.assertIn(self.f, relocation_destinations(self.target, {"distance": 5}))
        self.assertNotIn(self.f, service.teleport_destinations(self.actor, self.target))


if __name__ == "__main__":
    unittest.main()
