"""Strict editor ranks and automatic IDs; canonical engine card data is retained."""

from copy import deepcopy
import re

from game.character.character import Character
from game.character.servants import VALID_SERVANT_CLASSES
from game.rank.rank import FixedRank


ATTRIBUTE_NAMES = {"strength": "筋力", "endurance": "耐久", "flexibility": "敏捷", "magic": "魔力", "fortune": "幸运"}
ATTRIBUTE_RANKS = ("E", "D", "C", "B", "A")
RANK_VALUES = {rank: index for index, rank in enumerate(ATTRIBUTE_RANKS, 1)}
FIXED_RANK_CHOICES = ("C", "B", "A", "EX")


def parse_fixed_rank(text, *, allow_plus):
    match = re.fullmatch(r"(EX|GM|C|B|A)(\+?)", text.strip())
    if match is None:
        raise ValueError("等级请填写C、B、A、EX或GM")
    rank, plus = match.group(1), len(match.group(2))
    FixedRank(rank, plus, allow_plus=allow_plus)
    return {"rank": rank, "plus": plus} if plus else rank


def display_fixed_rank(value):
    return value["rank"] + "+" * value.get("plus", 0) if isinstance(value, dict) else value


def parse_attribute(text):
    text = text.strip()
    if re.fullmatch(r"[EDCBA]\+{0,2}", text) is None:
        raise ValueError("属性只接受E、D、C、B、A，可附加+或++，例如C+、A++")
    value, plus = RANK_VALUES[text[0]], len(text) - 1
    return {"value": value, "plus": plus} if plus else value


def display_attribute(value):
    number, plus = (value.get("value"), value.get("plus", 0)) if isinstance(value, dict) else (value, 0)
    if type(number) is not int or number not in range(1, 6) or type(plus) is not int or plus not in range(3):
        raise ValueError("此属性超出角色编辑器支持的E～A及最多两个加符范围")
    return ATTRIBUTE_RANKS[number - 1] + "+" * plus


def next_card_id(kind, servant_class, cards):
    if kind == "master":
        prefix = "master"
    elif kind == "servant" and servant_class in VALID_SERVANT_CLASSES:
        prefix = servant_class.lower() + "_"
    else:
        raise ValueError("请选择Master或Servant；Servant必须选择合法职介")
    numbers = [int(match.group(1)) for key in cards if (match := re.fullmatch(re.escape(prefix) + r"([0-9]+)", key))]
    return prefix + str(max([9, *numbers]) + 1)


def new_card(kind, servant_class, cards):
    data = {"card_id": next_card_id(kind, servant_class, cards), "character_type": kind,
            "name": "", "attributes": {name: 3 for name in Character.ATTRIBUTE_NAMES},
            "class_skills": [], "personal_skills": [], "basic_magics": [], "noble_phantasms": []}
    data.update({"talent": "C", "command_spell": 3} if kind == "master" else {"servant_class": servant_class, "noble": "C"})
    return data


def class_ranks(definition):
    return tuple(rank for rank, components in definition.get("ranks", {}).items() if components)


def validate_editor_card(data, catalogs):
    """Editor selection limits supplement, without narrowing, the engine schema."""
    if not isinstance(data.get("name"), str) or not data["name"].strip():
        raise ValueError("请填写角色名称")
    attributes = data.get("attributes", {})
    if set(attributes) != set(ATTRIBUTE_NAMES):
        raise ValueError("请填写全部五项基础属性")
    for name, value in attributes.items():
        try:
            display_attribute(value)
        except ValueError as error:
            raise ValueError(f"{ATTRIBUTE_NAMES[name]}：{error}") from error
    classes = data.get("class_skills", [])
    if data.get("character_type") == "master" and classes:
        raise ValueError("御主没有职介技能，请选择基础魔术")
    if len(classes) > 2 or len({item["name"] for item in classes}) != len(classes):
        raise ValueError("职介技能至多选择两个，不能重复")
    for item in classes:
        if item["name"] not in catalogs["class_skill"] or item["rank"] not in class_ranks(catalogs["class_skill"][item["name"]]):
            raise ValueError(f"职介技能没有可用定义：{item['name']} {item['rank']}")
    personal = data.get("personal_skills", [])
    if len(personal) > 3 or len(set(personal)) != len(personal):
        raise ValueError("固有技能至多选择三个，不能重复")
    if any(key not in catalogs["personal_skill"] for key in personal):
        raise ValueError("所选固有技能不在技能库中，请刷新技能库后重新选择")
    basic = data.get("basic_magics", [])
    if len(set(basic)) != len(basic):
        raise ValueError("基础魔术不能重复选择")
    if any(key not in catalogs["basic_magic"] for key in basic):
        raise ValueError("所选基础魔术不在技能库中，请刷新技能库后重新选择")
    return deepcopy(data)
