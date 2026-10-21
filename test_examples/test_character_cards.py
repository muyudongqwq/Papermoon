"""Factory contracts; synthetic Servant contents are not recorded game cards."""

from copy import deepcopy
from contextlib import ExitStack
import json
import unittest
from unittest.mock import patch

from game.character import (
    CHARACTER_CARD_DATA,
    create_character_from_card,
    get_character_card_definition,
    list_character_cards,
    validate_character_card_catalog,
    validate_character_card_definition,
)
from game.character.card_factory import create_master_test_0
from game.character.masters import Master
from game.character.servants import Servant
from game.game_loop import GameLoop
from game.game_manager import GameManager
from game.map.map import Location, Road
from game.skill.content_registry import CONTENT_CATALOGS
from game.turn.decision import ScriptedDecisionProvider


def servant_card():
    return {
        "card_id": "fixture_servant",
        "character_type": "servant",
        "name": "Fixture",
        "attributes": {"strength": 3, "endurance": 4, "flexibility": 3,
                       "magic": {"value": 4, "plus": 1}, "fortune": 2},
        "servant_class": "Saber",
        "noble": {"rank": "A", "plus": 1},
        "class_skills": [{"name": "对魔力", "rank": "B"}],
        "personal_skills": ["fixture:passive"],
        "basic_magics": ["healing"],
        "noble_phantasms": ["fixture:blade"],
    }


def noble_definition(skill_id="fixture:blade"):
    return {
        "skill_id": skill_id,
        "name": "Fixture blade",
        "noble_phantasm_type": "physical",
        "range_type": "anti_unit",
        "components": [{
            "component_id": "release", "type": "active", "target": "selectable_enemy",
            "effects": [{"effect_type": "create_attack_event", "effect_data": {"damage_value": 60}}],
        }],
    }


class CharacterCardTests(unittest.TestCase):
    def setUp(self):
        self.contexts = ExitStack()
        self.addCleanup(self.contexts.close)
        self.card = servant_card()
        self.contexts.enter_context(patch.dict(CHARACTER_CARD_DATA, {self.card["card_id"]: self.card}))
        self.contexts.enter_context(patch.dict(CONTENT_CATALOGS["personal_skill"], {
            "fixture:passive": {
                "skill_id": "fixture:passive", "name": "Fixture passive", "rank": "C",
                "components": [{
                    "component_id": "passive", "type": "passive", "target": "self",
                    "effects": [{"effect_type": "numeric_attribute_bonus", "effect_data": {
                        "effect_target": "dice_bonus", "value": 2,
                    }}],
                }],
            },
        }))
        self.contexts.enter_context(patch.dict(CONTENT_CATALOGS["noble_phantasm"], {
            "fixture:blade": noble_definition(),
        }))

    def test_catalog_validation_and_type_filter_do_not_instantiate_cards(self):
        original = deepcopy(CHARACTER_CARD_DATA)
        with patch("game.character.card_factory.Master", side_effect=AssertionError("created Master")):
            self.assertIn("master_test_0", validate_character_card_catalog())
            self.assertIn("master_test_0", list_character_cards(character_type="master"))
        self.assertIn("fixture_servant", list_character_cards(character_type="servant"))
        self.assertEqual(CHARACTER_CARD_DATA, original)
        json.dumps(CHARACTER_CARD_DATA, ensure_ascii=False)

    def test_migrated_master_matches_compatibility_entry(self):
        generic = create_character_from_card("master_test_0")
        legacy = create_master_test_0("Renamed")
        self.assertIsInstance(generic, Master)
        self.assertEqual(generic.card_id, legacy.card_id)
        self.assertNotEqual(generic.character_id, legacy.character_id)
        self.assertEqual(generic.name, "莱昂纳多·达·芬奇")
        self.assertEqual(legacy.name, "Renamed")
        self.assertEqual((generic.magic.value, generic.magic.plus_capacity), (5, 2))
        for field in ("personal_skills", "magic_skill"):
            self.assertEqual([skill.skill_id for skill in getattr(generic, field)],
                             [skill.skill_id for skill in getattr(legacy, field)])

    def test_instances_and_definition_copies_do_not_share_runtime_state(self):
        definition = get_character_card_definition("master_test_0")
        definition["attributes"]["magic"]["value"] = 0
        definition["personal_skills"].clear()
        first = create_character_from_card("master_test_0")
        second = create_character_from_card("master_test_0")
        first.magic.value = 1
        first.personal_skills[0].definitions[0]["trigger"]["priority"] = -999
        first.personal_skills[0].expired_component_ids.add("prevent_damage_with_mp")
        first.magic_skill.clear()
        self.assertEqual(second.magic.value, 5)
        self.assertEqual(second.personal_skills[0].definitions[0]["trigger"]["priority"], 100)
        self.assertEqual(second.personal_skills[0].expired_component_ids, set())
        self.assertEqual(len(second.magic_skill), 2)
        self.assertEqual(get_character_card_definition("master_test_0")["attributes"]["magic"]["value"], 5)

    def test_servant_loads_all_content_kinds_and_links_through_existing_rules(self):
        owner = Master("Owner", 3, 3, 3, 3, 3, "C", 3)
        a, b = Location("A"), Location("B")
        road = Road(a, b)
        actor = create_character_from_card("fixture_servant", name="Chosen", position=road, master=owner)
        self.assertIsInstance(actor, Servant)
        self.assertEqual(actor.card_id, "fixture_servant")
        self.assertEqual(actor.name, "Chosen")
        self.assertIs(actor.master, owner)
        self.assertIn(actor, owner.servants)
        self.assertIn(actor, road.occupants)
        self.assertTrue(owner.is_ally(actor))
        self.assertEqual(actor.magic_resistance, 0.2)
        self.assertEqual(actor.dice_bonus, 2)
        self.assertEqual([skill.skill_id for skill in actor.class_skills], ["class:对魔力"])
        self.assertEqual([skill.skill_id for skill in actor.magic_skill], ["basic_magic:healing"])
        self.assertEqual(actor.noble_phantasms[0].source_type, "noble_phantasm")
        self.assertEqual(actor.noble_phantasms[0].rank.rank, "A")
        self.assertEqual(actor.noble.plus, 1)
        self.assertIsNone(actor.game_manager)
        owner_mp, actor_mp = owner.mp, actor.mp
        self.assertIsNotNone(actor.pay_mp_with_ledger(actor_mp + 7))
        self.assertEqual(actor.mp, 0)
        self.assertEqual(owner.mp, owner_mp - 7)

    def test_noble_capacity_reuses_two_or_three_rule_and_rejects_before_placement(self):
        extra = {f"fixture:blade{i}": noble_definition(f"fixture:blade{i}") for i in range(4)}
        with patch.dict(CONTENT_CATALOGS["noble_phantasm"], extra):
            for plus, count, valid in ((0, 2, True), (0, 3, False), (1, 3, True), (1, 4, False)):
                with self.subTest(plus=plus, count=count):
                    self.card["noble"] = {"rank": "A", "plus": plus}
                    self.card["noble_phantasms"] = list(extra)[:count]
                    location = Location("A")
                    if valid:
                        actor = create_character_from_card("fixture_servant", position=location)
                        self.assertEqual(len(actor.noble_phantasms), count)
                    else:
                        with self.assertRaisesRegex(ValueError, "超过上限"):
                            create_character_from_card("fixture_servant", position=location)
                        self.assertEqual(location.occupants, [])

    def test_missing_unknown_and_duplicate_content_is_rejected(self):
        for field, entries, message in (
            ("personal_skills", ["missing"], "未知"),
            ("basic_magics", ["missing"], "未知"),
            ("noble_phantasms", ["missing"], "未知"),
            ("personal_skills", ["fixture:passive"] * 2, "重复"),
            ("class_skills", [{"name": "对魔力", "rank": "B"}] * 2, "重复"),
            ("class_skills", [{"name": "对魔力", "rank": "EX"}], "尚未定义"),
        ):
            with self.subTest(field=field, entries=entries):
                definition = servant_card()
                definition[field] = entries
                with self.assertRaisesRegex(ValueError, message):
                    validate_character_card_definition(definition)
        with patch.dict(CONTENT_CATALOGS["personal_skill"], {
            "alias": CONTENT_CATALOGS["personal_skill"]["fixture:passive"],
        }):
            definition = servant_card()
            definition["personal_skills"].append("alias")
            with self.assertRaisesRegex(ValueError, "重复skill_id"):
                validate_character_card_definition(definition)

    def test_invalid_fields_types_and_rank_values_are_rejected(self):
        cases = [
            {"character_type": "npc"}, {"card_id": "Servant_test_0"}, {"name": " "},
            {"noble": {"rank": "EX", "plus": 1}}, {"servant_class": "saber"},
            {"personal_skills": "fixture:passive"}, {"class_skills": {}},
            {"effects": []}, {"talent": "A"},
        ]
        for replacement in cases:
            with self.subTest(replacement=replacement):
                definition = servant_card()
                definition.update(replacement)
                with self.assertRaises(ValueError):
                    validate_character_card_definition(definition)
        for value in (True, -1, "A", [5, 2], {"value": 5, "plus": 3}, {"value": 5, "plus": True}):
            with self.subTest(attribute=value):
                definition = servant_card()
                definition["attributes"]["magic"] = value
                with self.assertRaises(ValueError):
                    validate_character_card_definition(definition)
        definition = servant_card()
        del definition["attributes"]["strength"]
        with self.assertRaisesRegex(ValueError, "缺少字段"):
            validate_character_card_definition(definition)
        for field, value in (("command_spell", True), ("command_spell", -1),
                             ("talent", {"rank": "A", "plus": 1})):
            definition = deepcopy(CHARACTER_CARD_DATA["master_test_0"])
            definition[field] = value
            with self.assertRaises(ValueError):
                validate_character_card_definition(definition)

    def test_wrong_catalog_key_unknown_card_and_invalid_overrides_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "未知角色卡"):
            create_character_from_card("missing_card_for_factory_test")
        with patch.dict(CHARACTER_CARD_DATA, {"wrong_key": servant_card()}):
            with self.assertRaisesRegex(ValueError, "不一致"):
                get_character_card_definition("wrong_key")
        for arguments in ({"name": ""}, {"position": "A"}, {"master": "Owner"}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                create_character_from_card("fixture_servant", **arguments)
        with self.assertRaises(ValueError):
            create_character_from_card("master_test_0", master=create_master_test_0())

    def test_failed_load_or_full_master_does_not_leave_map_or_relation_entries(self):
        owner = Master("Owner", 3, 3, 3, 3, 3, "C", 3)
        location = Location("A")
        invalid_noble = noble_definition()
        invalid_noble["components"][0]["effects"][0]["effect_data"] = {}
        with patch.dict(CONTENT_CATALOGS["noble_phantasm"], {"fixture:blade": invalid_noble}):
            with self.assertRaises(ValueError):
                create_character_from_card("fixture_servant", position=location, master=owner)
        self.assertEqual(location.occupants, [])
        self.assertEqual(owner.servants, [])
        self.assertEqual(owner.allies, set())
        self.assertEqual(owner.ally_sources, {})
        for _ in range(2):
            create_character_from_card("fixture_servant", master=owner)
        with self.assertRaisesRegex(ValueError, "上限"):
            create_character_from_card("fixture_servant", master=owner, position=location)
        self.assertEqual(location.occupants, [])
        self.assertEqual(len(owner.servants), 2)

    def test_load_time_passives_see_initial_position_and_master(self):
        component = CONTENT_CATALOGS["personal_skill"]["fixture:passive"]["components"][0]
        component["condition"] = {"position_is_building": True}
        building = Location("Workshop", is_building=True)
        self.assertEqual(create_character_from_card("fixture_servant", position=building).dice_bonus, 2)
        self.assertEqual(create_character_from_card("fixture_servant", position=Location("Roadside")).dice_bonus, 0)
        component["condition"] = {"condition_id": "master_is_none"}
        owner = create_master_test_0()
        self.assertEqual(create_character_from_card("fixture_servant", master=owner).dice_bonus, 0)
        self.assertEqual(create_character_from_card("fixture_servant").dice_bonus, 2)

    def test_migrated_card_runs_existing_global_turn_and_end_flow(self):
        location = Location("A")
        actor = create_character_from_card("master_test_0", position=location)
        game = GameManager([actor], location, maximum_turns=1)
        decisions = ScriptedDecisionProvider(["barrel_replica", "pass", "pass"])
        result = GameLoop(game, decisions).run()
        self.assertEqual(result, {"reason": "turn_limit", "winners": [], "turn": 1})
        self.assertEqual(decisions.command_index, 3)
        self.assertEqual(actor.card_id, "master_test_0")
        self.assertTrue(actor.has_status("dead"))


if __name__ == "__main__":
    unittest.main()
