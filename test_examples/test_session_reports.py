import contextlib
import io
import json
import time
import unittest
from unittest.mock import patch

from game.action.action import Action
from game.character import create_character_from_card
from game.character.masters import Master
from game.game_manager import GameManager
from game.game_session import GameSession
from game.session_view import character_view
from game.map.map import Location
from game.modifier.modifier import create_modifier
from game.skill.casting import CastingState
from game.skill.component_runtime import record_component_use
from game.skill.reality_marble_runtime import RealityMarble
from game.turn.battle import BattleManager
from game.turn.damage import DamageEvent, DamageResolver
from game.turn.decision import ScriptedDecisionProvider
from game.turn.defense import DefenseResolver


class SessionReportTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b = Location("Arena", is_building=True), Location("Secret")
        self.nero = create_character_from_card("servant_test_0", name="Nero", position=self.a)
        self.target = Master("Target", 3, 8, 3, 3, 3, "C", 3)
        self.witness = Master("Witness", 3, 3, 3, 3, 3, "C", 3)
        self.secret = Master("SecretActor", 3, 3, 3, 3, 3, "C", 3)
        self.target.position = self.witness.position = self.a
        self.secret.position = self.b
        self.game = GameManager([self.nero, self.target, self.witness, self.secret], self.a)
        self.game.start_game()
        self.game.turn_manager.turn = 1
        for character in self.game.characters:
            character.current_global_turn = 1
            character.own_visible.clear()
            character.shared_visible.clear()
            character.perceived.clear()
        self.witness.own_visible.extend([self.nero, self.target])
        self.session = GameSession(self.game, {
            self.nero.character_id: "nero", self.target.character_id: "target",
            self.witness.character_id: "witness", self.secret.character_id: "secret",
        })
        # Synchronous projection fixtures do not start a competing worker.
        self.game.rule_reports.subscribe(self.session._on_rule_report)
        self.addCleanup(self.game.rule_reports.unsubscribe, self.session._on_rule_report)

    def battle(self):
        battle = BattleManager([self.nero, self.target, self.witness])
        self.game.turn_manager.battles.append(battle)
        battle.start_battle()
        return battle

    def view(self, character):
        return character_view(character, self.session._position_id, exact=True)

    def reports(self, owner="gm", kind=None):
        values = [event["payload"] for event in self.session.get_events(owner) if event["type"] == "rule_report"]
        return [value for value in values if kind is None or value["kind"] == kind]

    def skill(self, actor, suffix):
        return next(skill for skill in (*actor.personal_skills, *getattr(actor, "noble_phantasms", []))
                    if skill.skill_id.endswith(":" + suffix))

    def choose(self, choice, turn):
        self.game.turn_manager.turn = self.nero.current_global_turn = turn
        self.game.event_manager.emit("global_turn_start", decision_provider=ScriptedDecisionProvider([choice]))

    def test_card_view_has_final_noble_values_and_reading_does_not_create_runtime_state(self):
        self.battle()
        skills = self.nero.personal_skills + self.nero.noble_phantasms
        before = [dict(skill.component_runtime_states) for skill in skills]
        view = self.view(self.nero)
        json.dumps(view, allow_nan=False)
        laus = next(skill for skill in view["skills"] if skill["skill_id"].endswith(":laus_saint_claudius"))
        self.assertEqual(laus["casting"]["mp_cost"], 100)
        self.assertIn("150", laus["description"])
        self.assertIn("150", laus["components"][0]["effects"][0]["description"])
        self.assertEqual(before, [skill.component_runtime_states for skill in skills])
        self.assertEqual(view["attribute_details"]["flexibility"]["rank"], "A")

    def test_usage_and_cached_skill_set_views_follow_actual_battle_counters(self):
        self.battle()
        self.choose("swordsmanship", 1)
        sword = self.skill(self.nero, "swordsmanship")
        self.nero.resolve_skill_component(sword.skill_id, "swordsmanship", target=self.nero,
                                         selected_choice_ids=["attack"], turn_number=1)
        self.choose("independent_action", 2)
        group = self.view(self.nero)["skill_sets"][0]
        self.assertEqual(group["current_set"], "independent_action")
        cached = next(item for item in group["sets"] if item["set_id"] == "swordsmanship")
        self.assertFalse(cached["active"])
        self.assertEqual(cached["skills"][0]["components"][0]["usage"]["remaining"], 2)
        self.choose("swordsmanship", 3)
        current = next(item for item in self.view(self.nero)["skills"] if item["skill_id"] == sword.skill_id)
        self.assertEqual(current["components"][0]["usage"]["used"], 1)

    def test_battle_usage_outside_battle_is_inapplicable_and_new_battle_has_new_counter(self):
        battle = self.battle()
        fire = self.skill(self.nero, "original_fire")
        self.nero.resolve_skill_component(fire.skill_id, "original_fire", target=self.nero, turn_number=1)
        battle.end_battle()
        fire_view = next(item for item in self.view(self.nero)["skills"] if item["skill_id"] == fire.skill_id)
        self.assertIsNone(fire_view["components"][0]["usage"]["remaining"])
        self.assertIn("battle_usage_requires_battle", fire_view["components"][0]["runtime_reasons"])
        next_battle = self.battle()
        self.assertNotEqual(battle.battle_id, next_battle.battle_id)
        fire_view = next(item for item in self.view(self.nero)["skills"] if item["skill_id"] == fire.skill_id)
        self.assertEqual(fire_view["components"][0]["usage"]["remaining"], 3)

    def test_shared_cooldown_and_expired_components_are_presented_without_claiming_legality(self):
        skill = self.target.create_personal_skill({
            "skill_id": "cooldown", "name": "Cooldown", "rank": "C",
            "components": [{"component_id": key, "type": "active", "target": "self",
                            "cooldown": {"turns": 2, "group": "shared"},
                            "effects": [{"effect_type": "attack_bonus", "effect_data": {"value": 1}}]}
                           for key in ("first", "second")],
        })
        record_component_use(self.target, skill, skill.definitions[0], turn_number=1)
        skill.expire_component("first")
        view = next(item for item in self.view(self.target)["skills"] if item["skill_id"] == "cooldown")
        self.assertFalse(view["components"][0]["active"])
        self.assertEqual(view["components"][1]["cooldown"]["ready_turn"], 4)
        self.assertEqual(view["components"][1]["cooldown"]["turns_remaining"], 3)
        self.assertFalse(view["components"][1]["runtime_available"])

    def test_shield_view_shows_remaining_value_and_mental_restriction(self):
        self.target.add_modifier(create_modifier({"effect_type": "shield", "effect_data": {"value": 35}}, self.target))
        DamageResolver().resolve(DamageEvent(self.nero, self.target, 10, "physical"))
        view = self.view(self.target)
        self.assertEqual(view["combat"]["shield"], 25)
        self.assertEqual(next(item for item in view["modifiers"] if item["effect_type"] == "shield")["value"], 25)
        headache = next(item for item in self.view(self.nero)["skills"] if item["name"] == "头痛")
        self.assertIn("精神", headache["description"])

    def test_casting_state_and_reports_cover_shared_mp_progress_and_refund(self):
        self.target.add_servant(self.nero)
        self.nero.mp = 10
        mp = self.target.mp
        skill = self.skill(self.nero, "laus_saint_claudius")
        state = CastingState.start(self.nero, skill, 1)
        state.advance_at_global_turn_end(1)
        self.assertEqual(self.view(self.nero)["casting"]["layers"], 1)
        self.assertEqual(self.view(self.nero)["casting"]["paid_mp"], 100)
        state.interrupt(reason="test")
        self.assertEqual(self.target.mp, mp)
        self.assertIsNone(self.view(self.nero)["casting"])
        self.assertEqual(self.reports("nero", "casting_interrupted")[-1]["data"]["refunded_mp"], 100)
        self.assertEqual(self.reports("target", "casting_started"), [])
        self.assertTrue(self.reports("target", "resource_changed"))

    def test_hidden_attacker_is_redacted_and_hp_and_skill_details_have_distinct_audiences(self):
        DamageResolver().resolve(DamageEvent(self.secret, self.nero, 9, "magic", skill_id="secret_spell"))
        target_report = self.reports("nero", "damage_resolved")[-1]
        self.assertIsNone(target_report["actor"])
        self.assertEqual(target_report["data"]["amount"], 9)
        self.assertIn("hp_after", target_report["data"])
        self.assertNotIn("secret_spell", json.dumps(target_report))
        source_report = self.reports("secret", "damage_resolved")[-1]
        self.assertNotIn("hp_after", source_report["data"])
        self.assertEqual(source_report["data"]["skill_id"], "secret_spell")
        observer = self.reports("witness", "damage_resolved")[-1]
        self.assertNotIn("amount", observer["data"])
        self.assertIsNone(observer["actor"])
        self.assertEqual(self.reports("gm", "damage_resolved")[-1]["actor"]["name"], "SecretActor")

    def test_private_changes_do_not_reach_visible_witnesses_or_unseen_controllers(self):
        self.nero._emit_builtin_resource_change("resource_gained", "mp", 10, 20,
                                                requested_value=10, operation="add", reason="test")
        self.assertTrue(self.reports("nero", "resource_changed"))
        self.assertEqual(self.reports("witness", "resource_changed"), [])
        self.assertEqual(self.reports("secret", "resource_changed"), [])
        snapshot = self.session.get_snapshot("witness")
        enemy = next(actor for actor in snapshot["characters"] if actor["character_id"] == self.nero.character_id)
        for key in ("skills", "casting", "modifiers", "combat", "card_id", "hp"):
            self.assertNotIn(key, enemy)

    def test_visibility_is_frozen_per_record_and_returned_data_is_detached(self):
        DamageResolver().resolve(DamageEvent(self.secret, self.nero, 3, "physical"))
        original = self.reports("nero")
        self.nero.own_visible.append(self.secret)
        self.session._capture_views()
        self.assertEqual(self.reports("nero"), original)
        self.assertIsNone(self.reports("nero", "damage_resolved")[-1]["actor"])
        original[-1]["data"]["amount"] = 999
        self.assertEqual(self.reports("nero", "damage_resolved")[-1]["data"]["amount"], 3)
        json.dumps(self.session.get_events("gm"), allow_nan=False)
        json.dumps(self.game.rule_reports.history, allow_nan=False)

    def test_attack_roll_defense_and_damage_share_attack_identity_and_keep_enemy_rolls_private(self):
        self.battle()
        self.nero.own_visible.append(self.target)
        self.target.own_visible.append(self.nero)
        profile = Action(self.nero, "attack", damage_value=40).build_attack_profile()
        attack = profile.assign_target(self.target)
        self.target.add_modifier(create_modifier({"effect_type": "shield", "effect_data": {"value": 10}}, self.target))
        with patch("game.turn.defense.random.randint", return_value=5):
            DefenseResolver().resolve_phase(self.target, "block", attacks=[attack])
        self.assertFalse(attack.consume_resolution_modifiers())
        declared = self.reports("target", "attack_declared")[-1]
        damage = self.reports("target", "damage_resolved")[-1]
        resolved = self.reports("target", "attack_resolved")[-1]
        self.assertEqual(declared["data"]["attack_id"], damage["data"]["attack_id"])
        self.assertEqual(declared["data"]["attack_id"], resolved["data"]["attack_id"])
        self.assertEqual(resolved["data"]["defense_type"], "block")
        self.assertEqual(len(self.reports("target", "attack_resolved")), 1)
        self.assertEqual(damage["data"]["shield_absorbed"], 10)
        self.assertEqual([item["data"]["stat_name"] for item in self.reports("nero", "roll_resolved")], ["physical_attack"])
        self.assertEqual([item["data"]["stat_name"] for item in self.reports("target", "roll_resolved")], ["block"])

    def test_dodge_and_teleport_misses_are_reported_without_fake_damage(self):
        self.battle()
        self.target.dodge = 999
        for method in ("dodge", "teleport"):
            attack = Action(self.nero, "attack").build_attack_profile().assign_target(self.target)
            if method == "dodge":
                with patch("game.turn.defense.random.randint", return_value=5):
                    DefenseResolver().resolve_phase(self.target, "dodge", attacks=[attack])
            else:
                attack.miss_because_target_moved()
            self.assertFalse(self.reports("gm", "attack_resolved")[-1]["data"]["hit"])
        self.assertEqual(self.reports("gm", "damage_resolved"), [])
        self.assertEqual(self.reports("gm", "attack_resolved")[-1]["data"]["reason"], "target_teleported")

    def test_field_lifecycle_exit_penalty_and_death_reports_keep_complete_json(self):
        battle = self.battle()
        state = CastingState.start(self.nero, self.skill(self.nero, "golden_theatre"), 1)
        state.advance_at_global_turn_end(1)
        self.assertEqual(len(self.view(self.nero)["fields"]), 1)
        self.target.hp = 10
        self.target.brink_of_death_counter = 0
        battle.remove_participant(self.target, decision_provider=ScriptedDecisionProvider(["deny"]))
        self.assertFalse(self.reports("target", "battle_exit_permission")[-1]["data"]["allowed"])
        self.assertTrue(self.reports("target", "character_died"))
        battle.end_battle(reason="test")
        self.assertEqual(self.view(self.nero)["fields"], [])
        self.assertTrue(self.reports("nero", "field_removed"))
        self.assertEqual(self.reports("gm", "battle_ended")[-1]["data"]["reason"], "test")
        json.dumps(self.session.get_snapshot("gm"), allow_nan=False)

    def test_real_cards_complete_session_and_nested_reaction_produces_owned_report(self):
        location = Location("RealCards")
        master = create_character_from_card("master_test_0", name="Master", position=location)
        nero = create_character_from_card("servant_test_0", name="Nero", position=location, master=master)
        game = GameManager([master, nero], location, maximum_turns=1)
        session = GameSession(game, {master.character_id: "master", nero.character_id: "nero"})
        self.addCleanup(lambda: (session.stop(), session.join(2)))
        cursor = 0
        injected = False
        deadline = time.monotonic() + 5
        with contextlib.redirect_stdout(io.StringIO()):
            session.start()
            while time.monotonic() < deadline:
                for event in session.get_events("gm", after=cursor, timeout=0.1):
                    cursor = event["sequence"]
                    if event["type"] == "session_ended":
                        self.assertEqual(event["payload"]["state"], "completed", session.get_snapshot("gm"))
                        self.assertTrue(session.join(2))
                        records = [item["payload"] for item in session.get_events("master") if item["type"] == "rule_report"]
                        use = next(item for item in records if item["kind"] == "skill_activated"
                                   and item["data"].get("skill_name") == "无瑕之人")
                        self.assertEqual(use["data"]["paid_costs"]["mp"], 10)
                        self.assertEqual(game.rule_reports._listeners, [])
                        for owner in ("master", "nero", "gm"):
                            json.dumps(session.get_snapshot(owner), allow_nan=False)
                            json.dumps(session.get_events(owner), allow_nan=False)
                        return
                    if event["type"] != "decision_requested":
                        continue
                    request = event["payload"]
                    if request["allow_refresh"] and not injected:
                        session.gm_command("gm", "damage", target_id=master.character_id, damage_type=0, amount=20)
                        injected = True
                        continue
                    if request["kind"] == "numeric":
                        session.submit_decision(request["controller_id"], request["request_id"], request["revision"], value=10)
                    else:
                        options = request["options"]
                        preferred = ("无瑕之人", "单独行动", "空过", "继续本阶段", "确认当前骰面")
                        option = next((item for text in preferred for item in options if text in item["label"]), options[0])
                        session.submit_decision(request["controller_id"], request["request_id"], request["revision"], option_id=option["option_id"])
        self.fail(f"真实卡片会话未完成：{session.get_snapshot('gm')}")

    def test_marble_definition_preserves_live_references_with_a_session_listener(self):
        definition = {"reality_marble_id": "test", "entrance": self.a,
                      "selected_targets": [self.nero], "interior": {"effects": []}}
        marble = RealityMarble(definition, self.nero, self.skill(self.nero, "golden_theatre"))
        self.assertIs(marble.entrance, self.a)
        self.assertIs(marble.selected_targets[0], self.nero)
        marble.definition["interior"]["effects"].append({"test": True})
        self.assertEqual(definition["interior"]["effects"], [])

    def test_reaction_event_quota_is_contextual_and_does_not_mutate_on_read(self):
        skill = self.target.create_personal_skill({
            "skill_id": "reaction_quota", "name": "Quota", "rank": "C",
            "components": [{"component_id": "guard", "type": "react", "target": "self",
                            "trigger": {"event_type": "before_damage", "timing": "before"},
                            "condition": {"event_target_is_self": True},
                            "effects": [{"effect_type": "modify_event_value",
                                         "effect_data": {"operation": "add", "value": -1}}]}],
        })
        events = self.game.event_manager
        outside = events.component_limit_view(self.target, skill, skill.definitions[0])
        self.assertIsNone(outside["remaining"])
        captured = []

        def capture(record, context):
            if record["kind"] == "skill_activated" and record["data"]["actor"].get("skill_id") == skill.skill_id:
                captured.append(events.component_limit_view(self.target, skill, skill.definitions[0]))

        self.game.rule_reports.subscribe(capture)
        DamageResolver().resolve(DamageEvent(self.nero, self.target, 10, "physical"),
                                 decision_provider=ScriptedDecisionProvider(["guard"]))
        self.assertEqual(captured[0]["remaining"], 0)
        self.assertFalse(captured[0]["context_required"])

    def test_report_view_failure_unsubscribes_and_releases_worker(self):
        self.game.rule_reports.unsubscribe(self.session._on_rule_report)
        session = self.session
        capture = session._capture_views

        def broken_after_report():
            if any(event["type"] == "rule_report" for event in session._events):
                raise RuntimeError("report view failed")
            capture()

        def run(loop):
            self.game.rule_reports.record("test", actor=self.nero, private=True)

        session._capture_views = broken_after_report
        with patch("game.game_session._SessionGameLoop.run", run):
            session.start()
            self.assertTrue(session.join(2))
        self.assertEqual(session.state, "failed")
        self.assertIn("report view failed", session.get_snapshot("gm")["error"])
        self.assertEqual(self.game.rule_reports._listeners, [])
        self.assertIsNone(self.game._active_session)
        self.assertEqual(session.get_events("nero")[-1]["type"], "session_ended")


if __name__ == "__main__":
    unittest.main()
