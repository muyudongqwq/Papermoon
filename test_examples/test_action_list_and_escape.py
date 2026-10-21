import unittest

from game.character.masters import Master
from game.character.servants import Servant
from game.map.map import Location
from game.map.movement import Encounter, MovementResolver
from game.turn.Turn import TurnManager
from game.action.action import Action
from game.action.action_list import ActionContext, ActionListBuilder, PathPlanner
from game.turn.battle import BattleManager
from game.turn.decision import ScriptedDecisionProvider


def connect(left, right):
    left.add_connection(right)
    right.add_connection(left)


def create_servant(name="Servant", flexibility=3):
    servant = Servant(
        name=name,
        strength=3,
        endurance=3,
        flexibility=flexibility,
        magic=3,
        fortune=3,
        servant_class="Saber",
        noble="A",
    )
    master = Master(
        name=f"{name} Master",
        strength=3,
        endurance=3,
        flexibility=3,
        magic=3,
        fortune=3,
        talent="C",
        command_spell=3,
    )
    master.add_servant(servant)
    return servant


class PathPlannerTests(unittest.TestCase):
    def test_move_requires_one_step_and_allows_backtracking(self):
        a = Location("A")
        b = Location("B")
        connect(a, b)
        actor = create_servant()
        actor.position = a
        planner = PathPlanner(actor, maximum_steps=2)

        with self.assertRaises(ValueError):
            planner.finish()
        planner.add_step(b)
        planner.add_step(a)

        self.assertEqual(planner.finish(), [a, b, a])
        self.assertEqual(planner.remaining_steps, 0)


class ActionListTests(unittest.TestCase):
    def test_forced_escape_ap1_only_offers_move(self):
        a = Location("A")
        b = Location("B")
        connect(a, b)
        actor = create_servant()
        actor.position = a
        actor.current_global_turn = 4
        actor.forced_move_turn = 4

        entries = ActionListBuilder().get_available_actions(
            ActionContext(actor, "AP1", turn_number=4, characters=[actor])
        )

        self.assertEqual([entry.action_id for entry in entries], ["move"])

    def test_attack_uses_own_visibility_but_direct_attack_can_target_battler(self):
        location = Location("Arena")
        remote = Location("Remote")
        actor = create_servant("Actor")
        own_target = create_servant("Own")
        shared_target = create_servant("Shared")
        actor.position = own_target.position = shared_target.position = location
        actor.own_visible = [own_target]
        actor.shared_visible = [shared_target]
        actor.any_visible = [own_target, shared_target]
        battle = BattleManager([actor, own_target, shared_target])
        battle.start_battle()
        actor.own_visible = [own_target]
        actor.shared_visible = [shared_target]

        attack = next(
            entry
            for entry in ActionListBuilder().get_action_entries(
                ActionContext(actor, "attack_phase", battle=battle)
            )
            if entry.action_id == "attack"
        )
        self.assertEqual(attack.valid_targets, [own_target])

        battle.remove_participant(actor)
        actor.position = remote
        actor.own_visible = [own_target]
        direct_attack = next(
            entry
            for entry in ActionListBuilder().get_action_entries(
                ActionContext(
                    actor,
                    "AP1",
                    turn_number=1,
                    characters=[actor, own_target],
                )
            )
            if entry.action_id == "direct_attack"
        )
        self.assertTrue(own_target.in_battle)
        self.assertTrue(direct_attack.available)
        self.assertEqual(direct_attack.valid_targets, [own_target])

    def test_attack_does_not_treat_perceived_or_shared_as_own_visibility(self):
        location = Location("Arena")
        actor = create_servant("Actor")
        own_target = create_servant("Own")
        perceived_target = create_servant("Perceived")
        shared_target = create_servant("Shared")
        for character in (actor, own_target, perceived_target, shared_target):
            character.position = location
        actor.own_visible = [own_target]
        actor.own_perceived = [perceived_target]
        actor.shared_visible = [shared_target]
        actor.shared_perceived = []
        actor.perceived = [perceived_target]
        actor.any_visible = [own_target, perceived_target, shared_target]
        battle = BattleManager([
            actor, own_target, perceived_target, shared_target,
        ])
        battle.start_battle()
        actor.own_visible = [own_target]
        actor.own_perceived = [perceived_target]
        actor.shared_visible = [shared_target]
        actor.shared_perceived = []
        actor.perceived = [perceived_target]
        actor.any_visible = [own_target, perceived_target, shared_target]

        attack = next(
            entry
            for entry in ActionListBuilder().get_action_entries(
                ActionContext(actor, "attack_phase", battle=battle)
            )
            if entry.action_id == "attack"
        )

        self.assertEqual(attack.valid_targets, [own_target])
        self.assertIn(perceived_target, actor.any_visible)
        self.assertIn(shared_target, actor.any_visible)

    def test_attack_target_rules_exclude_allies(self):
        location = Location("Arena")
        actor = create_servant("Actor")
        ally = create_servant("Ally")
        enemy = create_servant("Enemy")
        actor.position = ally.position = enemy.position = location
        actor.add_ally(ally, source="test")
        actor.own_visible = [ally, enemy]
        battle = BattleManager([actor, ally, enemy])
        battle.start_battle()
        actor.own_visible = [ally, enemy]

        attack = next(
            entry
            for entry in ActionListBuilder().get_action_entries(
                ActionContext(actor, "attack_phase", battle=battle)
            )
            if entry.action_id == "attack"
        )

        self.assertEqual(attack.valid_targets, [enemy])

    def test_direct_attack_excludes_characters_at_same_map_node(self):
        location = Location("Arena")
        remote = Location("Remote")
        actor = create_servant("Actor")
        same_node = create_servant("Same")
        distant = create_servant("Distant")
        actor.position = same_node.position = location
        distant.position = remote
        actor.own_visible = [same_node, distant]

        direct_attack = next(
            entry
            for entry in ActionListBuilder().get_action_entries(
                ActionContext(
                    actor,
                    "AP1",
                    turn_number=1,
                    characters=[actor, same_node, distant],
                )
            )
            if entry.action_id == "direct_attack"
        )

        self.assertTrue(direct_attack.available)
        self.assertEqual(direct_attack.valid_targets, [distant])

    def test_action_entries_keep_unavailable_reasons(self):
        actor = create_servant()
        actor.position = Location("Open Ground")

        hide = next(
            entry
            for entry in ActionListBuilder().get_action_entries(
                ActionContext(actor, "AP1", turn_number=1, characters=[actor])
            )
            if entry.action_id == "hide"
        )

        self.assertFalse(hide.available)
        self.assertIn("position_is_not_building", hide.unavailable_reasons)


class StayEscapeTests(unittest.TestCase):
    def test_pass_spends_one_ap_without_adding_stay(self):
        actor = create_servant()
        actor.position = Location("A")

        self.assertTrue(Action(actor, "pass").pass_action())
        self.assertEqual(actor.action_point, 1)
        self.assertFalse(actor.has_status("stay"))

    def test_stay_spends_attack_phase_and_refreshes_one_modifier(self):
        actor = create_servant("Actor")
        target = create_servant("Target")
        battle = BattleManager([actor, target])
        battle.start_battle()

        self.assertTrue(Action(actor, "stay").stay())
        self.assertEqual(actor.attack_phase_count, 0)
        self.assertIn(actor, battle.stayed_this_round)

        actor.attack_phase_count = 1
        self.assertTrue(Action(actor, "stay").stay())
        stay_modifiers = [
            modifier
            for modifier in actor.modifiers
            if getattr(modifier, "status", None) == "stay"
        ]
        self.assertEqual(len(stay_modifiers), 1)
        self.assertEqual(stay_modifiers[0].duration, 2)

    def test_escape_keeps_position_grants_map_ap_and_has_three_turn_lockout(self):
        location = Location("Battlefield")
        actor = create_servant("Actor")
        first_enemy = create_servant("First")
        second_enemy = create_servant("Second")
        actor.position = first_enemy.position = second_enemy.position = location
        battle = BattleManager([actor, first_enemy, second_enemy])
        battle.start_battle()
        Action(actor, "stay").stay()
        actor.attack_phase_count = 1

        escape = Action(actor, "escape")
        escape.game_turn = 2
        self.assertTrue(escape.escape())
        self.assertIs(actor.position, location)
        self.assertFalse(actor.in_battle)
        self.assertEqual(actor.action_point, 2)
        self.assertEqual(actor.forced_move_turn, 2)
        self.assertEqual(actor.last_escape_turn, 2)
        self.assertFalse(actor.has_status("stay"))
        self.assertEqual(actor.move_conversion, 2)

        # Escape当回合结束时会进行第一次持续时间结算；减益仍覆盖随后三回合。
        for _ in range(3):
            actor.update_modifiers()
            self.assertEqual(actor.move_conversion, 2)
        actor.update_modifiers()
        self.assertEqual(actor.move_conversion, 3)

        for turn_number in (3, 4, 5):
            next_battle = BattleManager([actor, first_enemy])
            next_battle.start_battle()
            actor.status_flags.add("stay")
            actor.attack_phase_count = 1
            retry = Action(actor, "escape")
            retry.game_turn = turn_number
            self.assertFalse(retry.escape())
            next_battle.remove_participant(actor)
            actor.status_flags.discard("stay")

        final_battle = BattleManager([actor, first_enemy])
        final_battle.start_battle()
        actor.status_flags.add("stay")
        actor.attack_phase_count = 1
        retry = Action(actor, "escape")
        retry.game_turn = 6
        self.assertTrue(retry.escape())

    def test_all_stay_disbands_before_next_round_and_only_grants_ap2(self):
        location = Location("Arena")
        first = create_servant("First", flexibility=5)
        second = create_servant("Second", flexibility=3)
        first.position = second.position = location
        battle = BattleManager([first, second])
        battle.start_battle()
        manager = TurnManager()
        manager.characters = [first, second]
        manager.battles = [battle]

        manager.start_turn()
        manager.run_battles(ScriptedDecisionProvider(["stay", "stay"]))
        self.assertTrue(battle.all_stayed_last_round)
        manager.end_turn()

        manager.start_turn()

        self.assertTrue(battle.ended)
        self.assertEqual(battle.end_reason, "all_stayed")
        self.assertEqual(first.action_point, 1)
        self.assertEqual(second.action_point, 1)
        with self.assertRaises(ValueError):
            manager.add_action(Action(first, "pass"), ap_layer=1)
        manager.execute_action_layer(1)
        self.assertTrue(manager.add_action(Action(first, "pass"), ap_layer=2))

    def test_battle_runs_before_map_and_escaped_actor_joins_map_ap1(self):
        location = Location("Battlefield")
        exit_location = Location("Exit")
        connect(location, exit_location)
        actor = create_servant("Actor", flexibility=5)
        first_enemy = create_servant("First", flexibility=3)
        second_enemy = create_servant("Second", flexibility=2)
        first_enemy.add_ally(second_enemy)
        actor.position = first_enemy.position = second_enemy.position = location
        battle = BattleManager([actor, first_enemy, second_enemy])
        battle.start_battle()
        Action(actor, "stay").stay()
        manager = TurnManager()
        manager.characters = [actor, first_enemy, second_enemy]
        manager.battles = [battle]

        manager.start_turn()
        self.assertTrue(manager.battle_phase_pending)
        self.assertFalse(manager.map_phase_started)
        manager.run_battles(ScriptedDecisionProvider(["escape"]))

        self.assertTrue(manager.map_phase_started)
        self.assertIn(actor, manager.non_battle_order)
        self.assertEqual(actor.forced_move_turn, manager.turn)
        with self.assertRaises(ValueError):
            manager.add_action(Action(actor, "pass"), ap_layer=1)
        self.assertTrue(
            manager.add_movement_action(
                actor,
                [location, exit_location],
                ap_layer=1,
            )
        )


class EncounterIntegrationTests(unittest.TestCase):
    def test_one_actor_has_one_movement_decision_and_multiple_declarations(self):
        actor = create_servant("Actor")
        first = create_servant("First")
        second = create_servant("Second")
        actor.own_visible = [first, second]
        encounter = Encounter(
            [actor, first, second],
            None,
            [],
            awareness={actor: [first, second]},
        )

        self.assertTrue(encounter.declare_battle_target(actor, target=first))
        self.assertTrue(encounter.declare_battle_target(actor, target=second))
        self.assertFalse(encounter.resolved)
        self.assertTrue(encounter.finish_battle_decision(actor))
        self.assertTrue(encounter.resolved)
        self.assertEqual(len(encounter.battle_requests), 2)

    def test_declaring_against_battler_joins_the_existing_battle_next_turn(self):
        location = Location("Arena")
        first = create_servant("First")
        second = create_servant("Second")
        newcomer = create_servant("Newcomer")
        first.position = second.position = newcomer.position = location
        existing = BattleManager([first, second])
        existing.start_battle()
        newcomer.own_visible = [first]
        encounter = Encounter(
            [newcomer, first],
            location,
            [],
            awareness={newcomer: [first]},
        )
        encounter.choose_battle(newcomer, first)
        manager = TurnManager()
        manager.characters = [first, second, newcomer]
        manager.battles = [existing]
        manager.add_pending_encounter(encounter)

        manager.start_turn()

        self.assertIs(newcomer.current_battle, existing)
        self.assertIn(newcomer, existing.participants)
        self.assertEqual(
            sum(newcomer in battle.participants for battle in manager.battles),
            1,
        )

    def test_existing_battle_members_do_not_reencounter_each_other_on_map_step(self):
        start = Location("Start")
        arena = Location("Arena")
        connect(start, arena)
        first = create_servant("First")
        second = create_servant("Second")
        mover = create_servant("Mover")
        first.position = second.position = arena
        mover.position = start
        battle = BattleManager([first, second])
        battle.start_battle()
        mover.add_ally(first)
        mover.add_ally(second)
        first.update_visibility([first, second, mover])
        second.update_visibility([first, second, mover])
        mover.update_visibility([first, second, mover])

        from game.map.movement import MovementState
        state = MovementState(mover, [start, arena])
        state.remaining_movement = 1
        encounters = MovementResolver().resolve(
            [state],
            [mover],
            [first, second, mover],
        )

        self.assertEqual(len(encounters), 1)
        self.assertIn(mover, encounters[0].aware_characters)

    def test_ap1_encounter_can_replace_ap2_path_and_stop_ap1_path(self):
        start = Location("Start")
        encounter_location = Location("Encounter")
        old_destination = Location("Old")
        new_destination = Location("New")
        connect(start, encounter_location)
        connect(encounter_location, old_destination)
        connect(encounter_location, new_destination)
        mover = create_servant("Mover", flexibility=5)
        opponent = create_servant("Opponent", flexibility=3)
        mover.position = start
        opponent.position = encounter_location
        manager = TurnManager()
        manager.characters = [mover, opponent]
        manager.start_turn()
        ap1 = manager.add_movement_action(
            mover,
            [start, encounter_location, old_destination],
            ap_layer=1,
        )
        manager.add_movement_action(
            mover,
            [encounter_location, old_destination],
            ap_layer=2,
        )

        waiting = manager.execute_action_layer(1)
        encounter = waiting["encounters"][0]
        manager.replan_encounter(
            encounter,
            mover,
            [encounter_location, new_destination],
        )
        manager.continue_encounter(encounter, opponent)
        manager.resume_action_layer()

        self.assertIs(mover.position, encounter_location)
        self.assertTrue(ap1.movement_state.finished)
        manager.execute_action_layer(2)
        self.assertIs(mover.position, new_destination)


if __name__ == "__main__":
    unittest.main()
