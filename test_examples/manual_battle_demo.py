"""Two-character interactive battle demo.

Run from the project root with:
    python test_examples/manual_battle_demo.py
"""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from game.character.servants import Servant
from game.turn.battle import BattleManager
from game.turn.decision import TerminalDecisionProvider


def create_characters():
    saber = Servant(
        name="Saber",
        strength=10,
        endurance=5,
        flexibility=4,
        magic=3,
        fortune=3,
        servant_class="Saber",
        noble="A",
    )

    archer = Servant(
        name="Archer",
        strength=3,
        endurance=3,
        flexibility=3,
        magic=3,
        fortune=2,
        servant_class="Archer",
        noble="A",
    )

    return saber, archer


def show_battle_status(characters):
    print()
    print("=" * 40)
    print("当前战斗状态")
    for character in characters:
        print(
            f"{character.name} | "
            f"HP={character.hp}/{character.hpmax} | "
            f"攻击阶段={character.attack_phase_count} | "
            f"待防御攻击={len(character.pending_attacks)} | "
            f"状态={character.status_flags}"
        )
    print("=" * 40)


def main():
    saber, archer = create_characters()
    characters = [saber, archer]

    battle = BattleManager(characters)
    battle.start_battle()

    print("双人手动战斗演示开始")
    print("行动顺序：", " → ".join(character.name for character in battle.current_order))
    print("可以输入选项编号，也可以输入显示出的中文名称、英文指令或角色名。")

    show_battle_status(characters)
    battle.run_battle_turn(TerminalDecisionProvider())
    show_battle_status(characters)

    print("本次演示已完成一个战斗轮。")
    print("最后一名角色产生的攻击会留在目标的待防御攻击中，等待下一轮防御阶段结算。")


if __name__ == "__main__":
    main()
