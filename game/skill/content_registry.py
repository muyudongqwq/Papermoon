"""技能、魔术与宝具的数据校验和统一装载入口。"""

from copy import deepcopy

from game.skill.basic_magic_data import BASIC_MAGIC_DATA
from game.skill.class_skill_data import CLASS_SKILL_DATA
from game.skill.content_data import NOBLE_PHANTASM_DATA, PERSONAL_SKILL_DATA
from game.skill.skill_runtime import (
    create_noble_phantasm,
    create_personal_skill,
    load_basic_magic,
    validate_personal_skill_definition,
    validate_skill_components,
)


CONTENT_CATALOGS = {
    "personal_skill": PERSONAL_SKILL_DATA,
    "basic_magic": BASIC_MAGIC_DATA,
    "noble_phantasm": NOBLE_PHANTASM_DATA,
}


def validate_noble_phantasm_definition(definition):
    required = {
        "skill_id",
        "name",
        "noble_phantasm_type",
        "range_type",
        "components",
    }
    missing = required - set(definition)
    if missing:
        raise ValueError(f"宝具缺少字段：{sorted(missing)}")
    if definition["noble_phantasm_type"] not in {
        "physical",
        "magic",
        "support",
    }:
        raise ValueError("宝具类型必须是physical、magic或support")
    if definition["range_type"] not in {
        "anti_unit",
        "anti_army",
        "anti_fortress",
        "bounded_field",
    }:
        raise ValueError("宝具范围必须是anti_unit、anti_army、anti_fortress或bounded_field")

    # 复用技能组件的结构校验；宝具Rank若由角色卡提供，校验时使用占位值。
    skill_shape = deepcopy(definition)
    skill_shape.setdefault("rank", "C")
    for component in skill_shape["components"]:
        component.setdefault("type", "active")
    return validate_personal_skill_definition(skill_shape)


def validate_content_catalogs():
    """Validate every catalog entry and reject mismatched dictionary keys."""
    validated = {}
    for content_type, catalog in CONTENT_CATALOGS.items():
        ids = set()
        for entry_id, definition in catalog.items():
            if entry_id in ids:
                raise ValueError(f"{content_type}数据ID重复：{entry_id}")
            ids.add(entry_id)
            if content_type == "noble_phantasm":
                validate_noble_phantasm_definition(definition)
            else:
                validate_personal_skill_definition(definition)
            validated.setdefault(content_type, []).append(entry_id)
    validated["class_skill"] = []
    for skill_name, ranks in CLASS_SKILL_DATA.items():
        if not isinstance(ranks, dict):
            raise TypeError(f"职介技能{skill_name}的等级数据必须是字典")
        for rank, components in ranks.items():
            if not components:
                continue
            if not isinstance(components, list):
                raise TypeError(f"职介技能{skill_name} {rank}的组件必须是列表")
            validate_skill_components(
                components,
                path=f"class_skill[{skill_name}][{rank}]",
                label=f"职介技能{skill_name} {rank}",
            )
            validated["class_skill"].append(f"{skill_name}:{rank}")
    return validated


def load_content(character, content_type, entry_id):
    """Load one catalog entry into the correct character collection."""
    if content_type == "basic_magic":
        loaded = load_basic_magic(character, entry_id)
        loaded.content_catalog_id = entry_id
        return loaded
    try:
        definition = deepcopy(CONTENT_CATALOGS[content_type][entry_id])
    except KeyError as error:
        raise ValueError(f"未知的{content_type}数据：{entry_id}") from error
    if content_type == "personal_skill":
        loaded = create_personal_skill(character, definition)
        loaded.content_catalog_id = entry_id
        return loaded
    if content_type == "noble_phantasm":
        loaded = create_noble_phantasm(character, definition)
        loaded.content_catalog_id = entry_id
        return loaded
    raise ValueError(f"未知的内容类型：{content_type}")


def bulk_load_content(
    character,
    *,
    personal_skills=(),
    basic_magics=(),
    noble_phantasms=(),
):
    """Load a character card's declared content in stable input order."""
    requests = (
        ("personal_skill", personal_skills),
        ("basic_magic", basic_magics),
        ("noble_phantasm", noble_phantasms),
    )
    loaded = {
        "personal_skill": [],
        "basic_magic": [],
        "noble_phantasm": [],
    }
    for content_type, entry_ids in requests:
        for entry_id in entry_ids:
            loaded[content_type].append(
                load_content(character, content_type, entry_id)
            )
    return loaded
