import unittest

from game.action.action_list import ActionContext, ActionListBuilder
from game.character.masters import Master
from game.game_manager import GameManager
from game.map.map import Location
from game.skill.component_runtime import component_use_count
from game.skill.content_data import PERSONAL_SKILL_DATA
from game.skill.effect_validation import validate_effect_definition
from game.skill.skill_runtime import SkillUnavailableError, apply_skill_effect
from game.turn.battle import BattleManager


def master(name="Master"):
    return Master(name, 3, 3, 3, 5, 3, "C", 3)


def source_skill(actor, skill_id="source"):
    return actor.create_personal_skill({
        "skill_id": skill_id,
        "name": skill_id,
        "rank": "C",
        "components": [{
            "component_id": "passive",
            "type": "passive",
            "effects": [{
                "effect_type": "add_status",
                "effect_data": {"value": f"{skill_id}_loaded"},
            }],
        }],
    })


class CardEffectBridgeTests(unittest.TestCase):
    def test_restore_component_restores_usage_and_cooldown(self):
        actor = master()
        actor.current_global_turn = 1
        actor.hp -= 10
        limited = actor.create_personal_skill({
            "skill_id": "limited",
            "name": "限次技能",
            "rank": "C",
            "components": [{
                "component_id": "use",
                "type": "active",
                "available_phases": ["AP1"],
                "target": "self",
                "usage_limit": {"scope": "game", "maximum": 1},
                "cooldown": {"turns": 3},
                "effects": [{
                    "effect_type": "recover_resource",
                    "effect_data": {"resource_id": "hp", "value": 1},
                }],
            }],
        })
        actor.resolve_skill_component("limited", "use", turn_number=1)
        source = source_skill(actor)
        result = apply_skill_effect({
            "effect_type": "restore_component",
            "effect_data": {
                "usage_amount": "all",
                "cooldown_turns": "all",
                "skill_ids": ["limited"],
            },
        }, actor, source, actor=actor, turn_number=1)

        self.assertEqual(len(result["restored"]), 1)
        self.assertEqual(component_use_count(
            actor, limited, limited.definitions[0],
        ), 0)
        actor.resolve_skill_component("limited", "use", turn_number=1)

    def test_restore_component_rejects_other_target_by_default(self):
        actor = master("Actor")
        other = master("Other")
        source = source_skill(actor)
        with self.assertRaisesRegex(SkillUnavailableError, "只能作用于自身"):
            apply_skill_effect({
                "effect_type": "restore_component",
                "effect_data": {"usage_amount": "all"},
            }, other, source, actor=actor)

    def test_selectable_attribute_replaces_placeholder(self):
        actor = master()
        skill = actor.create_personal_skill({
            "skill_id": "choose_attribute",
            "name": "选择属性",
            "rank": "C",
            "components": [{
                "component_id": "boost",
                "type": "active",
                "available_phases": ["AP1"],
                "target": "selectable_attribute",
                "target_rules": {},
                "effects": [{
                    "effect_type": "attribute_bonus",
                    "modifier_id": "chosen_attribute_bonus",
                    "duration": 1,
                    "effect_data": {
                        "effect_target": "selected_attribute",
                        "value": 1,
                    },
                }],
            }],
        })
        entry = next(
            item for item in ActionListBuilder().get_available_actions(
                ActionContext(actor, "AP1", characters=[actor])
            )
            if item.skill is skill
        )
        magic = next(choice for choice in entry.valid_targets if choice.value == "magic")
        actor.resolve_skill_component(skill.skill_id, "boost", target=magic)

        modifier = next(
            modifier for modifier in actor.modifiers
            if modifier.modifier_id == "chosen_attribute_bonus"
        )
        self.assertEqual(modifier.effect_target, "magic")

    def test_permanent_content_cannot_be_removed_or_regained(self):
        actor = master()
        source = source_skill(actor)
        definition = {
            "skill_id": "catalog:test_grant",
            "name": "仓库技能",
            "rank": "C",
            "components": [{
                "component_id": "passive",
                "type": "passive",
                "effects": [{
                    "effect_type": "add_status",
                    "effect_data": {"value": "catalog_loaded"},
                }],
            }],
        }
        PERSONAL_SKILL_DATA["test_grant"] = definition
        try:
            apply_skill_effect({
                "effect_type": "add_content",
                "effect_data": {
                    "content_type": "personal_skill",
                    "content_id": "test_grant",
                },
            }, actor, source, actor=actor)
            with self.assertRaisesRegex(SkillUnavailableError, "不能再次失去"):
                apply_skill_effect({
                    "effect_type": "remove_content",
                    "effect_data": {
                        "content_type": "personal_skill",
                        "content_id": "test_grant",
                    },
                }, actor, source, actor=actor)
        finally:
            PERSONAL_SKILL_DATA.pop("test_grant", None)

    def test_permanent_removal_blocks_reacquisition(self):
        actor = master()
        source = source_skill(actor)
        actor.load_basic_magic("healing")
        apply_skill_effect({
            "effect_type": "remove_content",
            "effect_data": {
                "content_type": "basic_magic",
                "content_id": "healing",
            },
        }, actor, source, actor=actor)
        with self.assertRaisesRegex(SkillUnavailableError, "永久移除"):
            apply_skill_effect({
                "effect_type": "add_content",
                "effect_data": {
                    "content_type": "basic_magic",
                    "content_id": "healing",
                },
            }, actor, source, actor=actor)

    def test_basic_familiar_magic_has_two_ap_and_battle_components(self):
        actor = master()
        enemy = master("Enemy")
        location = Location("Workshop")
        actor.position = enemy.position = location
        game = GameManager([actor, enemy], location)
        game.start_game()
        magic = actor.load_basic_magic("familiar")
        non_battle, battle = magic.definitions
        self.assertEqual(non_battle["available_phases"], ["AP1"])
        self.assertIn(
            {"resource": "action_point", "value": 2},
            non_battle["cost"],
        )
        self.assertEqual(battle["available_phases"], ["attack_phase"])
        self.assertIn(
            {"resource": "attack_phase_count", "value": 1},
            battle["cost"],
        )

        actor.action_point = 2
        actor.resolve_skill_component(
            magic.skill_id,
            "summon_non_battle",
            target=location,
            phase="AP1",
        )
        familiar = actor.familiars[0]
        self.assertEqual(actor.action_point, 0)
        self.assertEqual(familiar.move_conversion, 1)
        self.assertFalse(familiar.allows_action("attack"))

    def test_basic_familiar_magic_spends_attack_phase_and_joins_battle(self):
        actor = master()
        enemy = master("Enemy")
        location = Location("Arena")
        actor.position = enemy.position = location
        game = GameManager([actor, enemy], location)
        game.start_game()
        battle = BattleManager([actor, enemy])
        battle.start_battle()
        game.turn_manager.battles.append(battle)
        magic = actor.load_basic_magic("familiar")
        actor.attack_phase_count = 1

        actor.resolve_skill_component(
            magic.skill_id,
            "summon_in_battle",
            target=location,
            phase="attack_phase",
            battle=battle,
        )

        familiar = actor.familiars[0]
        self.assertEqual(actor.attack_phase_count, 0)
        self.assertIn(familiar, battle.participants)
        self.assertIs(familiar.current_battle, battle)
        self.assertEqual(familiar.attack_phase_count, 0)

    def test_new_effect_schemas_are_strict(self):
        self.assertTrue(validate_effect_definition({
            "effect_type": "restore_component",
            "effect_data": {"usage_amount": 1},
        }))
        with self.assertRaises(ValueError):
            validate_effect_definition({
                "effect_type": "add_content",
                "effect_data": {
                    "content_type": "class_skill",
                    "content_id": "x",
                },
            })


if __name__ == "__main__":
    unittest.main()
