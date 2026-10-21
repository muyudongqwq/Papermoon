import json
import unittest

from game.action.action import Action
from game.character.masters import Master
from game.game_manager import GameManager
from game.map.map import Location
from game.modifier.modifier import create_modifier
from test_examples.minimal_card_battle import run_acceptance
from game.turn.battle import BattleManager


class MinimalCardBattleTests(unittest.TestCase):
    def assert_closed_attack_records(self, result):
        declared = {report["data"]["attack_id"] for report in result["reports"] if report["kind"] == "attack_declared"}
        ended = {report["data"]["attack_id"] for report in result["reports"]
                 if report["kind"] in {"attack_resolved", "attack_cancelled"}}
        self.assertTrue(declared)
        self.assertEqual(declared, ended)

    def test_recorded_cards_fight_through_nobles_and_survival_to_natural_ceasefire(self):
        result = run_acceptance()
        self.assertEqual(result["summary"]["turns"], 8)
        self.assertEqual(result["final_snapshot"]["result"]["reason"], "session_stopped")
        counts = result["summary"]["report_counts"]
        self.assertEqual(counts["character_died"], 2)
        self.assertEqual(counts["field_created"], 2)
        self.assertEqual(counts["field_removed"], 2)
        self.assertEqual(counts["battle_ended"], 1)
        skills = [report["data"].get("skill_name") for report in result["reports"] if report["kind"] == "skill_activated"]
        for name in ("招荡的黄金剧场", "童女讴歌的华丽帝政", "陨铁之刃·原初之火", "治疗", "战斗续行", "纵使三度迎来夕阳"):
            self.assertIn(name, skills)
        self.assertEqual(skills.count("战斗续行"), 4)
        self.assertEqual(skills.count("纵使三度迎来夕阳"), 2)
        for character in result["final_snapshot"]["characters"]:
            self.assertFalse(character["in_battle"])
            self.assertEqual(character["fields"], [])
        self.assert_closed_attack_records(result)
        json.dumps(result, allow_nan=False)

    def test_normal_random_dice_uses_same_structured_client_without_forced_deaths(self):
        result = run_acceptance(seed=1, fixed_die=None)
        self.assertIsNone(result["fixed_die"])
        self.assertLess(result["summary"]["turns"], 12)
        self.assertEqual(result["final_snapshot"]["result"]["reason"], "session_stopped")
        self.assertTrue(any(actor["hp"] > 0 for actor in result["summary"]["characters"] if "御主" in actor["name"]))
        self.assert_closed_attack_records(result)

    def make_battle(self):
        location = Location("Cancel")
        actors = [Master(name, 3, 3, 3, 3, 3, "C", 3) for name in ("A", "B", "C")]
        for actor in actors:
            actor.position = location
        game = GameManager(actors, location)
        game.start_game()
        battle = BattleManager(actors)
        game.turn_manager.battles.append(battle)
        battle.start_battle()
        return game, battle, actors

    def test_discard_report_does_not_resolve_attack_or_consume_resolution_modifier(self):
        game, battle, (actor, target, other) = self.make_battle()
        modifier = create_modifier({
            "effect_type": "dice_bonus", "effect_data": {"effect_target": "physical_attack", "value": 1},
            "consumption": {"event": "attack_resolved", "uses": 1, "remove_when_empty": True},
        }, actor)
        actor.add_modifier(modifier)
        attack = Action(actor, "attack").build_attack_profile().assign_target(target)
        target.pending_attacks.append(attack)
        hp = target.hp
        battle.remove_participant(actor)
        self.assertFalse(attack.resolved)
        self.assertFalse(attack._resolution_consumption_done)
        self.assertEqual(modifier.remaining_uses, 1)
        self.assertEqual(target.hp, hp)
        self.assertNotIn(attack, target.pending_attacks)
        self.assertFalse(attack.report_cancelled("duplicate"))
        self.assertEqual(len([record for record in game.rule_reports.history if record["kind"] == "attack_cancelled"]), 1)

    def test_preserved_character_locked_attack_is_not_reported_as_cancelled(self):
        game, battle, (actor, target, other) = self.make_battle()
        ordinary = Action(actor, "attack").build_attack_profile().assign_target(target)
        locked = Action(other, "attack", target_lock=True).build_attack_profile().assign_target(target)
        target.pending_attacks.extend([ordinary, locked])
        battle.remove_participant(target, preserve_target_locked_attacks=True)
        self.assertEqual(target.pending_attacks, [locked])
        cancelled = [record["data"]["public"]["attack_id"] for record in game.rule_reports.history
                     if record["kind"] == "attack_cancelled"]
        self.assertEqual(cancelled, [ordinary.attack_id])
        self.assertFalse(locked._cancellation_reported)


if __name__ == "__main__":
    unittest.main()
