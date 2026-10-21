"""将角色拥有的主动技能组件包装为统一行动。"""

from game.skill.skill_runtime import resolve_skill_component


class SkillAction:
    def __init__(self, actor, skill, component, target=None, input_values=None):
        self.actor = actor
        self.skill = skill
        self.component = component
        self.target = actor if component.get("target", "self") == "self" else target
        self.input_values = dict(input_values or {})
        self.component_id = component["component_id"]
        self.action_id = component.get(
            "_runtime_action_id",
            f"skill:{skill.skill_id}:{self.component_id}",
        )
        self.definition = component
        self.ap_cost = sum(
            cost.get("value", 0)
            for cost in component.get("cost", [])
            if cost.get("resource") == "action_point"
        )
        self.ap_layer = None
        self.game_turn = None
        self.game_manager = None
        self.defer_to_checkpoint = False
        self.checkpoint_pending = False
        self.checkpoint_result = None
        self.ignored = False
        self.ignored_reason = None
        self.virtual_attack_phase = False

    def resolve(self, decision_provider=None):
        return resolve_skill_component(
            self.actor,
            self.skill,
            self.component_id,
            target=self.target,
            decision_provider=decision_provider,
            input_values=self.input_values,
            turn_number=self.game_turn,
            action_id=self.action_id,
            phase=(
                f"AP{self.ap_layer}—{self.skill.name}"
                if self.ap_layer is not None
                else self.skill.name
            ),
            virtual_attack_phase=self.virtual_attack_phase,
            battle=getattr(self.actor, "current_battle", None),
            game_manager=self.game_manager or getattr(
                self.actor, "game_manager", None,
            ),
        )
