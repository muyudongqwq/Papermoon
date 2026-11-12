"""Regenerate Designer Python modules when their source ``.ui`` files change."""

from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
FORMS = {
    ROOT / "ui" / "gamemaster.ui": ROOT / "GameMasterClient" / "ui_gamemaster.py",
    ROOT / "ui" / "groupmanager.ui": ROOT / "GameMasterClient" / "ui_groupmanager.py",
    ROOT / "ui" / "characterstatus.ui": ROOT / "GameMasterClient" / "ui_characterstatus.py",
}


def ensure_generated_ui():
    """Compile only stale forms; packaged builds keep their bundled modules."""
    if getattr(sys, "frozen", False):
        return
    stale = [(source, target) for source, target in FORMS.items()
             if source.exists() and (not target.exists() or source.stat().st_mtime_ns > target.stat().st_mtime_ns)]
    if not stale:
        return
    bundled = Path(sys.executable).with_name("pyside6-uic.exe")
    compiler = str(bundled if bundled.exists() else shutil.which("pyside6-uic") or "")
    if not compiler:
        raise RuntimeError("检测到.ui文件已更新，但没有找到pyside6-uic。请确认PySide6安装完整。")
    startup = None
    if sys.platform == "win32":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    for source, target in stale:
        temporary = target.with_suffix(".py.tmp")
        try:
            subprocess.run(
                [compiler, str(source), "-o", str(temporary)],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                startupinfo=startup,
            )
            temporary.replace(target)
        except subprocess.CalledProcessError as error:
            detail = (error.stderr or error.stdout or str(error)).strip()
            raise RuntimeError(f"无法更新{source.name}：{detail}") from error
        finally:
            temporary.unlink(missing_ok=True)

