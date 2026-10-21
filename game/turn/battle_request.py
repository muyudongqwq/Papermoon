from dataclasses import dataclass


@dataclass
class BattleRequest:
    """一次明确指向目标的宣战申请。"""

    actor: object
    target: object
    encounter: object = None
    submitted_layer: object = None
    locked_layer: object = None
    is_ambush: object = None

    @property
    def locked(self):
        return self.is_ambush is not None

    def lock(self, ap_layer=None):
        if self.locked:
            return self.is_ambush

        self.locked_layer = ap_layer
        game_manager = getattr(self.target, "game_manager", None)
        position_revealed = bool(
            game_manager is not None
            and game_manager.is_position_revealed(self.target, self.actor)
        )
        self.is_ambush = (
            self.target in self.actor.own_visible
            and self.actor not in self.target.any_visible
            and not position_revealed
        )
        return self.is_ambush

    def lock_from_encounter_snapshot(self):
        """兼容没有TurnManager/AP行动层的独立调用。"""
        if self.locked:
            return self.is_ambush
        self.locked_layer = self.submitted_layer
        target_was_aware = (
            self.actor in self.encounter.awareness.get(self.target, [])
            if self.encounter is not None
            else self.actor in self.target.any_visible
        )
        game_manager = getattr(self.target, "game_manager", None)
        position_revealed = bool(
            game_manager is not None
            and game_manager.is_position_revealed(self.target, self.actor)
        )
        self.is_ambush = (
            self.target in self.actor.own_visible
            and not target_was_aware
            and not position_revealed
        )
        return self.is_ambush
