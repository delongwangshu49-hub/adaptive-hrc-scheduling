"""S09 r2: source release faults and calendar partition regressions."""

import math
import random
import unittest
from dataclasses import replace

from test_event_backend import (
    allocation,
    backend,
    command,
    config,
    finish,
    operation,
    prepared_assembly,
    start,
)

from adaptive_hrc_scheduling.contracts.messages import WorldEvent

EARLY_SPLITS = (
    0.9318793748042817,
    1.3014819896906704,
    1.474256627819626,
    1.5010294557803932,
    1.7297303961646582,
    2.2859853267725425,
)
CROSSING_SPLITS = (
    0.36540211453714627,
    1.0064989389811243,
    1.6534043075156033,
    1.8079733892749712,
    1.8679419121244432,
    1.9700306758876893,
    2.025652820613957,
    3.44293236937797,
)


class SourceReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        e = backend()
        prepared_assembly(e)
        cls.ready = e.now

    def world(self, offset, *, resource="AS1_X", release=False, cfg=None):
        e = backend(
            (
                WorldEvent("source.failure", self.ready + offset, "failure", resource, release),
                WorldEvent("source.repair", self.ready + 4, "repair", resource, None),
            ),
            cfg=cfg,
        )
        prepared_assembly(e)
        op = operation(e, "WELD")
        e.select_process(op.id, "mode.WELD.R", allocation(e, "WELD", "R", "W2").id)
        return e, op.transfers[0].id

    def dispatch(self, e, phase, action="start"):
        return start(e, "WELD", phase, "R", transfer=True, action=action)

    def assert_source_held(self, e):
        self.assertEqual(e._position("J1.A1_out").location_id, "AS1")
        self.assertTrue(any(x.resource_id == "AS1_X" for x in e.snapshot.locks))

    def test_fault_before_preposition_cannot_unlock_source(self):
        e, _ = self.world(0)
        before = e.snapshot
        self.assertFalse(self.dispatch(e, "preposition").accepted)
        self.assertEqual(e.snapshot, before)
        self.assert_source_held(e)
        e.advance(self.ready + 4)
        self.assertTrue(self.dispatch(e, "preposition").accepted)

    def test_fault_between_preposition_and_rig_blocks_rig(self):
        e, gid = self.world(1)
        self.assertTrue(self.dispatch(e, "preposition").accepted)
        finish(e, gid)
        self.assertFalse(self.dispatch(e, "rig").accepted)
        self.assert_source_held(e)

    def test_source_fault_pauses_preposition_and_rig_until_repair(self):
        for offset, phase in ((0.5, "preposition"), (1.5, "rig")):
            with self.subTest(phase=phase):
                e, gid = self.world(offset)
                self.assertTrue(self.dispatch(e, "preposition").accepted)
                if phase == "rig":
                    finish(e, gid)
                    self.assertTrue(self.dispatch(e, "rig").accepted)
                e.advance(self.ready + offset)
                progress = e._history(gid)[-1]
                self.assertEqual(progress.status, "paused")
                self.assertAlmostEqual(progress.remaining_base_min, 0.5, places=12)
                self.assert_source_held(e)
                self.assertFalse(any(x.resource_id == "W1" for x in e.snapshot.locks))
                self.assertFalse(self.dispatch(e, phase, "resume").accepted)
                e.advance(self.ready + 4)
                self.assertTrue(self.dispatch(e, phase, "resume").accepted)
                self.assertAlmostEqual(e.completion_time(gid), self.ready + 4.5, places=12)
                finish(e, gid)
                if phase == "rig":
                    self.assertEqual(e._position("J1.A1_out").location_id, "G1")
                    self.assertFalse(any(x.resource_id == "AS1_X" for x in e.snapshot.locks))

    def test_safe_unlock_flag_permits_failed_source_fixture_release(self):
        e, gid = self.world(0, release=True)
        for phase in ("preposition", "rig"):
            self.assertTrue(self.dispatch(e, phase).accepted)
            finish(e, gid)
        self.assertEqual(e._position("J1.A1_out").location_id, "G1")

    def test_unheld_fixture_at_source_does_not_block_transport(self):
        c = config()
        fixture = next(r for r in c.resources if r.id == "AS1_X")
        c = replace(c, resources=c.resources + (replace(fixture, id="AS1_UNUSED"),))
        e, gid = self.world(1.5, resource="AS1_UNUSED", cfg=c)
        for phase in ("preposition", "rig"):
            self.assertTrue(self.dispatch(e, phase).accepted)
            finish(e, gid)
        self.assertEqual(e._position("J1.A1_out").location_id, "G1")
        self.assertFalse(e.interruptions)

    def test_source_fault_at_or_after_rig_completion_cannot_stop_move(self):
        for offset in (2, 2.5):
            with self.subTest(offset=offset):
                e, gid = self.world(offset)
                for phase in ("preposition", "rig", "move"):
                    self.assertTrue(self.dispatch(e, phase).accepted)
                    finish(e, gid)
                self.assertEqual(e._history(gid)[-1].status, "completed")
                self.assertFalse(e.interruptions)


class CalendarPartitionTests(unittest.TestCase):
    def bracket(self, events=()):
        e = backend(events)
        self.assertTrue(start(e, "BRACKET", "work", worker="W2").accepted)
        return e, operation(e, "BRACKET").process_group_id

    def test_audit_sequences_cannot_complete_early_or_reject_legal_step(self):
        for splits in (EARLY_SPLITS, CROSSING_SPLITS):
            with self.subTest(splits=splits):
                e, gid = self.bracket()
                end = e.completion_time(gid)
                for at in (*splits, math.nextafter(end, 0)):
                    e.advance(at)
                    self.assertEqual(e._history(gid)[-1].status, "running")
                    self.assertGreater(e._history(gid)[-1].remaining_base_min, 0)
                e.advance(end)
                self.assertEqual(e._history(gid)[-1].completed_min, end)

    def test_split_and_unsplit_fault_have_same_remaining_work_and_resume(self):
        initial, gid = self.bracket()
        end = initial.completion_time(gid)
        fault = math.nextafter(end, 0)
        records = []
        for splits in ((), EARLY_SPLITS, CROSSING_SPLITS):
            e, gid = self.bracket(
                (
                    WorldEvent("worker.failure", fault, "failure", "W2", None),
                    WorldEvent("worker.repair", end, "repair", "W2", None),
                )
            )
            for at in (*splits, fault):
                e.advance(at)
            p = e._history(gid)[-1]
            self.assertEqual(p.status, "paused")
            self.assertEqual(len(e.interruptions), 1)
            records.append((p.remaining_base_min, e.interruptions))
            e.advance(end)
            self.assertTrue(start(e, "BRACKET", "work", worker="W2", action="resume").accepted)
            finish(e, gid)
            self.assertTrue(e._done(gid, "work"))
        self.assertEqual(records[0], records[1])
        self.assertEqual(records[0], records[2])

    def test_exact_completion_precedes_same_time_fault_after_many_splits(self):
        initial, gid = self.bracket()
        end = initial.completion_time(gid)
        e, gid = self.bracket((WorldEvent("worker.failure", end, "failure", "W2", None),))
        for at in (*EARLY_SPLITS, math.nextafter(end, 0), end):
            e.advance(at)
        self.assertEqual(e._history(gid)[-1].completed_min, end)
        self.assertFalse(e.interruptions)

    def test_seeded_partitions_match_direct_remaining_work(self):
        direct, gid = self.bracket()
        end = direct.completion_time(gid)
        at = math.nextafter(end, 0)
        direct.advance(at)
        for seed in (0, 1, 16, 42, 109, 149):
            with self.subTest(seed=seed):
                e, gid = self.bracket()
                rng = random.Random(seed)
                for t in sorted(rng.uniform(0, at) for _ in range(15)):
                    e.advance(t)
                e.advance(at)
                self.assertEqual(e._history(gid), direct._history(gid))

    def test_cleanup_split_fault_preserves_same_positive_remaining_time(self):
        cases = []
        fault = math.nextafter(1.0, 0)
        for splits in ((), (0.1, 0.31, 0.69)):
            e = backend(
                (
                    WorldEvent("cancel", 0, "cancel", "J1", None),
                    WorldEvent("worker.failure", fault, "failure", "W1", None),
                    WorldEvent("worker.repair", 1.0, "repair", "W1", None),
                )
            )
            self.assertTrue(e.dispatch(command(e, "cleanup", material="J1.C1.raw")).accepted)
            for at in (*splits, fault):
                e.advance(at)
            c = e.cleanup_records[0]
            self.assertEqual(c.status, "paused")
            self.assertGreater(c.remaining_min, 0)
            cases.append(c.remaining_min)
        self.assertEqual(cases[0], cases[1])


if __name__ == "__main__":
    unittest.main()
