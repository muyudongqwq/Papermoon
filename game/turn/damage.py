from game.turn.damage_types import normalize_damage_type
from uuid import uuid4


def report_discarded_attacks(attacks, reason):
   """Close presentation records without resolving damage or consuming buffs."""
   for attack in list(attacks):
      notify = getattr(attack, "report_cancelled", None)
      if notify is not None:
         notify(reason)


class AttackProfile:
   """A fully generated attack which has not been assigned a target yet.

   Rolling, outgoing damage modifiers and one-shot attack bonuses belong to
   profile generation.  Target validation, incoming modifiers and queuing
   belong to ``assign_target`` and the later defense pipeline.
   """

   VALID_RESOLUTION_CHANNELS = {"attack", "release"}

   def __init__(
      self,
      source,
      value,
      damage_type,
      attack_roll,
      skill=None,
      attack_die=None,
      attack_roll_bonus=0,
      percentage_modifiers=None,
      flat_modifiers=None,
      action_id="attack",
      skill_id=None,
      source_tags=None,
      ignore_shield=False,
      roll_result=None,
      resolution_channel="attack",
      damage_segments=None,
      target_lock=False,
      ignore_block=False,
   ):
      if resolution_channel not in self.VALID_RESOLUTION_CHANNELS:
         raise ValueError(
            f"未知的攻击发动出口：{resolution_channel}"
         )
      segments = list(damage_segments or [value])
      if not segments:
         raise ValueError("攻击至少需要一个伤害段")
      if any(
         isinstance(segment, bool)
         or not isinstance(segment, (int, float))
         or segment < 0
         for segment in segments
      ):
         raise ValueError("攻击伤害段必须是非负数值")

      self.source = source
      self.damage_segments = segments
      self.value = sum(segments)
      self.damage_type = normalize_damage_type(damage_type)
      self.attack_roll = attack_roll
      self.skill = skill
      self.attack_die = attack_die
      self.attack_roll_bonus = attack_roll_bonus
      self.percentage_modifiers = list(percentage_modifiers or [])
      self.source_was_in_brink = source.has_status("brink_of_death")
      if self.source_was_in_brink:
         self.percentage_modifiers.append(-0.5)
      self.flat_modifiers = list(flat_modifiers or [])
      self.action_id = action_id
      self.skill_id = skill_id
      self.source_tags = set(source_tags or [])
      self.ignore_shield = ignore_shield
      self.ignore_block = ignore_block
      self.roll_result = roll_result
      self.resolution_channel = resolution_channel
      self.target_lock = bool(target_lock)

   @property
   def total_base_damage(self):
      return self.value

   @property
   def offset_power(self):
      """Outgoing attack value before any target-side mitigation."""
      value = self.value * (1 + sum(self.percentage_modifiers))
      value += sum(self.flat_modifiers)
      return max(0, int(value))

   def assign_target(self, target):
      """Create an independent pending attack for one declared target."""
      reveal = getattr(self.source, "reveal_presence_to", None)
      if reveal is not None:
         reveal(target)
      return AttackEvent(
         source=self.source,
         target=target,
         value=self.value,
         damage_type=self.damage_type,
         attack_roll=self.attack_roll,
         skill=self.skill,
         attack_die=self.attack_die,
         attack_roll_bonus=self.attack_roll_bonus,
         percentage_modifiers=list(self.percentage_modifiers),
         flat_modifiers=list(self.flat_modifiers),
         action_id=self.action_id,
         skill_id=self.skill_id,
         source_tags=set(self.source_tags),
         ignore_shield=self.ignore_shield,
         ignore_block=self.ignore_block,
         roll_result=self.roll_result,
         resolution_channel=self.resolution_channel,
         damage_segments=list(self.damage_segments),
         target_lock=self.target_lock,
         source_statuses_snapshotted=True,
         attack_profile=self,
      )


class DamageEvent:
    def __init__(
       self,
       source,
       target,
       value,
       damage_type,
       is_hidden=False,
       skill=None,
       percentage_modifiers=None,
       flat_modifiers=None,
       action_id=None,
       skill_id=None,
       source_tags=None,
       ignore_shield=False,
       source_statuses_snapshotted=False,
       attack_id=None,
    ):
      self.source = source
      self.target = target
      self.value = value
      self.damage_type = normalize_damage_type(damage_type)
      self.is_hidden = is_hidden
      self.skill = skill
      self.percentage_modifiers = list(percentage_modifiers or [])
      self.flat_modifiers = list(flat_modifiers or [])
      self.action_id = action_id
      self.skill_id = skill_id
      self.source_tags = set(source_tags or [])
      self.ignore_shield = ignore_shield
      self.source_statuses_snapshotted = source_statuses_snapshotted
      self.attack_id = attack_id
      self.calculated_value = None
      self.shield_absorptions = []
      self.final_value = None

class DamageResolver:
   """统一伤害顺序：合并百分比 -> 乘除 -> 固定加减 -> 向零取整。"""

   def calculate(self, event):
      if event.target.has_status("brink_of_death"):
         return 0
      percentage_modifiers = list(event.percentage_modifiers)
      flat_modifiers = list(event.flat_modifiers)
      if (
         not event.source_statuses_snapshotted
         and event.source is not None
         and getattr(event.source, "has_status", lambda _status: False)(
            "brink_of_death"
         )
      ):
         percentage_modifiers.append(-0.5)
      modifier_manager = getattr(event.target, "modifier_manager", None)
      if modifier_manager is not None and event.damage_type != "true_damage":
         incoming_percentages, incoming_flats = (
         modifier_manager.get_damage_adjustments(
               "incoming",
               event.damage_type,
               action_id=event.action_id,
               skill_id=event.skill_id,
               source_tags=event.source_tags,
               context={
                  "actor": event.source,
                  "source": event,
                  "target": event.target,
                  "action_id": event.action_id,
                  "skill_id": event.skill_id,
                  "damage_type": event.damage_type,
                  "tags": event.source_tags,
               },
            )
         )
         percentage_modifiers.extend(incoming_percentages)
         flat_modifiers.extend(incoming_flats)
      if event.damage_type == "magic":
         resistance = getattr(event.target, "magic_resistance", 0)
         if modifier_manager is not None:
            resistance += modifier_manager.get_contextual_bonus(
               "magic_resistance",
               context={
                  "actor": event.target,
                  "source": event,
                  "target": event.target,
                  "action_id": event.action_id,
                  "skill_id": event.skill_id,
                  "damage_type": event.damage_type,
                  "tags": event.source_tags,
               },
            )
         percentage_modifiers.append(-resistance)

      percentage_total = sum(percentage_modifiers)
      flat_total = sum(flat_modifiers)
      damage = event.value * (1 + percentage_total)
      damage += flat_total
      return max(0, int(damage))

   def resolve(self, event, decision_provider=None):
      hp_before = event.target.hp
      position = event.target.position
      battle = event.target.current_battle
      damage = self.calculate(event)
      event.calculated_value = damage
      game_manager = getattr(event.target, "game_manager", None)
      event_manager = getattr(game_manager, "event_manager", None)
      if event_manager is not None:
         before_event = event_manager.emit(
            "before_damage",
            timing="before",
            actor=event.source,
            source=event,
            target=event.target,
            value=damage,
            phase="damage_resolution",
            battle=getattr(event.target, "current_battle", None),
            position=getattr(event.target, "position", None),
            payload={
               "damage_type": event.damage_type,
               "action_id": event.action_id,
               "skill_id": event.skill_id,
               "damage_event": event,
            },
            decision_provider=decision_provider,
         )
         damage = (
            0
            if before_event.cancelled
            else max(0, int(before_event.value))
         )
      modifier_manager = getattr(event.target, "modifier_manager", None)
      if modifier_manager is not None:
         damage, absorptions = modifier_manager.absorb_damage(damage, event)
         event.shield_absorptions = absorptions
      damage = event.target.take_damage(
         damage, decision_provider=decision_provider, damage_event=event,
      )
      event.final_value = damage
      modifier_context = {
         "actor": event.source,
         "source": event,
         "target": event.target,
         "action_id": event.action_id,
         "skill_id": event.skill_id,
         "damage_type": event.damage_type,
         "tags": set(event.source_tags) | {"damage"},
         "event": event,
      }
      owners = []
      for owner in (event.source, event.target):
         if owner is None or owner in owners:
            continue
         owners.append(owner)
         manager = getattr(owner, "modifier_manager", None)
         if manager is not None:
            manager.consume_event("damage_resolved", modifier_context)
      if damage > 0 and modifier_manager is not None:
         modifier_manager.consume_event(
            "damage_received",
            modifier_context,
         )
      context = {
         "damage": damage,
         "damage_type": event.damage_type,
         "source": event.source,
         "target": event.target,
         "event": event,
      }
      trigger_target = getattr(event.target, "trigger_resource_event", None)
      if trigger_target is not None:
         trigger_target("damage_received", **context)
      if event.source is not None and event.source is not event.target:
         trigger_source = getattr(event.source, "trigger_resource_event", None)
         if trigger_source is not None:
            trigger_source("damage_dealt", **context)
      if event_manager is not None:
         common = {
            "actor": event.source,
            "source": event,
            "target": event.target,
            "value": damage,
            "phase": "damage_resolution",
            "battle": getattr(event.target, "current_battle", None),
            "position": getattr(event.target, "position", None),
            "payload": {
               "damage_type": event.damage_type,
               "action_id": event.action_id,
               "skill_id": event.skill_id,
               "damage_event": event,
            },
            "decision_provider": decision_provider,
         }
         event_manager.emit("damage_received", **common)
         if event.source is not None and event.source is not event.target:
            event_manager.emit("damage_dealt", **common)
      from game.rule_report import report
      report(event.target, "damage_resolved", actor=event.source, targets=[event.target],
             position=position, battle=battle,
             public={"attack_id": event.attack_id},
             involved={"amount": damage, "damage_type": event.damage_type},
             actor_data={"action_id": event.action_id, "skill_id": event.skill_id,
                         "base_damage": event.value},
             target_data={"hp_before": hp_before, "hp_after": event.target.hp,
                          "hp_lost": max(0, hp_before - event.target.hp),
                          "shield_absorbed": sum(amount for _, amount in event.shield_absorptions)})
      return damage

class AttackEvent:
   def __init__(
      self,
      source,
      target,
      value,
      damage_type,
      attack_roll,
      skill,
      attack_die=None,
      attack_roll_bonus=0,
      percentage_modifiers=None,
      flat_modifiers=None,
      action_id="attack",
      skill_id=None,
      source_tags=None,
      ignore_shield=False,
      roll_result=None,
      resolution_channel="attack",
      damage_segments=None,
      source_statuses_snapshotted=False,
      attack_profile=None,
      target_lock=False,
      ignore_block=False,
   ):
      self.attack_id = uuid4().hex
      self.source = source
      self.target = target
      self.value = value #这是原始伤害
      self.damage_type = normalize_damage_type(damage_type)
      self.skill = skill
      self.resolved = False
      self.hit = None
      self.final_damage = 0
      self.attack_roll = attack_roll
      self.attack_die = attack_die
      self.attack_roll_bonus = attack_roll_bonus
      self.percentage_modifiers = list(percentage_modifiers or [])
      self.source_was_in_brink = source.has_status("brink_of_death")
      if self.source_was_in_brink and not source_statuses_snapshotted:
         self.percentage_modifiers.append(-0.5)
      self.flat_modifiers = list(flat_modifiers or [])
      self.action_id = action_id
      self.skill_id = skill_id
      self.source_tags = set(source_tags or [])
      self.ignore_shield = ignore_shield
      self.roll_result = roll_result
      self.ignore_block = ignore_block
      if resolution_channel not in AttackProfile.VALID_RESOLUTION_CHANNELS:
         raise ValueError(f"未知的攻击发动出口：{resolution_channel}")
      self.resolution_channel = resolution_channel
      self.damage_segments = list(damage_segments or [value])
      self.original_hit_segments = len(self.damage_segments)
      self.final_hit_segments = self.original_hit_segments
      self.attack_profile = attack_profile
      self.target_lock = bool(target_lock)
      self.defense_roll_started = False
      self.resolution_reason = None
      self._resolution_consumption_done = False
      self._cancellation_reported = False
      from game.rule_report import report
      report(target, "attack_declared", actor=source, targets=[target],
             public={"attack_id": self.attack_id, "channel": resolution_channel},
             involved={"damage_type": self.damage_type, "attack_roll": attack_roll},
             actor_data={"skill_id": skill_id, "action_id": action_id,
                         "base_damage": self.value})

   def miss_because_target_moved(self):
      if self.resolved or self.defense_roll_started:
         return False
      self.hit = False
      self.final_damage = 0
      self.resolved = True
      self.resolution_reason = "target_teleported"
      self.consume_resolution_modifiers()
      return True

   def report_cancelled(self, reason):
      if self.resolved or self._cancellation_reported:
         return False
      self._cancellation_reported = True
      from game.rule_report import report
      report(self.target, "attack_cancelled", actor=self.source, targets=[self.target],
             public={"attack_id": self.attack_id}, involved={"reason": reason})
      return True

   def consume_resolution_modifiers(self):
      if self._resolution_consumption_done:
         return False
      self._resolution_consumption_done = True
      context = {
         "actor": self.source,
         "source": self,
         "target": self.target,
         "action_id": self.action_id,
         "skill_id": self.skill_id,
         "damage_type": self.damage_type,
         "tags": set(self.source_tags) | {"attack"},
         "event": self,
      }
      owners = []
      for owner in (self.source, self.target):
         if owner is None or owner in owners:
            continue
         owners.append(owner)
         manager = getattr(owner, "modifier_manager", None)
         if manager is not None:
            manager.consume_event("attack_resolved", context)
      from game.rule_report import report
      report(self.target, "attack_resolved", actor=self.source, targets=[self.target],
             public={"attack_id": self.attack_id},
             involved={"hit": self.hit, "damage": self.final_damage,
                       "defense_type": getattr(self, "defense_type", None),
                       "reason": self.resolution_reason,
                       "remaining_hit_segments": self.final_hit_segments,
                       "offset_reduction": getattr(getattr(self, "offset_attempt", None), "reduction", None)})
      return True

