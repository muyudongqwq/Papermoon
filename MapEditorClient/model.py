"""Serializable editor document and conversion to the game map model."""

import json
import math
from dataclasses import dataclass
from pathlib import Path

from game.map.map import Location, Map

MAP_FORMAT = "papermoon_map"
MAP_FORMAT_VERSION = 1


def _nonempty_string(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}必须是非空字符串")
    return value.strip()


def _number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field}必须是有限数字")
    return float(value)


def _boolean(value, field):
    if not isinstance(value, bool):
        raise ValueError(f"{field}必须是布尔值")
    return value


@dataclass
class LocationRecord:
    location_id: str
    name: str
    x: float
    y: float
    is_building: bool = False
    high_level: bool = False
    is_port: bool = False

    def to_dict(self):
        return {
            "location_id": self.location_id,
            "name": self.name,
            "position": {"x": self.x, "y": self.y},
            "is_building": self.is_building,
            "high_level": self.high_level,
            "is_port": self.is_port,
        }


@dataclass
class RoadRecord:
    road_id: str
    location_ids: list[str]

    def to_dict(self):
        return {"road_id": self.road_id, "location_ids": list(self.location_ids)}


class MapDocument:
    """Editable map data with stable IDs independent from display names."""

    def __init__(self):
        self.locations: dict[str, LocationRecord] = {}
        self.roads: dict[str, RoadRecord] = {}
        self._location_counter = 1
        self._road_counter = 1

    @property
    def is_empty(self):
        return not self.locations and not self.roads

    def _next_id(self, prefix, collection, counter_name):
        counter = getattr(self, counter_name)
        while f"{prefix}_{counter}" in collection:
            counter += 1
        setattr(self, counter_name, counter + 1)
        return f"{prefix}_{counter}"

    def add_location(
        self,
        name,
        x=0.0,
        y=0.0,
        *,
        is_building=False,
        high_level=False,
        is_port=False,
        location_id=None,
    ):
        name = _nonempty_string(name, "地点名称")
        if any(record.name == name for record in self.locations.values()):
            raise ValueError(f"地点名称重复：{name}")
        location_id = location_id or self._next_id("location", self.locations, "_location_counter")
        location_id = _nonempty_string(location_id, "location_id")
        if location_id in self.locations:
            raise ValueError(f"location_id重复：{location_id}")
        is_building = _boolean(is_building, "is_building")
        high_level = _boolean(high_level, "high_level")
        is_port = _boolean(is_port, "is_port")
        if is_port and (is_building or high_level):
            raise ValueError("码头不能同时是建筑或拥有高层")
        record = LocationRecord(
            location_id,
            name,
            _number(x, "position.x"),
            _number(y, "position.y"),
            is_building,
            high_level,
            is_port,
        )
        self.locations[location_id] = record
        return record

    def rename_location(self, location_id, name):
        record = self.locations[location_id]
        name = _nonempty_string(name, "地点名称")
        if any(other.location_id != location_id and other.name == name for other in self.locations.values()):
            raise ValueError(f"地点名称重复：{name}")
        record.name = name
        return record

    def add_road(self, location_ids, *, road_id=None):
        location_ids = list(location_ids)
        if len(location_ids) < 2:
            raise ValueError("道路至少需要连接两个地点")
        if len(set(location_ids)) != len(location_ids):
            raise ValueError("同一地点不能在一条道路中重复出现")
        missing = [location_id for location_id in location_ids if location_id not in self.locations]
        if missing:
            raise ValueError(f"道路引用了不存在的地点：{', '.join(missing)}")
        selected = frozenset(location_ids)
        if any(frozenset(road.location_ids) == selected for road in self.roads.values()):
            raise ValueError("这些地点之间已经存在相同道路")
        road_id = road_id or self._next_id("road", self.roads, "_road_counter")
        road_id = _nonempty_string(road_id, "road_id")
        if road_id in self.roads:
            raise ValueError(f"road_id重复：{road_id}")
        record = RoadRecord(road_id, location_ids)
        self.roads[road_id] = record
        return record

    def delete_road(self, road_id):
        return self.roads.pop(road_id, None)

    def delete_location(self, location_id):
        record = self.locations.pop(location_id, None)
        if record is None:
            return None
        for road_id in [road_id for road_id, road in self.roads.items() if location_id in road.location_ids]:
            self.roads.pop(road_id)
        return record

    def road_name(self, road):
        return " ↔ ".join(self.locations[location_id].name for location_id in road.location_ids)

    def to_dict(self):
        return {
            "format": MAP_FORMAT,
            "format_version": MAP_FORMAT_VERSION,
            "locations": [record.to_dict() for record in self.locations.values()],
            "roads": [record.to_dict() for record in self.roads.values()],
        }

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError("地图文件根节点必须是对象")
        if data.get("format") != MAP_FORMAT:
            raise ValueError("不是Papermoon地图文件")
        if data.get("format_version") != MAP_FORMAT_VERSION:
            raise ValueError(f"不支持的地图格式版本：{data.get('format_version')}")
        locations = data.get("locations")
        roads = data.get("roads")
        if not isinstance(locations, list) or not isinstance(roads, list):
            raise ValueError("locations和roads必须是列表")
        document = cls()
        for index, entry in enumerate(locations):
            if not isinstance(entry, dict) or not isinstance(entry.get("position"), dict):
                raise ValueError(f"locations[{index}]格式错误")
            position = entry["position"]
            document.add_location(
                entry.get("name"),
                position.get("x"),
                position.get("y"),
                is_building=entry.get("is_building", False),
                high_level=entry.get("high_level", False),
                is_port=entry.get("is_port", False),
                location_id=entry.get("location_id"),
            )
        for index, entry in enumerate(roads):
            if not isinstance(entry, dict) or not isinstance(entry.get("location_ids"), list):
                raise ValueError(f"roads[{index}]格式错误")
            document.add_road(entry["location_ids"], road_id=entry.get("road_id"))
        return document

    def to_game_map(self):
        """Create the engine's canonical Map without editor-only coordinates."""
        game_map = Map()
        runtime_locations = {}
        for record in self.locations.values():
            location = Location(
                record.name,
                high_level=record.high_level,
                is_building=record.is_building,
                is_port=record.is_port,
            )
            game_map.add_location(location)
            runtime_locations[record.location_id] = location
        for road in self.roads.values():
            game_map.add_road(*(runtime_locations[location_id] for location_id in road.location_ids))
        return game_map


def load_map_document(path):
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"地图JSON格式错误：第{error.lineno}行第{error.colno}列") from error
    return MapDocument.from_dict(data)


def save_map_document(document, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(document.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path

