"""旧版完整战斗流程演示；保留为手动回归示例。"""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from game.character.servants import Servant
from game.character.masters import Master

from game.map.map import Map, Location
from game.map.movement import MovementResolver, MovementState

from game.action.action import Action
from game.action.action_resolver import ActionResolver
from game.turn.Turn import TurnManager


# ============================================================
# 地图
#
# A -- road_AB -- B -- road_BC -- C
# ============================================================

def create_full_flow_test_map():

    game_map = Map()

    A = Location("A")
    B = Location("B")
    C = Location("C")

    game_map.add_location(A)
    game_map.add_location(B)
    game_map.add_location(C)

    game_map.add_road(A, B)
    game_map.add_road(B, C)

    return game_map, A, B, C


# ============================================================
# 测试角色
# ============================================================

def create_full_flow_test_characters(A, C):

    # Saber:
    # 筋力10
    # ATK = 100
    #
    # Archer:
    # 耐久3
    # HP = 90
    #
    # Archer使用50%格挡：
    #
    # 第一次：
    # 90 - 50 = 40
    #
    # 第二次：
    # 40 - 50 = -10
    #
    # 触发濒死 → HP = 1

    saber = Servant(
        "Saber",
        10,     # strength
        5,      # endurance
        4,      # flexibility
        3,      # magic
        3,      # fortune
        "Saber",
        "A"
    )

    archer = Servant(
        "Archer",
        3,
        3,
        3,
        3,
        2,
        "Archer",
        "A"
    )

    saber_master = Master("Saber Master", 3, 3, 3, 3, 3, "C", 3)
    archer_master = Master("Archer Master", 3, 3, 3, 3, 3, "C", 3)
    saber_master.add_servant(saber)
    archer_master.add_servant(archer)

    saber.position = A
    archer.position = C


    # 当前默认格挡减伤率
    saber.block_resistance = 0.5
    archer.block_resistance = 0.5


    # ========================================================
    # 测试专用
    #
    # 这里把block设得很高，
    # 是为了保证本次集成测试中的格挡判定一定成功。
    #
    # 这样可以排除1d10随机性，
    # 专门测试战斗流程。
    #
    # 正常游戏不要这样设置。
    # ========================================================

    saber.block = 100
    archer.block = 100


    return saber, archer


# ============================================================
# 打印角色状态
# ============================================================

def show_full_status(saber, archer):

    print("-" * 60)

    print(
        f"Saber | "
        f"HP={saber.hp}/{saber.hpmax} | "
        f"AP={saber.action_point} | "
        f"攻击阶段={saber.attack_phase_count} | "
        f"位置={saber.position.name} | "
        f"in_battle={saber.in_battle} | "
        f"pending_attacks={len(saber.pending_attacks)} | "
        f"status={saber.status_flags}"
    )

    print(
        f"Archer | "
        f"HP={archer.hp}/{archer.hpmax} | "
        f"AP={archer.action_point} | "
        f"攻击阶段={archer.attack_phase_count} | "
        f"位置={archer.position.name} | "
        f"in_battle={archer.in_battle} | "
        f"pending_attacks={len(archer.pending_attacks)} | "
        f"status={archer.status_flags}"
    )

    print("-" * 60)


# ============================================================
# 全流程测试
# ============================================================

def test_complete_game_flow():

    print("\n")
    print("=" * 70)
    print("完整战斗流程测试开始")
    print("=" * 70)


    # ========================================================
    # 1. 初始化
    # ========================================================

    print("\n========== 1. 初始化 ==========\n")

    game_map, A, B, C = create_full_flow_test_map()

    saber, archer = create_full_flow_test_characters(
        A,
        C
    )

    characters = [
        saber,
        archer
    ]


    turn_manager = TurnManager()

    turn_manager.characters = characters


    # ========================================================
    # 2. 全局回合1开始
    # ========================================================

    print("\n========== 2. 全局回合1 ==========\n")

    turn_manager.start_turn()

    print(
        "当前全局回合:",
        turn_manager.turn
    )


    # TurnManager.start_turn会重置movement_point
    # 所以这里再给予本轮测试移动力

    saber.movement_point = 3
    archer.movement_point = 2


    road_AB = game_map.roads[0]
    road_BC = game_map.roads[1]


    saber_state = MovementState(
        saber,
        [
            A,
            road_AB,
            B,
            road_BC
        ]
    )


    archer_state = MovementState(
        archer,
        [
            C,
            road_BC,
            B
        ]
    )


    movement_states = [
        saber_state,
        archer_state
    ]


    # Saber敏捷更高
    initiative_order = [
        saber,
        archer
    ]


    print("开始移动")


    encounters = MovementResolver().resolve(
        movement_states,
        initiative_order,
        characters
    )


    assert encounters

    encounter = encounters[0]


    print(
        "发生相遇:",
        [
            c.name
            for c in encounter.characters
        ]
    )

    print(
        "相遇地点:",
        encounter.position.name
    )


    # 我们之前的测试：
    # 应该在road_BC相遇

    assert encounter.position is road_BC


    # ========================================================
    # 3. Saber宣战
    # ========================================================

    print("\n========== 3. Saber选择宣战 ==========\n")


    battle_choice = turn_manager.declare_battle(
        encounter,
        saber,
        archer,
    )

    # 方案1：所有知情角色都作出决定后，相遇才完成结算。
    archer_choice = turn_manager.continue_encounter(
        encounter,
        archer,
    )

    # AP1 checkpoint：在这里读取最终视野并锁定偷袭结果。
    turn_manager.execute_action_layer(1)


    print(
        "choose_battle:",
        battle_choice
    )

    print(
        "Archer choose_continue:",
        archer_choice
    )

    print(
        "resolved:",
        encounter.resolved
    )

    print(
        "pending_battle:",
        encounter.pending_battle
    )


    assert encounter.resolved is True
    assert encounter.pending_battle is True


    # 当前回合还没有真正开始Battle

    assert saber.in_battle is False
    assert archer.in_battle is False


    turn_manager.add_pending_encounter(
        encounter
    )


    print(
        "待处理战斗数量:",
        len(turn_manager.pending_encounters)
    )


    assert len(
        turn_manager.pending_encounters
    ) == 1


    # ========================================================
    # 4. 回合1结束
    # ========================================================

    print("\n========== 4. 全局回合1结束 ==========\n")

    turn_manager.end_turn()


    # ========================================================
    # 5. 全局回合2
    #
    # pending battle正式建立
    # ========================================================

    print("\n========== 5. 全局回合2 ==========\n")

    turn_manager.start_turn()


    print(
        "当前全局回合:",
        turn_manager.turn
    )


    assert len(
        turn_manager.battles
    ) == 1


    battle = turn_manager.battles[0]


    # 如果你的pending battle系统已经负责先手排序，
    # 可以删掉这里的手动赋值。
    #
    # 当前测试固定：
    # Saber → Archer

    print(
        "Battle参与者:",
        [
            c.name
            for c in battle.participants
        ]
    )


    print(
        "行动顺序:",
        [
            c.name
            for c in battle.current_order
        ]
    )


    assert saber.in_battle is True
    assert archer.in_battle is True


    show_full_status(
        saber,
        archer
    )


    # ========================================================
    # 6. Saber回合
    # ========================================================

    print("\n========== 6. Saber回合 ==========\n")


    battle.start_character_turn(
        saber
    )


    # --------------------------------------------------------
    # Saber防御阶段
    #
    # 第一回合还没人攻击Saber
    # --------------------------------------------------------

    print("\n--- Saber防御阶段 ---")


    saber_defense = battle.defense_phase(
        saber,
        "block"
    )


    assert saber_defense is None


    # --------------------------------------------------------
    # Saber攻击阶段
    # --------------------------------------------------------

    print("\n--- Saber攻击阶段 ---")


    assert battle.attack_phase(
        saber
    ) is True


    archer_hp_before = archer.hp


    saber_attack = Action(
        actor=saber,
        action_id="attack",
        target=archer
    )


    saber_attack_result = (
        ActionResolver().resolve(
            saber_attack
        )
    )


    print(
        "Saber攻击:",
        saber_attack_result
    )


    # 攻击尚未结算
    assert archer.hp == archer_hp_before

    assert len(
        archer.pending_attacks
    ) == 1


    # 普通攻击消耗一个攻击阶段
    assert saber.attack_phase_count == 0


    battle.end_character_turn(
        saber
    )


    # ========================================================
    # 7. Archer回合
    # ========================================================

    print("\n========== 7. Archer回合 ==========\n")


    battle.start_character_turn(
        archer
    )


    # --------------------------------------------------------
    # Archer防御阶段
    # --------------------------------------------------------

    print("\n--- Archer防御阶段：格挡 ---")


    archer_hp_before = archer.hp


    archer_defense = battle.defense_phase(
        archer,
        "block"
    )


    print(
        "防御结果:",
        archer_defense
    )


    first_damage = (
        archer_hp_before
        - archer.hp
    )


    expected_first_damage = (
        saber.atk
        * (
            1
            - archer.block_resistance
        )
    )


    print(
        "第一次实际伤害:",
        first_damage
    )

    print(
        "第一次理论伤害:",
        expected_first_damage
    )


    # 浮点数不用严格==
    assert abs(
        first_damage
        - expected_first_damage
    ) < 1e-9


    # 应该从90 → 40
    print(
        "Archer当前HP:",
        archer.hp
    )


    assert archer.hp == 40


    # --------------------------------------------------------
    # Archer攻击Saber
    # --------------------------------------------------------

    print("\n--- Archer攻击阶段 ---")


    assert battle.attack_phase(
        archer
    ) is True


    saber_hp_before = saber.hp


    archer_attack = Action(
        actor=archer,
        action_id="attack",
        target=saber
    )


    result = ActionResolver().resolve(
        archer_attack
    )


    assert result is True


    # 此时Saber不能掉血
    assert saber.hp == saber_hp_before

    assert len(
        saber.pending_attacks
    ) == 1


    battle.end_character_turn(
        archer
    )


    show_full_status(
        saber,
        archer
    )


    # ========================================================
    # 8. 全局回合2结束
    # ========================================================

    print("\n========== 8. 全局回合2结束 ==========\n")


    turn_manager.end_turn()


    # ========================================================
    # 9. 全局回合3
    #
    # reset_turn会恢复attack_phase_count
    # ========================================================

    print("\n========== 9. 全局回合3 ==========\n")


    turn_manager.start_turn()


    print(
        "当前全局回合:",
        turn_manager.turn
    )


    assert saber.attack_phase_count == 1
    assert archer.attack_phase_count == 1


    # ========================================================
    # 10. Saber回合
    # ========================================================

    print("\n========== 10. Saber回合 ==========\n")


    battle.start_character_turn(
        saber
    )


    # --------------------------------------------------------
    # Saber防御
    #
    # 结算上回合Archer的攻击
    # --------------------------------------------------------

    print("\n--- Saber防御阶段：格挡 ---")


    saber_hp_before = saber.hp


    saber_defense = battle.defense_phase(
        saber,
        "block"
    )


    print(
        "Saber防御结果:",
        saber_defense
    )


    assert saber.hp < saber_hp_before

    assert len(
        saber.pending_attacks
    ) == 0


    # --------------------------------------------------------
    # Saber再次攻击Archer
    # --------------------------------------------------------

    print("\n--- Saber第二次攻击Archer ---")


    assert battle.attack_phase(
        saber
    ) is True


    second_attack = Action(
        actor=saber,
        action_id="attack",
        target=archer
    )


    result = ActionResolver().resolve(
        second_attack
    )


    assert result is True

    assert len(
        archer.pending_attacks
    ) == 1


    # 仍然只是AttackEvent
    # Archer仍然40HP

    assert archer.hp == 40


    battle.end_character_turn(
        saber
    )


    # ========================================================
    # 11. Archer回合
    #
    # 第二次格挡后进入濒死
    # ========================================================

    print("\n========== 11. Archer回合 ==========\n")


    battle.start_character_turn(
        archer
    )


    print(
        "\n--- Archer第二次格挡 ---"
    )


    archer_defense = battle.defense_phase(
        archer,
        "block"
    )


    print(
        "防御结果:",
        archer_defense
    )


    print(
        "Archer HP:",
        archer.hp
    )

    print(
        "Archer状态:",
        archer.status_flags
    )

    print(
        "濒死计数器:",
        archer.brink_of_death_counter
    )


    # 40 - 50 = -10
    # → 触发濒死
    # → HP = 1

    assert archer.hp == 1

    assert archer.brink_of_death_counter == 0

    assert archer.has_status(
        "brink_of_death"
    )

    assert archer.has_status(
        "weakness"
    )


    print(
        "PASS：Archer成功进入濒死"
    )


    # ========================================================
    # 12. Archer执行stay
    # ========================================================

    print("\n========== 12. Archer执行stay ==========\n")


    stay_action = Action(
        actor=archer,
        action_id="stay",
        target=None
    )


    stay_result = ActionResolver().resolve(
        stay_action
    )


    print(
        "stay结果:",
        stay_result
    )


    assert stay_result is True

    assert archer.has_status(
        "stay"
    )

    # stay占用了本轮攻击阶段；Escape只能在下一战斗轮使用。
    battle.end_character_turn(archer)
    turn_manager.end_turn()
    turn_manager.start_turn()

    # 完成Saber在新战斗轮中的攻击阶段，随后轮到Archer。
    saber_stay = Action(
        actor=saber,
        action_id="stay",
    )
    assert ActionResolver().resolve(saber_stay) is True
    battle.end_character_turn(saber)
    battle.start_character_turn(archer)


    # ========================================================
    # 13. Archer撤退
    #
    # Escape本身不再移动角色；大地图AP1将从road_BC开始。
    # ========================================================

    print("\n========== 13. Archer撤退 ==========\n")


    print(
        "撤退前位置:",
        archer.position.name
    )

    print(
        "撤退前Battle参与者:",
        [
            c.name
            for c in battle.participants
        ]
    )


    escape_action = Action(
        actor=archer,
        action_id="escape",
    )
    escape_action.game_turn = turn_manager.turn


    escape_result = ActionResolver().resolve(
        escape_action
    )


    print(
        "撤退结果:",
        escape_result
    )


    assert escape_result is True


    print(
        "撤退后位置:",
        archer.position.name
    )

    print(
        "Archer.in_battle:",
        archer.in_battle
    )


    assert archer.position is road_BC
    assert archer.in_battle is False
    assert archer.action_point == 2
    assert archer.forced_move_turn == turn_manager.turn


    # ========================================================
    # 14. Battle结束检查
    # ========================================================

    print("\n========== 14. Battle结束检查 ==========\n")


    print(
        "当前Battle参与者:",
        [
            c.name
            for c in battle.participants
        ]
    )


    print(
        "battle.ended:",
        battle.ended
    )


    print(
        "Saber.in_battle:",
        saber.in_battle
    )


    print(
        "Archer.in_battle:",
        archer.in_battle
    )


    # Archer退出后只剩Saber
    # check_battle_end应该自动结束Battle

    assert battle.ended is True

    assert saber.in_battle is False
    assert archer.in_battle is False


    # ========================================================
    # 15. 最终结果
    # ========================================================

    print("\n========== 15. 最终状态 ==========\n")


    show_full_status(
        saber,
        archer
    )


    print(
        "\n"
        + "=" * 70
    )

    print(
        "PASS：完整战斗流程全部通过"
    )

    print(
        "=" * 70
    )
    return saber, archer


# ============================================================
# main
# ============================================================

if __name__ == "__main__":
    test_complete_game_flow()
