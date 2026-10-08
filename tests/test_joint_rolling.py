"""Cross-tick fixed program, causal audit and fail-closed receipt semantics."""

import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_joint_mechanisms import problem
from run_joint_rolling import prepare

from adaptive_hrc_scheduling.algorithms.joint_rolling import FrozenTailPolicy
from adaptive_hrc_scheduling.algorithms.lns import Options, fingerprint
from adaptive_hrc_scheduling.control.joint_rolling_loop import run_frozen
from adaptive_hrc_scheduling.control.light_loop import audit_decisions, capture
from adaptive_hrc_scheduling.domain import building as b


class RollingTests(unittest.TestCase):
    def setUp(self):
        self.options = Options(seed=18, iterations=0, repair_trials=6, wall_seconds=30)

    def test_actual_complete_tail_full_preparation_and_causal_audit(self):
        journal = prepare()
        anchor = problem(journal)
        prefix = journal.snapshot.events
        result = run_frozen(journal, anchor, self.options)
        self.assertEqual(result.status, "COMPLETED", (result.reason, result.decision_findings))
        self.assertEqual(result.execution_audit.status, "PASS")
        self.assertFalse(result.decision_findings)
        self.assertEqual(result.trace.events[: len(prefix)], prefix)
        self.assertTrue(result.window_complete)
        self.assertGreater(len(result.requests), 3)
        self.assertEqual(
            tuple(round(x, 9) for x in result.actual_score), result.proposal.best_score
        )

    def test_irrelevant_future_wakes_same_deadline_without_changing_program(self):
        normal = prepare()
        at = normal.time + 0.1
        changed = prepare(future=(b.WorldEvent("IRRELEVANT", at, "FAILURE", "TEST1", None, None),))
        a = run_frozen(normal, problem(normal), self.options)
        z = run_frozen(changed, problem(changed), self.options)
        self.assertEqual(a.proposal.best, z.proposal.best)
        self.assertEqual(z.status, "COMPLETED", (z.reason, z.decision_findings))
        self.assertFalse(z.decision_findings)
        self.assertGreater(len(z.requests), len(a.requests))
        self.assertEqual(a.requests[0].plan_sha256, z.requests[0].plan_sha256)
        self.assertEqual(a.requests[0].action, z.requests[0].action)
        self.assertEqual(
            tuple(round(x, 9) for x in a.actual_score), tuple(round(x, 9) for x in z.actual_score)
        )

    def test_actual_r1_failure_is_preserved_and_never_replanned(self):
        base = prepare()
        journal = prepare(
            future=(b.WorldEvent("R1-FAIL", base.time + 0.1, "FAILURE", "R1", None, None),)
        )
        result = run_frozen(journal, problem(journal), self.options)
        self.assertEqual(
            result.status, "WINDOW_CENSORED", (result.reason, result.decision_findings)
        )
        self.assertIsNone(result.actual_score)
        self.assertTrue(any(e.kind == "EXTERNAL" for e in result.trace.events))
        self.assertEqual(len({r.plan_sha256 for r in result.requests}), 1)
        self.assertFalse(result.decision_findings)
        self.assertIn("R1", result.trace.failed_resources)
        self.assertTrue(any(r.location == "J2" for r in result.trace.residencies))

    def test_call_budget_is_censored_not_nominal_completion(self):
        journal = prepare()
        result = run_frozen(journal, problem(journal), self.options, max_calls=1)
        self.assertEqual(result.status, "WINDOW_CENSORED")
        self.assertEqual(result.reason, "CALL_BUDGET")
        self.assertIsNone(result.actual_score)
        self.assertFalse(result.window_complete)
        self.assertFalse(result.decision_findings)

    def test_budget_ends_on_actual_completion_does_not_mislabel_censoring(self):
        journal = prepare()
        anchor = problem(journal)
        plan = FrozenTailPolicy(anchor, self.options)
        result = run_frozen(journal, anchor, self.options, max_calls=len(plan.steps))
        self.assertTrue(result.window_complete)
        self.assertEqual(result.status, "COMPLETED", result.reason)
        self.assertIsNotNone(result.actual_score)
        self.assertEqual(result.reason, "CALL_BUDGET_EXIT_AFTER_COMPLETION")
        self.assertFalse(result.decision_findings)

    def test_cancellation_preserves_real_prefix_and_no_delivery_claim(self):
        base = prepare()
        journal = prepare(
            future=(b.WorldEvent("CANCEL", base.time + 0.1, "CANCEL", "PRODUCT-1", None, None),)
        )
        result = run_frozen(journal, problem(journal), self.options)
        self.assertEqual(
            result.status, "WINDOW_CENSORED", (result.reason, result.decision_findings)
        )
        self.assertTrue(result.trace.products[0].cancelled)
        self.assertIsNone(result.actual_score)
        self.assertFalse(result.decision_findings)

    def test_duplicate_receipt_and_unconfirmed_next_request_fail_closed(self):
        journal = prepare()
        policy = FrozenTailPolicy(problem(journal), self.options)
        feedback = capture(journal.world)
        request = policy.propose(feedback, journal.s.intervals, sequence=10)
        with self.assertRaisesRegex(ValueError, "ACTUAL_RECEIPT_REQUIRED"):
            policy.propose(feedback, journal.s.intervals, sequence=11)
        policy.confirm(request, accepted=False, after_h=journal.time)
        with self.assertRaisesRegex(ValueError, "DUPLICATE_RECEIPT"):
            policy.confirm(request, accepted=True, after_h=journal.time)
        stopped = policy.propose(feedback, journal.s.intervals, sequence=11)
        self.assertEqual(stopped.status, "STOP")
        self.assertIsNone(stopped.action)

    def test_changed_sealed_plan_is_rejected_before_execution(self):
        journal = prepare()
        policy = FrozenTailPolicy(problem(journal), self.options)
        policy.steps = policy.steps[:-1]
        with self.assertRaisesRegex(ValueError, "SEALED_PLAN_CHANGED"):
            policy.propose(capture(journal.world), journal.s.intervals, sequence=10)

    def test_missing_actual_intervals_is_stop_not_reconstruction_from_nominal(self):
        journal = prepare()
        policy = FrozenTailPolicy(problem(journal), self.options)
        request = policy.propose(capture(journal.world), (), sequence=10)
        self.assertEqual(request.status, "STOP")
        self.assertIn("PREFIX_CHANGED", request.reason)

    def test_independent_next_action_failure_never_executes_or_researches(self):
        journal = prepare()
        policy = FrozenTailPolicy(problem(journal), self.options)
        report = type("Report", (), {"status": "INVALID", "findings": ()})()
        before = journal.snapshot
        with patch(
            "adaptive_hrc_scheduling.algorithms.joint_rolling.check_run", return_value=report
        ):
            request = policy.propose(capture(journal.world), journal.s.intervals, sequence=10)
        self.assertEqual(request.status, "STOP")
        self.assertIsNone(request.action)
        self.assertEqual(journal.snapshot, before)

    def test_sealed_program_and_options_do_not_read_hidden_future(self):
        a = prepare(future=(b.WorldEvent("FUTURE-A", 100, "FAILURE", "R1", None, None),))
        z = prepare(future=(b.WorldEvent("FUTURE-Z", 200, "FAILURE", "TEST1", None, None),))
        pa, pz = (
            FrozenTailPolicy(problem(a), self.options),
            FrozenTailPolicy(problem(z), self.options),
        )
        self.assertEqual(pa.plan_sha256, pz.plan_sha256)
        self.assertEqual(fingerprint(pa.proposal.best), fingerprint(pz.proposal.best))

    def test_causal_audit_rejects_changed_observation_with_physical_pass(self):
        journal = prepare()
        result = run_frozen(journal, problem(journal), self.options)
        self.assertEqual(result.execution_audit.status, "PASS")
        turns = list(result.turns)
        turn = turns[-2]
        human = turn.feedback.observation.people[0]
        obs = replace(
            turn.feedback.observation,
            people=(
                replace(human, fatigue=human.fatigue + 0.01),
                *turn.feedback.observation.people[1:],
            ),
        )
        turns[-2] = replace(turn, feedback=replace(turn.feedback, observation=obs))
        self.assertTrue(audit_decisions(journal.config, result.trace, tuple(turns)))

    def test_late_unload_retains_hardware_until_actual_human_stage(self):
        journal = prepare(late_unload=True)
        anchor = problem(journal, fixed="HR-seq")
        result = run_frozen(journal, anchor, self.options)
        self.assertEqual(result.status, "COMPLETED", (result.reason, result.decision_findings))
        self.assertEqual(round(result.actual_score[0], 9), 7.5)
        self.assertFalse(result.decision_findings)
        unload = next(
            t
            for t in result.turns
            if t.decision.plan.commands
            and t.decision.plan.commands[0].activity_id == "PRODUCT-1.W-B"
            and t.decision.plan.commands[0].unit_index == 2
        )
        self.assertEqual(unload.decision.time_h, 7)
        self.assertTrue(
            {"R1", "FIX-J2"} <= {lock.resource_id for lock in unload.feedback.state.locks}
        )

    def test_failure_while_waiting_for_unload_cannot_clear_cell_or_fixture(self):
        journal = prepare(
            late_unload=True, future=(b.WorldEvent("FAIL-HELD", 4, "FAILURE", "R1", None, None),)
        )
        result = run_frozen(journal, problem(journal, fixed="HR-seq"), self.options)
        self.assertEqual(
            result.status, "WINDOW_CENSORED", (result.reason, result.decision_findings)
        )
        self.assertFalse(result.decision_findings)
        self.assertIsNone(result.actual_score)
        self.assertTrue({"R1", "FIX-J2"} <= {lock.resource_id for lock in result.trace.locks})
        self.assertTrue(any(r.location == "J2" for r in result.trace.residencies))

    def test_actual_clock_jump_does_not_shift_fixed_start_or_replan(self):
        journal = prepare()
        policy = FrozenTailPolicy(problem(journal), self.options)
        original = policy.plan_sha256
        journal.advance(journal.time + 0.1)
        request = policy.propose(
            capture(journal.world), journal.s.intervals, sequence=len(journal.turns) + 1
        )
        self.assertEqual(request.status, "STOP")
        self.assertIn("FIXED_START_CLOCK_MISSED", request.reason)
        self.assertEqual(policy.plan_sha256, original)
        self.assertIsNone(request.action)


if __name__ == "__main__":
    unittest.main()
