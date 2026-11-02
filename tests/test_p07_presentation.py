"""Protect material presentation errors: changed totals, censoring and capacity."""

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / "analysis/p07"


def presentation_module():
    sys.path.insert(0, str(ANALYSIS))
    try:
        spec = importlib.util.spec_from_file_location(
            "p07_presentation_data", ANALYSIS / "presentation_data.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(ANALYSIS))


class P07PresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = presentation_module()
        cls.source = ROOT / "results/p07/r3"
        cls.tables = json.loads((ROOT / "results/p07/presentation-r1/tables.json").read_bytes())

    def test_actual_tables_pass_and_changed_exposure_is_rejected(self):
        self.assertEqual(self.module.validate_tables(self.tables, self.source)["status"], "PASS")
        bad = copy.deepcopy(self.tables)
        bad["fatigue_windows"][0]["delta_E"] += 1000
        with self.assertRaisesRegex(ValueError, "PRESENTATION_NUMBER"):
            self.module.validate_tables(bad, self.source)

    def test_unreceived_product_cannot_be_replaced_by_zero_receipt(self):
        bad = copy.deepcopy(self.tables)
        urgent = next(row for row in bad["e20_response"] if row["product_id"] == "PRODUCT-4")
        self.assertIsNone(urgent["received_h"])
        self.assertEqual(urgent["tardiness_status"], "LOWER_BOUND_RIGHT_CENSORED")
        urgent["received_h"] = 0.0
        with self.assertRaisesRegex(ValueError, "PRESENTATION_TYPE"):
            self.module.validate_tables(bad, self.source)

    def test_calendar_capacity_keeps_rest_inside_eligible_windows(self):
        actual = self.module.derive(self.source)
        higher = [r for r in actual["activity_decomposition"] if r["unit"] == "H-CPU-EDD"]
        rest = next(row for row in higher if row["phase"] == "REST")
        self.assertAlmostEqual(rest["calendar_eligible_person_h"], 1.25, places=8)
        self.assertAlmostEqual(
            sum(row["calendar_eligible_person_h"] for row in higher),
            rest["calendar_person_h_denominator"],
            places=7,
        )


if __name__ == "__main__":
    unittest.main()
