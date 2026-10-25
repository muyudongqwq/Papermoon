"""Native DPI rendering while preserving the editor's original typography."""

import ctypes
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk


ICON_DIRECTORY = Path(__file__).resolve().with_name("assets")


def configure_skill_editor_icon(root):
    """Use bundled artwork for the window, its child dialogs and taskbar."""
    photo = tk.PhotoImage(master=root, file=str(ICON_DIRECTORY / "papermoon.png"))
    root.iconphoto(True, photo)
    root._papermoon_icon = photo
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p("Papermoon.SkillEditor"))
        root.iconbitmap(default=str(ICON_DIRECTORY / "papermoon.ico"))
        from skilleditor.window_icon import WindowsWindowIcons
        root._papermoon_native_icons = WindowsWindowIcons(root, ICON_DIRECTORY / "papermoon.ico")


def enable_high_dpi():
    """Configure Windows before creating any Tk window; leave other OSes alone."""
    if sys.platform != "win32":
        return "native"
    try:
        from ctypes import wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        set_context = user32.SetProcessDpiAwarenessContext
        set_context.argtypes = [ctypes.c_void_p]
        set_context.restype = wintypes.BOOL
        if set_context(ctypes.c_void_p(-4)):  # PER_MONITOR_AWARE_V2
            return "per_monitor_v2"
        if ctypes.get_last_error() == 5:  # A manifest/host already chose a mode.
            return "already_configured"
    except (AttributeError, OSError):
        pass
    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return "per_monitor"
    except (AttributeError, OSError):
        pass
    try:
        if ctypes.windll.user32.SetProcessDPIAware():
            return "system"
    except (AttributeError, OSError):
        pass
    return "unavailable"


def configure_display(root):
    scale = max(1.0, root.winfo_fpixels("1i") / 96)
    # Tk scales point-sized fonts natively. Its pixel-sized Treeview rows do
    # not follow that scale, so retain their original logical height instead
    # of adding extra leading or replacing the system's named fonts.
    style = ttk.Style(root)
    rowheight = int(style.lookup("Treeview", "rowheight") or 20)
    style.configure("Treeview", rowheight=max(round(rowheight * scale), round(22 * scale)))
    width, height = max(480, root.winfo_screenwidth() - 80), max(360, root.winfo_screenheight() - 100)
    root.geometry(f"{min(width, round(1320 * scale))}x{min(height, round(880 * scale))}")
    root.minsize(min(width, round(1024 * scale)), min(height, round(680 * scale)))
