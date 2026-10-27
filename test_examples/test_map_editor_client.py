import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from MapEditorClient.model import load_map_document, save_map_document
from MapEditorClient.window import MapEditorWindow


class MapEditorClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MapEditorWindow()

    def tearDown(self):
        self.window.dirty = False
        self.window.close()
        self.application.processEvents()

    def test_add_connect_select_and_delete(self):
        a = self.window.add_location("A", QPointF(0, 0), is_building=True)
        b = self.window.add_location("B", QPointF(200, 0))
        road = self.window.connect_location_ids([a.location_id, b.location_id])
        self.assertIn(road.road_id, self.window.road_items)
        self.window._apply_selection([f"road:{road.road_id}"])
        self.assertTrue(self.window.ui.roadPropertiesGroup.isVisibleTo(self.window))
        self.assertEqual(self.window.ui.roadConnectionsList.count(), 2)
        self.window.delete_keys([f"location:{a.location_id}"])
        self.assertNotIn(a.location_id, self.window.document.locations)
        self.assertEqual(self.window.document.roads, {})

    def test_location_properties_update_document_and_graphics(self):
        record = self.window.add_location("A", QPointF(10, 20))
        self.window._apply_selection([f"location:{record.location_id}"])
        self.window.ui.nameEdit.setText("住宅区")
        self.window._rename_selected_location()
        self.window.ui.buildingCheck.setChecked(True)
        self.window.ui.highLevelCheck.setChecked(True)
        self.assertEqual(record.name, "住宅区")
        self.assertTrue(record.is_building)
        self.assertTrue(record.high_level)
        self.window.ui.portCheck.setChecked(True)
        self.assertTrue(record.is_port)
        self.assertFalse(record.is_building)
        self.assertFalse(record.high_level)

    def test_saved_document_can_be_opened_in_new_window(self):
        self.window.add_location("A", QPointF(0, 0))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "map.json"
            save_map_document(self.window.document, path)
            other = MapEditorWindow()
            try:
                self.assertTrue(other.open_path(path))
                self.assertEqual(load_map_document(path).to_dict(), other.document.to_dict())
                self.assertFalse(other.dirty)
            finally:
                other.close()


if __name__ == "__main__":
    unittest.main()

