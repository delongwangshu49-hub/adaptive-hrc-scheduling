"""Regression counterexamples for the four S15 post-release audit findings."""

import copy
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_production_contracts import Builder

from adaptive_hrc_scheduling.contracts.codec import ContractError
from adaptive_hrc_scheduling.control.production_decisions import check_decisions, record
from adaptive_hrc_scheduling.control.production_loop import Decision
from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.production_audit_geometry import walk_collision
from adaptive_hrc_scheduling.production_backend import ProductionBackend
from adaptive_hrc_scheduling.production_checker import check_run
from adaptive_hrc_scheduling.production_geometry import route
from adaptive_hrc_scheduling.production_navigation import walk, walk_blocker
from adaptive_hrc_scheduling.production_pedestrians import fork_walk_phases, walk_yaw


def command(world, person, target, points=None):
    config = world.config
    source = world._position(person).location
    rt = route(config, "REPAIR-WALK-" + str(world.s.revision), source, target, None, person=person)
    if points is None:
        points = walk(config, world.s, person, source, target)
    rt = replace(rt, points=tuple(m.Point(*p) for p in points))
    op = m.Operation(
        "REPAIR-WALK-" + str(world.s.revision),
        "PRODUCT-1",
        "REPAIR-WALK",
        "WALK",
        "WALK",
        (),
        (m.Role(person, world.people[person].qualifications[0]),),
        (m.PersonPosition(person, source),),
        (),
        source,
        target,
        rt.id,
        person,
        (),
        (),
        0,
        0,
        0,
        ("ML-METHOD",),
        (),
        None,
        None,
        None,
    )
    return m.DispatchCommand(
        "S15-PROD-1.0",
        config.id,
        world.config_hash,
        world.run_id,
        0,
        "REPAIR-WALK-" + str(world.s.revision),
        "PRODUCT-1",
        op.activity_id,
        op.id,
        0,
        0,
        "MOVE",
        world.s.time_h,
        world.s.revision,
        (m.RoleBinding(person, person),),
        service=m.Service(op, rt),
    )


class PedestrianRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = Builder().configuration()

    def test_whole_fork_is_no_longer_excluded_for_p1(self):
        world = ProductionBackend(self.config)
        cmd = command(world, "P1", "CONTROL-SUPPORT-MEP-RECEIVE-P1")
        rt = cmd.service.route
        # A valid route is corrupted to cross the stationary rear guard.
        points = (rt.points[0], m.Point(6, 4.3, 0), rt.points[-1])
        bad = replace(cmd, service=replace(cmd.service, route=replace(rt, points=points)))
        self.assertIn("DECLARED_WALK_COLLISION", world.dispatch(bad).reason)
        self.assertIsNotNone(
            walk_collision(self.config, world.s, bad.service.operation, bad.service.route)
        )

    def test_independent_audit_catches_executor_collision_predicate_bypass(self):
        world = ProductionBackend(self.config)
        cmd = command(world, "E1", "CONTROL-SUPPORT-MEP-RECEIVE-E1")
        rt = cmd.service.route
        bad = replace(
            cmd,
            service=replace(
                cmd.service,
                route=replace(rt, points=(rt.points[0], m.Point(15, 12, 0), rt.points[-1])),
            ),
        )
        self.assertIn("DECLARED_WALK_COLLISION", world.dispatch(bad).reason)
        world = ProductionBackend(self.config)
        with patch(
            "adaptive_hrc_scheduling.production_navigation.clear_segment", return_value=True
        ):
            self.assertEqual(world.dispatch(bad).kind, "STARTED")
        world.advance(world.s.running[0].earliest_end_h)
        report = check_run(self.config, world.snapshot())
        self.assertEqual(report.status, "INVALID")
        self.assertTrue(any("WALK_COLLISION:CUT1" in f.reason for f in report.findings))

    def test_legal_boarding_and_alighting_preserve_full_body_and_audit(self):
        world = ProductionBackend(self.config)
        for target in ("RECEIVE", "CONTROL-P1"):
            cmd = command(world, "P1", target)
            self.assertEqual(world.dispatch(cmd).kind, "STARTED")
            world.advance(world.s.running[0].earliest_end_h)
        self.assertEqual(check_run(self.config, world.snapshot()).status, "PASS")

    def test_side_pose_requires_exact_complete_access_path(self):
        points = ((6, 4.75, 0.2), (6, 4.5, 0.2), (4.5, 4.5, 0.2), (4.5, 4.5, 0))
        phases, _ = fork_walk_phases(points, (6, 7, 0), leaving=True)
        self.assertEqual(walk_yaw(points, (5, 4.5, 0.2), phases), 90)
        self.assertEqual(walk_yaw(points, (5, 4.5, 0.2), {}), 0)
        bad = ((6, 4.3, 0.2), *points[1:])
        phases, _ = fork_walk_phases(bad, (6, 7, 0), leaving=True)
        self.assertFalse(phases)
        world = ProductionBackend(self.config)
        self.assertIsNotNone(walk_blocker(self.config, world.s, "P1", "RECEIVE", "CONTROL-P1", bad))

    def test_turn_sweep_rejects_corner_outside_both_axis_aligned_poses(self):
        world = ProductionBackend(self.config)
        cmd = command(world, "P1", "RECEIVE")
        obstacle = [("TURN-CORNER", (6.44, 4.04, 0.3), (6.46, 4.06, 0.4))]
        points = tuple((p.x, p.y, p.z) for p in cmd.service.route.points)
        with patch("adaptive_hrc_scheduling.production_navigation.boxes", return_value=obstacle):
            self.assertEqual(
                walk_blocker(
                    self.config, world.s, "P1", cmd.service.operation.location, "RECEIVE", points
                ),
                "TURN-CORNER",
            )
        with patch(
            "adaptive_hrc_scheduling.production_audit_geometry.boxes", return_value=obstacle
        ):
            self.assertEqual(
                walk_collision(self.config, world.s, cmd.service.operation, cmd.service.route),
                "TURN-CORNER",
            )


class DecisionRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = Builder().configuration()
        world = ProductionBackend(cls.config)
        obs = world.observe()
        cmd = command(world, "E1", "CONTROL-SUPPORT-MEP-RECEIVE-E1")
        plan = m.Plan("S15-PROD-1.0", cls.config.id, obs.id, (cmd,), "CANDIDATE", "TEST")
        receipt = world.dispatch(cmd)
        assert receipt.kind == "STARTED", receipt.reason
        first = record(Decision(obs, plan, (), receipt.id))
        world.advance(world.s.running[0].earliest_end_h)
        obs = world.observe()
        last = record(
            Decision(
                obs, m.Plan("S15-PROD-1.0", cls.config.id, obs.id, (), "WAIT", "TEST_END"), (), None
            )
        )
        cls.snapshot, cls.rows = world.snapshot(), [first, last]

    def test_genuine_observation_plan_receipt_prefix_passes(self):
        self.assertEqual(check_run(self.config, self.snapshot).status, "PASS")
        report = check_decisions(self.config, self.snapshot, self.rows)
        self.assertEqual(report.status, "PASS", report.findings)

    def test_identical_mutation_in_both_backends_cannot_replace_causality(self):
        for field, value in (
            ("state_revision", 999999),
            ("sampled_h", 999999),
            ("observation_id", "OBS-NONEXISTENT"),
            ("receipt_id", "NONEXISTENT"),
            ("state_sha256", "0" * 64),
            ("event_ids_sha256", "0" * 64),
            ("event_count", 999999),
            ("received_h", 1),
            ("rejected_parents", ["UNSEEN"]),
        ):
            with self.subTest(field=field):
                left = copy.deepcopy(self.rows)
                left[0][field] = value
                right = copy.deepcopy(left)
                self.assertEqual(left, right)
                for rows in (left, right):
                    self.assertNotEqual(
                        check_decisions(self.config, self.snapshot, rows).status, "PASS"
                    )

    def test_plan_mutation_and_missing_dispatch_or_terminal_are_rejected(self):
        rows = copy.deepcopy(self.rows)
        rows[0]["plan"]["commands"][0]["id"] = "UNEXECUTED-COMMAND"
        self.assertNotEqual(check_decisions(self.config, self.snapshot, rows).status, "PASS")
        for rows in (self.rows[:1], self.rows[1:], [], [dict(plan=self.rows[0]["plan"])]):
            self.assertNotEqual(check_decisions(self.config, self.snapshot, rows).status, "PASS")

    def test_accepted_event_is_not_the_started_dispatch_result(self):
        rows = copy.deepcopy(self.rows)
        rows[0]["receipt_id"] = self.snapshot.events[0].id
        self.assertNotEqual(check_decisions(self.config, self.snapshot, rows).status, "PASS")


class WorldRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = Builder().configuration()

    def test_known_fault_repair_and_duplicate_fault_remain_valid(self):
        world = ProductionBackend(self.config)
        for index, kind in enumerate(("FAILURE", "FAILURE", "REPAIR")):
            world.apply_world(
                m.WorldEvent(
                    f"W-{index}",
                    world.run_id,
                    0,
                    0,
                    kind,
                    "FORK-01",
                    "PRODUCT-1",
                    0,
                    "FAIL",
                    "ML-METHOD",
                )
            )
        self.assertEqual(check_run(self.config, world.snapshot()).status, "PASS")

    def test_fabricated_fault_and_repair_without_failure_are_rejected(self):
        world = ProductionBackend(self.config)
        fact = m.WorldEvent(
            "FAULT", world.run_id, 0, 0, "FAILURE", "FORK-01", "PRODUCT-1", 0, "FAIL", "ML-METHOD"
        )
        world.apply_world(fact)
        snapshot = world.snapshot()
        event = snapshot.events[0]
        for changed, failed in (
            (replace(fact, entity_id="BOGUS"), ("BOGUS",)),
            (replace(fact, kind="REPAIR"), ()),
        ):
            with self.subTest(fact=changed):
                clean = ProductionBackend(self.config)
                with self.assertRaises(ContractError):
                    clean.apply_world(changed)
                bad = replace(
                    snapshot,
                    state=replace(snapshot.state, failed_resources=failed),
                    events=(
                        replace(
                            event,
                            world=changed,
                            state=replace(event.state, failed_resources=failed),
                        ),
                    ),
                )
                self.assertEqual(check_run(self.config, bad).status, "INVALID")


if __name__ == "__main__":
    unittest.main()
