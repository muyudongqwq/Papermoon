import unittest

from game.character.servants import Servant
from game.game_manager import GameManager
from game.map.map import Location
from core.terminal_commands import TerminalCommandHandler
from game.skill.skill_runtime import SkillUnavailableError
from game.turn.damage import DamageEvent, DamageResolver


def create_servant(name="Caster"):
    return Servant(name, 3, 3, 3, 5, 3, "Caster", "A")


def resource_skill_definition():
    return {
        "skill_id": "battle_will_system",
        "name": "战意系统",
        "rank": "C",
        "components": [
            {
                "component_id": "resource",
                "type": "passive",
                "effects": [{
                    "effect_type": "add_resource",
                    "effect_data": {
                        "resource_id": "battle_will",
                        "name": "战意",
                        "initial_value": 1,
                        "minimum": 0,
                        "maximum": 5,
                        "gain_rules": [
                            {
                                "trigger_event": "damage_received",
                                "condition": {"damage_at_least": 1},
                                "operation": "add",
                                "value": 1,
                            },
                            {
                                "trigger_event": "damage_received",
                                "condition": {"damage_at_least": 10},
                                "operation": "add",
                                "value": 2,
                            },
                        ],
                    },
                }],
            },
            {
                "component_id": "spend",
                "type": "active",
                "target": "self",
                "cost": [{"resource": "battle_will", "value": 2}],
                "effects": [{
                    "effect_type": "gain_resource",
                    "effect_data": {
                        "resource_id": "battle_will",
                        "value": 1,
                    },
                }],
            },
        ],
    }


class ResourceRuntimeTests(unittest.TestCase):
    def test_builtin_and_custom_resource_changes_emit_events(self):
        actor = create_servant()
        game = GameManager([actor], Location("Grail"))
        actor.game_manager = game
        actor.add_resource({
            "resource_id": "charges",
            "name": "充能",
            "initial_value": 1,
            "maximum": 5,
        })
        actor.mp -= 10

        actor.recover_resource("mp", 4)
        actor.gain_resource("charges", 2)

        events = game.event_manager.history
        event_types = [event.event_type for event in events]
        self.assertEqual(event_types.count("resource_changed"), 2)
        self.assertIn("resource_recovered", event_types)
        self.assertIn("resource_gained", event_types)
        custom = next(
            event
            for event in events
            if event.event_type == "resource_gained"
        )
        self.assertEqual(custom.payload["old_value"], 1)
        self.assertEqual(custom.payload["new_value"], 3)
        self.assertEqual(custom.payload["change"], 2)

    def test_unified_recovery_returns_actual_amount_and_keeps_wrappers(self):
        actor = create_servant()
        actor.hp = actor.hpmax - 5
        actor.mp = actor.mpmax - 4

        self.assertEqual(actor.recover_resource("hp", 20), 5)
        self.assertEqual(actor.recover_mp(20), 4)
        actor.hp -= 3
        self.assertEqual(actor.heal(2.9), 2)

    def test_dead_character_cannot_recover_hp(self):
        actor = create_servant()
        actor.die()

        self.assertEqual(actor.recover_resource("hp", 30), 0)
        self.assertEqual(actor.hp, 0)
        self.assertTrue(actor.has_status("dead"))

    def test_custom_resource_recovery_requires_and_obeys_maximum(self):
        actor = create_servant()
        actor.add_resource({
            "resource_id": "charges",
            "name": "充能",
            "initial_value": 2,
            "maximum": 5,
        })
        actor.add_resource({
            "resource_id": "unbounded",
            "name": "无限资源",
            "initial_value": 2,
        })

        self.assertEqual(actor.recover_resource("charges", 10), 3)
        self.assertEqual(actor.get_resource_value("charges"), 5)
        with self.assertRaises(ValueError):
            actor.recover_resource("unbounded", 1)

    def test_recover_resource_skill_supports_maximum_percentage(self):
        actor = create_servant()
        actor.hp = 1
        actor.create_personal_skill({
            "skill_id": "percentage_heal",
            "name": "比例治疗",
            "rank": "C",
            "components": [{
                "component_id": "active",
                "type": "active",
                "target": "self",
                "effects": [{
                    "effect_type": "recover_resource",
                    "effect_data": {
                        "resource_id": "hp",
                        "calculation": "maximum_percentage",
                        "value": 0.25,
                    },
                }],
            }],
        })

        result = actor.resolve_skill_component("percentage_heal", "active")

        self.assertEqual(result["results"], [int(actor.hpmax * 0.25)])
        self.assertEqual(actor.hp, 1 + int(actor.hpmax * 0.25))

    def test_recover_resource_skill_can_use_actual_mp_cost(self):
        actor = create_servant()
        actor.hp -= 20
        actor.create_personal_skill({
            "skill_id": "mana_heal",
            "name": "魔力治疗",
            "rank": "C",
            "components": [{
                "component_id": "active",
                "type": "active",
                "target": "self",
                "cost": [{"resource": "mp", "value": 7}],
                "effects": [{
                    "effect_type": "recover_resource",
                    "effect_data": {
                        "resource_id": "hp",
                        "value_source": "actual_mp_cost",
                    },
                }],
            }],
        })
        starting_hp = actor.hp
        starting_mp = actor.mp

        result = actor.resolve_skill_component("mana_heal", "active")

        self.assertEqual(result["results"], [7])
        self.assertEqual(actor.hp, starting_hp + 7)
        self.assertEqual(actor.mp, starting_mp - 7)

    def test_passive_add_resource_and_duplicate_source_are_idempotent(self):
        actor = create_servant()
        skill = actor.create_personal_skill(resource_skill_definition())
        resource = actor.get_resource("battle_will")
        actor.gain_resource("battle_will", 2)

        duplicate = actor.add_resource(
            resource.definition_signature(),
            source=skill,
            source_type="personal_skill",
            source_id="battle_will_system:C",
        )

        self.assertIs(duplicate, resource)
        self.assertEqual(actor.get_resource_value("battle_will"), 3)

    def test_different_definition_or_source_cannot_redefine_resource(self):
        actor = create_servant()
        actor.add_resource({
            "resource_id": "marks",
            "name": "刻印",
            "initial_value": 1,
        }, source_id="first")

        with self.assertRaises(ValueError):
            actor.add_resource({
                "resource_id": "marks",
                "name": "其他刻印",
                "initial_value": 1,
            }, source_id="second")

    def test_resource_operations_clamp_and_truncate_toward_zero(self):
        actor = create_servant()
        actor.add_resource({
            "resource_id": "marks",
            "name": "刻印",
            "initial_value": 5,
            "minimum": -10,
            "maximum": 8,
        })

        actor.modify_resource("marks", "multiply", 0.5)
        self.assertEqual(actor.get_resource_value("marks"), 2)
        actor.modify_resource("marks", "set", -5)
        actor.modify_resource("marks", "multiply", 0.5)
        self.assertEqual(actor.get_resource_value("marks"), -2)
        actor.modify_resource("marks", "set", 99)
        self.assertEqual(actor.get_resource_value("marks"), 8)

    def test_resource_payment_cannot_cross_configured_minimum(self):
        actor = create_servant()
        actor.add_resource({
            "resource_id": "resolve",
            "name": "决意",
            "initial_value": 2,
            "minimum": 1,
        })

        self.assertFalse(actor.can_pay_resource("resolve", 2))
        self.assertTrue(actor.pay_resource("resolve", 1))
        self.assertEqual(actor.get_resource_value("resolve"), 1)

    def test_same_event_resolves_all_matching_gain_rules_in_order(self):
        actor = create_servant()
        actor.create_personal_skill(resource_skill_definition())

        results = actor.trigger_resource_event(
            "damage_received",
            damage=12,
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(actor.get_resource_value("battle_will"), 4)

    def test_damage_resolver_dispatches_resource_events(self):
        attacker = create_servant("Attacker")
        target = create_servant("Target")
        target.create_personal_skill(resource_skill_definition())

        DamageResolver().resolve(DamageEvent(
            attacker,
            target,
            10,
            "physical",
        ))

        self.assertEqual(target.get_resource_value("battle_will"), 4)

    def test_custom_resource_can_pay_active_skill_cost(self):
        actor = create_servant()
        actor.create_personal_skill(resource_skill_definition())
        actor.gain_resource("battle_will", 2)

        result = actor.resolve_skill_component(
            "battle_will_system",
            "spend",
        )

        self.assertEqual(result["paid_costs"], {"battle_will": 2})
        self.assertEqual(actor.get_resource_value("battle_will"), 2)

    def test_resource_effect_is_unavailable_before_resource_exists(self):
        actor = create_servant()
        actor.create_personal_skill({
            "skill_id": "orphan_gain",
            "name": "无容器资源获得",
            "rank": "C",
            "components": [{
                "component_id": "gain",
                "type": "active",
                "target": "self",
                "effects": [{
                    "effect_type": "gain_resource",
                    "effect_data": {
                        "resource_id": "missing_resource",
                        "value": 1,
                    },
                }],
            }],
        })

        with self.assertRaises(SkillUnavailableError):
            actor.resolve_skill_component("orphan_gain", "gain")

    def test_terminal_status_displays_custom_resource(self):
        actor = create_servant()
        actor.create_personal_skill(resource_skill_definition())
        output = []
        handler = TerminalCommandHandler(None, output_func=output.append)

        handler.show_character(actor)

        self.assertIn("特殊资源 战意 1/5", output[0])

    def test_dead_character_keeps_resource_but_stops_gaining_it(self):
        actor = create_servant()
        actor.create_personal_skill(resource_skill_definition())
        actor.die()

        results = actor.trigger_resource_event(
            "damage_received",
            damage=20,
        )

        self.assertEqual(results, [])
        self.assertTrue(actor.has_resource("battle_will"))
        self.assertEqual(actor.get_resource_value("battle_will"), 1)


if __name__ == "__main__":
    unittest.main()
