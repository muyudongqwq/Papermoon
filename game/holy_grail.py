class HolyGrail:
    """记录圣杯的出场、就绪、位置与携带者。"""

    def __init__(
        self,
        designated_location,
        appearance_servant_deaths=4,
        ready_servant_deaths=6,
    ):
        self.designated_location = designated_location
        self.appearance_servant_deaths = None
        self.ready_servant_deaths = None
        self.configure_thresholds(
            appearance_servant_deaths,
            ready_servant_deaths,
        )
        self.appeared = False
        self.carrier = None
        self.ground_location = None
        self.pending_drop_location = None
        self.status = set()
        self.servant_death_count = 0

    @property
    def ready(self):
        return "Ready" in self.status

    @property
    def position(self):
        if self.carrier is not None:
            return self.carrier.position
        return self.ground_location

    def configure_thresholds(
        self,
        appearance_servant_deaths,
        ready_servant_deaths,
    ):
        appearance = int(appearance_servant_deaths)
        ready = int(ready_servant_deaths)
        if appearance < 0:
            raise ValueError("圣杯出场所需的从者死亡数不能小于0")
        if ready < appearance:
            raise ValueError("圣杯就绪阈值不能小于出场阈值")
        self.appearance_servant_deaths = appearance
        self.ready_servant_deaths = ready

    def refresh(self, characters):
        from game.character.servants import Servant

        self.servant_death_count = sum(
            isinstance(character, Servant) and character.has_status("dead")
            for character in characters
        )

        if (
            not self.appeared
            and self.servant_death_count >= self.appearance_servant_deaths
        ):
            self.appeared = True
            self.ground_location = self.designated_location

        if self.servant_death_count >= self.ready_servant_deaths:
            self.status.add("Ready")
        return self.appeared

    def note_carrier_death(self, character, death_location):
        if self.carrier is not character:
            return False
        self.carrier = None
        self.pending_drop_location = death_location
        return True

    def resolve_pending_drop(self):
        if self.pending_drop_location is None:
            return False
        self.ground_location = self.pending_drop_location
        self.pending_drop_location = None
        return True

    def pick_up(self, character):
        if (
            not self.appeared
            or self.carrier is not None
            or character.position is not self.ground_location
            or not character.is_alive()
        ):
            return False
        self.carrier = character
        self.ground_location = None
        self.pending_drop_location = None
        return True

    def drop(self, character):
        if self.carrier is not character:
            return False
        self.ground_location = character.position
        self.carrier = None
        self.pending_drop_location = None
        return True
