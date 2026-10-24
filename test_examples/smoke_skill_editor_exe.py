"""Integration checks for the actual single-file Windows executable.

Run after building: python -m test_examples.smoke_skill_editor_exe
"""

import ctypes
from ctypes import wintypes
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

from SkillEditorClient.effect_options import FORM_EFFECT_TYPES as EFFECT_TYPES
from SkillEditorClient import EXECUTABLE_NAME, VERSION
from SkillEditorClient.effect_reference import read_dictionary


ROOT = Path(__file__).resolve().parents[1]
EXE = Path(os.environ.get("PAPERMOON_EDITOR_DIST", ROOT)) / EXECUTABLE_NAME


@unittest.skipUnless(os.name == "nt" and EXE.is_file(), "Build the Windows exe first")
class SkillEditorExeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="Papermoon-exe-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def probe(self, executable):
        report = self.directory / "report.json"
        # No Python search paths and an unrelated working directory: this must
        # succeed using only the runtime and resources inside the executable.
        environment = {key: value for key, value in os.environ.items()
                       if key.upper() not in {"PYTHONPATH", "PYTHONHOME"}}
        environment["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
        subprocess.run([str(executable), "--check-installation", str(report)],
                       cwd=self.directory, env=environment, check=True, timeout=45)
        value = json.loads(report.read_text(encoding="utf-8"))
        self.assertTrue(value["frozen"])
        self.assertFalse(value["console"])
        self.assertTrue(value["resource_found"])
        self.assertEqual(value["saved_skill"], "active")
        self.assertEqual(value["effect_types"], list(EFFECT_TYPES))
        self.assertEqual(value["parameter_form"], {"value": 5})
        self.assertEqual(value["reference_effect"], "attack_bonus")
        self.assertEqual(value["reference_count"], len(EFFECT_TYPES))
        self.assertTrue(value["reference_readonly"])
        self.assertEqual(value["version"], VERSION)
        self.assertIn(VERSION, value["title"])
        self.assertEqual(value["dictionary_sha256"], hashlib.sha256(read_dictionary().encode("utf-8")).hexdigest())
        self.assertTrue(value["reference_views_match"])
        self.assertEqual(Path(value["data_root"]), executable.parent)
        self.assertEqual(Path(value["default_catalog"]), executable.parent / "userdata" / "catalog.json")
        self.assertEqual(value["core_command"][:2], [str(executable), "--run-core"])
        self.assertGreater(value["validated"]["personal_skill"], 0)

    def test_project_exe_has_no_console_and_can_save_form(self):
        self.probe(EXE)

    def test_exe_runs_alone_from_chinese_directory_without_installed_python(self):
        folder = self.directory / "独立分发 测试"
        folder.mkdir()
        executable = folder / EXE.name
        shutil.copy2(EXE, executable)
        self.probe(executable)
        self.assertEqual(sorted(item.name for item in folder.iterdir()), [EXE.name])

    def test_bundled_core_dispatch_validates_catalog(self):
        # This explicit Core mode intentionally creates its own terminal.
        result = subprocess.run([str(EXE), "--run-core", "--check", "--catalog", str(self.directory / "catalog.json")],
                                cwd=self.directory, timeout=45)
        self.assertEqual(result.returncode, 0)

    def test_normal_entry_shows_editor_window_and_closes_cleanly(self):
        self.check_normal_window(EXE, "Papermoon · SkillEditorClient")

    def test_character_entry_shows_editor_window_and_closes_cleanly(self):
        from CharacterEditorClient import EXECUTABLE_NAME
        character = EXE.parent / EXECUTABLE_NAME
        if not character.is_file():
            self.skipTest("Build the character editor first")
        self.check_normal_window(character, "Papermoon · CharacterEditorClient")

    def check_normal_window(self, source, title_prefix):
        executable = self.directory / source.name
        shutil.copy2(source, executable)
        user32 = ctypes.windll.user32
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        process = subprocess.Popen([str(executable), "--catalog", str(self.directory / "catalog.json")], cwd=self.directory)
        try:
            # One-file bootloaders use a child process for the actual window;
            # the isolated catalog path lets us identify it by its window text.
            target = []
            def visit(window, _parameter):
                title = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(window, title, len(title))
                if title_prefix in title.value:
                    # Verify it belongs to this exe before sending WM_CLOSE.
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
                    kernel = ctypes.windll.kernel32
                    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
                    kernel.OpenProcess.restype = wintypes.HANDLE
                    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
                    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                    handle = kernel.OpenProcess(0x1000, False, pid.value)
                    if handle:
                        try:
                            name = ctypes.create_unicode_buffer(32768)
                            length = wintypes.DWORD(len(name))
                            if kernel.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(length)) and Path(name.value) == executable:
                                target.append(window)
                        finally:
                            kernel.CloseHandle(handle)
                return True
            callback = callback_type(visit)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and not target:
                self.assertIsNone(process.poll(), "Editor exited before creating its window")
                user32.EnumWindows(callback, 0)
                if not target:
                    time.sleep(0.1)
            self.assertTrue(target, "Editor window did not appear")
            for window in target:
                user32.PostMessageW(window, 0x0010, 0, 0)
            self.assertEqual(process.wait(timeout=15), 0)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
