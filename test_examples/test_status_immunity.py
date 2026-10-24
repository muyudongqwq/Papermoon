"""Debuff rejection before application, tags, charge lifetime and attribution."""

from copy import deepcopy
import contextlib
import io
import unittest
from unittest.mock import patch

from game.character.masters import Master
from game.game.game_manager import GameManager
from game.map.map import Location
from game.skill.skill import Skill
from game.skill.skill_runtime import apply_skill_effect
from game.skill.effect_validation import validate_effect_definition
from game.status.data import STATUS_DATA, marker
from game.status.registry import validate_status_definition
from game.status.runtime import status_view


class StatusImmunityTests(unittest.TestCase):
    def setUp(self):
        catalog = patch.dict(STATUS_DATA, deepcopy(STATUS_DATA), clear=True)
        catalog.start()
        self.addCleanup(catalog.stop)
        capture = contextlib.redirect_stdout(io.StringIO())
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)
        self.a, self.b, self.target = [Master(name, 3, 3, 3, 3, 3, "C", 3) for name in ("A", "B", "Target")]
        location = Location("A")
        for actor in (self.a, self.b, self.target):
            actor.position = location
        self.game = GameManager([self.a, self.b, self.target], location)
        self.game.start_game()
        self.game.turn_manager.turn = 1
        self.skill = Skill("Test", "C", definitions=[], skill_id="test")
        for key, tags, polarity in (("poison", ["poison"], "debuff"), ("fear", ["mental"], "debuff"),
                                    ("slow", ["movement"], "debuff"), ("good", ["poison"], "buff"),
                                    ("neutral_tag", ["poison"], "neutral")):
            STATUS_DATA[key] = {**marker(key, key, polarity=polarity), "tags": tags}

    def apply(self, key, actor=None, **overrides):
        return apply_skill_effect({"effect_type": "add_status", "effect_data": {"status_id": key}, **overrides},
                                  self.target, self.skill, actor=actor or self.a)

    def guard(self, uses=3, duration=3, tags=None, actor=None):
        definition = STATUS_DATA["debuff_immunity"]
        definition["duration"] = duration
        if uses is None:
            definition.pop("consumption", None)
        else:
            definition["consumption"] = {"event": "status_blocked", "uses": uses}
        data = definition["components"][0]["effects"][0]["effect_data"]
        data.clear()
        if tags is not None:
            data["tags"] = tags
        return self.apply("debuff_immunity", actor).modifier

    def test_only_new_debuffs_are_blocked_existing_statuses_are_untouched(self):
        old = self.apply("poison").modifier
        guard = self.guard()
        self.assertFalse(self.apply("fear"))
        self.assertIn(old, self.target.modifiers)
        self.assertTrue(self.target.has_status("poison"))
        self.assertFalse(self.target.has_status("fear"))
        self.assertTrue(self.apply("good"))
        self.assertTrue(self.apply("neutral_tag"))
        self.assertEqual(guard.remaining_uses, 2)

    def test_tag_any_matching_omitted_and_empty_lists(self):
        guard = self.guard(tags=["poison", "mental"])
        self.assertTrue(self.apply("slow"))
        self.assertEqual(guard.remaining_uses, 3)
        self.assertFalse(self.apply("poison"))
        self.assertFalse(self.apply("fear"))
        self.assertEqual(guard.remaining_uses, 1)
        self.target.remove_modifier(guard)
        for tags in (None, []):
            guard = self.guard(tags=tags)
            self.assertFalse(self.apply("burning"))  # Untagged debuff also matches all.
            self.target.remove_modifier(guard)

    def test_effective_polarity_overrides_catalog_and_actor_tags_are_ignored(self):
        guard = self.guard(tags=["poison"])
        self.a.tags = {"poison"}
        self.assertTrue(self.apply("slow"))
        self.assertTrue(self.apply("poison", polarity="buff"))
        self.assertFalse(self.apply("good", polarity="debuff"))
        self.assertEqual(guard.remaining_uses, 2)

    def test_all_charges_can_be_used_in_one_turn_and_last_block_removes_parent(self):
        guard = self.guard(uses=2)
        self.assertFalse(self.apply("poison"))
        self.assertFalse(self.apply("fear"))
        self.assertEqual(guard.remaining_uses, 0)
        self.assertNotIn(guard, self.target.modifiers)
        self.assertFalse(any(m.effect_type == "status_immunity" for m in self.target.modifiers))
        self.assertTrue(self.apply("slow"))

    def test_duration_expires_even_with_unused_charges_and_unlimited_is_supported(self):
        guard = self.guard(uses=4, duration=1)
        self.game.resolve_turn_end_event(1)
        self.assertNotIn(guard, self.target.modifiers)
        self.assertEqual(guard.remaining_uses, 4)
        self.assertTrue(self.apply("poison"))
        guard = self.guard(uses=None, duration=None)
        for _ in range(5):
            self.assertFalse(self.apply("fear"))
        self.assertIsNone(guard.remaining_uses)
        self.game.resolve_turn_end_event(2)
        self.assertIn(guard, self.target.modifiers)

    def test_blocked_status_never_applies_passive_effects_or_emits_added_events(self):
        STATUS_DATA["fear"]["components"] = [{"component_id": "penalty", "type": "passive", "effects": [
            {"effect_type": "attack_bonus", "effect_data": {"value": -30}}]}]
        self.guard()
        before = self.target.atk_bonus
        start = len(self.game.rule_reports.history)
        result = self.apply("fear")
        self.assertFalse(result)
        self.assertFalse(result.modifier.applied)
        self.assertEqual(result.modifier.status_runtime.children, [])
        self.assertEqual(self.target.atk_bonus, before)
        records = self.game.rule_reports.history[start:]
        self.assertFalse(any(r["kind"] == "status_added" for r in records))
        blocked = next(r for r in records if r["kind"] == "status_blocked")
        self.assertEqual(blocked["data"]["target"]["status_id"], "fear")

    def test_one_attempt_consumes_only_one_pool_and_sources_remain_separate(self):
        first = self.guard(uses=1, actor=self.a)
        second = self.guard(uses=2, actor=self.b)
        self.assertFalse(self.apply("poison"))
        self.assertNotIn(first, self.target.modifiers)
        self.assertEqual(second.remaining_uses, 2)
        self.assertFalse(self.apply("fear"))
        self.assertEqual(second.remaining_uses, 1)

    def test_refresh_and_stack_attempts_are_blocked_without_changing_existing_instance(self):
        original = self.apply("burning").modifier
        duration, stacks = original.duration, original.stack_count
        guard = self.guard()
        self.assertFalse(self.apply("burning"))
        self.assertEqual((original.duration, original.stack_count), (duration, stacks))
        self.assertEqual(guard.remaining_uses, 2)

    def test_reapply_immunity_refreshes_counter_using_existing_use_refresh_rules(self):
        guard = self.guard()
        self.apply("poison")
        self.assertEqual(guard.remaining_uses, 2)
        self.assertIs(self.guard(uses=5), guard)
        self.assertEqual(guard.remaining_uses, 5)
        self.assertEqual(status_view(guard)["remaining_uses"], 5)
        STATUS_DATA["debuff_immunity"]["consumption"]["use_refresh_rule"] = "unchanged"
        self.apply("fear")
        self.apply("debuff_immunity")
        self.assertEqual(guard.remaining_uses, 4)

    def test_expired_counter_is_detached_before_synchronous_removal_callbacks(self):
        self.guard(uses=1)
        removed = self.target.create_personal_skill({"skill_id": "on_remove", "name": "On remove", "rank": "C", "components": [{
            "component_id": "apply", "type": "trigger", "target": "self",
            "trigger": {"event_type": "status_removed"}, "condition": {"event_target_is_self": True},
            "effects": [{"effect_type": "add_status", "effect_data": {"status_id": "slow"}}]}]})
        self.assertFalse(self.apply("poison"))
        self.assertTrue(self.target.has_status("slow"))
        self.assertFalse(self.target.has_status("debuff_immunity"))

    def test_immunity_blocks_reentrant_debuff_while_its_passives_are_installing(self):
        self.target.create_personal_skill({
            "skill_id": "reentrant_debuff",
            "name": "Reentrant debuff",
            "rank": "C",
            "components": [{
                "component_id": "apply",
                "type": "trigger",
                "target": "self",
                "trigger": {"event_type": "modifier_applied"},
                "condition": {"event_target_is_self": True},
                "limit": {"scope": "global_turn", "maximum": 1},
                "effects": [{
                    "effect_type": "add_status",
                    "effect_data": {"status_id": "poison"},
                }],
            }],
        })
        guard = self.guard(uses=3)
        self.assertFalse(self.target.has_status("poison"))
        self.assertEqual(guard.remaining_uses, 2)

    def test_single_use_immunity_can_be_consumed_during_install_without_orphan_children(self):
        self.target.create_personal_skill({
            "skill_id": "consume_new_guard",
            "name": "Consume new guard",
            "rank": "C",
            "components": [{
                "component_id": "apply",
                "type": "trigger",
                "target": "self",
                "trigger": {"event_type": "modifier_applied"},
                "condition": {"event_target_is_self": True},
                "limit": {"scope": "global_turn", "maximum": 1},
                "effects": [{
                    "effect_type": "add_status",
                    "effect_data": {"status_id": "poison"},
                }],
            }],
        })
        guard = self.guard(uses=1)
        self.assertFalse(self.target.has_status("poison"))
        self.assertFalse(self.target.has_status("debuff_immunity"))
        self.assertNotIn(guard, self.target.modifiers)
        self.assertFalse(any(
            modifier.effect_type == "status_immunity"
            for modifier in self.target.modifiers
        ))

    def test_schema_rejects_bad_tags_counter_and_invalid_application_overrides(self):
        for tags in ("poison", [1], [""], [" "]):
            with self.subTest(tags=tags), self.assertRaises((TypeError, ValueError)):
                validate_status_definition({**marker("bad", "bad"), "tags": tags})
            with self.assertRaises((TypeError, ValueError)):
                validate_effect_definition({"effect_type": "status_immunity", "effect_data": {"tags": tags}})
        for consumption in ({"event": "status_blocked", "uses": 0}, {"event": "attack_committed", "uses": 1},
                            {"event": "status_blocked", "mode": "optional"}, {"event": "status_blocked", "remove_when_empty": False}):
            with self.subTest(consumption=consumption):
                with self.assertRaises((TypeError, ValueError)):
                    validate_status_definition({**marker("bad", "bad"), "consumption": consumption})
                with self.assertRaises((TypeError, ValueError)):
                    self.apply("poison", consumption=consumption)

    def test_direct_modifier_immunity_can_also_use_existing_duration_and_charges(self):
        result = apply_skill_effect({"effect_type": "status_immunity", "effect_data": {"tags": ["mental"]},
                                    "consumption": {"event": "status_blocked", "uses": 1}, "duration": 2},
                                   self.target, self.skill, actor=self.a)
        self.assertTrue(result)
        self.assertFalse(self.apply("fear"))
        self.assertNotIn(result.modifier, self.target.modifiers)


if __name__ == "__main__":
    unittest.main()
