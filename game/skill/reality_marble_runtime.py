from copy import deepcopy

from game.map.map import Location, get_nodes_within_distance
from game.skill.field_runtime import FieldEffect


class RealityMarble(FieldEffect):
    """A disconnected temporary map whose ambient rules reuse field effects."""

    source_type = "reality_marble"

    def __init__(self, definition, owner, skill, *, turn_number=0):
        entrance_object = definition.get("entrance")
        selected_targets = list(definition.get("selected_targets", []))
        data = deepcopy(definition, {id(obj): obj for obj in [entrance_object, *selected_targets] if obj is not None})
        data["entrance"] = entrance_object
        data["selected_targets"] = selected_targets
        self.reality_marble_id = data.get("reality_marble_id")
        if not self.reality_marble_id:
            raise ValueError("固有结界必须提供reality_marble_id")

        entrance = entrance_object or owner.position
        if entrance is None:
            raise ValueError("固有结界缺少入口地点")
        capture_radius = data.get("capture_radius", 0)
        if (
            not isinstance(capture_radius, int)
            or isinstance(capture_radius, bool)
            or capture_radius < 0
        ):
            raise ValueError("固有结界capture_radius必须是非负整数")

        interior_data = deepcopy(data.get("interior", {}))
        interior = Location(
            interior_data.get("location_name", f"{self.reality_marble_id}内部"),
            high_level=False,
            is_building=interior_data.get("is_building", False),
        )
        # No connections are added: ordinary movement can never enter or leave.
        interior.is_reality_marble_interior = True
        interior.reality_marble = self
        interior.reality_marble_effects = []

        effects = interior_data.get("effects", [])
        field_definition = {
            "field_id": f"reality_marble:{self.reality_marble_id}",
            "name": data.get("name", self.reality_marble_id),
            "field_type": "bounded_field",
            "center": interior,
            "radius": 0,
            "duration": data.get("duration"),
            "cost": data.get("cost", []),
            "effects": effects,
            "selected_targets": data.get("selected_targets", []),
            "remove_on_source_death": False,
            "remove_with_source": data.get("remove_with_source", False),
            "exclusive_center": False,
        }
        super().__init__(
            field_definition,
            owner,
            skill,
            turn_number=turn_number,
        )
        self.definition = data
        self.field_id = self.reality_marble_id
        self.name = data.get("name", self.reality_marble_id)
        self.entrance = entrance
        self.capture_radius = capture_radius
        self.interior = interior
        self.interior.reality_marble_effects.append(self)
        self.captured_characters = []
        self.collapsed = False

    def capture_candidates(self, characters):
        nodes = get_nodes_within_distance(self.entrance, self.capture_radius)
        return [
            character
            for character in characters
            if character.is_alive() and character.position in nodes
        ]

    def deploy(self, characters, turn_number=0):
        self.captured_characters = self.capture_candidates(characters)
        captured = set(self.captured_characters)
        for character in self.captured_characters:
            character.position = self.interior
        # A target carried away before its defense roll avoids attacks from
        # attackers left outside. If both sides were captured, the attack is
        # still local to the new space and remains pending. An already-created
        # attack whose attacker alone was captured likewise remains committed.
        for character in characters:
            for attack in list(character.pending_attacks):
                if attack.target in captured and attack.source not in captured:
                    if attack.miss_because_target_moved():
                        character.pending_attacks.remove(attack)
        self.refresh(characters, turn_number, created=True)
        return list(self.captured_characters)

    def contains(self, character):
        return character.position is self.interior

    def owner_can_sustain(self):
        return self.owner.is_alive() and self.contains(self.owner)

    def end_turn(self, characters, turn_number):
        if not self.owner_can_sustain():
            return False
        return super().end_turn(characters, turn_number)

    def remove(self):
        if self.removed:
            return False
        super().remove()
        if self in self.interior.reality_marble_effects:
            self.interior.reality_marble_effects.remove(self)
        self.collapsed = True
        return True


class RealityMarbleManager:
    """Own the single active Reality Marble and its collapse/return rules."""

    def __init__(self, game_manager):
        self.game_manager = game_manager
        self.active = None
        self._transitioning = False

    @property
    def reality_marbles(self):
        return [] if self.active is None else [self.active]

    def can_deploy(self, marble):
        return bool(
            self.active is None
            and marble.owner.is_alive()
            and marble.owner.position is marble.entrance
            and not getattr(
                marble.owner.position,
                "is_reality_marble_interior",
                False,
            )
        )

    def deploy(self, marble):
        if not self.can_deploy(marble):
            return False
        self.active = marble
        self._transitioning = True
        try:
            marble.deploy(
                self.game_manager.characters,
                self.game_manager.turn_manager.turn,
            )
        finally:
            self._transitioning = False
        self.game_manager.reconcile_after_reality_marble_change()
        return True

    def refresh(self):
        marble = self.active
        if marble is None:
            return
        if not marble.owner_can_sustain():
            self.collapse(reason="owner_left_or_dead")
            return
        marble.refresh(
            self.game_manager.characters,
            self.game_manager.turn_manager.turn,
        )

    def end_turn(self, turn_number):
        marble = self.active
        if marble is None:
            return False
        if not marble.end_turn(self.game_manager.characters, turn_number):
            self.collapse(reason="duration_or_maintenance")
            return False
        marble.refresh(self.game_manager.characters, turn_number)
        return True

    def on_position_changed(self, character, old_position, new_position):
        marble = self.active
        if marble is None or self._transitioning:
            return
        if (
            character is marble.owner
            and old_position is marble.interior
            and new_position is not marble.interior
        ):
            self.collapse(reason="owner_left")

    def on_character_death(self, character):
        marble = self.active
        if marble is not None and character is marble.owner:
            self.collapse(reason="owner_dead")

    def collapse(self, reason="external"):
        marble = self.active
        if marble is None:
            return []
        occupants = list(marble.interior.occupants)
        self.active = None
        self._transitioning = True
        try:
            marble.remove()
            for character in occupants:
                character.position = marble.entrance
        finally:
            self._transitioning = False
        marble.collapse_reason = reason
        self.game_manager.reconcile_after_reality_marble_change()
        return occupants
