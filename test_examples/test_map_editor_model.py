import json
import tempfile
import unittest
from pathlib import Path

from MapEditorClient.model import MapDocument, load_map_document, save_map_document


class MapEditorModelTests(unittest.TestCase):
    def test_round_trip_and_game_map_conversion_preserve_branch_road(self):
        document = MapDocument()
        a = document.add_location("A", 10, 20, is_building=True, high_level=True)
        b = document.add_location("B", 100, 20)
        c = document.add_location("C", 50, 100)
        document.add_road([a.location_id, b.location_id, c.location_id])

        reopened = MapDocument.from_dict(document.to_dict())
        self.assertEqual(reopened.to_dict(), document.to_dict())
        game_map = reopened.to_game_map()
        self.assertEqual(len(game_map.roads), 1)
        self.assertEqual(len(game_map.roads[0].connected_locations), 3)
        self.assertTrue(game_map.locations["A"].is_building)
        self.assertIsNotNone(game_map.locations["A"].high_level_location)

    def test_delete_location_also_deletes_connected_roads(self):
        document = MapDocument()
        a = document.add_location("A")
        b = document.add_location("B")
        document.add_road([a.location_id, b.location_id])
        document.delete_location(a.location_id)
        self.assertEqual(document.roads, {})

    def test_duplicate_names_roads_and_missing_references_are_rejected(self):
        document = MapDocument()
        a = document.add_location("A")
        b = document.add_location("B")
        with self.assertRaises(ValueError):
            document.add_location("A")
        document.add_road([a.location_id, b.location_id])
        with self.assertRaises(ValueError):
            document.add_road([b.location_id, a.location_id])
        data = document.to_dict()
        data["roads"][0]["location_ids"][0] = "missing"
        with self.assertRaises(ValueError):
            MapDocument.from_dict(data)

    def test_file_round_trip_uses_utf8_json(self):
        document = MapDocument()
        document.add_location("教会", 1.5, -2, is_building=True)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "地图.json"
            save_map_document(document, path)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["format"], "papermoon_map")
            self.assertEqual(load_map_document(path).to_dict(), document.to_dict())

    def test_port_round_trip_and_engine_conversion(self):
        document = MapDocument()
        port = document.add_location("码头", is_port=True)
        reopened = MapDocument.from_dict(document.to_dict())
        self.assertTrue(reopened.locations[port.location_id].is_port)
        self.assertTrue(reopened.to_game_map().locations["码头"].is_port)
        with self.assertRaises(ValueError):
            document.add_location("非法码头", is_port=True, is_building=True)


if __name__ == "__main__":
    unittest.main()

