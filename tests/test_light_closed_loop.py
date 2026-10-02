"""S12 causal feedback, execution commitments and independent negative audits."""

import importlib.util
import json
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from adaptive_hrc_scheduling.building_backend import BuildingBackend
from adaptive_hrc_scheduling.checker import check_run
from adaptive_hrc_scheduling.control.light_loop import (
    Options,
    audit_decisions,
    capture,
    choose,
    run_loop,
)
from adaptive_hrc_scheduling.domain import building as b

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("s12_cases", ROOT / "scripts/run_light_loop.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def config(variant="SR-W1", products=1):
    return fixture.generator.synthetic_fixture(
        fixture.generator.build_configuration(variant, products=products)
    )


def scenario(c, events=(), seed=17):
    return b.HiddenScenario(
        "C04-1.0",
        c.id,
        seed,
        tuple(
            b.WorldEvent(f"TEST-{i}", t, k, target, None, None)
            for i, (t, k, target) in enumerate(events)
        ),
    )


def run(c=None, events=(), horizon=12, source=None, **options):
    c = c or config()
    return run_loop(
        c, scenario(c, events), Options(horizon_h=horizon, **options), feedback_source=source
    )


class LightLoopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.complete = {
            v: run(config(v), horizon=170, source=fixture.SyntheticFeedback())
            for v in ("SR-W1", "SR-W2")
        }
        cls.w1 = cls.complete["SR-W1"]

    def assert_valid(self, r):
        self.assertEqual(r.report.status, "PASS", r.report.findings)
        self.assertEqual(r.decision_findings, ())
        self.assertNotEqual(r.status, "INVALID_TRACE")

    def test_complete_module_variants_and_plan_actual_separation(self):
        for v, r in self.complete.items():
            with self.subTest(variant=v):
                self.assert_valid(r)
                self.assertEqual(r.status, "COMPLETED")
                self.assertEqual(len(r.trace.quality), 7)
                self.assertEqual(len(r.report.metrics["people"]), 15)
                self.assertTrue(all(t.decision.plan.status == "INCOMPLETE" for t in r.turns))
                self.assertTrue(
                    all(p.ready_h is None for t in r.turns for p in t.decision.plan.predicted_ready)
                )
                codes = {
                    a.code
                    for a in config(v).activities
                    if a.id in {e.entity_id for e in r.trace.events if e.kind == "UNIT_START"}
                }
                self.assertTrue({"W-3D", "MEP-E", "MEP-P", "Q-PACK", "MOVE-OUT"} <= codes)

    def test_repeat_same_stream_same_observed_history_and_actions(self):
        a, c = run(horizon=6), run(horizon=6)
        self.assertEqual(a.turns, c.turns)
        self.assertEqual(a.trace, c.trace)
        for i, t in enumerate(a.turns):
            previous = a.turns[i - 1].feedback.observation.event_ids if i else ()
            self.assertEqual(
                choose(
                    t.feedback, Options(horizon_h=6), sequence=i + 1, previous_event_ids=previous
                ),
                t.decision,
            )

    def test_future_hidden_failure_cannot_change_earlier_dispatch(self):
        a = run(events=[(5, "FAILURE", "CR1")], horizon=6)
        c = run(events=[(5, "FAILURE", "CUT1")], horizon=6)
        self.assert_valid(a)
        self.assert_valid(c)
        earlier_a = [t.decision for t in a.turns if t.decision.time_h < 5]
        earlier_c = [t.decision for t in c.turns if t.decision.time_h < 5]
        self.assertTrue(earlier_a)
        self.assertEqual(earlier_a, earlier_c)
        self.assertNotEqual(
            [t.feedback for t in a.turns if t.decision.time_h == 5],
            [t.feedback for t in c.turns if t.decision.time_h == 5],
        )

    def test_hidden_scenario_seed_not_exported_or_read_by_policy(self):
        c = config()
        a = capture(BuildingBackend(c, scenario(c, [(100, "FAILURE", "CR1")], 1)))
        d = capture(BuildingBackend(c, scenario(c, [(200, "FAILURE", "CUT1")], 999)))
        self.assertEqual(a, d)
        self.assertEqual(choose(a), choose(d))
        text = json.dumps(asdict(a))
        for token in ('"scenario"', '"event_cursor"', '"random_cursor"', '"observation_queue"'):
            self.assertNotIn(token, text)

    def test_future_order_catalogue_is_projected_until_arrival(self):
        c = config(products=2)
        c = replace(c, products=(c.products[0], replace(c.products[1], release_h=4)))
        w = BuildingBackend(c)
        f = capture(w)
        self.assertNotIn("PRODUCT-2", json.dumps(asdict(f)))
        w.advance(4, stop_on_feedback=True)
        f2 = capture(w)
        self.assertIn("PRODUCT-2", {p.id for p in f2.configuration.products})
        self.assertIn("ORDER_ARRIVAL", choose(f2, sequence=2).triggers)

    def test_no_visible_orders_waits_then_dispatches_on_arrival(self):
        c = config()
        c = replace(c, products=(replace(c.products[0], release_h=2),))
        r = run(c, horizon=4)
        self.assert_valid(r)
        self.assertEqual(r.turns[0].decision.action, "WAIT")
        cmds = [t.decision for t in r.turns if t.decision.action == "DISPATCH"]
        self.assertEqual(cmds[0].time_h, 2)

    def test_observed_failure_delays_cut_until_observed_repair(self):
        normal = run(horizon=6)
        failed = run(events=[(0, "FAILURE", "CUT1"), (4, "REPAIR", "CUT1")], horizon=6)
        self.assert_valid(failed)

        def cut(r):
            return next(
                t.decision.time_h
                for t in r.turns
                if t.decision.plan.commands
                and t.decision.plan.commands[0].activity_id.endswith(".CUT")
            )

        self.assertLess(cut(normal), 4)
        self.assertEqual(cut(failed), 4.5)  # Repair at 4; legal shift resumes at 4.5.
        self.assertTrue(
            any(any(x.startswith("EXTERNAL:") for x in t.decision.triggers) for t in failed.turns)
        )

    def test_material_arrival_identification_and_release_gate_real_dispatch(self):
        c = config()
        mid = next(a.material_ids[0] for a in c.activities if a.code == "CUT")
        c = replace(
            c,
            materials=tuple(
                replace(m, arrived=False, identified=False, released=False) if m.id == mid else m
                for m in c.materials
            ),
        )
        r = run(
            c,
            [
                (2, "MATERIAL_ARRIVAL", mid),
                (3, "MATERIAL_IDENTIFY", mid),
                (4, "MATERIAL_RELEASE", mid),
            ],
            horizon=6,
        )
        self.assert_valid(r)
        cut = [
            t
            for t in r.turns
            if t.decision.plan.commands and t.decision.plan.commands[0].activity_id.endswith(".CUT")
        ]
        self.assertEqual(cut[0].decision.time_h, 4.5)  # Same observed calendar break.

    def test_quality_failure_holds_descendants_without_automatic_pass(self):
        r = run(horizon=70, source=fixture.SyntheticFeedback(fail_quality="Q-STR"))
        self.assert_valid(r)
        self.assertEqual(r.status, "UNFINISHED")
        self.assertTrue(any(q.result == "FAIL" for q in r.trace.quality))
        self.assertFalse(
            any(e.entity_id.endswith(".COAT") and e.kind == "UNIT_START" for e in r.trace.events)
        )

    def test_delayed_quality_changes_downstream_dispatch_after_completion(self):
        r = run(horizon=70, source=fixture.SyntheticFeedback(quality_delay_h=2))
        self.assert_valid(r)

        def start(r, suffix):
            return next(
                e.time_h
                for e in r.trace.events
                if e.kind == "UNIT_START" and e.entity_id.endswith(suffix)
            )

        self.assertGreater(start(r, ".COAT"), start(self.w1, ".COAT"))
        first = next(q for q in r.trace.quality if q.activity_id.endswith(".Q-STR"))
        complete = next(
            e.time_h
            for e in r.trace.events
            if e.kind == "ACTIVITY_COMPLETE" and e.entity_id.endswith(".Q-STR")
        )
        self.assertGreaterEqual(first.time_h, complete + 2)

    def test_observed_outbound_occupancy_changes_second_product_dispatch(self):
        c = config(products=2)
        held = run(c, horizon=340, source=fixture.SyntheticFeedback())
        received = run(c, horizon=340, source=fixture.SyntheticFeedback(receive_delay_h=2))
        self.assert_valid(held)
        self.assert_valid(received)
        self.assertEqual(held.status, "UNFINISHED")
        self.assertEqual(received.status, "COMPLETED")
        self.assertEqual(sum(p.state == "READY" for p in held.trace.products), 1)
        self.assertFalse(
            any(
                e.kind == "UNIT_START" and e.entity_id == "PRODUCT-2.MOVE-OUT"
                for e in held.trace.events
            )
        )
        self.assertTrue(
            any(
                e.kind == "UNIT_START" and e.entity_id == "PRODUCT-2.MOVE-OUT"
                for e in received.trace.events
            )
        )

    def test_cancellation_finishes_committed_unit_then_clears_module(self):
        r = run(horizon=70, source=fixture.SyntheticFeedback(cancel_code="W-3D"))
        self.assert_valid(r)
        self.assertEqual(r.status, "CLOSED_WITH_CANCELLATION")
        self.assertEqual(r.trace.products[0].state, "QUARANTINED")
        self.assertTrue(any(e.kind == "CLEANUP_START" for e in r.trace.events))
        self.assertTrue(any(e.kind == "CLEANUP_LANDED" for e in r.trace.events))
        self.assertEqual(r.trace.products[0].location, "Q1")
        self.assertFalse(r.trace.locks)

    def test_cancellation_of_raw_work_keeps_physical_residency(self):
        r = run(events=[(0.2, "CANCEL", "PRODUCT-1")], horizon=8)
        self.assert_valid(r)
        self.assertEqual(r.status, "UNFINISHED")
        self.assertTrue(r.trace.residencies)
        completed = [e for e in r.trace.events if e.kind == "UNIT_COMPLETE"]
        self.assertTrue(completed)
        self.assertTrue(all(e.time_h > 0.2 for e in completed))
        self.assertEqual(len(r.trace.consumed_commands), 1)

    def test_committed_running_modes_crews_and_residencies_are_not_replanned(self):
        w = BuildingBackend(config())
        f = capture(w)
        d = choose(f)
        w.dispatch(d.plan.commands[0])
        before = w.snapshot
        d2 = choose(capture(w), sequence=2)
        self.assertNotEqual(d2.action, "DISPATCH")
        self.assertEqual(w.snapshot.running, before.running)
        self.assertEqual(w.snapshot.residencies, before.residencies)
        self.assertEqual(w.snapshot.attempts, before.attempts)
        self.assertEqual(w.snapshot.locks, before.locks)

    def test_actual_failure_in_move_retains_emergency_prefix(self):
        move = next(
            e
            for e in self.w1.trace.events
            if e.kind == "UNIT_START" and e.entity_id.endswith(".MV-IN-B")
        )
        r = run(
            events=[(move.time_h + 0.1, "FAILURE", json.loads(move.reason)["equipment"][0])],
            horizon=12,
        )
        self.assert_valid(r)
        self.assertEqual(r.status, "UNFINISHED")
        self.assertEqual(r.reason, "EMERGENCY_HOLD_NO_SAFE_PATH")
        self.assertEqual(r.trace.time_h, move.time_h + 0.1)
        self.assertTrue(r.trace.locks)
        self.assertTrue(any(x.state == "EMERGENCY_HOLD" for x in r.trace.running))

    def test_default_qualification_and_hr_remain_disabled(self):
        r = run_loop(fixture.generator.build_configuration(), options=Options(horizon_h=2))
        self.assert_valid(r)
        self.assertFalse(r.trace.consumed_commands)
        modes = {m.id: m for a in config().activities for m in a.modes}
        self.assertTrue(
            all(
                modes[t.decision.plan.commands[0].mode_id].kind != "HR-seq"
                for t in self.w1.turns
                if t.decision.plan.commands
            )
        )

    def test_no_implicit_quality_or_process_release(self):
        r = run(horizon=70)
        self.assert_valid(r)
        self.assertFalse(r.trace.quality)
        self.assertFalse(r.trace.released_processes)
        self.assertEqual(r.status, "UNFINISHED")

    def test_horizon_allows_ready_but_no_new_labor(self):
        end = self.w1.trace.products[0].ready_h
        r = run(horizon=end, source=fixture.SyntheticFeedback())
        self.assert_valid(r)
        self.assertEqual(r.status, "COMPLETED")
        self.assertEqual(r.trace.products[0].ready_h, end)
        self.assertFalse(any(e.kind == "UNIT_START" and e.time_h == end for e in r.trace.events))

    def test_budget_exhaustion_is_valid_unfinished_prefix(self):
        for kwargs in ({"max_decisions": 1}, {"max_bindings": 1}):
            r = run(**kwargs)
            self.assert_valid(r)
            self.assertEqual(r.status, "UNFINISHED")

    def test_options_and_stale_observation_fail_closed(self):
        for opts in (
            Options(poll_h=0),
            Options(horizon_h=float("nan")),
            Options(max_decisions=True),
            Options(rule="BAD"),
        ):
            with self.subTest(opts=opts), self.assertRaises(ValueError):
                run_loop(config(), options=opts)
        f = capture(BuildingBackend(config()))
        with self.assertRaises(ValueError):
            choose(replace(f, observation=replace(f.observation, received_h=1)))

    def test_wait_wakes_on_actual_feedback_without_looking_ahead_in_policy(self):
        c = config()
        w = BuildingBackend(c, scenario(c, [(0.25, "FAILURE", "CUT1")]))
        w.advance(1, stop_on_feedback=True)
        self.assertEqual(w.time, 0.25)
        w2 = BuildingBackend(c, scenario(c, [(0.25, "FAILURE", "CUT1")]))
        w2.advance(1)
        self.assertEqual(w2.time, 1)
        self.assertEqual(check_run(c, w.snapshot).status, "PASS")

    def test_action_and_feedback_ledger_reject_single_defect_mutations(self):
        r = run(horizon=2)
        t = r.turns[0]
        cmd = t.decision.plan.commands[0]
        mutations = [
            replace(t, decision=replace(t.decision, revision=999)),
            replace(
                t,
                decision=replace(
                    t.decision,
                    plan=replace(t.decision.plan, commands=(replace(cmd, config_id="FOREIGN"),)),
                ),
            ),
            replace(
                t,
                decision=replace(
                    t.decision, plan=replace(t.decision.plan, commands=(replace(cmd, roles=()),))
                ),
            ),
            replace(t, actual_event_ids=()),
            replace(
                t,
                feedback=replace(
                    t.feedback,
                    observation=replace(t.feedback.observation, event_ids=(r.trace.events[-1].id,)),
                ),
            ),
        ]
        for changed in mutations:
            with self.subTest(changed=changed.decision.id):
                self.assertTrue(audit_decisions(config(), r.trace, (changed,) + r.turns[1:]))
        self.assertTrue(audit_decisions(config(), r.trace, r.turns[1:]))

    def test_s10_independently_rejects_physical_trace_mutation(self):
        r = self.w1
        trace = replace(r.trace, residencies=())
        with patch(
            "adaptive_hrc_scheduling.building_backend.BuildingBackend.dispatch",
            side_effect=AssertionError("not independent"),
        ):
            self.assertNotEqual(check_run(config(), trace).status, "PASS")
            self.assertEqual(check_run(config(), r.trace).status, "PASS")

    def test_controller_does_not_mutate_feedback_and_ordering_is_stable(self):
        f = capture(BuildingBackend(config()))
        original = asdict(f)
        d = choose(f)
        changed = replace(
            f,
            configuration=replace(
                f.configuration,
                activities=tuple(reversed(f.configuration.activities)),
                edges=tuple(reversed(f.configuration.edges)),
            ),
        )
        self.assertEqual(d, choose(changed))
        self.assertEqual(original, asdict(f))

    def test_future_quality_outcomes_share_all_actions_until_first_observation(self):
        good = run(horizon=60, source=fixture.SyntheticFeedback())
        bad = run(horizon=60, source=fixture.SyntheticFeedback(fail_quality="Q-STR"))
        t = next(q.time_h for q in bad.trace.quality)
        self.assertEqual(
            [x.decision for x in good.turns if x.decision.time_h < t],
            [x.decision for x in bad.turns if x.decision.time_h < t],
        )
        self.assert_valid(good)
        self.assert_valid(bad)


if __name__ == "__main__":
    unittest.main()
