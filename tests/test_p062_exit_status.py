"""A native Kit crash must not become saved success through a zero batch code."""

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "desktop/p051/src"), str(ROOT / "desktop/s19b/src")]
from p051_desktop.exit_status import completion_status  # noqa: E402


class CompletionStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.launch = dict(run_id="RUN", request_id="REQ", session={"spec": {}})
        self.final = dict(
            run_id="RUN", epoch=0, phase="STOPPED", save_status="COMPLETE", audit_status="PASS"
        )

    def write(self, name, value):
        p = self.root / name
        p.parent.mkdir(exist_ok=True)
        p.write_text(json.dumps(value), encoding="utf8")

    def valid(self):
        self.write(
            "report.json", dict(self.launch, status="PASS", closed=True, session_final=self.final)
        )
        self.write("control-state.json", dict(self.launch, phase="STOPPED"))
        self.write("session/final-commit.json", dict(final=self.final))

    def test_zero_without_report_is_incomplete(self):
        self.assertEqual(completion_status(self.root, self.launch, 0)["status"], "INCOMPLETE")

    def test_saved_terminal_and_matching_identity_are_required(self):
        self.valid()
        self.assertEqual(
            completion_status(self.root, self.launch, 0)["status"], "SAVED_COMPLETION_RECORDED"
        )
        self.write("control-state.json", dict(self.launch, phase="RUNNING"))
        self.assertEqual(
            completion_status(self.root, self.launch, 0)["reason"], "COMPLETION_NOT_TERMINAL"
        )
        self.write("control-state.json", dict(self.launch, phase="STOPPED", run_id="OTHER"))
        self.assertEqual(
            completion_status(self.root, self.launch, 0)["reason"], "COMPLETION_IDENTITY"
        )

    def test_missing_or_mismatched_final_never_counts_as_saved(self):
        self.valid()
        self.write("session/final-commit.json", dict(final=dict(self.final, save_status="UNKNOWN")))
        self.assertEqual(
            completion_status(self.root, self.launch, 0)["reason"], "COMPLETION_FINAL_MISMATCH"
        )
        self.assertEqual(completion_status(self.root, self.launch, 1)["reason"], "LAUNCHER_NONZERO")

    def test_corrupt_summary_fails_closed(self):
        self.valid()
        self.write("report.json", [])
        self.assertEqual(
            completion_status(self.root, self.launch, 0)["reason"], "COMPLETION_RECORD_SHAPE"
        )
        (self.root / "report.json").write_text("{", encoding="utf8")
        self.assertEqual(completion_status(self.root, self.launch, 0)["status"], "INCOMPLETE")

    def test_close_false_missing_or_non_boolean_cannot_be_normal_exit(self):
        self.valid()
        for closed in (False, None, 1, "true"):
            with self.subTest(closed=closed):
                report = dict(self.launch, status="PASS", session_final=self.final)
                if closed is not None:
                    report["closed"] = closed
                self.write("report.json", report)
                self.assertEqual(
                    completion_status(self.root, self.launch, 0)["reason"],
                    "COMPLETION_CLOSE_UNCONFIRMED",
                )

    def native_records(self):
        self.launch["backend"] = "isaac"
        self.valid()
        self.write("request.json", self.launch)
        binding = dict(
            run_id="RUN",
            request_id="REQ",
            launch_id="CURRENT",
            request_sha256=hashlib.sha256((self.root / "request.json").read_bytes()).hexdigest(),
        )
        self.write("worker-launch.json", dict(binding, format="S19B-NATIVE-LAUNCH-1"))
        native = dict(binding, format="S19B-NATIVE-EXIT-1", state="EXITED", pid=123, returncode=0)
        self.write("worker-native-exit.json", native)
        return native

    def test_native_positive_requires_this_launch_and_request_bytes(self):
        self.native_records()
        self.assertEqual(
            completion_status(self.root, self.launch, 0)["status"], "SAVED_COMPLETION_RECORDED"
        )
        with (self.root / "request.json").open("a") as stream:
            stream.write(" ")
        self.assertEqual(
            completion_status(self.root, self.launch, 0)["reason"],
            "COMPLETION_NATIVE_EXIT_UNCONFIRMED",
        )

    def test_native_stale_identity_unknown_and_nonzero_are_rejected(self):
        native = self.native_records()
        for key, value in (
            ("launch_id", "OLD"),
            ("run_id", "OTHER"),
            ("request_id", "OTHER"),
            ("request_sha256", "0" * 64),
            ("state", "RUNNING"),
            ("pid", None),
            ("pid", 0),
            ("returncode", None),
            ("returncode", False),
            ("returncode", 0xC0000005),
        ):
            with self.subTest(key=key, value=value):
                self.write("worker-native-exit.json", dict(native, **{key: value}))
                self.assertEqual(
                    completion_status(self.root, self.launch, 0)["reason"],
                    "COMPLETION_NATIVE_EXIT_UNCONFIRMED",
                )
        (self.root / "worker-native-exit.json").unlink()
        self.assertEqual(completion_status(self.root, self.launch, 0)["status"], "INCOMPLETE")


if __name__ == "__main__":
    unittest.main()
