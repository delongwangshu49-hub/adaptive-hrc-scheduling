"""Regression oracles for the authorized C04/C05 r2 repairs."""

import importlib.util
import json
import unittest
from dataclasses import replace
from pathlib import Path

from adaptive_hrc_scheduling.building_backend import BuildingBackend
from adaptive_hrc_scheduling.contracts.building import ContractError, dumps, validate
from adaptive_hrc_scheduling.contracts.codec import as_data
from adaptive_hrc_scheduling.domain import building as b

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "repair_witness", ROOT / "scripts/run_building_witness.py"
)
witness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(witness)


class BuildingRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = witness.generator.synthetic_fixture(witness.generator.build_configuration())
        world = BuildingBackend(cls.c)
        cls.before = {}
        for activity in cls.c.activities:
            cls.before[activity.code] = world.checkpoint()
            witness.run_activity(world, activity.id)
        cls.ready = world.checkpoint()

    def world(self, code):
        return BuildingBackend.restore(self.c, self.before[code])

    def start(self, world, code, **kwargs):
        for _ in range(1000):
            cmd = witness.command(world, "PRODUCT-1." + code, **kwargs)
            result = world.dispatch(cmd)
            if result.accepted:
                return next(r for r in world.s.running if r.activity_id == cmd.activity_id)
            self.assertIn(
                result.reason, ("CALENDAR_OR_QUALIFICATION", "FATIGUE_PROTECTION", "REST_COMMITTED")
            )
            if result.reason == "FATIGUE_PROTECTION":
                world.rest(tuple(x.person_id for x in cmd.roles), 0.25)
            world.advance(world.time + 0.25)
        self.fail("no start window")

    def changed_activity(self, activity):
        return replace(
            self.c,
            activities=tuple(activity if a.id == activity.id else a for a in self.c.activities),
        )

    def test_mandatory_quality_gates_cannot_be_removed(self):
        for a in self.c.activities:
            if a.quality_evidence:
                with self.subTest(code=a.code), self.assertRaisesRegex(ContractError, "quality"):
                    validate(self.changed_activity(replace(a, quality_evidence=None)))

    def test_wait_gates_and_positive_wait_cannot_be_removed(self):
        for a in self.c.activities:
            if a.wait_h:
                for field, value in (("wait_h", 0), ("release_evidence", None)):
                    with self.subTest(code=a.code, field=field), self.assertRaises(ContractError):
                        validate(self.changed_activity(replace(a, **{field: value})))

    def test_required_work_cannot_be_empty(self):
        for a in self.c.activities:
            for m in a.modes:
                if m.units:
                    bad = replace(
                        a, modes=tuple(replace(x, units=()) if x.id == m.id else x for x in a.modes)
                    )
                    with (
                        self.subTest(code=a.code, mode=m.kind),
                        self.assertRaisesRegex(ContractError, "work"),
                    ):
                        validate(self.changed_activity(bad))

    def test_required_equipment_cannot_be_removed(self):
        for code in ("CUT", "W-B", "W-3D", "MOVE-F", "Q-FIN"):
            a = next(a for a in self.c.activities if a.code == code)
            m = a.modes[0]
            bad = replace(
                a,
                modes=(replace(m, units=(replace(m.units[0], equipment=()),) + m.units[1:]),)
                + a.modes[1:],
            )
            with self.subTest(code=code), self.assertRaisesRegex(ContractError, "equipment"):
                validate(self.changed_activity(bad))

    def test_invalidated_structure_blocks_new_work_and_survives_restore(self):
        w = self.world("FLOOR")
        witness.fact(w, "INVALIDATE", "PRODUCT-1.Q-STR")
        for candidate in (w, BuildingBackend.restore(self.c, w.checkpoint())):
            before = candidate.s
            result = candidate.dispatch(witness.command(candidate, "PRODUCT-1.FLOOR"))
            self.assertFalse(result.accepted)
            self.assertEqual(candidate.s.products, before.products)
            self.assertEqual(candidate.s.materials, before.materials)
            self.assertEqual(candidate.s.products[0].state, "QUALITY_HOLD")

    def test_invalidated_work_and_wait_cannot_reopen_descendants(self):
        for invalidated in ("W-3D", "WAIT-COAT"):
            with self.subTest(activity=invalidated):
                w = self.world("FLOOR")
                witness.fact(w, "INVALIDATE", "PRODUCT-1." + invalidated)
                self.assertFalse(w.dispatch(witness.command(w, "PRODUCT-1.FLOOR")).accepted)

    def test_invalidation_during_move_keeps_safe_tail_then_blocks(self):
        w = self.world("MOVE-F")
        run = self.start(w, "MOVE-F")
        w.advance(run.start_h + 0.5)
        witness.fact(w, "INVALIDATE", "PRODUCT-1.Q-STR")
        w.advance(run.end_h)
        self.assertEqual(w.s.products[0].location, "F1")
        self.assertEqual(w.s.products[0].state, "QUALITY_HOLD")
        self.assertFalse(w.dispatch(witness.command(w, "PRODUCT-1.FLOOR")).accepted)

    def assert_restore_rejected(self, state):
        # Bypass dumps only to exercise the receiving restore boundary on invalid JSON data.
        with self.assertRaisesRegex(ContractError, "residen|physical|location"):
            BuildingBackend.restore(self.c, json.dumps(as_data(state)))

    def test_restore_requires_stationary_residency(self):
        w = self.world("MEP-E")
        self.assert_restore_rejected(replace(w.s, residencies=()))
        r = w.s.residencies[0]
        self.assert_restore_rejected(replace(w.s, residencies=(replace(r, owner="FOREIGN"),)))
        self.assert_restore_rejected(
            replace(
                w.s, residencies=w.s.residencies + (b.Residency("GHOST", "Q1", "GHOST", False),)
            )
        )

    def test_restore_requires_move_source_and_target(self):
        w = self.world("MOVE-F")
        run = self.start(w, "MOVE-F")
        w.advance(run.start_h + 0.5)
        for location in ("J3", "F1"):
            with self.subTest(location=location):
                self.assert_restore_rejected(
                    replace(
                        w.s, residencies=tuple(r for r in w.s.residencies if r.location != location)
                    )
                )
        self.assert_restore_rejected(
            replace(
                w.s,
                residencies=tuple(
                    replace(r, reserved=False) if r.location == "F1" else r for r in w.s.residencies
                ),
            )
        )

    def test_recovery_accepts_raw_components_join_and_all_activity_boundaries(self):
        for code, text in self.before.items():
            with self.subTest(code=code):
                self.assertEqual(BuildingBackend.restore(self.c, text).checkpoint(), text)
        for code in ("MV-IN-B", "MV-B", "JOIN-IN", "MOVE-F", "MOVE-OUT"):
            w = self.world(code)
            run = self.start(w, code)
            for fraction in (0.1, 0.3, 0.45, 0.6, 0.85):
                w.advance(run.start_h + fraction * (run.end_h - run.start_h))
                text = w.checkpoint()
                restored = BuildingBackend.restore(self.c, text)
                self.assertEqual(restored.checkpoint(), text)
            w.advance(run.end_h)
            validate(w.s, config=self.c)
        w = BuildingBackend.restore(self.c, self.ready)
        witness.fact(w, "RECEIVED", "PRODUCT-1")
        validate(w.s, config=self.c)

    def test_advance_stops_at_hidden_emergency_without_losing_prefix(self):
        w = self.world("MOVE-F")
        run = self.start(w, "MOVE-F")
        event = b.WorldEvent("CRANE-FAULT", w.time + 0.5, "FAILURE", "CR1", None, None)
        state = replace(w.s, scenario=b.HiddenScenario("C04-1.0", self.c.id, 0, (event,)))
        text = dumps(state, config=self.c)
        coarse = BuildingBackend.restore(self.c, text)
        split = BuildingBackend.restore(self.c, text)
        receipt = coarse.advance(run.end_h)
        split.advance(event.time_h)
        self.assertFalse(receipt.accepted)
        self.assertEqual(receipt.reason, "EMERGENCY_HOLD_NO_SAFE_PATH")
        self.assertEqual(coarse.time, event.time_h)
        self.assertEqual(coarse.checkpoint(), split.checkpoint())
        self.assertIn("CR1", coarse.s.failed_resources)
        before = coarse.checkpoint()
        with self.assertRaisesRegex(ContractError, "EMERGENCY_HOLD"):
            coarse.advance(run.end_h)
        self.assertEqual(coarse.checkpoint(), before)

    def test_cleanup_rejects_failed_source_and_target_atomically(self):
        for location in ("F1", "Q1"):
            with self.subTest(location=location):
                w = self.world("FLOOR")
                witness.fact(w, "CANCEL", "PRODUCT-1")
                witness.fact(w, "FAILURE", location)
                before = w.checkpoint()
                result = w.cleanup("PRODUCT-1")
                self.assertFalse(result.accepted)
                self.assertIn("LOCATION_FAILED", result.reason)
                self.assertEqual(w.checkpoint(), before)

    def test_cleanup_destination_fault_preserves_in_transit_commitment(self):
        w = self.world("FLOOR")
        witness.fact(w, "CANCEL", "PRODUCT-1")
        for _ in range(1000):
            result = w.cleanup("PRODUCT-1")
            if result.accepted:
                break
            self.assertIn(
                result.reason, ("CALENDAR_OR_QUALIFICATION", "FATIGUE_PROTECTION", "REST_COMMITTED")
            )
            if result.reason == "FATIGUE_PROTECTION":
                w.rest(("Lop", "Lrig", "Lsig"), 0.25)
            w.advance(w.time + 0.25)
        self.assertTrue(result.accepted)
        service = w.s.services[0]
        w.advance(service.start_h + 0.5)
        witness.fact(w, "FAILURE", "Q1")
        self.assertEqual(w.s.services[0].state, "EMERGENCY_HOLD")
        text = w.checkpoint()
        restored = BuildingBackend.restore(self.c, text)
        with self.assertRaisesRegex(ContractError, "EMERGENCY_HOLD"):
            restored.advance(service.end_h)
        self.assertEqual(restored.checkpoint(), text)
        self.assertEqual(restored.s.products[0].location, "IN_TRANSIT")
        self.assertEqual({r.location for r in restored.s.residencies}, {"F1", "Q1"})

    def test_same_product_dual_frames_resident_fixture_exclusive(self):
        w = self.world("W-B")
        witness.run_activity(w, "PRODUCT-1.MV-IN-T")
        self.assertEqual(
            {r.entity_id for r in w.s.residencies if r.location == "J2"},
            {"PRODUCT-1.BOTTOM", "PRODUCT-1.TOP"},
        )
        run = self.start(w, "W-B")
        result = w.dispatch(witness.command(w, "PRODUCT-1.W-T", bindings={"W1": "W2"}))
        self.assertFalse(result.accepted)
        self.assertEqual(
            [(x.resource_id, x.owner) for x in w.s.locks if x.resource_id == "FIX-J2"],
            [("FIX-J2", "PRODUCT-1.W-B")],
        )
        w.advance(run.end_h)
        validate(w.s, config=self.c)

    def failed_pond(self):
        w = self.world("Q-POND")
        run = self.start(w, "Q-POND")
        w.advance(run.end_h)
        witness.fact(w, "QUALITY_RESULT", "PRODUCT-1.Q-POND", "FAIL", 0)
        return w

    def start_repair(self, w):
        for _ in range(1000):
            result = w.repair_quality("PRODUCT-1.Q-POND")
            if result.accepted:
                return w.s.services[0]
            self.assertIn(
                result.reason, ("CALENDAR_OR_QUALIFICATION", "FATIGUE_PROTECTION", "REST_COMMITTED")
            )
            if result.reason == "FATIGUE_PROTECTION":
                w.rest(("QA1", "T1"), 0.25)
            w.advance(w.time + 0.25)
        self.fail("no repair window")

    def test_local_repair_does_not_bypass_other_invalidated_ancestor(self):
        w = self.failed_pond()
        witness.fact(w, "INVALIDATE", "PRODUCT-1.Q-STR")
        before = w.checkpoint()
        self.assertFalse(w.repair_quality("PRODUCT-1.Q-POND").accepted)
        self.assertEqual(w.checkpoint(), before)

    def test_new_invalidation_during_repair_preserves_hold(self):
        w = self.failed_pond()
        service = self.start_repair(w)
        w.advance(service.start_h + 0.1)
        witness.fact(w, "INVALIDATE", "PRODUCT-1.Q-STR")
        w.advance(service.end_h)
        self.assertEqual(w.s.products[0].state, "QUALITY_HOLD")
        self.assertEqual(w._attempt("PRODUCT-1.Q-POND").number, 0)
        self.assertTrue(any(e.kind == "REPAIR_STOPPED" for e in w.s.events))
        validate(w.s, config=self.c)

    def test_valid_local_repair_can_finish_product(self):
        w = self.failed_pond()
        service = self.start_repair(w)
        w.advance(service.end_h)
        codes = [a.code for a in self.c.activities]
        for code in codes[codes.index("WAIT-W") :]:
            witness.run_activity(w, "PRODUCT-1." + code)
        self.assertEqual(w.s.products[0].state, "READY")
        self.assertEqual(
            [q.result for q in w.s.quality if q.activity_id == "PRODUCT-1.Q-POND"], ["FAIL", "PASS"]
        )
        validate(w.s, config=self.c)

    def test_j2_rejects_another_product_while_dual_frames_reside(self):
        config = witness.generator.synthetic_fixture(
            witness.generator.build_configuration(products=2)
        )
        # Two product lots fit PRE in this synthetic layout; J2 retains capacity one product.
        config = replace(
            config,
            resources=tuple(
                replace(r, capacity=2) if r.id == "PRE" else r for r in config.resources
            ),
        )
        w = BuildingBackend(config)
        for aid in (
            "PRODUCT-1.KIT",
            "PRODUCT-1.CUT",
            "PRODUCT-1.MV-IN-B",
            "PRODUCT-1.MV-IN-T",
            "PRODUCT-2.KIT",
            "PRODUCT-2.CUT",
        ):
            witness.run_activity(w, aid)
        for _ in range(1000):
            cmd = witness.command(w, "PRODUCT-2.MV-IN-B")
            result = w.dispatch(cmd)
            if "CAPACITY" in result.reason:
                break
            self.assertIn(
                result.reason, ("CALENDAR_OR_QUALIFICATION", "FATIGUE_PROTECTION", "REST_COMMITTED")
            )
            if result.reason == "FATIGUE_PROTECTION":
                w.rest(tuple(x.person_id for x in cmd.roles), 0.25)
            w.advance(w.time + 0.25)
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "DESTINATION_CAPACITY:J2")
        self.assertEqual({r.owner for r in w.s.residencies if r.location == "J2"}, {"PRODUCT-1"})
        validate(w.s, config=config)


if __name__ == "__main__":
    unittest.main()
