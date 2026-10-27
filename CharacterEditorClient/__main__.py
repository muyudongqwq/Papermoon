"""Source entry point and disposable installation diagnostic."""

import argparse
import json
from pathlib import Path
import sys
import tempfile
import tkinter as tk
import traceback

from core.catalog import CatalogProject, DEFAULT_CATALOG, DATA_ROOT
from SkillEditorClient.display import enable_high_dpi
from CharacterEditorClient import VERSION
from CharacterEditorClient.app import CharacterEditorClient


def run():
    parser = argparse.ArgumentParser(description="Papermoon CharacterEditorClient")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--check-installation", type=Path)
    args = parser.parse_args()
    enable_high_dpi()
    root = tk.Tk()
    root.withdraw()
    try:
        if args.check_installation:
            with tempfile.TemporaryDirectory() as folder:
                app = CharacterEditorClient(root, CatalogProject(Path(folder) / "catalog.json"))
                def fail(error):
                    raise RuntimeError(str(error))
                app.error = fail
                builtins = app.project.effective()["character_card"]
                for key, definition in builtins.items():
                    app.load(key)
                    if app.form.read() != definition:
                        raise ValueError(f"角色卡往返结果不一致：{key}")
                from CharacterEditorClient.model import new_card
                card = new_card("master", None, builtins)
                app.load(card["card_id"], card, new=True)
                app.form.name.set("打包验证角色")
                for variable in app.form.attributes.values():
                    variable.set("C")
                app.form.attributes["magic"].set("A++")
                if not app.save():
                    raise ValueError("打包后无法保存角色卡")
                reopened = CatalogProject(app.project.path)
                saved = reopened.data["character_card"][card["card_id"]]
                import ctypes
                root.update()
                args.check_installation.write_text(json.dumps({"version": VERSION, "title": root.title(),
                    "cards": list(builtins), "catalog": str(args.catalog.resolve()),
                    "console": ctypes.windll.kernel32.GetConsoleWindow() if sys.platform == "win32" else None,
                    "data_root": str(DATA_ROOT), "default_catalog": str(DEFAULT_CATALOG),
                    "saved_card": card["card_id"], "saved_magic": saved["attributes"]["magic"],
                    "validated": reopened.validate(), "builtin_round_trip": True,
                    "frozen": getattr(sys, "frozen", False)}, ensure_ascii=False, indent=2), encoding="utf-8")
            root.destroy()
            return 0
        app = CharacterEditorClient(root, CatalogProject(args.catalog))
        def callback_error(kind, error, tb):
            folder = DATA_ROOT / "userdata"
            folder.mkdir(parents=True, exist_ok=True)
            with (folder / "CharacterEditorClient_error.log").open("a", encoding="utf-8") as stream:
                traceback.print_exception(kind, error, tb, file=stream)
            app.error(error)
        root.report_callback_exception = callback_error
        root.deiconify()
        root.mainloop()
        return 0
    except Exception as error:
        if args.check_installation:
            args.check_installation.write_text(json.dumps({"error": str(error), "traceback": traceback.format_exc()}, ensure_ascii=False), encoding="utf-8")
            root.destroy()
            return 1
        from tkinter import messagebox
        messagebox.showerror("无法打开角色卡编辑器", str(error), parent=root)
        root.destroy()
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
