# 通用角色卡入口

正式角色卡目录为 `game/character/card_data.py::CHARACTER_CARD_DATA`，统一创建入口为
`game/character/card_factory.py::create_character_from_card()`。当前支持御主和从者；
NPC、使魔继续使用各自的现有入口。

目前正式目录包含御主 `master_test_0` 和Archer尼禄 `servant_test_0`。
`create_master_test_0()` 仍可调用，并转发到通用入口。

## 使用

```python
from game.character import (
    create_character_from_card,
    get_character_card_definition,
    list_character_cards,
    validate_character_card_catalog,
)
from game.map.map import Location

validate_character_card_catalog()
assert "master_test_0" in list_character_cards(character_type="master")
actor = create_character_from_card("master_test_0", name="测试御主", position=Location("A"))
assert actor.card_id == "master_test_0"
definition = get_character_card_definition(actor.card_id)
assert definition["character_type"] == "master"
servant = create_character_from_card("servant_test_0", master=actor, position=actor.position)
assert servant.master is actor
assert len(servant.noble_phantasms) == 3
```

`card_id` 标识角色卡模板，`character_id` 标识实际创建的角色。使用同一张卡
创建多个角色时，模板ID相同，角色ID各不相同；技能、资源、加符、冷却和组件
状态分别保存。查询得到的定义也是独立副本，不会修改正式目录。

可选参数只有：

- `name`：覆盖展示名称，省略时使用卡中名称。
- `position`：指定初始 `Location` 或 `Road` 对象。
- `master`：仅供从者指定现有 `Master` 对象，通过原有主从服务绑定。

入口会先检查结构和内容引用，再建立初始位置/主从关系，依次装载职介技能、
固有技能、基础魔术和宝具。装载时的被动条件因此能看到初始上下文；底层装载
仍会进行原有校验。装载失败会移除新建角色的位置、主从及友军条目。

工厂不会自动加入GameManager，也不分配Session控制者。通常应在会话启动前创建
角色，再交给GameManager和GameSession；运行中动态加入仍须遵守工作线程的所有权。

## 数据格式

所有卡必须包含 `card_id`、`character_type`、`name` 和 `attributes`。
`card_id` 以小写字母开头，只含小写字母、数字和下划线，且必须与目录键一致。

基础属性必须完整提供 `strength`、`endurance`、`flexibility`、`magic`、`fortune`。
无加符时填写非负整数，有加符时填写对象，例如 `{"value": 5, "plus": 2}`。
加符范围沿用AttributeRank的0至2；布尔值、文本Rank及元组不作为卡片属性输入。

御主卡还必须包含：

- `talent`：天赋Rank，例如 `"A"`；沿用FixedRank规则，不允许加符。
- `command_spell`：初始令咒数量，非负整数。

从者卡还必须包含：

- `servant_class`：沿用现有职介名，例如 `"Saber"`、`"Caster"`。
- `noble`：宝具Rank，例如 `"A"` 或 `{"rank": "A", "plus": 1}`。
  加符限制及持有上限沿用现有规则：通常最多2件，有一个宝具加符时最多3件。

可选字段如下；省略内容列表时按空列表处理：

| 字段 | 内容 |
| --- | --- |
| `source` | 原始样本路径等来源说明，仅作记录 |
| `class_skills` | `[{"name": "对魔力", "rank": "B"}]`，引用职介技能库 |
| `personal_skills` | 固有技能目录ID列表 |
| `basic_magics` | 基础魔术目录ID列表，如 `["healing", "workshop"]` |
| `noble_phantasms` | 宝具目录ID列表，仅从者卡使用 |

使用Core内容项目时，`class_skills`也可引用Skill Editor创建的自定义职介技能。
职介目录按名称组织，每个条目的`ranks`保存各等级组件；卡片通过上述name、rank
选择一份定义。名称与等级缺失会拒绝保存，仍被引用的职介技能或等级不能删除。
项目覆盖仅在加载该项目的Core中生效，不改写内置职介技能数据。

同一初始卡不允许重复的skill_id，即使通过不同目录别名引用也会拒绝。未知字段、
缺失属性、错误Rank、未知内容和超出宝具上限均会报错。工厂沿用现有Rank/技能
规则，不额外按历史规则书计算总属性点或修改卡面效果。

下面是已录入尼禄卡的基础结构；完整内容引用以正式目录为准：

```json
{
  "card_id": "servant_test_0",
  "character_type": "servant",
  "name": "尼禄·克劳狄乌斯·凯萨·奥古斯都·日耳曼尼库斯",
  "source": "test_examples/samples/Servant_test_0.txt",
  "attributes": {
    "strength": 2,
    "endurance": 2,
    "flexibility": 5,
    "magic": 4,
    "fortune": 2
  },
  "servant_class": "Archer",
  "noble": {"rank": "A", "plus": 1},
  "class_skills": [],
  "personal_skills": [
    "servant_test_0:imperial_privilege",
    "servant_test_0:setting_sun",
    "servant_test_0:headache"
  ],
  "basic_magics": [],
  "noble_phantasms": [
    "servant_test_0:golden_theatre",
    "servant_test_0:original_fire",
    "servant_test_0:laus_saint_claudius"
  ]
}
```

## 尼禄卡的当前裁定与实现边界

- 皇帝特权在全局回合开始选择本回合能力，不占行动；同一场战斗切换来回仍保留
  剑术和战斗续行的已用次数。借用气息遮断A、单独行动A遵循现行职介库，单独
  行动A为无主时免维持消耗，不采用旧卡的“三天”。
- 保命按通用濒死、自动战斗续行、玩家选择其他保命的顺序。夕阳允许回血，HP
  最低为1直到真实全局回合末；第三次使用移除技能，当前回合保护仍然有效。
- 剧场支付40MP、咏唱1回合后自动展开，不消耗攻击阶段；持续至本场战斗结束。
  仅持有者不因格挡失败失去攻击阶段。任何活着的角色撤退、瞬移或隐蔽离场，
  均先由尼禄决定许可；拒绝时直接60点伤害，不提供闪避、格挡或抵消窗口。
  未指定伤害类型的这60点暂按物理伤害接入普通修正和护盾，不额外赋予穿盾。
- 原初之火为免费即时发动，每场3次，一回合基础攻击伤害+40；没有额外咏唱或
  解放行动。头痛只作用于带有mental标签的精神检定。
- 华丽帝政最终消耗100MP、咏唱1回合，消耗一个攻击阶段解放，对所选目标造成
  基础150魔术伤害；可闪避和抵消，忽略格挡减伤和护盾，仍受对魔力等修正。
  对城规则会翻倍，因此数据基础值为50MP/75伤害，避免重复翻倍。

叙述中的剧场视听遮蔽尚未增加独立感官系统；现阶段实现卡面“效果”段的机械
规则。样本中的攻击距离和最大捕捉人数未建立新数值体系，沿用现有战斗目标规则。
专项测试位于 `test_examples/test_servant_test_0_card.py`，覆盖主从支付、死亡/圣杯、
多种离场、致死中断与本机会话队列。原始样本保留，不会被自动改写。

## 录入下一张卡

1. 原始卡放在 `test_examples/samples/`。命名沿用 `Master_test_0.txt`、
   `Servant_test_0.txt`，对应目录ID为 `master_test_0`、`servant_test_0`。
2. 对照当前裁定，先将技能与宝具写入 `game/skill/content_data.py` 的对应目录；
   已有职介技能和基础魔术直接引用，不复制规则实现。
3. 在CHARACTER_CARD_DATA增加一条基础数据与内容引用，不增加专用工厂函数。
4. 运行目录校验、该卡专项测试和全量测试。新增或变更Effect字段时，仍必须
   同步更新 `game/skill/代码数据规范.txt`。

文本样本不会被工厂自动解析或执行；新文本放入samples也不会自动变为可运行卡。
正式宝具目录现有尼禄的3件宝具，工厂测试另有独立临时夹具用于校验通用格式。

```powershell
python -c "from character import validate_character_card_catalog; print(validate_character_card_catalog())"
python -m unittest discover -s test_examples -p "test_character_cards.py"
python -m unittest discover -s test_examples -p "test_servant_test_0_card.py"
python -m unittest discover -s test_examples -p "test_*.py"
```
