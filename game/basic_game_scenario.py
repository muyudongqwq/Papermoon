"""两组Master–Servant的最小可玩测试场景。"""

from game.character.masters import Master
from game.character.servants import Servant
from game.game_manager import GameManager
from game.map.map import Location, Map


def create_basic_game_scenario(grail_location_name="商业区B"):
    game_map = Map()
    residential_a = Location("住宅区A", is_building=True)
    commercial_b = Location("商业区B")
    church_c = Location("教会C", is_building=True)

    for location in (residential_a, commercial_b, church_c):
        game_map.add_location(location)
    game_map.add_road(residential_a, commercial_b)
    game_map.add_road(commercial_b, church_c)

    locations = {
        residential_a.name: residential_a,
        commercial_b.name: commercial_b,
        church_c.name: church_c,
    }
    if grail_location_name not in locations:
        raise ValueError(f"未知的圣杯出现地点：{grail_location_name}")

    saber_master = Master(
        name="Saber的御主",
        strength=3,     # C
        endurance=3,    # C
        flexibility=3,  # C
        magic=3,        # C
        fortune=5,      # A
        talent="C",
        command_spell=3,
    )
    archer_master = Master(
        name="Archer的御主",
        strength=3,     # C
        endurance=3,    # C
        flexibility=4,  # B
        magic=3,        # C
        fortune=3,      # C
        talent="C",
        command_spell=3,
    )

    saber = Servant(
        name="Saber",
        strength=5,     # A
        endurance=5,    # A
        flexibility=5,  # A
        magic=5,        # A
        fortune=5,      # A
        servant_class="Saber",
        noble="A",
    )
    archer = Servant(
        name="Archer",
        strength=5,     # A
        endurance=5,    # A
        flexibility=5,  # A
        magic=5,        # A
        fortune=4,      # B
        servant_class="Archer",
        noble="A",
    )

    saber_master.add_servant(saber)
    archer_master.add_servant(archer)

    saber_master.position = residential_a
    saber.position = residential_a
    archer_master.position = church_c
    archer.position = church_c

    characters = [saber_master, saber, archer_master, archer]
    game = GameManager(
        characters=characters,
        player_characters=characters,
        grail_location=locations[grail_location_name],
        grail_appearance_deaths=1,
        grail_ready_deaths=1,
    )
    # 保留地图与地点引用，便于手动演示和断言场景状态。
    game.game_map = game_map
    game.locations = locations
    return game
