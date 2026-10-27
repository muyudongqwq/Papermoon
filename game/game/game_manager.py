from game.turn.Turn import TurnManager
from game.turn.decision import DecisionOption, DecisionRequest

from game.game.holy_grail import HolyGrail
from game.skill.field_runtime import FieldManager
from game.skill.reality_marble_runtime import RealityMarbleManager
from game.skill.observation_runtime import ObservationManager
from game.game.command_spell_transfer import CommandSpellTransferManager
from game.skill.event_runtime import EventManager
from game.skill.trap_runtime import TrapManager
from game.skill.summon_runtime import SummonManager
from game.skill.delay_runtime import DelayManager
from game.game.relationship import InformationManager, RelationshipManager
from game.game.rule_report import RuleReportManager
from game.map.boat import BoatManager


class GameManager:
    """负责游戏开始、全局结束和圣杯胜利条件。"""

    def __init__(
        self,
        characters,
        grail_location,
        player_characters=None,
        maximum_turns=120,
        grail_appearance_deaths=4,
        grail_ready_deaths=6,
        turn_manager=None,
    ):
        self.characters = list(characters)
        self.dead_characters = []
        self.removed_characters = []
        self._next_registration_index = 0
        for character in self.characters:
            self._assign_registration_metadata(character, registered_turn=0)
        self.player_characters = list(
            (
                character
                for character in self.characters
                if not getattr(character, "is_npc", False)
            )
            if player_characters is None
            else player_characters
        )
        if any(
            character not in self.characters
            for character in self.player_characters
        ):
            raise ValueError("玩家角色必须存在于游戏角色列表中")
        if any(
            getattr(character, "is_npc", False)
            for character in self.player_characters
        ):
            raise ValueError("NPC与使魔不能登记为玩家角色")
        if int(maximum_turns) < 1:
            raise ValueError("最大回合数必须至少为1")

        self.maximum_turns = int(maximum_turns)
        self.turn_manager = turn_manager or TurnManager()
        self.holy_grail = HolyGrail(
            grail_location,
            grail_appearance_deaths,
            grail_ready_deaths,
        )
        self.started = False
        self.ended = False
        self.end_reason = None
        self.winners = []
        self.grail_announcements = []
        self.field_manager = FieldManager(self)
        self.reality_marble_manager = RealityMarbleManager(self)
        self.command_spell_transfer_manager = CommandSpellTransferManager(self)
        self.observation_manager = ObservationManager(self)
        self.event_manager = EventManager(self)
        self.rule_reports = RuleReportManager(self)
        self.relationship_manager = RelationshipManager(self)
        self.information_manager = InformationManager(self)
        self.trap_manager = TrapManager(self)
        self.summon_manager = SummonManager(self)
        self.delay_manager = DelayManager(self)
        self.boat_manager = BoatManager(self)

    @property
    def field_effects(self):
        return list(self.field_manager.fields)

    def refresh_fields(self):
        self.field_manager.refresh()
        self.reality_marble_manager.refresh()

    def create_field(self, field):
        return self.field_manager.register(field)

    def get_map_nodes(self, merge_area_levels=True):
        from game.map.map import get_area_root

        game_map = getattr(self, "game_map", None)
        if game_map is not None:
            nodes = list(game_map.locations.values()) + list(game_map.roads)
        else:
            seeds = [
                character.position
                for character in self.characters
                if character.position is not None
            ]
            if self.holy_grail.designated_location is not None:
                seeds.append(self.holy_grail.designated_location)
            nodes = []
            pending = list(seeds)
            while pending:
                node = pending.pop(0)
                if node in nodes:
                    continue
                nodes.append(node)
                pending.extend(getattr(node, "connected_locations", []))
        result = []
        for node in nodes:
            if getattr(node, "is_boat", False):
                continue
            candidate = get_area_root(node) if merge_area_levels else node
            if candidate not in result:
                result.append(candidate)
        return result

    def get_special_visible_characters(self, observer):
        result = []
        for character in (
            self.observation_manager.visible_characters(observer)
            + self.field_manager.owner_visible_characters(observer)
        ):
            if character not in result:
                result.append(character)
        return result

    def get_shareable_special_visible_characters(self, observer):
        result = []
        for character in (
            self.observation_manager.visible_characters(observer)
            + self.field_manager.shareable_owner_visible_characters(observer)
        ):
            if character not in result:
                result.append(character)
        return result

    def get_special_visible_nodes(self, observer):
        return (
            self.observation_manager.visible_nodes(observer)
            | self.field_manager.owner_visible_nodes(observer)
        )

    def is_position_revealed(self, observer, target):
        state = getattr(target, "casting_state", None)
        return bool(state is not None and state.is_revealed_to(observer))

    def record_movement_first_step(self, character, origin, destination):
        return self.observation_manager.record_first_step(
            character,
            origin,
            destination,
            self.turn_manager.current_ap_layer,
        )

    @property
    def active_reality_marble(self):
        return self.reality_marble_manager.active

    def deploy_reality_marble(self, reality_marble):
        return self.reality_marble_manager.deploy(reality_marble)

    def collapse_reality_marble(self, reason="external"):
        return self.reality_marble_manager.collapse(reason=reason)

    def on_character_position_changed(self, character, old_position, new_position):
        self.boat_manager.on_position_changed(character, old_position, new_position)
        self.command_spell_transfer_manager.on_position_changed(
            character,
            old_position,
            new_position,
        )
        self.reality_marble_manager.on_position_changed(
            character,
            old_position,
            new_position,
        )
        if old_position is not None:
            self.event_manager.emit(
                "position_left",
                actor=character,
                source=character,
                target=character,
                position=old_position,
                payload={"old_position": old_position, "new_position": new_position},
            )
        if new_position is not None:
            self.event_manager.emit(
                "position_entered",
                actor=character,
                source=character,
                target=character,
                position=new_position,
                payload={"old_position": old_position, "new_position": new_position},
            )

    def reconcile_after_reality_marble_change(self):
        """Refresh position-derived state after mass transport.

        Existing battles keep their identities when all their members move
        together. Split/merge battle scheduling remains owned by TurnManager;
        ending checks and visibility are safe to refresh immediately here.
        """
        for battle in self.turn_manager.battles:
            if not battle.ended:
                battle.check_battle_end()
        self.turn_manager.refresh_travel_groups()
        self.turn_manager.update_visibility()

    @property
    def all_characters(self):
        return list(self.characters) + list(self.dead_characters)

    def _assign_registration_metadata(self, character, registered_turn):
        if getattr(character, "registration_index", None) is None:
            character.registration_index = self._next_registration_index
            self._next_registration_index += 1
        character.registered_turn = registered_turn
        return character.registration_index

    def register_character(
        self,
        character,
        position=None,
        *,
        activate_immediately=False,
        battle=None,
    ):
        """Register one new runtime entity without granting retroactive turns."""
        if (
            character in self.characters
            or character in self.dead_characters
            or any(
                record["character"] is character
                for record in self.removed_characters
            )
        ):
            return False
        if getattr(character, "game_manager", None) not in {None, self}:
            raise ValueError("角色已经属于另一场游戏")
        known_characters = self.all_characters + [
            record["character"] for record in self.removed_characters
        ]
        if any(other.character_id == character.character_id for other in known_characters):
            raise ValueError("角色ID已经存在于本局")
        spawn_position = position or character.position
        if spawn_position is None:
            raise ValueError("动态注册角色必须指定出现地点")

        from game.character.familiar import Familiar

        if isinstance(character, Familiar):
            summoner = character.summoner
            if summoner not in self.characters or not summoner.is_alive():
                raise ValueError("使魔的召唤者必须是本局存活角色")

        turn_number = self.turn_manager.turn
        character.game_manager = self
        character.despawn_reason = None
        character.status_flags.discard("despawned")
        character.activation_turn = (
            turn_number
            if activate_immediately
            else turn_number + 1
        ) if self.started else 0
        self._assign_registration_metadata(character, turn_number)
        self.characters.append(character)
        character.position = spawn_position

        if getattr(character, "is_npc", False):
            from game.turn.initialivemanager import InitiativeManager

            InitiativeManager.capture_fixed_snapshot(character)

        if isinstance(character, Familiar):
            summoner = character.summoner
            if character not in summoner.familiars:
                summoner.familiars.append(character)
            character.add_ally(
                summoner,
                source=("summoner_familiar", id(summoner)),
            )
            # A familiar at an existing battlefield must join it.  It can be
            # attacked, defend, and guard immediately, but receives no attack
            # phase until its normal activation turn.
            if battle is None:
                battle = self.get_battle_at(spawn_position)

        if self.started:
            self.turn_manager.characters.append(character)
            if activate_immediately:
                if character not in self.turn_manager.global_action_order:
                    self.turn_manager.global_action_order.append(character)
                if (
                    self.turn_manager.map_phase_started
                    and not character.in_battle
                    and character not in self.turn_manager.non_battle_order
                ):
                    self.turn_manager.non_battle_order.append(character)
            else:
                character.action_point = 0
                character.attack_phase_count = 0

        if battle is not None:
            battle.add_participant(character)
            if not activate_immediately:
                character.attack_phase_count = 0
            battle.queue_late_participant(character)

        self.refresh_fields()
        self.turn_manager.update_visibility()
        self.event_manager.emit(
            "character_registered",
            actor=character,
            source=character,
            target=character,
            position=spawn_position,
        )
        return character

    def _unlink_character_relations(self, character):
        summoner = getattr(character, "summoner", None)
        if summoner is not None and character in summoner.familiars:
            summoner.familiars.remove(character)
        for ally in list(character.allies):
            character.remove_ally(ally)

    def despawn_character(self, character, reason="external"):
        """Remove an entity without death status, triggers, or grail count."""
        if character not in self.characters:
            return False
        self.summon_manager.on_character_removed(character, reason=reason)
        last_position = character.position
        for familiar in list(getattr(character, "familiars", [])):
            self.despawn_character(familiar, reason="summoner_exit")

        character.interrupt_casting(reason=f"despawn:{reason}")
        self.command_spell_transfer_manager.on_character_death(character)
        self.reality_marble_manager.on_character_death(character)
        self.observation_manager.remove_owner(character)
        self.field_manager.remove_for_owner_death(character)
        self.trap_manager.remove_owner_traps(character, reason="owner_exit")
        self.holy_grail.note_carrier_death(character, last_position)

        battle = getattr(character, "current_battle", None)
        if battle is not None:
            battle.remove_participant(character)
        self.turn_manager.remove_character(character, add_to_dead=False)
        if character in self.characters:
            self.characters.remove(character)
        if character in self.player_characters:
            self.player_characters.remove(character)
        self._unlink_character_relations(character)
        from game.turn.damage import report_discarded_attacks
        report_discarded_attacks(character.pending_attacks, "target_despawned")
        character.pending_attacks.clear()
        character.despawn_reason = reason
        character.status_flags.add("despawned")
        if reason == "destroyed":
            character.hp = 0
        character.position = None
        self.removed_characters.append({
            "character": character,
            "reason": reason,
            "turn": self.turn_manager.turn,
            "last_position": last_position,
        })
        self.event_manager.emit(
            "character_despawned",
            actor=character,
            source=character,
            target=character,
            position=last_position,
            payload={"reason": reason},
        )
        self.turn_manager.update_visibility()
        return True

    def start_game(self):
        if self.started:
            return False
        if not self.characters:
            raise ValueError("游戏至少需要一名角色")
        if self.holy_grail.designated_location is None:
            raise ValueError("游戏开始前必须指定圣杯出现地点")

        self.turn_manager.characters = list(self.characters)
        self.turn_manager.dead_characters = self.dead_characters
        self.turn_manager.game_manager = self
        for character in self.characters:
            character.game_manager = self
        from game.character.familiar import Familiar

        for character in self.characters:
            if not isinstance(character, Familiar):
                continue
            summoner = character.summoner
            if summoner not in self.characters:
                raise ValueError("初始使魔的召唤者必须存在于本局")
            if character not in summoner.familiars:
                summoner.familiars.append(character)
            character.add_ally(
                summoner,
                source=("summoner_familiar", id(summoner)),
            )
        from game.turn.initialivemanager import InitiativeManager

        for character in self.characters:
            if getattr(character, "is_npc", False):
                InitiativeManager.capture_fixed_snapshot(character)
        self.holy_grail.refresh(self.all_characters)
        self.turn_manager.update_visibility()
        self.started = True
        return True

    def check_game_end(self):
        return self.ended

    def configure_grail_thresholds(
        self,
        appearance_servant_deaths,
        ready_servant_deaths,
    ):
        self.holy_grail.configure_thresholds(
            appearance_servant_deaths,
            ready_servant_deaths,
        )
        self.holy_grail.refresh(self.all_characters)

    def refresh_grail_state(self):
        return self.holy_grail.refresh(self.all_characters)

    def handle_character_death(self, character, death_location):
        """把所有死亡来源汇入同一套游戏清理流程。"""
        for familiar in list(getattr(character, "familiars", [])):
            self.despawn_character(familiar, reason="summoner_exit")
        self.command_spell_transfer_manager.on_character_death(character)
        self.reality_marble_manager.on_character_death(character)
        self.observation_manager.remove_owner(character)
        self.field_manager.remove_for_owner_death(character)
        self.trap_manager.remove_owner_traps(character, reason="owner_death")
        # Owner death may have collapsed the Reality Marble before cleanup.
        death_location = character.position or death_location
        self.holy_grail.note_carrier_death(character, death_location)
        if character in self.characters:
            self.characters.remove(character)
        if character not in self.dead_characters:
            self.dead_characters.append(character)
        self.turn_manager.remove_character(character)
        self._unlink_character_relations(character)
        self.event_manager.emit(
            "character_died",
            actor=character,
            source=character,
            target=character,
            position=death_location,
        )
        return True

    def is_player_character(self, character):
        return character in self.player_characters

    def handle_grail_investigation(self, character, decision_provider=None):
        self.refresh_grail_state()
        grail = self.holy_grail
        result = {"available": False, "action": None}
        if not grail.appeared or not self.is_player_character(character):
            return result

        if grail.carrier is character:
            result["available"] = True
            if decision_provider is None:
                return result
            should_drop = decision_provider.choose(DecisionRequest(
                character=character,
                phase="调查—圣杯",
                prompt="是否将圣杯留在当前地点？",
                options=(
                    DecisionOption("丢弃圣杯", True, ("drop", "丢弃")),
                    DecisionOption("继续携带", False, ("keep", "保留")),
                ),
            ))
            if should_drop and grail.drop(character):
                result["action"] = "dropped"
            return result

        if grail.carrier is None and character.position is grail.position:
            result["available"] = True
            if decision_provider is None:
                return result
            should_pick_up = decision_provider.choose(DecisionRequest(
                character=character,
                phase="调查—圣杯",
                prompt="是否拾取圣杯？",
                options=(
                    DecisionOption("拾取圣杯", True, ("pick_up", "拾取")),
                    DecisionOption("不拾取", False, ("leave", "留下")),
                ),
            ))
            if should_pick_up and grail.pick_up(character):
                result["action"] = "picked_up"
        return result

    def is_battle_request_target(self, character, ap_layer=None):
        for encounter in self.turn_manager.pending_encounters:
            for request in encounter.battle_requests:
                if request.target is character:
                    return True
        for request in self.turn_manager.pending_battle_requests:
            if request.target is character:
                return True
        return False

    def announce_grail_position(self, ap_layer):
        self.refresh_grail_state()
        if not self.holy_grail.appeared:
            return []
        location = self.holy_grail.position
        announcement = {
            "turn": self.turn_manager.turn,
            "ap_layer": ap_layer,
            "location": location,
            "ready": self.holy_grail.ready,
            "recipients": [
                character
                for character in self.player_characters
                if character.is_alive()
            ],
        }
        self.grail_announcements.append(announcement)
        location_name = getattr(location, "name", str(location))
        for character in announcement["recipients"]:
            print(
                f"{character.name}：圣杯位于{location_name}"
                f"（{'Ready' if self.holy_grail.ready else '未就绪'}）"
            )
            self.rule_reports.record("grail_announced", actor=character, private=True,
                                     position=location,
                                     actor_data={"location_name": location_name,
                                                 "ready": self.holy_grail.ready, "ap_layer": ap_layer})
        return announcement["recipients"]

    def on_ap_checkpoint(self, ap_layer):
        self.holy_grail.resolve_pending_drop()
        self.refresh_grail_state()
        recipients = self.announce_grail_position(ap_layer)
        self.event_manager.emit(
            "ap_checkpoint",
            phase=f"AP{ap_layer}_checkpoint",
            payload={"ap_layer": ap_layer},
        )
        return recipients

    def declare_victory(self, master):
        from game.character.masters import Master

        if self.ended or not isinstance(master, Master):
            return False
        winners = [master]
        winners.extend(
            servant
            for servant in master.servants
            if servant.is_alive()
        )
        return self.end_game(reason="victory", winners=winners)

    def resolve_turn_end_event(self, turn_number, decision_provider=None):
        # Expiry follows all end-of-turn triggers. New/refreshed durations from
        # those triggers belong to the next boundary, not the current snapshot.
        characters = list(self.all_characters)
        snapshots = {character: {m: m.duration_revision for m in character.modifiers}
                     for character in characters}
        self.event_manager.emit(
            "global_turn_end",
            phase="global_turn_end",
            payload={"turn_number": turn_number},
            decision_provider=decision_provider,
        )
        for character in characters:
            character.update_modifiers("global_turn_end", turn_number=turn_number,
                                       duration_snapshot=snapshots[character])

    def on_turn_end(self, turn_number, *, emit_event=True, decision_provider=None):
        if emit_event:
            self.resolve_turn_end_event(turn_number, decision_provider=decision_provider)
        self.observation_manager.end_turn(turn_number)
        self.field_manager.end_turn(turn_number)
        self.reality_marble_manager.end_turn(turn_number)
        self.command_spell_transfer_manager.end_turn(turn_number)
        self.summon_manager.end_turn(turn_number)
        self.refresh_grail_state()
        if self.ended or turn_number < self.maximum_turns:
            return False
        for character in self.characters[:]:
            if character.is_alive():
                character.die()
            else:
                character.status_flags.add("dead")
        self.refresh_grail_state()
        return self.end_game(reason="turn_limit")

    def end_game(self, reason="external", winners=None):
        if self.ended:
            return False
        self.ended = True
        self.end_reason = reason
        self.winners = list(winners or [])
        for character in self.winners:
            character.status_flags.add("Victory")
        return True

    def force_end_game(self, reason="external", winners=None):
        """供特殊胜利或其他外部结算直接调用。"""
        return self.end_game(reason=reason, winners=winners)

    def get_battle_at(self, position, exclude=None):
        for battle in self.turn_manager.battles:
            if battle is exclude or battle.ended:
                continue
            if any(
                participant.is_alive()
                and participant.position is position
                for participant in battle.participants
            ):
                return battle
        return None

    def resolve_command_spell_teleport(
        self,
        character,
        destination,
        *,
        emergency_guard_target=None,
        decision_provider=None,
    ):
        """Apply command-spell transfer using the shared spatial-transfer rules."""
        return self.resolve_relocation(
            character,
            destination,
            emergency_guard_target=emergency_guard_target,
            decision_provider=decision_provider,
            reason="command_spell_teleport",
        )

    def resolve_relocation(
        self,
        character,
        destination,
        *,
        emergency_guard_target=None,
        decision_provider=None,
        reason="relocate",
    ):
        """Move one character and reconcile combat/AP state without rerolls.

        Callers own destination eligibility and costs. This common resolution
        keeps skill transfers, command spells and GM transfers consistent.
        """
        if not character.is_alive() or destination is character.position:
            return False

        # The casting runtime owns the corresponding MP refund.
        character.interrupt_casting(reason=reason)
        character.detach_ride_group()

        origin_battle = character.current_battle
        had_attack_phase = (
            origin_battle is not None and character.attack_phase_count > 0
        )

        # Position-locked attacks lose a teleported target. Character-locked
        # attacks follow it and receive a detached/simple defense resolution
        # after the destination state has been reconciled.
        tracked_attacks = []
        for owner in list(self.characters):
            for attack in list(owner.pending_attacks):
                if attack.target is not character:
                    continue
                if getattr(attack, "target_lock", False):
                    tracked_attacks.append(attack)
                    continue
                if attack.miss_because_target_moved():
                    owner.pending_attacks.remove(attack)

        if character.travel_group is not None:
            self.turn_manager.leave_travel_group(character)
        if origin_battle is not None:
            origin_battle.remove_participant(
                character,
                preserve_target_locked_attacks=True,
                decision_provider=decision_provider,
            )
            if not character.is_alive():
                return {
                    "character": character, "destination": destination,
                    "origin_battle": origin_battle, "destination_battle": None,
                    "had_attack_phase": had_attack_phase, "trap_results": [],
                    "interrupted_by_death": True,
                }

        character.position = destination
        self.turn_manager.movement_resolver.invalidate_contacts(character)
        trap_results = self.trap_manager.trigger_entry(
            [character],
            destination,
            decision_provider=decision_provider,
        )
        if not character.is_alive():
            if origin_battle is not None:
                origin_battle.check_battle_end()
            return {
                "character": character,
                "destination": destination,
                "origin_battle": origin_battle,
                "destination_battle": None,
                "had_attack_phase": had_attack_phase,
                "trap_results": trap_results,
            }
        destination_battle = self.get_battle_at(destination)
        if destination_battle is not None:
            destination_battle.add_participant(character)
            if origin_battle is not None:
                character.attack_phase_count = (
                    character.attack_phase_count if had_attack_phase else 0
                )
            else:
                character.attack_phase_count = (
                    1 if self.turn_manager.ap1_is_unfinished(character) else 0
                )
            # Even without an attack phase, a teleported newcomer must receive
            # their guard/defense windows at the end of this battle round.
            destination_battle.queue_late_participant(character)
            legal_guard_targets = destination_battle.get_emergency_guard_targets(
                character,
                position=destination,
            )
            if emergency_guard_target in legal_guard_targets:
                destination_battle.resolve_emergency_guard(
                    character,
                    emergency_guard_target,
                    decision_provider,
                )
        elif origin_battle is not None:
            character.attack_phase_count = 0
            character.temporary_mp_waits_for_personal_turn_end = False
            character.action_point = 2 if had_attack_phase else 0
            self.turn_manager.register_battle_exit_to_map(
                character,
                grant_full_ap=had_attack_phase,
            )
        else:
            self.turn_manager.replan_after_map_teleport(character)

        if tracked_attacks and character.is_alive():
            resolver = destination_battle or origin_battle
            if resolver is not None:
                resolver.resolve_simple_round_attack_events(
                    [
                        attack
                        for attack in tracked_attacks
                        if attack in character.pending_attacks
                        and not attack.resolved
                    ],
                    decision_provider,
                )

        self.turn_manager.update_visibility()
        if destination_battle is None:
            encounters = self.turn_manager.movement_resolver.check_encounter(
                self.characters,
                [],
            )
            self.turn_manager.queue_teleport_encounters(encounters)
        if origin_battle is not None:
            origin_battle.check_battle_end()
        return {
            "character": character,
            "destination": destination,
            "origin_battle": origin_battle,
            "destination_battle": destination_battle,
            "had_attack_phase": had_attack_phase,
            "trap_results": trap_results,
        }
