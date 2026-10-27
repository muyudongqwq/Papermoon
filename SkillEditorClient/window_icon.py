"""Separate native Windows icon handles, sized for each editor window's DPI."""

import ctypes
from ctypes import wintypes
import tkinter as tk


class WindowsWindowIcons:
    def __init__(self, root, path):
        self.path = str(path)
        self.windows = {}
        self.api = ctypes.WinDLL("user32", use_last_error=True)
        self.api.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                        ctypes.c_int, ctypes.c_int, wintypes.UINT]
        self.api.LoadImageW.restype = wintypes.HANDLE
        self.api.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        self.api.SendMessageW.restype = wintypes.HANDLE  # Both icon messages return HICON.
        self.api.DestroyIcon.argtypes = [wintypes.HANDLE]
        self.api.DestroyIcon.restype = wintypes.BOOL
        if hasattr(self.api, "GetDpiForWindow"):
            self.api.GetDpiForWindow.argtypes = [wintypes.HWND]
            self.api.GetDpiForWindow.restype = wintypes.UINT
        if hasattr(self.api, "GetSystemMetricsForDpi"):
            self.api.GetSystemMetricsForDpi.argtypes = [ctypes.c_int, wintypes.UINT]
            self.api.GetSystemMetricsForDpi.restype = ctypes.c_int
        root.bind_all("<Map>", self.changed, add=True)
        root.bind_all("<Configure>", self.changed, add=True)
        root.bind_all("<Destroy>", self.destroyed, add=True)
        self.apply(root)

    def apply(self, window):
        window.winfo_id()  # Ensure the native window exists, even while withdrawn.
        handle = int(window.tk.call("wm", "frame", str(window)), 0)
        dpi = self.api.GetDpiForWindow(handle) if hasattr(self.api, "GetDpiForWindow") else 0
        dpi = dpi or round(window.winfo_fpixels("1i"))
        previous = self.windows.get(window)
        if previous is not None and previous[:2] == (handle, dpi):
            return
        icons = []
        try:
            for metric, base in ((49, 16), (11, 32)):  # SM_CXSMICON, SM_CXICON
                size = (self.api.GetSystemMetricsForDpi(metric, dpi)
                        if hasattr(self.api, "GetSystemMetricsForDpi") else round(base * dpi / 96))
                icon = self.api.LoadImageW(None, self.path, 1, size, size, 0x10)  # ICON, LOADFROMFILE
                if not icon:
                    raise ctypes.WinError(ctypes.get_last_error())
                icons.append(icon)
        except BaseException:
            self.release(icons)
            raise
        for kind, icon in enumerate(icons):
            self.api.SendMessageW(handle, 0x0080, kind, icon)  # WM_SETICON: SMALL, BIG
        self.windows[window] = (handle, dpi, *icons)
        if previous is not None:
            self.release(previous[2:])

    def changed(self, event):
        if isinstance(event.widget, (tk.Tk, tk.Toplevel)):
            self.apply(event.widget)

    def destroyed(self, event):
        previous = self.windows.pop(event.widget, None)
        if previous is not None:
            self.release(previous[2:])

    def release(self, icons):
        for icon in icons:
            self.api.DestroyIcon(icon)
