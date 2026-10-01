"""S09 capacity, cancellation and multi-input integration regressions."""

import json
import unittest
from dataclasses import replace

from test_event_backend import (
    ROOT,
    allocation,
    backend,
    command,
    config,
    finish,
    operation,
    prepared_assembly,
    process,
    start,
    transfer_to,
)

from adaptive_hrc_scheduling.contracts.codec import as_data, decode, loads
from adaptive_hrc_scheduling.contracts.messages import Assignment, WorldEvent
from adaptive_hrc_scheduling.contracts.validation import validate
from adaptive_hrc_scheduling.domain.models import Configuration


def issue(e, op, phase, mode, q, gid=None, action="start", attempt=1, sequence=0):
    a = Assignment(
        op.id,
        mode,
        gid or op.process_group_id,
        phase,
        q.id,
        attempt,
        sequence,
        e.now,
        e.now + 1,
        "MANUAL_BOUNDARY",
    )
    return e.dispatch(command(e, action, a=a))


def two_orders():
    c = config()
    data = json.loads(json.dumps(as_data(c)).replace("J1", "J2"))
    second = decode(Configuration, data)
    return replace(
        c,
        orders=c.orders + second.orders,
        operations=c.operations + second.operations,
        materials=c.materials + second.materials,
    )


class BoundaryTests(unittest.TestCase):
    def test_buffer_failure_pauses_deposit_until_repair(self):
        e = backend(
            (
                WorldEvent("failure.buffer", 4.5, "failure", "PIPE_BUFFER", None),
                WorldEvent("repair.buffer", 6, "repair", "PIPE_BUFFER", None),
            )
        )
        for phase in ("setup", "work"):
            self.assertTrue(start(e, "CUT", phase, "R").accepted)
            finish(e)
        self.assertTrue(start(e, "CUT", "handoff", "R").accepted)
        e.advance(5)
        self.assertEqual(e.snapshot.phases[-1].status, "paused")
        self.assertIsNone(e._position("J1.C1_out"))
        before = e.snapshot
        self.assertFalse(start(e, "CUT", "handoff", "R", action="resume").accepted)
        self.assertEqual(e.snapshot, before)
        e.advance(6)
        self.assertTrue(start(e, "CUT", "handoff", "R", action="resume").accepted)
        finish(e)
        self.assertEqual(e.now, 6.5)
        self.assertEqual(e._position("J1.C1_out").location_id, "PIPE_BUFFER")

    def test_multiple_modules_must_use_distinct_physical_identities(self):
        c = config()
        c = replace(
            c,
            materials=tuple(
                replace(m, quantity=2) if m.id == "J1.A1_out" else m for m in c.materials
            ),
        )
        validate(c)
        from adaptive_hrc_scheduling.contracts.codec import ContractError

        with self.assertRaisesRegex(ContractError, "ONE_MODULE"):
            backend(cfg=c)

    def test_buffer_full_blocks_handoff_holds_source_frees_worker(self):
        e = backend(cfg=two_orders())
        process(e, "CUT", "R")
        op = next(o for o in e.config.operations if o.id == "J2.C1")
        q = allocation(e, "CUT", "R", "W1")
        for phase in ("setup", "work"):
            self.assertTrue(issue(e, op, phase, "mode.CUT.R", q).accepted)
            finish(e, op.process_group_id)
        before = e.snapshot
        r = issue(e, op, "handoff", "mode.CUT.R", q)
        self.assertEqual(r.reason, "BUFFER_FULL")
        self.assertEqual(before, e.snapshot)
        self.assertTrue(
            any(
                x.resource_id == "CS1" and x.owner_group_id == op.process_group_id
                for x in e.snapshot.locks
            )
        )
        self.assertFalse(any(x.resource_id in {"W1", "R1"} for x in e.snapshot.locks))

    def test_cancelled_handoff_bypasses_full_buffer_with_scrap_lock(self):
        e = backend((WorldEvent("cancel.2", 9, "cancel", "J2", None),), cfg=two_orders())
        process(e, "CUT", "R")
        op = next(o for o in e.config.operations if o.id == "J2.C1")
        q = allocation(e, "CUT", "R", "W1")
        for phase in ("setup", "work"):
            self.assertTrue(issue(e, op, phase, "mode.CUT.R", q).accepted)
            finish(e, op.process_group_id)
        self.assertTrue(issue(e, op, "handoff", "mode.CUT.R", q).accepted)
        self.assertTrue(any(x.resource_id == "SCRAP_RECEIVE" for x in e.snapshot.locks))
        finish(e, op.process_group_id)
        self.assertEqual(e._position(op.output_id).status, "scrapped")
        self.assertEqual(e._position("J1.C1_out").location_id, "PIPE_BUFFER")

    def test_cancel_running_work_keeps_handoff_then_clears(self):
        e = backend((WorldEvent("cancel.1", 2, "cancel", "J1", None),))
        self.assertTrue(start(e, "CUT", "setup", "R").accepted)
        finish(e)
        self.assertTrue(start(e, "CUT", "work", "R").accepted)
        finish(e)
        self.assertFalse(e.dispatch(command(e, "cleanup", material="J1.C1.raw")).accepted)
        self.assertTrue(start(e, "CUT", "handoff", "R").accepted)
        finish(e)
        self.assertEqual(e._position("J1.C1_out").status, "scrapped")
        self.assertTrue(e.dispatch(command(e, "cleanup", material="J1.B1.raw")).accepted)
        e.advance(e.now + 2)
        self.assertEqual(e.status().code, "DRAINED")

    def test_failure_after_cancel_shortens_restart_tail_and_unlock_flag_matters(self):
        events = (
            WorldEvent("cancel.1", 2, "cancel", "J1", None),
            WorldEvent("failure.1", 2.5, "failure", "CS1_M", False),
            WorldEvent("repair.1", 5, "repair", "CS1_M", None),
        )
        e = backend(events)
        start(e, "CUT", "setup", "R")
        finish(e)
        start(e, "CUT", "work", "R")
        e.advance(3)
        self.assertFalse(e.dispatch(command(e, "cleanup", material="J1.C1.raw")).accepted)
        e.advance(5)
        self.assertTrue(e.dispatch(command(e, "cleanup", material="J1.C1.raw")).accepted)
        self.assertTrue(e.dispatch(command(e, "cleanup", material="J1.B1.raw")).accepted)
        e.advance(8)
        self.assertEqual(e.status().code, "DRAINED")
        self.assertFalse(e._done(operation(e, "CUT").process_group_id, "work"))

    def test_cancelled_restore_does_not_resurrect_paused_work(self):
        # Assembly work is resume-policy, unlike CUT/WELD restart work.
        e = backend()
        process(e, "CUT", "R")
        process(e, "BRACKET", worker="W2")
        for p in ("setup", "align"):
            self.assertTrue(start(e, "ASSEMBLE", p, "HR").accepted)
            finish(e)
        t = e.now
        # Recreate the same deterministic prefix with the disturbance calendar.
        e = backend(
            (
                WorldEvent("failure.1", t + 0.25, "failure", "R1", None),
                WorldEvent("repair.1", t + 0.5, "repair", "R1", None),
                WorldEvent("cancel.1", t + 0.75, "cancel", "J1", None),
            )
        )
        process(e, "CUT", "R")
        process(e, "BRACKET", worker="W2")
        for p in ("setup", "align"):
            start(e, "ASSEMBLE", p, "HR")
            finish(e)
        start(e, "ASSEMBLE", "work", "HR")
        e.advance(t + 0.5)
        self.assertTrue(start(e, "ASSEMBLE", "restore", "HR", sequence=1).accepted)
        finish(e)
        self.assertFalse(start(e, "ASSEMBLE", "work", "HR", action="resume").accepted)
        self.assertTrue(e.dispatch(command(e, "cleanup", material="J1.A1_out")).accepted)
        e.advance(e.now + 8)
        self.assertEqual(e.status().code, "DRAINED")
        self.assertTrue(
            any(p.phase_id == "work" and p.status == "paused" for p in e.snapshot.phases)
        )

    def test_preposition_cancel_withdraws_target_but_requires_reset(self):
        initial = backend()
        prepared_assembly(initial)
        t = initial.now
        e = backend((WorldEvent("cancel.1", t + 0.5, "cancel", "J1", None),))
        prepared_assembly(e)
        op = operation(e, "WELD")
        e.select_process(op.id, "mode.WELD.R", allocation(e, "WELD", "R", "W2").id)
        self.assertTrue(start(e, "WELD", "preposition", "R", transfer=True).accepted)
        finish(e)
        self.assertFalse(start(e, "WELD", "rig", "R", transfer=True).accepted)
        self.assertFalse(e.snapshot.reservations)
        self.assertFalse(any(x.resource_id == "WS1" for x in e.snapshot.locks))
        self.assertTrue(any(x.resource_id == "G1" for x in e.snapshot.locks))
        self.assertTrue(start(e, "WELD", "reset", "R", transfer=True).accepted)
        finish(e)
        self.assertTrue(e.dispatch(command(e, "cleanup", material="J1.A1_out")).accepted)
        e.advance(e.now + 8)
        self.assertEqual(e.status().code, "DRAINED")

    def test_inflight_cancel_unloads_original_target_and_cleanup_waits_reset(self):
        initial = backend()
        prepared_assembly(initial)
        t = initial.now
        e = backend((WorldEvent("cancel.1", t + 2.5, "cancel", "J1", None),))
        prepared_assembly(e)
        transfer_to(e, "WELD", "R", stop="unload")
        self.assertEqual(e._position("J1.A1_out").location_id, "WS1")
        self.assertFalse(start(e, "WELD", "setup", "R", "W2").accepted)
        self.assertFalse(e.dispatch(command(e, "cleanup", material="J1.A1_out")).accepted)
        self.assertTrue(start(e, "WELD", "reset", "R", transfer=True).accepted)
        finish(e)
        self.assertTrue(e.dispatch(command(e, "cleanup", material="J1.A1_out")).accepted)
        e.advance(e.now + 8)
        self.assertEqual(e.status().code, "DRAINED")
        self.assertEqual(e._position("J1.A1_out").status, "scrapped")

    def test_cleanup_crane_fault_cannot_bypass_move_and_reset(self):
        initial = backend()
        prepared_assembly(initial)
        t = initial.now
        e = backend(
            (
                WorldEvent("cancel.1", t, "cancel", "J1", None),
                WorldEvent("failure.1", t + 2.5, "failure", "G1", True),
                WorldEvent("repair.1", t + 5, "repair", "G1", None),
            )
        )
        prepared_assembly(e)
        self.assertTrue(e.dispatch(command(e, "cleanup", material="J1.A1_out")).accepted)
        e.advance(t + 4)
        self.assertEqual(e._position("J1.A1_out").status, "in_transit")
        self.assertEqual(e.cleanup_records[0].status, "paused")
        e.advance(t + 10)
        self.assertEqual(e.status().code, "DRAINED")
        self.assertAlmostEqual(e.drained_at_min, t + 8.5)

    def test_declared_common_prefix_mode_switch_preserves_history(self):
        e = backend()
        process(e, "CUT", "R")
        process(e, "BRACKET", worker="W2")
        self.assertTrue(start(e, "ASSEMBLE", "setup", "H").accepted)
        finish(e)
        self.assertTrue(start(e, "ASSEMBLE", "align", "HR").accepted)
        finish(e)
        self.assertFalse(start(e, "ASSEMBLE", "work", "H").accepted)
        self.assertTrue(start(e, "ASSEMBLE", "work", "HR").accepted)
        history = e._history(operation(e, "ASSEMBLE").process_group_id)
        self.assertEqual(history[0].mode_id, "mode.ASSEMBLE.H")

    def test_multimodule_join_reserves_all_slots_waits_last_reset(self):
        c = loads(
            Configuration, (ROOT / "examples/contracts/structural.json").read_text(encoding="utf-8")
        )
        c = replace(
            c,
            orders=tuple(replace(o, release_min=0) for o in c.orders if o.id == "J03"),
            operations=tuple(o for o in c.operations if o.order_id == "J03"),
            materials=tuple(m for m in c.materials if m.order_id == "J03"),
        )
        # Zero ordinary work rates isolate the spatial mechanism, while wait is
        # still positive and recovery/speed retain declared configuration values.
        c = replace(
            c,
            resources=tuple(
                replace(
                    r,
                    worker_parameters=replace(
                        r.worker_parameters,
                        work_per_min=0,
                        carry_per_min=0,
                        collaborate_per_min=0,
                        supervise_per_min=0,
                    ),
                )
                if r.kind == "worker"
                else r
                for r in c.resources
            ),
        )
        validate(c)
        e = backend(cfg=c)
        for suffix, station in (("1", "AS1"), ("2", "AS2")):
            for kind, prefix, site in (
                ("CUT", "C", "CS1"),
                ("BRACKET", "B", "PS1"),
                ("ASSEMBLE", "A", station),
            ):
                op = e.ctx.ops[f"J03.{prefix}{suffix}"]
                mode = e.ctx.modes[f"mode.{kind}.H"]
                q = next(
                    e.ctx.q[x]
                    for x in mode.allocation_ids
                    if e.ctx.q[x].station_id == site and e.ctx.q[x].worker_id == "H1"
                )
                for phase in mode.phases:
                    r = issue(e, op, phase.id, mode.id, q)
                    self.assertTrue(r.accepted, r.reason)
                    finish(e, op.process_group_id)
        op = e.ctx.ops["J03.A3"]
        mode = e.ctx.modes["mode.ASSEMBLE.H"]
        q = next(
            e.ctx.q[x]
            for x in mode.allocation_ids
            if e.ctx.q[x].station_id == "AS3" and e.ctx.q[x].worker_id == "H1"
        )
        e.select_process(op.id, mode.id, q.id)
        for i, group in enumerate(op.transfers):
            source = e._position(group.material_id).location_id
            tq = next(
                e.ctx.q[x]
                for x in group.allocation_ids
                if e.ctx.q[x].worker_id == "H1"
                and e.ctx.routes[e.ctx.q[x].route_id].source_id == source
                and e.ctx.routes[e.ctx.q[x].route_id].target_id == "AS3"
            )
            for phase in ("preposition", "rig", "move", "unload", "reset"):
                r = issue(e, op, phase, mode.id, tq, group.id)
                self.assertTrue(r.accepted, r.reason)
                if i == 0 and phase == "preposition":
                    self.assertEqual(len(e.snapshot.reservations), 2)
                    self.assertEqual({r.slot for r in e.snapshot.reservations}, {0, 1})
                if i == 1 and phase == "reset":
                    self.assertFalse(issue(e, op, "setup", mode.id, q).accepted)
                finish(e, group.id)
        self.assertTrue(issue(e, op, "setup", mode.id, q).accepted)
        finish(e, op.process_group_id)
        self.assertEqual(e._position(op.output_id).location_id, "AS3")
        self.assertTrue(all(e._position(mid).status == "consumed" for mid in op.input_ids))
        self.assertEqual(len([x for x in e.snapshot.locks if x.resource_id == "AS3"]), 1)


if __name__ == "__main__":
    unittest.main()
