import unittest
from types import SimpleNamespace
from unittest.mock import patch

from game.character.servants import Servant
from game.map.map import Location
from game.turn.battle import BattleManager
from game.turn.damage import AttackEvent
from game.turn.decision import ScriptedDecisionProvider


def servant(name, flexibility=3, endurance=5):
    return Servant(
        name=name,
        strength=3,
        endurance=endurance,
        flexibility=flexibility,
        magic=3,
        fortune=3,
        servant_class="Saber",
        noble="A",
    )


def setup_simple_round(*helpers):
    location = Location("Arena", high_level=True)
    actor = servant("Attacker", flexibility=1)
    target = servant("Target", flexibility=2)
    actor.position = target.position = location
    for helper in helpers:
        helper.position = location
        helper.add_ally(target)

    battle = BattleManager([actor, target])
    battle.start_battle()
    turn_manager = SimpleNamespace(
        global_action_order=list(helpers) + [target, actor],
    )
    game_manager = SimpleNamespace(
        characters=[actor, target, *helpers],
        turn_manager=turn_manager,
    )
    for character in game_manager.characters:
        character.game_manager = game_manager

    effect = battle.add_effect(
        {
            "effect_type": "add_simple_round",
            "effect_data": {
                "trigger_phase": "battle_start",
                "damage_value": 10,
            },
        },
        actor,
        target,
    )
    return battle, effect, actor, target, location


class SimpleRoundGuardTests(unittest.TestCase):
    def test_all_answers_are_collected_before_first_guard_resolves(self):
        first = servant("First")
        second = servant("Second")
        battle, effect, _, target, _ = setup_simple_round(first, second)
        provider = ScriptedDecisionProvider(["guard", "guard"])
        observed_request_counts = []
        original = battle.resolve_guard_attack

        def observe(*args, **kwargs):
            observed_request_counts.append(len(provider.requests))
            return original(*args, **kwargs)

        battle.resolve_guard_attack = observe
        with patch("game.turn.defense.random.randint", return_value=10):
            battle.resolve_simple_round(effect, provider)

        self.assertEqual(observed_request_counts, [2])
        self.assertEqual(
            [request.phase for request in provider.requests],
            ["简易战斗轮—援护", "简易战斗轮—援护"],
        )
        self.assertEqual(target.pending_attacks, [])

    def test_only_first_effective_guard_executes_when_attack_is_finished(self):
        first = servant("First")
        second = servant("Second")
        battle, effect, _, _, _ = setup_simple_round(first, second)
        provider = ScriptedDecisionProvider(["guard", "guard"])

        with patch("game.turn.defense.random.randint", return_value=10):
            battle.resolve_simple_round(effect, provider)

        self.assertEqual(len(battle.guard_history), 1)
        self.assertIs(battle.guard_history[0]["guarder"], first)
        self.assertEqual(
            battle.guard_history[0]["guard_kind"],
            "simple_round",
        )
        self.assertNotIn(first, battle.guarded_this_round)
        self.assertNotIn(second, battle.guarded_this_round)
        self.assertEqual(first.action_point, 2)

    def test_residual_attack_passes_to_next_guard_in_global_map_order(self):
        slow_prompted_first = servant("SlowPromptedFirst", flexibility=1)
        fast_in_map_order = servant("FastInMapOrder", flexibility=10)
        battle, effect, _, target, _ = setup_simple_round(
            slow_prompted_first,
            fast_in_map_order,
        )
        # 候选询问顺序与地图行动顺序故意相反。
        target.game_manager.turn_manager.global_action_order = [
            fast_in_map_order,
            slow_prompted_first,
        ]
        fast_in_map_order.hp = 1
        provider = ScriptedDecisionProvider(["guard", "guard"])

        with patch("game.turn.defense.random.randint", return_value=1):
            battle.resolve_simple_round(effect, provider)

        self.assertEqual(
            [record["guarder"] for record in battle.guard_history],
            [fast_in_map_order, slow_prompted_first],
        )
        self.assertEqual(target.pending_attacks, [])

    def test_high_level_and_ground_are_not_the_same_guard_position(self):
        helper = servant("HighLevelHelper")
        battle, _, actor, target, location = setup_simple_round(helper)
        helper.position = location.high_level_location
        state = {
            "actor": actor,
            "defenders": {target},
            "completed_defenders": set(),
            "used_guarders": set(),
        }

        self.assertEqual(
            battle.get_simple_round_guard_candidates(state, target),
            [],
        )

    def test_ineligible_allies_are_filtered(self):
        one_way = servant("OneWay")
        brink = servant("Brink")
        other_battle = servant("OtherBattle")
        battle, _, actor, target, _ = setup_simple_round(
            one_way,
            brink,
            other_battle,
        )
        target.remove_ally(one_way)
        brink.status_flags.add("brink_of_death")
        other_battle.current_battle = object()

        state = {
            "actor": actor,
            "defenders": {target},
            "completed_defenders": set(),
            "used_guarders": set(),
        }
        self.assertEqual(
            battle.get_simple_round_guard_candidates(state, target),
            [],
        )

    def test_guarder_can_spend_attribute_plus_before_blocking(self):
        helper = servant("Helper")
        battle, effect, _, _, _ = setup_simple_round(helper)
        helper.strength.plus = 1
        provider = ScriptedDecisionProvider([
            "guard",
            "use_plus",
            "strength",
            "confirm",
            "confirm",
        ])

        with patch("game.turn.defense.random.randint", return_value=10):
            battle.resolve_simple_round(effect, provider)

        self.assertEqual(helper.strength.plus, 0)
        self.assertEqual(helper._active_attribute_plus_uses["strength"], 1)
        self.assertIn(
            "简易战斗轮—援护即时操作",
            [request.phase for request in provider.requests],
        )

    def test_guarder_can_use_free_immediate_skill_before_blocking(self):
        helper = servant("Helper")
        helper.create_personal_skill({
            "skill_id": "instant_guard_boost",
            "name": "即时援护强化",
            "rank": "C",
            "components": [{
                "component_id": "boost",
                "type": "active",
                "available_phases": ["simple_round_guard"],
                "resolution_timing": "immediate",
                "target": "self",
                "effects": [{
                    "modifier_id": "instant_guard_dice",
                    "effect_type": "numeric_attribute_bonus",
                    "polarity": "buff",
                    "stacking": {
                        "stack_group": "instant_guard_dice",
                        "stack_scope": "same_source",
                        "stacking_rule": "refresh",
                    },
                    "duration": 1,
                    "effect_data": {
                        "effect_target": "dice_bonus",
                        "value": 2,
                    },
                }],
            }],
        })
        battle, effect, _, _, _ = setup_simple_round(helper)
        provider = ScriptedDecisionProvider([
            "guard",
            "即时援护强化",
            "confirm",
        ])

        with patch("game.turn.defense.random.randint", return_value=10):
            battle.resolve_simple_round(effect, provider)

        self.assertEqual(helper.dice_bonus, 2)
        self.assertEqual(helper.action_point, 2)
        self.assertEqual(helper.attack_phase_count, 1)


class MultiDefenderSimpleRoundTests(unittest.TestCase):
    @staticmethod
    def attack(actor, target, value=10):
        event = AttackEvent(
            source=actor,
            target=target,
            value=value,
            damage_type="physical",
            attack_roll=1,
            skill=None,
            attack_die=1,
        )
        target.pending_attacks.append(event)
        return event

    def test_completed_defender_can_guard_later_defender(self):
        location = Location("Arena")
        actor = servant("Attacker", flexibility=1)
        first = servant("First", flexibility=10)
        second = servant("Second", flexibility=5)
        outsider = servant("Outsider", flexibility=3)
        for character in (actor, first, second, outsider):
            character.position = location
        first.add_ally(second)
        outsider.add_ally(first)
        outsider.add_ally(second)
        battle = BattleManager([actor, first, second])
        battle.start_battle()
        game_manager = SimpleNamespace(
            characters=[actor, first, second, outsider],
            turn_manager=SimpleNamespace(
                global_action_order=[outsider, first, second, actor],
            ),
        )
        for character in game_manager.characters:
            character.game_manager = game_manager

        provider = ScriptedDecisionProvider([
            "skip",   # 第一名防守前：只有未受攻击的Outsider有资格
            "dodge",  # First完成自己的防御阶段
            "guard",  # 第二名防守前：First现在可以援护Second
            "skip",   # Outsider仍会再次被询问
        ])
        attacks = [
            self.attack(actor, first),
            self.attack(actor, second),
        ]

        with patch("game.turn.defense.random.randint", return_value=10):
            result = battle.resolve_simple_round_attack_events(
                attacks,
                provider,
            )

        guard_requests = [
            request
            for request in provider.requests
            if request.phase == "简易战斗轮—援护"
        ]
        self.assertEqual(
            [request.character for request in guard_requests],
            [outsider, first, outsider],
        )
        self.assertEqual(result["defense_order"], [first, second])
        self.assertEqual(result["completed_defenders"], {first, second})
        self.assertEqual(result["used_guarders"], {first})
        self.assertEqual(second.pending_attacks, [])

    def test_fixed_multi_target_effect_shares_one_attack_roll(self):
        location = Location("Arena")
        actor = servant("Attacker", flexibility=1)
        first = servant("First", flexibility=10)
        second = servant("Second", flexibility=5)
        for character in (actor, first, second):
            character.position = location
        battle = BattleManager([actor, first, second])
        battle.start_battle()
        effect = battle.add_effect(
            {
                "effect_type": "add_simple_round",
                "effect_data": {
                    "trigger_phase": "battle_start",
                    "attack_mode": "fixed",
                    "damage_value": 10,
                },
            },
            actor,
            [first, second],
        )

        with patch("game.action.action.random.randint", return_value=7), patch(
            "game.turn.defense.random.randint",
            return_value=10,
        ):
            result = battle.resolve_simple_round(
                effect,
                ScriptedDecisionProvider(["dodge", "dodge"]),
            )

        self.assertEqual(len(effect.attack_events), 2)
        self.assertIs(effect.attack_event, effect.attack_events[0])
        self.assertEqual(
            effect.attack_events[0].attack_die,
            effect.attack_events[1].attack_die,
        )
        self.assertEqual(result["defense_order"], [first, second])

    def test_dead_defender_is_skipped_but_attacker_death_does_not_cancel(self):
        location = Location("Arena")
        actor = servant("Attacker", flexibility=1)
        dead_first = servant("DeadFirst", flexibility=10)
        living_second = servant("LivingSecond", flexibility=5)
        for character in (actor, dead_first, living_second):
            character.position = location
        battle = BattleManager([actor, dead_first, living_second])
        first_attack = self.attack(actor, dead_first)
        second_attack = self.attack(actor, living_second)
        dead_first.hp = 0
        actor.hp = 0

        result = battle.resolve_simple_round_attack_events(
            [first_attack, second_attack],
            ScriptedDecisionProvider(["dodge"]),
        )

        self.assertTrue(result["results"][0]["skipped"])
        self.assertFalse(result["results"][1]["skipped"])
        self.assertNotIn(dead_first, result["completed_defenders"])
        self.assertIn(living_second, result["completed_defenders"])

    def test_select_mode_uses_virtual_attack_phase_and_preserves_normal_phase(self):
        location = Location("Arena")
        actor = servant("Attacker", flexibility=10)
        target = servant("Target", flexibility=5)
        actor.position = target.position = location
        actor.own_visible = [target]
        target.dodge = 100
        battle = BattleManager([actor, target])
        battle.start_battle()
        actor.own_visible = [target]
        effect = battle.add_effect(
            {
                "effect_type": "add_simple_round",
                "effect_data": {
                    "trigger_phase": "battle_start",
                    "attack_mode": "select",
                },
            },
            actor,
            target,
        )
        original_attack_phases = actor.attack_phase_count

        result = battle.resolve_simple_round(
            effect,
            ScriptedDecisionProvider(["attack", "dodge"]),
        )

        self.assertEqual(actor.attack_phase_count, original_attack_phases)
        self.assertEqual(len(result["defense_results"]), 1)
        self.assertEqual(len(effect.attack_events), 1)
        self.assertTrue(effect.resolved)


if __name__ == "__main__":
    unittest.main()
