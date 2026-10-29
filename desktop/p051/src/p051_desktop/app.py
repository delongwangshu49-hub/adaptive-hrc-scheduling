"""Approved B route: local React shell and a PID-correlated native Kit sibling."""

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QDesktopServices, QPalette
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT), str(ROOT / "src"), str(ROOT / "scripts"), str(ROOT / "desktop/s19b/src")]

from s19b_desktop.embedded import KitHost  # noqa: E402
from s19b_desktop.model import atomic_json, read_json  # noqa: E402

from .client import Client, prepare_launch  # noqa: E402
from .delta import ProjectionDelta  # noqa: E402
from .geometry import accepts_host, plan  # noqa: E402


def configure_application(app):
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in {
        "Window": "#202020",
        "WindowText": "#E7E5E1",
        "Base": "#171717",
        "AlternateBase": "#292929",
        "Text": "#E7E5E1",
        "Button": "#292929",
        "ButtonText": "#E7E5E1",
        "Highlight": "#525252",
        "HighlightedText": "#FFFFFF",
        "ToolTipBase": "#292929",
        "ToolTipText": "#E7E5E1",
    }.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(color))
    app.setPalette(palette)


def ask_yes_no(parent, title, message):
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(message)
    box.setIcon(QMessageBox.Icon.NoIcon)
    box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    box.setDefaultButton(QMessageBox.StandardButton.No)
    box.exec()
    return box.standardButton(box.clickedButton())


class LocalPage(QWebEnginePage):
    def acceptNavigationRequest(self, url, kind, is_main):
        return url.scheme() in ("file", "qrc", "about", "data")

    def javaScriptConsoleMessage(self, level, message, line, source):
        print(f"WEB {level}: {message} ({source}:{line})", flush=True)


class NativeViewport(KitHost):
    """Dedicated adapter; legacy KitHost remains byte-for-byte unchanged."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setMinimumSize(500, 160)
        self.last_geometry = None
        self.hide()

    def attach(self, pid):
        top = self.window()
        size, state = top.size(), top.windowState()
        super().attach(pid)
        if self.foreign:
            # A maximized GLFW window must not maximize its new Qt ancestor.
            style = self.api.GetWindowLongPtrW(self.hwnd, -16)
            self.api.SetWindowLongPtrW(self.hwnd, -16, style & ~(0x01000000 | 0x20000000))
            self.foreign.setWindowState(Qt.WindowState.WindowNoState)
            if not state & (Qt.WindowState.WindowMaximized | Qt.WindowState.WindowFullScreen):

                def restore():
                    top.showNormal()
                    top.resize(size)

                QTimer.singleShot(0, restore)

    def effective_minimum(self):
        hint = self.minimumSizeHint()
        minima = [
            (500, 160),
            (self.minimumWidth(), self.minimumHeight()),
            (max(0, hint.width()), max(0, hint.height())),
        ]
        if self.container:
            ch = self.container.minimumSizeHint()
            minima.extend(
                [
                    (self.container.minimumWidth(), self.container.minimumHeight()),
                    (max(0, ch.width()), max(0, ch.height())),
                ]
            )
        layout_minimum = self.layout_box.minimumSize()
        minima.append((layout_minimum.width(), layout_minimum.height()))
        return tuple(max(x[i] for x in minima) for i in (0, 1))

    def commit(self, geometry, reviewed):
        minimum = self.effective_minimum()
        if (
            not accepts_host(reviewed, minimum)
            or geometry.width < minimum[0]
            or geometry.height < minimum[1]
        ):
            raise ValueError("GEOMETRY_BLOCKED")
        self.setGeometry(geometry.x, geometry.y, geometry.width, geometry.height)
        self.last_geometry = geometry
        if self.hwnd:
            self.show()
            self.raise_()
            self.sync_geometry()


class Bridge(QObject):
    event = Signal(str)

    def __init__(self, shell):
        super().__init__(shell)
        self.shell = shell

    @Slot(str, result=str)
    def invoke(self, raw):
        try:
            value = json.loads(raw)
            if not isinstance(value, dict) or not isinstance(value.get("action"), str):
                raise ValueError("UI_MESSAGE")
            result = self.shell.invoke(value["action"], value.get("data", {}))
            return json.dumps(dict(ok=True, data=result), ensure_ascii=False)
        except (ValueError, OSError, KeyError, TypeError) as error:
            return json.dumps(dict(ok=False, error=str(error)), ensure_ascii=False)


class Workbench(QWidget):
    def __init__(self, *, directory=None, writable=False, runs=None, audit=None):
        super().__init__()
        self.setWindowTitle("连续生产工作台 · Production Workbench · P05.1")
        self.resize(1366, 768)
        self.setMinimumSize(1280, 720)
        self.runs = Path(runs or ROOT / ".local/p051-ui-runs")
        self.audit = Path(audit) if audit else None
        if self.audit:
            self.audit.mkdir(parents=True, exist_ok=True)
        self.directory = Path(directory) if directory else None
        self.writable = writable
        self.client = None
        self.worker = None
        self.launch = None
        self.worker_log = None
        self.worker_exit = None
        self.phase = "DISCONNECTED"
        self.detached = False
        self.display_error = None
        self.frame_identity = None
        self.frame_changed_at = None
        self.view_sequence = 0
        self.form_open = False
        self.split_ratio = 0.5
        self.label_width = None
        self.language = "zh"
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="P051-display")
        self.future = None
        self.outstanding = None
        self.pending_call = None
        self.snapshot = {}
        self.last_layout = None
        self.last_emit = 0
        self.last_projection_key = None
        self.delta = ProjectionDelta()
        self.close_when_drained = False
        self.native = NativeViewport(self)
        self.hud_corner = "top-left"
        self.hud = QLabel(self)
        self.hud.hide()
        self.web = QWebEngineView(self)
        self.web.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        profile = QWebEngineProfile(self.web)
        self.page = LocalPage(profile, self.web)
        self.web.setPage(self.page)
        self.page.settings().setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False
        )
        self.page.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False
        )
        self.channel = QWebChannel(self.page)
        self.bridge = Bridge(self)
        self.channel.registerObject("workbench", self.bridge)
        self.page.setWebChannel(self.channel)
        self.page.renderProcessTerminated.connect(self.renderer_failed)
        self.page.loadFinished.connect(lambda ok: self.emit("load", dict(ok=ok)))
        self.page.loadFinished.connect(self.display_loaded)
        self.web.load(QUrl.fromLocalFile(str(ROOT / "desktop/p051/web/dist/index.html")))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(250)
        self.recovery = QWidget(self)
        recovery_layout = QVBoxLayout(self.recovery)
        recovery_layout.addWidget(
            QLabel(
                "显示不可用；不会重启生产或重发请求。\nDisplay unavailable; no production restart or request replay."
            )
        )
        retry = QPushButton("恢复显示 / Recover display")
        retry.clicked.connect(self.web.reload)
        recovery_layout.addWidget(retry)
        stop = QPushButton("安全停止 / Safe stop")
        stop.clicked.connect(self.confirm_stop)
        recovery_layout.addWidget(stop)
        self.recovery.setStyleSheet(
            "background:#202020;color:#E7E5E1; font-size:14px; QPushButton{background:#292929;border:1px solid #525252;padding:6px;}"
        )
        self.recovery.hide()
        self.arrange()

    def emit(self, kind, value):
        if self.audit and kind in ("preview", "submit", "worker_exit", "launched", "error", "load"):
            with (self.audit / "ui-events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(dict(at=time.monotonic(), kind=kind, data=value), ensure_ascii=False)
                    + "\n"
                )
        self.bridge.event.emit(json.dumps(dict(kind=kind, data=value), ensure_ascii=False))

    def invoke(self, action, data):
        if action == "initialize":
            self.last_projection_key = None
            self.delta = ProjectionDelta()
            self.arrange()
            return dict(
                layout=self.last_layout,
                language=self.language,
                phase=self.phase,
                directory=str(self.directory) if self.directory else None,
            )
        if action == "hud":
            if data["corner"] not in (
                "hidden",
                "top-left",
                "top-right",
                "bottom-left",
                "bottom-right",
            ):
                raise ValueError("HUD_CORNER")
            self.hud_corner = data["corner"]
            return dict(corner=self.hud_corner)
        if action == "layout":
            self.form_open = bool(data.get("form_open", False))
            self.arrange()
            return self.last_layout
        if action == "split":
            ratio = data["ratio"]
            if type(ratio) not in (int, float) or not 0.1 <= ratio <= 0.9:
                raise ValueError("SPLIT_RANGE")
            candidate = plan(
                self.width(),
                self.height(),
                form_open=self.form_open,
                split_ratio=ratio,
                label_width=self.label_width,
            )
            if not candidate.geometry_admissible:
                raise ValueError("PANEL_MINIMUM")
            self.split_ratio = ratio
            self.arrange()
            return self.last_layout
        if action == "labelwidth":
            candidate = plan(
                self.width(),
                self.height(),
                form_open=self.form_open,
                split_ratio=self.split_ratio,
                label_width=data["width"],
            )
            if not candidate.geometry_admissible:
                raise ValueError("PANEL_MINIMUM")
            self.label_width = data["width"]
            self.arrange()
            return self.last_layout
        if action == "language":
            self.language = data["language"]
            if self.language not in ("zh", "en"):
                raise ValueError("LANGUAGE")
            return dict(language=self.language)
        if action == "connection":
            self.detached = bool(data.get("detached", False))
            self.last_projection_key = None
            self.delta = ProjectionDelta()
            if self.detached:
                self.emit(
                    "projection",
                    dict(
                        self.snapshot,
                        status="UNKNOWN",
                        writable=False,
                        error="DISPLAY_DISCONNECTED",
                    ),
                )
            return dict(detached=self.detached)
        if action == "fullscreen":
            self.showNormal() if self.isFullScreen() else self.showFullScreen()
            return dict(fullscreen=self.isFullScreen())
        if action == "restore":
            self.split_ratio = 0.5
            self.arrange()
            return self.last_layout
        if action == "start":
            if self.worker and self.worker.poll() is None:
                raise ValueError("WORKER_ALREADY_RUNNING")
            if self.outstanding or self.future:
                raise ValueError("WAIT_FOR_PENDING_OPERATION")
            self.phase = "PREPARING"
            self.detached = False
            self.future = self.executor.submit(prepare_launch, ROOT, self.runs, data)
            self.outstanding = "launch"
            return dict(status="PREPARING")
        if action == "open":
            if self.worker and self.worker.poll() is None:
                raise ValueError("WORKER_ALREADY_RUNNING")
            directory = QFileDialog.getExistingDirectory(
                self,
                "打开保存会话 / Open saved session",
                str(self.runs),
                options=QFileDialog.Option.DontUseNativeDialog,
            )
            if directory:
                self.directory = Path(directory)
                self.client = None
                self.writable = False
                self.phase = "SAVED_READ_ONLY"
            return dict(directory=directory, writable=False)
        if action in ("preview", "submit"):
            if (
                action == "preview"
                and data.get("kind") == "STOP_REQUEST"
                and self.launch
                and self.worker
                and self.worker.poll() is None
            ):
                from s19b_desktop.control import command

                state = read_json(self.directory / "control-state.json", 32_000_000)
                envelope = command(self.launch, "stop", state["last_sequence"] + 1)
                preview = dict(
                    kind="STOP_REQUEST",
                    target_id=self.launch["run_id"],
                    payload=dict(scope="NO_NEW_DISPATCH_SAFE_DRAIN"),
                    time_rule="NEXT_LEGAL_BOUNDARY",
                    client_sequence=envelope["sequence"],
                    request_id=envelope["command_id"],
                    transport="S19B-CONTROL-1",
                    envelope=envelope,
                )
                self.emit("preview", preview)
                return dict(status="PREVIEW_READY")
            if action == "submit" and data.get("transport") == "S19B-CONTROL-1":
                from s19b_desktop.control import submit, validate_command

                envelope = validate_command(data["envelope"], self.launch)
                if envelope["action"] != "stop":
                    raise ValueError("STOP_ONLY_CONTROL_BRIDGE")
                key = submit(self.directory, envelope)
                self.emit(
                    "submit",
                    dict(request_id=envelope["command_id"], status="SUBMITTED", transport=key),
                )
                return dict(status="SUBMITTED")
            if self.detached or self.display_error:
                raise ValueError("DISPLAY_UNKNOWN; reconnect before business input")
            if not self.client:
                raise ValueError("WAIT_FOR_VERIFIED_FRAME")
            if self.future:
                if self.outstanding == "poll" and self.pending_call is None:
                    self.pending_call = (action, data)
                    return dict(status="QUEUED_AFTER_VERIFICATION")
                raise ValueError("REQUEST_BUSY")
            self.outstanding = action
            self.future = self.executor.submit(
                self.client.build_request if action == "preview" else self.client.submit, data
            )
            return dict(status="PENDING")
        if action == "query":
            return dict(
                receipts=self.snapshot.get("receipts", []),
                submitted=self.snapshot.get("submitted", []),
            )
        if action in ("camera", "locate"):
            return self.send_view(action, **data)
        if action == "export":
            if not self.snapshot.get("envelope"):
                raise ValueError("NO_VERIFIED_FRAME")
            path, _ = QFileDialog.getSaveFileName(
                self,
                "导出已验证投影 / Export verified projection",
                str(self.directory / "timeline-view.json"),
                "JSON (*.json)",
                options=QFileDialog.Option.DontUseNativeDialog,
            )
            if path:
                value = dict(
                    self.snapshot,
                    selection=data,
                    scope="READ_ONLY_DELIVERED_PREFIX",
                    language=self.language,
                )
                atomic_json(Path(path), value)
            return dict(path=path)
        if action == "evidence":
            if self.directory:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.directory.resolve())))
            return dict(directory=str(self.directory))
        raise ValueError("UNSUPPORTED_UI_ACTION")

    def send_view(self, action, **data):
        if not self.directory or not self.launch or self.worker_exit is not None:
            raise ValueError("NATIVE_SESSION_UNAVAILABLE")
        self.view_sequence += 1
        request = dict(
            run_id=self.launch["run_id"],
            request_id=self.launch["request_id"],
            epoch=0,
            sequence=self.view_sequence,
            action=action,
            **data,
        )
        atomic_json(self.directory / "view-request.json", request)
        return dict(status="SUBMITTED_VIEW_ONLY", sequence=self.view_sequence)

    def start_worker(self, directory, request):
        self.directory, self.launch = directory, request
        self.client = None
        self.writable = True
        self.worker_exit = None
        self.frame_identity = self.frame_changed_at = None
        env = os.environ.copy()
        for name in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "PYTHONEXE"):
            env.pop(name, None)
        env["PYTHONUTF8"] = "1"
        request_path = directory / "request.json"
        if request["backend"] == "isaac":
            command = [
                "C:/Program Files/PowerShell/7/pwsh.exe",
                "-NoProfile",
                "-File",
                str(ROOT / "scripts/launch_s19b_kit.ps1"),
                "-IsaacRoot",
                "D:/Dev/tools/isaac-sim-6.1",
                "-RequestFile",
                str(request_path),
            ]
        else:
            command = [
                str(ROOT / ".venv/Scripts/python.exe"),
                "-u",
                str(ROOT / "scripts/run_s19b_prototype.py"),
                "--request",
                str(request_path),
            ]
        self.worker_log = (directory / "p051-worker.log").open("w", encoding="utf-8")
        self.worker = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdout=self.worker_log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        self.phase = "CONNECTING"
        self.emit(
            "launched",
            dict(directory=str(directory), run_id=request["run_id"], backend=request["backend"]),
        )

    def arrange(self):
        self.web.setGeometry(self.rect())
        p = plan(
            self.width(),
            self.height(),
            form_open=self.form_open,
            split_ratio=self.split_ratio,
            label_width=self.label_width,
        )
        if not p.geometry_admissible:
            self.split_ratio, self.label_width = 0.5, None
            p = plan(self.width(), self.height(), form_open=self.form_open)
        if not p.geometry_admissible:
            self.emit("error", dict(error=p.reason))
            return
        try:
            self.native.commit(p.plots[0], p)
        except ValueError as error:
            self.emit("error", dict(error=str(error)))
            return
        self.last_layout = dict(
            client=list(p.client),
            profile=p.profile,
            orientation=p.orientation,
            label_width=p.label_width,
            plots=[vars(r) for r in p.plots],
            form_open=self.form_open,
            minimum=list(self.native.effective_minimum()),
            geometry_guard="ACCEPTED",
            equal_panels=self.split_ratio == 0.5,
            equal_area=False,
            split_ratio=self.split_ratio,
        )
        self.emit("layout", self.last_layout)
        if hasattr(self, "recovery"):
            self.recovery.setGeometry(12, self.height() - 180, self.width() - 24, 148)

    def poll(self):
        try:
            if self.future and self.future.done():
                future, task = self.future, self.outstanding
                self.future = self.outstanding = None
                result = future.result()
                if task == "launch":
                    self.start_worker(*result)
                elif task == "poll":
                    self.snapshot = result
                    if (
                        self.worker
                        and self.worker.poll() is None
                        and result.get("status") == "VERIFIED"
                        and not self.display_error
                    ):
                        self.phase = "RUNNING"
                    shown = dict(result, phase=self.phase, worker_exit=self.worker_exit)
                    if self.detached or self.display_error:
                        shown.update(
                            status="UNKNOWN",
                            writable=False,
                            error=self.display_error or "DISPLAY_DISCONNECTED",
                        )
                    projection_key = (
                        self.client.consumer.sequence if self.client else None,
                        result.get("status"),
                        self.client.schedules.revision if self.client else 0,
                        len(result.get("submitted", [])),
                        self.detached,
                        self.display_error,
                    )
                    if projection_key != self.last_projection_key:
                        self.emit("projection", self.delta.encode(shown))
                        self.last_projection_key = projection_key
                else:
                    self.emit(task, result)
                if self.pending_call:
                    action, data = self.pending_call
                    self.pending_call = None
                    self.invoke(action, data)
            if self.worker:
                code = self.worker.poll()
                if code is not None and self.worker_exit is None:
                    self.worker_exit = code
                    self.phase = "EXITED" if code == 0 else "FAILED"
                    self.native.release()
                    self.native.hide()
                    self.hud.hide()
                    if self.worker_log:
                        self.worker_log.close()
                    self.emit("worker_exit", dict(code=code))
                    if self.audit:
                        atomic_json(
                            self.audit / "worker-exit.json",
                            dict(code=code, directory=str(self.directory)),
                        )
            if self.directory:
                if (
                    not self.client
                    and (
                        (self.directory / "run-spec.json").exists()
                        or (self.directory / "session/run-spec.json").exists()
                    )
                    and not self.future
                ):
                    self.client = Client(self.directory, writable=self.writable)
                if self.client and not self.future:
                    self.outstanding = "poll"
                    self.future = self.executor.submit(self.client.poll)
                if self.launch and self.launch["backend"] == "isaac" and self.worker_exit is None:
                    ready = self.directory / "started.json"
                    if ready.exists() and not self.native.hwnd:
                        self.native.attach(read_json(ready)["pid"])
                        if self.native.hwnd:
                            self.arrange()
                    if self.native.hwnd:
                        self.native.sync_geometry()
            frame = None
            if (
                self.directory
                and (self.directory / "p051-native-frame.json").exists()
                and self.native.hwnd
            ):
                raw_frame = read_json(self.directory / "p051-native-frame.json")
                if self.launch and (raw_frame.get("run_id"), raw_frame.get("epoch")) == (
                    self.launch["run_id"],
                    0,
                ):
                    frame = dict(
                        raw_frame,
                        age_s=max(0, time.monotonic() - raw_frame["published_monotonic_s"]),
                    )
                    identity = raw_frame.get("frame_number")
                    if identity is not None and identity != self.frame_identity:
                        self.frame_identity, self.frame_changed_at = identity, time.monotonic()
                    frame["counter_age_s"] = (
                        time.monotonic() - self.frame_changed_at
                        if self.frame_changed_at is not None
                        else None
                    )
                    frame["fresh"] = (
                        frame["age_s"] < 5
                        and frame["counter_age_s"] is not None
                        and frame["counter_age_s"] < 5
                    )
            if (
                self.directory
                and self.launch
                and (self.directory / "control-state.json").exists()
                and self.worker_exit is None
            ):
                control = read_json(self.directory / "control-state.json", 32_000_000)
                if control.get("run_id") == self.launch["run_id"] and control.get("phase") in (
                    "STOPPING",
                    "STOPPED",
                    "STOP_BLOCKED",
                    "FAILED",
                ):
                    self.phase = control["phase"]
            self.emit(
                "status",
                dict(
                    phase=self.phase,
                    native=self.native.measure(),
                    worker_exit=self.worker_exit,
                    language=self.language,
                    frame=frame,
                    detached=self.detached,
                    fullscreen=self.isFullScreen(),
                    source_age_s=self.snapshot.get("source_age_s"),
                ),
            )
            if self.audit:
                with (self.audit / "measurements.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(
                        json.dumps(
                            dict(
                                at=time.monotonic(),
                                phase=self.phase,
                                source_age_s=self.snapshot.get("source_age_s"),
                                status=self.snapshot.get("status"),
                                reader=self.snapshot.get("reader_metrics"),
                                rows=len(self.snapshot.get("rows", [])),
                                frame=frame,
                            )
                        )
                        + "\n"
                    )
                atomic_json(
                    self.audit / "latest-ui.json",
                    dict(
                        layout=self.last_layout,
                        phase=self.phase,
                        worker_exit=self.worker_exit,
                        directory=str(self.directory),
                        native=self.native.measure(),
                        projection_status=self.snapshot.get("status"),
                        envelope=self.snapshot.get("envelope"),
                        rows=len(self.snapshot.get("rows", [])),
                        error=self.snapshot.get("error"),
                        language=self.language,
                    ),
                )
            if self.close_when_drained and self.worker_exit is not None:
                self.close()
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            self.emit("error", dict(error=str(error)))
            if self.audit:
                atomic_json(self.audit / "last-error.json", dict(error=str(error)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "web"):
            self.arrange()

    def renderer_failed(self, status, code):
        self.phase = "DISPLAY_UNKNOWN" if self.worker_exit is None else self.phase
        self.display_error = f"RENDERER_TERMINATED:{code}"
        self.recovery.show()
        self.recovery.raise_()
        if self.audit:
            atomic_json(self.audit / "renderer-failed.json", dict(status=str(status), code=code))
        # Display failure never restarts the business process or replays a request.

    def display_loaded(self, ok):
        if ok:
            self.display_error = None
            if hasattr(self, "recovery"):
                self.recovery.hide()

    def confirm_stop(self):
        if not self.worker or self.worker.poll() is not None:
            return
        answer = ask_yes_no(
            self,
            "安全停止 / Safe stop",
            "停止新调度并等待安全段排空？\nStop new dispatch and drain safe segments?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            from s19b_desktop.control import command, submit

            state = read_json(self.directory / "control-state.json", 32_000_000)
            submit(self.directory, command(self.launch, "stop", state["last_sequence"] + 1))

    def closeEvent(self, event):
        if self.worker and self.worker.poll() is None:
            answer = ask_yes_no(
                self,
                "生产仍运行 / Production running",
                "关闭窗口需先安全停止并等待原进程退出。提交停止请求？\nSafely stop and wait for the worker before closing?",
            )
            event.ignore()
            if answer == QMessageBox.StandardButton.Yes:
                try:
                    from s19b_desktop.control import command, submit

                    state = read_json(self.directory / "control-state.json", 32_000_000)
                    submit(self.directory, command(self.launch, "stop", state["last_sequence"] + 1))
                    self.close_when_drained = True
                except (ValueError, OSError) as error:
                    self.emit("error", dict(error=str(error)))
            return
        self.hud.hide()
        self.timer.stop()
        if self.client:
            self.client.schedules.close()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.page.setWebChannel(None)
        super().closeEvent(event)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--writable", action="store_true")
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args()
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication([])
    configure_application(app)
    workbench = Workbench(directory=args.directory, writable=args.writable, audit=args.audit)
    workbench.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
