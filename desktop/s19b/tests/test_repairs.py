"""S19B-6 fault boundaries. No Kit or production simulation is started."""

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from s19b_desktop import app as ui  # noqa: E402
from s19b_desktop.model import (  # noqa: E402
    Draft,
    InputError,
    atomic_json,
    canonical_digest,
    read_json,
)
from s19b_desktop.review import (  # noqa: E402
    REQUIRED,
    DisplayRequestError,
    bind_live_bundle,
    data_age,
    display_sequence,
    evidence_status,
    guarded_display,
    history_reason,
    preview_evidence,
    seal_evidence,
    validate_confirmation,
    validate_display_request,
)


class RepairContracts(unittest.TestCase):
    def test_actual_worker_finally_reseals_failed_report(self):
        path = Path(__file__).resolve().parents[3] / "scripts/run_s19b_prototype.py"
        spec = importlib.util.spec_from_file_location("s19b_failure_worker", path)
        worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(worker)
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            request = dict(
                protocol="S19B-PROTOTYPE-1",
                run_id="injected-failure",
                request_id="failure-request",
                backend="light",
                draft=Draft().data(),
                created_at="test",
                display_hold_s=0,
            )
            atomic_json(root / "request.json", request)
            with (
                patch.object(sys, "argv", ["worker", "--request", str(root / "request.json")]),
                patch.object(worker, "run", side_effect=RuntimeError("INJECTED_RUN_FAILURE")),
            ):
                self.assertEqual(worker.main(), 1)
            report = read_json(root / "report.json")
            self.assertEqual(report["status"], "FAILED")
            self.assertTrue(report["closed"])
            self.assertIn("INJECTED_RUN_FAILURE", report["error"])
            self.assertEqual(evidence_status(root, report)[0], "partial_evidence")

    def test_display_fault_does_not_swallow_production_guard(self):
        errors = []
        for error in (OSError("sharing"), ValueError("bad JSON"), DisplayRequestError("camera")):
            with patch.object(Path, "read_text", side_effect=error):
                self.assertIsNone(
                    guarded_display(lambda: Path("unused").read_text(), errors.append)
                )
        self.assertEqual(len(errors), 3)
        with self.assertRaisesRegex(RuntimeError, "LOCATION_CHANGED_PRODUCTION_OR_USD"):
            guarded_display(
                lambda: (_ for _ in ()).throw(RuntimeError("LOCATION_CHANGED_PRODUCTION_OR_USD")),
                errors.append,
            )

    def test_recovered_display_first_request_and_old_ack(self):
        request = dict(run_id="r", request_id="q")
        old = dict(**request, epoch=0, sequence=5, action="camera", camera="Overview")
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            atomic_json(root / "view-request.json", old)
            seq = display_sequence(root, request) + 1
            new = dict(old, sequence=seq)
            self.assertEqual(seq, 6)
            validate_display_request(new, request, 5)
            with self.assertRaises(InputError):
                validate_confirmation(dict(old, accepted=True, scope="DISPLAY_ONLY"), new)
            atomic_json(root / "view-confirmation.json", dict(old, run_id="OTHER"))
            with self.assertRaises(InputError):
                display_sequence(root, request)

    def test_large_legacy_journal_preview_and_final_reason(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            row = dict(sequence=1, final_reason="EDD", padding="x" * 100_000)
            final = dict(sequence=222, final_reason="PATH_BLOCKED", failures=[])
            with (root / "online-journal.json").open("w", encoding="utf-8") as stream:
                stream.write("[")
                for _ in range(210):
                    stream.write(json.dumps(row) + ",")
                stream.write(json.dumps(final) + "]")
            self.assertGreater((root / "online-journal.json").stat().st_size, 20_000_000)
            self.assertIn("raw prefix", preview_evidence(root, "online-journal.json"))
            self.assertEqual(history_reason(root)["sequence"], 222)
            for invalid in ('[{"sequence":1},]', '[{"sequence":1}', "[1]", "[] {}"):
                (root / "online-journal.json").write_text(invalid, encoding="utf-8")
                with self.assertRaises(InputError):
                    history_reason(root)

    def test_failed_final_report_and_partial_evidence(self):
        request = dict(run_id="r", request_id="q")
        report = dict(**request, status="FAILED", closed=False)
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            atomic_json(root / "report.json", report)
            seal_evidence(root, request)
            self.assertEqual(evidence_status(root, report)[0], "partial_evidence")
            for key in REQUIRED:
                atomic_json(root / key, report if key == "report.json" else {})
            seal_evidence(root, request)
            report["closed"] = True
            atomic_json(root / "report.json", report)
            seal_evidence(root, request)
            self.assertEqual(evidence_status(root, report)[0], "integrity_checked")
            atomic_json(root / "report.json", dict(report, closed=False))
            with self.assertRaises(InputError):
                evidence_status(root, report)

    def test_monotonic_age_survives_wall_clock_change(self):
        live = dict(published_wall_s=10000, published_monotonic_s=10)
        self.assertEqual(data_age(live, monotonic_now=12), 2)
        with self.assertRaises(InputError):
            data_age(live, monotonic_now=9)
        with self.assertRaises(InputError):
            data_age({"published_wall_s": 10000}, now=100)


class BindingQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.window = ui.Workbench(runs=self.root, settings=self.root / "settings.json")
        self.window.timer.stop()
        self.window.busy = lambda: True
        self.window.arrange_scene = lambda: None
        self.window.poll_display = lambda: None
        self.window.run_directory = self.root
        self.window.run_id, self.window.request_id = "r", "q"
        self.window.submitted_s = time.monotonic()
        self.live = self.fixture(self.root, "r", "q")

    def fixture(self, root, run, request):
        root.mkdir(exist_ok=True)
        config = {"test": "binding"}
        atomic_json(root / "configuration.json", config)
        atomic_json(root / "sources.json", {})
        live = dict(
            protocol="S19B-PROTOTYPE-1",
            run_id=run,
            request_id=request,
            epoch=0,
            sequence=1,
            time_h=0,
            published_wall_s=time.time(),
            published_monotonic_s=time.monotonic(),
            products=[],
            active=[],
            config_sha256=canonical_digest(config),
            source_version=hashlib.sha256((root / "sources.json").read_bytes()).hexdigest(),
            backend="light",
            phase="RUNNING",
        )
        atomic_json(root / "live.json", live)
        atomic_json(
            root / "entity-catalog.json",
            dict(
                run_id=run,
                request_id=request,
                config_sha256=live["config_sha256"],
                entities=[{"id": run}],
            ),
        )
        return live

    def wait(self, predicate):
        deadline = time.monotonic() + 4
        while not predicate():
            self.qt.processEvents()
            if time.monotonic() > deadline:
                self.fail("bounded wait expired")
            time.sleep(0.01)

    def tearDown(self):
        self.window.busy = lambda: False
        self.window.binding_executor.shutdown(wait=True, cancel_futures=True)
        self.window.close()
        self.window.deleteLater()
        self.qt.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.qt.processEvents()
        self.temp.cleanup()

    def test_bad_catalog_remains_unknown_on_repeated_polls(self):
        catalog = self.root / "entity-catalog.json"
        atomic_json(
            catalog,
            dict(
                run_id="OTHER",
                request_id="q",
                config_sha256=self.live["config_sha256"],
                entities=[],
            ),
        )
        for _ in range(3):
            self.window.poll()
            self.wait(lambda: self.window.binding_future.done())
            self.window.poll()
            self.assertIsNone(self.window.bound_version)
            self.assertFalse(self.window.record_current)
            self.assertFalse(self.window.locate_button.isEnabled())
        self.fixture(self.root, "r", "q")
        self.window.poll()
        self.wait(lambda: self.window.binding_future.done())
        self.window.poll()
        self.assertTrue(self.window.record_current)

    def test_slow_old_binding_never_blocks_or_binds_new_run(self):
        gate = threading.Event()

        def slow(directory, live, backend):
            if live["run_id"] == "r":
                gate.wait(2)
            return bind_live_bundle(directory, live, backend)

        with patch.object(ui, "bind_live_bundle", slow):
            began = time.perf_counter()
            self.window.poll()
            self.assertLess(time.perf_counter() - began, 0.25)
            self.assertFalse(self.window.record_current)
            other = self.root / "other"
            self.fixture(other, "new", "new-q")
            self.window.run_directory = other
            self.window.run_id, self.window.request_id = "new", "new-q"
            self.window.poll()
            gate.set()
            self.wait(lambda: self.window.binding_future.done())
            self.window.poll()
            self.assertTrue(self.window.record_current)
            self.assertEqual(self.window.entity_rows, [{"id": "new"}])

    def test_future_timestamp_unknown_disables_controls_without_reraising(self):
        self.window.last_live = dict(self.live, published_monotonic_s=time.monotonic() + 60)
        self.window.record_current = True
        self.window.stop_button.setEnabled(True)
        self.window.mark_unknown("LIVE_CLOCK")
        self.assertFalse(self.window.stop_button.isEnabled())
        self.assertFalse(self.window.record_current)
        self.assertEqual(self.window.age.text(), self.window.t("unknown_value"))

    def test_bad_display_file_does_not_block_control_reconnection(self):
        self.window.detached = True
        self.window.control_request = dict(run_id="r", request_id="q")
        self.window.poll = lambda: None
        atomic_json(self.root / "started.json", dict(run_id="r", request_id="q"))
        with (
            patch.object(ui, "recover", return_value=({"commands": {}, "responses": {}}, [])),
            patch.object(ui, "ProcessWatch"),
            patch.object(ui, "display_sequence", side_effect=InputError("DISPLAY_DAMAGED")),
        ):
            self.window.reconnect()
            self.assertFalse(self.window.detached)
            self.assertEqual(self.window.control_state["commands"], {})
            self.assertFalse(self.window.send_view("camera", camera="Top"))
            self.assertFalse((self.root / "view-request.json").exists())
        self.window.process_watch = None


if __name__ == "__main__":
    unittest.main()
