"""S18 admission and phase boundary tests; synthetic seeds are not full-chain evidence."""

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_production_contracts import Builder
from build_simulation_production import configuration, generated

from adaptive_hrc_scheduling.contracts.codec import ContractError, as_data
from adaptive_hrc_scheduling.contracts.production import (
    digest,
    dumps,
    loads,
    production_schema,
    validate,
)
from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.production_backend import ProductionBackend


class SimulationAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = configuration()

    def reject(self, config, reason):
        with self.assertRaisesRegex(ContractError, reason):
            validate(config)

    def test_round_trip_and_industrial_identity(self):
        c = self.config
        self.assertEqual(as_data(loads(m.Configuration, dumps(c))), as_data(c))
        self.assertEqual(c.research.industrial_g2, "OPEN")
        self.assertEqual(c.research.industrial_qualification, "NOT_ESTABLISHED")

    def test_missing_and_wrong_approval(self):
        c = self.config
        self.reject(replace(c, research=None), "SIM_SCOPE")
        self.reject(replace(c, research=replace(c.research, proposal_sha256="0" * 64)), "SIM_SCOPE")
        self.reject(
            replace(c, research=replace(c.research, assumption_sha256="0" * 64)), "SIM_SCOPE"
        )

    def test_consumer_mixing_and_missing_q_map(self):
        c = self.config
        self.reject(
            replace(c, research=replace(c.research, consumers=c.research.consumers[:-1])),
            "SIM_SCOPE",
        )
        self.reject(
            replace(
                c,
                research=replace(
                    c.research,
                    scope_bindings=tuple(
                        replace(b, assumption_ids=b.assumption_ids[:-1])
                        for b in c.research.scope_bindings
                    ),
                ),
            ),
            "SIM_SCOPE",
        )

    def test_product_component_and_process_version_rejection(self):
        c = self.config
        for field, value in (
            ("product_revision", "v2"),
            ("component_id", "PRODUCT-1.TOP"),
            ("process_revision", "v2"),
            ("fixture_revision", "v2"),
        ):
            with self.subTest(field=field):
                bindings = (
                    replace(c.research.scope_bindings[0], **{field: value}),
                    *c.research.scope_bindings[1:],
                )
                self.reject(
                    replace(c, research=replace(c.research, scope_bindings=bindings)), "SIM_SCOPE"
                )

    def test_no_industrial_or_legacy_inference(self):
        c = self.config
        self.reject(replace(c, purpose="RESEARCH_BLOCKED"), "SIM_VERSION_PURPOSE")
        self.reject(replace(c, schema_version="S15-PROD-1.0"), "SIM_VERSION_PURPOSE")
        self.reject(
            replace(
                c,
                evidence=tuple(
                    replace(e, status="PASS", basis="INDUSTRIAL") if e.id == "G2-WPS" else e
                    for e in c.evidence
                ),
            ),
            "SIM_CANNOT",
        )
        old = Builder().configuration()
        self.reject(replace(old, purpose="SIMULATION_RESEARCH_ONLY"), "SIM_VERSION_PURPOSE")

    def test_old_wire_digest_and_generated_inputs_unchanged(self):
        old = Builder(synthetic=False).configuration()
        path = (
            Path(__file__).resolve().parents[1] / "examples/production_contracts/Configuration.json"
        )
        self.assertEqual(dumps(old), path.read_text(encoding="utf-8"))
        self.assertEqual(
            as_data(loads(m.Configuration, path.read_text(encoding="utf-8"))), as_data(old)
        )
        self.assertEqual(digest(old), digest(loads(m.Configuration, dumps(old))))

    def test_strict_schema_versions_and_generated_files(self):
        old = production_schema(m.Configuration)
        new = production_schema(m.Configuration, simulation=True)
        self.assertEqual(
            old["$defs"]["Configuration"]["properties"]["schema_version"]["enum"], ["S15-PROD-1.0"]
        )
        self.assertEqual(
            new["$defs"]["Configuration"]["properties"]["schema_version"]["enum"], ["S18-PROD-2.0"]
        )
        root = Path(__file__).resolve().parents[1]
        for name, contents in generated().items():
            self.assertEqual((root / name).read_text(encoding="utf-8"), contents)
        self.assertNotIn("research", json.loads(dumps(Builder().configuration())))

    def test_missing_stage_and_duration_drift_rejected(self):
        c = self.config
        op = next(o for o in c.operations if o.branch and o.branch.phase == "ROBOT")
        self.reject(
            replace(c, operations=tuple(o for o in c.operations if o.id != op.id)),
            "CORE_BINDING|PREREQUISITE",
        )
        self.reject(
            replace(
                c,
                operations=tuple(
                    replace(o, base_h=0.25) if o.id == op.id else o for o in c.operations
                ),
            ),
            "CORE_PROCESS_TIME",
        )


class SimulationPhaseTests(unittest.TestCase):
    def setUp(self):
        self.config = configuration()
        self.world = ProductionBackend(self.config)
        self.h = [
            o
            for o in self.config.operations
            if o.activity_id == "PRODUCT-1.W-B" and o.production_mode == "H"
        ]
        self.hr = [
            o
            for o in self.config.operations
            if o.activity_id == "PRODUCT-1.W-B" and o.production_mode == "HR-seq"
        ]
        first = self.hr[0]
        self.world.s = replace(
            self.world.s,
            completed=first.prerequisites,
            positions=tuple(
                replace(p, location="J2", support="J2")
                if p.id in ("OP1", "PRODUCT-1.BOTTOM")
                else p
                for p in self.world.s.positions
            ),
        )

    def command(self, op, person="OP1"):
        w = self.world
        return m.DispatchCommand(
            self.config.schema_version,
            self.config.id,
            digest(self.config),
            w.run_id,
            w.epoch,
            "TEST-" + op.id + str(w.s.revision),
            op.product_id,
            op.activity_id,
            op.id,
            0,
            op.unit_index,
            op.production_mode,
            w.s.time_h,
            w.s.revision,
            tuple(m.RoleBinding(r.id, person) for r in op.roles),
            branch=op.branch,
            research=self.config.research,
        )

    def complete(self, op, person="OP1"):
        c = self.command(op, person)
        receipt = self.world.dispatch(c)
        self.assertEqual(receipt.kind, "STARTED", receipt.reason)
        end = next(r.earliest_end_h for r in self.world.s.running if r.command.id == c.id)
        self.world.advance(end)

    def test_setup_holds_both_resources_and_mode_is_immutable(self):
        self.complete(self.hr[0])
        owners = {o.resource_id: o.command_id for o in self.world.s.owners}
        self.assertEqual(owners["R1"], owners["FIX-J2"])
        self.assertIn("PRODUCT-1.W-B", owners["R1"])
        receipt = self.world.dispatch(self.command(self.h[0], "W1"))
        self.assertEqual(receipt.reason, "SIM_ATTEMPT_IMMUTABLE")

    def test_exit_required_robot_does_not_release_and_late_unload_holds(self):
        self.complete(self.hr[0])
        receipt = self.world.dispatch(self.command(self.hr[1]))
        self.assertEqual(receipt.reason, "SIM_ISOLATION_EXIT_REQUIRED")
        # Boundary seed only. Actual WALK evidence is verified by continuous-chain tests.
        self.world.s = replace(
            self.world.s,
            positions=tuple(
                replace(p, location="CONTROL-OP1", support="CONTROL-OP1") if p.id == "OP1" else p
                for p in self.world.s.positions
            ),
        )
        self.complete(self.hr[1])
        self.assertEqual({o.resource_id for o in self.world.s.owners}, {"R1", "FIX-J2"})
        receipt = self.world.dispatch(self.command(self.hr[2]))
        self.assertEqual(receipt.reason, "PERSON_NOT_PRESENT")
        self.assertEqual({o.resource_id for o in self.world.s.owners}, {"R1", "FIX-J2"})

    def test_actual_unload_releases_and_preserves_no_quality_pass(self):
        self.complete(self.hr[0])
        self.world.s = replace(
            self.world.s,
            positions=tuple(
                replace(p, location="CONTROL-OP1", support="CONTROL-OP1") if p.id == "OP1" else p
                for p in self.world.s.positions
            ),
        )
        self.complete(self.hr[1])
        self.world.s = replace(
            self.world.s,
            positions=tuple(
                replace(p, location="J2", support="J2") if p.id == "OP1" else p
                for p in self.world.s.positions
            ),
        )
        self.complete(self.hr[2])
        self.assertEqual(self.world.s.owners, ())
        self.assertEqual(self.world.s.mode_attempts[0].state, "COMPLETE")
        self.assertEqual(self.world.s.gates, ())

    def test_duplicate_and_wrong_phase_binding(self):
        c = self.command(self.hr[0])
        receipt = self.world.dispatch(c)
        self.assertEqual(self.world.dispatch(c), receipt)
        self.assertEqual(len(self.world.s.mode_attempts), 1)
        with self.assertRaisesRegex(ContractError, "COMMAND_BRANCH_BINDING"):
            validate(replace(c, branch=None), config=self.config)

    def test_interrupted_attempt_cannot_switch_or_resume(self):
        c = self.command(self.hr[0])
        self.world.dispatch(c)
        self.world.exception(c.id, "TEST_FAILURE")
        self.assertEqual(self.world.s.mode_attempts[0].state, "HOLD")
        resume = replace(c, id="RESUME", resume_of=c.id, expected_revision=self.world.s.revision)
        self.assertEqual(self.world.dispatch(resume).reason, "SIM_INTERRUPTED_ATTEMPT_HOLD")

    def test_roles_are_independent_of_people(self):
        self.assertEqual(self.h[0].roles[0].id, "WELDER")
        self.assertEqual(self.hr[0].roles[0].id, "OPERATOR")
        wrong = self.command(self.hr[0], "W1")
        self.assertEqual(self.world.dispatch(wrong).reason, "PERSON_QUALIFICATION")

    def entrance(self):
        from adaptive_hrc_scheduling.production_geometry import route

        rt = route(self.config, "ENTER-ROUTE", "CONTROL-OP1", "J2", None, person="OP1")
        from adaptive_hrc_scheduling.production_navigation import walk

        rt = replace(
            rt,
            points=tuple(
                m.Point(*p) for p in walk(self.config, self.world.s, "OP1", "CONTROL-OP1", "J2")
            ),
        )
        op = replace(
            self.hr[0],
            id="ENTER",
            activity_id="ENTER",
            action="WALK",
            phase="WALK",
            prerequisites=(),
            roles=(m.Role("OP1", "ROBOT"),),
            role_locations=(m.PersonPosition("OP1", "CONTROL-OP1"),),
            equipment=(),
            location="CONTROL-OP1",
            target="J2",
            route_id=rt.id,
            entity_id="OP1",
            base_h=0,
            kappa=0,
            production_mode=None,
            branch=None,
            hold_resources=(),
            release_resources=(),
        )
        c = replace(
            self.command(op),
            mode_id="MOVE",
            roles=(m.RoleBinding("OP1", "OP1"),),
            service=m.Service(op, rt),
        )
        return c

    def exit_seed(self):
        self.world.s = replace(
            self.world.s,
            positions=tuple(
                replace(p, location="CONTROL-OP1", support="CONTROL-OP1") if p.id == "OP1" else p
                for p in self.world.s.positions
            ),
        )

    def test_robot_running_blocks_human_entry(self):
        self.complete(self.hr[0])
        self.exit_seed()
        self.assertEqual(self.world.dispatch(self.command(self.hr[1])).kind, "STARTED")
        self.assertEqual(self.world.dispatch(self.entrance()).reason, "SIM_ENTRY_REQUIRES_STOP")

    def test_incoming_walk_blocks_robot_start(self):
        self.complete(self.hr[0])
        self.exit_seed()
        self.assertEqual(self.world.dispatch(self.entrance()).kind, "STARTED")
        self.assertEqual(
            self.world.dispatch(self.command(self.hr[1])).reason, "SIM_INCOMING_PERSON_DURING_ROBOT"
        )


class SimulationHandoverTests(unittest.TestCase):
    setUp = SimulationPhaseTests.setUp
    command = SimulationPhaseTests.command
    complete = SimulationPhaseTests.complete

    def begin_h(self):
        self.world.s = replace(
            self.world.s,
            positions=tuple(
                replace(p, location="J2", support="J2") if p.id in ("W1", "W2") else p
                for p in self.world.s.positions
            ),
        )
        self.complete(self.h[0], "W1")

    def service(self, change):
        from adaptive_hrc_scheduling.production_handover import operation

        op = operation(self.config, change, "TEST-" + change.phase + str(self.world.s.revision))
        c = replace(
            self.command(op),
            roles=tuple(m.RoleBinding(r.id, r.id) for r in op.roles),
            service=m.Service(op, None),
        )
        return op, c

    def test_charged_handover_then_restore_switches_crew(self):
        self.begin_h()
        start = self.world.s.time_h
        change = m.Handover(
            "PRODUCT-1.W-B", self.h[0].branch.definition_id, "W1", "W2", 0, "HANDOVER"
        )
        op, c = self.service(change)
        receipt = self.world.dispatch(c)
        self.assertEqual(receipt.kind, "STARTED", receipt.reason)
        self.world.advance(start + 0.1)
        self.assertEqual(self.world.s.mode_attempts[0].crew[0].person_id, "W1")
        self.assertEqual(
            self.world.dispatch(self.command(self.h[1], "W1")).reason, "SIM_RESTORE_REQUIRED"
        )
        op, c = self.service(replace(change, phase="RESTORE"))
        self.assertEqual(self.world.dispatch(c).kind, "STARTED")
        self.world.advance(start + 0.2)
        self.assertEqual(self.world.s.mode_attempts[0].crew[0].person_id, "W2")
        self.assertEqual({o.resource_id for o in self.world.s.owners}, {"WELD-J2", "FIX-J2"})
        self.assertEqual(self.world.dispatch(self.command(self.h[1], "W2")).kind, "STARTED")
        charged = [i for i in self.world.s.intervals if i.phase in ("HANDOVER", "RESTORE")]
        self.assertAlmostEqual(
            sum(i.end_h - i.start_h for i in charged if i.person_id == "W1"), 0.1
        )
        self.assertAlmostEqual(
            sum(i.end_h - i.start_h for i in charged if i.person_id == "W2"), 0.2
        )

    def test_zero_cost_or_restore_first_is_rejected(self):
        self.begin_h()
        change = m.Handover(
            "PRODUCT-1.W-B", self.h[0].branch.definition_id, "W1", "W2", 0, "RESTORE"
        )
        op, c = self.service(change)
        self.assertEqual(self.world.dispatch(c).reason, "HANDOVER_RESTORE_ORDER")
        bad = replace(c, service=m.Service(replace(op, base_h=0), None))
        with self.assertRaisesRegex(ContractError, "HANDOVER_SERVICE_FIELDS"):
            validate(bad, config=self.config)

    def test_cancel_does_not_release_prepared_structural_attempt(self):
        self.complete(self.hr[0])
        self.world.apply_world(
            m.WorldEvent(
                "CANCEL",
                self.world.run_id,
                0,
                self.world.s.time_h,
                "CANCEL",
                "PRODUCT-1",
                "PRODUCT-1",
                0,
                "UNKNOWN",
                "ML-METHOD",
            )
        )
        self.assertEqual(self.world.s.mode_attempts[0].state, "HOLD")
        self.assertEqual({o.resource_id for o in self.world.s.owners}, {"R1", "FIX-J2"})
