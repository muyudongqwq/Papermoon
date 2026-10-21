"""Non-player character entity types."""

from .character import Character


class NPC(Character):
    """A GM-controlled character using the ordinary Character rules."""

    def __init__(
        self,
        name,
        strength=1,
        endurance=1,
        flexibility=1,
        magic=1,
        fortune=1,
        *,
        move_conversion=0,
        initiative_anchor=None,
    ):
        super().__init__(
            name,
            strength,
            endurance,
            flexibility,
            magic,
            fortune,
        )
        if not isinstance(move_conversion, int) or move_conversion < 0:
            raise ValueError("NPC移动力必须是非负整数")
        self.move_conversion = move_conversion
        self.entity_type = "npc"
        self.is_npc = True
        self.controller = "gm"
        self.initiative_anchor = initiative_anchor

def __getattr__(name):
    """Keep ``from character.npc import Familiar`` working without a cycle."""
    if name == "Familiar":
        from .familiar import Familiar

        return Familiar
    raise AttributeError(name)
