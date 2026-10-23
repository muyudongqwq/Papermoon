"""Local threaded sessions with structured decisions; no HTTP or sockets."""

from copy import deepcopy
from threading import Lock, Thread
from uuid import uuid4

from game.game.command_spell import CommandSpellService
from game.game.game_loop import GameLoop
from game.game.gm_commands import GMCommandService
from game.game.queued_decision import QueuedDecisionProvider, SessionStopped
from game.game.session_view import build_snapshot, current_known_characters, redact_status_sources


class _SessionGameLoop(GameLoop):
    def run_global_turn(self):
        self.decision_provider.checkpoint()
        return super().run_global_turn()


class GameSession:
    """Own one engine worker and cached, detached per-controller views.

    Controller IDs are supplied by a trusted local caller. Authentication and
    transport are deliberately outside this in-process interface. Once started,
    callers must use this interface instead of mutating GameManager directly.
    """

    TERMINAL_STATES = {"completed", "stopped", "failed"}
    _ownership_lock = Lock()

    def __init__(self, game_manager, controllers, *, session_id=None, gm_id="gm"):
        if getattr(game_manager, "_active_session", None) is not None:
            raise ValueError("GameManager已经由另一会话运行")
        if not isinstance(gm_id, str) or not gm_id:
            raise ValueError("gm_id必须是非空字符串")
        self.game_manager = game_manager
        self.session_id = uuid4().hex if session_id is None else session_id
        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError("session_id必须是非空字符串")
        self.gm_id = gm_id
        self._controllers = dict(controllers)
        known = {actor.character_id for actor in self._characters()}
        if len(known) != len(self._characters()):
            raise ValueError("角色ID必须唯一")
        if set(self._controllers) - known:
            raise ValueError("控制权映射中存在未知角色ID")
        if any(not isinstance(owner, str) or not owner for owner in self._controllers.values()):
            raise ValueError("控制者ID必须是非空字符串")
        self._controller_ids = set(self._controllers.values()) | {gm_id}
        for actor in self._characters():
            self._controller_for(actor)
        self._state = "created"
        self._result = None
        self._error = None
        self._thread = None
        self._events = []
        self._views = {}
        self._positions = {}
        self._position_ids = {}
        self.decision_provider = QueuedDecisionProvider(
            self.session_id, self._controller_for, self._publish, gm_id=gm_id,
        )
        self._condition = self.decision_provider.condition
        self.game_loop = None
        self._capture_views()

    def _characters(self):
        return (list(self.game_manager.characters) + list(self.game_manager.dead_characters)
                + [record["character"] for record in self.game_manager.removed_characters])

    def _controller_for(self, character):
        current = character
        visited = set()
        while current is not None and id(current) not in visited:
            visited.add(id(current))
            owner = self._controllers.get(current.character_id)
            if owner is not None:
                self._controllers[character.character_id] = owner
                return owner
            summoner = getattr(current, "summoner", None)
            master = getattr(current, "master", None)
            inherited = getattr(current, "controller", None)
            if summoner is not None:
                current = summoner
            elif master is not None:
                current = master
            elif inherited is not current and hasattr(inherited, "character_id"):
                current = inherited
            elif getattr(current, "is_npc", False):
                self._controllers[character.character_id] = self.gm_id
                return self.gm_id
            else:
                break
        raise ValueError(f"角色缺少控制权分配：{character.character_id}")

    def _authorize(self, controller_id):
        if not isinstance(controller_id, str) or controller_id not in self._controller_ids:
            raise PermissionError("未知控制者")

    def _position_id(self, position):
        if position is None:
            return None
        if position not in self._position_ids:
            position_id = uuid4().hex
            self._position_ids[position] = position_id
            self._positions[position_id] = position
        return self._position_ids[position]

    def _capture_views(self):
        for node in self.game_manager.get_map_nodes(merge_area_levels=False):
            self._position_id(node)
        self._views = {owner: build_snapshot(self, owner) for owner in self._controller_ids}

    def _report_projection(self, record, context, controller_id):
        gm = controller_id == self.gm_id
        owned = {character for character in self._characters()
                 if self._controller_for(character) == controller_id}
        known = current_known_characters(owned, self._characters())
        actor, targets = context["actor"], context["targets"]
        actor_owned = actor in owned
        target_owned = any(target in owned for target in targets)
        involved = actor_owned or target_owned
        if not gm:
            if context["private"] and not involved:
                return None
            if not context["broadcast"] and not involved and actor not in known and not any(
                target in known for target in targets
            ):
                return None
        result = {key: deepcopy(value) for key, value in record.items()
                  if key not in {"actor", "targets", "position_name", "data"}}
        result["actor"] = record["actor"] if gm or actor in known else None
        result["targets"] = [entry for target, entry in zip(targets, record["targets"])
                             if gm or target in known]
        position = context["position"]
        position_known = gm or any(character in known and character.position is position
                                   for character in [actor, *targets] if character is not None)
        result["position_id"] = self._position_id(position) if position_known else None
        data = dict(record["data"]["public"])
        if gm or involved:
            data.update(record["data"]["involved"])
        if gm or actor_owned:
            data.update(record["data"]["actor"])
        if gm or target_owned:
            data.update(record["data"]["target"])
        result["data"] = deepcopy(data)
        if not gm:
            redact_status_sources(result["data"], known)
        return result

    def _on_rule_report(self, record, context):
        # Freeze disclosure now. Later visibility changes cannot reveal older
        # records, and every audience shares one sequence number for this result.
        with self._condition:
            projections = {owner: value for owner in self._controller_ids
                           if (value := self._report_projection(record, context, owner)) is not None}
            self._events.append({
                "sequence": len(self._events) + 1, "session_id": self.session_id,
                "type": "rule_report", "payload": projections[self.gm_id],
                "_projections": projections, "_recipient": self.gm_id,
            })
            self._capture_views()
            self._condition.notify_all()

    def _publish(self, event_type, payload, recipient=None):
        with self._condition:
            if event_type == "decision_requested":
                self._state = "waiting"
            elif event_type in {"decision_answered", "decision_invalidated"}:
                self._state = "running"
            self._capture_views()
            self._events.append({
                "sequence": len(self._events) + 1,
                "session_id": self.session_id,
                "type": event_type,
                "payload": deepcopy(payload),
                "_recipient": recipient,
            })
            self._condition.notify_all()

    @property
    def state(self):
        with self._condition:
            return self._state

    def start(self):
        with self._condition:
            if self._state != "created":
                raise ValueError("会话只能启动一次")
            with self._ownership_lock:
                if getattr(self.game_manager, "_active_session", None) is not None:
                    raise ValueError("同一GameManager不能由两个会话同时运行")
                self.game_manager._active_session = self
                self.game_loop = _SessionGameLoop(self.game_manager, self.decision_provider)
                self.game_manager.rule_reports.subscribe(self._on_rule_report)
            self._state = "running"
            self._thread = Thread(target=self._run, name=f"Papermoon-{self.session_id}", daemon=True)
            self._thread.start()
        return self.session_id

    def _run(self):
        try:
            self._publish("session_started", {})
            result = self.game_loop.run()
            final_state = "completed"
        except SessionStopped:
            self.game_manager.force_end_game(reason="session_stopped")
            result = self.game_loop.get_result()
            final_state = "stopped"
        except Exception as error:
            self.game_manager.rule_reports.unsubscribe(self._on_rule_report)
            self._error = f"{type(error).__name__}: {error}"
            self.game_manager.force_end_game(reason="session_error")
            result = self.game_loop.get_result()
            final_state = "failed"
        finally:
            with self._condition:
                self.game_manager.rule_reports.unsubscribe(self._on_rule_report)
                self.decision_provider.close()
                self._state = final_state
                self._result = {**result, "winners": [actor.character_id for actor in result["winners"]]}
                try:
                    self._publish("session_ended", {"state": final_state, **self._result})
                except Exception as error:
                    # A broken view must not prevent clients learning that the
                    # worker failed, or leave ownership of this game locked.
                    self._state = "failed"
                    self._error = self._error or f"{type(error).__name__}: {error}"
                    self._result = {"reason": "session_error", "winners": [], "turn": result["turn"]}
                    for owner, view in self._views.items():
                        view.update(state="failed", decision=None, result=deepcopy(self._result))
                        if owner == self.gm_id:
                            view["error"] = self._error
                    self._events.append({
                        "sequence": len(self._events) + 1, "session_id": self.session_id,
                        "type": "session_ended", "payload": {"state": "failed", **self._result},
                        "_recipient": None,
                    })
                finally:
                    with self._ownership_lock:
                        self.game_manager._active_session = None
                    self._condition.notify_all()

    def stop(self):
        with self._condition:
            if self._state == "created":
                self._state = "stopped"
                self.decision_provider.close()
                self._result = {"reason": "session_stopped", "winners": [],
                                "turn": self.game_manager.turn_manager.turn}
                self._publish("session_ended", {"state": "stopped", **self._result})
            elif self._state not in self.TERMINAL_STATES:
                self.decision_provider.stop()

    def join(self, timeout=5):
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def get_snapshot(self, controller_id):
        self._authorize(controller_id)
        with self._condition:
            return deepcopy(self._views[controller_id])

    def get_pending_decision(self, controller_id):
        self._authorize(controller_id)
        return self.decision_provider.current(controller_id)

    def get_events(self, controller_id, *, after=0, timeout=0):
        self._authorize(controller_id)
        if type(after) is not int or after < 0 or timeout < 0:
            raise ValueError("事件游标和等待时间不能小于0")

        def visible():
            return [event for event in self._events
                    if event["sequence"] > after
                    and (controller_id in event.get("_projections", {})
                         or event["_recipient"] in {None, controller_id} or controller_id == self.gm_id)]

        with self._condition:
            self._condition.wait_for(lambda: visible() or self._state in self.TERMINAL_STATES, timeout)
            result = []
            for event in visible():
                view = {key: deepcopy(value) for key, value in event.items() if not key.startswith("_")}
                if "_projections" in event:
                    view["payload"] = deepcopy(event["_projections"][controller_id])
                result.append(view)
            return result

    def submit_decision(self, controller_id, request_id, revision, *, option_id=None, value=None):
        self._authorize(controller_id)
        self.decision_provider.submit(controller_id, request_id, revision, option_id=option_id, value=value)

    def _character(self, character_id):
        matches = [actor for actor in self._characters() if actor.character_id == character_id]
        if len(matches) != 1:
            raise ValueError("未知或不唯一的角色ID")
        return matches[0]

    def command_spell(self, controller_id, *, master_id, target_id, effect,
                      destination_id=None, emergency_guard_target_id=None):
        self._authorize(controller_id)
        if (any(not isinstance(item, str) or not item for item in (master_id, target_id, effect))
                or any(item is not None and (not isinstance(item, str) or not item)
                       for item in (destination_id, emergency_guard_target_id))):
            raise ValueError("令咒效果和实体ID必须是非空字符串")

        def execute():
            master, target = self._character(master_id), self._character(target_id)
            if controller_id not in {self.gm_id, self._controller_for(master)}:
                raise PermissionError("不能使用其他玩家的令咒")
            service = CommandSpellService(self.game_manager)
            if master not in service.available_masters():
                raise ValueError("指定角色没有可用令咒")
            if effect in {"mp", "damage"}:
                if destination_id is not None or emergency_guard_target_id is not None:
                    raise ValueError("此令咒效果不接受位置或援护参数")
                method = service.grant_temporary_mp if effect == "mp" else service.grant_damage_bonus
                changed = method(master, target)
            elif effect == "teleport":
                destination = self._positions.get(destination_id)
                if destination is None:
                    raise ValueError("未知地点ID")
                guard = None if emergency_guard_target_id is None else self._character(emergency_guard_target_id)
                if guard is not None and guard not in service.emergency_guard_targets(master, target, destination):
                    raise ValueError("无效的紧急援护目标")
                changed = service.teleport(master, target, destination,
                    emergency_guard_target=guard, decision_provider=self.decision_provider)
                if changed:
                    self.game_loop.planned_positions[target] = target.position
                    for layer in self.game_loop.planned_start_positions.values():
                        layer[target] = target.position
            else:
                raise ValueError("未知令咒效果")
            if not changed:
                raise ValueError("令咒操作不满足使用条件")
            return {"kind": "command_spell", "effect": effect,
                    "master_id": master_id, "target_id": target_id}

        return self.decision_provider.enqueue_operation(controller_id, execute)

    def gm_command(self, controller_id, command, *, target_id, **parameters):
        self._authorize(controller_id)
        if controller_id != self.gm_id:
            raise PermissionError("只有GM可以执行强制命令")
        schema = {"add_resource": {"resource", "amount"}, "damage": {"damage_type", "amount"},
                  "teleport": {"destination_id"}, "kill": set()}
        if (not isinstance(command, str) or command not in schema
                or set(parameters) != schema[command]
                or not isinstance(target_id, str) or not target_id):
            raise ValueError("未知GM命令、无效角色ID或参数不匹配")
        if command == "teleport" and not isinstance(parameters["destination_id"], str):
            raise ValueError("地点ID必须是字符串")
        parameters = deepcopy(parameters)

        def execute():
            target = self._character(target_id)
            service = GMCommandService(self.game_manager)
            if command == "add_resource":
                result = service.add_resource(target, parameters["resource"], parameters["amount"])
            elif command == "damage":
                result = service.damage(target, parameters["damage_type"], parameters["amount"],
                                        decision_provider=self.decision_provider)
            elif command == "teleport":
                destination = self._positions.get(parameters["destination_id"])
                if destination is None:
                    raise ValueError("未知地点ID")
                result = service.teleport(target, destination, decision_provider=self.decision_provider)
                self.game_loop.planned_positions[target] = target.position
                for layer in self.game_loop.planned_start_positions.values():
                    layer[target] = target.position
            else:
                result = service.kill(target)
            return {**{key: value for key, value in result.items()
                       if key not in {"target", "destination", "event", "result"}},
                    "target_id": target_id,
                    **({"destination_id": parameters["destination_id"]} if command == "teleport" else {})}

        return self.decision_provider.enqueue_operation(controller_id, execute)
