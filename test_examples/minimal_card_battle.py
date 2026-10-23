"""Repeatable combat acceptance run using two copies of the recorded cards.

python test_examples/minimal_card_battle.py --output test_examples/results/minimal_card_battle.json
"""

import argparse
from collections import Counter
import contextlib
import io
import json
from pathlib import Path
import random
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from game.character import create_character_from_card
from game.game.game_manager import GameManager
from game.game.game_session import GameSession
from game.map.map import Location
from game.turn.battle import BattleManager


def create_scenario():
    location = Location("录卡实战场", is_building=True)
    characters = []
    controllers = {}
    teams = {}
    for team in ("A", "B"):
        master = create_character_from_card("master_test_0", name=f"{team}方御主", position=location)
        servant = create_character_from_card("servant_test_0", name=f"{team}方尼禄", position=location, master=master)
        characters.extend([master, servant])
        for actor in (master, servant):
            controllers[actor.character_id] = team
            teams[actor.character_id] = team
    game = GameManager(characters, location, maximum_turns=12,
                       grail_appearance_deaths=1, grail_ready_deaths=1)
    game.start_game()
    battle = BattleManager(characters)
    game.turn_manager.battles.append(battle)
    battle.start_battle()
    return GameSession(game, controllers), teams


class CombatPolicy:
    """A scripted client, choosing only options offered by the engine."""

    def __init__(self, teams):
        self.teams = teams
        self.used_fire = set()
        self.healed = set()
        self.multi_target_selected = set()

    def choose(self, request, snapshot):
        if request["kind"] == "numeric":
            return {"value": min(request["maximum"], max(request["minimum"], 5))}
        options = request["options"]
        labels = {option["label"]: option for option in options}
        actor_id = request["character_id"]
        actor = next(item for item in snapshot["characters"] if item["character_id"] == actor_id)
        team = self.teams[actor_id]
        turn = snapshot["turn"]
        phase = request["phase"]
        is_servant = actor["entity_type"] == "servant"
        enemies = [item for item in snapshot["characters"]
                   if self.teams.get(item["character_id"]) != team and item.get("hp", 0) > 0]
        enemies.sort(key=lambda item: (item["entity_type"] != "servant", item["name"]))
        ally_servant = next((item for item in snapshot["characters"]
                             if self.teams.get(item["character_id"]) == team
                             and item["entity_type"] == "servant" and item.get("hp", 0) > 0), None)

        def select(*preferences):
            for preference in preferences:
                if preference in labels:
                    return {"option_id": labels[preference]["option_id"]}
            return None

        if "战斗续行 A" in labels:
            return select("战斗续行 A")
        if "记录：阵地制作" in labels:
            return select("记录：阵地制作")
        if phase.startswith("反应："):
            for label in labels:
                if "无瑕之人" in label:
                    return select(label)
                if "纵使三度迎来夕阳" in label:
                    sun = next(skill for skill in actor["skills"] if skill["name"] == "纵使三度迎来夕阳")
                    if sun["components"][0]["usage"]["used"] < 1:
                        return select(label)
            return select("不发动反应")
        if phase == "攻击":
            if not is_servant and not ally_servant and not any(enemy["entity_type"] == "servant" for enemy in enemies):
                return select("停留")
            if is_servant:
                casting = actor["casting"]
                if casting and casting["layers"] >= 1:
                    return select("解放宝具", "解放")
                if turn <= 2:
                    return select("咏唱")
                fire = next((label for label in labels if "原初之火" in label), None)
                if fire and (actor_id, turn) not in self.used_fire:
                    self.used_fire.add((actor_id, turn))
                    return select(fire)
            elif (actor_id not in self.healed and ally_servant
                  and ally_servant["hp"] < ally_servant["hpmax"] and any(label in labels for label in ("解放魔术", "解放"))):
                self.healed.add(actor_id)
                return select("解放魔术", "解放")
            return select("普通攻击", "停留")
        if phase == "咏唱对象选择":
            desired = "招荡的黄金剧场" if turn == 1 else "童女讴歌的华丽帝政"
            return select(desired)
        if phase == "解放目标选择":
            if not is_servant:
                return select(ally_servant["name"] if ally_servant else actor["name"])
            marker = (actor_id, turn)
            if marker in self.multi_target_selected:
                return select("完成选择")
            self.multi_target_selected.add(marker)
            return select(*(enemy["name"] for enemy in enemies))
        if phase == "攻击目标选择":
            return select(*(enemy["name"] for enemy in enemies))
        if phase == "防御":
            return select("格挡")
        if phase.startswith("AP"):
            return select("空过")
        common = select("继续本阶段", "不进行援护", "不援护", "确认当前骰面", "完成选择", "结束加符使用", "不使用加符", "完成")
        if common:
            return common
        raise RuntimeError(f"实战脚本未处理决策：{actor['name']} / {phase} / {list(labels)}")


def run_acceptance(*, seed=20261021, fixed_die=5, timeout=15):
    """Run one isolated scenario; stop after combat, without declaring a win."""
    random_state = random.getstate()
    session = None
    random.seed(seed)
    with contextlib.ExitStack() as stack:
        if fixed_die is not None:
            # Equal-stat mirror cards must still reroll initiative ties.
            combat_random = SimpleNamespace(randint=lambda _low, _high: fixed_die)
            for module in ("game.turn.roll", "game.turn.defense", "game.action.action", "game.skill.skill_runtime"):
                stack.enter_context(patch(f"{module}.random", combat_random))
        terminal = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        try:
            session, teams = create_scenario()
            policy = CombatPolicy(teams)
            cursor = 0
            ended_combat = False
            decisions = []
            deadline = time.monotonic() + timeout
            session.start()
            while time.monotonic() < deadline:
                for event in session.get_events("gm", after=cursor, timeout=0.1):
                    cursor = event["sequence"]
                    if event["type"] == "rule_report" and event["payload"]["kind"] == "battle_ended":
                        ended_combat = True
                        session.stop()
                    elif event["type"] == "decision_requested" and not ended_combat:
                        request = event["payload"]
                        answer = policy.choose(request, session.get_snapshot("gm"))
                        if answer is None:
                            raise RuntimeError(f"实战脚本缺少合法选项：{request['phase']} / {request.get('options')}")
                        label = (next(option["label"] for option in request["options"]
                                      if option["option_id"] == answer["option_id"])
                                 if "option_id" in answer else answer["value"])
                        decisions.append({"turn": session.get_snapshot("gm")["turn"],
                                          "controller_id": request["controller_id"],
                                          "phase": request["phase"], "answer": label})
                        if len(decisions) > 1000:
                            raise RuntimeError(f"实战决策超过安全上限，末项：{decisions[-1]}")
                        session.submit_decision(request["controller_id"], request["request_id"],
                                                request["revision"], **answer)
                    elif event["type"] == "session_ended":
                        snapshot = session.get_snapshot("gm")
                        if not ended_combat or snapshot["state"] != "stopped":
                            raise RuntimeError(f"实战未自然结束战斗：{snapshot['result']} / {snapshot.get('error')}")
                        if not session.join(2):
                            raise RuntimeError("实战会话线程未结束")
                        events = session.get_events("gm")
                        reports = [item["payload"] for item in events if item["type"] == "rule_report"]
                        counts = Counter(item["kind"] for item in reports)
                        return {
                            "scenario": "recorded_cards_two_teams", "audience": "gm", "seed": seed, "fixed_die": fixed_die,
                            "fixture": "双方各一张正式御主卡与尼禄卡，同格开战；卡面HP、MP、技能不修改。",
                            "stop_rule": "战斗自然结束后停止验收；不宣告整局胜利，回合上限不能代替验收成功。",
                            "summary": {"turns": snapshot["turn"], "decision_count": len(decisions),
                                        "battle_end_reason": next(item["data"]["reason"] for item in reports if item["kind"] == "battle_ended"),
                                        "surviving_teams": sorted({teams[actor["character_id"]] for actor in snapshot["characters"] if actor["hp"] > 0}),
                                        "report_counts": dict(sorted(counts.items())),
                                        "characters": [{"name": actor["name"], "hp": actor["hp"], "mp": actor["mp"],
                                                        "statuses": actor["statuses"]} for actor in snapshot["characters"]]},
                            "decisions": decisions, "reports": reports,
                            "final_snapshot": snapshot, "terminal_log": terminal.getvalue(),
                        }
            raise TimeoutError("实战验收超时")
        finally:
            if session is not None:
                session.stop()
                if not session.join(2):
                    raise RuntimeError("实战会话未能停止")
            random.setstate(random_state)


def main():
    parser = argparse.ArgumentParser(description="已录入角色卡的最小双阵营实战验收")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--seed", type=int, default=20261021)
    parser.add_argument("--random-dice", action="store_true", help="使用种子驱动的正常随机骰，默认固定d10=5")
    args = parser.parse_args()
    result = run_acceptance(seed=args.seed, fixed_die=None if args.random_dice else 5)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
