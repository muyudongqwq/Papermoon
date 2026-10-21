import unittest

from game.action.action import Action
from game.action.action_list import ActionContext, ActionListBuilder
from game.character.masters import Master
from game.character.servants import Servant
from game.map.map import Location
from game.map.movement import MovementAction, MovementResolver
from game.map.ride_group import create_ride_group, get_movement_formation
from game.map.travel_group import TravelGroup
from game.skill.skill_runtime import load_class_skill
from game.turn.damage import AttackProfile
from game.turn.Turn import TurnManager


def create_master(name, move=2):
    character = Master(name, 3, 3, 3, 3, 3, "C", 3)
    character.move_conversion = move
    return character


def create_assassin(name, rank):
    character = Servant(name, 3, 3, 3, 3, 3, "Assassin", "C")
    load_class_skill(character, "气息遮断", rank)
    return character


def connect(left, right):
    left.add_connection(right)
    right.add_connection(left)


class PresenceConcealmentTests(unittest.TestCase):
    def setUp(self):
        self.building = Location("Building", is_building=True)

    def test_rank_bonus_and_observer_relative_visibility(self):
        observer = create_master("Observer")
        assassin = create_assassin("Assassin", "C")
        observer.position = assassin.position = self.building

        self.assertEqual(assassin.hide, 5)
        observer.update_visibility([observer, assassin])
        self.assertNotIn(assassin, observer.any_visible)

        observer.own_perceived.append(assassin)
        observer.update_visibility([observer, assassin])
        self.assertNotIn(assassin, observer.own_visible)
        self.assertIn(assassin, observer.any_visible)

    def test_investigation_reveals_normal_hidden_but_not_rank_b(self):
        investigator = create_master("Investigator")
        normal = Servant("Normal", 3, 3, 3, 3, 3, "Saber", "C")
        assassin = create_assassin("Assassin", "B")
        investigator.position = normal.position = assassin.position = self.building
        Action(normal, "hide", characters=[investigator, normal, assassin]).hide()

        result = Action(
            investigator,
            "investigate",
            characters=[investigator, normal, assassin],
        ).investigate()

        self.assertIn(normal, result["servants"])
        self.assertNotIn(assassin, result["servants"])

    def test_rank_a_active_hide_cannot_be_perceived(self):
        observer = create_master("Observer")
        assassin = create_assassin("Assassin", "A")
        observer.position = assassin.position = self.building
        Action(assassin, "hide", characters=[observer, assassin]).hide()
        observer.perceive = 100

        result = Action(
            observer,
            "perceive",
            characters=[observer, assassin],
        ).perceive()

        self.assertNotIn(assassin, observer.own_perceived)
        self.assertEqual(
            result["checks"][0]["blocked_by"],
            "presence_concealment",
        )

    def test_attack_exposes_presence_until_next_global_turn(self):
        observer = create_master("Observer")
        assassin = create_assassin("Assassin", "C")
        observer.position = assassin.position = self.building
        observer.update_visibility([observer, assassin])
        self.assertNotIn(assassin, observer.any_visible)

        AttackProfile(
            assassin,
            10,
            "physical",
            10,
        ).assign_target(observer)
        observer.update_visibility([observer, assassin])
        self.assertIn(assassin, observer.any_visible)

        assassin.reset_turn()
        observer.update_visibility([observer, assassin])
        self.assertNotIn(assassin, observer.any_visible)

    def test_entering_battle_removes_active_hide_and_auto_concealment(self):
        observer = create_master("Observer")
        assassin = create_assassin("Assassin", "A")
        observer.position = assassin.position = self.building
        Action(assassin, "hide", characters=[observer, assassin]).hide()

        assassin.start_battle()
        observer.update_visibility([observer, assassin])

        self.assertFalse(assassin.has_status("hidden"))
        self.assertIn(assassin, observer.any_visible)


class CarryTests(unittest.TestCase):
    def setUp(self):
        self.a = Location("A")
        self.b = Location("B")
        self.c = Location("C")
        self.d = Location("D")
        connect(self.a, self.b)
        connect(self.b, self.c)
        connect(self.c, self.d)

    def test_rider_controls_route_and_uses_fastest_member_speed(self):
        rider = create_master("Rider", move=4)
        passenger = create_master("Passenger", move=1)
        rider.carry_capacity = 1
        rider.position = passenger.position = self.a
        group = create_ride_group(rider, passenger)

        action = MovementAction(
            rider,
            [self.a, self.b, self.c, self.d],
            ap_layer=1,
        )
        action.ap_layer = 1
        resolver = MovementResolver()

        self.assertIsNotNone(group)
        self.assertTrue(action.prepare(resolver))
        resolver.resolve([action.movement_state], [rider, passenger], [rider, passenger])
        self.assertIs(rider.position, self.d)
        self.assertIs(passenger.position, self.d)
        self.assertEqual(rider.action_point, 1)
        self.assertEqual(passenger.action_point, 1)

    def test_travel_group_takes_minimum_of_ride_units(self):
        rider = create_master("Rider", move=5)
        passenger = create_master("Passenger", move=1)
        walker = create_master("Walker", move=3)
        rider.carry_capacity = 1
        rider.position = passenger.position = walker.position = self.a
        rider.add_ally(walker)
        create_ride_group(rider, passenger)
        travel = TravelGroup(rider, [walker])

        members, speed = get_movement_formation(rider, ap_layer=1)

        self.assertEqual(speed, 3)
        self.assertEqual(set(members), {rider, passenger, walker})
        self.assertIs(rider.travel_group, travel)
        self.assertIsNone(passenger.travel_group)

    def test_nested_carry_is_rejected_and_battle_dissolves_carry(self):
        rider = create_master("Rider", move=4)
        passenger = create_master("Passenger", move=2)
        third = create_master("Third", move=1)
        rider.carry_capacity = passenger.carry_capacity = 1
        rider.position = passenger.position = third.position = self.a
        group = create_ride_group(rider, passenger)

        self.assertIsNone(create_ride_group(passenger, third))
        rider.start_battle()
        self.assertIsNone(rider.ride_group)
        self.assertIsNone(passenger.carried_by)

    def test_riding_class_skill_provides_capacity(self):
        rider = Servant("Rider", 3, 3, 3, 3, 3, "Rider", "C")
        load_class_skill(rider, "骑乘", "B")
        self.assertEqual(rider.get_carry_capacity(), 1)
        self.assertTrue(rider.has_status("carriable"))

    def test_losing_capacity_dissolves_the_ride_group(self):
        rider = Servant("Rider", 3, 3, 3, 3, 3, "Rider", "C")
        passenger = create_master("Passenger")
        rider.position = passenger.position = self.a
        load_class_skill(rider, "骑乘", "B")
        create_ride_group(rider, passenger)
        modifier = next(
            modifier
            for modifier in rider.modifiers
            if modifier.effect_type == "carry_capacity"
        )

        rider.remove_modifier(modifier)

        self.assertIsNone(rider.ride_group)
        self.assertIsNone(passenger.carried_by)
        self.assertFalse(rider.has_status("carriable"))

    def test_invitation_action_is_free_and_requires_acceptance(self):
        rider = create_master("Rider", move=4)
        passenger = create_master("Passenger", move=2)
        rider.carry_capacity = 1
        rider.position = passenger.position = self.a
        manager = TurnManager()
        manager.characters = [rider, passenger]
        manager.start_turn()
        context = ActionContext(
            actor=rider,
            phase="AP1",
            turn_number=manager.turn,
            turn_manager=manager,
            characters=[rider, passenger],
        )

        entries = ActionListBuilder().get_available_actions(context)
        invite = next(entry for entry in entries if entry.action_id == "invite_carry")
        self.assertEqual(invite.valid_targets, [passenger])
        self.assertFalse(manager.invite_to_ride(rider, passenger, accepted=False))
        group = manager.invite_to_ride(rider, passenger, accepted=True)

        self.assertIsNotNone(group)
        self.assertEqual(rider.action_point, 2)
        self.assertEqual(passenger.action_point, 2)


if __name__ == "__main__":
    unittest.main()
