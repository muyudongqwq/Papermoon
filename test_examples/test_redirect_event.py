import unittest

from game.character.masters import Master
from game.game.game_manager import GameManager
from game.map.map import Location
from game.skill.effect_validation import validate_effect_definition
from game.skill.event_runtime import GameEvent
from game.skill.redirect_runtime import resolve_redirect_event
from game.turn.damage import AttackProfile, DamageEvent, DamageResolver
from game.turn.decision import ScriptedDecisionProvider
from game.turn.defense import DefenseResolver


def make_master(name):
    return Master(name, 3, 3, 3, 3, 3, "C", 3)


class RedirectEventTests(unittest.TestCase):
    def setUp(self):
        self.location = Location("Arena")
        self.attacker = make_master("Attacker")
        self.first = make_master("First")
        self.second = make_master("Second")
        self.redirector = make_master("Redirector")
        for character in (
            self.attacker,
            self.first,
            self.second,
            self.redirector,
        ):
            character.position = self.location
        self.game = GameManager(
            [self.attacker, self.first, self.second, self.redirector],
            self.location,
        )
        self.game.start_game()

    @staticmethod
    def effect(redirect_type, new_target="self"):
        return {
            "effect_type": "redirect_event",
            "effect_data": {
                "redirect_type": redirect_type,
                "new_target": new_target,
            },
        }

    def test_schema_accepts_only_attack_or_damage(self):
        validate_effect_definition(self.effect("attack"), component_type="react")
        validate_effect_definition(self.effect("damage"), component_type="react")
        invalid = self.effect("status")
        with self.assertRaises(ValueError):
            validate_effect_definition(invalid, component_type="react")

    def test_range_attack_is_rebuilt_as_one_redirected_group(self):
        profile = AttackProfile(
            source=self.attacker,
            value=40,
            damage_type="physical",
            attack_roll=27,
            damage_segments=[20, 20],
            target_type="selectable_character",
            target_rules={"minimum": 1, "maximum": 2, "must_be_alive": True},
        )
        old_attacks = [
            profile.assign_target(self.first),
            profile.assign_target(self.second),
        ]
        self.first.pending_attacks.append(old_attacks[0])
        self.second.pending_attacks.append(old_attacks[1])
        event = GameEvent(
            "before_attack_defense",
            timing="before",
            actor=self.attacker,
            source=old_attacks[0],
            target=self.first,
            payload={"attack_event": old_attacks[0]},
        )

        result = resolve_redirect_event(
            self.effect("attack", "event_actor"),
            self.redirector,
            None,
            actor=self.redirector,
            event=event,
            redirect_targets=[self.attacker, self.first],
        )

        self.assertTrue(event.cancelled)
        self.assertTrue(all(attack.resolved for attack in old_attacks))
        self.assertNotIn(old_attacks[0], self.first.pending_attacks)
        self.assertNotIn(old_attacks[1], self.second.pending_attacks)
        new_attacks = result["attacks"]
        self.assertEqual(len(new_attacks), 2)
        self.assertTrue(all(attack.source is self.redirector for attack in new_attacks))
        self.assertEqual({attack.attack_roll for attack in new_attacks}, {27})
        self.assertTrue(all(attack.damage_segments == [20, 20] for attack in new_attacks))
        self.assertEqual(
            {attack.attack_group_id for attack in new_attacks},
            {profile.attack_group_id},
        )

    def test_react_component_redirects_before_defense_starts(self):
        self.redirector.create_personal_skill({
            "skill_id": "test_reflect",
            "name": "反射",
            "rank": "C",
            "components": [{
                "component_id": "reflect",
                "type": "react",
                "target": "self",
                "trigger": {
                    "event_type": "before_attack_defense",
                    "timing": "before",
                },
                "effects": [self.effect("attack", "event_actor")],
            }],
        })
        profile = AttackProfile(
            source=self.attacker,
            value=20,
            damage_type="physical",
            attack_roll=20,
            target_type="selectable_character",
            target_rules={"must_be_alive": True, "exclude_self": True},
        )
        attack = profile.assign_target(self.first)
        self.first.pending_attacks.append(attack)

        result = DefenseResolver().resolve_attack(
            self.first,
            attack,
            "block",
            ScriptedDecisionProvider(["反射"]),
        )

        self.assertTrue(result["redirected"])
        self.assertFalse(attack.defense_roll_started)
        redirected = self.attacker.pending_attacks[-1]
        self.assertIs(redirected.source, self.redirector)
        self.assertIs(redirected.target, self.attacker)

    def test_damage_redirect_recalculates_against_new_target(self):
        damage = DamageEvent(
            source=self.attacker,
            target=self.first,
            value=30,
            damage_type="physical",
            target_type="selectable_character",
            target_rules={"must_be_alive": True},
        )
        event = GameEvent(
            "before_damage",
            timing="before",
            actor=self.attacker,
            source=damage,
            target=self.first,
            value=30,
            payload={"damage_event": damage},
        )

        result = resolve_redirect_event(
            self.effect("damage", "self"),
            self.redirector,
            None,
            actor=self.redirector,
            event=event,
        )

        self.assertIs(result["target"], self.redirector)
        self.assertIs(damage.target, self.redirector)
        self.assertIs(event.target, self.redirector)
        self.assertEqual(event.value, DamageResolver().calculate(damage))

    def test_invalid_later_redirect_keeps_last_legal_target(self):
        damage = DamageEvent(
            source=self.attacker,
            target=self.first,
            value=30,
            damage_type="physical",
            target_type="selectable_character",
            target_rules={"must_be_alive": True},
        )
        event = GameEvent(
            "before_damage",
            timing="before",
            actor=self.attacker,
            source=damage,
            target=self.first,
            value=30,
            payload={"damage_event": damage},
        )
        resolve_redirect_event(
            self.effect("damage", "self"),
            self.redirector,
            None,
            actor=self.redirector,
            event=event,
        )
        self.second.die()

        skipped = resolve_redirect_event(
            self.effect("damage", "selected_target"),
            self.second,
            None,
            actor=self.redirector,
            event=event,
        )

        self.assertTrue(skipped["skipped"])
        self.assertIs(damage.target, self.redirector)


if __name__ == "__main__":
    unittest.main()
