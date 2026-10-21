"""玩家自定义技能与宝具的数据仓库。

录卡时只向这两个字典追加符合统一组件格式的定义。基础魔术有独立的
公共仓库，职介技能继续按名称和Rank从class_skill_data装载。
"""


PERSONAL_SKILL_DATA = {
    "master_test_0:unblemished_person": {
        "skill_id": "master_test_0:unblemished_person",
        "name": "无瑕之人",
        "description": "受到伤害时，可投入MP等量抵消本次伤害。",
        "rank": "A",
        "components": [{
            "component_id": "prevent_damage_with_mp",
            "type": "react",
            "trigger": {
                "event_type": "before_damage",
                "timing": "before",
                "priority": 100,
            },
            "target": "self",
            "condition": {
                "event_target_is_self": True,
                "event_value_at_least": 1,
            },
            "inputs": [{
                "input_id": "prevented_damage",
                "input_type": "resource_amount",
                "resource": "mp",
                "minimum": 1,
                "maximum": {
                    "source": "context",
                    "key": "event_value",
                    "maximum": 400,
                },
                "prompt": "请输入要以MP抵消的伤害（0至400）。",
            }],
            "cost": [{
                "resource": "mp",
                "value": {"input_id": "prevented_damage"},
            }],
            "effects": [{
                "effect_type": "modify_event_value",
                "effect_data": {
                    "operation": "add",
                    "value": {"input_id": "prevented_damage", "multiplier": -1},
                    "minimum": 0,
                },
            }],
        }],
    },
    "master_test_0:world_faith_domination": {
        "skill_id": "master_test_0:world_faith_domination",
        "name": "天物流转",
        "rank": "A",
        "components": [{
            "component_id": "convert_battle_mp",
            "type": "trigger",
            "trigger": {
                "event_type": "battle_round_end",
                "timing": "after",
            },
            "target": "self",
            "condition": {
                "battle_state": True,
                "event_value_at_least": 2,
            },
            "effects": [{
                "effect_type": "grant_temporary_mp",
                "effect_data": {
                    "value_source": "event_value",
                    "multiplier": 0.5,
                },
            }],
        }],
    },
    "master_test_0:starfire": {
        "skill_id": "master_test_0:starfire",
        "name": "星火予此",
        "rank": "A",
        "components": [{
            "component_id": "choose_record",
            "type": "trigger",
            "trigger": {
                "event_type": "global_turn_start",
                "timing": "after",
                "priority": 100,
            },
            "target": "self",
            "choices": {
                "maximum_selections": 1,
                "allow_duplicate": False,
                "options": [
                    {
                        "choice_id": "barrel_replica",
                        "name": "记录：Barrel Replica",
                        "effects": [{
                            "effect_type": "switch_skill_set",
                            "effect_data": {
                                "group_id": "master_test_0:starfire_records",
                                "set_id": "barrel_replica",
                                "skill_ids": ["master_test_0:barrel_replica"],
                            },
                        }],
                    },
                    {
                        "choice_id": "zabaniya",
                        "name": "记录：冥想神经 Zabaniya",
                        "effects": [{
                            "effect_type": "switch_skill_set",
                            "effect_data": {
                                "group_id": "master_test_0:starfire_records",
                                "set_id": "zabaniya",
                                "skill_ids": ["master_test_0:zabaniya"],
                            },
                        }],
                    },
                    {
                        "choice_id": "territory_creation",
                        "name": "记录：阵地制作",
                        "effects": [{
                            "effect_type": "switch_skill_set",
                            "effect_data": {
                                "group_id": "master_test_0:starfire_records",
                                "set_id": "territory_creation",
                                "skill_ids": ["master_test_0:territory_creation"],
                            },
                        }],
                    },
                ],
            },
        }],
    },
    "master_test_0:barrel_replica": {
        "skill_id": "master_test_0:barrel_replica",
        "name": "Barrel Replica",
        "rank": "B",
        "casting": {"mp_cost": 300},
        "components": [
        {
            "component_id": "release_barrel_battle",
            "name": "解放魔术（战斗）",
            "type": "active",
            "casting_requirement": 1,
            "resolution_timing": "defense_phase",
            "target": "selectable_character",
            "condition": {"battle_state": True},
            "target_rules": {
                "exclude_self": True,
                "must_be_alive": True,
                "required_visibility": "any_visible",
            },
            "cooldown": {
                "turns": 6,
                "group": "master_test_0:barrel_replica",
            },
            "effects": [{
                "effect_type": "create_attack_event",
                "effect_data": {
                    "attack_stat": "magic_attack",
                    "damage_type": "magic",
                    "value_source": "target_attribute",
                    "attribute": "magic",
                    "multiplier": 120,
                    "flat": 300,
                    "resolution_channel": "release",
                },
            }],
        },
        {
            "component_id": "release_barrel_remote",
            "name": "解放魔术（超距）",
            "type": "active",
            "casting_requirement": 1,
            "resolution_timing": "defense_phase",
            "target": "selectable_character",
            "condition": {"battle_state": False},
            "target_rules": {
                "exclude_self": True,
                "exclude_same_position": True,
                "must_be_alive": True,
                "required_visibility": "any_visible",
            },
            "cooldown": {
                "turns": 6,
                "group": "master_test_0:barrel_replica",
            },
            "effects": [{
                "effect_type": "add_simple_round",
                "effect_data": {
                    "attacker_rule": "actor",
                    "defender_rule": "target",
                    "trigger_phase": "immediate",
                    "attack_mode": "fixed",
                    "attack_stat": "magic_attack",
                    "damage_type": "magic",
                    "damage_value_source": "target_attribute",
                    "damage_attribute": "magic",
                    "damage_multiplier": 120,
                    "damage_flat": 300,
                    "resolution_channel": "release",
                    "consume_attack_phase": False,
                    "enter_battle": False,
                    "is_ambush": False,
                },
            }],
        }],
    },
    "master_test_0:zabaniya": {
        "skill_id": "master_test_0:zabaniya",
        "name": "冥想神经 Zabaniya",
        "rank": "B",
        "casting": {
            "mp_cost": 0,
            "auto_activate_component_id": "battle_concealment",
        },
        "components": [
            {
                "component_id": "search_area",
                "name": "双重感知",
                "type": "active",
                "available_phases": ["AP1", "AP2"],
                "resolution_timing": "immediate",
                "target": "self",
                "condition": {"battle_state": False},
                "cost": [{"resource": "action_point", "value": 1}],
                "cooldown": {
                    "turns": 6,
                    "group": "master_test_0:zabaniya",
                },
                "effects": [{
                    "effect_type": "perception_check",
                    "effect_data": {"scope": "current_area", "attempts": 2},
                }],
            },
            {
                "component_id": "outside_concealment",
                "name": "信息截断",
                "type": "active",
                "available_phases": ["AP1"],
                "resolution_timing": "immediate",
                "target": "self",
                "condition": {"battle_state": False},
                "cost": [{"resource": "action_point", "value": 2}],
                "cooldown": {
                    "turns": 6,
                    "group": "master_test_0:zabaniya",
                },
                "effects": [{
                    "modifier_id": "master_test_0:information_severance",
                    "name": "信息截断 C",
                    "effect_type": "presence_concealment",
                    "polarity": "buff",
                    "duration": None,
                    "stacking": {
                        "stack_group": "master_test_0:information_severance",
                        "stack_scope": "all_sources",
                        "stacking_rule": "replace",
                        "max_stacks": 1,
                    },
                    "effect_data": {
                        "rank": "C",
                        "value": 2,
                        "remove_when_revealed": True,
                    },
                }],
            },
            {
                "component_id": "battle_concealment",
                "name": "圈境",
                "type": "active",
                "casting_requirement": 1,
                "resolution_timing": "immediate",
                "target": "self",
                "condition": {"battle_state": True},
                "cooldown": {
                    "turns": 6,
                    "group": "master_test_0:zabaniya",
                },
                "effects": [{
                    "modifier_id": "master_test_0:battle_concealment",
                    "name": "圈境 C",
                    "effect_type": "hidden",
                    "polarity": "buff",
                    "duration": 1,
                    "duration_timing": "global_turn_end",
                    "stacking": {
                        "stack_group": "master_test_0:battle_concealment",
                        "stack_scope": "all_sources",
                        "stacking_rule": "replace",
                        "max_stacks": 1,
                    },
                    "effect_data": {
                        "value": "hidden",
                        "requires_building": False,
                        "remove_on_position_change": False,
                        "remove_on_battle_entry": False,
                        "withdraw_from_battle": True,
                        "rejoin_on_expire": True,
                        "prevent_movement": True,
                    },
                }],
            },
        ],
    },
    "master_test_0:territory_creation": {
        "skill_id": "master_test_0:territory_creation",
        "name": "阵地制作",
        "rank": "B",
        "casting": {"mp_cost": 0},
        "components": [{
            "component_id": "upgrade_workshop",
            "name": "展开阵地",
            "type": "active",
            "casting_requirement": 2,
            "resolution_timing": "immediate",
            "target": "selectable_ally",
            "target_rules": {
                "must_be_alive": True,
                "minimum": 1,
                "unlimited_targets": True,
            },
            "effects": [{
                "effect_type": "create_field",
                "effect_data": {
                    "field_id": "master_test_0:territory",
                    "name": "阵地制作 B",
                    "field_type": "territory",
                    "apply_once": True,
                    "center_rule": "actor_position",
                    "radius": 0,
                    "duration": None,
                    "include_area_levels": True,
                    "remove_on_source_death": True,
                    "exclusive_center": True,
                    "owner_unique_key": "basic_magic_workshop",
                    "center_target": {
                        "requirements": {
                            "is_building": True,
                            "owner_field_type": "workshop",
                        },
                    },
                    "effects": [
                        {
                            "modifier_id": "master_test_0:territory_magic_resistance_owner",
                            "name": "阵地：对魔力 B",
                            "effect_type": "magic_resistance",
                            "polarity": "buff",
                            "stacking": {
                                "stack_group": "master_test_0:territory_magic_resistance",
                                "stack_scope": "all_sources",
                                "stacking_rule": "replace",
                                "max_stacks": 1,
                            },
                            "effect_data": {"value": 0.2},
                            "application_mode": "continuous",
                            "effect_target": {"scope": "field_owner", "relation": "self"},
                        },
                        {
                            "modifier_id": "master_test_0:territory_magic_resistance_selected",
                            "name": "阵地：对魔力 B",
                            "effect_type": "magic_resistance",
                            "polarity": "buff",
                            "stacking": {
                                "stack_group": "master_test_0:territory_magic_resistance",
                                "stack_scope": "all_sources",
                                "stacking_rule": "replace",
                                "max_stacks": 1,
                            },
                            "effect_data": {"value": 0.2},
                            "application_mode": "continuous",
                            "effect_target": {"scope": "characters_in_field", "relation": "selected"},
                        },
                        {
                            "effect_type": "perception_check",
                            "effect_data": {"scope": "source_field", "attempts": 1},
                            "application_mode": "turn_end",
                            "effect_target": {"scope": "field_owner", "relation": "self"},
                        },
                    ],
                },
            }],
        }],
    },
}


# Servant_test_0: Archer Nero. Historical descriptions are provenance;
# borrowed class skills use the current class catalog and survival uses the
# current ordering: ordinary brink, battle continuation, then other choices.
from copy import deepcopy as _deepcopy
from game.skill.class_skill_data import CLASS_SKILL_DATA as _CLASS_SKILL_DATA


_INSTANT_BATTLE_PHASES = ["turn_start", "guard_phase", "defense_phase", "attack_phase", "turn_end",
                          "simple_round_attack", "simple_round_guard", "simple_round_defense"]


def _nero_dice_bonus(stat):
    return {"effect_type": "dice_bonus", "polarity": "buff", "duration": 1,
            "effect_data": {"effect_target": stat, "value": 9}}


PERSONAL_SKILL_DATA.update({
    "servant_test_0:imperial_privilege": {
        "skill_id": "servant_test_0:imperial_privilege", "name": "皇帝特权", "rank": "EX",
        "description": "每个全局回合开始免费选择剑术、气息遮断、单独行动或战斗续行A；切换保留已用次数。",
        "components": [{
            "component_id": "choose_privilege", "type": "trigger",
            "trigger": {"event_type": "global_turn_start", "timing": "after", "priority": 100},
            "target": "self",
            "choices": {"options": [
                {"choice_id": key, "name": name, "effects": [{
                    "effect_type": "switch_skill_set", "effect_data": {
                        "group_id": "servant_test_0:imperial_privilege", "set_id": key,
                        "skill_ids": [f"servant_test_0:{key}"],
                    },
                }]}
                for key, name in (("swordsmanship", "剑术 A"), ("presence_concealment", "气息遮断 A"),
                                  ("independent_action", "单独行动 A"), ("battle_continuation", "战斗续行 A"))
            ]},
        }],
    },
    "servant_test_0:swordsmanship": {
        "skill_id": "servant_test_0:swordsmanship", "name": "剑术", "rank": "A",
        "description": "每场战斗3次，免费选择一回合内攻击骰或防御骰+9。",
        "components": [{
            "component_id": "swordsmanship", "type": "active", "target": "self",
            "available_phases": list(_INSTANT_BATTLE_PHASES), "resolution_timing": "immediate",
            "condition": {"battle_state": True}, "usage_limit": {"scope": "battle", "maximum": 3},
            "choices": {"options": [
                {"choice_id": "attack", "name": "攻击骰+9", "effects": [
                    _nero_dice_bonus(stat) for stat in ("physical_attack", "magic_attack")]},
                {"choice_id": "defense", "name": "防御骰+9", "effects": [
                    _nero_dice_bonus(stat) for stat in ("dodge", "block", "offset")]},
            ]},
        }],
    },
    "servant_test_0:presence_concealment": {
        "skill_id": "servant_test_0:presence_concealment", "name": "气息遮断", "rank": "A",
        "description": "隐蔽骰+6；免于调查揭露，主动隐藏时免于感知揭露。",
        "components": _deepcopy(_CLASS_SKILL_DATA["气息遮断"]["A"]),
    },
    "servant_test_0:independent_action": {
        "skill_id": "servant_test_0:independent_action", "name": "单独行动", "rank": "A",
        "description": "无主时免除魔力维持消耗。",
        "components": _deepcopy(_CLASS_SKILL_DATA["单独行动"]["A"]) + [{
            "component_id": "initial_masterless", "type": "passive", "target": "self",
            "condition": {"condition_id": "master_is_none"},
            "effects": _deepcopy(_CLASS_SKILL_DATA["单独行动"]["A"][0]["effects"]),
        }],
    },
    "servant_test_0:battle_continuation": {
        "skill_id": "servant_test_0:battle_continuation", "name": "战斗续行", "rank": "A",
        "description": "通用濒死不可用时，受到致命伤自动保留1HP，每场战斗2次。",
        "components": [{
            "component_id": "survive", "type": "trigger", "target": "self",
            "trigger": {"event_type": "before_battle_continuation", "timing": "before"},
            "condition": {"event_target_is_self": True},
            "usage_limit": {"scope": "battle", "maximum": 2},
            "effects": [{"effect_type": "prevent_death", "effect_data": {"hp": 1}}],
        }],
    },
    "servant_test_0:setting_sun": {
        "skill_id": "servant_test_0:setting_sun", "name": "纵使三度迎来夕阳", "rank": "A",
        "description": "通用濒死、战斗续行之后可选择发动，本全局回合HP最低1且允许回复；整局3次后移除技能。",
        "components": [{
            "component_id": "setting_sun", "type": "react", "target": "self",
            "trigger": {"event_type": "before_lethal_damage", "timing": "before"},
            "condition": {"event_target_is_self": True},
            "limit": {"scope": "event"}, "usage_limit": {"scope": "game", "maximum": 3},
            "effects": [{"effect_type": "prevent_death", "effect_data": {
                "hp": 1, "hp_floor_duration": 1, "remove_skill_when_exhausted": True,
            }}],
        }],
    },
    "servant_test_0:headache": {
        "skill_id": "servant_test_0:headache", "name": "头痛", "rank": "E", "negative_skill": True,
        "description": "明确标记的精神判定-12。",
        "components": [{"component_id": "mental_penalty", "type": "passive", "target": "self",
            "effects": [{"effect_type": "dice_bonus", "polarity": "debuff", "purifiable": False,
                "conditions": {"tags": ["mental"]},
                "effect_data": {"effect_target": "dice_bonus", "value": -12}}],
        }],
    },
})


NOBLE_PHANTASM_DATA = {
    "servant_test_0:golden_theatre": {
        "skill_id": "servant_test_0:golden_theatre", "name": "招荡的黄金剧场", "rank": "B",
        "description": "40MP、咏唱1回合后自动展开，不消耗攻击阶段，持续至本场战斗结束。自身格挡失败保留攻击阶段，未经许可离场者受到60点无法防御的物理伤害。",
        "noble_phantasm_type": "support", "range_type": "bounded_field", "mp_cost": 40,
        "casting": {"auto_activate_component_id": "open_theatre", "activation_mode": "automatic"},
        "components": [{
            "component_id": "open_theatre", "type": "active", "target": "self",
            "casting_requirement": 1, "resolution_timing": "immediate",
            "condition": {"battle_state": True}, "cooldown": {"turns": 1},
            "effects": [{"effect_type": "create_field", "effect_data": {
                "field_id": "servant_test_0:golden_theatre", "name": "黄金剧场",
                "field_type": "bounded_field", "radius": 0, "exclusive_center": False,
                "owner_unique_key": "servant_test_0:golden_theatre", "battle_bound": True,
                # Direct, physical damage uses normal damage modifiers/shields;
                # no defense roll is offered. No extra shield bypass is granted.
                "exit_penalty": {"value": 60, "damage_type": "physical"},
                "effects": [{"effect_type": "add_status", "polarity": "buff", "purifiable": False,
                    "application_mode": "continuous", "effect_target": {"scope": "field_owner"},
                    "effect_data": {"value": "retain_attack_phase_on_failed_defense"}}],
            }}],
        }],
    },
    "servant_test_0:original_fire": {
        "skill_id": "servant_test_0:original_fire", "name": "陨铁之刃·原初之火", "rank": "B",
        "description": "每场战斗3次，免费即时发动，一回合基础攻击伤害+40。",
        "noble_phantasm_type": "support", "range_type": "anti_unit", "mp_cost": 0,
        "casting": {"activation_mode": "instant"},
        "components": [{
            "component_id": "original_fire", "type": "active", "target": "self",
            "available_phases": list(_INSTANT_BATTLE_PHASES), "resolution_timing": "immediate",
            "condition": {"battle_state": True}, "usage_limit": {"scope": "battle", "maximum": 3},
            "effects": [{"effect_type": "attack_bonus", "polarity": "buff", "duration": 1,
                         "effect_data": {"value": 40}}],
        }],
    },
    "servant_test_0:laus_saint_claudius": {
        "skill_id": "servant_test_0:laus_saint_claudius", "name": "童女讴歌的华丽帝政", "rank": "A",
        "description": "100MP、咏唱1回合，消耗一个攻击阶段解放。对所选目标造成基础150点魔术伤害，可闪避、抵消，忽略格挡减伤与护盾。",
        "noble_phantasm_type": "magic", "range_type": "anti_fortress",
        # The engine doubles anti-fortress base cost/damage: final values are
        # the card's explicit 100MP and 150 magic damage, rather than 200/300.
        "mp_cost": 50,
        "components": [{
            "component_id": "release", "type": "active", "casting_requirement": 1,
            "target": "selectable_enemy", "resolution_timing": "defense_phase",
            "cooldown": {"turns": 2},
            "effects": [{"effect_type": "create_attack_event", "effect_data": {
                "damage_type": "magic", "damage_value": 75, "ignore_block": True, "ignore_shield": True,
            }}],
        }],
    },
}
