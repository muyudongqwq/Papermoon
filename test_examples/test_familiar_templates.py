import unittest

from game.action.action_list import ActionContext, ActionListBuilder
from game.character.familiar import FamiliarFactory
from game.character.masters import Master
from game.turn.damage import AttackProfile
from game.turn.defense import get_offset_attack_options


def make_master(name="Summoner"):
    return Master(name, 3, 3, 3, 3, 3, "C", 3)


class FamiliarTemplateTests(unittest.TestCase):
    def test_fixed_template_expands_compact_stats(self):
        familiar = FamiliarFactory.create("jade_lama", make_master())

        self.assertEqual(familiar.hpmax, 30)
        self.assertEqual(familiar.mpmax, 0)
        self.assertEqual(familiar.atk, 30)
        self.assertEqual(familiar.physical_attack, 10)
        self.assertEqual(familiar.dodge, 10)
        self.assertEqual(familiar.block, 10)
        self.assertEqual(familiar.offset, 10)
        self.assertEqual(familiar.familiar_template_id, "jade_lama")

    def test_action_allowlist_filters_common_actions(self):
        familiar = FamiliarFactory.create("amber_elder", make_master())
        battle_actions = ActionListBuilder().get_action_entries(ActionContext(
            actor=familiar,
            phase="attack_phase",
        ))
        self.assertNotIn("attack", [entry.action_id for entry in battle_actions])

        defense_actions = ActionListBuilder().get_action_entries(ActionContext(
            actor=familiar,
            phase="defense_phase",
        ))
        self.assertEqual(
            {entry.action_id for entry in defense_actions},
            {"dodge", "block"},
        )

    def test_offset_requires_an_allowed_attack(self):
        summoner = make_master()
        attacker = make_master("Attacker")
        incoming = AttackProfile(
            source=attacker,
            value=10,
            damage_type="physical",
            attack_roll=None,
            resolution_channel="attack",
        ).assign_target(summoner)

        non_attacker = FamiliarFactory.create("amber_elder", summoner)
        self.assertEqual(get_offset_attack_options(non_attacker, incoming), [])

        attacker_familiar = FamiliarFactory.create("jade_lama", summoner)
        options = get_offset_attack_options(attacker_familiar, incoming)
        self.assertEqual([option.option_id for option in options], ["normal_attack"])

    def test_summoner_source_inherits_omitted_stats(self):
        summoner = make_master()
        definition = {
            "template_id": "copy_test",
            "name": "Copy",
            "stat_block": {
                "source": "summoner",
                "hp": 40,
            },
            "actions": {"allow": ["pass"]},
        }
        familiar = FamiliarFactory.create_from_definition(definition, summoner)

        self.assertEqual(familiar.hpmax, 40)
        self.assertEqual(familiar.mpmax, summoner.mpmax)
        self.assertEqual(familiar.atk, summoner.atk)
        self.assertEqual(familiar.physical_attack, summoner.physical_attack)
        self.assertEqual(familiar.dodge, summoner.dodge)


if __name__ == "__main__":
    unittest.main()
