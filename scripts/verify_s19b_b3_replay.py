"""B3 bounded Qt replay costs and fresh-run labels; not an online benchmark."""

import argparse
import ctypes
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop/s19b/src"))


def memory():
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
            (name, ctypes.c_size_t)
            for name in ("peak", "working", "ppp", "pp", "pnpp", "pnp", "page", "peakpage")
        ]

    value = Counters()
    value.cb = ctypes.sizeof(value)
    get_process = ctypes.windll.kernel32.GetCurrentProcess
    get_process.restype = wintypes.HANDLE
    get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
    get_memory.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    get_memory.restype = wintypes.BOOL
    if not get_memory(get_process(), ctypes.byref(value), value.cb):
        raise ctypes.WinError()
    return dict(working_set_bytes=value.working, peak_working_set_bytes=value.peak)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QEvent, Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
    from s19b_desktop.app import Workbench, configure_application
    from s19b_desktop.model import atomic_json, canonical_digest, read_json
    from s19b_desktop.review import reason_fact

    live = read_json(args.live)
    journal_path = args.live.parent / "online-journal.json"
    # Offline benchmark input, not the bounded live-message parser.
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    rows = sorted(
        journal,
        key=lambda row: len(json.dumps(reason_fact([row]), ensure_ascii=False)),
        reverse=True,
    )[:40]
    fixtures = [dict(live, reason=reason_fact([row])) for row in rows]
    atomic_json(args.output / "fixtures.json", fixtures)
    fixture_hash = hashlib.sha256((args.output / "fixtures.json").read_bytes()).hexdigest()
    source_hashes = {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (ROOT / "desktop/s19b/src").rglob("*.py")
    }
    protocol = dict(
        method="OFFSCREEN_QT_REPLAY_NOT_ONLINE_FRONTEND_TOGGLE_OR_KIT_BENCHMARK",
        fixture_sha256=fixture_hash,
        sources=source_hashes,
        sequence=["zh-CN", "en", "en", "zh-CN"],
        warmup=20,
        samples_per_block=200,
        period_ms=250,
        p95_limit_s=0.05,
        max_limit_s=0.25,
        paint="offscreen Qt event processing; excludes real GPU/native paint",
        production_load="saved SR-W1 final rows plus actual 40 largest reason lists; display stress only, not chronological live snapshots",
        journal_sha256=hashlib.sha256(journal_path.read_bytes()).hexdigest(),
    )
    atomic_json(args.output / "predeclared.json", protocol)
    app = QApplication([])
    configure_application(app)
    settings = args.output / "settings.json"
    atomic_json(settings, {"locale": "zh-CN", "isaac_root": ""})
    window = Workbench(runs=args.output / "runs", settings=settings)
    window.show()
    window.timer.stop()
    window.saved_record_valid = True
    results = dict(protocol=protocol, blocks=[], controls=[], status="RUNNING")
    for locale in protocol["sequence"]:
        window.language.setCurrentIndex(0 if locale == "zh-CN" else 1)
        before = canonical_digest(fixtures)
        times = []
        cpu_start = time.process_time()
        for index in range(protocol["warmup"] + protocol["samples_per_block"]):
            began = time.perf_counter()
            window.render_live(fixtures[index % len(fixtures)])
            app.processEvents()
            elapsed = time.perf_counter() - began
            if index >= protocol["warmup"]:
                times.append(elapsed)
            QTest.qWait(max(0, int(250 - elapsed * 1000)))
        ordered = sorted(times)
        unchanged = before == canonical_digest(fixtures)
        assert unchanged and not (args.output / "runs").exists()
        results["blocks"].append(
            dict(
                locale=locale,
                samples_s=times,
                p50_s=ordered[99],
                p95_s=ordered[190],
                max_s=ordered[-1],
                cpu_s=time.process_time() - cpu_start,
                memory=memory(),
                input_unchanged=unchanged,
                no_commands=True,
                work_limits_pass=ordered[190] <= 0.05 and ordered[-1] <= 0.25,
            )
        )
        atomic_json(args.output / "replay.json", results)
        print("REPLAY_BLOCK", locale, results["blocks"][-1]["work_limits_pass"], flush=True)

    # Real CPU launch after a previous successful run must immediately replace
    # the old success labels, before any backend initialization is received.
    window.saved_record_valid = False
    window.last_live = None
    window.connection_key = "actual_exit"
    window.connection.setText("OLD_SUCCESS_SENTINEL")
    window.control_status.setText("OLD_SUCCESS_SENTINEL")
    window.arm.setChecked(True)

    def confirm():
        dialog = app.activeModalWidget()
        assert isinstance(dialog, QMessageBox)
        QTest.mouseClick(dialog.button(QMessageBox.StandardButton.Yes), Qt.MouseButton.LeftButton)

    QTimer.singleShot(40, confirm)
    window.launch()
    assert "OLD_SUCCESS_SENTINEL" not in window.connection.text()
    assert "OLD_SUCCESS_SENTINEL" not in window.control_status.text()
    assert window.connection.text() == window.t("submitted")
    assert window.control_status.text() == window.t("control_unknown")
    results["controls"].append("FRESH_RUN_LABELS_CLEAR_OLD_SUCCESS_BEFORE_INITIALIZATION")
    window.timer.start(250)
    end = time.monotonic() + 420
    while not window.stop_button.isEnabled():
        app.processEvents()
        QTest.qWait(30)
        if time.monotonic() >= end:
            raise TimeoutError("CPU_INITIALIZATION")
    QTimer.singleShot(40, confirm)
    window.stop_production()
    while window.busy():
        app.processEvents()
        QTest.qWait(30)
        if time.monotonic() >= end:
            raise TimeoutError("CPU_STOP_EXIT")
    assert window.phase_key == "stopped", window.feedback.text()
    assert read_json(window.run_directory / "process-exit.json")["exit_code"] == 0
    results["control_run"] = str(window.run_directory)
    results["controls"].append("ACTUAL_CPU_ORDERLY_STOP_AUDITS_EXIT")
    results["status"] = (
        "PASS_WITH_SCOPE_LIMITS"
        if all(b["work_limits_pass"] for b in results["blocks"])
        else "WORK_LIMITS_FAILED_WITH_CONTROL_CHECKS_PASS"
    )
    atomic_json(args.output / "replay.json", results)
    window.timer.stop()
    window.close()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    return 0 if results["status"] == "PASS_WITH_SCOPE_LIMITS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
