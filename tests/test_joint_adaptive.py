"""Actual adaptive execution retains independent physical and causal audits."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_joint_adaptive import before_move
from run_joint_mechanisms import problem
from run_joint_rolling import prepare

from adaptive_hrc_scheduling.algorithms.lns import Options, Verification
from adaptive_hrc_scheduling.control.joint_adaptive_loop import run_adaptive
from adaptive_hrc_scheduling.control.joint_rolling_loop import run_frozen
from adaptive_hrc_scheduling.domain import building as b


class AdaptiveTests(unittest.TestCase):
    def setUp(self):
        self.options = Options(seed=18, iterations=0, repair_trials=6, wall_seconds=30)

    def run_case(self, *, future=(), fixed=None, late=False, calls=1000):
        journal = prepare(future=future, late_unload=late)
        anchor = problem(journal, fixed=fixed)
        prefix = journal.snapshot.events
        result = run_adaptive(journal, anchor, self.options, max_calls=calls)
        self.assertEqual(result.execution_audit.status, "PASS")
        self.assertFalse(result.decision_findings, result.decision_findings)
        self.assertEqual(result.trace.events[: len(prefix)], prefix)
        self.assertTrue(all(r.end_h == anchor.end for r in result.replans))
        return result

    def test_normal_replans_complete_suffix_and_matches_frozen_actual_score(self):
        result = self.run_case()
        journal = prepare()
        frozen = run_frozen(journal, problem(journal), self.options)
        self.assertEqual(result.status, "COMPLETED", result.reason)
        self.assertEqual(result.actual_score, frozen.actual_score)
        self.assertGreater(len({r.observation_sha256 for r in result.replans}), 3)
        self.assertTrue(all(r.proposal.best is not None for r in result.replans))

    def test_hidden_future_does_not_change_first_choice(self):
        a = self.run_case(future=(b.WorldEvent("F1", 100, "FAILURE", "R1", None, None),))
        z = self.run_case(future=(b.WorldEvent("F2", 200, "FAILURE", "TEST1", None, None),))
        self.assertEqual(a.replans[0].proposal.best, z.replans[0].proposal.best)
        self.assertEqual(a.replans[0].action, z.replans[0].action)
        self.assertEqual(a.actual_score, z.actual_score)

    def test_new_irrelevant_failure_replans_from_actual_feedback_without_horizon_drift(self):
        at = prepare().time + 0.1
        result = self.run_case(future=(b.WorldEvent("F", at, "FAILURE", "TEST1", None, None),))
        self.assertEqual(result.status, "COMPLETED", result.reason)
        self.assertTrue(any(r.observed_h == at for r in result.replans))
        self.assertIn("TEST1", result.trace.failed_resources)

    def test_failure_in_committed_setup_cannot_switch_mode_or_erase_occupancy(self):
        at = prepare().time + 0.1
        result = self.run_case(future=(b.WorldEvent("F", at, "FAILURE", "R1", None, None),))
        self.assertEqual(result.status, "WINDOW_CENSORED")
        self.assertIsNone(result.actual_score)
        self.assertTrue(any(r.location == "J2" for r in result.trace.residencies))
        modes = {
            t.decision.plan.commands[0].mode_id
            for t in result.turns
            if t.decision.plan.commands
            and t.decision.plan.commands[0].activity_id == "PRODUCT-1.W-B"
        }
        self.assertEqual(len(modes), 1)

    def test_fixed_h_and_hr_retain_late_unload_reverse_result(self):
        hr = self.run_case(fixed="HR-seq", late=True)
        h = self.run_case(fixed="H", late=True)
        self.assertEqual(hr.status, "COMPLETED", hr.reason)
        self.assertEqual(h.status, "COMPLETED", h.reason)
        self.assertEqual(hr.actual_score[0], 7.5)
        self.assertGreater(hr.actual_score[0], h.actual_score[0])

    def test_cancel_and_call_budget_keep_null_scores(self):
        at = prepare().time + 0.1
        cancelled = self.run_case(
            future=(b.WorldEvent("C", at, "CANCEL", "PRODUCT-1", None, None),)
        )
        limited = self.run_case(calls=1)
        for result in (cancelled, limited):
            self.assertEqual(result.status, "WINDOW_CENSORED")
            self.assertIsNone(result.actual_score)
        self.assertTrue(cancelled.trace.products[0].cancelled)
        self.assertEqual(limited.reason, "CALL_BUDGET")

    def test_budget_ends_at_actual_completion(self):
        base = self.run_case()
        exact = self.run_case(calls=len(base.replans))
        self.assertEqual(exact.status, "COMPLETED")
        self.assertEqual(exact.reason, "CALL_BUDGET_EXIT_AFTER_COMPLETION")
        self.assertEqual(base.actual_score, exact.actual_score)

    def test_invalid_final_suffix_cannot_execute(self):
        journal = prepare()
        anchor = problem(journal)
        before = journal.snapshot
        from adaptive_hrc_scheduling.algorithms.joint_lns import joint_search

        proposal = joint_search(anchor, self.options)
        with (
            patch(
                "adaptive_hrc_scheduling.control.joint_adaptive_loop.joint_search",
                return_value=proposal,
            ),
            patch(
                "adaptive_hrc_scheduling.algorithms.joint_lns.JointProblem.verify",
                return_value=Verification(False, None, ("INJECTED",)),
            ),
        ):
            result = run_adaptive(journal, anchor, self.options)
        self.assertEqual(result.trace, before)
        self.assertEqual(result.status, "WINDOW_CENSORED")
        self.assertIn("FINAL_SUFFIX_REJECTED", result.reason)

    def test_driver_anchor_mismatch_is_rejected_before_search(self):
        journal = prepare()
        anchor = problem(journal)
        journal.advance(journal.time + 0.1)
        with self.assertRaisesRegex(ValueError, "ANCHOR_MISMATCH"):
            run_adaptive(journal, anchor, self.options)

    def test_failure_observed_during_move_changes_only_uncommitted_weld_mode(self):
        baseline = before_move()
        at = baseline.time + 0.01
        changed = before_move((b.WorldEvent("F", at, "FAILURE", "R1", None, None),))
        normal = run_adaptive(baseline, problem(baseline), self.options)
        result = run_adaptive(changed, problem(changed), self.options)
        self.assertEqual(normal.replans[0].proposal.best, result.replans[0].proposal.best)
        self.assertEqual(result.status, "COMPLETED", result.reason)
        self.assertEqual(result.execution_audit.status, "PASS")
        self.assertFalse(result.decision_findings)

        def modes(value):
            return {
                t.decision.plan.commands[0].mode_id
                for t in value.turns
                if t.decision.plan.commands
                and t.decision.plan.commands[0].activity_id == "PRODUCT-1.W-B"
            }

        self.assertNotEqual(modes(normal), modes(result))
        self.assertEqual(len(modes(result)), 1)
        self.assertIn("R1", result.trace.failed_resources)


if __name__ == "__main__":
    unittest.main()
