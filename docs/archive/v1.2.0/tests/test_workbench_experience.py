"""Startup diagnosis, export boundaries and owned helper cancellation."""

import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop/p051/src"))
from p051_desktop.diagnostics import check_startup, prepare_checked_launch  # noqa: E402
from p051_desktop.geometry import gantt_focus, plan  # noqa: E402
from p051_desktop.presentation import interval, selected_lanes  # noqa: E402
from p051_desktop.processes import CancellableProcesses  # noqa: E402


class ExperienceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runs = self.root / "results"

    def fixture(self, portable=False):
        for name in (
            ".venv/Scripts/python.exe",
            "scripts/run_s19b_prototype.py",
            "desktop/p051/web/dist/index.html",
        ):
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("fixture")
        if portable:
            (self.root / "portable-launch.py").write_text("fixture")

    def test_missing_cpu_environment_names_exact_path_and_both_source_envs(self):
        result = check_startup(self.root, self.runs, probe=False)
        self.assertFalse(result["ready"])
        missing = next(x for x in result["checks"] if x["id"] == "CPU_PYTHON")
        self.assertEqual(missing["target"], str(self.root / ".venv/Scripts/python.exe"))
        self.assertIn("uv sync --locked", missing["fix"])
        self.assertIn("desktop/p051", missing["fix"])

    def test_portable_repair_does_not_instruct_user_to_build_source(self):
        self.fixture(True)
        (self.root / ".venv/Scripts/python.exe").unlink()
        result = check_startup(self.root, self.runs, probe=False)
        missing = next(x for x in result["checks"] if x["id"] == "CPU_PYTHON")
        self.assertIn("ZIP", missing["fix"])
        self.assertNotIn("uv sync", missing["fix"])

    def test_cpu_has_no_isaac_dependency_and_allows_unicode_results(self):
        self.fixture()
        result = check_startup(self.root, self.root / "中文 结果", probe=False)
        self.assertTrue(result["ready"])
        self.assertNotIn("ISAAC_61", [x["id"] for x in result["checks"]])
        self.assertEqual(list((self.root / "中文 结果").iterdir()), [])

    def test_kit_reports_missing_install_and_non_ascii_path(self):
        self.fixture()
        result = check_startup(
            self.root,
            self.root / "中文",
            "isaac",
            self.root / "missing",
            self.root / "ps",
            probe=False,
        )
        failed = {x["id"] for x in result["checks"] if x["status"] == "FAIL"}
        self.assertTrue({"ISAAC_61", "POWERSHELL_7", "KIT_ASCII_RESULTS"}.issubset(failed))

    def test_unwritable_result_target_is_explained(self):
        self.fixture()
        self.runs.write_text("not a directory")
        result = check_startup(self.root, self.runs, probe=False)
        self.assertEqual(
            next(x for x in result["checks"] if x["id"] == "RESULTS_WRITABLE")["status"], "FAIL"
        )

    def test_import_failure_is_not_reported_ready(self):
        self.fixture()
        with patch(
            "p051_desktop.diagnostics.subprocess.run",
            return_value=subprocess.CompletedProcess([], 1, "", "missing dependency"),
        ) as run:
            result = check_startup(self.root, self.runs)
        self.assertFalse(result["ready"])
        self.assertIn("missing dependency", result["checks"][-1]["fix"])
        self.assertEqual(run.call_args.kwargs["cwd"], self.root)
        self.assertEqual(run.call_args.args[0][0], str(self.root / ".venv/Scripts/python.exe"))

    def test_missing_runtime_prevents_launch_preparation(self):
        with patch("p051_desktop.client.prepare_launch") as launch:
            with self.assertRaisesRegex(ValueError, "STARTUP_CHECK_FAILED"):
                prepare_checked_launch(self.root, self.runs, {"backend": "light"})
            launch.assert_not_called()

    def test_gantt_focus_widens_time_plot_without_changing_dual_layout(self):
        before = plan(1366, 768)
        focus = gantt_focus(1366, 768)
        self.assertGreater(focus.plots[1].width, before.plots[1].width * 2)
        self.assertEqual(plan(1366, 768), before)
        self.assertTrue(gantt_focus(1280, 720, form_open=True).geometry_admissible)

    def test_export_uses_original_rows_and_rejects_unknown_ids(self):
        row = dict(row_id="a", start_h=1, end_h=2, schedule_state="ACTUAL")
        selected = selected_lanes(
            {"rows": [row]}, {"lanes": [{"name": "name", "row_ids": ["a", "fake"]}]}
        )
        self.assertEqual(selected, [("name", [row])])
        self.assertIs(selected[0][1][0], row)
        self.assertIsNone(interval({"start_h": 2}))
        self.assertEqual(interval({"start_h": 2, "end_h": 2.001}), (2, 2.001))

    def test_filtered_csv_selection_not_silently_truncated_at_100(self):
        rows = [dict(row_id=str(i)) for i in range(120)]
        lanes = [dict(name=str(i), row_ids=[str(i)]) for i in range(120)]
        self.assertEqual(len(selected_lanes({"rows": rows}, {"lanes": lanes})), 120)

    def test_owned_helper_can_be_cancelled_and_cannot_restart(self):
        runner = CancellableProcesses()
        self.addCleanup(runner.close)
        errors = []

        def run():
            try:
                runner.run(
                    [sys.executable, "-c", "import time;time.sleep(30)"],
                    capture_output=True,
                    timeout=40,
                )
            except RuntimeError as exc:
                errors.append(str(exc))

        thread = threading.Thread(target=run)
        thread.start()
        deadline = time.monotonic() + 5
        while not runner.children and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(runner.children)
        runner.close()
        thread.join(7)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, ["READ_ONLY_CHECK_CANCELLED"])
        with self.assertRaisesRegex(RuntimeError, "CANCELLED"):
            runner.run([sys.executable, "-c", "print('must not run')"])

    def test_check_serializes_for_ui_report(self):
        self.fixture()
        self.assertEqual(
            json.loads(json.dumps(check_startup(self.root, self.runs, probe=False)))["version"],
            "1.2.0",
        )


if __name__ == "__main__":
    unittest.main()
