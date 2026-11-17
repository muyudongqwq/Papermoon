"""Translate older persisted effect data into the current catalog schema."""

_FIXED_ROUND_FIELDS = {
    "attack_stat", "attack_roll_bonus", "damage_type", "damage_value", "damage_value_source",
    "damage_attribute", "damage_multiplier", "damage_flat", "damage_flat_modifiers",
    "damage_percentage_modifiers", "resolution_channel",
}


def migrate_legacy_effects(value, component=None):
    if isinstance(value, list):
        for item in value:
            migrate_legacy_effects(item, component)
        return
    if not isinstance(value, dict):
        return
    if "component_id" in value and "type" in value:
        component = value

    kind = value.get("effect_type")
    data = value.get("effect_data")
    if isinstance(data, dict):
        if kind == "add_simple_round":
            mode = data.get("attack_mode")
            if mode in ("select", "fixed"):
                data.pop("attack_mode")
            if mode == "fixed" or (mode is None and _FIXED_ROUND_FIELDS.intersection(data)):
                kind = value["effect_type"] = "add_fixed_simple_round"
        if kind == "add_fixed_simple_round":
            for old, new in (("damage_multiplier", "multiplier"), ("damage_flat", "flat"),
                             ("damage_flat_modifiers", "flat_modifiers"),
                             ("damage_percentage_modifiers", "percentage_modifiers")):
                if old in data and new not in data:
                    data[new] = data.pop(old)
        if kind in {"add_skill", "remove_skill"} and data.get("collection") == "personal_skills":
            data.pop("collection")
        if kind == "order_change" and data.get("subject") in ("actor", "target") and "move_actor" not in data:
            data["move_actor"] = data.pop("subject") == "actor"
        if kind == "prevent_death" and type(data.get("remove_skill_when_exhausted")) is bool:
            remove = data.pop("remove_skill_when_exhausted")
            usage = component.get("usage_limit") if component is not None else None
            if remove and isinstance(usage, dict):
                usage.setdefault("remove_skill_when_exhausted", True)

    for item in value.values():
        migrate_legacy_effects(item, component)
