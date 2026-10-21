import unittest

from game.character.masters import Master
from game.character.servants import Servant
from game.game_manager import GameManager
from game.map.map import Location, Road
from game.map.movement import MovementAction
from game.turn.Turn import TurnManager
from game.action.action import Action
from game.turn.battle_request import BattleRequest
from game.turn.decision import ScriptedDecisionProvider


def create_master(name="Master"):
    return Master(name, 3, 3, 3, 3, 3, "C", 3)


def create_servant(name="Servant", flexibility=3, magic=3):
    return Servant(
        name,
        3,
        3,
        flexibility,
        magic,
        3,
        "Saber",
        "A",
    )


class MasterServantBindingTests(unittest.TestCase):
    def test_master_accepts_two_servants_and_rejects_third(self):
        master = create_master()
        first = create_servant("First")
        second = create_servant("Second")
        third = create_servant("Third")

        self.assertTrue(master.add_servant(first))
        self.assertTrue(master.add_servant(second))
        self.assertFalse(master.add_servant(third))
        self.assertEqual(master.servants, [first, second])
        self.assertIs(first.master, master)
        self.assertIs(second.master, master)
        self.assertIsNone(third.master)
        self.assertTrue(master.is_ally(first))
        self.assertFalse(first.is_ally(second))

    def test_death_detaches_relationship_but_keeps_alliance(self):
        master = create_master()
        servant = create_servant()
        master.add_servant(servant)

        master.die()

        self.assertIsNone(servant.master)
        self.assertEqual(master.servants, [])
        self.assertTrue(master.is_ally(servant))


class SharedVisibilityTests(unittest.TestCase):
    def test_perception_is_shared_but_removed_by_the_original_sources_range(self):
        nodes = [Location(str(index)) for index in range(8)]
        for left, right in zip(nodes, nodes[1:]):
            left.add_connection(right)
            right.add_connection(left)

        master = create_master()
        servant = create_servant("Observer")
        target = create_servant("Target")
        master.add_servant(servant)
        servant.position = nodes[0]
        master.position = nodes[7]
        target.position = nodes[4]
        characters = [master, servant, target]
        servant.own_perceived.append(target)

        servant.update_visibility(characters)
        master.update_visibility(characters)

        self.assertIn(target, servant.own_perceived)
        self.assertIn(target, master.shared_perceived)
        self.assertIn(target, servant.perceived)
        self.assertIn(target, master.perceived)
        self.assertIn(target, servant.any_visible)

        # Target离开感知来源Servant的5格；即使仍在Master的5格内，
        # Master也会失去这份共享感知，因为Master没有独立感知记录。
        target.position = nodes[6]
        servant.update_visibility(characters)
        master.update_visibility(characters)

        self.assertNotIn(target, servant.own_perceived)
        self.assertNotIn(target, master.shared_perceived)
        self.assertNotIn(target, servant.perceived)
        self.assertNotIn(target, master.perceived)

    def test_independent_perception_source_survives_other_source_expiration(self):
        nodes = [Location(str(index)) for index in range(8)]
        for left, right in zip(nodes, nodes[1:]):
            left.add_connection(right)
            right.add_connection(left)

        master = create_master()
        servant = create_servant("Observer")
        target = create_servant("Target")
        master.add_servant(servant)
        servant.position = nodes[0]
        master.position = nodes[7]
        target.position = nodes[4]
        servant.own_perceived.append(target)
        master.own_perceived.append(target)

        target.position = nodes[6]
        master.update_visibility([master, servant, target])
        servant.update_visibility([master, servant, target])

        self.assertNotIn(target, servant.own_perceived)
        self.assertIn(target, master.own_perceived)
        self.assertIn(target, servant.shared_perceived)
        self.assertIn(target, servant.perceived)

    def test_master_and_two_servants_share_network_but_keep_own_visibility(self):
        location_a = Location("A")
        location_b = Location("B")
        location_c = Location("C")
        master = create_master()
        first = create_servant("First")
        second = create_servant("Second")
        enemy = create_servant("Enemy")
        master.add_servant(first)
        master.add_servant(second)
        first.position = location_a
        enemy.position = location_a
        master.position = location_b
        second.position = location_c
        characters = [master, first, second, enemy]

        master.update_visibility(characters)

        self.assertIn(enemy, first.own_visible)
        self.assertIn(enemy, master.shared_visible)
        self.assertNotIn(enemy, second.shared_visible)
        self.assertIn(enemy, master.any_visible)
        self.assertNotIn(enemy, second.any_visible)
        self.assertNotIn(enemy, master.own_visible)
        self.assertNotIn(enemy, second.own_visible)

        attack = Action(
            second,
            "attack",
            enemy,
            ignore_attack_phase_count=True,
        )
        self.assertFalse(attack.attack())

    def test_shared_vision_prevents_ambush_but_cannot_grant_ambush(self):
        actor = create_servant("Actor")
        target = create_servant("Target")
        encounter = type("EncounterStub", (), {"awareness": {}})()

        actor.own_visible = [target]
        target.any_visible = [actor]
        request = BattleRequest(actor, target, encounter, submitted_layer=1)
        self.assertFalse(request.lock(1))

    def test_shared_perception_prevents_ambush(self):
        location = Location("Building", is_building=True)
        actor = create_servant("Actor")
        target = create_servant("Target")
        scout = create_servant("Scout")
        master = create_master("Target Master")
        master.add_servant(target)
        master.add_servant(scout)
        for character in (actor, target, scout, master):
            character.position = location
        actor.status_flags.add("hidden")
        master.own_perceived.append(actor)
        target.update_visibility([actor, target, scout, master])

        self.assertIn(actor, target.shared_perceived)
        self.assertIn(actor, target.perceived)
        self.assertIn(actor, target.any_visible)
        actor.update_visibility([actor, target, scout, master])
        self.assertIn(target, actor.own_visible)

        encounter = type("EncounterStub", (), {"awareness": {}})()
        request = BattleRequest(actor, target, encounter, submitted_layer=1)
        self.assertFalse(request.lock(1))

        actor.own_visible = []
        actor.shared_visible = [target]
        actor.any_visible = [target]
        target.any_visible = []
        request = BattleRequest(actor, target, encounter, submitted_layer=1)
        self.assertFalse(request.lock(1))


class MendTests(unittest.TestCase):
    def test_mend_uses_servant_mp_then_master_mp_and_caps_at_missing_hp(self):
        master = create_master()
        servant = create_servant()
        master.add_servant(servant)
        servant.hp -= 40
        servant.mp = 10
        master.mp = 100
        action = Action(servant, "mend", amount=100)

        self.assertTrue(action.mend())
        self.assertEqual(action.actual_amount, 40)
        self.assertEqual(servant.hp, servant.hpmax)
        self.assertEqual(servant.mp, 0)
        self.assertEqual(master.mp, 70)
        self.assertEqual(servant.action_point, 0)

    def test_mend_is_atomic_when_combined_mp_is_insufficient(self):
        master = create_master()
        servant = create_servant()
        master.add_servant(servant)
        servant.hp -= 50
        servant.mp = 10
        master.mp = 20
        action = Action(servant, "mend", amount=50)

        self.assertFalse(action.mend())
        self.assertEqual(servant.mp, 10)
        self.assertEqual(master.mp, 20)
        self.assertEqual(servant.hp, servant.hpmax - 50)

    def test_battle_mend_consumes_attack_phase_instead_of_ap(self):
        servant = create_servant()
        servant.in_battle = True
        servant.hp -= 20
        servant.mp = 30
        servant.action_point = 2

        self.assertTrue(Action(servant, "mend", amount=20).mend())
        self.assertEqual(servant.attack_phase_count, 0)
        self.assertEqual(servant.action_point, 2)
        self.assertEqual(servant.hp, servant.hpmax)


class DirectAttackTests(unittest.TestCase):
    def test_direct_attack_resolves_on_submission_before_map_movement(self):
        attack_location = Location("Attack Origin")
        target_location = Location("Target Origin")
        road = Road(attack_location, target_location)
        attacker = create_servant("Attacker", flexibility=3)
        target = create_servant("Target", flexibility=5)
        attacker.position = attack_location
        target.position = target_location
        attacker.visibility = 2
        target.dodge = 100
        game = GameManager([attacker, target], attack_location)
        game.start_game()
        manager = game.turn_manager
        manager.start_turn()
        manager.non_battle_order = [target, attacker]
        attacker.own_visible = [target]
        movement = MovementAction(
            target,
            [target_location, road, attack_location],
        )
        manager.add_action(movement, ap_layer=1)
        provider = ScriptedDecisionProvider(["attack", "dodge"])
        direct_attack = Action(attacker, "direct_attack", target)

        manager.add_action(
            direct_attack,
            ap_layer=1,
            decision_provider=provider,
        )

        self.assertTrue(direct_attack.resolved_on_submission)
        self.assertEqual(attacker.action_point, 0)
        self.assertIs(target.position, target_location)
        records = game.information_manager.get_temporary_information(
            target,
            information_type="direct_attack_source",
        )
        self.assertEqual(len(records), 1)
        self.assertIs(records[0].source, attacker)
        self.assertIs(records[0].position, attack_location)
        self.assertEqual(provider.notifications, [{
            "recipient": target,
            "message": "你受到来自Attack Origin的超距打击。",
        }])

        # The cached action result is consumed by the AP layer without
        # opening a second simple round. Movement only starts afterwards.
        result = manager.execute_action_layer(1, decision_provider=provider)
        self.assertIsInstance(result, dict)
        self.assertEqual(len(provider.notifications), 1)
        self.assertIs(target.position, attack_location)

    def test_queued_direct_attack_has_pre_movement_priority_for_api_callers(self):
        attack_location = Location("A")
        target_location = Location("B")
        road = Road(attack_location, target_location)
        attacker = create_servant("Attacker", flexibility=3)
        target = create_servant("Target", flexibility=5)
        attacker.position = attack_location
        target.position = target_location
        attacker.visibility = 2
        target.dodge = 100
        manager = TurnManager()
        manager.characters = [attacker, target]
        manager.start_turn()
        manager.non_battle_order = [target, attacker]
        attacker.own_visible = [target]
        manager.add_action(
            MovementAction(
                target,
                [target_location, road, attack_location],
            ),
            ap_layer=1,
        )
        manager.add_action(
            Action(attacker, "direct_attack", target),
            ap_layer=1,
        )
        provider = ScriptedDecisionProvider(["attack", "dodge"])

        result = manager.execute_action_layer(1, decision_provider=provider)

        self.assertIsInstance(result, dict)
        self.assertEqual(attacker.action_point, 0)
        self.assertIs(target.position, attack_location)

    def test_direct_attack_source_information_expires_next_turn(self):
        location = Location("A")
        target_location = Location("B")
        attacker = create_servant("Attacker")
        target = create_servant("Target")
        attacker.position = location
        target.position = target_location
        game = GameManager([attacker, target], location)
        game.start_game()
        information = game.information_manager.record_direct_attack_source(
            attacker,
            target,
            location,
        )

        self.assertIn(information, game.information_manager.temporary_information)
        game.information_manager.begin_turn(
            game.turn_manager.turn + 1,
        )
        self.assertEqual(game.information_manager.temporary_information, [])

    def test_direct_attack_costs_two_ap_without_starting_battle_or_stopping_target(self):
        location = Location("A")
        target_location = Location("B")
        Road(location, target_location)
        attacker = create_servant("Attacker", flexibility=5)
        target = create_servant("Target", flexibility=3)
        create_master("Attacker Master").add_servant(attacker)
        create_master("Target Master").add_servant(target)
        attacker.position = location
        target.position = target_location
        attacker.visibility = 2
        target.dodge = 100
        manager = TurnManager()
        manager.characters = [attacker, target]
        manager.start_turn()
        direct_attack = Action(attacker, "direct_attack", target)
        target_action = Action(target, "perceive")
        manager.add_action(direct_attack, ap_layer=1)
        manager.add_action(target_action, ap_layer=1)

        result = manager.execute_action_layer(
            1,
            decision_provider=ScriptedDecisionProvider([
                "attack",
                "dodge",
            ]),
        )

        self.assertIsInstance(result, list)
        self.assertEqual(attacker.action_point, 0)
        self.assertEqual(target.action_point, 1)
        self.assertFalse(attacker.in_battle)
        self.assertFalse(target.in_battle)
        self.assertEqual(manager.battles, [])
        self.assertIsNotNone(target_action.checkpoint_result)

    def test_direct_attack_can_end_virtual_phase_without_ap_refund(self):
        location = Location("A")
        target_location = Location("B")
        attacker = create_servant("Attacker")
        target = create_servant("Target")
        attacker.position = location
        target.position = target_location
        attacker.own_visible = [target]

        result = Action(attacker, "direct_attack", target).direct_attack(
            ScriptedDecisionProvider(["stay"])
        )

        self.assertTrue(result["ended_without_refund"])
        self.assertEqual(attacker.action_point, 0)
        self.assertFalse(attacker.has_status("stay"))
        self.assertEqual(target.pending_attacks, [])

    def test_direct_attack_virtual_phase_can_use_battle_attack_skill(self):
        location = Location("A")
        target_location = Location("B")
        attacker = create_servant("Attacker")
        target = create_servant("Target")
        same_node = create_servant("SameNode")
        attacker.position = location
        same_node.position = location
        target.position = target_location
        attacker.own_visible = [target, same_node]
        target.dodge = 100
        attacker.create_personal_skill({
            "skill_id": "magic_bolt",
            "name": "魔弹",
            "rank": "C",
            "components": [{
                "component_id": "attack",
                "type": "active",
                "available_phases": ["attack_phase"],
                "resolution_timing": "defense_phase",
                "target": "selectable_enemy",
                "target_rules": {
                    "must_be_alive": True,
                    "must_be_hostile": True,
                    "required_visibility": "own_visible",
                },
                "condition": {
                    "battle_state": True,
                },
                "cost": [{
                    "resource": "attack_phase_count",
                    "value": 1,
                }],
                "effects": [{
                    "effect_type": "create_attack_event",
                    "effect_data": {
                        "attack_stat": "magic_attack",
                        "damage_type": "magic",
                        "damage_value": 20,
                    },
                }],
            }],
        })
        provider = ScriptedDecisionProvider([
            "魔弹",
            "Target",
            "dodge",
        ])

        result = Action(
            attacker,
            "direct_attack",
            target,
            characters=[attacker, target, same_node],
        ).direct_attack(provider)

        self.assertEqual(attacker.action_point, 0)
        self.assertEqual(attacker.attack_phase_count, 0)
        self.assertEqual(len(result["defense_results"]), 1)
        self.assertEqual(target.pending_attacks, [])
        self.assertIn(
            "魔弹",
            [
                option.label
                for request in provider.requests
                for option in getattr(request, "options", ())
            ],
        )
        self.assertNotIn(
            "SameNode",
            [
                option.label
                for request in provider.requests
                for option in getattr(request, "options", ())
            ],
        )

    def test_direct_attack_rejects_same_node_without_spending_ap(self):
        location = Location("A")
        attacker = create_servant("Attacker")
        target = create_servant("Target")
        attacker.position = target.position = location
        attacker.own_visible = [target]

        result = Action(attacker, "direct_attack", target).direct_attack(
            ScriptedDecisionProvider([])
        )

        self.assertFalse(result)
        self.assertEqual(attacker.action_point, 2)


class RestTests(unittest.TestCase):
    def test_rest_recovers_at_turn_end_and_automatically_continues_four_turns(self):
        building = Location("Workshop", is_building=True)
        master = create_master()
        master.position = building
        master.hp = 10
        master.mp = 0
        manager = TurnManager()
        manager.characters = [master]

        manager.start_turn()
        manager.add_action(Action(master, "rest"), ap_layer=1)
        manager.end_turn()
        self.assertEqual(master.hp, 10)
        self.assertEqual(master.mp, 0)
        self.assertEqual(master.rest_turns, 1)

        for _ in range(3):
            manager.start_turn()
            manager.end_turn()

        self.assertEqual(master.hp, master.hpmax)
        self.assertEqual(master.mp, master.mpmax)
        self.assertFalse(master.resting)
        self.assertEqual(master.last_rest_started_turn, 1)

    def test_other_instruction_cancels_automatic_rest(self):
        building = Location("Workshop", is_building=True)
        master = create_master()
        master.position = building
        master.hp = 10
        manager = TurnManager()
        manager.characters = [master]
        manager.start_turn()
        manager.add_action(Action(master, "rest"), ap_layer=1)
        manager.end_turn()
        self.assertEqual(master.hp, 10)

        manager.start_turn()
        manager.add_action(Action(master, "perceive"), ap_layer=1)
        recovered_hp = min(master.hpmax, 10 + int(master.hpmax * 0.25))
        self.assertEqual(master.hp, recovered_hp)
        manager.end_turn()

        self.assertFalse(master.resting)
        self.assertEqual(master.hp, recovered_hp)

    def test_interrupted_rest_calculates_all_completed_turns_at_once(self):
        building = Location("Workshop", is_building=True)
        master = create_master()
        master.position = building
        master.hp = 1
        master.mp = 0
        manager = TurnManager()
        manager.characters = [master]

        manager.start_turn()
        manager.add_action(Action(master, "rest"), ap_layer=1)
        manager.end_turn()
        for _ in range(2):
            manager.start_turn()
            manager.end_turn()

        self.assertEqual(master.rest_turns, 3)
        self.assertEqual((master.hp, master.mp), (1, 0))
        manager.start_turn()
        manager.add_action(Action(master, "perceive"), ap_layer=1)

        self.assertFalse(master.resting)
        self.assertEqual(master.hp, 68)
        self.assertEqual(master.mp, 67)

    def test_rest_cooldown_is_twelve_turns_from_start(self):
        building = Location("Workshop", is_building=True)
        master = create_master()
        master.position = building
        master.last_rest_started_turn = 1

        self.assertFalse(master.can_start_rest(12))
        self.assertTrue(master.can_start_rest(13))


class MasterlessServantTests(unittest.TestCase):
    def create_independent_servant(self, rank, magic=10):
        servant = create_servant(magic=magic)
        master = create_master()
        servant.add_class_skill("单独行动", rank)
        master.add_servant(servant)
        master.remove_servant(servant)
        return servant, master

    def test_independent_action_c_waives_twelve_upkeeps_then_costs_forty_five(self):
        servant, _master = self.create_independent_servant("C")
        starting_mp = servant.mp

        for turn_number in range(1, 13):
            servant.end_global_turn(turn_number)
        self.assertEqual(servant.mp, starting_mp)
        self.assertEqual(
            servant.find_modifiers(
                modifier_id="independent_action_free_upkeep"
            ),
            [],
        )

        servant.end_global_turn(13)
        self.assertEqual(servant.mp, starting_mp - 45)

    def test_independent_action_b_and_a_use_data_defined_durations(self):
        servant_b, _master_b = self.create_independent_servant("B")
        free_b = servant_b.find_modifiers(
            modifier_id="independent_action_free_upkeep"
        )[0]
        self.assertEqual(free_b.duration, 36)

        servant_a, _master_a = self.create_independent_servant("A")
        starting_mp = servant_a.mp
        free_a = servant_a.find_modifiers(
            modifier_id="independent_action_free_upkeep"
        )[0]
        self.assertIsNone(free_a.duration)
        for turn_number in range(1, 50):
            servant_a.end_global_turn(turn_number)
        self.assertEqual(servant_a.mp, starting_mp)

    def test_losing_master_again_resets_independent_action_duration(self):
        servant, first_master = self.create_independent_servant("C")
        for turn_number in range(1, 6):
            servant.end_global_turn(turn_number)
        free = servant.find_modifiers(
            modifier_id="independent_action_free_upkeep"
        )[0]
        self.assertEqual(free.duration, 7)

        second_master = create_master("Second Master")
        second_master.add_servant(servant)
        second_master.remove_servant(servant)

        refreshed = servant.find_modifiers(
            modifier_id="independent_action_free_upkeep"
        )[0]
        # Reapplying a buff from the same skill component replaces the old
        # runtime instance and resets its duration.
        self.assertIsNot(refreshed, free)
        self.assertEqual(refreshed.duration, 12)
        self.assertNotIn(servant, first_master.servants)

    def test_masterless_cost_modifier_does_not_change_other_mp_costs(self):
        servant, _master = self.create_independent_servant("C")

        self.assertEqual(
            servant.modifier_manager.calculate_cost(
                90,
                resource="mp",
                cost_id="masterless_upkeep",
            ),
            0,
        )
        self.assertEqual(
            servant.modifier_manager.calculate_cost(
                90,
                resource="mp",
                cost_id="skill_cost",
            ),
            90,
        )

    def test_masterless_servant_loses_ninety_mp_and_dies_at_zero(self):
        servant = create_servant(magic=4)
        servant.position = Location("A")
        manager = TurnManager()
        manager.characters = [servant]

        manager.start_turn()
        manager.end_turn()
        self.assertEqual(servant.mp, 30)
        self.assertTrue(servant.is_alive())

        manager.start_turn()
        manager.end_turn()
        self.assertEqual(servant.mp, 0)
        self.assertFalse(servant.is_alive())
        self.assertTrue(servant.has_status("dead"))
        self.assertEqual(servant.brink_of_death_counter, 1)


if __name__ == "__main__":
    unittest.main()
