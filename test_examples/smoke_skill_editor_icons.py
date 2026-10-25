"""Native Windows icon sizes and lifetime; run in a desktop environment."""

import ctypes
from ctypes import wintypes
import struct
import sys
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from skilleditor.display import ICON_DIRECTORY, configure_skill_editor_icon, enable_high_dpi


class IconInfo(ctypes.Structure):
    _fields_ = [("is_icon", wintypes.BOOL), ("x", wintypes.DWORD), ("y", wintypes.DWORD),
                ("mask", wintypes.HBITMAP), ("color", wintypes.HBITMAP)]


class Bitmap(ctypes.Structure):
    _fields_ = [("kind", wintypes.LONG), ("width", wintypes.LONG), ("height", wintypes.LONG),
                ("stride", wintypes.LONG), ("planes", wintypes.WORD), ("bits", wintypes.WORD),
                ("pixels", ctypes.c_void_p)]


@unittest.skipUnless(sys.platform == "win32", "Windows native icon checks")
class SkillEditorIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        enable_high_dpi()

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.errors = Mock()
        self.root.report_callback_exception = self.errors
        configure_skill_editor_icon(self.root)
        self.manager = self.root._papermoon_native_icons
        self.addCleanup(self.close)

    def close(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        self.assertEqual(self.manager.windows, {})
        self.errors.assert_not_called()

    def native_sizes(self, window):
        window.update()
        handle, dpi, small, large = self.manager.windows[window]
        api, gdi = self.manager.api, ctypes.WinDLL("gdi32")
        api.GetIconInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(IconInfo)]
        gdi.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
        gdi.DeleteObject.argtypes = [wintypes.HANDLE]
        result = []
        for kind, expected_handle in enumerate((small, large)):
            actual = api.SendMessageW(handle, 0x007F, kind, 0)  # WM_GETICON
            self.assertEqual(actual, expected_handle)
            info = IconInfo()
            self.assertTrue(api.GetIconInfo(actual, ctypes.byref(info)))
            try:
                bitmap = Bitmap()
                self.assertTrue(gdi.GetObjectW(info.color, ctypes.sizeof(bitmap), ctypes.byref(bitmap)))
                result.append((bitmap.width, bitmap.height))
            finally:
                for item in (info.mask, info.color):
                    if item:
                        gdi.DeleteObject(item)
        expected_sizes = [api.GetSystemMetricsForDpi(metric, dpi) for metric in (49, 11)]
        self.assertEqual(result, [(size, size) for size in expected_sizes])
        return result

    def test_asset_contains_20_40_and_native_window_uses_distinct_dpi_sizes(self):
        data = (ICON_DIRECTORY / "papermoon.ico").read_bytes()
        reserved, kind, count = struct.unpack_from("<HHH", data)
        self.assertEqual((reserved, kind), (0, 1))
        sizes = {(data[6 + index * 16] or 256, data[7 + index * 16] or 256) for index in range(count)}
        self.assertTrue({(20, 20), (40, 40)} <= sizes)
        self.native_sizes(self.root)

    def test_child_windows_inherit_correct_sizes_and_release_icons_on_close(self):
        self.root.deiconify()
        child = tk.Toplevel(self.root)
        child.geometry("220x100+30+30")
        self.native_sizes(child)
        previous = self.manager.windows[child]
        child.geometry("240x120+40+40")
        child.update()
        self.assertEqual(self.manager.windows[child], previous)
        child.destroy()
        self.assertNotIn(child, self.manager.windows)

    def test_failed_replacement_keeps_old_icons_and_releases_partial_load(self):
        api = self.manager.api
        previous = self.manager.windows[self.root]
        original_load = api.LoadImageW
        created = []

        def load(*args):
            if not created:
                icon = original_load(*args)
                created.append(icon)
                return icon
            ctypes.set_last_error(2)
            return 0

        with patch.object(api, "GetDpiForWindow", return_value=previous[1] + 24), \
                patch.object(api, "LoadImageW", side_effect=load), \
                patch.object(api, "DestroyIcon", wraps=api.DestroyIcon) as release:
            with self.assertRaises(OSError):
                self.manager.apply(self.root)
            release.assert_called_once_with(created[0])
        self.assertEqual(self.manager.windows[self.root], previous)
        self.native_sizes(self.root)


if __name__ == "__main__":
    unittest.main()
