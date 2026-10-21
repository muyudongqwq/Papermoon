import unittest

from game.action.action_list import ActionContext, ActionListBuilder
from game.character.masters import Master
from game.character.servants import Servant
from game.map.map import Location
from game.skill.content_registry import validate_content_catalogs
from game.turn.battle import BattleManager
from game.turn.damage import AttackEvent
from game.turn.decision import ScriptedDecisionProvider


def create_master(name="Master"):
    return Master(name, 3, 3, 3, 5, 3, "C", 3)


class ContentRegistryTests(unittest.TestCase):
    def test_catalogs_validate_and_bulk_load_basic_magic(self):
        validated = validate_content_catalogs()
        self.assertEqual(
            set(validated["basic_magic"]),
            {
                "magic_bullet",
                "reinforcement",
                "healing",
                "insight",
                "workshop",
                "trap",
                "familiar",
                "protection",
            },
        )

        actor = create_master()
        loaded = actor.bulk_load_content(
            basic_magics=("magic_bullet", "reinforcement", "healing"),
        )

        self.assertEqual(len(loaded["basic_magic"]), 3)
        self.assertEqual(len(actor.magic_skill), 3)
        self.assertTrue(all(
            skill.source_type == "magic"
            for skill in actor.magic_skill
        ))

    def test_loaded_magic_appears_through_release_entry(self):
        actor = create_master("Caster")
        target = Servant("Target", 3, 3, 3, 3, 3, "Saber", "A")
        location = Location("Arena")
        actor.position = target.position = location
        actor.own_visible = [target]
        target.hp -= 10
        actor.bulk_load_content(
            basic_magics=("magic_bullet", "reinforcement", "healing"),
        )

        actions = ActionListBuilder().get_available_actions(ActionContext(
            actor,
            "attack_phase",
            characters=[actor, target],
        ))
        entries = {entry.action_id: entry for entry in actions}

        self.assertIn("release", entries)
        self.assertEqual(entries["release"].name, "解放魔术")
        self.assertNotIn("skill:basic_magic:magic_bullet:battle_cast", entries)

    def test_character_resolver_can_find_magic_collection(self):
        actor = create_master("Caster")
        actor.hp -= 20
        actor.load_basic_magic("healing")
        starting_mp = actor.mp
        actor.attack_phase_count = 1

        result = actor.resolve_skill_component(
            "basic_magic:healing",
            "battle_cast",
            target=actor,
        )

        self.assertEqual(result["results"], [15])
        self.assertEqual(actor.mp, starting_mp - 10)
        # 底层组件只支付魔术费用；攻击阶段由“解放”行动入口消耗。
        self.assertEqual(actor.attack_phase_count, 1)

    def test_protection_uses_variable_mp_and_replaces_its_shield(self):
        actor = create_master()
        target = create_master("Target")
        actor.load_basic_magic("protection")
        starting_mp = actor.mp

        first = actor.resolve_skill_component(
            "basic_magic:protection",
            "protect",
            target=target,
            input_values={"x": 11},
        )

        self.assertEqual(first["paid_costs"], {"mp": 11})
        self.assertEqual(actor.mp, starting_mp - 11)
        self.assertEqual(target.shield, 16)

        actor.resolve_skill_component(
            "basic_magic:protection",
            "protect",
            target=target,
            input_values={"x": 5},
        )

        self.assertEqual(target.shield, 7)
        self.assertEqual(
            len([
                modifier
                for modifier in target.modifiers
                if modifier.modifier_id == "basic_magic_protection"
            ]),
            1,
        )

        target.update_modifiers("global_turn_end")
        self.assertEqual(target.shield, 0)

    def test_protection_input_cannot_exceed_magic_rank_limit(self):
        actor = create_master()
        target = create_master("Target")
        actor.load_basic_magic("protection")
        starting_mp = actor.mp

        with self.assertRaisesRegex(ValueError, "输入x必须位于"):
            actor.resolve_skill_component(
                "basic_magic:protection",
                "protect",
                target=target,
                input_values={"x": 51},
            )

        self.assertEqual(actor.mp, starting_mp)
        self.assertEqual(target.shield, 0)

    def test_protection_returns_to_defense_selection(self):
        attacker = Servant("Attacker", 3, 3, 3, 3, 3, "Saber", "A")
        defender = create_master("Caster")
        location = Location("Arena")
        attacker.position = defender.position = location
        defender.load_basic_magic("protection")
        battle = BattleManager([attacker, defender])
        battle.start_battle()
        attack = AttackEvent(
            source=attacker,
            target=defender,
            value=30,
            damage_type="physical",
            attack_roll=0,
            skill=None,
        )
        defender.pending_attacks.append(attack)
        provider = ScriptedDecisionProvider([
            "skill:basic_magic:protection:protect",
            "Caster",
            10,
            "confirm",
            "block",
        ])

        defense = battle.request_defense(
            defender,
            provider,
            attacks=[attack],
        )

        self.assertEqual(defense, "block")
        self.assertEqual(defender.shield, 15)


if __name__ == "__main__":
    unittest.main()
