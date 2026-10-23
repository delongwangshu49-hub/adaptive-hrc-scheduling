"""Native bilingual workbench for three finite S19B prototype entry points."""

import argparse
import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QIODevice, QProcess, QProcessEnvironment, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .control import (
    ProcessWatch,
    command,
    confirmation,
    recover,
    submit,
)
from .embedded import KitHost
from .i18n import error_text, translate
from .model import (
    CAMERAS,
    PROTOCOL,
    Draft,
    InputError,
    atomic_json,
    canonical_digest,
    read_history,
    read_json,
    validate_live,
)
from .review import (
    bind_live_bundle,
    data_age,
    display_sequence,
    evidence_label,
    explain_reason,
    history_reason,
    preview_evidence,
    validate_binding,
    validate_confirmation,
)

ROOT = Path(__file__).resolve().parents[4]

STYLE = """
QMainWindow, QWidget { background: #000000; color: #f4f4f4; font-size: 12px; }
QLabel#Title { color: #ffffff; font-size: 28px; font-weight: 750; }
QLabel#Subtitle { color: #b5b5b5; font-size: 12px; }
QGroupBox { background: #000000; border: 1px solid #3c3c3c; border-radius: 0; margin-top: 12px; padding: 12px 10px 8px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
QLabel { background: transparent; }
QPushButton { background: #000000; color: #f4f4f4; border: 1px solid #505050; border-radius: 0; padding: 7px 12px; font-weight: 600; }
QPushButton:hover { background: #151515; border-color: #b5b5b5; }
QPushButton:focus { border: 1px solid #ffffff; }
QPushButton:pressed { background: #222222; color: #ffffff; }
QPushButton:checked { background: #f4f4f4; border-color: #f4f4f4; color: #000000; }
QPushButton#Primary { background: #f4f4f4; color: #000000; border-color: #f4f4f4; font-weight: 700; }
QPushButton#Primary:hover { background: #ffffff; border-color: #ffffff; }
QPushButton#Primary:pressed { background: #b5b5b5; border-color: #b5b5b5; }
QPushButton#Primary:disabled, QPushButton:disabled { background: #000000; color: #808080; border-color: #303030; }
QLineEdit, QComboBox, QSpinBox, QTextEdit, QTableWidget, QListWidget { background: #000000; color: #f4f4f4; selection-background-color: #f4f4f4; selection-color: #000000; border: 1px solid #505050; border-radius: 0; padding: 4px; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTextEdit:focus, QTableWidget:focus, QListWidget:focus { border-color: #ffffff; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: #808080; border-color: #303030; }
QComboBox QAbstractItemView { background: #000000; color: #f4f4f4; selection-background-color: #f4f4f4; selection-color: #000000; border: 1px solid #505050; }
QTableWidget { gridline-color: #303030; }
QTextEdit { font-family: 'Microsoft YaHei UI'; font-weight: normal; }
QHeaderView::section { background: #000000; color: #b5b5b5; border: 0; border-bottom: 1px solid #505050; padding: 5px; font-weight: 600; }
QTableCornerButton::section { background: #000000; border: 0; }
QLabel#Status { background: #000000; color: #ffffff; border: 0; border-top: 1px solid #505050; border-bottom: 1px solid #505050; border-radius: 0; padding: 10px 0; font-weight: 600; }
QLabel#Warning { color: #b5b5b5; font-size: 12px; }
QCheckBox { background: transparent; padding: 5px; }
QScrollBar { background: #000000; border: 0; }
QScrollBar::handle { background: #505050; min-height: 24px; min-width: 24px; border-radius: 0; }
QScrollBar::handle:hover { background: #b5b5b5; }
QScrollBar::add-page, QScrollBar::sub-page { background: #000000; }
QToolTip { background: #000000; color: #f4f4f4; border: 1px solid #b5b5b5; }
"""


def configure_application(app):
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, "#000000"),
        (QPalette.ColorRole.WindowText, "#f4f4f4"),
        (QPalette.ColorRole.Base, "#000000"),
        (QPalette.ColorRole.AlternateBase, "#151515"),
        (QPalette.ColorRole.Text, "#f4f4f4"),
        (QPalette.ColorRole.Button, "#000000"),
        (QPalette.ColorRole.ButtonText, "#f4f4f4"),
        (QPalette.ColorRole.Highlight, "#f4f4f4"),
        (QPalette.ColorRole.HighlightedText, "#000000"),
        (QPalette.ColorRole.PlaceholderText, "#b5b5b5"),
        (QPalette.ColorRole.Light, "#b5b5b5"),
        (QPalette.ColorRole.Midlight, "#808080"),
        (QPalette.ColorRole.Mid, "#505050"),
        (QPalette.ColorRole.Dark, "#303030"),
        (QPalette.ColorRole.Shadow, "#000000"),
        (QPalette.ColorRole.Link, "#f4f4f4"),
        (QPalette.ColorRole.LinkVisited, "#b5b5b5"),
        (QPalette.ColorRole.ToolTipBase, "#000000"),
        (QPalette.ColorRole.ToolTipText, "#f4f4f4"),
    ):
        palette.setColor(role, QColor(color))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#808080"))
    app.setPalette(palette)
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(STYLE)


class Workbench(QMainWindow):
    def __init__(
        self,
        *,
        runs=None,
        settings=None,
        display_hold_s=300,
        control_mode=True,
        session_bundle=None,
    ):
        super().__init__()
        self.runs = Path(runs or ROOT / ".local/s19b-runs")
        self.settings_path = Path(settings or ROOT / ".local/s19b-desktop-settings.json")
        self.display_hold_s = display_hold_s
        self.pending_launch = None
        self.control_mode = control_mode
        self.session_bundle = session_bundle
        self.control_request = None
        self.pending_control = None
        self.control_state = None
        self.detached = False
        self.process_watch = None
        try:
            self.preferences = read_json(self.settings_path)
        except (OSError, ValueError):
            self.preferences = {}
        self.locale = self.preferences.get("locale", "zh-CN")
        if self.locale not in ("zh-CN", "en"):
            self.locale = "zh-CN"
        self.backend = "light"
        self.run_directory = None
        self.run_id = None
        self.request_id = None
        self.last_sequence = -1
        self.last_live = None
        self.history_record = None
        self.history_directory = None
        self.feedback_key = "cpu_hint"
        self.feedback_suffix = ""
        self.phase_key = "idle"
        self.view_sequence = 0
        self.pending_view = None
        self.bound_version = None
        self.binding_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="s19b-binding")
        self.binding_future = None
        self.binding_key = None
        self.record_current = False
        self.saved_record_valid = False
        self.connection_key = "exit_unknown"
        self.display_key = "location_unavailable"
        self.display_suffix = ""
        self.entity_rows = []
        self.evidence_dialog = None
        self.last_window_layout = None
        self.bindings = []
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.drain_output)
        self.process.readyReadStandardError.connect(self.drain_output)
        self.process.finished.connect(self.process_finished)
        self.process.errorOccurred.connect(self.process_error)
        self.build()
        self.resize(1640, 870)
        self.setMinimumSize(1360, 760)
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.x() + 12, screen.y() + 30)
        self.resize(min(1640, screen.width() - 24), min(870, screen.height() - 50))
        self.retranslate()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(250)

    def t(self, key):
        if self.control_mode:
            key = {
                "running": "running_control",
                "cpu_hint": "cpu_control",
                "kit_hint": "kit_control",
                "draft_locked": "draft_locked_control",
                "close_busy": "close_busy_control",
            }.get(key, key)
        return translate(key, self.locale)

    def label(self, key, *, wrap=False):
        widget = QLabel()
        widget.setWordWrap(wrap)
        self.bindings.append((widget, "setText", key))
        return widget

    def button(self, key, callback):
        widget = QPushButton()
        self.bindings.append((widget, "setText", key))
        widget.clicked.connect(callback)
        return widget

    def group(self, key):
        widget = QGroupBox()
        self.bindings.append((widget, "setTitle", key))
        return widget

    def build(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(22, 16, 22, 16)
        title_row = QHBoxLayout()
        titles = QVBoxLayout()
        title = self.label("title")
        title.setObjectName("Title")
        titles.addWidget(title)
        subtitle = self.label("subtitle")
        subtitle.setObjectName("Subtitle")
        titles.addWidget(subtitle)
        title_row.addLayout(titles)
        title_row.addStretch()
        self.language = QComboBox()
        self.language.addItem("简体中文", "zh-CN")
        self.language.addItem("English", "en")
        self.language.setCurrentIndex(0 if self.locale == "zh-CN" else 1)
        self.language.currentIndexChanged.connect(self.change_language)
        title_row.addWidget(self.language)
        outer.addLayout(title_row)
        tabs = QHBoxLayout()
        self.tabs = []
        for key, mode in (("cpu", "light"), ("kit", "isaac"), ("history", "history")):
            button = self.button(key, lambda checked=False, mode=mode: self.select_mode(mode))
            button.setCheckable(True)
            self.tabs.append(button)
            tabs.addWidget(button)
        self.settings_button = self.button("settings", self.show_settings)
        tabs.addWidget(self.settings_button)
        outer.addLayout(tabs)
        self.status = QLabel()
        self.status.setObjectName("Status")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self.pages = QStackedWidget()
        outer.addWidget(self.pages, 1)
        trial_page = QWidget()
        trial_row = QHBoxLayout(trial_page)
        trial_row.setContentsMargins(0, 0, 0, 0)
        self.input_group = self.group("input")
        self.input_group.setMinimumWidth(260)
        left = QVBoxLayout(self.input_group)
        form = QFormLayout()
        self.variant = QComboBox()
        self.variant.addItems(("SR-W1", "SR-W2"))
        self.count = QSpinBox()
        self.count.setRange(1, 3)
        self.count.valueChanged.connect(self.resize_orders)
        form.addRow(self.label("variant"), self.variant)
        form.addRow(self.label("count"), self.count)
        left.addLayout(form)
        self.orders = QTableWidget(1, 2)
        self.orders.setMinimumHeight(130)
        self.orders.setMaximumHeight(180)
        self.orders.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.orders.verticalHeader().hide()
        left.addWidget(self.orders)
        left.addWidget(self.label("note"))
        self.note = QLineEdit()
        self.note.setMaxLength(500)
        left.addWidget(self.note)
        self.check_button = self.button("validate", self.check_input)
        left.addWidget(self.check_button)
        self.draft_scope = QLabel()
        self.draft_scope.setWordWrap(True)
        left.addWidget(self.draft_scope)
        self.arm = QCheckBox()
        self.bindings.append((self.arm, "setText", "arm"))
        self.arm.toggled.connect(self.update_controls)
        left.addWidget(self.arm)
        self.launch_button = self.button("launch", self.launch)
        self.launch_button.setObjectName("Primary")
        left.addWidget(self.launch_button)
        self.stop_button = self.button("stop_production", self.stop_production)
        left.addWidget(self.stop_button)
        self.reconnect_button = self.button("reconnect", self.reconnect)
        left.addWidget(self.reconnect_button)
        self.recover_button = self.button("recover_run", self.choose_recovery)
        left.addWidget(self.recover_button)
        self.control_status = QLabel()
        self.control_status.setWordWrap(True)
        left.addWidget(self.control_status)
        left.addWidget(self.label("prefix", wrap=True))
        left.addStretch()
        self.input_scroll = QScrollArea()
        self.input_scroll.setWidgetResizable(True)
        self.input_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.input_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.input_scroll.setWidget(self.input_group)
        self.input_scroll.setFixedWidth(300)
        trial_row.addWidget(self.input_scroll)
        self.scene_group = self.group("scene")
        scene_layout = QVBoxLayout(self.scene_group)
        scene_layout.setContentsMargins(0, 18, 0, 0)
        self.scene_placeholder = self.label("scene_idle", wrap=True)
        self.scene_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scene_layout.addWidget(self.scene_placeholder)
        self.scene_host = KitHost()
        scene_layout.addWidget(self.scene_host, 1)
        trial_row.addWidget(self.scene_group, 1)
        right_widget = QWidget()
        right = QVBoxLayout(right_widget)
        right.setContentsMargins(0, 0, 0, 0)
        for widget in (
            self.stop_button,
            self.reconnect_button,
            self.recover_button,
            self.control_status,
        ):
            right.addWidget(widget)
        stats = self.group("version")
        stats_form = QFormLayout(stats)
        self.identity = QLabel("—")
        self.identity.setMinimumHeight(58)
        self.identity.setWordWrap(True)
        self.identity.setTextInteractionFlags(self.identity.textInteractionFlags())
        self.sim_clock = QLabel("—")
        self.age = QLabel("—")
        self.audit = QLabel()
        self.source_version = QLabel("—")
        self.connection = QLabel()
        self.connection.setWordWrap(True)
        stats_form.addRow(self.label("run_id"), self.identity)
        stats_form.addRow(self.label("sim_time"), self.sim_clock)
        stats_form.addRow(self.label("freshness"), self.age)
        stats_form.addRow(self.label("audit"), self.audit)
        stats_form.addRow(self.label("source_version"), self.source_version)
        stats_form.addRow(self.label("connection"), self.connection)
        right.addWidget(stats)
        activity = self.group("activity")
        activity_layout = QVBoxLayout(activity)
        self.product_table = QTableWidget(0, 3)
        self.product_table.setMinimumHeight(110)
        self.product_table.verticalHeader().hide()
        self.product_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.product_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.product_table.cellClicked.connect(self.select_entity_row)
        activity_layout.addWidget(self.product_table)
        right.addWidget(activity, 1)
        self.entity_group = self.group("entities")
        entity_layout = QVBoxLayout(self.entity_group)
        self.entity = QComboBox()
        self.entity.setEditable(True)
        self.entity.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        entity_layout.addWidget(self.entity)
        self.locate_button = self.button("locate", self.request_location)
        entity_layout.addWidget(self.locate_button)
        self.display_status = QLabel()
        self.display_status.setWordWrap(True)
        entity_layout.addWidget(self.display_status)
        right.addWidget(self.entity_group)
        self.camera_group = self.group("camera")
        camera_layout = QHBoxLayout(self.camera_group)
        self.camera = QComboBox()
        self.camera.addItems(CAMERAS)
        camera_layout.addWidget(self.camera)
        self.camera_button = self.button("camera_request", self.request_camera)
        camera_layout.addWidget(self.camera_button)
        right.addWidget(self.camera_group)
        self.close_scene_button = self.button("close_scene", self.close_display)
        right.addWidget(self.close_scene_button)
        self.evidence_button = self.button("view_evidence", self.inspect_current)
        right.addWidget(self.evidence_button)
        right_scroll = QScrollArea()
        self.right_scroll = right_scroll
        right_scroll.setWidgetResizable(True)
        right_scroll.setWidget(right_widget)
        right_scroll.setFixedWidth(370)
        right_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        trial_row.addWidget(right_scroll)
        self.pages.addWidget(trial_page)
        history_page = QWidget()
        history_layout = QVBoxLayout(history_page)
        history_layout.addWidget(self.label("history_hint", wrap=True))
        self.history_open_button = self.button("open_history", self.choose_history)
        history_layout.addWidget(self.history_open_button)
        history_layout.addWidget(self.label("evidence"))
        self.evidence_list = QListWidget()
        history_layout.addWidget(self.evidence_list, 1)
        history_layout.addWidget(self.button("open_evidence", self.open_evidence))
        self.history_details = QTextEdit()
        self.history_details.setReadOnly(True)
        history_layout.addWidget(self.history_details, 1)
        self.pages.addWidget(history_page)
        settings_page = QWidget()
        settings_layout = QFormLayout(settings_page)
        self.kit_root = QLineEdit(
            self.preferences.get("isaac_root", os.getenv("ISAAC_SIM_ROOT", ""))
        )
        settings_layout.addRow(self.label("kit_root"), self.kit_root)
        settings_layout.addRow(self.button("browse", self.choose_kit))
        settings_layout.addRow(self.button("save_settings", self.save_settings))
        self.pages.addWidget(settings_page)
        feedback_group = self.group("feedback")
        feedback_layout = QVBoxLayout(feedback_group)
        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        feedback_layout.addWidget(self.feedback)
        feedback_layout.addWidget(self.label("reason"))
        self.reason_details = QTextEdit()
        self.reason_details.setReadOnly(True)
        self.reason_details.setMaximumHeight(90)
        feedback_layout.addWidget(self.reason_details)
        outer.addWidget(feedback_group)
        scope = self.label("unsupported", wrap=True)
        scope.setObjectName("Warning")
        outer.addWidget(scope)
        self.resize_orders()

    def busy(self):
        return (
            self.process.state() != QProcess.ProcessState.NotRunning
            or self.process_watch is not None
        )

    def can_prepare_next(self):
        return (
            not self.control_mode
            and self.busy()
            and self.backend == "isaac"
            and self.record_current
            and self.phase_key == "checkpoint"
            and self.last_live is not None
            and self.last_live.get("audit") == self.last_live.get("decision_audit") == "PASS"
        )

    def resize_orders(self):
        self.orders.setRowCount(self.count.value())
        for row in range(self.orders.rowCount()):
            self.orders.setItem(row, 0, QTableWidgetItem(f"PRODUCT-{row + 1}"))
            self.orders.item(row, 0).setFlags(
                self.orders.item(row, 0).flags() & ~Qt.ItemFlag.ItemIsEditable
            )
            if self.orders.item(row, 1) is None:
                self.orders.setItem(row, 1, QTableWidgetItem("0"))

    def draft(self):
        try:
            release = tuple(
                float(self.orders.item(row, 1).text()) for row in range(self.count.value())
            )
        except (ValueError, AttributeError):
            raise InputError("RELEASE_TIME") from None
        return Draft(
            self.variant.currentText(), self.count.value(), release, self.note.text()
        ).validate()

    def check_input(self):
        try:
            self.draft()
        except InputError as error:
            self.set_feedback("input_prefix", str(error))
            return False
        self.set_feedback("input_ok")
        return True

    def set_feedback(self, key, suffix=""):
        self.feedback_key, self.feedback_suffix = key, suffix
        display_suffix = error_text(suffix, self.locale) if key == "input_prefix" else suffix
        self.feedback.setText(self.t(key) + ("\n" + display_suffix if display_suffix else ""))

    def retranslate(self):
        self.setWindowTitle(self.t("title") + " · S19B")
        for widget, method, key in self.bindings:
            mapped = (
                {
                    "subtitle": "subtitle_control",
                    "scope": "scope_control",
                    "prefix": "prefix_control",
                    "arm": "arm_control",
                    "unsupported": "unsupported_control",
                    "cpu_hint": "cpu_control",
                    "kit_hint": "kit_control",
                }.get(key, key)
                if self.control_mode
                else key
            )
            getattr(widget, method)(self.t(mapped))
        if self.control_mode:
            self.launch_button.setText(self.t("launch_control"))
        self.note.setPlaceholderText(self.t("placeholder"))
        self.orders.setHorizontalHeaderLabels((self.t("product"), self.t("release")))
        self.product_table.setHorizontalHeaderLabels(
            (self.t("product"), self.t("state"), self.t("action"))
        )
        self.status.setText(self.t(self.phase_key))
        self.connection.setText(self.t(self.connection_key))
        self.display_status.setText(self.t(self.display_key) + "\n" + self.display_suffix)
        self.set_feedback(self.feedback_key, self.feedback_suffix)
        self.camera_group.setVisible(self.backend == "isaac")
        self.close_scene_button.setVisible(self.backend == "isaac")
        for tab, mode in zip(self.tabs, ("light", "isaac", "history")):
            tab.setChecked(mode == self.backend)
        if self.last_live and self.backend != "history":
            self.render_live(self.last_live)
        else:
            self.audit.setText(self.t("not_run"))
        if self.backend == "history" and self.history_record:
            self.render_history()
        self.reason_details.setPlaceholderText(self.t("reason_unknown"))
        self.render_entities()
        self.update_controls()
        self.render_control()

    def change_language(self):
        self.locale = self.language.currentData()
        self.persist_preferences()
        self.retranslate()

    def persist_preferences(self):
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(
            self.settings_path, {"locale": self.locale, "isaac_root": self.kit_root.text().strip()}
        )

    def select_mode(self, mode):
        if self.busy():
            return
        self.backend = mode
        self.record_current = False
        self.pages.setCurrentIndex(1 if mode == "history" else 0)
        self.phase_key = "historical" if mode == "history" else "idle"
        self.set_feedback(
            "history_hint" if mode == "history" else "kit_hint" if mode == "isaac" else "cpu_hint"
        )
        self.retranslate()

    def show_settings(self):
        if not self.busy():
            self.pages.setCurrentIndex(2)

    def choose_kit(self):
        folder = QFileDialog.getExistingDirectory(self, self.t("kit_root"))
        if folder:
            self.kit_root.setText(folder)

    def save_settings(self):
        self.persist_preferences()
        self.set_feedback("settings_saved")

    def launch(self):
        if self.pending_launch is not None or not self.arm.isChecked() or not self.check_input():
            return
        draft = self.draft()
        if self.control_mode and not self.busy():
            if not self.confirm_control("confirm_start", draft):
                self.set_feedback("not_confirmed")
                return
        if self.busy():
            if not self.can_prepare_next():
                self.set_feedback("draft_locked")
                return
            try:
                read_history(self.run_directory)
            except (OSError, ValueError, TypeError, KeyError) as error:
                self.set_feedback("history_error", str(error))
                return
            self.pending_launch = draft
            try:
                self.send_view("close_display")
            except OSError as error:
                self.pending_launch = None
                self.set_feedback("display_unknown", str(error))
                self.update_controls()
                return
            self.set_feedback("next_trial_pending")
            self.update_controls()
            return
        self.start_trial(draft)

    def start_trial(self, draft):
        if self.busy():
            return
        if self.backend == "isaac":
            kit = Path(self.kit_root.text().strip())
            if not (kit / "python.bat").is_file():
                self.set_feedback("kit_missing")
                return
        python = ROOT / ".venv/Scripts/python.exe"
        if not python.is_file():
            self.set_feedback("python_missing")
            return
        self.runs.mkdir(parents=True, exist_ok=True)
        self.run_id = "S19B-" + uuid.uuid4().hex
        if self.session_bundle:
            self.run_id = self.session_bundle["spec"]["run_id"]
        self.request_id = uuid.uuid4().hex
        self.run_directory = self.runs / self.run_id
        self.run_directory.mkdir()
        request = dict(
            protocol=PROTOCOL,
            run_id=self.run_id,
            request_id=self.request_id,
            backend=self.backend,
            draft=draft.data(),
            created_at=datetime.now(timezone.utc).isoformat(),
            display_hold_s=self.display_hold_s,
        )
        if self.session_bundle:
            from .model import validate_request

            request["session"] = self.session_bundle
            validate_request(request)
        if self.control_mode:
            request["control"] = confirmation(request, ROOT, self.run_directory)
            self.control_request = request
            self.control_state = None
            self.pending_control = command(request, "start", 1)
            self.detached = False
            atomic_json(self.run_directory / "start-command.json", self.pending_control)
            submit(self.run_directory, self.pending_control)
        request_file = self.run_directory / "request.json"
        atomic_json(request_file, request)
        self.last_sequence, self.last_live, self.last_window_layout = -1, None, None
        self.bound_version = None
        self.binding_future = None
        self.binding_key = None
        self.pending_view = None
        self.entity_rows = []
        self.connection_key = "submitted"
        self.display_key, self.display_suffix = "location_unavailable", ""
        self.connection.setText(self.t(self.connection_key))
        self.display_status.setText(self.t(self.display_key))
        self.record_current = False
        self.reason_details.clear()
        self.saved_record_valid = False
        self.phase_key = "connecting"
        self.identity.setText(self.run_id)
        self.sim_clock.setText("—")
        self.age.setText("—")
        self.source_version.setText("—")
        self.audit.setText(self.t("not_run"))
        self.product_table.setRowCount(0)
        self.process.setWorkingDirectory(str(ROOT))
        env = QProcessEnvironment.systemEnvironment()
        for name in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "PYTHONEXE"):
            env.remove(name)
        env.insert("PYTHONUTF8", "1")
        self.process.setProcessEnvironment(env)
        if self.control_request:
            # File-backed logging survives loss of the frontend. QProcess pipes
            # would otherwise turn a successful orphan worker into BrokenPipe
            # during final output, despite correct saved production evidence.
            self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
            self.process.setStandardOutputFile(
                str(self.run_directory / "process.log"), QIODevice.OpenModeFlag.Append
            )
        if self.backend == "light":
            self.process.setProgram(str(python))
            self.process.setArguments(
                ["-u", str(ROOT / "scripts/run_s19b_prototype.py"), "--request", str(request_file)]
            )
        else:
            self.process.setProgram("C:/Program Files/PowerShell/7/pwsh.exe")
            self.process.setArguments(
                [
                    "-NoProfile",
                    "-File",
                    str(ROOT / "scripts/launch_s19b_kit.ps1"),
                    "-IsaacRoot",
                    str(kit.resolve()),
                    "-RequestFile",
                    str(request_file),
                ]
            )
        self.process.start()
        self.submitted_s = time.monotonic()
        self.set_feedback("submitted")
        self.status.setText(self.t(self.phase_key))
        self.update_controls()
        self.render_control()

    def drain_output(self):
        data = bytes(self.process.readAllStandardOutput()) + bytes(
            self.process.readAllStandardError()
        )
        if self.run_directory and data:
            with (self.run_directory / "process.log").open("ab") as stream:
                stream.write(data)

    def process_error(self, _error):
        self.phase_key = "failed"
        self.record_current = False
        self.connection_key = "process_error"
        self.connection.setText(self.t(self.connection_key))
        self.status.setText(self.t(self.phase_key))
        self.set_feedback("process_error", self.process.errorString())
        self.update_controls()

    def process_finished(self, exit_code, _exit_status):
        success = False
        queued = self.pending_launch
        self.pending_launch = None
        self.drain_output()
        self.scene_host.release()
        self.scene_placeholder.show()
        if self.run_directory:
            atomic_json(
                self.run_directory / "process-exit.json",
                {
                    "run_id": self.run_id,
                    "request_id": self.request_id,
                    "exit_code": exit_code,
                    "exit_status": _exit_status.name,
                    "confirmed_by": "QT_PROCESS_FINISHED_SIGNAL",
                },
            )
        try:
            report = read_json(self.run_directory / "report.json")
            if report.get("run_id") != self.run_id or report.get("request_id") != self.request_id:
                raise InputError("REPORT_IDENTITY_MISMATCH")
            success = (
                exit_code == 0
                and report.get("status") == "PASS"
                and report.get("closed") is True
                and _exit_status == QProcess.ExitStatus.NormalExit
                and report.get("manifest", {}).get("termination")
                in (
                    ("ORDERLY_STOPPED", "OPERATIONS_COMPLETE")
                    if self.control_request
                    else ("DECLARED_CHECKPOINT",)
                )
                and report.get("manifest", {}).get("audit")
                == report.get("manifest", {}).get("decision_audit")
                == "PASS"
            )
            self.last_live = validate_live(
                read_json(self.run_directory / "live.json"),
                self.run_id,
                self.request_id,
                self.last_sequence,
            )
            validate_binding(self.run_directory, self.last_live, self.backend)
            if success:
                if read_history(self.run_directory)["integrity"] != "integrity_checked":
                    raise InputError("EVIDENCE_INDEX_MISSING")
            self.saved_record_valid = success
            self.record_current = False
            self.connection_key = "exited"
            self.connection.setText(self.t(self.connection_key))
            self.render_live(self.last_live)
            self.audit.setText(
                self.audit_text(
                    report.get("manifest", {}).get("audit"),
                    report.get("manifest", {}).get("decision_audit"),
                )
            )
            termination = report.get("manifest", {}).get("termination")
            self.phase_key = (
                "stopped"
                if success and termination == "ORDERLY_STOPPED"
                else "completed"
                if success and termination == "OPERATIONS_COMPLETE"
                else "finished"
                if success
                else "failed"
            )
            self.set_feedback(
                self.phase_key,
                termination if success else report.get("error", "")[-1600:],
            )
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.record_current = False
            self.saved_record_valid = False
            self.connection_key = "exited"
            self.connection.setText(self.t(self.connection_key))
            if self.last_live:
                self.render_live(self.last_live)
            self.audit.setText(self.t("unknown_value"))
            self.phase_key = "failed"
            self.set_feedback("failed", str(error))
        self.status.setText(self.t(self.phase_key))
        if self.control_request:
            try:
                self.control_state, _ = recover(self.run_directory, self.control_request)
                self.render_control()
            except (OSError, ValueError, TypeError, KeyError) as error:
                self.control_status.setText(self.t("control_unknown") + "\n" + str(error))
        self.update_controls()
        if queued is not None:
            if success and self.saved_record_valid:
                QTimer.singleShot(0, lambda: self.start_trial(queued))
            else:
                self.set_feedback("next_trial_failed")

    def render_live(self, live):
        self.identity.setText(
            live["run_id"][:18]
            + "…"
            + "\n"
            + live["request_id"][:18]
            + "…"
            + "\nepoch 0 · "
            + live.get("config_sha256", "")[:12]
        )
        self.identity.setToolTip(
            live["run_id"] + "\n" + live["request_id"] + "\n" + live.get("config_sha256", "")
        )
        self.sim_clock.setText(f"{live['time_h']:.6f} h")
        try:
            age = data_age(live)
            self.age.setText(f"{age:.1f} " + self.t("age"))
        except InputError:
            self.age.setText(self.t("unknown_value"))
        self.source_version.setText(live.get("source_version", "—")[:20])
        self.source_version.setToolTip(live.get("source_version", "—"))
        self.audit.setText(self.audit_text(live.get("audit"), live.get("decision_audit")))
        products = live["products"]
        self.product_table.setRowCount(len(products))
        for row, product in enumerate(products):
            key = (
                "received"
                if product["received"]
                else "cancelled"
                if product["cancelled"]
                else "ready"
                if product["ready"]
                else "released"
                if product["released"]
                else "pending"
            )
            actions = [
                r["operation"]
                + " · "
                + self.t(
                    r["status"] if r["status"] in ("STARTED", "EXCEPTION") else "unknown_value"
                )
                + " · "
                + self.t(r.get("phase", "unknown_value"))
                for r in live["active"]
                if r["product"] == product["id"]
            ]
            current = self.record_current or self.saved_record_valid
            for column, value in enumerate(
                (
                    product["id"],
                    self.t(key) if current else self.t("unknown_value"),
                    ("\n".join(actions) or self.t("none")) if current else self.t("stale_record"),
                )
            ):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                target = product["id"]
                if column == 2:
                    target = next(
                        (r["operation"] for r in live["active"] if r["product"] == product["id"]),
                        target,
                    )
                item.setData(Qt.ItemDataRole.UserRole, target)
                self.product_table.setItem(row, column, item)
        self.product_table.resizeRowsToContents()
        self.render_reason(
            live.get("reason"), current=self.record_current or self.saved_record_valid
        )

    def render_reason(self, fact, *, current=True):
        if not fact:
            self.reason_details.setPlainText(self.t("reason_unknown"))
            return
        lines = [
            explain_reason(fact.get("code", ""), self.locale),
            f"{fact.get('source', 'online-journal.json')} · #{fact.get('sequence')} · {fact.get('time_h')} h · {fact.get('observation_id')}",
        ]
        if fact.get("receipt_kind"):
            lines.append(
                self.t(
                    fact["receipt_kind"]
                    if fact["receipt_kind"] in ("STARTED", "REJECTED")
                    else "unknown_value"
                )
                + " · "
                + str(fact.get("receipt_id"))
            )
        if fact.get("failures"):
            lines.extend(explain_reason(code, self.locale) for code in fact["failures"])
        if not current:
            lines.insert(0, self.t("stale_record"))
        self.reason_details.setPlainText("\n".join(lines))
        self.reason_details.setToolTip(fact.get("code", ""))

    def audit_text(self, execution, decision):
        if execution == decision == "PASS":
            return self.t("passed")
        return (
            self.t("execution_audit")
            + ": "
            + self.t(execution if execution in ("PASS", "FAILED", "FAIL") else "not_run")
            + "\n"
            + self.t("decision_audit")
            + ": "
            + self.t(decision if decision in ("PASS", "FAILED", "FAIL") else "not_run")
        )

    def populate_evidence(self, listing, names):
        listing.clear()
        for name in names:
            item = QListWidgetItem(evidence_label(name, self.locale))
            item.setData(Qt.ItemDataRole.UserRole, name)
            listing.addItem(item)

    def render_entities(self):
        text = self.entity.currentText()
        self.entity.blockSignals(True)
        self.entity.clear()
        for row in self.entity_rows:
            self.entity.addItem(row["id"], row)
        if text:
            self.entity.setCurrentText(text)
        self.entity.blockSignals(False)

    def select_entity_row(self, row, column):
        item = self.product_table.item(row, column)
        if item:
            self.entity.setCurrentText(item.data(Qt.ItemDataRole.UserRole))
            self.right_scroll.ensureWidgetVisible(self.entity_group)

    def mark_unknown(self, detail=""):
        self.record_current = False
        self.phase_key = "unknown"
        self.connection_key = "unknown"
        # Disable actions before rendering potentially malformed saved values.
        self.update_controls()
        self.status.setText(self.t("unknown"))
        self.connection.setText(self.t("unknown"))
        self.display_key, self.display_suffix = "display_unknown", ""
        self.display_status.setText(self.t(self.display_key))
        self.set_feedback("unknown", detail)
        if self.last_live:
            self.render_live(self.last_live)
        self.render_control()
        self.update_controls()

    def poll(self):
        if not self.run_directory or not self.busy():
            return
        if self.process_watch:
            code = self.process_watch.exit_code()
            if code is not None:
                self.process_watch.close()
                self.process_watch = None
                self.process_finished(code, QProcess.ExitStatus.NormalExit)
                # Correct the observation provenance for this restored frontend.
                receipt = read_json(self.run_directory / "process-exit.json")
                receipt["confirmed_by"] = "WINDOWS_RETAINED_PROCESS_HANDLE_WAIT_AND_EXIT_CODE"
                atomic_json(self.run_directory / "process-exit.json", receipt)
                return
        if self.detached:
            self.mark_unknown("FRONTEND_DISCONNECTED_NO_REPLAY")
            return
        self.arrange_scene()
        try:
            live = validate_live(
                read_json(self.run_directory / "live.json", limit=100_000),
                self.run_id,
                self.request_id,
                self.last_sequence,
            )
            if self.bound_version is None:
                key = (
                    str(self.run_directory.resolve()),
                    self.run_id,
                    self.request_id,
                    self.backend,
                    live["config_sha256"],
                    live["source_version"],
                )
                if self.binding_key != key or self.binding_future is None:
                    if self.binding_future:
                        self.binding_future.cancel()
                    self.binding_key = key
                    self.binding_future = self.binding_executor.submit(
                        bind_live_bundle, self.run_directory, dict(live), self.backend
                    )
                if not self.binding_future.done():
                    self.mark_unknown("IDENTITY_CHECK_PENDING")
                    return
                future, self.binding_future = self.binding_future, None
                rows = future.result()
                self.entity_rows = rows
                self.bound_version = (live["config_sha256"], live["source_version"])
                self.render_entities()
            if (live["config_sha256"], live["source_version"]) != self.bound_version:
                raise InputError("LIVE_VERSION_CHANGED")
            if (
                self.last_live
                and live["sequence"] == self.last_sequence
                and canonical_digest(live) != canonical_digest(self.last_live)
            ):
                raise InputError("LIVE_SEQUENCE_CONTENT_CHANGED")
            age = data_age(live)
            self.last_sequence = live["sequence"]
            self.last_live = live
            keys = {
                "INITIALIZED": "initialized",
                "RUNNING": "running",
                "AUDITING": "auditing",
                "CHECKPOINT_DISPLAY_OPEN": "checkpoint",
                "CHECKPOINT_SAVED": "checkpoint",
                "STOPPING": "stopping",
                "PRODUCTION_SAVED": "auditing",
            }
            if age > 5:
                self.mark_unknown()
                return
            self.record_current = live.get("phase") in keys
            self.connection_key = "connected" if self.record_current else "unknown"
            self.connection.setText(self.t(self.connection_key))
            self.phase_key = "unknown" if age > 5 else keys.get(live["phase"], "unknown")
            self.status.setText(self.t(self.phase_key))
            if self.feedback_key in (
                "submitted",
                "initialized",
                "running",
                "auditing",
                "checkpoint",
                "unknown",
            ):
                self.set_feedback(self.phase_key)
            self.render_live(live)
            self.arrange_scene()
            self.poll_display()
            if live.get("display_error"):
                self.display_key = "display_unknown"
                self.display_status.setText(
                    self.t("display_unknown") + "\n" + live["display_error"]["message"]
                )
            if self.control_request:
                self.control_state, _ = recover(self.run_directory, self.control_request)
                self.render_control()
            self.update_controls()
        except FileNotFoundError:
            if self.last_live or time.monotonic() - self.submitted_s > 5:
                self.mark_unknown("LIVE_RECORD_MISSING")
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.mark_unknown(str(error))

    def update_controls(self):
        busy = self.busy()
        next_draft = self.can_prepare_next()
        editable = (not busy or next_draft) and self.pending_launch is None
        self.launch_button.setText(
            self.t(
                "launch_control"
                if self.control_mode
                else "restart_display"
                if next_draft
                else "launch"
            )
        )
        self.launch_button.setEnabled(editable and self.arm.isChecked())
        self.input_group.setEnabled(editable)
        self.draft_scope.setText(
            self.t(
                "next_trial_pending"
                if self.pending_launch
                else "draft_for_next"
                if next_draft
                else "draft_locked"
                if busy
                else "draft_pre_run"
            )
        )
        for button in self.tabs + [self.settings_button]:
            button.setEnabled(not busy)
        self.camera_button.setEnabled(busy and self.backend == "isaac" and self.record_current)
        self.locate_button.setEnabled(busy and self.backend == "isaac" and self.record_current)
        self.close_scene_button.setEnabled(busy and self.phase_key == "checkpoint")
        self.evidence_button.setEnabled(self.run_directory is not None)
        # Input group is locked during production; controls live outside it.
        self.stop_button.setVisible(self.control_mode)
        self.reconnect_button.setVisible(self.control_mode)
        self.recover_button.setVisible(self.control_mode)
        self.control_status.setVisible(self.control_mode)
        self.stop_button.setEnabled(
            bool(
                self.control_request
                and busy
                and self.record_current
                and not self.detached
                and self.control_state
                and self.control_state["phase"] in ("STARTING", "RUNNING")
                and self.pending_control is None
            )
        )
        self.reconnect_button.setEnabled(bool(self.control_request and busy))
        self.recover_button.setEnabled(not busy)

    def confirm_control(self, key, draft=None):
        detail = self.t(key)
        if draft:
            detail += "\n" + json.dumps(
                dict(backend=self.backend, **draft.data()), ensure_ascii=False, indent=2
            )
        dialog = QMessageBox(self)
        dialog.setWindowTitle(self.t("control_title"))
        dialog.setText(detail)
        dialog.setIcon(QMessageBox.Icon.NoIcon)
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        dialog.button(QMessageBox.StandardButton.Yes).setText(self.t("confirm_yes"))
        dialog.button(QMessageBox.StandardButton.No).setText(self.t("confirm_no"))
        return dialog.exec() == QMessageBox.StandardButton.Yes

    def render_control(self):
        if not hasattr(self, "control_status"):
            return
        text = self.t("control_unknown")
        if self.control_state and not self.detached and (self.record_current or not self.busy()):
            state = self.control_state
            text = self.t("control_phase") + ": " + self.t("control_" + state["phase"])
            if self.pending_control:
                key = canonical_digest(self.pending_control)
                receipt = state["responses"].get(key)
                if receipt:
                    text += "\n" + self.t(
                        "control_accepted" if receipt["accepted"] else "control_rejected"
                    )
                    text += " · " + (receipt["result"] or self.t("control_pending"))
                    if not receipt["accepted"]:
                        text += "\n" + receipt["reason"]
                    if receipt["result"] is not None or not receipt["accepted"]:
                        self.pending_control = None
                else:
                    text += "\n" + self.t("control_pending")
        self.control_status.setText(text)

    def stop_production(self):
        if not self.stop_button.isEnabled() or not self.confirm_control("confirm_stop"):
            return
        try:
            state, pending = recover(self.run_directory, self.control_request)
            if pending:
                raise InputError("CONTROL_UNRESOLVED_REQUEST")
            self.pending_control = command(self.control_request, "stop", state["last_sequence"] + 1)
            submit(self.run_directory, self.pending_control)
            self.set_feedback("stop_submitted")
            self.update_controls()
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.mark_unknown(str(error))

    def disconnect_control(self):
        self.detached = True
        self.mark_unknown("FRONTEND_DISCONNECTED_NO_REPLAY")
        self.render_control()

    def reconnect(self):
        try:
            state, pending = recover(self.run_directory, self.control_request)
            try:
                self.view_sequence = max(
                    self.view_sequence, display_sequence(self.run_directory, self.control_request)
                )
            except (OSError, ValueError, TypeError, KeyError):
                # Display-channel corruption cannot prevent production control
                # recovery. New display requests retry their own validation.
                self.display_key, self.display_suffix = "display_unknown", ""
            started = read_json(self.run_directory / "started.json")
            if (started.get("run_id"), started.get("request_id")) != (self.run_id, self.request_id):
                raise InputError("CONTROL_PROCESS_IDENTITY")
            if not self.process_watch:
                watch = ProcessWatch(started)
                if self.process.state() == QProcess.ProcessState.NotRunning:
                    self.process_watch = watch
                else:
                    watch.close()
            self.control_state, self.detached = state, False
            # Restore one unresolved envelope, without submitting it again.
            candidates = [
                e["request"]
                for e in state["commands"].values()
                if state["responses"][e["digest"]]["accepted"]
                and state["responses"][e["digest"]]["result"] is None
            ]
            if pending:
                candidates += [
                    read_json(self.run_directory / "control-inbox" / (p + ".json")) for p in pending
                ]
            self.pending_control = max(candidates, key=lambda c: c["sequence"], default=None)
            self.poll()
            self.set_feedback("reconnected")
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.mark_unknown(str(error))

    def choose_recovery(self):
        folder = QFileDialog.getExistingDirectory(self, self.t("recover_run"), str(self.runs))
        if folder:
            self.restore_run(Path(folder))

    def restore_run(self, directory):
        if self.busy():
            return False
        try:
            from .model import validate_request

            request = validate_request(read_json(directory / "request.json"))
            state, _ = recover(directory, request)
            if state["phase"] in ("STOPPED", "STOP_BLOCKED", "COMPLETED", "FAILED"):
                # An ended worker cannot be reattached. Verify saved evidence
                # and the original actual-exit receipt, then open read-only.
                record = read_history(directory)
                exit_record = read_json(directory / "process-exit.json")
                if record["report"].get("closed") is not True or exit_record.get("exit_code") != 0:
                    raise InputError("CONTROL_SAVED_EXIT_UNVERIFIED")
                return self.load_history(directory)
            started = read_json(directory / "started.json")
            if (started.get("run_id"), started.get("request_id")) != (
                request["run_id"],
                request["request_id"],
            ):
                raise InputError("CONTROL_PROCESS_IDENTITY")
            watch = ProcessWatch(started)
            self.run_directory, self.control_request = directory, request
            self.run_id, self.request_id = request["run_id"], request["request_id"]
            self.backend = request["backend"]
            self.control_state, self.process_watch = state, watch
            self.last_sequence, self.last_live, self.bound_version = -1, None, None
            self.binding_future, self.binding_key = None, None
            self.saved_record_valid = False
            self.record_current = False
            self.entity_rows = []
            self.pending_view = None
            self.submitted_s = time.monotonic()
            self.detached = False
            self.pages.setCurrentIndex(0)
            self.retranslate()
            self.reconnect()
            return True
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.set_feedback("control_unknown", str(error))
            return False

    def send_view(self, action, **extra):
        if not self.run_directory or not self.busy():
            return False
        try:
            self.view_sequence = max(
                self.view_sequence,
                display_sequence(
                    self.run_directory, dict(run_id=self.run_id, request_id=self.request_id)
                ),
            )
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.display_key, self.display_suffix = "display_unknown", str(error)
            self.display_status.setText(self.t(self.display_key) + "\n" + self.display_suffix)
            self.set_feedback("display_unknown", str(error))
            return False
        self.view_sequence += 1
        self.pending_view = dict(
            run_id=self.run_id,
            request_id=self.request_id,
            epoch=0,
            sequence=self.view_sequence,
            action=action,
            **extra,
        )
        self.view_submitted_s = time.monotonic()
        atomic_json(
            self.run_directory / "view-request.json",
            self.pending_view,
        )
        return True

    def request_camera(self):
        if not self.record_current:
            return
        if self.send_view("camera", camera=self.camera.currentText()):
            self.set_feedback("camera_pending")

    def request_location(self):
        if not self.record_current or self.backend != "isaac" or not self.busy():
            self.display_key = "location_unavailable"
        else:
            if not self.send_view("locate", entity_id=self.entity.currentText()):
                return
            self.display_key = "location_pending"
        self.display_suffix = ""
        self.display_status.setText(self.t(self.display_key))

    def poll_display(self):
        if not self.pending_view or self.pending_view["action"] == "close_display":
            return
        locate = self.pending_view["action"] == "locate"
        path = self.run_directory / (
            "location-confirmation.json" if locate else "view-confirmation.json"
        )
        try:
            if not path.is_file():
                if time.monotonic() - self.view_submitted_s > 5:
                    self.display_key = "display_unknown"
                return
            value = read_json(path)
            if value.get("sequence") != self.pending_view["sequence"]:
                if time.monotonic() - self.view_submitted_s > 5:
                    self.display_key = "display_unknown"
                return
            validate_confirmation(value, self.pending_view)
            if locate:
                self.display_key = (
                    "location_confirmed" if value["accepted"] else "location_rejected"
                )
                self.display_suffix = "\n".join(value.get("paths", []))
                if value.get("unmapped_targets"):
                    self.display_suffix += (
                        "\n"
                        + self.t("unmapped_targets")
                        + ": "
                        + ", ".join(value["unmapped_targets"])
                    )
            else:
                self.display_key = "camera_confirmed" if value["accepted"] else "display_unknown"
                self.display_suffix = value.get("camera_path", "")
                self.set_feedback(self.display_key, self.display_suffix)
        except (OSError, ValueError, TypeError, KeyError):
            self.display_key, self.display_suffix = "display_unknown", ""
        finally:
            self.display_status.setText(self.t(self.display_key) + "\n" + self.display_suffix)

    def close_display(self):
        if self.phase_key == "checkpoint":
            self.send_view("close_display")
            self.set_feedback("close_pending")

    def choose_history(self):
        folder = QFileDialog.getExistingDirectory(self, self.t("open_history"), str(self.runs))
        if folder:
            self.load_history(Path(folder))

    def inspect_current(self):
        if not self.run_directory:
            return
        if not self.busy():
            self.load_history(self.run_directory)
            return
        try:
            result = read_history(self.run_directory)
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.set_feedback("history_error", str(error))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(self.t("evidence_preview"))
        layout = QVBoxLayout(dialog)
        preview = QTextEdit()
        preview.setReadOnly(True)
        listing = QListWidget()
        self.populate_evidence(listing, result["evidence"])

        def show(item):
            try:
                read_history(self.run_directory)
                value = preview_evidence(self.run_directory, item.data(Qt.ItemDataRole.UserRole))
                if isinstance(value, Path):
                    preview.setPlainText(str(value))
                else:
                    preview.setPlainText(value)
            except (OSError, ValueError, TypeError, KeyError) as error:
                preview.setPlainText(self.t("history_error") + "\n" + str(error))

        listing.itemClicked.connect(show)
        layout.addWidget(
            QLabel(
                self.t("historical") + " · " + self.t(result["integrity"]) + "\n" + result["run_id"]
            )
        )
        layout.addWidget(listing)
        layout.addWidget(preview, 1)
        dialog.resize(780, 650)
        self.evidence_dialog = dialog
        dialog.show()

    def load_history(self, folder):
        if self.busy():
            return False
        try:
            result = read_history(folder)
        except (OSError, ValueError, TypeError, KeyError) as error:
            self.history_record, self.history_directory = None, None
            self.evidence_list.clear()
            self.history_details.clear()
            self.render_reason(None)
            self.phase_key = "unknown"
            self.status.setText(self.t("unknown"))
            self.set_feedback("history_error", str(error))
            return False
        self.history_record, self.history_directory = result, Path(folder)
        self.select_mode("history")
        self.populate_evidence(self.evidence_list, result["evidence"])
        self.render_history()
        self.set_feedback("historical", result["run_id"])
        return True

    def render_history(self):
        result = self.history_record
        self.populate_evidence(self.evidence_list, result["evidence"])
        manifest = result["manifest"]
        summary = [
            self.t("historical"),
            self.t(result["integrity"]),
            self.t("record_identity") if result["identity_complete"] else self.t("legacy_id"),
            self.t("sim_time") + ": " + str(manifest.get("time_h", "—")) + " h",
            self.audit_text(manifest.get("audit"), manifest.get("decision_audit")),
        ]
        exit_path = self.history_directory / "process-exit.json"
        summary.append(
            self.t("exited") + " · " + str(read_json(exit_path).get("exit_code"))
            if exit_path.is_file()
            else self.t("exit_unknown")
        )
        state_path = self.history_directory / "state.json"
        if state_path.is_file():
            state = read_json(state_path, 20_000_000)
            for product in state.get("products", []):
                key = (
                    "received"
                    if product.get("received_h") is not None
                    else "cancelled"
                    if product.get("cancelled") is True
                    else "ready"
                    if product.get("ready_h") is not None
                    else "released"
                    if product.get("released") is True
                    else "pending"
                )
                summary.append(str(product.get("product_id", "—")) + " · " + self.t(key))
        self.history_details.setPlainText(
            "\n".join(summary)
            + "\n"
            + json.dumps(
                {
                    "run_id": result["run_id"],
                    "record_sha256": result["record_sha256"],
                    "status": result["report"].get("status"),
                    "closed": result["report"].get("closed"),
                    "manifest": result["manifest"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        try:
            fact = history_reason(self.history_directory)
            self.render_reason(fact, current=False)
        except (OSError, ValueError, TypeError, KeyError):
            self.render_reason(None)

    def open_evidence(self):
        item = self.evidence_list.currentItem()
        name = item.data(Qt.ItemDataRole.UserRole) if item else None
        if self.history_directory and item and name in self.history_record["evidence"]:
            try:
                result = read_history(self.history_directory)
                if name not in result["evidence"]:
                    raise InputError("EVIDENCE_UNAVAILABLE")
                value = preview_evidence(self.history_directory, name)
                if isinstance(value, Path):
                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(value)))
                else:
                    self.history_details.setPlainText(self.t("evidence_preview") + "\n" + value)
            except (OSError, ValueError, TypeError, KeyError) as error:
                self.history_details.setPlainText(self.t("history_error") + "\n" + str(error))

    def arrange_scene(self):
        """Attach the correlated worker to the main window, including during startup."""
        if self.backend != "isaac" or sys.platform != "win32":
            return
        try:
            started = read_json(self.run_directory / "started.json")
            if started.get("run_id") != self.run_id or started.get("request_id") != self.request_id:
                raise InputError("WINDOW_RUN_IDENTITY_MISMATCH")
            self.scene_host.attach(started["pid"])
            self.scene_host.sync_geometry()
            layout = self.scene_host.measure()
            if layout:
                self.scene_placeholder.hide()
                if layout != self.last_window_layout:
                    atomic_json(self.run_directory / "window-layout.json", layout)
                    self.last_window_layout = layout
                if not layout["child_of_main"] or not layout["contained_in_host"]:
                    self.set_feedback("embedding_error", "NATIVE_CONTAINMENT_UNCONFIRMED")
        except FileNotFoundError:
            pass
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            self.set_feedback("embedding_error", str(error))

    def closeEvent(self, event):
        if self.busy():
            if self.phase_key == "checkpoint":
                self.close_display()
            else:
                self.set_feedback("close_busy")
            event.ignore()
        else:
            self.persist_preferences()
            self.binding_executor.shutdown(wait=False, cancel_futures=True)
            event.accept()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=Path)
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--session-bundle", type=Path)
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    configure_application(app)
    window = Workbench(
        runs=args.runs,
        settings=args.settings,
        session_bundle=read_json(args.session_bundle) if args.session_bundle else None,
    )
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
