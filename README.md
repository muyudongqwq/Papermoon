# Papermoon

Papermoon 是节点地图、全局回合与战斗回合共同驱动的文字规则引擎。

## 目录用途

- `game/`：全部规则实现和规则资料，外层仅保留Python包入口；包含
  `game/`（整局管理、循环、Session、指令、状态视图与战报）、`action/`、`character/`、
  `map/`、`modifier/`、`rank/`、`resource/`、`skill/`、`status/`、`turn/`。
- `core/`：终端界面、菜单与提示、人工测试场景及内容项目加载入口。
- `skilleditor/`：技能和角色卡编辑窗口。
- `test_examples/`：自动测试、手动演示和历届角色卡样本。
- `reference/`：操作说明、接口文档、交接记录与测试基线。
- `todo/`：保留原状。

规则导入统一使用`game.*`，例如`from game.character import create_character_from_card`。
整局模块使用`game.game.*`，例如`from game.game.game_manager import GameManager`；
外层公共入口`from game import GameManager`仍可使用。
终端适配器位于`core/terminal_game_runner.py`；开发规范位于`game/skill/代码数据规范.txt`，
新客户端展示用字典位于`SkillEditorClient/effect_dictionary.txt`。

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

当前源码测试基线为696项，另有62项实际Tk控件检查（旧版14项、新客户端48项）。
beta 0.1 exe此前通过4项独立运行检查，详见[测试基线](reference/TEST_BASELINE_2026-10-21.md)。

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

`game/game/game_loop.py::GameLoop` 负责正式战斗、AP1/AP2 行动收集、路径规划和
Encounter 暂停后继续执行。调用者必须提供决策器，所有选择均通过
`decision_provider.choose(request)` 完成；`run()` 返回 `reason`、`winners`
和 `turn`。其中 `winners` 仍为角色对象，当前接口尚未提供网络序列化。

例如，用脚本决策器运行一回合最小场景：

```python
from game.character.masters import Master
from game.game.game_loop import GameLoop
from game.game.game_manager import GameManager
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

`game/game/game_session.py::GameSession` 用单个工作线程运行一局游戏，
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


## 状态仓库

Skill Editor 的“状态”分类统一定义状态，技能通过以下效果引用：

```json
{"effect_type": "add_status", "effect_data": {"status_id": "burning"}}
```

角色无需安装状态结算技能。内置 `burning` 是可修改的示例：每次全局回合末造成
每层10点基础魔术伤害，持续3次回合末，可净化。同一施加者和技能重复施加叠层并刷新时间，默认最多3层；
不同施加者分别记录来源、持续时间和伤害。状态可包含持续数值修正（passive）、
自动触发（trigger）或由承受者选择的反应（react），复用现有效果字典。

反应型状态按“承受者＋状态ID”每全局回合最多一次，刷新或重施不重置；自动触发
按承受者、状态ID、原施加者、原技能和组件分别限每回合一次，避免循环触发。
回合末先结算事件，再扣持续时间；该事件链中新施加或刷新时间的效果从下次末尾计时。

项目格式已更新为 `format_version: 2`，含 `status` 内容目录，直接拒绝旧版本项目。
`add_status` 不再接受 `value` 字符串，持续时间写在 effect 顶层。
完整格式及编辑示例见 [代码数据规范](game/skill/代码数据规范.txt) 的“状态仓库”。

状态运行实现位于 `game/status/`；角色结构化状态的 `status_instances` 和结构化战报
记录各实例的名称、来源、层数及剩余回合；终端 `status` / `status all` 也显示这些信息。

在Skill Editor的状态JSON中，修改`stacking.max_stacks`控制叠层上限，使用以下伤害
效果配置每层伤害（不要同时设置固定`value`）：

```json
{"effect_type": "damage", "effect_data": {
  "damage_type": "magic", "value_source": "status_stack_count", "multiplier": 10
}}
```

上述效果按当前实例层数乘以10计算，每次只结算一段伤害，沿用原有伤害修正和护盾。

## SkillEditorClient 表单试验版

双击根目录 [SkillEditorClient beta 0.1.exe](<SkillEditorClient beta 0.1.exe>) 打开新客户端，不附带CMD窗口。
exe自带Python及Tkinter，可独立运行，无需另外安装Python；原版的`skilleditor`与
`Start_Skill_Editor.cmd`照常使用。旧的新客户端.pyw、.vbs入口已移除。

当前源码的新建流程：弹窗填写名称和Rank，点击“开始”（或“取消”返回）。新建固有技能ID从10起，
在已有最大数字ID之后顺延，0至9保留给测试；数据格式使用数字字符串，例如`"10"`。
左侧固有技能的数字ID按数值排序，既有名称式ID及引用保持原样；基础魔术和宝具沿用原命名方式。
顶部重复的名称/Rank摘要已移除；名称和等级标签及文本框为11pt、约原宽度一半，改名不改变ID。
技能说明保持常显多行文本框，字号10pt。
Rank下拉提供E至EX，GM可手动填写并通过校验。

新技能初始没有技能单元、消耗或效果。点击“新建技能单元”后，在单元内按需“新建效果”或
添加消耗；新单元component_id从unit_0起自动编号，不提供ID输入框，已有单元ID不改写。
“技能类型”输入框为半宽，新单元的类型和目标初始留空，分别提示“选择技能类型”和“选择效果目标”，
选择后显示对应说明；保存前需明确选择。已有技能保留原类型和目标，未写target时保留运行时默认自身的语义。
可用阶段显示中文，直接勾选、随宽度自动排列，并用灰色边框区域与目标隔开。
技能单元、消耗、效果及高级设置默认全部折叠，
展开不改变数据。单元标题、加号、新建按钮及单元末尾“删除此技能单元”均为11pt；
末尾按钮直接删除所在单元，不再显示全局删除按钮或选择框。单元内先显示效果，再显示消耗。
从左侧选中已有技能时，所有可折叠区统一关闭；重复选中当前技能也会收起，保留未保存草稿。
左侧目录和职介技能编辑方式沿用原版；此界面调整晚于beta 0.1打包快照。

无AP1/AP2时，消耗资源选项不提供action_point；移除阶段后会清空失效的资源选择并要求
重新选择，不会擅自删除消耗或改写其数值。effect_type可下拉选择现有44种效果，并显示中文名称。
effect_data提供“参数选择”：从当前效果允许的字段中选择并添加，填写数值或文本；布尔值及
固定选项可下拉选择，status_id包含当前项目中的自定义状态。星号标记必填字段，最终仍由
引擎统一校验。未选择合法效果类型时不显示effect_data区，重新选择不丢失已有参数草稿。
未选效果类型仅显示“请选择效果类型”；效果参数区域与阶段区域使用相同灰色底框。
“效果参数高级设置”用于嵌套对象、列表及复杂配置，与参数表单切换时同步当前内容；
无效草稿会保留并阻止切换。切换效果类型不自动删除已填参数或附加设置，不适用的内容需自行删除。
其他未表单化字段保留在折叠的高级设置中。整条技能的JSON预览页签仍为只读，重复的工具栏按钮已移除。

在技能单元中新建效果并选择“choices”（可选发动），效果参数区可填写每次最多选择几项，
并勾选是否允许同一次发动重复选择同一分支。仅该类型显示效果内部的“可选分支”折叠栏，
其中可新建、命名和删除分支，编辑各分支的效果与额外消耗；条件保留在“分支高级设置”中。
剑术等已有choices会自动显示为可选发动效果；原有choice_id保留，新分支自动生成内部标识，
未命名时标题仅显示“分支 1”等序号。各折叠区域默认关闭。
choices是编辑器的结构入口，保存、导出及JSON预览仍使用技能单元原有choices结构，
不会写入effect_type="choices"；每个单元可配置一组，独立选择需另建单元，分支效果内不嵌套此入口。

dice_bonus的“调整的属性”可选择攻击骰（物理与魔术）或防御骰（闪避、格挡、抵消），
分别保存为effect_target="attack"、"defense"；一条效果即可同时调整对应各项，仍可单独选择具体骰。
内置剑术的两个分支各使用一条分组效果，持续时间和每场战斗使用次数不变。

阶段勾选项文案修改`SkillEditorClient/model.py`中的`PHASE_LABELS`右侧文字，保留AP1等左侧内部键。
消耗标题下的提示修改`SkillEditorClient/forms.py`中的`COST_HINT`；目标说明在`model.py`的`TARGET_DESCRIPTIONS`。

工具栏“效果字典”打开独立只读窗口；每条效果的“查看说明”直接定位到对应类型。
可搜索effect_type、中文名称、参数或说明，查看固定必填/可选参数、编辑器候选值、
效果字典原文及Modifier公共字段。窗口不阻塞技能编辑，可选择文字并按Ctrl+C复制，
关闭参考不会保存或改变技能草稿。原完整字典页签继续保留。

源码版的独立参考窗口和完整字典页签统一读取`SkillEditorClient/effect_dictionary.txt`。
修改这份文本后，重新启动源码版即可看到更新；`game/skill/代码数据规范.txt`单独保留开发规范，
旧版skilleditor读取该规范文件。两份文件不会自动同步，修改展示文字不会改变引擎规则。

效果的处理方式统一使用`calculation`，由effect_type限定候选值；原`operation`参数不再接受。
`add_resource`中gain_rules同样使用`calculation`。例如资源设定使用
`{"effect_type":"modify_resource","effect_data":{"resource_id":"charges","calculation":"set","value":3}}`。

默认与旧版共用`userdata/catalog.json`内容项目；保存的变更在下次Core启动时生效。
也可用“打开项目”选择其他现有项目。没有自动保存，Ctrl+S或“保存条目”才写入磁盘。
角色卡、状态和职介技能继续用“条目高级设置”中的原JSON编辑区；宝具的通用字段可用表单，
专用字段保留在技能高级设置中。
点击“启动Core测试”时仍打开游戏交互终端，编辑器本身不需要后台终端。
exe中的Core同样使用自带运行环境；关闭编辑器不会关闭已启动的Core。

exe默认读写自身所在目录的`userdata/catalog.json`，不受启动时工作目录影响。
如将exe复制给其他GM，需要已有自定义内容时，请一并复制`userdata/catalog.json`。
可执行文件包含打包时的代码；修改Python源码后需要重新打包，修改外部内容项目无需重新打包。
源码运行入口仍为`python -m SkillEditorClient`。
按用户要求，只有明确要求时才重新打包exe；日常修改可在项目根目录运行
`pyw -3 -m SkillEditorClient`预览，保存草稿并关闭、重新启动源码窗口即可读取更新。
当前根目录beta 0.1 exe包含calculation字段统一、字典路径调整及打包时的客户端展示字典。
窗口标题与Windows产品版本标注beta 0.1，Windows数字文件版本为0.1.0.0。

重新打包（Windows，构建工具不属于运行时依赖）：

```powershell
python -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install -r SkillEditorClient/requirements-build.txt
.\.venv-build\Scripts\python.exe -m SkillEditorClient.build_exe
```

生成的exe、独立构建环境及中间产物不提交到Git；如需分发可直接复制exe。

新客户端检查：`python -m test_examples.smoke_skill_editor_client`（需要正常桌面环境）。
exe打包检查：`python -m test_examples.smoke_skill_editor_exe`。
