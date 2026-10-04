"""S14 shared contracts and causal, independently audited logistics witnesses."""

import importlib.util
import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from adaptive_hrc_scheduling.contracts.codec import ContractError, as_data
from adaptive_hrc_scheduling.contracts.logistics import TOP_LEVEL, dumps, loads, validate
from adaptive_hrc_scheduling.control.logistics_ledger import EventLedger
from adaptive_hrc_scheduling.control.logistics_loop import run_loop
from adaptive_hrc_scheduling.domain import logistics as m
from adaptive_hrc_scheduling.logistics_backend import LogisticsBackend
from adaptive_hrc_scheduling.logistics_checker import check_run
from adaptive_hrc_scheduling.planning.logistics import choose, planning_input

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "ml_generator", ROOT / "scripts/build_logistics_contracts.py"
)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def world(witness="V01", synthetic=True):
    return LogisticsBackend(fixture.configuration(synthetic=synthetic, witness=witness))


def event(w, kind, entity="RAW", evidence="ML-RELEASE", product="PRODUCT-1", ident=None):
    e = m.WorldEvent(
        ident or f"WORLD-{len(w.events)}",
        w.run_id,
        w.epoch,
        w.s.time_h,
        kind,
        entity,
        product,
        0,
        "PASS",
        evidence,
    )
    w.apply_world(e)
    return e


def arrival(w):
    event(w, "ARRIVAL", evidence="RECEIVE")
    event(w, "IDENTIFY")
    event(w, "RELEASE")


def finish(w, op):
    cmd = fixture.command(w, op)
    receipt = w.dispatch(cmd)
    if receipt.kind != "STARTED":
        raise AssertionError(receipt.reason)
    end = next(r.earliest_end_h for r in w.s.running if r.command.id == cmd.id)
    w.advance(end)
    return cmd


class LogisticsTests(unittest.TestCase):
    def test_foreign_entities_wrong_modes_and_walk_person_are_rejected(self):
        c = fixture.configuration(synthetic=True, witness="V03")
        with self.assertRaisesRegex(ContractError, "FOREIGN_ENTITY"):
            validate(
                replace(
                    c,
                    operations=(replace(c.operations[0], entity_id="PRODUCT-2"),)
                    + c.operations[1:],
                )
            )
        w = world()
        arrival(w)
        with self.assertRaisesRegex(ContractError, "COMMAND_MODE"):
            w.dispatch(replace(fixture.command(w, "TAKE-IN"), mode_id="H"))
        c = fixture.command(w, "WALK-0")
        with self.assertRaisesRegex(ContractError, "WALK_PERSON_IDENTITY"):
            w.dispatch(replace(c, roles=(m.RoleBinding("W1", "W2"),)))

    def test_hst_qualification_is_not_fork_qualification(self):
        c = fixture.configuration(synthetic=True)
        people = tuple(
            replace(p, qualifications=tuple(q for q in p.qualifications if q != "FORK"))
            if p.id == "P1"
            else p
            for p in c.people
        )
        w = LogisticsBackend(replace(c, people=people))
        arrival(w)
        receipt = w.dispatch(fixture.command(w, "TAKE-IN"))
        self.assertIn("PERSON_QUALIFICATION", receipt.reason)
        self.assertFalse(w.s.owners)
        self.audit(w)

    def test_external_completion_replay_is_idempotent(self):
        w = world("V03")
        finish(w, "SHIP-1")
        event(w, "RECEIVE_PERMIT", entity="PRODUCT-1")
        c = finish(w, "RECEIVE-1")
        state = w.s
        receipt = w.dispatch(c)
        self.assertEqual(receipt.kind, "COMPLETED")
        self.assertEqual(w.s, state)
        self.assertEqual(self.audit(w).metrics.received_count, 1)

    def test_work_cannot_be_configured_as_recovery(self):
        c = fixture.configuration(synthetic=True)
        op = replace(c.operations[0], phase="REST")
        with self.assertRaisesRegex(ContractError, "REST_PHASE_MISMATCH"):
            validate(replace(c, operations=(op,) + c.operations[1:]))

    def test_cancelled_stock_disposal_does_not_erase_or_recreate_quantity(self):
        c = fixture.configuration(synthetic=True)
        op = fixture.operation("DISPOSE", "SCRAP", source="RECEIVE", inputs=(("RAW", 6),))
        w = LogisticsBackend(replace(c, operations=c.operations + (op,)))
        arrival(w)
        event(w, "CANCEL", entity="PRODUCT-1")
        finish(w, "DISPOSE")
        self.assertEqual((w._lot("RAW").available, w._lot("RAW").scrapped), (0, 6))
        self.assertEqual(len(w.s.products), 1)
        self.audit(w)

    def test_empty_history_cannot_contain_unrecorded_stock_changes(self):
        w = world()
        self.audit(w)
        state = replace(w.s, lots=(replace(w.s.lots[0], available=99), w.s.lots[1]))
        self.assertEqual(
            check_run(w.config, replace(w.snapshot(), state=state)).status, "INCOMPLETE"
        )

    def test_calendar_cap_and_missing_quality_cannot_start(self):
        for violation in ("cap", "calendar", "quality"):
            c = fixture.configuration(synthetic=True, witness="V02")
            op = fixture.operation(
                "GUARDED",
                "WORK",
                source="J2",
                roles=(("W1", "WELD", "J2"),),
                equipment=("WELD-J2",),
                duration=2,
            )
            people = tuple(
                replace(p, initial_f=c.cap)
                if p.id == "W1" and violation == "cap"
                else replace(p, valid_until_h=0.01)
                if p.id == "W1" and violation == "calendar"
                else p
                for p in c.people
            )
            if violation == "quality":
                op = replace(op, quality_gates=("G2",))
            w = LogisticsBackend(replace(c, people=people, operations=c.operations + (op,)))
            before = w.s
            r = w.dispatch(fixture.command(w, op.id))
            self.assertIn(r.kind, ("REJECTED", "DEFERRED"))
            self.assertEqual(w.s.humans, before.humans)
            self.assertFalse(w.s.owners)
            self.audit(w)

    def test_transit_failure_retains_actual_position_and_source_commitment(self):
        w = world()
        arrival(w)
        c = fixture.command(w, "TAKE-IN")
        w.dispatch(c)
        w.advance(0.02, auto_complete=False)
        point = w.routes["S01"].points[2]
        proof = replace(
            w.light_readback(c),
            location="IN_TRANSIT",
            support="FORK-01",
            position_m=(point.x, point.y, point.z),
            landed=False,
            detached=False,
            progress=0.25,
            role_positions=(m.PersonPosition("P1", "IN_TRANSIT"), m.PersonPosition("QA1", "STEEL")),
        )
        w.progress(c.id, proof)
        event(w, "FAILURE", entity="FORK-01")
        self.assertEqual(w._position("RAW").location, "IN_TRANSIT")
        self.assertEqual(w.s.motions, (proof,))
        event(w, "REPAIR", entity="FORK-01")
        resume = replace(fixture.command(w, "TAKE-IN", "RESUME"), resume_of=c.id)
        self.assertEqual(w.dispatch(resume).kind, "STARTED")
        self.assertEqual(w.s.running[0].start_progress, 0.25)
        w.advance(w.s.running[0].earliest_end_h)
        self.assertEqual(w._position("RAW").location, "STEEL")
        self.assertFalse(w.s.motions)
        self.audit(w)

    def test_partial_reservation_does_not_allow_overcommit(self):
        c = fixture.configuration(synthetic=True)
        c = replace(
            c,
            lots=(replace(c.lots[0], quantity=10), c.lots[1]),
            operations=c.operations
            + (
                fixture.operation("R6", "RESERVE", source="RECEIVE", inputs=(("RAW", 6),)),
                fixture.operation("R5", "RESERVE", source="RECEIVE", inputs=(("RAW", 5),)),
            ),
        )
        w = LogisticsBackend(c)
        arrival(w)
        finish(w, "R6")
        before = w.s
        self.assertEqual(w.dispatch(fixture.command(w, "R5")).kind, "REJECTED")
        self.assertEqual(w._lot("RAW").available, 4)
        self.assertEqual(w.s.reservations, before.reservations)
        self.audit(w)

    def test_ready_cannot_use_missing_core_mapping(self):
        c = fixture.configuration(synthetic=True, witness="V03")
        op = fixture.operation(
            "FALSE-READY", "READY", product="PRODUCT-3", entity="PRODUCT-3", source="OUT1"
        )
        w = LogisticsBackend(
            replace(
                c,
                initial_ready_products=(),
                initial_ready_evidence=(),
                operations=c.operations + (op,),
            )
        )
        self.assertIn("READY_MISSING_CORE_MAPPING", w.dispatch(fixture.command(w, op.id)).reason)
        self.assertIsNone(w._product("PRODUCT-3").ready_h)
        self.audit(w)

    def test_e1_cart_branch_delivery_and_consumption(self):
        c = fixture.configuration(synthetic=True)
        lot = m.Lot(
            "MEP",
            "PRODUCT-1",
            "MEP",
            "set",
            1,
            0.08,
            (1.2, 0.8, 0.6),
            "MEP-RECEIVE",
            (),
            True,
            True,
            True,
        )
        ops = (
            fixture.operation(
                "CART-IN",
                "TRANSFER",
                entity="MEP",
                source="MEP-RECEIVE",
                target="MEP-STORE",
                route="P01",
                equipment=("CART-01",),
                roles=(("E1", "CART", "MEP-RECEIVE"), ("PL1", "PLUMB", "MEP-STORE")),
                phase="PUSH",
            ),
            fixture.operation(
                "MEP-RESERVE",
                "RESERVE",
                activity="MEP-USE",
                source="MEP-STORE",
                inputs=(("MEP", 1),),
                prior=("CART-IN",),
            ),
            fixture.operation(
                "MEP-USE", "WORK", source="MEP-STORE", inputs=(("MEP", 1),), prior=("MEP-RESERVE",)
            ),
        )
        c = replace(
            c,
            lots=c.lots + (lot,),
            operations=c.operations + ops,
            person_positions=tuple(
                replace(
                    p,
                    location={"E1": "MEP-RECEIVE", "PL1": "MEP-STORE"}.get(p.person_id, p.location),
                )
                for p in c.person_positions
            ),
        )
        w = LogisticsBackend(c)
        for op in ops:
            finish(w, op.id)
        self.assertEqual(w._lot("MEP").consumed, 1)
        self.assertEqual(w._position("E1").location, "MEP-STORE")
        self.audit(w)

    def test_reordered_duplicate_and_reset_feedback_never_rolls_state_back(self):
        w = world()
        arrival(w)
        finish(w, "TAKE-IN")
        ledger = EventLedger(w.config, w.run_id)
        latest = w.events[-1]
        self.assertEqual(
            ledger.accept(latest, received_sim_h=w.s.time_h + 0.1, wall_elapsed_s=1), "BUFFERED"
        )
        self.assertIsNone(ledger.state)
        self.assertEqual(ledger.status, "INCOMPLETE")
        for e in w.events[:-1]:
            ledger.accept(e, received_sim_h=w.s.time_h + 0.2, wall_elapsed_s=2)
        self.assertEqual(ledger.state, w.s)
        self.assertEqual(
            ledger.accept(latest, received_sim_h=w.s.time_h + 0.3, wall_elapsed_s=3), "DUPLICATE"
        )
        with self.assertRaisesRegex(ContractError, "PAYLOAD_CONFLICT"):
            ledger.accept(
                replace(latest, reason="tampered"), received_sim_h=w.s.time_h + 1, wall_elapsed_s=0
            )
        ledger.reset(1)
        self.assertEqual(
            ledger.accept(latest, received_sim_h=w.s.time_h + 1, wall_elapsed_s=0), "STALE_EPOCH"
        )
        self.assertIsNone(ledger.state)

    def test_s11_rules_and_s12_causal_loop_execute_new_logistics(self):
        for rule in ("EDD", "SPT", "FASTEST_LEGAL"):
            w = world()
            scenario = m.HiddenScenario(
                "S14-ML-1.0",
                w.config.id,
                tuple(
                    m.WorldEvent(
                        f"ORDER-{i}", w.run_id, 0, 0, kind, "RAW", "PRODUCT-1", 0, "PASS", evidence
                    )
                    for i, (kind, evidence) in enumerate(
                        (
                            ("ARRIVAL", "RECEIVE"),
                            ("IDENTIFY", "ML-RELEASE"),
                            ("RELEASE", "ML-RELEASE"),
                        )
                    )
                ),
            )
            turns, report = run_loop(w, scenario, rule=rule)
            self.assertEqual(report.status, "PASS", report.findings)
            self.assertIn("OPEN-WORK", w.s.completed)
            self.assertGreater(len(turns), 8)

    def audit(self, w):
        result = check_run(w.config, w.snapshot())
        self.assertEqual(result.status, "PASS", result.findings[:5])
        return result

    def test_ten_shared_schemas_roundtrip_and_version_rejection(self):
        files = fixture.generated()
        self.assertEqual(len(TOP_LEVEL), 10)
        c = fixture.configuration()
        for kind in TOP_LEVEL:
            text = files[f"examples/logistics_contracts/{kind.__name__}.json"]
            value = loads(kind, text, config=c)
            self.assertEqual(json.loads(dumps(value, config=c)), json.loads(text))
        data = as_data(c)
        data["schema_version"] = "C04-1.0"
        with self.assertRaises(ContractError):
            loads(m.Configuration, json.dumps(data))

    def test_generated_files_are_exact_and_route_endpoints_are_bound(self):
        for name, text in fixture.generated().items():
            self.assertEqual((ROOT / name).read_bytes(), text.encode(), name)
        c = fixture.configuration(synthetic=True)
        routes = tuple(
            replace(r, points=r.points[:-1] + (m.Point(40, 40, 0.8),)) if r.id == "S01" else r
            for r in c.routes
        )
        with self.assertRaisesRegex(ContractError, "ROUTE_ENDPOINT_MISMATCH"):
            validate(replace(c, routes=routes))

    def test_preparation_has_no_motion_then_travel_is_observed(self):
        w = world()
        arrival(w)
        w.dispatch(fixture.command(w, "TAKE-IN"))
        w.advance(0.03)
        self.assertFalse(w.s.motions)
        self.assertEqual(w._position("RAW").location, "RECEIVE")
        w.advance(0.044)
        self.assertEqual(w._position("RAW").location, "IN_TRANSIT")
        self.assertTrue(w.s.owners)
        self.audit(w)

    def test_v01_received_preprocessed_delivered_then_consumed(self):
        w = world()
        self.assertEqual(w._position("STEEL-COMP").location, "UNFABRICATED")
        arrival(w)
        for op in (
            "TAKE-IN",
            "TO-PRE",
            "RESERVE-CUT",
            "CUT",
            "WALK-0",
            "DELIVER",
            "RESERVE-WORK",
            "OPEN-WORK",
        ):
            finish(w, op)
        self.assertEqual(w._lot("RAW").converted, 6)
        self.assertEqual(w._lot("PREPARED").consumed, 5)
        self.assertEqual(w._position("P1").location, "PRE-OUT")
        self.assertEqual(w._position("STEEL-COMP").location, "PRE-OUT")
        self.assertEqual(w.s.reservations, ())
        self.audit(w)

    def test_v02_component_actual_move_and_two_fixed_weld_stations(self):
        w = world("V02")
        for op in ("MV-IN-B", "W-B", "WALK-0", "W-3D"):
            finish(w, op)
        self.assertEqual(w._position("BOTTOM").location, "J2")
        self.assertEqual(w._position("WELD-J2").location, "J2")
        self.assertEqual(w._position("WELD-J3").location, "J3")
        self.audit(w)

    def test_v03_internal_transfer_is_not_external_receipt(self):
        w = world("V03")
        finish(w, "SHIP-1")
        self.assertIsNone(w._product("PRODUCT-1").received_h)
        c = fixture.command(w, "RECEIVE-1", "NO-PERMIT")
        self.assertEqual(w.dispatch(c).kind, "REJECTED")
        event(w, "RECEIVE_PERMIT", entity="PRODUCT-1")
        finish(w, "RECEIVE-1")
        self.assertEqual(w._position("PRODUCT-1").location, "EXTERNAL")
        for op in ("EMPTY-CR1", "WALK-0", "WALK-1", "BUFFER-3"):
            finish(w, op)
        self.assertEqual(w._position("PRODUCT-3").location, "FG1")
        self.assertEqual(w._position("PRODUCT-2").location, "FG2")
        report = self.audit(w)
        self.assertEqual(
            (
                report.metrics.ready_count,
                report.metrics.received_count,
                report.metrics.internal_finished_count,
            ),
            (3, 1, 2),
        )

    def test_unknown_qualifications_do_not_become_scene_pass(self):
        w = world(synthetic=False)
        receipt = w.dispatch(fixture.command(w, "TAKE-IN"))
        self.assertEqual(receipt.kind, "REJECTED")
        self.assertFalse(w.s.running or w.s.owners)
        self.audit(w)

    def test_duplicate_payload_and_reset_epoch(self):
        w = world()
        arrival(w)
        c = fixture.command(w, "TAKE-IN")
        first = w.dispatch(c)
        state = w.s
        self.assertEqual(w.dispatch(c), first)
        self.assertEqual(w.s, state)
        with self.assertRaisesRegex(ContractError, "PAYLOAD_CONFLICT"):
            w.dispatch(replace(c, issued_sim_h=1))
        w.reset()
        with self.assertRaisesRegex(ContractError, "STALE_EPOCH"):
            w.dispatch(c)

    def test_unreleased_arrival_cannot_be_transferred(self):
        w = world()
        event(w, "ARRIVAL", evidence="RECEIVE")
        before = w.s.lots
        receipt = w.dispatch(fixture.command(w, "TAKE-IN"))
        self.assertEqual(receipt.kind, "REJECTED")
        self.assertEqual(w.s.lots, before)
        self.audit(w)

    def test_atomic_quantity_overreservation(self):
        c = fixture.configuration(synthetic=True)
        op = fixture.operation("TOO-MUCH", "RESERVE", source="RECEIVE", inputs=(("RAW", 7),))
        c = replace(c, operations=c.operations + (op,))
        w = LogisticsBackend(c)
        arrival(w)
        self.assertEqual(w.dispatch(fixture.command(w, "TOO-MUCH")).kind, "REJECTED")
        self.assertEqual(w._lot("RAW").available, 6)
        self.assertFalse(w.s.reservations)
        self.audit(w)

    def test_wrong_units_and_fixed_machine_motion_are_rejected(self):
        c = fixture.configuration(synthetic=True)
        with self.assertRaisesRegex(ContractError, "UNIT_CONVERSION"):
            validate(replace(c, lots=(c.lots[0], replace(c.lots[1], unit="t"))))
        op = fixture.operation(
            "ILLEGAL-MOVE",
            "TRANSFER",
            entity="CUT1",
            source="RECEIVE",
            target="STEEL",
            route="S01",
            equipment=("FORK-01",),
        )
        with self.assertRaisesRegex(ContractError, "FIXED_DEVICE_MOTION"):
            validate(replace(c, operations=c.operations + (op,)))

    def test_missing_role_and_source_person_must_reject(self):
        w = world()
        arrival(w)
        c = fixture.command(w, "TAKE-IN")
        with self.assertRaisesRegex(ContractError, "ROLE_COVERAGE"):
            w.dispatch(replace(c, roles=()))
        c = fixture.configuration(synthetic=True)
        c = replace(
            c,
            person_positions=tuple(
                replace(p, location="PRE-IN") if p.person_id == "P1" else p
                for p in c.person_positions
            ),
        )
        w = LogisticsBackend(c)
        arrival(w)
        self.assertEqual(w.dispatch(fixture.command(w, "TAKE-IN")).reason, "PERSON_NOT_PRESENT")

    def test_device_failure_preserves_load_source_and_ownership(self):
        w = world()
        arrival(w)
        c = fixture.command(w, "TAKE-IN")
        w.dispatch(c)
        event(w, "FAILURE", entity="FORK-01")
        self.assertEqual(w.s.running[0].status, "EXCEPTION")
        self.assertTrue(w.s.owners)
        self.assertEqual(w._lot("RAW").location, "RECEIVE")
        event(w, "REPAIR", entity="FORK-01")
        self.assertEqual(w.s.running[0].status, "EXCEPTION")
        self.audit(w)

    def test_fault_resume_keeps_remaining_work_and_original_attempt(self):
        w = world()
        arrival(w)
        c = fixture.command(w, "TAKE-IN")
        w.dispatch(c)
        original_end = w.s.running[0].earliest_end_h
        w.advance(original_end / 2, auto_complete=False)
        event(w, "FAILURE", entity="FORK-01")
        w.advance(w.s.time_h + 0.01, auto_complete=False)
        event(w, "REPAIR", entity="FORK-01")
        resume = replace(fixture.command(w, "TAKE-IN", "RESUME-1"), resume_of=c.id)
        self.assertEqual(w.dispatch(resume).kind, "STARTED")
        self.assertAlmostEqual(w.s.running[0].earliest_end_h, original_end + 0.01)
        w.advance(w.s.running[0].earliest_end_h)
        self.assertEqual(w._lot("RAW").location, "STEEL")
        self.assertEqual(w.s.completed.count("TAKE-IN"), 1)
        self.audit(w)

    def test_duplicate_arrival_and_foreign_product_do_not_add_stock(self):
        w = world()
        e = event(w, "ARRIVAL", evidence="RECEIVE")
        state = w.s
        self.assertIsNone(w.apply_world(e))
        self.assertEqual(w.s, state)
        with self.assertRaisesRegex(ContractError, "DUPLICATE"):
            event(w, "ARRIVAL", evidence="RECEIVE", ident="ANOTHER-ARRIVAL")
        self.assertEqual(w.s, state)

    def test_b_plus_one_full_slot_defers_third_without_fake_release(self):
        c = fixture.configuration(synthetic=True, witness="V03")
        c = replace(
            c,
            operations=tuple(
                replace(o, prerequisites=()) if o.id == "BUFFER-3" else o for o in c.operations
            ),
            devices=tuple(
                replace(d, initial_location="OUT1") if d.id == "CR1" else d for d in c.devices
            ),
            person_positions=tuple(
                replace(p, location="OUT1" if p.person_id == "Lrig" else "FG1")
                if p.person_id in ("Lrig", "QA1")
                else p
                for p in c.person_positions
            ),
        )
        w = LogisticsBackend(c)
        state = w.s
        r = w.dispatch(fixture.command(w, "BUFFER-3"))
        self.assertEqual(r.kind, "DEFERRED")
        self.assertEqual(r.reason, "CAPACITY:FG1")
        self.assertEqual(w.s.positions, state.positions)
        self.assertFalse(w.s.owners)
        self.audit(w)

    def test_tool_hold_survives_operator_release_and_requires_retrieval(self):
        c = fixture.configuration(synthetic=True, witness="V02")
        locs = {p.id: p.position for p in c.places}
        routes = tuple(
            m.Route(
                ident,
                source,
                target,
                "TEST1",
                ("TEST-AISLE",),
                tuple(m.Point(*locs[x]) for x in (source, target)),
                0.5,
                0.5,
                "ML-ROUTE",
                (0.8, 1.1, 1.2),
            )
            for ident, source, target in (
                ("TOOL-OUT", "TEST-PARK", "TEST-USE"),
                ("TOOL-BACK", "TEST-USE", "TEST-PARK"),
            )
        )
        deploy = fixture.operation(
            "DEPLOY",
            "DEPLOY_TOOL",
            entity="TEST1",
            source="TEST-PARK",
            target="TEST-USE",
            route="TOOL-OUT",
            roles=(("QA1", "TOOL", "TEST-PARK"),),
            equipment=("TEST1",),
            phase="PUSH",
            hold="TEST1",
        )
        retrieve = fixture.operation(
            "RETRIEVE",
            "RETRIEVE_TOOL",
            entity="TEST1",
            source="TEST-USE",
            target="TEST-PARK",
            route="TOOL-BACK",
            roles=(("QA1", "TOOL", "TEST-USE"),),
            equipment=("TEST1",),
            phase="PUSH",
            release="TEST1",
            prior=("DEPLOY",),
        )
        steal = fixture.operation("STEAL", "WORK", source="TEST-USE", equipment=("TEST1",))
        c = replace(
            c,
            routes=c.routes + routes,
            operations=(deploy, retrieve, steal),
            person_positions=tuple(
                replace(p, location="TEST-PARK") if p.person_id == "QA1" else p
                for p in c.person_positions
            ),
        )
        w = LogisticsBackend(c)
        finish(w, "DEPLOY")
        self.assertEqual({x.resource_id for x in w.s.owners}, {"TEST1"})
        self.assertEqual(w.dispatch(fixture.command(w, "STEAL")).kind, "DEFERRED")
        finish(w, "RETRIEVE")
        self.assertFalse(w.s.owners)
        self.assertEqual(w._position("QA1").location, "TEST-PARK")
        self.audit(w)

    def test_rest_label_tampering_is_detected_even_with_matching_numbers(self):
        w = world()
        arrival(w)
        finish(w, "TAKE-IN")
        e = w.events[-1]
        rows = list(e.state.intervals)
        rows[0] = replace(rows[0], phase="REST")
        state = replace(e.state, intervals=tuple(rows))
        trace = replace(
            w.snapshot(), state=state, events=tuple(w.events[:-1]) + (replace(e, state=state),)
        )
        self.assertTrue(
            any(f.reason == "HUMAN_INTERVALS" for f in check_run(w.config, trace).findings)
        )

    def test_future_world_time_is_rejected_and_observation_delivery_is_delayed(self):
        w = world()
        future = m.WorldEvent(
            "FUTURE", w.run_id, w.epoch, 1, "ARRIVAL", "RAW", "PRODUCT-1", 0, "PASS", "RECEIVE"
        )
        with self.assertRaisesRegex(ContractError, "WORLD_TIME"):
            w.apply_world(future)
        obs = w.observe(0.01)
        self.assertEqual(w.deliver(), ())
        w.advance(0.01)
        self.assertEqual(w.deliver(), (obs,))
        self.audit(w)

    def test_early_completion_and_unread_departure_rejected_atomically(self):
        w = world()
        arrival(w)
        c = fixture.command(w, "TAKE-IN")
        w.dispatch(c)
        state = w.s
        with self.assertRaisesRegex(ContractError, "EARLY_OR_STALE"):
            w.complete(c.id, w.light_readback(c))
        self.assertEqual(w.s, state)
        w = world("V03")
        finish(w, "SHIP-1")
        event(w, "RECEIVE_PERMIT", entity="PRODUCT-1")
        c = fixture.command(w, "RECEIVE-1")
        w.dispatch(c)
        with self.assertRaisesRegex(ContractError, "NO_EXTERNAL_DEPARTURE"):
            w.complete(c.id, replace(w.light_readback(c), departed_boundary=False))
        self.assertIsNone(w._product("PRODUCT-1").received_h)

    def test_cancelled_finished_product_stays_in_slot(self):
        w = world("V03")
        event(w, "CANCEL", entity="PRODUCT-1")
        self.assertEqual(w._position("PRODUCT-1").location, "FG1")
        self.assertEqual(w.dispatch(fixture.command(w, "SHIP-1")).kind, "REJECTED")
        self.audit(w)

    @patch("adaptive_hrc_scheduling.planning.logistics.time.perf_counter", return_value=0.0)
    def test_future_scenario_is_not_a_policy_argument(self, _clock):
        w = world()
        arrival(w)
        obs = w.observe()
        inp = planning_input(w.config, obs)
        a = choose(w.config, inp, sequence=1)
        b = choose(w.config, inp, sequence=1)
        self.assertEqual(a, b)
        self.assertEqual(a.commands[0].operation_id, "TAKE-IN")
        event(w, "FAILURE", entity="FORK-01")
        changed = choose(w.config, planning_input(w.config, w.observe()), sequence=2)
        self.assertFalse(changed.commands)

    def test_decision_budget_expiry_does_not_dispatch(self):
        w = world()
        arrival(w)
        inp = planning_input(w.config, w.observe(), budget_ms=100)
        state = w.s
        with patch(
            "adaptive_hrc_scheduling.planning.logistics.time.perf_counter", side_effect=(0.0, 1.0)
        ):
            result = choose(w.config, inp)
        self.assertEqual(result.status, "NO_PLAN_FOUND")
        self.assertEqual(result.reason, "DECISION_BUDGET")
        self.assertFalse(result.commands)
        self.assertEqual(w.s, state)

    def test_independent_audit_detects_fake_landing_and_missing_event(self):
        w = world()
        arrival(w)
        finish(w, "TAKE-IN")
        last = w.events[-1]
        bad = replace(last, readback=replace(last.readback, position_m=(99, 99, 99)))
        report = check_run(w.config, replace(w.snapshot(), events=tuple(w.events[:-1]) + (bad,)))
        self.assertTrue(any(f.rule == "R08" for f in report.findings))
        report = check_run(w.config, replace(w.snapshot(), events=tuple(w.events[1:])))
        self.assertNotEqual(report.status, "PASS")

    def test_independent_audit_rejects_quantity_and_role_tampering(self):
        w = world()
        arrival(w)
        finish(w, "TAKE-IN")
        last = w.events[-1]
        state = replace(
            last.state, lots=(replace(last.state.lots[0], available=100), last.state.lots[1])
        )
        report = check_run(
            w.config,
            replace(
                w.snapshot(),
                state=state,
                events=tuple(w.events[:-1]) + (replace(last, state=state),),
            ),
        )
        self.assertTrue(any(f.rule == "R01" for f in report.findings))


if __name__ == "__main__":
    unittest.main()
