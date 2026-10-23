import unittest

from game.character.masters import Master
from game.game.game_manager import GameManager
from game.map.map import Location


def make_master(name):
    return Master(name, 3, 3, 3, 3, 3, "C", 3)


def reality_marble_skill(*, radius=0, duration=None, maintenance=None):
    data = {
        "reality_marble_id": "test_marble",
        "name": "测试固有结界",
        "capture_radius": radius,
        "duration": duration,
        "interior": {
            "location_name": "测试固有结界内部",
            "effects": [{
                "modifier_id": "marble_visibility",
                "effect_type": "visibility_bonus",
                "application_mode": "continuous",
                "effect_target": {
                    "scope": "characters_in_field",
                    "relation": "all",
                },
                "effect_data": {"value": 1},
            }],
        },
    }
    if maintenance is not None:
        data["maintenance"] = maintenance
    return {
        "skill_id": "test_reality_marble_skill",
        "name": "测试固有结界",
        "rank": "A",
        "skill_category": "reality_marble",
        "components": [{
            "component_id": "deploy",
            "type": "active",
            "available_phases": ["AP1", "attack_phase"],
            "target": "self",
            "cost": [{"resource": "mp", "value": 10}],
            "effects": [{
                "effect_type": "deploy_reality_marble",
                "effect_data": data,
            }],
        }],
    }


def ordinary_field_skill():
    return {
        "skill_id": "inside_field",
        "name": "内部结界",
        "rank": "C",
        "skill_category": "field_skill",
        "components": [{
            "component_id": "deploy",
            "type": "active",
            "available_phases": ["AP1"],
            "target": "self",
            "cost": [],
            "effects": [{
                "effect_type": "create_field",
                "effect_data": {
                    "field_id": "forbidden_inside_field",
                    "field_type": "bounded_field",
                    "radius": 0,
                    "effects": [],
                },
            }],
        }],
    }


class RealityMarbleTests(unittest.TestCase):
    def setUp(self):
        self.entrance = Location("入口")
        self.outside = Location("外部")
        self.entrance.add_connection(self.outside)
        self.outside.add_connection(self.entrance)
        self.owner = make_master("Owner")
        self.target = make_master("Target")
        self.bystander = make_master("Bystander")
        self.owner.position = self.target.position = self.entrance
        self.bystander.position = self.outside
        self.game = GameManager(
            [self.owner, self.target, self.bystander],
            self.entrance,
        )
        self.game.start_game()
        self.skill = self.owner.create_personal_skill(reality_marble_skill())

    def deploy(self):
        result = self.owner.resolve_skill_component(
            self.skill.skill_id,
            "deploy",
        )
        return result["results"][0]["reality_marble"]

    def test_deploy_creates_disconnected_map_and_captures_exact_node(self):
        marble = self.deploy()
        self.assertIs(self.game.active_reality_marble, marble)
        self.assertIs(self.owner.position, marble.interior)
        self.assertIs(self.target.position, marble.interior)
        self.assertIs(self.bystander.position, self.outside)
        self.assertEqual(marble.interior.connected_locations, [])
        self.assertIn(marble.interior, self.owner.seen_locations)
        self.assertEqual(self.owner.visibility, 1)

    def test_owner_leaving_immediately_collapses_and_returns_occupants(self):
        marble = self.deploy()
        self.owner.position = self.outside
        self.assertIsNone(self.game.active_reality_marble)
        self.assertTrue(marble.collapsed)
        self.assertEqual(marble.collapse_reason, "owner_left")
        self.assertIs(self.owner.position, self.outside)
        self.assertIs(self.target.position, self.entrance)
        self.assertEqual(self.target.visibility, 0)

    def test_owner_death_immediately_collapses(self):
        marble = self.deploy()
        self.owner.die()
        self.assertIsNone(self.game.active_reality_marble)
        self.assertEqual(marble.collapse_reason, "owner_dead")
        self.assertIs(self.target.position, self.entrance)
        self.assertIn(self.owner, self.game.dead_characters)

    def test_ordinary_fields_cannot_be_created_inside(self):
        marble = self.deploy()
        field_skill = self.target.create_personal_skill(ordinary_field_skill())
        result = self.target.resolve_skill_component(
            field_skill.skill_id,
            "deploy",
        )
        field_result = result["results"][0]
        self.assertFalse(field_result["created"])
        self.assertEqual(
            field_result["reason"],
            "reality_marble_forbids_field",
        )
        self.assertEqual(self.game.field_effects, [])
        self.assertIs(self.game.active_reality_marble, marble)

    def test_second_reality_marble_is_blocked_and_refunds_mp(self):
        from game.skill.skill_runtime import SkillUnavailableError

        self.deploy()
        other_skill = self.target.create_personal_skill(reality_marble_skill())
        # Skill ids are per-character, so the same definition is valid here.
        before = self.target.mp
        with self.assertRaises(SkillUnavailableError):
            self.target.resolve_skill_component(
                other_skill.skill_id,
                "deploy",
            )
        self.assertEqual(self.target.mp, before)

    def test_duration_expiry_returns_everyone_to_entrance(self):
        owner = make_master("DurationOwner")
        target = make_master("DurationTarget")
        owner.position = target.position = self.entrance
        game = GameManager([owner, target], self.entrance)
        game.start_game()
        skill = owner.create_personal_skill(
            reality_marble_skill(duration=1)
        )
        game.turn_manager.turn = 1
        owner.current_global_turn = 1
        owner.resolve_skill_component(skill.skill_id, "deploy")
        game.reality_marble_manager.end_turn(1)
        self.assertIsNotNone(game.active_reality_marble)
        game.reality_marble_manager.end_turn(2)
        self.assertIsNone(game.active_reality_marble)
        self.assertIs(owner.position, self.entrance)
        self.assertIs(target.position, self.entrance)


if __name__ == "__main__":
    unittest.main()
