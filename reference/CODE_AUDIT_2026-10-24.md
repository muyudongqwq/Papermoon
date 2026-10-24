# Papermoon 代码审计记录（2026-10-24）

## 协作边界

- `PapermoonCoreDeveloper2.0` 继续负责编辑器、UI、打包和新功能。
- 本线程负责规则引擎审计、回归测试、生命周期与并发安全。
- 共享高冲突文件在修改前协调：`game/skill/skill_runtime.py`、`game/modifier/modifier_manager.py`、`game/skill/effect_validation.py`、`core/catalog.py`以及两份 effect dictionary。

## 基线

- Git 基线提交：`79ea7ac`。
- 全量自动测试：审计开始时 745 项；三批修复后 750 项通过。
- 源码 Tk 冒烟：124 项通过（需正常 Windows 桌面权限）。
- 费用、咏唱、抵消、MP 账本定向测试：57 项通过。
- `game`、`core`、两个编辑器与 `skilleditor` 全部通过 `compileall`。

## 已确认问题

### A1：状态免疫在自身生效期间存在同步重入窗口

严重度：高。已修复。

`ModifierManager._apply_new()` 先调用 `modifier.apply()`，再把父 `add_status` modifier 加入角色列表。但 `StatusModifier` 的 apply 过程会立即安装 passive 子 modifier，子 modifier 又会同步发出 `modifier_applied`事件。

`StatusImmunityModifier.blocks()` 同时要求：

- 子免疫已 applied；
- 父状态已 applied；
- 父状态已在 `target.modifiers` 中。

因此，若 `modifier_applied` 触发器在免疫状态安装途中同步施加减益，第一次减益会穿透。最小复现已确认：`poison_present=True`，3 次免疫仅剩 2 次。

已按事务原则修复：父状态在 passive 子 modifier 安装前即预注册且可见；同步回调若消耗或移除父状态，安装会终止并清理之后才返回的子 modifier。新增两项回归测试，分别覆盖多次免疫与“唯一一次免疫在安装中即被消耗”的边界。

### A2：两个独立编辑器进程同时保存时可能静默覆盖

严重度：高。已修复。

`CatalogProject.save()` 使用“读当前文件→与 `_saved_bytes` 比较→写临时文件→`os.replace`”。`_CATALOG_LOCK` 只是进程内 `RLock`，不能协调 SkillEditorClient 与 CharacterEditorClient 这两个独立 EXE。

两个进程可同时读到相同旧版本，同时通过冲突检查，然后先后 replace；后者会覆盖前者，且不会报错。现有测试只覆盖“先后保存”，没有覆盖真正同时保存。

已使用 Python 标准库实现跨进程独占锁，并将“重读、比较、备份、replace”包含在同一临界区。锁在进程退出时由操作系统释放，等待超时会返回明确错误。新增的 spawn 子进程测试强制建立并发时间窗口，确认后写入者等待锁后会检测版本冲突，不会覆盖新文件。

### A3：GameSession 工作线程非 Exception 退出会泄漏会话所有权

严重度：中。已修复。

原 `_run()` 仅捕获 `Exception`。若引擎边界抛出 `SystemExit` 等 `BaseException`，`finally` 会访问尚未赋值的 `final_state`，导致 `UnboundLocalError`：线程已死亡，但会话仍显示 `running`，`GameManager._active_session` 仍被占用。`Thread.start()` 自身失败也有同类所有权泄漏。

已完成：

- 工作线程边界预先建立安全结果，并捕获 `BaseException` 进入失败收尾。
- `Thread.start()` 失败时回滚订阅、线程引用、会话状态与 GameManager 所有权。
- 新增 2 项回归测试；`test_game_session` 共 21 项通过。

## 未发现明确缺陷的部分

### 重复与逻辑冗余审阅

后续等价重构将数值 Modifier 中重复的目标字段读取，以及
`attack_bonus`、`magic_resistance`、`movement_point_bonus`、`visibility_bonus`
四类效果完全相同的“施加/撤销/层数变化”生命周期收敛到两个内部基类。
同时移除了 HiddenModifier 对基类空实现的重复覆盖，并简化可选消耗的空 `pass`
分支。公开类名、effect ID、数据格式和运行顺序均未变更。

静态精确重复扫描后，规则代码仅剩 FixedRank/NobleRank 两个三行展示函数相同；
抽象它们不会减少复杂度，因此保留。战斗、目标与行动中的长函数虽仍较大，但它们依赖严格的阶段顺序和
中间状态；本轮未为形式上的短小强行拆分。重构后 160 项 Modifier 相关定向测试、750 项全量自动测试与
124 项源码 Tk 冒烟全部通过。

### 费用、咏唱和退费链

定向审计与 57 项测试表明，当前链条已覆盖：

- activation、casting_start、maintenance 时机分离；
- 预付咏唱费用不重复扣除；
- Servant/Master/临时 MP 多池支付账本；
- 中断按原支付者退还；
- 零咏唱、抵消解放、切换咏唱和死亡支付者边界。

本轮没有发现可复现的重复扣费或退费重复问题。`skill_runtime.py` 体积很大，但在功能分支仍活跃时不建议做大规模拆分。

## 建议的后续批次

1. 由功能线重建两个 EXE，再运行双 EXE 安装诊断；现有 EXE 是修复前构建，本轮不把它的结果当作新代码验证。
2. 等功能线稳定后，再将 `skill_runtime.py` 按“目标/费用/攻击构建/效果执行”边界做小步拆分，每次拆分都保持全量测试为绿。
