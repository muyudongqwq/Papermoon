import time
import unittest
from unittest.mock import patch

from game.action.action import Action
from game.action.action_list import ActionContext, ActionListBuilder
from game.character import create_character_from_card
from game.character.masters import Master
from game.game.game_manager import GameManager
from game.game.game_session import GameSession
from game.map.map import Location
from game.modifier.modifier import create_modifier
from game.skill.casting import CastingState, castable_sources, get_casting_mp_cost, release_options
from game.skill.component_runtime import component_use_count
from game.skill.skill_runtime import SkillUnavailableError
from game.skill.effect_validation import validate_effect_definition
from game.turn.battle import BattleManager
from game.turn.damage import AttackEvent, DamageEvent, DamageResolver
from game.turn.decision import ScriptedDecisionProvider
from game.turn.defense import DefenseResolver
from game.turn.roll import RollResolver


class ServantTest0CardTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b = Location("Arena"), Location("Outside")
        self.a.add_connection(self.b)
        self.b.add_connection(self.a)
        self.actor = create_character_from_card("servant_test_0", name="Nero", position=self.a)
        self.first = Master("First", 3, 10, 3, 3, 3, "C", 3)
        self.second = Master("Second", 3, 3, 2, 3, 3, "C", 3)
        self.third = Master("Third", 3, 3, 1, 3, 3, "C", 3)
        for target in (self.first, self.second, self.third):
            target.position = self.a
        self.game = GameManager([self.actor, self.first, self.second, self.third], self.a,
                                grail_appearance_deaths=1, grail_ready_deaths=1)
        self.game.start_game()
        self.battle = BattleManager(list(self.game.characters))
        self.game.turn_manager.battles.append(self.battle)
        self.battle.start_battle()
        self.set_turn(1)

    def set_turn(self, number):
        self.game.turn_manager.turn = number
        for actor in self.game.all_characters:
            actor.current_global_turn = number

    def choose_privilege(self, choice, turn=1):
        self.set_turn(turn)
        self.game.event_manager.emit("global_turn_start", decision_provider=ScriptedDecisionProvider([choice]))
        return self.actor.switchable_skill_sets["servant_test_0:imperial_privilege"]["sets"][choice][0]

    def noble(self, name):
        return next(skill for skill in self.actor.noble_phantasms if skill.skill_id.endswith(":" + name))

    def open_theatre(self):
        skill = self.noble("golden_theatre")
        state = CastingState.start(self.actor, skill, self.actor.current_global_turn)
        self.assertIsNotNone(state)
        result = state.advance_at_global_turn_end(self.actor.current_global_turn)
        self.assertTrue(result["auto_activated"])
        return self.game.field_manager.fields[-1]

    def damage(self, amount, provider=None):
        return DamageResolver().resolve(DamageEvent(self.first, self.actor, amount, "true_damage"),
                                        decision_provider=provider)

    def test_factory_loads_three_nobles_and_no_effectless_magic_resistance(self):
        self.assertEqual(self.actor.servant_class, "Archer")
        self.assertEqual([getattr(self.actor, name).value for name in self.actor.ATTRIBUTE_NAMES], [2, 2, 5, 4, 2])
        self.assertEqual((self.actor.noble.rank, self.actor.noble.plus), ("A", 1))
        self.assertEqual(len(self.actor.noble_phantasms), 3)
        self.assertEqual(self.actor.class_skills, [])
        self.assertEqual(self.actor.magic_resistance, 0)

    def test_sword_bonus_is_free_and_uses_survive_switching_same_battle(self):
        sword = self.choose_privilege("swordsmanship")
        base, attacks, mp = self.actor.physical_attack, self.actor.attack_phase_count, self.actor.mp
        magic, defense = self.actor.magic_attack, {name: getattr(self.actor, name) for name in ("dodge", "block", "offset")}
        self.assertEqual([len(option["effects"]) for option in sword.definitions[0]["choices"]["options"]], [1, 1])
        self.actor.resolve_skill_component(sword.skill_id, "swordsmanship", target=self.actor,
                                          selected_choice_ids=["attack"], turn_number=1)
        self.assertEqual(self.actor.physical_attack, base + 9)
        self.assertEqual(self.actor.magic_attack, magic + 9)
        self.assertEqual({name: getattr(self.actor, name) for name in defense}, defense)
        self.assertEqual(self.actor.attack_phase_count, attacks)
        self.assertEqual(self.actor.mp, mp)
        self.choose_privilege("presence_concealment", 2)
        self.assertEqual(self.actor.physical_attack, base)
        self.assertEqual(self.actor.magic_attack, magic)
        restored = self.choose_privilege("swordsmanship", 3)
        self.assertIs(restored, sword)
        self.assertEqual(component_use_count(self.actor, sword, sword.definitions[0]), 1)
        for turn in (3, 4):
            self.set_turn(turn)
            self.actor.resolve_skill_component(sword.skill_id, "swordsmanship", target=self.actor,
                                              selected_choice_ids=["defense"], turn_number=turn)
            self.assertEqual({name: getattr(self.actor, name) for name in defense}, {name: value + 9 for name, value in defense.items()})
            self.assertEqual(self.actor.physical_attack, base)
            self.assertEqual(self.actor.magic_attack, magic)
            self.actor.update_modifiers("global_turn_end", turn_number=turn)
            self.assertEqual({name: getattr(self.actor, name) for name in defense}, defense)
        with self.assertRaises(SkillUnavailableError):
            self.actor.resolve_skill_component(sword.skill_id, "swordsmanship", target=self.actor,
                                              selected_choice_ids=["attack"], turn_number=5)

    def test_borrowed_class_skills_use_current_rank_rules(self):
        hide = self.actor.hide
        self.choose_privilege("presence_concealment")
        self.assertEqual(self.actor.hide, hide + 6)
        modifier = next(item for item in self.actor.modifiers if item.effect_type == "presence_concealment")
        self.assertTrue(modifier.investigation_immunity)
        self.assertTrue(modifier.active_hide_perception_immunity)
        self.choose_privilege("independent_action", 2)
        self.assertEqual(self.actor.hide, hide)
        mp = self.actor.mp
        self.actor.end_global_turn(2)
        self.assertEqual(self.actor.mp, mp)
        self.choose_privilege("swordsmanship", 3)
        self.actor.end_global_turn(3)
        self.assertEqual(self.actor.mp, mp - 90)

    def test_headache_only_affects_explicit_mental_rolls(self):
        ordinary = RollResolver().roll(self.actor, "perceive", allow_luck=False, initial_die=5)
        mental = RollResolver().roll(self.actor, "perceive", allow_luck=False, initial_die=5,
                                    modifier_context={"tags": {"mental"}})
        attack = RollResolver().roll(self.actor, "physical_attack", allow_luck=False, initial_die=5)
        self.assertEqual(mental.total, ordinary.total - 12)
        self.assertEqual(attack.total, 5 + self.actor.physical_attack)

    def test_survival_order_and_sun_lock_exhaustion(self):
        continuation = self.choose_privilege("battle_continuation")
        provider = ScriptedDecisionProvider(["setting_sun"] * 3)
        self.damage(self.actor.hp + 100, provider)
        self.assertTrue(self.actor.has_status("brink_of_death"))
        self.assertEqual(provider.command_index, 0)
        self.assertEqual(component_use_count(self.actor, continuation, continuation.definitions[0]), 0)
        self.actor.remove_status_modifiers("brink_of_death")
        for count in (1, 2):
            self.damage(100, provider)
            self.assertEqual(self.actor.hp, 1)
            self.assertEqual(component_use_count(self.actor, continuation, continuation.definitions[0]), count)
            self.assertEqual(provider.command_index, 0)
        for turn in (2, 3, 4):
            self.set_turn(turn)
            self.damage(100, provider)
            self.assertEqual(self.actor.hp, 1)
            used = provider.command_index
            self.actor.update_modifiers("battle_turn_end", turn_number=turn)
            self.damage(100, provider)
            self.assertEqual(provider.command_index, used)
            self.assertEqual(self.actor.hp, 1)
            self.actor.recover_resource("hp", 20)
            self.assertEqual(self.actor.hp, 21)
            self.damage(100, provider)
            self.assertEqual(self.actor.hp, 1)
            self.actor.update_modifiers("global_turn_end", turn_number=turn)
        self.assertEqual(provider.command_index, 3)
        self.assertFalse(any(skill.skill_id == "servant_test_0:setting_sun" for skill in self.actor.personal_skills))
        self.damage(100, provider)
        self.assertIn(self.actor, self.game.dead_characters)

    def test_multiple_other_survival_skills_are_player_choices(self):
        self.actor.brink_of_death_counter = 0
        self.actor.create_personal_skill({
            "skill_id": "fixture:other_survival", "name": "Other rescue", "rank": "C",
            "components": [{
                "component_id": "other", "type": "react", "target": "self",
                "trigger": {"event_type": "before_lethal_damage", "timing": "before"},
                "condition": {"event_target_is_self": True},
                "effects": [{"effect_type": "prevent_death", "effect_data": {"hp": 1}}],
            }],
        })
        provider = ScriptedDecisionProvider(["other"])
        self.damage(self.actor.hp + 1, provider)
        self.assertEqual(self.actor.hp, 1)
        self.assertEqual(len(provider.requests), 1)
        self.assertIn("纵使三度迎来夕阳", [option.label for option in provider.requests[0].options])
        self.assertFalse(any(mod.effect_type == "hp_floor" for mod in self.actor.modifiers))

    def test_theatre_auto_opens_after_chant_without_release_stage_cost(self):
        mp, count = self.actor.mp, self.actor.attack_phase_count
        field = self.open_theatre()
        self.assertEqual(self.actor.mp, mp - 40)
        self.assertEqual(self.actor.attack_phase_count, count)
        self.assertIsNone(self.actor.casting_state)
        self.assertIs(field.bound_battle, self.battle)
        self.assertTrue(self.actor.has_status("retain_attack_phase_on_failed_defense"))
        self.assertNotIn(self.noble("golden_theatre"), castable_sources(self.actor))
        self.battle.end_battle(reason="test_end")
        self.assertTrue(field.removed)
        self.assertFalse(self.actor.has_status("retain_attack_phase_on_failed_defense"))

    def test_theatre_protects_only_owner_from_failed_block_stage_loss(self):
        self.open_theatre()
        for target in (self.actor, self.first):
            target.attack_phase_count = 1
            attack = AttackEvent(self.second, target, 10, "physical", 999, None)
            with patch("game.turn.defense.random.randint", return_value=5):
                DefenseResolver().resolve_attack(target, attack, "block")
        self.assertEqual(self.actor.attack_phase_count, 1)
        self.assertEqual(self.first.attack_phase_count, 0)

    def test_theatre_requests_owner_permission_and_penalty_has_no_defense_window(self):
        self.open_theatre()
        provider = ScriptedDecisionProvider(["deny", "allow"])
        hp = self.first.hp
        self.battle.remove_participant(self.first, decision_provider=provider)
        self.assertEqual(self.first.hp, hp - 60)
        self.assertFalse(self.battle.ended)
        hp = self.second.hp
        self.battle.remove_participant(self.second, decision_provider=provider)
        self.assertEqual(self.second.hp, hp)
        self.assertTrue(all(request.phase == "battle_exit_permission" for request in provider.requests))
        self.assertTrue(all(request.character is self.actor for request in provider.requests))

    def test_theatre_penalty_also_covers_teleport_and_hidden_withdrawal(self):
        self.open_theatre()
        provider = ScriptedDecisionProvider(["deny", "deny"])
        self.game.decision_provider = provider
        hp = self.first.hp
        self.game.resolve_command_spell_teleport(self.first, self.b, decision_provider=provider)
        self.assertEqual(self.first.hp, hp - 60)
        self.assertIs(self.first.position, self.b)
        hp = self.second.hp
        self.second.add_modifier(create_modifier({
            "effect_type": "hidden", "duration": 1,
            "effect_data": {"value": "hidden", "withdraw_from_battle": True, "requires_building": False},
        }, self.second))
        self.assertEqual(self.second.hp, hp - 60)
        self.assertFalse(self.second.in_battle)
        self.assertEqual(provider.command_index, 2)

    def test_fatal_exit_penalty_does_not_move_or_duplicate_dead_character(self):
        self.open_theatre()
        self.first.hp = 20
        self.first.brink_of_death_counter = 0
        result = self.game.resolve_command_spell_teleport(
            self.first, self.b, decision_provider=ScriptedDecisionProvider(["deny"]),
        )
        self.assertTrue(result["interrupted_by_death"])
        self.assertIsNone(self.first.position)
        self.assertIs(self.first.death_location, self.a)
        self.assertIn(self.first, self.game.dead_characters)
        self.assertNotIn(self.first, self.b.occupants)
        self.assertNotIn(self.first, self.battle.participants)

    def test_ordinary_escape_uses_same_theatre_permission_window(self):
        self.open_theatre()
        self.game.decision_provider = ScriptedDecisionProvider(["deny"])
        self.first.add_modifier(create_modifier({"effect_type": "add_status", "effect_data": {"status_id": "stay"}}, self.first))
        self.first.attack_phase_count = 1
        before = self.first.hp
        action = Action(self.first, "escape")
        action.game_turn = 2
        self.assertTrue(action.escape())
        self.assertEqual(self.first.hp, before - 60)
        self.assertFalse(self.first.in_battle)

    def test_fatal_hidden_exit_leaves_no_hidden_modifier_on_dead_character(self):
        self.open_theatre()
        self.game.decision_provider = ScriptedDecisionProvider(["deny"])
        self.second.hp = 20
        self.second.brink_of_death_counter = 0
        result = self.second.add_modifier(create_modifier({
            "effect_type": "hidden", "duration": 1,
            "effect_data": {"value": "hidden", "withdraw_from_battle": True, "requires_building": False},
        }, self.second))
        self.assertFalse(result)
        self.assertFalse(self.second.is_alive())
        self.assertFalse(self.second.has_status("hidden"))
        self.assertFalse(any(item.effect_type == "hidden" for item in self.second.modifiers))
        self.assertNotIn(self.second, self.battle.participants)
        self.assertIsNone(self.second.position)

    def test_new_effect_fields_are_strictly_validated(self):
        for effect in (
            {"effect_type": "hp_floor", "effect_data": {"value": 0}},
            {"effect_type": "prevent_death", "effect_data": {"hp_floor_duration": -1}},
            {"effect_type": "create_attack_event", "effect_data": {"ignore_block": "yes"}},
            {"effect_type": "create_field", "effect_data": {
                "field_id": "invalid", "exit_penalty": {"value": 60, "damage_type": "physical"},
            }},
        ):
            with self.subTest(effect=effect), self.assertRaises((ValueError, TypeError)):
                validate_effect_definition(effect)

    def test_theatre_chant_refunds_if_battle_ends_before_completion(self):
        skill = self.noble("golden_theatre")
        mp = self.actor.mp
        state = CastingState.start(self.actor, skill, 1)
        self.battle.end_battle()
        self.assertNotIn(skill, castable_sources(self.actor))
        self.assertFalse(state.advance_at_global_turn_end(1))
        self.assertTrue(state.interrupted)
        self.assertEqual(self.actor.mp, mp)
        self.assertIsNone(self.actor.casting_state)
        self.assertEqual(self.game.field_manager.fields, [])

    def test_real_card_queue_routes_privilege_survival_and_exit_to_owner(self):
        self.open_theatre()
        self.actor.brink_of_death_counter = 0
        session = GameSession(self.game, {
            self.actor.character_id: "nero",
            **{actor.character_id: "other" for actor in (self.first, self.second, self.third)},
        })

        def cleanup():
            session.stop()
            self.assertTrue(session.join(2))

        self.addCleanup(cleanup)
        cursor = 0

        def request():
            nonlocal cursor
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                for event in session.get_events("gm", after=cursor, timeout=0.2):
                    cursor = event["sequence"]
                    if event["type"] == "decision_requested":
                        return event["payload"]
                    self.assertNotEqual(event["type"], "session_ended", event)
            self.fail("真实角色卡的会话决策未到达")

        def answer(dto, text):
            option = next(item for item in dto["options"] if text in item["label"])
            session.submit_decision(dto["controller_id"], dto["request_id"], dto["revision"],
                                    option_id=option["option_id"])

        session.start()
        privilege = request()
        self.assertEqual(privilege["controller_id"], "nero")
        answer(privilege, "单独行动")
        outer = request()
        while not outer["allow_refresh"]:
            answer(outer, "继续本阶段")
            outer = request()
        self.assertTrue(outer["allow_refresh"], outer)
        session.gm_command("gm", "damage", target_id=self.actor.character_id, damage_type=0, amount=999)
        reaction = request()
        self.assertEqual(reaction["controller_id"], "nero")
        self.assertFalse(reaction["allow_refresh"])
        answer(reaction, "纵使三度迎来夕阳")
        refreshed = request()
        self.assertEqual(self.actor.hp, 1)
        self.assertEqual(refreshed["phase"], outer["phase"])
        destination = next(node["position_id"] for node in session.get_snapshot("gm")["positions"]
                           if node["name"] == "Outside")
        before = self.first.hp
        session.gm_command("gm", "teleport", target_id=self.first.character_id, destination_id=destination)
        permission = request()
        self.assertEqual(permission["phase"], "battle_exit_permission")
        self.assertEqual(permission["controller_id"], "nero")
        self.assertIsNone(session.get_pending_decision("other"))
        answer(permission, "不允许")
        request()
        self.assertEqual(self.first.hp, before - 60)
        self.assertIs(self.first.position, self.b)

    def test_original_fire_is_an_instant_free_action_with_three_battle_uses(self):
        fire = self.noble("original_fire")
        entries = ActionListBuilder().get_available_actions(ActionContext(
            self.actor, "attack_phase", characters=self.game.characters, battle=self.battle, turn_number=1,
        ))
        self.assertIn(fire, [entry.skill for entry in entries])
        self.assertNotIn(fire, [skill for skill, _ in release_options(self.actor)])
        base, mp, count = self.actor.atk, self.actor.mp, self.actor.attack_phase_count
        for turn in (1, 2, 3):
            self.set_turn(turn)
            self.actor.resolve_skill_component(fire.skill_id, "original_fire", target=self.actor, turn_number=turn)
            self.assertEqual(self.actor.atk, base + 40)
            self.assertEqual(self.actor.mp, mp)
            self.assertEqual(self.actor.attack_phase_count, count)
            self.actor.update_modifiers("global_turn_end", turn_number=turn)
        with self.assertRaises(SkillUnavailableError):
            self.actor.resolve_skill_component(fire.skill_id, "original_fire", target=self.actor, turn_number=4)

    def test_laus_final_cost_damage_area_and_block_shield_bypass(self):
        skill = self.noble("laus_saint_claudius")
        self.assertEqual(get_casting_mp_cost(self.actor, skill), 100)
        state = CastingState.start(self.actor, skill, 1)
        state.advance_at_global_turn_end(1)
        self.first.add_modifier(create_modifier({"effect_type": "shield", "effect_data": {"value": 999}}, self.first))
        provider = ScriptedDecisionProvider(["First", "Second", "confirm"])
        self.actor.attack_phase_count = 1
        with patch("game.turn.roll.random.randint", return_value=5):
            self.assertTrue(Action(self.actor, "release").release(provider))
        self.assertEqual(self.actor.attack_phase_count, 0)
        first_attack, second_attack = self.first.pending_attacks[-1], self.second.pending_attacks[-1]
        self.assertEqual(first_attack.value, 150)
        self.assertEqual(first_attack.damage_type, "magic")
        self.assertTrue(first_attack.ignore_shield)
        self.assertTrue(first_attack.ignore_block)
        hp = self.first.hp
        with patch("game.turn.defense.random.randint", return_value=5):
            DefenseResolver().resolve_phase(self.first, "block", attacks=[first_attack])
        self.assertEqual(self.first.hp, hp - 150)
        self.assertEqual(self.first.shield, 999)
        self.second.dodge = 999
        with patch("game.turn.defense.random.randint", return_value=5):
            result = DefenseResolver().resolve_phase(self.second, "dodge", attacks=[second_attack])
        self.assertEqual(result["total_damage"], 0)

    def test_laus_can_be_offset_by_release_magic_and_still_respects_resistance(self):
        skill = self.noble("laus_saint_claudius")
        self.actor.resolve_skill_component(skill.skill_id, "release", target=self.first,
                                          casting_prepaid=True, casting_release=True, turn_number=1)
        attack = self.first.pending_attacks[-1]
        self.first.load_basic_magic("magic_bullet")
        provider = ScriptedDecisionProvider(["offset", "魔弹"])
        with patch("game.turn.roll.random.randint", return_value=5):
            attempt = self.battle.request_defense(self.first, provider, attacks=[attack])
        self.assertGreater(attempt.reduction, 0)
        self.first.magic_resistance = 0.2
        result = DefenseResolver().resolve_phase(self.first, attempt, attacks=[attack])
        self.assertLess(result["total_damage"], 120)

    def test_real_card_master_payment_death_and_grail_checkpoint(self):
        self.first.add_servant(self.actor)
        self.actor.mp = 10
        before = self.first.mp
        state = CastingState.start(self.actor, self.noble("laus_saint_claudius"), 1)
        self.assertIsNotNone(state)
        self.assertEqual(self.actor.mp, 0)
        self.assertEqual(self.first.mp, before - 90)
        state.interrupt()
        self.assertEqual(self.actor.mp, 10)
        self.assertEqual(self.first.mp, before)
        self.actor.brink_of_death_counter = 0
        self.damage(self.actor.hp + 1, ScriptedDecisionProvider(["skip"]))
        self.assertIn(self.actor, self.game.dead_characters)
        self.assertNotIn(self.actor, self.first.servants)
        self.game.on_ap_checkpoint(1)
        self.assertIs(self.game.holy_grail.position, self.a)


if __name__ == "__main__":
    unittest.main()
