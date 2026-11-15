"""Regressions found by actual embedded Isaac acceptance."""

import ast
import asyncio
import math
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "desktop/s19b/src")]
from p051_scene_link import focus_distance  # noqa: E402

from adaptive_hrc_scheduling.full_schedule import frozen_prefix_unchanged  # noqa: E402


class NativeRepairTests(unittest.TestCase):
    def test_control_fence_preserves_observed_process_exit_and_failure(self):
        from test_p062_limited_repair import host_methods

        namespace = host_methods()
        namespace["control_phase"] = lambda directory, launch: "STOPPED"
        for code, phase in [(0, "EXITED"), (1, "FAILED"), (None, "STOPPING")]:
            host = types.SimpleNamespace(
                worker_exit=code,
                worker=None,
                directory=Path("run"),
                launch={"run_id": "run"},
                client=None,
                phase=phase,
                writable=True,
                snapshot={"writable": False},
            )
            self.assertEqual(namespace["enforce_write_fence"](host), "CONTROL_STOPPED")
            self.assertFalse(host.writable)
            self.assertEqual(host.phase, "STOPPED" if code is None else phase)

    def test_actual_completed_end_replaces_prediction_without_unfreezing_start_or_roles(self):
        old = dict(
            command_id="C",
            start_h=0.034486111111111106,
            end_h=0.5344861111111111,
            operation_id="O",
            roles=[{"person_id": "P"}],
        )
        end = 0.5344861111111108
        events = [
            types.SimpleNamespace(kind="STARTED", command=types.SimpleNamespace(id="C")),
            types.SimpleNamespace(kind="COMPLETED", command_id="C", occurred_sim_h=end),
        ]
        new = dict(old, end_h=end)
        self.assertTrue(frozen_prefix_unchanged([old], [new], events))
        for field, value in [
            ("end_h", end + 1),
            ("start_h", 0),
            ("operation_id", "OTHER"),
            ("roles", []),
        ]:
            with self.subTest(field=field):
                self.assertFalse(
                    frozen_prefix_unchanged([old], [dict(new, **{field: value})], events)
                )
        self.assertFalse(frozen_prefix_unchanged([old], [], events))
        self.assertFalse(frozen_prefix_unchanged([old], [new], events[:1]))

    def test_focus_sphere_fits_narrow_portrait_and_wide_rendered_frusta(self):
        for aspect in [0.5, 1, 16 / 9, 3.4]:
            radius = 1.5
            distance = focus_distance(radius * 2, 50, 20.955, 15.2908, aspect)
            # Project sampled sphere points; the whole silhouette must stay
            # inside either fitted aperture, including a short wide viewport.
            tx = 20.955 / 100
            ty = min(15.2908 / 100, tx / aspect)
            for angle in range(360):
                a = math.radians(angle)
                offset = radius * math.sin(a)
                depth = distance + radius * math.cos(a)
                self.assertLess(abs(offset / depth), min(tx, ty))
        with self.assertRaisesRegex(ValueError, "CAMERA_PROJECTION_UNAVAILABLE"):
            focus_distance(3, 0, 20, 15, 2)

    def capture(self, clock):
        tree = ast.parse((ROOT / "scripts/run_s19b_prototype.py").read_text("utf-8-sig"))
        fn = next(
            n
            for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "capture_viewport_complete"
        )
        scope = {"time": types.SimpleNamespace(monotonic=clock)}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), "capture", "exec"), scope)
        return scope[fn.name]

    def test_ready_png_and_viewport_future_still_require_renderer_barrier(self):
        loop = asyncio.new_event_loop()
        self.addCleanup(loop.close)
        asyncio.set_event_loop(loop)
        self.addCleanup(asyncio.set_event_loop, None)
        events = []

        class Capture:
            async def wait_for_result(self):
                events.append("future")

        app = Mock()
        app.update.side_effect = lambda: loop.run_until_complete(asyncio.sleep(0))
        interface, path = Mock(), Mock()
        path.read_bytes.return_value = b"IEND\xaeB`\x82"
        interface.wait_async_capture.side_effect = lambda: events.append("barrier")
        self.capture(lambda: 0)(
            app, Mock(), path, Mock(), lambda *args: Capture(), interface, notify=events.append
        )
        self.assertEqual(
            events, ["REQUESTED", "future", "PNG_COMPLETE", "barrier", "ASYNC_COMPLETE"]
        )
        events.clear()
        interface.wait_async_capture.side_effect = RuntimeError("SDK_CAPTURE_FAILURE")
        with self.assertRaisesRegex(RuntimeError, "SDK_CAPTURE_FAILURE"):
            self.capture(lambda: 0)(
                app, Mock(), path, Mock(), lambda *args: Capture(), interface, notify=events.append
            )
        self.assertNotIn("ASYNC_COMPLETE", events)


if __name__ == "__main__":
    unittest.main()
