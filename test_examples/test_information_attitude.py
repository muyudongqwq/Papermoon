import unittest

from game.character.familiar import Familiar
from game.character.masters import Master
from game.character.servants import Servant
from game.action.action import Action
from game.game_manager import GameManager
from game.relationship import Attitude
from game.map.map import Location
from game.map.movement import Encounter, MovementResolver, MovementState
from game.turn.battle import BattleManager
from game.turn.decision import ScriptedDecisionProvider


def master(name):
    return Master(name, 3, 3, 3, 3, 3, "C", 3)


def servant(name):
    return Servant(name, 3, 3, 3, 3, 3, "Saber", "C")


def connect(first, second):
    first.add_connection(second)
    second.add_connection(first)


class AttitudeAndInformationTests(unittest.TestCase):
    def setUp(self):
        self.a = Location("A", is_building=True)
        self.b = Location("B", is_building=True)
        connect(self.a, self.b)

    def test_familiar_mirrors_only_summoners_outward_attitude(self):
        summoner = master("Summoner")
        other = servant("Other")
        familiar = Familiar("Scout", summoner)

        summoner.set_base_attitude(other, Attitude.FRIENDLY)
        self.assertEqual(familiar.get_base_attitude(other), Attitude.FRIENDLY)
        self.assertEqual(other.get_base_attitude(familiar), Attitude.NEUTRAL)

        summoner.set_base_attitude(other, Attitude.HOSTILE)
        self.assertEqual(familiar.get_base_attitude(other), Attitude.HOSTILE)
        self.assertEqual(other.get_base_attitude(familiar), Attitude.NEUTRAL)

    def test_ordinary_ally_does_not_share_vision_but_master_servant_does(self):
        owner = master("Owner")
        own_servant = servant("Own Servant")
        ordinary_ally = servant("Ordinary Ally")
        hidden_enemy = servant("Enemy")
        owner.add_servant(own_servant)
        owner.add_ally(ordinary_ally, source="test_alliance")
        owner.position = self.a
        own_servant.position = self.b
        ordinary_ally.position = self.a
        hidden_enemy.position = self.b
        characters = [owner, own_servant, ordinary_ally, hidden_enemy]

        own_servant.update_visibility(characters)
        owner.update_visibility(characters)
        ordinary_ally.update_visibility(characters)

        self.assertIn(hidden_enemy, owner.shared_visible)
        self.assertNotIn(hidden_enemy, ordinary_ally.any_visible)

    def test_alliance_creation_and_exit_apply_on_next_turn(self):
        first = master("First")
        second = servant("Second")
        first.position = second.position = self.a
        game = GameManager([first, second], self.a)
        first.set_base_attitude(second, Attitude.FRIENDLY)
        second.set_base_attitude(first, Attitude.FRIENDLY)

        invitation = game.relationship_manager.invite_alliance(
            first,
            second,
            "moon-pact",
            betrayal_rules=("fixed-rule",),
        )
        game.relationship_manager.accept_invitation(invitation, second)
        self.assertFalse(first.is_ally(second))

        game.turn_manager.turn = 1
        game.relationship_manager.apply_turn_start()
        alliance = game.relationship_manager.get_alliance("moon-pact")
        self.assertIsNotNone(alliance)
        self.assertTrue(first.is_ally(second))
        self.assertEqual(alliance.betrayal_rules, ("fixed-rule",))

        game.relationship_manager.request_exit(first, alliance)
        self.assertTrue(first.is_ally(second))
        game.relationship_manager.apply_turn_start()
        self.assertFalse(first.is_ally(second))
        self.assertTrue(first.is_friendly_with(second))

    def test_friendly_contact_can_replan_but_cannot_declare(self):
        first = servant("First")
        second = servant("Second")
        first.set_base_attitude(second, Attitude.FRIENDLY)
        encounter = Encounter(
            [first, second],
            self.a,
            [],
            awareness={first: [second]},
        )

        self.assertEqual(encounter.get_battle_targets(first), [])
        self.assertFalse(encounter.choose_battle(first, second))
        self.assertTrue(encounter.choose_replan(first))
        self.assertTrue(encounter.resolved)

    def test_identical_following_edge_suppresses_only_repeated_contact(self):
        first = servant("First")
        second = servant("Second")
        first.position = second.position = self.a
        characters = [first, second]
        for character in characters:
            character.update_visibility(characters)
        resolver = MovementResolver()

        initial = resolver.check_encounter(characters, [])
        self.assertEqual(len(initial), 1)
        initial[0].choose_continue(first)
        initial[0].choose_continue(second)

        first_state = MovementState(first, [self.a, self.b], movement_limit=1)
        second_state = MovementState(second, [self.a, self.b], movement_limit=1)
        resolver.step(first_state)
        self.assertEqual(resolver.check_encounter(characters, []), [])
        resolver.step(second_state)
        self.assertEqual(resolver.check_encounter(characters, []), [])

    def test_trap_knowledge_is_persistent_and_not_shared_to_alliance_ally(self):
        owner = master("Owner")
        own_servant = servant("Own Servant")
        ally = servant("Alliance Ally")
        owner.add_servant(own_servant)
        owner.add_ally(ally, source="test_alliance")
        owner.position = own_servant.position = ally.position = self.a
        game = GameManager([owner, own_servant, ally], self.a)

        trap = game.information_manager.register_trap_information(
            "trap-1",
            owner,
            self.a,
            share_with_links=True,
        )
        self.assertTrue(game.information_manager.knows_trap(owner, trap))
        self.assertTrue(game.information_manager.knows_trap(own_servant, trap))
        self.assertFalse(game.information_manager.knows_trap(ally, trap))

        own_servant.position = self.b
        game.information_manager.refresh_trap_sharing()
        self.assertTrue(game.information_manager.knows_trap(own_servant, trap))

    def test_ally_attack_asks_target_and_only_rejection_breaks_relation(self):
        attacker = servant("Attacker")
        target = servant("Target")
        attacker.position = target.position = self.a
        attacker.add_ally(target, source="test")
        game = GameManager([attacker, target], self.a)
        game.start_game()
        battle = BattleManager([attacker, target], auto_link=False)
        battle.add_combat_link(attacker, target, source="test")
        battle.start_battle()
        attacker.own_visible = [target]

        accepted = Action(
            attacker,
            "attack",
            target,
            ignore_attack_phase_count=True,
        )
        self.assertTrue(accepted.attack(ScriptedDecisionProvider(["yes"])))
        self.assertTrue(attacker.is_ally(target))

        target.pending_attacks.clear()
        rejected = Action(
            attacker,
            "attack",
            target,
            ignore_attack_phase_count=True,
        )
        self.assertTrue(rejected.attack(ScriptedDecisionProvider(["no"])))
        self.assertFalse(attacker.is_ally(target))
        self.assertEqual(
            target.get_base_attitude(attacker),
            Attitude.HOSTILE,
        )

    def test_declaration_forces_mutual_hostility_and_creates_combat_link(self):
        first = servant("First")
        second = servant("Second")
        first.position = second.position = self.a
        game = GameManager([first, second], self.a)
        game.start_game()
        encounter = Encounter(
            [first, second],
            self.a,
            [],
            awareness={first: [second]},
        )

        self.assertTrue(encounter.choose_battle(first, second))
        self.assertEqual(first.get_base_attitude(second), Attitude.HOSTILE)
        self.assertEqual(second.get_base_attitude(first), Attitude.HOSTILE)
        battle = BattleManager([first, second], auto_link=False)
        battle.add_combat_link(first, second, encounter.battle_requests[0])
        battle.start_battle()
        self.assertFalse(battle.ended)


if __name__ == "__main__":
    unittest.main()
