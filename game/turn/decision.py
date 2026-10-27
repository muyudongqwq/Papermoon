from dataclasses import dataclass, field
from typing import Any, Iterable


class DecisionRefreshRequested(Exception):
    """An immediate effect invalidated the options of an open decision."""


class BattleFlowCleared(Exception):
    """A GM command ended active battles while a decision was open."""


@dataclass(frozen=True)
class DecisionOption:
    """A value that can be selected by number, label, or an alias."""

    label: str
    value: Any
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def matches(self, command):
        normalized = command.strip().casefold()
        names = (self.label, *self.aliases)
        return any(normalized == name.strip().casefold() for name in names)


@dataclass(frozen=True)
class DecisionRequest:
    """A UI-independent description of one decision the engine needs."""

    character: Any
    phase: str
    prompt: str
    options: tuple[DecisionOption, ...]
    allow_refresh: bool = False

    def __init__(self, character, phase, prompt, options: Iterable[DecisionOption], *, allow_refresh=False):
        options = tuple(options)
        if not options:
            raise ValueError("选择请求至少需要一个选项")

        object.__setattr__(self, "character", character)
        object.__setattr__(self, "phase", phase)
        object.__setattr__(self, "prompt", prompt)
        object.__setattr__(self, "options", options)
        object.__setattr__(self, "allow_refresh", bool(allow_refresh))

    def resolve(self, command):
        normalized = str(command).strip()
        if normalized.isdigit():
            index = int(normalized) - 1
            if 0 <= index < len(self.options):
                return self.options[index].value

        matches = [option for option in self.options if option.matches(normalized)]
        if len(matches) == 1:
            return matches[0].value
        if len(matches) > 1:
            raise ValueError(f"指令不唯一：{command}")
        raise ValueError(f"未知指令：{command}")


@dataclass(frozen=True)
class NumericDecisionRequest:
    character: Any
    phase: str
    prompt: str
    minimum: int
    maximum: int
    allow_refresh: bool = False

    def resolve(self, command):
        try:
            value = int(str(command).strip())
        except ValueError as error:
            raise ValueError(f"请输入整数：{command}") from error
        if not self.minimum <= value <= self.maximum:
            raise ValueError(
                f"请输入{self.minimum}至{self.maximum}之间的整数"
            )
        return value


class TerminalDecisionProvider:
    """Reads decisions from a terminal. The battle engine itself never calls input()."""

    def choose(self, request):
        character_name = getattr(request.character, "name", str(request.character))
        print()
        print(character_name)
        print(f"处于：{request.phase}阶段")
        if isinstance(request, NumericDecisionRequest):
            print(
                f"可以输入：{request.minimum}至{request.maximum}的整数"
            )
        else:
            print("可以执行的命令：")
            for index, option in enumerate(request.options, start=1):
                print(f"{index}.{option.label}")
        if request.prompt:
            print(request.prompt)

        while True:
            command = input("> ")
            try:
                return request.resolve(command)
            except ValueError as error:
                print(error)
                print("请输入选项编号或显示出的名称。")

    @staticmethod
    def notify(message, *, recipient=None):
        if recipient is not None:
            print(f"{getattr(recipient, 'name', recipient)}：{message}")
        else:
            print(message)


class ScriptedDecisionProvider:
    """Non-interactive provider used by tests and future replay/AI controllers."""

    def __init__(self, commands):
        self.commands = list(commands)
        self.command_index = 0
        self.requests = []
        self.notifications = []

    def notify(self, message, *, recipient=None):
        self.notifications.append({
            "recipient": recipient,
            "message": str(message),
        })

    def choose(self, request):
        self.requests.append(request)
        if self.command_index >= len(self.commands):
            raise RuntimeError("测试指令已经用尽")
        command = self.commands[self.command_index]
        self.command_index += 1
        return request.resolve(command)

    def choose_optional(self, request, default="confirm"):
        """Consume a scripted command only when it belongs to an optional prompt."""
        if self.command_index >= len(self.commands):
            return default
        command = self.commands[self.command_index]
        try:
            result = request.resolve(command)
        except ValueError:
            return default
        self.requests.append(request)
        self.command_index += 1
        return result
