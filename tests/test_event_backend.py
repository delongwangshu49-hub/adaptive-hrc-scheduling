"""Deterministic S09 execution witnesses; no scheduling algorithm or benchmark."""

import math
import unittest
from dataclasses import replace
from pathlib import Path

from adaptive_hrc_scheduling.contracts.codec import ContractError, loads
from adaptive_hrc_scheduling.contracts.messages import (
    Assignment,
    DispatchCommand,
    HiddenScenario,
    WorldEvent,
)
from adaptive_hrc_scheduling.contracts.validation import validate
from adaptive_hrc_scheduling.domain.models import Configuration
from adaptive_hrc_scheduling.event_backend import EventBackend

ROOT = Path(__file__).resolve().parents[1]


def config():
    return loads(Configuration, (ROOT / "examples/contracts/toy.json").read_text(encoding="utf-8"))


def backend(events=(), cfg=None):
    cfg = cfg or config()
    return EventBackend(
        cfg, HiddenScenario("S06-1.1", "hidden_scenario", cfg.id, cfg.units, 0, tuple(events))
    )


def operation(e, kind):
    return next(o for o in e.config.operations if o.kind == kind)


def allocation(e, kind, mode, worker):
    m = e.ctx.modes[f"mode.{kind}.{mode}"]
    return next(e.ctx.q[qid] for qid in m.allocation_ids if e.ctx.q[qid].worker_id == worker)


def command(e, action, *, a=None, worker=None, duration=None, material=None):
    return DispatchCommand(
        "S06-1.1",
        "dispatch",
        f"command.{len(e.events) + len(e._commands) + 1}",
        e.snapshot.run_id,
        e.config.id,
        "observation.manual",
        e.config.units,
        e.now,
        action,
        a,
        worker,
        duration,
        material,
    )


def start(
    e, kind, phase, mode="H", worker="W1", *, transfer=False, action="start", attempt=1, sequence=0
):
    op = operation(e, kind)
    if transfer:
        group = op.transfers[0]
        gid = group.id
        q = next(e.ctx.q[x] for x in group.allocation_ids if e.ctx.q[x].worker_id == worker)
    else:
        gid = op.process_group_id
        q = allocation(e, kind, mode, worker)
    a = Assignment(
        op.id,
        f"mode.{kind}.{mode}",
        gid,
        phase,
        q.id,
        attempt,
        sequence,
        e.now,
        e.now + 100,
        "MANUAL_WITNESS",
    )
    return e.dispatch(command(e, action, a=a))


def finish(e, gid=None):
    running = [
        p for p in e.snapshot.phases if p.status == "running" and (gid is None or p.group_id == gid)
    ]
    assert running
    p = running[-1]
    from adaptive_hrc_scheduling.contracts.messages import phase_execution_id

    key = phase_execution_id(p.operation_id, p.group_id, p.phase_id, p.attempt, p.restore_sequence)
    e.advance(e._deadlines[key])


def process(e, kind, mode="H", worker="W1"):
    op = operation(e, kind)
    for p in e.ctx.modes[f"mode.{kind}.{mode}"].phases:
        result = start(e, kind, p.id, mode, worker)
        assert result.accepted, result.reason
        finish(e, op.process_group_id)


def prepared_assembly(e):
    process(e, "CUT", "R", "W1")
    process(e, "BRACKET", "H", "W2")
    process(e, "ASSEMBLE", "HR", "W1")


def transfer_to(e, kind, mode="H", worker="W1", *, stop="reset"):
    op = operation(e, kind)
    if op.process_group_id:
        q = allocation(e, kind, mode, "W2")
        e.select_process(op.id, f"mode.{kind}.{mode}", q.id)
    for phase in ("preposition", "rig", "move", "unload", "reset"):
        r = start(e, kind, phase, mode, worker, transfer=True)
        assert r.accepted, r.reason
        finish(e, op.transfers[0].id)
        if phase == stop:
            break


class BackendTests(unittest.TestCase):
    def test_release_creates_raw_once_and_no_future_order(self):
        c = config()
        c = replace(c, orders=(replace(c.orders[0], release_min=2.0),))
        e = backend(cfg=c)
        self.assertFalse(e.snapshot.materials)
        e.advance(2)
        self.assertEqual(len(e.snapshot.materials), 2)
        e.advance(3)
        self.assertEqual(len(e.snapshot.materials), 2)

    def test_reject_missing_predecessor_atomically(self):
        e = backend()
        before = e.snapshot
        self.assertFalse(start(e, "ASSEMBLE", "setup").accepted)
        self.assertEqual(e.snapshot, before)

    def test_competition_does_not_hold_half_hr_team(self):
        e = backend()
        self.assertTrue(start(e, "CUT", "setup", "R").accepted)
        before = e.snapshot
        r = start(e, "BRACKET", "work", worker="W1")
        self.assertFalse(r.accepted)
        self.assertEqual(before, e.snapshot)
        self.assertTrue(start(e, "BRACKET", "work", worker="W2").accepted)
        self.assertEqual(len([p for p in e.snapshot.phases if p.status == "running"]), 2)

    def test_declared_duration_not_planned_end(self):
        e = backend()
        self.assertTrue(start(e, "CUT", "setup", "R").accepted)
        e.advance(1)
        self.assertTrue(e._done(operation(e, "CUT").process_group_id, "setup"))
        self.assertTrue(start(e, "CUT", "work", "R").accepted)
        e.advance(4)
        self.assertTrue(e._done(operation(e, "CUT").process_group_id, "work"))

    def test_hr_sync_and_feed_completion(self):
        e = backend()
        process(e, "CUT", "R")
        process(e, "BRACKET", worker="W2")
        op = operation(e, "ASSEMBLE")
        self.assertTrue(start(e, "ASSEMBLE", "setup", "HR").accepted)
        self.assertEqual(len(e.picked_materials), 2)
        self.assertIsNone(e._position(op.output_id))
        finish(e)
        self.assertFalse(e.picked_materials)
        self.assertEqual(e._position(op.output_id).location_id, "AS1")
        self.assertTrue(start(e, "ASSEMBLE", "align", "HR").accepted)
        finish(e)
        self.assertTrue(start(e, "ASSEMBLE", "work", "HR").accepted)
        locks = {x.resource_id for x in e.snapshot.locks if x.owner_group_id == op.process_group_id}
        self.assertTrue({"W1", "R1", "AS1", "AS1_X"} <= locks)
        p = e.snapshot.phases[-1]
        self.assertGreater(p.speed_multiplier, 1)
        finish(e)
        self.assertFalse(any(x.resource_id in {"R1", "W1"} for x in e.snapshot.locks))

    def test_source_released_only_after_rig_and_reset_required(self):
        e = backend()
        prepared_assembly(e)
        op = operation(e, "WELD")
        e.select_process(op.id, "mode.WELD.R", allocation(e, "WELD", "R", "W2").id)
        self.assertTrue(start(e, "WELD", "preposition", "R", transfer=True).accepted)
        self.assertTrue(any(x.resource_id == "AS1" for x in e.snapshot.locks))
        finish(e)
        self.assertTrue(start(e, "WELD", "rig", "R", transfer=True).accepted)
        finish(e)
        self.assertFalse(any(x.resource_id == "AS1" for x in e.snapshot.locks))
        self.assertEqual(e._position(op.input_ids[0]).status, "in_transit")
        for p in ("move", "unload"):
            self.assertTrue(start(e, "WELD", p, "R", transfer=True).accepted)
            finish(e)
        self.assertTrue(start(e, "WELD", "setup", "R", "W2").accepted)
        self.assertTrue(start(e, "WELD", "reset", "R", transfer=True).accepted)
        self.assertEqual(len([p for p in e.snapshot.phases if p.status == "running"]), 2)
        finish(e, op.transfers[0].id)
        self.assertFalse(any(x.resource_id == "G1" for x in e.snapshot.locks))

    def test_full_manual_execution_drains_and_tail_rests(self):
        e = backend()
        prepared_assembly(e)
        transfer_to(e, "WELD", "R")
        process(e, "WELD", "R", "W2")
        transfer_to(e, "INSPECT")
        process(e, "INSPECT", worker="W2")
        transfer_to(e, "LIFT", stop="unload")
        completion = e.snapshot.orders[0].actual_completion_min
        self.assertIsNotNone(completion)
        self.assertNotEqual(e.status().code, "DRAINED")
        self.assertTrue(start(e, "LIFT", "reset", transfer=True).accepted)
        finish(e)
        self.assertEqual(e.status().code, "DRAINED")
        self.assertEqual(e.drained_at_min, completion + 1)
        e.advance(e.now + 3)
        self.assertTrue(all(w.activity == "rest" for w in e.snapshot.workers))
        validate(e.snapshot, config=e.config)

    def test_same_time_completion_before_failure_and_cancel_before_dispatch(self):
        e = backend(
            (
                WorldEvent("failure.1", 1, "failure", "R1", None),
                WorldEvent("cancel.1", 1, "cancel", "J1", None),
            )
        )
        self.assertTrue(start(e, "CUT", "setup", "R").accepted)
        e.advance(1)
        self.assertEqual(e.snapshot.phases[0].status, "completed")
        self.assertFalse(start(e, "CUT", "work", "R").accepted)
        types = [x.event_type for x in e.events if x.sim_time_min == 1]
        self.assertEqual(types[0], "completed")

    def test_restart_after_restore_keeps_failed_attempt(self):
        e = backend(
            (
                WorldEvent("failure.1", 2, "failure", "R1", None),
                WorldEvent("repair.1", 3, "repair", "R1", None),
            )
        )
        self.assertTrue(start(e, "CUT", "setup", "R").accepted)
        finish(e)
        self.assertTrue(start(e, "CUT", "work", "R").accepted)
        e.advance(3)
        self.assertEqual(e.snapshot.phases[-1].status, "failed")
        self.assertFalse(start(e, "CUT", "work", "R", attempt=2).accepted)
        self.assertTrue(start(e, "CUT", "restore", "R", sequence=1).accepted)
        finish(e)
        self.assertTrue(start(e, "CUT", "work", "R", attempt=2).accepted)
        finish(e)
        attempts = [p for p in e.snapshot.phases if p.phase_id == "work"]
        self.assertEqual([p.status for p in attempts], ["failed", "completed"])
        self.assertEqual([p.attempt for p in attempts], [1, 2])

    def test_paused_stage_resumes_original_sample(self):
        e = backend(
            (
                WorldEvent("failure.1", 1, "failure", "W2", None),
                WorldEvent("repair.1", 2, "repair", "W2", None),
            )
        )
        self.assertTrue(start(e, "BRACKET", "work", worker="W2").accepted)
        before = e.snapshot.phases[-1]
        e.advance(2)
        self.assertEqual(e.snapshot.phases[-1].status, "paused")
        self.assertTrue(start(e, "BRACKET", "work", worker="W2", action="resume").accepted)
        self.assertEqual(e.snapshot.phases[-1].sampled_f, before.sampled_f)
        finish(e)
        self.assertAlmostEqual(e.now, 4.6)

    def test_explicit_rest_and_wait_cap_protection(self):
        c = config()
        c = replace(
            c,
            resources=tuple(
                replace(r, worker_parameters=replace(r.worker_parameters, initial_f=0.79))
                if r.kind == "worker"
                else r
                for r in c.resources
            ),
        )
        e = backend(cfg=c)
        before = e.snapshot
        self.assertFalse(start(e, "BRACKET", "work").accepted)
        self.assertEqual(e.snapshot, before)
        e.advance(10)
        self.assertTrue(any(x.cause == "FATIGUE_PROTECTION" for x in e.events))
        self.assertTrue(all(w.fatigue <= c.fatigue_cap for w in e.snapshot.workers))

    def test_cancel_raw_cleanup_is_positive_and_covers_all_materials(self):
        e = backend((WorldEvent("cancel.1", 0, "cancel", "J1", None),))
        for m in tuple(e.snapshot.materials):
            self.assertTrue(e.dispatch(command(e, "cleanup", material=m.material_id)).accepted)
        self.assertNotEqual(e.status().code, "DRAINED")
        e.advance(3)
        self.assertEqual(e.status().code, "DRAINED")
        self.assertEqual(e.drained_at_min, 2)
        self.assertTrue(all(m.status == "scrapped" for m in e.snapshot.materials))

    def test_cancel_setup_finishes_then_clears_without_work(self):
        e = backend((WorldEvent("cancel.1", 0.5, "cancel", "J1", None),))
        self.assertTrue(start(e, "CUT", "setup", "R").accepted)
        e.advance(1)
        self.assertFalse(start(e, "CUT", "work", "R").accepted)
        for m in tuple(e.snapshot.materials):
            self.assertTrue(e.dispatch(command(e, "cleanup", material=m.material_id)).accepted)
        e.advance(4)
        self.assertEqual(e.status().code, "DRAINED")
        self.assertFalse(any(p.phase_id == "work" for p in e.snapshot.phases))

    def test_commands_cannot_replay_or_rewind(self):
        e = backend()
        c = command(e, "rest", worker="W1", duration=1)
        self.assertTrue(e.dispatch(c).accepted)
        with self.assertRaises(ContractError):
            e.dispatch(c)
        self.assertFalse(start(e, "CUT", "setup", "R").accepted)
        e.advance(1)
        with self.assertRaises(ContractError):
            e.advance(0)

    def test_waiting_is_not_false_drain_or_deadlock_claim(self):
        e = backend()
        self.assertEqual(e.status().code, "WAITING")
        self.assertIn("EXPLICIT_DISPATCH", e.status().reason)

    def test_split_clock_never_completes_one_float_early(self):
        e = backend()
        self.assertTrue(start(e, "BRACKET", "work", worker="W2").accepted)
        gid = operation(e, "BRACKET").process_group_id
        end = e.completion_time(gid)
        for t in (0.1, 0.3, 1.1, 2.2, math.nextafter(end, 0)):
            e.advance(t)
            self.assertFalse(e._done(gid, "work"))
        e.advance(end)
        self.assertTrue(e._done(gid, "work"))

    def test_failed_worker_can_take_protective_rest_without_erasing_fault(self):
        c = config()
        c = replace(
            c,
            resources=tuple(
                replace(
                    r,
                    worker_parameters=replace(r.worker_parameters, initial_f=0.79, work_per_min=0),
                )
                if r.kind == "worker"
                else r
                for r in c.resources
            ),
        )
        e = backend((WorldEvent("failure.1", 0.1, "failure", "W2", None),), cfg=c)
        # Use INSPECT-free source BRACKET, whose required handoff still protects
        # carry: lower that declared rate just for this fault/rest boundary.
        c = replace(
            c,
            resources=tuple(
                replace(r, worker_parameters=replace(r.worker_parameters, carry_per_min=0))
                if r.kind == "worker"
                else r
                for r in c.resources
            ),
        )
        e = backend((WorldEvent("failure.1", 0.1, "failure", "W2", None),), cfg=c)
        self.assertTrue(start(e, "BRACKET", "work", worker="W2").accepted)
        e.advance(12)
        self.assertTrue(next(r.failed for r in e.snapshot.resources if r.resource_id == "W2"))
        self.assertEqual(e.snapshot.phases[0].status, "paused")
        self.assertTrue(
            any(x.entity_id == "W2" and x.cause == "FATIGUE_PROTECTION" for x in e.events)
        )

    def test_invalid_external_repair_does_not_consume_calendar_or_clock(self):
        e = backend((WorldEvent("repair.invalid", 2, "repair", "R1", None),))
        before = e.snapshot
        with self.assertRaises(ContractError):
            e.advance(3)
        self.assertEqual(before, e.snapshot)
        with self.assertRaises(ContractError):
            e.advance(3)


if __name__ == "__main__":
    unittest.main()
