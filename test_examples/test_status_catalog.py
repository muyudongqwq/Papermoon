"""Status definitions, live sources, expiry boundaries and editor projects."""

import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.catalog import CatalogProject, empty_project
from core.terminal_commands import TerminalCommandHandler
from game.character.masters import Master
from game.character.servants import Servant
from game.character.familiar import Familiar
from game.game.character_state import character_state, effect_view
from game.game.game_manager import GameManager
from game.game.game_session import GameSession
from game.map.map import Location
from game.modifier.modifier import create_modifier
from game.skill.effect_validation import validate_effect_definition
from game.skill.skill import Skill
from game.skill.skill_runtime import apply_skill_effect, SkillUnavailableError
from game.status.data import STATUS_DATA, marker
from game.status.registry import validate_status_catalog, validate_status_definition
from game.turn.damage import DamageEvent, DamageResolver
from game.turn.decision import ScriptedDecisionProvider
from skilleditor.documents import copy_definition, new_definition, parse_entry


def damage(value=1):
    return {"effect_type": "damage", "effect_data": {"value": value, "damage_type": "magic"}}


def component(kind="trigger", event="damage_received", effects=None, **kwargs):
    return {"component_id": "tick", "type": kind, "target": "self",
            "trigger": {"event_type": event}, "effects": effects or [damage()], **kwargs}


class StatusRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.catalog = patch.dict(STATUS_DATA, deepcopy(STATUS_DATA), clear=True)
        self.catalog.start()
        self.addCleanup(self.catalog.stop)
        self.capture = contextlib.redirect_stdout(io.StringIO())
        self.capture.__enter__()
        self.addCleanup(self.capture.__exit__, None, None, None)
        self.a, self.b, self.target = [Master(n, 3, 3, 3, 3, 3, "C", 3) for n in ("A", "B", "Target")]
        self.location = Location("A", is_building=True)
        for actor in (self.a, self.b, self.target):
            actor.position = self.location
        self.game = GameManager([self.a, self.b, self.target], self.location)
        self.game.start_game()
        self.game.turn_manager.turn = 1
        self.source = Skill("Fire", "C", definitions=[], skill_id="fire")

    def define(self, key="test_status", components=None, **kwargs):
        definition = marker(key, key, polarity="debuff", purifiable=True)
        definition.update(components=components or [], **kwargs)
        STATUS_DATA[key] = definition
        validate_status_definition(definition)
        return definition

    def apply(self, key="burning", actor=None, target=None, source=None, **kwargs):
        return apply_skill_effect({"effect_type": "add_status", "effect_data": {"status_id": key}, **kwargs},
                                  target or self.target, source or self.source, actor=actor or self.a).modifier

    def end(self, turn):
        self.game.turn_manager.turn = turn
        self.game.resolve_turn_end_event(turn)

    def test_burning_ticks_three_times_then_expires_without_card_skill(self):
        self.apply()
        hp = self.target.hp
        for turn in (1, 2, 3, 4):
            self.end(turn)
            self.assertEqual(self.target.hp, hp - 10 * min(turn, 3))
        self.assertFalse(self.target.has_status("burning"))
        self.assertEqual(self.target.personal_skills, [])

    def test_multiple_casters_using_same_skill_remain_separate_and_attributed(self):
        first = self.apply(actor=self.a)
        second = self.apply(actor=self.b)
        self.assertIsNot(first, second)
        self.end(1)
        self.assertEqual(self.target.hp, 70)
        reports = [r for r in self.game.rule_reports.history if r["kind"] == "status_triggered"]
        self.assertEqual([r["actor"]["name"] for r in reports], ["A", "B"])
        self.assertEqual([r["data"]["target"]["instance_id"] for r in reports],
                         [first.status_runtime.instance_id, second.status_runtime.instance_id])

    def test_same_caster_reapplication_refreshes_without_duplicate_tick(self):
        STATUS_DATA["burning"]["stacking"]["stacking_rule"] = "refresh"
        original = self.apply()
        self.end(1)
        self.assertEqual(original.duration, 2)
        self.assertIs(self.apply(), original)
        self.assertEqual(original.duration, 3)
        self.end(2)
        self.assertEqual(self.target.hp, 70)

    def test_burning_two_stacks_deal_twenty_and_refresh_time(self):
        original = self.apply()
        self.end(1)
        self.assertIs(self.apply(), original)
        self.assertEqual((original.stack_count, original.duration), (2, 3))
        self.end(2)
        self.assertEqual(self.target.hp, 60)

    def test_burning_cap_limits_damage_and_stacks(self):
        for _ in range(5):
            status = self.apply()
        self.assertEqual(status.stack_count, 3)
        self.end(1)
        self.assertEqual(self.target.hp, 60)

    def test_each_caster_damage_uses_its_own_stack_count(self):
        self.apply(actor=self.a)
        self.apply(actor=self.a)
        self.apply(actor=self.b)
        self.end(1)
        self.assertEqual(self.target.hp, 60)
        records = [r for r in self.game.rule_reports.history if r["kind"] == "status_triggered"]
        self.assertEqual([r["data"]["target"]["stack_count"] for r in records], [2, 1])
        self.assertEqual([r["actor"]["name"] for r in records], ["A", "B"])

    def test_stack_value_reads_current_layers_after_earlier_end_trigger(self):
        skill = self.target.create_personal_skill({"skill_id": "renew", "name": "renew", "rank": "C",
            "components": [component(event="global_turn_end", effects=[{
                "effect_type": "add_status", "effect_data": {"status_id": "burning"}}])]})
        self.apply(actor=self.target, source=skill)
        self.end(1)
        self.assertEqual(self.target.hp, 70)

    def test_scaled_damage_keeps_multiplier_flat_and_damage_pipeline(self):
        data = STATUS_DATA["burning"]["components"][0]["effects"][0]["effect_data"]
        data.update(multiplier=7, flat=2)
        self.apply()
        self.apply()
        self.target.add_modifier(create_modifier({"effect_type": "shield", "effect_data": {"value": 5}}, self.target))
        self.end(1)
        self.assertEqual(self.target.hp, 79)  # (2 * 7 + 2) - 5

    def test_fixed_value_remains_fixed_when_status_has_multiple_stacks(self):
        self.define(components=[component(event="global_turn_end", effects=[damage(10)])],
                    stacking={"stack_scope": "same_source", "stacking_rule": "stack", "max_stacks": 3})
        for _ in range(3):
            self.apply("test_status")
        self.end(1)
        self.assertEqual(self.target.hp, 80)

    def test_react_can_read_stacks_without_reacting_multiple_times(self):
        self.define(components=[component("react", effects=[{
            "effect_type": "damage", "effect_data": {"damage_type": "magic",
                "value_source": "status_stack_count", "multiplier": 10}}])],
            stacking={"stack_scope": "same_source", "stacking_rule": "stack", "max_stacks": 3})
        self.apply("test_status")
        self.apply("test_status")
        decisions = ScriptedDecisionProvider(["1"])
        self.game.decision_provider = decisions
        DamageResolver().resolve(DamageEvent(self.a, self.target, 2, "magic"))
        self.assertEqual(self.target.hp, 68)
        self.assertEqual(len(decisions.requests), 1)

    def test_resource_recovery_can_read_stack_count(self):
        self.define(components=[component(event="global_turn_end", effects=[{
            "effect_type": "recover_resource", "effect_data": {"resource_id": "hp", "value_source": "status_stack_count"}}])],
            stacking={"stack_scope": "same_source", "stacking_rule": "stack", "max_stacks": 3})
        self.target.hp = 60
        for _ in range(3):
            self.apply("test_status")
        self.end(1)
        self.assertEqual(self.target.hp, 63)

    def test_temporary_mp_can_scale_from_status_stacks(self):
        self.define(components=[component(event="probe", effects=[{
            "effect_type": "grant_temporary_mp", "effect_data": {
                "value_source": "status_stack_count", "multiplier": 5, "flat": 1}}])],
            stacking={"stack_scope": "same_source", "stacking_rule": "stack", "max_stacks": 3})
        self.apply("test_status")
        self.apply("test_status")
        self.game.event_manager.emit("probe")
        self.assertEqual(self.target.temporary_mp, 11)

    def test_stack_source_is_unavailable_on_ordinary_skills(self):
        effect = {"effect_type": "damage", "effect_data": {
            "damage_type": "magic", "value_source": "status_stack_count", "multiplier": 10}}
        with self.assertRaises(SkillUnavailableError):
            apply_skill_effect(effect, self.target, self.source, actor=self.a, status_stack_count=999)
        self.assertEqual(self.target.hp, 90)

    def test_layer_formula_is_shown_in_effect_description(self):
        effect = STATUS_DATA["burning"]["components"][0]["effects"][0]
        self.assertIn("状态层数×10", effect_view(effect)["description"])

    def test_purifying_one_source_keeps_other_source_and_aggregate_flag(self):
        first, second = self.apply(actor=self.a), self.apply(actor=self.b)
        self.target.purify_modifiers(first)
        self.assertTrue(self.target.has_status("burning"))
        self.assertIn(second, self.target.modifiers)
        self.end(1)
        self.assertEqual(self.target.hp, 80)

    def test_full_purification_stops_damage(self):
        self.apply()
        self.target.purify_modifiers()
        self.end(1)
        self.assertEqual(self.target.hp, 90)

    def test_caster_death_does_not_turn_existing_burn_into_self_damage(self):
        self.apply()
        self.a.die()
        self.end(1)
        self.assertEqual(self.target.hp, 80)
        report = next(r for r in self.game.rule_reports.history if r["kind"] == "status_triggered")
        self.assertEqual(report["actor"]["name"], "A")

    def test_target_death_cleans_status_and_stops_triggers(self):
        self.apply()
        self.target.die()
        self.end(1)
        self.assertEqual(self.target.modifiers, [])
        self.assertFalse(any(r["kind"] == "status_triggered" for r in self.game.rule_reports.history))

    def test_servant_uses_same_status_engine(self):
        servant = Servant("Servant", 3, 3, 3, 3, 3, "Saber", "C")
        self.game.register_character(servant, self.location)
        hp = servant.hp
        self.apply(target=servant)
        self.end(1)
        self.assertEqual(servant.hp, hp - 10)

    def test_familiar_uses_same_status_engine(self):
        familiar = Familiar("Familiar", self.target)
        self.game.register_character(familiar, self.location)
        self.apply(target=familiar)
        self.end(1)
        self.assertEqual(familiar.hp, 20)

    def test_separate_sources_keep_independent_expiry(self):
        self.apply(actor=self.a, duration=1)
        self.apply(actor=self.b, duration=2)
        self.end(1)
        self.assertEqual(self.target.hp, 70)
        statuses = character_state(self.target)["status_instances"]
        self.assertEqual([s["source_name"] for s in statuses], ["B"])
        self.end(2)
        self.assertEqual(self.target.hp, 60)

    def test_reactive_value_change_uses_owner_condition_and_original_source(self):
        self.define(components=[component("react", event="before_damage",
            trigger={"event_type": "before_damage", "timing": "before"},
            condition={"event_target_is_self": True}, effects=[{
                "effect_type": "modify_event_value", "effect_data": {"calculation": "add", "value": -2, "minimum": 0}}])])
        self.apply("test_status")
        decisions = ScriptedDecisionProvider(["1"])
        self.game.decision_provider = decisions
        DamageResolver().resolve(DamageEvent(self.a, self.b, 5, "magic"))
        self.assertEqual(len(decisions.requests), 0)
        DamageResolver().resolve(DamageEvent(self.b, self.target, 5, "magic"))
        self.assertEqual(self.target.hp, 87)
        self.assertIs(decisions.requests[0].character, self.target)

    def test_status_can_recover_resources_using_same_effect_dictionary(self):
        self.define(components=[component(event="global_turn_end", effects=[{
            "effect_type": "recover_resource", "effect_data": {"resource_id": "hp", "value": 5}}])])
        self.target.hp -= 20
        self.apply("test_status")
        self.end(1)
        self.assertEqual(self.target.hp, 75)

    def test_reapplying_from_inside_a_trigger_does_not_bypass_turn_quota(self):
        self.define(components=[component(event="status_added", effects=[{
            "effect_type": "add_status", "effect_data": {"status_id": "test_status"}}])])
        self.apply("test_status")
        records = [r for r in self.game.rule_reports.history if r["kind"] == "status_triggered"]
        self.assertEqual(len(records), 1)
        self.assertFalse(any(event.stopped for event in self.game.event_manager.history))

    def test_terminal_status_lists_each_source_and_remaining_time(self):
        self.apply(actor=self.a)
        self.apply(actor=self.b)
        output = []
        TerminalCommandHandler(self.game, output_func=output.append).show_character(self.target)
        text = "\n".join(output)
        self.assertIn("燃烧（来源：A；3回合；1层）", text)
        self.assertIn("燃烧（来源：B；3回合；1层）", text)

    def test_hidden_caster_provenance_is_preserved_for_gm_and_redacted_for_player(self):
        self.a.position = self.b.position = Location("Far")
        self.target.own_perceived.clear()
        self.target.shared_perceived.clear()
        self.target.perceived.clear()
        session = GameSession(self.game, {self.target.character_id: "player", self.a.character_id: "enemy", self.b.character_id: "enemy"})
        self.game.rule_reports.subscribe(session._on_rule_report)
        self.addCleanup(self.game.rule_reports.unsubscribe, session._on_rule_report)
        self.apply()
        gm = session.get_snapshot("gm")
        player = session.get_snapshot("player")
        gm_target = next(c for c in gm["characters"] if c["name"] == "Target")
        player_target = next(c for c in player["characters"] if c["name"] == "Target")
        self.assertEqual(gm_target["status_instances"][0]["source_name"], "A")
        self.assertIsNone(player_target["status_instances"][0]["source_name"])
        reports = [e["payload"] for e in session.get_events("player") if e["type"] == "rule_report"]
        applied = next(r for r in reports if r["kind"] == "modifier_applied")
        self.assertIsNone(applied["data"]["status_instance"]["source_name"])

    def test_damage_still_uses_shields(self):
        self.apply()
        self.target.add_modifier(create_modifier({"effect_type": "shield", "effect_data": {"value": 6}}, self.target))
        self.end(1)
        self.assertEqual(self.target.hp, 86)

    def test_status_does_not_expire_at_individual_battle_turn_end(self):
        status = self.apply(duration=1)
        self.target.update_modifiers("battle_turn_end", turn_number=1)
        self.assertEqual(status.duration, 1)
        self.end(1)
        self.assertEqual(self.target.hp, 80)
        self.assertFalse(self.target.has_status("burning"))

    def test_real_turn_manager_sends_event_before_expiry_once(self):
        self.apply(duration=1)
        self.game.turn_manager.end_turn()
        self.assertEqual(self.target.hp, 80)
        self.assertFalse(self.target.has_status("burning"))
        self.assertEqual(sum(e.event_type == "global_turn_end" for e in self.game.event_manager.history), 1)

    def test_turn_manager_passes_explicit_decision_provider_to_end_reactions(self):
        self.define(components=[component("react", event="global_turn_end")])
        self.apply("test_status")
        decisions = ScriptedDecisionProvider(["1"])
        self.game.turn_manager.end_turn(decision_provider=decisions)
        self.assertEqual(len(decisions.requests), 1)
        self.assertEqual(self.target.hp, 89)

    def test_status_applied_during_end_event_waits_until_next_boundary(self):
        self.target.create_personal_skill({"skill_id": "ignite", "name": "ignite", "rank": "C",
            "components": [component(event="global_turn_end", effects=[{
                "effect_type": "add_status", "effect_data": {"status_id": "burning"}}])]})
        self.end(1)
        instance = character_state(self.target)["status_instances"][0]
        self.assertEqual(instance["duration"], 3)
        self.assertEqual(self.target.hp, 90)

    def test_status_refreshed_during_end_event_keeps_new_duration(self):
        STATUS_DATA["burning"]["stacking"]["stacking_rule"] = "refresh"
        skill = self.target.create_personal_skill({"skill_id": "renew", "name": "renew", "rank": "C",
            "components": [component(event="global_turn_end", effects=[{
                "effect_type": "add_status", "effect_data": {"status_id": "burning"}}])]})
        status = self.apply(actor=self.target, source=skill, duration=1)
        self.end(1)
        self.assertEqual(status.duration, 3)
        self.assertEqual(self.target.hp, 80)

    def test_passive_and_stack_cleanup_are_owned_by_status(self):
        self.define(components=[{"component_id": "slow", "type": "passive", "target": "self",
                    "effects": [{"effect_type": "dice_bonus", "effect_data": {"effect_target": "dodge", "value": -2}}]}],
                    stacking={"stacking_rule": "stack", "stack_scope": "same_source", "max_stacks": 3})
        initial = self.target.dodge
        status = self.apply("test_status")
        self.assertEqual(self.target.dodge, initial - 2)
        self.apply("test_status")
        self.assertEqual(self.target.dodge, initial - 4)
        self.assertEqual(len(self.target.get_purifiable_modifiers()), 1)
        self.target.purify_modifiers(status)
        self.assertEqual(self.target.dodge, initial)
        self.assertEqual(self.target.modifiers, [])

    def test_passive_expiry_and_death_restore_attributes(self):
        self.define(duration=1, components=[{"component_id": "buff", "type": "passive",
            "effects": [{"effect_type": "attack_bonus", "effect_data": {"value": 5}}]}])
        initial = self.target.atk
        self.apply("test_status")
        self.assertEqual(self.target.atk, initial + 5)
        self.end(1)
        self.assertEqual(self.target.atk, initial)
        self.apply("test_status")
        self.target.die()
        self.assertEqual(self.target.atk, initial)

    def test_react_quota_shared_across_sources_components_and_reapplication(self):
        self.define(components=[component("react"), component("react", component_id="other")])
        first = self.apply("test_status", actor=self.a)
        second = self.apply("test_status", actor=self.b)
        decisions = ScriptedDecisionProvider(["1", "1", "1"])
        self.game.decision_provider = decisions
        DamageResolver().resolve(DamageEvent(self.a, self.target, 2, "magic"))
        self.assertEqual(len(decisions.requests), 1)
        self.assertEqual(self.target.hp, 87)
        self.target.remove_modifier(first)
        self.target.remove_modifier(second)
        self.apply("test_status")
        DamageResolver().resolve(DamageEvent(self.a, self.target, 2, "magic"))
        self.assertEqual(len(decisions.requests), 1)
        self.game.turn_manager.turn = 2
        DamageResolver().resolve(DamageEvent(self.a, self.target, 2, "magic"))
        self.assertEqual(len(decisions.requests), 2)

    def test_two_reactive_statuses_cannot_infinite_loop(self):
        self.define("first", [component("react")])
        self.define("second", [component("react")])
        self.apply("first")
        self.apply("second")
        decisions = ScriptedDecisionProvider(["1", "1"])
        self.game.decision_provider = decisions
        DamageResolver().resolve(DamageEvent(self.a, self.target, 2, "magic"))
        self.assertEqual(self.target.hp, 86)
        self.assertEqual(len(decisions.requests), 2)
        self.assertFalse(any(event.stopped for event in self.game.event_manager.history))

    def test_automatic_status_cycle_is_bounded_without_depth_cutoff(self):
        self.define(components=[component()])
        self.apply("test_status")
        DamageResolver().resolve(DamageEvent(self.a, self.target, 2, "magic"))
        self.assertEqual(self.target.hp, 87)
        self.assertFalse(any(event.stopped for event in self.game.event_manager.history))

    def test_purified_queued_status_does_not_execute_stale_candidate(self):
        self.define(components=[component(event="probe")])
        self.apply("test_status")
        self.target.create_personal_skill({"skill_id": "cleanse", "name": "cleanse", "rank": "C",
            "components": [component(event="probe", trigger={"event_type": "probe", "priority": 10},
                                     effects=[{"effect_type": "purify", "effect_data": {}}])]})
        self.game.event_manager.emit("probe")
        self.assertEqual(self.target.hp, 90)

    def test_live_instances_hold_definition_snapshot(self):
        self.apply()
        STATUS_DATA["burning"]["components"][0]["effects"][0]["effect_data"]["multiplier"] = 50
        self.end(1)
        self.assertEqual(self.target.hp, 80)

    def test_structured_state_is_json_and_separates_sources(self):
        self.apply(actor=self.a)
        self.apply(actor=self.b)
        state = character_state(self.target)
        json.dumps(state, allow_nan=False)
        self.assertEqual([s["source_name"] for s in state["status_instances"]], ["A", "B"])
        self.assertEqual([s["duration"] for s in state["status_instances"]], [3, 3])

    def test_application_reports_include_each_instance(self):
        self.apply(actor=self.a)
        self.apply(actor=self.b)
        records = [r for r in self.game.rule_reports.history if r["kind"] == "modifier_applied"]
        self.assertEqual([r["data"]["target"]["status_instance"]["source_name"] for r in records], ["A", "B"])

    def test_old_value_unknown_status_and_inner_duration_are_rejected(self):
        for data in ({"value": "burning"}, {"status_id": "missing"}, {"status_id": "burning", "duration": 2}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                validate_effect_definition({"effect_type": "add_status", "effect_data": data})
            with self.subTest(runtime=data), self.assertRaises(ValueError):
                create_modifier({"effect_type": "add_status", "effect_data": data}, self.target)

    def test_status_schema_rejects_unsupported_or_mistyped_rules(self):
        invalid = [
            {"duration": 0}, {"duration_timing": "battle_turn_end"}, {"surprise": True},
            {"components": [component("active")]},
            {"components": [component(limit={"maximum": 99})]},
            {"components": [component(trigger={"event_type": "probe", "timing": "wrong"})]},
            {"components": [{"component_id": "passive", "type": "passive", "effects": [damage()]}]},
        ]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises((ValueError, TypeError)):
                validate_status_definition({**deepcopy(STATUS_DATA["burning"]), **changes})


class StatusEditorProjectTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "catalog.json"
        self.project = CatalogProject(self.path)

    def test_status_template_save_reopen_export_copy_and_activate(self):
        definition = new_definition("状态", "my_burning")
        self.project.put("status", "my_burning", definition)
        self.project.save()
        loaded = CatalogProject(self.path)
        self.assertEqual(loaded.data["status"]["my_burning"], definition)
        exported = {"category": "status", "entry_id": "my_burning", "definition": definition}
        self.assertEqual(parse_entry(json.dumps(exported)), exported)
        copied = copy_definition("status", "other_burning", definition)
        self.assertEqual(copied["status_id"], "other_burning")
        with loaded.activate():
            self.assertIn("my_burning", validate_status_catalog())
        self.assertNotIn("my_burning", STATUS_DATA)

    def test_edited_stack_formula_round_trip_and_actual_damage(self):
        definition = new_definition("状态", "my_burning")
        definition["stacking"]["max_stacks"] = 4
        definition["components"][0]["effects"][0]["effect_data"].update(multiplier=7, flat=2)
        self.project.put("status", "my_burning", definition)
        self.project.save()
        loaded = CatalogProject(self.path)
        with contextlib.redirect_stdout(io.StringIO()), loaded.activate():
            a, b = [Master(n, 3, 3, 3, 3, 3, "C", 3) for n in ("A", "B")]
            location = Location("A")
            a.position = b.position = location
            game = GameManager([a, b], location)
            game.start_game()
            source = Skill("fire", "C", definitions=[], skill_id="fire")
            for _ in range(3):
                apply_skill_effect({"effect_type": "add_status", "effect_data": {"status_id": "my_burning"}},
                                   b, source, actor=a)
            game.turn_manager.turn = 1
            game.resolve_turn_end_event(1)
            self.assertEqual(b.hp, 67)  # 3 * 7 + 2
        self.assertNotIn("my_burning", STATUS_DATA)

    def test_referenced_status_cannot_be_deleted_and_failed_edit_rolls_back(self):
        self.project.put("status", "my_status", new_definition("状态", "my_status"))
        skill = new_definition("固有技能", "my_skill")
        skill["components"][0]["effects"] = [{"effect_type": "add_status", "effect_data": {"status_id": "my_status"}}]
        self.project.put("personal_skill", "my_skill", skill)
        previous = deepcopy(self.project.data)
        with self.assertRaises(ValueError):
            self.project.remove_override("status", "my_status")
        self.assertEqual(self.project.data, previous)
        self.assertNotIn("my_status", STATUS_DATA)

    def test_status_to_status_reference_is_checked_without_recursively_expanding_cycles(self):
        definition = new_definition("状态", "my_status")
        definition["components"][0]["effects"] = [{"effect_type": "add_status", "effect_data": {"status_id": "my_status"}}]
        self.project.put("status", "my_status", definition)
        broken = deepcopy(definition)
        broken["components"][0]["effects"][0]["effect_data"]["status_id"] = "missing"
        with self.assertRaises(ValueError):
            self.project.put("status", "my_status", broken)
        self.assertEqual(self.project.data["status"]["my_status"], definition)

    def test_version_one_is_rejected_without_automatic_migration(self):
        old = empty_project()
        old["format_version"] = 1
        self.path.write_text(json.dumps(old), encoding="utf-8")
        original = self.path.read_bytes()
        with self.assertRaises(ValueError):
            CatalogProject(self.path)
        self.assertEqual(self.path.read_bytes(), original)

    def test_builtin_status_override_is_restored_after_exception(self):
        original = deepcopy(STATUS_DATA)
        changed = deepcopy(STATUS_DATA["burning"])
        changed["duration"] = 7
        self.project.put("status", "burning", changed)
        with self.assertRaises(RuntimeError), self.project.activate():
            self.assertEqual(STATUS_DATA["burning"]["duration"], 7)
            raise RuntimeError("test")
        self.assertEqual(STATUS_DATA, original)
        self.project.remove_override("status", "burning")
        self.assertEqual(self.project.effective()["status"]["burning"], original["burning"])
