"""Windows lock recovery and exact producer callback; no E20 completion claim."""

import ast
import hashlib
import io
import json
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

R = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(R / "scripts"), str(R / "desktop/s19b/src")]
import p051_native_telemetry as telemetry  # noqa: E402
from s19b_desktop.model import atomic_json  # noqa: E402


class NativeTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.publisher = telemetry.NativeFramePublisher(self.directory)
        self.old = dict(run_id="P051-TEST", published_monotonic_s=time.monotonic() - 10)

    def test_real_windows_lock_retains_stale_bytes_and_recovers(self):
        if sys.platform != "win32":
            self.skipTest("Windows replacement semantics")
        atomic_json(self.publisher.path, self.old)
        old_bytes = self.publisher.path.read_bytes()
        logs = io.StringIO()
        with redirect_stdout(logs):
            with self.publisher.path.open("rb"):
                for revision in (2, 3):
                    self.assertFalse(self.publisher.publish(dict(self.old, revision=revision)))
                    self.assertEqual(self.publisher.path.read_bytes(), old_bytes)
                    self.assertGreater(time.monotonic() - self.old["published_monotonic_s"], 5)
            self.assertTrue(self.publisher.publish(dict(self.old, revision=4)))
        self.assertEqual(json.loads(self.publisher.path.read_bytes())["revision"], 4)
        records = [json.loads(x) for x in logs.getvalue().splitlines()]
        self.assertEqual(len(records), 2)
        self.assertEqual(records[-1]["skipped_updates"], 2)
        self.assertEqual(self.publisher.skipped, 0)

    def test_first_denial_does_not_invent_a_frame(self):
        with patch.object(telemetry, "atomic_json", side_effect=PermissionError("denied")):
            with redirect_stdout(io.StringIO()):
                self.assertFalse(self.publisher.publish(self.old))
        self.assertFalse(self.publisher.path.exists())

    def test_other_io_failures_propagate(self):
        for error in (OSError("disk full"), ValueError("invalid JSON")):
            with self.subTest(error=error):
                with patch.object(telemetry, "atomic_json", side_effect=error):
                    with self.assertRaises(type(error)):
                        self.publisher.publish(self.old)
        self.assertEqual(self.publisher.skipped, 0)

    def test_only_native_frame_destination_is_used(self):
        with patch.object(telemetry, "atomic_json") as writer:
            self.publisher.publish(self.old)
        writer.assert_called_once_with(self.directory / "p051-native-frame.json", self.old)

    def producer(self, publisher):
        source = ast.parse((R / "scripts/run_s19b_prototype.py").read_text())
        run = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == "run")
        publish = next(
            n for n in run.body if isinstance(n, ast.FunctionDef) and n.name == "publish"
        )
        outer = ast.parse("def factory():\n sequence = 0\n return None\n").body[0]
        outer.body[-1:] = [publish, ast.Return(value=ast.Name(id="publish", ctx=ast.Load()))]
        module = ast.fix_missing_locations(ast.Module(body=[outer], type_ignores=[]))
        (self.directory / "sources.json").write_text("{}")
        self.world = NS(s=NS(running=[], revision=1, time_h=0, completed=[], products=[]))
        context = dict(
            atomic_json=atomic_json,
            output=self.directory,
            native_publisher=publisher,
            request=dict(run_id="P051-TEST", request_id="test", backend="fixture"),
            world=self.world,
            PROTOCOL="fixture",
            digest=lambda _: "fixture",
            config=None,
            time=time,
            hashlib=hashlib,
            control=None,
            reason_fact=lambda _: None,
            policy=NS(journal=[]),
            viewport=NS(
                camera_path="/Camera", resolution=(640, 480), frame_info=dict(frame_number=1)
            ),
            current_display_error=None,
        )
        exec(compile(module, "exact_producer_publish", "exec"), context)
        return context["factory"](), context

    def test_exact_publish_continues_live_progress_after_native_denial(self):
        publish, _ = self.producer(self.publisher)
        with redirect_stdout(io.StringIO()):
            with patch.object(telemetry, "atomic_json", side_effect=PermissionError("denied")):
                publish("RUNNING")
                self.world.s.revision = 2
                self.world.s.time_h = 1
                publish("RUNNING")
            publish("STOPPED")
        live = json.loads((self.directory / "live.json").read_bytes())
        frame = json.loads(self.publisher.path.read_bytes())
        self.assertEqual((live["sequence"], live["revision"], live["time_h"]), (3, 2, 1))
        self.assertEqual(frame["source_state_revision"], 2)
        self.assertEqual(self.publisher.skipped, 0)

    def test_live_write_denial_is_still_fatal(self):
        publish, context = self.producer(self.publisher)
        context["atomic_json"] = lambda *args: (_ for _ in ()).throw(PermissionError("live"))
        with self.assertRaisesRegex(PermissionError, "live"):
            publish("RUNNING")
        self.assertEqual(self.publisher.skipped, 0)

    def test_legacy_callback_has_no_native_write(self):
        publish, _ = self.producer(None)
        publish("RUNNING")
        self.assertFalse(self.publisher.path.exists())


if __name__ == "__main__":
    unittest.main()
