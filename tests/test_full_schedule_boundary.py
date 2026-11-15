"""Real admission at a replay boundary must tolerate only clock roundoff."""

import math
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_simulation_production import configuration as base

from adaptive_hrc_scheduling.full_schedule import (
    FullSchedulePolicy,
    configuration,
    frozen_prefix_unchanged,
)
from adaptive_hrc_scheduling.planning.production import choose, planning_input
from adaptive_hrc_scheduling.production_backend import ProductionBackend


class FullScheduleBoundaryTests(unittest.TestCase):
    def setup_policy(self, offset):
        world = ProductionBackend(configuration(base()))
        now = 0.5344861111111108  # Observed native boundary in v1.4.0 acceptance.
        world.s = replace(world.s, time_h=now)
        value = planning_input(world.config, world.observe(), 10000)
        plan = choose(world.config, value)
        self.assertTrue(plan.commands)
        command = replace(plan.commands[0], issued_sim_h=offset(now))
        policy = FullSchedulePolicy(SimpleNamespace(world=world))
        policy.dirty = None
        policy.queue = [SimpleNamespace(plan=replace(plan, commands=(command,)))]
        return world, value, command, policy

    def decide(self, world, value, policy):
        return policy.decide(value, world.snapshot(), (), sequence=1, rejected=())

    def test_roundoff_rebinds_to_observation_and_real_dispatch_starts(self):
        for offset in (
            lambda now: 0.5344861111111111,
            lambda now: math.nextafter(now, -math.inf),
            lambda now: now,
        ):
            with self.subTest(offset=offset):
                world, value, original, policy = self.setup_policy(offset)
                result = self.decide(world, value, policy)
                self.assertEqual(len(result.commands), 1, result.reason)
                issued = result.commands[0]
                self.assertEqual(issued.issued_sim_h, value.observation.sampled_h)
                self.assertEqual(issued.expected_revision, world.s.revision)
                self.assertIsNone(policy.dirty)
                self.assertEqual(policy.queue[0].plan.commands[0], original)
                self.assertEqual(world.dispatch(issued).kind, "STARTED")

    def test_material_drift_remains_wait_or_replan(self):
        for delta in (-1e-5, 1e-5):
            with self.subTest(delta=delta):
                world, value, _, policy = self.setup_policy(lambda now: now + delta)
                result = self.decide(world, value, policy)
                self.assertFalse(result.commands)
                self.assertEqual(policy.dirty, "EXECUTION_DEVIATION" if delta < 0 else None)

    def test_other_admission_failures_still_require_replan(self):
        world, value, original, policy = self.setup_policy(
            lambda now: math.nextafter(now, math.inf)
        )
        invalid = replace(original, operation_id="MISSING-OPERATION", service=None)
        policy.queue[0].plan = replace(policy.queue[0].plan, commands=(invalid,))
        result = self.decide(world, value, policy)
        self.assertFalse(result.commands)
        self.assertEqual(policy.dirty, "EXECUTION_DEVIATION")

    def test_replan_freezes_actual_start_after_roundoff_boundary_dispatch(self):
        world, value, _, policy = self.setup_policy(lambda now: 0.5344861111111111)
        issued = self.decide(world, value, policy).commands[0]
        receipt = world.dispatch(issued)
        self.assertEqual(receipt.kind, "STARTED")
        old = dict(
            command_id=issued.id,
            start_h=0.5344861111111111,
            end_h=1.034486111111111,
            operation_id=issued.operation_id,
            roles=[],
        )
        actual = dict(old, start_h=receipt.occurred_sim_h, end_h=1.0344861111111108)
        self.assertTrue(frozen_prefix_unchanged([old], [actual], world.events))
        # Neither the old prediction nor another nearby float is the receipt.
        for start in (old["start_h"], math.nextafter(actual["start_h"], math.inf)):
            self.assertFalse(
                frozen_prefix_unchanged([old], [dict(actual, start_h=start)], world.events)
            )
        for field, replacement in (
            ("end_h", 2),
            ("operation_id", "OTHER"),
            ("roles", [{"person_id": "OTHER"}]),
        ):
            self.assertFalse(
                frozen_prefix_unchanged([old], [dict(actual, **{field: replacement})], world.events)
            )
        self.assertFalse(frozen_prefix_unchanged([dict(old, start_h=0.5)], [actual], world.events))


if __name__ == "__main__":
    unittest.main()
