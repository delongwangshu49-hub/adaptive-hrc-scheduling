"""S18 production rejection and fixed-domain no-update plumbing only."""

import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_production_contracts import Builder

from adaptive_hrc_scheduling.algorithms.joint_production import (
    FrozenProductionPolicy,
    joint_production_boundary,
)
from adaptive_hrc_scheduling.algorithms.lns import Options, Verification
from adaptive_hrc_scheduling.algorithms.production_lns import ProductionProblem
from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.planning.production import planning_input
from adaptive_hrc_scheduling.production_backend import ProductionBackend


def problem(world):
    obs = world.observe()
    world.deliver()
    return ProductionProblem(
        world.config, planning_input(world.config, obs, 10000), world.snapshot()
    )


class ProductionJointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = Builder().configuration()

    def setUp(self):
        self.world = ProductionBackend(self.config)
        self.options = Options(seed=18, iterations=1, repair_trials=2, wall_seconds=30)

    def test_joint_gate_returns_no_command_and_preserves_protected_state(self):
        pr = problem(self.world)
        before = self.world.snapshot()
        with patch("adaptive_hrc_scheduling.algorithms.joint_production.search") as searched:
            gate = joint_production_boundary(pr)
        searched.assert_not_called()
        self.assertEqual(gate.status, "BLOCKED")
        self.assertIsNone(gate.candidate)
        self.assertIn("S15_HR_SEQUENCE_MAPPING_ABSENT", gate.reasons)
        self.assertEqual(self.world.snapshot(), before)

    def test_fixed_control_uses_real_walk_service_and_independent_both_audits(self):
        pr = problem(self.world)
        decision = FrozenProductionPolicy(pr).decide(pr, self.options)
        self.assertEqual(decision.status, "SHIELDED", decision.safety.reasons)
        self.assertTrue(pr.verify(decision.candidate).valid)
        command = decision.candidate.commands[0]
        self.assertIsNotNone(command.service)
        self.assertEqual(command.service.operation.action, "WALK")
        self.assertEqual(decision.proposal.options, self.options)
        self.assertEqual(self.world.s.running, ())

    def test_observed_route_failure_cannot_change_frozen_choice(self):
        anchor = problem(self.world)
        policy = FrozenProductionPolicy(anchor)
        normal = policy.decide(anchor, self.options)
        event = m.WorldEvent(
            "FAILURE",
            self.world.run_id,
            0,
            0,
            "FAILURE",
            "GROUND-SPINE",
            "PRODUCT-1",
            0,
            "PASS",
            "ML-METHOD",
        )
        self.world.apply_world(event)
        current = problem(self.world)
        failed = policy.decide(current, self.options)
        self.assertEqual(failed.proposal.best, normal.proposal.best)
        self.assertEqual(failed.proposal.best_score, normal.proposal.best_score)
        self.assertEqual(failed.status, "WAIT")
        self.assertFalse(failed.safety.valid)
        self.assertIsNone(failed.candidate)
        self.assertEqual(self.world.s.running, ())

    def test_shield_failure_never_researches_or_replaces_nominal_cache(self):
        current = problem(self.world)
        policy = FrozenProductionPolicy(current)
        normal = policy.decide(current, self.options)
        with patch.object(
            current, "verify", return_value=Verification(False, None, ("AUDIT",))
        ) as verify:
            failed = policy.decide(current, self.options)
        self.assertEqual(verify.call_count, 1)
        self.assertEqual(failed.status, "WAIT")
        self.assertEqual(failed.proposal.best, normal.proposal.best)

    def test_common_budget_and_anchor_history_required(self):
        anchor = problem(self.world)
        policy = FrozenProductionPolicy(anchor)
        changed = ProductionProblem(
            self.config, replace(anchor.value, budget_ms=100), anchor.prefix
        )
        with self.assertRaisesRegex(ValueError, "COMMON_PRODUCTION"):
            policy.decide(changed, self.options)
        event = m.WorldEvent(
            "FAIL", self.world.run_id, 0, 0, "FAILURE", "R1", "PRODUCT-1", 0, "PASS", "ML-METHOD"
        )
        self.world.apply_world(event)
        later = FrozenProductionPolicy(problem(self.world))
        with self.assertRaisesRegex(ValueError, "ANCHOR_ACTUAL_PRODUCTION"):
            later.decide(anchor, self.options)

    def test_forged_production_prefix_fails_before_boundary_or_search(self):
        pr = problem(self.world)
        with self.assertRaises(ValueError):
            ProductionProblem(
                self.config,
                pr.value,
                replace(pr.prefix, state=replace(pr.prefix.state, positions=())),
            )


if __name__ == "__main__":
    unittest.main()
