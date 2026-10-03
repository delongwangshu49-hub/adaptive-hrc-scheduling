"""Independent failure-oriented tests of scene rehearsal continuity and boundaries."""

import copy
import json
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sim.isaac.scene.layout import CORE_ORIGIN, PERSON_STATIONS, layout_comparison, local, world
from sim.isaac.scene.model import Box
from sim.isaac.scene.trials import Rehearsal, validate_placements

PEOPLE = tuple(PERSON_STATIONS)


class BuildingTrialsTests(unittest.TestCase):
    def test_candidate_selection_preserves_conflicts(self):
        a, b = layout_comparison()
        self.assertTrue(a["pad_bay_conflicts"])
        self.assertFalse(a["selected"])
        self.assertEqual(b["pad_bay_conflicts"], [])
        self.assertTrue(b["selected"])
        self.assertEqual(a["required_endpoint_manhattan_m"], b["required_endpoint_manhattan_m"])

    def test_coordinate_inverse(self):
        self.assertEqual(world((0, 0, 0)), CORE_ORIGIN)
        self.assertEqual(local(world((36, 24, 0.6))), (36, 24, 0.6))

    def test_each_trial_continuous_complete_reset(self):
        for name in ("T1", "T2", "T3", "T4"):
            with self.subTest(name=name):
                r = Rehearsal(name, PEOPLE)
                initial = copy.deepcopy(r.positions)
                for action in r.actions:
                    if action.equipment:
                        for axis, limit in enumerate((2.5, 2.5, 0.5)):
                            peak = max(
                                1.875
                                * abs(a[axis] - b[axis])
                                * (len(action.points) - 1)
                                / action.seconds
                                for a, b in zip(action.points, action.points[1:])
                            )
                            self.assertLessEqual(peak, limit + 1e-9)

                for _ in range(20000):
                    previous = copy.deepcopy(r.positions)
                    r.advance(0.1)
                    self.assertNotEqual(r.status, "BLOCKED", r.blocked)
                    for key, pos in previous.items():
                        # At 0.1s steps, a jump exceeds any scene route's speed.
                        self.assertLess(math.dist(pos, r.positions[key]), 0.6, key)
                    if not r.action:
                        break
                self.assertEqual(r.status, "COMPLETE_GEOMETRY_ONLY")
                self.assertFalse(r.owners)
                self.assertFalse(r.snapshot()["production_receipt"])
                self.assertEqual(r.snapshot()["quality"], "UNKNOWN")
                r.reset()
                self.assertEqual(r.positions, initial)

    def test_fault_is_transactional_then_resume(self):
        r = Rehearsal("T1", PEOPLE)
        start = copy.deepcopy(r.positions)
        obstacle = Box("occupied_handoff", (1, 7, 0.7), (1, 1, 1))
        r.advance(1, [obstacle])
        self.assertEqual(r.status, "BLOCKED")
        self.assertEqual(r.elapsed, 0)
        self.assertEqual(r.positions, start)
        self.assertFalse(r.owners)
        r.advance(1)
        self.assertEqual(r.status, "RUNNING")
        self.assertGreater(r.elapsed, 0)

    def test_wrong_resource_owner_and_duplicate_reject(self):
        r = Rehearsal("T3", PEOPLE)
        r.claim("WELD1", "OTHER_PRODUCT")
        r.advance(1)
        self.assertEqual(r.status, "BLOCKED")
        self.assertEqual(r.owners, {"WELD1": "OTHER_PRODUCT"})
        self.assertEqual(r.elapsed, 0)

    def test_pause_step_and_speed(self):
        r = Rehearsal("T1", PEOPLE)
        r.paused = True
        s = r.snapshot()
        r.advance(2)
        self.assertEqual(s, r.snapshot())
        r.advance(0.1, single_step=True)
        self.assertAlmostEqual(r.elapsed, 0.1)
        r.paused = False
        r.speed = 4
        r.advance(0.1)
        self.assertAlmostEqual(r.elapsed, 0.5)

    def test_nonfinite_dt_reject(self):
        r = Rehearsal("T1", PEOPLE)
        for v in (-1, float("nan"), float("inf")):
            with self.assertRaisesRegex(ValueError, "INVALID_DT"):
                r.advance(v)

    def test_j2_same_product_double_frame_no_extra_fixture(self):
        validate_placements(
            {
                "P1.BOTTOM": {"product": "P1", "zone": "J2"},
                "P1.TOP": {"product": "P1", "zone": "J2"},
            }
        )
        with self.assertRaisesRegex(ValueError, "CAPACITY:J2"):
            validate_placements(
                {
                    "P1.BOTTOM": {"product": "P1", "zone": "J2"},
                    "P2.TOP": {"product": "P2", "zone": "J2"},
                }
            )

    def test_buffer_quarantine_outbound_capacity(self):
        for zone, count in (("BUF", 3), ("Q1", 2), ("OUT1", 2)):
            with self.assertRaisesRegex(ValueError, "CAPACITY:" + zone):
                validate_placements(
                    {f"P{i}.BOTTOM": {"product": f"P{i}", "zone": zone} for i in range(count)}
                )

    def test_cross_product_lineage(self):
        with self.assertRaisesRegex(ValueError, "CROSS_PRODUCT"):
            validate_placements({"P1.BOTTOM": {"product": "P2", "zone": "J3"}})

    def test_test_group_held_during_wait(self):
        r = Rehearsal("T3", PEOPLE)
        while "TEST1 HELD" not in r.action.label:
            r.advance(0.5)
            self.assertNotEqual(r.status, "BLOCKED", r.blocked)
        r.advance(1)
        self.assertEqual(r.owners["TEST1"], "T3")
        with self.assertRaisesRegex(ValueError, "RESOURCE_BUSY:TEST1"):
            r.claim("TEST1", "T4")

    def test_scene_objects_do_not_extend_configuration(self):
        root = Path(__file__).resolve().parents[1]
        c = json.loads(
            (root / "examples/building_contracts/configuration.json").read_text(encoding="utf-8")
        )
        self.assertFalse(any(r["id"].startswith("SCN-") for r in c["resources"]))
        self.assertEqual(len(c["activities"]), 37)


if __name__ == "__main__":
    unittest.main()
