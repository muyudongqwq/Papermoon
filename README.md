# Papermoon

Papermoon 是节点地图、全局回合与战斗回合共同驱动的文字规则引擎。

## 目录用途

| 目录 | 实际用途 |
| --- | --- |
| [game/](game/) | 游戏规则与运行内核。负责角色、行动、回合、战斗、技能及状态结算，也保存内置内容定义和历史规则资料；外层包入口提供常用类的延迟导入。 |
| [core/](core/) | 终端运行与内容项目接入层。提供测试菜单、人工决策提示、实战场景和运行记录；`catalog.py`负责加载自定义内容、全项目校验、备份及跨进程保存保护，包入口同时导出常用内核接口。 |
| [SkillEditorClient/](SkillEditorClient/) | 当前使用的技能与状态编辑器。提供技能单元、可选分支、触发事件、条件、消耗和效果参数表单，以及只读效果参考；职介技能以JSON编辑为主，“测试程序”单独使用表单。还包含源码启动和exe构建入口。 |
| [CharacterEditorClient/](CharacterEditorClient/) | 独立角色卡编辑器。编辑御主、从者的名称、属性与等级，自动分配ID；选择固有技能，以及御主的基础魔术或从者的职介技能。与技能编辑器共享内容项目，礼装和宝具选择入口预留。 |
| [MapEditorClient/](MapEditorClient/) | PySide6可视化地图编辑器。编辑地点、建筑、高层与可连接多个地点的道路，保存画布坐标，并可转换为规则内核使用的`Map`。 |
| [test_examples/](test_examples/) | 自动回归、真实Tk控件检查、exe分发检查、完整审计脚本及人工演示入口。实卡对战脚本用于复现决策过程、验证结算与战报。 |
| [reference/](reference/) | 项目文档与工作记录：角色卡格式、人工测试说明、Session接口、交接进度、测试基线和代码审计报告。 |
| [.vscode/](.vscode/) | VS Code调试配置；当前提供从`main.py`启动Papermoon的调试入口。 |

`game/`内部按结算职责划分：

| 子目录 | 实际用途 |
| --- | --- |
| [game/game/](game/game/) | 整局协调与调用接口：游戏管理、通用循环、GameSession、队列决策、令咒、GM指令、角色关系、圣杯进度，以及状态快照、可见信息与结构化战报。 |
| [game/action/](game/action/) | 行动定义、候选行动生成、目标与合法性检查，以及行动提交后的分派执行。包含内置行动和运行时追加的动态行动。 |
| [game/character/](game/character/) | 角色实体与通用角色卡工厂。实现御主、从者、NPC、使魔，以及属性、主从关系、资源访问等角色行为；`card_data.py`保存内置卡。目录内做卡文本为参考资料。 |
| [game/map/](game/map/) | 节点地图、距离与高层位置、移动结算，以及同行、骑乘队伍和共同移动规则；同时保存地图文字与图片资料。 |
| [game/modifier/](game/modifier/) | 底层持续效果实例与生命周期管理。处理属性、骰子、护盾、伤害修正等效果的施加、叠层、刷新、到期、净化、次数消耗与撤销，并提供条件上下文匹配。 |
| [game/rank/](game/rank/) | 属性、技能、天赋和宝具等级的数值表示与校验，包括加符、临时属性修正和等级取值。 |
| [game/resource/](game/resource/) | 自定义角色资源及统一消耗工具。定义资源边界、增减、重置和获得规则；`costs.py`集中处理费用计算、支付预检查、扣费及MP支付账本。 |
| [game/skill/](game/skill/) | 技能定义、校验、装载与执行。保存固有技能、职介技能、基础魔术和宝具的内置数据，实现技能单元、输入表达式、事件与条件、咏唱、场地、固有结界、召唤、陷阱等运行逻辑；开发用效果规范也在此目录。 |
| [game/status/](game/status/) | 可复用的命名状态仓库。`data.py`定义燃烧、弱体无效等状态，`registry.py`负责查询与校验，`runtime.py`把状态单元接入持续效果和事件系统，保留施加来源、层数、持续时间与剩余次数。 |
| [game/turn/](game/turn/) | 全局回合和战斗阶段的推进，以及先手、攻击、防御、抵消、伤害、骰子判定和玩家决策请求。 |

[test_examples/samples/](test_examples/samples/)保存测试卡和历史角色卡原文，用作录卡、裁定与回归时的对照资料；
这些文本不会自动变成可运行角色，实际装载使用内置数据或内容项目中的定义。

[SkillEditorClient/assets/](SkillEditorClient/assets/)保存编辑器共用的Papermoon图标：透明PNG用于窗口，
多尺寸ICO用于Windows标题栏、任务栏与exe图标，含20px、40px等九种尺寸，各尺寸均直接从原图生成。
窗口按自身DPI分别加载大小图标，子窗口与跨屏DPI变化沿用同一处理；SkillEditorClient打包脚本会收录运行时资源。

本地的`userdata/`保存自定义内容与运行记录，`build/`、`dist/`和缓存目录存放生成结果；它们由`.gitignore`排除，
不属于GitHub上的源码目录。

规则导入统一使用`game.*`，例如`from game.character import create_character_from_card`。
整局模块使用`game.game.*`，例如`from game.game.game_manager import GameManager`；
外层公共入口`from game import GameManager`仍可使用。
终端适配器位于`core/terminal_game_runner.py`；开发规范位于`game/skill/代码数据规范.txt`，
新客户端展示用字典位于`SkillEditorClient/effect_dictionary.txt`。

## 运行

单人人工测试可直接双击 `Start_Core.cmd`，编辑内容可双击 `Start_SkillEditorClient.vbs`。
前者提供实卡直接对战、地图流程及双方选卡；后者是当前的技能与状态表单编辑器，并保留高级JSON设置。
详细步骤和记录位置见[操作说明](reference/MANUAL_TESTING.md)。

```powershell
python -m core --menu
python -m SkillEditorClient
```

启动基础终端场景：

```powershell
python main.py
```

运行全部自动测试：

```powershell
python -m unittest discover -s test_examples -p "test_*.py"
```

当前源码测试基线为745项，另有124项实际Tk控件检查（旧版14项、技能客户端80项、状态表单17项、角色编辑器13项）。
beta 0.1 exe此前通过4项独立运行检查，详见[测试基线](reference/TEST_BASELINE_2026-10-21.md)。

运行本轮完整审计（五轮全量、打乱测试顺序、32个随机种子实战、目录/语法和终端检查）：

```powershell
python test_examples/audit_test_suite.py
```

汇总保存到 `test_examples/results/regression_audit.json`。当前已建立`core`与
`SkillEditorClient`两个入口：规则复用原实现，编辑改动通过独立JSON项目在启动时加载。

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

SkillEditorClient的“状态”分类提供表单：名称、说明保持显示，存续规则、叠加规则及状态单元
默认折叠。可编辑正负面、净化、持续回合、死亡后保留、来源范围、重施与叠层规则；状态单元
提供持续生效、自动触发、可选反应三种类型，复用事件、条件及效果参数表单。没有单元的状态是标记，
需由其他规则读取；新建状态不预装燃烧效果。状态不提供Rank、主动行动、咏唱、消耗或choices。
同来源及各事件目标有专门解释；反应次数仍由引擎统一管理。分组及复杂强度比较保留在叠加高级设置。

回退方式：取消工具栏“状态表单”勾选，当前完整草稿转回原JSON编辑，再勾选可返回表单。
切换不自动保存，不完整草稿会阻止切换并原样保留；结构不支持的导入内容仍可直接用JSON修复。
状态数据格式和规则引擎没有修改；保存沿用catalog.json.bak备份。
若要默认关闭实验入口，可将SkillEditorClient/status_form.py的ENABLE_STATUS_FORM设为False。
实验表单保留独立接入和回退开关，未迁移或批量改写userdata，当前内置13项状态可无损往返。

状态新增`tags`列表和可选`consumption={"event":"status_blocked","uses":次数}`；状态表单可直接
填写逗号分隔标签、次数限制和持续时间。内置“弱体无效”`debuff_immunity`默认1次、1回合，
在passive单元内使用`status_immunity`。该效果的`effect_data.tags`任一匹配待施加状态本身标签时，
阻止最终标记为debuff的状态；省略或空列表匹配全部负面状态。不会清除已有状态，不影响buff或neutral。
被阻止的状态不执行持续效果，也不发送施加后事件。每项匹配的施加/刷新/叠层尝试消耗1次，
同回合可连续阻止；次数耗尽或持续时间到期即移除父状态及所有持续效果。次数可不限，时间可永久。
多个免疫来源只消耗一份，按父状态叠加priority由高到低、同优先级先施加者优先。
重施时次数沿用use_refresh_rule，默认重置。终端与状态快照展示剩余次数，结构化战报记录status_blocked。

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
exe自带Python及Tkinter，可独立运行，无需另外安装Python。
双击根目录的`Start_SkillEditorClient.vbs`直接运行当前源码，使用电脑现有Python，不显示CMD窗口。
修改源码后关闭编辑器、再双击该脚本即可看到更新；无需在终端输入命令。

当前源码的新建流程：弹窗填写名称和Rank，点击“开始”（或“取消”返回）。新建固有技能ID从10起，
在已有最大数字ID之后顺延，0至9保留给测试；数据格式使用数字字符串，例如`"10"`。
左侧固有技能的数字ID按数值排序，既有名称式ID及引用保持原样；基础魔术和宝具沿用原命名方式。
顶部重复的名称/Rank摘要已移除；名称和等级标签及文本框为11pt、约原宽度一半，改名不改变ID。
技能说明保持常显多行文本框，字号10pt。
Rank下拉提供E至EX，GM可手动填写并通过校验。

新技能初始没有技能单元、消耗或效果。点击“新建技能单元”后，在单元内按需“新建效果”或
添加消耗；新单元component_id从unit_0起自动编号，不提供ID输入框，已有单元ID不改写。
“技能类型”输入框为半宽，新单元的类型和目标初始留空，框内分别提示“（在这里选择技能类型）”和“（在这里选择效果目标）”，
选择后显示对应说明；保存前需明确选择。已有技能保留原类型和目标，未写target时保留运行时默认自身的语义。
可用阶段显示中文，直接勾选、随宽度自动排列，并用灰色边框区域与目标隔开。
新建技能单元自动展开，点击新建效果时该效果自动展开；消耗、效果分组及高级设置默认折叠。
展开不改变数据。单元标题、加号、新建按钮及单元末尾“删除此技能单元”均为11pt；
末尾按钮直接删除所在单元，不再显示全局删除按钮或选择框。单元内先显示效果，再显示消耗。
从左侧选中已有技能时，所有可折叠区统一关闭；重复选中当前技能也会收起，保留未保存草稿。
左侧目录和职介技能编辑方式沿用原版；此界面调整晚于beta 0.1打包快照。

无AP1/AP2时，消耗资源选项不提供action_point；移除阶段后会清空失效的资源选择并要求
重新选择，不会擅自删除消耗或改写其数值。effect_type可下拉选择现有效果，并显示中文名称。
effect_data提供“参数选择”：直接列出当前效果全部可填参数，必填项排在最前并标星；空白可选项不写入，
已填的0、false和空列表保留。删除参数后可通过添加菜单恢复。布尔值及
固定选项可下拉选择，status_id包含当前项目中的自定义状态。星号标记必填字段，最终仍由
引擎统一校验。未选择合法效果类型时不显示effect_data区，重新选择不丢失已有参数草稿。
没有候选项的参数使用普通文本框，有候选项时才提供下拉选择。add_resource的resource_id显示为“资源名称”，
不再展示重复的name行；已有独立name保留在高级JSON中，新资源未填name时由资源名称作为显示名。
未选效果类型时框内显示“（在这里选择效果类型）”；类型、目标与效果类型的占位提示不会进入数据，
占位状态下对应解释留空。效果参数区域与阶段区域使用相同灰色底框。
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

active类型下提供“是否需要咏唱”，新建技能单元默认为否；选是后隐藏可用阶段，显示
“咏唱所需回合数”（正整数），每个完成咏唱的全局回合末累积1回合，映射casting_requirement。
切回否会恢复原阶段勾选；其他类型隐藏咏唱选项与阶段框。现有技能的咏唱需求自动显示。
新设咏唱的固有技能/基础魔术若没有casting配置，保存时建立release配置；费用统一使用cost列表。
已有消耗、自动展开等设置保留。原为instant的技能选是后改为release；其余咏唱设置仍在技能高级设置中编辑。
引擎目前只对active单元推进咏唱，完成后自动展开的技能也使用active；trigger/react/passive没有独立咏唱流程。

消耗统一写为`cost`列表，每项使用`resource`、`value`、可选`cost_id`与`timing`。
每个技能单元的消耗栏填写该单元完整费用，可选“开始咏唱时预付”或“技能发动时”，没有公共消耗区域。
未填timing默认activation（发动时）；casting_start表示咏唱预付，无需咏唱直接发动时支付。
咏唱预付只支持MP，保留临时MP、自身MP、御主补足及原账本退款；不退行动资源。
开始咏唱时选定单元，预付该单元费用；达到该单元回合数后只能解放该单元。
更换单元需要先中断并按原账本退款，再重新选择；不会支付其他单元的费用，也不共享咏唱进度。
单元的发动时费用和所选分支费用相加支付，分支费用仅选中时支付，重复选择则分别支付。
场地与固有结界的effect_data.cost使用maintenance，在参数表单内可添加维持消耗，创建回合不扣维持费。
技能顶层cost、原mp_cost、casting.mp_cost、additional_cost与maintenance对象不再作为数据写法接受。
华丽帝政的单元直接写100MP，普通自定义cost不再因对城范围被隐藏翻倍；宝具单元未提供cost时保留原Rank默认规则，
编辑器可确定Rank时会展示默认费用并保存到该单元。明确写cost=[]表示该单元免费。伤害倍率规则保持原样。
trigger在相同灰底框中显示“发动条件”：选择条件后显示解释及对应取值，可逐行新增、删除，
连接菜单仅可选择与、或，按从上到下依次组合；每行单独勾选非，表示要求该条件判定为False。
“删除此条件”位于对应行的“新增条件”上方；只剩一个条件时隐藏删除按钮。
原有平铺条件完整保留；无法用线性列表表示的嵌套分组在“条件高级设置”中编辑。
切换技能类型时条件在表单与单元高级设置间同步；未完成的草稿不会被覆盖。
trigger和react在目标上方显示“触发事件”灰底表单，提供现有36类事件的中文选项和说明，
例如全局回合开始、受到伤害后、伤害结算前、资源变化、状态施加等。选择事件时自动带入
当前引擎实际发送的before/after时机；已有配置完整保留，自定义事件ID也可填写。
优先级等字段在“触发事件高级设置”中编辑；事件决定何时检查，条件表单负责附加筛选。
事件名称和说明修改`SkillEditorClient/trigger_editor.py`中的`EVENT_OPTIONS`，保留内部事件ID。

工具栏“效果字典”打开独立只读窗口；每条效果的“查看说明”直接定位到对应类型。
可搜索effect_type、中文名称、参数或说明，查看固定必填/可选参数、编辑器候选值、
效果字典原文及Modifier公共字段。窗口不阻塞技能编辑，可选择文字并按Ctrl+C复制，
关闭参考不会保存或改变技能草稿。原完整字典页签继续保留。

源码版的独立参考窗口和完整字典页签统一读取`SkillEditorClient/effect_dictionary.txt`。
修改这份文本后，重新启动源码版即可看到更新；`game/skill/代码数据规范.txt`单独保留开发规范，
两份文件不会自动同步，修改展示文字不会改变引擎规则。

效果的处理方式统一使用`calculation`，由effect_type限定候选值；原`operation`参数不再接受。
`add_resource`中gain_rules同样使用`calculation`。例如资源设定使用
`{"effect_type":"modify_resource","effect_data":{"resource_id":"charges","calculation":"set","value":3}}`。

默认与旧版共用`userdata/catalog.json`内容项目；保存的变更在下次Core启动时生效。
也可用“打开项目”选择其他现有项目。没有自动保存，Ctrl+S或“保存条目”才写入磁盘。
状态使用可视化表单，并保留JSON编辑切换；职介技能中仅“测试程序”启用按等级分组的技能单元/效果表单，
保存仍使用原name/ranks结构，其他职介技能继续使用JSON编辑区。角色卡使用独立编辑器；
宝具的通用字段可用表单，专用字段保留在技能高级设置中。
点击“技能测试”会打开专用的技能测试终端，编辑器本身不需要后台终端。
exe中的Core同样使用自带运行环境；关闭编辑器不会关闭已启动的Core。

exe默认读写自身所在目录的`userdata/catalog.json`，不受启动时工作目录影响。
如将exe复制给其他GM，需要已有自定义内容时，请一并复制`userdata/catalog.json`。
可执行文件包含打包时的代码；修改Python源码后需要重新打包，修改外部内容项目无需重新打包。
源码可双击`Start_SkillEditorClient.vbs`，也可使用`python -m SkillEditorClient`。
按用户要求，只有明确要求时才重新打包exe；日常修改可在项目根目录运行
`pyw -3 -m SkillEditorClient`预览，保存草稿并关闭、重新启动源码窗口即可读取更新。
当前双编辑器发布目录为`dist/PapermoonEditors`，包含`SkillEditorClient beta 0.2.exe`和
`CharacterEditorClient beta 0.1.exe`。技能编辑器保留状态表单，两份程序均自带Python及Tk运行库，
普通启动不显示CMD。请将两份exe保持在同一文件夹，技能编辑器右上角按钮才能找到角色卡编辑器。
发布目录的`userdata/catalog.json`保存一份当前本地内容；发布包和源码目录各自保存，之后不会自动同步。

重新打包（Windows，构建工具不属于运行时依赖）：

```powershell
python -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install -r SkillEditorClient/requirements-build.txt
.\.venv-build\Scripts\python.exe -m SkillEditorClient.build_exe --distpath dist/PapermoonEditors
.\.venv-build\Scripts\python.exe -m CharacterEditorClient.build_exe --distpath dist/PapermoonEditors
```

生成的exe、独立构建环境及中间产物不提交到Git；如需分发可直接复制exe。

### Qt / PySide6开发环境

Qt界面开发使用独立的`.venv`环境，不与仅用于旧版Tk编辑器打包的
`.venv-build`混用。首次建立或重新建立环境：

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\python.exe -m pip install -r requirements-qt.txt
```

VS Code打开本目录时会默认选择`.venv`。Qt Designer、UI转换和资源编译工具分别为：

```powershell
.\.venv\Scripts\pyside6-designer.exe
.\.venv\Scripts\pyside6-uic.exe input.ui -o output.py
.\.venv\Scripts\pyside6-rcc.exe resources.qrc -o resources_rc.py
```

运行测试：

```powershell
.\.venv\Scripts\python.exe -m pytest test_examples
```

新客户端检查：`python -m test_examples.smoke_skill_editor_client`（需要正常桌面环境）。
Windows图标尺寸与资源释放检查：`python -m test_examples.smoke_skill_editor_icons`。
实验状态表单检查：`python -m test_examples.smoke_status_editor`。
角色卡编辑器检查：`python -m test_examples.smoke_character_editor_client`。
exe打包检查：`python -m test_examples.smoke_skill_editor_exe`。
双编辑器发布包检查：先设置环境变量`PAPERMOON_EDITOR_DIST`为发布目录绝对路径，运行
`python -m unittest test_examples.smoke_skill_editor_exe test_examples.smoke_editor_pair_exe`。

### 可视化地图编辑器

双击`Start_MapEditorClient.vbs`，或在项目根目录运行：

```powershell
.\.venv\Scripts\python.exe -m MapEditorClient
```

工具栏可新建、打开和保存地图，也可新建地点、连接道路和删除选中对象。地点节点可在画布中拖动；
按住Ctrl可在左侧列表或画布中选择两个以上地点，再创建普通道路或三岔路。右侧编辑地点名称、建筑与高层属性，
道路属性列出全部连接地点。地图默认保存到`userdata/maps/*.json`，包含稳定对象ID、节点位置及规则属性；
`MapEditorClient.model.load_map_document(path).to_game_map()`可转换为游戏内核的`Map`。

Designer源文件是`ui/mapeditor.ui`，生成文件是`MapEditorClient/ui_mapeditor.py`。修改`.ui`后重新生成：

```powershell
.\.venv\Scripts\pyside6-uic.exe ui\mapeditor.ui -o MapEditorClient\ui_mapeditor.py
```

不要直接修改生成的`ui_mapeditor.py`。

## 独立角色卡编辑器 beta 0.1

SkillEditorClient已去掉窗口及页签中的试验版字样，左侧不再列出角色卡，新建列表也不再提供御主卡/从者卡。
右上方“角色卡编辑器”按钮打开独立窗口，沿用当前内容项目；也可双击Start_CharacterEditorClient.vbs。
源码入口为CharacterEditorClient；窗口不显示CMD。源码入口缺失会报错；打包模式只寻找同文件夹下的
CharacterEditorClient beta 0.1.exe或CharacterEditorClient.exe，缺失时明确报错，不回退到其他编辑器。

新建时只确认Master/Servant，Servant额外选择现有合法职介。ID不允许手工输入，Master从master10开始，
Servant按职介分别从saber_10、archer_10等开始，均向已有最大编号后顺延；因引擎ID只接受小写，职介前缀
保存为小写，界面职介仍显示Saber、Archer等原名称。已有角色ID不改动。
五项基础属性只接受E/D/C/B/A及最多两个加符，例如C+、A++，保存为引擎原有数值/plus结构。
Master天赋与Servant宝具等级可下拉C/B/A/EX，也可手动输入GM；候选不显示GM。宝具等级允许原规则的
C+/B+/A+，天赋不接受加符。属性、天赋及宝具等级使用短输入框；界面不显示角色ID或初始令咒，
新御主令咒固定初始化为3，既有卡数值保留。新卡五项属性初始留空，未填或非法输入不能保存。

新建角色卡按钮位于左侧列表下方，与技能编辑器新建入口位置相近。
从者职介技能列出库中所有可用项，最多勾选两项，每项选择已定义等级；御主不提供职介技能，改为从基础魔术库勾选，
沿用现有规则不额外限制数量。双方固有技能从相同项目技能库中最多选三项。
御主显示“礼装（预留）”，从者显示“宝具（预留）”；已有角色的宝具及从者基础魔术引用保留。
两张内置卡可无损往返，并可保存给Core直接使用。
技能库修改后先在技能编辑器保存，再点击角色编辑器“刷新技能库”，保留当前属性与技能草稿。
两个窗口共享catalog.json，保存检查外部修改，避免互相覆盖；当前卡被其他窗口改动时保留草稿并报错，
新卡ID被另一个窗口占用时，刷新后自动重新编号。保存仍保留.bak。
