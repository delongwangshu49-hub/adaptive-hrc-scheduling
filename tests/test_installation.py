"""S01 installation checks only; no domain or simulator tests."""

import json
import subprocess
import sys
import tempfile
import unittest
from importlib.metadata import distribution


class InstallationTests(unittest.TestCase):
    def test_installed_entry_from_outside_repository(self):
        # -I ignores PYTHONPATH and the current directory; this needs an install.
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-I", "-m", "adaptive_hrc_scheduling"],
                cwd=directory, capture_output=True, text=True, check=True,
            )
        report = json.loads(result.stdout)
        self.assertEqual(report["version"], distribution("adaptive-hrc-scheduling").version)
        self.assertEqual(report["scope"], "installation-only")

    def test_lightweight_package_has_no_runtime_dependencies(self):
        self.assertEqual(distribution("adaptive-hrc-scheduling").requires or [], [])


if __name__ == "__main__":
    unittest.main()
