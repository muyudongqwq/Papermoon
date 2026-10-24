"""Windowed executable entry and the editor's separate terminal Core process."""

import ctypes
from pathlib import Path
import sys
import traceback


def core_command(catalog):
    if getattr(sys, "frozen", False):
        command = [sys.executable, "--run-core"]
    else:
        python = Path(sys.executable)
        if python.name.casefold() == "pythonw.exe":
            python = python.with_name("python.exe")
        command = [str(python), "-m", "core"]
    return [*command, "--menu", "--pause-on-exit", "--catalog", str(catalog)]


def character_editor_command(catalog):
    from core.catalog import DATA_ROOT
    if getattr(sys, "frozen", False):
        folder = Path(sys.executable).resolve().parent
        choices = (folder / "CharacterEditorClient beta 0.1.exe", folder / "CharacterEditorClient.exe")
        executable = next((path for path in choices if path.is_file()), None)
        if executable is None:
            raise FileNotFoundError(f"同文件夹下未找到可用角色卡编辑器：{choices[0]}")
        command = [str(executable)]
    else:
        entry = DATA_ROOT / "CharacterEditorClient" / "__main__.py"
        if not entry.is_file():
            raise FileNotFoundError(f"同文件夹下未找到角色卡编辑器入口：{entry}")
        python = Path(sys.executable)
        windowed = python.with_name("pythonw.exe")
        if sys.platform == "win32" and windowed.is_file():
            python = windowed
        command = [str(python), "-m", "CharacterEditorClient"]
    return [*command, "--catalog", str(Path(catalog).resolve())]


def terminal_main(argv):
    # A windowed executable starts with no Python standard streams. Only the
    # explicit Core child acquires a console; the editor never allocates one.
    if sys.platform == "win32":
        kernel = ctypes.windll.kernel32
        if not kernel.GetConsoleWindow() and not kernel.AllocConsole():
            raise ctypes.WinError()
        kernel.SetConsoleCP(65001)
        kernel.SetConsoleOutputCP(65001)
        sys.stdin = open("CONIN$", "r", encoding="utf-8")
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
        sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)
    from core.__main__ import main
    return main(argv)


def main():
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "--run-core":
            return terminal_main(sys.argv[2:])
        if len(sys.argv) == 3 and sys.argv[1] == "--check-installation":
            return check_installation(Path(sys.argv[2]))
        from SkillEditorClient.__main__ import run
        return run()
    except Exception:
        from core.catalog import DATA_ROOT
        folder = DATA_ROOT / "userdata"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "SkillEditorClient_error.log"
        path.write_text(traceback.format_exc(), encoding="utf-8")
        if sys.platform == "win32":
            ctypes.windll.user32.MessageBoxW(None, f"启动失败，错误记录已保存到：\n{path}", "SkillEditorClient", 16)
        return 1


def check_installation(output):
    """Explicit packaging check: real Tk controls and a disposable catalog."""
    import json
    import hashlib
    import tempfile
    import tkinter as tk
    from core.catalog import CatalogProject, DATA_ROOT, DEFAULT_CATALOG
    from SkillEditorClient.app import SkillEditorClient
    from SkillEditorClient.model import new_client_definition
    from skilleditor.documents import new_definition
    from SkillEditorClient import VERSION
    from SkillEditorClient.effect_reference import DICTIONARY_PATH
    from skilleditor.display import enable_high_dpi

    enable_high_dpi()
    root = tk.Tk()
    root.withdraw()
    try:
        with tempfile.TemporaryDirectory(prefix="Papermoon-exe-check-") as folder:
            catalog = Path(folder) / "catalog.json"
            app = SkillEditorClient(root, CatalogProject(catalog))
            app.load("personal_skill", "packaging_check", new_client_definition("固有技能", "packaging_check"))
            app.form.add_component(new_definition("固有技能", "packaging_check")["components"][0])
            candidate = app.candidate()
            candidate.save()
            reopened = CatalogProject(catalog)
            reference = app.open_effect_reference()
            reference.withdraw()
            report = {
                "frozen": getattr(sys, "frozen", False),
                "console": ctypes.windll.kernel32.GetConsoleWindow() if sys.platform == "win32" else None,
                "executable": sys.executable,
                "data_root": str(DATA_ROOT),
                "default_catalog": str(DEFAULT_CATALOG),
                "resource_found": DICTIONARY_PATH.is_file(),
                "title": root.title(),
                "version": VERSION,
                "dictionary_sha256": hashlib.sha256(reference.dictionary.encode("utf-8")).hexdigest(),
                "reference_views_match": app.read_reference_dictionary() == reference.dictionary,
                "saved_skill": reopened.data["personal_skill"]["packaging_check"]["components"][0]["component_id"],
                "effect_types": list(app.form.components[0].effects[0].type_box.cget("values")),
                "parameter_form": json.loads(app.form.components[0].effects[0].data.get()),
                "reference_effect": reference.current_effect,
                "reference_count": len(reference.visible_effects),
                "reference_readonly": reference.text.cget("state") == "disabled",
                "core_command": core_command(catalog),
                "validated": reopened.validate(),
            }
            app.load("status", "debuff_immunity")
            status = app.form.read()
            report["status_round_trip"] = status == app.project.effective()["status"]["debuff_immunity"]
            report["status_effect"] = status["components"][0]["effects"][0]["effect_type"]
            report["status_form"] = type(app.form).__name__ == "StatusForm"
            report["cards_hidden"] = all(category != "character_card" for category, key in app.items.values())
            try:
                report["character_editor_command"] = character_editor_command(catalog)
            except FileNotFoundError as error:
                report["character_editor_missing_error"] = str(error)
            root.update()
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        root.destroy()
    return 0
