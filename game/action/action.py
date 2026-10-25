from game.modifier.modifier import create_modifier
from game.map.map import get_distance
from game.turn.damage import AttackProfile, DamageEvent, DamageResolver
from game.turn.damage_types import normalize_damage_type
from game.turn.roll import RollResolver
from game.action.action_data import get_action_definition
import random
class Action:
    def __init__(
        self,
        actor,
        action_id,
        target=None,
        characters=None,
        attack_stat="physical_attack",
        attack_roll_bonus=0,
        damage_value=None,
        damage_type="physical",
        damage_percentage_modifiers=None,
        damage_flat_modifiers=None,
        damage_action_id=None,
        damage_source_tags=None,
        ignore_shield=False,
        target_lock=False,
        skill=None,
        ignore_attack_phase_count=False,
        ignore_target_visibility=False,
        amount=None,
        automatic=False,
        confirmed=False,
    ):
        self.actor = actor
        self.action_id = action_id
        self.definition = get_action_definition(action_id)
        if (
            action_id == "attack"
            and attack_stat == "physical_attack"
            and damage_type == "physical"
            and getattr(actor, "normal_attack_type", "physical") == "magic"
        ):
            attack_stat = "magic_attack"
            damage_type = "magic"
        self.target = target
        self.characters = list(characters) if characters is not None else []
        self.attack_stat = attack_stat
        self.attack_roll_bonus = attack_roll_bonus
        self.damage_value = damage_value
        self.damage_type = normalize_damage_type(damage_type)
        self.damage_percentage_modifiers = list(
            damage_percentage_modifiers or []
        )
        self.damage_flat_modifiers = list(damage_flat_modifiers or [])
        self.damage_action_id = damage_action_id
        self.damage_source_tags = set(damage_source_tags or [])
        self.ignore_shield = ignore_shield
        self.target_lock = bool(target_lock)
        self.skill = skill
        self.ignore_attack_phase_count = ignore_attack_phase_count
        self.ignore_target_visibility = ignore_target_visibility
        self.created_attack_profile = None
        self.created_attack_event = None
        self.amount = amount
        self.automatic = automatic
        self.confirmed = confirmed
        self.game_turn = None
        self.game_manager = None
        self.simple_round_effect = None
        self.defer_to_checkpoint = False
        self.ap_layer = None
        self.checkpoint_pending = False
        self.checkpoint_result = None
        self.ignored = False
        self.ignored_reason = None
        self.virtual_attack_phase = False

    @classmethod
    def create_magic_attack(cls, actor, target, **kwargs):
        """保留给技能等系统调用的普通魔术攻击接口。"""
        kwargs.setdefault("attack_stat", "magic_attack")
        kwargs.setdefault("damage_type", "magic")
        return cls(actor, "attack", target=target, **kwargs)

    def can_use_non_battle_action(self):
        actor = self.actor
        return (
            not actor.in_battle
            and actor.position is not None
            and actor.action_point >= 1
        )

    def consume_action_point(self):
        self.actor.action_point -= 1

    def move(self):
        actor = self.actor
        target = self.target

        if not self.can_use_non_battle_action():
            return False
        if actor.movement_locked or actor.has_status("cannot_move"):
            self.ignored = True
            self.ignored_reason = (
                "cannot_move" if actor.has_status("cannot_move")
                else "movement_locked_by_battle_request"
            )
            return False

        if target not in actor.position.connected_locations:
            return False

        self.consume_action_point()
        actor.position = target

        return True

    def investigate(self, decision_provider=None):
        actor = self.actor
        if (
            not self.can_use_non_battle_action()
            or actor.has_status("cannot_investigate")
        ):
            return False

        self.consume_action_point()
        if self.defer_to_checkpoint:
            self.checkpoint_pending = True
            return {
                "pending": True,
                "ap_layer": self.ap_layer,
                "action": self,
            }

        return self.resolve_investigate_snapshot(decision_provider)

    def resolve_investigate_snapshot(self, decision_provider=None):
        actor = self.actor

        from game.character.masters import Master
        from game.character.servants import Servant

        location = actor.position
        revealed_statuses = set(location.status)
        actor.investigated_statuses[location] = revealed_statuses

        nearest_masters = self.get_nearest_characters(Master)
        nearest_servants = self.get_nearest_characters(Servant)
        revealed_characters = nearest_masters + nearest_servants

        for character in revealed_characters:
            actor.revealed_positions[character] = character.position
            character.reveal_hidden_to(actor)
            character.reveal_presence_to(actor)

        result = {
            "location": location,
            "statuses": revealed_statuses,
            "masters": nearest_masters,
            "servants": nearest_servants,
            "positions": {
                character: character.position
                for character in revealed_characters
            },
        }
        if self.game_manager is not None:
            result["grail_interaction"] = (
                self.game_manager.handle_grail_investigation(
                    actor,
                    decision_provider,
                )
            )
        self.checkpoint_pending = False
        self.checkpoint_result = result
        return result

    def get_nearest_characters(self, character_type):
        actor = self.actor
        candidates = []

        for character in self.characters:
            if (
                character is actor
                or not isinstance(character, character_type)
                or character.has_investigation_immunity()
            ):
                continue
            distance = get_distance(actor.position, character.position)
            if distance is not None:
                candidates.append((distance, character))

        if not candidates:
            return []

        nearest_distance = min(distance for distance, _ in candidates)
        return [
            character
            for distance, character in candidates
            if distance == nearest_distance
        ]

    def hide(self):
        actor = self.actor
        if not self.can_use_non_battle_action():
            return False
        if not actor.position.is_building:
            return False
        if actor.has_status("hidden"):
            return False

        self.consume_action_point()
        effect = {
            "modifier_id": "hidden",
            "effect_type": "hidden",
            "polarity": "buff",
            "purifiable": False,
            "stacking": {
                "stack_group": "hidden",
                "stack_scope": "all_sources",
                "stacking_rule": "reject",
                "max_stacks": 1,
            },
            "effect_data": {
                "value": "hidden",
                "duration": None,
            },
        }
        modifier = create_modifier(
            effect,
            actor,
            source=actor,
            source_type="action",
            source_id="hide",
            applied_turn=self.game_turn,
            applied_phase=(f"AP{self.ap_layer}" if self.ap_layer else None),
        )
        modifier_result = actor.add_modifier(modifier)
        if not modifier_result:
            return False

        for character in self.characters:
            for field in ("own_visible", "shared_visible", "any_visible"):
                visible = getattr(character, field, [])
                if actor in visible:
                    visible.remove(actor)
        # 普通视野应立即失去隐藏者，但洞悉、工房等明确无视隐蔽的
        # 特殊视野必须在同一动作结算后重新生效。
        game_manager = getattr(actor, "game_manager", None)
        if game_manager is not None:
            game_manager.turn_manager.update_visibility()
        else:
            for character in self.characters:
                character.update_visibility(self.characters)
        return True

    def perceive(self):
        actor = self.actor
        if not self.can_use_non_battle_action():
            return False

        self.consume_action_point()
        if self.defer_to_checkpoint:
            self.checkpoint_pending = True
            return {
                "pending": True,
                "ap_layer": self.ap_layer,
                "action": self,
            }

        return self.resolve_perceive_snapshot()

    def battle_perceive(self):
        actor = self.actor
        if (
            not actor.in_battle
            or actor.current_battle is None
            or actor.attack_phase_count <= 0
            or not actor.is_alive()
        ):
            return False
        actor.attack_phase_count -= 1
        return self.resolve_perceive_snapshot()

    def resolve_perceive_snapshot(self):
        actor = self.actor
        characters = list(self.characters)
        if not characters:
            game_manager = getattr(actor, "game_manager", None)
            characters = list(getattr(game_manager, "characters", []))
        actor.update_visibility(characters)
        checks = []
        detected = []

        for character in characters:
            if character is actor or character in actor.own_visible:
                continue
            distance = get_distance(actor.position, character.position, 5)
            if distance is None:
                continue

            if character.blocks_perception_while_actively_hidden():
                checks.append({
                    "target": character,
                    "distance": distance,
                    "perceive_die": None,
                    "hide_die": None,
                    "perceive_roll": None,
                    "hide_roll": None,
                    "success": False,
                    "blocked_by": "presence_concealment",
                })
                continue

            perceive_die = random.randint(1, 10)
            hide_die = random.randint(1, 10)
            perceive_roll = perceive_die + actor.perceive
            hide_roll = hide_die + character.hide
            success = hide_roll <= perceive_roll

            checks.append({
                "target": character,
                "distance": distance,
                "perceive_die": perceive_die,
                "hide_die": hide_die,
                "perceive_roll": perceive_roll,
                "hide_roll": hide_roll,
                "success": success,
            })

            if success:
                if character not in actor.own_perceived:
                    actor.own_perceived.append(character)
                character.reveal_hidden_to(actor)
                detected.append(character)

        actor.update_visibility(characters)
        result = {
            "checks": checks,
            "detected": detected,
        }
        self.checkpoint_pending = False
        self.checkpoint_result = result
        return result

    def resolve_checkpoint(self, decision_provider=None):
        if not self.checkpoint_pending:
            return self.checkpoint_result
        if self.action_id == "perceive":
            return self.resolve_perceive_snapshot()
        if self.action_id == "investigate":
            return self.resolve_investigate_snapshot(decision_provider)
        if self.action_id == "wish":
            return self.resolve_wish_checkpoint()
        raise ValueError(f"{self.action_id}不是checkpoint动作")

    def pass_action(self):
        if not self.can_use_non_battle_action():
            return False
        self.consume_action_point()
        return True

    def join_travel_group(self):
        """Engine-facing fallback; terminal planning submits this before the AP layer."""
        manager = getattr(
            getattr(self.actor, "game_manager", None),
            "turn_manager",
            None,
        )
        if manager is None or self.target is None:
            return False
        return manager.submit_travel_join(
            self.actor,
            self.target,
            self.ap_layer or manager.current_ap_layer,
        )

    def invite_carry(self, accepted=False):
        manager = getattr(
            getattr(self.actor, "game_manager", None),
            "turn_manager",
            None,
        )
        if manager is None or self.target is None:
            return False
        return manager.invite_to_ride(
            self.actor,
            self.target,
            accepted=accepted,
        )

    def leave_carry(self):
        manager = getattr(
            getattr(self.actor, "game_manager", None),
            "turn_manager",
            None,
        )
        if manager is None:
            return self.actor.detach_ride_group()
        return manager.leave_ride_group(self.actor)

    def join_battle(self):
        actor = self.actor
        manager = getattr(
            getattr(actor, "game_manager", None),
            "turn_manager",
            None,
        )
        if (
            manager is None
            or self.target is None
            or not self.can_use_non_battle_action()
        ):
            return False
        request = manager.submit_battle_join(
            actor,
            self.target,
            self.ap_layer,
        )
        if not request:
            return False
        self.consume_action_point()
        self.created_battle_request = request
        return request

    def transfer_travel_leader(self):
        manager = getattr(
            getattr(self.actor, "game_manager", None),
            "turn_manager",
            None,
        )
        if manager is None or self.target is None:
            return False
        return manager.transfer_travel_leader(self.actor, self.target)

    def surrender(self):
        from game.character.masters import Master

        actor = self.actor
        if (
            not isinstance(actor, Master)
            or actor.in_battle
            or not actor.is_alive()
            or actor.action_point < 1
            or actor.servants
        ):
            return False
        self.consume_action_point()
        actor.die()
        return True

    def wish(self):
        from game.character.masters import Master

        actor = self.actor
        game = self.game_manager
        if (
            not isinstance(actor, Master)
            or game is None
            or self.ap_layer not in (None, 1)
            or not self.can_use_non_battle_action()
            or not game.is_player_character(actor)
            or not game.holy_grail.ready
            or actor.position is not game.holy_grail.position
        ):
            return False

        self.consume_action_point()
        if self.defer_to_checkpoint:
            self.checkpoint_pending = True
            return {
                "pending": True,
                "ap_layer": self.ap_layer,
                "action": self,
            }
        return self.resolve_wish_checkpoint()

    def resolve_wish_checkpoint(self):
        actor = self.actor
        game = self.game_manager
        success = bool(
            game is not None
            and actor.is_alive()
            and game.holy_grail.ready
            and actor.position is game.holy_grail.position
            and not game.is_battle_request_target(actor, self.ap_layer)
        )
        if success:
            success = game.declare_victory(actor)
        self.checkpoint_pending = False
        self.checkpoint_result = {
            "success": success,
            "cancelled_by_battle_request": bool(
                game is not None
                and game.is_battle_request_target(actor, self.ap_layer)
            ),
        }
        return self.checkpoint_result

    def stay(self):
        actor = self.actor

        if not actor.in_battle or actor.attack_phase_count <= 0:
            return False

        effect = {
            "duration": 2,
            "modifier_id": "stay",
            "effect_type": "add_status",
            "stacking": {
                "stack_group": "stay",
                "stack_scope": "all_sources",
                "stacking_rule": "refresh",
                "max_stacks": 1,
                "duration_refresh_rule": "reset",
            },
            "effect_data":{
                "status_id": "stay"
            }
        }
        modifier = create_modifier(
            effect,
            actor,
            source=actor,
            source_type="action",
            source_id="stay",
            applied_turn=self.game_turn,
            applied_phase="attack_phase",
        )
        modifier_result = actor.add_modifier(modifier)
        if not modifier_result:
            return False

        actor.attack_phase_count -= 1
        battle = actor.current_battle
        if battle is not None:
            battle.mark_stayed(actor)
        return True

    def build_attack_profile(self, decision_provider=None, *, for_offset=False):
        """Roll and snapshot one normal attack without assigning a target."""
        attacker = self.actor
        skill_id = getattr(
           self.skill,
           "skill_id",
           getattr(self.skill, "name", None),
        )
        attack_tags = set(self.damage_source_tags)
        if for_offset:
           attack_tags.add("offset")
        modifier_context = {
           "actor": attacker,
           "source": self,
           "target": self.target,
           "action_id": self.damage_action_id or self.action_id,
           "skill_id": skill_id,
           "damage_type": self.damage_type,
           "tags": attack_tags,
        }
        if not hasattr(attacker, self.attack_stat):
           raise ValueError(f"未知的攻击骰属性：{self.attack_stat}")

        if for_offset:
           roll_result = None
           dice = None
           attack_roll = None
        else:
           roll_result = RollResolver().roll(
               attacker,
               self.attack_stat,
               decision_provider=decision_provider,
               phase="攻击—幸运",
               situational_bonus=self.attack_roll_bonus,
               initial_die=random.randint(1, 10),
               roller=lambda: random.randint(1, 10),
               modifier_context=modifier_context,
           )
           dice = roll_result.die
           attack_roll = roll_result.total

        damage_value = self.damage_value
        if damage_value is None:
           if (
              self.action_id == "attack"
              and hasattr(attacker, "normal_attack_damage")
           ):
              damage_value = attacker.normal_attack_damage
           elif self.attack_stat == "physical_attack":
              damage_value = attacker.get_effective_atk(modifier_context)
           elif self.attack_stat == "magic_attack":
              damage_value = (
                 attacker.get_effective_attribute_value(
                    "magic",
                    modifier_context,
                 ) * 10
              )
           else:
              raise ValueError("未知攻击必须明确提供damage_value")

        outgoing_percentages, outgoing_flats = (
           attacker.modifier_manager.get_damage_adjustments(
              "outgoing",
              self.damage_type,
              action_id=self.damage_action_id or self.action_id,
              skill_id=skill_id,
              source_tags=self.damage_source_tags,
              context=modifier_context,
           )
        )
        command_spell_bonus = attacker.consume_command_spell_damage()

        profile = AttackProfile(
            source = attacker,
            value = damage_value,
            damage_type = self.damage_type,
            skill = self.skill,
            attack_roll = attack_roll,
            attack_die = dice,
            attack_roll_bonus = self.attack_roll_bonus,
            roll_result=roll_result,
            percentage_modifiers=(
               self.damage_percentage_modifiers
               + outgoing_percentages
            ),
            flat_modifiers=(
               self.damage_flat_modifiers
               + outgoing_flats
               + ([command_spell_bonus] if command_spell_bonus else [])
            ),
            action_id=self.damage_action_id or self.action_id,
            skill_id=skill_id,
            source_tags=attack_tags,
            ignore_shield=self.ignore_shield,
            target_lock=self.target_lock,
            resolution_channel="attack",
            target_type=self.definition.get("target"),
            target_rules=self.definition.get("target_rules", {}),
        )
        self.created_attack_profile = profile
        attacker.modifier_manager.consume_event(
           "attack_committed",
           {**modifier_context, "event": profile},
        )
        return profile

    def assign_attack_target(
        self,
        profile,
        target,
        *,
        declared_target_position=None,
        decision_provider=None,
    ):
        """Bind a generated profile to one target and queue the event."""
        if target is None:
            raise ValueError("攻击缺少目标")
        event = profile.assign_target(target)
        if declared_target_position is None:
            declared_target_position = target.position
        if (
            target.position is not declared_target_position
            and not event.target_lock
        ):
           event.miss_because_target_moved()
        else:
           manager = getattr(profile.source, "game_manager", None)
           relationships = getattr(manager, "relationship_manager", None)
           if relationships is not None:
              relationships.resolve_attack_attitude(
                 profile.source,
                 target,
                 decision_provider,
              )
           target.pending_attacks.append(event)
        self.created_attack_event = event
        return event

    def attack(self, decision_provider=None):
        attacker = self.actor
        target = self.target
        if (
            not attacker.in_battle
            and not self.ignore_attack_phase_count
            and not self.virtual_attack_phase
        ):
           return False
        if (
            not self.ignore_attack_phase_count
            and attacker.attack_phase_count <= 0
        ):
           return False

        if (
            target is None
            or not target.is_alive()
        ):
           return False
        if (
            not self.ignore_target_visibility
            and target not in attacker.own_visible
        ):
           return False

        declared_target_position = target.position
        profile = self.build_attack_profile(decision_provider)
        self.assign_attack_target(
            profile,
            target,
            declared_target_position=declared_target_position,
            decision_provider=decision_provider,
        )
        if not self.ignore_attack_phase_count:
           attacker.attack_phase_count -= 1

        return True

    def mend(self):
        from game.character.servants import Servant

        actor = self.actor
        if not isinstance(actor, Servant) or not actor.is_alive():
            return False
        if self.amount is None or self.amount <= 0:
            return False

        missing_hp = max(0, actor.hpmax - actor.hp)
        actual_amount = min(self.amount, missing_hp)
        if actual_amount <= 0:
            return False

        if actor.in_battle or self.virtual_attack_phase:
            if actor.attack_phase_count <= 0:
                return False
        else:
            if self.ap_layer not in (None, 1) or actor.action_point < 2:
                return False

        if not actor.consume_mp(actual_amount):
            return False

        self.actual_amount = actor.recover_resource("hp", actual_amount)
        if actor.in_battle or self.virtual_attack_phase:
            actor.attack_phase_count -= 1
        else:
            actor.action_point -= 2
        return True

    def rest(self):
        from game.character.masters import Master

        actor = self.actor
        if not isinstance(actor, Master):
            return False
        if actor.in_battle or actor.position is None:
            return False
        if not actor.position.is_building:
            return False
        if self.ap_layer not in (None, 1) or actor.action_point < 2:
            return False

        turn_number = self.game_turn
        if turn_number is None:
            raise ValueError("rest必须由TurnManager提供当前回合数")
        if not actor.resting:
            if not actor.can_start_rest(turn_number):
                return False
            actor.resting = True
            actor.rest_turns = 0
            actor.rest_started_turn = turn_number
            actor.last_rest_started_turn = turn_number

        actor.action_point -= 2
        actor.rest_scheduled_turn = turn_number
        return True

    def command_spell_transfer(self):
        actor = self.actor
        target = self.target
        manager = self.game_manager
        if manager is None:
            manager = getattr(actor, "game_manager", None)
        if manager is None:
            return False
        transfer_manager = manager.command_spell_transfer_manager
        existing = getattr(actor, "command_spell_transfer", None)
        if existing is not None:
            if existing.recipient is not target:
                return False
            maintained = transfer_manager.continue_transfer(
                existing,
                self.game_turn,
            )
            return {
                "transfer": existing,
                "maintained": bool(maintained),
                "automatic": self.automatic,
            } if maintained else False

        transfer = transfer_manager.start(
            actor,
            target,
            self.amount,
            self.game_turn,
            accepted=self.confirmed,
        )
        if not transfer:
            return False
        return {
            "transfer": transfer,
            "maintained": True,
            "automatic": self.automatic,
        }

    def chant(self, decision_provider=None):
        from game.skill.casting import (
            castable_sources,
            castable_options, release_option_label, get_casting_mp_cost,
            start_or_continue_casting,
        )
        from game.turn.decision import DecisionOption, DecisionRequest

        actor = self.actor
        if not actor.is_alive():
            return False
        if actor.in_battle or self.virtual_attack_phase:
            if actor.attack_phase_count < 1:
                return False
        elif self.ap_layer not in (None, 1) or actor.action_point < 2:
            return False

        state = actor.casting_state
        skill = state.skill if state is not None else self.target
        if state is None:
            candidates = castable_sources(actor)
            if skill not in candidates:
                if not candidates:
                    return False
                if len(candidates) == 1:
                    skill = candidates[0]
                else:
                    if decision_provider is None:
                        raise ValueError("开始咏唱需要DecisionProvider选择对象")
                    skill = decision_provider.choose(DecisionRequest(
                        character=actor,
                        phase="咏唱对象选择",
                        prompt="请选择要咏唱的魔术或宝具。",
                        options=tuple(
                            DecisionOption(
                                candidate.name,
                                candidate,
                                (candidate.skill_id,),
                            )
                            for candidate in candidates
                        ) + (
                            DecisionOption(
                                "返回行动选择",
                                None,
                                ("back", "返回"),
                            ),
                        ),
                    ))
                    if skill is None:
                        return False

        component_id = state.component_id if state is not None else None
        if state is None:
            options = castable_options(actor, skill)
            if not options:
                return False
            if len(options) == 1:
                component_id = options[0][1]["component_id"]
            else:
                if decision_provider is None:
                    raise ValueError("开始咏唱需要选择技能单元")
                component_id = decision_provider.choose(DecisionRequest(
                    character=actor, phase="咏唱单元选择", prompt="请选择本次咏唱并准备解放的技能单元。",
                    options=tuple(DecisionOption(release_option_label(source, component) +
                                                 f"（预付{get_casting_mp_cost(actor, source, component)}MP）", component["component_id"],
                                                 (component["component_id"],)) for source, component in options)
                    + (DecisionOption("返回行动选择", None, ("back", "返回")),),
                ))
                if component_id is None:
                    return False

        turn_number = self.game_turn
        if turn_number is None:
            turn_number = actor.current_global_turn
        result = start_or_continue_casting(
            actor,
            skill=skill,
            turn_number=turn_number,
            component_id=component_id,
        )
        if result is None:
            return False
        if actor.in_battle or self.virtual_attack_phase:
            actor.attack_phase_count -= 1
        else:
            actor.action_point -= 2
        self.skill = result.skill
        return result

    def interrupt_casting(self):
        actor = self.actor
        if actor.casting_state is None:
            return False
        if not actor.in_battle and self.ap_layer not in (None, 1):
            return False
        refunds = actor.interrupt_casting(reason="manual")
        return {"interrupted": True, "refunds": refunds}

    def release(self, decision_provider=None):
        from game.skill.casting import (
            select_release_option,
            select_release_targets,
        )
        from game.skill.skill_runtime import resolve_skill_component

        actor = self.actor
        if not actor.is_alive():
            return False
        if actor.in_battle or self.virtual_attack_phase:
            if actor.attack_phase_count < 1:
                return False
        elif self.ap_layer not in (None, 1) or actor.action_point < 2:
            return False
        if decision_provider is None:
            raise ValueError("解放需要DecisionProvider选择效果和目标")

        selected = select_release_option(actor, decision_provider)
        if selected is None:
            return False
        skill, component = selected
        targets = select_release_targets(
            actor,
            skill,
            component,
            decision_provider,
        )
        if not targets:
            return False

        state = actor.casting_state
        prepaid = state is not None and state.skill is skill and state.component_id == component["component_id"]
        if state is not None and not prepaid:
            return False
        result = resolve_skill_component(
            actor,
            skill,
            component["component_id"],
            targets=targets,
            decision_provider=decision_provider,
            casting_prepaid=prepaid,
            casting_release=True,
            turn_number=self.game_turn,
            phase="release",
            action_id="release",
        )
        if actor.in_battle or self.virtual_attack_phase:
            actor.attack_phase_count -= 1
        else:
            actor.action_point -= 2
        if state is not None:
            state.finish_release()
        self.skill = skill
        self.target = targets
        return result

    def direct_attack(self, decision_provider=None):
        actor = self.actor
        target = self.target
        if actor.in_battle or target is None or not target.is_alive():
            return False
        if actor.position is target.position:
            return False
        if self.ap_layer not in (None, 1) or actor.action_point < 2:
            return False
        if target not in actor.own_visible:
            return False
        if decision_provider is None:
            raise ValueError("战斗外攻击需要DecisionProvider处理目标防御")

        from game.turn.battle import BattleManager

        actor.action_point -= 2
        game_manager = getattr(actor, "game_manager", None)
        characters = (
            list(game_manager.characters)
            if game_manager is not None
            else list(self.characters)
        )
        if actor not in characters:
            characters.append(actor)
        if target not in characters:
            characters.append(target)

        resolver = BattleManager(characters)
        return resolver.run_virtual_attack_phase(
            actor,
            decision_provider,
            characters=characters,
            preferred_target=target,
            remote_only=True,
            reveal_direct_attack_source=True,
        )

    def escape(self):
        actor = self.actor
        if not actor.has_status("stay"):
            return False
        if actor.has_status("cannot_escape"):
            return False
        if not actor.in_battle or actor.attack_phase_count <= 0:
            return False

        turn_number = self.game_turn
        if turn_number is None:
            turn_number = getattr(actor, "current_global_turn", 0)
        if (
            actor.last_escape_turn is not None
            and turn_number - actor.last_escape_turn < 4
        ):
            return False

        battle = actor.current_battle
        actor.remove_status_modifiers("stay")
        movement_penalty_effect = next(
            effect
            for effect in self.definition["effects"]
            if effect["effect_type"] == "numeric_attribute_bonus"
        )
        movement_penalty = create_modifier(
            movement_penalty_effect,
            actor,
            source=actor,
            source_type="action",
            source_id="escape",
            applied_turn=turn_number,
            applied_phase="attack_phase",
        )
        movement_penalty_result = actor.add_modifier(movement_penalty)
        if not movement_penalty_result:
            return False
        actor.attack_phase_count -= 1
        actor.last_escape_turn = turn_number
        actor.ap1_forfeited_turn = None
        actor.action_point = 2
        actor.movement_point = 0
        actor.forced_move_turn = turn_number
        if battle is not None:
            battle.remove_participant(actor)
        else:
            actor.in_battle = False
        return True






