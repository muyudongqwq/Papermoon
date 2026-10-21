"""Runtime action grants created by the ``add_action`` skill effect."""

from copy import deepcopy

from game.skill.skill import Skill


class DynamicActionGrant:
    def __init__(
        self,
        owner,
        source_skill,
        definition,
        *,
        duration=None,
        applied_turn=0,
        remove_with_source=True,
    ):
        self.owner = owner
        self.source_skill = source_skill
        self.definition = deepcopy(definition)
        self.action_id = definition["action_id"]
        self.duration = duration
        self.applied_turn = int(applied_turn or 0)
        self.remove_with_source = bool(remove_with_source)
        self.active = True

        component = deepcopy(definition)
        component["component_id"] = f"dynamic_action:{self.action_id}"
        component["type"] = "active"
        component["_runtime_action_id"] = self.action_id
        component.pop("action_id", None)
        component.pop("description", None)
        component.pop("action_type", None)
        self.runtime_skill = Skill(
            definition["name"],
            getattr(source_skill, "rank_name", None) or "C",
            definitions=[component],
            skill_id=(
                f"dynamic_action:{source_skill.skill_id}:"
                f"{self.action_id}:{id(self)}"
            ),
            skill_category="dynamic_action",
        )
        self.runtime_skill.source_type = "dynamic_action"
        self.runtime_skill.granted_by = source_skill
        self.runtime_skill.dynamic_action_grant = self

    def update(self, turn_number):
        if not self.active or self.duration is None:
            return False
        if turn_number is not None and self.applied_turn == turn_number:
            return False
        self.duration -= 1
        return self.duration <= 0


def _find_action(owner, action_id):
    return next((
        grant
        for grant in owner.dynamic_actions
        if grant.active and grant.action_id == action_id
    ), None)


def remove_dynamic_action(owner, grant, *, reason="removed"):
    if not grant.active:
        return False
    grant.active = False
    if grant in owner.dynamic_actions:
        owner.dynamic_actions.remove(grant)
    if grant.runtime_skill in owner.dynamic_action_skills:
        owner.dynamic_action_skills.remove(grant.runtime_skill)

    # Objects explicitly tied to the granted action disappear with it. This
    # mirrors skill-source cleanup without treating the grant as a card skill.
    from game.skill.skill_runtime import _cleanup_skill_sources, remove_personal_skill

    removed_skills = []
    for skill in list(owner.personal_skills):
        if (
            getattr(skill, "granted_by", None) is grant.runtime_skill
            and getattr(skill, "remove_with_source", False)
        ):
            removed_skills.append(remove_personal_skill(
                owner,
                skill,
                reason="dynamic_action_source_removed",
            ))
    cleanup = _cleanup_skill_sources(owner, grant.runtime_skill)
    cleanup["skills"] = removed_skills
    grant.runtime_skill.removed = True
    return {
        "grant": grant,
        "reason": reason,
        "cleanup": cleanup,
    }


def grant_dynamic_action(
    owner,
    source_skill,
    definition,
    *,
    duration=None,
    duplicate_policy="reject",
    applied_turn=0,
    remove_with_source=True,
):
    from game.action.action_data import ACTION_DATA
    from game.skill.skill_runtime import SkillUnavailableError

    action_id = definition["action_id"]
    if action_id in ACTION_DATA:
        raise SkillUnavailableError(
            f"动态行动action_id不能覆盖基础行动：{action_id}"
        )
    existing = _find_action(owner, action_id)
    replaced = None
    if existing is not None:
        if duplicate_policy == "reject":
            raise SkillUnavailableError(f"角色已经拥有动态行动：{action_id}")
        replaced = remove_dynamic_action(
            owner,
            existing,
            reason="dynamic_action_replaced",
        )

    grant = DynamicActionGrant(
        owner,
        source_skill,
        definition,
        duration=duration,
        applied_turn=applied_turn,
        remove_with_source=remove_with_source,
    )
    owner.dynamic_actions.append(grant)
    owner.dynamic_action_skills.append(grant.runtime_skill)
    return {"grant": grant, "replaced": replaced}


def update_dynamic_actions(owner, *, turn_number=None):
    removed = []
    for grant in list(owner.dynamic_actions):
        if grant.update(turn_number):
            removed.append(remove_dynamic_action(
                owner,
                grant,
                reason="dynamic_action_expired",
            ))
    return removed


def remove_dynamic_actions_for_source(owner, source_skill):
    manager = getattr(owner, "game_manager", None)
    targets = [owner]
    if manager is not None:
        for character in (
            list(getattr(manager, "characters", []))
            + list(getattr(manager, "dead_characters", []))
        ):
            if character not in targets:
                targets.append(character)
    removed = []
    for target in targets:
        for grant in list(target.dynamic_actions):
            if (
                grant.source_skill is source_skill
                and grant.remove_with_source
            ):
                removed.append(remove_dynamic_action(
                    target,
                    grant,
                    reason="grant_source_removed",
                ))
    return removed
