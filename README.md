# Papermoon

Papermoon 是节点地图、全局回合与战斗回合共同驱动的文字规则引擎。

## 目录用途

- `game/`：全部规则实现、游戏状态、GameLoop、Session和规则资料；包含
  `action/`、`character/`、`map/`、`modifier/`、`rank/`、`resource/`、`skill/`、`turn/`。
- `core/`：终端界面、菜单与提示、人工测试场景及内容项目加载入口。
- `skilleditor/`：技能和角色卡编辑窗口。
- `test_examples/`：自动测试、手动演示和历届角色卡样本。
- `reference/`：操作说明、接口文档、交接记录与测试基线。
- `todo/`：保留原状。

规则导入统一使用`game.*`，例如`from game.character import create_character_from_card`。
终端适配器位于`core/terminal_game_runner.py`；效果字典位于`game/skill/effect_dictionary.txt`。

## 运行

单人人工测试可直接双击 `Start_Core.cmd`，编辑内容可双击 `Start_Skill_Editor.cmd`。
前者提供实卡直接对战、地图流程及双方选卡；后者是使用同一校验器的窗口式JSON编辑器。
详细步骤和记录位置见[操作说明](reference/MANUAL_TESTING.md)。

```powershell
python -m core --menu
python -m skilleditor
```

启动基础终端场景：

```powershell
python main.py
```

运行全部自动测试：

```powershell
python -m unittest discover -s test_examples -p "test_*.py"
```

当前测试基线为 607 项，另有11项实际Tk控件冒烟检查，验证结果见[测试基线](reference/TEST_BASELINE_2026-10-21.md)。

运行本轮完整审计（五轮全量、打乱测试顺序、32个随机种子实战、目录/语法和终端检查）：

```powershell
python test_examples/audit_test_suite.py
```

汇总保存到 `test_examples/results/regression_audit.json`。当前已建立`core`与
`skilleditor`两个入口：规则复用原实现，编辑改动通过独立JSON项目在启动时加载。

## 通用角色卡

`game/character/card_data.py::CHARACTER_CARD_DATA` 保存已录入的御主和从者数据，
`create_character_from_card(card_id, ...)` 统一创建角色并装载引用的内容。
当前已有御主 `master_test_0` 和Archer尼禄 `servant_test_0`，旧
`create_master_test_0()` 调用保留。

```python
from game.character import create_character_from_card

actor = create_character_from_card("master_test_0", name="测试御主")
assert actor.card_id == "master_test_0"
servant = create_character_from_card("servant_test_0", master=actor)
assert len(servant.noble_phantasms) == 3
```

卡片字段、校验和下一张从者卡的录入流程见[角色卡说明](reference/CHARACTER_CARDS.md)。

## 通用游戏循环

`game/game_loop.py::GameLoop` 负责正式战斗、AP1/AP2 行动收集、路径规划和
Encounter 暂停后继续执行。调用者必须提供决策器，所有选择均通过
`decision_provider.choose(request)` 完成；`run()` 返回 `reason`、`winners`
和 `turn`。其中 `winners` 仍为角色对象，当前接口尚未提供网络序列化。

例如，用脚本决策器运行一回合最小场景：

```python
from game.character.masters import Master
from game.game_loop import GameLoop
from game.game_manager import GameManager
from game.map.map import Location
from game.turn.decision import ScriptedDecisionProvider

location = Location("A")
actor = Master("Actor", 3, 3, 3, 3, 3, "C", 3)
actor.position = location
game = GameManager([actor], location, maximum_turns=1)
result = GameLoop(game, ScriptedDecisionProvider(["pass", "pass"])).run()
assert result == {"reason": "turn_limit", "winners": [], "turn": 1}
```

`run()` 自动开始游戏；逐回合调用 `run_global_turn()` 前需要先调用
`game.start_game()`。GameLoop本身保持同步执行；外部结构化输入可使用下述Session。
规则模块保留已有的 `print()` 日志；核心结算另有结构化战报，不从终端文字反解析。

`TerminalGameRunner` 继承 `GameLoop`，保留原有调用接口，负责终端决策器的
默认创建、行动分隔、退出异常和游戏结果提示。令咒菜单及特殊文本指令仍在
终端决策器中；Session通过现有服务提供结构化入口。

## 本机会话

`game/game_session.py::GameSession` 用单个工作线程运行一局游戏，
`QueuedDecisionProvider` 在决策处等待选项ID或整数答案，校验控制权和请求版本。
会话提供按玩家过滤的快照、事件游标、结构化令咒/GM操作和协作停止。

`get_events()` 现包含 `rule_report`：攻击、防御结果、掷骰、伤害、资源/状态变化、
技能发动、咏唱、场地及离场/死亡等结果。角色快照补充技能说明、次数、冷却、
咏唱进度、加符和持续效果。详情只提供给有权读取的玩家，GM可读取完整记录；
事件按发生时的信息过滤，后续视野变化不会修改旧战报。字段见[Session接口说明](reference/SESSION_RUNTIME.md)。

当前只使用本机内存和线程，没有HTTP、WebSocket或端口监听。完整调用示例、
接口及当前限制见[Session接口说明](reference/SESSION_RUNTIME.md)。

## 手动演示

两组已录入御主/尼禄卡的自动实战验收：

```powershell
python test_examples/minimal_card_battle.py --output test_examples/results/minimal_card_battle_fixed.json
python test_examples/minimal_card_battle.py --random-dice --seed 1 --output test_examples/results/minimal_card_battle_random.json
```

默认只固定战斗骰为5，先手同属性重掷仍按指定随机种子进行；第二条使用正常随机
骰。双阵营均使用正式卡面数值，经Session选择咏唱、宝具、治疗、保命及攻击。
从者双双退场后，存活御主选择停战；若一方先被消灭，则由原战斗条件结束。
验收在战斗自然结束后停止，不代替整局胜利。输出JSON包含完整GM战报和决策记录。
该驱动用于独立进程验收，不是正式玩家策略或AI。

手动双人战斗演示：

```powershell
python test_examples/manual_battle_demo.py
```

旧版完整流程回归演示：

```powershell
python test_examples/full_flow_demo.py
```
