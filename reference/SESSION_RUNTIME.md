# 本机 Session 运行层

阶段 C 已建立本机进程内的会话接口。每局游戏由一个工作线程运行现有同步规则
内核；决策队列在需要玩家选择时等待答案。当前没有 HTTP、WebSocket、端口监听、
远程连接或部署服务。

## 启动和决策

```python
from game.character.masters import Master
from game import GameManager, GameSession
from game.map.map import Location

location = Location("A")
actor = Master("Actor", 3, 3, 3, 3, 3, "C", 3)
actor.position = location
game = GameManager([actor], location, maximum_turns=1)
session = GameSession(game, {actor.character_id: "player-1"})
session.start()

cursor = 0
finished = False
try:
    while not finished:
        for event in session.get_events("player-1", after=cursor, timeout=1):
            cursor = event["sequence"]
            if event["type"] == "decision_requested":
                request = event["payload"]
                option = next(option for option in request["options"]
                              if option["label"] == "空过")
                session.submit_decision(
                    "player-1", request["request_id"], request["revision"],
                    option_id=option["option_id"],
                )
            elif event["type"] == "session_ended":
                finished = True
    assert session.join(2)
    assert session.get_snapshot("player-1")["result"] == {
        "reason": "turn_limit", "winners": [], "turn": 1,
    }
finally:
    session.stop()
    session.join(2)
```

`start()` 非阻塞且只能调用一次。会话状态为 `created`、`running`、`waiting`、
`completed`、`stopped` 或 `failed`。工作线程在任意普通、数值、反应、幸运和
援护选择处通过同一个决策器等待输入；调用者无需接触规则对象。

## ID、控制权和输入格式

- `character_id` 在角色创建时生成，角色改名、死亡或退场后保持不变，属性只读。
  这是当前运行对象的身份；存盘恢复及跨进程重建尚未实现。
- `controllers` 使用角色 ID 映射控制者 ID。可以分别分配主从；没有显式分配的
  从者继承御主的控制者，使魔继承召唤者，NPC 默认由 GM 控制。首次分配结果会
  保留，解除主从关系不会丢失玩家控制权。暂不提供运行中重新分配控制权的接口。
- 同名角色用不同 ID 区分。动态注册也拒绝重复 ID。
- 每个请求带 `session_id`、`request_id`、单调递增的 `revision`、控制者 ID、
  角色 ID、`phase`、`prompt`、`kind`、`allow_refresh` 和 `allow_cancel`。
- 选项只输出 `option_id` 和 `label`，真实角色、技能、行动及目标对象保留在内核。
  选项提交使用 `option_id`；数值请求输出 `minimum`/`maximum`，提交整数 `value`。
- 过期版本、错误请求 ID、重复提交、未知选项、越界数值及用布尔值冒充整数都会
  被拒绝；错误玩家不能回答别人的决策。GM 可以代答。
- `allow_cancel` 当前为 `False`。如果规则允许返回，会以普通选项提供。

控制者 ID 由可信的本地调用者提供；它本身不是登录凭据。未来网络适配器需要先
验证登录身份，再绑定对应控制者，不能直接信任客户端声明的控制者 ID。

## 读取快照和事件

- `get_pending_decision(controller_id)`：读取当前仍可提交的请求。其他玩家看不到
  这个请求；提交答案或排入即时操作后，旧请求立即停止接受答案。
- `get_snapshot(controller_id)`：返回最近一次决策/事件边界缓存的独立副本，包含
  会话、回合、AP、阶段、当前请求、受控角色、已知位置和可见战斗。
- 自己的角色包含精确 HP、MP、临时 MP、AP、属性、资源、技能和持续效果；可见敌方只提供
  身份和已知位置；未见角色不输出。GM 获得全部角色的精确状态。
- `get_events(controller_id, after=0, timeout=0)`：按全局事件序号读取事件；正数
  `timeout` 等待新事件。序号可能跳跃，因为私人事件已按控制权过滤。
- 输出均为 JSON 可序列化的数据；修改返回的字典不会修改游戏。

事件包括 `session_started`、`decision_requested`、`decision_answered`、
`decision_invalidated`、`operation_completed`、`operation_failed`、
`notification`、`rule_report` 和 `session_ended`。决策/操作/定向通知仅给对应玩家及 GM；会话
开始、结束和规则主动发布的公共通知为公共事件。

当前事件保存在进程内存中，可按游标重读。决策日志包含选项编号/数值，可将其
转换为 `ScriptedDecisionProvider` 指令重放确定流程。骰子随机流、持久化存档、
完整隐私情报系统仍待实现。核心战报已按下述接口接入；原有 `print()` 保留，
战报直接读取结算结果，不截取或解析标准输出。

## 结构化战报

`game/rule_report.py::RuleReportManager` 独立于技能触发队列，只记录结果，不发动
技能或请求选择。`GameManager.rule_reports.history` 是可信调用者可读取的完整
JSON记录，包含所有权限层，不应直接提供给玩家。Session启动时订阅新记录，
结束、停止或异常时解除订阅；启动前的记录不会按当前视野重新投递。

Session使用同一个事件流和游标输出 `type="rule_report"`，例如：

```json
{
  "sequence": 24,
  "session_id": "...",
  "type": "rule_report",
  "payload": {
    "report_id": 18,
    "kind": "damage_resolved",
    "turn": 1,
    "phase": "defense",
    "battle_id": "...",
    "actor": null,
    "targets": [{"character_id": "...", "name": "目标", "entity_type": "master"}],
    "position_id": "...",
    "data": {"attack_id": "...", "amount": 20, "damage_type": "magic", "hp_before": 90, "hp_after": 70, "hp_lost": 20, "shield_absorbed": 0}
  }
}
```

同一条结果对所有接收者使用相同sequence和report_id，但payload按权限投影：

- GM读取完整结果；角色控制者读取自己的技能、骰值、资源与状态详情。
- 伤害的施受双方可读伤害量、类型及命中/防御结果；精确HP和护盾吸收量只给
  受伤方及GM，技能ID和基础伤害只给发动方及GM。
- 可见旁观者只获得事件种类和已知角色，不获得伤害量、精确HP或技能详情；
  不可见的第三方不接收该结果。私人的资源、状态、掷骰和咏唱记录不发给旁观者。
- 未知来源角色使用actor=null，未知目标从targets省略；不泄露未知角色的名字、
  技能ID和位置。位置只有被允许知道时才提供，否则position_id=null。
- 过滤在记录发生时完成；后来发现角色不会补开旧记录。读取返回独立副本。

视野投影在事件发生时按当前位置、隐蔽、直接共享关系和有效感知重新只读计算，
不直接信任全局回合的旧缓存。瞬移离开视野不会泄露目的地；死亡角色不继续提供
观察视野。读取不会更新规则缓存、发现新地点或触发技能。

MP的 `resource_changed` 额外提供 `pool`（`mp`或`temporary_mp`），以便区分普通
与临时资源。主从共同支付按实际付款人分别记录；退款按原账本归还。临时MP发放、
支付、退款、到期清除，以及无御主维持费均记录实际变化，零变化不生成记录。
补齐旧代码中的直接MP赋值只增加展示战报，不额外发动资源事件或反应技能。

当前kind覆盖：

| 类别 | kind |
| --- | --- |
| 回合和战斗 | global_turn_start、global_turn_end、battle_declared、battle_joined、battle_left、battle_turn_start、battle_turn_end、battle_round_end、battle_ended |
| 行动和攻击 | action_resolved、attack_declared、attack_resolved、attack_cancelled、guard_started、roll_resolved、damage_resolved |
| 技能和状态 | skill_activated、skill_added、skill_removed、resource_changed、status_added、status_removed、modifier_applied、modifier_removed、modifier_refreshed、modifier_stacked |
| 咏唱和场地 | casting_started、casting_progressed、casting_released、casting_interrupted、field_created、field_removed、battle_exit_permission |
| 位置及离场 | position_left、position_entered、character_registered、character_despawned、character_died、grail_announced |

`data` 的常用字段：

- attack_declared/attack_resolved：attack_id关联同一次攻击，包含发动出口或命中、
  damage、defense_type、reason、剩余命中段和抵消量。闪避及瞬移失效也会记录，
  不产生虚构的伤害事件。援护可有多段结算，共用原攻击ID。
- attack_cancelled：死亡/退场或跳过防御时，被原有清理流程移除的未结算攻击，
  使用相同attack_id和reason关闭战报记录。不结算伤害、不消耗attack_resolved类
  Modifier，也不改写原攻击对象的resolved状态。被保留的角色锁定攻击不视为取消。
- damage_resolved：amount沿用引擎最终伤害值；hp_lost是前后HP差，二者在通用
  濒死、过量伤害等情形可能不同。attack_id为null时表示直接伤害。
- roll_resolved：初始/最终骰面、总值、加成、倍数、大成功/失败及重骰/翻转历史，
  仅骰子的控制者和GM读取。
- skill_activated：技能/组件ID、名称、发动类型、实际paid_costs与可变inputs；
  对主动、触发、反应及抵消发动采用同一记录方式。
- resource_changed：resource_id、old_value、new_value、change、operation、reason。
- casting_*：技能ID、层数或支付/退款量；battle_exit_permission提供allowed。

记录顺序表示实际结算完成顺序；嵌套反应、保命和死亡清理可以先于外层伤害完成。
report_id只标识结果，不用于回复决策。战报仍为内存记录，不是完整存盘或随机流。

## 角色详细状态

原有角色字段保留；以下新增字段仅出现在自己控制的角色及GM视图中：

- `card_id`、`servant_class`；`attribute_details`包含基础/有效值、显示Rank、
  剩余加符及容量；`combat`包含攻击/防御骰、ATK、攻击阶段、移动点、护盾、
  对魔力、幸运重骰及剩余通用濒死次数。
- `skills`分为class_skill、personal_skill、basic_magic、noble_phantasm，提供
  ID、名称、Rank、说明、负面标记、咏唱发动方式/范围/当前MP成本及components。
  对城宝具说明使用最终基础伤害，例如帝政显示100MP/150伤害。
- 每个component提供阶段、消耗、可变输入、效果说明、选择分支、咏唱层数要求、
  生命周期active、usage（scope/maximum/used/remaining）、cooldown
  （ready_turn/turns_remaining）和last_used_turn。相同冷却组读取共同就绪回合。
- `runtime_available/runtime_reasons`只说明次数、冷却及生命周期限制，不表示
  目标、资源或当前阶段必然合法。实际可用行动以DecisionRequest为准。
- `event_limit`展示trigger/react的事件限额。缺少当前匹配事件/目标上下文时，
  remaining=null、context_required=true，不伪造“本回合还可用”的结论。
  `usage.scope=battle`在战斗外used/remaining同样为null；新战斗使用新的计数。
- `casting`为null或当前技能、started_turn、continued_turn、layers、maximum_layers、
  paid_mp与activation_mode。paid_mp包括实际主从共同支付的总量。
- `modifiers`提供效果类型、说明、极性、当前值、剩余持续时间/消耗次数/阶段窗口、
  叠加数及可净化标记；护盾value为剩余护盾。`resource_details`补充自定义资源边界。
- `skill_sets`展示当前互斥技能包和已缓存技能包，切出的技能保留真实次数/冷却。
  `fields`展示自己建立的场地；`incoming_attacks`提供待防御攻击ID、类型、骰值与出口。
- 战斗条目增加稳定battle_id、当前阶段和可见的当前行动角色ID。

快照在决策、操作和战报事件边界更新。读取快照不会新建技能计数器、支付消耗或
触发规则。说明用于展示；现阶段不生成目标相关的“预计最终伤害”。

## 即时令咒和 GM 操作

只在 `allow_refresh=True` 的决策窗口接收即时操作，包括地图行动选择、受保护的
目标/路径选择、战斗攻击及防御选择。其余嵌套窗口需要先完成本次选择。
规则自行生成的技能输入、相遇及其他选择同样可以等待答案。

即时操作返回 `operation_id`，排入工作线程，随后通过事件返回结果。旧请求立即
失效；完成或拒绝操作后，内核重新生成请求和选项。外部线程不会直接修改角色。
操作如果触发反应技能，会产生嵌套决策，完成该决策后继续操作并刷新原选择。

令咒入口复用 `CommandSpellService`：

```python
operation_id = session.command_spell(
    "player-1", master_id=master_id, target_id=target_id, effect="mp",
)
```

`effect` 为 `mp`、`damage` 或 `teleport`；瞬移需传 `destination_id`，可额外传
`emergency_guard_target_id`，省略时不援护。位置 ID 来自快照。主从关系、令咒
费用、已见地点和援护资格由现有服务验证。不能使用其他玩家的御主令咒。

GM 入口复用 `GMCommandService`，对象通过 ID 解析，支持同名角色：

```python
session.gm_command("gm", "add_resource", target_id=target_id, resource="hp", amount=10)
session.gm_command("gm", "damage", target_id=target_id, damage_type=0, amount=10)
session.gm_command("gm", "teleport", target_id=target_id, destination_id=position_id)
session.gm_command("gm", "kill", target_id=target_id)
```

伤害类型编号沿用现有服务：0 为真实伤害，1 为物理，2 为魔术。普通玩家不能调用
GM 入口；操作结果只发给请求者与 GM。

## 结束和线程所有权

一局 GameManager 同时只能由一个 Session 运行。启动后使用 Session 接口提交
操作和读取缓存，不应从调用者线程直接读写规则对象。独立游戏可以创建独立会话。

`stop()` 请求协作停止，在等待选择或全局回合边界退出；它会结束这局运行，不能
恢复。`join(timeout)` 等待工作线程退出。正常结束输出 `reason`、胜者角色 ID
和 `turn`；取消原因为 `session_stopped`，未处理异常为 `session_error`，异常
详情仅供 GM 读取。视图构建错误也会关闭会话并发布结束事件。

## 验证

```powershell
python -m unittest discover -s test_examples -p "test_game_session.py"
python -m unittest discover -s test_examples -p "test_session_reports.py"
python -m unittest discover -s test_examples -p "test_*.py"
```

会话专项测试覆盖两个模拟客户端、答案校验、数值输入、快照过滤、停止/异常、
同名角色、三种令咒、四种 GM 命令、嵌套反应、动态召唤、路径刷新、战斗与幸运
窗口、胜者 ID、脚本回放及会话所有权。

战报与状态专项另有16项，覆盖实际伤害/护盾、骰值、闪避/瞬移失效、冷却组、
切换缓存、咏唱共同支付与退款、事件限额上下文、场地/死亡、隐私冻结、JSON副本、
异常解除订阅及真实御主与尼禄卡的完整会话和嵌套反应。

本轮新增23项：录卡交叉分支15项、事件边界可见性4项、MP战报对账4项。
完整审计可运行 `python test_examples/audit_test_suite.py`，详细结果见测试基线。
