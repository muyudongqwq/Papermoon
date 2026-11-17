"""Character-card point budgets from Servant 9.31 and Master 8.21.

The values intentionally live with the character editor.  They are code-side
rules for now, rather than user-configurable game settings.
"""

from dataclasses import dataclass


SERVANT_POINT_BUDGET = 45
MASTER_POINT_BUDGET = 30
PLUS_COST = 2

FIXED_RANK_COSTS = {"C": 1, "B": 2, "A": 3, "EX": 6}
CLASS_SKILL_COSTS = {"E": -2, "D": -1, "C": 1, "B": 2, "A": 3, "EX": 6}
PERSONAL_SKILL_COSTS = {"C": 1, "B": 2, "A": 4, "EX": 8}
NEGATIVE_SKILL_REFUNDS = {"D": 1, "E": 2}
NOBLE_PHANTASM_COSTS = {"C": 2, "B": 4, "A": 6, "EX": 12}


@dataclass(frozen=True)
class PointAssessment:
    points: int
    budget: int
    status: str
    gm_override: bool = False

    @property
    def importable(self):
        return self.status != "over"

    @property
    def remaining(self):
        return self.budget - self.points


def _rank_and_plus(value):
    if isinstance(value, str):
        return value, 0
    if isinstance(value, dict):
        return value.get("rank"), value.get("plus", 0)
    return None, 0


def _attribute_points(value):
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, dict):
        return value["value"] + value.get("plus", 0) * PLUS_COST
    raise ValueError("角色属性无法用于点数检定")


def _rank_points(value, costs, label, *, allow_plus=False):
    rank, plus = _rank_and_plus(value)
    if rank == "GM":
        return 0
    try:
        points = costs[rank]
    except KeyError as error:
        raise ValueError(f"{label}的{rank}等级没有点数定义") from error
    if plus:
        if not allow_plus:
            raise ValueError(f"{label}不支持加符计分")
        points += plus * PLUS_COST
    return points


def _selected_definitions(card, catalogs, category, field):
    catalog = catalogs[category]
    for key in card.get(field, []):
        try:
            yield catalog[key]
        except KeyError as error:
            raise ValueError(f"角色卡引用了不存在的{category}：{key}") from error


def _has_gm_rank(card, catalogs):
    fixed_field = "talent" if card.get("character_type") == "master" else "noble"
    if _rank_and_plus(card.get(fixed_field))[0] == "GM":
        return True
    if any(item.get("rank") == "GM" for item in card.get("class_skills", [])):
        return True
    for category, field in (
        ("personal_skill", "personal_skills"),
        ("basic_magic", "basic_magics"),
        ("noble_phantasm", "noble_phantasms"),
    ):
        if any(_rank_and_plus(definition.get("rank"))[0] == "GM"
               for definition in _selected_definitions(card, catalogs, category, field)):
            return True
    return False


def assess_character_points(card, catalogs):
    """Return the point state of one validated editor card.

    A GM rank in any selected, point-bearing rank field overrides the total and
    makes the card usable.  This does not alter the numeric total shown to the
    editor; it only changes the resulting status to ``valid``.
    """
    kind = card.get("character_type")
    if kind not in {"master", "servant"}:
        raise ValueError("点数检定只支持Master或Servant")
    budget = MASTER_POINT_BUDGET if kind == "master" else SERVANT_POINT_BUDGET
    gm_override = _has_gm_rank(card, catalogs)
    points = sum(_attribute_points(value) for value in card.get("attributes", {}).values())

    fixed_field = "talent" if kind == "master" else "noble"
    if _rank_and_plus(card.get(fixed_field))[0] != "GM":
        points += _rank_points(
            card.get(fixed_field),
            FIXED_RANK_COSTS,
            "天赋等级" if kind == "master" else "宝具适性",
            allow_plus=kind == "servant",
        )

    for item in card.get("class_skills", []):
        if item.get("rank") != "GM":
            points += _rank_points(
                item.get("rank"),
                CLASS_SKILL_COSTS,
                f"职介技能{item.get('name', '')}",
            )

    for definition in _selected_definitions(card, catalogs, "personal_skill", "personal_skills"):
        rank = _rank_and_plus(definition.get("rank"))[0]
        if rank == "GM":
            continue
        if definition.get("negative_skill") and rank in NEGATIVE_SKILL_REFUNDS:
            points -= NEGATIVE_SKILL_REFUNDS[rank]
        else:
            points += _rank_points(rank, PERSONAL_SKILL_COSTS, f"固有技能{definition.get('name', '')}")

    # Master 8.21 grants two basic magics without slot or point cost.  The
    # editor's existing selection validation remains independent of scoring.
    for definition in _selected_definitions(card, catalogs, "basic_magic", "basic_magics"):
        if _rank_and_plus(definition.get("rank"))[0] == "GM":
            gm_override = True

    noble_rank, _ = _rank_and_plus(card.get("noble"))
    for definition in _selected_definitions(card, catalogs, "noble_phantasm", "noble_phantasms"):
        rank = definition.get("rank", noble_rank)
        if rank != "GM":
            points += _rank_points(rank, NOBLE_PHANTASM_COSTS, f"宝具{definition.get('name', '')}")
            points += definition.get("rank_plus", 0) * PLUS_COST

    status = "valid" if gm_override or points == budget else "under" if points < budget else "over"
    return PointAssessment(points=points, budget=budget, status=status, gm_override=gm_override)


def describe_point_assessment(assessment):
    if assessment.gm_override:
        return f"GM等级：可用（当前计入{assessment.points}/{assessment.budget}点）"
    if assessment.status == "valid":
        return f"点数正好：{assessment.points}/{assessment.budget}"
    if assessment.status == "under":
        return f"尚余{assessment.remaining}点：{assessment.points}/{assessment.budget}"
    return f"超出{-assessment.remaining}点，不可导入：{assessment.points}/{assessment.budget}"
