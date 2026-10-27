"""Small, persistent skill laboratory built on the production game rules."""

from itertools import combinations

from game.character import create_character_from_card
from game.character.masters import Master
from game.character.npc import NPC
from game.character.servants import Servant
from game.game.game_manager import GameManager
from game.map.map import HIGH_LEVEL_NAME_SUFFIX, Location, Map, get_distance
from game.map.travel_group import TravelGroup
from game.skill.skill_runtime import iter_character_skills, load_class_skill
from game.turn.damage import report_discarded_attacks


DEFAULT_TEST_MASTER_CARD = "master_test_0"
DEFAULT_TEST_SERVANT_CARD = "servant_test_0"


class SkillTestGameManager(GameManager):
    """A game which only ends when the operator explicitly quits."""

    def end_game(self, reason="external", winners=None):
        if reason not in {"manual_quit", "manual_interrupt", "end_of_input"}:
            self.suppressed_end_reasons = getattr(self, "suppressed_end_reasons", [])
            self.suppressed_end_reasons.append(reason)
            return False
        return super().end_game(reason=reason, winners=winners)


def _mark_test_opponent(character, role, card_id):
    character.is_npc = True
    character.controller = "gm"
    character.skill_test_opponent = True
    character.skill_test_role = role
    character.skill_test_card_id = card_id
    character.test_prevent_death = True
    character.endurance.value = 10
    character.magic.value = 10
    character.hp = character.hpmax
    character.mp = character.mpmax
    if not hasattr(character, "class_skills"):
        character.class_skills = []
    if not any(skill.skill_id == "class:测试程序" for skill in character.class_skills):
        load_class_skill(character, "测试程序", "GM")
    return character


def _create_player_characters(entries, spawn):
    """Create up to two human-operated cards or fixed-data ally NPCs."""
    if not 1 <= len(entries) <= 2:
        raise ValueError("玩家方必须加入一至两名角色")
    result = []
    masters = []
    for index, entry in enumerate(entries, 1):
        if entry == "fixed":
            actor = NPC(
                f"固定测试友军{index}",
                strength=3,
                endurance=3,
                flexibility=3,
                magic=3,
                fortune=3,
                move_conversion=2,
            )
            actor.controller = "player"
            actor.skill_test_player_controlled = True
            actor.position = spawn
        else:
            actor = create_character_from_card(entry, position=spawn)
            actor.name = f"玩家{index}·{actor.name}"
        if isinstance(actor, Master):
            masters.append(actor)
        result.append(actor)

    # A selected Master and Servant form the natural test pair.  Other
    # combinations remain ordinary allies without inventing ownership.
    free_master = next((actor for actor in masters if len(actor.servants) < 2), None)
    for actor in result:
        if isinstance(actor, Servant) and actor.master is None and free_master is not None:
            free_master.add_servant(actor)
    for first, second in combinations(result, 2):
        first.add_ally(second, source="skill_test_player_side")
    return result


def create_skill_test_scenario(
    player_entries,
    *,
    test_master_card=DEFAULT_TEST_MASTER_CARD,
    test_servant_card=DEFAULT_TEST_SERVANT_CARD,
):
    """Create A-roadAB-B-roadBC-C with player side at A and test side at C."""
    game_map = Map()
    a, b, c = (Location(name) for name in ("A", "B", "C"))
    for location in (a, b, c):
        game_map.add_location(location)
    road_ab = game_map.add_road(a, b)
    road_bc = game_map.add_road(b, c)
    road_ab.name = "roadAB"
    road_bc.name = "roadBC"

    players = _create_player_characters(list(player_entries), a)
    test_master = _mark_test_opponent(
        create_character_from_card(test_master_card, position=c),
        "master",
        test_master_card,
    )
    if not isinstance(test_master, Master):
        raise ValueError("测试Master模板必须是御主角色卡")
    test_master.name = f"测试Master·{test_master.name}"
    test_servant = _mark_test_opponent(
        create_character_from_card(test_servant_card, position=c, master=test_master),
        "servant",
        test_servant_card,
    )
    if not isinstance(test_servant, Servant):
        raise ValueError("测试Servant模板必须是从者角色卡")
    test_servant.name = f"测试Servant·{test_servant.name}"

    actors = [*players, test_master, test_servant]
    actual_players = [actor for actor in players if not getattr(actor, "is_npc", False)]
    game = SkillTestGameManager(
        actors,
        b,
        player_characters=actual_players,
        maximum_turns=2**31 - 1,
        grail_appearance_deaths=2**30,
        grail_ready_deaths=2**30,
    )
    game.game_map = game_map
    game.locations = {node.name: node for node in (a, b, c, road_ab, road_bc)}
    game.skill_test_npcs = {"master": test_master, "servant": test_servant}
    game.skill_test_npc_cards = {
        "master": test_master_card,
        "servant": test_servant_card,
    }
    game.skill_test_death_protection = {"master": True, "servant": True}
    game.skill_test_patrol_endpoints = (a, c)
    game.skill_test_patrol_group = TravelGroup(
        test_master,
        [test_master, test_servant],
    )
    game.skill_test_service = SkillTestService(game)
    return game


class SkillTestService:
    """Test-only mutations kept outside card effects and ordinary actions."""

    def __init__(self, game):
        self.game = game

    def resolve_role(self, role, *, living=True):
        key = str(role).strip().casefold()
        if key not in {"master", "servant"}:
            raise ValueError(f"测试角色参数必须是master或servant：{role}")
        actor = self.game.skill_test_npcs.get(key)
        if actor is None or (living and not actor.is_alive()):
            raise ValueError(f"测试角色当前不存在或已经死亡：{key}")
        return actor

    def resolve_target(self, value):
        key = str(value).strip().casefold()
        if key in {"master", "servant"}:
            return self.resolve_role(key)
        return self.game_manager_commands.resolve_target(value)

    @property
    def game_manager_commands(self):
        from game.game.gm_commands import GMCommandService

        return GMCommandService(self.game)

    @staticmethod
    def _boolean(value):
        normalized = str(value).strip().casefold()
        if normalized not in {"true", "false"}:
            raise ValueError("boolean参数必须是true或false")
        return normalized == "true"

    def prevent_death(self, target, enabled):
        enabled = self._boolean(enabled)
        key = str(target).strip().casefold()
        roles = ("master", "servant") if key == "all" else (key,)
        actors = []
        for role in roles:
            actor = self.resolve_role(role)
            actor.test_prevent_death = enabled
            self.game.skill_test_death_protection[role] = enabled
            actors.append(actor)
        return {"targets": actors, "enabled": enabled}

    def respawn(self, role):
        key = str(role).strip().casefold()
        old = self.resolve_role(key, living=False)
        if old.is_alive() and old in self.game.characters:
            raise ValueError(f"{key}仍然存活，不能重复生成")
        spawn = self.game.locations["C"]
        card_id = self.game.skill_test_npc_cards[key]
        counterpart_key = "servant" if key == "master" else "master"
        counterpart = self.game.skill_test_npcs.get(counterpart_key)
        master = counterpart if key == "servant" and isinstance(counterpart, Master) and counterpart.is_alive() else None
        actor = _mark_test_opponent(
            create_character_from_card(card_id, position=spawn, master=master),
            key,
            card_id,
        )
        actor.name = f"测试{key.title()}·{actor.name}"
        actor.test_prevent_death = self.game.skill_test_death_protection[key]
        if key == "master" and isinstance(counterpart, Servant) and counterpart.is_alive():
            actor.add_servant(counterpart)
        self.game.register_character(actor, position=spawn, activate_immediately=False)
        self.game.skill_test_npcs[key] = actor
        return actor

    def teleport(self, target, position, *, decision_provider=None):
        actor = self.resolve_target(target)
        destination = self.game_manager_commands.resolve_position(position)
        return self.game_manager_commands.teleport(
            actor,
            destination,
            decision_provider=decision_provider,
        )

    def clear(self):
        manager = self.game.turn_manager
        participants = []
        for battle in list(manager.battles):
            participants.extend(actor for actor in battle.participants if actor not in participants)
            battle.end_battle(reason="gm_clear")
        for first, second in combinations(participants, 2):
            manager.movement_resolver.suppress_contact_until_separated(first, second)

        for character in self.game.characters:
            report_discarded_attacks(character.pending_attacks, "gm_clear")
            character.pending_attacks.clear()
            character.clear_movement_lock()
        manager.battles.clear()
        manager.pending_encounters.clear()
        manager.waiting_encounters.clear()
        manager.teleport_encounters.clear()
        manager.pending_battle_requests.clear()
        manager.battle_phase_pending = False
        master = self.game.skill_test_npcs.get("master")
        servant = self.game.skill_test_npcs.get("servant")
        if (
            master is not None
            and servant is not None
            and master.is_alive()
            and servant.is_alive()
            and master.position is servant.position
        ):
            for actor in (master, servant):
                if actor.travel_group is not None:
                    actor.travel_group.dissolve()
            group = TravelGroup(master, [master, servant])
            self.game.skill_test_patrol_group = group
            if group not in manager.travel_groups:
                manager.travel_groups.append(group)
        return {
            "participants": participants,
            "refresh_decision": bool(participants),
        }

    def building(self, position):
        node = self.game_manager_commands.resolve_position(position)
        if node not in self.game.game_map.locations.values() or getattr(node, "is_high_level", False):
            raise ValueError("building只能指定A、B或C的地面地点")
        node.is_building = True
        if getattr(self.game, "skill_test_high_buildings", False):
            self._make_high_level(node)
        return node

    def _make_high_level(self, node):
        root = node.area_root
        if root.high_level_location is not None:
            return root.high_level_location
        upper = Location(
            f"{root.name}{HIGH_LEVEL_NAME_SUFFIX}",
            is_building=True,
            _area_root=root,
        )
        root.high_level = True
        root.high_level_location = upper
        root.add_connection(upper)
        upper.add_connection(root)
        self.game.game_map.locations[upper.name] = upper
        self.game.locations[upper.name] = upper
        return upper

    def high_building(self):
        self.game.skill_test_high_buildings = True
        return [
            self._make_high_level(node)
            for node in (self.game.locations[name] for name in ("A", "B", "C"))
            if node.is_building
        ]

    def reset_skill(self, skill_id):
        skill_id = str(skill_id).strip()
        if not skill_id:
            raise ValueError("skill_id不能为空")
        matched = []
        for actor in self.game.characters:
            for skill in iter_character_skills(actor):
                if skill.skill_id != skill_id:
                    continue
                matched.append((actor, skill))
                for state in skill.component_runtime_states.values():
                    state.game_uses = 0
                    state.turn_uses.clear()
                    state.battle_uses.clear()
                skill.expired_component_ids.clear()
        if not matched:
            raise ValueError(f"场上角色均未持有技能：{skill_id}")
        event_manager = self.game.event_manager
        owner_ids = {id(actor) for actor, _skill in matched}

        def belongs_to_skill(key):
            return any(
                key[index] in owner_ids and key[index + 1] == skill_id
                for index in range(len(key) - 1)
            )

        event_manager._event_uses = {
            key for key in event_manager._event_uses
            if not belongs_to_skill(key)
        }
        event_manager._turn_uses = {
            key: value for key, value in event_manager._turn_uses.items()
            if not belongs_to_skill(key)
        }
        event_manager._chain_uses = {
            key for key in event_manager._chain_uses
            if not belongs_to_skill(key)
        }
        event_manager._lifecycle_reservations = {
            key for key in event_manager._lifecycle_reservations
            if not belongs_to_skill(key)
        }
        return matched

    def show(self, content, target=None):
        kind = str(content).strip().casefold()
        if kind not in {"event", "modifier", "status", "pending_attacks"}:
            raise ValueError(f"未知的展示内容：{content}")
        actors = self.game.characters if target is None else [self.resolve_target(target)]
        if kind == "event":
            current = list(self.game.event_manager._stack)
            delayed = [entry for entry in self.game.delay_manager.entries if not entry.resolved and not entry.cancelled]
            if target is not None:
                actor = actors[0]
                current = [event for event in current if actor in {event.actor, event.source, event.target} or actor in event.targets]
                delayed = [entry for entry in delayed if actor in {entry.actor, entry.target}]
            return {"current": current, "delayed": delayed}
        if kind == "modifier":
            return {actor: list(actor.modifiers) for actor in actors}
        if kind == "status":
            from game.status.runtime import iter_status_runtimes, status_view

            return {actor: [status_view(runtime.status_modifier) for runtime in iter_status_runtimes(actor)] for actor in actors}
        return {actor: [attack for attack in actor.pending_attacks if not attack.resolved] for actor in actors}


class SkillTestAutomation:
    """Choose only out-of-battle patrol decisions for the two fixed NPCs."""

    def __init__(self, game):
        self.game = game
        self.goals = {actor: game.locations["A"] for actor in game.skill_test_npcs.values()}
        self.reached_during_plan = set()

    def handles(self, request):
        actor = request.character
        return bool(
            getattr(actor, "skill_test_opponent", False)
            and actor.is_alive()
            and not actor.in_battle
        )

    def choose(self, request):
        actor = request.character
        options = list(getattr(request, "options", ()))

        if request.phase == "AP1—同行":
            return False

        battle = next((option for option in options if isinstance(option.value, tuple) and option.value and option.value[0] == "battle"), None)
        if battle is not None:
            return battle.value
        finish = next((option for option in options if option.value == "finish"), None)
        if finish is not None and any(option.value == "finish" for option in options) and actor in self.reached_during_plan:
            self.reached_during_plan.discard(actor)
            return "finish"
        if request.phase == "move_path":
            goal = self.goals.setdefault(actor, self.game.locations["A"])
            step_options = [option for option in options if isinstance(option.value, tuple) and option.value and option.value[0] == "step"]
            if step_options:
                choice = min(step_options, key=lambda option: get_distance(option.value[1], goal) if get_distance(option.value[1], goal) is not None else 10**9)
                if choice.value[1] is goal:
                    self.reached_during_plan.add(actor)
                    self.goals[actor] = self.game.locations["C"] if goal is self.game.locations["A"] else self.game.locations["A"]
                return choice.value
            if finish is not None:
                return finish.value
        move = next((option for option in options if getattr(option.value, "action_id", None) == "move"), None)
        if move is not None:
            return move.value
        declaration_finish = next((option for option in options if option.value == "finish"), None)
        if declaration_finish is not None:
            return declaration_finish.value
        following = next((option for option in options if option.value == "follow"), None)
        if following is not None:
            return following.value
        continuing = next((option for option in options if option.value == "continue"), None)
        if continuing is not None:
            return continuing.value
        passing = next((option for option in options if getattr(option.value, "action_id", None) == "pass" or option.value == "pass"), None)
        if passing is not None:
            return passing.value
        optional_skip = next((
            option
            for option in options
            if option.value is None
            or option.value is False
            or option.value == "skip"
            or any(word in option.label for word in ("不发动", "跳过", "取消"))
        ), None)
        if optional_skip is not None:
            return optional_skip.value
        if options:
            # Fixed test cards may contain mandatory start-of-turn choices.
            # Keep their out-of-battle behavior deterministic until the GM
            # replaces the placeholder cards with the final templates.
            return options[0].value
        raise ValueError(f"测试NPC没有可用的自动选择：{request.phase}")
