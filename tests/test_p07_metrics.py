"""Hand calculations and rejecting controls for new offline P07 adapters."""

import sys
import unittest
from copy import deepcopy
from pathlib import Path

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R / "analysis/p07"))
from adapters import (  # noqa: E402 -- repository path bootstrap
    calendar_intersection,
    check_human_interval,
    hours,
    pair_values,
    people_metrics,
    product_metrics,
)
from export import IDENTITY_FIELDS, validate_pair  # noqa: E402
from validate import validate_identity  # noqa: E402


def person(pid="P1", initial=0.2, valid=100):
    return dict(
        id=pid,
        initial_f=initial,
        valid_until_h=valid,
        calendar=dict(period_h=24, windows=[dict(start_h=0, end_h=4)]),
    )


def interval(start, end, f, rate, phase="WAIT", pid="P1"):
    dt = end - start
    if phase in ("REST", "OFF_SHIFT"):
        active = min(dt, f / rate) if rate else dt
        final = max(0, f - rate * dt)
        e = active * (f + max(0, f - rate * active)) / 2
    else:
        final = f + rate * dt
        e = (f + final) * dt / 2
    return dict(
        person_id=pid,
        start_h=start,
        end_h=end,
        start_f=f,
        end_f=final,
        rate=rate,
        phase=phase,
        exposure=e,
        command_id=None,
    )


class P07ArithmeticTests(unittest.TestCase):
    def test_union_and_overlap_wait_not_double_counted(self):
        self.assertEqual(hours([[0, 2], [1, 3], [3, 4], [9, 10]]), 5)
        for bad in ([[2, 1]], [[0, float("inf")]], [[-1, 0]]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                hours(bad)

    def test_calendar_qualification_half_open_boundaries(self):
        p = person(valid=25)
        self.assertEqual(calendar_intersection(2, 28, p), [[2, 4], [24, 25]])
        self.assertEqual(calendar_intersection(25, 26, p), [])

    def test_recovery_zero_crossing_and_bad_exposure(self):
        r = interval(0, 10, 0.2, 0.1, "REST")
        self.assertAlmostEqual(r["exposure"], 0.2)
        check_human_interval(r)
        for key in ("end_f", "exposure"):
            bad = dict(r)
            bad[key] += 0.1
            with self.subTest(key=key), self.assertRaises(ValueError):
                check_human_interval(bad)

    def test_new_person_not_zero_filled_before_arrival(self):
        r = interval(2, 3, 0.1, 0.02, pid="W3")
        s = dict(
            time_h=3,
            humans=[dict(person_id="W3", fatigue=0.12, exposure=0.11, peak=0.12)],
            intervals=[r],
        )
        g = [
            dict(
                target_id="W3",
                workforce_kind="PERSON_ARRIVE",
                sim_h=2,
                payload=dict(parameter_template_id="T"),
            )
        ]
        rows, _, _ = people_metrics(
            dict(people=[person("W3", 0.1)]), s, generations=g, rates={"T": 10}
        )
        self.assertEqual(rows[0]["defined_from_h"], 2)
        self.assertEqual(rows[0]["before_arrival"], "NOT_IN_CATALOG")
        self.assertEqual(rows[0]["presence_h"], 1)
        self.assertEqual(rows[0]["presence_labour_cost"], 10)

    def test_depart_return_keeps_exposure_and_real_denominators(self):
        a = interval(0, 1, 0.2, 0.02)
        b = interval(1, 2, 0.22, 0.1, "OFF_SHIFT")
        c = interval(2, 3, 0.12, 0.02)
        s = dict(
            time_h=3,
            intervals=[a, b, c],
            humans=[dict(person_id="P1", fatigue=0.14, exposure=0.51, peak=0.22)],
        )
        changes = [
            dict(person_id="P1", time_h=1, status="DEPARTED"),
            dict(person_id="P1", time_h=2, status="PRESENT"),
        ]
        rows, _, _ = people_metrics(dict(people=[person()]), s, changes, rates={"P1": 10})
        self.assertEqual(rows[0]["presence_h"], 2)
        self.assertEqual(rows[0]["availability_h"], 2)
        self.assertAlmostEqual(rows[0]["exposure_F_h"], 0.51)
        self.assertEqual(rows[0]["presence_labour_cost"], 20)
        for mutate in ("missing_person", "gap", "reset_e", "missing_rate"):
            with self.subTest(mutate=mutate):
                bad = deepcopy(s)
                cfg = dict(people=[person()])
                rates = {"P1": 10}
                if mutate == "missing_person":
                    cfg["people"] = []
                elif mutate == "gap":
                    bad["intervals"][1]["start_h"] += 0.1
                elif mutate == "reset_e":
                    bad["humans"][0]["exposure"] = 0
                else:
                    rates = {}
                with self.assertRaises(ValueError):
                    people_metrics(cfg, bad, changes, rates=rates)

    def test_cancel_receipt_and_censored_delay_are_separate(self):
        p = [
            dict(id="A", order_id="O", release_h=0, due_h=5),
            dict(id="B", order_id="O", release_h=0, due_h=5),
        ]
        s = [
            dict(product_id="A", released=True, cancelled=True, ready_h=None, received_h=None),
            dict(product_id="B", released=True, cancelled=False, ready_h=7, received_h=None),
        ]
        rows = product_metrics(p, s, 10)
        self.assertIsNone(rows[0]["received_delay_lower_bound_h"])
        self.assertEqual(rows[1]["ready_tardiness_h"], 2)
        self.assertIsNone(rows[1]["received_tardiness_h"])
        self.assertEqual(rows[1]["received_delay_lower_bound_h"], 5)
        self.assertFalse(rows[0]["on_time_received"])
        with self.assertRaises(ValueError):
            product_metrics(p, s[:1], 10)

    def test_pairing_refuses_duplicates_versions_windows_and_missing_sides(self):
        a = dict(
            scenario="N",
            method="ADAPTIVE",
            source_family="c1",
            evaluation_window_h=720,
            input_configuration_sha256="x",
            m=3,
        )
        b = dict(a, method="EDD", m=5)
        self.assertEqual(pair_values([a, b], "m")[0]["delta_adaptive_minus_edd"], -2)
        for key, value in [
            ("source_family", "c2"),
            ("evaluation_window_h", 100),
            ("input_configuration_sha256", "wrong"),
        ]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                pair_values([a, dict(b, **{key: value})], "m")
        for bad in ([a], [a, b, b]):
            with self.assertRaises(ValueError):
                pair_values(bad, "m")
        self.assertIsNone(pair_values([dict(a, m=None), b], "m")[0]["delta_adaptive_minus_edd"])

    def test_dual_domain_refuses_identity_mismatch_and_unknown_render_scope(self):
        envelope = {k: "x" for k in IDENTITY_FIELDS}
        view = dict(
            envelope=envelope,
            writable=False,
            forecast_audit_pending=False,
            people=[],
            devices=[],
            orders=[],
            full_schedule={},
            rows=[dict(row_id="a")],
        )
        scene = {
            k: deepcopy(view[k])
            for k in ("envelope", "people", "devices", "orders", "full_schedule")
        }
        scene["scope"] = "RECONSTRUCTED_DOMAIN_STATE_NOT_NEW_NATIVE_RENDER"
        validate_pair(view, scene)
        for key in IDENTITY_FIELDS:
            bad = deepcopy(scene)
            bad["envelope"][key] = "wrong"
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_pair(view, bad)
        for scope in ("NEW_NATIVE_RENDER", "UNKNOWN"):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                validate_pair(view, dict(scene, scope=scope))
        for changes in (
            dict(writable=True),
            dict(forecast_audit_pending=True),
            dict(rows=view["rows"] * 2),
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_pair(dict(view, **changes), scene)

    def test_source_pin_run_epoch_and_comparison_window_rejections(self):
        entry = dict(source_family="c1", source=dict(expected_sha256="raw"))
        for k in ("analysis", "independent", "configuration", "events"):
            entry[k] = dict(sha256=k)
        cache = dict(
            run_id="R",
            epoch=0,
            provenance={
                k: deepcopy(entry[k])
                for k in ("analysis", "independent", "configuration", "events")
            },
        )
        cache["provenance"]["source"] = dict(sha256="raw")
        computed = dict(
            summary=dict(run_id="R", epoch=0, source_family="c1", evaluation_window_h=720)
        )
        validate_identity(cache, computed, entry)
        for k, v in [
            ("run_id", "other"),
            ("epoch", 1),
            ("source_family", "c2"),
            ("evaluation_window_h", 1),
        ]:
            bad = deepcopy(computed)
            bad["summary"][k] = v
            with self.subTest(k=k), self.assertRaises(ValueError):
                validate_identity(cache, bad, entry)
        for k in ("analysis", "independent", "configuration", "events", "source"):
            bad = deepcopy(cache)
            bad["provenance"][k]["sha256"] = "wrong"
            with self.subTest(k=k), self.assertRaises(ValueError):
                validate_identity(bad, computed, entry)


if __name__ == "__main__":
    unittest.main()
