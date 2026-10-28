import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import gc
import threading
import unittest
import weakref
from unittest.mock import patch
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QPointF
from PySide6.QtWidgets import QApplication, QMessageBox
from shiboken6 import isValid

from MapEditorClient.model import load_map_document, save_map_document
from MapEditorClient.window import MapEditorWindow


class MapEditorClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MapEditorWindow()

    def tearDown(self):
        self.dispose_window(self.window)

    def dispose_window(self, window):
        if isValid(window):
            window.dirty = False
            window.close()
            if isValid(window):
                window.deleteLater()
        # processEvents() alone does not guarantee delivery of DeferredDelete
        # when tests do not run QApplication.exec(). Keep cleanup on this thread.
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.application.processEvents()

    def test_close_destroys_native_window_and_children_on_gui_thread(self):
        window = MapEditorWindow()
        self.addCleanup(self.dispose_window, window)
        window.add_location("A", QPointF(0, 0))
        scene, item = window.scene, next(iter(window.location_items.values()))
        destroyed_threads = []
        window.destroyed.connect(lambda: destroyed_threads.append(threading.get_ident()))
        window.dirty = False
        self.assertTrue(window.close())
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.application.processEvents()
        self.assertFalse(isValid(window))
        self.assertFalse(isValid(scene))
        self.assertFalse(isValid(item))
        self.assertEqual(destroyed_threads, [threading.get_ident()])

    def test_cancel_close_preserves_dirty_window_and_document(self):
        record = self.window.add_location("未保存地点", QPointF(0, 0))
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.assertFalse(self.window.close())
        self.assertTrue(isValid(self.window))
        self.assertTrue(self.window.dirty)
        self.assertIn(record.location_id, self.window.document.locations)

    def test_closed_window_waits_for_gui_deletion_during_worker_collection(self):
        window = MapEditorWindow()
        window.add_location("A", QPointF(0, 0))
        reference = weakref.ref(window)
        destroyed_threads = []
        window.destroyed.connect(lambda: destroyed_threads.append(threading.get_ident()))
        window.dirty = False
        window.close()
        del window
        worker = threading.Thread(target=gc.collect)
        worker.start()
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertIsNotNone(reference())
        self.assertTrue(isValid(reference()))
        self.assertEqual(destroyed_threads, [])
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.application.processEvents()
        self.assertEqual(destroyed_threads, [threading.get_ident()])
        self.assertTrue(reference() is None or not isValid(reference()))

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
                self.dispose_window(other)


if __name__ == "__main__":
    unittest.main()

