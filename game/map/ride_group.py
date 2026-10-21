"""Riding/carrying relationships and their flattened movement formation."""


class RideGroup:
    """One fixed rider and the passengers whose routes it controls."""

    def __init__(self, rider, passengers=None):
        self.rider = rider
        self.passengers = []
        if not self._rider_available(rider):
            raise ValueError("角色当前不能建立携带关系")
        rider.ride_group = self
        for passenger in list(passengers or []):
            if not self.add_passenger(passenger):
                self.dissolve()
                raise ValueError("乘客不满足同乘条件")

    @property
    def members(self):
        return [self.rider, *self.passengers] if self.rider is not None else []

    @property
    def capacity(self):
        if self.rider is None:
            return 0
        return self.rider.get_carry_capacity()

    @property
    def active(self):
        return self.rider is not None and bool(self.passengers)

    @staticmethod
    def _position_locked(character):
        return bool(
            getattr(character, "resting", False)
            or getattr(character, "command_spell_transfer", None) is not None
            or getattr(character, "movement_locked", False)
        )

    @classmethod
    def _rider_available(cls, rider):
        return bool(
            rider is not None
            and rider.is_alive()
            and not rider.in_battle
            and rider.position is not None
            and rider.get_carry_capacity() > 0
            and getattr(rider, "carried_by", None) is None
        )

    def can_add(self, passenger):
        rider = self.rider
        if not self._rider_available(rider):
            return False
        if self._position_locked(rider):
            return False
        if passenger is rider or passenger in self.passengers:
            return False
        if len(self.passengers) >= self.capacity:
            return False
        if (
            not passenger.is_alive()
            or passenger.in_battle
            or passenger.position is not rider.position
            or getattr(passenger, "ride_group", None) is not None
            or getattr(passenger, "carried_by", None) is not None
            or self._position_locked(passenger)
        ):
            return False
        return True

    def add_passenger(self, passenger):
        if not self.can_add(passenger):
            return False
        travel_group = getattr(passenger, "travel_group", None)
        if travel_group is not None:
            travel_group.remove_member(passenger)
        self.passengers.append(passenger)
        passenger.carried_by = self
        return True

    def remove_passenger(self, passenger):
        if passenger not in self.passengers:
            return False
        self.passengers.remove(passenger)
        if getattr(passenger, "carried_by", None) is self:
            passenger.carried_by = None
        if not self.passengers:
            self.dissolve()
        return True

    def retain_passengers(self, passengers):
        """Keep the selected passengers when capacity is reduced."""
        retained = list(dict.fromkeys(passengers))
        if any(passenger not in self.passengers for passenger in retained):
            raise ValueError("保留名单中存在不属于本携带关系的角色")
        if len(retained) > self.capacity:
            raise ValueError("保留的乘客数量超过当前携带容量")
        for passenger in self.passengers[:]:
            if passenger not in retained:
                self.remove_passenger(passenger)
        return list(retained)

    def get_movement_conversion(self, ap_layer=None):
        members = self.members
        if not members:
            return 0
        return max(
            member.get_effective_move_conversion(ap_layer=ap_layer)
            for member in members
        )

    def validate(self):
        if not self._rider_available(self.rider):
            self.dissolve()
            return False
        for passenger in self.passengers[:]:
            if (
                not passenger.is_alive()
                or passenger.in_battle
                or passenger.position is not self.rider.position
                or getattr(passenger, "carried_by", None) is not self
                or getattr(passenger, "ride_group", None) is not None
            ):
                self.remove_passenger(passenger)
        while len(self.passengers) > self.capacity:
            self.remove_passenger(self.passengers[-1])
        if not self.passengers:
            self.dissolve()
            return False
        return True

    def dissolve(self):
        rider = self.rider
        for passenger in list(self.passengers):
            if getattr(passenger, "carried_by", None) is self:
                passenger.carried_by = None
        self.passengers.clear()
        if rider is not None and getattr(rider, "ride_group", None) is self:
            rider.ride_group = None
        self.rider = None
        return True


def create_ride_group(rider, passenger):
    group = getattr(rider, "ride_group", None)
    if group is None:
        try:
            group = RideGroup(rider)
        except ValueError:
            return None
    if not group.add_passenger(passenger):
        if not group.active:
            group.dissolve()
        return None
    return group


def get_ride_unit(character):
    group = getattr(character, "ride_group", None)
    if group is not None:
        return group
    return getattr(character, "carried_by", None)


def get_movement_controller(character):
    ride_group = get_ride_unit(character)
    base = ride_group.rider if ride_group is not None else character
    travel_group = getattr(base, "travel_group", None)
    if travel_group is not None and travel_group.leader is not None:
        return travel_group.leader
    return base


def get_movement_formation(controller, ap_layer=None):
    """Return (members, limit) after composing riding and ordinary travel."""
    travel_group = getattr(controller, "travel_group", None)
    if travel_group is not None and travel_group.leader is controller:
        normal_members = list(travel_group.members)
        members = []
        unit_speeds = []
        for member in normal_members:
            ride_group = getattr(member, "ride_group", None)
            if ride_group is not None and ride_group.validate():
                unit_members = ride_group.members
                unit_speed = ride_group.get_movement_conversion(ap_layer)
            else:
                unit_members = [member]
                unit_speed = member.get_effective_move_conversion(
                    ap_layer=ap_layer,
                )
            for unit_member in unit_members:
                if unit_member not in members:
                    members.append(unit_member)
            unit_speeds.append(unit_speed)
        return members, min(unit_speeds) if unit_speeds else 0

    ride_group = getattr(controller, "ride_group", None)
    if ride_group is not None and ride_group.validate():
        return ride_group.members, ride_group.get_movement_conversion(ap_layer)
    return [controller], controller.get_effective_move_conversion(
        ap_layer=ap_layer,
    )
