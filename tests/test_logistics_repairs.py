"""S14 r1 counterexamples: physical ownership, input evidence and recovery."""

import unittest
from dataclasses import replace
from unittest.mock import patch

from test_isaac_adapter import ControlledPort
from test_logistics import arrival, event, finish, fixture

from adaptive_hrc_scheduling.backends.isaac_adapter import IsaacAdapter
from adaptive_hrc_scheduling.contracts.codec import ContractError
from adaptive_hrc_scheduling.contracts.logistics import digest, validate
from adaptive_hrc_scheduling.control.logistics_loop import run_loop
from adaptive_hrc_scheduling.domain import logistics as m
from adaptive_hrc_scheduling.logistics_backend import LogisticsBackend
from adaptive_hrc_scheduling.logistics_checker import check_run
from adaptive_hrc_scheduling.planning.logistics import choose, planning_input


def prepared_world():
    c = fixture.configuration(synthetic=True)
    move = fixture.operation(
        "MOVE-BUSY-RAW",
        "TRANSFER",
        entity="RAW",
        source="PRE-IN",
        target="PRE-OUT",
        route="S03",
        equipment=("FORK-01",),
        roles=(("P1", "FORK", "PRE-IN"), ("W2", "WELD", "PRE-OUT")),
        prior=("RESERVE-CUT",),
        phase="DRIVE",
    )
    c = replace(
        c,
        operations=c.operations + (move,),
        person_positions=tuple(
            replace(p, location="PRE-OUT") if p.person_id == "W2" else p for p in c.person_positions
        ),
    )
    w = LogisticsBackend(c)
    arrival(w)
    for op in ("TAKE-IN", "TO-PRE", "RESERVE-CUT"):
        finish(w, op)
    return w


class RecordingPort(ControlledPort):
    def reset(self, *args):
        super().reset(*args)
        self.world_events = []

    def world_event(self, event):
        self.world_events.append(event)
        if self.fault == "world":
            raise RuntimeError("PARTIAL_PORT_EFFECT")


class LogisticsRepairTests(unittest.TestCase):
    def test_material_processing_and_transport_are_mutually_exclusive(self):
        for first, second in (("CUT", "MOVE-BUSY-RAW"), ("MOVE-BUSY-RAW", "CUT")):
            with self.subTest(first=first):
                w = prepared_world()
                self.assertEqual(w.dispatch(fixture.command(w, first)).kind, "STARTED")
                before = w.s
                receipt = w.dispatch(fixture.command(w, second))
                self.assertEqual(receipt.reason, "RESOURCE_BUSY:ENTITY:RAW")
                self.assertEqual(w.s.owners, before.owners)
                self.assertEqual(w.s.lots, before.lots)
                self.assertEqual(w.s.running, before.running)
                self.assertEqual(check_run(w.config, w.snapshot()).status, "PASS")

    def test_checker_rejects_original_split_lock_counterexample(self):
        w = prepared_world()
        admit = LogisticsBackend._admit

        def broken_admit(world, command):
            result = admit(world, command)
            if command.operation_id == "CUT":
                world._put(
                    owners=tuple(
                        replace(x, resource_id="LOT:RAW") if x.resource_id == "ENTITY:RAW" else x
                        for x in world.s.owners
                    )
                )
            return result

        with patch.object(LogisticsBackend, "_admit", broken_admit):
            self.assertEqual(w.dispatch(fixture.command(w, "CUT")).kind, "STARTED")
            self.assertEqual(w.dispatch(fixture.command(w, "MOVE-BUSY-RAW")).kind, "STARTED")
        report = check_run(w.config, w.snapshot())
        self.assertEqual(report.status, "INVALID")
        self.assertIn("RESOURCE_OVERLAP", [f.reason for f in report.findings])

    def test_completion_requires_all_input_readbacks(self):
        w = prepared_world()
        cmd = fixture.command(w, "CUT")
        w.dispatch(cmd)
        w.advance(w.s.running[0].earliest_end_h, auto_complete=False)
        proof = w.light_readback(cmd)
        before = w.s
        with self.assertRaisesRegex(ContractError, "INPUT_READBACK_COVERAGE"):
            w.complete(cmd.id, replace(proof, inputs=()))
        self.assertEqual(w.s, before)
        sample = proof.inputs[0]
        for bad in (
            replace(sample, position_m=(45, 40, 1)),
            replace(sample, supported=False),
            replace(sample, visible=False),
            replace(sample, quantity=0),
            replace(sample, quantity=7),
        ):
            with self.subTest(sample=bad):
                with self.assertRaisesRegex(ContractError, "INPUT_READBACK"):
                    w.complete(cmd.id, replace(proof, inputs=(bad,)))
                self.assertEqual(w.s, before)
        w.complete(cmd.id, proof)
        self.assertEqual(w._lot("PREPARED").available, 5)

    def test_checker_rejects_missing_and_false_input_evidence(self):
        w = prepared_world()
        finish(w, "CUT")
        snapshot = w.snapshot()
        completion = snapshot.events[-1]
        sample = completion.readback.inputs[0]
        for inputs, expected in (
            ((), "INCOMPLETE"),
            ((replace(sample, supported=False),), "INVALID"),
            ((replace(sample, quantity=0),), "INVALID"),
        ):
            with self.subTest(inputs=inputs):
                forged = replace(completion, readback=replace(completion.readback, inputs=inputs))
                report = check_run(
                    w.config, replace(snapshot, events=snapshot.events[:-1] + (forged,))
                )
                self.assertEqual(report.status, expected)

    def test_world_replays_do_not_repeat_port_effects(self):
        a = IsaacAdapter(fixture.configuration(synthetic=True), RecordingPort())
        w = a.world
        events = [
            m.WorldEvent("ARR", w.run_id, 0, 0, "ARRIVAL", "RAW", "PRODUCT-1", 0, "PASS", "RECEIVE")
        ]
        for ident, kind in (("F", "FAILURE"), ("R", "REPAIR")):
            events.append(replace(events[0], id=ident, kind=kind, entity_id="FORK-01"))
        for e in events:
            a.apply_world(e)
        before = w.s
        for e in events:
            self.assertIsNone(a.apply_world(e))
        self.assertEqual(w.s, before)
        self.assertEqual(a.port.world_events, events)
        with self.assertRaisesRegex(ContractError, "EVENT_PAYLOAD_CONFLICT"):
            a.apply_world(replace(events[0], evidence_id="STEEL"))
        self.assertEqual(a.port.world_events, events)
        a.reset()
        with self.assertRaisesRegex(ContractError, "STALE_EPOCH"):
            a.apply_world(events[0])
        self.assertEqual(a.port.world_events, [])

    def test_world_port_failure_blocks_execution_until_reset(self):
        a = IsaacAdapter(fixture.configuration(synthetic=True), RecordingPort())
        a.port.fault = "world"
        e = m.WorldEvent(
            "ARR", a.world.run_id, 0, 0, "ARRIVAL", "RAW", "PRODUCT-1", 0, "PASS", "RECEIVE"
        )
        for action in (
            lambda: a.apply_world(e),
            lambda: a.apply_world(e),
            lambda: a.dispatch(fixture.command(a.world, "TAKE-IN")),
            lambda: a.advance(1),
        ):
            with self.assertRaisesRegex(ContractError, "WORLD_PORT_FAILURE_RESET_REQUIRED"):
                action()
        self.assertEqual(len(a.port.world_events), 1)
        a.reset()
        self.assertIsNone(a.world_port_error)
        a.apply_world(replace(e, epoch=a.world.epoch))

    def test_production_scope_cannot_promote_reference_metadata(self):
        c = fixture.configuration(synthetic=True, witness="V02")
        core = next(a for a in c.core_activities if a.code == "W-3D")
        altered = tuple(
            replace(
                o,
                activity_id=core.id,
                roles=o.roles[:1],
                role_locations=o.role_locations[:1],
                equipment=(),
                base_h=0,
            )
            if o.id == "W-3D"
            else o
            for o in c.operations
        )
        for ops in (c.operations, altered):
            production = replace(c, scope="PRODUCTION", operations=ops)
            with self.assertRaisesRegex(ContractError, "PRODUCTION_MAPPING_NOT_IMPLEMENTED"):
                validate(production)
            snap = LogisticsBackend(c).snapshot()
            report = check_run(production, replace(snap, config_sha256=digest(production)))
            self.assertEqual(report.status, "INVALID")
            self.assertEqual(report.findings[0].reason, "PRODUCTION_MAPPING_NOT_IMPLEMENTED")
        validate(c)

    def test_repair_replans_held_command_and_completes_without_manual_resume(self):
        for rule in ("EDD", "SPT", "FASTEST_LEGAL"):
            with self.subTest(rule=rule):
                w = LogisticsBackend(fixture.configuration(synthetic=True))
                arrival(w)
                first = fixture.command(w, "TAKE-IN", "FIRST")
                w.dispatch(first)
                w.advance(0.01)
                event(w, "FAILURE", entity="FORK-01")
                plan = choose(w.config, planning_input(w.config, w.observe(), 10000), rule=rule)
                self.assertEqual(plan.commands, ())
                self.assertIn("DEVICE_FAILED", plan.reason)
                repair = m.WorldEvent(
                    "REPAIRED",
                    w.run_id,
                    0,
                    0.02,
                    "REPAIR",
                    "FORK-01",
                    "PRODUCT-1",
                    0,
                    "PASS",
                    "ML-RELEASE",
                )
                turns, audit = run_loop(
                    w,
                    m.HiddenScenario("S14-ML-1.0", w.config.id, (repair,)),
                    rule=rule,
                    budget_ms=10000,
                )
                resumes = [
                    t.plan.commands[0]
                    for t in turns
                    if t.plan.commands and t.plan.commands[0].resume_of
                ]
                self.assertEqual(len(resumes), 1)
                self.assertEqual(resumes[0].resume_of, first.id)
                self.assertEqual(resumes[0].roles, first.roles)
                self.assertIn("OPEN-WORK", w.s.completed)
                self.assertFalse(w.s.running)
                self.assertEqual(audit.status, "PASS", audit.findings)

    def test_cancelled_work_is_not_resumed_by_planner(self):
        w = prepared_world()
        c = fixture.command(w, "CUT")
        w.dispatch(c)
        event(w, "FAILURE", entity="CUT1")
        event(w, "CANCEL", entity="PRODUCT-1")
        event(w, "REPAIR", entity="CUT1")
        before = w.s
        plan = choose(w.config, planning_input(w.config, w.observe(), 10000))
        self.assertEqual(plan.commands, ())
        self.assertIn("CUT:PRODUCT_UNAVAILABLE", plan.reason)
        self.assertEqual(w.s, before)


if __name__ == "__main__":
    unittest.main()
