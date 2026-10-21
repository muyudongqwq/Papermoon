from dataclasses import dataclass, field
from game.turn.damage_types import normalize_damage_type


@dataclass
class SimpleRoundEffect:
    """在指定阶段前插入一次可包含多名防守方的简易战斗轮。"""

    actor: object
    target: object
    trigger_phase: str
    attack_stat: str = "physical_attack"
    attack_roll_bonus: int = 0
    damage_value: object = None
    damage_value_source: str = None
    damage_attribute: str = None
    damage_multiplier: int | float = 1
    damage_flat: int | float = 0
    damage_type: str = "physical"
    resolution_channel: str = "attack"
    damage_percentage_modifiers: object = None
    damage_flat_modifiers: object = None
    skill: object = None
    source: object = None
    is_ambush: bool = False
    attack_mode: str = "fixed"
    consume_attack_phase: bool = False
    enter_battle: bool = False
    targets: list = field(default_factory=list)
    resolved: bool = False
    attack_event: object = None
    attack_events: list = field(default_factory=list)
    defense_order: list = field(default_factory=list)
    completed_defenders: set = field(default_factory=set)
    used_guarders: set = field(default_factory=set)
    defender_positions: dict = field(default_factory=dict)

    effect_type = "add_simple_round"

    def __post_init__(self):
        if not self.targets:
            self.targets = [self.target]
        self.targets = list(dict.fromkeys(self.targets))
        if self.attack_mode not in {"fixed", "select"}:
            raise ValueError(
                f"未知的简易战斗轮攻击模式：{self.attack_mode}"
            )

    @classmethod
    def from_effect(cls, effect, actor, target):
        data = effect.get("effect_data", {})
        trigger_phase = data.get("trigger_phase")
        if not trigger_phase:
            raise ValueError("add_simple_round必须定义trigger_phase")

        attack_stat = data.get("attack_stat", "physical_attack")
        default_damage_type = (
            "magic" if attack_stat == "magic_attack" else "physical"
        )
        defenders = list(target) if isinstance(target, (list, tuple, set)) else [target]
        defenders = list(data.get("targets", defenders))
        if not defenders:
            raise ValueError("add_simple_round至少需要一名防守方")
        trigger_target = data.get("trigger_target", defenders[0])
        if trigger_target == "actor":
            trigger_target = actor
        elif trigger_target in {"target", "first_defender"}:
            trigger_target = defenders[0]
        return cls(
            actor=actor,
            target=trigger_target,
            trigger_phase=trigger_phase,
            attack_stat=attack_stat,
            attack_roll_bonus=data.get("attack_roll_bonus", 0),
            damage_value=data.get("damage_value"),
            damage_value_source=data.get("damage_value_source"),
            damage_attribute=data.get("damage_attribute"),
            damage_multiplier=data.get("damage_multiplier", 1),
            damage_flat=data.get("damage_flat", 0),
            damage_type=normalize_damage_type(
                data.get("damage_type", default_damage_type)
            ),
            resolution_channel=data.get("resolution_channel", "attack"),
            damage_percentage_modifiers=list(
                data.get("damage_percentage_modifiers", [])
            ),
            damage_flat_modifiers=list(
                data.get("damage_flat_modifiers", [])
            ),
            skill=data.get("skill"),
            source=data.get("source"),
            is_ambush=data.get("is_ambush", False),
            attack_mode=data.get("attack_mode", "fixed"),
            consume_attack_phase=data.get("consume_attack_phase", False),
            enter_battle=data.get("enter_battle", False),
            targets=defenders,
        )


def create_battle_effect(effect, actor, target):
    effect_type = effect.get("effect_type")
    if effect_type == "add_simple_round":
        return SimpleRoundEffect.from_effect(effect, actor, target)
    raise ValueError(f"未知的战斗效果：{effect_type}")
