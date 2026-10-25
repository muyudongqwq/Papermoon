class MovementAction:
    """UI/AP行动层使用的完整路径移动动作。"""

    action_id = "move"

    def __init__(self, actor, path, movement_limit=None, ap_layer=None):
        if not path or len(path) < 2:
            raise ValueError("移动路径必须至少移动1步")
        if movement_limit is None:
            from game.map.ride_group import (
                get_movement_controller,
                get_movement_formation,
            )

            if get_movement_controller(actor) is actor:
                _, movement_limit = get_movement_formation(
                    actor,
                    ap_layer=ap_layer,
                )
        self.movement_limit = (
            actor.get_effective_move_conversion(ap_layer=ap_layer)
            if movement_limit is None
            else movement_limit
        )
        if len(path) - 1 > self.movement_limit:
            raise ValueError("移动路径超过本次行动的最大移动步数")
        self.actor = actor
        from game.action.action_data import get_action_definition
        self.definition = get_action_definition(self.action_id)
        self.path = list(path)
        self.movement_state = None
        self.ap_layer = None
        self.ignored = False
        self.ignored_reason = None

    def prepare(self, resolver):
        if self.movement_state is not None:
            return True
        if self.path[0] is not self.actor.position:
            return False
        from game.map.ride_group import (
            get_movement_controller,
            get_movement_formation,
        )

        if get_movement_controller(self.actor) is not self.actor:
            return False
        members, movement_limit = get_movement_formation(
            self.actor,
            ap_layer=self.ap_layer,
        )
        companions = [
            member for member in members if member is not self.actor
        ]

        if len(self.path) - 1 > movement_limit:
            return False
        self.movement_limit = movement_limit

        if companions:
            if not resolver.convert_group_movement(
                self.actor,
                companions,
                movement_limit,
            ):
                return False
        elif not resolver.convert_movement(
            self.actor,
            movement_limit=self.movement_limit,
        ):
            return False
        self.movement_state = MovementState(
            self.actor,
            self.path,
            companions=companions,
            movement_limit=movement_limit,
        )
        return True


class MovementResolver:
    def __init__(self):
        # A contact record is created only after a real Encounter.  Each side's
        # next traversed directed edge is then compared at their next contact.
        self.contact_records = {}

    @staticmethod
    def _contact_key(first, second):
        return frozenset((first, second))

    def record_contact_step(self, character, start, end):
        for pair, record in self.contact_records.items():
            if character in pair:
                record[character] = (start, end)

    def invalidate_contacts(self, character):
        """Mark non-path movement (for example teleport) as a divergence."""
        for pair, record in self.contact_records.items():
            if character in pair:
                record[character] = None

    def should_suppress_repeated_contact(self, first, second):
        key = self._contact_key(first, second)
        if key not in self.contact_records:
            return False
        record = self.contact_records[key]
        first_edge = record.get(first, "missing")
        second_edge = record.get(second, "missing")
        suppress = (
            first_edge not in {"missing", None}
            and second_edge not in {"missing", None}
            and first_edge == second_edge
        )
        record.clear()
        return suppress

    def register_contact(self, first, second):
        self.contact_records.setdefault(
            self._contact_key(first, second),
            {},
        ).clear()

    def get_movement_order(self, movement_states, initiative_order):
        active_states = [c for c in movement_states
                   if c.remaining_movement> 0]
        initiative_index = {character:index
                            for index, character
                            in enumerate(initiative_order)}
        active_states.sort(
            key = lambda c:(c.remaining_movement, -initiative_index[c.actor]),
            reverse=True
        )
        return active_states
    #高移动力先动的排序
    def has_movement(self, movement_states):
        return any(self.can_move(state)
                   for state in movement_states)

    def has_hostile_pair(self,group):
        for i in range(len(group)):
            for j in range(i+1, len(group)):
                character1 = group[i]
                character2 = group[j]

                if not character1.is_ally(character2):
                    return True
        return False

    def can_move(self, state):
        if state.actor.movement_locked or state.actor.has_status("cannot_move"):
            return False
        if state.remaining_movement <=0:
            return False
        if state.finished == True:
            return False
#        if actor.has_status("cannot_move"):
#            return False
#       if state.pending_encounter:
#            return False
        return True
    #能不能动的判定

    def resolve(
        self,
        movement_states,
        initiative_order,
        characters,
        decision_provider=None,
    ):
        while self.has_movement(movement_states):
            movement_order = self.get_movement_order(
                movement_states, initiative_order
            )
            if not movement_order: break
            state = movement_order[0]
            moved = self.step(state, decision_provider=decision_provider)

            if not moved: continue

            encounters = self.check_encounter(characters, movement_states)
            if encounters:
                return encounters
        return None
#这一步在遭遇后打一个断点，以决定是继续前进，开始战斗，还是改变路径。

    def step(self, state, decision_provider=None):
        if state.actor.movement_locked or state.actor.has_status("cannot_move"):
            return False
        if not state.actor.is_alive():
            state.finished = True
            state.remaining_movement = 0
            return False
        if len(state.path)<= 1:
            state.finished = True
            return False
        current = state.actor.position
        next_position = state.path[1]

        if next_position not in current.connected_locations:
            print("非法路径！")
            state.finished = True
            state.remaining_movement = 0
            return False

        state.path.pop(0)
        destination = state.path[0]
        from game.map.ride_group import get_movement_formation

        formation_members, _ = get_movement_formation(state.actor)
        state.actor.position = destination
        self.record_contact_step(state.actor, current, destination)
        for companion in state.companions[:]:
            if (
                companion not in formation_members
                or companion.position is not current
                or companion.in_battle
                or not companion.is_alive()
            ):
                state.companions.remove(companion)
                continue
            companion.position = destination
            self.record_contact_step(companion, current, destination)
        game_manager = getattr(state.actor, "game_manager", None)
        if game_manager is not None:
            game_manager.record_movement_first_step(
                state.actor,
                current,
                destination,
            )
            for companion in state.companions:
                game_manager.record_movement_first_step(
                    companion,
                    current,
                    destination,
                )
            game_manager.trap_manager.trigger_entry(
                [state.actor, *state.companions],
                destination,
                decision_provider=decision_provider,
            )
        state.remaining_movement -=1
        state.steps_completed += 1
        if game_manager is not None:
            ap_layer = getattr(
                getattr(game_manager, "turn_manager", None),
                "current_ap_layer",
                None,
            )
            for index, character in enumerate(
                [state.actor, *state.companions]
            ):
                common = {
                    "actor": character,
                    "source": state,
                    "target": character,
                    "phase": ap_layer,
                    "position": destination,
                    "decision_provider": decision_provider,
                    "payload": {
                        "origin": current,
                        "destination": destination,
                        "origin_name": getattr(current, "name", str(current)),
                        "destination_name": getattr(
                            destination,
                            "name",
                            str(destination),
                        ),
                        "step_index": state.steps_completed,
                        "remaining_movement": state.remaining_movement,
                        "is_companion": index > 0,
                    },
                }
                game_manager.event_manager.emit(
                    "movement_step",
                    value=1,
                    **common,
                )
                if len(state.path) == 1:
                    game_manager.event_manager.emit(
                        "movement_completed",
                        value=state.steps_completed,
                        **common,
                    )
        if not state.actor.is_alive():
            state.finished = True
            state.remaining_movement = 0
        return True

    def convert_movement(self, actor, movement_limit=None):
        if actor.movement_locked or actor.has_status("cannot_move"):
            return False
        if actor.action_point <= 0:
            return False

        actor.action_point -=1
        if movement_limit is None:
            movement_limit = actor.get_effective_move_conversion()
        actor.movement_point += movement_limit

        return True

    def convert_group_movement(self, leader, companions, movement_limit):
        members = [leader, *companions]
        if movement_limit is None or movement_limit < 1:
            return False
        if any(
            member.movement_locked
            or member.has_status("cannot_move")
            or member.action_point <= 0
            or member.in_battle
            or not member.is_alive()
            or member.position is not leader.position
            for member in members
        ):
            return False

        for member in members:
            member.action_point -= 1
            member.movement_point += movement_limit
        return True

    def check_encounter(self, characters, movement_states):
        locations = {}
        for character in characters:
            pos = character.position

            if pos is None:
                continue
#测试用代码：如果角色没有位置就不管他了。

            if pos not in locations:
                locations[pos]=[]

            locations[pos].append(character)

        encounter_groups = [
            (position, group)
            for position, group in locations.items()
            if len(group) > 1
        ]

        # 场地效果和perceived都需要在每一步移动后刷新。
        game_manager = next((
            getattr(character, "game_manager", None)
            for character in characters
            if getattr(character, "game_manager", None) is not None
        ), None)
        if game_manager is not None:
            game_manager.refresh_fields()
        # perceived的距离维护仍需在每一步移动后执行，即使没有相遇候选。
        for character in characters:
            character.update_visibility(characters)

        encounters = [

        ]
        for pos, group in encounter_groups:
            encounter_group, awareness = self.get_encounter_data(group)
            if len(encounter_group) <= 1:
                continue

            encounter = Encounter(
                encounter_group,
                pos,
                movement_states,
                awareness=awareness,
            )
            encounters.append(encounter)
            for observer, targets in awareness.items():
                for target in targets:
                    observer.encountered_this_turn.add(target)
                    self.register_contact(observer, target)
        return encounters

    def get_encounter_group(self, group):
        encounter_characters, _ = self.get_encounter_data(group)
        return encounter_characters

    def get_encounter_data(self, group):
        encounter_characters = []
        awareness = {}
        contact_results = {}

        for character1 in group:
            for character2 in group:
                if character1 is character2:
                    continue
                first_group = getattr(character1, "travel_group", None)
                if (
                    first_group is not None
                    and first_group is getattr(character2, "travel_group", None)
                ):
                    continue
                first_ride = (
                    getattr(character1, "ride_group", None)
                    or getattr(character1, "carried_by", None)
                )
                if first_ride is not None and first_ride is (
                    getattr(character2, "ride_group", None)
                    or getattr(character2, "carried_by", None)
                ):
                    continue
                if (
                    character1.in_battle
                    and character2.in_battle
                    and character1.current_battle is character2.current_battle
                ):
                    continue
                contact_key = self._contact_key(character1, character2)
                if contact_key not in contact_results:
                    contact_results[contact_key] = (
                        self.should_suppress_repeated_contact(
                            character1,
                            character2,
                        )
                    )
                if contact_results[contact_key]:
                    continue

                manager = getattr(character1, "game_manager", None)
                position_revealed = bool(
                    manager is not None
                    and manager.is_position_revealed(character1, character2)
                )
                if (
                    character2 not in character1.any_visible
                    and not position_revealed
                ):
                    continue

                if character1 not in encounter_characters:
                    encounter_characters.append(character1)
                if character2 not in encounter_characters:
                    encounter_characters.append(character2)
                awareness.setdefault(character1, []).append(character2)

        return encounter_characters, awareness

class MovementState:
    def __init__(
        self,
        actor,
        path,
        companions=None,
        movement_limit=None,
    ):
        if not path:
            raise ValueError("移动路径为空")
        if path[0] is not actor.position:
            raise ValueError(
                "路径起点不一致"
            )
        self.actor = actor
        self.path = path.copy()
        self.companions = list(companions or [])
        self.remaining_movement = (
            actor.movement_point
            if movement_limit is None
            else movement_limit
        )
        self.paused = False
        self.finished = False
        # Resumed movement continues the same event sequence.
        self.steps_completed = 0

    def create_movement_state(self, actor, path):
        if not self.convert_movement(actor):
            return None
        return MovementState(actor, path)

    def resume(self, encounter, initiative_order, characters):
        if not encounter.resolved:
            return None
        if encounter.enter_battle:
            return None
        return self.resolve(encounter.movement_states, initiative_order, characters)

class Encounter:
    def __init__(self, characters, position, movement_states, awareness=None):
        self.characters = characters
        self.position = position
#保存移动的状态
        self.movement_states = movement_states

        self.resolved = False
        self.enter_battle = False
#是否在等待下个回合开战
        self.pending_battle = False

        if awareness is None:
            awareness = {
                character: [
                    target
                    for target in characters
                    if target is not character
                ]
                for character in characters
            }
        self.awareness = {
            character: list(targets)
            for character, targets in awareness.items()
            if targets
        }
        self.aware_characters = list(self.awareness)
        self.battle_declarers = []
        self.battle_requests = []
        self.replan_characters = set()

        self.movement_decisions = {
            character: None
            for character in self.aware_characters
        }

        self.decisions = {
            (character, target): None
            for character, targets in self.awareness.items()
            for target in targets
        }
    def get_decision_targets(self, character, unresolved_only=False):
        targets = list(self.awareness.get(character, []))
        if unresolved_only:
            targets = [
                target
                for target in targets
                if self.decisions.get((character, target)) is None
            ]
        return targets

    def _update_ride_divergence(self, character):
        ride_group = (
            getattr(character, "ride_group", None)
            or getattr(character, "carried_by", None)
        )
        if ride_group is None or ride_group.rider is None:
            return
        rider = ride_group.rider
        if character is not rider:
            passenger = character
        else:
            passenger = None

        if (
            passenger is not None
            and self.movement_decisions.get(passenger) == "battle"
        ):
            ride_group.remove_passenger(passenger)
            return

        rider_decision = self.movement_decisions.get(rider)
        if rider_decision is None:
            return
        for current_passenger in ride_group.passengers[:]:
            passenger_decision = self.movement_decisions.get(current_passenger)
            if (
                passenger_decision is not None
                and passenger_decision != rider_decision
            ):
                ride_group.remove_passenger(current_passenger)

    def set_non_battle_decision(self, character, decision, target=None):
        if character not in self.aware_characters:
            return False
        if self.resolved:
            return False

        if self.movement_decisions.get(character) is not None:
            return False
        self.movement_decisions[character] = decision
        for current_target in self.get_decision_targets(character):
            if self.decisions[(character, current_target)] is None:
                self.decisions[(character, current_target)] = decision
        if decision == "replan":
            self.replan_characters.add(character)
        self._update_ride_divergence(character)
        self.check_resolution()
        return True

    def choose_continue(self, character, target=None):
        return self.set_non_battle_decision(
            character,
            "continue",
            target=target,
        )

    def choose_replan(self, character, target=None):
        return self.set_non_battle_decision(
            character,
            "replan",
            target=target,
        )

    def get_battle_targets(self, character):
        return [
            target
            for target in self.awareness.get(character, [])
            if target in self.characters
            and not character.is_friendly_with(target)
        ]

    def declare_battle_target(self, character, target=None, ap_layer=None):
        if character not in self.aware_characters or self.resolved:
            return False
        targets = [
            current_target
            for current_target in self.get_battle_targets(character)
            if not any(
                request.actor is character and request.target is current_target
                for request in self.battle_requests
            )
        ]
        if target is None:
            if len(targets) != 1:
                raise ValueError("存在多个宣战目标时必须明确指定target")
            target = targets[0]
        if target not in targets:
            return False

        from game.turn.battle_request import BattleRequest

        self.decisions[(character, target)] = "battle"
        if character not in self.battle_declarers:
            self.battle_declarers.append(character)
        request = BattleRequest(
            actor=character,
            target=target,
            encounter=self,
            submitted_layer=ap_layer,
        )
        if ap_layer is None:
            request.lock_from_encounter_snapshot()
        self.battle_requests.append(request)
        manager = getattr(character, "game_manager", None)
        relationship_manager = getattr(manager, "relationship_manager", None)
        if relationship_manager is not None:
            relationship_manager.force_mutual_hostile(character, target)
        event_manager = getattr(manager, "event_manager", None)
        if event_manager is not None:
            event_manager.emit(
                "battle_declared",
                actor=character,
                source=request,
                target=target,
                phase=(f"AP{ap_layer}" if ap_layer is not None else None),
                position=self.position,
                payload={"encounter": self, "request": request},
            )
        return request

    def finish_battle_decision(self, character):
        if character not in self.aware_characters or self.resolved:
            return False
        if not any(
            request.actor is character
            for request in self.battle_requests
        ):
            return False
        self.movement_decisions[character] = "battle"
        for target in self.get_decision_targets(character):
            if self.decisions[(character, target)] is None:
                self.decisions[(character, target)] = "continue"
        self._update_ride_divergence(character)
        self.check_resolution()
        return True

    def choose_battle(self, character, target=None, ap_layer=None):
        if not self.declare_battle_target(
            character,
            target=target,
            ap_layer=ap_layer,
        ):
            return False
        return self.finish_battle_decision(character)

    def get_ambush_pairs(self):
        return [
            (request.actor, request.target)
            for request in self.battle_requests
            if request.locked and request.is_ambush
        ]

    def lock_battle_requests(self, ap_layer):
        for request in self.battle_requests:
            if request.submitted_layer == ap_layer:
                request.lock(ap_layer)
        self.check_resolution()

    def requests_are_locked(self):
        return all(request.locked for request in self.battle_requests)

    def check_resolution(self):
        if None in self.movement_decisions.values():
            return
        self.enter_battle = any(
            decision == "battle"
            for decision in self.decisions.values()
        )
        self.pending_battle = (
            self.enter_battle
            and self.requests_are_locked()
        )
        self.resolved = True

    def can_resume_movement(self):
        return (
            self.resolved
            and not self.enter_battle
        )
