import shlex

from game.gm_commands import GMCommandService


class GameExitRequested(Exception):
    """终端使用者要求结束当前游戏。"""


class TerminalCommandHandler:
    """处理不消耗行动的终端保留指令。"""

    COMMANDS = {
        "status",
        "status all",
        "map",
        "position",
        "grail",
        "help",
        "quit",
    }
    GM_COMMANDS = {
        "add_resource": 3,
        "damage": 3,
        "teleport": 2,
        "kill": 1,
    }

    def __init__(
        self,
        game_manager,
        output_func=print,
        decision_provider=None,
    ):
        self.game_manager = game_manager
        self.output = output_func
        self.decision_provider = decision_provider
        self.gm_commands = GMCommandService(game_manager)
        self.last_result = None

    @staticmethod
    def _split(command):
        try:
            return shlex.split(str(command).strip())
        except ValueError as error:
            raise ValueError(f"无法解析指令：{command}") from error

    def _handle_gm_command(self, parts):
        command_name = parts[0].casefold()
        expected = self.GM_COMMANDS[command_name]
        parameters = parts[1:]
        if len(parameters) != expected:
            raise ValueError(
                f"{command_name}需要{expected}个参数，"
                f"实际收到{len(parameters)}个"
            )
        if command_name == "add_resource":
            result = self.gm_commands.add_resource(*parameters)
            self.output(
                f"GM：{result['target'].name}的{result['resource_id']} "
                f"{result['old_value']}→{result['new_value']}"
            )
        elif command_name == "damage":
            result = self.gm_commands.damage(
                *parameters,
                decision_provider=self.decision_provider,
            )
            self.output(
                f"GM：{result['target'].name}受到"
                f"{result['final_damage']}点{result['damage_type']}伤害。"
            )
        elif command_name == "teleport":
            result = self.gm_commands.teleport(
                *parameters,
                decision_provider=self.decision_provider,
            )
            self.output(
                f"GM：{result['target'].name}被转移至"
                f"{result['destination'].name}。"
            )
        else:
            result = self.gm_commands.kill(*parameters)
            self.output(f"GM：{result['target'].name}已死亡。")
        self.last_result = result
        return True

    def handle(self, command, character=None):
        normalized = str(command).strip().casefold()
        parts = self._split(command)
        if parts and parts[0].casefold() in self.GM_COMMANDS:
            return self._handle_gm_command(parts)
        if normalized not in self.COMMANDS:
            return False
        if normalized == "status":
            self.show_character(character)
        elif normalized == "status all":
            for current in self.game_manager.characters:
                self.show_character(current)
        elif normalized == "map":
            self.show_map(character)
        elif normalized == "position":
            self.show_position(character)
        elif normalized == "grail":
            self.show_grail()
        elif normalized == "help":
            self.show_help()
        elif normalized == "quit":
            self.game_manager.force_end_game(reason="manual_quit")
            raise GameExitRequested()
        return True

    def show_character(self, character):
        if character is None:
            self.output("当前没有正在行动的角色。")
            return
        position = getattr(character.position, "name", "未设置")
        statuses = ", ".join(sorted(character.status_flags)) or "无"
        custom_resources = ", ".join(
            (
                f"{resource.name} "
                f"{resource.current_value}"
                + (
                    f"/{resource.maximum}"
                    if resource.maximum is not None
                    else ""
                )
            )
            for resource in character.resources.values()
        )
        identity = character.name
        servant_class = getattr(character, "servant_class", None)
        if servant_class is not None:
            identity += f" | 职介：{servant_class}"
        visibility = character.format_non_ally_visibility()
        if visibility:
            identity += (
                visibility
                if servant_class is not None
                else f" | {visibility}"
            )
        resource_display = (
            f" | 特殊资源 {custom_resources}" if custom_resources else ""
        )
        casting = getattr(character, "casting_state", None)
        casting_display = (
            f" | 咏唱 {casting.name}（{casting.layers}层）"
            if casting is not None
            else ""
        )
        self.output(
            f"{identity} | HP {character.hp}/{character.hpmax} | "
            f"MP {character.mp}/{character.mpmax}"
            f"（临时{character.temporary_mp}） | AP {character.action_point} | "
            f"位置 {position} | 状态 {statuses}"
            f"{resource_display}{casting_display}"
        )

    def show_position(self, character):
        if character is None or character.position is None:
            self.output("当前角色没有地图位置。")
            return
        self.output(f"位置：{character.position.name}")
        fields = getattr(character.position, "field_effects", [])
        if fields:
            self.output("场地：" + "、".join(field.name for field in fields))

    def show_map(self, character):
        if character is None or character.position is None:
            self.output("当前角色没有地图位置。")
            return
        connected = ", ".join(
            location.name
            for location in character.position.connected_locations
        ) or "无"
        self.output(f"当前位置：{character.position.name}")
        self.output(f"相邻节点：{connected}")
        fields = getattr(character.position, "field_effects", [])
        if fields:
            self.output("当前场地：" + "、".join(field.name for field in fields))

    def show_grail(self):
        grail = self.game_manager.holy_grail
        self.game_manager.refresh_grail_state()
        if not grail.appeared:
            self.output("圣杯尚未出现。")
            return
        position = getattr(grail.position, "name", "未知")
        carrier = getattr(grail.carrier, "name", "无")
        self.output(
            f"圣杯位置：{position} | 携带者：{carrier} | "
            f"状态：{'Ready' if grail.ready else '未就绪'}"
        )

    def show_help(self):
        self.output(
            "辅助指令：status, status all, position, map, "
            "grail, commandspell, help, quit"
        )
        self.output(
            "GM指令：add_resource [target] [resource_name] [amount], "
            "damage [target] [damage_type] [amount], "
            "teleport [target] [target_position], kill [target]"
        )
