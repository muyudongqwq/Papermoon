from copy import deepcopy
from dataclasses import dataclass, field

from game.action.action_data import ACTION_DATA, get_action_definition
from game.action.action_rules import get_condition_reasons, target_matches_rules
from game.skill.input_runtime import is_input_expression


PHASE_ALIASES = {
    "attack": "attack_phase",
    "defense": "defense_phase",
}


@dataclass
class ActionContext:
    actor: object
    phase: str
    turn_number: int = 0
    turn_manager: object = None
    battle: object = None
    characters: list = field(default_factory=list)
    encounter: object = None
    planning_mode: bool = True
    incoming_attacks: list = field(default_factory=list)
    game_manager: object = None
    position_overrides: dict = field(default_factory=dict)
    virtual_attack_phase: bool = False

    def __post_init__(self):
        self.phase = PHASE_ALIASES.get(self.phase, self.phase)
        if not self.turn_number:
            self.turn_number = getattr(self.actor, "current_global_turn", 0)
        if self.battle is None:
            self.battle = getattr(self.actor, "current_battle", None)
        if not self.characters and self.turn_manager is not None:
            self.characters = list(self.turn_manager.characters)
        if not self.incoming_attacks:
            self.incoming_attacks = list(
                getattr(self.actor, "pending_attacks", [])
            )
        if self.game_manager is None and self.turn_manager is not None:
            self.game_manager = getattr(
                self.turn_manager,
                "game_manager",
                None,
            )


@dataclass
class ActionEntry:
    action_id: str
    name: str
    definition: dict
    available: bool
    unavailable_reasons: list = field(default_factory=list)
    valid_targets: list = field(default_factory=list)
    input_requests: list = field(default_factory=list)
    skill: object = None
    skill_component: dict = None


@dataclass(frozen=True)
class AttributeChoice:
    """UI-safe value object for a card-selected character attribute."""

    value: str
    name: str


def is_free_immediate_skill_entry(entry):
    """Whether selecting a skill should return to the same phase menu."""
    if entry.skill is None:
        return False
    if entry.definition.get("resolution_timing") != "immediate":
        return False
    for cost in entry.definition.get("cost", []):
        if cost.get("resource") not in {
            "action_point",
            "attack_phase_count",
        }:
            continue
        value = cost.get("value", 0)
        # A variable phase cost cannot be proven free while building the menu.
        if is_input_expression(value) or value > 0:
            return False
    return True


class PathPlanner:
    """记录玩家逐步选择的路径；不进行自动寻路。"""

    def __init__(self, actor, start=None, maximum_steps=None):
        self.actor = actor
        self.start = actor.position if start is None else start
        if self.start is None:
            raise ValueError("移动必须具有起点")
        self.maximum_steps = (
            actor.get_effective_move_conversion()
            if maximum_steps is None
            else maximum_steps
        )
        if self.maximum_steps < 1:
            raise ValueError("移动步数上限必须至少为1")
        self.path = [self.start]

    @property
    def steps(self):
        return len(self.path) - 1

    @property
    def remaining_steps(self):
        return self.maximum_steps - self.steps

    @property
    def current(self):
        return self.path[-1]

    def get_next_options(self):
        if self.remaining_steps <= 0:
            return []
        return list(self.current.connected_locations)

    def add_step(self, destination):
        if self.remaining_steps <= 0:
            raise ValueError("移动力已经用尽")
        if destination not in self.current.connected_locations:
            raise ValueError("下一节点没有与当前位置连接")
        self.path.append(destination)
        return list(self.path)

    def remove_last_step(self):
        if self.steps <= 0:
            return False
        self.path.pop()
        return list(self.path)

    def can_finish(self):
        return self.steps >= 1

    def finish(self):
        if not self.can_finish():
            raise ValueError("move至少需要移动1步；原地空过请使用pass")
        return list(self.path)


class ActionListBuilder:
    def get_action_entries(self, context):
        entries = []
        for action_id, raw_definition in ACTION_DATA.items():
            if context.phase not in raw_definition["available_phases"]:
                continue
            allows_action = getattr(context.actor, "allows_action", None)
            if allows_action is not None and not allows_action(action_id):
                continue

            definition = get_action_definition(action_id)
            if action_id == "release":
                from game.skill.casting import release_options

                source_types = {
                    getattr(skill, "source_type", None)
                    for skill, _component in release_options(context.actor)
                }
                if source_types == {"magic"}:
                    definition["name"] = "解放魔术"
                elif source_types == {"noble_phantasm"}:
                    definition["name"] = "解放宝具"
                elif source_types and source_types <= {
                    "magic",
                    "noble_phantasm",
                }:
                    definition["name"] = "解放魔术/宝具"
            reasons = self.get_unavailable_reasons(definition, context)
            valid_targets = self.get_valid_targets(definition, context)
            if self.requires_selectable_target(definition) and not valid_targets:
                reasons.append("no_valid_targets")

            input_requests = self.get_input_requests(
                definition,
                context,
                valid_targets,
            )
            entries.append(ActionEntry(
                action_id=action_id,
                name=definition["name"],
                definition=definition,
                available=not reasons,
                unavailable_reasons=self.unique(reasons),
                valid_targets=valid_targets,
                input_requests=input_requests,
            ))
        entries.extend(self.get_skill_action_entries(context))
        return sorted(
            entries,
            key=lambda entry: (
                entry.definition["display_order"],
                entry.action_id,
            ),
        )

    def get_skill_action_entries(self, context):
        from game.skill.skill_runtime import (
            iter_character_skills,
            skill_component_is_usable,
        )
        from game.skill.component_runtime import component_runtime_reasons
        from game.skill.casting import get_casting_config

        entries = []
        for skill in iter_character_skills(context.actor):
            active_components = [
                component
                for component in skill.definitions
                if component.get("type") == "active"
            ]
            for component in active_components:
                if get_casting_config(skill) and get_casting_config(skill).get("activation_mode") != "instant":
                    # 具有咏唱配置的组件统一从“解放”入口发动。
                    continue
                if context.phase not in component.get("available_phases", []):
                    continue
                action_id = (
                    component.get("_runtime_action_id")
                    or f"skill:{skill.skill_id}:{component['component_id']}"
                )
                allows_action = getattr(context.actor, "allows_action", None)
                if allows_action is not None and not allows_action(
                    action_id,
                    skill_action=True,
                ):
                    continue
                component_name = component.get("name")
                name = (
                    f"{skill.name}：{component_name}"
                    if component_name and len(active_components) > 1
                    else component_name or skill.name
                )
                definition = {
                    "action_id": action_id,
                    "name": name,
                    "type": "active",
                    "action_type": "skill",
                    "available_phases": list(
                        component.get("available_phases", [])
                    ),
                    "resolution_timing": component.get(
                        "resolution_timing",
                        "immediate",
                    ),
                    "target": component.get("target", "self"),
                    "target_rules": deepcopy(
                        component.get("target_rules", {})
                    ),
                    "condition": deepcopy(component.get("condition", {})),
                    "cost": deepcopy(component.get("cost", [])),
                    "effects": deepcopy(component.get("effects", [])),
                    "inputs": deepcopy(component.get("inputs", [])),
                    "display_order": component.get("display_order", 50),
                }
                if definition["target"] == "selectable_enemy":
                    definition["target_rules"].setdefault(
                        "must_be_alive",
                        True,
                    )
                    definition["target_rules"].setdefault(
                        "must_be_hostile",
                        True,
                    )
                reasons = self.get_unavailable_reasons(definition, context)
                reasons.extend(component_runtime_reasons(
                    context.actor,
                    skill,
                    component,
                    turn_number=context.turn_number,
                    battle=context.battle,
                ))
                if any(
                    effect.get("effect_type") == "create_field"
                    for effect in component.get("effects", [])
                ):
                    from game.skill.field_runtime import FieldEffect

                    game_manager = context.game_manager or getattr(
                        context.actor,
                        "game_manager",
                        None,
                    )
                    if game_manager is not None:
                        for effect in component.get("effects", []):
                            if effect.get("effect_type") != "create_field":
                                continue
                            data = deepcopy(effect.get("effect_data", {}))
                            data.setdefault("center", context.actor.position)
                            preview = FieldEffect(
                                data,
                                context.actor,
                                skill,
                                turn_number=context.turn_number,
                            )
                            if not game_manager.field_manager.can_register(preview):
                                reasons.append("field_center_unavailable")
                                break
                valid_targets = self.get_valid_targets(definition, context)
                valid_targets = [
                    target
                    for target in valid_targets
                    if skill_component_is_usable(
                        component,
                        context.actor,
                        target,
                        skill=skill,
                        phase=context.phase,
                        turn_number=context.turn_number,
                        battle=context.battle,
                        game_manager=context.game_manager,
                        turn_manager=context.turn_manager,
                        incoming_attacks=context.incoming_attacks,
                        position_overrides=context.position_overrides,
                        virtual_attack_phase=context.virtual_attack_phase,
                    )
                ]
                if self.requires_selectable_target(definition) and not valid_targets:
                    reasons.append("no_valid_targets")
                if definition["target"] == "self" and not valid_targets:
                    reasons.append("no_valid_effects")
                entries.append(ActionEntry(
                    action_id=action_id,
                    name=name,
                    definition=definition,
                    available=not reasons,
                    unavailable_reasons=self.unique(reasons),
                    valid_targets=valid_targets,
                    skill=skill,
                    skill_component=component,
                ))
        return entries

    def get_available_actions(self, context):
        return [
            entry
            for entry in self.get_action_entries(context)
            if entry.available
        ]

    def get_unavailable_reasons(self, definition, context):
        actor = context.actor
        condition = definition["condition"]
        reasons = []

        if definition["action_id"] in {
            "chant",
            "interrupt_casting",
            "release",
        }:
            from game.skill.casting import (
                castable_sources,
                release_options,
            )

            state = getattr(actor, "casting_state", None)
            if definition["action_id"] == "chant":
                if state is None and not castable_sources(actor):
                    reasons.append("no_castable_source")
                if context.phase == "AP1" and actor.action_point < 2:
                    reasons.append("insufficient_action_point")
                if (
                    context.phase == "attack_phase"
                    and actor.attack_phase_count < 1
                ):
                    reasons.append("attack_phase_unavailable")
            elif definition["action_id"] == "interrupt_casting":
                if state is None:
                    reasons.append("not_casting")
            elif definition["action_id"] == "release":
                has_release = bool(release_options(actor))
                if not has_release:
                    reasons.append("no_releasable_effect")
                if context.phase == "AP1" and actor.action_point < 2:
                    reasons.append("insufficient_action_point")
                if (
                    context.phase == "attack_phase"
                    and actor.attack_phase_count < 1
                ):
                    reasons.append("attack_phase_unavailable")

        reasons.extend(get_condition_reasons(condition, actor, context))

        if (
            context.phase == "AP1"
            and actor.ap1_forfeited_turn == context.turn_number
        ):
            reasons.append("ap1_forfeited")
        if (
            context.phase == "AP1"
            and actor.forced_move_turn == context.turn_number
            and definition["action_id"] != "move"
        ):
            reasons.append("escape_requires_ap1_move")
        if (
            context.phase == "AP2"
            and context.turn_manager is not None
            and actor in context.turn_manager.layer_actors[2]
        ):
            reasons.append("ap2_already_reserved")

        reasons.extend(self.get_cost_reasons(definition, context))
        return self.unique(reasons)

    def get_cost_reasons(self, definition, context):
        actor = context.actor
        reasons = []
        for cost in definition["cost"]:
            cost_condition = cost.get("condition", {})
            if (
                "battle_state" in cost_condition
                and (
                    True if context.virtual_attack_phase else actor.in_battle
                ) != cost_condition["battle_state"]
            ):
                continue
            if not cost.get("required", True):
                continue

            resource = cost["resource"]
            if "value_source" in cost:
                if resource == "mp" and actor.get_available_mp() < 1:
                    reasons.append("insufficient_mp")
                continue
            required = cost.get("value", 0)
            if is_input_expression(required):
                # 精确消耗要等玩家给出输入后判定；空输入范围已由
                # component_input_reasons阻止进入可用行动列表。
                continue
            required = actor.modifier_manager.calculate_cost(
                required,
                resource=resource,
                cost_id=cost.get("cost_id"),
            )
            if resource == "mp" and hasattr(actor, "get_available_mp"):
                available = actor.get_available_mp()
            elif getattr(actor, "has_resource", lambda _resource: False)(
                resource
            ):
                available = actor.get_available_resource(resource)
            else:
                available = getattr(actor, resource, None)
            if available is None:
                reasons.append(f"unknown_resource:{resource}")
            elif available < required:
                reasons.append(f"insufficient_{resource}")
        return reasons

    def get_valid_targets(self, definition, context):
        candidates = self._get_target_candidates(definition, context)
        return [
            target
            for target in candidates
            if target_matches_rules(
                context.actor,
                target,
                definition["target_rules"],
                context,
                target_type=definition["target"],
            )
        ]

    def _get_target_candidates(self, definition, context):
        actor = context.actor
        target_type = definition["target"]
        rules = definition["target_rules"]

        if target_type == "none":
            return []
        if target_type == "self":
            return [actor]
        if target_type == "current_position":
            return [actor.position] if actor.position is not None else []
        if target_type == "selectable_map_node":
            game_manager = context.game_manager or getattr(
                actor,
                "game_manager",
                None,
            )
            if game_manager is None:
                return []
            nodes = game_manager.get_map_nodes(
                merge_area_levels=rules.get("merge_area_levels", True),
            )
            if not rules.get("include_roads", False):
                from game.map.map import Road

                nodes = [node for node in nodes if not isinstance(node, Road)]
            return nodes
        if target_type == "selectable_character":
            return [
                character
                for character in context.characters
                if character.is_alive()
                and (
                    character is not actor
                    or not rules.get("exclude_self", False)
                )
            ]
        if target_type == "selectable_attribute":
            labels = {
                "strength": "筋力",
                "endurance": "耐久",
                "flexibility": "敏捷",
                "magic": "魔力",
                "fortune": "幸运",
                "noble": "宝具",
            }
            allowed = list(rules.get(
                "allowed_attributes",
                actor.ATTRIBUTE_NAMES,
            ))
            if rules.get("include_noble", False):
                allowed.append("noble")
            return [
                AttributeChoice(attribute, labels.get(attribute, attribute))
                for attribute in dict.fromkeys(allowed)
                if hasattr(actor, attribute)
            ]
        if target_type == "selectable_ally":
            return [
                character
                for character in context.characters
                if character.is_alive()
                and (
                    character is actor
                    or actor.is_ally(character)
                )
                and (
                    character is not actor
                    or rules.get("allow_self", True)
                )
            ]
        if target_type == "selectable_command_spell_recipient":
            from game.character.masters import Master

            return [
                character
                for character in context.characters
                if isinstance(character, Master)
                and character is not actor
                and character.is_alive()
                and not character.in_battle
                and character.position is actor.position
                and getattr(character, "command_spell_transfer", None) is None
            ]
        if target_type == "carry_candidate":
            actor_position = context.position_overrides.get(
                actor,
                actor.position,
            )
            return [
                character
                for character in context.characters
                if character is not actor
                and character.is_alive()
                and not character.in_battle
                and context.position_overrides.get(
                    character,
                    character.position,
                ) is actor_position
                and getattr(character, "ride_group", None) is None
                and getattr(character, "carried_by", None) is None
                and not getattr(character, "resting", False)
                and getattr(character, "command_spell_transfer", None) is None
                and not character.movement_locked
            ]
        if target_type == "incoming_attacks":
            return list(context.incoming_attacks)
        if target_type == "selectable_path":
            if (
                actor.position is None
                or actor.movement_locked
                or actor.has_status("cannot_move")
            ):
                return []
            return list(actor.position.connected_locations)
        if target_type == "selectable_travel_group":
            if getattr(actor, "travel_group", None) is not None:
                return []
            actor_position = context.position_overrides.get(
                actor,
                actor.position,
            )
            targets = []
            seen_groups = set()
            for character in context.characters:
                if character is actor or not character.is_alive():
                    continue
                if character.in_battle:
                    continue
                target_position = context.position_overrides.get(
                    character,
                    character.position,
                )
                if target_position is not actor_position:
                    continue
                group = getattr(character, "travel_group", None)
                members = [character] if group is None else list(group.members)
                if group is not None:
                    if group in seen_groups:
                        continue
                    seen_groups.add(group)
                    target = group.leader
                else:
                    target = character
                if all(
                    actor.is_ally(member) and member.is_ally(actor)
                    for member in members
                ):
                    targets.append(target)
            return targets
        if target_type == "selectable_battle_participant":
            return [
                character
                for character in context.characters
                if character is not actor
                and character.is_alive()
                and character.in_battle
                and character.position is actor.position
                and not actor.is_ally(character)
            ]
        if target_type == "guardable_battle_participant":
            if context.battle is None:
                return []
            return [
                character
                for character in context.battle.participants
                if character is not actor
                and character.is_alive()
                and bool(context.battle.get_guardable_attacks(character))
            ]
        if target_type == "travel_group_members":
            group = getattr(actor, "travel_group", None)
            if group is None or group.leader is not actor:
                return []
            return [
                member
                for member in group.members
                if member is not actor and member.is_alive()
            ]
        if target_type == "characters_within_distance":
            return list(context.characters)
        if target_type == "selectable_enemy":
            candidates = (
                context.battle.participants
                if context.battle is not None
                and definition["action_id"] == "attack"
                and not context.virtual_attack_phase
                else context.characters
            )
            return list(candidates)
        return []

    def get_input_requests(self, definition, context, valid_targets):
        requests = deepcopy(definition["inputs"])
        for request in requests:
            if request.get("source") == "valid_targets":
                request["options"] = list(valid_targets)
            if request.get("maximum_source") == "mend_maximum":
                request["maximum"] = int(min(
                    context.actor.hpmax - context.actor.hp,
                    context.actor.get_available_mp(),
                ))
        return requests

    @staticmethod
    def requires_selectable_target(definition):
        return definition["target"] in {
            "selectable_path",
            "selectable_enemy",
            "selectable_travel_group",
            "selectable_battle_participant",
            "guardable_battle_participant",
            "travel_group_members",
            "selectable_character",
            "selectable_ally",
            "selectable_command_spell_recipient",
            "carry_candidate",
            "selectable_map_node",
            "selectable_attribute",
        }

    @staticmethod
    def unique(values):
        return list(dict.fromkeys(values))
