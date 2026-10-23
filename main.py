"""Papermoon终端版的默认启动入口。"""

from game.game.basic_game_scenario import create_basic_game_scenario
from core.terminal_game_runner import TerminalGameRunner


def main():
    game = create_basic_game_scenario()
    return TerminalGameRunner(game).run()


if __name__ == "__main__":
    main()
