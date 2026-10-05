"""S15 recipe boundaries and independent event corruption checks."""

import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_production_contracts import Builder

from adaptive_hrc_scheduling.contracts.codec import ContractError
from adaptive_hrc_scheduling.contracts.production import validate
from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.planning.production import choose, planning_input
from adaptive_hrc_scheduling.production_backend import ProductionBackend
from adaptive_hrc_scheduling.production_checker import check_run


class ProductionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builder = Builder()
        cls.config = cls.builder.configuration()

    def test_wv01_window_requires_exact_approved_case(self):
        from adaptive_hrc_scheduling.control.production_loop import Scenario, validate_scenario

        config = Builder(products=3, rework=True).configuration()
        scenario = Scenario(id="B2_SUPPLEMENTAL_960", until_h=960, receive_after_h=840)
        validate_scenario(config, scenario)
        for change in (
            {"id": "NORMAL"},
            {"until_h": 961},
            {"until_h": 720},
            {"receive_after_h": 700},
            {"quality_fail": "Q-POND"},
            {"rework_fail": True},
            {"actual_device_failure": True},
            {"actual_path_obstruction": True},
            {"loaded_failure": True},
            {"cancel_product": "PRODUCT-1"},
            {"cancel_stage": "READY"},
            {"delayed_lot": "PRODUCT-1.ST-B.01"},
            {"arrival_after_h": 24},
        ):
            with self.subTest(change=change), self.assertRaisesRegex(ContractError, "WV01"):
                validate_scenario(config, replace(scenario, **change))
        for changed in (
            replace(config, rework_enabled=False),
            replace(config, products=config.products[:2]),
            replace(config, products=tuple(replace(p, release_h=1) for p in config.products)),
            replace(config, products=tuple(replace(p, variant="SR-W2") for p in config.products)),
        ):
            with self.assertRaisesRegex(ContractError, "WV01"):
                validate_scenario(changed, scenario)
        validate_scenario(self.config, Scenario(until_h=240))
        validate_scenario(self.config, Scenario())
        with self.assertRaises(ContractError):
            validate_scenario(config, Scenario(until_h=800))

    def test_backpressure_requires_positive_interval_and_capacity_decision(self):
        from types import SimpleNamespace

        from adaptive_hrc_scheduling.production_witness import buffer_backpressure

        config = Builder(products=3, rework=True).configuration()
        backend = ProductionBackend(config)
        places = {"PRODUCT-1": "FG1", "PRODUCT-2": "FG2", "PRODUCT-3": "OUT1"}
        state = replace(
            backend.s,
            time_h=800,
            positions=tuple(
                replace(p, location=places[p.id], support=places[p.id]) if p.id in places else p
                for p in backend.s.positions
            ),
            products=tuple(replace(p, released=True, ready_h=799) for p in backend.s.products),
        )

        def event(t, state=state):
            return SimpleNamespace(occurred_sim_h=t, state=state, sequence=1)

        reason = "PRODUCT-3.BUFFER:CAPACITY:FG1"
        decisions = [(800, False, reason)]
        self.assertEqual(
            buffer_backpressure(config, [event(800), event(840)], decisions)["blocked_product"],
            "PRODUCT-3",
        )
        for events, altered_decisions in (
            ([event(800), event(800)], decisions),
            ([event(800), event(840)], [(800, True, reason)]),
            ([event(800), event(840)], [(800, False, "PRODUCT-3.BUFFER:CALENDAR")]),
            ([event(800), event(840)], [(799, False, reason)]),
            (
                [
                    event(
                        800,
                        replace(
                            state, products=tuple(replace(p, ready_h=None) for p in state.products)
                        ),
                    ),
                    event(840),
                ],
                decisions,
            ),
            (
                [
                    event(
                        800,
                        replace(
                            state,
                            positions=tuple(
                                replace(p, location="EXTERNAL") if p.id == "PRODUCT-1" else p
                                for p in state.positions
                            ),
                        ),
                    ),
                    event(840),
                ],
                decisions,
            ),
        ):
            self.assertIsNone(buffer_backpressure(config, events, altered_decisions))

    def test_idle_wait_exposure_requires_explicit_rest_before_cap(self):
        backend = ProductionBackend(self.config)
        backend.s = replace(
            backend.s,
            time_h=7.9,
            humans=tuple(
                replace(h, fatigue=0.799, peak=0.799) if h.person_id == "W1" else h
                for h in backend.s.humans
            ),
        )
        person = backend.people["W1"]
        self.assertGreater(0.799 + person.wait_rate * 0.6, self.config.cap)
        plan = choose(self.config, planning_input(self.config, backend.observe()))
        self.assertEqual(plan.reason, "IDLE_CAP_REST")
        command = plan.commands[0]
        self.assertEqual(command.service.operation.action, "REST")
        self.assertEqual(command.service.operation.entity_id, "W1")
        self.assertEqual(command.service.operation.base_h, self.config.min_rest_h)
        self.assertEqual(backend.dispatch(command).kind, "STARTED")
        backend.advance(8.5)
        human = next(h for h in backend.s.humans if h.person_id == "W1")
        self.assertLessEqual(human.fatigue, self.config.cap)
        intervals = [i for i in backend.s.intervals if i.person_id == "W1"]
        self.assertAlmostEqual(
            sum(i.end_h - i.start_h for i in intervals if i.phase == "REST"),
            self.config.min_rest_h,
        )
        self.assertTrue(any(i.phase == "WAIT" and i.rate == person.wait_rate for i in intervals))

    def test_idle_rest_between_orders_does_not_prepare_unreleased_order(self):
        config = Builder(products=2).configuration()
        config = replace(
            config,
            products=tuple(
                replace(p, release_h=24) if p.id == "PRODUCT-2" else p for p in config.products
            ),
        )
        backend = ProductionBackend(config)
        backend.s = replace(
            backend.s,
            time_h=7.9,
            completed=tuple(o.id for o in config.operations if o.product_id == "PRODUCT-1"),
            humans=tuple(
                replace(h, fatigue=0.799, peak=0.799) if h.person_id == "W1" else h
                for h in backend.s.humans
            ),
        )
        plan = choose(config, planning_input(config, backend.observe()))
        self.assertEqual(plan.reason, "IDLE_CAP_REST")
        self.assertEqual(plan.commands[0].product_id, "PRODUCT-1")
        self.assertEqual(plan.commands[0].service.operation.action, "REST")
        self.assertFalse(backend._product("PRODUCT-2").released)

    def test_preout_new_frame_waits_for_existing_frame_to_leave(self):
        from adaptive_hrc_scheduling.production_navigation import output_blocker

        config = self.config
        backend = ProductionBackend(config)
        bottom = next(o for o in config.operations if o.id.endswith(".FORM-BOTTOM"))
        top = next(o for o in config.operations if o.id.endswith(".FORM-TOP"))
        ident = bottom.component_outputs[0]
        self.assertIsNone(output_blocker(config, backend.s, top))
        occupied = replace(
            backend.s,
            positions=tuple(
                replace(p, location=bottom.location, support=bottom.location)
                if p.id == ident
                else p
                for p in backend.s.positions
            ),
        )
        self.assertEqual(output_blocker(config, occupied, top), ident)
        cleared = replace(
            occupied,
            positions=tuple(
                replace(p, location="J2", support="J2") if p.id == ident else p
                for p in occupied.positions
            ),
        )
        self.assertIsNone(output_blocker(config, cleared, top))

    def test_cancelled_unused_stock_is_returned_only_after_reverse_transport(self):
        from adaptive_hrc_scheduling.control.production_loop import Scenario, run
        from adaptive_hrc_scheduling.production_cancel import service
        from adaptive_hrc_scheduling.production_geometry import validate_service

        backend = ProductionBackend(self.config)
        result = run(
            backend, Scenario(id="CANCEL-STOCK", cancel_product="PRODUCT-1", cancel_stage="STOCK")
        )
        self.assertEqual(result.audit.status, "PASS")
        events = result.snapshot.events
        cancelled = next(e for e in events if e.world and e.world.kind == "CANCEL")
        stock = [lot for lot in cancelled.state.lots if lot.arrived and lot.available > 0]
        self.assertTrue(stock)
        self.assertTrue(all(lot.returned == 0 for lot in stock))
        moves = [
            e
            for e in events
            if e.kind == "COMPLETED"
            and e.command.service
            and e.command.service.operation.action == "TRANSFER"
        ]
        returns = [
            e
            for e in events
            if e.kind == "COMPLETED"
            and e.command.service
            and e.command.service.operation.action == "RETURN"
        ]
        self.assertTrue(moves)
        self.assertTrue(returns)
        self.assertTrue(all(e.state.time_h > cancelled.state.time_h for e in returns))
        self.assertTrue(all(lot.available == 0 for lot in result.snapshot.state.lots))
        self.assertIsNone(result.snapshot.state.products[0].received_h)
        item = service(self.config, stock[0].id, stock[0].location, stock[0].available)
        validate_service(self.config, item)
        with self.assertRaises(ContractError):
            validate_service(
                self.config, replace(item, operation=replace(item.operation, target="FG1"))
            )

    def test_loaded_failure_preserves_sample_and_requires_repair_before_resume(self):
        from adaptive_hrc_scheduling.control.production_loop import Scenario, run

        backend = ProductionBackend(self.config)
        result = run(backend, Scenario(id="LOADED-FAILURE", until_h=1, loaded_failure=True))
        self.assertEqual(result.audit.status, "PASS", result.audit.findings[:5])
        self.assertTrue(result.manifest["loaded_failure_injected"])
        failure = next(e for e in result.snapshot.events if e.world and e.world.kind == "FAILURE")
        repair = next(e for e in result.snapshot.events if e.world and e.world.kind == "REPAIR")
        sample = failure.state.motions[0]
        self.assertGreater(sample.progress, 0)
        self.assertLess(sample.progress, 1)
        self.assertEqual(failure.state.motions, repair.state.motions)
        resumed = [e for e in result.snapshot.events if e.kind == "STARTED" and e.command.resume_of]
        self.assertTrue(resumed)
        self.assertGreaterEqual(resumed[0].state.time_h, repair.state.time_h)

    def test_unannounced_device_failure_reference_reports_exception_before_notice(self):
        from adaptive_hrc_scheduling.control.production_loop import Scenario, run

        result = run(
            ProductionBackend(self.config),
            Scenario(id="OBSERVED-FAILURE", until_h=1, actual_device_failure=True),
        )
        self.assertEqual(result.audit.status, "PASS", result.audit.findings[:5])
        events = result.snapshot.events
        failure_index = next(
            i for i, e in enumerate(events) if e.world and e.world.kind == "FAILURE"
        )
        self.assertEqual(events[failure_index - 1].kind, "EXCEPTION")
        self.assertEqual(
            events[failure_index - 1].reason, "ACTUAL_EXECUTION:ACTUAL_DEVICE_FAILED:FORK-01"
        )
        self.assertFalse(events[failure_index - 1].state.failed_resources)
        self.assertIn("FORK-01", events[failure_index].state.failed_resources)
        self.assertTrue(any(e.kind == "STARTED" and e.command.resume_of for e in events))
        self.assertFalse(any(r.status == "EXCEPTION" for r in result.snapshot.state.running))

    def test_path_obstruction_reference_blocks_route_then_resumes_verified_sample(self):
        from adaptive_hrc_scheduling.control.production_loop import Scenario, run, validate_scenario

        scenario = Scenario(id="PATH-OBSTRUCTION", until_h=1, actual_path_obstruction=True)
        result = run(ProductionBackend(self.config), scenario)
        self.assertEqual(result.audit.status, "PASS", result.audit.findings[:5])
        self.assertTrue(result.manifest["actual_path_obstruction_injected"])
        self.assertFalse(result.manifest["loaded_failure_injected"])
        events = result.snapshot.events
        index = next(i for i, e in enumerate(events) if e.world and e.world.kind == "FAILURE")
        exception, notice = events[index - 1 : index + 1]
        self.assertEqual(exception.kind, "EXCEPTION")
        self.assertEqual(
            exception.reason, "ACTUAL_EXECUTION:COLLISION:/World/Static/S15_TEST_PATH_OBSTRUCTION"
        )
        self.assertFalse(exception.state.failed_resources)
        self.assertNotIn("FORK-01", notice.state.failed_resources)
        repair = next(e for e in events if e.world and e.world.kind == "REPAIR")
        self.assertEqual(notice.state.motions, repair.state.motions)
        resumed = next(e for e in events if e.kind == "STARTED" and e.command.resume_of)
        self.assertGreaterEqual(resumed.state.time_h, repair.state.time_h)
        self.assertFalse(result.snapshot.state.failed_resources)
        with self.assertRaises(ContractError):
            validate_scenario(self.config, replace(scenario, actual_device_failure=True))

    def test_isaac_event_clock_keeps_exact_calendar_boundaries(self):
        from adaptive_hrc_scheduling.backends.production_isaac_adapter import IsaacAdapter

        class IdlePort:
            def reset(self, *_args):
                pass

        light = ProductionBackend(self.config)
        adapter = IsaacAdapter(self.config, IdlePort())
        for clock in (127.8687198861111, 128.4161229965833, 128.5, 144.0):
            light.advance(clock)
            adapter.advance_to(clock)
            self.assertEqual(adapter.world.s.time_h, clock)
            self.assertEqual(adapter.world.s.intervals, light.s.intervals)
            self.assertEqual(adapter.world.s.humans, light.s.humans)
        self.assertEqual([e.kind for e in adapter.world.events], [e.kind for e in light.events])

    def test_reserved_material_keeps_ingress_group_until_consumed(self):
        from adaptive_hrc_scheduling.production_navigation import ingress_groups

        backend = ProductionBackend(self.config)
        lot = next(x for x in self.config.lots if ".ME-E.01" in x.id)
        state = replace(
            backend.s,
            lots=tuple(
                replace(x, arrived=True, available=0, location="F1." + lot.id)
                if x.id == lot.id
                else x
                for x in backend.s.lots
            ),
            reservations=(
                m.Reservation(lot.id, lot.product_id, "PRODUCT-1.MEP-E", 0, lot.quantity),
            ),
        )
        self.assertEqual(ingress_groups(self.config, state)[False], {lot.group_id})
        self.assertFalse(ingress_groups(self.config, replace(state, reservations=()))[False])

    def floor_access_fixture(self, group="FLOOR"):
        from adaptive_hrc_scheduling import production_supports as support
        from adaptive_hrc_scheduling.production_navigation import boxes

        config = self.config
        state = ProductionBackend(config).s
        racks = []
        for rack in state.supports:
            layout = next(
                (
                    item
                    for item in config.support_layouts
                    if item.root == rack.root and item.group_id.endswith("GROUP-" + group)
                ),
                None,
            )
            racks.append(
                replace(rack, layout_id=layout.id, beams=support.deployed(config, layout))
                if layout
                else rack
            )
        state = replace(state, supports=tuple(racks))
        obstacles = [
            item
            for item in boxes(config, state)
            if item[0].startswith("SC-") or item[0] in support.ROOTS
        ]
        return config, obstacles

    def test_lining_and_external_cladding_access_sweeps_complete_carrier(self):
        from adaptive_hrc_scheduling.production_geometry import transport_sweeps
        from adaptive_hrc_scheduling.production_navigation import clear_segment

        checked = 0
        for group in ("LINING", "EXT", "FIT"):
            config, obstacles = self.floor_access_fixture(group)
            lots = {lot.id: lot for lot in config.lots}
            routes = {r.id: r for r in config.routes}
            for op in config.operations:
                if (
                    not op.route_id
                    or op.entity_id not in lots
                    or not lots[op.entity_id].group_id.endswith("GROUP-" + group)
                ):
                    continue
                for path, size in transport_sweeps(config, op, routes[op.route_id]):
                    self.assertTrue(
                        all(
                            clear_segment(a, b, obstacles, size, margin=0)
                            for a, b in zip(path, path[1:])
                        ),
                        op.id,
                    )
                checked += 1
        self.assertEqual(checked, 96)

    def test_pack_receiver_uses_process_station_outside_cart_approach(self):
        from adaptive_hrc_scheduling.production_geometry import standing_point, transport_sweeps
        from adaptive_hrc_scheduling.production_navigation import clear_segment

        op = next(o for o in self.config.operations if o.id == "PRODUCT-1.PR-I.01.DELIVER-3")
        rt = next(r for r in self.config.routes if r.id == op.route_id)
        self.assertIn(m.PersonPosition("P1", "F1"), op.role_locations)

        def clear(point):
            obstacle = [
                (
                    "P1",
                    (point[0] - 0.3, point[1] - 0.6, point[2]),
                    (point[0] + 0.3, point[1] + 0.6, point[2] + 1.9),
                )
            ]
            return all(
                clear_segment(a, b, obstacle, size, margin=0)
                for path, size in transport_sweeps(self.config, op, rt)
                for a, b in zip(path, path[1:])
            )

        self.assertFalse(clear((50, 21.75, 0.2)))
        self.assertTrue(clear(standing_point(self.config, "P1", "F1")))

    def test_floor_access_sweeps_all_deployed_bars_and_retained_trestles(self):
        from adaptive_hrc_scheduling.production_navigation import clear_segment

        config, obstacles = self.floor_access_fixture()
        checked = 0
        for operation in config.operations:
            if ".FL." not in operation.id or not operation.route_id:
                continue
            route = next(r for r in config.routes if r.id == operation.route_id)
            points = [(p.x, p.y, p.z) for p in route.points]
            size = next(lot.size_m for lot in config.lots if lot.id == operation.entity_id)
            parts = [
                ((0, 0, 0), size, True),
                ((0, -1.8, 0.05), (1.5, 2.6, 0.18), False),
                ((0, -2.7, 0.2), (1.3, 0.1, 1.6), False),
                ((0, -2.25, 0.2), (0.6, 1.2, 1.9), False),
            ]
            parts += [((dx, -0.75, 0), (0.1, 0.12, 2.5), False) for dx in (-0.65, 0.65)]
            parts += [((dx, -0.25, -0.12), (0.12, 1.3, 0.12), True) for dx in (-0.65, 0.65)]
            for offset, dimensions, lifts in parts:
                path = [
                    (x + offset[0], y + offset[1], (z if lifts else 0) + offset[2])
                    for x, y, z in points
                ]
                self.assertTrue(
                    all(
                        clear_segment(a, b, obstacles, dimensions, margin=0)
                        for a, b in zip(path, path[1:])
                    ),
                    operation.id,
                )
            checked += 1
        self.assertEqual(checked, 24)
        # The former frontal withdrawal crosses another deployed contact bar.
        source = next(p.position for p in config.places if p.id == "MEP-RECEIVE.PRODUCT-1.FL.03")
        self.assertFalse(
            clear_segment(
                source, (source[0], 20.8, source[2]), obstacles, (2.4, 1.25, 0.15), margin=0
            )
        )

    def test_floor_empty_access_retracts_below_front_support_columns(self):
        from adaptive_hrc_scheduling.production_geometry import route
        from adaptive_hrc_scheduling.production_navigation import clear_segment

        config, obstacles = self.floor_access_fixture()
        checked = 0
        for place in config.places:
            if ".FL." not in place.id:
                continue
            for source, target in ((place.id, "FORK-PARK"), ("FORK-PARK", place.id)):
                rt = route(config, "EMPTY-CHECK", source, target, "FORK-01", empty=True)
                points = [(p.x, p.y, p.z) for p in rt.points]
                parts = [
                    ((0, -1.8, 0.05), (1.5, 2.6, 0.18), False),
                    ((0, -2.7, 0.2), (1.3, 0.1, 1.6), False),
                    ((0, -2.25, 0.2), (0.6, 1.2, 1.9), False),
                ]
                parts += [((dx, -0.75, 0), (0.1, 0.12, 2.5), False) for dx in (-0.65, 0.65)]
                parts += [((dx, -1.45, -0.12), (0.12, 1.3, 0.12), True) for dx in (-0.65, 0.65)]
                for offset, dimensions, lifts in parts:
                    path = [
                        (x + offset[0], y + offset[1], (z if lifts else 0) + offset[2])
                        for x, y, z in points
                    ]
                    self.assertTrue(
                        all(
                            clear_segment(a, b, obstacles, dimensions, margin=0)
                            for a, b in zip(path, path[1:])
                        ),
                        (source, target),
                    )
                checked += 1
        self.assertEqual(checked, 60)

    def test_exact_approved_variants(self):
        for variant, count, mass in [("SR-W1", 88, 8), ("SR-W2", 91, 8.05)]:
            config = Builder(variant=variant).configuration()
            self.assertEqual(sum(not lot.parent_ids for lot in config.lots), count)
            self.assertEqual(config.products[0].mass_t, mass)
            self.assertEqual(
                len(config.bindings),
                sum(
                    len(next(m for m in a.modes if m.enabled).units) or 1
                    for a in config.core_activities
                ),
            )

    def test_changed_primary_quantity_rejected(self):
        first = self.config.lots[0]
        bad = replace(
            self.config, lots=(replace(first, quantity=first.quantity * 2), *self.config.lots[1:])
        )
        with self.assertRaisesRegex(ContractError, "APPROVED_PACKAGE_DRIFT"):
            validate(bad)

    def test_missing_core_unit_rejected(self):
        with self.assertRaisesRegex(ContractError, "INCOMPLETE_CORE_MAPPING"):
            validate(replace(self.config, bindings=self.config.bindings[:-1]))

    def test_converted_package_envelope_cannot_shrink(self):
        net = next(lot for lot in self.config.lots if lot.id.endswith(".NET"))
        bad = replace(
            self.config,
            lots=tuple(
                replace(lot, size_m=(0.1, 0.1, 0.1)) if lot == net else lot
                for lot in self.config.lots
            ),
        )
        with self.assertRaisesRegex(ContractError, "STEEL_CONVERSION_DRIFT"):
            validate(bad)

    def test_unapproved_component_mass_cannot_enter_production(self):
        component = next(e for e in self.config.entities if e.id.endswith(".COLUMNS"))
        bad = replace(
            self.config,
            entities=tuple(
                replace(e, mass_t=0.8) if e == component else e for e in self.config.entities
            ),
        )
        with self.assertRaisesRegex(ContractError, "APPROVED_COMPONENT_DRIFT"):
            validate(bad)

    def test_assembly_requires_each_component_port(self):
        assembly = next(o for o in self.config.operations if o.component_inputs)
        bad = replace(
            self.config,
            operations=tuple(
                replace(o, component_input_places=o.component_input_places[:-1])
                if o == assembly
                else o
                for o in self.config.operations
            ),
        )
        with self.assertRaisesRegex(ContractError, "COMPONENT_INPUT_PORTS"):
            validate(bad)

    def test_material_batch_does_not_bypass_a_transport_leg(self):
        selected = next(o for o in self.config.operations if o.id == "PRODUCT-1.ST-B.01.DELIVER-0")
        bad = replace(
            self.config, operations=tuple(o for o in self.config.operations if o != selected)
        )
        with self.assertRaises(ContractError):
            validate(bad)

    def test_kit_cannot_release_before_identified_raw_stock(self):
        from adaptive_hrc_scheduling.contracts.production import mode_for

        w = ProductionBackend(self.config)
        op = next(o for o in self.config.operations if o.id == "PRODUCT-1.KIT.U1")
        command = m.DispatchCommand(
            "S15-PROD-1.0",
            self.config.id,
            w.config_hash,
            w.run_id,
            0,
            "EARLY-KIT",
            op.product_id,
            op.activity_id,
            op.id,
            0,
            0,
            mode_for(op),
            0,
            0,
            tuple(m.RoleBinding(r.id, r.id) for r in op.roles),
        )
        receipt = w.dispatch(command)
        self.assertEqual(receipt.kind, "REJECTED")
        self.assertIn("KIT_INPUT_NOT_RELEASED", receipt.reason)
        self.assertEqual(check_run(self.config, w.snapshot()).status, "PASS")

    def test_changed_core_duration_rejected(self):
        selected = next(o for o in self.config.operations if o.id == "PRODUCT-1.CUT.U1")
        bad = replace(
            self.config,
            operations=tuple(
                replace(o, base_h=o.base_h + 0.5) if o == selected else o
                for o in self.config.operations
            ),
        )
        with self.assertRaisesRegex(ContractError, "CORE_PROCESS_TIME_MAPPING"):
            validate(bad)

    def test_premature_quality_is_rejected(self):
        w = ProductionBackend(self.config)
        a = next(a for a in self.config.core_activities if a.quality_evidence)
        e = m.WorldEvent(
            "EARLY",
            w.run_id,
            0,
            0,
            "QUALITY",
            a.quality_evidence,
            a.product_id,
            0,
            "PASS",
            a.quality_evidence,
        )
        with self.assertRaisesRegex(ContractError, "GATE_BEFORE_INSPECTION"):
            w.apply_world(e)
        self.assertFalse(w.events)

    def test_sh01_only_relaxes_lining_height_and_covers_removal(self):
        from adaptive_hrc_scheduling import production_supports as support

        config = self.config
        lining = next(
            x
            for x in config.support_layouts
            if x.root == "MEP-RECEIVE" and x.group_id.endswith("GROUP-LINING")
        )
        floor = next(
            x
            for x in config.support_layouts
            if x.root == lining.root and x.group_id.endswith("GROUP-FLOOR")
        )
        self.assertAlmostEqual(max(c.position[2] for c in lining.contacts), 2.444)
        self.assertTrue(support.movements(config, None, lining))
        self.assertTrue(support.movements(config, lining, floor))
        with self.assertRaisesRegex(ContractError, "SUPPORT_MOTION_BOUND"):
            support.movements(replace(config, support_height_approval_id=None), None, lining)
        high = replace(
            floor,
            contacts=tuple(replace(c, position=(*c.position[:2], 2.444)) for c in floor.contacts),
        )
        with self.assertRaisesRegex(ContractError, "SUPPORT_MOTION_BOUND"):
            support.movements(config, None, high)

    def test_front_wet_packages_cannot_arrive_before_rear_floor_delivery(self):
        for variant in ("SR-W1", "SR-W2"):
            builder = Builder(variant=variant)
            config = builder.configuration()
            rear = {
                o.id for o in config.operations if ".FL." in o.id and o.id.endswith(".DELIVER-3")
            }
            self.assertEqual(len(rear), 6)
            front = [
                o for o in config.operations if ".WT-F." in o.id and o.id.endswith(".DELIVER-0")
            ]
            self.assertTrue(front)
            for op in front:
                self.assertTrue(rear <= set(op.prerequisites))
                world = ProductionBackend(config)
                event = m.WorldEvent(
                    "EARLY-WET",
                    world.run_id,
                    0,
                    0,
                    "ARRIVAL",
                    op.entity_id,
                    op.product_id,
                    0,
                    "PASS",
                    op.location,
                )
                with self.assertRaisesRegex(ContractError, "ARRIVAL_DELIVERY_PREDECESSORS"):
                    world.apply_world(event)
                self.assertFalse(world.events)

    def test_repair_branch_requires_actual_first_failure_and_exact_recipe(self):
        from adaptive_hrc_scheduling.contracts.production import mode_for

        config = Builder(rework=True).configuration()
        world = ProductionBackend(config)
        op = next(o for o in config.operations if o.id == "PRODUCT-1.REPAIR.DIAGNOSE")
        cmd = m.DispatchCommand(
            "S15-PROD-1.0",
            config.id,
            world.config_hash,
            world.run_id,
            0,
            "EARLY-REPAIR",
            op.product_id,
            op.activity_id,
            op.id,
            1,
            0,
            mode_for(op),
            0,
            0,
            (m.RoleBinding("T1", "T1"),),
        )
        self.assertEqual(world.dispatch(cmd).reason, "REPAIR_NOT_ACTIVATED")
        arrival = m.WorldEvent(
            "EARLY-PATCH",
            world.run_id,
            0,
            0,
            "ARRIVAL",
            "PRODUCT-1.REPAIR.PATCH",
            "PRODUCT-1",
            0,
            "PASS",
            "MEP-RECEIVE.PRODUCT-1.REPAIR.PATCH",
        )
        with self.assertRaisesRegex(ContractError, "REPAIR_NOT_ACTIVATED"):
            world.apply_world(arrival)
        with self.assertRaisesRegex(ContractError, "UNAPPROVED_REPAIR_BRANCH"):
            validate(
                replace(
                    config,
                    operations=tuple(
                        replace(o, attempt_index=2) if o.id == op.id else o
                        for o in config.operations
                    ),
                )
            )
        altered = replace(
            config,
            lots=tuple(
                replace(lot, quantity=0.03, mass_t=0.03)
                if lot.id == "PRODUCT-1.REPAIR.PATCH"
                else lot
                for lot in config.lots
            ),
        )
        with self.assertRaisesRegex(ContractError, "REPAIR_PACKAGE_DRIFT"):
            validate(altered)

    def test_empty_history_mass_corruption_is_detected(self):
        w = ProductionBackend(self.config)
        self.assertEqual(check_run(self.config, w.snapshot()).status, "PASS")
        bad = replace(
            w.snapshot(),
            state=replace(w.s, masses=tuple(replace(x, installed_t=1) for x in w.s.masses)),
        )
        self.assertNotEqual(check_run(self.config, bad).status, "PASS")

    def test_tile_front_ingress_waits_for_all_six_rear_packages(self):
        config = self.config
        rear = {f"PRODUCT-1.WT-T.{n:02}.DELIVER-3" for n in range(1, 7)}
        for n in range(7, 11):
            op = next(o for o in config.operations if o.id == f"PRODUCT-1.WT-T.{n:02}.DELIVER-0")
            self.assertTrue(rear <= set(op.prerequisites))
            world = ProductionBackend(config)
            event = m.WorldEvent(
                "EARLY-TILE",
                world.run_id,
                0,
                0,
                "ARRIVAL",
                op.entity_id,
                op.product_id,
                0,
                "PASS",
                op.location,
            )
            with self.assertRaisesRegex(ContractError, "ARRIVAL_DELIVERY_PREDECESSORS"):
                world.apply_world(event)
            self.assertFalse(world.events)

    def test_two_product_receive_group_cannot_overlap(self):
        b = Builder(products=2)
        w = ProductionBackend(b.configuration())
        for index in (1, 2):
            lot = f"PRODUCT-{index}.ST-B.01"
            e = m.WorldEvent(
                f"A-{index}",
                w.run_id,
                0,
                0,
                "ARRIVAL",
                lot,
                f"PRODUCT-{index}",
                0,
                "PASS",
                b.ports[lot]["RECEIVE"],
            )
            if index == 1:
                w.apply_world(e)
            else:
                with self.assertRaisesRegex(ContractError, "GROUP_CAPACITY"):
                    w.apply_world(e)
        self.assertEqual(check_run(w.config, w.snapshot()).status, "PASS")

    def test_unreleased_packages_do_not_trigger_speculative_walks(self):
        w = ProductionBackend(self.config)
        plan = choose(self.config, planning_input(self.config, w.observe(), 10000))
        if plan.commands:
            self.assertNotIn(plan.commands[0].operation_id, ("PRODUCT-1.ST-B.01.DELIVER-0",))
            self.assertEqual(plan.commands[0].product_id, "PRODUCT-1")

    def test_shift_boundary_does_not_prepare_unavailable_material(self):
        w = ProductionBackend(self.config)
        op = next(o for o in self.config.operations if o.id == "PRODUCT-1.ST-B.01.DELIVER-0")
        # A released order with predecessors complete, but its raw package has
        # not arrived. Calendar closure must not turn this into useful travel.
        w.s = replace(
            w.s,
            time_h=3.999,
            products=tuple(replace(p, released=True) for p in w.s.products),
            completed=op.prerequisites,
        )
        value = replace(planning_input(self.config, w.observe(), 10000), operations=(op,))
        plan = choose(self.config, value)
        self.assertFalse(plan.commands)
        self.assertIn("ENTITY_NOT_AT_SOURCE", plan.reason)

    def support_fixture(self):
        from adaptive_hrc_scheduling import production_supports as support
        from adaptive_hrc_scheduling.contracts.production import mode_for

        layout = next(
            item
            for item in self.config.support_layouts
            if item.root == "MEP-RECEIVE" and item.group_id.endswith("GROUP-COAT")
        )
        c = replace(
            self.config,
            devices=tuple(
                replace(d, initial_location="CART-PARK") if d.id == "CART-01" else d
                for d in self.config.devices
            ),
            person_positions=tuple(
                m.PersonPosition(p.person_id, f"CONTROL-SUPPORT-{layout.root}-{p.person_id}")
                if p.person_id in ("P1", "E1")
                else p
                for p in self.config.person_positions
            ),
        )
        w = ProductionBackend(c)

        def command(target, ident):
            op = support.change_operation(c, target, "PRODUCT-1", ident)
            return m.DispatchCommand(
                "S15-PROD-1.0",
                c.id,
                w.config_hash,
                w.run_id,
                0,
                ident,
                op.product_id,
                op.activity_id,
                op.id,
                0,
                0,
                mode_for(op),
                w.s.time_h,
                w.s.revision,
                tuple(m.RoleBinding(r.id, r.id) for r in op.roles),
                service=m.Service(op, None),
            )

        return w, layout, command

    def test_support_change_is_timed_and_requires_all_visible_bars(self):
        w, layout, command = self.support_fixture()
        cmd = command(layout, "SUPPORT-TEST")
        self.assertEqual(w.dispatch(cmd).kind, "STARTED")
        self.assertAlmostEqual(w.s.running[0].earliest_end_h, 0.06)
        w.advance(0.03)
        self.assertTrue(w.s.motions)
        self.assertIsNone(w._support_state(layout.root).layout_id)
        self.assertTrue(
            any(
                a.position != b.position
                for a, b in zip(
                    w.s.supports[0].beams, ProductionBackend(w.config).s.supports[0].beams
                )
            )
        )
        w.advance(0.06, auto_complete=False)
        proof = w.light_readback(cmd)
        self.assertEqual(proof.progress, 1)
        prior = w.s
        with self.assertRaisesRegex(ContractError, "INCOMPLETE_FINISH_READBACK"):
            w.complete(cmd.id, replace(proof, progress=0))
        self.assertEqual(w.s, prior)
        with self.assertRaisesRegex(ContractError, "SUPPORT_READBACK_COVERAGE"):
            w.complete(cmd.id, replace(proof, beams=proof.beams[:-1]))
        self.assertEqual(w.s, prior)
        hidden = replace(proof.beams[0], visible=False)
        with self.assertRaisesRegex(ContractError, "SUPPORT_READBACK_INVALID"):
            w.complete(cmd.id, replace(proof, beams=(hidden, *proof.beams[1:])))
        w.complete(cmd.id, proof)
        self.assertEqual(w._support_state(layout.root).layout_id, layout.id)
        report = check_run(w.config, w.snapshot())
        self.assertEqual(report.status, "PASS", report.findings[:5])

    def test_arrival_waits_for_support_and_occupied_rack_cannot_change(self):
        w, layout, command = self.support_fixture()
        lot = "PRODUCT-1.ST-COAT.01"
        arrival = m.WorldEvent(
            "ARRIVE-COAT",
            w.run_id,
            0,
            0,
            "ARRIVAL",
            lot,
            "PRODUCT-1",
            0,
            "PASS",
            self.builder.ports[lot]["MEP-RECEIVE"],
        )
        with self.assertRaisesRegex(ContractError, "SUPPORT_NOT_READY"):
            w.apply_world(arrival)
        self.assertFalse(w._lot(lot).arrived)
        cmd = command(layout, "SUPPORT-TEST")
        w.dispatch(cmd)
        w.advance(0.06)
        with self.assertRaisesRegex(ContractError, "SUPPORT_PERSON_NOT_CLEAR"):
            w.apply_world(replace(arrival, occurred_sim_h=w.s.time_h))
        for _ in range(2):
            plan = choose(w.config, planning_input(w.config, w.observe(), 10000))
            self.assertTrue(plan.commands)
            self.assertEqual(plan.commands[0].service.operation.action, "WALK")
            self.assertEqual(w.dispatch(plan.commands[0]).kind, "STARTED")
            w.advance(w.s.running[0].earliest_end_h)
        w.apply_world(replace(arrival, occurred_sim_h=w.s.time_h))
        other = next(
            item
            for item in w.config.support_layouts
            if item.root == layout.root and item.group_id.endswith("GROUP-FLOOR")
        )
        receipt = w.dispatch(command(other, "ILLEGAL-CHANGE"))
        self.assertEqual(receipt.kind, "REJECTED")
        self.assertIn("SUPPORT_CHANGE_OCCUPIED", receipt.reason)
        self.assertEqual(check_run(w.config, w.snapshot()).status, "PASS")

    def test_adjacent_float_calendar_boundary_advances_exactly(self):
        import math

        w = ProductionBackend(self.config)
        w.advance(math.nextafter(8.5, 0))
        w.advance(8.5)
        self.assertEqual(w.s.time_h, 8.5)
        self.assertEqual(check_run(w.config, w.snapshot()).status, "PASS")

    def test_independent_audit_rejects_forged_support_pose_and_state(self):
        w, layout, command = self.support_fixture()
        cmd = command(layout, "SUPPORT-FORGERY")
        w.dispatch(cmd)
        w.advance(0.06)
        snapshot = w.snapshot()
        event = snapshot.events[-1]
        sample = event.readback.beams[0]
        altered = (sample.position[0] + 0.05, *sample.position[1:])
        proof = replace(
            event.readback, beams=(replace(sample, position=altered), *event.readback.beams[1:])
        )

        def corrupt(state):
            return replace(
                state,
                supports=tuple(
                    replace(rack, beams=(replace(rack.beams[0], position=altered), *rack.beams[1:]))
                    if rack.root == layout.root
                    else rack
                    for rack in state.supports
                ),
            )

        forged = replace(
            snapshot,
            state=corrupt(snapshot.state),
            events=(
                *snapshot.events[:-1],
                replace(event, readback=proof, state=corrupt(event.state)),
            ),
        )
        report = check_run(w.config, forged)
        self.assertEqual(report.status, "INVALID")
        self.assertTrue(any(f.reason == "SUPPORT_READBACK_INVALID" for f in report.findings))

    def test_support_layout_cannot_expand_approved_motion_area(self):
        from adaptive_hrc_scheduling import production_supports as support

        place_id = self.builder.ports["PRODUCT-1.ST-COAT.01"]["MEP-RECEIVE"]
        c = replace(
            self.config,
            places=tuple(
                replace(p, position=(p.position[0] + 3, *p.position[1:])) if p.id == place_id else p
                for p in self.config.places
            ),
        )
        c = replace(c, support_layouts=support.layouts(c))
        with self.assertRaisesRegex(ContractError, "SUPPORT_MOTION_BOUND|MATERIAL_GROUP_ENVELOPE"):
            validate(c)

    def test_support_attachment_space_cannot_be_used_for_material_storage(self):
        from adaptive_hrc_scheduling import production_supports as support

        port = self.builder.ports["PRODUCT-1.FL.01"]["MEP-RECEIVE"]
        config = replace(
            self.config,
            places=tuple(
                replace(p, position=(p.position[0] + 0.05, *p.position[1:])) if p.id == port else p
                for p in self.config.places
            ),
        )
        config = replace(config, support_layouts=support.layouts(config))
        with self.assertRaisesRegex(ContractError, "MATERIAL_GROUP_ENVELOPE"):
            validate(config)

    def test_cart_operator_egress_accounts_for_wheels_and_retracted_tray(self):
        from adaptive_hrc_scheduling.production_geometry import standing_point
        from adaptive_hrc_scheduling.production_navigation import boxes, clear_segment, walk

        w = ProductionBackend(self.config)
        place = next(d.initial_location for d in self.config.devices if d.id == "CART-01")
        start = standing_point(self.config, "E1", place)
        parts = [b for b in boxes(self.config, w.s) if b[0].startswith("CART-01")]
        self.assertEqual(len(parts), 9)
        obstacles = [b for b in parts if b[0] == "CART-01"]
        self.assertTrue(clear_segment(start, (start[0], start[1] - 0.1, start[2]), obstacles))
        path = walk(self.config, w.s, "E1", place, "CONTROL-E1")
        self.assertTrue(all(clear_segment(a, b, obstacles) for a, b in zip(path, path[1:])))
        # The same legal egress must survive executor admission, not just routing.
        from adaptive_hrc_scheduling.production_geometry import route

        config = replace(
            self.config,
            person_positions=tuple(
                replace(p, location=place) if p.person_id == "E1" else p
                for p in self.config.person_positions
            ),
        )
        w = ProductionBackend(config)
        rt = replace(
            route(config, "EGRESS", place, "CONTROL-E1", None, person="E1"),
            points=tuple(m.Point(*p) for p in path),
        )
        op = m.Operation(
            "EGRESS",
            "PRODUCT-1",
            "EGRESS",
            "WALK",
            "WALK",
            (),
            (m.Role("E1", "CART"),),
            (m.PersonPosition("E1", place),),
            (),
            place,
            "CONTROL-E1",
            rt.id,
            "E1",
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
        command = m.DispatchCommand(
            "S15-PROD-1.0",
            config.id,
            w.config_hash,
            w.run_id,
            0,
            "EGRESS",
            op.product_id,
            op.activity_id,
            op.id,
            0,
            0,
            "MOVE",
            0,
            0,
            (m.RoleBinding("E1", "E1"),),
            service=m.Service(op, rt),
        )
        self.assertEqual(w.dispatch(command).kind, "STARTED")
        w.advance(w.s.running[0].earliest_end_h)
        self.assertEqual(w._position("E1").location, "CONTROL-E1")
        self.assertEqual(check_run(config, w.snapshot()).status, "PASS")

    def test_support_resume_preserves_verified_partial_pose(self):
        w, layout, command = self.support_fixture()
        cmd = command(layout, "SUPPORT-INTERRUPT")
        w.dispatch(cmd)
        w.advance(0.03)
        prior = w._support_state(layout.root).beams
        w.exception(cmd.id, "VERIFIED_SAMPLE_INTERRUPT")
        w.advance(0.04)
        self.assertEqual(w._support_state(layout.root).beams, prior)
        resume = replace(
            cmd,
            id="SUPPORT-RESUME",
            resume_of=cmd.id,
            issued_sim_h=w.s.time_h,
            expected_revision=w.s.revision,
        )
        self.assertEqual(w.dispatch(resume).kind, "STARTED")
        w.advance(0.07)
        self.assertEqual(w._support_state(layout.root).layout_id, layout.id)
        report = check_run(w.config, w.snapshot())
        self.assertEqual(report.status, "PASS", report.findings[:5])

    def test_nominal_support_path_rejects_bystander_without_moving_beams(self):
        w, layout, command = self.support_fixture()
        # A bystander at the permanent side holder obstructs the first lift.
        from adaptive_hrc_scheduling import production_supports as support
        from adaptive_hrc_scheduling.production_geometry import standing_point
        from adaptive_hrc_scheduling.production_navigation import support_paths_clear

        park = support.parking(w.config, layout.root)[0].position
        config = replace(
            w.config,
            places=(
                *w.config.places,
                replace(
                    next(p for p in w.config.places if p.id == "CONTROL-E1"),
                    id="CONTROL-BYSTANDER",
                    position=(*park[:2], 0),
                ),
            ),
            person_positions=tuple(
                replace(p, location="CONTROL-BYSTANDER") if p.person_id == "QA1" else p
                for p in w.config.person_positions
            ),
        )
        blocked = ProductionBackend(config)
        self.assertEqual(standing_point(config, "QA1", "CONTROL-BYSTANDER")[:2], park[:2])
        self.assertFalse(support_paths_clear(config, blocked.s, None, layout))
        cmd = replace(command(layout, "BLOCKED-SUPPORT"), config_sha256=blocked.config_hash)
        before = blocked.s.supports
        receipt = blocked.dispatch(cmd)
        self.assertEqual(receipt.kind, "REJECTED")
        self.assertIn("SUPPORT_PATH_BLOCKED", receipt.reason)
        self.assertEqual(blocked.s.supports, before)

    def test_failed_support_sample_does_not_spend_unobserved_motion(self):
        w, layout, command = self.support_fixture()
        cmd = command(layout, "SUPPORT-MISSING-SAMPLE")
        w.dispatch(cmd)
        w.advance(0.0205)
        poses = w._support_state(layout.root).beams
        w.advance(0.0255, auto_complete=False)
        w.exception(cmd.id, "FAILED_BEFORE_NEW_MOTION_SAMPLE")
        w.advance(0.0355, auto_complete=False)
        resumed = replace(
            cmd,
            id="RECOVER-SUPPORT",
            resume_of=cmd.id,
            issued_sim_h=w.s.time_h,
            expected_revision=w.s.revision,
        )
        self.assertEqual(w.dispatch(resumed).kind, "STARTED")
        self.assertEqual(w._support_state(layout.root).beams, poses)
        self.assertAlmostEqual(w.s.running[0].active_before_h, 0.0205)
        self.assertAlmostEqual(w.s.running[0].earliest_end_h, 0.075)
        w.advance(0.075)
        self.assertEqual(w._support_state(layout.root).layout_id, layout.id)
        report = check_run(w.config, w.snapshot())
        self.assertEqual(report.status, "PASS", report.findings[:5])

    def test_rolling_test_trolley_does_not_use_a_load_lifting_route(self):
        routes = [r for r in self.config.routes if r.device_id == "TEST1"]
        self.assertTrue(routes)
        self.assertTrue(all(p.z == 0 for r in routes for p in r.points))


if __name__ == "__main__":
    unittest.main()
