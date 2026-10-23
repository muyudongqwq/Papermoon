from copy import deepcopy

from game.action.action_rules import validate_condition, validate_target_rules


# type沿用skill数据的含义：主动、被动或触发。
ACTION_TYPES = {"active", "passive", "trigger"}

# action_type描述行动的规则/UI类别，不再承担唯一标识的职责。
ACTION_TYPE_CATEGORIES = {
    "movement",
    "investigation",
    "perception",
    "stealth",
    "attack",
    "defense",
    "recovery",
    "escape",
    "special",
}

ACTION_PHASES = {
    "AP1",
    "AP2",
    "battle_start",
    "turn_start",
    "guard_phase",
    "defense_phase",
    "attack_phase",
    "turn_end",
    "battle_end",
    "simple_round_attack",
    "simple_round_guard",
    "simple_round_defense",
}

RESOLUTION_TIMINGS = {
    "immediate",
    "ap_checkpoint",
    "defense_phase",
    "battle_start",
    "phase_start",
    "phase_end",
    "character_turn_end",
    "global_turn_end",
    "battle_end",
}

TARGET_TYPES = {
    "none",
    "self",
    "current_position",
    "selectable_path",
    "selectable_enemy",
    "characters_within_distance",
    "incoming_attacks",
    "selectable_travel_group",
    "selectable_battle_participant",
    "guardable_battle_participant",
    "travel_group_members",
    "selectable_command_spell_recipient",
    "carry_candidate",
    "selectable_map_node",
    "selectable_character",
    "selectable_ally",
    "selectable_attribute",
}


ACTION_DATA = {
    "move": {
        "action_id": "move",
        "name": "移动",
        "description": "消耗1AP，使角色沿所选路径移动。",
        "type": "active",
        "action_type": "movement",
        "available_phases": ["AP1", "AP2"],
        "resolution_timing": "immediate",
        "target": "selectable_path",
        "target_rules": {
            "minimum_steps": 1,
            "maximum_steps_source": "move_conversion",
            "path_must_be_connected": True,
            "allow_backtracking": True,
            "allow_early_stop": True,
        },
        "condition": {
            "actor_alive": True,
            "battle_state": False,
            "movement_locked": False,
        },
        "cost": [
            {"resource": "action_point", "value": 1},
        ],
        "effects": [
            {
                "effect_type": "move_along_path",
                "effect_data": {
                    "movement_source": "move_conversion",
                    "node_cost": 1,
                    "check_encounter_each_step": True,
                },
            },
        ],
    },
    "pass": {
        "action_id": "pass",
        "name": "空过",
        "description": "不产生效果并消耗当前的1AP。",
        "type": "active",
        "action_type": "special",
        "available_phases": ["AP1", "AP2"],
        "resolution_timing": "immediate",
        "target": "none",
        "target_rules": {},
        "condition": {
            "actor_alive": True,
            "battle_state": False,
        },
        "cost": [
            {"resource": "action_point", "value": 1},
        ],
        "effects": [],
    },
    "join_travel_group": {
        "action_id": "join_travel_group",
        "name": "加入同行",
        "description": "在本AP行动层开始前加入同起点友军的同行团体，不消耗AP。",
        "type": "active",
        "action_type": "special",
        "available_phases": ["AP1", "AP2"],
        "resolution_timing": "phase_start",
        "target": "selectable_travel_group",
        "target_rules": {
            "same_ap_start_position": True,
            "all_members_mutual_allies": True,
            "target_group_leader_remains": True,
        },
        "condition": {
            "actor_alive": True,
            "battle_state": False,
            "position_required": True,
            "not_in_travel_group": True,
            "no_pending_travel_join": True,
        },
        "cost": [],
        "effects": [
            {
                "effect_type": "join_travel_group",
                "effect_data": {
                    "free_action": True,
                    "clear_ap2_plan_when_used_in_ap1": True,
                },
            },
        ],
    },
    "invite_carry": {
        "action_id": "invite_carry",
        "name": "邀请同乘",
        "description": "免费邀请同地点角色成为乘客；受邀者确认后立即生效。",
        "type": "active",
        "action_type": "special",
        "available_phases": ["AP1", "AP2"],
        "resolution_timing": "immediate",
        "target": "carry_candidate",
        "target_rules": {
            "same_position": True,
            "requires_confirmation": True,
        },
        "condition": {
            "actor_alive": True,
            "battle_state": False,
            "position_required": True,
            "carry_capacity_available": True,
        },
        "cost": [],
        "effects": [],
    },
    "leave_carry": {
        "action_id": "leave_carry",
        "name": "结束同乘",
        "description": "乘客下车；骑乘者使用时解除自己的全部携带关系。",
        "type": "active",
        "action_type": "special",
        "available_phases": ["AP1", "AP2"],
        "resolution_timing": "immediate",
        "target": "none",
        "target_rules": {},
        "condition": {
            "actor_alive": True,
            "battle_state": False,
            "in_ride_group": True,
        },
        "cost": [],
        "effects": [],
    },
    "join_battle": {
        "action_id": "join_battle",
        "name": "加入战斗",
        "description": "在当前地点加入一场已经开始的战斗，并锁定后续移动。",
        "type": "active",
        "action_type": "special",
        "available_phases": ["AP1", "AP2"],
        "resolution_timing": "ap_checkpoint",
        "target": "selectable_battle_participant",
        "target_rules": {
            "same_position": True,
            "must_be_alive": True,
            "must_be_hostile": True,
            "target_battle_state": True,
        },
        "condition": {
            "actor_alive": True,
            "battle_state": False,
            "position_required": True,
            "movement_locked": False,
        },
        "cost": [
            {"resource": "action_point", "value": 1},
        ],
        "effects": [
            {
                "effect_type": "submit_battle_request",
                "effect_data": {
                    "source": "join_battle",
                    "lock_movement": True,
                    "lock_ambush_at_ap_checkpoint": True,
                },
            },
        ],
    },
    "transfer_travel_leader": {
        "action_id": "transfer_travel_leader",
        "name": "转让同行leader",
        "description": "当前leader将本回合的同行指挥权免费转让给一名成员。",
        "type": "active",
        "action_type": "special",
        "available_phases": ["AP1", "AP2"],
        "resolution_timing": "immediate",
        "target": "travel_group_members",
        "target_rules": {"exclude_self": True},
        "condition": {
            "actor_alive": True,
            "battle_state": False,
            "travel_group_leader": True,
            "leader_transfer_available": True,
        },
        "cost": [],
        "effects": [
            {
                "effect_type": "transfer_travel_leader",
                "effect_data": {"maximum_per_global_turn": 1},
            },
        ],
    },
    "surrender": {
        "action_id": "surrender",
        "name": "退场",
        "description": "失去所有Servant的Master主动退场并进入死亡流程。",
        "type": "active",
        "action_type": "special",
        "available_phases": ["AP1", "AP2"],
        "resolution_timing": "immediate",
        "target": "self",
        "target_rules": {},
        "condition": {
            "actor_alive": True,
            "actor_type": "Master",
            "battle_state": False,
            "servant_count": 0,
        },
        "cost": [
            {"resource": "action_point", "value": 1},
        ],
        "effects": [
            {
                "effect_type": "leave_game",
                "effect_data": {
                    "status": "dead",
                    "trigger_on_death_effects": False,
                },
            },
        ],
    },
    "wish": {
        "action_id": "wish",
        "name": "许愿",
        "description": "Master在Ready状态的圣杯所在地许愿，并在AP1 checkpoint确定胜利。",
        "type": "active",
        "action_type": "special",
        "available_phases": ["AP1"],
        "resolution_timing": "ap_checkpoint",
        "target": "self",
        "target_rules": {},
        "condition": {
            "actor_alive": True,
            "actor_type": "Master",
            "player_character": True,
            "battle_state": False,
            "position_required": True,
            "grail_ready": True,
            "at_grail_position": True,
        },
        "cost": [
            {"resource": "action_point", "value": 1},
        ],
        "effects": [
            {
                "effect_type": "declare_victory",
                "effect_data": {
                    "include_living_servants": True,
                    "cancel_if_battle_request_target": True,
                    "refund_cost_on_cancel": False,
                },
            },
        ],
    },
    "investigate": {
        "action_id": "investigate",
        "name": "调查",
        "description": "揭露当前位置状态，并记录最近的非隐藏御主和从者的位置。",
        "type": "active",
        "action_type": "investigation",
        "available_phases": ["AP1", "AP2"],
        "resolution_timing": "ap_checkpoint",
        "target": "current_position",
        "target_rules": {},
        "condition": {
            "actor_alive": True,
            "battle_state": False,
            "position_required": True,
            "forbidden_status": ["cannot_investigate"],
        },
        "cost": [
            {"resource": "action_point", "value": 1},
        ],
        "effects": [
            {
                "effect_type": "reveal_location_status",
                "effect_data": {},
            },
            {
                "effect_type": "reveal_nearest_characters",
                "effect_data": {
                    "character_types": ["Master", "Servant"],
                    "exclude_status": ["hidden"],
                    "distance_limit": None,
                    "store_positions_in": "revealed_positions",
                },
            },
        ],
    },
    "perceive": {
        "action_id": "perceive",
        "name": "感知",
        "description": "在本AP层checkpoint感知距离5以内的角色，记录其位置但不获得真实视野。",
        "type": "active",
        "action_type": "perception",
        "available_phases": ["AP1", "AP2"],
        "resolution_timing": "ap_checkpoint",
        "target": "characters_within_distance",
        "target_rules": {
            "distance": 5,
            "exclude_self": True,
            "exclude_own_visible": True,
        },
        "condition": {
            "actor_alive": True,
            "battle_state": False,
            "position_required": True,
        },
        "cost": [
            {"resource": "action_point", "value": 1},
        ],
        "effects": [
            {
                "effect_type": "perception_check",
                "effect_data": {
                    "actor_roll": "1d10+perceive",
                    "target_roll": "1d10+hide",
                    "success_comparison": ">=",
                    "result_list": "own_perceived",
                    "shared_result_list": "shared_perceived",
                    "combined_result_list": "perceived",
                    "remove_outside_distance": 5,
                },
            },
        ],
    },
    "battle_perceive": {
        "action_id": "battle_perceive",
        "name": "感知",
        "description": (
            "在正式战斗的攻击阶段消耗攻击阶段，按既有感知对抗检定"
            "距离5以内尚未看见的角色。"
        ),
        "type": "active",
        "action_type": "perception",
        "available_phases": ["attack_phase"],
        "resolution_timing": "immediate",
        "target": "characters_within_distance",
        "target_rules": {
            "distance": 5,
            "exclude_self": True,
            "exclude_own_visible": True,
        },
        "condition": {
            "actor_alive": True,
            "battle_state": True,
            "position_required": True,
            "attack_phase_count_at_least": 1,
        },
        "cost": [
            {"resource": "attack_phase_count", "value": 1},
        ],
        "effects": [
            {
                "effect_type": "perception_check",
                "effect_data": {
                    "actor_roll": "1d10+perceive",
                    "target_roll": "1d10+hide",
                    "success_comparison": ">=",
                    "result_list": "own_perceived",
                    "shared_result_list": "shared_perceived",
                    "combined_result_list": "perceived",
                    "remove_outside_distance": 5,
                },
            },
        ],
    },
    "hide": {
        "action_id": "hide",
        "name": "隐藏",
        "description": "在建筑内进入隐藏状态；离开建筑时解除。",
        "type": "active",
        "action_type": "stealth",
        "available_phases": ["AP1", "AP2"],
        "resolution_timing": "immediate",
        "target": "self",
        "target_rules": {},
        "condition": {
            "actor_alive": True,
            "battle_state": False,
            "position_is_building": True,
            "forbidden_status": ["hidden"],
        },
        "cost": [
            {"resource": "action_point", "value": 1},
        ],
        "effects": [
            {
                "effect_type": "hidden",
                "polarity": "buff",
                "purifiable": False,
                "effect_data": {
                    "value": "hidden",
                    "duration": None,
                    "remove_when_leaving_building": True,
                },
            },
            {
                "effect_type": "remove_from_visibility",
                "effect_data": {
                    "visibility_lists": [
                        "own_visible",
                        "shared_visible",
                        "any_visible",
                    ],
                },
            },
        ],
    },
    "stay": {
        "action_id": "stay",
        "name": "停留",
        "description": "空过当前攻击阶段，并记录本战斗轮选择了待机。",
        "type": "active",
        "action_type": "special",
        "available_phases": ["attack_phase"],
        "resolution_timing": "immediate",
        "target": "self",
        "target_rules": {},
        "condition": {
            "actor_alive": True,
            "battle_state": True,
        },
        "cost": [
            {"resource": "attack_phase_count", "value": 1},
        ],
        "effects": [
            {
                "duration": 2,
                "effect_type": "add_status",
                "effect_data": {
                    "status_id": "stay",
                },
            },
        ],
    },
    "attack": {
        "action_id": "attack",
        "name": "普通攻击",
        "description": "选择自身视野内的敌人并生成待防御的普通物理攻击。",
        "type": "active",
        "action_type": "attack",
        "available_phases": ["attack_phase"],
        "resolution_timing": "defense_phase",
        "target": "selectable_enemy",
        "target_rules": {
            "minimum": 1,
            "maximum": 1,
            "must_be_alive": True,
            "must_be_hostile": True,
            "required_visibility": "own_visible",
            "target_battle_state": True,
        },
        "condition": {
            "actor_alive": True,
            "battle_state": True,
            "attack_phase_count_at_least": 1,
        },
        "cost": [
            {"resource": "attack_phase_count", "value": 1},
        ],
        "effects": [
            {
                "effect_type": "create_attack_event",
                "effect_data": {
                    "attack_stat": "physical_attack",
                    "attack_die": "1d10",
                    "damage_source": "actor_attribute",
                    "effect_target": "atk",
                    "damage_type": "physical",
                    "pending_list": "pending_attacks",
                },
            },
        ],
    },
    "direct_attack": {
        "action_id": "direct_attack",
        "name": "非战斗攻击",
        "description": (
            "在AP1消耗2AP，对与自己不在同一地图节点、但处于自身视野内的角色"
            "于行动提交时立即进入一次不产生战斗或偷袭的虚拟攻击阶段；"
            "其结算先于本行动层的地图移动。"
        ),
        "type": "active",
        "action_type": "attack",
        "available_phases": ["AP1"],
        "resolution_timing": "immediate",
        "target": "selectable_enemy",
        "target_rules": {
            "minimum": 1,
            "maximum": 1,
            "must_be_alive": True,
            "must_be_hostile": True,
            "required_visibility": "own_visible",
            "exclude_same_position": True,
        },
        "condition": {
            "actor_alive": True,
            "battle_state": False,
        },
        "cost": [
            {"resource": "action_point", "value": 2},
        ],
        "effects": [
            {
                "effect_type": "add_simple_round",
                "effect_data": {
                    "trigger_phase": "immediate",
                    "attack_mode": "select",
                    "attack_stat": "physical_attack",
                    "damage_type": "physical",
                    "is_ambush": False,
                    "enter_battle": False,
                    "source": "direct_attack",
                },
            },
        ],
    },
    "mend": {
        "action_id": "mend",
        "name": "修补",
        "description": "Servant消耗等量MP回复自身HP，MP不足部分由存活御主补足。",
        "type": "active",
        "action_type": "recovery",
        "available_phases": ["AP1", "attack_phase"],
        "resolution_timing": "immediate",
        "target": "self",
        "target_rules": {},
        "condition": {
            "actor_alive": True,
            "actor_type": "Servant",
            "missing_hp_at_least": 1,
        },
        "cost": [
            {
                "resource": "mp",
                "value_source": "selected_amount",
                "payment_rule": "servant_then_master",
                "atomic": True,
            },
            {
                "resource": "action_point",
                "value": 2,
                "condition": {"battle_state": False},
            },
            {
                "resource": "attack_phase_count",
                "value": 1,
                "condition": {"battle_state": True},
            },
        ],
        "effects": [
            {
                "effect_type": "recover_resource",
                "effect_data": {
                    "resource_id": "hp",
                    "value_source": "actual_mp_cost",
                    "calculation": "flat",
                },
            },
        ],
    },
    "rest": {
        "action_id": "rest",
        "name": "休息",
        "description": "Master在建筑内累计休息回合，并在休息结束或被打断时一次性回复最大HP和MP的25%乘以已完成回合数。",
        "type": "active",
        "action_type": "recovery",
        "available_phases": ["AP1"],
        "resolution_timing": "global_turn_end",
        "target": "self",
        "target_rules": {},
        "condition": {
            "actor_alive": True,
            "actor_type": "Master",
            "battle_state": False,
            "position_is_building": True,
            "cooldown_ready": "rest",
        },
        "cost": [
            {"resource": "action_point", "value": 2},
        ],
        "effects": [
            {
                "effect_type": "recover_resource",
                "effect_data": {
                    "resource_id": "hp",
                    "value": 0.25,
                    "calculation": "maximum_percentage",
                    "recovery_timing": "rest_end_or_interrupt",
                    "maximum_turns": 4,
                    "auto_continue": True,
                    "cooldown_from_start": 12,
                },
            },
            {
                "effect_type": "recover_resource",
                "effect_data": {
                    "resource_id": "mp",
                    "value": 0.25,
                    "calculation": "maximum_percentage",
                    "recovery_timing": "rest_end_or_interrupt",
                    "maximum_turns": 4,
                    "auto_continue": True,
                    "cooldown_from_start": 12,
                },
            },
        ],
    },
    "command_spell_transfer": {
        "action_id": "command_spell_transfer",
        "name": "令咒移植",
        "description": "与同节点另一名Master持续三回合移植令咒；双方整回合均被占用。",
        "type": "active",
        "action_type": "special",
        "available_phases": ["AP1"],
        "resolution_timing": "global_turn_end",
        "target": "selectable_command_spell_recipient",
        "target_rules": {
            "exclude_self": True,
            "must_be_alive": True,
            "same_position": True,
        },
        "condition": {
            "actor_alive": True,
            "actor_type": "Master",
            "battle_state": False,
            "command_spell_at_least": 1,
            "no_command_spell_transfer": True,
        },
        "cost": [
            {"resource": "action_point", "value": 2},
        ],
        "effects": [],
    },
    "chant": {
        "action_id": "chant",
        "name": "咏唱",
        "description": "开始或继续咏唱；非战斗时占用AP1和AP2，战斗时占用攻击阶段。",
        "type": "active",
        "action_type": "special",
        "available_phases": ["AP1", "attack_phase"],
        "resolution_timing": "immediate",
        "target": "none",
        "target_rules": {},
        "condition": {"actor_alive": True},
        "cost": [],
        "effects": [{
            "effect_type": "continue_casting",
            "effect_data": {"duration": 2},
        }],
    },
    "interrupt_casting": {
        "action_id": "interrupt_casting",
        "name": "中断咏唱",
        "description": "清除咏唱并原路返还实际支付的MP；不消耗AP或攻击阶段。",
        "type": "active",
        "action_type": "special",
        "available_phases": ["AP1", "attack_phase"],
        "resolution_timing": "immediate",
        "target": "none",
        "target_rules": {},
        "condition": {
            "actor_alive": True,
            "required_casting": True,
        },
        "cost": [],
        "effects": [{
            "effect_type": "interrupt_casting",
            "effect_data": {"refund_mp": True},
        }],
    },
    "release": {
        "action_id": "release",
        "name": "解放",
        "description": "解放达到咏唱层数要求的魔术或宝具效果。",
        "type": "active",
        "action_type": "special",
        "available_phases": ["AP1", "attack_phase"],
        "resolution_timing": "immediate",
        "target": "none",
        "target_rules": {},
        "condition": {
            "actor_alive": True,
            "release_available": True,
        },
        "cost": [],
        "effects": [{
            "effect_type": "release_casting",
            "effect_data": {},
        }],
    },
    "escape": {
        "action_id": "escape",
        "name": "撤退",
        "description": "消耗上回合的stay状态并退出战斗，随后以2AP进入地图行动。",
        "type": "active",
        "action_type": "escape",
        "available_phases": ["attack_phase"],
        "resolution_timing": "immediate",
        "target": "self",
        "target_rules": {},
        "condition": {
            "actor_alive": True,
            "battle_state": True,
            "required_status": ["stay"],
            "forbidden_status": ["cannot_escape"],
            "cooldown_ready": "escape",
        },
        "cost": [
            {"resource": "attack_phase_count", "value": 1},
        ],
        "effects": [
            {
                "effect_type": "consume_status",
                "effect_data": {"value": "stay"},
            },
            {
                "modifier_id": "escape_movement_penalty",
                "effect_type": "numeric_attribute_bonus",
                "polarity": "debuff",
                "purifiable": False,
                "duration_timing": "global_turn_end",
                "stacking": {
                    "stack_group": "escape_movement_penalty",
                    "stack_scope": "same_source",
                    "stacking_rule": "refresh",
                    "max_stacks": 1,
                    "duration_refresh_rule": "reset",
                },
                "effect_data": {
                    "effect_target": "move_conversion",
                    "value": -1,
                    "duration": 4,
                },
            },
            {
                "effect_type": "remove_from_battle",
                "effect_data": {},
            },
            {
                "effect_type": "grant_map_actions",
                "effect_data": {
                    "action_point": 2,
                    "forced_AP1_action_id": "move",
                },
            },
        ],
    },
    "guard": {
        "action_id": "guard",
        "name": "援护",
        "description": "在自身防御阶段前，使用格挡替所选角色依序处理待结算攻击。",
        "type": "active",
        "action_type": "defense",
        "available_phases": ["guard_phase"],
        "resolution_timing": "immediate",
        "target": "guardable_battle_participant",
        "target_rules": {
            "exclude_self": True,
            "must_be_alive": True,
            "pending_attacks_at_least": 1,
            "maximum_targets_source": "guard_target_limit",
        },
        "condition": {
            "actor_alive": True,
            "battle_state": True,
            "forbidden_status": ["brink_of_death"],
        },
        "cost": [],
        "effects": [{
            "effect_type": "redirect_pending_attacks",
            "effect_data": {
                "forced_defense_type": "block",
                "stop_on_new_brink_of_death": True,
                "preserve_queue_order": True,
            },
        }],
    },
    "dodge": {
        "action_id": "dodge",
        "name": "闪避",
        "description": "以闪避骰对抗攻击骰，成功时避免该次攻击。",
        "type": "active",
        "action_type": "defense",
        "available_phases": ["defense_phase", "simple_round_defense"],
        "resolution_timing": "defense_phase",
        "target": "incoming_attacks",
        "target_rules": {"selection": "next_pending_attack"},
        "condition": {
            "actor_alive": True,
            "pending_attacks_at_least": 1,
        },
        "cost": [],
        "effects": [
            {
                "effect_type": "resolve_defense",
                "effect_data": {
                    "defense_type": "dodge",
                    "defense_stat": "dodge",
                    "success_comparison": ">=",
                    "success_damage": 0,
                },
            },
        ],
    },
    "block": {
        "action_id": "block",
        "name": "格挡",
        "description": "使用格挡骰处理攻击池中下一次来袭攻击。",
        "type": "active",
        "action_type": "defense",
        "available_phases": ["defense_phase", "simple_round_defense"],
        "resolution_timing": "defense_phase",
        "target": "incoming_attacks",
        "target_rules": {"selection": "next_pending_attack"},
        "condition": {
            "actor_alive": True,
            "pending_attacks_at_least": 1,
        },
        "cost": [],
        "effects": [
            {
                "effect_type": "resolve_defense",
                "effect_data": {
                    "defense_type": "block",
                    "defense_stat": "block",
                    "success_comparison": ">=",
                    "damage_reduction_source": "block_resistance",
                    "failure_sets_attack_phase_count": 0,
                },
            },
        ],
    },
    "offset": {
        "action_id": "offset",
        "name": "抵消",
        "description": "消耗可用攻击阶段，以抵消骰和自身ATK削减来袭伤害。",
        "type": "active",
        "action_type": "defense",
        "available_phases": ["defense_phase", "simple_round_defense"],
        "resolution_timing": "defense_phase",
        "target": "incoming_attacks",
        "target_rules": {"selection": "next_pending_attack"},
        "condition": {
            "actor_alive": True,
            "pending_attacks_at_least": 1,
        },
        "cost": [
            {
                "resource": "attack_phase_count",
                "value": 1,
                "required": False,
            },
        ],
        "effects": [
            {
                "effect_type": "resolve_defense",
                "effect_data": {
                    "defense_type": "offset",
                    "defense_stat": "offset",
                    "success_comparison": ">=",
                    "reduction_source": "atk",
                    "failure_max_reduction_ratio": 0.5,
                    "no_attack_phase_damage_multiplier": 1,
                },
            },
        ],
    },
}


ACTION_DATA["move"]["inputs"] = [
    {
        "input_id": "path",
        "input_type": "path",
        "selection_mode": "step_by_step",
        "source": "connected_nodes",
        "minimum_steps": 1,
        "maximum_steps_source": "move_conversion",
        "allow_early_stop": True,
        "allow_backtracking": True,
    },
]
ACTION_DATA["attack"]["inputs"] = [
    {
        "input_id": "target",
        "input_type": "target",
        "source": "valid_targets",
    },
]
ACTION_DATA["direct_attack"]["inputs"] = [
    {
        "input_id": "target",
        "input_type": "target",
        "source": "valid_targets",
    },
]
ACTION_DATA["mend"]["inputs"] = [
    {
        "input_id": "amount",
        "input_type": "integer",
        "minimum": 1,
        "maximum_source": "mend_maximum",
    },
]
for _definition in ACTION_DATA.values():
    _definition.setdefault("inputs", [])

_DISPLAY_ORDER = {
    "move": 10,
    "join_travel_group": 12,
    "invite_carry": 13,
    "leave_carry": 13,
    "join_battle": 14,
    "transfer_travel_leader": 16,
    "wish": 15,
    "investigate": 20,
    "perceive": 30,
    "battle_perceive": 30,
    "hide": 40,
    "mend": 50,
    "rest": 60,
    "command_spell_transfer": 61,
    "chant": 62,
    "release": 64,
    "interrupt_casting": 66,
    "direct_attack": 70,
    "surrender": 80,
    "pass": 90,
    "attack": 10,
    "escape": 30,
    "stay": 90,
    "guard": 5,
    "dodge": 10,
    "block": 20,
    "offset": 30,
}
for _action_id, _definition in ACTION_DATA.items():
    _definition["display_order"] = _DISPLAY_ORDER[_action_id]


REQUIRED_ACTION_FIELDS = {
    "action_id",
    "name",
    "type",
    "action_type",
    "available_phases",
    "resolution_timing",
    "target",
    "target_rules",
    "condition",
    "cost",
    "effects",
    "inputs",
    "display_order",
}


def validate_action_data(action_data=None):
    data = ACTION_DATA if action_data is None else action_data
    errors = []

    for action_id, definition in data.items():
        missing = REQUIRED_ACTION_FIELDS - set(definition)
        if missing:
            errors.append(f"{action_id}缺少字段：{sorted(missing)}")
            continue
        if definition["action_id"] != action_id:
            errors.append(f"{action_id}的action_id与字典键不一致")
        if definition["type"] not in ACTION_TYPES:
            errors.append(f"{action_id}的type无效：{definition['type']}")
        if definition["action_type"] not in ACTION_TYPE_CATEGORIES:
            errors.append(
                f"{action_id}的action_type无效：{definition['action_type']}"
            )
        invalid_phases = set(definition["available_phases"]) - ACTION_PHASES
        if invalid_phases:
            errors.append(f"{action_id}包含未知阶段：{sorted(invalid_phases)}")
        if definition["resolution_timing"] not in RESOLUTION_TIMINGS:
            errors.append(
                f"{action_id}的resolution_timing无效："
                f"{definition['resolution_timing']}"
            )
        if definition["target"] not in TARGET_TYPES:
            errors.append(f"{action_id}的target无效：{definition['target']}")
        try:
            validate_condition(
                definition["condition"],
                path=f"{action_id}.condition",
            )
            validate_target_rules(
                definition["target_rules"],
                path=f"{action_id}.target_rules",
            )
        except (TypeError, ValueError) as error:
            errors.append(str(error))
        if not isinstance(definition["cost"], list):
            errors.append(f"{action_id}的cost必须是列表")
        if not isinstance(definition["effects"], list):
            errors.append(f"{action_id}的effects必须是列表")
        if not isinstance(definition["inputs"], list):
            errors.append(f"{action_id}的inputs必须是列表")

    if errors:
        raise ValueError("ACTION_DATA验证失败：\n" + "\n".join(errors))
    return True


def get_action_definition(action_id):
    try:
        return deepcopy(ACTION_DATA[action_id])
    except KeyError as error:
        raise ValueError(f"未知的action_id：{action_id}") from error


validate_action_data()
