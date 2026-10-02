"""C05 targeted witnesses. Oracles are constants, arithmetic and state invariants."""

import importlib.util
import unittest
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

from adaptive_hrc_scheduling.building_backend import BuildingBackend
from adaptive_hrc_scheduling.building_human import integrate
from adaptive_hrc_scheduling.contracts.building import ContractError, validate
from adaptive_hrc_scheduling.domain import building as b

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("witness", ROOT / "scripts/run_building_witness.py")
witness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(witness)
generator = witness.generator


class BuildingExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = generator.synthetic_fixture(generator.build_configuration())
        cls.vertical = witness.run_chain(until="FLOOR").checkpoint()
        cls.full = witness.run_chain().checkpoint()

    def vertical_world(self):
        return BuildingBackend.restore(self.c, self.vertical)

    def full_world(self):
        return BuildingBackend.restore(self.c, self.full)

    def world_before(self, code):
        w = BuildingBackend(self.c)
        for a in self.c.activities:
            if a.code == code:
                break
            witness.run_activity(w, a.id)
        return w

    def start_when_ready(self, w, aid, **kwargs):
        for _ in range(1000):
            result = w.dispatch(witness.command(w, aid, **kwargs))
            if result.accepted:
                return next(r for r in w.s.running if r.activity_id == aid)
            if result.reason not in (
                "CALENDAR_OR_QUALIFICATION",
                "FATIGUE_PROTECTION",
                "REST_COMMITTED",
            ):
                self.fail(result.reason)
            if result.reason == "FATIGUE_PROTECTION":
                w.rest(tuple(r.person_id for r in witness.command(w, aid, **kwargs).roles), 0.25)
            w.advance(w.time + 0.25)
        self.fail("no feasible start")

    def test_v01_full_chain_ready_received_and_window(self):
        w = self.full_world()
        p = w.s.products[0]
        self.assertEqual(p.state, "READY")
        self.assertEqual(p.location, "OUT1")
        self.assertEqual(len(w.s.quality), 7)
        self.assertTrue(all(q.result == "PASS" and q.valid for q in w.s.quality))
        self.assertEqual({x.id for x in self.c.products[0].bom}, set(p.installed_bom))
        self.assertTrue(any(r.location == "OUT1" for r in w.s.residencies))
        w.advance(w.time + 1)
        witness.fact(w, "RECEIVED", p.product_id)
        self.assertFalse(any(r.location == "OUT1" for r in w.s.residencies))
        w.advance(240)
        for person in self.c.people:
            intervals = [x for x in w.s.intervals if x.person_id == person.id]
            self.assertEqual(intervals[0].start_h, 0)
            self.assertEqual(intervals[-1].end_h, 240)
            self.assertTrue(all(a.end_h == bb.start_h for a, bb in zip(intervals, intervals[1:])))
            # Independent equation integration of every interval, not the executor's integrator.
            f = person.initial_f
            area = 0
            peak = f
            for interval in intervals:
                dt = interval.end_h - interval.start_h
                if interval.activity in ("REST", "OFF_SHIFT"):
                    u = min(dt, f / interval.rate)
                    end = max(0, f - interval.rate * dt)
                    area += u * (f + max(0, f - interval.rate * u)) / 2
                else:
                    end = f + interval.rate * dt
                    area += dt * (f + end) / 2
                peak = max(peak, end)
                f = end
            h = next(x for x in w.s.people if x.person_id == person.id)
            self.assertAlmostEqual(h.exposure, area, places=9)
            self.assertAlmostEqual(h.fatigue, f, places=10)
            self.assertLessEqual(peak, self.c.cap)

    def test_v01_missing_final_quality_not_ready(self):
        w = self.full_world()
        aid = "PRODUCT-1.Q-FIN"
        witness.fact(w, "INVALIDATE", aid)
        self.assertNotEqual(w.s.products[0].state, "READY")
        self.assertIsNone(w.s.products[0].ready_h)

    def test_v11s_component_merge_and_f1_residency(self):
        cut = self.world_before("MV-IN-B")
        self.assertFalse(any(r.entity_id.endswith(".RAW") for r in cut.s.residencies))
        self.assertEqual(len(cut.s.components), 3)
        w = self.vertical_world()
        self.assertEqual(w.s.products[0].location, "F1")
        self.assertTrue(
            all(c.incorporated and c.location == "INCORPORATED" for c in w.s.components)
        )
        self.assertEqual({r.location for r in w.s.residencies}, {"F1"})
        self.assertFalse(w.s.locks)
        self.assertEqual(
            len(
                [
                    e
                    for e in w.s.events
                    if e.kind == "ARRIVAL_CONFIRMED" and e.entity_id.endswith("JOIN-IN")
                ]
            ),
            3,
        )

    def test_v02_destination_full_atomic(self):
        w = self.world_before("MOVE-F")
        w._set(residencies=w.s.residencies + (b.Residency("FOREIGN", "F1", "FOREIGN", False),))
        before = w.s
        result = w.dispatch(witness.command(w, "PRODUCT-1.MOVE-F"))
        # The exact capacity branch is exercised at the next legal calendar slot.
        while result.reason in (
            "CALENDAR_OR_QUALIFICATION",
            "FATIGUE_PROTECTION",
            "REST_COMMITTED",
        ):
            w.advance(w.time + 0.25)
            before = w.s
            result = w.dispatch(witness.command(w, "PRODUCT-1.MOVE-F"))
        self.assertIn("CAPACITY", result.reason)
        for field in (
            "products",
            "components",
            "materials",
            "locks",
            "residencies",
            "attempts",
            "running",
        ):
            self.assertEqual(getattr(before, field), getattr(w.s, field))
        self.assertTrue(any(r.location == "J3" for r in w.s.residencies))

    def test_v03_parallel_distinct_faces(self):
        w = self.vertical_world()
        w.advance(72)
        self.start_when_ready(w, "PRODUCT-1.MEP-E")
        result = w.dispatch(witness.command(w, "PRODUCT-1.MEP-P"))
        self.assertTrue(result.accepted, result.reason)
        self.assertEqual(len(w.s.running), 2)
        w.advance(max(r.end_h for r in w.s.running))
        self.assertFalse(w.s.running)

    def test_v03_unapproved_parallel_rejected(self):
        c = replace(self.c, face_pairs=())
        # This is a declared changed configuration fixture, not forged recovery.
        w = BuildingBackend(c)
        for a in c.activities:
            witness.run_activity(w, a.id)
            if a.code == "FLOOR":
                break
        w.advance(72)
        self.start_when_ready(w, "PRODUCT-1.MEP-E")
        result = w.dispatch(witness.command(w, "PRODUCT-1.MEP-P"))
        self.assertEqual(result.reason, "WORK_FACE_CONFLICT")

    def test_v04_missing_role_does_not_take_locks(self):
        w = self.world_before("W-3D")
        before = w.s
        cmd = replace(witness.command(w, "PRODUCT-1.W-3D"), roles=(b.RoleBinding("W1", "W1"),))
        with self.assertRaises(ContractError):
            w.dispatch(cmd)
        self.assertEqual(w.s, before)

    def test_v05_real_move_intermediate_and_landing(self):
        w = self.world_before("MOVE-F")
        run = self.start_when_ready(w, "PRODUCT-1.MOVE-F")
        w.advance(run.start_h + 0.5)
        self.assertEqual(w.s.products[0].location, "IN_TRANSIT")
        self.assertEqual({r.location for r in w.s.residencies}, {"J3", "F1"})
        w.advance(run.end_h)
        self.assertEqual(w.s.products[0].location, "F1")
        self.assertEqual({r.location for r in w.s.residencies}, {"F1"})

    def test_v05_overload(self):
        c = replace(self.c, products=(replace(self.c.products[0], mass_t=12),))
        w = BuildingBackend(c)
        for a in c.activities:
            if a.code == "MOVE-F":
                break
            witness.run_activity(w, a.id)
        while True:
            result = w.dispatch(witness.command(w, "PRODUCT-1.MOVE-F"))
            if result.reason not in (
                "CALENDAR_OR_QUALIFICATION",
                "FATIGUE_PROTECTION",
                "REST_COMMITTED",
            ):
                break
            w.advance(w.time + 0.25)
        self.assertEqual(result.reason, "MOVE_OVERLOAD")

    def test_v06_elapsed_wait_is_not_release(self):
        w = self.world_before("WAIT-COAT")
        a = w._attempt("PRODUCT-1.WAIT-COAT")
        w.advance(a.wait_until_h)
        result = w.dispatch(witness.command(w, "PRODUCT-1.WAIT-COAT"))
        self.assertEqual(result.reason, "PROCESS_RELEASE_HOLD")
        self.assertEqual(w.s.products[0].location, "J3")

    def test_v07_h_d1_independent_rational_oracle(self):
        p = next(p for p in self.c.people if p.id == "W1")
        h = b.HumanState("W1", 0.2, 0, 0.2, 0)
        duration = Fraction(1, 2) * (1 + Fraction(1, 2) * Fraction(1, 5))
        end = Fraction(1, 5) + Fraction(15, 100) * duration
        first = duration * (Fraction(1, 5) + end) / 2
        second = end * end / (2 * Fraction(1, 5))
        h, _ = integrate(p, h, "WORK", 0, float(duration), 0.8)
        h, _ = integrate(p, h, "REST", float(duration), 2, 0.8)
        self.assertEqual(h.fatigue, 0)
        self.assertAlmostEqual(h.exposure, float(first + second), places=12)
        self.assertEqual(float(first + second), 0.332203125)

    def test_v07_high_f_and_calendar_rejected(self):
        w = self.world_before("W-B")
        w.advance(24)
        w._set(
            people=tuple(
                replace(h, fatigue=0.75, peak=0.75) if h.person_id == "W1" else h
                for h in w.s.people
            )
        )
        result = w.dispatch(witness.command(w, "PRODUCT-1.W-B"))
        self.assertEqual(result.reason, "FATIGUE_PROTECTION")
        w.rest(("W1",), 2)
        w.advance(27.9)
        result = w.dispatch(witness.command(w, "PRODUCT-1.W-B"))
        self.assertEqual(result.reason, "CALENDAR_OR_QUALIFICATION")

    def test_v07_handover_charges_both_and_restore(self):
        w = self.world_before("W-B")
        run = self.start_when_ready(w, "PRODUCT-1.W-B")
        w.advance(run.end_h)
        w.advance(24)
        result = w.handover("PRODUCT-1.W-B", "W1", "W2")
        self.assertTrue(result.accepted, result.reason)
        before = {h.person_id: h.exposure for h in w.s.people}
        w.advance(w.s.services[0].end_h)
        w.advance(w.s.services[0].end_h)
        self.assertFalse(w.s.services)
        self.assertTrue(any(e.kind == "RESTORE_COMPLETE" for e in w.s.events))
        self.assertTrue(
            all(
                next(h.exposure for h in w.s.people if h.person_id == p) > before[p]
                for p in ("W1", "W2")
            )
        )
        result = w.dispatch(witness.command(w, "PRODUCT-1.W-B", bindings={"W1": "W2"}))
        self.assertTrue(result.accepted, result.reason)
        self.assertEqual(w._attempt("PRODUCT-1.W-B").completed_units, 1)

    def test_v08_unknown_dismantling_holds(self):
        w = self.full_world()
        result = w.repair_quality("PRODUCT-1.Q-STR")
        self.assertEqual(result.reason, "UNKNOWN_DISMANTLING_METHOD_HOLD")

    def test_v08_local_repair_repeats_wait_and_inspection(self):
        w = self.world_before("Q-POND")
        run = self.start_when_ready(w, "PRODUCT-1.Q-POND")
        w.advance(run.end_h)
        witness.fact(w, "QUALITY_RESULT", "PRODUCT-1.Q-POND", "FAIL", 0)
        for _ in range(500):
            result = w.repair_quality("PRODUCT-1.Q-POND")
            if result.accepted:
                break
            self.assertIn(
                result.reason, ("CALENDAR_OR_QUALIFICATION", "FATIGUE_PROTECTION", "REST_COMMITTED")
            )
            if result.reason == "FATIGUE_PROTECTION":
                w.rest(("QA1", "T1"), 0.25)
            w.advance(w.time + 0.25)
        self.assertTrue(result.accepted)
        service = w.s.services[0]
        w.advance(service.end_h)
        self.assertEqual(w._attempt("PRODUCT-1.WAIT-W").number, 1)
        self.assertGreaterEqual(w._attempt("PRODUCT-1.WAIT-W").wait_until_h, w.time + 4)
        for code in ("WAIT-W", "TEST-SET", "WAIT-TEST", "Q-POND"):
            witness.run_activity(w, "PRODUCT-1." + code)
        self.assertEqual(
            [q.result for q in w.s.quality if q.activity_id == "PRODUCT-1.Q-POND"], ["FAIL", "PASS"]
        )
        self.assertEqual(
            w.repair_quality("PRODUCT-1.Q-POND").reason, "REPAIR_LIMIT_QUARANTINE_REQUIRED"
        )

    def test_v09_variant_missing_kit_only_blocks_dependency(self):
        c = generator.synthetic_fixture(generator.build_configuration("SR-W2"))
        c = replace(
            c,
            materials=tuple(
                replace(m, released=False) if m.activity_id.endswith(".MEP-P") else m
                for m in c.materials
            ),
        )
        w = BuildingBackend(c)
        for a in c.activities:
            witness.run_activity(w, a.id)
            if a.code == "FLOOR":
                break
        w.advance(72)
        run = self.start_when_ready(w, "PRODUCT-1.MEP-E")
        result = w.dispatch(witness.command(w, "PRODUCT-1.MEP-P"))
        self.assertIn("MATERIAL_KIT", result.reason)
        self.assertEqual(len(w.s.running), 1)
        w.advance(run.end_h)

    def test_v10_cancel_suspended_tail_and_cleanup(self):
        w = self.world_before("MOVE-F")
        run = self.start_when_ready(w, "PRODUCT-1.MOVE-F")
        w.advance(run.start_h + 0.5)
        witness.fact(w, "CANCEL", "PRODUCT-1")
        self.assertTrue(any(x.resource_id == "CR1" for x in w.s.locks))
        self.assertEqual(w.cleanup("PRODUCT-1").reason, "UNKNOWN_COMPONENT_CLEARANCE_HOLD")
        w.advance(run.end_h)
        self.assertTrue(w.s.products[0].cancelled)
        for _ in range(200):
            result = w.cleanup("PRODUCT-1")
            if result.accepted:
                break
            self.assertIn(
                result.reason, ("CALENDAR_OR_QUALIFICATION", "FATIGUE_PROTECTION", "REST_COMMITTED")
            )
            w.advance(w.time + 0.25)
        self.assertTrue(result.accepted, result.reason)
        w.advance(w.s.services[0].end_h)
        self.assertEqual(w.s.products[0].state, "QUARANTINED")
        self.assertEqual(w.s.products[0].location, "Q1")
        self.assertIsNone(w.s.products[0].ready_h)

    def test_v10_crane_failure_holds_no_time_mask(self):
        w = self.world_before("MOVE-F")
        run = self.start_when_ready(w, "PRODUCT-1.MOVE-F")
        w.advance(run.start_h + 0.5)
        witness.fact(w, "FAILURE", "CR1")
        state = w.s
        self.assertEqual(w.s.running[0].state, "EMERGENCY_HOLD")
        with self.assertRaisesRegex(ContractError, "EMERGENCY_HOLD"):
            w.advance(run.end_h)
        self.assertEqual(w.s, state)
        witness.fact(w, "REPAIR", "CR1")
        with self.assertRaisesRegex(ContractError, "EMERGENCY_HOLD"):
            w.advance(run.end_h)

    def test_v10_same_tick_completion_then_cancel(self):
        w = self.world_before("MOVE-OUT")
        run = self.start_when_ready(w, "PRODUCT-1.MOVE-OUT")
        event = b.WorldEvent("CANCEL-AT-LANDING", run.end_h, "CANCEL", "PRODUCT-1", None, None)
        w._set(scenario=replace(w.s.scenario, events=(event,)))
        w.advance(run.end_h)
        self.assertEqual(w.s.products[0].location, "OUT1")
        self.assertTrue(w.s.products[0].cancelled)
        result = w.dispatch(witness.command(w, "PRODUCT-1.READY"))
        self.assertEqual(result.reason, "CANCELLED_OR_QUARANTINED")

    def test_idempotent_command_and_fact(self):
        w = BuildingBackend(self.c)
        cmd = witness.command(w, "PRODUCT-1.KIT")
        self.assertTrue(w.dispatch(cmd).accepted)
        state = w.s
        self.assertEqual(w.dispatch(cmd).reason, "DUPLICATE_COMMAND")
        self.assertEqual(w.s, state)
        e = b.WorldEvent("CANCEL-1", 0, "CANCEL", "PRODUCT-1", None, None)
        w.apply_event(e)
        state = w.s
        self.assertEqual(w.apply_event(e).reason, "DUPLICATE_EVENT")
        self.assertEqual(w.s, state)

    def test_checkpoint_restore_mid_move_and_delayed_observation(self):
        w = self.world_before("MOVE-F")
        run = self.start_when_ready(w, "PRODUCT-1.MOVE-F")
        w.advance(run.start_h + 0.3)
        self.assertEqual(w.observe(delay_h=2), ())
        recovered = BuildingBackend.restore(self.c, w.checkpoint())
        for world in (w, recovered):
            world.advance(run.end_h + 2)
        self.assertEqual(w.checkpoint(), recovered.checkpoint())
        self.assertEqual(w.deliver_observations(), recovered.deliver_observations())

    def test_paired_future_observations_equal(self):
        worlds = []
        for t in (30, 40):
            s = b.HiddenScenario(
                "C04-1.0",
                self.c.id,
                7,
                (b.WorldEvent("FAIL-FUTURE", t, "FAILURE", "CR1", None, None),),
            )
            w = BuildingBackend(self.c, s)
            w.advance(20)
            worlds.append(w)
        self.assertEqual(worlds[0].observe(), worlds[1].observe())

    def test_default_gaps_and_hr_remain_blocked(self):
        c = generator.build_configuration()
        w = BuildingBackend(c)
        self.assertEqual(
            w.dispatch(witness.command(w, "PRODUCT-1.KIT")).reason, "UNQUALIFIED_METHOD"
        )
        a = next(a for a in c.activities if a.code == "W-B")
        cmd = witness.command(w, a.id, mode=a.modes[1].id)
        with self.assertRaisesRegex(ContractError, "disabled"):
            w.dispatch(cmd)

    def test_snapshot_digest_cannot_restore_different_configuration(self):
        with self.assertRaisesRegex(ContractError, "digest"):
            BuildingBackend.restore(replace(self.c, min_rest_h=0.5), self.vertical)

    def test_sr_w2_full_chain_has_additional_branch(self):
        world = witness.run_chain(variant="SR-W2")
        self.assertEqual(world.s.products[0].state, "READY")
        self.assertTrue(
            {"B-BRANCH", "B-EXTRA-BASIN", "B-EXTRA-SOCKET"}
            <= set(world.s.products[0].installed_bom)
        )
        self.assertEqual(world._attempt("PRODUCT-1.MEP-P").completed_units, 4)
        self.assertEqual(world._attempt("PRODUCT-1.Q-FIN").completed_units, 3)

    def test_conditional_hr_robot_retains_cell_until_unload(self):
        config = generator.synthetic_fixture(generator.build_configuration(), hr=True)
        world = BuildingBackend(config)
        for code in ("KIT", "CUT", "MV-IN-B"):
            witness.run_activity(world, "PRODUCT-1." + code)
        mode = world.activities["PRODUCT-1.W-B"].modes[1].id
        first = self.start_when_ready(world, "PRODUCT-1.W-B", mode=mode)
        world.advance(first.end_h)
        second = self.start_when_ready(world, "PRODUCT-1.W-B", mode=mode)
        self.assertFalse(second.roles)
        world.advance(second.end_h)
        self.assertTrue(any(x.resource_id == "R1" for x in world.s.locks))
        self.assertTrue(any(x.location == "J2" for x in world.s.residencies))
        self.assertFalse(any(x.resource_id == "OP1" for x in world.s.locks))
        third = self.start_when_ready(world, "PRODUCT-1.W-B", mode=mode)
        world.advance(third.end_h)
        self.assertFalse(any(x.resource_id == "R1" for x in world.s.locks))
        self.assertTrue(any(x.location == "J2" for x in world.s.residencies))

    def test_changed_fixture_revision_rejected(self):
        config = generator.synthetic_fixture(generator.build_configuration(), hr=True)
        config = replace(
            config,
            evidence=tuple(
                replace(e, revision="v2") if e.id == "G2-FIXTURE" else e for e in config.evidence
            ),
        )
        with self.assertRaisesRegex(ContractError, "revision"):
            BuildingBackend(config)

    def test_recovery_rejects_removed_running_lock(self):
        world = BuildingBackend(self.c)
        world.dispatch(witness.command(world, "PRODUCT-1.KIT"))
        bad = replace(world.s, locks=())
        with self.assertRaisesRegex(ContractError, "missing lock"):
            validate(bad, config=self.c)

    def test_recovery_after_arbitrary_work_split(self):
        world = self.world_before("W-B")
        run = self.start_when_ready(world, "PRODUCT-1.W-B")
        world.advance((run.start_h + run.end_h) / 2)
        restored = BuildingBackend.restore(self.c, world.checkpoint())
        for w in (world, restored):
            w.advance(run.end_h)
        self.assertEqual(world.checkpoint(), restored.checkpoint())

    def test_no_premature_completion(self):
        import math

        world = BuildingBackend(self.c)
        run = self.start_when_ready(world, "PRODUCT-1.KIT")
        world.advance(math.nextafter(run.end_h, run.start_h))
        self.assertEqual(world._attempt("PRODUCT-1.KIT").state, "RUNNING")
        world.advance(run.end_h)
        self.assertEqual(world._attempt("PRODUCT-1.KIT").state, "COMPLETED")

    def test_two_products_block_and_release_out1(self):
        config = generator.synthetic_fixture(generator.build_configuration(products=2))
        world = BuildingBackend(config)
        for a in config.activities:
            if a.product_id == "PRODUCT-1":
                witness.run_activity(world, a.id)
        for a in config.activities:
            if a.product_id != "PRODUCT-2":
                continue
            if a.code == "MOVE-OUT":
                break
            witness.run_activity(world, a.id)
        # Only the destination is blocked; reach a legal move-start work window.
        for _ in range(200):
            result = world.dispatch(witness.command(world, "PRODUCT-2.MOVE-OUT"))
            if "CAPACITY" in result.reason:
                break
            self.assertIn(
                result.reason, ("CALENDAR_OR_QUALIFICATION", "FATIGUE_PROTECTION", "REST_COMMITTED")
            )
            world.advance(world.time + 0.25)
        self.assertIn("CAPACITY", result.reason)
        self.assertEqual(world._product("PRODUCT-2").location, "F1")
        witness.fact(world, "RECEIVED", "PRODUCT-1")
        witness.run_activity(world, "PRODUCT-2.MOVE-OUT")
        witness.run_activity(world, "PRODUCT-2.READY")
        self.assertEqual(world._product("PRODUCT-2").state, "READY")


if __name__ == "__main__":
    unittest.main()
