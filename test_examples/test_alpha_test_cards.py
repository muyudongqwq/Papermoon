"""Import, point budget, and executable subset of the local alpha cards."""

import unittest

from CharacterEditorClient.point_rules import assess_character_points
from core.catalog import BUILTINS
from game.character import create_character_from_card
from game.character.masters import Master


class AlphaTestCardTests(unittest.TestCase):
    def test_both_cards_validate_and_use_exact_servant_budget(self):
        for card_id in ("archer_alpha_test", "lancer_alpha_test"):
            with self.subTest(card_id=card_id):
                assessment = assess_character_points(
                    BUILTINS["character_card"][card_id], BUILTINS,
                )
                self.assertEqual((assessment.points, assessment.budget), (45, 45))
                self.assertEqual(assessment.status, "valid")
                self.assertTrue(assessment.importable)
                self.assertEqual(create_character_from_card(card_id).card_id, card_id)

    def test_lancer_loads_passives_class_skills_and_two_noble_phantasms(self):
        actor = create_character_from_card("lancer_alpha_test")

        self.assertEqual((actor.strength.value, actor.endurance.value), (6, 6))
        self.assertEqual(actor.get_effective_move_conversion(), 5)
        self.assertEqual(actor.get_carry_capacity(), 1)
        self.assertEqual([skill.rank.rank for skill in actor.class_skills], ["E", "A"])
        self.assertEqual(len(actor.noble_phantasms), 2)
        self.assertEqual(actor.get_effective_atk(), 80)

    def test_archer_uses_real_luck_and_can_trade_both_initial_skills(self):
        actor = create_character_from_card("archer_alpha_test")
        self.assertEqual(actor.fortune.value, 5)
        self.assertEqual(len(actor.personal_skills), 3)
        self.assertEqual(len(actor.noble_phantasms), 2)

        actor.resolve_skill_component(
            "archer_alpha_test:uncrowned_arms",
            "sacrifice_for_flame",
            target=actor,
            phase="attack_phase",
        )
        skill_ids = {skill.skill_id for skill in actor.personal_skills}
        self.assertNotIn("archer_alpha_test:uncrowned_arms", skill_ids)
        self.assertIn("archer_alpha_test:mana_burst_flame", skill_ids)

        actor.resolve_skill_component(
            "archer_alpha_test:bhargavastra",
            "sacrifice_for_brahmastra",
            target=actor,
            phase="attack_phase",
        )
        noble_ids = {skill.skill_id for skill in actor.noble_phantasms}
        self.assertNotIn("archer_alpha_test:bhargavastra", noble_ids)
        self.assertIn("archer_alpha_test:brahmastra_kundala", noble_ids)
        self.assertEqual(len(noble_ids), 2)

    def test_lancer_gains_battle_continuation_when_master_is_lost(self):
        master = Master("Master", 3, 3, 3, 3, 3, "C", 3)
        actor = create_character_from_card("lancer_alpha_test", master=master)
        master.remove_servant(actor)
        self.assertIn(
            "lancer_alpha_test:battle_continuation",
            {skill.skill_id for skill in actor.personal_skills},
        )

    def test_lancer_area_noble_has_declared_cost_damage_and_cooldown(self):
        actor = create_character_from_card("lancer_alpha_test")
        noble = next(
            skill for skill in actor.noble_phantasms
            if skill.skill_id == "lancer_alpha_test:spear_king_annihilation"
        )
        component = noble.definitions[0]
        self.assertEqual(component["casting_requirement"], 1)
        self.assertEqual(component["cost"][0]["value"], 50)
        self.assertEqual(component["cooldown"]["turns"], 3)
        self.assertEqual(component["effects"][0]["effect_data"]["damage_value"], 200)


if __name__ == "__main__":
    unittest.main()
