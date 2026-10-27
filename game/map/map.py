from collections import deque


HIGH_LEVEL_NAME_SUFFIX = "（高层）"


def get_nodes_within_distance(start, max_distance):
    """Return every map node reachable with at most max_distance movement."""
    if start is None:
        return set()
    if max_distance < 0:
        raise ValueError("视野距离不能小于0")

    visited = {start}
    queue = deque([(start, 0)])

    while queue:
        current, distance = queue.popleft()
        if distance >= max_distance:
            continue

        for connected in current.connected_locations:
            if connected in visited:
                continue
            visited.add(connected)
            queue.append((connected, distance + 1))

    return visited


def get_distance(start, target, max_distance=None):
    """Return movement cost between two nodes, or None when unreachable."""
    if start is None or target is None:
        return None
    if start is target:
        return 0
    if max_distance is not None and max_distance < 0:
        return None

    visited = {start}
    queue = deque([(start, 0)])

    while queue:
        current, distance = queue.popleft()
        if max_distance is not None and distance >= max_distance:
            continue

        for connected in current.connected_locations:
            if connected in visited:
                continue
            next_distance = distance + 1
            if connected is target:
                return next_distance
            visited.add(connected)
            queue.append((connected, next_distance))

    return None


def get_area_root(position):
    """Return the ground-level Location that owns a map position's area."""
    if position is None:
        return None
    return getattr(position, "area_root", position)


def is_same_area(position1, position2):
    """Whether two map positions belong to the same location-wide area."""
    if position1 is None or position2 is None:
        return False
    return get_area_root(position1) is get_area_root(position2)


def get_area_positions(position):
    """Return every movement node covered by a location-wide effect."""
    root = get_area_root(position)
    if root is None:
        return []
    return root.get_area_positions()


def get_area_occupants(position):
    """Return all characters on the ground and high level of one location."""
    occupants = []
    for area_position in get_area_positions(position):
        for character in area_position.occupants:
            if character not in occupants:
                occupants.append(character)
    return occupants


class Location:
    def __init__(
        self,
        name,
        high_level=False,
        is_building=False,
        is_port=False,
        _area_root=None,
    ):
        if is_port and (is_building or high_level or _area_root is not None):
            raise ValueError("码头不能是建筑、拥有高层或作为高层地点")
        self.name = name
        self.high_level = bool(high_level)
        self.is_building = is_building
        self.is_port = bool(is_port)
        self.is_boat = False
#保存了地点的名称和是否是建筑，是否拥有高层
        self.connected_locations = []
        self.status = set()
        self.occupants = []
        self.field_effects = []
        self.is_high_level = _area_root is not None
        self.area_root = self if _area_root is None else _area_root
        self.high_level_location = None

        if self.high_level and not self.is_high_level:
            upper_level = Location(
                f"{name}{HIGH_LEVEL_NAME_SUFFIX}",
                high_level=False,
                is_building=is_building,
                is_port=False,
                _area_root=self,
            )
            self.high_level_location = upper_level
            self.add_connection(upper_level)
            upper_level.add_connection(self)

    def add_connection(self, location):
#添加相邻地点
        if location not in self.connected_locations:
            self.connected_locations.append(location)

    def get_area_positions(self):
        root = self.area_root
        positions = [root]
        if root.high_level_location is not None:
            positions.append(root.high_level_location)
        return positions

    def get_area_occupants(self):
        return get_area_occupants(self)

    def is_same_area(self, other):
        return is_same_area(self, other)
#增加和移除状态
    def add_status(self, status):
        self.status.add(status)
    def remove_status(self, status):
        if status in self.status: self.status.remove(status)
    def has_status(self, status):
        return status in self.status

#在人物卡中展示人物当前位置，以及是否存在高层
    def show_status(self):
        print(f"地点:{self.name}")

        if self.is_high_level:
            print("类型:高层地点")
            print(f"所属地点:{self.area_root.name}")
        elif self.high_level:
            print("类型:包含高层")

        for location in self.connected_locations:
            print(f"- {location.name}")

class Road:
    def __init__(self, *locations):
        if len(locations) < 2:
            raise ValueError("道路至少需要连接两个地点")
        if len({id(location) for location in locations}) != len(locations):
            raise ValueError("同一地点不能在一条道路中重复出现")

        # 保留前两个字段，兼容已有的双向道路代码。
        self.location1 = locations[0]
        self.location2 = locations[1]
        self.connected_locations = []

        self.is_building = False
        self.status = set()
        self.occupants = []
        self.field_effects = []
        self.area_root = self

        for location in locations:
            self.add_connection(location)

    def refresh_name(self):
        location_names = "-".join(
            location.name
            for location in self.connected_locations
        )
        self.name = f"道路:{location_names}"

    def add_connection(self, location):
        if location in self.connected_locations:
            return False

        self.connected_locations.append(location)
        location.add_connection(self)
        self.refresh_name()
        return True
#道路和地点会建立双向连接，因此可以继续给已有道路增加岔路地点
    def add_status(self, status):
        self.status.add(status)
    def remove_status(self, status):
        if status in self.status: self.status.remove(status)
    def has_status(self, status):
        return status in self.status
    def show_status(self):
        print(
            "道路:"
            + "←→".join(
                location.name
                for location in self.connected_locations
            )
        )

    def get_area_positions(self):
        return [self]

    def get_area_occupants(self):
        return list(self.occupants)

    def is_same_area(self, other):
        return self is other
#上面只是在给路加东西，以及展示路上到底有什么
    def connects(self, *locations):
        if len(locations) < 2:
            return False
        return all(
            location in self.connected_locations
            for location in locations
        )
#排除重复道路


class Map:
    def __init__(self):
        self.locations = {}
        self.roads = []

    def add_location(self, location):
        self.locations[location.name]= location
        if location.high_level_location is not None:
            high_level = location.high_level_location
            self.locations[high_level.name] = high_level

    def add_road(self, *locations):
       if len(locations) < 2:
          raise ValueError("道路至少需要连接两个地点")

       existing_road = self.get_road(*locations)
       if existing_road is not None:
          return existing_road

       road = Road(*locations)
       self.roads.append(road)
       return road

    def get_road(self, *locations):
        for road in self.roads:
            if road.connects(*locations):
                return road
        return None

    def has_road(self, *locations):
        return self.get_road(*locations) is not None
        return False

