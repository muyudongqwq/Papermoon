"""Adapt live statuses to the existing event queue without adding card skills."""

from copy import deepcopy
from itertools import count

from game.skill.skill import Skill


_INSTANCE_IDS = count(1)


class StatusRuntime(Skill):
    def __init__(self, modifier, definition):
        self.instance_id = next(_INSTANCE_IDS)
        super().__init__(definition["name"], "C", definitions=definition["components"],
                         skill_id=f"status:{definition['status_id']}:{self.instance_id}",
                         description=definition.get("description", ""))
        self.source_type = "status"
        self.status_modifier = modifier
        self.status_id = definition["status_id"]
        self.origin_skill = getattr(modifier.source, "origin_skill", modifier.source)
        self.children = []

    def quota_key(self, owner, component):
        # Reapplication and multiple react components cannot reset the quota.
        if component["type"] == "react":
            return id(owner), self.status_id, "react"
        return (id(owner), self.status_id, id(self.status_modifier.source_actor),
                id(self.origin_skill), component["component_id"])

    def apply_passives(self):
        from game.modifier.modifier import create_modifier

        parent = self.status_modifier
        try:
            for component in self.definitions:
                if component["type"] != "passive":
                    continue
                for effect in component["effects"]:
                    child_effect = deepcopy(effect)
                    child_effect.update(purifiable=False, persist_after_death=parent.persist_after_death,
                                        stacking={"stacking_rule": "independent", "stack_scope": "independent",
                                                  "stack_count": parent.stack_count, "max_stacks": parent.max_stacks})
                    child = create_modifier(child_effect, parent.target, source=self,
                                            source_actor=parent.source_actor, source_type="status",
                                            source_id=self.skill_id)
                    child.status_parent = parent
                    result = parent.target.add_modifier(child)
                    if result:
                        self.children.append(result.modifier)
        except Exception:
            self.remove_passives()
            raise

    def remove_passives(self):
        for child in self.children[:]:
            self.status_modifier.target.remove_modifier(child)
        self.children.clear()

    def change_stacks(self, difference):
        for child in self.children:
            child.change_stack_count(self.status_modifier.stack_count + difference)


def iter_status_runtimes(character):
    for modifier in character.modifiers[:]:
        runtime = getattr(modifier, "status_runtime", None)
        if runtime is not None and modifier.applied:
            yield runtime


def status_view(modifier):
    runtime = modifier.status_runtime
    source = modifier.source_actor
    return {"instance_id": runtime.instance_id, "status_id": runtime.status_id,
            "name": modifier.name, "description": runtime.description,
            "source_character_id": getattr(source, "character_id", None),
            "source_name": getattr(source, "name", None),
            "source_skill_id": getattr(runtime.origin_skill, "skill_id", modifier.source_id),
            "duration": modifier.duration, "stack_count": modifier.stack_count,
            "polarity": modifier.polarity, "purifiable": modifier.purifiable}
