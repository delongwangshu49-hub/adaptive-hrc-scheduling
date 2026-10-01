"""S08 deterministic disturbance rules; no resource allocator or event loop.

Snapshots passed to apply_events are already advanced through all completions
at their clock. Returned records preserve physical locks, costs and history.
"""

import hashlib
import json
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Literal

from .contracts.codec import ID, Index, Nonnegative, Positive, as_data, decode, require
from .contracts.messages import HiddenScenario, phase_execution_id
from .contracts.validation import Context, validate
from .domain.models import Phase
from .domain.phases import resolve_process_phase
from .domain.state import ExecutionSnapshot, PhaseState, Preparation, WorkerState
from .human_state import sample_phase


@dataclass(frozen=True)
class TickItem:
    id: ID
    at_min: Nonnegative
    stage: Literal["completion", "external", "protection", "observation", "dispatch"]


def ordered_tick(items):
    """Stable order within one clock; caller advances work/integrals first."""
    items = tuple(decode(TickItem, as_data(x)) for x in items)
    require(len({x.id for x in items}) == len(items), "duplicate tick identity")
    require(len({x.at_min for x in items}) <= 1, "tick spans multiple times")
    ranks = {
        name: i
        for i, name in enumerate(
            ("completion", "external", "protection", "observation", "dispatch")
        )
    }
    return tuple(sorted(items, key=lambda x: (ranks[x.stage], x.id)))


def paired_bits(seed, stream, entity_id, event_type, occurrence, *, attempt=0):
    """256 deterministic bits keyed by identity, never by call order.

    This is a random-input primitive, not a fitted probability distribution.
    Use separate streams for exogenous, processing and observation inputs.
    """
    for x in (seed, occurrence, attempt):
        decode(Index, x)
    for x in (stream, entity_id, event_type):
        decode(ID, x)
    payload = json.dumps(
        ["S08-1", seed, stream, entity_id, event_type, occurrence, attempt], separators=(",", ":")
    )
    return int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest(), "big")


def phase_rule(config, progress):
    """Resolve an existing process or fixed-route transport phase."""
    ctx = Context(config)
    _, transfer, q = ctx.binding(
        progress.operation_id, progress.group_id, progress.allocation_id, progress.mode_id
    )
    if transfer is None:
        return resolve_process_phase(
            config, progress.operation_id, progress.mode_id, progress.phase_id
        )
    names = ("preposition", "rig", "move", "unload", "reset")
    require(progress.phase_id in names, "unknown transport phase")
    i = names.index(progress.phase_id)
    human = progress.phase_id in {"rig", "unload"}
    return Phase(
        progress.phase_id,
        names[i - 1 : i] if i else (),
        getattr(ctx.routes[q.route_id], progress.phase_id + "_min"),
        ("worker", "crane", "route") if human else ("crane", "route"),
        "carry" if human else None,
        False,
        "resume",
        "reset" if i in (0, 4) else "unload_reset",
        False,
        False,
    )


def advance_phase(progress, elapsed_min, at_min):
    """Advance only net work since the caller's previous clock, not downtime.

    The declared floating-point remaining duration is the exact calendar boundary.
    No epsilon completes nearby work. Integration,
    output movement and completion lock effects belong to the S09 caller.
    """
    decode(PhaseState, as_data(progress))
    decode(Nonnegative, elapsed_min)
    decode(Nonnegative, at_min)
    require(
        progress.status == "running" and progress.completed_min is None,
        "only running work advances",
    )
    require(progress.started_min <= at_min - elapsed_min, "elapsed before start")
    require(progress.remaining_base_min > 0, "running phase has no work")
    duration = decode(Positive, progress.remaining_base_min * progress.speed_multiplier)
    require(elapsed_min <= duration, "advance crosses completion; split at boundary")
    left = (
        Fraction(0)
        if elapsed_min == duration
        else Fraction(progress.remaining_base_min)
        - Fraction(elapsed_min) / Fraction(progress.speed_multiplier)
    )
    require(left >= 0, "unrepresentable remaining work")
    return replace(
        progress,
        remaining_base_min=float(left),
        status="completed" if left == 0 else "running",
        completed_min=at_min if left == 0 else None,
    )


def restart_attempt(config, failed, worker_state, at_min):
    """Construct a fresh attempt only at an independently authorized actual start.

    Does not insert it in history, acquire resources or grant dispatch permission.
    The failed record remains in the caller's append-only attempt history.
    """
    decode(Nonnegative, at_min)
    decode(PhaseState, as_data(failed))
    decode(WorkerState, as_data(worker_state))
    require(failed.completed_min is None, "failed attempt cannot be completed")
    rule = phase_rule(config, failed)
    require(0 < failed.remaining_base_min <= rule.base_min, "invalid failed work remainder")
    require(
        failed.status == "failed" and rule.interruption == "restart",
        "only a failed restart phase gets a new attempt",
    )
    require(at_min >= failed.started_min, "restart before prior start")
    q = next(q for q in config.allocations if q.id == failed.allocation_id)
    require(worker_state.worker_id == q.worker_id, "bound worker mismatch")
    parameters = next(r.worker_parameters for r in config.resources if r.id == q.worker_id)
    timing = sample_phase(rule, parameters, worker_state.fatigue, config.fatigue_cap)
    return replace(
        failed,
        attempt=failed.attempt + 1,
        status="running",
        remaining_base_min=rule.base_min,
        sampled_f=timing.sampled_f,
        speed_multiplier=timing.speed_multiplier,
        started_min=at_min,
        completed_min=None,
    )


def preparation_for(config, binding, *, valid):
    """Service/reassignment begins invalid; preparation completion establishes it.

    Replace the robot's prior record even when the new group uses the same site.
    Last robot work completion or cancellation exit clears it with clear_preparation.
    """
    require(type(valid) is bool, "valid must be bool")
    ctx = Context(config)
    _, transfer, q = ctx.binding(binding.operation_id, binding.group_id, binding.allocation_id)
    require(transfer is None and q.robot_id is not None, "not a robot process binding")
    return Preparation(q.robot_id, binding.operation_id, binding.group_id, q.station_id, valid)


def clear_preparation(robot_id):
    decode(ID, robot_id)
    return Preparation(robot_id, None, None, None, False)


def group_resources(ctx, binding):
    op, transfer, q = ctx.binding(binding.operation_id, binding.group_id, binding.allocation_id)
    ids = {q.worker_id, q.robot_id, q.equipment_id, q.station_id, q.fixture_id, q.crane_id}
    if q.route_id:
        route = ctx.routes[q.route_id]
        ids.add(route.space_id)
        if transfer:
            # The source is no longer required after rig has released it.
            ids.add(route.target_id)
    if op.feed_space_id and transfer is None:
        ids.add(op.feed_space_id)
    return ids - {None}


def _interruption_resources(ctx, binding, snapshot):
    op, transfer, q = ctx.binding(binding.operation_id, binding.group_id, binding.allocation_id)
    if transfer is None:
        ids = group_resources(ctx, binding)
        if not any(
            p.group_id == binding.group_id
            and p.phase_id == "setup"
            and p.status in {"running", "paused"}
            for p in snapshot.phases
        ):
            ids.discard(op.feed_space_id)
        return ids
    route = ctx.routes[q.route_id]
    ids = {q.crane_id, route.space_id}
    for p in snapshot.phases:
        if p.group_id != binding.group_id or p.status not in {"running", "paused"}:
            continue
        if p.phase_id in {"rig", "unload"}:
            ids.add(q.worker_id)
        if p.phase_id in {"preposition", "rig"}:
            ids.add(route.source_id)
        if p.phase_id in {"preposition", "unload"}:
            ids.update((route.target_id, q.fixture_id))
    return ids - {None}


@dataclass(frozen=True)
class Interruption:
    phase_execution_id: str
    cause_event_id: str
    policy: str
    discarded_base_min: float


@dataclass(frozen=True)
class EventResult:
    snapshot: ExecutionSnapshot
    applied_event_ids: tuple[str, ...]
    interruptions: tuple[Interruption, ...]


def apply_events(config, snapshot, events):
    """Apply just this clock's external batch in stable ID order, atomically.

    No phase may remain running with zero work: completion processing precedes
    this call. Replaying the same batch against the same input is deterministic;
    callers consume event IDs once, rather than applying releases twice.
    """
    validate(snapshot, config=config)
    events = tuple(events)
    batch = HiddenScenario("S06-1.1", "hidden_scenario", config.id, config.units, 0, tuple(events))
    validate(batch, config=config)
    require(all(e.sim_time_min == snapshot.sim_time_min for e in events), "wrong event clock")
    require(
        all(p.remaining_base_min > 0 for p in snapshot.phases if p.status == "running"),
        "process completions before external events",
    )
    ctx = Context(config)
    state = snapshot
    interruptions = []
    ordered = sorted(batch.events, key=lambda e: e.id)
    for event in ordered:
        if event.type in {"release", "cancel"}:
            prior = next(o for o in state.orders if o.order_id == event.entity_id)
            if event.type == "release":
                require(not prior.released, "order already released")
                new = replace(prior, released=True)
            else:
                # Cancellation and release can share a time; ID order is normative.
                new = replace(prior, cancelled=True)
            state = replace(state, orders=tuple(new if o == prior else o for o in state.orders))
            continue
        resource = next(r for r in state.resources if r.resource_id == event.entity_id)
        if event.type == "repair":
            require(resource.failed, "repair of healthy resource")
            new = replace(resource, failed=False, release_allowed=None)
            state = replace(
                state, resources=tuple(new if r == resource else r for r in state.resources)
            )
            continue  # repair never starts work or restores robot preparation
        new = replace(resource, failed=True, release_allowed=event.release_allowed)
        affected = {
            b.group_id
            for b in state.bindings
            if event.entity_id in _interruption_resources(ctx, b, state)
        }
        affected.update(
            lock.owner_group_id for lock in state.locks if lock.resource_id == event.entity_id
        )
        phases = []
        stopped = set()
        for p in state.phases:
            if p.group_id in affected and p.status in {"running", "paused"}:
                rule = phase_rule(config, p)
                status = "failed" if rule.interruption == "restart" else "paused"
                if p.status == "running" or status != p.status:
                    interruptions.append(
                        Interruption(
                            phase_execution_id(
                                p.operation_id,
                                p.group_id,
                                p.phase_id,
                                p.attempt,
                                p.restore_sequence,
                            ),
                            event.id,
                            rule.interruption,
                            rule.base_min - p.remaining_base_min if status == "failed" else 0.0,
                        )
                    )
                stopped.add(p.group_id)
                p = replace(p, status=status)
            phases.append(p)
        freed = {
            lock.resource_id
            for lock in state.locks
            if lock.owner_group_id in stopped
            and lock.purpose == "active"
            and ctx.r[lock.resource_id].kind in {"worker", "robot"}
            and lock.resource_id != event.entity_id
            and not next(r.failed for r in state.resources if r.resource_id == lock.resource_id)
        }
        state = replace(
            state,
            resources=tuple(new if r == resource else r for r in state.resources),
            phases=tuple(phases),
            preparations=tuple(
                replace(p, valid=False)
                if p.robot_id == event.entity_id or p.group_id in affected
                else p
                for p in state.preparations
            ),
            locks=tuple(
                lock
                for lock in state.locks
                if not (
                    lock.owner_group_id in stopped
                    and lock.purpose == "active"
                    and lock.resource_id in freed
                )
            ),
            workers=tuple(
                replace(w, activity="wait") if w.worker_id in freed else w for w in state.workers
            ),
        )
    validate(state, config=config)
    return EventResult(state, tuple(e.id for e in ordered), tuple(interruptions))


@dataclass(frozen=True)
class CancellationTail:
    group_id: str
    phase_ids: tuple[str, ...]
    wait_for_repair: bool
    cleanup_required: bool


def cancellation_tail(config, snapshot, group_id):
    """Minimal committed phase sequence before cleanup; never a start permission.

    Cleanup cost/route allocation and actual reservation withdrawal remain S09.
    Failure-locked fixtures block cleanup, and transport cannot bypass failures.
    """
    validate(snapshot, config=config)
    ctx = Context(config)
    require(group_id in ctx.groups, "unknown group")
    op, transfer = ctx.groups[group_id]
    order = next(o for o in snapshot.orders if o.order_id == op.order_id)
    require(order.cancelled, "order is not cancelled")
    binding = next((b for b in snapshot.bindings if b.group_id == group_id), None)
    if binding is None:
        return CancellationTail(group_id, (), False, order.actual_completion_min is None)
    history = [p for p in snapshot.phases if p.group_id == group_id]
    active = [p for p in history if p.status in {"running", "paused"}]
    require(len(active) <= 1, "multiple active phases in one group")
    completed = {p.phase_id for p in history if p.status == "completed"}
    current = active[0] if active else None
    tail = []
    if transfer:
        names = ("preposition", "rig", "move", "unload", "reset")
        if current:
            i = names.index(current.phase_id)
            tail = ["preposition", "reset"] if i == 0 else list(names[i:])
        elif "reset" not in completed:
            if "unload" in completed:
                tail = ["reset"]
            elif "move" in completed:
                tail = ["unload", "reset"]
            elif "rig" in completed:
                tail = ["move", "unload", "reset"]
            elif "preposition" in completed:
                tail = ["reset"]
    elif current:
        tail = [current.phase_id]
        if phase_rule(config, current).cancel_boundary == "handoff_then_clear":
            tail.append("handoff")
    elif "work" in completed and "handoff" not in completed:
        successful = next(p for p in history if p.phase_id == "work" and p.status == "completed")
        if phase_rule(config, successful).cancel_boundary == "handoff_then_clear":
            tail = ["handoff"]
    relevant = (
        group_resources(ctx, binding)
        | _interruption_resources(ctx, binding, snapshot)
        | {lock.resource_id for lock in snapshot.locks if lock.owner_group_id == group_id}
    )
    failures = [r for r in snapshot.resources if r.failed and r.resource_id in relevant]
    blocked = any(
        transfer is not None
        or bool(tail)
        or (
            ctx.r[r.resource_id].kind in {"equipment", "station", "fixture"}
            and r.release_allowed is not True
        )
        for r in failures
    )
    return CancellationTail(group_id, tuple(tail), blocked, order.actual_completion_min is None)


def restore_progress(config, snapshot, group_id, mode_id):
    """Build an inserted restore at its authorized start; no material side effects.

    Resource acquisition and fatigue permission are still the caller's duties.
    An interrupted restore must resume its old record, never allocate another ID.
    """
    validate(snapshot, config=config)
    ctx = Context(config)
    binding = next((b for b in snapshot.bindings if b.group_id == group_id), None)
    require(binding is not None, "restore needs binding")
    op, transfer, q = ctx.binding(binding.operation_id, group_id, binding.allocation_id, mode_id)
    require(transfer is None and q.robot_id is not None, "restore needs robot process")
    require(
        not next(o.cancelled for o in snapshot.orders if o.order_id == op.order_id),
        "cancelled order cannot start restore",
    )
    history = [p for p in snapshot.phases if p.group_id == group_id]
    require(
        not any(
            p.status == "running" or (p.phase_id == "restore" and p.status == "paused")
            for p in history
        ),
        "resume existing work/restore rather than nesting restore",
    )
    mode = ctx.modes[mode_id]
    require(
        any(p.phase_id == mode.preparation_phase_id and p.status == "completed" for p in history),
        "restore requires completed original preparation",
    )
    require(
        not any(p.phase_id == "work" and p.status == "completed" for p in history),
        "robot work already completed",
    )
    require(
        not any(
            r.failed and r.resource_id in group_resources(ctx, binding) for r in snapshot.resources
        ),
        "restore resources failed",
    )
    require(
        not any(
            p.robot_id == q.robot_id and p.group_id == group_id and p.valid
            for p in snapshot.preparations
        ),
        "preparation is already valid",
    )
    rule = resolve_process_phase(config, op.id, mode_id, "restore")
    sequence = 1 + max((p.restore_sequence for p in history), default=0)
    return PhaseState(
        op.id,
        mode_id,
        q.id,
        group_id,
        "restore",
        1,
        sequence,
        "running",
        rule.base_min,
        None,
        1.0,
        snapshot.sim_time_min,
        None,
    )


def withdrawable_reservations(config, snapshot):
    """Return unoccupied reservations releasable at a cancelled safe boundary.

    In-flight/committed transfers retain their destination. Returning a slot
    reservation never releases the enclosing station lock or moves a material.
    """
    validate(snapshot, config=config)
    ctx = Context(config)
    cancelled = {o.order_id for o in snapshot.orders if o.cancelled}
    result = []
    for reservation in snapshot.reservations:
        material = ctx.materials[reservation.material_id]
        if material.order_id not in cancelled:
            continue
        underway = any(
            p.group_id == reservation.owner_group_id
            and p.status in {"running", "paused"}
            and p.phase_id != "reset"
            for p in snapshot.phases
        )
        underway = underway or any(
            m.material_id == reservation.material_id
            and m.location_id == reservation.location_id
            and m.status not in {"consumed", "scrapped"}
            for m in snapshot.materials
        )
        for op in config.operations:
            for transfer in op.transfers:
                if transfer.material_id != material.id:
                    continue
                history = [p for p in snapshot.phases if p.group_id == transfer.id]
                complete = {p.phase_id for p in history if p.status == "completed"}
                if any(
                    p.status in {"running", "paused"} and p.phase_id != "reset" for p in history
                ):
                    underway = True
                if complete.intersection({"rig", "move"}) and "unload" not in complete:
                    underway = True
        if not underway:
            result.append(reservation)
    return tuple(result)


def offline_order_ids(config, scenario):
    """Offline J_eval only. Never call this from a planning consumer."""
    validate(scenario, config=config)
    cancelled = {
        e.entity_id
        for e in scenario.events
        if e.type == "cancel" and e.sim_time_min <= config.observation_window_min
    }
    return tuple(
        sorted(
            o.id
            for o in config.orders
            if o.release_min <= config.observation_window_min and o.id not in cancelled
        )
    )
