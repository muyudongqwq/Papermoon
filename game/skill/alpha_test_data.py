"""Executable content for the two locally supplied alpha-test Servants.

Only mechanics expressible by the shared component system are automated here.
Descriptions call out the few remaining GM-adjudicated clauses explicitly.
"""


_BATTLE_PHASES = [
    "turn_start", "guard_phase", "defense_phase", "attack_phase", "turn_end",
    "simple_round_attack", "simple_round_guard", "simple_round_defense",
]


def _attribute_bonus(attribute, value=1):
    return {
        "effect_type": "attribute_bonus",
        "polarity": "buff",
        "purifiable": False,
        "effect_data": {"effect_target": attribute, "value": value},
    }


def _dice_bonus(target, value, *, duration=1, polarity="buff"):
    return {
        "effect_type": "dice_bonus",
        "polarity": polarity,
        "duration": duration,
        "effect_data": {"effect_target": target, "value": value},
    }


def _damage_reduction(modifier_id, value, *, duration=1):
    return {
        "modifier_id": modifier_id,
        "effect_type": "damage_modifier",
        "polarity": "buff",
        "duration": duration,
        "effect_data": {
            "direction": "incoming",
            "calculation": "flat",
            "value": -value,
            "damage_types": ["physical"],
        },
    }


ALPHA_PERSONAL_SKILL_DATA = {
    "lancer_alpha_test:mystic_eyes": {
        "skill_id": "lancer_alpha_test:mystic_eyes",
        "name": "魔眼·重瞳",
        "rank": "A",
        "description": (
            "GM先手动进行双方魔力判定；成功后再发动本组件，使目标本回合只能进行防御。"
            "当前通用技能系统尚不能自动完成双方属性对抗。"
        ),
        "components": [{
            "component_id": "suppress_fighting_spirit",
            "type": "active",
            "target": "selectable_enemy",
            "condition": {"battle_state": True},
            "available_phases": list(_BATTLE_PHASES),
            "resolution_timing": "immediate",
            "cooldown": {"turns": 2},
            "effects": [{
                "modifier_id": "lancer_alpha_test:mystic_eyes_restriction",
                "effect_type": "action_restriction",
                "polarity": "debuff",
                "duration": 1,
                "effect_data": {
                    "all_actions": True,
                    "exclude_action_ids": ["dodge", "block", "offset", "stay", "pass"],
                    "reason": "受到魔眼·重瞳压制，只能进行防御",
                },
            }],
        }],
    },
    "lancer_alpha_test:might": {
        "skill_id": "lancer_alpha_test:might",
        "name": "力拔山兮气盖世",
        "rank": "A",
        "description": "筋力常驻+1；举重时视为EX的专用判定暂由GM裁定。",
        "components": [{
            "component_id": "overwhelming_strength",
            "type": "passive",
            "target": "self",
            "effects": [_attribute_bonus("strength")],
        }],
    },
    "lancer_alpha_test:last_stand": {
        "skill_id": "lancer_alpha_test:last_stand",
        "name": "破釜沉舟",
        "rank": "A",
        "description": "耐久常驻+1；失去御主时获得战斗续行A。",
        "components": [
            {
                "component_id": "endurance",
                "type": "passive",
                "target": "self",
                "effects": [_attribute_bonus("endurance")],
            },
            {
                "component_id": "gain_battle_continuation",
                "type": "trigger",
                "trigger_event": "master_lost",
                "target": "self",
                "condition": {"condition_id": "master_is_none"},
                "effects": [{
                    "effect_type": "add_skill",
                    "effect_data": {
                        "skill_ref": {
                            "content_type": "personal_skill",
                            "skill_id": "lancer_alpha_test:battle_continuation",
                        },
                    },
                }],
            },
        ],
    },
    "lancer_alpha_test:battle_continuation": {
        "skill_id": "lancer_alpha_test:battle_continuation",
        "name": "战斗续行",
        "rank": "A",
        "description": "魔力供给中断后，首次受到致命伤时保留1HP并维持三回合生命下限。",
        "components": [{
            "component_id": "survive",
            "type": "trigger",
            "target": "self",
            "trigger": {"event_type": "before_battle_continuation", "timing": "before"},
            "condition": {"event_target_is_self": True},
            "usage_limit": {"scope": "battle", "maximum": 1},
            "effects": [{
                "effect_type": "prevent_death",
                "effect_data": {"hp": 1, "hp_floor_duration": 3},
            }],
        }],
    },
    "archer_alpha_test:uncrowned_arms": {
        "skill_id": "archer_alpha_test:uncrowned_arms",
        "name": "无冠的武艺",
        "rank": "A",
        "description": (
            "每场战斗2次，攻击骰+7、闪避骰-4。真名未公开时攻击加成应降至+5，"
            "该公开状态暂由GM手动修正；也可永久失去本技能换取魔力放出（炎）。"
        ),
        "components": [
            {
                "component_id": "martial_mastery",
                "type": "active",
                "target": "self",
                "condition": {"battle_state": True},
                "available_phases": list(_BATTLE_PHASES),
                "resolution_timing": "immediate",
                "usage_limit": {"scope": "battle", "maximum": 2},
                "effects": [
                    _dice_bonus("attack", 7),
                    _dice_bonus("dodge", -4, duration=2, polarity="debuff"),
                ],
            },
            {
                "component_id": "sacrifice_for_flame",
                "name": "舍弃技能：获得魔力放出（炎）",
                "type": "active",
                "target": "self",
                "available_phases": list(_BATTLE_PHASES),
                "resolution_timing": "immediate",
                "effects": [
                    {"effect_type": "remove_skill", "effect_data": {"skill": "self"}},
                    {"effect_type": "add_skill", "effect_data": {
                        "skill_ref": {
                            "content_type": "personal_skill",
                            "skill_id": "archer_alpha_test:mana_burst_flame",
                        },
                    }},
                ],
            },
        ],
    },
    "archer_alpha_test:mana_burst_flame": {
        "skill_id": "archer_alpha_test:mana_burst_flame",
        "name": "魔力放出（炎）",
        "rank": "B",
        "description": "本回合攻击骰+6；普通攻击转为魔术伤害暂由GM在伤害结算时裁定。",
        "components": [{
            "component_id": "flame_attack",
            "type": "active",
            "target": "self",
            "condition": {"battle_state": True},
            "available_phases": list(_BATTLE_PHASES),
            "resolution_timing": "immediate",
            "effects": [_dice_bonus("attack", 6)],
        }],
    },
    "archer_alpha_test:divinity": {
        "skill_id": "archer_alpha_test:divinity",
        "name": "神性",
        "rank": "A",
        "description": (
            "每场战斗2次，本回合物理伤害减免30、闪避骰-4。对神特攻标签暂未自动化；"
            "也可永久失去本技能换取贫者的见识。"
        ),
        "components": [
            {
                "component_id": "divine_defense",
                "type": "active",
                "target": "self",
                "condition": {"battle_state": True},
                "available_phases": list(_BATTLE_PHASES),
                "resolution_timing": "immediate",
                "usage_limit": {"scope": "battle", "maximum": 2},
                "effects": [
                    _damage_reduction("archer_alpha_test:divine_defense", 30),
                    _dice_bonus("dodge", -4, polarity="debuff"),
                ],
            },
            {
                "component_id": "sacrifice_for_insight",
                "name": "舍弃技能：获得贫者的见识",
                "type": "active",
                "target": "self",
                "available_phases": list(_BATTLE_PHASES),
                "resolution_timing": "immediate",
                "effects": [
                    {"effect_type": "remove_skill", "effect_data": {"skill": "self"}},
                    {"effect_type": "add_skill", "effect_data": {
                        "skill_ref": {
                            "content_type": "personal_skill",
                            "skill_id": "archer_alpha_test:insight_of_the_poor",
                        },
                    }},
                ],
            },
        ],
    },
    "archer_alpha_test:insight_of_the_poor": {
        "skill_id": "archer_alpha_test:insight_of_the_poor",
        "name": "贫者的见识",
        "rank": "B",
        "description": (
            "看穿目标底力技并仅对该目标获得40物理减免；当前信息揭露和指定来源减伤"
            "尚未统一，暂实现为本回合对所有来源的40物理减免，由GM负责揭露目标信息。"
        ),
        "components": [{
            "component_id": "insight",
            "type": "active",
            "target": "self",
            "condition": {"battle_state": True},
            "available_phases": list(_BATTLE_PHASES),
            "resolution_timing": "immediate",
            "effects": [_damage_reduction("archer_alpha_test:insight", 40)],
        }],
    },
    "archer_alpha_test:vaikarthana": {
        "skill_id": "archer_alpha_test:vaikarthana",
        "name": "毗迦尔多纳·迦尔纳",
        "rank": "E",
        "negative_skill": True,
        "description": (
            "角色实际幸运按A录入以保留原本加骰，但卡面伪装为E暂不能自动显示；"
            "隐蔽行动已禁用，遭遇时的偷袭资格仍由GM取消。"
        ),
        "components": [{
            "component_id": "cannot_hide",
            "type": "passive",
            "target": "self",
            "effects": [{
                "modifier_id": "archer_alpha_test:cannot_hide",
                "effect_type": "action_restriction",
                "polarity": "debuff",
                "purifiable": False,
                "effect_data": {
                    "action_ids": ["hide"],
                    "reason": "毗迦尔多纳·迦尔纳不能进行隐蔽",
                },
            }],
        }],
    },
}


def _replace_content(old_id, new_id, content_type):
    return [
        {"effect_type": "remove_content", "effect_data": {
            "content_type": content_type, "content_id": old_id, "permanent": True,
        }},
        {"effect_type": "add_content", "effect_data": {
            "content_type": content_type, "content_id": new_id, "permanent": True,
        }},
    ]


ALPHA_NOBLE_PHANTASM_DATA = {
    "lancer_alpha_test:overlord_spear": {
        "skill_id": "lancer_alpha_test:overlord_spear",
        "name": "霸王枪",
        "rank": "B",
        "description": "常驻增加20点基础攻击伤害。",
        "noble_phantasm_type": "support",
        "range_type": "anti_unit",
        "components": [{
            "component_id": "spear_attack",
            "type": "passive",
            "target": "self",
            "effects": [{
                "effect_type": "attack_bonus",
                "polarity": "buff",
                "purifiable": False,
                "effect_data": {"value": 20},
            }],
        }],
    },
    "lancer_alpha_test:spear_king_annihilation": {
        "skill_id": "lancer_alpha_test:spear_king_annihilation",
        "name": "沉舟破釜·枪王击灭",
        "rank": "A",
        "rank_plus": 1,
        "description": "消耗50MP，咏唱一回合，对所选全部敌人造成200点物理伤害，冷却3回合。",
        "noble_phantasm_type": "physical",
        "range_type": "anti_army",
        "components": [{
            "component_id": "release",
            "type": "active",
            "target": "selectable_enemy",
            "casting_requirement": 1,
            "resolution_timing": "defense_phase",
            "cost": [{"resource": "mp", "value": 50, "timing": "casting_start"}],
            "cooldown": {"turns": 3},
            "effects": [{
                "effect_type": "create_attack_event",
                "effect_data": {"damage_type": "physical", "damage_value": 200},
            }],
        }],
    },
    "archer_alpha_test:bhargavastra": {
        "skill_id": "archer_alpha_test:bhargavastra",
        "name": "梵天啊，覆盖大地",
        "rank": "C",
        "rank_plus": 1,
        "description": "消耗30MP，本回合普通攻击基础伤害+70；也可永久舍弃以获得梵天啊，诅咒我身。",
        "noble_phantasm_type": "support",
        "range_type": "anti_unit",
        "casting": {"activation_mode": "instant"},
        "components": [
            {
                "component_id": "empower_attack",
                "type": "active",
                "target": "self",
                "condition": {"battle_state": True},
                "available_phases": list(_BATTLE_PHASES),
                "resolution_timing": "immediate",
                "cost": [{"resource": "mp", "value": 30, "timing": "casting_start"}],
                "effects": [{
                    "effect_type": "attack_bonus", "polarity": "buff", "duration": 1,
                    "effect_data": {"value": 70},
                }],
            },
            {
                "component_id": "sacrifice_for_brahmastra",
                "name": "舍弃宝具：获得梵天啊，诅咒我身",
                "type": "active",
                "target": "self",
                "available_phases": list(_BATTLE_PHASES),
                "resolution_timing": "immediate",
                "effects": _replace_content(
                    "archer_alpha_test:bhargavastra",
                    "archer_alpha_test:brahmastra_kundala",
                    "noble_phantasm",
                ),
            },
        ],
    },
    "archer_alpha_test:brahmastra_kundala": {
        "skill_id": "archer_alpha_test:brahmastra_kundala",
        "name": "梵天啊，诅咒我身",
        "rank": "C",
        "description": "对目标造成120点真实伤害；自身30点真实伤害暂由GM随后结算。",
        "noble_phantasm_type": "physical",
        "range_type": "anti_unit",
        "components": [{
            "component_id": "release",
            "type": "active",
            "target": "selectable_enemy",
            "resolution_timing": "defense_phase",
            "effects": [{
                "effect_type": "create_attack_event",
                "effect_data": {
                    "damage_type": "true_damage", "damage_value": 120,
                    "ignore_block": True, "ignore_shield": True,
                },
            }],
        }],
    },
    "archer_alpha_test:kavacha_and_kundala": {
        "skill_id": "archer_alpha_test:kavacha_and_kundala",
        "name": "日轮啊，化作甲胄",
        "rank": "C",
        "rank_plus": 1,
        "description": (
            "消耗30MP，获得可刷新的60点物理/魔术护盾，近似临时HP。"
            "濒死解除与立即行动暂由GM裁定；也可永久舍弃以获得日轮啊，顺从死亡。"
        ),
        "noble_phantasm_type": "support",
        "range_type": "anti_unit",
        "casting": {"activation_mode": "instant"},
        "components": [
            {
                "component_id": "solar_armor",
                "type": "active",
                "target": "self",
                "available_phases": list(_BATTLE_PHASES),
                "resolution_timing": "immediate",
                "cost": [{"resource": "mp", "value": 30, "timing": "casting_start"}],
                "effects": [{
                    "modifier_id": "archer_alpha_test:solar_armor",
                    "name": "日轮甲胄",
                    "effect_type": "shield",
                    "polarity": "buff",
                    "stacking": {
                        "stack_group": "archer_alpha_test:solar_armor",
                        "stack_scope": "all_sources",
                        "stacking_rule": "replace",
                        "max_stacks": 1,
                    },
                    "effect_data": {"value": 60, "damage_types": ["physical", "magic"]},
                }],
            },
            {
                "component_id": "sacrifice_for_vasavi",
                "name": "舍弃宝具：获得日轮啊，顺从死亡",
                "type": "active",
                "target": "self",
                "available_phases": list(_BATTLE_PHASES),
                "resolution_timing": "immediate",
                "effects": _replace_content(
                    "archer_alpha_test:kavacha_and_kundala",
                    "archer_alpha_test:vasavi_shakti",
                    "noble_phantasm",
                ),
            },
        ],
    },
    "archer_alpha_test:vasavi_shakti": {
        "skill_id": "archer_alpha_test:vasavi_shakti",
        "name": "日轮啊，顺从死亡",
        "rank": "C",
        "description": (
            "咏唱一回合，对所选全部目标造成150点真实伤害。自身60点真实伤害、"
            "3点高光值和死亡后强制完成咏唱尚未自动化，由GM结算。"
        ),
        "noble_phantasm_type": "physical",
        "range_type": "anti_army",
        "components": [{
            "component_id": "release",
            "type": "active",
            "target": "selectable_enemy",
            "casting_requirement": 1,
            "resolution_timing": "defense_phase",
            "effects": [{
                "effect_type": "create_attack_event",
                "effect_data": {
                    "damage_type": "true_damage", "damage_value": 150,
                    "ignore_block": True, "ignore_shield": True,
                },
            }],
        }],
    },
}
