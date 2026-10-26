from game.action.action_resolver import ActionResolver
from game.action.action_restriction import action_restriction_reasons
from game.turn.initialivemanager import InitiativeManager
from game.turn.battle import BattleManager
from game.map.movement import MovementAction, MovementResolver
from game.map.travel_group import TravelGroup, TravelJoinRequest
from game.map.ride_group import (
    create_ride_group,
    get_movement_controller,
    get_movement_formation,
)
from game.turn.damage import report_discarded_attacks
class TurnManager:
    ACTION_LAYERS = (1, 2)
    MOVEMENT_ACTION_IDS = {"move"}
    TWO_AP_ACTION_IDS = {
        "direct_attack",
        "mend",
        "rest",
        "chant",
        "release",
        "command_spell_transfer",
    }

    @classmethod
    def uses_two_ap(cls, action):
        return (
            action.action_id in cls.TWO_AP_ACTION_IDS
            or getattr(action, "ap_cost", 0) >= 2
        )

    def __init__(self):
        self.turn = 0
        self.characters = []
        self.dead_characters = []
        self.actions = []
        self.initiative_manager = InitiativeManager()
        self.current_order = []
        self.pending_encounters = []
        self.battles = []
        self.action_layers = {1: [], 2: []}
        self.layer_actors = {1: set(), 2: set()}
        self.checkpoint_actions = {1: [], 2: []}
        self.checkpoint_results = {1: [], 2: []}
        self.completed_checkpoints = []
        self.current_ap_layer = None
        self.non_battle_order = []
        # 本全局回合唯一的大地图行动顺位。战斗先于地图行动结算时，
        # 简易战斗轮等插入流程仍可引用同一顺位，而不会另行掷骰。
        self.global_action_order = []
        self.layer_execution = None
        self.waiting_encounters = []
        self.paused_movement_action = None
        self.movement_resolver = MovementResolver()
        self.map_phase_started = False
        self.battle_phase_pending = False
        self.game_manager = None
        self.travel_groups = []
        self.ride_groups = []
        self.travel_join_requests = {1: [], 2: []}
        self.travel_layer_prepared = set()
        self.ap_start_positions = {1: {}, 2: {}}
        self.pending_battle_requests = []
        self.teleport_encounters = []

    def start_turn(self):
        self.turn +=1

        if self.game_manager is not None:
            self.game_manager.relationship_manager.apply_turn_start()
            self.game_manager.information_manager.begin_turn(self.turn)
            self.game_manager.event_manager.clear_turn_usage(self.turn)

        for character in self.characters:
            character.current_global_turn = self.turn
            character.reset_turn()
            character.encountered_this_turn.clear()

        self.global_action_order = self.initiative_manager.determine_order([
            character
            for character in self.characters
            if character.can_act_on_turn(self.turn)
        ])
        if self.game_manager is not None:
            self.game_manager.event_manager.emit(
                "global_turn_start",
                phase="global_turn_start",
                payload={"turn_number": self.turn},
            )

        # 先解散上一战斗轮全员待机的战斗，再处理新的BattleRequest。
        for battle in self.battles:
            released = battle.disband_if_all_stayed()
            for character in released:
                character.ap1_forfeited_turn = self.turn
                character.action_point = 1

        self.start_pending_battles()
        active_battles = []
        for battle in self.battles:
            if not battle.ended:
                battle.global_turn = self.turn
                if battle.start_battle_turn():
                    active_battles.append(battle)

        self.map_phase_started = False
        self.battle_phase_pending = bool(active_battles)
        if not self.battle_phase_pending:
            self.start_action_layers()
        else:
            self.current_ap_layer = None
            self.non_battle_order = []
        self.update_visibility()

    def start_action_layers(self):
        available_characters = [
            character
            for character in self.characters
            if (
                not character.in_battle
                and character.can_act_on_turn(self.turn)
            )
        ]
        if not self.global_action_order:
            self.global_action_order = self.initiative_manager.determine_order(
                available_characters
            )
        self.non_battle_order = [
            character
            for character in self.global_action_order
            if character in available_characters
        ]
        # 兼容回合中临时加入、或直接从测试/API启动地图阶段的角色。
        for character in available_characters:
            if character not in self.non_battle_order:
                self.non_battle_order.append(character)
        self.current_ap_layer = 1
        self.completed_checkpoints = []
        self.checkpoint_results = {1: [], 2: []}
        self.layer_execution = None
        self.waiting_encounters = list(self.teleport_encounters)
        self.teleport_encounters = []
        self.paused_movement_action = None
        self.map_phase_started = True
        self.battle_phase_pending = False
        self.travel_join_requests = {1: [], 2: []}
        self.travel_layer_prepared = set()
        self.ap_start_positions = {
            1: {
                character: character.position
                for character in available_characters
            },
            2: {},
        }
        self.refresh_travel_groups()
        self.refresh_ride_groups()
        if self.game_manager is not None:
            self.game_manager.command_spell_transfer_manager.prepare_turn(self)
        return self.non_battle_order

    def refresh_travel_groups(self):
        groups = []
        for character in self.characters:
            group = getattr(character, "travel_group", None)
            if group is not None and group not in groups:
                groups.append(group)
        for group in groups[:]:
            if not group.validate(self.non_battle_order):
                groups.remove(group)
        self.travel_groups = groups
        return list(self.travel_groups)

    def refresh_ride_groups(self):
        groups = []
        for character in self.characters:
            group = (
                getattr(character, "ride_group", None)
                or getattr(character, "carried_by", None)
            )
            if group is not None and group not in groups:
                groups.append(group)
        for group in groups[:]:
            if not group.validate():
                groups.remove(group)
        self.ride_groups = groups
        return list(groups)

    def invite_to_ride(self, rider, passenger, *, accepted=False):
        if not accepted:
            return False
        group = create_ride_group(rider, passenger)
        if group is None:
            return False
        if group not in self.ride_groups:
            self.ride_groups.append(group)
        self.refresh_travel_groups()
        self.update_visibility()
        return group

    def leave_ride_group(self, character):
        group = (
            getattr(character, "carried_by", None)
            or getattr(character, "ride_group", None)
        )
        if group is None:
            return False
        if character is group.rider:
            result = group.dissolve()
        else:
            result = group.remove_passenger(character)
        self.refresh_ride_groups()
        return result

    def ap1_is_unfinished(self, character):
        if not self.map_phase_started:
            return True
        if 1 in self.completed_checkpoints:
            return False
        if self.current_ap_layer != 1:
            return False
        if self.layer_execution is None:
            return True
        execution = self.layer_execution
        for index, action in enumerate(execution["actions"]):
            if action.actor is character:
                return index >= execution["index"]
        return character not in self.layer_actors[1]

    def _discard_planned_layers(self, character, layers):
        layers = set(layers)
        self.actions[:] = [
            action for action in self.actions
            if not (action.actor is character and action.ap_layer in layers)
        ]
        for layer in layers:
            self.action_layers[layer][:] = [
                action for action in self.action_layers[layer]
                if action.actor is not character
            ]
            self.layer_actors[layer].discard(character)
            self.checkpoint_actions[layer][:] = [
                action for action in self.checkpoint_actions[layer]
                if action.actor is not character
            ]
        if self.layer_execution is not None:
            index = self.layer_execution["index"]
            prefix = self.layer_execution["actions"][:index]
            suffix = [
                action for action in self.layer_execution["actions"][index:]
                if not (action.actor is character and action.ap_layer in layers)
            ]
            self.layer_execution["actions"] = prefix + suffix

    def register_battle_exit_to_map(self, character, grant_full_ap):
        if character not in self.non_battle_order:
            self.non_battle_order.append(character)
        if grant_full_ap:
            self._discard_planned_layers(character, {1, 2})
        else:
            self.layer_actors[1].add(character)
            self.layer_actors[2].add(character)

    def replan_after_map_teleport(self, character):
        """Invalidate only plans which may be chosen again at this timing."""
        if not self.map_phase_started:
            return {"replan": ()}
        current = self.current_ap_layer
        if current == 1 and 1 not in self.completed_checkpoints:
            execution = self.layer_execution
            if execution is None:
                layers = {1, 2}
            else:
                indices = [
                    index for index, action in enumerate(execution["actions"])
                    if action.actor is character
                ]
                not_started = bool(indices) and min(indices) > execution["index"]
                layers = {1, 2} if not_started else {2}
                if indices and execution["index"] in indices:
                    action = execution["actions"][execution["index"]]
                    state = getattr(action, "movement_state", None)
                    if state is not None:
                        state.paused = True
                        state.finished = True
                        state.remaining_movement = 0
            self._discard_planned_layers(character, layers)
            return {"replan": tuple(sorted(layers))}
        if current == 2 and 2 not in self.completed_checkpoints:
            execution = self.layer_execution
            if execution is None:
                self._discard_planned_layers(character, {2})
                return {"replan": (2,)}
            indices = [
                index for index, action in enumerate(execution["actions"])
                if action.actor is character
            ]
            if not indices or min(indices) >= execution["index"]:
                self._discard_planned_layers(character, {2})
                return {"replan": (2,)}
        return {"replan": ()}

    def queue_teleport_encounters(self, encounters):
        for encounter in encounters:
            self.add_encounter(encounter)
            if encounter not in self.teleport_encounters:
                self.teleport_encounters.append(encounter)
        if self.map_phase_started:
            for encounter in self.teleport_encounters:
                if encounter not in self.waiting_encounters:
                    self.waiting_encounters.append(encounter)
            self.teleport_encounters = []

    def leave_travel_group(self, character):
        group = getattr(character, "travel_group", None)
        if group is None:
            return False
        result = group.remove_member(character, self.non_battle_order)
        self.refresh_travel_groups()
        return result

    def transfer_travel_leader(self, actor, new_leader):
        group = getattr(actor, "travel_group", None)
        if group is None:
            return False
        return group.transfer_leader(actor, new_leader, self.turn)

    def has_pending_travel_join(self, actor, ap_layer):
        return any(
            request.actor is actor and not request.resolved
            for request in self.travel_join_requests[ap_layer]
        )

    def submit_travel_join(self, actor, target, ap_layer):
        if ap_layer not in self.ACTION_LAYERS:
            raise ValueError("加入同行只能在AP1或AP2提出")
        if actor is target:
            return False
        if self.has_pending_travel_join(actor, ap_layer):
            return False
        request = TravelJoinRequest(actor, target, ap_layer)
        self.travel_join_requests[ap_layer].append(request)
        return request

    def _remove_layer_action(self, character, ap_layer):
        removed = []
        for action in self.action_layers[ap_layer][:]:
            if action.actor is not character:
                continue
            self.action_layers[ap_layer].remove(action)
            if action in self.actions:
                self.actions.remove(action)
            removed.append(action)
        reserves_layer = (
            ap_layer == 2
            and any(
                action.actor is character
                and self.uses_two_ap(action)
                for action in self.action_layers[1]
            )
        )
        if not reserves_layer:
            self.layer_actors[ap_layer].discard(character)
        return removed

    def resolve_travel_joins(self, ap_layer):
        if ap_layer not in self.travel_layer_prepared:
            self.ap_start_positions[ap_layer] = {
                character: character.position
                for character in self.characters
                if character.is_alive() and not character.in_battle
            }
        for request in self.travel_join_requests[ap_layer]:
            if request.resolved:
                continue
            actor = request.actor
            target = request.target
            if not actor.is_alive() or actor.in_battle:
                request.reason = "actor_unavailable"
            elif not target.is_alive() or target.in_battle:
                request.reason = "target_unavailable"
            elif getattr(actor, "travel_group", None) is not None:
                request.reason = "actor_already_in_group"
            elif actor.position is None or actor.position is not target.position:
                request.reason = "different_ap_start_position"
            else:
                group = getattr(target, "travel_group", None)
                existing_members = (
                    [target] if group is None else list(group.members)
                )
                leader = target if group is None else group.leader
                prospective_speed = min(
                    (
                        member.ride_group.get_movement_conversion(ap_layer)
                        if getattr(member, "ride_group", None) is not None
                        else member.get_effective_move_conversion(
                            ap_layer=ap_layer,
                        )
                    )
                    for member in [*existing_members, actor]
                )
                leader_action = self._get_submitted_action(leader, ap_layer)
                route_too_long = (
                    isinstance(leader_action, MovementAction)
                    and len(leader_action.path) - 1 > prospective_speed
                )
                if route_too_long:
                    request.reason = "leader_route_exceeds_group_movement"
                    request.resolved = True
                    continue
                if group is None:
                    group = TravelGroup(target)
                if group.add_member(actor, position=actor.position):
                    request.success = True
                    request.group = group
                    if group not in self.travel_groups:
                        self.travel_groups.append(group)
                    if ap_layer == 1:
                        self._remove_layer_action(actor, 2)
                else:
                    if not group.active:
                        group.dissolve()
                    request.reason = "travel_group_requirements_failed"
            request.resolved = True

        self.refresh_travel_groups()
        self._detach_independent_movers(ap_layer)
        self.update_visibility()
        self.travel_layer_prepared.add(ap_layer)
        return list(self.travel_join_requests[ap_layer])

    def _get_submitted_action(self, character, ap_layer):
        return next(
            (
                action
                for action in self.action_layers[ap_layer]
                if action.actor is character
            ),
            None,
        )

    def get_group_leader_movement_action(self, character, ap_layer):
        controller = get_movement_controller(character)
        if controller is character:
            return None
        action = self._get_submitted_action(controller, ap_layer)
        if action is not None and action.action_id == "move":
            return action
        return None

    def _detach_independent_movers(self, ap_layer):
        for group in self.travel_groups[:]:
            leader_action = self._get_submitted_action(group.leader, ap_layer)
            if leader_action is not None and leader_action.action_id == "move":
                continue
            for member in group.members[:]:
                if member is group.leader:
                    continue
                action = self._get_submitted_action(member, ap_layer)
                if action is not None and action.action_id == "move":
                    group.remove_member(member, self.non_battle_order)
        self.refresh_travel_groups()

    def prepare_travel_layer(self, ap_layer):
        result = self.resolve_travel_joins(ap_layer)
        self.refresh_ride_groups()
        return result

    def add_action(self, action, ap_layer=None, decision_provider=None):
        if ap_layer is None:
            ap_layer = self.current_ap_layer or 1
        if ap_layer not in self.ACTION_LAYERS:
            raise ValueError("AP行动层只能是1或2")
        if ap_layer in self.completed_checkpoints:
            raise ValueError(f"AP{ap_layer} checkpoint已经结束")
        if action.actor in self.layer_actors[ap_layer]:
            raise ValueError(
                f"{action.actor.name}在AP{ap_layer}层已经提交过行动"
            )
        if action.actor.in_battle:
            raise ValueError("战斗中的角色不能提交非战斗AP行动")
        if (
            isinstance(action, MovementAction)
            and getattr(action.actor, "carried_by", None) is not None
        ):
            action.actor.detach_ride_group()
        active_transfer = getattr(
            action.actor,
            "command_spell_transfer",
            None,
        )
        if (
            active_transfer is not None
            and action.action_id != "command_spell_transfer"
            and self.game_manager is not None
        ):
            self.game_manager.command_spell_transfer_manager.interrupt(
                active_transfer,
                f"other_action:{action.action_id}",
            )
        if (
            ap_layer == 1
            and action.actor.ap1_forfeited_turn == self.turn
        ):
            raise ValueError(f"{action.actor.name}本回合只能使用AP2")
        if (
            ap_layer == 1
            and action.actor.forced_move_turn == self.turn
            and action.action_id != "move"
        ):
            raise ValueError(f"{action.actor.name}的AP1必须选择移动")
        if self.uses_two_ap(action):
            if ap_layer != 1:
                raise ValueError(f"{action.action_id}只能在AP1行动层使用")
            if action.actor in self.layer_actors[2]:
                raise ValueError("该2AP行动与已提交的AP2行动冲突")
        if (
            action.action_id in self.MOVEMENT_ACTION_IDS
            and action.actor.movement_locked
        ):
            raise ValueError(
                f"{action.actor.name}已被BattleRequest锁定，不能移动"
            )

        action.ap_layer = ap_layer
        action.game_turn = self.turn
        action.game_manager = self.game_manager
        if (
            getattr(action.actor, "casting_state", None) is not None
            and action.action_id
            not in {"chant", "release", "interrupt_casting"}
        ):
            action.actor.interrupt_casting(
                reason=f"other_action:{action.action_id}"
            )
        if (
            getattr(action.actor, "resting", False)
            and action.action_id != "rest"
        ):
            action.actor.cancel_rest()
        if not getattr(action, "characters", None) and action.action_id in {
            "perceive",
            "investigate",
            "hide",
        }:
            action.characters = list(self.characters)
        self.actions.append(action)
        self.action_layers[ap_layer].append(action)
        self.layer_actors[ap_layer].add(action.actor)
        if self.uses_two_ap(action):
            self.layer_actors[2].add(action.actor)
        if action.action_id == "command_spell_transfer":
            target = action.target
            if target is None or target is action.actor:
                raise ValueError("令咒移植缺少合法接收方")
            for layer in self.ACTION_LAYERS:
                self._remove_layer_action(target, layer)
                self.layer_actors[layer].add(target)
        if action.action_id == "direct_attack" and decision_provider is not None:
            action.submission_result = ActionResolver().resolve(
                action,
                decision_provider,
            )
            action.resolved_on_submission = True
        return True

    def add_movement_action(self, actor, path, ap_layer=None):
        # A passenger may choose an independent move only by getting off.
        if getattr(actor, "carried_by", None) is not None:
            actor.detach_ride_group()
        travel_group = getattr(actor, "travel_group", None)
        if travel_group is not None and travel_group.leader is not actor:
            # Preserve normal同行 semantics: this plan detaches the follower
            # only if the leader does not submit a move for the same layer.
            movement_limit = actor.get_effective_move_conversion(
                ap_layer=ap_layer,
            )
        else:
            _, movement_limit = get_movement_formation(
                actor,
                ap_layer=ap_layer,
            )
        action = MovementAction(
            actor,
            path,
            movement_limit=movement_limit,
            ap_layer=ap_layer,
        )
        self.add_action(action, ap_layer=ap_layer)
        return action

    def add_encounter(self, encounter):
        if encounter not in self.pending_encounters:
            self.pending_encounters.append(encounter)
        return True

    def add_pending_encounter(self, encounter):
        if not encounter.pending_battle and not encounter.battle_requests:
            return False
        return self.add_encounter(encounter)

    def remove_character(self, character, *, add_to_dead=True):
        """从所有尚未结算的回合状态中清除角色。"""
        if character in self.characters:
            self.characters.remove(character)
        if add_to_dead and character not in self.dead_characters:
            self.dead_characters.append(character)
        self.leave_travel_group(character)

        self.current_order = [
            actor for actor in self.current_order if actor is not character
        ]
        self.global_action_order = [
            actor
            for actor in self.global_action_order
            if actor is not character
        ]
        self.non_battle_order = [
            actor for actor in self.non_battle_order if actor is not character
        ]

        self.actions[:] = [
            action
            for action in self.actions
            if action.actor is not character
            and getattr(action, "target", None) is not character
        ]
        for ap_layer in self.ACTION_LAYERS:
            self.action_layers[ap_layer][:] = [
                action
                for action in self.action_layers[ap_layer]
                if action.actor is not character
                and getattr(action, "target", None) is not character
            ]
            self.layer_actors[ap_layer].discard(character)
            self.checkpoint_actions[ap_layer][:] = [
                action
                for action in self.checkpoint_actions[ap_layer]
                if action.actor is not character
                and getattr(action, "target", None) is not character
            ]
            self.checkpoint_results[ap_layer][:] = [
                (action, result)
                for action, result in self.checkpoint_results[ap_layer]
                if action.actor is not character
            ]
            self.travel_join_requests[ap_layer][:] = [
                request
                for request in self.travel_join_requests[ap_layer]
                if request.actor is not character
                and request.target is not character
            ]
            self.ap_start_positions[ap_layer].pop(character, None)

        if self.layer_execution is not None:
            execution = self.layer_execution
            current_index = execution["index"]
            completed_and_current = execution["actions"][:current_index + 1]
            future = [
                action
                for action in execution["actions"][current_index + 1:]
                if action.actor is not character
                and getattr(action, "target", None) is not character
            ]
            execution["actions"] = completed_and_current + future

        for target in self.characters:
            report_discarded_attacks([
                attack for attack in target.pending_attacks
                if attack.source is character or attack.target is character
            ], "character_removed")
            target.pending_attacks[:] = [
                attack
                for attack in target.pending_attacks
                if attack.source is not character
                and attack.target is not character
            ]
        report_discarded_attacks(character.pending_attacks, "character_removed")
        character.pending_attacks.clear()

        removed_direct_requests = [
            request
            for request in self.pending_battle_requests
            if request.actor is character or request.target is character
        ]
        for request in removed_direct_requests:
            if getattr(request.actor, "movement_lock_source", None) is request:
                request.actor.clear_movement_lock()
        self.pending_battle_requests = [
            request
            for request in self.pending_battle_requests
            if request not in removed_direct_requests
        ]

        for encounter in self.pending_encounters[:]:
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
            encounter.movement_states = [
                state
                for state in encounter.movement_states
                if state.actor is not character
            ]
            encounter.awareness = {
                actor: [
                    target
                    for target in targets
                    if target is not character
                ]
                for actor, targets in encounter.awareness.items()
                if actor is not character
            }
            encounter.awareness = {
                actor: targets
                for actor, targets in encounter.awareness.items()
                if targets
            }
            encounter.aware_characters = list(encounter.awareness)
            encounter.movement_decisions = {
                actor: decision
                for actor, decision in encounter.movement_decisions.items()
                if actor is not character
            }
            encounter.decisions = {
                pair: decision
                for pair, decision in encounter.decisions.items()
                if character not in pair
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
            encounter.check_resolution()
            if (
                len(encounter.characters) < 2
                and encounter in self.pending_encounters
            ):
                self.pending_encounters.remove(encounter)
                if encounter in self.waiting_encounters:
                    self.waiting_encounters.remove(encounter)

        return True

    def declare_battle(self, encounter, actor, target=None):
        if self.current_ap_layer not in self.ACTION_LAYERS:
            raise ValueError("只能在AP1或AP2行动层提交BattleRequest")
        self.add_encounter(encounter)
        result = encounter.choose_battle(
            actor,
            target=target,
            ap_layer=self.current_ap_layer,
        )
        self.lock_resolved_encounter_movement(encounter)
        return result

    def submit_battle_join(self, actor, target, ap_layer=None):
        if ap_layer is None:
            ap_layer = self.current_ap_layer
        if ap_layer not in self.ACTION_LAYERS:
            return False
        if (
            not actor.is_alive()
            or actor.in_battle
            or actor.position is None
            or target is actor
            or not target.is_alive()
            or not target.in_battle
            or target.position is not actor.position
            or actor.is_ally(target)
        ):
            return False

        from game.turn.battle_request import BattleRequest

        request = BattleRequest(
            actor=actor,
            target=target,
            submitted_layer=ap_layer,
        )
        self.pending_battle_requests.append(request)
        actor.lock_movement(ap_layer, request)
        return request

    def continue_encounter(self, encounter, character, target=None):
        self.add_encounter(encounter)
        result = encounter.choose_continue(character, target=target)
        self.lock_resolved_encounter_movement(encounter)
        return result

    def replan_encounter(
        self,
        encounter,
        character,
        path=None,
        target=None,
    ):
        if self.current_ap_layer != 1:
            raise ValueError("只有AP1 Encounter可以改写AP2移动计划")
        if (
            self.paused_movement_action is None
            or self.paused_movement_action.actor is not character
        ):
            raise ValueError("只有当前因Encounter暂停的移动者可以改道")
        self.add_encounter(encounter)
        result = encounter.choose_replan(character, target=target)
        if not result:
            return False

        self.replace_ap2_action(character, path)
        return True

    def replace_ap2_action(self, character, path=None):
        existing = [
            action
            for action in self.action_layers[2]
            if action.actor is character
        ]
        for action in existing:
            self.action_layers[2].remove(action)
            if action in self.actions:
                self.actions.remove(action)
        self.layer_actors[2].discard(character)

        if path is None:
            from game.action.action import Action
            replacement = Action(character, "pass")
            return self.add_action(replacement, ap_layer=2)
        return self.add_movement_action(character, path, ap_layer=2)

    def lock_resolved_encounter_movement(self, encounter):
        if not encounter.resolved or not encounter.enter_battle:
            return False
        for request in encounter.battle_requests:
            request.actor.lock_movement(self.current_ap_layer, request)
            request.target.lock_movement(self.current_ap_layer, request)
        return True

    def start_pending_battles(self):
        for encounter in self.pending_encounters[:]:
            if not encounter.pending_battle:
                continue
            request_characters = []
            for request in encounter.battle_requests:
                for character in (request.actor, request.target):
                    if character not in request_characters:
                        request_characters.append(character)

            related_battles = []
            for character in request_characters:
                battle = getattr(character, "current_battle", None)
                if battle is not None and not battle.ended and battle not in related_battles:
                    related_battles.append(battle)

            if related_battles:
                battle = related_battles[0]
                newcomers = []
                for other_battle in related_battles[1:]:
                    for character in other_battle.participants:
                        if (
                            character not in battle.participants
                            and character not in newcomers
                        ):
                            newcomers.append(character)
                    battle.effects.extend(other_battle.effects)
                    battle.pending_order_changes.extend(
                        other_battle.pending_order_changes
                    )
                    battle.active_order_changes.extend(
                        other_battle.active_order_changes
                    )
                    battle.absorb_combat_links(other_battle)
                    other_battle.participants.clear()
                    other_battle.initial_order.clear()
                    other_battle.current_order.clear()
                    other_battle.round_order_snapshot.clear()
                    other_battle.pending_order_changes.clear()
                    other_battle.active_order_changes.clear()
                    other_battle.ended = True
                    other_battle.end_reason = "merged"
                for character in request_characters:
                    if (
                        character not in battle.participants
                        and character not in newcomers
                    ):
                        newcomers.append(character)
                battle.add_participants(newcomers)
                for request in encounter.battle_requests:
                    battle.add_combat_link(
                        request.actor,
                        request.target,
                        source=request,
                    )
                battle.refresh_participant_order()
            else:
                battle = BattleManager(request_characters, auto_link=False)
                for request in encounter.battle_requests:
                    battle.add_combat_link(
                        request.actor,
                        request.target,
                        source=request,
                    )
                battle.start_battle()
                self.battles.append(battle)

            for actor, target in encounter.get_ambush_pairs():
                effect = {
                    "effect_type": "add_simple_round",
                    "effect_data": {
                        "trigger_phase": "battle_start",
                        "attack_roll_bonus": 5,
                        "attack_stat": "physical_attack",
                        "damage_type": "physical",
                        "is_ambush": True,
                        "source": "ambush",
                    },
                }
                battle.add_effect(effect, actor, target)
            encounter.pending_battle = False
            self.pending_encounters.remove(encounter)

        request_batches = []
        for request in self.pending_battle_requests[:]:
            if not request.locked:
                continue
            actor = request.actor
            target = request.target
            if not actor.is_alive() or not target.is_alive():
                actor.clear_movement_lock()
                self.pending_battle_requests.remove(request)
                continue
            destination = getattr(target, "current_battle", None)
            if destination is not None and destination.ended:
                destination = None
            key = destination if destination is not None else target
            batch = next(
                (item for item in request_batches if item["key"] is key),
                None,
            )
            if batch is None:
                batch = {"key": key, "battle": destination, "requests": []}
                request_batches.append(batch)
            batch["requests"].append(request)

        for batch in request_batches:
            requests = batch["requests"]
            battle = batch["battle"]
            request_characters = []
            for request in requests:
                for character in (request.actor, request.target):
                    if character not in request_characters:
                        request_characters.append(character)

            if battle is None:
                battle = next(
                    (
                        getattr(character, "current_battle", None)
                        for character in request_characters
                        if getattr(character, "current_battle", None) is not None
                        and not character.current_battle.ended
                    ),
                    None,
                )
            if battle is None:
                battle = BattleManager(request_characters, auto_link=False)
                for request in requests:
                    battle.add_combat_link(
                        request.actor,
                        request.target,
                        source=request,
                    )
                battle.start_battle()
                self.battles.append(battle)
            else:
                battle.add_participants(request_characters)
                for request in requests:
                    battle.add_combat_link(
                        request.actor,
                        request.target,
                        source=request,
                    )
                battle.refresh_participant_order()

            for request in requests:
                if request.is_ambush:
                    effect = {
                        "effect_type": "add_simple_round",
                        "effect_data": {
                            "trigger_phase": "battle_start",
                            "attack_roll_bonus": 5,
                            "attack_stat": "physical_attack",
                            "damage_type": "physical",
                            "is_ambush": True,
                            "source": "ambush",
                        },
                    }
                    battle.add_effect(effect, request.actor, request.target)
                self.pending_battle_requests.remove(request)

    def get_layer_actions(self, ap_layer):
        initiative_index = {
            character: index
            for index, character in enumerate(self.non_battle_order)
        }
        return sorted(
            self.action_layers[ap_layer],
            key=lambda action: (
                # Direct attacks form a pre-movement window. Normally the UI
                # resolves them on submission; this also protects API callers.
                0 if action.action_id == "direct_attack" else 1,
                initiative_index.get(
                    action.actor,
                    len(initiative_index),
                ),
            ),
        )

    def get_action_ignore_reason(self, action):
        if not action.actor.is_alive():
            return "actor_not_alive"
        if action.actor.in_battle:
            return "actor_entered_battle"
        leader_movement = self.get_group_leader_movement_action(
            action.actor,
            self.current_ap_layer,
        )
        if (
            get_movement_controller(action.actor) is not action.actor
            and leader_movement is not None
        ):
            return "following_travel_group"
        if (
            action.action_id in self.MOVEMENT_ACTION_IDS
            and action.actor.movement_locked
        ):
            return "movement_locked_by_battle_request"
        restriction_reasons = action_restriction_reasons(
            action,
            phase=f"AP{self.current_ap_layer}",
            battle=None,
        )
        if restriction_reasons:
            return f"action_restricted:{restriction_reasons[0]}"
        return None

    def ignore_action(self, action, reason, ap_layer):
        action.ignored = True
        action.ignored_reason = reason
        if (
            reason == "following_travel_group"
            and self.uses_two_ap(action)
        ):
            self.layer_actors[2].discard(action.actor)
        return {
            "ignored": True,
            "reason": reason,
            "ap_layer": ap_layer,
        }

    def prepare_automatic_rests(self):
        if self.current_ap_layer != 1:
            return
        from game.character.masters import Master
        from game.action.action import Action

        for character in self.non_battle_order:
            if not isinstance(character, Master) or not character.resting:
                continue
            has_submitted_action = any(
                action.actor is character
                for layer in self.ACTION_LAYERS
                for action in self.action_layers[layer]
            )
            if has_submitted_action:
                continue
            if character.position is None or not character.position.is_building:
                character.cancel_rest()
                continue
            self.add_action(
                Action(character, "rest", automatic=True),
                ap_layer=1,
            )

    def execute_action_layer(self, ap_layer=None, decision_provider=None):
        if self.battle_phase_pending:
            raise RuntimeError("必须先完成本回合战斗阶段")
        if ap_layer is None:
            ap_layer = self.current_ap_layer
        if ap_layer not in self.ACTION_LAYERS:
            return []
        if self.current_ap_layer != ap_layer:
            raise ValueError(f"当前不是AP{ap_layer}行动层")

        if self.game_manager is not None:
            for character in self.non_battle_order:
                if (
                    character.is_alive()
                    and not character.in_battle
                    and character.can_act_on_turn(self.turn)
                ):
                    self.game_manager.delay_manager.resolve_checkpoint(
                        self.turn,
                        f"AP{ap_layer}",
                        character=character,
                        decision_provider=decision_provider,
                    )

        self.prepare_travel_layer(ap_layer)

        if self.waiting_encounters:
            return self.get_waiting_encounter_result()

        if self.layer_execution is None:
            if ap_layer == 1:
                self.prepare_automatic_rests()
            self.layer_execution = {
                "ap_layer": ap_layer,
                "actions": self.get_layer_actions(ap_layer),
                "index": 0,
                "results": [],
                "decision_provider": decision_provider,
            }
        elif self.layer_execution["ap_layer"] != ap_layer:
            raise RuntimeError("另一个AP行动层尚未执行完毕")

        return self.advance_action_layer()

    def advance_action_layer(self):
        execution = self.layer_execution
        ap_layer = execution["ap_layer"]
        actions = execution["actions"]
        resolver = ActionResolver()

        while execution["index"] < len(actions):
            action = actions[execution["index"]]
            if getattr(action, "resolved_on_submission", False):
                execution["results"].append((
                    action,
                    getattr(action, "submission_result", None),
                ))
                execution["index"] += 1
                continue
            ignore_reason = self.get_action_ignore_reason(action)
            if ignore_reason is not None:
                execution["results"].append((
                    action,
                    self.ignore_action(
                        action,
                        ignore_reason,
                        ap_layer,
                    ),
                ))
                execution["index"] += 1
                continue

            if isinstance(action, MovementAction):
                waiting_result = self.execute_movement_action(action)
                if waiting_result is not None:
                    return waiting_result
                continue

            action.defer_to_checkpoint = action.action_id in {
                "perceive",
                "investigate",
                "wish",
            }
            result = resolver.resolve(
                action,
                execution["decision_provider"],
            )
            execution["results"].append((action, result))
            if action.checkpoint_pending:
                self.checkpoint_actions[ap_layer].append(action)
            execution["index"] += 1

            if action.action_id == "move" and result:
                encounters = self.movement_resolver.check_encounter(
                    self.characters,
                    [],
                )
                if encounters:
                    return self.pause_for_encounters(encounters, None)

        results = execution["results"]
        self.layer_execution = None
        self.complete_checkpoint(
            ap_layer,
            decision_provider=execution["decision_provider"],
        )
        return results

    def execute_movement_action(self, action):
        execution = self.layer_execution
        if not action.prepare(self.movement_resolver):
            execution["results"].append((action, False))
            execution["index"] += 1
            return None

        encounters = self.movement_resolver.resolve(
            [action.movement_state],
            self.non_battle_order,
            self.characters,
            decision_provider=execution["decision_provider"],
        )
        if encounters:
            return self.pause_for_encounters(encounters, action)

        execution["results"].append((action, True))
        execution["index"] += 1
        return None

    def pause_for_encounters(self, encounters, movement_action):
        self.waiting_encounters = list(encounters)
        self.paused_movement_action = movement_action
        for encounter in encounters:
            self.add_encounter(encounter)
        return self.get_waiting_encounter_result()

    def get_waiting_encounter_result(self):
        return {
            "status": "waiting_for_encounter",
            "ap_layer": self.current_ap_layer,
            "encounters": list(self.waiting_encounters),
            "results_so_far": list(
                self.layer_execution["results"]
                if self.layer_execution is not None
                else []
            ),
        }

    def resume_action_layer(self):
        if not self.waiting_encounters:
            return self.execute_action_layer(self.current_ap_layer)
        if any(not encounter.resolved for encounter in self.waiting_encounters):
            return self.get_waiting_encounter_result()

        encounters = list(self.waiting_encounters)
        for encounter in encounters:
            self.lock_resolved_encounter_movement(encounter)

        movement_action = self.paused_movement_action
        should_replan = (
            movement_action is not None
            and any(
                movement_action.actor in encounter.replan_characters
                and not encounter.enter_battle
                for encounter in encounters
            )
        )
        self.waiting_encounters = []
        self.paused_movement_action = None

        if movement_action is not None:
            if movement_action.actor.movement_locked or should_replan:
                movement_action.movement_state.paused = True
                movement_action.movement_state.finished = True
                movement_action.movement_state.remaining_movement = 0
                self.layer_execution["results"].append((
                    movement_action,
                    {
                        "stopped": True,
                        "reason": (
                            "battle_request_at_encounter"
                            if movement_action.actor.movement_locked
                            else "replanned_after_encounter"
                        ),
                        "position": movement_action.actor.position,
                    },
                ))
                self.layer_execution["index"] += 1
            else:
                waiting_result = self.execute_movement_action(movement_action)
                if waiting_result is not None:
                    return waiting_result

        return self.advance_action_layer()

    def complete_checkpoint(self, ap_layer, decision_provider=None):
        if self.waiting_encounters:
            raise RuntimeError("Encounter尚未完成，不能进入AP checkpoint")
        checkpoint_results = []
        for action in self.checkpoint_actions[ap_layer]:
            checkpoint_results.append(
                (action, action.resolve_checkpoint(decision_provider))
            )
        self.checkpoint_results[ap_layer] = checkpoint_results

        self.refresh_travel_groups()
        self.update_visibility()
        for encounter in self.pending_encounters[:]:
            encounter.lock_battle_requests(ap_layer)
            self.lock_battle_request_movement(encounter, ap_layer)
            if encounter.resolved and not encounter.enter_battle:
                self.pending_encounters.remove(encounter)
        for request in self.pending_battle_requests:
            if request.submitted_layer == ap_layer:
                request.lock(ap_layer)

        self.completed_checkpoints.append(ap_layer)
        self.current_ap_layer = 2 if ap_layer == 1 else None
        if self.current_ap_layer == 2:
            self.ap_start_positions[2] = {
                character: character.position
                for character in self.characters
                if character.is_alive() and not character.in_battle
            }
        if self.game_manager is not None:
            self.game_manager.on_ap_checkpoint(ap_layer)
        return checkpoint_results

    def lock_battle_request_movement(self, encounter, ap_layer):
        for request in encounter.battle_requests:
            if request.locked_layer != ap_layer:
                continue
            request.actor.lock_movement(ap_layer, request)
            request.target.lock_movement(ap_layer, request)

    def execute_actions(self, decision_provider=None):
        results = []
        while self.current_ap_layer in self.ACTION_LAYERS:
            layer_result = self.execute_action_layer(
                self.current_ap_layer,
                decision_provider=decision_provider,
            )
            if isinstance(layer_result, dict):
                return layer_result
            results.extend(layer_result)
        return results

    def end_turn(self, decision_provider=None):
        if self.waiting_encounters:
            raise RuntimeError("Encounter尚未完成，不能结束回合")
        if self.battle_phase_pending:
            for battle in self.battles:
                if (
                    not battle.ended
                    and battle.current_character is None
                    and battle.current_phase == "turn_end"
                ):
                    # 兼容逐阶段手动驱动Battle的调用方式。
                    battle.current_phase = "round_ended"
                    battle.finish_battle_round()
            battle_phase_finished = all(
                battle.ended or battle.current_phase == "round_ended"
                for battle in self.battles
            )
            if not battle_phase_finished:
                raise RuntimeError("战斗阶段尚未完成，不能结束全局回合")
            self.battle_phase_pending = False
            if not self.map_phase_started:
                self.start_action_layers()
                self.update_visibility()
        if self.current_ap_layer in self.ACTION_LAYERS:
            self.execute_actions(decision_provider=decision_provider)

        if self.game_manager is not None:
            self.game_manager.relationship_manager.prepare_join_relationships(
                decision_provider
            )

        if self.game_manager is not None:
            self.game_manager.delay_manager.resolve_turn_end_fallback(
                self.turn,
                decision_provider=decision_provider,
            )
            self.game_manager.resolve_turn_end_event(self.turn, decision_provider=decision_provider)
        else:
            for character in [*self.characters, *self.dead_characters]:
                character.update_modifiers("global_turn_end", turn_number=self.turn)

        for character in self.characters[:]:
            character.advance_casting(
                self.turn,
                decision_provider=decision_provider,
            )
            character.end_global_turn(self.turn)

        if self.game_manager is not None:
            self.game_manager.on_turn_end(self.turn, emit_event=False)

        self.update_visibility()

        self.actions.clear()
        self.action_layers = {1: [], 2: []}
        self.layer_actors = {1: set(), 2: set()}
        self.checkpoint_actions = {1: [], 2: []}
        self.travel_join_requests = {1: [], 2: []}
        self.travel_layer_prepared = set()
        self.ap_start_positions = {1: {}, 2: {}}

    def update_visibility(self):
        if self.game_manager is not None:
            self.game_manager.refresh_fields()
        for character in self.characters:
            character.update_visibility(self.characters)
        if self.game_manager is not None:
            self.game_manager.information_manager.refresh_trap_sharing()

    def run_battles(self, decision_provider=None):
        if decision_provider is None:
            from game.turn.decision import TerminalDecisionProvider
            decision_provider = TerminalDecisionProvider()

        for battle in self.battles:
            if not battle.ended:
                battle.run_battle_turn(decision_provider)
        # A command-spell teleport can append a participant to a battle whose
        # ordinary slot was already processed earlier in this loop.
        for battle in self.battles:
            if (
                not battle.ended
                and battle.current_character is not None
                and battle.current_phase != "round_ended"
            ):
                battle.run_battle_turn(decision_provider)
        self.battle_phase_pending = False
        if self.game_manager is not None:
            self.game_manager.refresh_grail_state()
        if not self.map_phase_started:
            self.start_action_layers()
            self.update_visibility()

    def start_battle(self):
        self.current_order = (self.initiative_manager.determine_order(self.characters).copy())


