import unittest

from game.action.action import Action
from game.character.masters import Master
from game.game.game_manager import GameManager
from game.map.map import Location


def make_master(name, command_spell=3):
    return Master(name, 3, 3, 3, 3, 3, "C", command_spell)


class CommandSpellTransferTests(unittest.TestCase):
    def setUp(self):
        self.location = Location("Workshop", is_building=True)
        self.other = Location("Other")
        self.source = make_master("Source")
        self.recipient = make_master("Recipient")
        self.source.position = self.recipient.position = self.location
        self.game = GameManager(
            [self.source, self.recipient],
            self.location,
        )
        self.game.start_game()
        self.manager = self.game.command_spell_transfer_manager

    def start_transfer(self, amount=2, turn=1):
        action = Action(
            self.source,
            "command_spell_transfer",
            target=self.recipient,
            amount=amount,
            confirmed=True,
        )
        action.game_manager = self.game
        action.game_turn = turn
        result = action.command_spell_transfer()
        self.assertTrue(result)
        return result["transfer"]

    def test_three_valid_turns_transfer_only_remaining_amount(self):
        transfer = self.start_transfer(amount=3)
        self.assertEqual((self.source.action_point, self.recipient.action_point), (0, 0))
        self.manager.end_turn(1)

        self.source.action_point = self.recipient.action_point = 2
        self.assertTrue(self.manager.continue_transfer(transfer, 2))
        self.manager.end_turn(2)

        # Command spells are not prepaid. Spending during the ritual reduces
        # the amount that can actually be transferred at completion.
        self.source.command_spell = 1
        self.source.action_point = self.recipient.action_point = 2
        self.assertTrue(self.manager.continue_transfer(transfer, 3))
        completed = self.manager.end_turn(3)

        self.assertEqual(completed, [transfer])
        self.assertEqual(transfer.actual_amount, 1)
        self.assertEqual(self.source.command_spell, 0)
        self.assertEqual(self.recipient.command_spell, 4)
        self.assertIsNone(self.source.command_spell_transfer)
        self.assertIsNone(self.recipient.command_spell_transfer)

    def test_position_change_interrupts_without_transfer(self):
        transfer = self.start_transfer()
        self.source.position = self.other
        self.assertFalse(transfer.active)
        self.assertEqual(transfer.interruption_reason, "position_changed")
        self.assertEqual(self.source.command_spell, 3)
        self.assertEqual(self.recipient.command_spell, 3)

    def test_entering_battle_interrupts_without_transfer(self):
        transfer = self.start_transfer()
        self.recipient.in_battle = True
        self.assertFalse(transfer.active)
        self.assertEqual(transfer.interruption_reason, "entered_battle")

    def test_initial_action_reserves_both_layers_for_both_masters(self):
        turn = self.game.turn_manager
        turn.turn = 1
        turn.current_ap_layer = 1
        action = Action(
            self.source,
            "command_spell_transfer",
            target=self.recipient,
            amount=2,
            confirmed=True,
        )
        turn.add_action(action, ap_layer=1)
        self.assertIn(self.source, turn.layer_actors[1])
        self.assertIn(self.source, turn.layer_actors[2])
        self.assertIn(self.recipient, turn.layer_actors[1])
        self.assertIn(self.recipient, turn.layer_actors[2])

    def test_recipient_confirmation_is_required_by_runtime(self):
        transfer = self.manager.start(
            self.source,
            self.recipient,
            1,
            1,
            accepted=False,
        )
        self.assertFalse(transfer)
        self.assertEqual(self.manager.transfers, [])


if __name__ == "__main__":
    unittest.main()
