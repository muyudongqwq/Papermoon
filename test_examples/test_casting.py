import unittest
from types import SimpleNamespace

from game.action.action import Action
from game.action.action_list import ActionContext, ActionListBuilder
from game.action.action_resolver import ActionResolver
from game.character.masters import Master
from game.character.servants import Servant
from game.map.map import Location
from game.skill.casting import CastingState
from game.turn.decision import ScriptedDecisionProvider
from game.turn.roll import RollResolver


def create_master(name="Master"):
    return Master(name, 3, 3, 3, 5, 3, "C", 3)


def create_servant(name="Caster"):
    return Servant(name, 3, 5, 3, 5, 3, "Caster", "A")


def casting_skill(
    actor,
    skill_id="ritual",
    mp_cost=40,
    target="selectable_character",
    target_rules=None,
    requirements=(1, 2),
):
    components = []
    for index, requirement in enumerate(requirements, start=1):
        components.append({
            "component_id": f"effect_{index}",
            "name": f"效果{index}",
            "type": "active",
            "target": target,
            "target_rules": dict(target_rules or {}),
            "casting_requirement": requirement,
            "effects": [{
                "effect_type": "damage",
                "effect_data": {
                    "damage_type": "physical",
                    "value": index * 10,
                },
            }],
        })
    return actor.create_personal_skill({
        "skill_id": skill_id,
        "name": "仪式魔术",
        "rank": "C",
        "casting": {"mp_cost": mp_cost},
        "components": components,
    })


class CastingTests(unittest.TestCase):
    def test_action_list_exposes_chant_then_release_and_interrupt(self):
        actor = create_master()
        skill = casting_skill(actor, target="self", requirements=(1,))
        builder = ActionListBuilder()

        initial = builder.get_available_actions(ActionContext(actor, "AP1"))
        initial_ids = {entry.action_id for entry in initial}
        self.assertIn("chant", initial_ids)
        self.assertNotIn("release", initial_ids)
        self.assertNotIn(f"skill:{skill.skill_id}:effect_1", initial_ids)

        state = CastingState.start(actor, skill, 1)
        actor.advance_casting(1)
        actor.reset_turn()
        ready = builder.get_available_actions(ActionContext(actor, "AP1"))
        ready_ids = {entry.action_id for entry in ready}
        self.assertIn("chant", ready_ids)
        self.assertIn("release", ready_ids)
        self.assertIn("interrupt_casting", ready_ids)

    def test_non_battle_chant_progress_and_composite_release(self):
        actor = create_master()
        target = create_servant("Target")
        actor.game_manager = SimpleNamespace(characters=[actor, target])
        casting_skill(actor)
        starting_mp = actor.mp

        chant = Action(actor, "chant")
        chant.ap_layer = 1
        chant.game_turn = 1
        state = chant.chant(ScriptedDecisionProvider([]))

        self.assertIsNotNone(state)
        self.assertEqual(actor.action_point, 0)
        self.assertEqual(actor.mp, starting_mp - 40)
        self.assertEqual(state.layers, 0)
        self.assertTrue(actor.has_status("casting"))
        self.assertEqual(actor.advance_casting(1), 1)

        actor.reset_turn()
        continuation = Action(actor, "chant")
        continuation.ap_layer = 1
        continuation.game_turn = 2
        self.assertIs(continuation.chant(ScriptedDecisionProvider([])), state)
        self.assertEqual(actor.advance_casting(2), 2)

        actor.reset_turn()
        release = Action(actor, "release")
        release.ap_layer = 1
        release.game_turn = 3
        result = release.release(ScriptedDecisionProvider([
            "effect_2",
            "Target",
        ]))

        self.assertEqual(result["results"][0]["damage"], 20)
        self.assertIsNone(actor.casting_state)
        self.assertFalse(actor.has_status("casting"))
        self.assertEqual(actor.action_point, 0)
        self.assertEqual(actor.mp, starting_mp - 40)

    def test_interruption_refunds_each_original_mp_payer(self):
        master = create_master()
        servant = create_servant()
        servant.set_master(master)
        servant.mp = 10
        master.mp = 50
        skill = casting_skill(servant, mp_cost=40, target="self", requirements=(1,))

        state = CastingState.start(servant, skill, 1)
        self.assertEqual(servant.mp, 0)
        self.assertEqual(master.mp, 20)

        refunds = servant.interrupt_casting(reason="manual")

        self.assertEqual(servant.mp, 10)
        self.assertEqual(master.mp, 50)
        self.assertEqual(
            [(item["payer"], item["refunded"]) for item in refunds],
            [(servant, 10), (master, 30)],
        )
        self.assertIsNone(servant.casting_state)

    def test_missing_continuation_interrupts_and_refunds_at_turn_end(self):
        actor = create_master()
        skill = casting_skill(actor, target="self", requirements=(1,))
        starting_mp = actor.mp
        state = CastingState.start(actor, skill, 1)
        actor.advance_casting(1)
        self.assertEqual(state.layers, 1)

        self.assertFalse(actor.advance_casting(2))

        self.assertIsNone(actor.casting_state)
        self.assertEqual(actor.mp, starting_mp)

    def test_other_formal_action_interrupts_before_it_resolves(self):
        actor = create_master()
        actor.position = Location("Field")
        skill = casting_skill(actor, target="self", requirements=(1,))
        starting_mp = actor.mp
        CastingState.start(actor, skill, 1)

        result = ActionResolver().resolve(Action(actor, "pass"))

        self.assertTrue(result)
        self.assertIsNone(actor.casting_state)
        self.assertEqual(actor.mp, starting_mp)

    def test_zero_requirement_releases_without_creating_casting_state(self):
        actor = create_master()
        actor.hp -= 20
        actor.create_personal_skill({
            "skill_id": "instant_heal",
            "name": "即时治疗",
            "rank": "C",
            "casting": {"mp_cost": 30},
            "components": [{
                "component_id": "heal",
                "name": "治疗",
                "type": "active",
                "target": "self",
                "casting_requirement": 0,
                "effects": [{
                    "effect_type": "recover_resource",
                    "effect_data": {"resource_id": "hp", "value": 15},
                }],
            }],
        })
        starting_mp = actor.mp
        action = Action(actor, "release")
        action.ap_layer = 1
        action.game_turn = 1

        result = action.release(ScriptedDecisionProvider([]))

        self.assertEqual(result["results"], [15])
        self.assertEqual(actor.mp, starting_mp - 30)
        self.assertIsNone(actor.casting_state)

    def test_casting_halves_final_defense_roll_only(self):
        actor = create_master()
        skill = casting_skill(actor, target="self", requirements=(1,))
        CastingState.start(actor, skill, 1)

        defense = RollResolver().roll(
            actor,
            "block",
            allow_luck=False,
            initial_die=5,
        )
        attack = RollResolver().roll(
            actor,
            "physical_attack",
            allow_luck=False,
            initial_die=5,
        )

        self.assertEqual(defense.final_multiplier, 0.5)
        self.assertEqual(
            defense.total,
            int(defense.total_before_final_multiplier * 0.5),
        )
        self.assertEqual(attack.final_multiplier, 1)

    def test_area_release_can_select_multiple_allies_but_not_self(self):
        actor = create_master("Actor")
        ally = create_master("Ally")
        enemy = create_master("Enemy")
        actor.add_ally(ally)
        actor.game_manager = SimpleNamespace(
            characters=[actor, ally, enemy]
        )
        skill = casting_skill(
            actor,
            mp_cost=30,
            target="selectable_character",
            target_rules={
                "exclude_self": True,
                "unlimited_targets": True,
            },
            requirements=(1,),
        )
        state = CastingState.start(actor, skill, 1)
        actor.advance_casting(1)
        action = Action(actor, "release")
        action.ap_layer = 1
        action.game_turn = 2
        ally_hp = ally.hp
        enemy_hp = enemy.hp

        result = action.release(ScriptedDecisionProvider([
            "Ally",
            "Enemy",
        ]))

        self.assertEqual(result["targets"], [ally, enemy])
        self.assertEqual(ally.hp, ally_hp - 10)
        self.assertEqual(enemy.hp, enemy_hp - 10)
        self.assertNotIn(actor, result["targets"])

    def test_magic_anti_fortress_noble_uses_defaults_and_creates_attacks(self):
        actor = create_servant("Caster")
        ally = create_servant("Ally")
        target = create_servant("Target")
        actor.game_manager = SimpleNamespace(
            characters=[actor, ally, target]
        )
        noble = actor.create_noble_phantasm({
            "skill_id": "fortress_magic",
            "name": "城塞魔术",
            "rank": "C",
            "noble_phantasm_type": "magic",
            "range_type": "anti_fortress",
            "components": [{
                "component_id": "release",
                "name": "解放",
                "target": "selectable_character",
                "effects": [{
                    "effect_type": "create_attack_event",
                    "effect_data": {"initial_die": 5},
                }],
            }],
        })
        starting_mp = actor.mp
        state = CastingState.start(actor, noble, 1)
        self.assertEqual(actor.mp, starting_mp - 60)
        actor.advance_casting(1)
        action = Action(actor, "release")
        action.ap_layer = 1
        action.game_turn = 2

        result = action.release(ScriptedDecisionProvider([
            "Ally",
            "Target",
        ]))

        self.assertEqual(result["targets"], [ally, target])
        self.assertEqual(len(ally.pending_attacks), 1)
        self.assertEqual(len(target.pending_attacks), 1)
        self.assertEqual(ally.pending_attacks[0].damage_type, "magic")
        self.assertEqual(ally.pending_attacks[0].value, 180)
        self.assertIsNone(actor.casting_state)

    def test_custom_noble_roll_profile_uses_selected_base_attribute(self):
        actor = create_servant("Caster")
        target = create_servant("Target")
        actor.game_manager = SimpleNamespace(characters=[actor, target])
        noble = actor.create_noble_phantasm({
            "skill_id": "fortune_noble",
            "name": "幸运宝具",
            "rank": "C",
            "noble_phantasm_type": "physical",
            "range_type": "anti_unit",
            "roll_profile": {
                "type": "custom",
                "attribute": "fortune",
                "multiplier": 2,
            },
            "components": [{
                "component_id": "release",
                "name": "解放",
                "target": "selectable_character",
                "target_rules": {"exclude_self": True},
                "effects": [{
                    "effect_type": "create_attack_event",
                    "effect_data": {
                        "damage_value": 70,
                        "initial_die": 5,
                    },
                }],
            }],
        })
        action = Action(actor, "release")
        action.ap_layer = 1
        action.game_turn = 1

        result = action.release(ScriptedDecisionProvider(["Target"]))
        attack = result["results"][0]

        self.assertEqual(
            attack.attack_roll,
            5 + actor.fortune.value * 2 + actor.dice_bonus,
        )
        self.assertEqual(attack.value, 70)
        self.assertEqual(actor.mp, actor.mpmax - 30)

    def test_physical_noble_requires_card_defined_damage(self):
        actor = create_servant("Caster")

        with self.assertRaisesRegex(ValueError, "damage_value"):
            actor.create_noble_phantasm({
                "skill_id": "missing_damage",
                "name": "未定义伤害的物理宝具",
                "rank": "C",
                "noble_phantasm_type": "physical",
                "range_type": "anti_unit",
                "components": [{
                    "component_id": "release",
                    "name": "解放",
                    "target": "selectable_character",
                    "target_rules": {"exclude_self": True},
                    "effects": [{
                        "effect_type": "create_attack_event",
                        "effect_data": {"initial_die": 5},
                    }],
                }],
            })

    def test_support_noble_cannot_define_hit_roll_attack(self):
        actor = create_servant("Caster")

        with self.assertRaisesRegex(ValueError, "辅助宝具不会进行命中检定"):
            actor.create_noble_phantasm({
                "skill_id": "invalid_support",
                "name": "错误的辅助宝具",
                "rank": "C",
                "noble_phantasm_type": "support",
                "range_type": "anti_unit",
                "components": [{
                    "component_id": "release",
                    "name": "解放",
                    "target": "selectable_character",
                    "effects": [{
                        "effect_type": "create_attack_event",
                        "effect_data": {"damage_value": 10},
                    }],
                }],
            })


if __name__ == "__main__":
    unittest.main()
