"""Local terminal launcher: python -m core --menu."""

import argparse
from contextlib import redirect_stdout
from datetime import datetime
import json
from pathlib import Path
import random
import sys
import traceback
import uuid

from game.character import list_character_cards
from game.character.card_factory import get_character_card_definition
from core.catalog import CatalogProject, DEFAULT_CATALOG, ROOT
from core.scenarios import create_manual_scenario, start_manual_scenario
from game.rule_report import identity
from game.session_view import character_view
from core.terminal_game_runner import GameTerminalDecisionProvider, TerminalGameRunner
from core.terminal_commands import GameExitRequested


class Transcript:
    def __init__(self, console, file):
        self.console, self.file = console, file

    def write(self, text):
        self.console.write(text)
        self.file.write(text)
        self.file.flush()
        return len(text)

    def flush(self):
        self.console.flush()
        self.file.flush()

    def __getattr__(self, key):
        return getattr(self.console, key)


def choose_cards():
    teams = []
    for team in "AB":
        chosen = []
        for kind, label in (("master", "御主"), ("servant", "从者")):
            ids = list_character_cards(character_type=kind)
            if not ids:
                raise ValueError(f"目录中没有{label}卡")
            print(f"{team}方{label}卡：")
            for index, key in enumerate(ids, 1):
                print(f"  {index}. {get_character_card_definition(key)['name']} [{key}]")
            default = "master_test_0" if kind == "master" else "servant_test_0"
            while True:
                answer = input(f"编号或卡ID（回车使用{default}）：").strip()
                if not answer:
                    answer = default
                if answer.isdigit() and 1 <= int(answer) <= len(ids):
                    answer = ids[int(answer) - 1]
                if answer in ids:
                    chosen.append(answer)
                    break
                print("请选择列表中的卡。")
        teams.append(tuple(chosen))
    return teams


def menu(teams):
    while True:
        print("\nPapermoon core · 单人人工测试")
        print("你依次操作双方全部角色；所有反应、目标和保命选择均由你回答。")
        print("1. 直接对战：双方主从在中央广场开战")
        print("2. 地图流程：双方分处住宅区、教会，自行移动与相遇")
        print("3. 更换双方使用的角色卡")
        print("4. 原基础场景（通用测试角色）")
        print("0. 退出")
        print("当前卡组：" + "；".join(f"{team}方 {master} + {servant}" for team, (master, servant) in zip("AB", teams)))
        answer = input("> ").strip()
        if answer in {"0", "quit"}:
            return None, teams
        if answer == "3":
            teams = choose_cards()
        elif answer in {"1", "2", "4"}:
            return {"1": "battle", "2": "map", "4": "basic"}[answer], teams
        else:
            print("请输入0至4。")


def run_manual(project, *, scenario="battle", teams=None, seed=None, maximum_turns=120,
               log_root=ROOT / "userdata" / "runs", input_func=input, output_func=print):
    if seed is None:
        seed = random.SystemRandom().randrange(2**32)
    random_state = random.getstate()
    random.seed(seed)
    folder = Path(log_root) / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6])
    folder.mkdir(parents=True, exist_ok=False)
    game, result, error = None, None, None
    try:
        with (folder / "terminal.txt").open("w", encoding="utf-8") as transcript,\
                (folder / "reports.jsonl").open("w", encoding="utf-8") as journal,\
                redirect_stdout(Transcript(sys.stdout, transcript)), project.activate():
            snapshot = {"format_version": 1, **project.effective()}
            (folder / "catalog.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
            game = create_manual_scenario(scenario, teams=teams, maximum_turns=maximum_turns)

            def write_report(record, _context):
                journal.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                journal.flush()

            def logged_input(prompt):
                command = input_func(prompt)
                transcript.write(str(command) + "\n")
                transcript.flush()
                return command

            game.rule_reports.subscribe(write_report)
            provider = GameTerminalDecisionProvider(game, input_func=logged_input, output_func=output_func)
            runner = TerminalGameRunner(game, provider)
            print(f"\n场景：{scenario} | 随机种子：{seed}")
            print("辅助指令：help、status、status all、map、position、grail、commandspell、quit")
            print("这是单人兼任双方与GM的测试入口，status all可以查看所有存活角色。")
            print(f"本次测试记录：{folder}\n")
            try:
                start_manual_scenario(game)
                result = runner.run()
            except GameExitRequested:
                result = runner.get_result()
                runner.announce_game_result()
            except KeyboardInterrupt:
                game.force_end_game(reason="manual_interrupt")
                result = runner.get_result()
                print("\n测试已中断，正在保存记录。")
            finally:
                game.rule_reports.unsubscribe(write_report)
    except Exception:
        error = traceback.format_exc()
        (folder / "error.txt").write_text(error, encoding="utf-8")
        raise
    finally:
        random.setstate(random_state)
        reports = [] if game is None else game.rule_reports.history
        (folder / "reports.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
        summary = {"audience": "gm", "scenario": scenario, "seed": seed,
                   "catalog_path": str(project.path), "teams": teams,
                   "error": error, "result": None if result is None else {
                       **result, "winners": [identity(actor) for actor in result["winners"]]},
                   "characters": [] if game is None else [character_view(actor, lambda node: getattr(node, "name", None), exact=True)
                                                           for actor in game.all_characters]}
        (folder / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        output_func(f"记录已保存：{folder}")
    return result, folder


def main(argv=None):
    parser = argparse.ArgumentParser(description="Papermoon core：本地单人人工测试")
    parser.add_argument("--menu", action="store_true", help="显示场景及角色卡选择菜单")
    parser.add_argument("--scenario", choices=["battle", "map", "basic"], default="battle")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--master-card", default="master_test_0")
    parser.add_argument("--servant-card", default="servant_test_0")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--maximum-turns", type=int, default=120)
    parser.add_argument("--check", action="store_true", help="只校验内容项目，不开始游戏")
    parser.add_argument("--pause-on-exit", action="store_true", help="结束后等待回车，供编辑器启动使用")
    args = parser.parse_args(argv)
    if args.maximum_turns < 1:
        parser.error("最大回合数必须至少为1")
    try:
        project = CatalogProject(args.catalog)
        if args.check:
            print(json.dumps(project.validate(), ensure_ascii=False, indent=2))
            return 0
        teams = [(args.master_card, args.servant_card)] * 2
        with project.activate():
            scenario, teams = menu(teams) if args.menu else (args.scenario, teams)
        if scenario is not None:
            run_manual(project, scenario=scenario, teams=teams, seed=args.seed,
                       maximum_turns=args.maximum_turns)
        return 0
    except (EOFError, KeyboardInterrupt):
        print("\n已退出启动菜单。")
        return 0
    except Exception as error:
        print(f"启动或运行失败：{error}", file=sys.stderr)
        print("如已开始测试，请查看userdata/runs中最新目录的error.txt。", file=sys.stderr)
        return 1
    finally:
        if args.pause_on_exit:
            try:
                input("按回车关闭此测试终端……")
            except (EOFError, KeyboardInterrupt):
                pass


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
