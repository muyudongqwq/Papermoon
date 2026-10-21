"""地图结构的手动检查辅助脚本。"""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from game.map.map import Map, Location, Road
from game.character.servants import Servant
from game.character.masters import Master
from game.skill.class_skill_data import CLASS_SKILL_DATA
from game.modifier.modifier import create_modifier
from game.character.character import Character
from game.action.action import Action
from game.turn.Turn import TurnManager
from game.turn.initialivemanager import InitiativeManager
def create_test_map():
    game_map = Map()
    A = Location("A")
    B = Location("B")
    C = Location("C")

    game_map.add_location(A)
    game_map.add_location(B)
    game_map.add_location(C)

    game_map.add_road(A,B)
    game_map.add_road(B,C)

    return game_map,A,B,C

def show_map(game_map):
    for name, location in game_map.locations.items():
        print("地点:", name)
        for node in location.connected_locations:
            print("->", node.name)
