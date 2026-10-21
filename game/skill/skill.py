"""可由数据仓库装载的技能实例。"""

from copy import deepcopy

from game.rank.rank import SkillRank


VALID_SKILL_TYPES = {"active", "passive", "trigger", "react"}


class Skill:
    def __init__(
        self,
        name,
        rank,
        skill_type=None,
        effect=None,
        negative_skill=False,
        definitions=None,
        skill_id=None,
        casting=None,
        skill_category=None,
        description=None,
    ):
        self.name = name
        self.skill_id = skill_id or name
        self.rank = SkillRank(rank)
        self.rank_name = rank
        self.negative_skill = negative_skill
        self.source_type = "skill"
        self.skill_category = skill_category
        self.description = description
        self.casting = deepcopy(casting or {})
        # Runtime acquisition metadata.  Initial card skills keep these
        # defaults; add_skill fills them without changing the card schema.
        self.granted_by = None
        self.remove_with_source = False
        self.dynamic = False
        self.removed = False
        # Component lifecycles are runtime state, not card data.  Keeping the
        # expired identifiers on the skill instance lets one-shot triggers
        # survive across global turns without mutating their definitions.
        self.expired_component_ids = set()
        self.component_runtime_states = {}

        if definitions is None:
            if skill_type not in VALID_SKILL_TYPES:
                raise ValueError(f"未知的技能类型：{skill_type}")
            definitions = [{
                "type": skill_type,
                "target": "self",
                "effects": [effect] if effect is not None else [],
            }]
        self.definitions = deepcopy(definitions)
        for definition in self.definitions:
            if definition.get("type") not in VALID_SKILL_TYPES:
                raise ValueError(
                    f"未知的技能类型：{definition.get('type')}"
                )

        # 保留旧接口；复合技能以definitions为准。
        self.skill_type = skill_type
        self.effect = effect

    def is_component_active(self, component_id):
        return component_id not in self.expired_component_ids

    def expire_component(self, component_id):
        if component_id in self.expired_component_ids:
            return False
        self.expired_component_ids.add(component_id)
        return True

    def __str__(self):
        return f"{self.name} {self.rank}"
