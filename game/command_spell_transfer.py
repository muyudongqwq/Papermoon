from dataclasses import dataclass

from game.character.masters import Master


@dataclass
class CommandSpellTransfer:
    source: Master
    recipient: Master
    agreed_amount: int
    started_turn: int
    origin: object
    completed_turns: int = 0
    scheduled_turn: int | None = None
    active: bool = True
    completed: bool = False
    actual_amount: int = 0
    interruption_reason: str | None = None

    @property
    def participants(self):
        return (self.source, self.recipient)

    def is_valid(self):
        return bool(
            self.active
            and self.source.is_alive()
            and self.recipient.is_alive()
            and not self.source.in_battle
            and not self.recipient.in_battle
            and self.source.position is self.origin
            and self.recipient.position is self.origin
            and self.source.command_spell_transfer is self
            and self.recipient.command_spell_transfer is self
        )

    def schedule(self, turn_number):
        if not self.is_valid():
            return False
        self.scheduled_turn = turn_number
        # Both participants spend the whole map turn maintaining the ritual.
        self.source.action_point = 0
        self.recipient.action_point = 0
        return True


class CommandSpellTransferManager:
    REQUIRED_TURNS = 3

    def __init__(self, game_manager):
        self.game_manager = game_manager
        self.transfers = []

    def can_start(self, source, recipient, amount):
        return bool(
            isinstance(source, Master)
            and isinstance(recipient, Master)
            and source is not recipient
            and source.is_alive()
            and recipient.is_alive()
            and not source.in_battle
            and not recipient.in_battle
            and source.position is not None
            and source.position is recipient.position
            and source.command_spell_transfer is None
            and recipient.command_spell_transfer is None
            and isinstance(amount, int)
            and not isinstance(amount, bool)
            and amount >= 1
            and source.command_spell >= 1
        )

    def start(self, source, recipient, amount, turn_number, *, accepted=False):
        if not accepted or not self.can_start(source, recipient, amount):
            return False
        transfer = CommandSpellTransfer(
            source=source,
            recipient=recipient,
            agreed_amount=amount,
            started_turn=turn_number,
            origin=source.position,
        )
        source.command_spell_transfer = transfer
        recipient.command_spell_transfer = transfer
        self.transfers.append(transfer)
        if not transfer.schedule(turn_number):
            self.interrupt(transfer, "start_invalid")
            return False
        return transfer

    def continue_transfer(self, transfer, turn_number):
        if transfer not in self.transfers or not transfer.active:
            return False
        if not transfer.is_valid():
            self.interrupt(transfer, "requirements_failed")
            return False
        return transfer.schedule(turn_number)

    def interrupt(self, transfer, reason):
        if transfer is None or not transfer.active:
            return False
        transfer.active = False
        transfer.interruption_reason = reason
        for participant in transfer.participants:
            if participant.command_spell_transfer is transfer:
                participant.command_spell_transfer = None
        if transfer in self.transfers:
            self.transfers.remove(transfer)
        return True

    def interrupt_character(self, character, reason):
        return self.interrupt(
            getattr(character, "command_spell_transfer", None),
            reason,
        )

    def on_position_changed(self, character, old_position, new_position):
        transfer = getattr(character, "command_spell_transfer", None)
        if transfer is not None and new_position is not transfer.origin:
            self.interrupt(transfer, "position_changed")

    def on_battle_state_changed(self, character, in_battle):
        if in_battle:
            self.interrupt_character(character, "entered_battle")

    def on_character_death(self, character):
        self.interrupt_character(character, "death")

    def prepare_turn(self, turn_manager):
        """Reserve AP1/AP2 and enqueue one automatic maintenance action."""
        from game.action.action import Action

        for transfer in self.transfers[:]:
            if not transfer.is_valid():
                self.interrupt(transfer, "requirements_failed")
                continue
            if any(
                action.actor is transfer.source
                and action.action_id == "command_spell_transfer"
                for action in turn_manager.action_layers[1]
            ):
                continue
            action = Action(
                transfer.source,
                "command_spell_transfer",
                target=transfer.recipient,
                amount=transfer.agreed_amount,
                automatic=True,
                confirmed=True,
            )
            turn_manager.add_action(action, ap_layer=1)

    def end_turn(self, turn_number):
        completed = []
        for transfer in self.transfers[:]:
            if not transfer.is_valid():
                self.interrupt(transfer, "requirements_failed")
                continue
            if transfer.scheduled_turn != turn_number:
                self.interrupt(transfer, "not_maintained")
                continue
            transfer.completed_turns += 1
            if transfer.completed_turns < self.REQUIRED_TURNS:
                continue

            actual = min(
                transfer.agreed_amount,
                transfer.source.command_spell,
            )
            transfer.source.command_spell -= actual
            transfer.recipient.command_spell += actual
            transfer.actual_amount = actual
            transfer.completed = True
            transfer.active = False
            for participant in transfer.participants:
                if participant.command_spell_transfer is transfer:
                    participant.command_spell_transfer = None
            self.transfers.remove(transfer)
            completed.append(transfer)
        return completed
