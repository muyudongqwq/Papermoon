"""Validate reviewed cards and instantiate them through existing rule loaders."""

from copy import deepcopy
import re

from game.character.card_data import CHARACTER_CARD_DATA
from game.character.character import Character
from game.character.masters import Master
from game.character.servants import Servant, VALID_SERVANT_CLASSES
from game.map.map import Location, Road
from game.rank.rank import AttributeRank, FixedRank, SkillRank
from game.skill.class_skill_data import CLASS_SKILL_DATA
from game.skill.content_registry import CONTENT_CATALOGS, validate_noble_phantasm_definition
from game.skill.skill_runtime import (
    load_class_skill,
    validate_personal_skill_definition,
    validate_skill_components,
)


_CONTENT_FIELDS = {
    "personal_skills": "personal_skill",
    "basic_magics": "basic_magic",
    "noble_phantasms": "noble_phantasm",
}
_COMMON_FIELDS = {"card_id", "character_type", "name", "attributes"}
_OPTIONAL_FIELDS = {*_CONTENT_FIELDS, "class_skills", "source"}
_TYPE_FIELDS = {"master": {"talent", "command_spell"}, "servant": {"servant_class", "noble"}}


def _fields(data, required, optional, label):
    if not isinstance(data, dict):
        raise ValueError(f"{label}必须是字典")
    missing = required - set(data)
    unknown = set(data) - required - optional
    if missing:
        raise ValueError(f"{label}缺少字段：{sorted(missing)}")
    if unknown:
        raise ValueError(f"{label}存在未知字段：{sorted(map(str, unknown))}")


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}必须是非空字符串")


def _attribute(value, label):
    if isinstance(value, dict):
        _fields(value, {"value"}, {"plus"}, label)
        number, plus = value["value"], value.get("plus", 0)
    else:
        number, plus = value, 0
    if type(number) is not int or type(plus) is not int:
        raise ValueError(f"{label}的value和plus必须是整数")
    AttributeRank(number, plus)
    return number, plus


def _fixed_rank(value, label, *, allow_plus):
    if isinstance(value, dict):
        _fields(value, {"rank"}, {"plus"}, label)
        rank, plus = value["rank"], value.get("plus", 0)
    else:
        rank, plus = value, 0
    _text(rank, f"{label}.rank")
    if type(plus) is not int:
        raise ValueError(f"{label}.plus必须是整数")
    FixedRank(rank, plus, allow_plus=allow_plus)
    return rank, plus


def validate_character_card_definition(definition):
    """Return detached validated data without creating characters or effects."""
    if not isinstance(definition, dict):
        raise ValueError("角色卡必须是字典")
    kind = definition.get("character_type")
    if not isinstance(kind, str) or kind not in _TYPE_FIELDS:
        raise ValueError("角色类型必须是master或servant")
    _fields(definition, _COMMON_FIELDS | _TYPE_FIELDS[kind], _OPTIONAL_FIELDS, "角色卡")
    _text(definition["card_id"], "card_id")
    if re.fullmatch(r"[a-z][a-z0-9_]*", definition["card_id"]) is None:
        raise ValueError("card_id必须以小写字母开头，只包含小写字母、数字和下划线")
    _text(definition["name"], "角色名")
    if "source" in definition:
        _text(definition["source"], "source")
    attributes = definition["attributes"]
    _fields(attributes, set(Character.ATTRIBUTE_NAMES), set(), "基础属性")
    for name, value in attributes.items():
        _attribute(value, f"attributes.{name}")
    if kind == "master":
        _fixed_rank(definition["talent"], "talent", allow_plus=False)
        command_spell = definition["command_spell"]
        if type(command_spell) is not int or command_spell < 0:
            raise ValueError("初始令咒必须是非负整数")
    else:
        servant_class = definition["servant_class"]
        if servant_class not in VALID_SERVANT_CLASSES:
            raise ValueError(f"未知职介：{servant_class}")
        _fixed_rank(definition["noble"], "noble", allow_plus=True)

    data = deepcopy(definition)
    skill_ids = set()

    def record_skill_id(skill_id):
        _text(skill_id, "内容skill_id")
        if skill_id in skill_ids:
            raise ValueError(f"初始内容重复skill_id：{skill_id}")
        skill_ids.add(skill_id)

    class_skills = data.setdefault("class_skills", [])
    if not isinstance(class_skills, list):
        raise ValueError("class_skills必须是列表")
    for entry in class_skills:
        _fields(entry, {"name", "rank"}, set(), "职介技能")
        _text(entry["name"], "职介技能名")
        _text(entry["rank"], "职介技能等级")
        components = CLASS_SKILL_DATA.get(entry["name"], {}).get(entry["rank"])
        if not components:
            raise ValueError(f"未知或尚未定义的职介技能：{entry['name']} {entry['rank']}")
        validate_skill_components(components, path=f"class_skill[{entry['name']}][{entry['rank']}]")
        record_skill_id(f"class:{entry['name']}")

    for field, content_type in _CONTENT_FIELDS.items():
        entry_ids = data.setdefault(field, [])
        if not isinstance(entry_ids, list):
            raise ValueError(f"{field}必须是列表")
        for entry_id in entry_ids:
            _text(entry_id, field)
            content = CONTENT_CATALOGS[content_type].get(entry_id)
            if content is None:
                raise ValueError(f"未知的{content_type}数据：{entry_id}")
            if content_type == "noble_phantasm":
                validate_noble_phantasm_definition(content)
                default_rank = _fixed_rank(data.get("noble", "C"), "noble", allow_plus=True)[0]
                SkillRank(content.get("rank", default_rank))
            else:
                validate_personal_skill_definition(content)
                SkillRank(content["rank"])
            record_skill_id(content["skill_id"])
    if kind == "master" and data["noble_phantasms"]:
        raise ValueError("御主卡不能声明初始宝具")
    if kind == "servant":
        _, plus = _fixed_rank(data["noble"], "noble", allow_plus=True)
        if len(data["noble_phantasms"]) > (3 if plus else 2):
            raise ValueError("初始宝具持有数量超过上限")
    return data


def get_character_card_definition(card_id):
    """Read a reviewed card by exact ID; sample filenames are not parsed here."""
    _text(card_id, "card_id")
    if card_id not in CHARACTER_CARD_DATA:
        raise ValueError(f"未知角色卡：{card_id}")
    data = validate_character_card_definition(CHARACTER_CARD_DATA[card_id])
    if data["card_id"] != card_id:
        raise ValueError(f"角色卡目录键与card_id不一致：{card_id}")
    return data


def validate_character_card_catalog():
    """Validate all definitions and references, without applying passives."""
    return [get_character_card_definition(card_id)["card_id"] for card_id in CHARACTER_CARD_DATA]


def list_character_cards(*, character_type=None):
    if character_type is not None and (
        not isinstance(character_type, str) or character_type not in {"master", "servant"}
    ):
        raise ValueError("角色类型必须是master或servant")
    ids = validate_character_card_catalog()
    return tuple(card_id for card_id in ids
                 if character_type is None or CHARACTER_CARD_DATA[card_id]["character_type"] == character_type)


def create_character_from_card(card_id, *, name=None, position=None, master=None):
    """Create a fresh character with initial context and declared rule contents.

    This does not register the character with a game or assign a Session owner.
    No rule-bearing overrides, callbacks or arbitrary imports are accepted.
    """
    data = get_character_card_definition(card_id)
    if name is not None:
        _text(name, "角色名")
    if position is not None and not isinstance(position, (Location, Road)):
        raise ValueError("初始位置必须是Location或Road")
    if master is not None:
        if data["character_type"] != "servant" or not isinstance(master, Master):
            raise ValueError("只有从者卡可以指定Master对象作为御主")
        if not master.is_alive() or len(master.servants) >= 2:
            raise ValueError("御主已退场或从者数量已达上限")
    arguments = {attribute: _attribute(value, attribute) for attribute, value in data["attributes"].items()}
    arguments["name"] = data["name"] if name is None else name
    if data["character_type"] == "master":
        actor = Master(**arguments, talent=_fixed_rank(data["talent"], "talent", allow_plus=False),
                       command_spell=data["command_spell"])
    else:
        actor = Servant(**arguments, servant_class=data["servant_class"],
                        noble=_fixed_rank(data["noble"], "noble", allow_plus=True))
    actor.card_id = card_id
    try:
        # Load-time passive conditions must see the requested spawn context.
        if position is not None:
            actor.position = position
        if master is not None and not master.add_servant(actor):
            raise ValueError("从者无法加入指定御主")
        for entry in data["class_skills"]:
            if not hasattr(actor, "class_skills"):
                actor.class_skills = []
            load_class_skill(actor, entry["name"], entry["rank"])
        actor.bulk_load_content(**{field: data[field] for field in _CONTENT_FIELDS})
    except Exception:
        actor.position = None
        if master is not None:
            master.remove_servant(actor, trigger_master_lost=False)
        for ally in list(actor.allies):
            actor.remove_ally(ally)
        raise
    return actor


def create_master_test_0(name=None):
    """Compatibility entry for the first reviewed Master card."""
    return create_character_from_card("master_test_0", name=name)
