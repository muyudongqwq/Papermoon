"""Cross-feature combat checks with the two recorded card templates."""

import unittest
from unittest.mock import patch

from game.action.action import Action
from game.character import create_character_from_card
from game.game.command_spell import CommandSpellService
from game.game.game_manager import GameManager
from game.map.map import Location
from game.modifier.modifier import create_modifier
from game.skill.casting import CastingState
from game.skill.component_runtime import component_use_count, record_component_use
from game.skill.skill_runtime import SkillUnavailableError
from game.turn.battle import BattleManager
from game.turn.damage import AttackEvent, DamageEvent, DamageResolver
from game.turn.decision import ScriptedDecisionProvider
from game.turn.defense import DefenseResolver, get_offset_attack_options, resolve_offset_attack_option


class RecordedCardBranchTests(unittest.TestCase):
    def setUp(self):
        self.arena = Location("Arena", is_building=True)
        self.outside = Location("Outside", is_building=True)
        self.arena.add_connection(self.outside)
        self.outside.add_connection(self.arena)
        self.master = create_character_from_card("master_test_0", name="Master", position=self.arena)
        self.nero = create_character_from_card("servant_test_0", name="Nero", position=self.arena, master=self.master)
        self.enemy_master = create_character_from_card("master_test_0", name="EnemyMaster", position=self.arena)
        self.enemy = create_character_from_card("servant_test_0", name="Enemy", position=self.arena, master=self.enemy_master)
        self.game = GameManager([self.master, self.nero, self.enemy_master, self.enemy], self.arena)
        self.game.start_game()
        self.battle = BattleManager(list(self.game.characters))
        self.game.turn_manager.battles.append(self.battle)
        self.battle.start_battle()
        self.turn(1)

    def turn(self, number):
        self.game.turn_manager.turn = self.battle.global_turn = number
        for actor in self.game.all_characters:
            actor.current_global_turn = number

    def noble(self, actor, suffix):
        return next(skill for skill in actor.noble_phantasms if skill.skill_id.endswith(":" + suffix))

    def privilege(self, name, *, turn=1):
        self.turn(turn)
        self.game.event_manager.emit("global_turn_start", decision_provider=ScriptedDecisionProvider(
            [name, name, "territory_creation", "territory_creation"]))

    def theatre(self):
        state = CastingState.start(self.nero, self.noble(self.nero, "golden_theatre"), self.nero.current_global_turn)
        state.advance_at_global_turn_end(self.nero.current_global_turn)
        return self.game.field_manager.fields[-1]

    def incoming(self, target, *, damage=20, channel="attack", locked=False):
        attack = AttackEvent(self.enemy, target, damage, "physical", 0, None,
                             resolution_channel=channel, target_lock=locked)
        target.pending_attacks.append(attack)
        return attack

    def assert_world(self):
        self.assertFalse(set(self.game.characters) & set(self.game.dead_characters))
        for actor in self.game.all_characters:
            self.assertGreaterEqual(actor.mp, 0)
            self.assertLessEqual(actor.mp, actor.mpmax)
            self.assertGreaterEqual(actor.hp, 0)
            self.assertLessEqual(actor.hp, actor.hpmax)
            if actor.is_alive():
                self.assertIsNotNone(actor.position)
                self.assertIn(actor, actor.position.occupants)
            else:
                self.assertIsNone(actor.position)
                self.assertNotIn(actor, self.arena.occupants)
                self.assertNotIn(actor, self.outside.occupants)
                self.assertNotIn(actor, self.battle.participants)
            master = getattr(actor, "master", None)
            if master is not None:
                self.assertTrue(master.is_alive())
                self.assertIn(actor, master.servants)

    def test_actual_noble_used_as_offset_enters_same_cooldown_as_release(self):
        skill = self.noble(self.nero, "laus_saint_claudius")
        state = CastingState.start(self.nero, skill, 1)
        state.advance_at_global_turn_end(1)
        incoming = self.incoming(self.nero, channel="release")
        option = next(option for option in get_offset_attack_options(self.nero, incoming) if option.skill is skill)
        mp = self.nero.mp
        resolved = resolve_offset_attack_option(self.nero, option, turn_number=1)
        self.assertEqual(resolved["profiles"][0].value, 150)
        self.assertEqual(self.nero.mp, mp)
        self.assertIsNone(self.nero.casting_state)
        self.assertEqual(skill.component_runtime_states["release"].cooldown_ready_turn, 4)
        self.assertNotIn(skill, [option.skill for option in get_offset_attack_options(self.nero, incoming)])

    def test_offset_rejects_stale_option_before_cost_or_old_chant_refund(self):
        skill = self.noble(self.nero, "laus_saint_claudius")
        state = CastingState.start(self.nero, skill, 1)
        state.advance_at_global_turn_end(1)
        incoming = self.incoming(self.nero, channel="release")
        option = next(option for option in get_offset_attack_options(self.nero, incoming) if option.skill is skill)
        record_component_use(self.nero, skill, skill.definitions[0], turn_number=1)
        before = (self.nero.mp, self.master.mp, self.nero.casting_state)
        with self.assertRaises(SkillUnavailableError):
            resolve_offset_attack_option(self.nero, option, turn_number=1)
        self.assertEqual(before, (self.nero.mp, self.master.mp, self.nero.casting_state))

    def test_guard_actual_master_then_continue_residual_into_master_reaction(self):
        attack = self.incoming(self.master, damage=400)
        master_hp = self.master.hp
        with patch("game.turn.defense.random.randint", return_value=5):
            record = self.battle.resolve_guard(self.nero, self.master, ScriptedDecisionProvider([]))
        self.assertTrue(self.nero.has_status("brink_of_death"))
        self.assertEqual(self.master.hp, master_hp)
        self.assertGreater(record["results"][0]["residual_damage"], 0)
        self.assertIs(self.master.pending_attacks[0], attack)
        provider = ScriptedDecisionProvider(["无瑕之人", 5])
        with patch("game.turn.defense.random.randint", return_value=5):
            DefenseResolver().resolve_phase(self.master, "block", attacks=[attack], decision_provider=provider)
        self.assertEqual(self.master.hp, 1)
        self.assertTrue(self.master.has_status("brink_of_death"))
        self.assert_world()

    def test_ready_offset_option_is_invalid_after_chant_interruption(self):
        skill = self.noble(self.nero, "laus_saint_claudius")
        state = CastingState.start(self.nero, skill, 1)
        state.advance_at_global_turn_end(1)
        option = next(item for item in get_offset_attack_options(self.nero, self.incoming(self.nero, channel="release"))
                      if item.skill is skill)
        state.interrupt(reason="test")
        mp = self.nero.mp
        with self.assertRaises(SkillUnavailableError):
            resolve_offset_attack_option(self.nero, option)
        self.assertEqual(self.nero.mp, mp)

    def test_offset_cannot_spend_refund_returning_to_dead_master(self):
        self.nero.mp, self.master.mp = 10, 90
        state = CastingState.start(self.nero, self.noble(self.nero, "laus_saint_claudius"), 1)
        alternative = self.nero.create_personal_skill({
            "skill_id": "audit_instant", "name": "Instant", "rank": "C",  "casting": {"activation_mode": "release"},
            "components": [{"cost": [{"resource": "mp", "value": 100, "timing": "casting_start"}], "component_id": "release", "type": "active", "target": "selectable_enemy",
                            "effects": [{"effect_type": "create_attack_event", "effect_data": {"damage_value": 30}}]}],
        })
        attack = self.incoming(self.nero, channel="release")
        option = next(item for item in get_offset_attack_options(self.nero, attack) if item.skill is alternative)
        self.master.die()
        self.assertNotIn(alternative, [item.skill for item in get_offset_attack_options(self.nero, attack)])
        with self.assertRaises(SkillUnavailableError):
            resolve_offset_attack_option(self.nero, option)
        self.assertIs(self.nero.casting_state, state)
        self.assertEqual((self.nero.mp, self.master.mp), (0, 0))

    def test_offset_refund_affordability_respects_payer_mp_cap(self):
        self.nero.mp, self.master.mp = 10, 90
        state = CastingState.start(self.nero, self.noble(self.nero, "laus_saint_claudius"), 1)
        # Recovery while chanting fills both ordinary pools, so interrupting
        # the old chant cannot add its full nominal ledger again.
        self.nero.mp, self.master.mp = self.nero.mpmax, self.master.mpmax
        alternative = self.nero.create_personal_skill({
            "skill_id": "audit_expensive", "name": "Expensive", "rank": "C",
             "casting": {"activation_mode": "release"},
            "components": [{"cost": [{"resource": "mp", "value": self.nero.get_available_mp() + 1, "timing": "casting_start"}], "component_id": "release", "type": "active", "target": "selectable_enemy",
                            "effects": [{"effect_type": "create_attack_event", "effect_data": {"damage_value": 30}}]}],
        })
        self.assertNotIn(alternative, [item.skill for item in get_offset_attack_options(self.nero, self.incoming(self.nero, channel="release"))])
        self.assertIs(self.nero.casting_state, state)

    def test_command_spell_bonus_is_consumed_once_by_actual_noble_offset(self):
        skill = self.noble(self.nero, "laus_saint_claudius")
        state = CastingState.start(self.nero, skill, 1)
        state.advance_at_global_turn_end(1)
        self.assertTrue(CommandSpellService(self.game).grant_damage_bonus(self.master, self.nero))
        option = next(item for item in get_offset_attack_options(self.nero, self.incoming(self.nero, channel="release"))
                      if item.skill is skill)
        phases = self.nero.attack_phase_count
        result = resolve_offset_attack_option(self.nero, option)
        self.assertEqual(sum(profile.offset_power for profile in result["profiles"]), 240)
        self.assertEqual(self.nero.command_spell_damage_bonus, 0)
        self.assertEqual(self.nero.attack_phase_count, phases)
        self.assert_world()

    def test_offset_limits_conditions_and_shared_cooldown(self):
        skill = self.nero.create_personal_skill({
            "skill_id": "audit_offset", "name": "Audit offset", "rank": "C",
            "components": [{
                "component_id": name, "type": "active", "available_phases": ["attack_phase"],
                "condition": {"required_status": ["stay"]}, "target": "selectable_enemy",
                "usage_limit": {"scope": "battle", "maximum": 1},
                "cooldown": {"unit": "global_turn", "turns": 1, "group": "shared"},
                "cost": [{"resource": "mp", "value": 5}],
                "effects": [{"effect_type": "create_attack_event", "effect_data": {"damage_value": 20}}],
            } for name in ("one", "two")],
        })
        attack = self.incoming(self.nero)
        options = lambda: [item for item in get_offset_attack_options(self.nero, attack) if item.skill is skill]
        self.assertEqual(options(), [])
        self.nero.add_modifier(create_modifier({"effect_type": "add_status", "effect_data": {"status_id": "stay"}}, self.nero))
        first, second = options()
        resolve_offset_attack_option(self.nero, first)
        mp = self.nero.mp
        self.assertEqual(options(), [])
        with self.assertRaises(SkillUnavailableError):
            resolve_offset_attack_option(self.nero, second)
        self.assertEqual(self.nero.mp, mp)
        self.turn(3)
        self.assertEqual([item.component["component_id"] for item in options()], ["two"])
        # Losing the condition after selection must not charge MP.
        modifier = next(item for item in self.nero.modifiers if getattr(item, "status", None) == "stay")
        self.nero.remove_modifier(modifier)
        with self.assertRaises(SkillUnavailableError):
            resolve_offset_attack_option(self.nero, second)
        self.assertEqual(self.nero.mp, mp)

    def test_actual_zabaniya_exit_and_expiry_under_theatre_charges_once(self):
        self.theatre()
        self.game.decision_provider = ScriptedDecisionProvider(["deny", "pass"])
        skill = self.enemy_master.load_content("personal_skill", "master_test_0:zabaniya")
        state = CastingState.start(self.enemy_master, skill, 1)
        result = state.advance_at_global_turn_end(1)
        self.assertTrue(result["auto_activated"])
        self.assertTrue(self.enemy_master.has_status("hidden"))
        self.assertFalse(self.enemy_master.in_battle)
        self.assertEqual(self.enemy_master.hp, 1)
        hidden = next(item for item in self.enemy_master.modifiers if getattr(item, "status", None) == "hidden")
        # Exercise expiration through the normal modifier clock, including the
        # battle-entry cleanup that formerly removed the same effect twice.
        for number in range(2, 5):
            self.enemy_master.update_modifiers("global_turn_end", turn_number=number)
        self.assertNotIn(hidden, self.enemy_master.modifiers)
        self.assertTrue(self.enemy_master.in_battle)
        penalties = [record for record in self.game.rule_reports.history if record["kind"] == "damage_resolved"
                     and record["data"]["actor"].get("action_id") == "battle_exit_penalty"]
        self.assertEqual(len(penalties), 1)
        self.assert_world()

    def test_fatal_denied_teleport_interrupts_chant_and_cleans_all_attacks(self):
        self.theatre()
        self.enemy.seen_locations.add(self.outside)
        self.enemy.brink_of_death_counter = 0
        self.enemy.hp = 1
        self.enemy.mp = 10
        master_mp = self.enemy_master.mp
        CastingState.start(self.enemy, self.noble(self.enemy, "laus_saint_claudius"), 1)
        self.incoming(self.enemy)
        self.incoming(self.enemy, locked=True)
        spells = self.enemy_master.command_spell
        CommandSpellService(self.game).teleport(self.enemy_master, self.enemy, self.outside,
                                               decision_provider=ScriptedDecisionProvider(["deny", "pass"]))
        self.assertFalse(self.enemy.is_alive())
        self.assertEqual(self.enemy_master.command_spell, spells - 2)
        self.assertIsNone(self.enemy.casting_state)
        self.assertEqual(self.enemy_master.mp, master_mp)
        self.assertFalse(self.enemy.pending_attacks)
        self.assert_world()

    def test_escape_under_theatre_denial_charges_once_and_grants_map_action(self):
        self.theatre()
        self.game.decision_provider = ScriptedDecisionProvider(["deny"])
        self.enemy.add_modifier(create_modifier({"effect_type": "add_status", "effect_data": {"status_id": "stay"}}, self.enemy))
        hp = self.enemy.hp
        action = Action(self.enemy, "escape")
        action.game_turn = 2
        self.assertTrue(action.escape())
        self.assertEqual(self.enemy.hp, 1)
        self.assertTrue(self.enemy.has_status("brink_of_death"))
        self.assertEqual(self.enemy.action_point, 2)
        self.assertFalse(self.enemy.in_battle)
        self.assertIs(self.enemy.position, self.arena)
        penalties = [record for record in self.game.rule_reports.history if record["kind"] == "damage_resolved"
                     and record["data"]["actor"].get("action_id") == "battle_exit_penalty"]
        self.assertEqual(len(penalties), 1)
        self.assertEqual(hp, 60)
        self.assert_world()

    def test_two_command_spells_teleport_out_with_permission_preserves_locked_attack(self):
        self.theatre()
        self.enemy.seen_locations.add(self.outside)
        ordinary = self.incoming(self.enemy)
        locked = self.incoming(self.enemy, locked=True)
        # Attacks originate from the other team for this spatial-transfer fixture.
        ordinary.source = locked.source = self.nero
        hp, count = self.enemy.hp, self.enemy_master.command_spell
        result = CommandSpellService(self.game).teleport(self.enemy_master, self.enemy, self.outside,
                                                        decision_provider=ScriptedDecisionProvider(["allow", "block"]))
        self.assertTrue(result)
        self.assertEqual(self.enemy_master.command_spell, count - 2)
        self.assertIs(self.enemy.position, self.outside)
        self.assertEqual(ordinary.resolution_reason, "target_teleported")
        self.assertTrue(locked.resolved)
        self.assertLess(self.enemy.hp, hp)
        self.assert_world()

    def test_master_death_interrupt_refund_keeps_payers_and_no_servant_resurrection(self):
        self.nero.mp = 10
        mp = self.master.mp
        state = CastingState.start(self.nero, self.noble(self.nero, "laus_saint_claudius"), 1)
        self.assertEqual(self.master.mp, mp - 90)
        self.master.die()
        self.assertIsNone(self.nero.master)
        state.interrupt(reason="test")
        self.assertFalse(self.master.is_alive())
        self.assertIsNone(self.master.position)
        self.assertEqual(self.nero.mp, 10)
        self.assertEqual(self.master.mp, mp)
        self.assert_world()

    def test_independent_action_switch_after_master_loss_waives_upkeep_then_removes_it(self):
        self.master.die()
        self.privilege("independent_action", turn=2)
        mp = self.nero.mp
        self.nero.end_global_turn(2)
        self.assertEqual(self.nero.mp, mp)
        self.privilege("battle_continuation", turn=3)
        self.nero.end_global_turn(3)
        self.assertEqual(self.nero.mp, max(0, mp - 90))
        self.assert_world()

    def test_hidden_withdrawal_and_return_do_not_refresh_battle_survival_uses(self):
        self.privilege("battle_continuation")
        continuation = next(skill for skill in self.nero.personal_skills if skill.name == "战斗续行")
        self.nero.brink_of_death_counter = 0
        DamageResolver().resolve(DamageEvent(self.enemy, self.nero, 100, "true_damage"))
        self.assertEqual(component_use_count(self.nero, continuation, continuation.definitions[0]), 1)
        hidden = create_modifier({"effect_type": "hidden", "duration": 1,
                                  "effect_data": {"value": "hidden", "withdraw_from_battle": True,
                                                  "requires_building": False}}, self.nero)
        self.nero.add_modifier(hidden)
        self.assertFalse(self.nero.in_battle)
        self.nero.remove_modifier(hidden)
        self.assertTrue(self.nero.in_battle)
        self.assertIs(self.nero.current_battle, self.battle)
        self.assertEqual(component_use_count(self.nero, continuation, continuation.definitions[0]), 1)
        self.assert_world()
