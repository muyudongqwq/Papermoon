import unittest

from game.character.card_factory import create_master_test_0
from game.character.masters import Master
from game.game.game_manager import GameManager
from game.map.map import Location
from game.turn.battle import BattleManager
from game.turn.damage import DamageEvent, DamageResolver
from game.turn.decision import ScriptedDecisionProvider
from game.skill.casting import start_or_continue_casting


def ordinary_master(name="Target"):
    return Master(name, 3, 3, 3, 3, 3, "C", 3)


class MasterTest0CardTests(unittest.TestCase):
    def test_factory_loads_fixed_card_contents(self):
        actor = create_master_test_0()
        self.assertEqual(actor.magic.value, 5)
        self.assertEqual(actor.magic.plus_capacity, 2)
        self.assertEqual(
            [skill.skill_id for skill in actor.personal_skills],
            [
                "master_test_0:unblemished_person",
                "master_test_0:world_faith_domination",
                "master_test_0:starfire",
            ],
        )
        self.assertEqual(
            [skill.skill_id for skill in actor.magic_skill],
            ["basic_magic:healing", "basic_magic:workshop"],
        )

    def test_unblemished_person_pays_mp_before_shield_and_hp(self):
        actor = create_master_test_0()
        attacker = ordinary_master("Attacker")
        location = Location("Arena")
        actor.position = attacker.position = location
        game = GameManager([actor, attacker], location)
        game.start_game()
        game.decision_provider = ScriptedDecisionProvider([
            "无瑕之人",
            "40",
        ])
        old_mp = actor.mp
        old_hp = actor.hp
        damage = DamageResolver().resolve(DamageEvent(
            source=attacker,
            target=actor,
            value=50,
            damage_type="true_damage",
        ))
        self.assertEqual(damage, 10)
        self.assertEqual(actor.mp, old_mp - 40)
        self.assertEqual(actor.hp, old_hp - 10)

    def test_starfire_forces_first_selection_and_keeps_one_bundle(self):
        actor = create_master_test_0()
        location = Location("Workshop", is_building=True)
        actor.position = location
        game = GameManager([actor], location)
        game.start_game()
        game.decision_provider = ScriptedDecisionProvider(["barrel_replica"])
        game.turn_manager.start_turn()
        self.assertTrue(any(
            skill.skill_id == "master_test_0:barrel_replica"
            for skill in actor.personal_skills
        ))
        self.assertEqual(
            actor.switchable_skill_sets["master_test_0:starfire_records"]["current"],
            "barrel_replica",
        )

    def test_world_faith_uses_formal_round_mp_ledger(self):
        actor = create_master_test_0()
        other = ordinary_master()
        location = Location("Arena")
        actor.position = other.position = location
        game = GameManager([actor, other], location)
        game.start_game()
        battle = BattleManager([actor, other])
        battle.start_battle()
        battle.round_participants = {actor, other}
        actor.pay_mp_with_ledger(11)
        other.pay_mp_with_ledger(10)
        before = actor.temporary_mp
        battle.finish_battle_round()
        self.assertEqual(actor.temporary_mp - before, 10)

    def test_zabaniya_auto_release_temporarily_withdraws_then_rejoins(self):
        actor = create_master_test_0()
        other = ordinary_master()
        third = ordinary_master("Third")
        location = Location("Arena")
        actor.position = other.position = third.position = location
        game = GameManager([actor, other, third], location)
        game.start_game()
        zabaniya = actor.load_content(
            "personal_skill", "master_test_0:zabaniya"
        )
        battle = BattleManager([actor, other, third])
        battle.start_battle()
        state = start_or_continue_casting(actor, zabaniya, turn_number=1)
        result = state.advance_at_global_turn_end(1)
        self.assertTrue(result["auto_activated"])
        self.assertFalse(actor.in_battle)
        self.assertFalse(battle.ended)
        hidden = next(
            modifier for modifier in actor.modifiers
            if getattr(modifier, "status", None) == "hidden"
        )
        actor.remove_modifier(hidden)
        self.assertTrue(actor.in_battle)
        self.assertIn(actor, battle.participants)
        self.assertIn(actor, battle.late_participants)

    def test_battle_concealment_may_normally_disband_two_person_battle(self):
        actor = create_master_test_0()
        other = ordinary_master()
        location = Location("Arena")
        actor.position = other.position = location
        game = GameManager([actor, other], location)
        game.start_game()
        zabaniya = actor.load_content(
            "personal_skill", "master_test_0:zabaniya"
        )
        battle = BattleManager([actor, other])
        battle.start_battle()
        state = start_or_continue_casting(actor, zabaniya, turn_number=1)
        state.advance_at_global_turn_end(1)
        self.assertTrue(battle.ended)
        hidden = next(
            modifier for modifier in actor.modifiers
            if getattr(modifier, "status", None) == "hidden"
        )
        actor.remove_modifier(hidden)
        self.assertFalse(actor.in_battle)

    def test_territory_replaces_own_workshop_and_buffs_fixed_targets(self):
        actor = create_master_test_0()
        ally = ordinary_master("Ally")
        actor.add_ally(ally)
        ally.add_ally(actor)
        location = Location("Workshop", is_building=True)
        actor.position = ally.position = location
        game = GameManager([actor, ally], location)
        game.start_game()
        workshop = next(
            skill for skill in actor.magic_skill
            if skill.skill_id == "basic_magic:workshop"
        )
        actor.resolve_skill_component(
            workshop.skill_id,
            "establish",
            target=location,
            turn_number=1,
            phase="AP1",
        )
        territory = actor.load_content(
            "personal_skill", "master_test_0:territory_creation"
        )
        actor.resolve_skill_component(
            territory.skill_id,
            "upgrade_workshop",
            targets=[actor, ally],
            casting_prepaid=True,
            casting_release=True,
            turn_number=1,
            phase="release",
        )
        self.assertEqual(len(game.field_manager.fields), 1)
        field = game.field_manager.fields[0]
        self.assertEqual(field.field_type, "territory")
        self.assertEqual(field.selected_targets, [actor, ally])
        self.assertEqual(actor.magic_resistance, 0.2)
        self.assertEqual(ally.magic_resistance, 0.2)


if __name__ == "__main__":
    unittest.main()

