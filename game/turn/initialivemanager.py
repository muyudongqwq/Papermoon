import random


class InitiativeManager:
    """Build initiative while keeping NPC/familiar registration snapshots."""

    @staticmethod
    def _anchor_order(character):
        anchor = getattr(character, "initiative_anchor", None)
        if anchor is None:
            return getattr(character, "registration_index", None), "registration"

        game_manager = getattr(character, "game_manager", None)
        turn_manager = getattr(game_manager, "turn_manager", None)
        global_order = list(
            getattr(turn_manager, "global_action_order", []) or []
        )
        if anchor in global_order:
            return global_order.index(anchor), "global_order"

        battle = getattr(anchor, "current_battle", None)
        if battle is not None:
            battle_order = list(
                getattr(battle, "current_order", [])
                or getattr(battle, "initial_order", [])
                or []
            )
            if anchor in battle_order:
                return battle_order.index(anchor), "battle_order"

        return getattr(anchor, "registration_index", None), "registration"

    @classmethod
    def capture_fixed_snapshot(cls, character, fallback_order=0):
        """Capture an NPC/familiar's immutable base initiative once."""
        snapshot = getattr(character, "initiative_snapshot", None)
        if snapshot is not None:
            return snapshot
        if not getattr(character, "is_npc", False):
            return None

        registration_index = getattr(character, "registration_index", None)
        if registration_index is None:
            registration_index = fallback_order
        anchor_order, anchor_source = cls._anchor_order(character)
        if anchor_order is None:
            anchor_order = registration_index
        snapshot = {
            "flexibility": character.flexibility.value,
            "fortune": character.fortune.value,
            "anchor_order": anchor_order,
            "anchor_source": anchor_source,
            "registration_index": registration_index,
        }
        character.initiative_snapshot = snapshot
        return snapshot

    @classmethod
    def initiative_stats(cls, character, fallback_order=0):
        if getattr(character, "is_npc", False):
            snapshot = cls.capture_fixed_snapshot(
                character,
                fallback_order=fallback_order,
            )
            return snapshot["flexibility"], snapshot["fortune"]
        return character.flexibility.value, character.fortune.value

    def resolve_tie(self, characters):
        """Resolve a player-only equal-stat group without dropping losers."""
        result = []
        pending_groups = [list(characters)]
        while pending_groups:
            group = pending_groups.pop()
            if len(group) == 1:
                result.append(group[0])
                continue

            roll_groups = {}
            for character in group:
                roll = random.randint(1, 10)
                roll_groups.setdefault(roll, []).append(character)

            # The stack is LIFO: enqueue lower rolls first so higher groups
            # finish all of their own tie resolution before lower groups.
            for roll in sorted(roll_groups):
                pending_groups.append(roll_groups[roll])

        return result

    @staticmethod
    def _fixed_tie_key(character):
        snapshot = character.initiative_snapshot
        return (
            snapshot["anchor_order"],
            snapshot["registration_index"],
        )

    def determine_order(self, characters):
        indexed = list(enumerate(characters))
        stat_groups = {}
        for fallback_order, character in indexed:
            flex, fortune = self.initiative_stats(
                character,
                fallback_order=fallback_order,
            )
            stat_groups.setdefault((flex, fortune), []).append(character)

        order = []
        for stat_key in sorted(stat_groups, reverse=True):
            group = stat_groups[stat_key]
            players = [
                character
                for character in group
                if not getattr(character, "is_npc", False)
            ]
            fixed_entities = [
                character
                for character in group
                if getattr(character, "is_npc", False)
            ]

            # Player priority applies only after both flexibility and fortune
            # tie. NPCs and familiars never roll a d10.
            if len(players) == 1:
                order.extend(players)
            elif players:
                order.extend(self.resolve_tie(players))
            order.extend(sorted(fixed_entities, key=self._fixed_tie_key))
        return order


def show_initiallist(order):
    print("当前行动顺序：")
    for index, character in enumerate(order, start=1):
        print(f"{index}:{character.name}")
