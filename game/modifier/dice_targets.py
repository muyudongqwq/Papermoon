"""Shared groups for dice modifiers; group IDs are not character attributes."""

DICE_TARGET_GROUPS = {
    "attack": ("physical_attack", "magic_attack"),
    "defense": ("dodge", "block", "offset"),
}


def dice_targets(target):
    return DICE_TARGET_GROUPS.get(target, (target,))
