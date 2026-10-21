"""Human-operated scenarios; all characters use the selected card templates."""

from game.character import create_character_from_card
from game.basic_game_scenario import create_basic_game_scenario
from game.game_manager import GameManager
from game.map.map import Location, Map
from game.turn.battle import BattleManager


def create_manual_scenario(mode="battle", *, teams=None, maximum_turns=120):
    if mode == "basic":
        game = create_basic_game_scenario()
        game.maximum_turns = maximum_turns
        return game
    if mode not in {"battle", "map"}:
        raise ValueError(f"未知测试场景：{mode}")
    teams = teams or [("master_test_0", "servant_test_0")] * 2
    if len(teams) != 2:
        raise ValueError("当前人工测试场景需要两个阵营")
    game_map = Map()
    nodes = [Location("住宅区", is_building=True), Location("中央广场", is_building=True),
             Location("教会", is_building=True)]
    for node in nodes:
        game_map.add_location(node)
    game_map.add_road(nodes[0], nodes[1])
    game_map.add_road(nodes[1], nodes[2])
    actors = []
    for index, (master_id, servant_id) in enumerate(teams):
        team = "AB"[index]
        spawn = nodes[1] if mode == "battle" else nodes[index * 2]
        master = create_character_from_card(master_id, position=spawn)
        if master.entity_type != "master":
            raise ValueError("御主位置必须使用御主卡")
        master.name = f"{team}方御主·{master.name}"
        servant = create_character_from_card(servant_id, position=spawn, master=master)
        servant.name = f"{team}方从者·{servant.name}"
        actors.extend([master, servant])
    game = GameManager(actors, nodes[1], maximum_turns=maximum_turns,
                       grail_appearance_deaths=1, grail_ready_deaths=1)
    game.game_map = game_map
    game.locations = {node.name: node for node in nodes}
    game.manual_battle_start = mode == "battle"
    return game


def start_manual_scenario(game):
    game.start_game()
    if getattr(game, "manual_battle_start", False):
        battle = BattleManager(list(game.characters))
        game.turn_manager.battles.append(battle)
        battle.start_battle()
