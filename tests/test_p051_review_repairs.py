"""P051 recovery boundaries and truthful complete-plan projection."""

import copy
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from build_simulation_production import configuration as base
from p051_desktop.gantt import ScheduleReader, enrich
from test_session_lifecycle import request, setup_session

from adaptive_hrc_scheduling.contracts.codec import as_data
from adaptive_hrc_scheduling.full_schedule import FullSchedulePolicy, intervals


class RecoveryBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s = setup_session(Path(self.tmp.name) / "run", until=3)
        self.s.policy = FullSchedulePolicy(self.s)
        self.s.spec["clock"].update(simulation_rate=1000, idle_step_h=0.1)

    def test_only_accepted_future_recovery_unlocks_blocked_clock(self):
        s = self.s
        self.assertIsNone(s.policy.recovery_boundary())
        s.submit(request(s, 1, "DEVICE_FAIL", "FORK-01", dict(reason="TEST")))
        s.boundary()
        s.submit(
            request(
                s,
                2,
                "DEVICE_REPAIR",
                "FORK-01",
                dict(repair_evidence_id="ML-METHOD"),
                time_rule="AT_SIM_H",
                requested_sim_h=1,
            )
        )
        s.boundary()
        self.assertEqual(s.policy.recovery_boundary(), 1)
        for _ in range(12):
            if s.world.s.time_h >= 1:
                break
            self.assertIsNone(s.lifecycle.advance(1, idle=True))
            if s.world.s.time_h < 1:
                self.assertNotEqual(s.receipts[-1]["status"], "APPLIED")
            s.boundary()
        self.assertEqual(s.world.s.time_h, 1)
        self.assertEqual(s.receipts[-1]["status"], "APPLIED")
        self.assertIsNone(s.policy.recovery_boundary())

    def test_future_non_recovery_request_does_not_bypass_pause(self):
        s = self.s
        s.submit(
            request(
                s,
                1,
                "ORDER_CANCEL",
                "ORDER-1",
                dict(reason="TEST"),
                time_rule="AT_SIM_H",
                requested_sim_h=1,
            )
        )
        s.boundary()
        self.assertIsNone(s.policy.recovery_boundary())

    def test_unaccepted_tiny_step_keeps_drain_guard(self):
        self.assertEqual(self.s.lifecycle.advance(math.nextafter(0, 1), idle=True), "DRAIN_BLOCKED")

    def test_failed_calls_do_not_report_permanent_planning(self):
        policy = self.s.policy
        policy.calls = 3
        policy.version = 2
        policy.history = [{"status": "ADOPTED"}, {"status": "NO_FEASIBLE_PLAN"}]
        self.assertTrue(policy.reference()["planning"])
        policy.history.append({"status": "ADOPTED"})
        self.assertFalse(policy.reference()["planning"])


class CompletePlanProjectionTests(unittest.TestCase):
    def test_blocked_reference_is_retained_and_static_devices_are_visible(self):
        config = as_data(base())
        op = next(o for o in config["operations"] if o["equipment"])
        row = dict(
            command_id="C",
            operation_id=op["id"],
            activity_id=op["activity_id"],
            product_id=op["product_id"],
            roles=[],
            start_h=2,
            end_h=4,
            command=dict(mode_id="MOVE", attempt=0, service=None),
        )
        reader = ScheduleReader()
        self.addCleanup(reader.close)
        reader.verified["K"] = dict(
            format="P051-FULL-SCHEDULE-1", version=1, plan_id="P", intervals=[row]
        )
        original = copy.deepcopy(reader.verified)
        rows = reader.read_full(None, dict(artifact_sha256="K", failure="DEVICE_FAILED"))
        self.assertEqual(rows[0]["proposal_state"], "RETAINED_BLOCKED")
        displayed = enrich(dict(rows=rows), config, [])["rows"][0]
        self.assertEqual(displayed["equipment"], op["equipment"])
        self.assertEqual((displayed["start_h"], displayed["end_h"]), (2, 4))
        self.assertEqual(reader.verified, original)
        self.assertEqual(
            reader.read_full(None, dict(artifact_sha256="K"))[0]["proposal_state"], "CURRENT_PLAN"
        )

    def test_interruption_ends_only_the_interrupted_segment(self):
        from test_dynamic_workforce import service_command

        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        s = setup_session(Path(folder.name) / "run")
        world = s.world
        command = service_command(world, "W1")
        started = world.dispatch(command)
        self.assertEqual(started.kind, "STARTED")
        s.submit(
            request(
                s, 1, "PERSON_ABSENT", "W1", dict(reason="TEST", safety_policy="HOLD_AND_VERIFY")
            )
        )
        s.boundary()
        rows = intervals(SimpleNamespace(snapshot=world.snapshot()))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["end_status"], "INTERRUPTED")
        self.assertEqual(rows[0]["end_h"], 0)
        self.assertFalse(any(e.kind == "COMPLETED" for e in world.events))


if __name__ == "__main__":
    unittest.main()
