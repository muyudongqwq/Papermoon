from game.character.masters import Master
from game.character.servants import Servant


class CommandSpellService:
    """Rule service for immediate command-spell effects.

    The terminal menu lives in the terminal provider; this class deliberately
    contains no input calls so another UI can reuse the same rules.
    """

    TEMPORARY_MP_AMOUNT = 90
    DAMAGE_BONUS_AMOUNT = 90

    def __init__(self, game_manager):
        self.game_manager = game_manager

    def available_masters(self, minimum=1):
        return [
            character
            for character in self.game_manager.characters
            if isinstance(character, Master)
            and character.is_alive()
            and character.command_spell >= minimum
        ]

    @staticmethod
    def controlled_characters(master):
        return [master] + [
            servant
            for servant in master.servants
            if servant.is_alive() and servant.master is master
        ]

    def spend(self, master, amount):
        if master not in self.available_masters(amount):
            return False
        master.command_spell -= amount
        return True

    def grant_temporary_mp(self, master, target):
        if target not in self.controlled_characters(master):
            return False
        if not self.spend(master, 1):
            return False
        target.grant_temporary_mp(self.TEMPORARY_MP_AMOUNT)
        return True

    def grant_damage_bonus(self, master, target):
        if target not in self.controlled_characters(master):
            return False
        if not self.spend(master, 1):
            return False
        target.grant_command_spell_damage(self.DAMAGE_BONUS_AMOUNT)
        return True

    def teleport_destinations(self, master, servant):
        if (
            not isinstance(servant, Servant)
            or servant.master is not master
            or not servant.is_alive()
        ):
            return []
        return sorted(
            (
                location
                for location in servant.seen_locations
                if location is not None and location is not servant.position
            ),
            key=lambda location: str(location.name),
        )

    def emergency_guard_targets(self, master, servant, destination):
        if servant.master is not master:
            return []
        battle = self.game_manager.get_battle_at(destination)
        if battle is None:
            return []
        return battle.get_emergency_guard_targets(
            servant,
            position=destination,
        )

    def teleport(
        self,
        master,
        servant,
        destination,
        *,
        emergency_guard_target=None,
        decision_provider=None,
    ):
        if destination not in self.teleport_destinations(master, servant):
            return False
        if not self.spend(master, 2):
            return False
        return self.game_manager.resolve_command_spell_teleport(
            servant,
            destination,
            emergency_guard_target=emergency_guard_target,
            decision_provider=decision_provider,
        )
