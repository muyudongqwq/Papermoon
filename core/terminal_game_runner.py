from game.game.game_loop import GameLoop
from core.terminal_commands import GameExitRequested, TerminalCommandHandler
from game.game.command_spell import CommandSpellService
from game.turn.decision import (
    DecisionRefreshRequested,
    DecisionOption,
    DecisionRequest,
    NumericDecisionRequest,
)


class GameTerminalDecisionProvider:
    """终端决策器：默认只显示回合、角色和可用选项。"""

    def __init__(
        self,
        game_manager,
        input_func=input,
        output_func=print,
    ):
        self.game_manager = game_manager
        self.input = input_func
        self.output = output_func
        self.command_handler = TerminalCommandHandler(
            game_manager,
            output_func=output_func,
            decision_provider=self,
        )
        self.command_spell_service = CommandSpellService(game_manager)
        self._in_command_spell_menu = False

    def _choose_from(self, character, phase, options):
        return self.choose(DecisionRequest(
            character=character,
            phase=phase,
            prompt="",
            options=tuple(options),
        ))

    def handle_command_spell(self, current_character):
        masters = self.command_spell_service.available_masters()
        if not masters:
            self.output("没有可使用令咒的御主。")
            return False
        self._in_command_spell_menu = True
        try:
            master = self._choose_from(
                current_character,
                "令咒—选择御主",
                [
                    DecisionOption(
                        f"{master.name}（剩余{master.command_spell}划）",
                        master,
                        (master.name,),
                    )
                    for master in masters
                ] + [DecisionOption("返回", None, ("back", "返回"))],
            )
            if master is None:
                return False
            effects = [
                DecisionOption("临时MP+90（1划）", "mp", ("mp",)),
                DecisionOption("下一次攻击伤害+90（1划）", "damage", ("damage",)),
            ]
            teleport_targets = [
                target
                for target in master.servants
                if self.command_spell_service.teleport_destinations(master, target)
            ]
            if master.command_spell >= 2 and teleport_targets:
                effects.append(DecisionOption(
                    "瞬间移动从者（2划）",
                    "teleport",
                    ("teleport", "瞬移"),
                ))
            effects.append(DecisionOption("返回", None, ("back", "返回")))
            effect = self._choose_from(master, "令咒", effects)
            if effect is None:
                return False
            targets = self.command_spell_service.controlled_characters(master)
            if effect == "teleport":
                targets = teleport_targets
            target = self._choose_from(
                master,
                "令咒—选择对象",
                [DecisionOption(target.name, target, (target.name,)) for target in targets]
                + [DecisionOption("返回", None, ("back", "返回"))],
            )
            if target is None:
                return False
            if effect == "mp":
                changed = self.command_spell_service.grant_temporary_mp(master, target)
            elif effect == "damage":
                changed = self.command_spell_service.grant_damage_bonus(master, target)
            else:
                destination = self._choose_from(
                    target,
                    "令咒—瞬间移动",
                    [
                        DecisionOption(location.name, location, (location.name,))
                        for location in self.command_spell_service.teleport_destinations(master, target)
                    ] + [DecisionOption("返回", None, ("back", "返回"))],
                )
                if destination is None:
                    return False
                guard_targets = self.command_spell_service.emergency_guard_targets(
                    master,
                    target,
                    destination,
                )
                emergency_guard_target = None
                if guard_targets:
                    emergency_guard_target = self._choose_from(
                        target,
                        "令咒—紧急援护目标",
                        [
                            DecisionOption(
                                guard_target.name,
                                guard_target,
                                (guard_target.name,),
                            )
                            for guard_target in guard_targets
                        ] + [
                            DecisionOption(
                                "不援护",
                                None,
                                ("skip", "pass", "不援护"),
                            )
                        ],
                    )
                changed = self.command_spell_service.teleport(
                    master,
                    target,
                    destination,
                    emergency_guard_target=emergency_guard_target,
                    decision_provider=self,
                )
            if changed:
                self.output(f"{master.name}使用了令咒。剩余{master.command_spell}划。")
            return bool(changed)
        finally:
            self._in_command_spell_menu = False

    def display_request(self, request):
        if request.phase == "move_path":
            self.output("可选道路：")
            for index, option in enumerate(request.options, start=1):
                self.output(f"{index}.{option.label}")
            return
        character_name = getattr(
            request.character,
            "name",
            str(request.character),
        )
        self.output(f"全局回合：{self.game_manager.turn_manager.turn}")
        self.output(character_name)
        self.output("可用行动：")
        if isinstance(request, NumericDecisionRequest):
            self.output(f"{request.minimum}-{request.maximum}")
        else:
            for index, option in enumerate(request.options, start=1):
                self.output(f"{index}.{option.label}")

    def choose(self, request):
        while True:
            self.display_request(request)
            try:
                command = self.input("> ")
            except EOFError:
                self.game_manager.force_end_game(reason="end_of_input")
                raise GameExitRequested()

            if (
                not self._in_command_spell_menu
                and str(command).strip().casefold() == "commandspell"
            ):
                changed = self.handle_command_spell(request.character)
                if changed and request.phase in {
                    "攻击", "防御", "攻击目标选择", "AP1", "AP2", "move_path"
                }:
                    raise DecisionRefreshRequested()
                continue
            if self.command_handler.handle(command, request.character):
                continue
            try:
                return request.resolve(command)
            except ValueError:
                self.output("输入无效，请重新选择。")

    def separate_action(self):
        self.output("")

    def notify(self, message, *, recipient=None):
        if recipient is not None:
            self.output(f"{getattr(recipient, 'name', recipient)}：{message}")
        else:
            self.output(str(message))


class TerminalGameRunner(GameLoop):
    """Terminal adapter for the shared synchronous game loop.

    Inherited planning methods remain available for existing callers.
    """

    def __init__(self, game_manager, decision_provider=None):
        super().__init__(
            game_manager,
            decision_provider if decision_provider is not None
            else GameTerminalDecisionProvider(game_manager),
        )
        self.result_announced = False

    def run(self):
        try:
            result = super().run()
        except GameExitRequested:
            result = self.get_result()
        self.announce_game_result()
        return result

    def on_action_collected(self):
        separator = getattr(self.decision_provider, "separate_action", None)
        if separator is not None:
            separator()

    def announce_game_result(self):
        if self.result_announced or not self.game_manager.check_game_end():
            return False
        output = getattr(self.decision_provider, "output", print)
        reason = self.game_manager.end_reason or "unknown"
        output(f"游戏结束原因：{reason}")
        if reason == "victory":
            winner_names = ", ".join(
                character.name
                for character in self.game_manager.winners
            ) or "无"
            output(f"胜利者：{winner_names}")
        self.result_announced = True
        return True
