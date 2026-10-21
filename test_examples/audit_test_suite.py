"""Reproduce the regression audit without third-party dependencies.

Run from the repository root: python test_examples/audit_test_suite.py
"""

import argparse
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from test_examples.minimal_card_battle import run_acceptance
from game.character.card_factory import validate_character_card_catalog
from game.skill.content_registry import validate_content_catalogs


def cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield item


def combat_check(result):
    reports = result["reports"]
    declared = {item["data"]["attack_id"] for item in reports if item["kind"] == "attack_declared"}
    closed = [item["data"]["attack_id"] for item in reports
              if item["kind"] in {"attack_resolved", "attack_cancelled"}]
    assert declared and declared == set(closed), "Attack journal not closed"
    assert len(closed) == len(set(closed)), "Duplicate attack resolution/cancellation"
    assert result["summary"]["turns"] < 12, "Turn limit is not combat success"
    assert result["final_snapshot"]["state"] == "stopped"
    for actor in result["final_snapshot"]["characters"]:
        assert 0 <= actor["hp"] <= actor["hpmax"]
        assert 0 <= actor["mp"] <= actor["mpmax"]
        assert not actor["in_battle"] and not actor["fields"] and not actor["incoming_attacks"]
    json.dumps(result, allow_nan=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--combat-seeds", type=int, default=32)
    args = parser.parse_args()
    if args.combat_seeds < 1:
        parser.error("--combat-seeds must be positive")
    output = ROOT / "test_examples" / "results"
    output.mkdir(exist_ok=True)
    summary = {"suite_runs": [], "terminal": [], "combat": []}
    initial_threads = set(threading.enumerate())
    for seed in (None, 1, 7, 42, 20261021):
        suite = unittest.defaultTestLoader.discover(str(ROOT / "test_examples"), pattern="test_*.py")
        tests = list(cases(suite))
        if seed is not None:
            random.seed(seed)
            random.Random(seed).shuffle(tests)
        stream = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()):
            result = unittest.TextTestRunner(stream=stream).run(unittest.TestSuite(tests))
        if not result.wasSuccessful():
            raise AssertionError(stream.getvalue())
        assert set(threading.enumerate()) <= initial_threads, "Session worker leaked"
        summary["suite_runs"].append({"seed": seed, "shuffled": seed is not None,
                                      "tests": result.testsRun, "passed": True})
        print(f"Suite seed={seed}: {result.testsRun} passed", flush=True)

    sources = [path for path in ROOT.rglob("*.py") if "__pycache__" not in path.parts]
    for path in sources:
        ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    summary["python_files_parsed"] = len(sources)
    summary["catalogs"] = {"character_cards": len(validate_character_card_catalog()),
                           **{key: len(value) for key, value in validate_content_catalogs().items()}}
    for label, stdin, reason in (("quit", "quit\n", "manual_quit"), ("eof", "", "end_of_input")):
        completed = subprocess.run([sys.executable, "main.py"], cwd=ROOT, input=stdin,
                                   text=True, capture_output=True, encoding="utf-8",
                                   env=os.environ | {"PYTHONIOENCODING": "utf-8"}, timeout=10)
        assert completed.returncode == 0 and reason in completed.stdout, completed.stdout + completed.stderr
        summary["terminal"].append({"case": label, "reason": reason, "passed": True})
    for name, kwargs in (("fixed", {}), ("random", {"seed": 1, "fixed_die": None})):
        result = run_acceptance(**kwargs)
        combat_check(result)
        (output / f"minimal_card_battle_{name}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for seed in range(1, args.combat_seeds + 1):
        result = run_acceptance(seed=seed, fixed_die=None)
        combat_check(result)
        summary["combat"].append({"seed": seed, "ok": True, "turns": result["summary"]["turns"],
            "surviving_teams": result["summary"]["surviving_teams"],
            "decisions": result["summary"]["decision_count"]})
        if seed % 8 == 0:
            print(f"Random combat: {seed}/{args.combat_seeds} passed", flush=True)
    assert set(threading.enumerate()) <= initial_threads, "Combat worker leaked"
    summary["worker_leaks"] = 0
    (output / "random_combat_audit.json").write_text(json.dumps(summary["combat"], indent=2), encoding="utf-8")
    (output / "regression_audit.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Audit passed: syntax, terminal, suites, combat invariants, workers", flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
