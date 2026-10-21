"""Structured rule outcomes, independent of terminal text and skill triggers."""

from copy import deepcopy
import json


def identity(character):
    if character is None or not hasattr(character, "character_id"):
        return None
    return {"character_id": character.character_id, "name": character.name,
            "entity_type": character.entity_type}


def report(character, kind, **kwargs):
    manager = getattr(getattr(character, "game_manager", None), "rule_reports", None)
    if manager is not None:
        return manager.record(kind, **kwargs)
    return None


def report_mp_pool_change(character, pool, old_value, new_value, *, operation, reason):
    """Journal legacy direct MP mutations without introducing skill triggers."""
    if old_value == new_value:
        return None
    return report(character, "resource_changed", actor=character, targets=[character],
                  private=True, target_data={"resource_id": "mp", "pool": pool,
                      "old_value": old_value, "new_value": new_value,
                      "change": new_value - old_value, "operation": operation, "reason": reason})


class RuleReportManager:
    """Keep JSON records; listeners project each outcome at occurrence time.

    References in the live context never enter history. Reports do not emit
    GameEvents, ask decisions, or change rules. History is a trusted GM log.
    """

    def __init__(self, game_manager):
        self.game_manager = game_manager
        self.history = []
        self._listeners = []

    def subscribe(self, listener):
        if listener not in self._listeners:
            self._listeners.append(listener)

    def unsubscribe(self, listener):
        if listener in self._listeners:
            self._listeners.remove(listener)

    def record(self, kind, *, actor=None, targets=(), position=None, battle=None,
               phase=None, public=None, involved=None, actor_data=None,
               target_data=None, private=False, broadcast=False):
        targets = list(dict.fromkeys(target for target in targets if identity(target)))
        battle = battle or getattr(actor, "current_battle", None)
        if position is None:
            position = getattr(actor, "position", None)
        record = {
            "report_id": len(self.history) + 1, "kind": kind,
            "turn": self.game_manager.turn_manager.turn,
            "phase": phase or getattr(battle, "current_phase", None),
            "battle_id": getattr(battle, "battle_id", None),
            "actor": identity(actor), "targets": [identity(target) for target in targets],
            "position_name": getattr(position, "name", None),
            "data": {"public": public or {}, "involved": involved or {},
                     "actor": actor_data or {}, "target": target_data or {}},
        }
        # An explicit JSON boundary rejects accidental references or NaN early.
        record = json.loads(json.dumps(record, ensure_ascii=False, allow_nan=False))
        self.history.append(record)
        context = {"actor": actor, "targets": targets, "position": position,
                   "private": private, "broadcast": broadcast}
        for listener in tuple(self._listeners):
            listener(deepcopy(record), context)
        return deepcopy(record)

    def record_game_event(self, event):
        if event.timing != "after" or not event.completed or event.cancelled:
            return
        private_fields = {
            "action_resolved": ("action_id",),
            "resource_changed": ("resource_id", "old_value", "new_value", "change", "operation", "reason"),
            "modifier_applied": ("modifier_id", "effect_type", "polarity", "new_state"),
            "modifier_removed": ("modifier_id", "effect_type", "polarity", "reason"),
            "modifier_refreshed": ("modifier_id", "effect_type", "new_state"),
            "modifier_stacked": ("modifier_id", "effect_type", "new_state"),
            "status_added": ("status", "reason"), "status_removed": ("status", "reason"),
            "skill_added": ("skill_id", "skill_name", "source_type"),
            "skill_removed": ("skill_id", "skill_name", "reason"),
        }
        public_fields = {
            "global_turn_start": ("turn_number",),
            "global_turn_end": ("turn_number",),
            "position_left": (), "position_entered": (),
            "battle_declared": (), "battle_joined": (), "battle_left": ("reason",),
            "battle_turn_start": (), "battle_turn_end": (), "battle_round_end": (),
            "character_died": (), "character_registered": (),
            "character_despawned": ("reason",),
        }
        private = event.event_type in private_fields
        fields = private_fields.get(event.event_type, public_fields.get(event.event_type))
        if fields is None:
            return
        data = {key: event.payload[key] for key in fields if key in event.payload}
        if event.event_type == "resource_changed" and data.get("resource_id") == "mp":
            data["pool"] = "temporary_mp" if data.get("reason") == "pay_temporary_mp" else "mp"
        if event.event_type == "action_resolved":
            data["success"] = bool(event.payload.get("result"))
        # Modifier snapshots contain only the manager's explicit scalar state.
        self.record(event.event_type, actor=event.actor, targets=event.targets,
                    position=event.position, battle=event.battle, phase=event.phase,
                    private=private, broadcast=event.event_type in {"global_turn_start", "global_turn_end"},
                    **({"actor_data" if event.event_type == "action_resolved" else "target_data": data}
                       if private else {"public": data}))


def report_skill_use(actor, skill, component, targets, *, paid=None, inputs=None, phase=None):
    return report(actor, "skill_activated", actor=actor, targets=targets,
                  phase=phase, private=True,
                  actor_data={"skill_id": skill.skill_id, "skill_name": skill.name,
                              "component_id": component.get("component_id"),
                              "component_name": component.get("name", skill.name),
                              "activation_type": component["type"],
                              "paid_costs": dict(paid or {}), "inputs": dict(inputs or {})})
