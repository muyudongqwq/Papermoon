from game.action.action import Action
from game.action.action_list import (
    ActionContext,
    ActionListBuilder,
    PathPlanner,
    is_free_immediate_skill_entry,
)
from game.action.action_resolver import ActionResolver
from game.map.movement import MovementAction
from game.map.ride_group import get_movement_controller, get_movement_formation
from game.skill.skill_action import SkillAction
from game.skill.input_runtime import collect_skill_inputs
from game.turn.decision import (
    DecisionRefreshRequested,
    DecisionOption,
    DecisionRequest,
    NumericDecisionRequest,
)


class GameLoop:
    """Synchronous game orchestration shared by terminal and future clients.

    The caller supplies a decision provider; this loop never reads terminal
    input or formats terminal output. TurnManager and BattleManager retain
    ownership of all rule resolution.
    """

    def __init__(self, game_manager, decision_provider):
        self.game_manager = game_manager
        self.turn_manager = game_manager.turn_manager
        self.action_list_builder = ActionListBuilder()
        self.decision_provider = decision_provider
        self.game_manager.decision_provider = decision_provider
        self.planned_positions = {}
        self.planned_start_positions = {1: {}, 2: {}}

    def run(self):
        if not self.game_manager.started:
            self.game_manager.start_game()
        while not self.game_manager.check_game_end():
            self.run_global_turn()
        return self.get_result()

    def get_result(self):
        """Return the current outcome without displaying it."""
        return {
            "reason": self.game_manager.end_reason,
            "winners": list(self.game_manager.winners),
            "turn": self.turn_manager.turn,
        }

    def on_action_collected(self):
        """Adapter hook after an action choice is submitted or resolved."""

    def run_global_turn(self):
        if self.game_manager.check_game_end():
            return False
        self.turn_manager.start_turn()
        if self.turn_manager.battle_phase_pending:
            self.turn_manager.run_battles(self.decision_provider)
        if self.game_manager.check_game_end():
            return False

        self.collect_map_actions()
        self.execute_map_actions()
        if self.game_manager.check_game_end():
            return False
        self.turn_manager.end_turn(self.decision_provider)
        return not self.game_manager.check_game_end()

    def collect_map_actions(self):
        self.collect_travel_departures()
        self.planned_positions = {
            character: character.position
            for character in self.turn_manager.non_battle_order
        }
        self.planned_start_positions = {
            1: dict(self.planned_positions),
            2: dict(self.planned_positions),
        }
        planning_order = sorted(
            self.turn_manager.non_battle_order,
            key=lambda character: (
                1
                if get_movement_controller(character) is not character
                else 0,
                self.turn_manager.non_battle_order.index(character),
            ),
        )
        for character in planning_order:
            if not character.is_alive() or character.in_battle:
                continue
            if not self.should_follow_group_move(character, 1):
                self.collect_character_action(character, 1)
            self.planned_start_positions[2][character] = (
                self.planned_positions.get(character, character.position)
            )
            if character in self.turn_manager.layer_actors[2]:
                continue
            if self.turn_manager.has_pending_travel_join(character, 1):
                continue
            if not self.should_follow_group_move(character, 2):
                self.collect_character_action(character, 2)

    def collect_travel_departures(self):
        groups = self.turn_manager.refresh_travel_groups()
        departures = []
        for group in groups:
            for character in list(group.members):
                leave = self.decision_provider.choose(DecisionRequest(
                    character=character,
                    phase="AP1—同行",
                    prompt="",
                    options=(
                        DecisionOption(
                            "继续同行",
                            False,
                            ("follow", "继续"),
                        ),
                        DecisionOption(
                            "脱离同行",
                            True,
                            ("leave", "脱离"),
                        ),
                    ),
                ))
                if leave:
                    departures.append(character)
        for character in departures:
            self.turn_manager.leave_travel_group(character)

    def should_follow_group_move(self, character, ap_layer):
        if get_movement_controller(character) is character:
            return False
        return self.turn_manager.get_group_leader_movement_action(
            character,
            ap_layer,
        ) is not None

    def collect_character_action(self, character, ap_layer):
        phase = f"AP{ap_layer}"
        context = ActionContext(
            actor=character,
            phase=phase,
            turn_number=self.turn_manager.turn,
            turn_manager=self.turn_manager,
            characters=list(self.game_manager.characters),
            position_overrides=dict(
                self.planned_start_positions.get(ap_layer, {})
            ),
        )
        entries = self.action_list_builder.get_available_actions(context)
        if not entries:
            return None
        while True:
            if not entries:
                return None
            request = DecisionRequest(
                character=character,
                phase=phase,
                prompt="",
                allow_refresh=True,
                options=tuple(
                    DecisionOption(entry.name, entry, (entry.action_id,))
                    for entry in entries
                ),
            )
            try:
                entry = self.decision_provider.choose(request)
            except DecisionRefreshRequested:
                context = ActionContext(
                    actor=character,
                    phase=phase,
                    turn_number=self.turn_manager.turn,
                    turn_manager=self.turn_manager,
                    characters=list(self.game_manager.characters),
                    position_overrides=dict(
                        self.planned_start_positions.get(ap_layer, {})
                    ),
                )
                entries = self.action_list_builder.get_available_actions(context)
                continue
            if entry.action_id == "invite_carry":
                target = self.choose_target(
                    character,
                    entry.valid_targets,
                    ap_layer,
                )
                if target is None:
                    continue
                accepted = self.decision_provider.choose(DecisionRequest(
                    character=target,
                    phase=f"AP{ap_layer}—同乘",
                    prompt=f"{character.name}邀请你同乘，是否接受？",
                    options=(
                        DecisionOption("接受", True, ("accept", "接受")),
                        DecisionOption("拒绝", False, ("reject", "拒绝")),
                    ),
                ))
                if accepted:
                    self.turn_manager.invite_to_ride(
                        character,
                        target,
                        accepted=True,
                    )
                context = ActionContext(
                    actor=character,
                    phase=phase,
                    turn_number=self.turn_manager.turn,
                    turn_manager=self.turn_manager,
                    characters=list(self.game_manager.characters),
                    position_overrides=dict(
                        self.planned_start_positions.get(ap_layer, {})
                    ),
                )
                entries = self.action_list_builder.get_available_actions(context)
                continue
            if entry.action_id == "leave_carry":
                self.turn_manager.leave_ride_group(character)
                context = ActionContext(
                    actor=character,
                    phase=phase,
                    turn_number=self.turn_manager.turn,
                    turn_manager=self.turn_manager,
                    characters=list(self.game_manager.characters),
                    position_overrides=dict(
                        self.planned_start_positions.get(ap_layer, {})
                    ),
                )
                entries = self.action_list_builder.get_available_actions(context)
                continue
            if entry.action_id == "interrupt_casting":
                action = Action(character, "interrupt_casting")
                action.ap_layer = ap_layer
                action.game_turn = self.turn_manager.turn
                action.interrupt_casting()
                context = ActionContext(
                    actor=character,
                    phase=phase,
                    turn_number=self.turn_manager.turn,
                    turn_manager=self.turn_manager,
                    characters=list(self.game_manager.characters),
                    position_overrides=dict(
                        self.planned_start_positions.get(ap_layer, {})
                    ),
                )
                entries = self.action_list_builder.get_available_actions(
                    context
                )
                continue
            if entry.action_id == "join_travel_group":
                if character.casting_state is not None:
                    character.interrupt_casting(
                        reason="other_action:join_travel_group"
                    )
                target = self.choose_target(
                    character,
                    entry.valid_targets,
                    ap_layer,
                )
                if target is None:
                    continue
                submitted = self.turn_manager.submit_travel_join(
                    character,
                    target,
                    ap_layer,
                )
                if submitted:
                    self.on_action_collected()
                    target_group = getattr(target, "travel_group", None)
                    prospective_leader = (
                        target
                        if target_group is None
                        else target_group.leader
                    )
                    leader_action = self.turn_manager._get_submitted_action(
                        prospective_leader,
                        ap_layer,
                    )
                    if (
                        leader_action is not None
                        and leader_action.action_id == "move"
                    ):
                        return submitted
                context = ActionContext(
                    actor=character,
                    phase=phase,
                    turn_number=self.turn_manager.turn,
                    turn_manager=self.turn_manager,
                    characters=list(self.game_manager.characters),
                    position_overrides=dict(
                        self.planned_start_positions.get(ap_layer, {})
                    ),
                )
                entries = self.action_list_builder.get_available_actions(context)
                continue
            if entry.action_id == "transfer_travel_leader":
                if character.casting_state is not None:
                    character.interrupt_casting(
                        reason="other_action:transfer_travel_leader"
                    )
                target = self.choose_target(
                    character,
                    entry.valid_targets,
                    ap_layer,
                )
                if target is None:
                    continue
                self.turn_manager.transfer_travel_leader(character, target)
                context = ActionContext(
                    actor=character,
                    phase=phase,
                    turn_number=self.turn_manager.turn,
                    turn_manager=self.turn_manager,
                    characters=list(self.game_manager.characters),
                    position_overrides=dict(
                        self.planned_start_positions.get(ap_layer, {})
                    ),
                )
                entries = self.action_list_builder.get_available_actions(context)
                continue
            try:
                action = self.build_action(
                    character,
                    entry,
                    ap_layer,
                    context,
                )
            except DecisionRefreshRequested:
                context = ActionContext(
                    actor=character,
                    phase=phase,
                    turn_number=self.turn_manager.turn,
                    turn_manager=self.turn_manager,
                    characters=list(self.game_manager.characters),
                    position_overrides=dict(
                        self.planned_start_positions.get(ap_layer, {})
                    ),
                )
                entries = self.action_list_builder.get_available_actions(context)
                continue
            if action is None:
                continue
            if is_free_immediate_skill_entry(entry):
                action.ap_layer = ap_layer
                action.game_turn = self.turn_manager.turn
                action.game_manager = self.game_manager
                if getattr(character, "resting", False):
                    character.cancel_rest()
                if not ActionResolver().resolve(
                    action,
                    self.decision_provider,
                ):
                    raise RuntimeError(
                        f"{character.name}的即时技能{entry.name}未能执行"
                    )
                self.on_action_collected()
                context = ActionContext(
                    actor=character,
                    phase=phase,
                    turn_number=self.turn_manager.turn,
                    turn_manager=self.turn_manager,
                    characters=list(self.game_manager.characters),
                    position_overrides=dict(
                        self.planned_start_positions.get(ap_layer, {})
                    ),
                )
                entries = self.action_list_builder.get_available_actions(
                    context
                )
                continue
            self.turn_manager.add_action(
                action,
                ap_layer=ap_layer,
                decision_provider=self.decision_provider,
            )
            self.on_action_collected()
            return action

    def build_action(self, character, entry, ap_layer, context):
        action_id = entry.action_id
        if entry.skill is not None:
            target_type = entry.definition["target"]
            if target_type == "self":
                target = character
            elif target_type == "current_position" and entry.valid_targets:
                target = entry.valid_targets[0]
            elif entry.valid_targets:
                target = self.choose_target(
                    character,
                    entry.valid_targets,
                    ap_layer,
                    allow_refresh=True,
                )
                if target is None:
                    return None
            else:
                return None
            input_values = collect_skill_inputs(
                entry.skill_component,
                character,
                decision_provider=self.decision_provider,
                context={
                    "phase": f"AP{ap_layer}",
                    "turn_number": self.turn_manager.turn,
                    "turn_manager": self.turn_manager,
                    "game_manager": self.game_manager,
                },
            )
            return SkillAction(
                character,
                entry.skill,
                entry.skill_component,
                target=target,
                input_values=input_values,
            )

        if action_id == "move":
            if getattr(character, "carried_by", None) is not None:
                self.turn_manager.leave_ride_group(character)
            start = self.planned_positions.get(character, character.position)
            path = self.choose_path(character, start, ap_layer, allow_refresh=True)
            self.planned_positions[character] = path[-1]
            _, movement_limit = get_movement_formation(
                character,
                ap_layer=ap_layer,
            )
            return MovementAction(
                character,
                path,
                movement_limit=movement_limit,
                ap_layer=ap_layer,
            )

        if action_id in {"attack", "direct_attack", "join_battle"}:
            target = self.choose_target(character, entry.valid_targets, ap_layer, allow_refresh=True)
            if target is None:
                return None
            return Action(character, action_id, target=target)

        if action_id == "mend":
            maximum = int(min(
                character.hpmax - character.hp,
                character.get_available_mp(),
            ))
            amount = self.decision_provider.choose(NumericDecisionRequest(
                character=character,
                phase=f"AP{ap_layer}",
                prompt="",
                minimum=1,
                maximum=maximum,
            ))
            return Action(character, action_id, amount=amount)

        if action_id == "command_spell_transfer":
            target = self.choose_target(
                character,
                entry.valid_targets,
                ap_layer,
                allow_refresh=True,
            )
            if target is None:
                return None
            amount = self.decision_provider.choose(NumericDecisionRequest(
                character=character,
                phase=f"AP{ap_layer}—令咒移植",
                prompt=f"向{target.name}移植多少划令咒？",
                minimum=1,
                maximum=character.command_spell,
            ))
            accepted = self.decision_provider.choose(DecisionRequest(
                character=target,
                phase=f"AP{ap_layer}—令咒移植",
                prompt=(
                    f"{character.name}希望向你移植{amount}划令咒，"
                    "是否接受？"
                ),
                options=(
                    DecisionOption("接受", True, ("accept", "接受")),
                    DecisionOption("拒绝", False, ("reject", "拒绝")),
                ),
            ))
            if not accepted:
                return None
            return Action(
                character,
                action_id,
                target=target,
                amount=amount,
                confirmed=True,
            )

        return Action(character, action_id)

    def choose_target(self, character, targets, ap_layer, *, allow_refresh=False):
        return self.decision_provider.choose(DecisionRequest(
            character=character,
            phase=f"AP{ap_layer}",
            prompt="",
            allow_refresh=allow_refresh,
            options=tuple(
                DecisionOption(target.name, target, (str(target.name),))
                for target in targets
            ) + (
                DecisionOption(
                    "返回行动选择",
                    None,
                    ("back", "返回"),
                ),
            ),
        ))

    def choose_path(self, character, start, ap_layer, *, allow_refresh=False):
        _, maximum_steps = get_movement_formation(
            character,
            ap_layer=ap_layer,
        )
        planner = PathPlanner(
            character,
            start=start,
            maximum_steps=maximum_steps,
        )
        while planner.remaining_steps > 0:
            options = [
                DecisionOption(
                    location.name,
                    ("step", location),
                    (str(location.name),),
                )
                for location in planner.get_next_options()
            ]
            if planner.can_finish():
                options.append(DecisionOption(
                    "结束路径",
                    ("finish", None),
                    ("finish", "结束"),
                ))
                options.append(DecisionOption(
                    "退回上一节点",
                    ("back", None),
                    ("back", "返回"),
                ))
            choice, location = self.decision_provider.choose(DecisionRequest(
                character=character,
                phase="move_path",
                prompt="",
                allow_refresh=allow_refresh,
                options=tuple(options),
            ))
            if choice == "finish":
                break
            if choice == "back":
                planner.remove_last_step()
                continue
            planner.add_step(location)
        return planner.finish()

    def execute_map_actions(self):
        while (
            self.turn_manager.current_ap_layer
            in self.turn_manager.ACTION_LAYERS
            and not self.game_manager.check_game_end()
        ):
            ap_layer = self.turn_manager.current_ap_layer
            self.turn_manager.resolve_travel_joins(ap_layer)
            self.collect_missing_layer_actions(ap_layer)
            result = self.turn_manager.execute_action_layer(
                self.turn_manager.current_ap_layer,
                decision_provider=self.decision_provider,
            )
            while isinstance(result, dict):
                self.resolve_waiting_encounters(result["encounters"])
                result = self.turn_manager.resume_action_layer()

    def collect_missing_layer_actions(self, ap_layer):
        for character in self.turn_manager.non_battle_order:
            if (
                not character.is_alive()
                or character.in_battle
                or character.action_point <= 0
                or character in self.turn_manager.layer_actors[ap_layer]
                or self.should_follow_group_move(character, ap_layer)
            ):
                continue
            self.planned_positions[character] = character.position
            self.planned_start_positions[ap_layer][character] = (
                character.position
            )
            self.collect_character_action(character, ap_layer)

    def resolve_waiting_encounters(self, encounters):
        for encounter in encounters:
            while not encounter.resolved:
                unresolved_characters = [
                    character
                    for character, decision
                    in encounter.movement_decisions.items()
                    if decision is None
                ]
                unresolved_characters.sort(key=lambda character: (
                    1
                    if getattr(character, "travel_group", None) is not None
                    and character.travel_group.leader is not character
                    else 0,
                ))
                character = (
                    unresolved_characters[0]
                    if unresolved_characters
                    else None
                )
                if character is None:
                    break
                can_replan = (
                    self.turn_manager.current_ap_layer == 1
                    and self.turn_manager.paused_movement_action is not None
                    and self.turn_manager.paused_movement_action.actor is character
                    and character not in encounter.replan_characters
                )
                options = [
                    DecisionOption(
                        "继续原计划",
                        "continue",
                        ("continue",),
                    )
                ]
                for target in encounter.get_battle_targets(character):
                    options.append(DecisionOption(
                        f"停下并向{target.name}宣战",
                        ("battle", target),
                        (f"battle {target.name}",),
                    ))
                if can_replan:
                    options.append(DecisionOption(
                        "改写AP2移动",
                        "replan",
                        ("replan",),
                    ))
                group = getattr(character, "travel_group", None)
                leader_decision = None
                if group is not None and group.leader is not character:
                    leader_decision = encounter.movement_decisions.get(
                        group.leader
                    )
                    if leader_decision is not None:
                        options.insert(0, DecisionOption(
                            f"跟随{group.leader.name}的决定",
                            "follow",
                            ("follow", "跟随"),
                        ))
                decision = self.decision_provider.choose(DecisionRequest(
                    character=character,
                    phase=f"AP{self.turn_manager.current_ap_layer}",
                    prompt="",
                    options=tuple(options),
                ))
                if decision == "follow":
                    decision = leader_decision
                elif (
                    group is not None
                    and group.leader is not character
                    and leader_decision is not None
                    and decision != leader_decision
                ):
                    self.turn_manager.leave_travel_group(character)
                if decision == "continue":
                    self.turn_manager.continue_encounter(
                        encounter,
                        character,
                    )
                elif decision == "battle":
                    copied = False
                    for request in encounter.battle_requests:
                        if (
                            request.actor is group.leader
                            and request.target
                            in encounter.get_battle_targets(character)
                        ):
                            encounter.declare_battle_target(
                                character,
                                target=request.target,
                                ap_layer=self.turn_manager.current_ap_layer,
                            )
                            copied = True
                    if copied:
                        encounter.finish_battle_decision(character)
                        self.turn_manager.lock_resolved_encounter_movement(
                            encounter
                        )
                    else:
                        encounter.choose_continue(character)
                elif isinstance(decision, tuple) and decision[0] == "battle":
                    encounter.declare_battle_target(
                        character,
                        target=decision[1],
                        ap_layer=self.turn_manager.current_ap_layer,
                    )
                    while True:
                        remaining = [
                            target
                            for target in encounter.get_battle_targets(character)
                            if not any(
                                request.actor is character
                                and request.target is target
                                for request in encounter.battle_requests
                            )
                        ]
                        declaration_options = [
                            DecisionOption(
                                "完成宣战",
                                "finish",
                                ("finish", "完成"),
                            )
                        ]
                        declaration_options.extend(
                            DecisionOption(
                                f"同时向{target.name}宣战",
                                target,
                                (target.name,),
                            )
                            for target in remaining
                        )
                        declaration = self.decision_provider.choose(
                            DecisionRequest(
                                character=character,
                                phase=(
                                    f"AP{self.turn_manager.current_ap_layer}"
                                ),
                                prompt="",
                                options=tuple(declaration_options),
                            )
                        )
                        if declaration == "finish":
                            encounter.finish_battle_decision(character)
                            self.turn_manager.lock_resolved_encounter_movement(
                                encounter
                            )
                            break
                        encounter.declare_battle_target(
                            character,
                            target=declaration,
                            ap_layer=self.turn_manager.current_ap_layer,
                        )
                elif decision == "replan" and can_replan:
                    replacement = self.choose_replan(character)
                    self.turn_manager.replan_encounter(
                        encounter,
                        character,
                        path=replacement,
                    )
                else:
                    encounter.choose_replan(character)

    def choose_replan(self, character):
        choice = self.decision_provider.choose(DecisionRequest(
            character=character,
            phase="AP2",
            prompt="",
            options=(
                DecisionOption("重新移动", "move", ("move",)),
                DecisionOption("停在原地", "pass", ("pass",)),
            ),
        ))
        if choice == "pass":
            return None
        return self.choose_path(character, character.position, 2)
