"""Exercise real Qt confirmations and live B2 CPU / embedded Kit controls."""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop/s19b/src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--isaac-root", type=Path)
    parser.add_argument("--skip-kit", action="store_true")
    parser.add_argument("--orphan-launch", action="store_true")
    parser.add_argument("--full-normal", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    from PySide6.QtCore import QEvent, Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox
    from s19b_desktop.app import Workbench, configure_application
    from s19b_desktop.control import command, recover, submit
    from s19b_desktop.model import atomic_json, canonical_digest, read_history, read_json

    app = QApplication([])
    configure_application(app)
    settings = args.output / "settings.json"
    atomic_json(settings, {"locale": "zh-CN", "isaac_root": str(args.isaac_root or "")})
    window = Workbench(runs=args.output / "runs", settings=settings)
    window.show()
    results = dict(
        status="RUNNING", method="REAL_QT_SYNTHETIC_EVENTS_NOT_OWNER_ACCEPTANCE", checks=[], runs=[]
    )

    def save():
        atomic_json(args.output / "b2-ui-verification.json", results)

    def check(name, **facts):
        results["checks"].append(dict(name=name, status="PASS", **facts))
        save()
        print(name, flush=True)

    def wait(predicate, timeout=30):
        deadline = time.monotonic() + timeout
        while not predicate():
            app.processEvents()
            QTest.qWait(30)
            if window.phase_key == "failed" and not window.busy():
                raise RuntimeError("BACKEND_FAILED:" + window.feedback.text())
            if time.monotonic() >= deadline:
                raise TimeoutError("WAIT:" + window.phase_key + ":" + window.feedback.text())

    def answer(button):
        def act():
            dialog = app.activeModalWidget()
            if not isinstance(dialog, QMessageBox):
                raise RuntimeError("CONFIRMATION_MODAL_MISSING")
            results.setdefault("confirmations", []).append(
                dict(text=dialog.text(), answer=button.name)
            )
            QTest.mouseClick(dialog.button(button), Qt.MouseButton.LeftButton)

        QTimer.singleShot(80, act)

    def launch(yes=True):
        window.arm.setChecked(True)
        answer(QMessageBox.StandardButton.Yes if yes else QMessageBox.StandardButton.No)
        QTest.mouseClick(window.launch_button, Qt.MouseButton.LeftButton)

    def language(locale):
        window.language.setCurrentIndex(0 if locale == "zh-CN" else 1)
        app.processEvents()
        assert window.locale == locale

    def capture(name):
        app.processEvents()
        assert window.grab().save(str(args.output / name))

    def cleanup():
        # Release native containers before QApplication/interpreter teardown.
        window.timer.stop()
        window.close()
        window.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        app.quit()

    def stop_and_verify(name):
        wait(lambda: window.stop_button.isEnabled(), 420)
        before_id = (window.run_id, window.request_id)
        answer(QMessageBox.StandardButton.Yes)
        QTest.mouseClick(window.stop_button, Qt.MouseButton.LeftButton)
        pending = dict(window.pending_control)
        assert pending["action"] == "stop"
        window.disconnect_control()
        assert not window.record_current and not window.stop_button.isEnabled()
        assert "未知" in window.control_status.text() or "unknown" in window.control_status.text()
        # Same envelope submitted again exercises actual backend deduplication.
        submit(window.run_directory, pending)
        window.reconnect()
        assert (window.run_id, window.request_id) == before_id
        wait(lambda: not window.busy(), 420)
        assert window.phase_key == "stopped", window.feedback.text()
        directory = window.run_directory
        record = read_history(directory)
        report, manifest = record["report"], record["manifest"]
        state, unresolved = recover(directory, window.control_request)
        assert report["closed"] is True and record["integrity"] == "integrity_checked"
        assert manifest["termination"] == "ORDERLY_STOPPED"
        assert manifest["audit"] == manifest["decision_audit"] == "PASS"
        assert not unresolved and state["phase"] == "STOPPED"
        accepted_stops = [v for v in state["commands"].values() if v["request"]["action"] == "stop"]
        assert len(accepted_stops) == 1
        assert state["responses"][canonical_digest(pending)]["result"] == "STOPPED"
        assert read_json(directory / "process-exit.json")["exit_code"] == 0
        assert not read_json(directory / "state.json")["running"]
        assert manifest["received"] == 0
        check(
            name,
            termination=manifest["termination"],
            stop=manifest["orderly_stop"],
            received=manifest["received"],
            command_count=len(state["commands"]),
        )
        results["runs"].append(str(directory))
        capture(name + ".png")
        return directory

    try:
        wait(window.isVisible)
        window.note.setText("B2 简中 / English")
        draft = canonical_digest(window.draft().data())
        language("en")
        assert window.launch_button.text() == "Confirm and start production"
        assert draft == canonical_digest(window.draft().data())
        capture("ready-en.png")
        language("zh-CN")
        capture("ready-zh.png")
        window.orders.item(0, 1).setText("NaN")
        window.check_input()
        assert "RELEASE_TIME" in window.feedback.text()
        assert window.run_directory is None
        window.orders.item(0, 1).setText("0")
        launch(False)
        assert window.run_directory is None
        check("INPUT_AND_EXPLICIT_CONFIRMATION_REJECTION_BILINGUAL")
        launch()
        wait(lambda: window.record_current and window.last_live and window.last_live["active"], 420)
        if args.orphan_launch:
            atomic_json(
                args.output / "orphan-ready.json",
                dict(directory=str(window.run_directory), frontend_pid=os.getpid()),
            )
            # Simulate abrupt frontend loss, not backend termination. Parent test
            # reconnects via actual worker PID + creation time and retained handle.
            save()
            os._exit(0)
        if args.full_normal:

            def normal_result():
                wait(lambda: not window.busy(), 1800)
                assert window.phase_key == "completed", window.feedback.text()
                directory = window.run_directory
                result = read_history(directory)
                state, pending = recover(directory, window.control_request)
                assert result["integrity"] == "integrity_checked" and not pending
                assert state["phase"] == "COMPLETED" and len(state["commands"]) == 1
                assert result["manifest"]["termination"] == "OPERATIONS_COMPLETE"
                assert result["manifest"]["received"] == 1
                assert result["manifest"]["audit"] == result["manifest"]["decision_audit"] == "PASS"
                assert read_json(directory / "process-exit.json")["exit_code"] == 0
                results["runs"].append(str(directory))
                check(
                    "FULL_NORMAL_" + window.backend.upper(),
                    time_h=result["manifest"]["time_h"],
                    received=1,
                    completed=result["manifest"]["completed_static_operations"],
                    active_operations=result["manifest"]["active_static_operations"],
                )

            normal_result()
            if not args.skip_kit:
                window.select_mode("isaac")
                launch()
                wait(
                    lambda: (
                        window.record_current and window.last_live and window.last_live["active"]
                    ),
                    420,
                )
                wait(lambda: window.scene_host.hwnd is not None)
                layout = window.scene_host.measure()
                assert layout["child_of_main"] and layout["visible"] and layout["contained_in_host"]
                check("FULL_NORMAL_KIT_NATIVE_EMBEDDING", layout=layout)
                capture("full-normal-kit-running.png")
                normal_result()
            results["status"] = "PASS"
            save()
            cleanup()
            return
        directory = window.run_directory
        original = read_json(directory / "start-command.json")
        identity = (window.run_id, window.request_id)
        window.launch()
        assert identity == (window.run_id, window.request_id)
        language("en")
        assert identity == (window.run_id, window.request_id)
        submit(directory, original)
        negatives = [
            {**original, "action": "stop"},
            {**command(window.control_request, "stop", 2), "run_id": "OLD-RUN"},
            {**command(window.control_request, "stop", 2), "epoch": 1},
            command(window.control_request, "stop", 99),
            {**command(window.control_request, "stop", 2), "confirmed": False},
            {**command(window.control_request, "stop", 2), "action": "reset"},
        ]
        for value in negatives:
            submit(directory, value)
        wait(
            lambda: all(
                canonical_digest(v) in read_json(directory / "control-state.json")["responses"]
                for v in negatives
            )
        )
        state = read_json(directory / "control-state.json")
        assert all(not state["responses"][canonical_digest(v)]["accepted"] for v in negatives)
        assert len(state["commands"]) == 1
        log = args.output / "duplicate-worker.log"
        with log.open("wb") as stream:
            duplicate = subprocess.run(
                [
                    str(ROOT / ".venv/Scripts/python.exe"),
                    str(ROOT / "scripts/run_s19b_prototype.py"),
                    "--request",
                    str(directory / "request.json"),
                ],
                stdout=stream,
                stderr=stream,
                timeout=20,
            )
        assert duplicate.returncode != 0
        assert (
            read_json(directory / "started.json")["pid"] != duplicate.pid
            if hasattr(duplicate, "pid")
            else True
        )
        check(
            "LIVE_CPU_DUPLICATES_CONFLICT_OLD_EPOCH_ORDER_UNCONFIRMED_UNSUPPORTED_REJECTED",
            rejected=len(negatives),
        )
        language("zh-CN")
        stop_and_verify("CPU_STOP_DISCONNECT_PENDING_RECONNECT_DEDUP_AUDITS_EXIT")
        # True frontend process loss and fresh Workbench reconstruction.
        orphan = args.output / "orphan"
        with (args.output / "orphan-frontend.log").open("wb") as stream:
            child = subprocess.Popen(
                [
                    sys.executable,
                    __file__,
                    "--output",
                    str(orphan),
                    "--orphan-launch",
                    "--skip-kit",
                ],
                stdout=stream,
                stderr=stream,
            )
            wait(lambda: child.poll() is not None, 120)
        assert child.returncode == 0
        orphan_dir = Path(read_json(orphan / "orphan-ready.json")["directory"])
        assert window.restore_run(orphan_dir)
        assert window.process_watch is not None
        window.reconnect()
        window.reconnect()
        stop_and_verify("CPU_FRONTEND_PROCESS_LOSS_RESTORE_KERNEL_EXIT")
        assert window.restore_run(orphan_dir)  # ended backend opens read-only
        assert window.backend == "history"
        check("EXITED_BACKEND_RECOVERY_READ_ONLY")
        if not args.skip_kit:
            window.select_mode("isaac")
            launch()
            wait(
                lambda: window.record_current and window.last_live and window.last_live["active"],
                420,
            )
            wait(lambda: window.scene_host.hwnd is not None)
            layout = window.scene_host.measure()
            assert layout["visible"] and layout["child_of_main"] and layout["contained_in_host"]
            assert layout["host_window_physical"] == layout["scene_window_physical"]
            initial = window.size()
            window.resize(initial.width() - 80, initial.height() - 30)
            QTest.qWait(400)
            window.arrange_scene()
            resized = window.scene_host.measure()
            assert resized["child_of_main"] and resized["contained_in_host"]
            window.resize(initial)
            check("LIVE_KIT_CENTRAL_NATIVE_CHILD_AUTO_FILL", initial=layout, resized=resized)
            language("en")
            capture("kit-running-en.png")
            language("zh-CN")
            capture("kit-running-zh.png")
            # Read-only B1 paths still operate during production.
            window.entity.setCurrentText("FORK-01")
            window.request_location()
            wait(lambda: window.display_key == "location_confirmed", 120)
            location = read_json(window.run_directory / "location-confirmation.json")
            assert location["state_before_sha256"] == location["state_after_sha256"]
            window.camera.setCurrentText("Top")
            window.request_camera()
            wait(lambda: window.display_key == "camera_confirmed", 120)
            check("B1_READ_ONLY_LOCATION_CAMERA_CURRENT_B2_SOURCE")
            stop_and_verify("KIT_STOP_PENDING_RECONNECT_READBACK_AUDITS_CLOSE_EXIT")
        results["status"] = "PASS"
        save()
        window.close()
    except BaseException as error:
        results["status"] = "FAILED"
        results["error"] = repr(error)
        save()
        if window.busy():
            # Retain and let the authorized backend continue; never kill it.
            print("FAILED_WITH_LIVE_BACKEND:" + str(window.run_directory), flush=True)
            os._exit(1)
        raise
    print(json.dumps(dict(status=results["status"], checks=len(results["checks"]))), flush=True)
    cleanup()


if __name__ == "__main__":
    main()
