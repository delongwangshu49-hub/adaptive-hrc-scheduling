"""CPU regressions for the real smoke script's per-step callback contract."""

import importlib.util
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "isaac_smoke.py"
SPEC = importlib.util.spec_from_file_location("isaac_smoke", SOURCE)
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


class CallbackContractTests(unittest.TestCase):
    def record(self, **updates):
        return {"physics_step": 14, "simulation_time": 14 / 60, "dt": 1 / 60, **updates}

    def check(self, records):
        SMOKE.check_step_callbacks(records, 14, 14 / 60, 1 / 60)

    def test_one_matching_callback_passes(self):
        self.check([self.record()])

    def test_missing_and_duplicate_cannot_cancel(self):
        # Two steps have two records in total, but neither step meets the contract.
        for records in ([], [self.record(), self.record()]):
            with (
                self.subTest(count=len(records)),
                self.assertRaisesRegex(RuntimeError, "exactly one"),
            ):
                self.check(records)

    def test_stale_or_skipped_step_fails(self):
        for step in (13, 15):
            with self.subTest(step=step), self.assertRaisesRegex(RuntimeError, "step mismatch"):
                self.check([self.record(physics_step=step)])

    def test_wrong_or_nonfinite_time_fails(self):
        for value in (13 / 60, 15 / 60, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaisesRegex(RuntimeError, "time mismatch"):
                self.check([self.record(simulation_time=value)])

    def test_wrong_or_nonfinite_dt_fails(self):
        for value in (0, 1 / 30, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaisesRegex(RuntimeError, "callback dt"):
                self.check([self.record(dt=value)])


if __name__ == "__main__":
    unittest.main()
