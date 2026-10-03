"""S13 repository asset checks, deliberately separate from production execution."""

import copy
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sim.isaac.scene.model import (  # noqa: E402
    FIXTURES,
    POSES,
    Box,
    SceneState,
    Transfer,
    check_phase,
    fk,
    key,
    load_config,
    phase_record,
    reachable_bound,
    robot_check,
    sweep,
)


class BuildingSceneTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / "examples/building_contracts/configuration.json")

    def bad_config(self, mutate, error):
        c = copy.deepcopy(self.config)
        mutate(c)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "config.json"
            p.write_text(json.dumps(c), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, error):
                load_config(p)

    def test_unit_reject(self):
        self.bad_config(lambda c: c["units"].update(length="cm"), "UNIT")

    def test_duplicate_reject(self):
        self.bad_config(lambda c: c["resources"].append(c["resources"][0]), "DUPLICATE")

    def test_missing_resource(self):
        self.bad_config(lambda c: c["resources"].pop(), "RESOURCE")

    def test_no_extra_welder_or_test_token(self):
        for name in ("WELD2", "TEST1-METER", "FIX-J2-SECOND"):
            self.bad_config(
                lambda c: c["resources"].append(dict(id=name, kind="EQUIPMENT", capacity=1)),
                "RESOURCE",
            )

    def test_identity_is_not_normalized_lossily(self):
        self.assertEqual(len({key(x) for x in ("A.B", "A-B", "A_B", "A/B", "人")}), 5)

    def test_declared_time_conversion(self):
        self.assertEqual(phase_record(self.config, "CUT")["declared_seconds"], 1800)
        self.assertEqual(phase_record(self.config, "WAIT-TEST")["declared_seconds"], 14400)

    def test_all_fixtures_reset_three_times(self):
        for fixture in FIXTURES:
            scene = SceneState(self.config, fixture)
            first = scene.snapshot()
            for _ in range(3):
                scene.route = {"progress": 0.5}
                scene.joints = [50] * 6
                scene.wall_visible = False
                scene.reset()
                self.assertEqual(scene.snapshot(), first)

    def test_dual_frame_one_product_one_fixture(self):
        s = SceneState(self.config, "dual_frame")
        self.assertEqual(sum(e["location"] == "J2" for e in s.entities.values()), 2)
        with self.assertRaisesRegex(ValueError, "RESOURCE_BUSY"):
            s.claim("FIX-J2", "PRODUCT-1.TOP")

    def test_second_product_rejected(self):
        for fixture in ("dual_frame", "quarantine", "outbound"):
            s = SceneState(self.config, fixture)
            occupied = (
                "J2" if fixture == "dual_frame" else "Q1" if fixture == "quarantine" else "OUT1"
            )
            s.entities["PRODUCT-2"] = dict(
                product="PRODUCT-2", location=occupied, kind="MODULE", position=(16, 10, 0.6)
            )
            with self.assertRaisesRegex(ValueError, "CAPACITY"):
                s.validate()

    def test_buffer_third_component_rejected(self):
        s = SceneState(self.config)
        s.place("PRODUCT-1.BOTTOM", "BUF", (26, 7.5, 0.6))
        s.place("PRODUCT-1.TOP", "BUF", (26, 12.5, 0.6))
        with self.assertRaisesRegex(ValueError, "CAPACITY"):
            s.place("PRODUCT-1.COLUMNS", "BUF", (26, 10, 0.6))
        self.assertEqual(s.entities["PRODUCT-1.COLUMNS"]["location"], "PRE")

    def test_merge_requires_three_landed_sources(self):
        s = SceneState(self.config, "joining")
        with self.assertRaisesRegex(ValueError, "MERGE_NOT_LANDED"):
            s.merge()
        s.place("PRODUCT-1.TOP", "J3", (36, 10, 3.6))
        s.place("PRODUCT-1.COLUMNS", "J3", (36, 10, 0.8))
        s.merge()
        self.assertEqual(list(s.entities), ["PRODUCT-1"])
        self.assertEqual(s.entities["PRODUCT-1"]["mass_kg"], 8000)
        self.assertEqual(len(s.entities["PRODUCT-1"]["lineage"]), 3)
        s.entities["PRODUCT-1.BOTTOM"] = copy.deepcopy(s.entities["PRODUCT-1"])
        with self.assertRaisesRegex(ValueError, "MERGE_DUPLICATE"):
            s.validate()

    def test_wait_ownership_hidden_wall_not_release(self):
        s = SceneState(self.config, "mep_wait")
        s.wall_visible = False
        self.assertEqual(s.faces, ["WET"])
        self.assertEqual(s.phase["people"], [])
        self.assertEqual(s.entities["PRODUCT-1"]["location"], "F1")
        s.owners.pop("TEST1")
        with self.assertRaisesRegex(ValueError, "TEST_HOLD"):
            s.validate()

    def test_visual_completion_never_pass(self):
        s = SceneState(self.config, "outbound")
        self.assertEqual(s.quality, "UNKNOWN")
        s.quality = "PASS"
        with self.assertRaisesRegex(ValueError, "QUALITY"):
            s.validate()

    def test_phase_responsibility_mutations(self):
        for code in (
            "CUT",
            "W-B",
            "W-3D",
            "MV-IN-B",
            "JOIN-IN",
            "TEST-SET",
            "WAIT-TEST",
            "Q-POND",
            "WAIT-W",
        ):
            good = phase_record(self.config, code)
            self.assertTrue(check_phase(self.config, good))
            for field, value in (
                ("people", ["UNKNOWN"]),
                ("equipment", ["EXTRA"]),
                ("person_state", "REST"),
                ("quality", "PASS"),
                ("production_receipt", True),
            ):
                bad = copy.deepcopy(good)
                bad[field] = value
                with self.assertRaisesRegex(ValueError, "PHASE"):
                    check_phase(self.config, bad)

    def test_human_robot_and_power_distinct(self):
        manual = phase_record(self.config, "W-B", "H")
        self.assertIn("W1", manual["people"])
        self.assertIn("WELD1", manual["equipment"])
        for unit in range(3):
            robot = phase_record(self.config, "W-B", "HR-seq", unit)
            self.assertIn("R1", robot["equipment"])
            self.assertNotIn("WELD1", robot["equipment"])
            self.assertFalse(robot["production_receipt"])
        manual["mode"] = "HR-seq"
        with self.assertRaisesRegex(ValueError, "PHASE"):
            check_phase(self.config, manual)

    def test_crane_roles_and_three_join_moves(self):
        self.assertEqual(phase_record(self.config, "JOIN-IN")["people"], ["Lop", "Lrig", "Lsig"])
        self.assertEqual(phase_record(self.config, "MV-IN-B")["people"], ["Lrig", "Lsig", "P1"])
        move = next(a["move"] for a in self.config["activities"] if a["code"] == "JOIN-IN")
        self.assertEqual(len(move["entity_ids"]), 3)
        self.assertEqual(move["equipment"], "CR1")

    def test_continuous_sweep_finds_between_endpoints(self):
        with self.assertRaisesRegex(ValueError, "COLLISION:block"):
            sweep([(0, 0, 1), (10, 0, 1)], (1, 1, 1), [Box("block", (5, 0, 1), (0.1, 0.1, 0.1))])

    def test_contact_rounding_does_not_hide_penetration(self):
        load = Box("load", (0, 0, 1.1), (6, 3, 1))
        self.assertFalse(load.overlaps(Box("support", (0, 0, 0.3), (0.4, 0.4, 0.60000002))))
        self.assertTrue(load.overlaps(Box("penetration", (0, 0, 0.3001), (0.4, 0.4, 0.6))))

    def test_wrong_endpoint_and_early_release(self):
        t = Transfer("CR1", (36, 10, 0.6), (36, 24, 0.6), (6, 3, 3.8), 8, 1)
        with self.assertRaisesRegex(ValueError, "NOT_ATTACHED"):
            t.sample(0.5)
        t.attach()
        with self.assertRaisesRegex(ValueError, "NOT_LANDED"):
            t.detach()
        for i in range(241):
            t.sample(i / 240)
        with self.assertRaisesRegex(ValueError, "ARRIVAL"):
            t.land((35.98, 24, 0.6))
        with self.assertRaisesRegex(ValueError, "ARRIVAL"):
            t.land(t.target, 0.2)
        t.land(t.position)
        t.detach()
        self.assertEqual(t.state, "RELEASED")

    def test_gantry_track_obstacle(self):
        with self.assertRaisesRegex(ValueError, "COLLISION:rail"):
            Transfer(
                "CR1",
                (36, 24, 0.6),
                (16, 24, 0.6),
                (6, 3, 3.8),
                8,
                1,
                [Box("rail", (22, 0.75, 1), (0.2, 0.2, 2))],
            )

    def test_travel_limit_and_load(self):
        with self.assertRaisesRegex(ValueError, "GANTRY_TRAVEL"):
            Transfer("CR1", (36, 10, 0.6), (41, 24, 0.6), (6, 3, 3.8), 8, 1)
        with self.assertRaisesRegex(ValueError, "OVERLOAD"):
            Transfer("HST1", (6, 10, 0.6), (36, 10, 0.6), (1.6, 1.6, 2.8), 4)

    def test_hst_route_clears_resident_frame(self):
        Transfer(
            "HST1",
            (16, 12.5, 0.6),
            (26, 12.5, 0.6),
            (6, 3, 0.4),
            2,
            obstacles=[Box("other_frame", (16, 7.5, 0.7), (6, 3, 0.2))],
        )

    def test_robot_zero_pose_independent_exact(self):
        t, _ = fk([0] * 6)
        self.assertAlmostEqual(t[0][3], 23.05)
        self.assertAlmostEqual(t[1][3], 10)
        self.assertAlmostEqual(t[2][3], 1.15)

    def test_robot_local_poses_and_unreachable(self):
        for pose in POSES:
            self.assertTrue(math.isfinite(robot_check(pose)[0][3]))
        self.assertFalse(reachable_bound((30, 15, 1)))

    def test_robot_limit_and_collision(self):
        with self.assertRaisesRegex(ValueError, "JOINT_LIMIT"):
            fk([180, 0, 0, 0, 0, 0])
        with self.assertRaisesRegex(ValueError, "ROBOT_COLLISION:fixture"):
            robot_check(POSES[0], [Box("fixture", (20.8, 10, 0.8), (0.6, 0.6, 0.8))])

    def test_robot_continuity(self):
        previous = None
        for i in range(241):
            q = [a + (b - a) * i / 240 for a, b in zip(POSES[0], POSES[1])]
            t = robot_check(q)
            point = tuple(t[k][3] for k in range(3))
            if previous:
                self.assertLess(math.dist(previous, point), 0.02)
            previous = point


if __name__ == "__main__":
    unittest.main()
