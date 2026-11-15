from copy import deepcopy
from types import SimpleNamespace
import unittest

from game.character.card_data import CHARACTER_CARD_DATA
from game.character.card_factory import create_character_from_card
from game.character.masters import Master
from game.game.game_manager import GameManager
from game.map.map import Location
from game.skill.effect_validation import validate_effect_definition
from game.turn.damage import AttackProfile, DamageResolver
from game.turn.defense import DefenseResolver
from game.turn.initialivemanager import InitiativeManager
from game.turn.roll import RollResolver, roll_d10


def traits(subject, **fields):
    return {"character_matches": {"subject": subject, **fields}}


def effect(effect_type, **data):
    return {"effect_type": effect_type, "effect_data": data}


def grant(character, skill_id, component_type, effect_data, **component_fields):
    character.create_personal_skill({
        "skill_id": skill_id, "name": skill_id, "rank": "B",
        "components": [{
            "component_id": "main", "type": component_type, "target": "self",
            "effects": [effect_data], **component_fields,
        }],
    })


class CombatTraitTests(unittest.TestCase):
    def setUp(self):
        arena = Location("Arena")
        self.attacker, self.divine, self.other = [
            Master(name, 3, 5, 3, 3, 3, "C", 3)
            for name in ("Attacker", "Divine", "Other")
        ]
        for actor in (self.attacker, self.divine, self.other):
            actor.position = arena
        self.game = GameManager([self.attacker, self.divine, self.other], arena)
        self.game.start_game()
        self.divine.tags.add("divine")

    def attack(self, target):
        return AttackProfile(
            source=self.attacker, value=100, damage_type="physical",
            attack_roll=8, skill=None,
        ).assign_target(target)

    def damage(self, target):
        return DefenseResolver().create_damage_event(target, self.attack(target))

    def grant_anti_divine(self, condition=None, **data):
        grant(self.attacker, "anti_divine", "passive", effect(
            "special_attack", special_attack_id="anti_divine",
            condition=condition or traits("event_target", tags=["divine"]), **data,
        ))

    def grant_vulnerability(self, actor):
        grant(actor, "vulnerability", "trigger",
              effect("modify_event_value", calculation="multiply", value=1.2),
              trigger={"event_type": "special_attack_hit", "timing": "before"},
              condition={"event_target_is_self": True, "special_attack_id": "anti_divine"})

    def test_special_attack_marks_actual_damage_and_allows_defender_to_modify_it(self):
        self.grant_vulnerability(self.divine)
        self.assertEqual(DamageResolver().resolve(self.damage(self.divine)), 100)
        self.divine.hp = self.divine.hpmax
        self.grant_anti_divine(multiplier=1.5)
        damage = self.damage(self.divine)
        self.assertEqual(DamageResolver().resolve(damage), 180)
        self.assertEqual(damage.special_attack_ids, ("anti_divine",))
        self.assertEqual(DamageResolver().resolve(self.damage(self.other)), 100)

    def test_special_attack_checks_live_status_and_does_not_emit_on_preview(self):
        self.grant_anti_divine(traits("event_target", tags=["divine"], statuses=["burning"]),
                              multiplier=1.5)
        damage = self.damage(self.divine)
        resolver = DamageResolver()
        self.assertEqual(resolver.calculate(damage), 100)
        grant(self.divine, "burning", "passive", effect("add_status", status_id="burning"))
        history_size = len(self.game.event_manager.history)
        self.assertEqual(resolver.calculate(damage), 150)
        self.assertEqual(len(self.game.event_manager.history), history_size)

    def test_redirect_rechecks_special_attack_before_vulnerability(self):
        self.grant_anti_divine(multiplier=1.5)
        self.grant_vulnerability(self.divine)
        grant(self.other, "take_hit", "trigger",
              effect("redirect_event", redirect_type="damage", new_target="self"),
              trigger={"event_type": "before_damage", "timing": "before"},
              condition=traits("event_target", tags=["divine"]))
        damage = self.damage(self.divine)
        original_hp = self.divine.hp
        self.assertEqual(DamageResolver().resolve(damage), 100)
        self.assertIs(damage.target, self.other)
        self.assertEqual(damage.special_attack_ids, ())
        self.assertEqual(self.divine.hp, original_hp)

    def test_incoming_attack_roll_bonus_is_per_target_even_with_a_shared_roll(self):
        grant(self.divine, "moon", "passive", effect(
            "incoming_attack_roll_bonus", value=1,
            condition=traits("event_actor", tags=["deity"]),
        ))
        attack = self.attack(self.divine)
        self.assertEqual(attack.attack_roll, 8)
        self.attacker.tags.add("deity")
        self.assertEqual(attack.attack_roll, 9)
        self.assertEqual(self.attack(self.other).attack_roll, 8)
        attack.change_target(self.other)
        self.assertEqual(attack.attack_roll, 8)

    def test_fixed_face_all_roll_types_ignores_luck_and_uses_true_name(self):
        grant(self.divine, "moon", "passive", effect(
            "fixed_die", value=1,
            condition=traits("battle_opponent", true_name="西王母"),
        ))
        self.assertEqual(roll_d10(self.divine, roller=lambda: 9), 9)
        self.other.true_name = "西王母"
        self.divine.current_battle = SimpleNamespace(participants=[self.divine, self.other])
        self.divine.in_battle = True

        class NoLuckChoice:
            def choose(self, request):
                raise AssertionError("固定骰面不应弹出幸运选项")

        for stat in ("magic_attack", "dodge", "escape", "perceive", "fortune"):
            result = RollResolver().roll(self.divine, stat, initial_die=10,
                                         decision_provider=NoLuckChoice())
            self.assertEqual((result.initial_die, result.die), (1, 1))
            self.assertFalse(result.critical_success)
        self.assertEqual(roll_d10(self.divine, roller=lambda: 9), 1)
        self.divine.current_battle.participants.remove(self.other)
        self.assertEqual(roll_d10(self.divine, roller=lambda: 9), 9)

    def test_fixed_face_initiative_tie_terminates(self):
        for actor in (self.attacker, self.divine):
            grant(actor, "fixed", "passive", effect("fixed_die", value=1))
        self.assertEqual(InitiativeManager().resolve_tie([self.attacker, self.divine]),
                         [self.attacker, self.divine])

    def test_card_uses_explicit_true_name_and_does_not_share_mutable_tags(self):
        from unittest.mock import patch

        card = deepcopy(CHARACTER_CARD_DATA["master_test_0"])
        card.update(true_name="西王母", tags=["deity"])
        with patch.dict(CHARACTER_CARD_DATA, {"master_test_0": card}):
            first = create_character_from_card("master_test_0", name="化名")
            second = create_character_from_card("master_test_0")
        self.assertEqual(first.true_name, "西王母")
        self.assertEqual(first.name, "化名")
        first.tags.add("divine")
        self.assertEqual(second.tags, {"deity"})

    def test_invalid_fixed_face_and_unconditional_special_attack_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_effect_definition(effect("fixed_die", value=11))
        with self.assertRaises(ValueError):
            validate_effect_definition(effect("special_attack", special_attack_id="x", condition={}))
