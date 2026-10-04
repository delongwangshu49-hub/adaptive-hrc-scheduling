"""Transport/lifecycle tests. The controlled port is not real Isaac evidence."""

import unittest
from dataclasses import replace

from test_logistics import fixture

from adaptive_hrc_scheduling.backends.isaac_adapter import IsaacAdapter
from adaptive_hrc_scheduling.contracts.codec import ContractError
from adaptive_hrc_scheduling.domain import logistics as m
from adaptive_hrc_scheduling.logistics_checker import check_run


class ControlledPort:
    def reset(self, *args):
        self.starts = []
        self.fault = None

    def preflight(self, command):
        if self.fault == "preflight":
            raise ContractError("ACTUAL_PERSON_MISSING")

    def start(self, run):
        self.starts.append(run)

    def step(self, *args):
        if self.fault == "running":
            raise ContractError("ACTUAL_OBSTACLE")
        return None

    def world_event(self, event):
        pass


def adapter():
    a = IsaacAdapter(fixture.configuration(synthetic=True), ControlledPort())
    w = a.world
    for i, (kind, ev) in enumerate(
        (("ARRIVAL", "RECEIVE"), ("IDENTIFY", "ML-RELEASE"), ("RELEASE", "ML-RELEASE"))
    ):
        a.apply_world(
            m.WorldEvent(
                "W" + str(i), w.run_id, w.epoch, 0, kind, "RAW", "PRODUCT-1", 0, "PASS", ev
            )
        )
    return a


def proof(a, c):
    w = a.world
    return m.Readback(
        "ISAAC_USD",
        w.run_id,
        w.epoch,
        c.id,
        w.s.time_h,
        "RAW",
        "STEEL",
        "STEEL",
        (6, 14, 0.8),
        (m.PersonPosition("P1", "STEEL"), m.PersonPosition("QA1", "STEEL")),
        True,
        True,
        True,
        True,
        True,
        False,
        "USD-SAMPLE",
        1,
    )


class AdapterTests(unittest.TestCase):
    def test_send_pause_and_duplicate_do_not_complete(self):
        a = adapter()
        w = a.world
        c = fixture.command(w, "TAKE-IN")
        first = a.dispatch(c)
        self.assertEqual(first.kind, "STARTED")
        self.assertEqual(a.dispatch(c), first)
        self.assertEqual(len(a.port.starts), 1)
        a.advance(3600, playing=False)
        self.assertEqual(w.s.time_h, 0)
        a.advance(w.s.running[0].earliest_end_h * 3600)
        self.assertFalse(w.s.completed)
        p = proof(a, c)
        receipt = a.feedback(p)
        self.assertEqual(receipt.kind, "COMPLETED")
        state = w.s
        self.assertEqual(a.feedback(p), receipt)
        self.assertEqual(w.s, state)
        self.assertEqual(check_run(w.config, w.snapshot()).status, "PASS")

    def test_port_preflight_rejection_has_no_ownership_or_start(self):
        a = adapter()
        a.port.fault = "preflight"
        receipt = a.dispatch(fixture.command(a.world, "TAKE-IN"))
        self.assertEqual(receipt.kind, "REJECTED")
        self.assertFalse(a.world.s.owners or a.world.s.running or a.port.starts)

    def test_actual_failure_keeps_commitments_and_observation_delay(self):
        a = adapter()
        w = a.world
        a.dispatch(fixture.command(w, "TAKE-IN"))
        a.port.fault = "running"
        a.advance(5)
        self.assertEqual(w.events[-1].kind, "EXCEPTION")
        self.assertTrue(w.s.owners)
        self.assertIsNone(a.deliver(delay_h=0.01))
        a.advance(36)
        a.deliver()
        self.assertEqual(a.ledger.state, w.s)
        self.assertEqual(check_run(w.config, w.snapshot()).status, "PASS")

    def test_early_foreign_or_old_callbacks_do_not_commit(self):
        a = adapter()
        w = a.world
        c = fixture.command(w, "TAKE-IN")
        a.dispatch(c)
        p = proof(a, c)
        with self.assertRaisesRegex(ContractError, "EARLY_OR_STALE"):
            a.feedback(p)
        with self.assertRaisesRegex(ContractError, "PROOF_SOURCE"):
            a.feedback(replace(p, source="LIGHT_EXECUTOR"))
        a.reset()
        state = a.world.s
        self.assertEqual(a.feedback(p), "STALE_EPOCH")
        self.assertEqual(a.world.s, state)
        with self.assertRaisesRegex(ContractError, "INVALID_SIMULATION_DELTA"):
            a.advance(-1)


if __name__ == "__main__":
    unittest.main()
