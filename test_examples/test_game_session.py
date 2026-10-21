import json
from copy import copy
import threading
import time
import unittest
from unittest.mock import patch

from game.character.familiar import Familiar
from game.character.masters import Master
from game.character.servants import Servant
from game.game_manager import GameManager
from game.game_session import GameSession
from game.game_loop import GameLoop

from game.map.map import Location
from game.turn.battle import BattleManager
from game.turn.decision import ScriptedDecisionProvider


def master(name, flexibility=3):
    return Master(name, 3, 3, flexibility, 3, 3, "C", 3)


class GameSessionTests(unittest.TestCase):
    def make_session(self, *, two=False, separated=False, maximum_turns=1):
        location = Location("A")
        other_location = Location("B")
        location.add_connection(other_location)
        other_location.add_connection(location)
        actor = master("Actor", flexibility=5)
        actor.position = location
        actors = [actor]
        owners = {actor.character_id: "p1"}
        if two:
            other = master("Other")
            other.position = other_location if separated else location
            actors.append(other)
            owners[other.character_id] = "p2"
        game = GameManager(actors, location, maximum_turns=maximum_turns)
        return self.attach_session(GameSession(game, owners)), actors

    def attach_session(self, session):
        def cleanup():
            session.stop()
            self.assertTrue(session.join(2), "会话工作线程未结束")
        self.addCleanup(cleanup)
        return session

    def wait_event(self, session, event_type, *, after=0, owner="gm"):
        deadline = time.monotonic() + 3
        cursor = after
        while time.monotonic() < deadline:
            events = session.get_events(owner, after=cursor, timeout=0.2)
            for event in events:
                cursor = event["sequence"]
                if event["type"] == event_type:
                    return event
            if session.state in session.TERMINAL_STATES:
                break
        self.fail(f"缺少事件{event_type}: {session.get_snapshot('gm')}")

    def answer(self, session, request, label=None, *, value=None, owner=None):
        arguments = {"value": value} if request["kind"] == "numeric" else {
            "option_id": next(option["option_id"] for option in request["options"]
                              if label is None or option["label"] == label)
        }
        session.submit_decision(owner or request["controller_id"], request["request_id"],
                                request["revision"], **arguments)

    def finish_with_pass(self, session, *, after=0):
        cursor = after
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            for event in session.get_events("gm", after=cursor, timeout=0.2):
                cursor = event["sequence"]
                if event["type"] == "decision_requested":
                    self.answer(session, event["payload"], "空过")
                elif event["type"] == "session_ended":
                    self.assertEqual(event["payload"]["state"], "completed")
                    self.assertTrue(session.join(2))
                    return
        self.fail("会话未完成")

    def test_two_clients_complete_game_using_only_serializable_messages(self):
        session, actors = self.make_session(two=True)
        failures = []
        answered = []

        def client(owner):
            try:
                cursor = 0
                while True:
                    for event in session.get_events(owner, after=cursor, timeout=1):
                        json.dumps(event, ensure_ascii=False)
                        cursor = event["sequence"]
                        if event["type"] == "decision_requested":
                            request = event["payload"]
                            self.assertEqual(request["controller_id"], owner)
                            self.answer(session, request, "空过", owner=owner)
                            answered.append(owner)
                        elif event["type"] == "session_ended":
                            return
            except Exception as error:
                failures.append(error)
                session.stop()

        session.start()
        clients = [threading.Thread(target=client, args=(owner,), daemon=True)
                   for owner in ("p1", "p2")]
        for client_thread in clients:
            client_thread.start()
        for client_thread in clients:
            client_thread.join(3)
            self.assertFalse(client_thread.is_alive())
        self.assertEqual(failures, [])
        self.assertTrue(session.join(2))
        self.assertEqual(session.state, "completed")
        self.assertCountEqual(answered, ["p1", "p1", "p2", "p2"])
        snapshot = session.get_snapshot("p1")
        json.dumps(snapshot, ensure_ascii=False)
        self.assertEqual(snapshot["result"], {"reason": "turn_limit", "winners": [], "turn": 1})
        self.assertTrue(all(actor.has_status("dead") for actor in actors))
        decisions = [event["payload"] for event in session.get_events("gm")
                     if event["type"] == "decision_answered"]
        replay_commands = [int(item["option_id"].split(":")[1]) for item in decisions]
        replay_location = Location("A")
        replay_other_location = Location("B")
        replay_location.add_connection(replay_other_location)
        replay_other_location.add_connection(replay_location)
        replay_actors = [master("Actor", flexibility=5), master("Other")]
        for actor in replay_actors:
            actor.position = replay_location
        replay = GameManager(replay_actors, replay_location, maximum_turns=1)
        result = GameLoop(replay, ScriptedDecisionProvider(replay_commands)).run()
        self.assertEqual(result, snapshot["result"])

    def test_wrong_owner_stale_version_and_raw_strings_are_rejected(self):
        session, _ = self.make_session(two=True)
        session.start()
        event = self.wait_event(session, "decision_requested")
        request = event["payload"]
        option_id = request["options"][0]["option_id"]
        with self.assertRaises(PermissionError):
            session.submit_decision("p2", request["request_id"], request["revision"], option_id=option_id)
        with self.assertRaises(ValueError):
            session.submit_decision("p1", request["request_id"], request["revision"] + 1, option_id=option_id)
        with self.assertRaises(ValueError):
            session.submit_decision("p1", request["request_id"], request["revision"], option_id="pass")
        with self.assertRaises(ValueError):
            session.submit_decision("p1", request["request_id"], request["revision"], value="pass")
        self.assertEqual(session.get_pending_decision("p1"), request)
        self.assertIsNone(session.get_pending_decision("p2"))
        self.answer(session, request, "空过")
        with self.assertRaises(ValueError):
            self.answer(session, request, "空过")

    def test_command_spell_refresh_invalidates_old_answer_and_unlocks_skill(self):
        session, (actor,) = self.make_session()
        actor.load_basic_magic("protection")
        actor.mp = 0
        session.start()
        first = self.wait_event(session, "decision_requested")
        old = first["payload"]
        self.assertNotIn("防护", [option["label"] for option in old["options"]])
        operation = session.command_spell("p1", master_id=actor.character_id,
                                          target_id=actor.character_id, effect="mp")
        refreshed = self.wait_event(session, "decision_requested", after=first["sequence"])
        request = refreshed["payload"]
        self.assertGreater(request["revision"], old["revision"])
        self.assertNotEqual(request["request_id"], old["request_id"])
        self.assertIn("防护", [option["label"] for option in request["options"]])
        with self.assertRaises(ValueError):
            self.answer(session, old, "空过")
        self.assertEqual(actor.command_spell, 2)
        self.assertEqual(actor.temporary_mp, 90)
        completed = [event for event in session.get_events("p1") if event["type"] == "operation_completed"]
        self.assertEqual(completed[0]["payload"]["operation_id"], operation)
        self.answer(session, request, "空过")
        self.finish_with_pass(session, after=refreshed["sequence"])

    def test_numeric_choice_validation_and_nested_skill_inputs(self):
        session, (actor,) = self.make_session()
        actor.load_basic_magic("protection")
        session.start()
        event = self.wait_event(session, "decision_requested")
        self.answer(session, event["payload"], "防护")
        target = self.wait_event(session, "decision_requested", after=event["sequence"])
        self.answer(session, target["payload"], "Actor")
        numeric = self.wait_event(session, "decision_requested", after=target["sequence"])
        request = numeric["payload"]
        self.assertEqual(request["kind"], "numeric")
        for value in (True, "10", 1.5, request["maximum"] + 1):
            with self.assertRaises(ValueError):
                self.answer(session, request, value=value)
        self.answer(session, request, value=10)
        next_action = self.wait_event(session, "decision_requested", after=numeric["sequence"])
        self.assertEqual(actor.shield, 15)
        self.answer(session, next_action["payload"], "空过")
        self.finish_with_pass(session, after=next_action["sequence"])

    def test_views_hide_unseen_characters_and_enemy_resources_and_are_detached(self):
        session, actors = self.make_session(two=True, separated=True)
        session.start()
        self.wait_event(session, "decision_requested")
        own = session.get_snapshot("p1")
        full = session.get_snapshot("gm")
        self.assertEqual([actor["character_id"] for actor in own["characters"]], [actors[0].character_id])
        self.assertEqual(len(full["characters"]), 2)
        own["characters"][0]["hp"] = -999
        self.assertNotEqual(session.get_snapshot("p1")["characters"][0]["hp"], -999)
        self.assertFalse(any(event["type"] == "decision_requested" for event in session.get_events("p2")))
        with self.assertRaises(PermissionError):
            session.get_snapshot("intruder")

        same_place, _ = self.make_session(two=True)
        same_place.start()
        self.wait_event(same_place, "decision_requested")
        visible_enemy = next(actor for actor in same_place.get_snapshot("p1")["characters"] if actor["name"] == "Other")
        self.assertNotIn("hp", visible_enemy)
        self.assertNotIn("mp", visible_enemy)

    def test_stop_wakes_waiting_engine_and_clears_request(self):
        session, _ = self.make_session()
        session.start()
        self.wait_event(session, "decision_requested")
        session.stop()
        self.assertTrue(session.join(2))
        self.assertEqual(session.state, "stopped")
        self.assertIsNone(session.get_pending_decision("gm"))
        self.assertEqual(session.get_snapshot("gm")["result"]["reason"], "session_stopped")
        with self.assertRaises(ValueError):
            session.start()

    def test_worker_failure_is_reported_and_does_not_leave_client_waiting(self):
        session, _ = self.make_session()
        def broken_start():
            raise RuntimeError("test engine failure")
        session.game_manager.start_game = broken_start
        session.start()
        self.assertTrue(session.join(2))
        self.assertEqual(session.state, "failed")
        self.assertIn("test engine failure", session.get_snapshot("gm")["error"])
        self.assertNotIn("error", session.get_snapshot("p1"))
        self.assertEqual(session.get_snapshot("p1")["result"]["reason"], "session_error")

    def test_gm_commands_use_ids_even_when_names_are_duplicated(self):
        session, actors = self.make_session(two=True)
        actors[0].name = actors[1].name = "Same name"
        first_id, second_id = [actor.character_id for actor in actors]
        self.assertNotEqual(first_id, second_id)
        actors[1].hp -= 20
        session.start()
        waiting = self.wait_event(session, "decision_requested")
        with self.assertRaises(PermissionError):
            session.gm_command("p1", "kill", target_id=second_id)
        session.gm_command("gm", "add_resource", target_id=second_id, resource="hp", amount=10)
        refreshed = self.wait_event(session, "decision_requested", after=waiting["sequence"])
        self.assertEqual(actors[1].hp, actors[1].hpmax - 10)
        self.assertEqual(actors[0].hp, actors[0].hpmax)
        session.gm_command("gm", "damage", target_id=second_id, damage_type=0, amount=5)
        next_request = self.wait_event(session, "decision_requested", after=refreshed["sequence"])
        self.assertEqual(actors[1].hp, actors[1].hpmax - 15)
        destination = next(node["position_id"] for node in session.get_snapshot("gm")["positions"] if node["name"] == "B")
        session.gm_command("gm", "teleport", target_id=second_id, destination_id=destination)
        teleported = self.wait_event(session, "decision_requested", after=next_request["sequence"])
        self.assertEqual(actors[1].position.name, "B")
        session.gm_command("gm", "kill", target_id=first_id)
        remaining = self.wait_event(session, "decision_requested", after=teleported["sequence"])
        self.assertEqual(remaining["payload"]["character_id"], second_id)
        self.assertTrue(actors[0].has_status("dead"))
        self.answer(session, remaining["payload"], "空过")
        self.finish_with_pass(session, after=remaining["sequence"])

    def test_invalid_operation_returns_error_and_reissues_request(self):
        session, actors = self.make_session(two=True)
        session.start()
        event = self.wait_event(session, "decision_requested")
        operation = session.command_spell("p2", master_id=actors[0].character_id,
                                          target_id=actors[0].character_id, effect="mp")
        error = self.wait_event(session, "operation_failed", after=event["sequence"])
        self.assertEqual(error["payload"]["operation_id"], operation)
        self.assertEqual(actors[0].command_spell, 3)
        refreshed = self.wait_event(session, "decision_requested", after=error["sequence"])
        self.assertEqual(refreshed["payload"]["character_id"], actors[0].character_id)

    def test_master_servant_and_summon_control_is_stable(self):
        location = Location("A")
        owner = master("Owner")
        servant = Servant("Servant", 3, 3, 5, 3, 3, "Saber", "A")
        owner.add_servant(servant)
        familiar = Familiar("Familiar", owner)
        for actor in (owner, servant, familiar):
            actor.position = location
        game = GameManager([owner, servant, familiar], location, maximum_turns=1)
        session = self.attach_session(GameSession(game, {owner.character_id: "p1"}))
        session.start()
        self.wait_event(session, "decision_requested")
        self.assertCountEqual(session.get_snapshot("p1")["controlled_character_ids"],
                              [actor.character_id for actor in (owner, servant, familiar)])
        self.finish_with_pass(session)
        self.assertEqual(session.state, "completed")

    def test_gm_damage_can_pause_for_nested_reaction_then_refresh_outer_choice(self):
        session, (actor,) = self.make_session()
        actor.create_personal_skill({
            "skill_id": "session_reaction", "name": "Reaction", "rank": "C",
            "components": [{
                "component_id": "reduce", "type": "react",
                "trigger": {"event_type": "before_damage", "timing": "before"},
                "condition": {"event_target_is_self": True}, "target": "self",
                "effects": [{"effect_type": "modify_event_value", "effect_data": {
                    "operation": "add", "value": -10, "minimum": 0,
                }}],
            }],
        })
        starting_hp = actor.hp
        session.start()
        outer = self.wait_event(session, "decision_requested")
        session.gm_command("gm", "damage", target_id=actor.character_id, damage_type=0, amount=20)
        reaction = self.wait_event(session, "decision_requested", after=outer["sequence"])
        self.assertFalse(reaction["payload"]["allow_refresh"])
        with self.assertRaises(ValueError):
            session.command_spell("p1", master_id=actor.character_id, target_id=actor.character_id, effect="mp")
        self.answer(session, reaction["payload"])
        refreshed = self.wait_event(session, "decision_requested", after=reaction["sequence"])
        self.assertEqual(actor.hp, starting_hp - 10)
        self.assertGreater(refreshed["payload"]["revision"], reaction["payload"]["revision"])
        self.assertEqual(refreshed["payload"]["phase"], outer["payload"]["phase"])

    def test_ids_survive_renaming_and_dynamic_registration(self):
        location = Location("A")
        actor = master("Same")
        actor.position = location
        original_id = actor.character_id
        actor.name = "Renamed"
        self.assertEqual(actor.character_id, original_id)
        with self.assertRaises(AttributeError):
            actor.character_id = "replacement"
        game = GameManager([actor], location)
        game.start_game()
        familiar = Familiar("Renamed", actor)
        self.assertTrue(game.register_character(familiar, location))
        self.assertNotEqual(familiar.character_id, actor.character_id)
        familiar_id = familiar.character_id
        game.despawn_character(familiar)
        self.assertEqual(familiar.character_id, familiar_id)
        duplicate = copy(actor)
        with self.assertRaises(ValueError):
            game.register_character(duplicate, location)
        self.assertNotIn(duplicate, game.characters)

    def test_gm_teleport_during_path_planning_rebuilds_action_window(self):
        session, (actor,) = self.make_session()
        session.start()
        action = self.wait_event(session, "decision_requested")
        self.answer(session, action["payload"], "移动")
        path = self.wait_event(session, "decision_requested", after=action["sequence"])
        self.assertEqual(path["payload"]["phase"], "move_path")
        self.assertTrue(path["payload"]["allow_refresh"])
        destination = next(node["position_id"] for node in session.get_snapshot("gm")["positions"] if node["name"] == "B")
        session.gm_command("gm", "teleport", target_id=actor.character_id, destination_id=destination)
        refreshed = self.wait_event(session, "decision_requested", after=path["sequence"])
        self.assertEqual(refreshed["payload"]["phase"], "AP1")
        self.assertEqual(actor.position.name, "B")
        with self.assertRaises(ValueError):
            self.answer(session, path["payload"])
        self.answer(session, refreshed["payload"], "空过")
        self.finish_with_pass(session, after=refreshed["sequence"])

    def test_command_spell_damage_and_teleport_reuse_existing_costs(self):
        a, b = Location("A"), Location("B")
        a.add_connection(b)
        b.add_connection(a)
        owner = master("Owner")
        servant = Servant("Servant", 3, 3, 5, 3, 3, "Saber", "A")
        owner.add_servant(servant)
        owner.position = servant.position = a
        servant.seen_locations.add(b)
        game = GameManager([owner, servant], a, maximum_turns=1)
        session = self.attach_session(GameSession(game, {owner.character_id: "p1"}))
        session.start()
        initial = self.wait_event(session, "decision_requested")
        session.command_spell("p1", master_id=owner.character_id, target_id=servant.character_id, effect="damage")
        refreshed = self.wait_event(session, "decision_requested", after=initial["sequence"])
        self.assertEqual(servant.command_spell_damage_bonus, 90)
        destination = next(node["position_id"] for node in session.get_snapshot("p1")["positions"] if node["name"] == "B")
        session.command_spell("p1", master_id=owner.character_id, target_id=servant.character_id,
                              effect="teleport", destination_id=destination)
        moved = self.wait_event(session, "decision_requested", after=refreshed["sequence"])
        self.assertIs(servant.position, b)
        self.assertEqual(owner.command_spell, 0)
        self.answer(session, moved["payload"], "空过")
        self.finish_with_pass(session, after=moved["sequence"])

    def test_dynamic_summon_receives_id_and_owner_in_next_snapshot(self):
        session, (actor,) = self.make_session(maximum_turns=2)
        actor.load_basic_magic("familiar")
        session.start()
        initial = self.wait_event(session, "decision_requested")
        summon_label = next(option["label"] for option in initial["payload"]["options"]
                            if "使魔" in option["label"])
        self.answer(session, initial["payload"], summon_label)
        next_turn = self.wait_event(session, "decision_requested", after=initial["sequence"])
        self.assertEqual(session.get_snapshot("p1")["turn"], 2)
        familiar = actor.familiars[0]
        self.assertNotEqual(familiar.character_id, actor.character_id)
        self.assertIn(familiar.character_id, session.get_snapshot("p1")["controlled_character_ids"])
        self.answer(session, next_turn["payload"], "空过")
        self.finish_with_pass(session, after=next_turn["sequence"])

    def test_queue_pauses_for_battle_defense_and_luck_choices(self):
        location = Location("Arena")
        first = Servant("First", 3, 5, 5, 3, 3, "Saber", "A")
        second = Servant("Second", 3, 5, 3, 3, 3, "Archer", "A")
        first.position = second.position = location
        game = GameManager([first, second], location, maximum_turns=1)
        game.start_game()
        battle = BattleManager([first, second])
        game.turn_manager.battles.append(battle)
        battle.start_battle()
        session = self.attach_session(GameSession(game, {first.character_id: "p1", second.character_id: "p2"}))
        phases = []
        cursor = 0
        with patch("game.turn.roll.random.randint", return_value=5):
            session.start()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                events = session.get_events("gm", after=cursor, timeout=0.2)
                for event in events:
                    cursor = event["sequence"]
                    if event["type"] != "decision_requested":
                        continue
                    request = event["payload"]
                    phases.append(request["phase"])
                    label = None
                    if request["phase"] == "攻击":
                        label = "普通攻击" if request["character_id"] == first.character_id else "停留"
                    elif request["phase"] == "攻击目标选择":
                        label = "Second"
                    elif request["phase"] == "防御":
                        label = "格挡"
                    self.answer(session, request, label)
                if session.state in session.TERMINAL_STATES:
                    break
            self.assertTrue(session.join(2))
        self.assertEqual(session.state, "completed", session.get_snapshot("gm"))
        self.assertIn("防御", phases)
        self.assertTrue(any("幸运" in phase for phase in phases))
        self.assertGreater(second.last_defense_total_damage, 0)

    def test_final_winners_are_ids_and_ended_session_needs_no_answers(self):
        session, (actor,) = self.make_session()
        session.game_manager.start_game()
        session.game_manager.end_game(reason="victory", winners=[actor])
        session.start()
        self.assertTrue(session.join(2))
        self.assertEqual(session.get_snapshot("p1")["result"],
                         {"reason": "victory", "winners": [actor.character_id], "turn": 0})
        self.assertIsNone(session.get_pending_decision("p1"))

    def test_view_failure_still_closes_session_and_releases_game(self):
        session, _ = self.make_session()
        def broken_view():
            raise RuntimeError("test view failure")
        session._capture_views = broken_view
        session.start()
        self.assertTrue(session.join(2))
        self.assertEqual(session.state, "failed")
        self.assertIn("test view failure", session.get_snapshot("gm")["error"])
        self.assertIsNone(session.game_manager._active_session)
        self.assertEqual(session.get_events("p1")[-1]["type"], "session_ended")

    def test_only_one_session_can_own_game_and_stop_before_start_is_final(self):
        session, actors = self.make_session()
        other = self.attach_session(GameSession(session.game_manager, {actors[0].character_id: "p1"}))
        session.start()
        self.wait_event(session, "decision_requested")
        with self.assertRaises(ValueError):
            other.start()
        self.assertIs(session.game_manager.decision_provider, session.decision_provider)
        other.stop()
        self.assertEqual(other.state, "stopped")
        self.assertEqual(other.get_snapshot("gm")["result"]["reason"], "session_stopped")
        with self.assertRaises(ValueError):
            other.start()


if __name__ == "__main__":
    unittest.main()
