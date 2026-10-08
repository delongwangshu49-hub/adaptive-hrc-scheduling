"""Complete nominal production windows must survive independent reconstruction."""

import sys
import unittest
from dataclasses import replace
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_simulation_production import configuration

from adaptive_hrc_scheduling.algorithms.simulation_joint import SimulationJointProblem
from adaptive_hrc_scheduling.production_backend import ProductionBackend


class SimulationJointTests(unittest.TestCase):
    def test_full_window_reconstruction_and_truncation_rejected(self):
        c = configuration()
        w = ProductionBackend(c)
        problem = SimulationJointProblem(c, w.observe(), w.snapshot(), end_h=0.5)
        result = problem.initial(perf_counter() + 30)
        self.assertIsNotNone(result.candidate, result.reasons)
        checked = problem.verify(result.candidate)
        self.assertTrue(checked.valid, checked.reasons)
        bad = replace(result.candidate, steps=result.candidate.steps[:-1])
        self.assertFalse(problem.verify(bad).valid)
        snapshot, rows = problem.preview(result.candidate)
        self.assertEqual(snapshot.state.time_h, 0.5)
        self.assertEqual(snapshot.state.gates, ())
        self.assertEqual(snapshot.state.receive_permits, ())
        self.assertTrue(all(not x.arrived for x in snapshot.state.lots))
        self.assertGreater(len(rows), 1)

    def test_fixed_modes_and_five_neighborhoods(self):
        c = configuration()
        w = ProductionBackend(c)
        for mode in ("H", "HR-seq"):
            problem = SimulationJointProblem(
                c, w.observe(), w.snapshot(), end_h=0.5, fixed_mode=mode
            )
            genes = problem.genes()
            self.assertTrue(all(v == mode for _, v in genes.modes))
            self.assertEqual({a for a, _ in genes.order}, {a.id for a in c.core_activities})
            self.assertGreater(len(genes.crews), len(genes.modes))
            self.assertEqual(
                set(problem.mutable(None)), {"MODE", "CREW", "ORDER", "START_SLOT", "REST"}
            )
