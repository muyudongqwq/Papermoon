"""Rebuild the standalone Windows client using an isolated PyInstaller install.

Run from the project root: python -m SkillEditorClient.build_exe
"""

from pathlib import Path
import argparse
import subprocess
import sys

from SkillEditorClient import APPLICATION_NAME


def main():
    parser = argparse.ArgumentParser(description="Build SkillEditorClient")
    parser.add_argument("--distpath", type=Path)
    args = parser.parse_args()
    from PyInstaller.utils.hooks.tcl_tk import tcltk_info
    if not tcltk_info.available:
        raise RuntimeError("无法读取Tcl/Tk运行库，请在正常Windows桌面环境中重新打包。")
    root = Path(__file__).resolve().parents[1]
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", APPLICATION_NAME, "--distpath", str(args.distpath.resolve() if args.distpath else root),
        "--workpath", str(root / "build" / "SkillEditorClient"),
        "--specpath", str(root / "build"), "--paths", str(root),
        "--add-data", str(root / "SkillEditorClient" / "effect_dictionary.txt") + ";SkillEditorClient",
        "--icon", str(root / "skilleditor" / "assets" / "papermoon.ico"),
        "--add-data", str(root / "skilleditor" / "assets" / "papermoon.ico") + ";skilleditor/assets",
        "--add-data", str(root / "skilleditor" / "assets" / "papermoon.png") + ";skilleditor/assets",
        "--version-file", str(root / "SkillEditorClient" / "version_info.txt"),
        "--collect-submodules", "game", "--hidden-import", "core.__main__",
        "--noupx", str(root / "SkillEditorClient" / "executable.py"),
    ], cwd=root, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
