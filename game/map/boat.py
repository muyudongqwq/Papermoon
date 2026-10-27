"""Dynamic boat locations and port-to-port transport."""

from game.map.map import Location
from game.map.movement import Encounter
from game.map.ride_group import get_movement_controller, get_movement_formation


class BoatLocation(Location):
    """An isolated temporary location used during one transport."""

    def __init__(self, name, origin, destination, departure_turn):
        super().__init__(name)
        self.is_boat = True
        self.origin = origin
        self.destination = destination
        self.departure_turn = departure_turn
        self.internal_encounter_created = False
        self.internal_encounters = []


class BoatManager:
    """Creates, boards, arrives and removes per-route temporary boats."""

    def __init__(self, game_manager):
        self.game_manager = game_manager
        self.active_boats = []
        self._boats_by_trip = {}
        self._next_index = 0

    def get_ports(self):
        return [
            node
            for node in self.game_manager.get_map_nodes(merge_area_levels=False)
            if getattr(node, "is_port", False)
        ]

    def get_or_create(self, origin, destination, turn):
        key = (origin, destination, int(turn))
        boat = self._boats_by_trip.get(key)
        if boat is not None:
            return boat
        boat = BoatLocation(
            f"boat_{self._next_index}",
            origin,
            destination,
            int(turn),
        )
        self._next_index += 1
        self._boats_by_trip[key] = boat
        self.active_boats.append(boat)
        return boat

    def board(self, actor, destination, *, turn, ap_layer):
        if ap_layer != 1:
            return False
        origin = actor.position
        if (
            origin is None
            or not getattr(origin, "is_port", False)
            or destination is origin
            or destination not in self.get_ports()
            or actor.in_battle
            or not actor.is_alive()
            or actor.movement_locked
            or actor.has_status("cannot_move")
            or actor.action_point < 2
        ):
            return False
        if get_movement_controller(actor) is not actor:
            return False

        members, _ = get_movement_formation(actor, ap_layer=1)
        members = list(dict.fromkeys(members))
        if any(
            not member.is_alive()
            or member.in_battle
            or member.position is not origin
            or member.movement_locked
            or member.has_status("cannot_move")
            for member in members
        ):
            return False

        boat = self.get_or_create(origin, destination, turn)
        for member in members:
            member.action_point = 0
            member.boat_boarded_turn = int(turn)
            member.position = boat
        return {
            "boat": boat,
            "origin": origin,
            "destination": destination,
            "passengers": members,
        }

    def create_internal_encounters(self):
        encounters = []
        resolver = self.game_manager.turn_manager.movement_resolver
        for boat in list(self.active_boats):
            if boat.internal_encounter_created:
                continue
            boat.internal_encounter_created = True
            occupants = [
                character
                for character in boat.occupants
                if character.is_alive() and character.position is boat
            ]
            awareness = {
                observer: [
                    target
                    for target in occupants
                    if target is not observer
                    and not (
                        getattr(observer, "travel_group", None) is not None
                        and observer.travel_group is getattr(target, "travel_group", None)
                    )
                    and not (
                        (getattr(observer, "ride_group", None) or getattr(observer, "carried_by", None))
                        is not None
                        and (getattr(observer, "ride_group", None) or getattr(observer, "carried_by", None))
                        is (getattr(target, "ride_group", None) or getattr(target, "carried_by", None))
                    )
                ]
                for observer in occupants
            }
            awareness = {observer: targets for observer, targets in awareness.items() if targets}
            if not awareness:
                continue
            encounter_characters = list(dict.fromkeys([
                *awareness,
                *(target for targets in awareness.values() for target in targets),
            ]))
            encounter = Encounter(
                encounter_characters,
                boat,
                [],
                awareness=awareness,
            )
            encounter.is_boat_encounter = True
            boat.internal_encounters.append(encounter)
            encounters.append(encounter)
            for observer, targets in awareness.items():
                for target in targets:
                    observer.encountered_this_turn.add(target)
                    resolver.register_contact(observer, target)
                    resolver.suppress_contact_until_separated(observer, target)
        return encounters

    def arrive_all(self, turn):
        arrivals = []
        for boat in list(self.active_boats):
            if boat.departure_turn != int(turn):
                continue
            passengers = [
                character
                for character in list(boat.occupants)
                if character.is_alive() and character.position is boat
            ]
            for character in passengers:
                character.position = boat.destination
            for encounter in boat.internal_encounters:
                encounter.position = boat.destination
            arrivals.append({
                "boat": boat,
                "destination": boat.destination,
                "passengers": passengers,
            })
            self._remove_boat(boat)
        return arrivals

    def on_position_changed(self, character, old_position, new_position):
        if getattr(old_position, "is_boat", False) and old_position is not new_position:
            self._detach_from_boat_encounters(character, old_position)
            self._remove_if_empty(old_position)

    def remove_character(self, character):
        position = getattr(character, "position", None)
        if getattr(position, "is_boat", False):
            if character in position.occupants:
                position.occupants.remove(character)
            self._remove_if_empty(position)

    def _remove_if_empty(self, boat):
        if not boat.occupants:
            self._remove_boat(boat)

    def _detach_from_boat_encounters(self, character, boat):
        turn_manager = self.game_manager.turn_manager
        encounters = list(dict.fromkeys([
            *boat.internal_encounters,
            *turn_manager.pending_encounters,
            *turn_manager.waiting_encounters,
        ]))
        for encounter in encounters:
            if not getattr(encounter, "is_boat_encounter", False):
                continue
            removed_requests = [
                request
                for request in encounter.battle_requests
                if request.actor is character or request.target is character
            ]
            for request in removed_requests:
                for actor in (request.actor, request.target):
                    if getattr(actor, "movement_lock_source", None) is request:
                        actor.clear_movement_lock()
            encounter.characters = [
                actor for actor in encounter.characters if actor is not character
            ]
            encounter.awareness = {
                observer: [
                    target for target in targets if target is not character
                ]
                for observer, targets in encounter.awareness.items()
                if observer is not character
            }
            encounter.awareness = {
                observer: targets
                for observer, targets in encounter.awareness.items()
                if targets
            }
            encounter.aware_characters = list(encounter.awareness)
            encounter.movement_decisions = {
                actor: decision
                for actor, decision in encounter.movement_decisions.items()
                if actor in encounter.aware_characters
            }
            encounter.decisions = {
                pair: decision
                for pair, decision in encounter.decisions.items()
                if character not in pair
                and pair[0] in encounter.awareness
                and pair[1] in encounter.awareness[pair[0]]
            }
            encounter.battle_declarers = [
                actor
                for actor in encounter.battle_declarers
                if actor is not character
            ]
            encounter.battle_requests = [
                request
                for request in encounter.battle_requests
                if request not in removed_requests
            ]
            encounter.replan_characters.discard(character)
            encounter.resolved = False
            encounter.enter_battle = False
            encounter.pending_battle = False
            encounter.check_resolution()
            if len(encounter.characters) < 2 or not encounter.awareness:
                for collection in (
                    turn_manager.pending_encounters,
                    turn_manager.waiting_encounters,
                ):
                    if encounter in collection:
                        collection.remove(encounter)

    def _remove_boat(self, boat):
        if boat in self.active_boats:
            self.active_boats.remove(boat)
        for key, candidate in list(self._boats_by_trip.items()):
            if candidate is boat:
                self._boats_by_trip.pop(key, None)


def positions_share_visibility_space(first, second):
    """Boats can see only their own occupants; the map cannot see into boats."""
    first_boat = bool(getattr(first, "is_boat", False))
    second_boat = bool(getattr(second, "is_boat", False))
    if not first_boat and not second_boat:
        return True
    return first is second
