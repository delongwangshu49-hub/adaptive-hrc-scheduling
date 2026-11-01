"""Capture lifecycle barrier and unchanged original native-close contract."""

import ast
import hashlib
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts/run_s19b_prototype.py"


def load_capture(clock):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
    function = next(
        x
        for x in tree.body
        if isinstance(x, ast.FunctionDef) and x.name == "capture_swapchain_complete"
    )
    namespace = {"time": types.SimpleNamespace(monotonic=clock)}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(SOURCE), "exec"), namespace)
    return namespace["capture_swapchain_complete"]


class CaptureCompletionTests(unittest.TestCase):
    def test_existing_complete_png_does_not_skip_SDK_completion_barrier(self):
        capture = load_capture(lambda: 0)
        path = Mock()
        path.read_bytes.return_value = b"imageIEND\xaeB`\x82"
        events = []
        app = Mock()
        app.update.side_effect = lambda: events.append("frame")
        interface = Mock()
        interface.capture_next_frame_swapchain.side_effect = lambda name: events.append("request")
        interface.wait_async_capture.side_effect = lambda: events.append("barrier")
        capture(app, lambda: events.append("fit"), path, interface, notify=events.append)
        self.assertEqual(
            events,
            ["REQUESTED", "request", "fit", "frame", "PNG_COMPLETE", "barrier", "ASYNC_COMPLETE"],
        )
        interface.wait_async_capture.assert_called_once_with()

    def test_missing_and_temporarily_locked_png_keep_pumping_before_barrier(self):
        capture = load_capture(lambda: 0)
        path = Mock()
        path.read_bytes.side_effect = [FileNotFoundError(), PermissionError(), b"IEND\xaeB`\x82"]
        app, interface, fit = Mock(), Mock(), Mock()
        capture(app, fit, path, interface)
        self.assertEqual(app.update.call_count, 3)
        self.assertEqual(fit.call_count, 3)
        interface.wait_async_capture.assert_called_once_with()

    def test_incomplete_png_timeout_preserves_failure_and_never_claims_async_complete(self):
        capture = load_capture(Mock(side_effect=[0, 0, 31]))
        path, interface = Mock(), Mock()
        path.read_bytes.return_value = b"partial"
        phases = []
        with self.assertRaisesRegex(RuntimeError, "KIT_SWAPCHAIN_CAPTURE_TIMEOUT"):
            capture(Mock(), Mock(), path, interface, notify=phases.append)
        interface.wait_async_capture.assert_not_called()
        self.assertEqual(phases, ["REQUESTED"])

    def test_SDK_barrier_exception_is_preserved_without_completion_receipt(self):
        capture = load_capture(lambda: 0)
        path, interface = Mock(), Mock()
        path.read_bytes.return_value = b"IEND\xaeB`\x82"
        error = RuntimeError("capture driver refused completion")
        interface.wait_async_capture.side_effect = error
        phases = []
        with self.assertRaises(RuntimeError) as caught:
            capture(Mock(), Mock(), path, interface, notify=phases.append)
        self.assertIs(caught.exception, error)
        self.assertEqual(phases, ["REQUESTED", "PNG_COMPLETE"])

    def test_original_main_close_native_exit_and_failure_contract_AST_is_unchanged(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
        main = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == "main")
        checksum = hashlib.sha256(ast.dump(main, include_attributes=False).encode()).hexdigest()
        self.assertEqual(
            checksum, "fe09bcaf10d720d4b6075dde63ea60d449e67a02fda2061fe42c44967b09f387"
        )

    def test_capture_helper_has_no_shutdown_exit_or_closed_success_bypass(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
        capture = next(
            x
            for x in tree.body
            if isinstance(x, ast.FunctionDef) and x.name == "capture_swapchain_complete"
        )
        calls = [x.func for x in ast.walk(capture) if isinstance(x, ast.Call)]
        self.assertFalse(
            any(
                isinstance(x, ast.Attribute) and x.attr in ("shutdown", "close", "_exit")
                for x in calls
            )
        )


if __name__ == "__main__":
    unittest.main()
