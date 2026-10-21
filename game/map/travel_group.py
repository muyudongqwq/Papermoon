from dataclasses import dataclass


@dataclass
class TravelJoinRequest:
    actor: object
    target: object
    ap_layer: int
    resolved: bool = False
    success: bool = False
    reason: str = None
    group: object = None


class TravelGroup:
    """A temporary group whose members travel under one leader."""

    def __init__(self, leader, members=None):
        self.leader = leader
        self.members = []
        self.last_leader_transfer_turn = None

        initial_members = list(members or [])
        if leader not in initial_members:
            initial_members.insert(0, leader)
        for character in initial_members:
            self._attach(character)

    @property
    def active(self):
        return len(self.members) >= 2

    @property
    def movement_conversion(self):
        return self.get_movement_conversion()

    def get_movement_conversion(self, ap_layer=None):
        if not self.members:
            return 0
        from game.map.ride_group import get_movement_formation

        if self.leader is not None:
            _, movement = get_movement_formation(
                self.leader,
                ap_layer=ap_layer,
            )
            return movement
        return min(
            character.get_effective_move_conversion(ap_layer=ap_layer)
            for character in self.members
        )

    def _attach(self, character):
        if character not in self.members:
            self.members.append(character)
        character.travel_group = self

    @staticmethod
    def are_mutual_allies(characters):
        return all(
            first.is_ally(second) and second.is_ally(first)
            for index, first in enumerate(characters)
            for second in characters[index + 1:]
        )

    def can_add(self, character, position=None):
        if character in self.members:
            return False
        if getattr(character, "travel_group", None) is not None:
            return False
        if getattr(character, "carried_by", None) is not None:
            return False
        if not character.is_alive() or character.in_battle:
            return False
        if not self.members:
            return False

        required_position = (
            self.leader.position if position is None else position
        )
        if required_position is None or character.position is not required_position:
            return False
        if any(
            not member.is_alive()
            or member.in_battle
            or member.position is not required_position
            for member in self.members
        ):
            return False
        return self.are_mutual_allies([*self.members, character])

    def add_member(self, character, position=None):
        if not self.can_add(character, position=position):
            return False
        self._attach(character)
        return True

    def choose_replacement_leader(self, initiative_order=None):
        if not self.members:
            self.leader = None
            return None
        order = list(initiative_order or [])
        order_index = {
            character: index for index, character in enumerate(order)
        }
        self.leader = min(
            self.members,
            key=lambda character: order_index.get(character, len(order_index)),
        )
        return self.leader

    def remove_member(self, character, initiative_order=None):
        if character not in self.members:
            return False
        self.members.remove(character)
        if getattr(character, "travel_group", None) is self:
            character.travel_group = None

        if len(self.members) < 2:
            self.dissolve()
        elif self.leader is character:
            self.choose_replacement_leader(initiative_order)
        return True

    def transfer_leader(self, actor, new_leader, turn_number):
        if actor is not self.leader or new_leader not in self.members:
            return False
        if new_leader is actor:
            return False
        if self.last_leader_transfer_turn == turn_number:
            return False
        self.leader = new_leader
        self.last_leader_transfer_turn = turn_number
        return True

    def validate(self, initiative_order=None):
        for character in self.members[:]:
            if (
                not character.is_alive()
                or character.in_battle
                or character.position is None
            ):
                self.remove_member(character, initiative_order)
        if len(self.members) < 2:
            self.dissolve()
            return False

        leader_position = self.leader.position
        for character in self.members[:]:
            if character.position is not leader_position:
                self.remove_member(character, initiative_order)
        if len(self.members) < 2:
            self.dissolve()
            return False

        if not self.are_mutual_allies(self.members):
            self.dissolve()
            return False
        return True

    def dissolve(self):
        members = list(self.members)
        for character in members:
            if getattr(character, "travel_group", None) is self:
                character.travel_group = None
        self.members.clear()
        self.leader = None
        return members


def get_travel_group_members(character):
    group = getattr(character, "travel_group", None)
    if group is None:
        return [character]
    return list(group.members)
