from game.map.map import get_area_positions, get_area_root


def character_class_name(character):
    return getattr(character, "servant_class", None) or "Master"


class LocationObservation:
    """A turn-scoped, area-wide magical observation created by Insight."""

    def __init__(self, owner, center, turn_number, ap_layer):
        self.owner = owner
        self.center = get_area_root(center)
        self.turn_number = int(turn_number or 0)
        self.ap_layer = ap_layer
        self.first_steps = {}
        self.active = True

    @property
    def covered_nodes(self):
        return set(get_area_positions(self.center))

    def covers(self, position):
        return position in self.covered_nodes

    def visible_characters(self, characters):
        if not self.active or not self.owner.is_alive():
            return []
        return [
            character
            for character in characters
            if character is not self.owner
            and character.is_alive()
            and self.covers(character.position)
        ]

    def record_first_step(self, character, origin, destination, ap_layer):
        if (
            not self.active
            or ap_layer != self.ap_layer
            or character in self.first_steps
            or not self.covers(origin)
            or self.covers(destination)
        ):
            return None
        report = {
            "type": "insight_first_step",
            "turn": self.turn_number,
            "ap_layer": self.ap_layer,
            "observer": self.owner,
            "character": character,
            "class_name": character_class_name(character),
            "origin": origin,
            "destination": destination,
        }
        self.first_steps[character] = report
        return report


class ObservationManager:
    def __init__(self, game_manager):
        self.game_manager = game_manager
        self.observations = []

    def create(self, owner, center, turn_number, ap_layer):
        observation = LocationObservation(
            owner,
            center,
            turn_number,
            ap_layer,
        )
        self.observations.append(observation)
        return observation

    def active_for(self, owner):
        return [
            observation
            for observation in self.observations
            if observation.active and observation.owner is owner
        ]

    def visible_characters(self, owner):
        result = []
        for observation in self.active_for(owner):
            for character in observation.visible_characters(
                self.game_manager.characters
            ):
                if character not in result:
                    result.append(character)
        return result

    def visible_nodes(self, owner):
        result = set()
        for observation in self.active_for(owner):
            result.update(observation.covered_nodes)
        return result

    def record_first_step(self, character, origin, destination, ap_layer):
        reports = []
        turn_number = self.game_manager.turn_manager.turn
        for observation in self.observations:
            if observation.turn_number != turn_number:
                continue
            report = observation.record_first_step(
                character,
                origin,
                destination,
                ap_layer,
            )
            if report is None:
                continue
            recipients = observation.owner.get_shared_vision_group()
            report["recipients"] = list(recipients)
            for recipient in recipients:
                recipient.insight_reports.append(report)
            reports.append(report)
            print(
                f"洞悉：{character.name}（{report['class_name']}）从"
                f"{origin.name}移动至{destination.name}。"
            )
        return reports

    def end_turn(self, turn_number):
        expired = []
        for observation in self.observations:
            if observation.active and observation.turn_number <= turn_number:
                observation.active = False
                expired.append(observation)
        self.observations = [
            observation
            for observation in self.observations
            if observation.active
        ]
        return expired

    def remove_owner(self, owner):
        for observation in self.observations:
            if observation.owner is owner:
                observation.active = False
        self.observations = [
            observation
            for observation in self.observations
            if observation.active
        ]
