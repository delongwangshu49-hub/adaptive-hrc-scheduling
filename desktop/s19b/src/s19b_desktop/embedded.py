"""Host only the correlated Kit worker's native Windows viewport in Qt."""

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import Qt
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import QVBoxLayout, QWidget


class KitHost(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setMinimumSize(500, 320)
        self.layout_box = QVBoxLayout(self)
        self.layout_box.setContentsMargins(0, 0, 0, 0)
        self.foreign = None
        self.container = None
        self.hwnd = None
        self.pid = None
        if sys.platform == "win32":
            self.api = ctypes.WinDLL("user32", use_last_error=True)
            self.api.GetParent.argtypes = [wintypes.HWND]
            self.api.GetParent.restype = wintypes.HWND
            self.api.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            self.api.GetAncestor.restype = wintypes.HWND
            self.api.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
            self.api.GetWindowLongPtrW.restype = ctypes.c_ssize_t
            self.api.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            self.api.SetWindowLongPtrW.restype = ctypes.c_ssize_t
            self.api.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            self.api.GetWindowThreadProcessId.argtypes = [
                wintypes.HWND,
                ctypes.POINTER(wintypes.DWORD),
            ]
            self.api.IsWindow.argtypes = [wintypes.HWND]
            self.api.IsWindowVisible.argtypes = [wintypes.HWND]
            self.api.IsChild.argtypes = [wintypes.HWND, wintypes.HWND]
            self.api.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            self.api.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            self.api.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
            self.api.SetWindowPos.argtypes = [
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ]

    def attach(self, pid):
        if sys.platform != "win32":
            raise RuntimeError("EMBEDDED_KIT_REQUIRES_WINDOWS")
        if self.hwnd:
            if not self.api.IsWindow(self.hwnd):
                self.release()
            return
        matches = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def collect(hwnd, _param):
            actual_pid = wintypes.DWORD()
            self.api.GetWindowThreadProcessId(hwnd, ctypes.byref(actual_pid))
            title = ctypes.create_unicode_buffer(256)
            self.api.GetWindowTextW(hwnd, title, len(title))
            if (
                actual_pid.value == pid
                and title.value.startswith("S19B ")
                and "Isaac Production Scene" in title.value
            ):
                matches.append(hwnd)
            return True

        self.api.EnumWindows(callback_type(collect), 0)
        if not matches:
            return
        if len(matches) != 1:
            raise RuntimeError("AMBIGUOUS_KIT_WINDOW")
        hwnd = matches[0]
        self.api.ShowWindow(hwnd, 0)
        # Qt controls parenting/geometry; strip Kit's top-level decorations first.
        style = self.api.GetWindowLongPtrW(hwnd, -16)
        style = (style & ~(0x80000000 | 0x00CF0000)) | 0x40000000
        self.api.SetWindowLongPtrW(hwnd, -16, style)
        self.foreign = QWindow.fromWinId(hwnd)
        if self.foreign is None:
            raise RuntimeError("FOREIGN_WINDOW_UNSUPPORTED")
        self.container = QWidget.createWindowContainer(self.foreign, self)
        self.container.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.layout_box.addWidget(self.container)
        self.hwnd, self.pid = hwnd, pid
        self.container.show()

    def sync_geometry(self):
        """Kit/GLFW can restore old top-level coordinates after minimization."""
        if not self.hwnd or self.window().isMinimized() or not self.api.IsWindow(self.hwnd):
            return
        parent = self.api.GetParent(self.hwnd)
        if not self.api.IsChild(int(self.window().winId()), self.hwnd):
            raise RuntimeError("KIT_NO_LONGER_EMBEDDED")
        target, actual = wintypes.RECT(), wintypes.RECT()
        self.api.GetWindowRect(int(self.container.winId()), ctypes.byref(target))
        self.api.GetWindowRect(self.hwnd, ctypes.byref(actual))
        if (target.left, target.top, target.right, target.bottom) != (
            actual.left,
            actual.top,
            actual.right,
            actual.bottom,
        ):
            position = wintypes.POINT(target.left, target.top)
            self.api.ScreenToClient(parent, ctypes.byref(position))
            if not self.api.SetWindowPos(
                self.hwnd,
                None,
                position.x,
                position.y,
                target.right - target.left,
                target.bottom - target.top,
                0x0014,
            ):
                raise ctypes.WinError(ctypes.get_last_error())

    def measure(self):
        if not self.hwnd or not self.api.IsWindow(self.hwnd):
            return None
        actual_pid = wintypes.DWORD()
        self.api.GetWindowThreadProcessId(self.hwnd, ctypes.byref(actual_pid))
        if actual_pid.value != self.pid:
            raise RuntimeError("KIT_WINDOW_OWNER_CHANGED")

        def rect(hwnd):
            result = wintypes.RECT()
            if not self.api.GetWindowRect(hwnd, ctypes.byref(result)):
                raise ctypes.WinError(ctypes.get_last_error())
            return [result.left, result.top, result.right, result.bottom]

        top = int(self.window().winId())
        host = int(self.container.winId())
        main_rect, host_rect, scene_rect = rect(top), rect(host), rect(self.hwnd)
        contained = (
            host_rect[0] <= scene_rect[0] < scene_rect[2] <= host_rect[2]
            and host_rect[1] <= scene_rect[1] < scene_rect[3] <= host_rect[3]
        )
        return dict(
            worker_pid=self.pid,
            scene_hwnd=int(self.hwnd),
            main_hwnd=top,
            host_hwnd=host,
            native_parent=int(self.api.GetParent(self.hwnd) or 0),
            native_root=int(self.api.GetAncestor(self.hwnd, 2) or 0),
            child_of_main=bool(self.api.IsChild(top, self.hwnd)),
            contained_in_host=contained,
            qt_window_physical=main_rect,
            host_window_physical=host_rect,
            scene_window_physical=scene_rect,
            visible=bool(self.api.IsWindowVisible(self.hwnd)),
            device_pixel_ratio=self.devicePixelRatioF(),
            scope="OWN_CORRELATED_WORKER_NATIVE_CHILD_ONLY",
            method="QWINDOW_FROMWINID_QWIDGET_CREATEWINDOWCONTAINER",
        )

    def release(self):
        # Called only after the backend has exited and destroyed its HWND.
        # Never detach a live Kit window back onto the desktop.
        if self.container:
            self.layout_box.removeWidget(self.container)
            self.container.deleteLater()
        self.container = self.foreign = None
        self.hwnd = self.pid = None
