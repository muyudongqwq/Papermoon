import os
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from GameMasterClient.window import GameMasterWindow
from MapEditorClient.model import MapDocument
from game.character.card_factory import create_character_from_card


class GameMasterClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def make_window(self, *, maximum_turns=2):
        window = GameMasterWindow()
        self.addCleanup(self.close_window, window)
        document = MapDocument()
        document.add_location("A", 0, 0, location_id="a")
        document.add_location("B", 240, 0, location_id="b")
        document.add_road(["a", "b"])
        window.map_document = document
        window.placement_scene.set_document(document)
        window.live_scene.set_document(document)
        actor = create_character_from_card("master_test_0", name="测试御主")
        actor._character_id = "character10"
        window.characters = [actor]
        window.rules = {
            "maximum_turns": maximum_turns,
            "grail_appearance_deaths": 2,
            "grail_ready_deaths": 2,
            "grail_location_id": "a",
        }
        window._build_runtime_map()
        window._build_placement_groups()
        for group in window.placement_groups:
            group["combo"].setCurrentIndex(1)
        return window

    @staticmethod
    def close_window(window):
        if window.session is not None and window.session.state not in window.session.TERMINAL_STATES:
            window.session.stop()
            window.session.join(2)
        window.close()

    def start_window(self, window):
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            window.start_game()
        self.wait_until(lambda: window.session.state == "ready")

    def wait_until(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.application.processEvents()
            if predicate():
                return
            time.sleep(0.005)
        self.fail("等待GUI会话状态超时")

    def finish_one_turn(self, window):
        window._poll_session()
        window.next_turn()
        while True:
            self.application.processEvents()
            window._poll_session()
            request = window.pending_decision
            if request is not None:
                if request["kind"] == "choice":
                    labels = [option["label"] for option in request["options"]]
                    window.ui.decisionOptionList.setCurrentRow(labels.index("空过") if "空过" in labels else 0)
                window.submit_decision()
            if window.session.state == "ready" and window.game_manager.turn_manager.turn == 1:
                return
            time.sleep(0.005)

    def test_designer_pages_are_connected_and_one_turn_can_run(self):
        window = self.make_window()
        self.assertEqual(window.ui.mainStack.currentWidget(), window.ui.mainMenuPage)
        self.start_window(window)
        self.finish_one_turn(window)
        self.assertEqual(window.game_manager.turn_manager.turn, 1)
        self.assertTrue(window.ui.nextTurnButton.isEnabled())
        self.assertEqual(window.ui.mainStack.currentWidget(), window.ui.gamePage)

    def test_safe_checkpoint_payload_replays_to_a_resumable_session(self):
        source = self.make_window()
        self.start_window(source)
        self.finish_one_turn(source)
        payload = source._save_payload()
        self.assertTrue(payload["resumable"])
        self.assertEqual(payload["snapshot"]["turn"], 1)
        self.assertIn("character_card", payload["catalog"])
        source.session.stop()
        source.session.join(2)

        restored = GameMasterWindow()
        self.addCleanup(self.close_window, restored)
        restored._restore_save(payload)
        self.assertEqual(restored.game_manager.turn_manager.turn, 1)
        self.assertEqual(restored.session.state, "ready")
        self.assertEqual(restored.characters[0].character_id, "character10")


if __name__ == "__main__":
    unittest.main()
