"""Visible native Kit host with or without the actual read-only Workbench polling."""

import argparse
import ctypes
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "desktop/s19b/src"), str(ROOT / "scripts")]


class ProcessCounters(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
        (n, ctypes.c_size_t)
        for n in ("peak", "working", "ppp", "pp", "pnpp", "pnp", "page", "peakpage", "private")
    ]


class ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("usage", wintypes.DWORD),
        ("pid", wintypes.DWORD),
        ("heap", ctypes.c_size_t),
        ("module", wintypes.DWORD),
        ("threads", wintypes.DWORD),
        ("parent", wintypes.DWORD),
        ("priority", wintypes.LONG),
        ("flags", wintypes.DWORD),
        ("name", wintypes.WCHAR * 260),
    ]


def process_sample(pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]

    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessCounters),
        wintypes.DWORD,
    ]
    handle = kernel.OpenProcess(0x1000 | 0x10, False, pid)
    if not handle:
        return dict(pid=pid, unavailable=ctypes.get_last_error())
    try:
        counters = ProcessCounters()
        counters.cb = ctypes.sizeof(counters)
        creation, exit_time, cpu_kernel, cpu_user = (wintypes.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(cpu_kernel),
            ctypes.byref(cpu_user),
        ) or not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return dict(pid=pid, unavailable=ctypes.get_last_error())

        def ticks(f):
            return (f.dwHighDateTime << 32) | f.dwLowDateTime

        return dict(
            pid=pid,
            creation_ticks=ticks(creation),
            cpu_s=(ticks(cpu_kernel) + ticks(cpu_user)) / 10_000_000,
            working_set_bytes=counters.working,
            peak_working_set_bytes=counters.peak,
            private_bytes=counters.private,
        )
    finally:
        kernel.CloseHandle(handle)


def process_tree(root_pid):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = kernel.Process32NextW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ProcessEntry),
    ]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateToolhelp32Snapshot(2, 0)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = ProcessEntry()
        entry.size = ctypes.sizeof(entry)
        rows = []
        valid = kernel.Process32FirstW(handle, ctypes.byref(entry))
        while valid:
            rows.append(dict(pid=entry.pid, parent=entry.parent, name=entry.name))
            valid = kernel.Process32NextW(handle, ctypes.byref(entry))
        selected = {root_pid}
        while True:
            expanded = selected | {r["pid"] for r in rows if r["parent"] in selected}
            if expanded == selected:
                break
            selected = expanded
        return [dict(**r, counters=process_sample(r["pid"])) for r in rows if r["pid"] in selected]
    finally:
        kernel.CloseHandle(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--mode", choices=("visible", "headless", "light"), required=True)
    parser.add_argument("--frontend", choices=("off", "zh-CN", "en"), required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    opts = parser.parse_args()
    out = opts.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    from measure_s19b_worker import case_args
    from s19b_desktop.control import ProcessWatch
    from s19b_desktop.model import atomic_json

    identity = dict(run_id="S19B-" + uuid.uuid4().hex, request_id="REQ-" + uuid.uuid4().hex)
    case = next(
        c
        for c in json.loads((ROOT / "examples/online/workloads.json").read_text(encoding="utf-8"))[
            "cases"
        ]
        if c["id"] == opts.case
    )
    declared = case_args(
        case, out, "light" if opts.mode == "light" else "isaac", identity["run_id"]
    )
    atomic_json(out / "identity.json", identity)
    atomic_json(
        out / "measurement.json",
        dict(
            case=opts.case,
            mode=opts.mode,
            frontend=opts.frontend,
            case_arguments=case["arguments"],
            limits_file=case["limits"],
            original_witness_arguments={
                key: str(value) if isinstance(value, Path) else value
                for key, value in vars(declared).items()
            },
            freeze_sha256=hashlib.sha256(opts.freeze.read_bytes()).hexdigest(),
            frontend_capability="MEASUREMENT_READ_ONLY_NO_USER_PRODUCTION_CONTROLS",
        ),
    )
    env = dict(os.environ)
    for key in ("PYTHONEXE", "PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"):
        env.pop(key, None)
    args = [
        str(ROOT / "scripts/measure_s19b_worker.py"),
        "--output",
        str(out),
        "--case",
        opts.case,
        "--mode",
        opts.mode,
        "--freeze",
        str(opts.freeze.resolve()),
    ]
    if opts.mode == "light":
        command = [str(ROOT / ".venv/Scripts/python.exe"), "-u", *args]
    else:
        command = [
            "C:/Program Files/PowerShell/7/pwsh.exe",
            "-NoProfile",
            "-File",
            str(ROOT / "scripts/measure_s19b_kit.ps1"),
            *args,
        ]
    window = host = app = None
    if opts.mode == "visible":
        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication, QMainWindow
        from s19b_desktop.app import Workbench, configure_application
        from s19b_desktop.embedded import KitHost

        app = QApplication([])
        configure_application(app)
        if opts.frontend == "off":
            window = QMainWindow()
            window.setWindowTitle("S19B measurement · frontend off")
            host = KitHost(window)
            host.setFixedSize(600, 434)
            window.setCentralWidget(host)
        else:
            atomic_json(
                out / "settings.json",
                dict(locale=opts.frontend, isaac_root="D:/Dev/tools/isaac-sim-6.1"),
            )
            window = Workbench(runs=out / "unused-runs", settings=out / "settings.json")
            window.timer.stop()
            window.control_mode = False
            window.select_mode("isaac")
            window.count.setValue(declared.products)
            window.variant.setCurrentText(declared.variant)
            for index, release in enumerate(declared.release_times or [0.0] * declared.products):
                window.orders.item(index, 1).setText(str(release))
            window.note.setText(
                "Predeclared read-only measurement: "
                + opts.case
                + "; scenario and budgets in measurement.json"
            )
            window.input_group.setEnabled(False)
            window.launch_button.setEnabled(False)
            window.stop_button.setEnabled(False)
            window.camera_group.setEnabled(False)
            window.entity_group.setEnabled(False)
            window.run_directory = out
            window.run_id, window.request_id = identity["run_id"], identity["request_id"]
            window.submitted_s = time.monotonic()
            host = window.scene_host
            host.setFixedSize(600, 434)
        window.show()
        for _ in range(20):
            app.processEvents()
    started = time.perf_counter()
    samples = []
    failure = None
    worker_watch = None
    quiesced = False
    with (out / "process.log").open("x", encoding="utf-8") as stream:
        child = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdout=stream,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if window is not None and opts.frontend != "off":
            window.busy = lambda: child.poll() is None
        try:
            next_tick = time.monotonic()
            while child.poll() is None:
                if app:
                    app.processEvents()
                if not quiesced and (out / "closing-ready.json").exists():
                    closing = json.loads((out / "closing-ready.json").read_text(encoding="utf-8"))
                    if any(closing.get(key) != value for key, value in identity.items()):
                        raise ValueError("CLOSE_HANDSHAKE_IDENTITY_MISMATCH")
                    if window is not None:
                        window.setFixedSize(window.size())
                    if host is not None:
                        # Keep the correlated native child embedded; stop foreign
                        # geometry/attachment calls before Kit destroys that HWND.
                        host.attach = lambda _pid: None
                        host.sync_geometry = lambda: None
                    if window is not None and opts.frontend != "off":
                        window.busy = lambda: False
                    quiesced = True
                    atomic_json(
                        out / "host-quiesced.json",
                        dict(**identity, pid=os.getpid(), worker_pid=closing["pid"]),
                    )
                now = time.monotonic()
                if now >= next_tick:
                    began = time.perf_counter()
                    row = dict(
                        perf_counter_s=began,
                        elapsed_s=began - started,
                        parent=process_sample(os.getpid()),
                        launcher=process_sample(child.pid),
                    )
                    row["process_tree"] = process_tree(os.getpid())
                    if (out / "started.json").exists():
                        worker = json.loads((out / "started.json").read_text(encoding="utf-8"))
                        if worker_watch is None:
                            worker_watch = ProcessWatch(worker)
                            atomic_json(
                                out / "process-watch-ready.json",
                                dict(
                                    pid=worker["pid"],
                                    process_token=worker["process_token"],
                                    observer_pid=os.getpid(),
                                ),
                            )
                        row["worker"] = process_sample(worker["pid"])
                        if not quiesced and host and (out / "display-ready.json").exists():
                            host.attach(worker["pid"])
                            app.processEvents()
                            host.sync_geometry()
                            if host.hwnd and not (out / "host-ready.json").exists():
                                layout = host.measure()
                                row["host_layout"] = layout
                                if (
                                    layout["visible"]
                                    and layout["child_of_main"]
                                    and layout["contained_in_host"]
                                ):
                                    atomic_json(out / "host-ready.json", layout)
                        if (
                            window
                            and opts.frontend != "off"
                            and not quiesced
                            and (out / "display-ready.json").exists()
                        ):
                            ui_start = time.perf_counter()
                            window.poll()
                            app.processEvents()
                            row["ui_poll_s"] = time.perf_counter() - ui_start
                            row["phase"] = window.phase_key
                            row["current"] = window.record_current
                            row["binding_pending"] = window.bound_version is None
                            if window.last_live:
                                row["state_age_wall_s"] = (
                                    time.time() - window.last_live["published_wall_s"]
                                )
                                row["state_age_s"] = (
                                    time.monotonic() - window.last_live["published_monotonic_s"]
                                )
                                row["sequence"] = window.last_sequence
                            window.input_group.setEnabled(False)
                            window.launch_button.setEnabled(False)
                            window.stop_button.setEnabled(False)
                            window.camera_group.setEnabled(False)
                            window.entity_group.setEnabled(False)
                    row["sampling_s"] = time.perf_counter() - began
                    samples.append(row)
                    next_tick = now + 0.25
                    if len(samples) % 20 == 0:
                        atomic_json(
                            out / "observer-progress.json", dict(samples=len(samples), **row)
                        )
                time.sleep(0.005 if app else 0.025)
        except BaseException as error:
            failure = repr(error)
            # Let the authorized witness complete. Never terminate a live worker.
            while child.poll() is None:
                if app:
                    app.processEvents()
                time.sleep(0.025)
        code = child.wait()
    worker_code = worker_watch.exit_code() if worker_watch else None
    if worker_watch:
        worker_watch.close()
    saved_report = (
        json.loads((out / "report.json").read_text(encoding="utf-8"))
        if (out / "report.json").exists()
        else {}
    )
    if worker_code != 0 or not saved_report.get("closed") or not (out / "stages.json").exists():
        failure = failure or "ACTUAL_WORKER_EXIT_OR_FULL_CLOSE_NOT_CONFIRMED"
    atomic_json(
        out / "process-exit.json",
        dict(
            exit_code=code,
            actual_worker_exit_code=worker_code,
            observer="INDEPENDENT_QT_CPYTHON_PARENT_WAIT_FOR_POWERSHELL7_WORKER",
            elapsed_s=time.perf_counter() - started,
            observer_failure=failure,
        ),
    )
    atomic_json(out / "observer-samples.json", samples)
    if app:
        host.release()
        window.close()
        window.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        app.quit()
    print(
        json.dumps(
            dict(output=str(out), exit_code=code, observer_failure=failure, samples=len(samples))
        ),
        flush=True,
    )
    return code if not failure else 1


if __name__ == "__main__":
    raise SystemExit(main())
