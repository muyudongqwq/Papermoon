import unittest

from game.character.masters import Master
from game.game.game_manager import GameManager
from game.map.map import Location


def make_master(name):
    return Master(name, 3, 3, 3, 3, 3, "C", 3)


def field_skill_definition(
    skill_id,
    field_id,
    *,
    field_type="bounded_field",
    effects=None,
    duration=None,
    maintenance=None,
):
    data = {
        "field_id": field_id,
        "name": field_id,
        "field_type": field_type,
        "radius": 0,
        "duration": duration,
        "effects": list(effects or []),
    }
    if maintenance is not None:
        data["maintenance"] = maintenance
    return {
        "skill_id": skill_id,
        "name": field_id,
        "rank": "C",
        "skill_category": "field_skill",
        "components": [{
            "component_id": "deploy",
            "type": "active",
            "available_phases": ["AP1"],
            "target": "self",
            "cost": [
                {"resource": "action_point", "value": 1},
                {"resource": "mp", "value": 10},
            ],
            "effects": [{
                "effect_type": "create_field",
                "effect_data": data,
            }],
        }],
    }


class FieldSkillTests(unittest.TestCase):
    def setUp(self):
        self.ground = Location("Tower", high_level=True, is_building=True)
        self.upper = self.ground.high_level_location
        self.other = Location("Other")
        self.ground.add_connection(self.other)
        self.other.add_connection(self.ground)
        self.first = make_master("First")
        self.second = make_master("Second")
        self.first.position = self.second.position = self.ground
        self.game = GameManager([self.first, self.second], self.ground)
        self.game.start_game()

    def test_territory_covers_and_reserves_ground_and_upper_level(self):
        skill = self.first.create_personal_skill(field_skill_definition(
            "territory_skill",
            "territory",
            field_type="territory",
        ))
        result = self.first.resolve_skill_component(
            skill.skill_id,
            "deploy",
        )
        field = result["results"][0]["field"]
        self.assertIn(self.ground, field.covered_nodes)
        self.assertIn(self.upper, field.covered_nodes)
        self.assertIn(field, self.ground.field_effects)
        self.assertIn(field, self.upper.field_effects)

        self.second.position = self.upper
        other_skill = self.second.create_personal_skill(field_skill_definition(
            "workshop_skill",
            "workshop",
            field_type="workshop",
        ))
        mp_before = self.second.mp
        ap_before = self.second.action_point
        blocked = self.second.resolve_skill_component(
            other_skill.skill_id,
            "deploy",
        )
        field_result = blocked["results"][0]
        self.assertFalse(field_result["created"])
        self.assertEqual(field_result["reason"], "center_occupied")
        self.assertEqual(self.second.mp, mp_before)
        self.assertEqual(self.second.action_point, ap_before - 1)

    def test_continuous_effect_is_added_and_removed_with_range(self):
        effect = {
            "modifier_id": "field_visibility",
            "effect_type": "visibility_bonus",
            "application_mode": "continuous",
            "effect_target": {
                "scope": "characters_in_field",
                "relation": "all",
            },
            "effect_data": {"value": 1},
        }
        skill = self.first.create_personal_skill(field_skill_definition(
            "barrier_skill",
            "barrier",
            effects=[effect],
        ))
        self.first.resolve_skill_component(skill.skill_id, "deploy")
        self.assertEqual(self.first.visibility, 1)
        self.first.position = self.other
        self.game.refresh_fields()
        self.assertEqual(self.first.visibility, 0)

    def test_maintenance_starts_after_creation_turn(self):
        skill = self.first.create_personal_skill(field_skill_definition(
            "maintained_barrier",
            "maintained",
            maintenance={"resource": "mp", "value": 15},
        ))
        self.game.turn_manager.turn = 1
        self.first.current_global_turn = 1
        self.first.resolve_skill_component(skill.skill_id, "deploy")
        after_creation = self.first.mp
        self.game.field_manager.end_turn(1)
        self.assertEqual(self.first.mp, after_creation)
        self.game.field_manager.end_turn(2)
        self.assertEqual(self.first.mp, after_creation - 15)

    def test_building_location_requirements(self):
        from game.skill.field_runtime import FieldEffect

        skill = self.first.create_personal_skill(field_skill_definition(
            "requirements_skill",
            "requirements",
        ))
        high_level_definition = {
            "field_id": "high_level_required",
            "field_type": "workshop",
            "center": self.upper,
            "center_target": {
                "requirements": ["building_with_high_level"],
            },
            "effects": [],
        }
        field = FieldEffect(
            high_level_definition,
            self.first,
            skill,
        )
        self.assertTrue(field.validate_location_requirements())

        ordinary_building = Location("House", is_building=True)
        high_level_definition["center"] = ordinary_building
        no_upper = FieldEffect(
            high_level_definition,
            self.first,
            skill,
        )
        self.assertFalse(no_upper.validate_location_requirements())

        building_definition = {
            "field_id": "building_required",
            "field_type": "bounded_field",
            "center": ordinary_building,
            "center_target": {
                "requirements": ["building_only"],
            },
            "effects": [],
        }
        building_field = FieldEffect(
            building_definition,
            self.first,
            skill,
        )
        self.assertTrue(building_field.validate_location_requirements())
        building_definition["center"] = self.other
        outside = FieldEffect(
            building_definition,
            self.first,
            skill,
        )
        self.assertFalse(outside.validate_location_requirements())


if __name__ == "__main__":
    unittest.main()
