"""Fresh-process imports verify the reorganized engine has one canonical namespace."""

import ast
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PackageLayoutTests(unittest.TestCase):
    def test_leaf_packages_import_independently_without_loading_ui_or_old_names(self):
        for first in ("game.character.card_factory", "game.action.action", "game.skill.skill_runtime", "game.game_manager"):
            script = f"""
import importlib, sys
importlib.import_module({first!r})
from game import GameManager
from game.game_manager import GameManager as direct
from game.character import create_character_from_card
from game.character.masters import Master
assert GameManager is direct
assert isinstance(create_character_from_card('master_test_0'), Master)
assert not any(name in sys.modules for name in ('core', 'skilleditor', 'tkinter'))
assert not any(name in sys.modules for name in ('action', 'character', 'map', 'modifier', 'rank', 'resource', 'skill', 'turn'))
"""
            result = subprocess.run([sys.executable, "-c", script], cwd=ROOT,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_rule_sources_do_not_import_the_terminal_or_editor(self):
        dependencies = []
        for path in (ROOT / "game").rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
                modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else (
                    [node.module or ""] if isinstance(node, ast.ImportFrom) and node.level == 0 else [])
                dependencies.extend((str(path.relative_to(ROOT)), name) for name in modules
                                    if name.split(".")[0] in {"core", "skilleditor"})
        self.assertEqual(dependencies, [])


if __name__ == "__main__":
    unittest.main()
