"""伤害类型的统一命名与校验。"""


VALID_DAMAGE_TYPES = {"physical", "magic", "true_damage"}


def normalize_damage_type(damage_type):
    if damage_type == "healing":
        raise ValueError("healing不是伤害类型；回复应使用recover_resource")
    if damage_type not in VALID_DAMAGE_TYPES:
        raise ValueError(f"未知的伤害类型：{damage_type}")
    return damage_type


def normalize_damage_types(damage_types):
    normalized = set()
    for damage_type in damage_types:
        if damage_type == "all":
            normalized.add("all")
        else:
            normalized.add(normalize_damage_type(damage_type))
    return normalized
