"""Independent zero-clamp, bad-result and cancellation witnesses for P07."""

import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis/p07"))
from adapters import fatigue_polyline  # noqa: E402
from cancellation import compute as cancellation_compute  # noqa: E402
from checks import e20_oracle, fixed_oracle  # noqa: E402


class P07RepairTests(unittest.TestCase):
    def test_recovery_zero_point_and_area_are_exact(self):
        iv = dict(start_h=0, end_h=10, start_f=0.2, end_f=0, rate=0.1, phase="REST", exposure=0.2)
        t, f = fatigue_polyline([iv])
        self.assertEqual(t, [0, 2, 10])
        self.assertEqual(f, [0.2, 0, 0])
        self.assertAlmostEqual(
            sum((b - a) * (x + y) / 2 for a, b, x, y in zip(t, t[1:], f, f[1:])), 0.2
        )
        for phase in ["REST", "OFF_SHIFT"]:
            self.assertEqual(fatigue_polyline([dict(iv, phase=phase)])[0], [0, 2, 10])

    def test_fixed_result_oracle_rejects_wrong_aggregate_and_denominator(self):
        iv = dict(
            person_id="P",
            start_h=0,
            end_h=10,
            start_f=0.2,
            end_f=0,
            rate=0.1,
            phase="REST",
            exposure=0.2,
        )
        person = dict(
            id="P",
            initial_f=0.2,
            recovery_rate=0.1,
            valid_until_h=1000,
            calendar=dict(period_h=24, windows=[dict(start_h=0, end_h=4)]),
        )
        cache = dict(
            unit="TEST",
            configuration=dict(people=[person]),
            final_state=dict(
                time_h=10,
                intervals=[iv],
                humans=[dict(person_id="P", fatigue=0, exposure=0.2, peak=0.2)],
            ),
            analysis=dict(common_horizon=dict(humans=[dict(person_id="P", exposure=0.2)])),
        )
        p = dict(
            person_id="P",
            exposure_F_h=0.2,
            fatigue=0,
            peak_f=0.2,
            presence_h=10,
            availability_h=4,
            presence_labour_cost=None,
            common_exposure_F_h=0.2,
        )
        actual = dict(
            people=[p],
            summary=dict(
                lifecycle_sum_E=0.2,
                lifecycle_max_E=0.2,
                available_person_h=4,
                presence_person_h=10,
                common_window_sum_E=0.2,
                common_window_max_E=0.2,
            ),
        )
        fixed_oracle(cache, actual, {})
        for field in ("lifecycle_sum_E", "available_person_h"):
            bad = deepcopy(actual)
            bad["summary"][field] = -100
            with self.subTest(field=field), self.assertRaises(ValueError):
                fixed_oracle(cache, bad, {})
        bad = deepcopy(actual)
        bad["people"][0]["availability_h"] = -100
        with self.assertRaises(ValueError):
            fixed_oracle(cache, bad, {})

    def test_E20_rejects_changed_time_and_incorrect_source_reference(self):
        products = []
        for i in range(4):
            products.append(
                dict(
                    ready_h=2 if i == 0 else None,
                    received_h=3 if i == 0 else None,
                    accepted_sim_h=0.1,
                    registration_applied_h=0.2,
                    actual_arrival_h=0.2,
                    first_observed_decision_h=0.2,
                    first_adopted_arrangement_h=0.2,
                    first_actual_production_h=1,
                    initial_or_new="DYNAMIC_NEW" if i else "INITIAL",
                )
            )
        reference = dict(products=products, plan_changes=[{} for _ in range(5)])
        e20_oracle(deepcopy(reference), reference)
        for value in [-100, 400, 50]:
            bad = deepcopy(reference)
            bad["products"][0]["first_actual_production_h"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                e20_oracle(bad, reference)

    def test_cancellation_material_units_balance_and_residue(self):
        case = dict(
            run_id="R",
            lots=[dict(id="L", product_id="P", material="STEEL", unit="kg", quantity=2)],
            state=dict(
                time_h=10,
                products=[dict(product_id="P", cancelled=True)],
                lots=[
                    dict(
                        id="L",
                        arrived=True,
                        location="EXTERNAL",
                        available=0,
                        consumed=0,
                        converted=0,
                        scrapped=0,
                        returned=2,
                    )
                ],
                masses=[],
                owners=[],
                running=[],
                reservations=[],
            ),
        )
        cache = dict(
            run_id="R",
            unit="C",
            epoch=0,
            final_state=dict(time_h=10, intervals=[]),
            commands={},
            events=[],
            milestones=[dict(kind="CANCEL", product_id="P", time_h=1)],
            configuration=dict(operations=[], routes=[]),
        )
        result = cancellation_compute(case, cache)
        self.assertEqual(result["materials"][0]["quantity_unit"], "kg")
        self.assertEqual(result["materials"][0]["returned"], 2)
        self.assertEqual(
            result["accounts"][0]["observed_cleanup_status"],
            "NO_RECORDED_MATERIAL_OR_INSTALLED_RESIDUE",
        )
        self.assertIsNone(result["accounts"][0]["presence_labour_cost"])
        bad = deepcopy(case)
        bad["state"]["lots"][0]["returned"] = 3
        with self.assertRaises(ValueError):
            cancellation_compute(bad, cache)


if __name__ == "__main__":
    unittest.main()
