"""Exercise real Qt widgets and CPU/visible Kit prefix entry points, retaining evidence."""

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop/s19b/src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--isaac-root", type=Path)
    parser.add_argument("--skip-kit", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    from PySide6.QtCore import QEvent, QPoint, Qt
    from PySide6.QtGui import QInputMethodEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from s19b_desktop.app import Workbench, configure_application
    from s19b_desktop.model import atomic_json, canonical_digest, read_json

    app = QApplication([])
    configure_application(app)
    settings = args.output / "settings.json"
    atomic_json(settings, {"locale": "zh-CN", "isaac_root": str(args.isaac_root or "")})
    window = Workbench(
        runs=args.output / "runs", settings=settings, display_hold_s=120, control_mode=False
    )
    window.show()
    results = {
        "status": "RUNNING",
        "method": "QTTEST_REAL_WIDGET_EVENTS_NOT_PHYSICAL_MOUSE_OR_IME_ACCEPTANCE",
        "checks": [],
        "runs": [],
        "test_process_pid": os.getpid(),
    }

    def save():
        atomic_json(args.output / "ui-verification.json", results)

    def wait(predicate, timeout=30):
        deadline = time.monotonic() + timeout
        while not predicate():
            app.processEvents()
            QTest.qWait(50)
            if window.phase_key == "failed" and not window.busy():
                raise RuntimeError("UI_BACKEND_FAILED:" + window.feedback.text())
            if time.monotonic() > deadline:
                raise TimeoutError("UI_CONDITION_TIMEOUT:" + window.phase_key)

    def screenshot(name):
        app.processEvents()
        QTest.qWait(150)
        if not window.grab().save(str(args.output / name)):
            raise RuntimeError("QT_CAPTURE_FAILED")

    def language(locale):
        window.language.setFocus()
        QTest.keyClick(window.language, Qt.Key.Key_Home if locale == "zh-CN" else Qt.Key.Key_End)
        app.processEvents()
        assert window.locale == locale

    def check(name, **detail):
        results["checks"].append(dict(name=name, status="PASS", **detail))
        save()
        print(name, flush=True)

    try:
        wait(window.isVisible)
        window.note.setFocus()
        app.clipboard().setText("小组中文输入 / English")
        QTest.keyClick(window.note, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        assert window.note.text() == "小组中文输入 / English"
        ime_event = QInputMethodEvent()
        ime_event.setCommitString(" · 输入法事件")
        app.sendEvent(window.note, ime_event)
        assert "输入法事件" in window.note.text()
        draft_digest = canonical_digest(window.draft().data())
        language("en")
        assert canonical_digest(window.draft().data()) == draft_digest
        assert window.launch_button.text() == "Start finite trial"
        screenshot("workbench-en.png")
        language("zh-CN")
        assert canonical_digest(window.draft().data()) == draft_digest
        screenshot("workbench-zh.png")
        check("BILINGUAL_DRAFT_PRESERVATION_AND_UNICODE_PASTE")
        window.orders.item(0, 1).setText("NaN")
        QTest.mouseClick(window.check_button, Qt.MouseButton.LeftButton)
        assert "RELEASE_TIME" in window.feedback.text()
        language("en")
        assert (
            "finite numbers" in window.feedback.text() and "释放时间" not in window.feedback.text()
        )
        language("zh-CN")
        assert window.run_directory is None
        window.orders.item(0, 1).setText("0")
        window.count.setValue(2)
        window.orders.item(1, 1).setText("0.5")
        assert window.draft().release_times == (0.0, 0.5)
        window.count.setValue(1)
        check("INPUT_REJECTION_AND_TWO_PRODUCT_DRAFT")
        QTest.mouseClick(
            window.arm, Qt.MouseButton.LeftButton, pos=QPoint(10, window.arm.height() // 2)
        )
        assert window.arm.isChecked() and window.launch_button.isEnabled()
        QTest.mouseClick(window.launch_button, Qt.MouseButton.LeftButton)
        assert window.audit.text() == window.t("not_run") and window.source_version.text() == "—"
        wait(lambda: window.run_directory is not None)
        cpu_dir = window.run_directory
        wait(lambda: window.last_live is not None, 300)
        assert window.feedback_key != "submitted"
        first_id, request_id = window.run_id, window.request_id
        draft_digest = canonical_digest(window.draft().data())
        language("en")
        assert window.run_id == first_id and window.request_id == request_id
        assert canonical_digest(window.draft().data()) == draft_digest
        assert not window.launch_button.isEnabled()
        wait(lambda: not window.busy(), 300)
        assert window.phase_key == "finished", read_json(cpu_dir / "report.json")
        screenshot("cpu-checkpoint-en.png")
        report = read_json(cpu_dir / "report.json")
        assert "online-journal.json" in window.reason_details.toPlainText()
        assert "Predecessor actions" in window.reason_details.toPlainText()
        window.request_location()
        assert window.display_key == "location_unavailable"
        check("B1_CPU_ACTUAL_WAIT_REASON_AND_LOCATION_UNAVAILABLE")
        results["runs"].append(
            dict(
                backend="light",
                directory=cpu_dir.name,
                run_id=first_id,
                manifest=report["manifest"],
                closed=report["closed"],
            )
        )
        check("REAL_CPU_PREFIX_AND_LIVE_LANGUAGE_SWITCH")
        before = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in cpu_dir.iterdir()
            if p.is_file()
        }
        assert window.load_history(cpu_dir)
        language("zh-CN")
        screenshot("history-zh.png")
        after = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in cpu_dir.iterdir()
            if p.is_file()
        }
        assert before == after
        check("READ_ONLY_HISTORY_AND_LANGUAGE_SWITCH", preserved_files=len(before))
        assert window.history_record["integrity"] == "integrity_checked"
        assert "前置动作" in window.reason_details.toPlainText()
        language("en")
        assert "Predecessor actions" in window.reason_details.toPlainText()
        for kind in ("damaged", "missing", "old-identity"):
            copy = args.output / ("history-" + kind)
            shutil.copytree(cpu_dir, copy)
            if kind == "damaged":
                (copy / "events.jsonl.gz").write_bytes(b"damaged")
            elif kind == "missing":
                (copy / "decisions.jsonl.gz").unlink()
            else:
                receipt = read_json(copy / "process-exit.json")
                atomic_json(copy / "process-exit.json", {**receipt, "run_id": "OLD-RUN"})
            assert not window.load_history(copy)
            assert window.history_record is None and window.evidence_list.count() == 0
        assert window.load_history(cpu_dir)
        check("B1_HISTORY_INTEGRITY_IDENTITY_NEGATIVES_AND_BILINGUAL_REASONS")
        if not args.skip_kit:
            assert args.isaac_root and (args.isaac_root / "python.bat").is_file()
            window.select_mode("isaac")
            QTest.mouseClick(window.launch_button, Qt.MouseButton.LeftButton)
            kit_dir = window.run_directory
            wait(lambda: window.phase_key == "checkpoint", 420)
            wait(lambda: window.scene_host.hwnd is not None, 20)
            layout = window.scene_host.measure()
            assert layout["child_of_main"] and layout["contained_in_host"]
            assert layout["native_root"] == layout["main_hwnd"]
            assert layout["visible"]
            original_size = window.size()
            window.resize(original_size.width() - 140, original_size.height() - 60)
            QTest.qWait(600)
            app.processEvents()
            resized = window.scene_host.measure()
            assert resized["child_of_main"] and resized["contained_in_host"]
            assert resized["scene_window_physical"] != layout["scene_window_physical"]
            window.showMinimized()
            QTest.qWait(300)
            assert window.isMinimized()
            window.showNormal()
            window.resize(original_size)
            QTest.qWait(500)
            app.processEvents()
            restored = window.scene_host.measure()
            atomic_json(
                kit_dir / "embedded-restoration-diagnostic.json",
                dict(
                    initial=layout,
                    resized=resized,
                    restored=restored,
                ),
            )
            assert restored["contained_in_host"] and restored["visible"]
            atomic_json(
                kit_dir / "embedded-window-verification.json",
                dict(
                    initial=layout,
                    resized=resized,
                    restored=restored,
                    minimization="QT_MAIN_WINDOW_MINIMIZED_AND_RESTORED",
                    owner_interaction="NOT_TESTED_BY_PHYSICAL_INPUT",
                ),
            )
            check("EMBEDDED_NATIVE_CHILD_RESIZE_AND_MINIMIZE", layout=restored)
            assert window.run_id != first_id
            assert window.input_group.isEnabled() and window.launch_button.isEnabled()
            assert window.launch_button.text() == window.t("restart_display")
            original_request = (kit_dir / "request.json").read_bytes()
            original_config = (kit_dir / "configuration.json").read_bytes()
            window.count.setValue(2)
            window.orders.item(1, 1).setText("0.5")
            window.note.setText("下一次试跑 / Next trial")
            assert window.draft().products == 2
            window.count.setValue(1)
            window.orders.item(0, 1).setText("0.25")
            assert original_request == (kit_dir / "request.json").read_bytes()
            assert original_config == (kit_dir / "configuration.json").read_bytes()
            check("CHECKPOINT_NEXT_DRAFT_EDITABLE_CURRENT_INPUT_AND_CONFIG_UNCHANGED")
            wait(lambda: (kit_dir / "view-state.json").is_file())
            rendered = read_json(kit_dir / "view-state.json")
            assert rendered["fill_frame"] is True
            assert all(
                abs(a - b) <= 8
                for a, b in zip(
                    rendered["render_resolution"],
                    (rendered["ui_viewport_width"], rendered["ui_viewport_height"]),
                )
            )
            check("REAL_KIT_RENDER_RESOLUTION_AUTO_FILLS_CURRENT_EMBEDDED_FRAME", readback=rendered)
            assert abs(rendered["ui_viewport_width"] - rendered["ui_main_width"]) <= 3
            assert abs(rendered["ui_viewport_height"] - rendered["ui_main_height"]) <= 3
            draft_before = canonical_digest(window.draft().data())
            run_before, request_before = window.run_id, window.request_id
            locations = []
            for entity_id in ("PRODUCT-1", "P1", "PRODUCT-1.ST-T.12.DELIVER-1", "FORK-01"):
                window.entity.setCurrentText(entity_id)
                window.right_scroll.ensureWidgetVisible(window.locate_button)
                QTest.mouseClick(window.locate_button, Qt.MouseButton.LeftButton)
                wait(lambda: window.display_key == "location_confirmed", 30)
                location = read_json(kit_dir / "location-confirmation.json")
                assert location["accepted"] is True and location["paths"]
                assert location["entity_id"] == entity_id
                assert location["usd_before_sha256"] == location["usd_after_sha256"]
                assert location["state_before_sha256"] == location["state_after_sha256"]
                locations.append(location)
            atomic_json(kit_dir / "verified-location-positive.json", locations)
            language("zh-CN")
            assert "已选择真实USD" in window.display_status.text()
            language("en")
            assert "Real USD" in window.display_status.text()
            assert window.run_id == run_before and window.request_id == request_before
            assert canonical_digest(window.draft().data()) == draft_before
            screenshot("b1-kit-location-en.png")
            language("zh-CN")
            screenshot("b1-kit-location-zh.png")
            language("en")
            window.entity.setCurrentText("B1-UNMAPPED-ENTITY")
            QTest.mouseClick(window.locate_button, Qt.MouseButton.LeftButton)
            wait(lambda: window.display_key == "location_rejected", 30)
            rejected = read_json(kit_dir / "location-confirmation.json")
            assert rejected["accepted"] is False and rejected["paths"] == []
            assert rejected["usd_before_sha256"] == rejected["usd_after_sha256"]
            check(
                "B1_REAL_USD_READONLY_LOCATION_AND_ACTUAL_UNMAPPED_REJECTION",
                positive=locations,
                negative=rejected,
            )
            live_path = kit_dir / "live.json"
            window.timer.stop()
            original_read = read_json
            last = original_read(live_path)
            for kind, update in (
                ("expired", {"published_wall_s": time.time() - 10}),
                ("old-run", {"run_id": "OLD-RUN"}),
                ("old-request", {"request_id": "OLD-REQUEST"}),
                ("source-drift", {"source_version": "0" * 64}),
                ("config-drift", {"config_sha256": "0" * 64}),
            ):

                def injected(path, *args, **kwargs):
                    return (
                        {**last, **update}
                        if Path(path) == live_path
                        else original_read(path, *args, **kwargs)
                    )

                with patch("s19b_desktop.app.read_json", side_effect=injected):
                    window.poll()
                assert window.phase_key == "unknown", kind
                assert window.product_table.item(0, 1).text() == window.t("unknown_value")
                assert not window.camera_button.isEnabled() and not window.locate_button.isEnabled()
                window.last_live = last
                window.last_sequence = last["sequence"]
            for failure in (FileNotFoundError(), ValueError("DAMAGED_JSON")):

                def unavailable(path, *args, **kwargs):
                    if Path(path) == live_path:
                        raise failure
                    return original_read(path, *args, **kwargs)

                with patch("s19b_desktop.app.read_json", side_effect=unavailable):
                    window.poll()
                assert window.phase_key == "unknown"
            window.timer.start(250)
            wait(lambda: window.phase_key == "checkpoint")
            window.inspect_current()
            assert window.evidence_dialog.isVisible()
            assert window.run_id == run_before and window.request_id == request_before
            window.evidence_dialog.close()
            check(
                "B1_UI_STALE_MISSING_DAMAGED_OLD_IDENTITY_AND_VERSION_REJECTION_AND_LIVE_EVIDENCE"
            )
            language("en")
            screenshot("kit-checkpoint-en.png")
            if os.name == "nt":
                screen = QApplication.primaryScreen()
                screen.grabWindow(0).save(str(args.output / "desktop-kit-and-workbench.png"))
            window.camera.setCurrentText("Fork")
            QTest.mouseClick(window.camera_button, Qt.MouseButton.LeftButton)
            wait(lambda: (kit_dir / "view-confirmation.json").is_file(), 30)
            ack = read_json(kit_dir / "view-confirmation.json")
            assert ack["run_id"] == window.run_id and ack["preset_source"] == "/World/Cameras/Fork"
            assert (
                ack["camera_path"] == "/S19B/ReviewCamera" and ack["view_matrix_max_error"] < 1e-4
            )
            wait(lambda: (kit_dir / "view-state.json").is_file())
            QTest.qWait(300)
            before_view = read_json(kit_dir / "view-state.json")
            import ctypes
            from ctypes import wintypes

            native = ctypes.WinDLL("user32", use_last_error=True)
            native.GetWindowThreadProcessId.argtypes = [
                wintypes.HWND,
                ctypes.POINTER(wintypes.DWORD),
            ]
            native.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
            native.SetForegroundWindow.argtypes = [wintypes.HWND]
            native.SetFocus.argtypes = [wintypes.HWND]
            native.SetFocus.restype = wintypes.HWND
            current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
            kit_thread = native.GetWindowThreadProcessId(window.scene_host.hwnd, None)
            assert native.AttachThreadInput(current_thread, kit_thread, True)
            try:
                native.SetForegroundWindow(int(window.winId()))
                native.SetFocus(window.scene_host.hwnd)
            finally:
                native.AttachThreadInput(current_thread, kit_thread, False)
            QTest.qWait(300)
            app.processEvents()
            QApplication.primaryScreen().grabWindow(int(window.winId())).save(
                str(args.output / "embedded-main-native.png")
            )
            QApplication.primaryScreen().grabWindow(window.scene_host.hwnd).save(
                str(args.output / "embedded-kit-native.png")
            )
            native.PostMessageW.argtypes = [
                wintypes.HWND,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            ]
            bounds = window.scene_host.measure()["scene_window_physical"]
            cx, cy = (bounds[2] - bounds[0]) // 2, (bounds[3] - bounds[1]) // 2
            assert native.PostMessageW(window.scene_host.hwnd, 0x0200, 0, cx | (cy << 16))
            assert native.PostMessageW(
                window.scene_host.hwnd,
                0x020A,
                120 << 16,
                (bounds[0] + cx) | ((bounds[1] + cy) << 16),
            )
            wait(
                lambda: (
                    read_json(kit_dir / "view-state.json")["view_matrix"]
                    != before_view["view_matrix"]
                ),
                15,
            )
            after_view = read_json(kit_dir / "view-state.json")
            assert after_view["run_id"] == window.run_id
            atomic_json(
                kit_dir / "embedded-input-verification.json",
                dict(
                    method="SYNTHETIC_WM_MOUSEMOVE_AND_WM_MOUSEWHEEL_TO_OWN_KIT_CHILD",
                    before=before_view,
                    after=after_view,
                    physical_operator_acceptance="NOT_PERFORMED",
                ),
            )
            check("EMBEDDED_NATIVE_WHEEL_CHANGED_REAL_RENDERED_CAMERA")
            old_id = window.run_id
            window.orders.item(0, 1).setText("0.25")
            QTest.mouseClick(window.launch_button, Qt.MouseButton.LeftButton)
            assert window.pending_launch is not None and not window.launch_button.isEnabled()
            wait(lambda: window.run_id != old_id, 120)
            next_dir = window.run_directory
            assert read_json(next_dir / "request.json")["draft"]["release_times"] == [0.25]
            assert original_request == (kit_dir / "request.json").read_bytes()
            report = read_json(kit_dir / "report.json")
            exit_receipt = read_json(kit_dir / "process-exit.json")
            assert exit_receipt["exit_code"] == 0 and exit_receipt["exit_status"] == "NormalExit"
            assert read_json(kit_dir / "window-layout.json")["child_of_main"] is True
            results["runs"].append(
                dict(
                    backend="isaac",
                    directory=kit_dir.name,
                    run_id=old_id,
                    manifest=report["manifest"],
                    closed=report["closed"],
                    camera_confirmation=ack,
                    window_layout=read_json(kit_dir / "window-layout.json")
                    if (kit_dir / "window-layout.json").is_file()
                    else None,
                )
            )
            check("VISIBLE_REAL_KIT_PREFIX_CAMERA_AND_CONFIRMED_EXIT")
            wait(lambda: window.phase_key == "checkpoint", 420)
            assert window.run_id != old_id and window.input_group.isEnabled()
            next_report = read_json(next_dir / "report.json")
            assert (
                next_report["manifest"]["audit"]
                == next_report["manifest"]["decision_audit"]
                == "PASS"
            )
            screenshot("next-trial-dark-zh.png")
            QTest.mouseClick(window.close_scene_button, Qt.MouseButton.LeftButton)
            wait(lambda: not window.busy(), 120)
            assert window.phase_key == "finished" and window.scene_host.hwnd is None
            next_report = read_json(next_dir / "report.json")
            results["runs"].append(
                dict(
                    backend="isaac",
                    directory=next_dir.name,
                    run_id=window.run_id,
                    manifest=next_report["manifest"],
                    closed=next_report["closed"],
                    entry="NEW_DRAFT_AFTER_CONFIRMED_OLD_DISPLAY_EXIT",
                )
            )
            check("NEXT_TRIAL_DISTINCT_IDENTITY_ONLY_AFTER_ACTUAL_OLD_DISPLAY_EXIT")
        results["status"] = "PASS_WITH_DOCUMENTED_LIMITS"
        results["kit_scope"] = (
            "NOT_RUN"
            if args.skip_kit
            else "FINITE_VISIBLE_PREFIX_NOT_COMPLETE_PRODUCTION_CHAIN_OR_B2_CONTROL"
        )
        results["physical_ime_and_owner_task_acceptance"] = "NOT_PERFORMED"
    except Exception as error:
        results["status"] = "FAILED"
        results["error"] = repr(error)
        save()
        if window.busy() and window.phase_key == "checkpoint":
            window.close_display()
            wait(lambda: not window.busy(), 120)
        raise
    finally:
        save()
        if not window.busy():
            window.timer.stop()
            window.close()
            window.deleteLater()
            app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
            app.quit()
    print(json.dumps({"status": results["status"], "checks": len(results["checks"])}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
