"""Reconcile MP ledgers with private reports across both pools and payers."""

import unittest

from game.character import create_character_from_card
from game.game_manager import GameManager
from game.game_session import GameSession
from game.map.map import Location
from game.skill.casting import CastingState


class MPJournalTests(unittest.TestCase):
    def setUp(self):
        node = Location("Arena")
        self.master = create_character_from_card("master_test_0", position=node)
        self.nero = create_character_from_card("servant_test_0", position=node, master=self.master)
        self.enemy = create_character_from_card("master_test_0", name="Enemy", position=node)
        self.game = GameManager([self.master, self.nero, self.enemy], node)
        self.game.start_game()
        self.session = GameSession(self.game, {self.master.character_id: "owner",
            self.nero.character_id: "owner", self.enemy.character_id: "enemy"})
        self.game.rule_reports.subscribe(self.session._on_rule_report)
        self.addCleanup(self.game.rule_reports.unsubscribe, self.session._on_rule_report)

    def changes(self, owner="gm"):
        return [event["payload"] for event in self.session.get_events(owner)
                if event["type"] == "rule_report" and event["payload"]["kind"] == "resource_changed"]

    def test_three_payment_pools_and_interrupted_cast_refund_reconcile_without_duplicates(self):
        self.nero.mp = 10
        self.nero.grant_temporary_mp(20)
        skill = next(item for item in self.nero.noble_phantasms if item.skill_id.endswith(":laus_saint_claudius"))
        mp = self.master.mp
        state = CastingState.start(self.nero, skill, 1)
        self.assertEqual((self.nero.temporary_mp, self.nero.mp, self.master.mp), (0, 0, mp - 70))
        state.interrupt(reason="test")
        self.assertEqual((self.nero.temporary_mp, self.nero.mp, self.master.mp), (20, 10, mp))
        self.nero.clear_temporary_mp()
        changes = self.changes()
        self.assertEqual(len(changes), 8)
        balances = {(self.nero.character_id, "temporary_mp"): 0,
                    (self.nero.character_id, "mp"): 10, (self.master.character_id, "mp"): mp}
        for item in changes:
            data = item["data"]
            key = (item["actor"]["character_id"], data["pool"])
            self.assertEqual(balances[key], data["old_value"])
            self.assertEqual(data["new_value"] - data["old_value"], data["change"])
            balances[key] = data["new_value"]
        self.assertEqual(balances, {(self.nero.character_id, "temporary_mp"): 0,
            (self.nero.character_id, "mp"): 10, (self.master.character_id, "mp"): mp})
        self.assertEqual(len(self.changes("owner")), 8)
        self.assertEqual(self.changes("enemy"), [])

    def test_masterless_upkeep_has_one_private_record_with_actual_clamped_cost(self):
        self.master.die()
        self.nero.mp = 40
        self.nero.end_global_turn(1)
        records = [item for item in self.changes() if item["data"].get("reason") == "masterless_upkeep"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["data"]["change"], -40)
        self.assertFalse(self.nero.is_alive())
        self.assertEqual(self.changes("enemy"), [])

    def test_base_master_temporary_payment_uses_separate_pool_and_no_zero_reports(self):
        self.master.grant_temporary_mp(90)
        mp = self.master.mp
        self.master.pay_mp_with_ledger(100)
        self.master.clear_temporary_mp()
        self.master.pay_mp_with_ledger(0)
        records = self.changes()
        self.assertEqual(len(records), 3)
        self.assertEqual([item["data"]["pool"] for item in records], ["temporary_mp", "temporary_mp", "mp"])
        self.assertEqual(self.master.mp, mp - 10)

    def test_insufficient_payment_leaves_all_pools_and_journal_untouched(self):
        self.nero.grant_temporary_mp(1)
        before = (self.nero.temporary_mp, self.nero.mp, self.master.mp, len(self.changes()))
        self.assertIsNone(self.nero.pay_mp_with_ledger(self.nero.get_available_mp() + 1))
        self.assertEqual(before, (self.nero.temporary_mp, self.nero.mp, self.master.mp, len(self.changes())))


if __name__ == "__main__":
    unittest.main()
