import unittest

from game.action.action_list import ActionContext, ActionListBuilder
from game.character.masters import Master
from game.skill.component_runtime import (
    component_use_count,
    reset_component_runtime,
)
from game.skill.skill_runtime import SkillUnavailableError, validate_skill_components
from game.turn.battle import BattleManager


def make_master(name="Actor"):
    return Master(name, 3, 3, 3, 3, 3, "C", 3)


def make_skill(actor, *, usage_limit=None, cooldown=None, cost=None):
    component = {
        "component_id": "limited_heal",
        "type": "active",
        "available_phases": ["AP1", "AP2"],
        "target": "self",
        "cost": list(cost or []),
        "effects": [{
            "effect_type": "recover_resource",
            "effect_data": {"resource_id": "hp", "value": 1},
        }],
    }
    if usage_limit is not None:
        component["usage_limit"] = usage_limit
    if cooldown is not None:
        component["cooldown"] = cooldown
    skill = actor.create_personal_skill({
        "skill_id": "limited_heal",
        "name": "限次治疗",
        "rank": "C",
        "components": [component],
    })
    return skill, component


class ComponentUsageTests(unittest.TestCase):
    def setUp(self):
        self.actor = make_master()
        self.actor.hp -= 20
        self.actor.current_global_turn = 1

    def resolve(self, turn_number=1):
        return self.actor.resolve_skill_component(
            "limited_heal",
            "limited_heal",
            turn_number=turn_number,
        )

    def test_global_turn_limit_resets_on_next_turn(self):
        skill, component = make_skill(
            self.actor,
            usage_limit={"scope": "global_turn", "maximum": 1},
        )

        self.resolve(1)
        with self.assertRaisesRegex(SkillUnavailableError, "usage_exhausted"):
            self.resolve(1)
        self.resolve(2)

        self.assertEqual(component_use_count(
            self.actor, skill, component, turn_number=1,
        ), 1)
        self.assertEqual(component_use_count(
            self.actor, skill, component, turn_number=2,
        ), 1)

    def test_battle_limit_is_per_battle_instance(self):
        other = make_master("Other")
        first_battle = BattleManager([self.actor, other])
        second_battle = BattleManager([self.actor, other])
        skill, component = make_skill(
            self.actor,
            usage_limit={"scope": "battle", "maximum": 1},
        )
        self.actor.current_battle = first_battle

        self.resolve(1)
        with self.assertRaises(SkillUnavailableError):
            self.resolve(2)
        self.actor.current_battle = second_battle
        self.resolve(2)

        self.assertEqual(component_use_count(
            self.actor, skill, component, battle=first_battle,
        ), 1)
        self.assertEqual(component_use_count(
            self.actor, skill, component, battle=second_battle,
        ), 1)

    def test_battle_limit_is_unavailable_outside_formal_battle(self):
        make_skill(
            self.actor,
            usage_limit={"scope": "battle", "maximum": 1},
        )

        with self.assertRaisesRegex(
            SkillUnavailableError,
            "battle_usage_requires_battle",
        ):
            self.resolve(1)

    def test_game_limit_never_resets_automatically(self):
        make_skill(
            self.actor,
            usage_limit={"scope": "game", "maximum": 2},
        )

        self.resolve(1)
        self.resolve(2)
        with self.assertRaisesRegex(SkillUnavailableError, "usage_exhausted"):
            self.resolve(100)

    def test_one_turn_cooldown_blocks_next_turn(self):
        make_skill(
            self.actor,
            cooldown={"turns": 1, "unit": "global_turn"},
        )

        self.resolve(1)
        with self.assertRaisesRegex(SkillUnavailableError, "on_cooldown"):
            self.resolve(1)
        with self.assertRaisesRegex(SkillUnavailableError, "on_cooldown"):
            self.resolve(2)
        self.resolve(3)

    def test_failed_payment_does_not_consume_usage_or_cooldown(self):
        skill, component = make_skill(
            self.actor,
            usage_limit={"scope": "game", "maximum": 1},
            cooldown={"turns": 2},
            cost=[{"resource": "mp", "value": 999}],
        )
        self.actor.mp = 0

        with self.assertRaisesRegex(SkillUnavailableError, "mp不足"):
            self.resolve(1)
        self.assertEqual(component_use_count(
            self.actor, skill, component,
        ), 0)
        self.assertNotIn(component["component_id"], skill.component_runtime_states)

        self.actor.mp = 999
        self.resolve(1)
        self.assertEqual(component_use_count(
            self.actor, skill, component,
        ), 1)

    def test_action_list_reports_exhausted_usage(self):
        make_skill(
            self.actor,
            usage_limit={"scope": "global_turn", "maximum": 1},
        )
        self.resolve(1)

        entries = ActionListBuilder().get_action_entries(ActionContext(
            actor=self.actor,
            phase="AP1",
            turn_number=1,
            characters=[self.actor],
        ))
        entry = next(
            item for item in entries
            if item.action_id == "skill:limited_heal:limited_heal"
        )

        self.assertFalse(entry.available)
        self.assertIn("global_turn_usage_exhausted", entry.unavailable_reasons)

    def test_reset_hook_can_restore_usage_and_cooldown(self):
        skill, component = make_skill(
            self.actor,
            usage_limit={"scope": "game", "maximum": 1},
            cooldown={"turns": 5},
        )
        self.resolve(1)

        self.assertTrue(reset_component_runtime(
            skill,
            component["component_id"],
            usage_scope="game",
            reset_cooldown=True,
        ))
        self.resolve(1)

    def test_validation_rejects_lifecycle_on_non_active_component(self):
        component = {
            "component_id": "bad_limit",
            "type": "passive",
            "usage_limit": {"scope": "game", "maximum": 1},
            "effects": [{
                "effect_type": "recover_resource",
                "effect_data": {"resource_id": "hp", "value": 1},
            }],
        }
        with self.assertRaisesRegex(ValueError, "只能用于active"):
            validate_skill_components([component])

    def test_validation_rejects_unknown_scope_and_zero_cooldown(self):
        component = {
            "component_id": "bad_limit",
            "type": "active",
            "usage_limit": {"scope": "day", "maximum": 1},
            "cooldown": {"turns": 0},
            "effects": [{
                "effect_type": "recover_resource",
                "effect_data": {"resource_id": "hp", "value": 1},
            }],
        }
        with self.assertRaises(ValueError):
            validate_skill_components([component])


if __name__ == "__main__":
    unittest.main()
