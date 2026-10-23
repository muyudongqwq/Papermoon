"""可直接装载的基础魔术数据。

这里只收录规则文本明确、且现有运行时能够完整结算的条目。仍需新增
关键词或确认行动时机的旧条目保存在 ``PENDING_BASIC_MAGIC_DATA``，不会
混入玩家的可执行行动列表。
"""


def _refresh_stacking(stack_group):
    return {
        "stack_group": stack_group,
        "stack_scope": "all_sources",
        "stacking_rule": "refresh",
        "max_stacks": 1,
    }


BASIC_MAGIC_DATA = {
    "familiar": {
        "skill_id": "basic_magic:familiar",
        "name": "使魔",
        "rank": "C",
        "skill_category": "basic_magic",
        "rules_text": (
            "消耗10MP召唤基础使魔。战斗外只能在AP1使用并占用2AP；"
            "战斗中占用1个攻击阶段。"
        ),
        "components": [
            {
                "component_id": "summon_non_battle",
                "name": "战斗外召唤",
                "type": "active",
                "available_phases": ["AP1"],
                "resolution_timing": "immediate",
                "target": "current_position",
                "condition": {
                    "actor_alive": True,
                    "battle_state": False,
                    "position_required": True,
                },
                "cost": [
                    {"resource": "action_point", "value": 2},
                    {"resource": "mp", "value": 10},
                ],
                "effects": [{
                    "effect_type": "summon",
                    "effect_data": {
                        "template_id": "basic_magic_familiar",
                        "placement_rule": "current_position",
                        "duration": None,
                        "activate_immediately": False,
                        "remove_with_source": False,
                    },
                }],
            },
            {
                "component_id": "summon_in_battle",
                "name": "战斗中召唤",
                "type": "active",
                "available_phases": ["attack_phase"],
                "resolution_timing": "immediate",
                "target": "current_position",
                "condition": {
                    "actor_alive": True,
                    "battle_state": True,
                    "position_required": True,
                },
                "cost": [
                    {"resource": "attack_phase_count", "value": 1},
                    {"resource": "mp", "value": 10},
                ],
                "effects": [{
                    "effect_type": "summon",
                    "effect_data": {
                        "template_id": "basic_magic_familiar",
                        "placement_rule": "current_position",
                        "duration": None,
                        "activate_immediately": False,
                        "remove_with_source": False,
                    },
                }],
            },
        ],
    },
    "insight": {
        "skill_id": "basic_magic:insight",
        "name": "洞悉",
        "rank": "C",
        "skill_category": "basic_magic",
        "rules_text": (
            "消耗10MP和1AP，观测任意地图节点至本回合结束；"
            "无视隐蔽获得该区域人员视野，并记录本AP由此出发者的职介与移动第一步。"
        ),
        "components": [{
            "component_id": "observe",
            "type": "active",
            "available_phases": ["AP1", "AP2"],
            "resolution_timing": "immediate",
            "target": "selectable_map_node",
            "target_rules": {
                "include_roads": True,
                "merge_area_levels": True,
            },
            "condition": {
                "actor_alive": True,
                "battle_state": False,
            },
            "cost": [
                {"resource": "action_point", "value": 1},
                {"resource": "mp", "value": 10},
            ],
            "effects": [{
                "effect_type": "observe_location",
                "effect_data": {},
            }],
        }],
    },
    "workshop": {
        "skill_id": "basic_magic:workshop",
        "name": "工房",
        "rank": "C",
        "skill_category": "basic_magic",
        "rules_text": (
            "消耗10MP和2AP，在当前建筑建立永久工房。"
            "工房主人无视工房内角色的隐蔽与气息遮断。"
        ),
        "components": [{
            "component_id": "establish",
            "type": "active",
            "available_phases": ["AP1"],
            "resolution_timing": "immediate",
            "target": "current_position",
            "condition": {
                "actor_alive": True,
                "battle_state": False,
                "position_required": True,
            },
            "cost": [
                {"resource": "action_point", "value": 2},
                {"resource": "mp", "value": 10},
            ],
            "effects": [{
                "effect_type": "create_field",
                "effect_data": {
                    "field_id": "basic_magic_workshop",
                    "name": "工房",
                    "field_type": "workshop",
                    "radius": 0,
                    "duration": None,
                    "include_area_levels": True,
                    "remove_on_source_death": True,
                    "exclusive_center": True,
                    "owner_unique_key": "basic_magic_workshop",
                    "owner_vision": {
                        "ignore_concealment": True,
                        "share": False,
                    },
                    "center_target": {
                        "requirements": {"is_building": True},
                    },
                    "effects": [],
                },
            }],
        }],
    },
    "magic_bullet": {
        "skill_id": "basic_magic:magic_bullet",
        "name": "魔弹",
        "rank": "C",
        "skill_category": "basic_magic",
         "casting": {"activation_mode": "release"},
        "rules_text": "消耗10MP，以魔术攻击骰进行攻击，命中后造成30点魔术伤害。",
        "components": [{
            "component_id": "battle_cast",
            "type": "active",
            "casting_requirement": 0,
            "resolution_timing": "defense_phase",
            "target": "selectable_enemy",
            "target_rules": {
                "must_be_alive": True,
                "must_be_hostile": True,
                "required_visibility": "own_visible",
            },
            "cost": ([] + [{"resource": "mp", "value": 10, "timing": "casting_start"}]),
            "effects": [{
                "effect_type": "create_attack_event",
                "effect_data": {
                    "attack_stat": "magic_attack",
                    "damage_type": "magic",
                    "damage_value": 30,
                },
            }],
        }],
    },
    "reinforcement": {
        "skill_id": "basic_magic:reinforcement",
        "name": "强化",
        "rank": "C",
        "skill_category": "basic_magic",
         "casting": {"activation_mode": "release"},
        "rules_text": "消耗10MP，使所选基础属性提高1级，持续1回合。",
        "components": [{
            "component_id": "battle_cast",
            "type": "active",
            "casting_requirement": 0,
            "resolution_timing": "immediate",
            "target": "selectable_character",
            "cost": ([] + [{"resource": "mp", "value": 10, "timing": "casting_start"}]),
            "choices": {
                "maximum_selections": 1,
                "allow_duplicate": False,
                "options": [
                    {
                        "choice_id": attribute,
                        "name": label,
                        "effects": [{
                            "modifier_id": (
                                f"basic_magic_reinforcement_{attribute}"
                            ),
                            "name": f"强化：{label}",
                            "effect_type": "attribute_bonus",
                            "polarity": "buff",
                            "stacking": _refresh_stacking(
                                f"basic_magic_reinforcement_{attribute}"
                            ),
                            "duration": 1,
                            "effect_data": {
                                "effect_target": attribute,
                                "value": 1,
                            },
                        }],
                    }
                    for attribute, label in (
                        ("strength", "筋力"),
                        ("endurance", "耐久"),
                        ("flexibility", "敏捷"),
                        ("magic", "魔力"),
                        ("fortune", "幸运"),
                    )
                ],
            },
        }],
    },
    "healing": {
        "skill_id": "basic_magic:healing",
        "name": "治疗",
        "rank": "C",
        "skill_category": "basic_magic",
         "casting": {"activation_mode": "release"},
        "rules_text": "消耗10MP，使一名角色回复15HP。",
        "components": [{
            "component_id": "battle_cast",
            "type": "active",
            "casting_requirement": 0,
            "resolution_timing": "immediate",
            "target": "selectable_character",
            "cost": ([] + [{"resource": "mp", "value": 10, "timing": "casting_start"}]),
            "effects": [{
                "effect_type": "recover_resource",
                "effect_data": {
                    "resource_id": "hp",
                    "value": 15,
                },
            }],
        }],
    },
    "protection": {
        "skill_id": "basic_magic:protection",
        "name": "防护",
        "rank": "C",
        "skill_category": "basic_magic",
        "rules_text": (
            "不占用AP或战斗阶段。投入X点MP（X至多为当前有效魔力Rank×10），"
            "使一名角色获得⌊X×1.5⌋点护盾至本回合结束；同名护盾不可叠加，"
            "再次施加时替换原护盾。"
        ),
        "components": [{
            "component_id": "protect",
            "type": "active",
            "available_phases": [
                "AP1",
                "AP2",
                "guard_phase",
                "defense_phase",
                "attack_phase",
                "simple_round_guard",
                "simple_round_defense",
            ],
            "resolution_timing": "immediate",
            "target": "selectable_character",
            "condition": {"actor_alive": True},
            "inputs": [{
                "input_id": "x",
                "input_type": "resource_amount",
                "resource": "mp",
                "minimum": 1,
                "maximum": {
                    "source": "actor_attribute",
                    "attribute": "magic",
                    "multiplier": 10,
                },
                "prompt": "请输入防护消耗的MP。",
            }],
            "cost": [{
                "resource": "mp",
                "value": {"input_id": "x"},
            }],
            "effects": [{
                "modifier_id": "basic_magic_protection",
                "name": "防护",
                "effect_type": "shield",
                "polarity": "buff",
                "duration": 1,
                "duration_timing": "global_turn_end",
                "stacking": {
                    "stack_group": "basic_magic_protection",
                    "stack_scope": "all_sources",
                    "stacking_rule": "replace",
                    "max_stacks": 1,
                },
                "effect_data": {
                    "value": {"input_id": "x", "multiplier": 1.5},
                },
            }],
        }],
    },
    "trap": {
        "skill_id": "basic_magic:trap",
        "name": "陷阱",
        "rank": "C",
        "skill_category": "basic_magic",
        "rules_text": (
            "消耗10MP和1AP，在当前节点设置陷阱。进入节点且不知晓陷阱的"
            "第一个移动单位触发简易战斗轮；命中者共同分摊30点魔术伤害。"
        ),
        "components": [{
            "component_id": "set_trap",
            "type": "active",
            "available_phases": ["AP1", "AP2"],
            "resolution_timing": "immediate",
            "target": "current_position",
            "condition": {
                "actor_alive": True,
                "battle_state": False,
                "position_required": True,
            },
            "cost": [
                {"resource": "action_point", "value": 1},
                {"resource": "mp", "value": 10},
            ],
            "choices": {
                "maximum_selections": 1,
                "allow_duplicate": False,
                "options": [
                    {
                        "choice_id": "share",
                        "name": "向主从与同行共享陷阱情报",
                        "effects": [{
                            "effect_type": "trap",
                            "effect_data": {
                                "base_damage": 30,
                                "share_knowledge": True,
                            },
                        }],
                    },
                    {
                        "choice_id": "private",
                        "name": "不共享陷阱情报",
                        "effects": [{
                            "effect_type": "trap",
                            "effect_data": {
                                "base_damage": 30,
                                "share_knowledge": False,
                            },
                        }],
                    },
                ],
            },
        }],
    },
}


# 这些名称来自旧数据，但现阶段不能被诚实地转换为完整可执行数据。
PENDING_BASIC_MAGIC_DATA = {}


def get_basic_magic_definition(magic_id):
    try:
        return BASIC_MAGIC_DATA[magic_id]
    except KeyError as error:
        pending = PENDING_BASIC_MAGIC_DATA.get(magic_id)
        if pending is not None:
            raise ValueError(
                f"基础魔术{pending['name']}尚未实装：{pending['blocked_by']}"
            ) from error
        raise ValueError(f"未知的基础魔术：{magic_id}") from error
