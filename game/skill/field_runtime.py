from copy import deepcopy

from game.map.map import (
    Road,
    get_area_positions,
    get_area_root,
    get_nodes_within_distance,
)
from game.modifier.modifier import create_modifier


FIELD_TYPES = {"workshop", "territory", "bounded_field"}
APPLICATION_MODES = {"continuous", "on_enter", "on_create", "turn_end"}


class FieldEffect:
    """One public, fixed-center workshop/territory/bounded field."""

    source_type = "field_skill"

    def __init__(self, definition, owner, skill, *, turn_number=0):
        center = definition.get("center")
        selected_targets = list(definition.get("selected_targets", []))
        data = deepcopy(definition, {id(obj): obj for obj in [center, *selected_targets] if obj is not None})
        # Runtime game objects must keep identity; deepcopy is only for the
        # serializable definition surrounding them.
        data["center"] = center
        data["selected_targets"] = selected_targets
        self.definition = data
        self.owner = owner
        self.skill = skill
        self.field_id = data["field_id"]
        self.name = data.get("name", self.field_id)
        self.field_type = data.get("field_type", "bounded_field")
        self.center = data.get("center") or owner.position
        self.radius = data.get("radius", 0)
        self.duration = data.get("duration")
        self.remove_on_source_death = data.get(
            "remove_on_source_death",
            False,
        )
        self.remove_with_source = data.get("remove_with_source", False)
        self.exclusive_center = data.get("exclusive_center", True)
        self.include_area_levels = data.get("include_area_levels", False)
        self.owner_unique_key = data.get("owner_unique_key")
        self.owner_vision = deepcopy(data.get("owner_vision"))
        self.effects = list(data.get("effects", []))
        self.selected_targets = selected_targets
        self.cost = data.get("cost", [])
        self.battle_bound = data.get("battle_bound", False)
        self.bound_battle = getattr(owner, "current_battle", None) if self.battle_bound else None
        self.exit_penalty = data.get("exit_penalty")
        self.created_turn = int(turn_number or 0)
        self.removed = False
        self.skill_id = f"field:{self.field_id}:{id(self)}"
        self.rank_name = getattr(skill, "rank_name", None)
        self._active_targets = {index: set() for index in range(len(self.effects))}
        self._continuous_modifiers = {}
        self._validate()
        self.covered_nodes = self._calculate_covered_nodes()
        self.center_nodes = set(
            get_area_positions(self.center)
            if self.field_type == "territory" or self.include_area_levels
            else [self.center]
        )

    def _validate(self):
        from game.resource.costs import validate_costs
        if "maintenance" in self.definition:
            raise ValueError("维持消耗请使用cost列表及maintenance支付时机")
        validate_costs(self.cost, timings=("maintenance",), inputs=False)
        if not self.field_id:
            raise ValueError("场地必须提供field_id")
        if self.field_type not in FIELD_TYPES:
            raise ValueError(f"未知的场地类型：{self.field_type}")
        if self.center is None:
            raise ValueError("场地缺少中心地点")
        if not isinstance(self.radius, int) or isinstance(self.radius, bool):
            raise TypeError("场地radius必须是非负整数")
        if self.radius < 0:
            raise ValueError("场地radius不能小于0")
        if self.duration is not None and (
            not isinstance(self.duration, int)
            or isinstance(self.duration, bool)
            or self.duration < 1
        ):
            raise ValueError("场地duration必须是正整数或None")
        for effect in self.effects:
            mode = effect.get("application_mode", "continuous")
            if mode not in APPLICATION_MODES:
                raise ValueError(f"未知的场地效果触发方式：{mode}")

    def _calculate_covered_nodes(self):
        origins = (
            get_area_positions(self.center)
            if self.field_type == "territory" or self.include_area_levels
            else [self.center]
        )
        covered = set()
        for origin in origins:
            covered.update(get_nodes_within_distance(origin, self.radius))
        return covered

    def validate_location_requirements(self):
        requirements = self.definition.get("center_target", {}).get(
            "requirements",
            self.definition.get("requirements", {}),
        )
        if isinstance(requirements, list):
            requirements = {name: True for name in requirements}
        area_root = get_area_root(self.center)
        is_building = bool(
            not isinstance(self.center, Road)
            and getattr(area_root, "is_building", False)
        )
        if (
            requirements.get("is_building")
            or requirements.get("building_only")
        ) and not is_building:
            return False
        if requirements.get("building_with_high_level") and not (
            is_building
            and getattr(area_root, "high_level_location", None) is not None
        ):
            return False
        if requirements.get("not_road") and isinstance(self.center, Road):
            return False
        if requirements.get("road_only") and not isinstance(self.center, Road):
            return False
        if requirements.get("high_level_only") and not getattr(
            self.center, "is_high_level", False
        ):
            return False
        required_status = requirements.get("location_status")
        if required_status and not self.center.has_status(required_status):
            return False
        required_owner_field_type = requirements.get("owner_field_type")
        if required_owner_field_type:
            manager = getattr(getattr(self.owner, "game_manager", None), "field_manager", None)
            if manager is None or not any(
                not field.removed
                and field.owner is self.owner
                and field.field_type == required_owner_field_type
                and self.center in field.center_nodes
                for field in manager.fields
            ):
                return False
        return True

    def conflicts_with(self, other):
        return bool(
            self.exclusive_center
            and other.exclusive_center
            and self.center_nodes.intersection(other.center_nodes)
        )

    def replaces(self, other):
        return bool(
            self.owner_unique_key
            and self.owner_unique_key == other.owner_unique_key
            and self.owner is other.owner
        )

    def _targets_for(self, effect, characters):
        target_data = effect.get("effect_target", {})
        scope = target_data.get("scope", "characters_in_field")
        relation = target_data.get("relation", "all")
        if scope == "field_owner":
            candidates = [self.owner]
        elif scope == "characters_in_field":
            candidates = [
                character
                for character in characters
                if character.is_alive()
                and character.position in self.covered_nodes
            ]
        else:
            return []
        if relation == "self":
            return [target for target in candidates if target is self.owner]
        if relation == "ally":
            return [
                target for target in candidates
                if target is not self.owner
                and self.owner.is_ally(target)
                and target.is_ally(self.owner)
            ]
        if relation == "enemy":
            return [
                target for target in candidates
                if target is not self.owner
                and not (
                    self.owner.is_ally(target)
                    and target.is_ally(self.owner)
                )
            ]
        if relation == "selected":
            return [target for target in candidates if target in self.selected_targets]
        return candidates

    def _apply_continuous(self, index, effect, target, turn_number):
        key = (index, target)
        if key in self._continuous_modifiers:
            return
        modifier_definition = deepcopy(effect)
        modifier_definition.pop("application_mode", None)
        modifier_definition.pop("effect_target", None)
        # A continuous field modifier lives and dies with the field itself.
        modifier_definition["duration"] = None
        modifier = create_modifier(
            modifier_definition,
            target,
            source=self,
            source_type=self.source_type,
            source_id=self.skill_id,
            applied_turn=turn_number,
            applied_phase="field_refresh",
        )
        result = target.add_modifier(modifier)
        applied = result.modifier
        if getattr(applied, "source", None) is self:
            self._continuous_modifiers[key] = applied

    def _remove_continuous(self, index, target):
        modifier = self._continuous_modifiers.pop((index, target), None)
        if modifier is not None and modifier in target.modifiers:
            target.remove_modifier(modifier)

    def _trigger(self, effect, target, turn_number, phase):
        from game.skill.skill_runtime import apply_skill_effect

        nested = deepcopy(effect)
        nested.pop("application_mode", None)
        nested.pop("effect_target", None)
        return apply_skill_effect(
            nested,
            target,
            self,
            actor=self.owner,
            turn_number=turn_number,
            phase=phase,
        )

    def refresh(self, characters, turn_number=0, *, created=False):
        for index, effect in enumerate(self.effects):
            mode = effect.get("application_mode", "continuous")
            current = set(self._targets_for(effect, characters))
            previous = self._active_targets[index]
            if mode == "continuous":
                for target in current - previous:
                    self._apply_continuous(index, effect, target, turn_number)
                for target in previous - current:
                    self._remove_continuous(index, target)
            elif mode == "on_enter":
                for target in current - previous:
                    self._trigger(effect, target, turn_number, "field_enter")
            elif mode == "on_create" and created:
                for target in current:
                    self._trigger(effect, target, turn_number, "field_create")
            self._active_targets[index] = current

    def pay_maintenance(self):
        from game.resource.costs import costs_at, pay_costs, SkillUnavailableError
        try:
            pay_costs(self.owner, costs_at(self.cost, "maintenance"), f"field:{self.field_id}:maintenance")
        except SkillUnavailableError:
            return False
        return True

    def end_turn(self, characters, turn_number):
        if self.remove_on_source_death and not self.owner.is_alive():
            return False
        if turn_number == self.created_turn:
            return True
        if not self.pay_maintenance():
            return False
        for effect in self.effects:
            if effect.get("application_mode") != "turn_end":
                continue
            for target in self._targets_for(effect, characters):
                self._trigger(effect, target, turn_number, "field_turn_end")
        if self.duration is not None:
            self.duration -= 1
            if self.duration <= 0:
                return False
        return True

    def remove(self):
        if self.removed:
            return False
        for index, targets in self._active_targets.items():
            for target in list(targets):
                self._remove_continuous(index, target)
        for node in self.covered_nodes:
            fields = getattr(node, "field_effects", None)
            if fields is not None and self in fields:
                fields.remove(self)
        self.removed = True
        return True


class FieldManager:
    def __init__(self, game_manager):
        self.game_manager = game_manager
        self.fields = []

    def can_register(self, field):
        if field.battle_bound and (field.bound_battle is None or field.bound_battle.ended):
            return False
        if getattr(field.center, "is_reality_marble_interior", False):
            return False
        return field.validate_location_requirements() and not any(
            field.conflicts_with(existing)
            for existing in self.fields
            if not existing.removed and not field.replaces(existing)
        )

    def register(self, field):
        if not self.can_register(field):
            return False
        replacements = [
            existing
            for existing in self.fields
            if not existing.removed and field.replaces(existing)
        ]
        for existing in replacements:
            self.remove(existing)
        self.fields.append(field)
        for node in field.covered_nodes:
            if not hasattr(node, "field_effects"):
                node.field_effects = []
            node.field_effects.append(field)
        field.refresh(
            self.game_manager.characters,
            self.game_manager.turn_manager.turn,
            created=True,
        )
        from game.game.rule_report import report
        report(field.owner, "field_created", actor=field.owner, private=True, position=field.center,
               actor_data={"field_id": field.field_id, "name": field.name,
                           "battle_bound": field.battle_bound, "duration": field.duration})
        return True

    def resolve_battle_exit(self, battle, character, decision_provider=None):
        """Check every bound field before any kind of living battle exit."""
        from game.turn.damage import DamageEvent, DamageResolver
        from game.turn.decision import DecisionOption, DecisionRequest
        provider = decision_provider or getattr(self.game_manager, "decision_provider", None)
        for field in self.fields[:]:
            if field.removed or field.bound_battle is not battle or not field.exit_penalty:
                continue
            if not character.is_alive():
                break
            allowed = False
            if provider is not None and field.owner.is_alive():
                allowed = provider.choose(DecisionRequest(
                    character=field.owner, phase="battle_exit_permission",
                    prompt=f"{character.name}将脱离{field.name}，是否允许？",
                    options=(DecisionOption("允许离场", True, ("allow",)),
                             DecisionOption("不允许离场", False, ("deny",))),
                ))
            from game.game.rule_report import report
            report(character, "battle_exit_permission", actor=field.owner, targets=[character],
                   involved={"allowed": bool(allowed)},
                   actor_data={"field_id": field.field_id, "field_name": field.name})
            if not allowed:
                penalty = field.exit_penalty
                DamageResolver().resolve(DamageEvent(
                    source=field.owner, target=character,
                    value=penalty["value"], damage_type=penalty["damage_type"],
                    skill=field.skill, action_id="battle_exit_penalty",
                    skill_id=field.skill.skill_id, source_tags={"field", "battle_exit"},
                    source_statuses_snapshotted=True,
                ), decision_provider=provider)

    def on_battle_end(self, battle):
        for field in self.fields[:]:
            if field.bound_battle is battle:
                self.remove(field)

    def owner_visible_characters(self, owner):
        result = []
        for field in self.fields:
            if (
                field.removed
                or field.owner is not owner
                or not field.owner_vision
                or field.field_type == "workshop"
            ):
                continue
            for character in self.game_manager.characters:
                if (
                    character is not owner
                    and character.is_alive()
                    and character.position in field.covered_nodes
                    and character not in result
                ):
                    result.append(character)
        return result

    def owner_visible_nodes(self, owner):
        nodes = set()
        for field in self.fields:
            if (
                not field.removed
                and field.owner is owner
                and field.owner_vision
                and field.field_type != "workshop"
            ):
                nodes.update(field.covered_nodes)
        return nodes

    def ignores_concealment(self, observer, target):
        return any(
            not field.removed
            and field.field_type == "workshop"
            and field.owner is observer
            and target.position in field.covered_nodes
            and bool((field.owner_vision or {}).get("ignore_concealment"))
            for field in self.fields
        )

    def shareable_owner_visible_characters(self, owner):
        result = []
        for field in self.fields:
            if (
                field.removed
                or field.owner is not owner
                or field.field_type == "workshop"
                or not (field.owner_vision or {}).get("share", False)
            ):
                continue
            for character in self.game_manager.characters:
                if (
                    character is not owner
                    and character.is_alive()
                    and character.position in field.covered_nodes
                    and character not in result
                ):
                    result.append(character)
        return result

    def refresh(self):
        turn = self.game_manager.turn_manager.turn
        for field in self.fields[:]:
            if field.remove_on_source_death and not field.owner.is_alive():
                self.remove(field)
                continue
            field.refresh(self.game_manager.characters, turn)

    def end_turn(self, turn_number):
        for field in self.fields[:]:
            if not field.end_turn(self.game_manager.characters, turn_number):
                self.remove(field)
        self.refresh()

    def remove(self, field):
        if field not in self.fields:
            return False
        field.remove()
        self.fields.remove(field)
        from game.game.rule_report import report
        report(field.owner, "field_removed", actor=field.owner, private=True, position=field.center,
               actor_data={"field_id": field.field_id, "name": field.name})
        return True

    def remove_for_owner_death(self, owner):
        removed = []
        for field in self.fields[:]:
            if field.owner is owner and field.remove_on_source_death:
                self.remove(field)
                removed.append(field)
        return removed

    def remove_for_source(self, skill):
        """Remove fields explicitly tied to a dynamically removed skill."""
        removed = []
        for field in self.fields[:]:
            if field.skill is skill and field.remove_with_source:
                self.remove(field)
                removed.append(field)
        return removed
