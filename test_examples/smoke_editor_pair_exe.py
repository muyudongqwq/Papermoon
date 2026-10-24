"""Check the distributed editor pair using only their embedded runtimes."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from SkillEditorClient import EXECUTABLE_NAME as SKILL_EXE
from CharacterEditorClient import EXECUTABLE_NAME as CHARACTER_EXE

ROOT = Path(__file__).resolve().parents[1]
DIST = Path(os.environ.get("PAPERMOON_EDITOR_DIST", ROOT / "dist" / "PapermoonEditors"))


@unittest.skipUnless(os.name == "nt" and all((DIST / name).is_file() for name in (SKILL_EXE, CHARACTER_EXE)),
                     "Build both Windows editors first")
class EditorPairExeTests(unittest.TestCase):
    def test_shared_folder_and_character_launch_command_without_installed_python(self):
        with tempfile.TemporaryDirectory(prefix="Papermoon-pair-") as temporary:
            directory = Path(temporary)
            folder = directory / "编辑器 独立分发"
            folder.mkdir()
            for name in (SKILL_EXE, CHARACTER_EXE):
                shutil.copy2(DIST / name, folder / name)
            environment = {key: value for key, value in os.environ.items()
                           if key.upper() not in {"PYTHONPATH", "PYTHONHOME"}}
            environment["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
            skill_report = directory / "skill.json"
            subprocess.run([str(folder / SKILL_EXE), "--check-installation", str(skill_report)],
                           cwd=directory, env=environment, check=True, timeout=60)
            skill = json.loads(skill_report.read_text(encoding="utf-8"))
            for key in ("frozen", "status_form", "status_round_trip", "cards_hidden"):
                self.assertTrue(skill[key], key)
            self.assertEqual(skill["status_effect"], "status_immunity")
            self.assertFalse(skill["console"])
            command = skill["character_editor_command"]
            self.assertEqual(Path(command[0]), folder / CHARACTER_EXE)
            character_report = directory / "character.json"
            subprocess.run([*command, "--check-installation", str(character_report)], cwd=directory,
                           env=environment, check=True, timeout=60)
            character = json.loads(character_report.read_text(encoding="utf-8"))
            self.assertTrue(character["frozen"])
            self.assertFalse(character["console"])
            self.assertTrue(character["builtin_round_trip"])
            self.assertEqual(character["version"], "beta 0.1")
            self.assertEqual(character["saved_card"], "master10")
            self.assertEqual(character["saved_magic"], {"value": 5, "plus": 2})
            self.assertEqual(character["catalog"], command[-1])
            self.assertEqual(Path(character["data_root"]), folder)
            self.assertEqual(Path(character["default_catalog"]), folder / "userdata" / "catalog.json")
            self.assertEqual(sorted(path.name for path in folder.iterdir()), sorted((SKILL_EXE, CHARACTER_EXE)))


if __name__ == "__main__":
    unittest.main()
