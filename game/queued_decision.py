"""An in-process decision bridge. This module opens no network connections."""

from collections import deque
from copy import deepcopy
from dataclasses import dataclass
from threading import Condition, RLock
from uuid import uuid4

from game.turn.decision import DecisionRefreshRequested, NumericDecisionRequest


class SessionStopped(Exception):
    """Cooperative cancellation at a decision or global-turn boundary."""


@dataclass
class _PendingDecision:
    request: object
    dto: dict
    accepting: bool = True
    answered: bool = False
    answer: object = None
    submission: dict = None


class QueuedDecisionProvider:
    """Suspend the synchronous engine until a validated structured answer arrives.

    ``publish`` runs on the engine thread. Only IDs, labels and numeric bounds
    cross this bridge; trusted option values remain in the pending frame.
    Immediate operations also execute on that thread and may ask nested choices.
    """

    def __init__(self, session_id, controller_for, publish, *, gm_id="gm"):
        self.session_id = session_id
        self.controller_for = controller_for
        self.publish = publish
        self.gm_id = gm_id
        self.condition = Condition(RLock())
        self._frames = []
        self._operations = deque()
        self._revision = 0
        self._stopped = False
        self._closed = False

    def checkpoint(self):
        with self.condition:
            if self._stopped or self._closed:
                raise SessionStopped()

    def stop(self):
        with self.condition:
            self._stopped = True
            self.condition.notify_all()

    def close(self):
        with self.condition:
            self._closed = True
            self.condition.notify_all()

    def _serialize(self, request):
        self._revision += 1
        dto = {
            "session_id": self.session_id,
            "request_id": uuid4().hex,
            "revision": self._revision,
            "controller_id": self.controller_for(request.character),
            "character_id": request.character.character_id,
            "phase": request.phase,
            "prompt": request.prompt,
            "allow_refresh": request.allow_refresh,
            "allow_cancel": False,
        }
        if isinstance(request, NumericDecisionRequest):
            dto.update(kind="numeric", minimum=request.minimum, maximum=request.maximum)
        else:
            dto.update(kind="choice", options=[
                {"option_id": f"option:{index}", "label": option.label}
                for index, option in enumerate(request.options, 1)
            ])
        return dto

    def current(self, controller_id):
        with self.condition:
            if not self._frames or self._closed or self._stopped:
                return None
            frame = self._frames[-1]
            if (not frame.accepting or frame.answered
                    or controller_id not in {frame.dto["controller_id"], self.gm_id}):
                return None
            return deepcopy(frame.dto)

    def submit(self, controller_id, request_id, revision, *, option_id=None, value=None):
        with self.condition:
            if not self._frames or self._closed or self._stopped:
                raise ValueError("当前没有等待回答的决策")
            frame = self._frames[-1]
            if controller_id not in {frame.dto["controller_id"], self.gm_id}:
                raise PermissionError("不能替其他玩家回答")
            if (not frame.accepting or frame.answered
                    or request_id != frame.dto["request_id"]
                    or type(revision) is not int or revision != frame.dto["revision"]):
                raise ValueError("决策已过期或已经提交")
            if isinstance(frame.request, NumericDecisionRequest):
                if option_id is not None or type(value) is not int:
                    raise ValueError("数值决策必须提交整数value")
                frame.answer = frame.request.resolve(value)
            else:
                if value is not None:
                    raise ValueError("选项决策只能提交option_id")
                options = frame.dto["options"]
                index = next((i for i, option in enumerate(options)
                              if option["option_id"] == option_id), None)
                if index is None:
                    raise ValueError("未知的option_id")
                frame.answer = frame.request.options[index].value
            frame.answered = True
            frame.accepting = False
            # Logging happens on the worker, after the external caller releases
            # the lock. No engine objects are read on the submitting thread.
            frame.submission = {"controller_id": controller_id, "option_id": option_id, "value": value}
            self.condition.notify_all()

    def enqueue_operation(self, controller_id, operation):
        with self.condition:
            if self._closed or self._stopped or not self._frames:
                raise ValueError("即时操作需要一个等待中的决策窗口")
            frame = self._frames[-1]
            if not frame.accepting or frame.answered or not frame.request.allow_refresh:
                raise ValueError("当前窗口不接受即时操作，请先完成当前选择")
            operation_id = uuid4().hex
            frame.accepting = False
            self._operations.append((operation_id, controller_id, operation))
            self.condition.notify_all()
            return operation_id

    def choose(self, request):
        self.checkpoint()
        with self.condition:
            frame = _PendingDecision(request, self._serialize(request))
            self._frames.append(frame)
            audience = frame.dto["controller_id"]
            self.publish("decision_requested", frame.dto, audience)
        try:
            while True:
                with self.condition:
                    self.condition.wait_for(lambda: self._stopped or self._closed or frame.answered or self._operations)
                    self.checkpoint()
                    if frame.answered:
                        submission = {
                            **frame.dto,
                            **frame.submission,
                        }
                        self.publish("decision_answered", submission, audience)
                        return frame.answer
                    operation_id, controller_id, operation = self._operations.popleft()
                    self.publish("decision_invalidated", {
                        "request_id": frame.dto["request_id"],
                        "revision": frame.dto["revision"],
                    }, audience)
                try:
                    result = operation()
                except SessionStopped:
                    raise
                except (ValueError, PermissionError) as error:
                    self.publish("operation_failed", {
                        "operation_id": operation_id, "error": str(error),
                    }, controller_id)
                    # Rebuild even after a rejected operation: a nested rule
                    # effect might already have changed resources or targets.
                    raise DecisionRefreshRequested()
                else:
                    self.publish("operation_completed", {
                        "operation_id": operation_id, "result": result,
                    }, controller_id)
                    raise DecisionRefreshRequested()
        finally:
            with self.condition:
                self._frames.remove(frame)
                self.condition.notify_all()

    def notify(self, message, *, recipient=None):
        self.publish("notification", {"message": str(message)},
                     None if recipient is None else self.controller_for(recipient))
