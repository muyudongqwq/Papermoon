"""职介技能的Rank数据。

``type``描述组件类型，``effect_type``描述组件产生的效果。每个非空
Rank都使用与固有技能相同的组件结构，并提供稳定的``component_id``。
"""


def _passive_component(component_id, effects):
    return {
        "component_id": component_id,
        "type": "passive",
        "target": "self",
        "effects": effects,
    }


def _attribute_bonus(attribute, value=1):
    return {
        "effect_type": "attribute_bonus",
        "effect_data": {
            "effect_target": attribute,
            "value": value,
        },
    }


def _fixed_status(status, *, polarity="neutral", purifiable=False):
    return {
        "effect_type": "add_status",
        "polarity": polarity,
        "purifiable": purifiable,
        "effect_data": {"value": status},
    }


def _magic_resistance(value):
    return _passive_component(
        "passive_magic_resistance",
        [{
            "effect_type": "magic_resistance",
            "effect_data": {"value": value},
        }],
    )


def _independent_action(duration):
    free_upkeep = {
        "modifier_id": "independent_action_free_upkeep",
        "effect_type": "cost_modifier",
        "polarity": "buff",
        "purifiable": False,
        "stacking": {
            "stack_group": "independent_action_free_upkeep",
            "stack_scope": "same_source",
            "stacking_rule": "refresh",
            "duration_refresh_rule": "reset",
        },
        "effect_data": {
            "resource": "mp",
            "cost_id": "masterless_upkeep",
            "calculation": "override",
            "value": 0,
        },
    }
    if duration is not None:
        free_upkeep["duration"] = duration
        free_upkeep["duration_timing"] = "masterless_upkeep_end"

    return {
        "component_id": "on_master_lost",
        "type": "trigger",
        "trigger_event": "master_lost",
        "target": "self",
        "condition": {"condition_id": "master_is_none"},
        "effects": [
            {
                "modifier_id": "independent_action_discount",
                "effect_type": "cost_modifier",
                "polarity": "buff",
                "purifiable": False,
                "stacking": {
                    "stack_group": "independent_action_discount",
                    "stack_scope": "same_source",
                    "stacking_rule": "refresh",
                },
                "effect_data": {
                    "resource": "mp",
                    "cost_id": "masterless_upkeep",
                    "calculation": "multiplier",
                    "value": 0.5,
                },
            },
            free_upkeep,
        ],
    }


def _mad_enhancement(attributes, statuses):
    effects = [_attribute_bonus(attribute) for attribute in attributes]
    effects.extend(
        _fixed_status(status, polarity="debuff", purifiable=False)
        for status in statuses
    )
    return _passive_component("passive_mad_enhancement", effects)


def _presence_concealment(
    rank,
    hide_bonus,
    *,
    investigation_immunity=False,
    active_hide_perception_immunity=False,
):
    rank_priority = {"C": 1, "B": 2, "A": 3, "EX": 4}[rank]
    return _passive_component(
        "passive_presence_concealment",
        [{
            "modifier_id": "presence_concealment",
            "effect_type": "presence_concealment",
            "polarity": "buff",
            "purifiable": False,
            "stacking": {
                "stack_group": "presence_concealment",
                "stack_scope": "all_sources",
                "stacking_rule": "strongest",
                "strength_comparison": "higher",
                "strength_priority": rank_priority,
            },
            "effect_data": {
                "rank": rank,
                "value": hide_bonus,
                "investigation_immunity": investigation_immunity,
                "active_hide_perception_immunity": (
                    active_hide_perception_immunity
                ),
            },
        }],
    )


def _carry_capacity(value=1):
    return {
        "modifier_id": "riding_carry_capacity",
        "effect_type": "carry_capacity",
        "polarity": "buff",
        "purifiable": False,
        "stacking": {
            "stack_group": "carry_capacity",
            "stack_scope": "all_sources",
            "stacking_rule": "strongest",
            "strength_comparison": "higher",
        },
        "effect_data": {"value": value},
    }


CLASS_SKILL_DATA = {
    "对魔力": {
        "C": [_magic_resistance(0.1)],
        "B": [_magic_resistance(0.2)],
        "A": [_magic_resistance(0.3)],
    },

    "骑乘": {
        "C": [_passive_component(
            "passive_riding",
            [{
                "effect_type": "movement_point_bonus",
                "effect_data": {"value": 1},
            }],
        )],
        "B": [_passive_component(
            "passive_riding",
            [_carry_capacity(1)],
        )],
        "A": [_passive_component(
            "passive_riding",
            [_carry_capacity(1)],
        )],
    },

    "单独行动": {
        "C": [_independent_action(12)],
        "B": [_independent_action(36)],
        "A": [_independent_action(None)],
    },

    "气息遮断": {
        "C": [_presence_concealment("C", 2)],
        "B": [_presence_concealment(
            "B",
            4,
            investigation_immunity=True,
        )],
        "A": [_presence_concealment(
            "A",
            6,
            investigation_immunity=True,
            active_hide_perception_immunity=True,
        )],
        "EX": [_presence_concealment(
            "EX",
            12,
            investigation_immunity=True,
            active_hide_perception_immunity=True,
        )],
    },

    "狂化": {
        "C": [_mad_enhancement(
            ("strength", "flexibility", "endurance"),
            ("cannot_investigate",),
        )],
        "B": [_mad_enhancement(
            ("strength", "flexibility", "endurance", "magic", "fortune"),
            ("cannot_investigate", "cannot_escape"),
        )],
        "A": [_mad_enhancement(
            ("strength", "flexibility", "endurance", "magic", "fortune"),
            ("cannot_investigate", "cannot_escape", "random_defense"),
        )],
    },

    "测试程序": {
        "GM": [_passive_component(
            "passive_debug_mode",
            [_fixed_status("debug_mode_on")],
        )],
    },
}
