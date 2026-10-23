from game.rank.rank import AttributeRank
from game.modifier.modifier import create_modifier
from game.modifier.modifier_manager import ModifierManager
from game.resource.resource import ResourceManager
from uuid import uuid4
class Character:
    ATTRIBUTE_NAMES = (
        "strength",
        "endurance",
        "flexibility",
        "magic",
        "fortune",
    )
    DERIVED_STAT_NAMES = (
        "physical_attack",
        "magic_attack",
        "dodge",
        "block",
        "offset",
        "perceive",
        "hide",
        "escape",
    )

    def __init__(self, name, strength, endurance, flexibility, magic, fortune):
        self._character_id = uuid4().hex
        self.name = name
        self.strength = AttributeRank(strength)
        self.endurance = AttributeRank(endurance)
        self.flexibility = AttributeRank(flexibility)
        self.magic = AttributeRank(magic)
        self.fortune = AttributeRank(fortune)
        self._plus_hpmax_bonus = 0
        self._plus_mpmax_bonus = 0
        self._active_attribute_plus_uses = {
            name: 0 for name in self.ATTRIBUTE_NAMES
        }
        self._in_battle = False
        #获取筋敏耐等基础属性

        self.basic_properties()
        self.hp = self.hpmax
        self.mp = self.mpmax
        #将初始状态设置为满

        self.bonus()
        self.init_luck()
        self.action_point = 2
        self.movement_point = 0
        #此处定义战斗开始时资源和回合资源
        self.brink_of_death_counter = 1
        #这是濒死计数器

        #初始化所有状态
        self.buffs = []
        self.debuffs = []
        self.personal_skills = []
        # Permanent card effects may grant content that can no longer be
        # removed, or erase content that can no longer be reacquired.
        self.permanently_gained_content = set()
        self.permanently_lost_content = set()
        self.dynamic_actions = []
        self.dynamic_action_skills = []
        # Stateful progress created by the ``growing`` effect. Keys include
        # the concrete source-skill identity, so two same-named skills never
        # share progress accidentally.
        self.growth_states = {}
        self.status_flags = set()
        self.status_sources = {}
        self.allies = set()
        self.attitudes = {}
        self.ally_sources = {}
        self.modifiers = []
        self.modifier_manager = ModifierManager(self)
        self.resource_manager = ResourceManager(self)
        # 兼容直观读取；资源变化仍应通过resource_manager或下方统一接口。
        self.resources = self.resource_manager.resources
        self.pending_attacks = []
        # Command-spell resources are deliberately separate from ordinary MP.
        # They are spent first and never increase mpmax.
        self.temporary_mp = 0
        self.temporary_mp_waits_for_personal_turn_end = False
        self.command_spell_damage_bonus = 0
        # Permanent memory used by command-spell teleportation.  Unlike
        # perceived/revealed positions, entries here must have belonged to
        # this character's real (possibly shared) vision at least once.
        self.seen_locations = set()
        self.shield = 0
        self.atk_bonus = 0
        self._position = None
        self.attack_phase_count = 1
        # 每个援护阶段最多选择的目标数；技能可通过数值Modifier修改。
        self.guard_target_limit = 1
        self.guard_opportunity_available = True
        self.block_resistance = 0.5
        self.magic_resistance = 0
        self.game_manager = None
        self.entity_type = "character"
        self.is_familiar = False
        self.controller = self
        self.summoner = None
        self.familiars = []
        self.registration_index = None
        self.registered_turn = None
        self.activation_turn = 0
        self.initiative_snapshot = None
        self.despawn_reason = None
        self.death_location = None
        self.travel_group = None
        self.ride_group = None
        self.carried_by = None
        self.carry_capacity = 0
        self.casting_state = None

        self.visibility = 0
        self.own_visible = []
        self.shareable_own_visible = []
        self.shared_visible = []
        self.any_visible = []
        self.own_perceived = []
        self.shared_perceived = []
        self.perceived = []
        self.investigated_statuses = {}
        self.revealed_positions = {}
        self.insight_reports = []
        self.encountered_this_turn = set()
        # A non-battle attack exposes presence concealment only to the
        # attacked characters until the next global turn.
        self.presence_concealment_exposed_to = set()

        self.in_battle = False
        self.current_battle = None
        self.movement_locked = False
        self.movement_lock_layer = None
        self.movement_lock_source = None
        self.current_global_turn = 0
        self.last_escape_turn = None
        self.forced_move_turn = None
        self.ap1_forfeited_turn = None
        self.is_npc = False
        #是否战斗中？处于哪一场战斗中？
        self.last_defense_attack_count = 0
        self.last_defense_hit_count = 0
        self.last_defense_total_damage = 0

    @property
    def character_id(self):
        """Stable runtime identity, independent of display name or controller."""
        return self._character_id

    def basic_properties(self): pass

    @property
    def hpmax(self):
        contextual = 0
        if hasattr(self, "modifier_manager"):
            contextual = self.modifier_manager.get_contextual_bonus(
                "attribute_bonus",
                effect_target="endurance",
                actor=self,
            )
        return max(
            1,
            (self.endurance.value + contextual) * 30
            + self._plus_hpmax_bonus
        )

    @property
    def mpmax(self):
        contextual = 0
        if hasattr(self, "modifier_manager"):
            contextual = self.modifier_manager.get_contextual_bonus(
                "attribute_bonus",
                effect_target="magic",
                actor=self,
            )
        return max(
            1,
            (self.magic.value + contextual) * 30
            + self._plus_mpmax_bonus
        )

    @property
    def in_battle(self):
        return self._in_battle

    @in_battle.setter
    def in_battle(self, value):
        value = bool(value)
        if value and getattr(self, "resting", False):
            self.cancel_rest()
        if value and not getattr(self, "_in_battle", False):
            if hasattr(self, "status_flags"):
                self.remove_hidden(reason="battle_entry")
            if hasattr(self, "ride_group"):
                self.detach_ride_group()
        if getattr(self, "_in_battle", False) and not value:
            self.clear_battle_plus_effects()
            self.modifier_manager.remove_battle_phase_windows()
            battle = getattr(self, "current_battle", None)
            if battle is not None:
                for participant in battle.participants[:]:
                    if participant is self:
                        continue
                    participant.modifier_manager.remove_battle_phase_windows_owned_by(
                        self
                    )
        self._in_battle = value
        self.refresh_brink_of_death_availability()
        game_manager = getattr(self, "game_manager", None)
        transfer_manager = getattr(
            game_manager,
            "command_spell_transfer_manager",
            None,
        )
        if transfer_manager is not None:
            transfer_manager.on_battle_state_changed(self, value)

    @property
    def atk(self):
        return self.strength.value * 10 + self.atk_bonus
    #初始化血量，魔力和ATK，默认为*10
    
    def bonus(self):
        self._derived_manual_adjustments = {
            name: 0 for name in self.DERIVED_STAT_NAMES
        }
        self._derived_modifier_bonuses = {
            name: 0 for name in self.DERIVED_STAT_NAMES
        }
        self.dice_bonus = 0

    def _derived_base_value(self, name):
        formulas = {
            "physical_attack": self.strength.value + self.flexibility.value,
            "magic_attack": self.magic.value * 2,
            "dodge": self.flexibility.value * 2,
            "block": self.strength.value * 2,
            "offset": self.fortune.value * 2,
            "perceive": self.fortune.value * 2,
            "hide": self.flexibility.value,
            "escape": self.strength.value * 2,
        }
        return formulas[name]

    def get_effective_attribute_value(self, name, context=None):
        if name not in self.ATTRIBUTE_NAMES:
            raise ValueError(f"未知的角色属性：{name}")
        value = getattr(self, name).value
        value += self.modifier_manager.get_contextual_bonus(
            "attribute_bonus",
            effect_target=name,
            context=context,
            actor=self,
        )
        return max(0, value)

    def get_effective_derived_stat(self, name, context=None):
        if name not in self.DERIVED_STAT_NAMES:
            raise ValueError(f"未知的派生骰属性：{name}")
        attributes = {
            attribute: self.get_effective_attribute_value(attribute, context)
            for attribute in self.ATTRIBUTE_NAMES
        }
        formulas = {
            "physical_attack": attributes["strength"] + attributes["flexibility"],
            "magic_attack": attributes["magic"] * 2,
            "dodge": attributes["flexibility"] * 2,
            "block": attributes["strength"] * 2,
            "offset": attributes["fortune"] * 2,
            "perceive": attributes["fortune"] * 2,
            "hide": attributes["flexibility"],
            "escape": attributes["strength"] * 2,
        }
        return (
            formulas[name]
            + self._derived_manual_adjustments.get(name, 0)
            + self._derived_modifier_bonuses.get(name, 0)
        )

    def get_effective_atk(self, context=None):
        return (
            self.get_effective_attribute_value("strength", context) * 10
            + self.atk_bonus
            + self.modifier_manager.get_contextual_bonus(
                "attack_bonus",
                context=context,
                actor=self,
            )
        )

    def get_effective_move_conversion(self, context=None, ap_layer=None):
        if context is None:
            context = {
                "actor": self,
                "phase_scope": "non_battle",
                "phase": f"AP{ap_layer}" if ap_layer else None,
                "action_id": "move",
                "tags": {"movement"},
            }
        return self.move_conversion + self.modifier_manager.get_contextual_bonus(
            "movement_point_bonus",
            context=context,
            actor=self,
        )

    def get_effective_visibility(self, context=None):
        return self.visibility + self.modifier_manager.get_contextual_bonus(
            "visibility_bonus",
            context=context,
            actor=self,
        )

    def sync_contextual_capacities(self, old_hpmax, old_mpmax, old_luck_max):
        if hasattr(self, "hp") and self.hpmax != old_hpmax:
            if self.has_status("dead"):
                self.hp = 0
            else:
                self.hp = min(
                    self.hpmax,
                    max(1, self.hp + self.hpmax - old_hpmax),
                )
        if hasattr(self, "mp") and self.mpmax != old_mpmax:
            self.mp = min(
                self.mpmax,
                max(1, self.mp + self.mpmax - old_mpmax),
            )
        if (
            hasattr(self, "luck_reroll")
            and self.luck_reroll_max != old_luck_max
        ):
            self.luck_reroll = min(
                self.luck_reroll_max,
                max(
                    0,
                    self.luck_reroll
                    + self.luck_reroll_max
                    - old_luck_max,
                ),
            )

    def _get_derived_stat(self, name):
        return (
            self._derived_base_value(name)
            + self._derived_manual_adjustments.get(name, 0)
            + self._derived_modifier_bonuses.get(name, 0)
        )

    def _set_derived_stat(self, name, value):
        if not isinstance(value, (int, float)):
            raise TypeError(f"{name}必须是数字")
        modifier_bonus = self._derived_modifier_bonuses.get(name, 0)
        self._derived_manual_adjustments[name] = (
            value - self._derived_base_value(name) - modifier_bonus
        )

    def adjust_derived_modifier(self, name, amount):
        if name not in self.DERIVED_STAT_NAMES:
            raise ValueError(f"未知的派生骰属性：{name}")
        self._derived_modifier_bonuses[name] += amount
        return self._get_derived_stat(name)

    @property
    def physical_attack(self):
        return self._get_derived_stat("physical_attack")

    @physical_attack.setter
    def physical_attack(self, value):
        self._set_derived_stat("physical_attack", value)

    @property
    def magic_attack(self):
        return self._get_derived_stat("magic_attack")

    @magic_attack.setter
    def magic_attack(self, value):
        self._set_derived_stat("magic_attack", value)

    @property
    def dodge(self):
        return self._get_derived_stat("dodge")

    @dodge.setter
    def dodge(self, value):
        self._set_derived_stat("dodge", value)

    @property
    def block(self):
        return self._get_derived_stat("block")

    @block.setter
    def block(self, value):
        self._set_derived_stat("block", value)

    @property
    def offset(self):
        return self._get_derived_stat("offset")

    @offset.setter
    def offset(self, value):
        self._set_derived_stat("offset", value)

    @property
    def perceive(self):
        return self._get_derived_stat("perceive")

    @perceive.setter
    def perceive(self, value):
        self._set_derived_stat("perceive", value)

    @property
    def hide(self):
        return self._get_derived_stat("hide")

    @hide.setter
    def hide(self, value):
        self._set_derived_stat("hide", value)

    @property
    def escape(self):
        return self._get_derived_stat("escape")

    @escape.setter
    def escape(self, value):
        self._set_derived_stat("escape", value)

    def init_luck(self):
        self.luck_reroll = self.luck_reroll_max
        #幸运E时没有重骰，DCBA对应0123，如果大于A则继续上升

    @property
    def luck_reroll_max(self):
        contextual = 0
        if hasattr(self, "modifier_manager"):
            contextual = self.modifier_manager.get_contextual_bonus(
                "attribute_bonus",
                effect_target="fortune",
                actor=self,
            )
        return max(self.fortune.value + contextual - 2, 0)

    @property
    def can_critical_success(self):
        return self.fortune.value >= 2

    @property
    def can_critical_failure(self):
        return True

    def adjust_attribute_modifier(self, attribute_name, amount):
        if attribute_name not in self.ATTRIBUTE_NAMES:
            raise ValueError(f"未知的角色属性：{attribute_name}")
        attribute = getattr(self, attribute_name)
        old_hpmax = self.hpmax
        old_mpmax = self.mpmax
        old_luck_max = self.luck_reroll_max
        effective_delta = attribute.adjust_modifier_bonus(amount)

        if attribute_name == "endurance" and hasattr(self, "hp"):
            hp_delta = self.hpmax - old_hpmax
            if not self.has_status("dead"):
                self.hp = min(self.hpmax, max(1, self.hp + hp_delta))
        elif attribute_name == "magic" and hasattr(self, "mp"):
            mp_delta = self.mpmax - old_mpmax
            self.mp = min(self.mpmax, max(0, self.mp + mp_delta))
        elif attribute_name == "fortune" and hasattr(self, "luck_reroll"):
            luck_delta = self.luck_reroll_max - old_luck_max
            self.luck_reroll = min(
                self.luck_reroll_max,
                max(0, self.luck_reroll + luck_delta),
            )
        return effective_delta

    def use_luck_reroll(self):
        if self.luck_reroll <= 0: return False
        self.luck_reroll -=1 
        return True
        #检查还能不能用幸运重骰

    def start_battle(self):
        travel_group = self.travel_group
        if travel_group is not None:
            travel_group.dissolve()
        self.detach_ride_group()
        self.remove_hidden(reason="battle_entry")
        self.clear_battle_plus_effects()
        self.luck_reroll=self.luck_reroll_max
        self.reset_attribute_pluses()
        self.in_battle = True
        #重置幸运重骰次数，进入战斗。

    def reset_attribute_pluses(self):
        for attribute_name in self.ATTRIBUTE_NAMES:
            getattr(self, attribute_name).reset_plus()

    def use_attribute_plus(self, attribute_name, allow_out_of_battle=False):
        """Consume and apply one battle plus; fortune is resolved by RollResolver."""
        if (
            (not self.in_battle and not allow_out_of_battle)
            or attribute_name == "fortune"
        ):
            return False
        if not self.consume_attribute_plus(attribute_name):
            return False
        self._active_attribute_plus_uses[attribute_name] += 1
        uses = self._active_attribute_plus_uses[attribute_name]
        if attribute_name in {"strength", "flexibility"}:
            getattr(self, attribute_name).temporary_multiplier = uses + 1
        elif attribute_name == "endurance":
            self._plus_hpmax_bonus += 60
            if not self.has_status("dead"):
                self.hp = min(self.hpmax, self.hp + 60)
        elif attribute_name == "magic":
            self._plus_mpmax_bonus += 60
            self.mp = min(self.mpmax, self.mp + 60)
        return True

    def clear_battle_plus_effects(self):
        """Remove temporary plus benefits without restoring spent pluses."""
        hp_bonus = self._plus_hpmax_bonus
        mp_bonus = self._plus_mpmax_bonus
        self.strength.temporary_multiplier = 1
        self.flexibility.temporary_multiplier = 1
        self._plus_hpmax_bonus = 0
        self._plus_mpmax_bonus = 0
        self._active_attribute_plus_uses = {
            name: 0 for name in self.ATTRIBUTE_NAMES
        }
        if hasattr(self, "hp"):
            if self.has_status("dead"):
                self.hp = 0
            else:
                self.hp = min(self.hpmax, max(1, self.hp - hp_bonus))
        if hasattr(self, "mp"):
            self.mp = min(self.mpmax, max(0, self.mp - mp_bonus))

    def consume_attribute_plus(self, attribute_name, amount=1):
        if attribute_name not in self.ATTRIBUTE_NAMES:
            raise ValueError(f"未知的角色属性：{attribute_name}")
        return getattr(self, attribute_name).consume_plus(amount)

    def restore_attribute_plus(self, attribute_name, amount=1):
        if attribute_name not in self.ATTRIBUTE_NAMES:
            raise ValueError(f"未知的角色属性：{attribute_name}")
        return getattr(self, attribute_name).restore_plus(amount)

    def reset_turn(self):
        self.action_point = 2
        self.movement_point = 0
        self.attack_phase_count = 1
        self.guard_opportunity_available = True
        self.clear_movement_lock()
        self.presence_concealment_exposed_to.clear()

    def get_presence_concealment(self):
        modifiers = [
            modifier
            for modifier in self.modifiers
            if modifier.applied
            and modifier.effect_type == "presence_concealment"
        ]
        if not modifiers:
            return None
        return max(
            modifiers,
            key=lambda modifier: (
                getattr(modifier, "strength_priority", 0) or 0,
                getattr(modifier, "value", 0),
            ),
        )

    def has_investigation_immunity(self):
        concealment = self.get_presence_concealment()
        return bool(
            concealment is not None
            and concealment.investigation_immunity
        )

    def blocks_perception_while_actively_hidden(self):
        concealment = self.get_presence_concealment()
        return bool(
            self.has_status("hidden")
            and concealment is not None
            and concealment.active_hide_perception_immunity
        )

    def is_presence_concealed_from(self, observer):
        """Whether passive presence concealment blocks this observer."""
        if observer is self or self.in_battle:
            return False
        if self.get_presence_concealment() is None:
            return False
        if observer in self.presence_concealment_exposed_to:
            return False
        return True

    def is_concealed_from(self, observer):
        hidden_modifiers = [
            modifier
            for modifier in self.modifiers
            if modifier.applied
            and getattr(modifier, "status", None) == "hidden"
        ]
        if hidden_modifiers:
            actively_hidden = any(
                getattr(modifier, "conceals_from", lambda _observer: True)(
                    observer
                )
                for modifier in hidden_modifiers
            )
        else:
            actively_hidden = self.has_status("hidden")
        return actively_hidden or self.is_presence_concealed_from(observer)

    def reveal_hidden_to(self, observer):
        changed = False
        for modifier in self.modifiers:
            if (
                modifier.applied
                and getattr(modifier, "status", None) == "hidden"
            ):
                reveal = getattr(modifier, "reveal_to", None)
                if reveal is not None and reveal(observer):
                    changed = True
        if changed:
            game_manager = getattr(self, "game_manager", None)
            turn_manager = getattr(game_manager, "turn_manager", None)
            if turn_manager is not None:
                turn_manager.update_visibility()
        return changed

    def reveal_presence_to(self, observer):
        modifiers = [
            modifier for modifier in self.modifiers
            if modifier.applied
            and modifier.effect_type == "presence_concealment"
        ]
        if (
            observer is not None
            and observer is not self
            and modifiers
        ):
            self.presence_concealment_exposed_to.add(observer)
            for modifier in modifiers:
                if getattr(modifier, "remove_when_revealed", False):
                    self.remove_modifier(modifier)
            game_manager = getattr(self, "game_manager", None)
            turn_manager = getattr(game_manager, "turn_manager", None)
            if turn_manager is not None:
                turn_manager.update_visibility()
        return observer

    def get_carry_capacity(self):
        return max(0, int(self.carry_capacity))

    def validate_ride_group(self):
        group = self.ride_group or self.carried_by
        if group is None:
            return True
        if (
            group.rider is self
            and 0 < group.capacity < len(group.passengers)
        ):
            game_manager = getattr(self, "game_manager", None)
            decision_provider = getattr(game_manager, "decision_provider", None)
            if decision_provider is not None:
                from game.turn.decision import DecisionOption, DecisionRequest

                remaining = list(group.passengers)
                retained = []
                while len(retained) < group.capacity:
                    passenger = decision_provider.choose(DecisionRequest(
                        character=self,
                        phase="携带容量变更",
                        prompt="请选择继续携带的角色。",
                        options=tuple(
                            DecisionOption(
                                candidate.name,
                                candidate,
                                (str(candidate.name),),
                            )
                            for candidate in remaining
                        ),
                    ))
                    retained.append(passenger)
                    remaining.remove(passenger)
                group.retain_passengers(retained)
        return group.validate()

    def detach_ride_group(self):
        if self.carried_by is not None:
            return self.carried_by.remove_passenger(self)
        if self.ride_group is not None:
            self.ride_group.dissolve()
            return True
        return False

    def can_act_on_turn(self, turn_number):
        return (
            self.is_alive()
            and self.despawn_reason is None
            and (
                self.activation_turn is None
                or turn_number >= self.activation_turn
            )
        )

    def grant_temporary_mp(self, amount):
        amount = int(amount)
        if amount <= 0:
            raise ValueError("临时MP必须大于0")
        self.temporary_mp += amount
        self.temporary_mp_waits_for_personal_turn_end = bool(self.in_battle)
        from game.game.rule_report import report_mp_pool_change
        report_mp_pool_change(self, "temporary_mp", self.temporary_mp - amount,
                              self.temporary_mp, operation="add", reason="grant_temporary_mp")
        return self.temporary_mp

    def clear_temporary_mp(self):
        removed = self.temporary_mp
        self.temporary_mp = 0
        self.temporary_mp_waits_for_personal_turn_end = False
        from game.game.rule_report import report_mp_pool_change
        report_mp_pool_change(self, "temporary_mp", removed, 0,
                              operation="set", reason="clear_temporary_mp")
        return removed

    def grant_command_spell_damage(self, amount=90):
        self.command_spell_damage_bonus += int(amount)
        return self.command_spell_damage_bonus

    def consume_command_spell_damage(self):
        amount = self.command_spell_damage_bonus
        self.command_spell_damage_bonus = 0
        return amount

    def remove_status_modifiers(self, status_name):
        removed = False
        for modifier in self.modifiers[:]:
            if getattr(modifier, "status", None) != status_name:
                continue
            removed = self.remove_modifier(modifier) or removed
        self.status_flags.discard(status_name)
        self.status_sources.pop(status_name, None)
        return removed

    def add_modifier(self, modifier):
        return self.modifier_manager.add(modifier)

    def add_resource(
        self,
        definition,
        *,
        source=None,
        source_type=None,
        source_id=None,
    ):
        return self.resource_manager.add(
            definition,
            source=source,
            source_type=source_type,
            source_id=source_id,
        )

    def has_resource(self, resource_id):
        return self.resource_manager.has(resource_id)

    def get_resource(self, resource_id):
        return self.resource_manager.get(resource_id)

    def get_resource_value(self, resource_id):
        return self.resource_manager.value(resource_id)

    def get_available_resource(self, resource_id):
        return self.resource_manager.available(resource_id)

    def gain_resource(self, resource_id, value):
        return self.resource_manager.gain(resource_id, value)

    def get_resource_maximum(self, resource_id):
        if resource_id == "hp":
            return self.hpmax
        if resource_id == "mp":
            return self.mpmax
        return self.get_resource(resource_id).maximum

    def get_recoverable_resource_amount(self, resource_id):
        maximum = self.get_resource_maximum(resource_id)
        if maximum is None:
            return None
        if resource_id == "hp":
            if self.has_status("dead"):
                return 0
            current = self.hp
        elif resource_id == "mp":
            current = self.mp
        else:
            current = self.get_resource_value(resource_id)
        return max(0, maximum - current)

    def recover_resource(self, resource_id, amount):
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            raise TypeError("资源回复量必须是数字")
        if amount < 0:
            raise ValueError("资源回复量不能小于0")
        amount = int(amount)
        if resource_id == "hp":
            if self.has_status("dead"):
                return 0
            old_value = self.hp
            self.hp = min(self.hpmax, self.hp + amount)
            self._emit_builtin_resource_change(
                "resource_recovered",
                "hp",
                old_value,
                self.hp,
                requested_value=amount,
                operation="add",
                reason="recover",
            )
            return self.hp - old_value
        if resource_id == "mp":
            old_value = self.mp
            self.mp = min(self.mpmax, self.mp + amount)
            self._emit_builtin_resource_change(
                "resource_recovered",
                "mp",
                old_value,
                self.mp,
                requested_value=amount,
                operation="add",
                reason="recover",
            )
            return self.mp - old_value
        return self.resource_manager.recover(resource_id, amount)

    def pay_mp_with_ledger(self, amount):
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            raise TypeError("MP消耗必须是数字")
        if amount < 0:
            raise ValueError("MP消耗不能小于0")
        amount = int(amount)
        if self.get_available_mp() < amount:
            return None
        temporary_cost = min(self.temporary_mp, amount)
        ordinary_cost = amount - temporary_cost
        self.temporary_mp -= temporary_cost
        self.mp -= ordinary_cost
        battle = getattr(self, "current_battle", None)
        if battle is not None and not getattr(battle, "ended", False):
            if temporary_cost:
                battle.record_mp_payment(self, temporary_cost, "temporary_mp")
            if ordinary_cost:
                battle.record_mp_payment(self, ordinary_cost, "mp")
        if temporary_cost:
            self._emit_builtin_resource_change(
                "resource_paid",
                "mp",
                self.temporary_mp + temporary_cost,
                self.temporary_mp,
                requested_value=temporary_cost,
                operation="subtract",
                reason="pay_temporary_mp",
            )
        if ordinary_cost:
            self._emit_builtin_resource_change(
                "resource_paid",
                "mp",
                self.mp + ordinary_cost,
                self.mp,
                requested_value=ordinary_cost,
                operation="subtract",
                reason="pay",
            )
        ledger = []
        if temporary_cost:
            ledger.append({
                "payer": self,
                "amount": temporary_cost,
                "pool": "temporary_mp",
            })
        if ordinary_cost:
            ledger.append({"payer": self, "amount": ordinary_cost, "pool": "mp"})
        return ledger

    def _emit_builtin_resource_change(
        self,
        event_type,
        resource_id,
        old_value,
        new_value,
        *,
        requested_value,
        operation,
        reason,
    ):
        change = new_value - old_value
        if change == 0:
            return None
        game_manager = getattr(self, "game_manager", None)
        event_manager = getattr(game_manager, "event_manager", None)
        if event_manager is None:
            return None
        payload = {
            "resource_id": resource_id,
            "old_value": old_value,
            "new_value": new_value,
            "change": change,
            "operation": operation,
            "requested_value": requested_value,
            "reason": reason,
        }
        event_manager.emit(
            "resource_changed",
            actor=self,
            source=self,
            target=self,
            value=change,
            phase=getattr(getattr(self, "current_battle", None), "current_phase", None),
            battle=getattr(self, "current_battle", None),
            position=self.position,
            payload=payload,
        )
        if event_type is None:
            return None
        return event_manager.emit(
            event_type,
            actor=self,
            source=self,
            target=self,
            value=change,
            phase=getattr(getattr(self, "current_battle", None), "current_phase", None),
            battle=getattr(self, "current_battle", None),
            position=self.position,
            payload=payload,
        )

    @staticmethod
    def refund_mp_ledger(ledger):
        results = []
        for payment in ledger:
            payer = payment["payer"]
            requested = payment["amount"]
            if payment.get("pool") == "temporary_mp":
                payer.temporary_mp += requested
                from game.game.rule_report import report_mp_pool_change
                report_mp_pool_change(payer, "temporary_mp", payer.temporary_mp - requested,
                                      payer.temporary_mp, operation="add", reason="refund")
                refunded = requested
            else:
                refunded = payer.recover_resource("mp", requested)
            results.append({
                "payer": payer,
                "requested": requested,
                "refunded": refunded,
            })
        return results

    def interrupt_casting(self, reason="manual"):
        from game.skill.casting import interrupt_casting

        return interrupt_casting(self, reason=reason)

    def advance_casting(self, turn_number, decision_provider=None):
        if self.casting_state is None:
            return False
        return self.casting_state.advance_at_global_turn_end(
            turn_number,
            decision_provider=decision_provider,
        )

    def modify_resource(self, resource_id, operation, value):
        return self.resource_manager.modify(resource_id, operation, value)

    def can_pay_resource(self, resource_id, amount):
        return self.resource_manager.can_pay(resource_id, amount)

    def pay_resource(self, resource_id, amount):
        return self.resource_manager.pay(resource_id, amount)

    def trigger_resource_event(self, event_name, **context):
        return self.resource_manager.trigger(event_name, **context)

    def reset_resources(self, timing):
        return self.resource_manager.reset(timing)

    def create_personal_skill(self, definition):
        from game.skill.skill_runtime import create_personal_skill

        return create_personal_skill(self, definition)

    def create_magic(self, definition):
        from game.skill.skill_runtime import create_magic

        return create_magic(self, definition)

    def load_basic_magic(self, magic_id):
        from game.skill.skill_runtime import load_basic_magic

        return load_basic_magic(self, magic_id)

    def load_content(self, content_type, entry_id):
        from game.skill.content_registry import load_content

        return load_content(self, content_type, entry_id)

    def bulk_load_content(self, **content_ids):
        from game.skill.content_registry import bulk_load_content

        return bulk_load_content(self, **content_ids)

    def resolve_skill_component(
        self,
        skill_id,
        component_id,
        target=None,
        **context,
    ):
        from game.skill.skill_runtime import resolve_skill_component

        from game.skill.skill_runtime import iter_character_skills

        skill = next(
            (
                candidate
                for candidate in iter_character_skills(self)
                if candidate.skill_id == skill_id
            ),
            None,
        )
        if skill is None:
            raise ValueError(f"未知的技能、魔术或宝具：{skill_id}")
        context.setdefault("turn_number", self.current_global_turn)
        return resolve_skill_component(
            self,
            skill,
            component_id,
            target=target,
            **context,
        )

    def remove_modifier(self, modifier):
        return self.modifier_manager.remove(modifier)

    def find_modifiers(self, **criteria):
        return self.modifier_manager.find(**criteria)

    def get_purifiable_modifiers(self):
        return self.modifier_manager.get_purifiable()

    def purify_modifiers(self, modifiers=None, maximum="all"):
        return self.modifier_manager.purify(
            modifiers=modifiers,
            maximum=maximum,
        )

    def _register_status_source(self, status_name, modifier):
        self.status_sources.setdefault(status_name, set()).add(modifier)
        self.status_flags.add(status_name)

    def _unregister_status_source(self, status_name, modifier):
        sources = self.status_sources.get(status_name)
        if sources is None:
            self.status_flags.discard(status_name)
            return
        sources.discard(modifier)
        if sources:
            return
        self.status_sources.pop(status_name, None)
        self.status_flags.discard(status_name)

    def lock_movement(self, ap_layer, source=None):
        self.movement_locked = True
        self.movement_lock_layer = ap_layer
        self.movement_lock_source = source

    def clear_movement_lock(self):
        self.movement_locked = False
        self.movement_lock_layer = None
        self.movement_lock_source = None

    def update_modifiers(self, timing="global_turn_end", turn_number=None, duration_snapshot=None):
        result = self.modifier_manager.update(
            timing,
            turn_number=turn_number,
            duration_snapshot=duration_snapshot,
        )
        if timing == "global_turn_end":
            self.clear_battle_plus_effects()
            from game.action.dynamic_action import update_dynamic_actions

            update_dynamic_actions(self, turn_number=turn_number)
        return result

    def update_phase_window_modifiers(
        self,
        *,
        scope,
        phase,
        boundary,
        phase_actor,
    ):
        return self.modifier_manager.update_phase_windows(
            scope=scope,
            phase=phase,
            boundary=boundary,
            phase_actor=phase_actor,
        )
#回合结束时处理过期的buff

    @property
    def position(self):
        return self._position

    @position.setter
    def position(self, new_position):
        old_position = getattr(self, "_position", None)
        if old_position is new_position:
            return

        if old_position is not None and hasattr(old_position, "occupants"):
            if self in old_position.occupants:
                old_position.occupants.remove(self)

        self._position = new_position

        if new_position is not None and hasattr(new_position, "occupants"):
            if self not in new_position.occupants:
                new_position.occupants.append(self)
            self.seen_locations.add(new_position)

        game_manager = getattr(self, "game_manager", None)
        if game_manager is not None and hasattr(
            game_manager,
            "on_character_position_changed",
        ):
            game_manager.on_character_position_changed(
                self,
                old_position,
                new_position,
            )

        if old_position is not None and self.has_status("hidden"):
            self.remove_hidden(reason="position_changed")

    def remove_hidden(self, reason=None):
        for modifier in self.modifiers[:]:
            if getattr(modifier, "status", None) != "hidden":
                continue
            if (
                reason == "position_changed"
                and not getattr(modifier, "remove_on_position_change", True)
            ):
                continue
            if (
                reason == "battle_entry"
                and not getattr(modifier, "remove_on_battle_entry", True)
            ):
                continue
            if getattr(modifier, "status", None) == "hidden":
                self.remove_modifier(modifier)
        if not self.status_sources.get("hidden"):
            self.status_flags.discard("hidden")
            self.status_sources.pop("hidden", None)

    def calculate_own_visibility(self, characters):
        """Read current sight without changing the turn's visibility caches."""
        from game.map.map import get_nodes_within_distance

        visible_nodes = get_nodes_within_distance(
            self.position,
            max(0, self.get_effective_visibility()),
        )
        game_manager = getattr(self, "game_manager", None)
        own_visible = []
        shareable = []
        for character in characters:
            if character is self or character.position not in visible_nodes:
                continue
            normally_visible = not character.is_concealed_from(self)
            workshop_visible = bool(
                game_manager is not None
                and game_manager.field_manager.ignores_concealment(
                    self,
                    character,
                )
            )
            if normally_visible or workshop_visible:
                own_visible.append(character)
            if normally_visible:
                shareable.append(character)

        if game_manager is not None:
            for character in game_manager.get_special_visible_characters(self):
                if character is not self and character not in own_visible:
                    own_visible.append(character)
            for character in game_manager.get_shareable_special_visible_characters(
                self
            ):
                if character is not self and character not in shareable:
                    shareable.append(character)

        return own_visible, shareable

    def update_own_visibility(self, characters):
        self.own_visible, self.shareable_own_visible = self.calculate_own_visibility(characters)
        return self.own_visible

    def calculate_own_perception(self):
        from game.map.map import get_distance

        return [
            character
            for character in self.own_perceived
            if character is not self
            and character.is_alive()
            and get_distance(self.position, character.position, 5) is not None
        ]

    def update_own_perception(self):
        self.own_perceived = self.calculate_own_perception()
        return self.own_perceived

    def current_awareness(self, characters):
        """Current rule-based knowledge for views, including direct sharing.

        Position/death events can precede the normal turn cache refresh. A
        read-only view must neither disclose stale coordinates nor advance it.
        """
        if not self.is_alive():
            return []
        known = []
        for observer in self.get_shared_vision_group():
            if not observer.is_alive():
                continue
            own, shareable = observer.calculate_own_visibility(characters)
            known.extend(own if observer is self else shareable)
            known.extend(observer.calculate_own_perception())
        return list(dict.fromkeys(known))

    def get_shared_vision_group(self):
        """Return direct rule-based vision links; ordinary allies do not share."""
        group = [self]

        def append(character):
            if (
                character is not None
                and character not in group
                and character.is_alive()
            ):
                group.append(character)

        append(getattr(self, "master", None))
        for servant in getattr(self, "servants", []):
            append(servant)
        append(getattr(self, "summoner", None))
        for familiar in getattr(self, "familiars", []):
            append(familiar)
        travel_group = getattr(self, "travel_group", None)
        if travel_group is not None:
            for member in travel_group.members:
                append(member)
        return group

    def update_visibility(self, characters):
        from game.map.map import get_nodes_within_distance

        vision_group = self.get_shared_vision_group()
        shared_visible_nodes = set()
        for character in vision_group:
            character.update_own_perception()
            character.update_own_visibility(characters)
            shared_visible_nodes.update(get_nodes_within_distance(
                character.position,
                max(0, character.get_effective_visibility()),
            ))
            game_manager = getattr(character, "game_manager", None)
            if game_manager is not None:
                shared_visible_nodes.update(
                    game_manager.get_special_visible_nodes(character)
                )

        self.seen_locations.update(shared_visible_nodes)

        shared_targets = []
        for character in vision_group:
            if character is self:
                continue
            for target in character.shareable_own_visible:
                if target not in shared_targets:
                    shared_targets.append(target)

        self.shared_visible = [
            target
            for target in shared_targets
            if target is not self and target not in self.own_visible
        ]

        shared_perception_targets = []
        for character in vision_group:
            if character is self:
                continue
            for target in character.own_perceived:
                if target not in shared_perception_targets:
                    shared_perception_targets.append(target)

        self.shared_perceived = [
            target
            for target in shared_perception_targets
            if target is not self and target not in self.own_perceived
        ]
        self.perceived = list(self.own_perceived) + list(self.shared_perceived)

        # any_visible is the canonical awareness union. Perception can make a
        # character encounter-aware, but never promotes it into own_visible;
        # attacks which require the actor's own sight continue to use that
        # narrower list explicitly.
        self.any_visible = list(dict.fromkeys([
            *self.own_visible,
            *self.shared_visible,
            *self.perceived,
        ]))

        return self.any_visible

    def has_status(self, status_name):
        return status_name in self.status_flags
#状态查询器
    def is_alive(self):
        return self.hp > 0
    
    def die(self):
        if self.has_status("dead"):
            return False
        self.interrupt_casting(reason="death")
        self.detach_ride_group()
        travel_group = self.travel_group
        if travel_group is not None:
            game_manager = getattr(self, "game_manager", None)
            initiative_order = (
                game_manager.turn_manager.non_battle_order
                if game_manager is not None
                else None
            )
            travel_group.remove_member(self, initiative_order)
        death_location = self.position
        self.death_location = death_location
        self.modifier_manager.remove_for_death()
        self.hp = 0
        self.status_flags.add("dead")
        battle = self.current_battle
        if battle is not None:
            battle.remove_participant(self)
        from game.turn.damage import report_discarded_attacks
        report_discarded_attacks(self.pending_attacks, "target_died")
        self.pending_attacks.clear()
        game_manager = getattr(self, "game_manager", None)
        if game_manager is not None:
            game_manager.handle_character_death(self, death_location)
        self.position = None
        return True
#存活检定
    def get_base_attitude(self, character):
        from game.game.relationship import Attitude

        # A familiar mirrors its summoner's outward base attitude.  The other
        # character's attitude toward the familiar remains independent.
        if (
            getattr(self, "is_familiar", False)
            and getattr(self, "summoner", None) is not None
            and character is not self.summoner
        ):
            return self.summoner.get_base_attitude(character)
        return self.attitudes.get(character, Attitude.NEUTRAL)

    def set_base_attitude(self, character, attitude):
        from game.game.relationship import normalize_attitude

        if character is self:
            raise ValueError("不能设置角色对自身的态度")
        attitude = normalize_attitude(attitude)
        self.attitudes[character] = attitude
        return attitude

    def ensure_friendly_base(self, character):
        from game.game.relationship import Attitude

        if self.get_base_attitude(character) is not Attitude.FRIENDLY:
            self.set_base_attitude(character, Attitude.FRIENDLY)
        return True

    def get_ally_sources(self, character):
        return set(self.ally_sources.get(character, set()))

    def add_ally(self, character, source="legacy"):
        if character is self:
            raise ValueError("角色不能与自身建立盟友关系")
        self.ally_sources.setdefault(character, set()).add(source)
        character.ally_sources.setdefault(self, set()).add(source)
        self.allies.add(character)
        character.allies.add(self)
        return True

    def is_ally(self, character):
        return bool(self.ally_sources.get(character))

    def is_friendly_with(self, character):
        from game.game.relationship import Attitude

        return (
            self.is_ally(character)
            or self.get_base_attitude(character) is Attitude.FRIENDLY
        )

    def is_hostile_to(self, character):
        from game.game.relationship import Attitude

        return self.get_base_attitude(character) is Attitude.HOSTILE

    def get_attitude(self, character):
        if self.is_ally(character):
            return "ally"
        return self.get_base_attitude(character).value

    def get_non_ally_visibility(self):
        def unique_hostiles(characters):
            result = []
            for character in characters:
                if (
                    character is self
                    or self.is_ally(character)
                    or not character.is_alive()
                    or character in result
                ):
                    continue
                result.append(character)
            return result

        return (
            unique_hostiles(self.any_visible),
            unique_hostiles(self.perceived),
        )

    def format_non_ally_visibility(self):
        visible, perceived = self.get_non_ally_visibility()
        if not visible and not perceived:
            return ""
        visible_names = ", ".join(character.name for character in visible)
        perceived_names = ", ".join(character.name for character in perceived)
        return f"（可见：[{visible_names}]，感知：[{perceived_names}]）"

    def remove_ally(self, character, source=None):
        if source is None:
            self.ally_sources.pop(character, None)
            character.ally_sources.pop(self, None)
        else:
            own_sources = self.ally_sources.get(character)
            if own_sources is not None:
                own_sources.discard(source)
                if not own_sources:
                    self.ally_sources.pop(character, None)
            other_sources = character.ally_sources.get(self)
            if other_sources is not None:
                other_sources.discard(source)
                if not other_sources:
                    character.ally_sources.pop(self, None)
        if not self.is_ally(character):
            self.allies.discard(character)
            character.allies.discard(self)
        return True
#友军增减

# =============================================================================
    def take_damage(self, damage, *, decision_provider=None, damage_event=None):
        if damage < 0 :raise ValueError("伤害为0")
        damage = int(damage)
        from game.skill.survival_runtime import prepare_survival_damage
        damage = prepare_survival_damage(
            self, damage, decision_provider=decision_provider, damage_event=damage_event,
        )

        old_hp = self.hp
        self.hp -= damage
        if self.hp <= 0:
            if self.brink_of_death_counter > 0:
                self.brink_of_death_counter -= 1
                self.hp = 1
                self.enter_brink()
            else:
                self.die()
        self._emit_builtin_resource_change(
            "resource_damaged",
            "hp",
            old_hp,
            self.hp,
            requested_value=damage,
            operation="subtract",
            reason="damage",
        )
        return damage


    def refresh_brink_of_death_availability(self):
        """Recover the one-use brink chance only after battle and weakness.

        Once brink triggers, ending weakness while still in the same battle
        must not make it available again.  Conversely, leaving battle alone is
        insufficient while the four-turn weakness remains.
        """
        if not hasattr(self, "brink_of_death_counter"):
            return False
        if not self.in_battle and not self.has_status("weakness"):
            self.brink_of_death_counter = 1
            return True
        return False


    def enter_brink(self):
        brink_effect = {
            "duration": 1,
            "modifier_id": "brink_of_death",
            "effect_type":"add_status",
            "polarity": "neutral",
            "purifiable": False,
            "stacking": {
                "stack_group": "brink_of_death",
                "stack_scope": "all_sources",
                "stacking_rule": "refresh",
                "max_stacks": 1,
            },
            "effect_data":{
                "status_id":"brink_of_death"
            }
        }
        weakness_effect = {
            "duration": 4,
            "modifier_id": "weakness",
            "effect_type":"add_status",
            "polarity": "debuff",
            "purifiable": False,
            "stacking": {
                "stack_group": "weakness",
                "stack_scope": "all_sources",
                "stacking_rule": "refresh",
                "max_stacks": 1,
            },
            "effect_data":{
                "status_id":"weakness"
            }
        }
        brink_modifier = create_modifier(
            brink_effect,
            self,
            source=self,
            source_type="system",
            source_id="brink_of_death",
            applied_turn=self.current_global_turn,
            applied_phase="damage_resolution",
        )
        weakness_modifier = create_modifier(
            weakness_effect,
            self,
            source=self,
            source_type="system",
            source_id="brink_of_death",
            applied_turn=self.current_global_turn,
            applied_phase="damage_resolution",
        )

        self.add_modifier(brink_modifier)
        self.add_modifier(weakness_modifier)
        manager = getattr(self, "game_manager", None)
        event_manager = getattr(manager, "event_manager", None)
        if event_manager is not None:
            event_manager.emit(
                "brink_entered",
                actor=self,
                source=self,
                target=self,
                phase="damage_resolution",
                battle=self.current_battle,
                position=self.position,
            )


    def heal(self, amount):
        return self.recover_resource("hp", amount)

    def get_available_mp(self):
        return self.temporary_mp + self.mp
    
    def consume_mp(self, amount):
        return self.pay_mp_with_ledger(amount) is not None

    def recover_mp(self, amount):
        return self.recover_resource("mp", amount)

    def end_global_turn(self, turn_number):
        if not self.temporary_mp_waits_for_personal_turn_end:
            self.clear_temporary_mp()
     #处理HPMP，不会出现负数MPHP变动
# ====================================================================================
    def show_status(self):
    #下面这一堆都是在屏幕上显示某角色的基础属性和HPMP/HPMPMAX，加骰等
        print("=" * 30)#这是一条分割线
        print(f"角色：{self.name}")
        self.show_class()
        self.show_command_spell()

        print(f"筋力：{self.strength}")
        print(f"耐久：{self.endurance}")
        print(f"敏捷：{self.flexibility}")
        print(f"魔力：{self.magic}")
        print(f"幸运：{self.fortune}")
        self.show_extra_status()

        print("-" * 30)#这是一条分割线
        print(f"HP：{self.hp}/{self.hpmax}")
        print(f"MP：{self.mp}/{self.mpmax}")
        print(f"ATK：{self.atk}")

        print("-" * 30)#这是一条分割线
        print(f"攻击骰：{self.physical_attack}")
        print(f"魔术骰：{self.magic_attack}")
        print(f"闪避骰：{self.dodge}")
        print(f"格挡骰：{self.block}")
        print(f"抵消骰：{self.offset}")

        print("-" * 30)#这是一条分割线
        print(f"幸运重骰剩余次数：{self.luck_reroll}/{self.luck_reroll_max}")

        print("-" * 30)#这是一条分割线
#区分从者和御主的卡面显示
    def show_extra_status(self):#宝具和天赋（如无就跳过，后同）
        pass

    def show_class(self):#展示职介
        pass

    def show_class_skill(self):#展示职介技能（Servant）
        pass

    def show_noble_phantasms(self):#展示宝具名（Servant）
        pass

    def show_magic_skills(self):#展示保有魔术（Master）
        pass

    def show_basic_magics(self):#展示基础魔术（Master）
        pass

    def show_mystic_codes(self):#展示魔术礼装（Master）
        pass

    def show_command_spell(self):#展示令咒数量（Master）
        pass
