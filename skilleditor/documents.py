"""Small document operations shared by the editor UI and its tests."""

from copy import deepcopy
import json

from core.catalog import CATEGORIES, parse_json

KINDS = {"固有技能": "personal_skill", "基础魔术": "basic_magic", "宝具": "noble_phantasm",
         "御主卡": "character_card", "从者卡": "character_card", "职介技能": "class_skill"}
LABELS = {"personal_skill": "固有技能", "class_skill": "职介技能", "basic_magic": "基础魔术", "noble_phantasm": "宝具", "character_card": "角色卡"}


def format_json(data):
    return json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def copy_definition(category, key, definition):
    data = deepcopy(definition)
    if category == "class_skill":
        data["name"] = key
        return data
    field = "card_id" if category == "character_card" else "skill_id"
    data[field] = f"basic_magic:{key}" if category == "basic_magic" else key
    return data


def new_definition(kind, key):
    category = KINDS[kind]
    if category == "class_skill":
        return {"name": key, "ranks": {"C": [{"component_id": "passive", "type": "passive",
                "target": "self", "effects": [{"effect_type": "attack_bonus", "polarity": "buff",
                                               "effect_data": {"value": 5}}]}]}}
    if category == "character_card":
        data = {"card_id": key, "character_type": "master" if kind == "御主卡" else "servant",
                "name": "新角色", "attributes": {name: 3 for name in ("strength", "endurance", "flexibility", "magic", "fortune")},
                "class_skills": [], "personal_skills": [], "basic_magics": [], "noble_phantasms": []}
        data.update({"talent": "C", "command_spell": 3} if kind == "御主卡" else {"servant_class": "Saber", "noble": "C"})
        return data
    data = {"skill_id": f"basic_magic:{key}" if category == "basic_magic" else key,
            "name": "新技能", "rank": "C", "description": "请修改名称、说明和效果。",
            "components": [{"component_id": "active", "type": "active", "available_phases": ["AP1", "AP2"],
                            "target": "self", "cost": [{"resource": "action_point", "value": 1}],
                            "effects": [{"effect_type": "attack_bonus", "polarity": "buff", "duration": 1,
                                         "effect_data": {"value": 5}}]}]}
    if category == "noble_phantasm":
        data.update({"noble_phantasm_type": "support", "range_type": "anti_unit", "casting": {"mp_cost": 10}})
        data["components"][0].update({"component_id": "release", "casting_requirement": 1,
            "available_phases": ["attack_phase"], "cost": [{"resource": "attack_phase_count", "value": 1}]})
    return data


def parse_entry(text):
    data = parse_json(text)
    if (not isinstance(data, dict) or set(data) != {"category", "entry_id", "definition"}
            or data["category"] not in CATEGORIES or not isinstance(data["entry_id"], str)
            or not isinstance(data["definition"], dict)):
        raise ValueError("条目文件必须包含category、entry_id和definition")
    return data
