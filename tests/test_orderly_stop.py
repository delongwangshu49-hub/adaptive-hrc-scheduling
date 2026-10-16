"""Actual production stop boundaries, preserved facts and independent audits."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_simulation_production import configuration

from adaptive_hrc_scheduling.contracts.codec import as_data
from adaptive_hrc_scheduling.control.production_loop import run
from adaptive_hrc_scheduling.production_backend import ProductionBackend


class OrderlyStopTests(unittest.TestCase):
    def test_stop_before_dispatch_preserves_unfinished_order(self):
        backend = ProductionBackend(configuration())
        result = run(backend, orderly_stop=lambda w: True)
        self.assertEqual(result.manifest["termination"], "ORDERLY_STOPPED")
        self.assertEqual(result.snapshot.events, ())
        self.assertEqual(result.manifest["received"], 0)
        self.assertEqual(result.audit.status, "PASS")
        self.assertEqual(result.decision_audit.status, "PASS")

    def test_started_work_drains_without_new_dispatch_or_world_input(self):
        backend = ProductionBackend(configuration())
        stop_at = []

        def hook(engine, phase):
            if phase == "after_dispatch" and engine.s.running and not stop_at:
                stop_at.append((len(engine.events), tuple(engine.s.running)))

        result = run(backend, execution_hook=hook, orderly_stop=lambda w: bool(stop_at))
        self.assertEqual(result.manifest["termination"], "ORDERLY_STOPPED")
        count, started = stop_at[0]
        self.assertTrue(started)
        self.assertFalse(result.snapshot.state.running)
        self.assertTrue(
            all(
                e.kind not in ("ACCEPTED", "STARTED", "WORLD")
                for e in result.snapshot.events[count:]
            )
        )
        self.assertTrue(
            all(r.command.operation_id in result.snapshot.state.completed for r in started)
        )
        self.assertEqual(result.manifest["received"], 0)
        self.assertFalse(any(p.cancelled for p in result.snapshot.state.products))
        self.assertEqual(result.audit.status, "PASS")
        self.assertEqual(result.decision_audit.status, "PASS")

    def test_hold_is_retained_and_cannot_be_reported_stopped(self):
        backend = ProductionBackend(configuration())
        held = []

        def hook(engine, phase):
            if phase == "after_dispatch" and engine.s.running and not held:
                held.append(engine.s.running[0].command.id)
                engine.exception(held[0], "STOP_TEST_ACTUAL_EXCEPTION")

        result = run(backend, execution_hook=hook, orderly_stop=lambda w: bool(held))
        self.assertEqual(result.manifest["termination"], "ORDERLY_STOP_BLOCKED")
        self.assertEqual([r.command.id for r in result.snapshot.state.running], held)
        self.assertEqual(result.snapshot.state.running[0].status, "EXCEPTION")
        self.assertEqual(result.audit.status, "PASS")
        self.assertEqual(result.decision_audit.status, "PASS")

    def test_absent_stop_does_not_change_default_prefix(self):
        config = configuration()
        original = run(ProductionBackend(config), stop_condition=lambda w: w.s.time_h >= 1)
        controlled = run(
            ProductionBackend(config),
            stop_condition=lambda w: w.s.time_h >= 1,
            orderly_stop=lambda w: False,
        )
        self.assertEqual(as_data(original), as_data(controlled))


if __name__ == "__main__":
    unittest.main()
