"""Disclosure at movement/death event boundaries before rule caches refresh."""

import json
import unittest

from game.character.masters import Master
from game.character.servants import Servant
from game.game.game_manager import GameManager
from game.game.game_session import GameSession
from game.map.map import Location


class SessionBoundaryPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b, self.far = Location("A"), Location("B"), Location("UnseenFar")
        self.a.add_connection(self.b)
        self.b.add_connection(self.a)
        self.observer = Master("Observer", 3, 3, 3, 3, 3, "C", 3)
        self.target = Master("Target", 3, 3, 3, 3, 3, "C", 3)
        self.observer.position = self.target.position = self.a
        self.game = GameManager([self.observer, self.target], self.a)
        self.game.start_game()
        self.session = GameSession(self.game, {self.observer.character_id: "observer", self.target.character_id: "target"})
        self.game.rule_reports.subscribe(self.session._on_rule_report)
        self.addCleanup(self.game.rule_reports.unsubscribe, self.session._on_rule_report)

    def ids(self):
        return {actor["character_id"] for actor in self.session.get_snapshot("observer")["characters"]}

    def test_teleport_out_of_view_does_not_disclose_destination_before_cache_refresh(self):
        self.assertIn(self.target.character_id, self.ids())
        self.target.position = self.far
        # The normal turn cache is intentionally still stale at this event boundary.
        self.assertIn(self.target, self.observer.own_visible)
        self.assertNotIn(self.target.character_id, self.ids())
        serialized = json.dumps(self.session.get_events("observer"))
        self.assertNotIn(self.session._position_id(self.far), serialized)
        self.assertNotIn("UnseenFar", serialized)

    def test_dead_observer_cannot_continue_reading_old_visibility(self):
        self.observer.die()
        self.session._capture_views()
        self.assertEqual(self.ids(), {self.observer.character_id})
        before = len(self.session.get_events("observer"))
        self.game.rule_reports.record("test", actor=self.target, public={"change": "secret"})
        self.assertEqual(len(self.session.get_events("observer")), before)

    def test_perception_remains_current_in_range_without_mutating_rule_cache(self):
        self.observer.own_perceived.append(self.target)
        self.game.turn_manager.update_visibility()
        self.target.position = self.b
        self.assertIn(self.target.character_id, self.ids())
        self.target.position = self.far
        self.assertNotIn(self.target.character_id, self.ids())
        self.assertIn(self.target, self.observer.own_perceived)

    def test_shared_visibility_is_rechecked_when_the_shared_observer_moves_away(self):
        servant = Servant("Scout", 3, 3, 3, 3, 3, "Archer", "A")
        self.observer.add_servant(servant)
        self.observer.position = self.b
        self.game.register_character(servant, self.a)
        self.game.turn_manager.update_visibility()
        # Dynamic control is inherited, keeping this existing Session valid.
        self.session._capture_views()
        self.assertIn(self.target.character_id, self.ids())
        servant.position = self.far
        self.assertIn(self.target, self.observer.shared_visible)
        self.assertNotIn(self.target.character_id, self.ids())


if __name__ == "__main__":
    unittest.main()
