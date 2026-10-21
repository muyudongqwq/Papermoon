# Papermoon 项目工作交接记录

更新时间：2026-10-21  
工作区：`C:\Users\hiiragi\Desktop\Papermoon`

## 0. 给新聊天的最短说明

Papermoon 已经不是概念原型，而是一个可通过终端完整运行、具有自动测试覆盖的文字规则引擎。当前工作的重点应从“继续重写底层”转为：

1. 保持现有规则内核稳定；
2. 保持已建立的通用 GameLoop、本机 Session 与队列决策运行层稳定；
3. 当前已有御主与尼禄两张正式卡，本轮以现有内容完成系统测试及问题修复；
4. 已提供 `core` 和 `skilleditor` 两个入口，当前等待用户独自进行第二轮人工测试；
5. 需要新卡时由用户选择样本，遇到未决定且影响结果的规则再请用户裁定。

目录已按用户要求整理：所有规则实现集中于game/，其下有action、character、map、
modifier、rank、resource、skill、turn。终端展示文件在core/；core、skilleditor、
test_examples仍在根目录，todo不动。导入统一game.*，不要恢复旧根目录模块或
增加sys.path/sys.modules别名。game包的公共类采用延迟导出，以避免子包导入循环。

除README外的Markdown文档现集中于reference/。本地Git使用main分支，远端origin为
https://github.com/muyudongqwq/Papermoon.git，由用户创建并授权首次提交与上传。
提交身份使用GitHub用户名及对应的隐私邮箱，只设置当前仓库，不修改全局Git身份。
.gitignore排除缓存、userdata、自动生成的test_examples/results及todo；.gitattributes
保持旧txt样本字节不变。Windows已启用127.0.0.1:7897系统代理，Git直连失败时
本次命令使用相同代理，不将代理配置写入仓库或全局配置。

新聊天开始后，应先完整阅读：

- `README.md`
- 本文件
- `game/skill/effect_dictionary.txt`
- `game/turn/decision.py`
- `game/game_loop.py`
- `game/game_session.py`
- `game/queued_decision.py`
- `game/rule_report.py`
- `game/character_state.py`
- `SESSION_RUNTIME.md`
- `core/terminal_game_runner.py`
- `game/game_manager.py`
- `game/turn/Turn.py`
- `game/turn/battle.py`
- `game/skill/content_data.py`
- `game/character/card_data.py`
- `game/character/card_factory.py`
- `CHARACTER_CARDS.md`
- `MANUAL_TESTING.md`
- `core/catalog.py`
- `core/scenarios.py`
- `core/__main__.py`
- `skilleditor/app.py`
- `test_examples/test_master_test_0_card.py`
- `test_examples/test_servant_test_0_card.py`

不要仅根据旧规则书或样例卡推翻现有行为。用户在长期讨论中确定的裁定已经大量写入代码和测试；当前代码与测试优先于旧文本。

---

## 1. 项目目标

本项目用于运行 Papermoon／折原战争式节点地图圣杯战争：

- 全局回合包含正式战斗阶段和大地图 AP1、AP2 行动层；
- 地图行动、相遇、宣战、偷袭、简易战斗轮和正式战斗相互衔接；
- Master、Servant、NPC、使魔共用角色基础能力，但保留各自规则差异；
- 技能、魔术、宝具尽量用声明式数据描述；
- Modifier、事件和效果关键词构成通用规则运行时；
- 终端只是目前的测试界面，最终玩家端预期为图形化界面；
- 文本指令主要保留给 GM 强制处理预想外情况。

## 2. 当前工程状态

当前统计：

- 非测试 Python 文件：85 个；
- 非测试 Python 代码：30,678 行；
- 自动测试模块：61 个；
- 自动测试：607 项，另有11项实际Tk控件冒烟检查；
- 默认顺序及随机种子 1、7、42、20261021打乱顺序：每次607项全部通过；
- 32个正常随机种子实战全部自然结束，未发现遗留会话线程；
- 代码可由 `python main.py` 启动最小终端场景。

确定性全量测试命令：

```powershell
python -c "import random, unittest; random.seed(1); suite=unittest.defaultTestLoader.discover('test_examples', pattern='test_*.py'); result=unittest.TextTestRunner(verbosity=1).run(suite); raise SystemExit(not result.wasSuccessful())"
```

普通测试命令：

```powershell
python -m unittest discover -s test_examples -p "test_*.py"
```

已修复的测试问题：

- 普通攻击抵消及魔术抵消测试在防御请求期间固定骰面为5，移除了成功断言对随机结果的依赖；正式掷骰规则未变。
- 阶段A、B、C已经完成。新增6项GameLoop、19项Session集成测试，完整验证记录见 `TEST_BASELINE_2026-10-21.md`。
- 阶段D已完成：通用角色卡入口、御主迁移、用户所选Archer尼禄卡录入，以及宝具/主从MP/死亡/圣杯验收。新增11项工厂测试与20项尼禄专项测试。
- 结构化核心战报与角色详细状态已完成，新增16项测试；包括真实御主/尼禄卡完整会话及嵌套反应，详见10.7。
- 最小双阵营实战已完成，固定与随机骰均自然结束战斗；新增4项验收/取消回归测试，修复未结算攻击清理缺少战报收尾，详见10.8。
- 当前会话层只使用本机线程和内存队列，没有HTTP、WebSocket、端口监听或远程连接。接口见 `SESSION_RUNTIME.md`。

## 3. 事实来源优先级

发生冲突时按以下顺序判断：

1. 当前用户最新裁定；
2. 已通过的自动测试；
3. 当前代码的统一实现；
4. `game/skill/effect_dictionary.txt` 中的正式数据格式；
5. `game/` 下的规则书；
6. `test_examples/samples/` 中的历届角色卡。

样例卡来自不同届，规则存在细微差异，只能用于发现潜在效果，不能直接视为当前规则。

## 4. 目录职责

- `game/action/`：通用行动声明、行动合法性、目标列表、行动解析。
- `game/character/`：Character、Master、Servant、Familiar、NPC及角色卡工厂。
- `game/`：GameManager、终端循环、令咒、圣杯、关系、GM指令和基础场景。
- `game/map/`：节点、道路、高层、移动、同行、同乘。
- `game/modifier/`：Modifier上下文、叠加、持续时间、消耗、净化及数值修正。
- `game/rank/`：Rank和加符基础结构。
- `game/resource/`：HP、MP以外的自定义资源。
- `game/skill/`：技能内容、验证器、事件、咏唱、场地、固有结界、召唤、陷阱等运行时。
- `game/turn/`：全局回合、战斗、先手、伤害、防御、掷骰、DecisionRequest。
- `test_examples/`：自动回归、手动演示、历史角色卡样本。
- `todo/`：旧讨论记录，不保证仍然代表当前待办。

注意：`game/skill/status.py` 当前为空。Status 的机械作用主要由 `status_flags` 和 `StatusModifier` 承担，不应仅因为该文件为空就另建一套状态系统。

## 5. 已稳定的核心架构

### 5.1 GameManager

`game/game_manager.py` 是一局游戏的聚合根，持有：

- 活跃、死亡和消失角色；
- TurnManager；
- HolyGrail；
- FieldManager；
- RealityMarbleManager；
- ObservationManager；
- EventManager；
- RelationshipManager；
- InformationManager；
- TrapManager；
- SummonManager；
- CommandSpellTransferManager。

它负责游戏开始、角色动态注册/移除、死亡清理、圣杯状态、回合上限、胜利和外部强制结束。

最大回合数默认 120。达到上限时所有仍存活角色进入死亡流程，然后以 `turn_limit` 结束。

### 5.2 TurnManager

`game/turn/Turn.py` 负责全局回合：

1. `start_turn()`；
2. 应用回合开始关系变化和事件；
3. 解散上一战斗轮全员待机的战斗；
4. 将已锁定的 BattleRequest 建成战斗；
5. 运行正式战斗；
6. 建立大地图 AP1/AP2 行动层；
7. 执行 AP1，处理移动中 Encounter，完成 AP1 checkpoint；
8. 执行 AP2并完成 checkpoint；
9. 全局回合结束：关系申请、Modifier、咏唱、角色回合末、场地、召唤、圣杯等。

每个角色每个 AP 层最多进行一次正式行动。两 AP 行动会占用 AP1 和 AP2。战斗角色在地图层视为没有普通 AP 行动。

### 5.3 BattleManager

`game/turn/battle.py` 负责：

- 战斗参与者与 CombatLink；
- 正式行动顺序和中途加入；
- 防御、攻击、待机、撤退；
- pending attacks；
- 援护、紧急援护；
- 简易战斗轮；
- 偷袭额外轮；
- 抵消、格挡、闪避；
- order change；
- 战斗轮事件和 MP 支付账本；
- 战斗成立与解散。

最新确认：隐蔽角色从战斗中退出后，如果剩余关系不足以维持战斗，原战斗立即解散。这是正常现象；不建立“暂离战斗成员”名单。隐藏结束时只有原战斗仍存在才会重新加入并排在末尾。

### 5.4 UI 无关决策接口

`game/turn/decision.py` 已提供：

- `DecisionRequest`；
- `NumericDecisionRequest`；
- `DecisionOption`；
- `TerminalDecisionProvider`；
- `ScriptedDecisionProvider`。

规则内核原则上通过 `decision_provider.choose(request)` 请求输入，不应直接调用 `input()`。这正是未来 GUI、网络客户端、AI 或回放控制器的接入点。

`GameTerminalDecisionProvider` 保留终端菜单；本机Session通过 `QueuedDecisionProvider` 等待结构化答案，令咒和GM操作复用现有服务。所有规则修改仍在同一工作线程上执行。

`DecisionRequest` 与 `NumericDecisionRequest` 增加默认False的 `allow_refresh` 元数据，只有具备重建请求处理的窗口显式开启。终端原有行为保持不变。角色拥有只读 `character_id`，不再以姓名作为Session唯一标识。

### 5.5 Action 系统

`game/action/action_data.py` 已定义标准行动：

- move、pass；
- join_travel_group、transfer_travel_leader；
- invite_carry、leave_carry；
- join_battle；
- surrender、wish；
- investigate、perceive、battle_perceive、hide；
- stay、attack、direct_attack；
- mend、rest、command_spell_transfer；
- chant、interrupt_casting、release、escape；
- guard、dodge、block、offset。

`ActionListBuilder` 根据角色、阶段、位置、资源和目标生成合法列表；`ActionResolver` 执行行动。前端不应自行重写合法性，应消费这里生成的列表。

### 5.6 Skill/Event/Modifier 系统

技能分为 active、passive、trigger、react，组件可包含：

- 阶段；
- 条件；
- 目标规则；
- 资源/阶段消耗；
- 冷却和次数；
- 可变输入；
- choices；
- effects；
- 咏唱需求。

事件系统支持 before/after、priority、触发限制、反应选择和防循环使用记录。

Modifier 支持：

- buff/debuff/neutral；
- 可净化与不可净化；
- replace、refresh、stack、strongest等叠加；
- 来源和同名技能规则；
- 持续时间与阶段窗口；
- 次数消耗；
- 战斗正式阶段窗口；
- 死亡后是否保留；
- 条件上下文；
- 伤害、骰值、属性、资源上限、费用、护盾、视野、移动等修正。

数值统一取 `int()` 的整数部分，对负数也是向零截断，不是数学意义上的 floor。

### 5.7 效果关键词

验证器当前严格接受以下 Effect：

- 内容/行动/技能：`add_content`、`remove_content`、`add_action`、`add_skill`、`remove_skill`、`switch_skill_set`、`growing`、`restore_component`；
- 攻击/伤害：`create_attack_event`、`add_simple_round`、`damage`、`change_damage_type`；
- 资源：`add_resource`、`gain_resource`、`modify_resource`、`recover_resource`、`grant_temporary_mp`；
- 事件：`modify_event_value`、`cancel_event`；
- 地图/特殊实体：`create_field`、`deploy_reality_marble`、`observe_location`、`perception_check`、`trap`、`summon`；
- 战斗顺序/净化：`order_change`、`purify`；
- Modifier：`add_status`、`attribute_bonus`、`numeric_attribute_bonus`、`dice_bonus`、`attack_bonus`、`plus_bonus`、`magic_resistance`、`movement_point_bonus`、`visibility_bonus`、`carry_capacity`、`presence_concealment`、`damage_modifier`、`cost_modifier`、`shield`、`hidden`。

`game/skill/effect_dictionary.txt` 是唯一正式字段说明。每完成或变更关键词，都要同步更新该文件。

未知 Effect 和已讨论但尚未实现的 Effect 都严格返回“效果关键词不存在”。不保留旧字段兼容。

尚未包装为通用技能 Effect 的只有 attitude/alliance/information 一组；对应底层管理器已经存在。

## 6. 已实现的重要规则摘要

### 6.1 地图、移动与相遇

- 地图为 Location/Road 节点图；Road 可连接多个 Location。
- 道路本身消耗 1 移动力。
- 地面与高层之间移动消耗 1；二者是同一“区域”，但战斗同位置判断仍区分具体节点。
- 移动路径由玩家逐步选择，允许往返，不做自动最短寻路。
- move 最少移动一步；原地空过使用 pass/stay。
- Encounter 会暂停移动，完成决定后恢复或重规划。
- AP1/AP2均支持继续、重规划、停下、参战等对应流程。
- 宣战决定不可撤回，并可触发同地点玩家重新考虑参战。
- BattleRequest 在 checkpoint 锁定；偷袭资格也按对应快照处理。
- direct attack 不能指定同一具体节点目标；它是超距打击。
- direct attack 在提交后、普通移动开始前立即进入简易战斗轮，并记录攻击来源位置作为临时情报。

### 6.2 视野、感知和调查

- 常时 `visibility=0`，即通常只看到同节点角色。
- `own_visible` 是自己直接视野；攻击目标必须来自自己的真实视野。
- `shared_visible` 是规则允许的共享视野；普通盟友不共享视野。
- Master/Servant保留视野共享；使魔与召唤者共享。
- `own_perceived` 是自己感知到的位置记录；`shared_perceived` 保留来源区分；`perceived` 是合并结果。
- perceived 计入 `any_visible`/遭遇知情，但不计入 `own_visible`，不能单独作为普通攻击视野。
- 感知范围为 5，成功比较为感知骰 >= 隐蔽骰；离开原感知者范围后移除。
- 调查取得行动层结束时的位置快照；普通主动隐藏会被调查揭露，气息遮断按Rank拥有额外免疫。
- 工房只解除对工房主人的隐蔽/气息遮断，不提供普通盟友视野。

### 6.3 战斗、简易轮、援护与抵消

- 正式战斗结束条件基于是否仍存在有效敌对/CombatLink，而不只是人数。
- 新加入战斗者排在末尾；多名新加入者先按敏捷、幸运（必要时规则骰）形成内部顺序，再整体放到末尾。
- NPC/使魔固定先手快照，同敏同幸慢于玩家角色；使魔再以召唤者锚点排序。
- 简易战斗轮为单攻击方、多防守方；防守方按正式战斗顺序/全局顺序规则行动。
- 援护阶段位于攻击和对应防御之间；符合条件者每轮援护一次。
- 简易轮友军援护不消耗 AP；紧急援护用于令咒传送入场，可选择不援护。
- 援护强制格挡，优先级高于 random_defense。
- 抵消可选择普通攻击或符合出口的攻击技能：attack 只能抵消 attack，release 只能抵消 release。
- 抵消实际支付资源、不消耗原本攻击阶段，可多次使用；没有可用攻击时不能抵消。
- 多段攻击合计为总伤，只进行一次抵消骰对抗；剩余命中段数按规则计算。
- pending attack 到防御/援护解析时正式结算。

### 6.4 掷骰、加符和伤害

- 基础骰：1d10 + 属性/派生值 + DiceModifier + 情境修正。
- 最终骰面 10 为大成功并 +15（需满足幸运资格）；骰面 1 为大失败并 -15；大失败资格人人拥有。
- 幸运加符把骰面 x 变为 11-x，只根据最终骰面做极值检定。
- 幸运重骰与翻转可交替多次，后一结果覆盖前一结果。
- 筋/敏加符按本回合消耗数量形成 x2、x3……倍率；耐/魔提高HP/MP上限；幸运翻转；宝具加符提高持有上限。
- 加符在每次进入战斗时按角色容量重置；逃离后重新加入同一战斗也重置。
- 伤害百分比先合计，再乘除，最后处理加减。
- 魔术伤害受 magic resistance；物理伤害不受；真实伤害跳过普通减免。
- Shield、DamageModifier和直接伤害均已接入统一伤害流程。

### 6.5 濒死、死亡和清理

- 正式角色每次脱离战斗前最多触发一次濒死保护。
- brink_of_death 存续期间受到伤害为0，自身伤害和最终骰值减半。
- 同时满足“不在战斗中”且“不在 weakness”时，濒死次数恢复为1。
- Familiar没有濒死，符合死亡条件时直接消失。
- 死亡角色从地点人员、行动、pending attack、BattleRequest、先手与活跃角色列表清除，进入 `dead_characters`。
- 圣杯携带者死亡时，圣杯在同回合下一 AP checkpoint 落在死亡地点。
- `persist_after_death` Modifier可保留并正常减少持续时间。

### 6.6 Master/Servant

- Master最多两名Servant；Servant最多一个Master。
- 同一Master的Servant自动建立规则友军关系。
- Servant消耗MP不足时尝试由Master支付。
- mend：Servant以自身MP等量回复HP；战斗占攻击阶段，地图占2AP。
- Master死亡后Servant解除从属；原有普通友军关系暂不自动删除。
- 无Master的Servant回合末支付90MP，不足则直接死亡；单独行动可将费用减为45并提供对应时长的免费期。
- surrender：失去全部Servant的Master可在地图AP退场。

### 6.7 stay、escape和战斗解散

- 战斗中的 stay 消耗攻击阶段并留下作为下一轮 escape 前置的记录。
- escape 只在战斗攻击阶段使用，要求上轮 stay；有3回合冷却。
- escape 后三回合 `movement_conversion -1`。
- escape 后进入地图行动，AP1固定为move；再次在原地发生Encounter可以重新参战。
- 战斗轮全部成员都stay，则下一全局回合开始时解散；解散角色当轮只有AP2。

### 6.8 咏唱与解放

- chant 可用于战斗和非战斗；地图只能AP1并占用AP2，战斗消耗攻击阶段。
- 维持咏唱必须继续选择咏唱；其他正式行动中断并返还已支付MP。
- interrupt casting 可主动中断并返还。
- release 根据组件 casting_requirement 过滤可用效果，选择目标时再执行。
- 攻击类魔术和宝具统一由 release 出口产生攻击；普通攻击由 attack 出口产生攻击。
- casting 状态下所有防御骰减半。
- 令咒瞬移会中断咏唱。
- 已支持 `auto_activate_component_id`，用于达到层数后自动发动特定组件。

### 6.9 令咒

目前菜单由 `commandspell` 打开，不预扣、不暂停，也允许返回：

- 临时MP +90，消耗1划；到下一次个人回合结束，若不存在则全局回合结束时扣除；
- 下一次任意攻击/宝具/魔术伤害 +90，消耗1划；范围攻击对每人+90，多段只加第一段；可叠加；
- 瞬移从者至Master见过的地点，消耗2划。

瞬移会刷新位置相关列表、打断咏唱，并按目标是否仍有攻击阶段决定转入新战场后的攻击资格。即使没有攻击阶段，仍可防御和援护。存在未结算攻击时可触发紧急援护选择。

令咒移植是独立的三回合地图行动，双方必须开始时确认，任何移动、战斗或对应中断都会失败；完成时扣除 `max(约定数量, 剩余数量)`。

### 6.10 场地、固有结界、陷阱、召唤

- Field支持 workshop、territory、barrier；默认同中心不能重复展开，先展开者阻断后展开者并返还后者费用。
- 场地可覆盖同地点高层，支持维护费用、多重效果、持续/进入/离开/回合末应用。
- Reality Marble是独立一格地图空间，不能普通移动进入；创建者离开或死亡立刻结束，内部角色回到入口。
- Trap隐蔽存在、没有自身视野；设置者拥有其视野，可选择是否向主从/同行共享知识。
- 曾经拥有陷阱视野者永久视为知道该陷阱，不会触发或受其伤害。
- 陷阱攻击用设置时魔术攻击快照，以简易战斗轮结算，命中者平均分摊固定总伤。
- Summon支持模板、数量、位置、持续时间、上限、替换策略、动作白名单等。
- Familiar位于`game/character/familiar.py`，随召唤者退场消失，与召唤者互为规则友军但不继承召唤者全部友军关系；视野共享，控制者继承召唤者。

### 6.11 关系和机械情报

- Attitude：盟友、友善、中立、敌对；除同盟外态度本质上是单向记录。
- 主从是天然盟友，但不自动建立同盟团体。
- 一个角色可属于多个同盟团体。
- 第一个多人同盟由邀请建立；加入已有同盟采取申请制，与至少一名成员同地点且与全部成员互为友善。
- 退出同盟下回合生效并下降为友善；攻击同盟成员可触发背盟。
- 普通盟友不共享视野；主从/召唤关系保留专门共享。
- 当前机械情报只重点处理陷阱、工房解除隐藏、Encounter/攻击来源临时记录等；大部分复杂情报留给GM。
- 关系和情报管理器已实现，但尚未包装成卡面通用Effect。

## 7. 当前正式内容数据

### 7.1 基础魔术

`game/skill/basic_magic_data.py` 已有：

- familiar；
- insight；
- workshop；
- magic_bullet；
- reinforcement；
- healing；
- protection；
- trap。

`PENDING_BASIC_MAGIC_DATA` 当前为空。

### 7.2 职介技能

`game/skill/class_skill_data.py` 已有：

- 对魔力；
- 骑乘；
- 单独行动；
- 气息遮断；
- 狂化；
- 测试程序。

### 7.3 第一张正式录入卡

样本来源：`test_examples/samples/Master_test_0.txt`。  
数据：`game/character/card_data.py::CHARACTER_CARD_DATA["master_test_0"]`。  
工厂：`create_character_from_card("master_test_0")`，旧 `create_master_test_0()` 为兼容包装。  
内容：`game/skill/content_data.py`。

已录入：

- 无瑕之人 A：before_damage反应，以输入数量的MP抵消伤害；
- 天物流转 A：战斗轮末将本轮支付MP的一半转为临时MP；
- 星火予此 A：全局回合开始切换记录，保留技能实例及冷却；
- Barrel Replica B：战斗内攻击和战斗外超距简易轮，300 + 目标魔力Rank×120魔术伤害，共享6回合冷却；
- 冥想神经 Zabaniya B：双重感知、非战斗气息遮断、战斗咏唱后隐蔽离场；
- 阵地制作 B：升级自己的工房，选择固定受益者，提供当前版本对魔力B及场地末感知。

该卡有7项专门测试，位于 `test_examples/test_master_test_0_card.py`。

### 7.4 第一张正式从者卡：Archer尼禄

样本为用户放入的 `test_examples/samples/Servant_test_0.txt`（原文件GB18030编码，
保持不变）。通用工厂使用 `create_character_from_card("servant_test_0")`；技能与
三件宝具均在 `game/skill/content_data.py`，没有新增专用角色构造器。

用户已确认的裁定：

- 保命顺序为通用濒死→战斗续行→其他保命；多个其他保命由玩家选择。
- 夕阳在本全局回合内提供HP最低1，允许回血；第三次使用移除技能，保护不提前消失。
- 剧场40MP、咏唱1回合后自动展开，不消耗攻击阶段；持续至本场战斗结束。
- 尼禄决定退场许可，任何形式的脱离都算；未经许可的60点伤害无法防御。
- 帝政150为魔术伤害，可闪避和抵消，忽略格挡减伤和护盾。
- 头痛-12仅用于明确标记的精神判定。

实现注意：

- 皇帝特权在全局回合开始选择技能，复用互斥技能组及缓存实例。剑术3次/战斗，
  战斗续行2次/战斗；切换不刷新次数。借用气息遮断A和单独行动A沿用现行职介库，
  不回滚到旧卡的“三天”。无效果的对魔力未装载。
- `game/skill/survival_runtime.py` 统一在护盾后、扣HP前处理保命；新事件为
  before_battle_continuation与before_lethal_damage。通用濒死仍由原有流程执行。
  prevent_death和hp_floor为通用Effect；hp_floor只在真实全局回合末到期。
- trigger/react现在也可声明usage_limit/cooldown，仍同时受事件limit约束。
- 剧场使用battle_bound场地及通用exit_penalty，统一接入remove_participant；死亡
  清理和正常战斗结束不受罚。惩罚致死时停止瞬移，并防止隐蔽Modifier在死亡后残留。
  这60点未指定类型，暂按物理直接伤害使用普通修正/护盾，不赋予额外穿盾。
- retain_attack_phase_on_failed_defense仅保护尼禄的失败格挡；现有格挡失败确实会
  清空攻击阶段，不要误认为内核不存在此规则。
- 原初之火为免费即时发动，3次/战斗，攻击基础伤害+40。咏唱配置新增
  activation_mode=release/instant/automatic；自动完成时条件失效会中断并退款。
- 帝政为对城，沿用翻倍规则，所以目录基础值50MP/75伤害，最终100MP/150伤害。
  ignore_block仅跳过格挡减伤，ignore_shield独立控制穿盾；对魔力仍有效。
- 头痛使用mental标签，不影响普通攻击、防御、感知。剧场的视听描写尚无独立
  感官系统，样本攻击距离/最大捕捉人数沿用现有目标规则。详见CHARACTER_CARDS.md。

20项专项测试覆盖卡片装载、切换次数、保命顺序及多个保命选择、场地生命周期、
各种离场及致死清理、伤害/闪避/抵消、MP账本退款、死亡/圣杯和真实卡片Session
队列的控制权及嵌套决策。未增加网络功能或依赖。

## 8. 已明确暂不处理或后置的内容

- 白热化；
- 羁绊值；
- 地瓜；
- 令咒感应；
- 完整的玩家隐私情报系统；
- 旧版暗示魔术；
- 监听器式实时令咒输入；
- 多客户端/服务端同步输入；
- GUI；
- `conflict_group` 的通用矛盾能力裁定，等实际技能需要时再做；
- 自定义技能可能需要独立选择窗口，已被明确要求记住，但尚未形成最终运行层界面。

格挡和抵消与旧规则书有差异，这是规则制定者接受的安全规则变化，不要为了与旧文本一致而回滚。

## 9. 现存工程问题与技术债

### 9.1 通用循环、会话、核心战报与详细状态已建立

`game/game_loop.py::GameLoop` 已负责以下通用编排：

- 游戏循环；
- AP1/AP2批量收集；
- 路径规划；
- Encounter交互；
- 正式战斗与地图阶段的衔接。

`TerminalGameRunner` 继承GameLoop，保留原有方法入口，负责终端默认决策器、行动分隔、退出异常和结果提示。GameLoop必须显式注入决策器，`run()` 返回reason、winners和turn；winners仍为角色对象。

终端显示、特殊文本指令和令咒菜单仍由 `GameTerminalDecisionProvider` 负责。
GameSession复用令咒与GM服务，提供结构化入口、工作线程、队列决策、快照和事件游标。
核心规则结果现在独立记录为rule_report；保留print，不以解析终端文字生成战报。

### 9.2 当前决策接口是同步拉取

内核调用 `decision_provider.choose(request)` 并等待返回。GUI/服务端需要：

- 把请求序列化；
- 把请求发给正确玩家；
- 等待玩家提交；
- 校验该提交仍对应当前请求；
- 将结果送回内核。

第一版本机实现已经采用以下方式：

1. 每个 GameSession 在独立工作线程运行现有同步内核；
2. `QueuedDecisionProvider.choose()` 将 DecisionRequest 转为DTO并放入输出队列；
3. 该调用等待对应输入队列中的答案；
4. 为未来HTTP/WebSocket/UI适配器保留Session队列入口；
5. 保留 ScriptedDecisionProvider 用于测试和回放。

等实际运行稳定后，再评估是否把内核改造成显式可暂停状态机。第一版直接改async风险很大，因为Encounter、简易轮、反应技能和令咒都存在嵌套决策。

实际入口为 `game/game_session.py`、`game/queued_decision.py` 和 `game/session_view.py`。选项只提交option_id，数值输入只提交整数value；请求ID、版本和控制者必须匹配。快照和事件不含规则对象，GM可看完整状态，玩家只看自己和机械视野允许的信息。

即时命令仅在allow_refresh=True窗口接收，成功或拒绝后均重建请求。嵌套反应窗口可以正常作答，但需完成该选择后再发即时命令。控制者ID来自可信本地调用者；持久化、随机流存档和跨进程恢复尚未实现。

### 9.3 通用角色卡入口及首张从者卡已完成

现有 `game/character/card_data.py` 和 `game/character/card_factory.py` 已提供：

- `CHARACTER_CARD_DATA`；
- 标准 `card_id`；
- 角色类型；
- 基础属性、天赋/宝具、令咒；
- 初始职介技能、固有技能、基础魔术、宝具ID；
- 通用 `create_character_from_card(card_id, ...)`。

御主测试卡已迁移并保留兼容包装，11项通用入口测试涵盖两种角色、四类内容、实例隔离、宝具上限、引用检查、初始被动条件和失败清理。正式目录已有master_test_0及servant_test_0，后者为用户所选Archer尼禄；宝具目录已有其3件宝具。

字段格式和录入步骤见 `CHARACTER_CARDS.md`。不要为每张新卡新增专用工厂函数，也不要把放入samples的文本直接视为已校验数据。

### 9.4 巨型模块

- `game/skill/skill_runtime.py` 已超过10万字节；
- `game/turn/battle.py` 也很大；原终端循环的通用编排已迁移到 `game/game_loop.py`，后者仍包含较多地图交互代码。

不要为了美观进行无目标重构。只有在建立运行层接口或新增通用Effect时，才按职责逐步提取服务，并以现有测试保护行为。

## 10. 本机运行层与后续设计

本机实现已放在现有 `game/` 下，未新增网络层目录。核心对象及后续扩展边界如下。

### 10.1 GameSession

负责一局运行实例：

- session_id；
- GameManager；
- 通用GameLoop；
- 当前状态；
- 控制权映射；
- 待处理DecisionRequest；
- 输入/输出事件队列；
- 启动、停止、异常和游戏结束。

### 10.2 SerializableDecision（当前采用DTO字典）

由 DecisionRequest 转换，至少包含：

- request_id；
- session_id；
- recipient/controller_id；
- character_id；
- phase；
- prompt；
- option_id、label；
- 数值输入上下限；
- revision/version；
- 是否允许刷新或取消。

前端只能提交 option_id，不要把任意字符串直接交给规则内核。

### 10.3 RuntimeDecisionProvider（已实现为QueuedDecisionProvider）

职责：

- 接收内核DecisionRequest；
- 确定控制者；
- 序列化并发布；
- 等待对应回答；
- 处理 `DecisionRefreshRequested`；
- 调用原request.resolve或直接映射受信value；
- 记录决策日志。

### 10.4 GameEvent/ViewEvent

规则事件和用户可见事件应分开：

- 规则事件仍由 EventManager 处理；
- 运行层产生只读的UI事件，例如角色行动、伤害、死亡、宣战、移动、回合切换；
- 每个事件根据控制权与机械情报生成不同玩家视图；
- GM拥有完整视图。

第一版不需要把全部隐藏情报自动化；可先支持公共事件、自己的精确状态和GM全量状态。

### 10.5 Snapshot

建立只读快照，不允许GUI直接持有Character对象：

- session；
- game/turn/AP/phase；
- 当前请求；
- 自己控制的角色；
- 对自己可见的地图/角色；
- 战斗列表；
- 公共日志；
- 游戏结束原因及胜者。

### 10.6 GM接口

已有 `game/gm_commands.py`：

- `add_resource target resource amount`；
- `damage target damage_type amount`；
- `teleport target position`；
- `kill target`。

非法参数统一抛ValueError。未来服务端应为GM提供结构化调用，不以玩家文本指令形式暴露。

### 10.7 核心战报与详细角色状态（已完成）

- `game/rule_report.py`提供独立结果记录，不发送规则GameEvent、不触发技能。
  EventManager在既有事件完成后投递白名单记录，攻击/骰子/伤害/技能/咏唱等出口
  补充明确结果。结构化记录不依赖print；终端输出保持兼容。
- GameManager.rule_reports.history是完整GM日志（含各权限层），只供可信调用者。
  GameSession启动时订阅新记录，停止/结束/异常均解除订阅。Session输出rule_report，
  每个结果只有一个全局事件序号，但按控制者冻结不同payload，不将完整GM历史给玩家。
- 已记录攻击、防御/抵消结果、幸运重骰/翻转、伤害及护盾、主从资源、技能发动、
  状态/Modifier、咏唱支付/进度/解放/中断退款、场地、许可、位置与死亡等结果。
  attack_id关联攻击与伤害；battle_id关联战斗。闪避和瞬移失效不伪造伤害。
- 未知来源/目标身份及位置会被隐藏；普通旁观者只读事件与已知身份，不读数值。
  精确HP/护盾仅给受伤方及GM，技能/基础伤害仅给发动方及GM，骰值/资源等为私人。
  视野后续变化不重写旧战报，返回值均独立且JSON可序列化。
- `game/character_state.py`只读展示技能说明、usage、共享冷却、咏唱层数/成本、
  加符、护盾剩余值、持续Modifier、资源边界和互斥技能缓存；Session补充自有场地、
  待防御攻击和当前战斗阶段。敌方可见条目仍只提供身份/已知位置。
- runtime_available只表示次数/冷却/生命周期，不能替代决策合法性。事件限额
  由EventManager.component_limit_view读取；缺少匹配事件上下文时remaining为null。
  战斗次数在战斗外也为null，不能显示成自动重置；切换来回仍保留真实计数。
- Skill顶层可选description仅供显示；未提供时生成通用效果说明。对城伤害倍数
  提取为同源只读函数，帝政展示最终100MP/150伤害，计算行为不变。
- 修复FieldEffect与RealityMarble构造时深拷贝活角色/地点图的问题：定义数据仍复制，
  center/entrance/selected_targets保留对象身份，避免订阅会话后复制线程锁失败。
- 专项 `test_examples/test_session_reports.py` 共16项，默认与四个固定种子全量555项
  通过。字段及精确边界见SESSION_RUNTIME.md；原始样本保持不变。

### 10.8 已录入卡片最小实战（已完成）

用户同意继续后，采用实战优先，不泛化扩充关键词。新增
`test_examples/minimal_card_battle.py`，两组正式master_test_0/servant_test_0镜像卡
在同一节点开战，卡面HP、MP、技能保持原样，通过Session提交合法选项。

默认只固定战斗d10=5；先手仍正常重掷，避免镜像属性在固定骰下永远平局。
默认种子20261021跑完8回合，166次决策、17次攻击声明（16结算、1取消），两名
尼禄退场后御主停战，剧场正常清理。覆盖三件宝具、治疗、主从MP、通用濒死、
每人两次战斗续行和每人一次夕阳；再遇致命伤时脚本选择不再发动夕阳。

正常随机骰/种子1跑完10回合、218次决策，A方主从退场，B方主从存活，战斗
自然结束。验收随后停止会话，不代替圣杯胜利；回合上限或异常不算成功。
完整GM战报及决策保存在test_examples/results/，复现命令见README。

实战发现待结算攻击在死亡/退场清理时无战报结束记录，现用attack_cancelled补齐。
这只是观察层记录，不调用伤害或attack_resolved消耗，也不改原攻击resolved状态。
保留角色锁定的攻击不报取消，重复清理不重复报告。4项新测试位于
`test_examples/test_minimal_card_battle.py`，全量559项通过；未新增规则关键词。

## 11. 推荐实施顺序

### 阶段A：冻结基线（已完成）

1. 修复两项随机抵消测试，使原有483项默认测试稳定通过；
2. 增加一份当前测试基线记录；
3. 不改变规则行为。

### 阶段B：抽离通用循环（已完成）

1. 从 `TerminalGameRunner` 提取与终端无关的 `GameLoop`；
2. 终端版改为调用GameLoop，确保现有终端测试不变；
3. 不直接修改 TurnManager/BattleManager 的公开语义。

已新增6项GameLoop集成测试，全量489项通过，终端启动和两种退出路径已验证。

### 阶段C：建立Session与队列决策器（已完成）

1. 为角色建立稳定ID，不再以名字作为网络唯一标识；
2. DecisionRequest增加运行层request_id封装；
3. 实现QueueDecisionProvider；
4. 实现Session启动/输入/事件/结束；
5. 用两个模拟客户端完成一局自动测试。

已实现本机GameSession、QueuedDecisionProvider、稳定角色ID、按控制权过滤的快照/事件、结构化令咒与四种GM命令、协作停止及异常收尾。19项会话测试包括两个模拟客户端完成一局、决策日志回放、嵌套反应与战斗/幸运选择。全量508项通过；未引入网络框架或GUI。

### 阶段D：通用角色卡数据（已完成）

1. 建立CHARACTER_CARD_DATA和通用工厂；
2. 把Master_test_0迁移进去，保留兼容工厂或测试适配；
3. 录入一张中等复杂度Servant卡；
4. 验证宝具、主从MP、死亡和圣杯流程。

四项均已完成。已通过通用目录录入用户的Servant_test_0（Archer尼禄），补齐通用
保命、场地离场惩罚、自动/即时宝具及格挡穿透规则，完成主从MP、死亡与圣杯验证。
通用入口11项、尼禄20项专项通过，全量539项通过。

### 阶段E：Core / Skill Editor封装（已完成，等待人工测试）

用户选择“双击启动，使用现有Python”。根目录有Start_Core.cmd、Start_Skill_Editor.cmd，
也可使用python -m core --menu、python -m skilleditor。

- core是终端运行入口与规则API门面，所有规则实现集中于game/，使用game.*导入。
  人工测试提供两组正式卡直接对战、地图流程、双方分别选卡及原基础场景。
  用户独自回答双方所有选择；无自动对手策略。测试场景圣杯阈值为1、上限120回合。
- skilleditor是Tk窗口式JSON编辑器，支持固有技能、基础魔术、宝具、御主/从者卡的
  新建、复制、搜索、校验、保存、导入导出和恢复；现在也支持职介技能。
  首版没有将44个效果的字段全部制作成表单。
- core/catalog.py共享目录加载与严格校验，默认项目userdata/catalog.json只保存覆盖；
  内置数据与样本不改写。保存前校验全部目录与角色引用，原子替换、保留.bak并拒绝
  覆盖被其他编辑器改动的文件。实际运行期间的内容快照固定，不实时热更新。
- 每次人工测试写入userdata/runs/时间-标识，包含终端输入输出、逐条及汇总GM战报、
  最终状态、实际目录快照；异常时附error.txt。正常退出用quit，Ctrl+C也会汇总。
- 新增16项封装边界测试及7项职介编辑测试；11项Tk实际控件检查另行运行。
  完整全量五轮605项通过，32种子实战、目录/语法及终端退出通过。
- 职介项目条目格式为name与ranks，目录键就是职介技能名称，支持中文；ranks映射
  等级到组件列表。Core在目录作用域中适配为原CLASS_SKILL_DATA，再复用原装载器。
  全项目校验角色引用，阻止删除仍被引用的技能/等级，作用域退出恢复内置目录。
  旧四目录项目读取时仅在内存补齐class_skill，显式保存才写回且保留旧版.bak。
- Windows编辑器启动前设置Per-Monitor V2 DPI感知（旧系统降级），仅改善原生渲染。
  用户要求保持原字号与间距，因此已恢复JSON区Consolas 11、参考区微软雅黑UI 10、
  系统默认界面字体及原逻辑行高，不额外增加行间距。已打开窗口需重启，草稿先保存。
- 目录迁移后同步修改全部Python导入、测试替换路径、演示和文档引用；终端适配器与
  辅助菜单移入core，game不依赖core或skilleditor。新增两个独立包检查，确认不同
  子包首次导入均正常，不加载界面、不出现新旧命名空间的重复角色类。

## 12. 下一项具体任务建议

阶段A、B、C、D、结构化战报/状态、系统审计及两个启动入口已完成。
下一步由用户独自进行人工测试，并根据反馈逐次调整终端信息展示。使用说明见
MANUAL_TESTING.md。当前不需要新卡或新增人工裁定；不要在编辑器复制结算逻辑。

本轮新增23项自动测试：真实卡交叉分支15项、视野边界4项、MP战报对账4项。
修复抵消绕过次数/冷却/条件及咏唱要求、退款资源预检错误、隐蔽归队重复移除、
事件边界旧视野泄露和部分MP变化缺少战报。未新增关键词或更改用户既定裁定。

复现全部审计：`python test_examples/audit_test_suite.py`。汇总与两份完整GM实战
记录保存在 `test_examples/results/`；测试不等于所有未来卡片与人工操作均已覆盖。

接口与限制见 `SESSION_RUNTIME.md`，基线复现命令和验证结果见 `TEST_BASELINE_2026-10-21.md`。

## 13. 协作偏好

- 使用“你”，不要使用敬语。
- 遇到规则尚未决定且不同选择会显著改变结果时，先列出冲突和需要决定的边界，再写代码。
- 已明确规则应直接实现并测试，不必反复确认。
- 每次增加或改变Effect字段，必须同步更新 `game/skill/effect_dictionary.txt`。
- 优先增加通用接口，不为单张卡写无法复用的硬编码；确有卡片特例时应明确标注。
- 修改后进行对应专项测试，并尽可能运行全量测试。
- 系统测试已完成；用户现已要求并取得Core / Skill Editor双击启动版本，下一步
  由用户独自人工测试。预计会多次调整终端信息展示，按反馈在展示层修改。
- 不要把旧规则书与现行裁定的差异擅自“修正”回去。
- 用户新增范围约束：所有功能处理完成前不添加网络功能；后续聊天不反复提及，
  只有判断确实到适当接入阶段时再讨论。当前按本地功能继续推进。

## 14. 迁移验收标准

实际运行层的第一阶段完成，应至少满足：

1. `python main.py` 的终端玩法仍可运行；
2. 全部自动测试稳定通过；
3. 同一GameSession可以暂停在任意DecisionRequest；
4. 外部调用者可读取当前请求并提交一个结构化答案；
5. 不允许错误玩家替其他角色回答；
6. commandspell等即时操作可使当前选项刷新；
7. 游戏结束能输出 reason 和 winners；
8. GM能通过结构化接口执行现有四种强制命令；
9. GUI/服务端不复制行动合法性、伤害或战斗规则；
10. 可以用ScriptedDecisionProvider或模拟客户端重放一段确定流程。

达到这些条件后，Papermoon才真正从“完整终端规则引擎”迁移为“可承载客户端的实际运行内核”。

阶段C完成时，上述条件已通过本机接口与模拟客户端验证；即时命令支持的刷新窗口和当前视图范围以 `SESSION_RUNTIME.md` 为准。真实网络客户端尚未接入。
