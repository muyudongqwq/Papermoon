"""Build the standalone windowed character editor with its own Python/Tk."""

import argparse
from pathlib import Path
import subprocess
import sys

from CharacterEditorClient import APPLICATION_NAME


def main():
    parser = argparse.ArgumentParser(description="Build CharacterEditorClient")
    parser.add_argument("--distpath", type=Path)
    args = parser.parse_args()
    from PyInstaller.utils.hooks.tcl_tk import tcltk_info
    if not tcltk_info.available:
        raise RuntimeError("无法读取Tcl/Tk运行库，请在正常Windows桌面环境中重新打包")
    root = Path(__file__).resolve().parents[1]
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", APPLICATION_NAME, "--distpath", str(args.distpath.resolve() if args.distpath else root),
        "--workpath", str(root / "build" / "CharacterEditorClient"), "--specpath", str(root / "build"),
        "--paths", str(root), "--collect-submodules", "game", "--noupx",
        "--version-file", str(root / "CharacterEditorClient" / "version_info.txt"),
        str(root / "CharacterEditorClient" / "executable.py"),
    ], cwd=root, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
