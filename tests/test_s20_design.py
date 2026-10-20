"""Design integrity, no test execution/leakage, and honest finite-sample analysis."""

import copy
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from s20_design import (  # noqa: E402
    authorize_development,
    fingerprint,
    keyed_uniform,
    load_design,
    paired_summary,
    validate_design,
)


class S20DesignTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.design = load_design()

    def altered(self, mutate, reason):
        design = copy.deepcopy(self.design)
        mutate(*design)
        with self.assertRaisesRegex(ValueError, reason):
            validate_design(*design)

    def test_registered_design_and_all_methods(self):
        result = validate_design(*self.design)
        self.assertEqual(result["splits"], {"dev": 4, "tune": 4, "test": 64})

    def test_no_formal_execution(self):
        self.altered(
            lambda c, m, s: m.update(formal_execution_enabled=True), "FORMAL_EXECUTION_LOCK"
        )
        for row in self.design[1]["rows"]:
            if row["split"] != "dev":
                with self.assertRaisesRegex(ValueError, "DEV_ONLY"):
                    authorize_development(row)

    def test_no_configuration_tampering(self):
        self.altered(lambda c, m, s: c["configurations"][0].update(cap=0.9), "CATALOG_DIGEST")

    def test_rehashed_bad_configuration_still_rejected(self):
        def mutate(c, m, s):
            c["configurations"][0]["cap"] = 0.9
            m["config_catalog_sha256"] = fingerprint(c)

        self.altered(mutate, "CONFIGURATION_BINDING")

    def test_source_drift_rejected(self):
        def mutate(c, m, s):
            s["files"]["scripts/build_simulation_production.py"] = "0" * 64
            m["source_catalog_sha256"] = fingerprint(s)

        self.altered(mutate, "SOURCE_DIGEST")

    def test_source_manifest_cannot_silently_drop_files(self):
        self.altered(lambda c, m, s: s["files"].clear(), "SOURCE_CATALOG_DIGEST")

    def test_duplicate_or_incomplete_pair_rejected(self):
        self.altered(lambda c, m, s: m["rows"].append(m["rows"][0]), "DUPLICATE_RUN")
        self.altered(lambda c, m, s: m["rows"].pop(), "INCOMPLETE_METHOD_PAIR")

    def test_test_case_cannot_be_renamed_development(self):
        def mutate(c, m, s):
            row = m["rows"][4]
            row["split"] = "dev"
            row["execution_authorization"] = "DEVELOPMENT_ONLY"

        self.altered(mutate, "SPLIT_BUDGET")

    def test_same_numerical_case_across_splits_rejected(self):
        def mutate(c, m, s):
            row = copy.deepcopy(m["rows"][0])
            row.update(
                id="RENAMED",
                pair_id="RENAMED",
                split="tune",
                execution_authorization="NOT_AUTHORIZED",
            )
            row["scenario"]["id"] = "RENAMED-SCENARIO"
            row["instance_identity"] = fingerprint(
                {"config": row["config_sha256"], "scenario": row["scenario"]}
            )
            m["rows"].append(row)

        self.altered(mutate, "SPLIT_LEAKAGE")

    def test_unequal_allowance_rejected(self):
        self.altered(lambda c, m, s: m["rows"][0].update(budget_id="MAIN"), "SPLIT_BUDGET")

    def test_keyed_stream_is_order_independent_and_separated(self):
        a = keyed_uniform("s", "missing", "e1", 2)
        keyed_uniform("s", "missing", "e2", 999)
        self.assertEqual(a, keyed_uniform("s", "missing", "e1", 2))
        self.assertNotEqual(a, keyed_uniform("s", "noise", "e1", 2))
        self.assertNotEqual(a, keyed_uniform("t", "missing", "e1", 2))
        self.assertTrue(0 <= a < 1)

    def test_finite_analysis_hand_calculation(self):
        rows = [
            dict(
                pair_id=str(i),
                left=dict(status="VALID", value=a),
                right=dict(status="VALID", value=b),
            )
            for i, (a, b) in enumerate(((2, 1), (4, 6), (8, 2)))
        ]
        result = paired_summary(rows)
        self.assertEqual(result["paired_mean"], 5 / 3)
        self.assertEqual((result["paired_min"], result["paired_max"]), (-2, 6))
        self.assertIsNone(result["confidence_interval"])

    def test_failures_censoring_and_missing_never_become_zero(self):
        rows = [
            dict(
                pair_id=str(i),
                left=dict(status=s, value=None),
                right=dict(status="VALID", value=10),
            )
            for i, s in enumerate(("FAILED", "MISSING", "CENSORED"))
        ]
        result = paired_summary(rows)
        self.assertEqual(result["planned_pairs"], 3)
        self.assertEqual(result["valid_pairs"], 0)
        self.assertIsNone(result["paired_mean"])
        self.assertEqual(result["statuses"]["left:CENSORED"], 1)

    def test_nonfinite_metrics_and_duplicate_analysis_pair_rejected(self):
        row = dict(
            pair_id="p",
            left=dict(status="VALID", value=math.nan),
            right=dict(status="VALID", value=1),
        )
        with self.assertRaisesRegex(ValueError, "NONFINITE_METRIC"):
            paired_summary([row])
        row["left"]["value"] = 2
        with self.assertRaisesRegex(ValueError, "DUPLICATE_ANALYSIS_PAIR"):
            paired_summary([row, row])


if __name__ == "__main__":
    unittest.main()
