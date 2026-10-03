"""R5 negative and continuity tests independent of USD rendering."""

import copy
import math
import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sim.isaac.scene.model import Box
from sim.isaac.scene.target_layout import (
    CONTROL,
    FIXED,
    PEOPLE,
    TASK_BY_ID,
    TASKS,
    WalkGraph,
    length,
    static_boxes,
    transfer_matrix,
    verify_task,
)
from sim.isaac.scene.target_trials import TargetRun


def obstacles(run):
    a = run.action
    moving = set(a.paths) if a else set()
    if a and a.task == "BOARD":
        moving.add("SCN-FORK-01")
    result = static_boxes()
    for n, p in run.positions.items():
        if n in moving or n in FIXED or n == "CR1-HOOK":
            continue
        size = run.size(n)
        result.append(Box(n, (p[0], p[1], p[2] + size[2] / 2), size))
    return result


def reach(run, label):
    for _ in range(200):
        if run.action.label.startswith(label):
            return
        run.advance(run.action.seconds, obstacles(run))
        if run.blocked:
            raise AssertionError(run.blocked)
    raise AssertionError("PHASE_NOT_FOUND:" + label)


class TargetTests(unittest.TestCase):
    def test_empty_hook_cannot_bypass_bogie_obstacle(self):
        blocked = Box("bogie-block", (40, 4, 1), (0.7, 0.7, 1.9))
        verify_task(TASK_BY_ID["M01"], [*static_boxes(), blocked])
        with self.assertRaisesRegex(ValueError, "COLLISION:bogie-block"):
            transfer_matrix([*static_boxes(), blocked])
        r = TargetRun("T2")
        reach(r, "EMPTY HOOK APPROACH")
        before = copy.deepcopy(r.positions)
        r.advance(1, [*obstacles(r), blocked])
        self.assertIn("COLLISION:bogie-block", r.blocked)
        self.assertEqual(r.positions, before)

    def test_empty_routes_and_tool_cart_matrix(self):
        rows = transfer_matrix()
        self.assertEqual(len(rows), 53)
        self.assertEqual(len({r["id"] for r in rows}), 53)
        self.assertEqual(sum(r["kind"] == "EMPTY_RETURN" for r in rows), 19)

    def test_combined_three_products_and_crossing(self):
        r = TargetRun("T4", combined=True)
        r.signal_external()
        yielded = False
        while r.action:
            r.advance(1, obstacles(r))
            self.assertIsNone(r.blocked, r.blocked)
            yielded |= r.person_state["W2"]["state"] == "YIELD"
        self.assertTrue(yielded)
        self.assertEqual(len(r.kinds), 3)

    def test_support_retraction_before_empty_return(self):
        for name, carrier in (("T1", "SCN-FORK-01"), ("T3", "SCN-CART-01")):
            r = TargetRun(name)
            reach(r, "RETRACT SUPPORT")
            self.assertEqual(r.extensions[carrier], 1)
            self.assertTrue(all(not s.endswith(carrier) for s in r.support.values()))
            r.advance(r.action.seconds)
            self.assertEqual(r.extensions[carrier], 0)
            self.assertTrue(r.action.label.startswith("EMPTY RETURN"))

    def test_all_required_tasks(self):
        self.assertEqual(len(TASKS), 19)
        for t in TASKS:
            with self.subTest(t=t.id):
                self.assertEqual(verify_task(t)["status"], "PASS_GEOMETRY_ONLY")
        self.assertEqual({t.target for t in TASKS if t.source == "OUT1"}, {"FG1", "FG2"})
        self.assertEqual({t.source for t in TASKS if t.target == "DISPATCH"}, {"FG1", "FG2"})

    def test_full_continuous_trials_with_all_current_obstacles(self):
        for trial in ("T1", "T2", "T3", "T4"):
            r = TargetRun(trial)
            ids = set(r.positions)
            if trial == "T4":
                r.signal_external()
            while r.action:
                r.advance(r.action.seconds / 7, obstacles(r))
                self.assertIsNone(r.blocked, (trial, r.index, r.blocked))
                self.assertEqual(set(r.positions), ids)
            self.assertEqual(r.status, "COMPLETE_GEOMETRY_ONLY")
            self.assertEqual(r.owners, {})
            self.assertFalse(r.snapshot()["production_receipt"])

    def test_fixed_equipment_displacement_rejected(self):
        r = TargetRun()
        r.positions["CUT1"] = (16, 12, 0)
        r.advance(1)
        self.assertIn("FIXED_MACHINE_MOVED", r.blocked)

    def test_missing_driver_rejected(self):
        r = TargetRun()
        reach(r, "CARRY S01")
        del r.action.paths["P1"]
        r.advance(1)
        self.assertIn("UNOPERATED_VEHICLE", r.blocked)

    def test_missing_crane_role_rejected(self):
        r = TargetRun("T2")
        reach(r, "EMPTY HOOK APPROACH")
        del r.action.roles["Lop"]
        r.advance(1)
        self.assertEqual(r.blocked, "MISSING_CRANE_ROLE")

    def test_operator_leaves_station(self):
        r = TargetRun("T2")
        reach(r, "CARRY M01")
        r.advance(1)
        r.positions["Lop"] = (55, 18, 0)
        before = r.positions["SCN-MODULE-001"]
        r.advance(1)
        self.assertIn("ROLE_NOT_AT_STATION", r.blocked)
        self.assertEqual(before, r.positions["SCN-MODULE-001"])

    def test_driver_leaves_moving_vehicle(self):
        r = TargetRun()
        reach(r, "CARRY S01")
        r.advance(1)
        r.positions["P1"] = (3, 3, 0)
        r.advance(1)
        self.assertIn("ACTOR_LEFT_MOTION", r.blocked)

    def test_person_double_task_rejected_atomically(self):
        r = TargetRun()
        reach(r, "LOAD / CHECK SUPPORT S01")
        r.claim("P1", "OTHER")
        r.advance(1)
        self.assertIn("PERSON_DOUBLE_TASK", r.blocked)
        self.assertEqual(r.owners, {"P1": "OTHER"})

    def test_transport_admission_negative_cases(self):
        for fault, reason in (
            ("unreleased", "BATCH_NOT_RELEASED"),
            ("source_missing", "SOURCE_MISSING"),
            ("target_full", "TARGET_FULL"),
            ("operator_missing", "OPERATOR_MISSING"),
        ):
            r = TargetRun()
            reach(r, "LOAD / CHECK SUPPORT S01")
            initial = copy.deepcopy(r.positions)
            r.faults.add(fault)
            r.advance(1)
            self.assertIn(reason, r.blocked)
            self.assertEqual(r.positions, initial)
            self.assertEqual(r.owners, {})

    def test_pause_and_obstacle_retain_identity_and_carrier(self):
        r = TargetRun()
        reach(r, "CARRY S01")
        r.advance(2)
        before = copy.deepcopy(r.positions)
        r.paused = True
        r.advance(10)
        self.assertEqual(r.positions, before)
        r.paused = False
        r.advance(2, [Box("barrier", (11, 10, 1.1), (1, 1, 3))])
        self.assertIn("COLLISION", r.blocked)
        self.assertEqual(r.positions, before)
        self.assertEqual(r.support["SCN-STEEL-001"], "CARRIER:SCN-FORK-01")
        r.advance(2)
        self.assertIsNone(r.blocked)

    def test_buffer_requires_signal_and_actual_move(self):
        r = TargetRun("T4")
        before = copy.deepcopy(r.positions)
        r.advance(20)
        self.assertIn("WAIT_EXTERNAL", r.blocked)
        self.assertEqual(r.positions, before)
        r.signal_external()
        self.assertEqual(r.slots["FG1"], "SCN-FG-P1")
        reach(r, "CARRY F03")
        r.advance(r.action.seconds)
        self.assertEqual(r.slots["FG1"], "SCN-FG-P1")
        self.assertEqual(r.slots["DISPATCH"], None)
        r.advance(r.action.seconds)
        self.assertIsNone(r.slots["FG1"])
        self.assertEqual(r.slots["DISPATCH"], "SCN-FG-P1")
        while r.action:
            r.advance(r.action.seconds, obstacles(r))
            self.assertIsNone(r.blocked)
        self.assertEqual(r.slots["FG1"], "SCN-FG-P3")
        self.assertEqual(r.slots["FG2"], "SCN-FG-P2")
        self.assertEqual(r.locations["SCN-FG-P1"], "DISPATCH")
        self.assertNotIn("EXTERNAL", r.locations.values())
        with self.assertRaisesRegex(ValueError, "DUPLICATE_EXTERNAL"):
            r.signal_external()

    def test_full_slot_never_overwritten(self):
        r = TargetRun("T4")
        with self.assertRaisesRegex(ValueError, "TARGET_FULL"):
            r.add_load("EXTRA", "module", "FG1")
        self.assertEqual(r.slots["FG1"], "SCN-FG-P1")

    def test_land_requires_real_position_and_attachment(self):
        r = TargetRun("T4")
        with self.assertRaisesRegex(ValueError, "NOT_LANDED"):
            r._effect(("land", "F03", "SCN-FG-P1"))
        self.assertEqual(r.slots["FG1"], "SCN-FG-P1")

    def test_crane_headroom_and_endpoint_failures(self):
        with self.assertRaisesRegex(ValueError, "HOOK_HEADROOM"):
            verify_task(TASK_BY_ID["M01"], hook_limit=7.8)
        with self.assertRaisesRegex(ValueError, "HOOK_COVERAGE"):
            verify_task(replace(TASK_BY_ID["M01"], source="RECEIVE"), obstacles=[])

    def test_adjacent_occupied_slot_sweeps(self):
        adjacent = Box("occupied-FG2", (20, 34, 2.2), (6, 3, 3.2))
        verify_task(TASK_BY_ID["F01"], obstacles=[*static_boxes(), adjacent])
        with self.assertRaisesRegex(ValueError, "COLLISION:occupied-FG2"):
            verify_task(TASK_BY_ID["F02"], obstacles=[*static_boxes(), adjacent])

    def test_no_full_module_on_fork(self):
        with self.assertRaisesRegex(ValueError, "LOAD_ADAPTATION"):
            verify_task(replace(TASK_BY_ID["S01"], load="module"), obstacles=[])

    def test_shortest_routes_replan_or_wait(self):
        start, end = (25, 18, 0), (45, 18, 0)
        direct = WalkGraph().route(start, end)
        self.assertEqual(length(direct), 20)
        detour = WalkGraph([Box("closed", (35, 18, 1), (2, 2, 2))]).route(start, end)
        self.assertGreater(length(detour), 20)
        with self.assertRaisesRegex(ValueError, "NO_LEGAL_PERSON_ROUTE"):
            WalkGraph([Box("closed", (35, 22, 1), (3, 44, 2))]).route(start, end)

    def test_concurrent_crossing_yields_without_reset(self):
        r = TargetRun("T3")
        reach(r, "TWO PEOPLE CROSS")
        start = r.positions["W2"]
        r.advance(1, obstacles(r))
        self.assertEqual(r.person_state["W2"]["state"], "YIELD")
        self.assertEqual(r.positions["W2"], start)
        while r.action.label.startswith("TWO PEOPLE"):
            r.advance(1, obstacles(r))
            self.assertIsNone(r.blocked)
            self.assertGreater(math.dist(r.positions["W1"], r.positions["W2"]), 0.6)

    def test_no_sixteenth_person_no_hst_no_weld_alias(self):
        r = TargetRun("T3")
        self.assertEqual(len(PEOPLE), 15)
        self.assertTrue(set(PEOPLE).issubset(r.positions))
        self.assertNotIn("HST1", r.positions)
        self.assertNotIn("WELD1", r.positions)
        self.assertEqual(len([n for n in r.positions if n.startswith("SCN-WELD-")]), 2)
        self.assertEqual(set(CONTROL), {"Lop", "Lrig", "Lsig"})

    def test_deterministic_reset(self):
        r = TargetRun("T2")
        before = r.snapshot()
        r.advance(10)
        r.reset()
        self.assertEqual(before, r.snapshot())


if __name__ == "__main__":
    unittest.main()
