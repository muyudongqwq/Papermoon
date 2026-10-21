"""Shared runtime context used by conditional Modifier queries."""

from dataclasses import dataclass, field


@dataclass
class ModifierContext:
    actor: object = None
    source: object = None
    target: object = None
    phase_scope: str | None = None
    phase: str | None = None
    action_id: str | None = None
    skill_id: str | None = None
    component_id: str | None = None
    damage_type: str | None = None
    battle: object = None
    position: object = None
    tags: set = field(default_factory=set)
    event: object = None

    def __post_init__(self):
        self.tags = set(self.tags or [])
        if self.battle is None:
            subject = self.actor or self.target
            self.battle = getattr(subject, "current_battle", None)
        if self.position is None:
            subject = self.target or self.actor
            self.position = getattr(subject, "position", None)
        if self.phase is None and self.battle is not None:
            self.phase = getattr(self.battle, "current_phase", None)
        if self.phase_scope is None:
            if self.phase and str(self.phase).startswith("simple_round"):
                self.phase_scope = "simple_round"
            elif self.battle is not None:
                self.phase_scope = "formal_battle"
            else:
                self.phase_scope = "non_battle"

    @classmethod
    def coerce(cls, context=None, **defaults):
        if isinstance(context, cls):
            values = {
                field_name: getattr(context, field_name)
                for field_name in cls.__dataclass_fields__
            }
            for key, value in defaults.items():
                if values.get(key) is None and value is not None:
                    values[key] = value
            return cls(**values)
        values = dict(context or {})
        for key, value in defaults.items():
            values.setdefault(key, value)
        known = {
            key: value
            for key, value in values.items()
            if key in cls.__dataclass_fields__
        }
        return cls(**known)

