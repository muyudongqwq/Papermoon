import unittest

from game.character.masters import Master
from game.game.game_manager import GameManager
from game.map.map import Location
from game.skill.event_runtime import GameEvent
from game.turn.damage import DamageEvent, DamageResolver
from game.turn.decision import ScriptedDecisionProvider


def make_master(name):
    return Master(name, 3, 3, 3, 3, 3, "C", 3)


def make_skill(skill_id, component):
    return {
        "skill_id": skill_id,
        "name": skill_id,
        "rank": "C",
        "components": [component],
    }


class EventRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.location = Location("A", is_building=True)
        self.attacker = make_master("Attacker")
        self.target = make_master("Target")
        self.attacker.position = self.location
        self.target.position = self.location
        self.game = GameManager(
            [self.attacker, self.target],
            self.location,
        )
        self.game.start_game()
        self.game.turn_manager.turn = 1

    def test_automatic_trigger_resolves_after_damage(self):
        self.target.create_personal_skill(make_skill(
            "recover_after_damage",
            {
                "component_id": "recover",
                "type": "trigger",
                "trigger": {
                    "event_type": "damage_received",
                    "timing": "after",
                    "priority": 0,
                },
                "condition": {"event_target_is_self": True},
                "target": "self",
                "effects": [{
                    "effect_type": "recover_resource",
                    "effect_data": {"resource_id": "hp", "value": 5},
                }],
            },
        ))

        start_hp = self.target.hp
        DamageResolver().resolve(DamageEvent(
            self.attacker,
            self.target,
            20,
            "physical",
        ))

        self.assertEqual(self.target.hp, start_hp - 15)
        self.assertEqual(
            self.game.event_manager.history[-1].event_type,
            "damage_dealt",
        )

    def test_react_modifies_damage_and_is_once_per_target_per_turn(self):
        self.target.create_personal_skill(make_skill(
            "damage_reaction",
            {
                "component_id": "reduce",
                "type": "react",
                "trigger": {
                    "event_type": "before_damage",
                    "timing": "before",
                    "priority": 10,
                },
                "condition": {"event_target_is_self": True},
                "target": "event_target",
                "cost": [],
                "effects": [{
                    "effect_type": "modify_event_value",
                    "effect_data": {
                        "calculation": "add",
                        "value": -10,
                        "minimum": 0,
                    },
                }],
            },
        ))
        decisions = ScriptedDecisionProvider(["1"])
        start_hp = self.target.hp

        DamageResolver().resolve(
            DamageEvent(self.attacker, self.target, 20, "physical"),
            decision_provider=decisions,
        )
        DamageResolver().resolve(
            DamageEvent(self.attacker, self.target, 20, "physical"),
            decision_provider=decisions,
        )

        self.assertEqual(self.target.hp, start_hp - 30)
        self.assertEqual(len(decisions.requests), 1)

    def test_priority_order_and_react_rotation(self):
        applied = []

        def record(candidate, event, _provider):
            applied.append(candidate.skill.skill_id)
            self.game.event_manager._event_uses.add(
                (event.event_id, *candidate.key)
            )
            self.game.event_manager._record_usage(
                candidate,
                event,
                self.game.event_manager._usage_targets(candidate, event),
            )
            return {}

        for owner, skill_id, priority in (
            (self.target, "low", 0),
            (self.attacker, "high", 10),
        ):
            owner.create_personal_skill(make_skill(
                skill_id,
                {
                    "component_id": "react",
                    "type": "react",
                    "trigger": {
                        "event_type": "test_event",
                        "priority": priority,
                    },
                    "target": "self",
                    "effects": [{
                        "effect_type": "recover_resource",
                        "effect_data": {"resource_id": "hp", "value": 0},
                    }],
                },
            ))

        original = self.game.event_manager._execute
        self.game.event_manager._execute = record
        try:
            self.game.event_manager.emit(
                "test_event",
                target=self.target,
                decision_provider=ScriptedDecisionProvider(["1", "1"]),
            )
        finally:
            self.game.event_manager._execute = original

        self.assertEqual(applied, ["high", "low"])

    def test_change_damage_type_recalculates_type_dependent_defenses(self):
        self.target.magic_resistance = 0.5
        self.target.create_personal_skill(make_skill(
            "convert_to_magic",
            {
                "component_id": "convert",
                "type": "trigger",
                "trigger": {
                    "event_type": "before_damage",
                    "timing": "before",
                },
                "condition": {"event_target_is_self": True},
                "target": "event_target",
                "effects": [{
                    "effect_type": "change_damage_type",
                    "effect_data": {"damage_type": "magic"},
                }],
            },
        ))
        event = DamageEvent(self.attacker, self.target, 20, "physical")

        damage = DamageResolver().resolve(event)

        self.assertEqual(event.damage_type, "magic")
        self.assertEqual(damage, 10)

    def test_type_change_replays_earlier_event_value_operations(self):
        self.target.magic_resistance = 0.5
        for skill_id, priority, effect in (
            (
                "halve_first",
                10,
                {
                    "effect_type": "modify_event_value",
                    "effect_data": {"calculation": "multiply", "value": 0.5},
                },
            ),
            (
                "convert_later",
                0,
                {
                    "effect_type": "change_damage_type",
                    "effect_data": {"damage_type": "magic"},
                },
            ),
        ):
            self.target.create_personal_skill(make_skill(
                skill_id,
                {
                    "component_id": skill_id,
                    "type": "trigger",
                    "trigger": {
                        "event_type": "before_damage",
                        "timing": "before",
                        "priority": priority,
                    },
                    "condition": {"event_target_is_self": True},
                    "target": "event_target",
                    "effects": [effect],
                },
            ))

        damage = DamageResolver().resolve(
            DamageEvent(self.attacker, self.target, 20, "physical")
        )

        # 新类型先经50%对魔力成为10，再重放先前的x0.5。
        self.assertEqual(damage, 5)

    def test_event_chain_depth_is_bounded(self):
        parent = None
        for depth in range(self.game.event_manager.MAX_CHAIN_DEPTH + 1):
            event = GameEvent("manual", parent=parent)
            if parent is not None:
                event.chain_id = parent.chain_id
                event.depth = parent.depth + 1
            parent = event
        stopped = self.game.event_manager.emit("manual", parent=parent)
        self.assertTrue(stopped.stopped)

    def test_until_triggered_expires_after_first_successful_execution(self):
        self.target.hp -= 30
        skill = self.target.create_personal_skill(make_skill(
            "one_shot_recovery",
            {
                "component_id": "recover_once",
                "type": "trigger",
                "trigger": {"event_type": "test_event"},
                "limit": {"scope": "until_triggered"},
                "target": "self",
                "effects": [{
                    "effect_type": "recover_resource",
                    "effect_data": {"resource_id": "hp", "value": 5},
                }],
            },
        ))

        first = self.game.event_manager.emit("test_event", target=self.target)
        self.game.turn_manager.turn += 1
        second = self.game.event_manager.emit("test_event", target=self.target)

        self.assertEqual(self.target.hp, self.target.hpmax - 25)
        self.assertEqual(len(first.records), 1)
        self.assertTrue(first.records[0]["component_expired"])
        self.assertEqual(second.records, [])
        self.assertFalse(skill.is_component_active("recover_once"))

    def test_declined_until_triggered_reaction_remains_available(self):
        self.target.hp -= 30
        skill = self.target.create_personal_skill(make_skill(
            "optional_one_shot",
            {
                "component_id": "optional_recover",
                "type": "react",
                "trigger": {"event_type": "test_event"},
                "limit": {"scope": "until_triggered"},
                "target": "self",
                "effects": [{
                    "effect_type": "recover_resource",
                    "effect_data": {"resource_id": "hp", "value": 5},
                }],
            },
        ))
        decisions = ScriptedDecisionProvider(["pass", "1"])

        declined = self.game.event_manager.emit(
            "test_event",
            target=self.target,
            decision_provider=decisions,
        )
        self.assertTrue(skill.is_component_active("optional_recover"))
        accepted = self.game.event_manager.emit(
            "test_event",
            target=self.target,
            decision_provider=decisions,
        )

        self.assertEqual(declined.records, [])
        self.assertEqual(len(accepted.records), 1)
        self.assertFalse(skill.is_component_active("optional_recover"))

    def test_next_battle_start_only_responds_to_owner_joining(self):
        self.target.hp -= 30
        skill = self.target.create_personal_skill(make_skill(
            "next_battle_boost",
            {
                "component_id": "on_join",
                "type": "trigger",
                "trigger": {"event_type": "battle_joined"},
                "limit": {"scope": "next_battle_start"},
                "target": "self",
                "effects": [{
                    "effect_type": "recover_resource",
                    "effect_data": {"resource_id": "hp", "value": 5},
                }],
            },
        ))

        other_joined = self.game.event_manager.emit(
            "battle_joined",
            actor=self.attacker,
            target=self.attacker,
        )
        owner_joined = self.game.event_manager.emit(
            "battle_joined",
            actor=self.target,
            target=self.target,
        )
        repeated = self.game.event_manager.emit(
            "battle_joined",
            actor=self.target,
            target=self.target,
        )

        self.assertEqual(other_joined.records, [])
        self.assertEqual(len(owner_joined.records), 1)
        self.assertEqual(repeated.records, [])
        self.assertFalse(skill.is_component_active("on_join"))


if __name__ == "__main__":
    unittest.main()
