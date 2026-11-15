"""Black-box fault tests. Fixtures and reports stay in the specified work directory."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

TOOL = Path(__file__).with_name("Test-HRCWorkbench.ps1")
PWSH = Path("C:/Program Files/PowerShell/7/pwsh.exe")
WORK = Path(os.environ.get("HRC_DIAG_TEST_ROOT", str(TOOL.parents[2] / ".local/diagnostic-tests")))
RESOURCE_FILES = (
    "scripts/run_s19b_prototype.py",
    "scripts/build_simulation_production.py",
    "scripts/build_production_contracts.py",
    "scripts/build_logistics_contracts.py",
    "scripts/build_building_contracts.py",
    "desktop/p051/src/p051_desktop/app.py",
    "desktop/s19b/src/s19b_desktop/control.py",
    "src/adaptive_hrc_scheduling/__init__.py",
    "docs/model/steel_process.tsv",
    "docs/model/steel_edges.tsv",
    "examples/building_contracts/configuration.json",
    ".venv/Scripts/python.exe",
)


def write(root, name, content="fixture"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.case = WORK / (self._testMethodName + "-" + uuid.uuid4().hex[:8])
        self.case.mkdir(parents=True)

    def fixture(self, portable=False):
        self.root = self.case / "项目 空格 ' quote"
        self.app = self.root / "app" if portable else self.root
        for name in RESOURCE_FILES:
            write(self.app, name)
        write(
            self.app,
            "desktop/p051/web/dist/index.html",
            '<script src="./assets/test.js"></script><script src="qrc:///qtwebchannel/qwebchannel.js"></script>',
        )
        write(self.app, "desktop/p051/web/dist/assets/test.js")
        if portable:
            write(self.root, "HRC-Workbench.exe")
            write(self.app, "portable-launch.py")
            self.manifest()
        else:
            write(self.app, "desktop/p051/.venv/Scripts/python.exe")
            for name in (
                "scripts/run_p051_workbench.py",
                "pyproject.toml",
                "uv.lock",
                "desktop/p051/pyproject.toml",
                "desktop/p051/uv.lock",
            ):
                write(self.app, name)
        return self.root

    def manifest(self):
        lines = []
        for path in sorted(self.root.rglob("*")):
            if path.is_file() and path.name != "PACKAGE-SHA256.txt":
                lines.append(
                    f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(self.root).as_posix()}\n"
                )
        write(self.root, "PACKAGE-SHA256.txt", "".join(lines))

    def run_tool(self, *extra, static=True, root=None, runs=None):
        args = [
            str(PWSH),
            "-NoProfile",
            "-File",
            str(TOOL),
            "-Root",
            str(root or self.root),
            "-RunsDirectory",
            str(runs or self.case / "runs"),
            "-SettingsFile",
            str(self.case / "settings.json"),
            "-OutputDirectory",
            str(self.case / "reports"),
        ]
        if static:
            args.append("-StaticOnly")
        result = subprocess.run(
            [*args, *map(str, extra)], capture_output=True, encoding="utf-8", timeout=80
        )
        (self.case / "console.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
        reports = list((self.case / "reports").glob("*/diagnosis.json"))
        self.assertEqual(len(reports), 1, result.stdout + result.stderr)
        self.report = json.loads(reports[0].read_text(encoding="utf-8-sig"))
        self.assertEqual(result.returncode, self.report["exit_code"])
        self.assertNotIn(
            "diagnostic.incomplete", [x["id"] for x in self.report["checks"]], result.stdout
        )
        return result.returncode

    def check(self, ident):
        return next(x for x in self.report["checks"] if x["id"] == ident)

    def test_static_checks_never_claim_runtime_success(self):
        self.fixture()
        self.assertEqual(self.run_tool(), 2)
        self.assertEqual(self.report["failures"], 0)
        self.assertEqual(self.check("cpu.python.probe")["status"], "WARN")

    def test_missing_cpu_environment_has_exact_path_and_fix(self):
        self.fixture()
        missing = self.app / ".venv/Scripts/python.exe"
        missing.unlink()
        self.assertEqual(self.run_tool(), 1)
        issue = self.check("cpu.python.file")
        self.assertEqual(Path(issue["target"]), missing)
        self.assertIn("uv sync --locked", issue["fix"])
        self.assertEqual(self.check("ui.python.file")["status"], "PASS")

    def test_missing_ui_environment_distinguished(self):
        self.fixture()
        (self.app / "desktop/p051/.venv/Scripts/python.exe").unlink()
        self.assertEqual(self.run_tool(), 1)
        self.assertIn("--project desktop/p051", self.check("ui.python.file")["fix"])

    def test_missing_frontend_asset(self):
        self.fixture()
        (self.app / "desktop/p051/web/dist/assets/test.js").unlink()
        self.assertEqual(self.run_tool(), 1)
        self.assertEqual(self.check("web.asset../assets/test.js")["status"], "FAIL")

    def test_qrc_is_not_a_missing_disk_file(self):
        self.fixture()
        self.run_tool()
        self.assertFalse(any("qrc:" in c["id"] for c in self.report["checks"]))

    def test_invalid_executable_is_not_accepted(self):
        self.fixture()
        self.assertEqual(self.run_tool(static=False), 1)
        self.assertEqual(self.check("cpu.python.launch")["status"], "FAIL")

    def test_truncated_pe_is_not_loaded_by_windows(self):
        self.fixture()
        (self.app / ".venv/Scripts/python.exe").write_bytes(b"MZ" + b"\0" * 98)
        self.assertEqual(self.run_tool(static=False), 1)
        self.assertEqual(
            self.check("cpu.python.launch")["evidence"]["reason"], "INVALID_EXECUTABLE"
        )

    def test_portable_integrity_works_in_unicode_space_quote_path(self):
        self.fixture(portable=True)
        self.assertEqual(self.run_tool(), 2)
        self.assertEqual(self.check("package.integrity")["status"], "PASS")

    def test_portable_missing_file(self):
        self.fixture(portable=True)
        (self.app / "docs/model/steel_edges.tsv").unlink()
        self.assertEqual(self.run_tool(), 1)
        differences = self.check("package.integrity")["evidence"]["differences"]
        self.assertIn({"path": "app/docs/model/steel_edges.tsv", "reason": "MISSING"}, differences)

    def test_portable_tampered_file(self):
        self.fixture(portable=True)
        write(self.app, "docs/model/steel_edges.tsv", "changed")
        self.assertEqual(self.run_tool(), 1)
        self.assertTrue(
            any(
                d["reason"] == "SHA256_MISMATCH"
                for d in self.check("package.integrity")["evidence"]["differences"]
            )
        )

    def test_manifest_path_traversal_rejected(self):
        self.fixture(portable=True)
        with (self.root / "PACKAGE-SHA256.txt").open("a") as stream:
            stream.write("0" * 64 + "  ../outside.txt\n")
        self.assertEqual(self.run_tool(), 1)
        self.assertTrue(
            any(
                d["reason"] == "UNSAFE_OR_DUPLICATE_PATH"
                for d in self.check("package.integrity")["evidence"]["differences"]
            )
        )

    def test_truncated_manifest_rejected(self):
        self.fixture(portable=True)
        path = self.root / "PACKAGE-SHA256.txt"
        path.write_text(path.read_text().splitlines()[0] + "\n")
        self.assertEqual(self.run_tool(), 1)
        self.assertTrue(
            any(
                d["reason"] == "REQUIRED_ENTRY_NOT_LISTED"
                for d in self.check("package.integrity")["evidence"]["differences"]
            )
        )

    def test_missing_portable_manifest(self):
        self.fixture(portable=True)
        (self.root / "PACKAGE-SHA256.txt").unlink()
        self.assertEqual(self.run_tool(), 1)
        self.assertEqual(self.check("package.manifest")["status"], "FAIL")

    def test_bad_settings_json(self):
        self.fixture(portable=True)
        write(self.case, "settings.json", "{broken")
        self.assertEqual(self.run_tool(), 1)
        self.assertEqual(self.check("settings")["status"], "FAIL")

    def test_wrong_settings_type(self):
        self.fixture(portable=True)
        write(self.case, "settings.json", '{"runs":42}')
        self.assertEqual(self.run_tool(), 1)
        self.assertEqual(self.check("settings")["status"], "FAIL")

    def test_output_path_is_a_file(self):
        self.fixture()
        write(self.case, "runs")
        self.assertEqual(self.run_tool(), 1)
        self.assertEqual(self.check("runs.writable")["status"], "FAIL")

    def test_cpu_does_not_require_isaac(self):
        self.fixture(portable=True)
        self.run_tool()
        self.assertEqual(self.check("isaac.not_required")["status"], "INFO")
        self.assertEqual(self.report["failures"], 0)

    def test_isaac_requires_configuration(self):
        self.fixture(portable=True)
        # Default results path inherits this test method's ASCII name; override using settings.
        write(self.case, "settings.json", json.dumps({"isaac": str(self.case / "missing-isaac")}))
        self.assertEqual(self.run_tool("-Backend", "Isaac"), 1)
        self.assertEqual(self.check("isaac.python_bat")["status"], "FAIL")

    def test_isaac_rejects_unicode_results(self):
        self.fixture(portable=True)
        self.assertEqual(self.run_tool("-Backend", "Isaac", runs=self.case / "中文结果"), 1)
        self.assertEqual(self.check("isaac.ascii_runs")["status"], "FAIL")

    def test_cpu_accepts_unicode_results(self):
        self.fixture(portable=True)
        self.assertEqual(self.run_tool(runs=self.case / "中文结果"), 2)
        self.assertEqual(self.check("runs.writable")["status"], "PASS")
        self.assertEqual(self.report["failures"], 0)

    def test_history_is_a_warning_not_proven_current_cause(self):
        self.fixture()
        run = self.case / "runs/old-session"
        write(run, "p051-worker.log", "FileNotFoundError: [WinError 2] 系统找不到指定的文件")
        self.assertEqual(self.run_tool(), 2)
        self.assertEqual(self.check("log.winerror2")["status"], "WARN")
        self.assertEqual(self.report["failures"], 0)

    def test_unknown_user_error_is_not_reported_resolved(self):
        self.fixture()
        self.assertEqual(self.run_tool("-ErrorText", "UNRECOGNIZED_FAILURE_123"), 2)
        self.assertEqual(self.check("error.reported")["status"], "WARN")

    def test_nonzero_worker_receipt_is_not_success(self):
        self.fixture()
        run = self.case / "runs/failed-session"
        write(run, "worker-native-exit.json", '{"returncode":-1,"run_id":"old"}')
        self.assertEqual(self.run_tool(), 2)
        self.assertEqual(self.check("logs.receipt")["status"], "WARN")

    def test_probe_timeout_is_bounded(self):
        self.fixture()
        # A real venv launcher with its original base interpreter, but no copied dependencies.
        original_env = Path(sys.prefix)
        shutil.copy2(Path(sys.executable), self.app / ".venv/Scripts/python.exe")
        shutil.copy2(original_env / "pyvenv.cfg", self.app / ".venv/pyvenv.cfg")
        write(self.app, "scripts/build_simulation_production.py", "import time\ntime.sleep(30)\n")
        self.assertEqual(self.run_tool("-ProbeTimeoutSeconds", "5", static=False), 1)
        self.assertEqual(self.check("cpu.python.launch")["evidence"]["reason"], "TIMEOUT")

    def test_missing_dependency_is_named_after_python_starts(self):
        self.fixture()
        shutil.copy2(Path(sys.executable), self.app / ".venv/Scripts/python.exe")
        shutil.copy2(Path(sys.prefix) / "pyvenv.cfg", self.app / ".venv/pyvenv.cfg")
        self.assertEqual(self.run_tool(static=False), 1)
        self.assertEqual(self.check("cpu.python.python_version")["status"], "PASS")
        issue = self.check("cpu.python.ortools")
        self.assertEqual(issue["status"], "FAIL")
        self.assertEqual(issue["evidence"]["error_type"], "ModuleNotFoundError")
        self.assertIn("ortools", issue["evidence"]["error"])

    def test_interactive_entry_produces_report(self):
        self.fixture()
        result = subprocess.run(
            [str(PWSH), "-NoProfile", "-File", str(TOOL.with_name("Start-Diagnostics.ps1"))],
            input=f"{self.root}\nCPU\n[WinError 2] test\n\n",
            capture_output=True,
            encoding="utf-8",
            timeout=20,
            env={**os.environ, "TEMP": str(self.case), "TMP": str(self.case)},
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        reports = list((self.case / "HRC-Diagnostics").glob("*/diagnosis.json"))
        self.assertEqual(len(reports), 1, result.stdout + result.stderr)
        report = json.loads(reports[0].read_text(encoding="utf-8-sig"))
        self.assertEqual(report["root"], str(self.root))
        self.assertTrue(any(c["id"] == "error.reported" for c in report["checks"]))

    def test_cmd_entry_preserves_failure_exit(self):
        self.fixture()
        # Execute this deliverable's CMD entry, not an alternate development shell.
        result = subprocess.run(
            [
                "cmd.exe",
                "/d",
                "/c",
                str(TOOL.with_name("Run-Diagnostics.cmd")),
                "-Root",
                str(self.root),
                "-StaticOnly",
                "-OutputDirectory",
                str(self.case / "reports"),
            ],
            input=b"\n",
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        reports = list((self.case / "reports").glob("*/diagnosis.json"))
        self.assertEqual(len(reports), 1, result.stdout + result.stderr)

    def test_trace_helper_records_portable_failure(self):
        self.trace_helper_case("portable", "portable-launch.py")

    def test_trace_helper_records_source_failure(self):
        self.trace_helper_case("source", "scripts/run_p051_workbench.py")

    def trace_helper_case(self, mode, entry):
        root = self.case / "取证 空格"
        missing = str(root / "missing-worker.exe")
        write(root, entry, "import subprocess\nsubprocess.run([" + repr(missing) + "])\n")
        log = self.case / "failed-launch.jsonl"
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-X",
                "utf8",
                str(TOOL.with_name("Trace-HRCStartup.py")),
                str(root),
                mode,
                str(log),
            ],
            capture_output=True,
            encoding="utf-8",
            timeout=15,
        )
        self.assertNotEqual(result.returncode, 0)
        record = json.loads(log.read_text(encoding="utf-8").strip())
        self.assertEqual(record["command"], [missing])
        self.assertEqual(Path(record["cwd"]), root)
        self.assertIn("FileNotFoundError", record["traceback"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
