"""Independent single-defect mutations of raw evidence, never dispatched again."""

import ast
import importlib.util
import json
import math
import unittest
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

from adaptive_hrc_scheduling import checker, metrics
from adaptive_hrc_scheduling.building_backend import BuildingBackend
from adaptive_hrc_scheduling.domain import building as b

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "s10_witness", ROOT / "scripts/run_building_witness.py"
)
witness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(witness)


def mutate_event(snapshot, predicate, change):
    rows = list(snapshot.events)
    index = next(i for i, e in enumerate(rows) if predicate(e))
    rows[index] = change(rows[index])
    return replace(snapshot, events=tuple(rows))


def detail(event, **changes):
    data = json.loads(event.reason)
    data.update(changes)
    return replace(event, reason=json.dumps(data))


class BuildingCheckerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worlds = {}
        for variant in ("SR-W1", "SR-W2"):
            w = witness.run_chain(variant=variant)
            w.advance(w.time + 1)
            witness.fact(w, "RECEIVED", "PRODUCT-1")
            w.advance(240)
            cls.worlds[variant] = w
        cls.c = cls.worlds["SR-W1"].config
        cls.s = cls.worlds["SR-W1"].s

    def assert_rule(self, rule, *, config=None, snapshot=None, **kwargs):
        result = checker.check_run(config or self.c, snapshot or self.s, **kwargs)
        self.assertNotEqual(result.status, "PASS")
        matches = [f for f in result.findings if f.rule == rule]
        self.assertTrue(matches, result.to_dict())
        self.assertTrue(all(f.object_id and math.isfinite(f.time_h) and f.code for f in matches))
        return result

    def assert_pass(self, w):
        r = checker.check_run(w.config, w.s)
        self.assertEqual(r.status, "PASS", r.findings[:10])
        return r

    def before(self, code):
        w = BuildingBackend(self.c)
        for a in self.c.activities:
            if a.code == code:
                return w
            witness.run_activity(w, a.id)
        self.fail(code)

    def start(self, w, aid, **kwargs):
        for _ in range(1000):
            receipt = w.dispatch(witness.command(w, aid, **kwargs))
            if receipt.accepted:
                return next(r for r in w.s.running if r.activity_id == aid)
            self.assertIn(
                receipt.reason,
                ("CALENDAR_OR_QUALIFICATION", "FATIGUE_PROTECTION", "REST_COMMITTED"),
            )
            if receipt.reason == "FATIGUE_PROTECTION":
                w.rest(tuple(r.person_id for r in witness.command(w, aid, **kwargs).roles), 0.25)
            w.advance(w.time + 0.25)
        self.fail("fixture failed to start")

    def test_normal_complete_both_variants_no_false_positive(self):
        for variant, w in self.worlds.items():
            with self.subTest(variant=variant):
                result = self.assert_pass(w)
                self.assertEqual(result.metrics["ready_products"], 1)
                self.assertEqual(result.metrics["received_products"], 1)
                self.assertEqual(len(result.metrics["people"]), 15)
                self.assertAlmostEqual(
                    result.metrics["products"][0]["ready_h"],
                    149.598500771668 if variant == "SR-W1" else 171.61789240458066,
                )
                self.assertEqual(result.metrics["moves_completed"], 9)

    def test_r01_position_single_defect(self):
        self.assert_rule(
            "R01",
            snapshot=replace(
                self.s,
                components=(replace(self.s.components[0], location="F1"),) + self.s.components[1:],
            ),
        )

    def test_r02_wait_single_defect(self):
        s = mutate_event(self.s, lambda e: e.kind == "WAIT_START", lambda e: detail(e, until=10000))
        self.assert_rule("R02", snapshot=s)

    def test_r03_qualification_single_defect(self):
        eid = self.c.activities[0].modes[0].qualification_ids[0]
        self.assert_rule(
            "R03",
            config=replace(
                self.c,
                evidence=tuple(
                    replace(e, status="UNKNOWN") if e.id == eid else e for e in self.c.evidence
                ),
            ),
        )

    def test_r04_missing_person_single_defect(self):
        s = mutate_event(
            self.s,
            lambda e: e.kind == "UNIT_START" and e.entity_id.endswith("W-3D"),
            lambda e: detail(e, roles=json.loads(e.reason)["roles"][:1]),
        )
        self.assert_rule("R04", snapshot=s)

    def test_r05_capacity_single_defect(self):
        self.assert_rule(
            "R05",
            config=replace(
                self.c,
                resources=tuple(
                    replace(r, capacity=1) if r.id == "BUF" else r for r in self.c.resources
                ),
            ),
        )

    def test_r06_compatible_parallel_and_single_defect(self):
        w = self.before("MEP-E")
        w.advance(72)
        self.start(w, "PRODUCT-1.MEP-E")
        self.start(w, "PRODUCT-1.MEP-P")
        w.advance(max(r.end_h for r in w.s.running))
        self.assert_pass(w)
        self.assert_rule("R06", config=replace(w.config, face_pairs=()), snapshot=w.s)

    def test_r07_early_source_release_single_defect(self):
        def change(e):
            d = json.loads(e.reason)
            d["residencies"] = [r for r in d["residencies"] if r["location"] != "J3"]
            return replace(e, reason=json.dumps(d))

        self.assert_rule(
            "R07",
            snapshot=mutate_event(
                self.s,
                lambda e: e.kind == "MOVE_RESERVED" and e.entity_id.endswith("MOVE-F"),
                change,
            ),
        )

    def test_r08_overload_single_defect(self):
        self.assert_rule(
            "R08", config=replace(self.c, products=(replace(self.c.products[0], mass_t=12),))
        )

    def test_r09_progress_single_defect(self):
        s = mutate_event(self.s, lambda e: e.kind == "UNIT_START", lambda e: detail(e, attempt=1))
        self.assert_rule("R09", snapshot=s)

    def test_r10_integral_single_defect(self):
        s = replace(
            self.s, intervals=(replace(self.s.intervals[0], exposure=99),) + self.s.intervals[1:]
        )
        self.assert_rule("R10", snapshot=s)

    def test_r11_quality_history_single_defect(self):
        s = replace(
            self.s, quality=(replace(self.s.quality[0], result="FAIL"),) + self.s.quality[1:]
        )
        self.assert_rule("R11", snapshot=s)

    def test_r12_kit_single_defect(self):
        self.assert_rule(
            "R12",
            config=replace(
                self.c,
                materials=(replace(self.c.materials[0], released=False),) + self.c.materials[1:],
            ),
        )

    def test_r13_cancel_single_defect(self):
        # Change one existing external fact into cancellation, retaining the suffix.
        def change(e):
            d = json.loads(e.reason)
            d.update(kind="CANCEL", entity_id="PRODUCT-1", value=None, attempt=None)
            return replace(e, reason=json.dumps(d))

        self.assert_rule(
            "R13", snapshot=mutate_event(self.s, lambda e: e.kind == "EXTERNAL", change)
        )

    def test_r14_visibility_single_defect(self):
        w = BuildingBackend(self.c)
        w.advance(1)
        obs = w.observe()[0]
        plan = b.Plan(
            "C04-1.0", self.c.id, obs.id, (), (b.Prediction("PRODUCT-1", None),), "INCOMPLETE"
        )
        good = checker.check_run(self.c, w.s, plan=plan, observation=obs)
        self.assertEqual(good.status, "PASS", good.findings)
        self.assert_rule("R14", snapshot=w.s, plan=plan, observation=replace(obs, sampled_h=2))

    def test_r15_false_ready_single_defect(self):
        s = replace(self.s, products=(replace(self.s.products[0], ready_h=1),))
        self.assert_rule("R15", snapshot=s)

    def test_r16_duplicate_single_defect(self):
        s = replace(self.s, events=self.s.events[:1] + self.s.events)
        self.assert_rule("R16", snapshot=s)

    def test_r17_missing_person_single_defect(self):
        result = self.assert_rule("R17", snapshot=replace(self.s, people=self.s.people[1:]))
        self.assertEqual(result.status, "INCOMPLETE")

    def test_r18_version_single_defect(self):
        self.assert_rule("R18", snapshot=replace(self.s, schema_version="S06-1.1"))

    def test_missing_event_incomplete_not_pass(self):
        result = self.assert_rule("R16", snapshot=replace(self.s, events=self.s.events[1:]))
        self.assertEqual(result.status, "INCOMPLETE")

    def test_out_of_order_is_not_silently_sorted(self):
        rows = list(self.s.events)
        rows[0], rows[2] = rows[2], rows[0]
        self.assert_rule("R16", snapshot=replace(self.s, events=tuple(rows)))

    def test_missing_final_quality_event_incomplete(self):
        rows = tuple(
            e
            for e in self.s.events
            if not (e.kind == "EXTERNAL" and '"entity_id": "PRODUCT-1.Q-FIN"' in e.reason)
        )
        result = checker.check_run(self.c, replace(self.s, events=rows))
        self.assertEqual(result.status, "INCOMPLETE")
        self.assertTrue(any(f.rule == "R15" for f in result.findings))

    def test_missing_person_intervals_incomplete(self):
        result = self.assert_rule(
            "R17",
            snapshot=replace(
                self.s, intervals=tuple(x for x in self.s.intervals if x.person_id != "W2")
            ),
        )
        self.assertEqual(result.status, "INCOMPLETE")

    def test_unfinished_orders_retained_and_delay_is_lower_bound(self):
        w = BuildingBackend(self.c)
        w.advance(240)
        r = self.assert_pass(w)
        self.assertEqual(r.metrics["released_products"], 1)
        self.assertEqual(r.metrics["incomplete_products"], 1)
        self.assertIsNone(r.metrics["order_tardiness_h"])
        self.assertEqual(r.metrics["order_tardiness_lower_bound_h"], 72)
        self.assertEqual(r.metrics["wip_product_h"], 0)

    def test_explicit_weights_include_unfinished_orders(self):
        w = BuildingBackend(self.c)
        w.advance(240)
        r = checker.check_run(self.c, w.s, order_weights={"ORDER-1": 3})
        self.assertEqual(r.status, "PASS")
        self.assertEqual(r.metrics["order_tardiness_lower_bound_h"], 216)
        self.assertIsNone(r.metrics["order_tardiness_h"])
        self.assertEqual(checker.check_run(self.c, w.s, order_weights={}).status, "INCOMPLETE")

    def test_future_completion_cannot_be_in_observation(self):
        w = BuildingBackend(self.c)
        w.advance(1)
        obs = w.observe()[0]
        plan = b.Plan(
            "C04-1.0", self.c.id, obs.id, (), (b.Prediction("PRODUCT-1", None),), "INCOMPLETE"
        )
        obs = replace(
            obs, products=(replace(obs.products[0], completed_activity_ids=("PRODUCT-1.Q-FIN",)),)
        )
        self.assert_rule("R14", snapshot=w.s, plan=plan, observation=obs)

    def test_rational_h_d1_and_zero_crossing(self):
        duration = Fraction(1, 2) * (1 + Fraction(1, 2) * Fraction(1, 5))
        f, e, peak = metrics.integrate_segment(0.2, float(duration), 0.15)
        final, rest, _ = metrics.integrate_segment(f, 2 - float(duration), 0.2, True)
        self.assertEqual(final, 0)
        self.assertAlmostEqual(e + rest, 0.332203125, places=14)
        self.assertAlmostEqual(peak, 0.2825)
        self.assertEqual(metrics.integrate_segment(0, 5, 0.2, True), (0, 0, 0))

    def test_hand_calculated_idle_window_all_people_and_no_wip(self):
        w = BuildingBackend(self.c)
        w.advance(2)
        r = self.assert_pass(w)
        # Every person waits: F=.2+.02*2=.24; E=(.2+.24)/2*2=.44.
        self.assertAlmostEqual(r.metrics["sum_exposure_F_h"], 15 * 0.44)
        self.assertAlmostEqual(r.metrics["max_exposure_F_h"], 0.44)
        self.assertEqual(r.metrics["labor_wait_person_h"], 30)
        self.assertEqual(r.metrics["wip_product_h"], 0)

    def test_hand_calculated_received_occupancy_tail(self):
        r = self.assert_pass(self.worlds["SR-W1"])
        self.assertAlmostEqual(r.metrics["occupancy_entity_or_product_h"]["OUT1"], 2)
        self.assertAlmostEqual(r.metrics["move_equipment_h"], 4)

    def test_j2_same_product_two_frames_residency_and_exclusive_fixture(self):
        w = self.before("MV-IN-B")
        witness.run_activity(w, "PRODUCT-1.MV-IN-B")
        witness.run_activity(w, "PRODUCT-1.MV-IN-T")
        self.assertEqual(sum(r.location == "J2" for r in w.s.residencies), 2)
        run = self.start(w, "PRODUCT-1.W-B")
        self.assertFalse(w.dispatch(witness.command(w, "PRODUCT-1.W-T")).accepted)
        w.advance(run.end_h)
        self.assert_pass(w)

    def test_forged_attempt_completion_is_detected(self):
        s = replace(
            self.s, attempts=(replace(self.s.attempts[0], completed_units=0),) + self.s.attempts[1:]
        )
        self.assert_rule("R09", snapshot=s)

    def test_unknown_event_and_nonfinite_interval_incomplete(self):
        for s in (
            mutate_event(self.s, lambda e: True, lambda e: replace(e, kind="UNKNOWN")),
            replace(
                self.s,
                intervals=(replace(self.s.intervals[0], end_h=float("nan")),)
                + self.s.intervals[1:],
            ),
        ):
            with self.subTest():
                self.assertEqual(checker.check_run(self.c, s).status, "INCOMPLETE")

    def test_plan_alone_cannot_certify_future_feasibility(self):
        w = BuildingBackend(self.c)
        w.advance(1)
        obs = w.observe()[0]
        plan = b.Plan(
            "C04-1.0",
            self.c.id,
            obs.id,
            (witness.command(w, "PRODUCT-1.KIT"),),
            (b.Prediction("PRODUCT-1", 150),),
            "CANDIDATE",
        )
        r = checker.check_run(self.c, w.s, plan=plan, observation=obs)
        self.assertEqual(r.status, "INCOMPLETE")

    def test_same_tick_due_cancellation_cannot_follow_dispatch(self):
        e = b.WorldEvent("DUE-CANCEL", 0, "CANCEL", "PRODUCT-1", None, None)
        s = replace(self.s, scenario=replace(self.s.scenario, events=(e,)))
        self.assert_rule("R16", snapshot=s)

    def test_computation_cost_is_separate_from_simulation(self):
        r = checker.check_run(
            self.c,
            self.s,
            computation_samples=({"wall_ms": 12, "budget_ms": 10, "fallback": True},),
        )
        self.assertEqual(r.status, "PASS")
        self.assertEqual(r.metrics["computation"]["budget_violations"], 1)
        self.assertEqual(r.metrics["computation"]["fallback_rate"], 1)

    def test_default_hr_disabled(self):
        c = witness.generator.build_configuration()
        self.assertTrue(
            all(not m.enabled for a in c.activities for m in a.modes if m.kind == "HR-seq")
        )
        r = checker.check_run(c, self.s)
        self.assertNotEqual(r.status, "PASS")

    def test_no_executor_or_shared_predicate_imports(self):
        for module in (checker, metrics):
            tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
            imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
            self.assertFalse(
                any(
                    x
                    and any(
                        word in x
                        for word in ("backend", "human_state", "building_human", "contracts")
                    )
                    for x in imports
                )
            )

    def test_mid_move_prefix_is_valid(self):
        w = self.before("MOVE-F")
        run = self.start(w, "PRODUCT-1.MOVE-F")
        w.advance(run.start_h + 0.5)
        self.assert_pass(w)

    def test_failure_holds_prefix(self):
        w = self.before("MOVE-F")
        run = self.start(w, "PRODUCT-1.MOVE-F")
        w.advance(run.start_h + 0.5)
        witness.fact(w, "FAILURE", "CR1")
        self.assert_pass(w)

    def test_cancellation_cleanup_keeps_labor_and_occupancy(self):
        w = self.before("MOVE-F")
        run = self.start(w, "PRODUCT-1.MOVE-F")
        w.advance(run.start_h + 0.5)
        witness.fact(w, "CANCEL", "PRODUCT-1")
        w.advance(run.end_h)
        for _ in range(200):
            receipt = w.cleanup("PRODUCT-1")
            if receipt.accepted:
                break
            w.advance(w.time + 0.25)
        self.assertTrue(receipt.accepted)
        w.advance(w.s.services[0].end_h)
        r = self.assert_pass(w)
        self.assertEqual(r.metrics["cancelled_products"], 1)
        self.assertGreater(r.metrics["labor_person_h"], 0)
        self.assertGreater(r.metrics["wip_product_h"], 0)

    def test_handover_and_restore_preserve_progress(self):
        w = self.before("W-B")
        run = self.start(w, "PRODUCT-1.W-B")
        w.advance(run.end_h)
        w.advance(24)
        self.assertTrue(w.handover("PRODUCT-1.W-B", "W1", "W2").accepted)
        w.advance(w.s.services[0].end_h)
        w.advance(w.s.services[0].end_h)
        self.start(w, "PRODUCT-1.W-B", bindings={"W1": "W2"})
        w.advance(w.s.running[0].end_h)
        self.assert_pass(w)

    def test_single_local_repair_preserves_failure_history(self):
        w = self.before("Q-POND")
        run = self.start(w, "PRODUCT-1.Q-POND")
        w.advance(run.end_h)
        witness.fact(w, "QUALITY_RESULT", "PRODUCT-1.Q-POND", "FAIL", 0)
        for _ in range(500):
            receipt = w.repair_quality("PRODUCT-1.Q-POND")
            if receipt.accepted:
                break
            if receipt.reason == "FATIGUE_PROTECTION":
                w.rest(("QA1", "T1"), 0.25)
            w.advance(w.time + 0.25)
        self.assertTrue(receipt.accepted)
        w.advance(w.s.services[0].end_h)
        for a in self.c.activities:
            if a.code in (
                "WAIT-W",
                "TEST-SET",
                "WAIT-TEST",
                "Q-POND",
                "TILE",
                "WAIT-TILE",
                "EXT",
                "Q-EXT",
                "PAINT",
                "WAIT-PAINT",
                "FIT",
                "Q-FIN",
                "PACK",
                "Q-PACK",
                "MOVE-OUT",
                "READY",
            ):
                witness.run_activity(w, a.id)
        r = self.assert_pass(w)
        self.assertEqual(r.metrics["repair_attempts"], 1)
        self.assertGreater(r.metrics["repair_service_h"], 1.5)


if __name__ == "__main__":
    unittest.main()
