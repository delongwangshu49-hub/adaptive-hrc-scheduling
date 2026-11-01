"""Exit supervision, terminal write fences and causal measurement boundaries."""

import ast
import hashlib
import json
import os
import sys
import tempfile
import time
import types
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "desktop/p051/src"),
    str(ROOT / "desktop/s19b/src"),
    str(ROOT / "scripts"),
]
import check_p062_canvas_age as age_tool  # noqa: E402
import supervise_s19b as supervisor  # noqa: E402
from p051_desktop.client import Client  # noqa: E402
from p051_desktop.delta import ProjectionDelta  # noqa: E402
from p051_desktop.write_fence import BLOCKED_PHASES, control_phase  # noqa: E402
from s19b_desktop.model import atomic_json, read_json  # noqa: E402
from test_session_lifecycle import setup_session  # noqa: E402

from adaptive_hrc_scheduling.control.production_loop import run  # noqa: E402


class NativeSupervisorTests(unittest.TestCase):
    def test_actual_child_code_and_launch_binding_survive_wrapper_independently(self):
        for code in (0, 7, 0xC0000005) if os.name == "nt" else (0, 7):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                request = root / "request.json"
                atomic_json(request, dict(run_id="RUN", request_id="REQ"))
                atomic_json(
                    root / "worker-launch.json",
                    dict(
                        format="S19B-NATIVE-LAUNCH-1",
                        run_id="RUN",
                        request_id="REQ",
                        launch_id="CURRENT",
                        request_sha256=hashlib.sha256(request.read_bytes()).hexdigest(),
                    ),
                )
                child = root / "child.py"
                child.write_text(
                    f"import ctypes;ctypes.windll.kernel32.ExitProcess({code})"
                    if code == 0xC0000005
                    else f"raise SystemExit({code})",
                    encoding="utf8",
                )
                with patch.object(supervisor, "WORKER", child):
                    self.assertEqual(supervisor.supervise(request, "CURRENT"), int(code != 0))
                receipt = read_json(root / "worker-native-exit.json")
                self.assertEqual(receipt["returncode"] & 0xFFFFFFFF, code)
                self.assertEqual(receipt["state"], "EXITED")
                self.assertEqual(receipt["launch_id"], "CURRENT")
                self.assertGreater(receipt["pid"], 0)
                with self.assertRaisesRegex(ValueError, "NATIVE_LAUNCH_IDENTITY"):
                    supervisor.supervise(request, "OLD")
                self.assertEqual(read_json(root / "worker-native-exit.json"), receipt)


def host_methods():
    """Execute the actual method ASTs with boundary doubles, without a GUI."""
    path = ROOT / "desktop/p051/src/p051_desktop/app.py"
    tree = ast.parse(path.read_text(encoding="utf8"))
    cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == "Workbench")
    methods = [
        x
        for x in cls.body
        if isinstance(x, ast.FunctionDef) and x.name in {"poll", "invoke", "enforce_write_fence"}
    ]
    namespace = dict(
        BLOCKED_PHASES=BLOCKED_PHASES,
        control_phase=control_phase,
        atomic_json=atomic_json,
        read_json=read_json,
        time=time,
        json=json,
    )
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class TerminalFenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.s = setup_session(self.root / "session", run_id="P062-REPAIR-TEST")
        self.s.projection.publish(self.s.world.observe())
        self.client = Client(self.s.output, writable=True)
        self.addCleanup(self.client.schedules.close)
        self.view = self.client.poll()
        self.assertTrue(self.view["writable"])

    def preview(self):
        return self.client.build_request(
            dict(kind="DEVICE_FAIL", target_id="FORK-01", payload=dict(reason="TEST"))
        )

    def stop(self):
        result = run(
            self.s.backend,
            self.s.scenario(),
            session=self.s,
            joint_policy=self.s.policy,
            orderly_stop=lambda world: True,
        )
        self.assertEqual(result.audit.status, "PASS")
        self.assertTrue(self.s.terminal)
        self.assertEqual(self.s.lifecycle.final["phase"], "STOPPED")

    def test_real_fresh_terminal_rejects_previously_reviewed_confirmation(self):
        preview = self.preview()
        self.stop()
        view = self.client.poll()
        self.assertLess(view["source_age_s"], 5)
        self.assertEqual(view["status"], "VERIFIED")
        self.assertFalse(view["writable"])
        self.assertEqual(view["write_block_reason"], "SESSION_TERMINAL")
        with self.assertRaisesRegex(ValueError, "READ_ONLY"):
            self.client.submit(preview)
        self.assertEqual(self.client.journal["sequence"], 0)
        self.assertFalse((self.s.output / "p051-confirmations/inbox").exists())

    def test_prior_unknown_request_and_original_id_are_preserved(self):
        preview = self.preview()
        result = self.client.submit(preview)
        self.stop()
        view = self.client.poll()
        self.assertEqual(result["business"], "UNKNOWN")
        self.assertEqual(view["submitted"][0]["request_id"], preview["request_id"])
        self.assertEqual(self.client.journal["sequence"], 1)
        self.assertEqual(len(list((self.s.output / "p051-confirmations/inbox").glob("*.json"))), 1)
        with self.assertRaisesRegex(ValueError, "DO_NOT_RESUBMIT"):
            self.client.submit(preview)

    def test_terminal_latch_survives_late_frame_or_missing_commit(self):
        self.stop()
        self.assertFalse(self.client.snapshot()["writable"])
        (self.s.output / "final-commit.json").unlink()
        self.client.writable = True
        self.assertFalse(self.client.snapshot()["writable"])
        self.assertFalse(self.client.project_snapshot()["writable"])

    def test_corrupt_or_wrong_identity_final_disables_publication(self):
        from adaptive_hrc_scheduling.contracts.session import digest

        path = self.s.output / "final-commit.json"
        for value in ({}, {"final": []}, {"final": {"run_id": "OTHER", "phase": "STOPPED"}}):
            with self.subTest(value=value):
                atomic_json(path, value)
                self.assertFalse(self.client.snapshot()["writable"])
        for phase in (None, [], {}, "UNRECOGNIZED"):
            atomic_json(
                path,
                dict(
                    final=dict(
                        run_id=self.s.spec["run_id"],
                        epoch=0,
                        run_spec_sha256=digest(self.s.spec),
                        phase=phase,
                    )
                ),
            )
            self.assertFalse(self.client.snapshot()["writable"])
        path.write_text("{", encoding="utf8")
        self.assertFalse(self.client.snapshot()["writable"])

    def test_live_control_stop_fence_is_identity_bound_and_latched(self):
        launch = dict(
            run_id=self.s.spec["run_id"], request_id="REQ", session=dict(spec=self.s.spec)
        )
        atomic_json(self.root / "request.json", launch)
        for phase in ("STOPPING", "STOPPED", "COMPLETED", "FAILED", "STOP_BLOCKED"):
            with self.subTest(phase=phase):
                atomic_json(self.root / "control-state.json", dict(launch, phase=phase))
                c = Client(self.s.output, writable=True)
                try:
                    self.assertFalse(c.poll()["writable"])
                    atomic_json(self.root / "control-state.json", dict(launch, phase="RUNNING"))
                    self.assertFalse(c.snapshot()["writable"])
                finally:
                    c.schedules.close()
        atomic_json(
            self.root / "control-state.json", dict(launch, request_id="OTHER", phase="RUNNING")
        )
        c = Client(self.s.output, writable=True)
        try:
            self.assertFalse(c.poll()["writable"])
            self.assertEqual(c.snapshot()["write_block_reason"], "CONTROL_UNKNOWN")
        finally:
            c.schedules.close()

    def test_running_control_and_normal_submission_remain_available(self):
        launch = dict(
            run_id=self.s.spec["run_id"], request_id="REQ", session=dict(spec=self.s.spec)
        )
        atomic_json(self.root / "request.json", launch)
        atomic_json(self.root / "control-state.json", dict(launch, phase="RUNNING"))
        c = Client(self.s.output, writable=True)
        try:
            self.assertTrue(c.poll()["writable"])
            result = c.submit(
                c.build_request(
                    dict(kind="DEVICE_FAIL", target_id="FORK-01", payload=dict(reason="TEST"))
                )
            )
            self.assertEqual(result["status"], "SUBMITTED")
        finally:
            c.schedules.close()

    def test_malformed_control_phase_cannot_authorize_writes(self):
        launch = dict(
            run_id=self.s.spec["run_id"], request_id="REQ", session=dict(spec=self.s.spec)
        )
        atomic_json(self.root / "request.json", launch)
        for phase in (None, "UNRECOGNIZED", [], {}):
            with self.subTest(phase=phase):
                atomic_json(self.root / "control-state.json", dict(launch, phase=phase))
                c = Client(self.s.output, writable=True)
                try:
                    self.assertFalse(c.poll()["writable"])
                    self.assertEqual(c.snapshot()["write_block_reason"], "CONTROL_UNKNOWN")
                finally:
                    c.schedules.close()

    def host(self):
        methods = host_methods()
        events = []
        future = Future()
        future.set_result(dict(self.view))
        host = types.SimpleNamespace(
            worker_exit=None,
            worker=types.SimpleNamespace(poll=lambda: None),
            directory=self.root,
            launch=dict(run_id=self.s.spec["run_id"], request_id="REQ", backend="cpu"),
            client=self.client,
            writable=True,
            snapshot=dict(self.view),
            phase="STOPPED",
            emit=lambda kind, data: events.append((kind, data)),
            delta=ProjectionDelta(),
            future=future,
            outstanding="poll",
            pending_call=None,
            detached=False,
            display_error=None,
            last_projection_key=None,
            audit=None,
            executor=Mock(),
            native=types.SimpleNamespace(hwnd=0, measure=lambda: {}),
            language="en",
            isFullScreen=lambda: False,
            close_when_drained=False,
        )
        for name in ("enforce_write_fence", "invoke", "poll"):
            setattr(host, name, types.MethodType(methods[name], host))
        return host, events

    def test_late_poll_cannot_restore_writable_or_running_state(self):
        host, events = self.host()
        self.stop()
        host.poll()
        self.assertFalse(host.writable)
        self.assertFalse(host.snapshot["writable"])
        self.assertEqual(host.phase, "STOPPED")
        self.assertFalse([x for x in events if x[0] == "error"])
        self.assertTrue(all(not v["writable"] for k, v in events if k == "projection"))

    def test_pending_confirmation_is_rechecked_before_any_publication(self):
        host, events = self.host()
        host.pending_call = ("submit", self.preview())
        self.stop()
        host.poll()
        self.assertIsNone(host.pending_call)
        self.assertFalse(host.snapshot["writable"])
        self.assertTrue(any(k == "error" and "READ_ONLY" in v["error"] for k, v in events))
        self.assertEqual(self.client.journal["sequence"], 0)
        self.assertFalse((self.s.output / "p051-confirmations/inbox").exists())


class CanvasAgeTests(unittest.TestCase):
    def canvas(self, source, sequence):
        return dict(
            event="js_observation",
            t_ns=1_000_000_000,
            observation=dict(
                event="canvas_complete",
                sequence=sequence,
                envelope=dict(sampled_monotonic_s=source),
            ),
        )

    def clock(self):
        return dict(
            event="clock_worker",
            q_send_ns=1_000_000_000,
            q_recv_ns=1_000_000_000,
            offset_worker_minus_qt_lo_ns=0,
            offset_worker_minus_qt_hi_ns=0,
        )

    def test_same_timestamp_future_confirmation_does_not_lower_age(self):
        rows = [
            self.clock(),
            self.canvas(0, 1),
            dict(event="resources", t_ns=1_000_000_000),
            self.canvas(0.5, 2),
            dict(event="resources", t_ns=2_000_000_000),
        ]
        result = age_tool.analyze(rows)
        self.assertEqual([x["sequence"] for x in result["samples"]], [1, 2])
        self.assertEqual(result["source_changed_ties"], 1)
        self.assertAlmostEqual(result["max_understatement_s"], 0.5)
        self.assertAlmostEqual(result["samples"][0]["lo_s"], 1 - 0.015625)
        self.assertTrue(all(x["canvas_line"] < x["resource_line"] for x in result["samples"]))

    def test_no_previous_confirmation_or_clock_produces_no_qualified_samples(self):
        result = age_tool.analyze(
            [self.clock(), dict(event="resources", t_ns=1_000_000_000), self.canvas(0.5, 2)]
        )
        self.assertEqual(result["corrected"]["n"], 0)
        self.assertEqual(result["skipped"]["no_previous_canvas"], 1)
        result = age_tool.analyze([self.canvas(0, 1), dict(event="resources", t_ns=1_000_000_000)])
        self.assertEqual(result["corrected"]["n"], 0)
        self.assertIsNone(result["corrected"]["p95_s"])
        self.assertEqual(result["qualification"], "NO_NEW_PERFORMANCE_PASS")


if __name__ == "__main__":
    unittest.main()
