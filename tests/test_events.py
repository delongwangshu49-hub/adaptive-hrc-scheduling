"""S08 state-transition regressions; hand-constructed states, not production runs."""

import itertools
import unittest
from dataclasses import replace
from pathlib import Path

from adaptive_hrc_scheduling.contracts.codec import ContractError, loads
from adaptive_hrc_scheduling.contracts.messages import WorldEvent, phase_execution_id
from adaptive_hrc_scheduling.contracts.validation import validate
from adaptive_hrc_scheduling.domain.models import Configuration
from adaptive_hrc_scheduling.domain.state import Binding, ExecutionSnapshot, Lock, PhaseState
from adaptive_hrc_scheduling.events import (
    TickItem,
    advance_phase,
    apply_events,
    cancellation_tail,
    clear_preparation,
    ordered_tick,
    paired_bits,
    phase_rule,
    preparation_for,
    restart_attempt,
    restore_progress,
)

FIXTURES = Path(__file__).resolve().parents[1] / "examples/contracts"


def config_and_snapshot():
    config = loads(Configuration, (FIXTURES / "toy.json").read_text(encoding="utf-8"))
    state = loads(
        ExecutionSnapshot,
        (FIXTURES / "execution_snapshot.json").read_text(encoding="utf-8"),
        config=config,
    )
    return config, state


def process_state(config, state, kind="CUT", mode="R", phase="work", status="running"):
    op = next(o for o in config.operations if o.kind == kind)
    mid = f"mode.{kind}.{mode}"
    m = next(m for m in config.modes if m.id == mid)
    q = next(q for q in config.allocations if q.id in m.allocation_ids)
    binding = Binding(op.id, op.process_group_id, q.id)
    progress = PhaseState(
        op.id,
        mid,
        q.id,
        binding.group_id,
        phase,
        1,
        0,
        status,
        0 if status == "completed" else 0.25,
        None,
        1.0,
        1.0,
        2.0 if status == "completed" else None,
    )
    rule = phase_rule(config, progress)
    if rule.fatigue_sensitive:
        progress = replace(progress, sampled_f=0.2, speed_multiplier=1.2)
    preparations = state.preparations
    if q.robot_id:
        preparations = tuple(
            preparation_for(config, binding, valid=True) if p.robot_id == q.robot_id else p
            for p in preparations
        )
    locks = [Lock(q.worker_id, binding.group_id, "active")]
    if q.robot_id:
        locks.append(Lock(q.robot_id, binding.group_id, "active"))
    for rid in (q.equipment_id, q.station_id, q.fixture_id):
        if rid:
            locks.append(Lock(rid, binding.group_id, "held"))
    result = replace(
        state,
        sim_time_min=2.0,
        bindings=(binding,),
        phases=(progress,),
        preparations=preparations,
        locks=tuple(locks),
    )
    validate(result, config=config)
    return result


def transfer_state(config, state, phase="move", status="running"):
    op = next(o for o in config.operations if o.kind == "LIFT")
    group = op.transfers[0]
    q = next(q for q in config.allocations if q.id in group.allocation_ids)
    binding = Binding(op.id, group.id, q.id)
    progress = PhaseState(
        op.id,
        op.mode_ids[0],
        q.id,
        group.id,
        phase,
        1,
        0,
        status,
        0 if status == "completed" else 0.5,
        None,
        1.0,
        1.0,
        2.0 if status == "completed" else None,
    )
    route = next(r for r in config.routes if r.id == q.route_id)
    result = replace(
        state,
        sim_time_min=2.0,
        bindings=(binding,),
        phases=(progress,),
        locks=(Lock(q.crane_id, group.id, "held"), Lock(route.space_id, group.id, "held")),
    )
    validate(result, config=config)
    return result


class EventTests(unittest.TestCase):
    def setUp(self):
        self.config, self.initial = config_and_snapshot()

    def event(self, kind, entity, flag=None, eid="event.a"):
        return WorldEvent(eid, 2.0, kind, entity, flag)

    def cancel(self, state):
        return apply_events(self.config, state, (self.event("cancel", "J1"),)).snapshot

    def test_tick_permutations_have_one_order(self):
        stages = ("completion", "external", "protection", "observation", "dispatch")
        items = tuple(TickItem("tick." + x, 2.0, x) for x in stages)
        for permutation in itertools.permutations(items):
            self.assertEqual(ordered_tick(permutation), items)
        with self.assertRaises(ContractError):
            ordered_tick((items[0], replace(items[1], at_min=3.0)))
        with self.assertRaises(ContractError):
            ordered_tick((items[0], items[0]))

    def test_external_input_order_does_not_change_state(self):
        state = process_state(self.config, self.initial)
        events = (
            self.event("failure", "CS1_M", False, "event.b"),
            self.event("cancel", "J1", eid="event.a"),
        )
        a = apply_events(self.config, state, events)
        b = apply_events(self.config, state, events[::-1])
        self.assertEqual(a, b)
        self.assertEqual(a.applied_event_ids, ("event.a", "event.b"))

    def test_completed_work_wins_over_simultaneous_failure(self):
        state = process_state(self.config, self.initial, status="completed")
        result = apply_events(self.config, state, (self.event("failure", "CS1_M", False),))
        self.assertEqual(result.snapshot.phases, state.phases)
        self.assertFalse(result.interruptions)
        self.assertFalse(result.snapshot.preparations[0].valid)

    def test_running_zero_work_rejected_before_external_batch(self):
        state = process_state(self.config, self.initial)
        state = replace(state, phases=(replace(state.phases[0], remaining_base_min=0.0),))
        with self.assertRaisesRegex(ContractError, "completions"):
            apply_events(self.config, state, ())

    def test_failure_restart_preserves_cost_history_binding_and_locks(self):
        state = process_state(self.config, self.initial)
        result = apply_events(self.config, state, (self.event("failure", "CS1_M", False),))
        after = result.snapshot
        self.assertEqual(after.phases[0].status, "failed")
        self.assertEqual(after.phases[0].attempt, 1)
        self.assertEqual(after.phases[0].remaining_base_min, 0.25)
        self.assertEqual(after.bindings, state.bindings)
        self.assertEqual(after.materials, state.materials)
        self.assertEqual(
            [(w.fatigue, w.exposure_min) for w in after.workers],
            [(w.fatigue, w.exposure_min) for w in state.workers],
        )
        self.assertEqual(
            [lock for lock in after.locks if lock.purpose == "held"],
            [lock for lock in state.locks if lock.purpose == "held"],
        )
        self.assertFalse(any(lock.purpose == "active" for lock in after.locks))
        self.assertEqual(result.interruptions[0].discarded_base_min, 2.75)
        self.assertEqual(state.phases[0].status, "running")  # immutable input

    def test_repeated_failure_does_not_double_count_failed_attempt(self):
        state = process_state(self.config, self.initial)
        first = apply_events(self.config, state, (self.event("failure", "CS1_M", False),))
        second = apply_events(
            self.config, first.snapshot, (self.event("failure", "CS1_M", False, "event.b"),)
        )
        self.assertFalse(second.interruptions)
        self.assertEqual(first.snapshot, second.snapshot)

    def test_repair_does_not_resume_restore_or_create_attempt(self):
        state = process_state(self.config, self.initial)
        failed = apply_events(self.config, state, (self.event("failure", "CS1_M", True),)).snapshot
        repaired = apply_events(self.config, failed, (self.event("repair", "CS1_M"),)).snapshot
        self.assertEqual(repaired.phases, failed.phases)
        self.assertFalse(repaired.preparations[0].valid)
        with self.assertRaises(ContractError):
            apply_events(self.config, repaired, (self.event("repair", "CS1_M"),))

    def test_restart_resamples_current_worker_and_changes_identity(self):
        state = process_state(self.config, self.initial, "CUT", "H")
        old = replace(state.phases[0], status="failed")
        worker = replace(self.initial.workers[0], fatigue=0.5, exposure_min=12.0)
        fresh = restart_attempt(self.config, old, worker, 4.0)
        self.assertEqual((fresh.attempt, fresh.sampled_f, fresh.speed_multiplier), (2, 0.5, 1.5))
        self.assertEqual(fresh.remaining_base_min, 4.0)
        self.assertEqual(old.remaining_base_min, 0.25)
        self.assertNotEqual(
            phase_execution_id(old.operation_id, old.group_id, old.phase_id, 1),
            phase_execution_id(fresh.operation_id, fresh.group_id, fresh.phase_id, 2),
        )

    def test_all_other_process_phases_resume_with_original_sample(self):
        for kind, mode, name in (
            ("CUT", "R", "setup"),
            ("BRACKET", "H", "work"),
            ("ASSEMBLE", "HR", "work"),
            ("INSPECT", "H", "work"),
            ("WELD", "R", "handoff"),
        ):
            with self.subTest(kind=kind, name=name):
                state = process_state(self.config, self.initial, kind, mode, name)
                site = next(
                    q.station_id
                    for q in self.config.allocations
                    if q.id == state.bindings[0].allocation_id
                )
                after = apply_events(
                    self.config, state, (self.event("failure", site, True),)
                ).snapshot
                self.assertEqual(after.phases[0], replace(state.phases[0], status="paused"))

    def test_weld_work_restarts(self):
        state = process_state(self.config, self.initial, "WELD", "HR")
        after = apply_events(self.config, state, (self.event("failure", "WS1_M", False),)).snapshot
        self.assertEqual(after.phases[0].status, "failed")

    def test_fault_while_waiting_invalidates_preparation(self):
        state = process_state(self.config, self.initial, phase="setup", status="completed")
        after = apply_events(self.config, state, (self.event("failure", "W1"),)).snapshot
        self.assertFalse(after.preparations[0].valid)
        self.assertEqual(after.phases, state.phases)

    def test_transfer_failure_keeps_transport_locks_even_with_release_flag(self):
        state = transfer_state(self.config, self.initial)
        after = apply_events(self.config, state, (self.event("failure", "G1", True),)).snapshot
        self.assertEqual(after.locks, state.locks)
        self.assertEqual(after.phases[0].status, "paused")
        tail = cancellation_tail(self.config, self.cancel(after), state.bindings[0].group_id)
        self.assertEqual(tail.phase_ids, ("move", "unload", "reset"))
        self.assertTrue(tail.wait_for_repair)

    def test_invalid_event_inputs_are_atomic(self):
        state = process_state(self.config, self.initial)
        for events in (
            (self.event("failure", "CS1_M"),),
            (self.event("failure", "CS1_M", True), self.event("repair", "CS1_M", eid="event.b")),
            (replace(self.event("cancel", "J1"), sim_time_min=3.0),),
        ):
            with self.assertRaises(ContractError):
                apply_events(self.config, state, events)
        self.assertFalse(state.orders[0].cancelled)

    def test_release_and_cancel_same_clock_follow_ids_without_uncancelling(self):
        state = replace(self.initial, orders=(replace(self.initial.orders[0], released=False),))
        events = (
            WorldEvent("z.release", 0.0, "release", "J1", None),
            WorldEvent("a.cancel", 0.0, "cancel", "J1", None),
        )
        after = apply_events(self.config, state, events).snapshot
        self.assertTrue(after.orders[0].released and after.orders[0].cancelled)

    def test_cancel_retains_fatigue_actual_completion_and_materials(self):
        state = replace(
            self.initial,
            sim_time_min=2.0,
            orders=(replace(self.initial.orders[0], actual_completion_min=1.0),),
        )
        after = self.cancel(state)
        self.assertEqual(after.workers, state.workers)
        self.assertEqual(after.materials, state.materials)
        self.assertEqual(after.orders[0].actual_completion_min, 1.0)

    def test_cancel_process_boundaries(self):
        for kind, mode, phase, expected in (
            ("CUT", "R", "setup", ("setup",)),
            ("CUT", "R", "work", ("work", "handoff")),
            ("BRACKET", "H", "work", ("work", "handoff")),
            ("ASSEMBLE", "HR", "align", ("align",)),
            ("WELD", "HR", "work", ("work", "handoff")),
            ("INSPECT", "H", "work", ("work",)),
            ("CUT", "R", "handoff", ("handoff",)),
        ):
            with self.subTest(kind=kind, phase=phase):
                state = self.cancel(process_state(self.config, self.initial, kind, mode, phase))
                tail = cancellation_tail(self.config, state, state.bindings[0].group_id)
                self.assertEqual(tail.phase_ids, expected)
                self.assertTrue(tail.cleanup_required)

    def test_cancel_completed_setup_skips_new_work_completed_work_keeps_handoff(self):
        for phase, expected in (("setup", ()), ("work", ("handoff",)), ("handoff", ())):
            state = self.cancel(
                process_state(self.config, self.initial, phase=phase, status="completed")
            )
            self.assertEqual(
                cancellation_tail(self.config, state, state.bindings[0].group_id).phase_ids,
                expected,
            )

    def test_cancel_failed_work_clears_only_when_unlock_is_allowed(self):
        for allowed in (False, True):
            state = process_state(self.config, self.initial)
            failed = apply_events(
                self.config, state, (self.event("failure", "CS1_M", allowed),)
            ).snapshot
            tail = cancellation_tail(self.config, self.cancel(failed), state.bindings[0].group_id)
            self.assertEqual(tail.phase_ids, ())
            self.assertEqual(tail.wait_for_repair, not allowed)

    def test_cancel_transport_each_boundary(self):
        expected = {
            "preposition": ("preposition", "reset"),
            "rig": ("rig", "move", "unload", "reset"),
            "move": ("move", "unload", "reset"),
            "unload": ("unload", "reset"),
            "reset": ("reset",),
        }
        for phase, phases in expected.items():
            state = self.cancel(transfer_state(self.config, self.initial, phase))
            self.assertEqual(
                cancellation_tail(self.config, state, state.bindings[0].group_id).phase_ids, phases
            )
        state = self.cancel(transfer_state(self.config, self.initial, "preposition", "completed"))
        self.assertEqual(
            cancellation_tail(self.config, state, state.bindings[0].group_id).phase_ids, ("reset",)
        )

    def test_advance_work_and_exact_completion(self):
        state = process_state(self.config, self.initial)
        p = state.phases[0]
        halfway = advance_phase(p, 0.125, 2.0)
        done = advance_phase(halfway, 0.125, 2.125)
        self.assertEqual(done.status, "completed")
        self.assertEqual(done.completed_min, 2.125)
        self.assertEqual(done.attempt, p.attempt)
        with self.assertRaises(ContractError):
            advance_phase(p, 0.5, 2.0)
        with self.assertRaises(ContractError):
            advance_phase(replace(p, status="paused"), 0.1, 2.0)

    def test_preparation_reassignment_same_station_needs_restore(self):
        state = process_state(self.config, self.initial)
        binding = state.bindings[0]
        self.assertFalse(preparation_for(self.config, binding, valid=False).valid)
        self.assertTrue(preparation_for(self.config, binding, valid=True).valid)
        self.assertEqual(clear_preparation("R1").group_id, None)

    def restore_state(self):
        state = process_state(self.config, self.initial, phase="setup", status="completed")
        return replace(state, preparations=(replace(state.preparations[0], valid=False),))

    def test_restore_identity_cost_and_interruption(self):
        state = self.restore_state()
        restore = restore_progress(self.config, state, state.bindings[0].group_id, "mode.CUT.R")
        self.assertEqual(
            (restore.restore_sequence, restore.attempt, restore.remaining_base_min), (1, 1, 1.0)
        )
        state = replace(state, phases=state.phases + (restore,))
        paused = apply_events(self.config, state, (self.event("failure", "R1"),)).snapshot
        self.assertEqual(paused.phases[-1].status, "paused")
        self.assertEqual(paused.phases[-1].restore_sequence, 1)
        with self.assertRaises(ContractError):
            restore_progress(self.config, paused, state.bindings[0].group_id, "mode.CUT.R")

    def test_restore_rejects_cancel_and_missing_original_prefix(self):
        state = self.restore_state()
        for candidate in (self.cancel(state), replace(state, phases=())):
            with self.assertRaises(ContractError):
                restore_progress(self.config, candidate, state.bindings[0].group_id, "mode.CUT.R")

    def test_stable_pairing_is_call_order_independent_and_attempt_scoped(self):
        keys = [("J1.C1", "failure", i) for i in range(12)]
        expected = {key: paired_bits(7, "world", *key) for key in keys}
        self.assertEqual({key: paired_bits(7, "world", *key) for key in reversed(keys)}, expected)
        self.assertNotEqual(
            paired_bits(7, "processing", "J1.C1", "work", 0, attempt=1),
            paired_bits(7, "processing", "J1.C1", "work", 0, attempt=2),
        )
        self.assertNotEqual(paired_bits(7, "world", *keys[0]), paired_bits(7, "sensor", *keys[0]))
        with self.assertRaises(ContractError):
            paired_bits(True, "world", *keys[0])

    def test_sensitive_completion_uses_declared_float_duration_without_epsilon(self):
        state = process_state(self.config, self.initial, "ASSEMBLE", "HR")
        p = state.phases[0]
        duration = p.remaining_base_min * p.speed_multiplier
        done = advance_phase(p, duration, 3.0)
        self.assertEqual(done.status, "completed")
        import math

        earlier = advance_phase(p, math.nextafter(duration, 0.0), 3.0)
        self.assertEqual(earlier.status, "running")

    def test_offline_cancellation_set_never_uses_completion_speed(self):
        from adaptive_hrc_scheduling.contracts.messages import HiddenScenario
        from adaptive_hrc_scheduling.events import offline_order_ids

        for time, expected in ((40.0, ()), (41.0, ("J1",))):
            scenario = HiddenScenario(
                "S06-1.1",
                "hidden_scenario",
                self.config.id,
                self.config.units,
                1,
                (WorldEvent("cancel.J1", time, "cancel", "J1", None),),
            )
            self.assertEqual(offline_order_ids(self.config, scenario), expected)

    def test_withdraw_reservations_never_removes_committed_transport_target(self):
        from adaptive_hrc_scheduling.domain.state import Reservation
        from adaptive_hrc_scheduling.events import withdrawable_reservations

        op = next(o for o in self.config.operations if o.kind == "WELD")
        transfer = op.transfers[0]
        q = next(q for q in self.config.allocations if q.id in transfer.allocation_ids)
        binding = Binding(op.id, transfer.id, q.id)
        reservation = Reservation(transfer.material_id, q.station_id, transfer.id, None)
        p = PhaseState(
            op.id,
            op.mode_ids[0],
            q.id,
            transfer.id,
            "rig",
            1,
            0,
            "running",
            0.5,
            None,
            1.0,
            1.0,
            None,
        )
        state = replace(
            self.initial,
            sim_time_min=2.0,
            bindings=(binding,),
            phases=(p,),
            reservations=(reservation,),
        )
        state = self.cancel(state)
        self.assertEqual(withdrawable_reservations(self.config, state), ())
        state = replace(
            state,
            phases=(
                replace(
                    p,
                    phase_id="preposition",
                    status="completed",
                    remaining_base_min=0.0,
                    completed_min=2.0,
                ),
            ),
        )
        self.assertEqual(withdrawable_reservations(self.config, state), (reservation,))
        self.assertEqual(state.reservations, (reservation,))  # instructions, not release execution

    def test_source_failure_after_rig_does_not_interrupt_crane_move(self):
        state = transfer_state(self.config, self.initial)
        q = next(q for q in self.config.allocations if q.id == state.bindings[0].allocation_id)
        route = next(r for r in self.config.routes if r.id == q.route_id)
        result = apply_events(self.config, state, (self.event("failure", route.source_id, False),))
        self.assertEqual(result.snapshot.phases, state.phases)
        self.assertFalse(result.interruptions)
        rig = transfer_state(self.config, self.initial, "rig")
        self.assertEqual(
            apply_events(self.config, rig, (self.event("failure", route.source_id, False),))
            .snapshot.phases[0]
            .status,
            "paused",
        )

        paused = apply_events(
            self.config, rig, (self.event("failure", route.source_id, False),)
        ).snapshot
        self.assertTrue(
            cancellation_tail(
                self.config, self.cancel(paused), rig.bindings[0].group_id
            ).wait_for_repair
        )

    def test_feed_route_failure_after_setup_does_not_interrupt_work(self):
        state = process_state(self.config, self.initial, "ASSEMBLE", "HR")
        result = apply_events(self.config, state, (self.event("failure", "FEED_ROUTE"),))
        self.assertEqual(result.snapshot.phases, state.phases)
        self.assertTrue(result.snapshot.preparations[0].valid)


if __name__ == "__main__":
    unittest.main()
