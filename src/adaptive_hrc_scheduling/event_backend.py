"""S09 deterministic execution of explicit commands, without a scheduling policy.

The S06 snapshot is a view, not a restart checkpoint. This executor also owns
the event cursor, committed cancellation tails, timers and cleanup records.
"""

import copy
import math
from dataclasses import dataclass, replace
from fractions import Fraction

from .contracts.codec import ContractError, Nonnegative, decode, require
from .contracts.messages import ExecutionEvent, HiddenScenario, WorldEvent, phase_execution_id
from .contracts.validation import Context, compatible_prefix, same_process_identity, validate
from .domain.state import (
    Binding,
    ExecutionSnapshot,
    Lock,
    MaterialPosition,
    OrderState,
    PhaseState,
    Reservation,
    ResourceState,
    WorkerState,
)
from .events import (
    apply_events,
    cancellation_tail,
    clear_preparation,
    phase_rule,
    preparation_for,
    restart_attempt,
    restore_progress,
    source_holding_resources,
    withdrawable_reservations,
)
from .human_state import evolve, process_start_allowed, sample_phase, time_to_cap


@dataclass(frozen=True)
class DispatchResult:
    accepted: bool
    reason: str


@dataclass(frozen=True)
class Cleanup:
    material_id: str
    owner: str
    worker_id: str
    allocation_id: str | None
    source_id: str
    target_id: str
    phase: str
    remaining_min: float
    status: str


@dataclass(frozen=True)
class ExecutionStatus:
    code: str
    reason: str
    next_event_min: float | None


TRANSPORT = ("preposition", "rig", "move", "unload", "reset")


def _key(p):
    return phase_execution_id(p.operation_id, p.group_id, p.phase_id, p.attempt, p.restore_sequence)


class EventBackend:
    """Trusted world-side adapter. Give planners only an authorized observation.

    start/resume commands execute one stage; planned_end is never a completion
    timer. Cleanup expands the explicitly requested material disposal into its
    declared stages. Rejected commands leave all physical state unchanged.
    """

    def __init__(
        self, config, scenario=None, *, run_id="run.execution", cleanup_space_id="SCRAP_RECEIVE"
    ):
        validate(config)
        require(
            all(m.quantity == 1 for m in config.materials if m.kind in {"module", "finished"}),
            "ONE_MODULE_PER_STABLE_MATERIAL_ID_REQUIRED",
        )
        self.config = config
        self.ctx = Context(config)
        self.cleanup_space_id = cleanup_space_id
        require(
            cleanup_space_id in self.ctx.r and self.ctx.r[cleanup_space_id].kind == "space",
            "DECLARED_CLEANUP_SPACE_REQUIRED",
        )
        if scenario is None:
            scenario = HiddenScenario("S06-1.1", "hidden_scenario", config.id, config.units, 0, ())
        validate(scenario, config=config)
        events = list(scenario.events)
        released = {e.entity_id for e in events if e.type == "release"}
        for order in config.orders:
            if order.id not in released:
                events.append(
                    WorldEvent("release." + order.id, order.release_min, "release", order.id, None)
                )
        require(len({e.id for e in events}) == len(events), "duplicate generated event ID")
        self._events = tuple(sorted(events, key=lambda e: (e.sim_time_min, e.id)))
        self._cursor = 0
        self._tails = {}
        self._deadlines = {}
        self._net_windows = {}
        self._rests = {}
        self._cleanups = {}
        self._picked = {}
        self._handoff_targets = {}
        self._commands = set()
        self._log = []
        self._interruptions = []
        self._intervals = []
        self.drained_at_min = None
        self._state = ExecutionSnapshot(
            "S06-1.1",
            "execution_snapshot",
            run_id,
            config.id,
            config.units,
            0.0,
            tuple(
                WorkerState(r.id, r.worker_parameters.initial_f, 0.0, "wait")
                for r in config.resources
                if r.kind == "worker"
            ),
            tuple(clear_preparation(r.id) for r in config.resources if r.kind == "robot"),
            (),
            (),
            (),
            (),
            (),
            tuple(ResourceState(r.id, False, None) for r in config.resources),
            tuple(OrderState(o.id, False, False, None) for o in config.orders),
        )
        validate(self._state, config=config)
        self._at_tick()

    @property
    def snapshot(self):
        return self._state

    @property
    def events(self):
        return tuple(self._log)

    @property
    def activity_intervals(self):
        """Actual worker intervals for a future independent checker, not metrics."""
        return tuple(self._intervals)

    @property
    def interruptions(self):
        return tuple(self._interruptions)

    def completion_time(self, group_id):
        """Current world calendar boundary; not an estimate for a planner."""
        phases = [p for p in self._state.phases if p.group_id == group_id and p.status == "running"]
        require(len(phases) == 1, "NO_SINGLE_RUNNING_PHASE")
        return self._deadlines[_key(phases[0])]

    @property
    def cleanup_records(self):
        return tuple(self._cleanups.values())

    @property
    def picked_materials(self):
        """Feed payloads (material, process group, feed space), outside S06 locations."""
        return tuple((mid, *value) for mid, value in self._picked.items())

    @property
    def now(self):
        return self._state.sim_time_min

    def _set(self, **fields):
        self._state = replace(self._state, **fields)

    def _record(self, kind, entity, old, new, cause, phase=None):
        self._log.append(
            ExecutionEvent(
                "S06-1.1",
                "execution_event",
                self._state.run_id,
                self.config.id,
                f"execution.{len(self._log) + 1}",
                self.config.units,
                self.now,
                kind,
                entity,
                phase,
                old,
                new,
                cause,
            )
        )

    def _order(self, oid):
        return next(o for o in self._state.orders if o.order_id == oid)

    def _worker(self, wid):
        return next(w for w in self._state.workers if w.worker_id == wid)

    def _position(self, mid):
        return next((m for m in self._state.materials if m.material_id == mid), None)

    def _binding(self, gid):
        return next((b for b in self._state.bindings if b.group_id == gid), None)

    def _history(self, gid):
        return [p for p in self._state.phases if p.group_id == gid]

    def _done(self, gid, pid):
        return any(p.phase_id == pid and p.status == "completed" for p in self._history(gid))

    def _put_material(self, mid, loc, status="stored", slot=None):
        item = MaterialPosition(mid, loc, status, slot)
        self._set(
            materials=tuple(m for m in self._state.materials if m.material_id != mid) + (item,)
        )

    def _consume(self, mid):
        item = self._position(mid)
        require(item is not None and item.status == "stored", "MATERIAL_NOT_AVAILABLE")
        self._put_material(mid, item.location_id, "consumed")

    def _lock(self, rid, gid, purpose):
        if rid is None:
            return
        item = Lock(rid, gid, purpose)
        if item not in self._state.locks:
            self._set(locks=self._state.locks + (item,))

    def _unlock(self, gid, *, purpose=None, resources=None):
        self._set(
            locks=tuple(
                x
                for x in self._state.locks
                if not (
                    x.owner_group_id == gid
                    and (purpose is None or x.purpose == purpose)
                    and (resources is None or x.resource_id in resources)
                )
            )
        )

    def _available(self, rid, owner, *, unlock_only=False):
        if rid is None:
            return
        state = next(r for r in self._state.resources if r.resource_id == rid)
        require(
            not state.failed or (unlock_only and state.release_allowed is True), "RESOURCE_FAILED"
        )
        resource = self.ctx.r[rid]
        owners = {x.owner_group_id for x in self._state.locks if x.resource_id == rid} - {owner}
        require(resource.capacity is None or len(owners) < resource.capacity, "RESOURCE_BUSY")
        if resource.kind == "worker":
            require(rid not in self._rests, "WORKER_RESTING")

    def _acquire(self, needs):
        for rid, gid, purpose in needs:
            self._available(rid, gid)
        for rid, gid, purpose in needs:
            self._lock(rid, gid, purpose)

    def _bind(self, op, gid, q, mode_id):
        prior = self._binding(gid)
        if prior and prior.allocation_id != q.id:
            history = self._history(gid)
            require(
                gid == op.process_group_id
                and history
                and all(p.phase_id == "setup" and p.status == "completed" for p in history),
                "BINDING_FROZEN",
            )
            require(same_process_identity(self.ctx.q[prior.allocation_id], q), "BINDING_FROZEN")
            require(
                compatible_prefix(
                    self.ctx, op, self.ctx.modes[history[0].mode_id], self.ctx.modes[mode_id]
                ),
                "MODE_FROZEN",
            )
        b = Binding(op.id, gid, q.id)
        self._set(bindings=tuple(x for x in self._state.bindings if x.group_id != gid) + (b,))
        self.ctx.compatible_bindings({b.group_id: b.allocation_id for b in self._state.bindings})
        return b

    def _material_ready(self, mid):
        pos = self._position(mid)
        require(pos is not None and pos.status == "stored", "MATERIAL_NOT_AVAILABLE")
        require(
            not next(r.failed for r in self._state.resources if r.resource_id == pos.location_id),
            "MATERIAL_LOCATION_FAILED",
        )
        material = self.ctx.materials[mid]
        if material.producer_id:
            op = self.ctx.ops[material.producer_id]
            require(self._done(op.process_group_id, material.available_at), "PREDECESSOR_PENDING")
        return pos

    def _buffer(self, material):
        for rid in material.storage_ids:
            r = self.ctx.r[rid]
            if r.kind != "buffer" or next(
                s.failed for s in self._state.resources if s.resource_id == rid
            ):
                continue
            count = sum(
                self.ctx.materials[m.material_id].quantity
                for m in self._state.materials
                if m.location_id == rid and m.status == "stored"
            )
            count += sum(
                self.ctx.materials[m.material_id].quantity
                for m in self._state.reservations
                if m.location_id == rid
            )
            if count + material.quantity <= r.capacity:
                return rid
        raise ContractError("BUFFER_FULL")

    def _scrap(self):
        return next(
            r.id
            for r in self.config.resources
            if r.kind == "terminal" and "scrap" in r.accepted_materials
        )

    def _reserve_target(self, op, transfer, q):
        route = self.ctx.routes[q.route_id]
        if self.ctx.r[route.target_id].kind == "terminal":
            return
        require(op.process_group_id is not None, "TARGET_PROCESS_REQUIRED")
        b = self._binding(op.process_group_id)
        # The process allocation must be explicitly selected before transport.
        require(b is not None, "TARGET_BINDING_REQUIRED")
        target_q = self.ctx.q[b.allocation_id]
        require(target_q.station_id == route.target_id, "TARGET_MISMATCH")
        owner = op.process_group_id
        self._acquire([(route.target_id, owner, "held"), (target_q.fixture_id, owner, "held")])
        groups = op.transfers if transfer.reserve_all_receiving_slots else (transfer,)
        for i, group in enumerate(groups):
            if (
                self._position(group.material_id)
                and self._position(group.material_id).location_id == route.target_id
            ):
                continue
            existing = next(
                (r for r in self._state.reservations if r.material_id == group.material_id), None
            )
            if existing:
                require(existing.location_id == route.target_id, "RESERVATION_MISMATCH")
                continue
            slot = i if transfer.reserve_all_receiving_slots else None
            self._set(
                reservations=self._state.reservations
                + (Reservation(group.material_id, route.target_id, owner, slot),)
            )

    def select_process(self, operation_id, mode_id, allocation_id):
        """Bind a receiving process before its first incoming transport, no locks.

        Needed because S06 transport commands do not carry the receiving P/Q.
        This is an explicit world-side selection, not automatic scheduling.
        """
        trial = copy.deepcopy(self)
        op = trial.ctx.ops[operation_id]
        require(
            trial._order(op.order_id).released and not trial._order(op.order_id).cancelled,
            "ORDER_UNAVAILABLE",
        )
        _, transfer, q = trial.ctx.binding(op.id, op.process_group_id, allocation_id, mode_id)
        require(transfer is None, "PROCESS_REQUIRED")
        trial._bind(op, op.process_group_id, q, mode_id)
        validate(trial._state, config=trial.config)
        self.__dict__.update(trial.__dict__)

    def dispatch(self, command):
        """Validate and commit the whole immediate command, or reject atomically."""
        validate(command, config=self.config)
        require(
            command.run_id == self._state.run_id and command.issued_min == self.now,
            "COMMAND_CLOCK_OR_RUN",
        )
        require(command.id not in self._commands, "DUPLICATE_COMMAND")
        trial = copy.deepcopy(self)
        try:
            if command.action in {"start", "resume"}:
                trial._start(command.assignment, command.action)
            elif command.action == "rest":
                trial._rest(command.worker_id, command.duration_min, "REQUESTED_REST")
            elif command.action == "cleanup":
                trial._cleanup_request(command.cleanup_material_id)
            else:
                require(
                    math.isfinite(self.now + command.duration_min)
                    and self.now + command.duration_min > self.now,
                    "UNREPRESENTABLE_TIME",
                )
            trial._sync_activities()
            validate(trial._state, config=trial.config)
        except ContractError as error:
            self._commands.add(command.id)
            reason = str(error)
            self._record(
                "rejected",
                command.id,
                "requested",
                "rejected",
                "FATIGUE_PROTECTION" if "FATIGUE" in reason else "EXECUTION_PRECONDITION",
            )
            return DispatchResult(False, reason)
        trial._commands.add(command.id)
        self.__dict__.update(trial.__dict__)
        if command.action == "wait":
            self.advance(self.now + command.duration_min)
        return DispatchResult(True, "ACCEPTED")

    def _start(self, a, action):
        op, transfer, q = self.ctx.binding(a.operation_id, a.group_id, a.allocation_id, a.mode_id)
        require(self._order(op.order_id).released, "ORDER_NOT_RELEASED")
        require(
            not any(
                c.owner == a.group_id and c.status != "completed" for c in self._cleanups.values()
            ),
            "CLEANUP_ACTIVE",
        )
        cancelled = self._order(op.order_id).cancelled
        if cancelled:
            tail = self._tails.get(a.group_id)
            require(
                tail is not None and tail.phase_ids and a.phase_id == tail.phase_ids[0],
                "CANCELLED_SUFFIX",
            )
        b = self._bind(op, a.group_id, q, a.mode_id)
        history = self._history(a.group_id)
        same = [
            p
            for p in history
            if p.phase_id == a.phase_id and p.restore_sequence == a.restore_sequence
        ]
        prior = same[-1] if same else None
        require(not any(p.status == "running" for p in history), "GROUP_RUNNING")
        require(
            not any(
                p.status == "paused"
                and p != prior
                and not (a.phase_id == "restore" and p.phase_id == "work")
                for p in history
            ),
            "RESUME_REQUIRED",
        )
        if prior:
            require(prior.status in {"paused", "failed"}, "PHASE_ALREADY_EXECUTED")
            require(prior.mode_id == a.mode_id and prior.allocation_id == q.id, "RESUME_IDENTITY")
            if prior.status == "paused":
                require(action == "resume" and a.attempt == prior.attempt, "RESUME_REQUIRED")
                p = replace(prior, status="running")
            else:
                require(
                    action == "start" and not cancelled and a.attempt == prior.attempt + 1,
                    "RESTART_REQUIRED",
                )
                p = restart_attempt(self.config, prior, self._worker(q.worker_id), self.now)
        elif a.phase_id == "restore":
            require(action == "start", "START_REQUIRED")
            p = restore_progress(self.config, self._state, a.group_id, a.mode_id)
            require(p.restore_sequence == a.restore_sequence, "RESTORE_SEQUENCE")
        else:
            require(action == "start" and a.attempt == 1, "FIRST_ATTEMPT_REQUIRED")
            p = PhaseState(
                op.id,
                a.mode_id,
                q.id,
                a.group_id,
                a.phase_id,
                1,
                0,
                "running",
                1.0,
                None,
                1.0,
                self.now,
                None,
            )
            rule = phase_rule(self.config, p)
            timing = sample_phase(
                rule,
                self.ctx.r[q.worker_id].worker_parameters,
                self._worker(q.worker_id).fatigue,
                self.config.fatigue_cap,
            )
            p = replace(
                p,
                remaining_base_min=rule.base_min,
                sampled_f=timing.sampled_f,
                speed_multiplier=timing.speed_multiplier,
            )
        rule = phase_rule(self.config, p)
        # A retained output reservation/feed token can be the failed resource
        # even though it is not named by the static phase's active roles.
        for lock in self._state.locks:
            if lock.owner_group_id == a.group_id:
                self._available(lock.resource_id, a.group_id)
        if not prior and a.phase_id != "restore":
            predecessors = rule.predecessors
            if cancelled and transfer and a.phase_id == "reset":
                predecessors = ("preposition",)
            require(all(self._done(a.group_id, pid) for pid in predecessors), "PHASE_PREDECESSOR")
        if transfer:
            self._start_transfer(op, transfer, q, p, prior)
        else:
            if rule.requires_preparation:
                require(
                    any(
                        x.robot_id == q.robot_id and x.group_id == b.group_id and x.valid
                        for x in self._state.preparations
                    ),
                    "RESTORE_REQUIRED",
                )
            protection = process_start_allowed(
                self.config,
                op.id,
                a.mode_id,
                a.phase_id,
                self._worker(q.worker_id),
                progress=p if prior and prior.status == "paused" else None,
            )
            require(protection.allowed, protection.reason)
            mode = self.ctx.modes[a.mode_id]
            needs = [(getattr(q, r + "_id"), a.group_id, "held") for r in mode.held_roles]
            needs += [(getattr(q, r + "_id"), a.group_id, "active") for r in rule.active_roles]
            if a.phase_id == "setup" and op.feed_space_id:
                needs.append((op.feed_space_id, a.group_id, "active"))
            self._acquire(needs)
            if not history:
                for group in op.transfers:
                    require(
                        self._done(group.id, "reset" if group.wait_for_reset else "unload"),
                        "INBOUND_PENDING",
                    )
                for mid in op.input_ids:
                    pos = self._material_ready(mid)
                    if self.ctx.materials[mid].kind == "module":
                        require(pos.location_id == q.station_id, "INPUT_LOCATION")
                # S06 has no human/feed location. Keep the physical payload in
                # explicit executor records until setup consumes it at completion.
                for mid in op.input_ids:
                    if self.ctx.materials[mid].kind in {"pipe", "bracket"}:
                        self._picked[mid] = (a.group_id, op.feed_space_id, self._position(mid))
                        self._set(
                            materials=tuple(
                                m for m in self._state.materials if m.material_id != mid
                            )
                        )
                    else:
                        self._put_material(mid, q.station_id)
            if a.phase_id == "handoff" and op.kind in {"CUT", "BRACKET"} and not prior:
                target = (
                    self._scrap() if cancelled else self._buffer(self.ctx.materials[op.output_id])
                )
                self._handoff_targets[a.group_id] = target
                if not cancelled:
                    self._lock(target, a.group_id, "reserved")
                    self._set(
                        reservations=self._state.reservations
                        + (Reservation(op.output_id, target, a.group_id, None),)
                    )
                else:
                    self._acquire(
                        [
                            (target, a.group_id, "active"),
                            (self.cleanup_space_id, a.group_id, "active"),
                        ]
                    )
            if q.robot_id and "robot" in rule.active_roles and not rule.requires_preparation:
                self._set(
                    preparations=tuple(
                        preparation_for(self.config, b, valid=False)
                        if x.robot_id == q.robot_id
                        else x
                        for x in self._state.preparations
                    )
                )
        if prior and prior.status == "paused":
            phases = tuple(p if x == prior else x for x in self._state.phases)
        else:
            phases = self._state.phases + (p,)
        self._set(phases=phases)
        self._timer(
            _key(p), p.remaining_base_min * p.speed_multiplier, net_amount=p.remaining_base_min
        )
        self._record("started", op.id, "ready", "running", "DISPATCH", _key(p))

    def _timer(self, key, duration, *, net_amount=None):
        end = self.now + duration
        require(math.isfinite(end) and end > self.now, "UNREPRESENTABLE_TIME")
        self._deadlines[key] = end
        self._net_windows[key] = (self.now, end, duration if net_amount is None else net_amount)

    def _remaining_at(self, key, at):
        """Project the original net amount onto the representable calendar interval.

        Exact ratios avoid accumulating partition-dependent subtraction error.
        Only the stored deadline completes work; no epsilon or early clipping.
        A resume creates a new interval from its preserved remaining net amount.
        """
        start, end, amount = self._net_windows[key]
        require(start <= at <= end, "CLOCK_OUTSIDE_NET_WINDOW")
        if at == end:
            return 0.0
        remaining = float(
            Fraction(amount) * (Fraction(end) - Fraction(at)) / (Fraction(end) - Fraction(start))
        )
        require(remaining > 0, "UNREPRESENTABLE_REMAINING_WORK")
        return remaining

    def _require_source_release(self, source_id):
        held = source_holding_resources(self.ctx, self._state, source_id)
        for state in self._state.resources:
            if state.resource_id in held:
                require(
                    not state.failed or state.release_allowed is True,
                    "SOURCE_HOLD_RELEASE_FORBIDDEN",
                )

    def _start_transfer(self, op, transfer, q, p, prior):
        route = self.ctx.routes[q.route_id]
        gid = p.group_id
        if p.phase_id == "preposition" and prior is None:
            pos = self._material_ready(transfer.material_id)
            require(pos.location_id == route.source_id, "SOURCE_MISMATCH")
            require(
                not any(
                    x.material_id == transfer.material_id and x.status != "completed"
                    for x in self._cleanups.values()
                ),
                "MATERIAL_IN_CLEANUP",
            )
            self._reserve_target(op, transfer, q)
        needs = [(q.crane_id, gid, "held"), (route.space_id, gid, "held")]
        if p.phase_id in {"preposition", "rig"}:
            state = next(r for r in self._state.resources if r.resource_id == route.source_id)
            require(not state.failed, "SOURCE_FAILED")
            self._require_source_release(route.source_id)
        if p.phase_id in {"preposition", "unload"}:
            target_owner = op.process_group_id or gid
            self._available(route.target_id, target_owner)
            self._available(q.fixture_id, target_owner)
        if p.phase_id in {"rig", "unload"}:
            needs.append((q.worker_id, gid, "active"))
        self._acquire(needs)
        # Include rig -> move(wait) -> unload, protecting required release labor.
        names = TRANSPORT[TRANSPORT.index(p.phase_id) :]
        if p.phase_id == "preposition":
            names = ("preposition",)
        state = self._worker(q.worker_id)
        for name in names:
            duration = p.remaining_base_min if name == p.phase_id else getattr(route, name + "_min")
            state = evolve(
                state,
                self.ctx.r[q.worker_id].worker_parameters,
                "carry" if name in {"rig", "unload"} else "wait",
                duration,
                self.config.fatigue_cap,
            ).state

    def _release_source(self, location):
        if any(
            m.location_id == location and m.status not in {"consumed", "scrapped", "finished"}
            for m in self._state.materials
        ):
            return
        if any(r.location_id == location for r in self._state.reservations):
            return
        ids = {location} | {r.id for r in self.config.resources if r.station_id == location}
        self._set(locks=tuple(x for x in self._state.locks if x.resource_id not in ids))

    def _complete(self, p):
        op, transfer, q = self.ctx.binding(p.operation_id, p.group_id, p.allocation_id, p.mode_id)
        gid = p.group_id
        self._unlock(gid, purpose="active")
        if transfer:
            route = self.ctx.routes[q.route_id]
            mid = transfer.material_id
            if p.phase_id == "rig":
                self._require_source_release(route.source_id)
                self._put_material(mid, q.crane_id, "in_transit")
                self._release_source(route.source_id)
            elif p.phase_id == "unload":
                reserved = next((r for r in self._state.reservations if r.material_id == mid), None)
                self._set(
                    reservations=tuple(r for r in self._state.reservations if r.material_id != mid)
                )
                if op.kind == "LIFT":
                    self._put_material(mid, route.target_id, "consumed")
                    self._put_material(op.output_id, route.target_id, "finished")
                    order = self.ctx.orders[op.order_id]
                    if all(
                        self._position(x) and self._position(x).status == "finished"
                        for x in order.required_finished_ids
                    ):
                        self._set(
                            orders=tuple(
                                replace(o, actual_completion_min=self.now)
                                if o.order_id == op.order_id
                                else o
                                for o in self._state.orders
                            )
                        )
                        self._record(
                            "arrived", op.order_id, "incomplete", "finished", "FINAL_UNLOAD"
                        )
                else:
                    self._put_material(
                        mid, route.target_id, slot=reserved.slot if reserved else None
                    )
            elif p.phase_id == "reset":
                self._unlock(gid)
        else:
            rule = phase_rule(self.config, p)
            if op.kind == "ASSEMBLE" and p.phase_id == "setup":
                for mid in op.input_ids:
                    if mid in self._picked:
                        _, _, original = self._picked.pop(mid)
                        self._put_material(mid, original.location_id, "consumed")
                    else:
                        self._consume(mid)
                self._put_material(op.output_id, q.station_id)
            if rule.establishes_preparation:
                b = self._binding(gid)
                self._set(
                    preparations=tuple(
                        preparation_for(self.config, b, valid=True)
                        if x.robot_id == q.robot_id
                        else x
                        for x in self._state.preparations
                    )
                )
            if p.phase_id == "work" and q.robot_id:
                self._set(
                    preparations=tuple(
                        clear_preparation(x.robot_id) if x.robot_id == q.robot_id else x
                        for x in self._state.preparations
                    )
                )
            if p.phase_id == "handoff" or (op.kind == "INSPECT" and p.phase_id == "work"):
                for mid in op.input_ids:
                    pos = self._position(mid)
                    if pos and pos.status == "stored":
                        self._consume(mid)
                if op.kind in {"CUT", "BRACKET"}:
                    target = self._handoff_targets[gid]
                    self._set(
                        reservations=tuple(
                            r for r in self._state.reservations if r.material_id != op.output_id
                        )
                    )
                    self._put_material(
                        op.output_id, target, "scrapped" if target == self._scrap() else "stored"
                    )
                    self._unlock(gid)
                else:
                    self._put_material(op.output_id, q.station_id)
                    self._unlock(gid, resources={q.equipment_id})
        self._record("completed", op.id, "running", "completed", "NET_WORK", _key(p))

    def _rest(self, wid, duration, cause):
        require(wid not in self._rests, "ALREADY_RESTING")
        active_groups = {p.group_id for p in self._state.phases if p.status == "running"}
        active_groups.update(c.owner for c in self._cleanups.values() if c.status == "running")
        self._set(
            locks=tuple(
                x
                for x in self._state.locks
                if not (
                    x.resource_id == wid
                    and x.purpose == "active"
                    and x.owner_group_id not in active_groups
                )
            )
        )
        require(not any(x.resource_id == wid for x in self._state.locks), "WORKER_BUSY")
        require(
            duration >= self.config.protective_rest_min
            if cause == "FATIGUE_PROTECTION"
            else duration > 0,
            "REST_DURATION",
        )
        end = self.now + duration
        require(end > self.now and math.isfinite(end), "UNREPRESENTABLE_TIME")
        self._rests[wid] = end
        self._record("started", wid, "wait", "rest", cause)

    def _sync_activities(self):
        activities = {
            w.worker_id: "rest" if w.worker_id in self._rests else "wait"
            for w in self._state.workers
        }
        for p in self._state.phases:
            if p.status == "running":
                rule = phase_rule(self.config, p)
                if rule.activity:
                    activities[self.ctx.q[p.allocation_id].worker_id] = rule.activity
        for c in self._cleanups.values():
            if c.status == "running" and c.phase in {"carry", "rig", "unload"}:
                activities[c.worker_id] = "carry"
        self._set(
            workers=tuple(replace(w, activity=activities[w.worker_id]) for w in self._state.workers)
        )

    def _refresh_cancellation(self):
        for gid, (op, _) in self.ctx.groups.items():
            if self._order(op.order_id).cancelled:
                self._tails[gid] = cancellation_tail(
                    self.config, self._state, gid, committed_tail=self._tails.get(gid)
                )
        withdrawn = withdrawable_reservations(self.config, self._state)
        self._set(reservations=tuple(r for r in self._state.reservations if r not in withdrawn))
        for r in withdrawn:
            if self.ctx.r[r.location_id].kind == "buffer":
                self._unlock(r.owner_group_id, purpose="reserved", resources={r.location_id})
            self._release_source(r.location_id)
        for prep in self._state.preparations:
            if prep.group_id in self._tails and not self._tails[prep.group_id].phase_ids:
                self._set(
                    preparations=tuple(
                        clear_preparation(x.robot_id) if x.robot_id == prep.robot_id else x
                        for x in self._state.preparations
                    )
                )

    def _at_tick(self):
        batch = []
        while (
            self._cursor < len(self._events) and self._events[self._cursor].sim_time_min == self.now
        ):
            batch.append(self._events[self._cursor])
            self._cursor += 1
        if batch:
            result = apply_events(self.config, self._state, batch)
            self._state = result.snapshot
            self._interruptions.extend(result.interruptions)
            for p in self._state.phases:
                if p.status != "running":
                    self._deadlines.pop(_key(p), None)
                    self._net_windows.pop(_key(p), None)
            for e in batch:
                if e.type == "release":
                    for m in self.config.materials:
                        if m.order_id == e.entity_id and m.producer_id is None:
                            self._put_material(m.id, m.storage_ids[0])
                self._record(
                    {
                        "release": "released",
                        "cancel": "cancelled",
                        "failure": "interrupted",
                        "repair": "restored",
                    }[e.type],
                    e.entity_id,
                    "before",
                    "after",
                    e.id,
                )
            self._interrupt_cleanup()
            # S08 retains the failed active token. Once the resource repairs,
            # a stopped stage no longer needs an active worker/robot occupancy.
            running_groups = {p.group_id for p in self._state.phases if p.status == "running"}
            failed_ids = {r.resource_id for r in self._state.resources if r.failed}
            self._set(
                locks=tuple(
                    x
                    for x in self._state.locks
                    if not (
                        x.purpose == "active"
                        and x.owner_group_id not in running_groups
                        and self.ctx.r[x.resource_id].kind in {"worker", "robot"}
                        and x.resource_id not in failed_ids
                        and not any(
                            c.owner == x.owner_group_id and c.status == "running"
                            for c in self._cleanups.values()
                        )
                    )
                )
            )
        self._refresh_cancellation()
        for wid, end in tuple(self._rests.items()):
            if end <= self.now:
                del self._rests[wid]
                self._record("completed", wid, "rest", "wait", "REST_TIMER")
        self._sync_activities()
        for w in self._state.workers:
            if w.activity == "wait":
                horizon = time_to_cap(
                    w.fatigue,
                    self.ctx.r[w.worker_id].worker_parameters,
                    "wait",
                    self.config.fatigue_cap,
                )
                if self.now + horizon <= self.now:
                    self._rest(w.worker_id, self.config.protective_rest_min, "FATIGUE_PROTECTION")
        self._retry_cleanup()
        self._sync_activities()
        if self._drained() and self.drained_at_min is None:
            self.drained_at_min = self.now
            for w in self._state.workers:
                self._rests[w.worker_id] = math.inf
            self._sync_activities()
        validate(self._state, config=self.config)

    def _next(self, until):
        times = [until, *self._deadlines.values(), *self._rests.values()]
        if self._cursor < len(self._events):
            times.append(self._events[self._cursor].sim_time_min)
        for w in self._state.workers:
            if w.activity == "wait":
                horizon = time_to_cap(
                    w.fatigue,
                    self.ctx.r[w.worker_id].worker_parameters,
                    "wait",
                    self.config.fatigue_cap,
                )
                at = self.now + horizon
                # A rounded addition must not lengthen a strict S07 cap horizon.
                if at - self.now > horizon:
                    at = math.nextafter(at, self.now)
                times.append(at)
        return min(times)

    def advance(self, until_min):
        """Advance across calendar boundaries; never start normal production."""
        trial = copy.deepcopy(self)
        trial._advance(until_min)
        self.__dict__.update(trial.__dict__)
        return self._state

    def _advance(self, until_min):
        until = decode(Nonnegative, until_min)
        require(until >= self.now, "CLOCK_REWIND")
        while self.now < until:
            self._at_tick()
            at = self._next(until)
            if at <= self.now:
                # No representable safe waiting step remains: begin positive rest.
                for w in self._state.workers:
                    if w.activity == "wait":
                        horizon = time_to_cap(
                            w.fatigue,
                            self.ctx.r[w.worker_id].worker_parameters,
                            "wait",
                            self.config.fatigue_cap,
                        )
                        if math.nextafter(self.now, math.inf) - self.now > horizon:
                            self._rest(
                                w.worker_id, self.config.protective_rest_min, "FATIGUE_PROTECTION"
                            )
                self._sync_activities()
                require(self._next(until) > self.now, "NO_REPRESENTABLE_PROGRESS")
                continue
            dt = at - self.now
            workers = []
            for w in self._state.workers:
                evolved = evolve(
                    w,
                    self.ctx.r[w.worker_id].worker_parameters,
                    w.activity,
                    dt,
                    self.config.fatigue_cap,
                )
                workers.append(evolved.state)
            phases, completed = [], []
            for p in self._state.phases:
                if p.status == "running":
                    done = self._deadlines[_key(p)] == at
                    p = replace(
                        p,
                        remaining_base_min=self._remaining_at(_key(p), at),
                        status="completed" if done else "running",
                        completed_min=at if done else None,
                    )
                    if p.status == "completed":
                        completed.append(p)
                phases.append(p)
            for w in self._state.workers:
                self._intervals.append((w.worker_id, self.now, at, w.activity))
            self._set(sim_time_min=at, workers=tuple(workers), phases=tuple(phases))
            for p in sorted(completed, key=_key):
                self._deadlines.pop(_key(p), None)
                self._net_windows.pop(_key(p), None)
                self._complete(p)
            for mid, c in tuple(self._cleanups.items()):
                if c.status == "running":
                    key = "cleanup." + mid
                    if self._deadlines[key] == at:
                        self._deadlines.pop(key)
                        self._net_windows.pop(key)
                        self._cleanup_complete(c)
                    else:
                        self._cleanups[mid] = replace(c, remaining_min=self._remaining_at(key, at))
            self._at_tick()
        return self._state

    def _drained(self):
        if any(not o.released for o in self._state.orders):
            return False
        if any(p.status == "running" for p in self._state.phases):
            return False
        if any(c.status != "completed" for c in self._cleanups.values()):
            return False
        if self._state.reservations or self._state.locks or self._picked:
            return False
        for o in self._state.orders:
            if not o.cancelled and o.actual_completion_min is None:
                return False
            if o.cancelled and any(
                m.status not in {"consumed", "scrapped", "finished"}
                and self.ctx.materials[m.material_id].order_id == o.order_id
                for m in self._state.materials
            ):
                return False
        return True

    def status(self):
        if self._drained():
            return ExecutionStatus("DRAINED", "ALL_PRODUCTION_CLEANUP_AND_RESET_COMPLETE", None)
        next_at = self._next(math.inf)
        if any(p.status == "running" for p in self._state.phases) or any(
            c.status == "running" for c in self._cleanups.values()
        ):
            return ExecutionStatus("RUNNING", "CALENDAR_WORK", next_at)
        if any(r.failed for r in self._state.resources):
            return ExecutionStatus("WAITING", "REPAIR_OR_OTHER_LEGAL_COMMAND_REQUIRED", next_at)
        return ExecutionStatus(
            "WAITING", "EXPLICIT_DISPATCH_OR_CLEANUP_REQUIRED_NO_POLICY_SEARCH", next_at
        )

    def _cleanup_request(self, mid):
        require(mid not in self._cleanups, "CLEANUP_ALREADY_REQUESTED")
        material = self.ctx.materials[mid]
        require(self._order(material.order_id).cancelled, "CLEANUP_REQUIRES_CANCELLATION")
        pos = self._position(mid)
        require(pos is not None and pos.status == "stored", "CLEANUP_MATERIAL_UNAVAILABLE")
        # Every group touching this entity must have reached its committed boundary.
        related = [
            gid
            for gid, (op, t) in self.ctx.groups.items()
            if (t and t.material_id == mid) or (not t and mid in (*op.input_ids, op.output_id))
        ]
        require(
            all(
                not self._tails[g].phase_ids and not self._tails[g].wait_for_repair for g in related
            ),
            "CLEANUP_BOUNDARY_PENDING",
        )
        op = self.ctx.ops[material.producer_id or material.consumer_id]
        gid = op.process_group_id or op.transfers[0].id
        require(
            not any(c.owner == gid and c.status != "completed" for c in self._cleanups.values()),
            "CLEANUP_OWNER_BUSY",
        )
        if self._binding(gid) is None:
            qid = self.ctx.modes[op.mode_ids[0]].allocation_ids[0]
            self._bind(op, gid, self.ctx.q[qid], op.mode_ids[0])
        target = self._scrap()
        if material.kind == "module":
            choices = sorted(
                (
                    q
                    for q in self.config.allocations
                    if q.skill == "TRANSFER"
                    and q.route_id
                    and self.ctx.routes[q.route_id].source_id == pos.location_id
                    and self.ctx.routes[q.route_id].target_id == target
                ),
                key=lambda q: q.id,
            )
            require(choices, "NO_DECLARED_CLEANUP_ROUTE")
            q = choices[0]
            c = Cleanup(
                mid,
                gid,
                q.worker_id,
                q.id,
                pos.location_id,
                target,
                "preposition",
                self.ctx.routes[q.route_id].preposition_min,
                "pending",
            )
        else:
            workers = sorted(
                r.id for r in self.config.resources if r.kind == "worker" and "TRANSFER" in r.skills
            )
            require(workers, "NO_CLEANUP_WORKER")
            c = Cleanup(
                mid,
                gid,
                workers[0],
                None,
                pos.location_id,
                target,
                "carry",
                self.config.cleanup_piece_min * material.quantity,
                "pending",
            )
        self._cleanups[mid] = c
        # Request acceptance does not assert resources are currently available.
        self._retry_cleanup()

    def _cleanup_needs(self, c):
        ids = {c.target_id, self.cleanup_space_id} if c.phase != "reset" else set()
        if c.allocation_id:
            q = self.ctx.q[c.allocation_id]
            ids.update((q.crane_id, self.ctx.routes[q.route_id].space_id))
        if c.phase in {"carry", "rig", "unload"}:
            ids.add(c.worker_id)
        return ids

    def _retry_cleanup(self):
        for mid in sorted(self._cleanups):
            c = self._cleanups[mid]
            if c.status not in {"pending", "paused"}:
                continue
            trial = copy.deepcopy(self)
            try:
                for rid in trial._cleanup_needs(c):
                    trial._available(rid, c.owner)
                if c.phase in {"carry", "preposition", "rig"}:
                    source_ids = {c.source_id} | {
                        r.id for r in trial.config.resources if r.station_id == c.source_id
                    }
                    for rid in source_ids:
                        state = next(x for x in trial._state.resources if x.resource_id == rid)
                        require(
                            not state.failed or state.release_allowed is True,
                            "CLEANUP_SOURCE_LOCKED",
                        )
                state = trial._worker(c.worker_id)
                names = ("carry",) if c.phase == "carry" else TRANSPORT[TRANSPORT.index(c.phase) :]
                if c.phase == "preposition":
                    names = ("preposition",)
                for name in names:
                    duration = (
                        c.remaining_min
                        if name == c.phase
                        else getattr(
                            trial.ctx.routes[trial.ctx.q[c.allocation_id].route_id], name + "_min"
                        )
                    )
                    state = evolve(
                        state,
                        trial.ctx.r[c.worker_id].worker_parameters,
                        "carry" if name in {"carry", "rig", "unload"} else "wait",
                        duration,
                        trial.config.fatigue_cap,
                    ).state
                for rid in trial._cleanup_needs(c):
                    trial._lock(rid, c.owner, "active" if rid == c.worker_id else "held")
                trial._cleanups[mid] = replace(c, status="running")
                trial._timer("cleanup." + mid, c.remaining_min)
                trial._record("started", mid, "pending", "running", "CLEANUP_" + c.phase.upper())
                validate(trial._state, config=trial.config)
            except ContractError:
                continue
            self.__dict__.update(trial.__dict__)

    def _interrupt_cleanup(self):
        failed = {r.resource_id for r in self._state.resources if r.failed}
        for mid, c in tuple(self._cleanups.items()):
            required = self._cleanup_needs(c)
            if c.phase in {"carry", "preposition", "rig"}:
                required.update(
                    {c.source_id}
                    | {r.id for r in self.config.resources if r.station_id == c.source_id}
                )
            if c.status == "running" and required & failed:
                self._cleanups[mid] = replace(c, status="paused")
                self._deadlines.pop("cleanup." + mid, None)
                self._net_windows.pop("cleanup." + mid, None)
                self._unlock(c.owner, resources={c.worker_id})
                self._record("interrupted", mid, "running", "paused", "CLEANUP_FAILURE")

    def _cleanup_complete(self, c):
        self._unlock(c.owner, resources={c.worker_id})
        if c.phase == "carry":
            self._put_material(c.material_id, c.target_id, "scrapped")
            self._release_source(c.source_id)
            self._unlock(c.owner)
            self._cleanups[c.material_id] = replace(c, remaining_min=0.0, status="completed")
        else:
            q = self.ctx.q[c.allocation_id]
            route = self.ctx.routes[q.route_id]
            if c.phase == "rig":
                self._put_material(c.material_id, q.crane_id, "in_transit")
                self._release_source(c.source_id)
            elif c.phase == "unload":
                self._put_material(c.material_id, c.target_id, "scrapped")
                self._unlock(c.owner, resources={c.target_id, self.cleanup_space_id})
            if c.phase == "reset":
                self._unlock(c.owner)
                self._cleanups[c.material_id] = replace(c, remaining_min=0.0, status="completed")
            else:
                name = TRANSPORT[TRANSPORT.index(c.phase) + 1]
                self._cleanups[c.material_id] = replace(
                    c, phase=name, remaining_min=getattr(route, name + "_min"), status="pending"
                )
        self._record(
            "completed", c.material_id, "running", "completed", "CLEANUP_" + c.phase.upper()
        )
