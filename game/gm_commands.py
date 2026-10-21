"""GM-only forced adjustments used by terminal and future UI adapters."""

from game.turn.damage import DamageEvent, DamageResolver


class GMCommandService:
    """Apply explicit GM overrides without pretending they are character actions."""

    DAMAGE_TYPES = {
        0: "true_damage",
        1: "physical",
        2: "magic",
    }

    def __init__(self, game_manager):
        self.game_manager = game_manager

    @staticmethod
    def _parse_integer(value, field_name):
        text = str(value).strip()
        try:
            parsed = int(text)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{field_name}必须是整数：{value}") from error
        if text not in {str(parsed), f"+{parsed}"}:
            raise ValueError(f"{field_name}必须是整数：{value}")
        return parsed

    @staticmethod
    def _resolve_unique_name(name, candidates, kind):
        normalized = str(name).strip().casefold()
        if not normalized:
            raise ValueError(f"{kind}名称不能为空")
        matches = [
            candidate
            for candidate in candidates
            if str(getattr(candidate, "name", "")).strip().casefold()
            == normalized
        ]
        if not matches:
            raise ValueError(f"不存在的{kind}：{name}")
        if len(matches) > 1:
            raise ValueError(f"{kind}名称不唯一：{name}")
        return matches[0]

    def resolve_target(self, name):
        if any(name is candidate for candidate in self.game_manager.characters):
            if not name.is_alive():
                raise ValueError("目标角色已经死亡")
            return name
        target = self._resolve_unique_name(
            name,
            self.game_manager.characters,
            "角色",
        )
        if not target.is_alive():
            raise ValueError(f"目标角色已经死亡：{name}")
        return target

    def _position_candidates(self):
        candidates = list(self.game_manager.get_map_nodes(
            merge_area_levels=False,
        ))

        def add(position):
            if position is not None and position not in candidates:
                candidates.append(position)

        grail = self.game_manager.holy_grail
        add(grail.designated_location)
        add(grail.position)
        for character in self.game_manager.all_characters:
            add(getattr(character, "position", None))
            add(getattr(character, "death_location", None))
            for position in getattr(character, "seen_locations", set()):
                add(position)
        marble = self.game_manager.active_reality_marble
        if marble is not None:
            add(getattr(marble, "entrance", None))
            add(getattr(marble, "interior", None))
        return candidates

    def resolve_position(self, name):
        if any(name is candidate for candidate in self._position_candidates()):
            return name
        return self._resolve_unique_name(
            name,
            self._position_candidates(),
            "地点",
        )

    @staticmethod
    def _resolve_custom_resource(target, resource_name):
        normalized = str(resource_name).strip().casefold()
        matches = [
            resource
            for resource in target.resources.values()
            if normalized in {
                resource.resource_id.strip().casefold(),
                resource.name.strip().casefold(),
            }
        ]
        if not matches:
            raise ValueError(f"{target.name}不存在资源：{resource_name}")
        unique = []
        for resource in matches:
            if resource not in unique:
                unique.append(resource)
        if len(unique) > 1:
            raise ValueError(f"资源名称不唯一：{resource_name}")
        return unique[0]

    def add_resource(self, target_name, resource_name, amount):
        target = self.resolve_target(target_name)
        amount = self._parse_integer(amount, "资源增加量")
        if amount < 0:
            raise ValueError("资源增加量不能小于0")

        normalized = str(resource_name).strip().casefold()
        if normalized in {"hp", "mp"}:
            old_value = getattr(target, normalized)
            setattr(target, normalized, old_value + amount)
            target._emit_builtin_resource_change(
                "resource_gained",
                normalized,
                old_value,
                getattr(target, normalized),
                requested_value=amount,
                operation="add",
                reason="gm_command",
            )
            new_value = getattr(target, normalized)
            resource_id = normalized
        else:
            resource = self._resolve_custom_resource(target, resource_name)
            old_value = resource.current_value
            resource.current_value += amount
            target.resource_manager._emit_change(
                "resource_gained",
                resource,
                old_value,
                operation="add",
                requested_value=amount,
                reason="gm_command",
            )
            new_value = resource.current_value
            resource_id = resource.resource_id
        return {
            "command": "add_resource",
            "target": target,
            "resource_id": resource_id,
            "amount": amount,
            "old_value": old_value,
            "new_value": new_value,
        }

    def damage(self, target_name, damage_type, amount, *, decision_provider=None):
        target = self.resolve_target(target_name)
        damage_type = self._parse_integer(damage_type, "伤害类型")
        if damage_type not in self.DAMAGE_TYPES:
            raise ValueError(f"未知的伤害类型编号：{damage_type}")
        amount = self._parse_integer(amount, "伤害量")
        if amount < 0:
            raise ValueError("伤害量不能小于0")

        event = DamageEvent(
            source=None,
            target=target,
            value=amount,
            damage_type=self.DAMAGE_TYPES[damage_type],
            action_id="gm_direct_attack",
            source_tags={"gm_command", "direct_attack"},
        )
        final_damage = DamageResolver().resolve(
            event,
            decision_provider=decision_provider,
        )
        return {
            "command": "damage",
            "target": target,
            "damage_type": event.damage_type,
            "requested_damage": amount,
            "final_damage": final_damage,
            "event": event,
        }

    def teleport(
        self,
        target_name,
        position_name,
        *,
        decision_provider=None,
    ):
        target = self.resolve_target(target_name)
        destination = self.resolve_position(position_name)
        if destination is target.position:
            raise ValueError(f"{target.name}已经位于{destination.name}")
        result = self.game_manager.resolve_command_spell_teleport(
            target,
            destination,
            decision_provider=decision_provider,
        )
        if not result:
            raise ValueError("目标无法被转移至指定地点")
        return {
            "command": "teleport",
            "target": target,
            "destination": destination,
            "result": result,
        }

    def kill(self, target_name):
        target = self.resolve_target(target_name)
        target.die()
        if target.is_alive() and target in self.game_manager.characters:
            raise ValueError(f"无法使目标死亡：{target_name}")
        return {
            "command": "kill",
            "target": target,
        }
