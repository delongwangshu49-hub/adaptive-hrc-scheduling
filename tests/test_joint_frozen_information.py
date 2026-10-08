"""Conditional full no-update information ablation and common safety shield."""

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from run_building_witness import fact
from run_joint_mechanisms import fixture, problem

from adaptive_hrc_scheduling.algorithms.joint_lns import FrozenJointPolicy
from adaptive_hrc_scheduling.algorithms.lns import Options, fingerprint


class FrozenInformationTests(unittest.TestCase):
    def setUp(self):
        self.options = Options(seed=18, iterations=2, repair_trials=6, wall_seconds=30)

    def test_normal_same_budget_same_result_and_separate_actual_audit(self):
        current = problem(fixture())
        policy = FrozenJointPolicy(current)
        before = current.world.snapshot
        decision = policy.decide(current, self.options)
        self.assertEqual(decision.status, "FEASIBLE", decision.safety.reasons)
        self.assertEqual(decision.proposal.options, self.options)
        self.assertEqual(decision.proposal.best_score, decision.safety.score)
        self.assertTrue(current.verify(decision.candidate).valid)
        self.assertEqual(current.world.snapshot, before)
        self.assertEqual(decision.anchor_sha256, decision.current_sha256)

    def test_new_robot_failure_does_not_change_proposal_and_shield_waits(self):
        world = fixture()
        anchor = problem(world)
        policy = FrozenJointPolicy(anchor)
        normal = policy.decide(anchor, self.options)
        fact(world, "FAILURE", "R1")
        current = problem(world)
        rejected = policy.decide(current, self.options)
        self.assertEqual(rejected.proposal.best, normal.proposal.best)
        self.assertEqual(rejected.proposal.best_score, normal.proposal.best_score)
        self.assertEqual(rejected.status, "WAIT")
        self.assertIsNone(rejected.candidate)
        self.assertFalse(rejected.safety.valid)
        self.assertNotEqual(rejected.current_sha256, rejected.anchor_sha256)
        self.assertEqual(
            [(h.candidate_sha256, h.accepted, h.trials) for h in rejected.proposal.history],
            [(h.candidate_sha256, h.accepted, h.trials) for h in normal.proposal.history],
        )

    def test_irrelevant_failure_does_not_change_ranking_or_actual_score(self):
        world = fixture()
        anchor = problem(world)
        policy = FrozenJointPolicy(anchor)
        normal = policy.decide(anchor, self.options)
        fact(world, "FAILURE", "TEST1")
        current = problem(world)
        unchanged = policy.decide(current, self.options)
        self.assertEqual(unchanged.status, "FEASIBLE", unchanged.safety.reasons)
        self.assertEqual(unchanged.proposal.best, normal.proposal.best)
        self.assertEqual(unchanged.safety.score, normal.safety.score)
        self.assertTrue(current.verify(unchanged.candidate).valid)

    def test_product_cancellation_cannot_be_repaired_by_observed_state(self):
        world = fixture()
        anchor = problem(world)
        policy = FrozenJointPolicy(anchor)
        nominal = policy.decide(anchor, self.options)
        fact(world, "CANCEL", "PRODUCT-1")
        current = problem(world)
        decision = policy.decide(current, self.options)
        self.assertEqual(decision.proposal.best, nominal.proposal.best)
        self.assertEqual(decision.status, "WAIT")
        self.assertFalse(decision.safety.valid)

    def test_search_receives_anchor_only_never_current_verification(self):
        current = problem(fixture())
        policy = FrozenJointPolicy(current)
        original = current.verify
        with patch.object(current, "verify", wraps=original) as actual_verify:
            decision = policy.decide(current, self.options)
        self.assertEqual(actual_verify.call_count, 1)
        self.assertEqual(decision.status, "FEASIBLE")
        self.assertIsNot(policy.anchor, current)

    def test_actual_audit_rejection_cannot_rank_or_replace_nominal_cache(self):
        from adaptive_hrc_scheduling.algorithms.lns import Verification

        current = problem(fixture())
        policy = FrozenJointPolicy(current)
        normal = policy.decide(current, self.options)
        with patch.object(current, "verify", return_value=Verification(False, None, ("AUDIT",))):
            rejected = policy.decide(current, self.options)
        self.assertEqual(rejected.status, "WAIT")
        self.assertEqual(rejected.proposal.best, normal.proposal.best)
        self.assertEqual(rejected.proposal.best_score, normal.proposal.best_score)
        self.assertEqual(rejected.safety.reasons, ("AUDIT",))

    def test_changed_window_controls_and_nonhistorical_anchor_fail(self):
        world = fixture()
        policy = FrozenJointPolicy(problem(world))
        with self.assertRaisesRegex(ValueError, "COMMON_DOMAIN"):
            policy.decide(problem(world, window=9), self.options)
        with self.assertRaisesRegex(ValueError, "COMMON_DOMAIN"):
            policy.decide(problem(world, state=False), self.options)
        other = fixture(failure="R1")
        wrong = FrozenJointPolicy(problem(other))
        with self.assertRaisesRegex(ValueError, "ANCHOR_ACTUAL_PREFIX"):
            wrong.decide(problem(world), self.options)

    def test_current_hidden_scenario_never_enters_proposal(self):
        from adaptive_hrc_scheduling.domain import building as b

        anchor = problem(fixture())
        policy = FrozenJointPolicy(anchor)
        a = fixture(future=(b.WorldEvent("A", 100, "FAILURE", "R1", None, None),))
        z = fixture(future=(b.WorldEvent("Z", 200, "FAILURE", "WELD1", None, None),))
        ra, rz = policy.decide(problem(a), self.options), policy.decide(problem(z), self.options)
        self.assertEqual(fingerprint(ra.proposal.best), fingerprint(rz.proposal.best))
        self.assertEqual(ra.candidate, rz.candidate)
        self.assertEqual(ra.safety, rz.safety)

    def test_committed_robot_tail_keeps_cell_and_fixture(self):
        from run_building_witness import command

        world = fixture()
        for _ in range(2):
            world.dispatch(command(world, "PRODUCT-1.W-B", mode="PRODUCT-1.HR-seq"))
            world.advance(world.s.running[0].end_h)
        current = problem(world)
        policy = FrozenJointPolicy(current)
        snapshot = copy.deepcopy(world.snapshot)
        decision = policy.decide(current, self.options)
        self.assertEqual(decision.status, "FEASIBLE", decision.safety.reasons)
        self.assertEqual(world.snapshot, snapshot)
        self.assertTrue({"R1", "FIX-J2"} <= {lock.resource_id for lock in snapshot.locks})
        self.assertEqual(
            current.preview(decision.candidate).events[: len(snapshot.events)], snapshot.events
        )

    def test_nominal_no_tail_returns_wait_without_actual_retry(self):
        current = problem(fixture(), window=0.25)
        policy = FrozenJointPolicy(current)
        with patch.object(current, "verify", side_effect=AssertionError("no actual search")):
            decision = policy.decide(current, self.options)
        self.assertEqual(decision.status, "WAIT")
        self.assertEqual(decision.safety.reasons, ("NO_NOMINAL_TAIL",))


if __name__ == "__main__":
    unittest.main()
