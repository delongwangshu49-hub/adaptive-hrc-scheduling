"""S06 static acceptance checks. No time advancement or scheduling is performed."""

import hashlib
import re
from itertools import combinations

from ..domain.models import Configuration
from ..domain.phases import resolve_process_phase
from ..domain.state import ExecutionSnapshot
from .codec import ContractError, as_data, decode, dumps, require
from .messages import (
    DispatchCommand,
    ExecutionEvent,
    HiddenScenario,
    OfflineEvaluation,
    Plan,
    PlanningInput,
    PlanningObservation,
    RunManifest,
)

LEGAL = {
    "CUT": {"H", "R"},
    "BRACKET": {"H"},
    "ASSEMBLE": {"H", "HR"},
    "WELD": {"R", "HR"},
    "INSPECT": {"H"},
    "LIFT": {"H"},
}


def unique(values, label):
    require(len(values) == len(set(values)), f"duplicate {label}")


def index(records, key="id"):
    values = [getattr(x, key) for x in records]
    unique(values, key)
    return dict(zip(values, records, strict=True))


def dag(edges):
    pending = {key: set(value) for key, value in edges.items()}
    for key, value in edges.items():
        unique(value, "predecessor")
        require(set(value) <= edges.keys(), f"{key}: unknown predecessor")
    while pending:
        roots = {key for key, value in pending.items() if not value}
        require(bool(roots), "cyclic dependency")
        pending = {key: value - roots for key, value in pending.items() if key not in roots}


def distinct_sources(options):
    """Bipartite matching, without enumerating all source combinations."""
    matched = {}

    def augment(item, visited):
        for source in sorted(options[item]):
            if source not in visited:
                visited.add(source)
                if source not in matched or augment(matched[source], visited):
                    matched[source] = item
                    return True
        return False

    return all(augment(item, set()) for item in range(len(options)))


def compatible_prefix(ctx, op, left, right):
    """Compare effective setup semantics, including operation overrides."""
    return (
        op.kind in {"ASSEMBLE", "WELD"}
        and left.switch_after == right.switch_after == "setup"
        and set(left.held_roles) == set(right.held_roles)
        and resolve_process_phase(ctx.c, op.id, left.id, "setup")
        == resolve_process_phase(ctx.c, op.id, right.id, "setup")
    )


def same_process_identity(left, right):
    return all(
        getattr(left, key) == getattr(right, key)
        for key in ("worker_id", "equipment_id", "station_id", "fixture_id")
    ) and (left.robot_id is None or right.robot_id is None or left.robot_id == right.robot_id)


class Context:
    def __init__(self, config):
        self.c = config
        self.r = index(config.resources)
        self.routes = index(config.routes)
        self.q = index(config.allocations)
        self.modes = index(config.modes)
        self.orders = index(config.orders)
        self.ops = index(config.operations)
        self.materials = index(config.materials)
        self.groups = {}
        for op in config.operations:
            if op.process_group_id:
                require(op.process_group_id not in self.groups, "duplicate process group")
                self.groups[op.process_group_id] = (op, None)
            for group in op.transfers:
                require(group.id not in self.groups, "duplicate transport group")
                self.groups[group.id] = (op, group)

    def resource(self, identifier, kind=None):
        require(identifier in self.r, f"unknown resource: {identifier}")
        item = self.r[identifier]
        require(kind is None or item.kind == kind, f"resource kind: {identifier}")
        return item

    def binding(self, op_id, group_id, allocation_id, mode_id=None):
        op, transfer = self.groups[group_id]
        require(op.id == op_id, "group belongs to another operation")
        q = self.q[allocation_id]
        if transfer:
            require(allocation_id in transfer.allocation_ids, "transport Q membership")
        else:
            modes = [self.modes[x] for x in op.mode_ids]
            if mode_id:
                require(mode_id in op.mode_ids, "operation/mode mismatch")
                modes = [self.modes[mode_id]]
            require(any(allocation_id in m.allocation_ids for m in modes), "process Q membership")
        return op, transfer, q

    def assignment(self, a):
        op, transfer, q = self.binding(a.operation_id, a.group_id, a.allocation_id, a.mode_id)
        require(a.mode_id in op.mode_ids, "assignment mode")
        mode = self.modes[a.mode_id]
        require(a.planned_end_min > a.planned_start_min, "planned interval must be positive")
        if transfer:
            require(
                a.phase_id in {"preposition", "rig", "move", "unload", "reset"}, "transport phase"
            )
            require(a.restore_sequence == 0, "transport cannot restore robot")
        elif a.phase_id == "restore":
            require(
                mode.preparation_phase_id is not None and a.restore_sequence > 0,
                "restore origin/sequence",
            )
            require(a.attempt == 1, "restore resumes; it does not restart")
        else:
            phase = index(mode.phases)[a.phase_id]
            require(a.restore_sequence == 0, "normal phase cannot have restore sequence")
            require(phase.interruption == "restart" or a.attempt == 1, "resume must retain attempt")
        return q

    def compatible_bindings(self, bindings):
        """Check selected transport endpoints against selected process stations."""
        for gid, qid in bindings.items():
            op, transfer = self.groups[gid]
            if transfer is None:
                continue
            route = self.routes[self.q[qid].route_id]
            if op.process_group_id in bindings:
                target = self.q[bindings[op.process_group_id]].station_id
                require(route.target_id == target, "selected transport/process target mismatch")
            producer = self.ops[self.materials[transfer.material_id].producer_id]
            if producer.process_group_id in bindings:
                source = self.q[bindings[producer.process_group_id]].station_id
                require(route.source_id == source, "selected transport/producer source mismatch")


def configuration(c):
    ctx = Context(c)
    require(c.fatigue_cap > 0, "positive fatigue cap")
    require(bool(c.orders) == bool(c.operations), "orders/operations presence mismatch")
    all_ids = [
        x.id
        for collection in (
            c.resources,
            c.routes,
            c.allocations,
            c.modes,
            c.orders,
            c.operations,
            c.materials,
        )
        for x in collection
    ] + list(ctx.groups)
    unique(all_ids, "instance ID")
    require(sum(r.kind == "crane" for r in c.resources) == 1, "single crane required")
    for r in c.resources:
        unique(r.skills, "skill")
        unique(r.reachable_station_ids, "reachable station")
        unique(r.accepted_materials, "material kind")
        require((r.capacity is None) == (r.kind == "terminal"), "only terminals are unbounded")
        if r.kind not in {"buffer", "terminal"}:
            require(r.capacity == 1, "individual resource capacity must be one")
        if r.kind in {"equipment", "fixture"}:
            ctx.resource(r.station_id, "station")
        else:
            require(r.station_id is None, "unexpected station binding")
        require(r.kind == "station" or r.receiving_slots == 0, "slots only on stations")
        require(r.kind == "robot" or not r.reachable_station_ids, "reachability only on robots")
        for station in r.reachable_station_ids:
            ctx.resource(station, "station")
        require((r.worker_parameters is not None) == (r.kind == "worker"), "worker parameters")
        if r.worker_parameters:
            require(r.worker_parameters.initial_f <= c.fatigue_cap, "initial fatigue above cap")
        if r.kind in {"buffer", "terminal"}:
            require(bool(r.accepted_materials), "typed buffer required")
        if r.kind == "terminal":
            require(set(r.accepted_materials) <= {"raw", "finished", "scrap"}, "terminal purpose")
    for route in c.routes:
        source, target = ctx.resource(route.source_id), ctx.resource(route.target_id)
        require(source.id != target.id, "route source equals destination")
        ctx.resource(route.space_id, "space")
        require(source.kind in {"station", "buffer"}, "invalid route source")
        require(target.kind in {"station", "terminal"}, "invalid route target")
    for q in c.allocations:
        worker = ctx.resource(q.worker_id, "worker")
        require(q.skill in worker.skills, "unqualified worker")
        if q.skill == "TRANSFER":
            ctx.resource(q.crane_id, "crane")
            route = ctx.routes[q.route_id]
            require(route.kind == "crane", "transport requires crane route")
            require(q.robot_id is None and q.equipment_id is None, "transport roles")
            target = ctx.r[route.target_id]
            require(
                q.station_id == (target.id if target.kind == "station" else None),
                "destination binding",
            )
        else:
            station = ctx.resource(q.station_id, "station")
            require(q.skill in station.skills, "station capability")
            require(q.crane_id is None and q.route_id is None, "process cannot use transport Q")
            if q.robot_id:
                robot = ctx.resource(q.robot_id, "robot")
                require(
                    q.skill in robot.skills and station.id in robot.reachable_station_ids,
                    "robot capability/reach",
                )
            require(
                (q.equipment_id is not None) == (q.skill in {"CUT", "WELD", "INSPECT"}),
                "required equipment",
            )
        for identifier, kind in ((q.equipment_id, "equipment"), (q.fixture_id, "fixture")):
            if identifier:
                r = ctx.resource(identifier, kind)
                require(r.station_id == q.station_id, "equipment/fixture location mismatch")
        station = ctx.r.get(q.station_id)
        needs_fixture = station is not None and bool(
            set(station.skills) & {"ASSEMBLE", "WELD", "INSPECT"}
        )
        require((q.fixture_id is not None) == needs_fixture, "required station fixture")
    for m in c.modes:
        require(m.name in LEGAL[m.operation_kind], "illegal mode")
        unique(m.allocation_ids, "Q member")
        phases = index(m.phases)
        if m.operation_kind == "LIFT":
            require(
                not m.phases and not m.allocation_ids and m.freeze_at == "preposition",
                "LIFT is transport-only",
            )
            continue
        require(bool(m.phases) and bool(m.allocation_ids), "empty mode or Q")
        dag({p.id: p.predecessors for p in m.phases})
        expected = {"work"}
        if m.operation_kind != "INSPECT":
            expected.add("handoff")
        if m.operation_kind not in {"BRACKET", "INSPECT"}:
            expected.add("setup")
        if m.operation_kind == "ASSEMBLE" and m.name == "HR":
            expected.add("align")
        require(set(phases) == expected, "phase template mismatch")
        sequence = [key for key in ("setup", "align", "work", "handoff") if key in phases]
        for i, key in enumerate(sequence):
            p = phases[key]
            require(
                p.predecessors == (() if i == 0 else (sequence[i - 1],)), "process phase dependency"
            )
            unique(p.active_roles, "active role")
            require(
                (p.activity is not None) == ("worker" in p.active_roles), "activity needs worker"
            )
            require(
                not p.fatigue_sensitive or (p.id == "work" and "worker" in p.active_roles),
                "sensitivity",
            )
            require(
                p.interruption
                == (
                    "restart" if key == "work" and m.operation_kind in {"CUT", "WELD"} else "resume"
                ),
                "interruption policy",
            )
        robot_required = m.name in {"R", "HR"}
        expected_prep = (
            ("align" if m.operation_kind == "ASSEMBLE" else "setup") if robot_required else None
        )
        require(m.preparation_phase_id == expected_prep, "robot preparation phase")
        for p in m.phases:
            expected_roles = set()
            if not (p.id == "work" and m.name == "R"):
                expected_roles.add("worker")
            if robot_required and p.id in {expected_prep, "work"}:
                expected_roles.add("robot")
            if m.operation_kind in {"CUT", "WELD", "INSPECT"}:
                expected_roles.add("equipment")
            require(set(p.active_roles) == expected_roles, "stage active resource roles")
            expected_activity = (
                None
                if "worker" not in expected_roles
                else (
                    "carry"
                    if (p.id == "handoff" and m.operation_kind in {"CUT", "BRACKET"})
                    or (p.id == "setup" and m.operation_kind == "ASSEMBLE")
                    else "supervise"
                    if p.id in {"align", "handoff"}
                    else "collaborate"
                    if p.id == "work" and m.name == "HR"
                    else "work"
                )
            )
            require(p.activity == expected_activity, "stage activity")
            require(
                p.fatigue_sensitive == (p.id == "work" and m.name != "R"), "stage speed sensitivity"
            )
            require(
                p.cancel_boundary
                == (
                    "handoff_then_clear"
                    if p.id == "work" and m.operation_kind != "INSPECT"
                    else "clear"
                ),
                "stage cancellation boundary",
            )
            require(
                p.establishes_preparation == (p.id == expected_prep), "preparation establishment"
            )
            require(
                p.requires_preparation == (p.id == "work" and robot_required),
                "work preparation requirement",
            )
        if expected_prep:
            prep = phases[expected_prep]
            require(
                {"worker", "robot"} <= set(prep.active_roles) and not prep.fatigue_sensitive,
                "restore template resources/cost",
            )
        expected_switch = "setup" if m.operation_kind in {"ASSEMBLE", "WELD"} else None
        require(m.switch_after == expected_switch, "mode switching boundary")
        require(
            m.freeze_at
            == (
                "align"
                if m.operation_kind == "ASSEMBLE" and m.name == "HR"
                else "work"
                if expected_switch
                else sequence[0]
            ),
            "mode freeze boundary",
        )
        for qid in m.allocation_ids:
            q = ctx.q[qid]
            require(q.skill == m.operation_kind, "Q operation qualification")
            require((q.robot_id is not None) == robot_required, "mode robot requirement")
            for p in m.phases:
                for role in p.active_roles:
                    require(getattr(q, role + "_id") is not None, "phase role missing in Q")
        expected_held = {"station"}
        if m.operation_kind in {"ASSEMBLE", "WELD", "INSPECT"}:
            expected_held.add("fixture")
        if m.operation_kind in {"CUT", "WELD"}:
            expected_held.add("equipment")
        require(set(m.held_roles) == expected_held, "process held resources")
    dag({op.id: op.predecessors for op in c.operations})
    for order in c.orders:
        require(order.due_min >= order.release_min, "due before release")
        require(bool(order.required_finished_ids), "required deliveries missing")
        unique(order.required_finished_ids, "required delivery")
        for mid in order.required_finished_ids:
            material = ctx.materials[mid]
            require(
                material.order_id == order.id and material.kind == "finished",
                "invalid finished reference",
            )
    for op in c.operations:
        require(op.order_id in ctx.orders, "unknown order")
        require(bool(op.mode_ids), "operation needs modes")
        unique(op.mode_ids, "operation mode")
        unique(op.input_ids, "operation input")
        require((op.process_group_id is None) == (op.kind == "LIFT"), "process group presence")
        for mode in op.mode_ids:
            require(ctx.modes[mode].operation_kind == op.kind, "operation mode kind")
        output = ctx.materials[op.output_id]
        require(
            output.producer_id == op.id and output.order_id == op.order_id, "output producer/order"
        )
        inputs = [ctx.materials[mid] for mid in op.input_ids]
        require(bool(inputs), "explicit inputs required, including raw sources")
        require(
            all(x.consumer_id == op.id and x.order_id == op.order_id for x in inputs),
            "input consumer/order",
        )
        require(
            {x.producer_id for x in inputs if x.producer_id} == set(op.predecessors),
            "material and precedence mismatch",
        )
        modules = [x for x in inputs if x.kind == "module"]
        require(
            {t.material_id for t in op.transfers} == {x.id for x in modules},
            "explicit per-module transport",
        )
        unique([t.material_id for t in op.transfers], "transported material")
        for t in op.transfers:
            require(bool(t.allocation_ids), "empty transport Q")
            unique(t.allocation_ids, "transport Q")
            require(t.wait_for_reset == (op.kind == "ASSEMBLE"), "join waits for last reset")
            require(t.reserve_all_receiving_slots == (op.kind == "ASSEMBLE"), "join reservation")
            for qid in t.allocation_ids:
                q = ctx.q[qid]
                require(q.skill == "TRANSFER", "unqualified transport allocation")
                route = ctx.routes[q.route_id]
                require(
                    route.source_id in ctx.materials[t.material_id].storage_ids, "transport source"
                )
                if op.kind == "LIFT":
                    require(route.target_id in output.storage_ids, "final transport target")
                else:
                    allowed = {
                        ctx.q[a].station_id
                        for m in op.mode_ids
                        for a in ctx.modes[m].allocation_ids
                    }
                    require(route.target_id in allowed, "transport destination")
                if op.kind == "ASSEMBLE":
                    require(
                        ctx.r[route.target_id].receiving_slots >= len(modules),
                        "join receiving capacity",
                    )
        if modules and op.kind == "ASSEMBLE":
            targets = {
                ctx.routes[ctx.q[q].route_id].target_id for q in op.transfers[0].allocation_ids
            }
            require(
                any(
                    distinct_sources(
                        [
                            {
                                ctx.routes[ctx.q[q].route_id].source_id
                                for q in t.allocation_ids
                                if ctx.routes[ctx.q[q].route_id].target_id == target
                                and ctx.routes[ctx.q[q].route_id].source_id != target
                            }
                            for t in op.transfers
                        ]
                    )
                    for target in targets
                ),
                "no distinct sources with common join target",
            )
        feed = any(x.kind in {"pipe", "bracket"} for x in inputs)
        require((op.feed_space_id is not None) == feed, "explicit feed route")
        if feed:
            ctx.resource(op.feed_space_id, "space")
        unique([(x.mode_id, x.phase_id) for x in op.duration_overrides], "duration override")
        for override in op.duration_overrides:
            require(
                override.mode_id in op.mode_ids
                and override.phase_id in index(ctx.modes[override.mode_id].phases),
                "duration override reference",
            )
        if op.kind in {"ASSEMBLE", "WELD"}:
            for left, right in combinations((ctx.modes[mid] for mid in op.mode_ids), 2):
                require(compatible_prefix(ctx, op, left, right), "incompatible common prefix")
    for material in c.materials:
        require(material.order_id in ctx.orders, "material order")
        require(bool(material.storage_ids), "material locations required")
        unique(material.storage_ids, "storage location")
        if material.producer_id:
            require(
                ctx.ops[material.producer_id].output_id == material.id,
                "material producer reference",
            )
        else:
            require(
                material.kind == "raw" and material.available_at == "release",
                "only raw material has no producer",
            )
        if material.consumer_id:
            require(
                material.id in ctx.ops[material.consumer_id].input_ids,
                "material consumer reference",
            )
        else:
            require(
                material.kind == "finished"
                and material.id in ctx.orders[material.order_id].required_finished_ids,
                "orphan material",
            )
        require(
            material.movement
            == {
                "raw": "raw_at_release",
                "pipe": "feed",
                "bracket": "feed",
                "module": "crane",
                "finished": "retained",
            }[material.kind],
            "material movement",
        )
        for loc in material.storage_ids:
            r = ctx.resource(loc)
            require(r.kind in {"station", "buffer", "terminal"}, "material storage kind")
            expected_storage = {
                "pipe": "buffer",
                "bracket": "buffer",
                "module": "station",
                "raw": "terminal",
                "finished": "terminal",
            }[material.kind]
            require(r.kind == expected_storage, "material storage purpose")
            if r.kind == "terminal":
                require(material.kind in r.accepted_materials, "terminal material purpose")
            if r.kind == "buffer":
                require(
                    material.kind in r.accepted_materials and material.quantity <= r.capacity,
                    "typed buffer capacity",
                )
        if material.producer_id:
            producer = ctx.ops[material.producer_id]
            expected_kind = {
                "CUT": "pipe",
                "BRACKET": "bracket",
                "ASSEMBLE": "module",
                "WELD": "module",
                "INSPECT": "module",
                "LIFT": "finished",
            }[producer.kind]
            require(material.kind == expected_kind, "operation output kind")
            require(
                material.available_at
                == (
                    "work"
                    if producer.kind == "INSPECT"
                    else "unload"
                    if producer.kind == "LIFT"
                    else "handoff"
                ),
                "material release boundary",
            )
            if material.kind == "module":
                sites = {
                    ctx.q[q].station_id
                    for mode in producer.mode_ids
                    for q in ctx.modes[mode].allocation_ids
                }
                require(
                    set(material.storage_ids) == sites,
                    "module output locations must match producer Q",
                )
    return ctx


def observation(value, ctx):
    require(value.configuration_id == ctx.c.id, "configuration mismatch")
    unique(value.observed_event_ids, "observed event")
    index(value.known_orders, "order_id")
    index(value.estimates, "resource_id")
    for k in value.known_orders:
        order = ctx.orders[k.order_id]
        require(
            order.release_min <= k.released_observed_min <= value.as_of_min,
            "unreleased or future order",
        )
        for time in (k.cancel_observed_min, k.completion_observed_min):
            require(
                time is None or k.released_observed_min <= time <= value.as_of_min,
                "future observation",
            )
        require(
            (k.actual_completion_min is None) == (k.completion_observed_min is None),
            "completion observation missing",
        )
        if k.actual_completion_min is not None:
            require(
                order.release_min <= k.actual_completion_min <= k.completion_observed_min,
                "completion chronology",
            )
    for e in value.estimates:
        r = ctx.resource(e.resource_id)
        require(e.sampled_min <= e.received_min <= value.as_of_min, "future estimate")
        require(
            r.kind == "worker" or (e.fatigue_estimate is None and e.exposure_estimate_min is None),
            "fatigue belongs to worker",
        )
    if value.execution is not None:
        execution = value.execution
        require(
            execution.sampled_min <= execution.received_min <= value.as_of_min,
            "future execution observation",
        )
        known = index(value.known_orders, "order_id")
        for b in execution.bindings:
            require(ctx.ops[b.operation_id].order_id in known, "unobserved execution order")
            require(
                ctx.orders[ctx.ops[b.operation_id].order_id].release_min <= execution.sampled_min,
                "execution before release",
            )
        for item in (*execution.materials, *execution.reservations):
            require(ctx.materials[item.material_id].order_id in known, "unobserved material order")
        execution_details(execution, ctx, execution.sampled_min, set(), complete=False)


def required_tail(a, observed, ctx):
    """Structural evidence for committed tails; runtime authorization remains separate."""
    if observed.execution is None:
        return False
    known = next(k for k in observed.known_orders if k.order_id == ctx.ops[a.operation_id].order_id)
    binding = next((b for b in observed.execution.bindings if b.group_id == a.group_id), None)
    if binding is None or binding.allocation_id != a.allocation_id:
        return False
    history = [p for p in observed.execution.phases if p.group_id == a.group_id]
    if any(p.phase_id == a.phase_id and p.status == "completed" for p in history):
        return False

    def same(p):
        return (p.mode_id, p.allocation_id) == (
            a.mode_id,
            a.allocation_id,
        )

    completed = {p.phase_id for p in history if same(p) and p.status == "completed"}
    in_progress = {p.phase_id for p in history if same(p) and p.status in {"running", "paused"}}
    underway = {
        p.phase_id
        for p in history
        if same(p)
        and p.status in {"running", "paused"}
        and (p.attempt, p.restore_sequence) == (a.attempt, a.restore_sequence)
    }
    _, transfer = ctx.groups[a.group_id]
    if known.actual_completion_min is not None:
        return (
            transfer is not None
            and a.phase_id == "reset"
            and ("unload" in completed or "reset" in underway)
        )
    if known.cancel_observed_min is None:
        return False
    if a.phase_id in underway:
        return True
    if transfer:
        if a.phase_id == "reset":
            return bool((completed | underway) & {"preposition", "rig", "move", "unload"})
        if a.phase_id in {"move", "unload"}:
            return "rig" in completed or "rig" in underway or "move" in underway
        return False
    return a.phase_id == "handoff" and bool({"work"} & (completed | in_progress))


def scenario(value, ctx):
    index(value.events)
    transitions = set()
    for e in value.events:
        if e.type in {"release", "cancel"}:
            order = ctx.orders[e.entity_id]
            require(e.release_allowed is None, "order event release flag")
            require(e.sim_time_min >= order.release_min, "event before order release")
            if e.type == "release":
                require(e.sim_time_min == order.release_min, "release time mismatch")
        else:
            r = ctx.resource(e.entity_id)
            fixed = r.kind in {"equipment", "station", "fixture"}
            if e.type == "failure" and fixed:
                require(
                    e.release_allowed is not None, "fixed-resource failure requires release_allowed"
                )
            if e.type == "repair":
                require(e.release_allowed is None, "repair release flag")
            key = (e.sim_time_min, e.entity_id)
            require(key not in transitions, "conflicting same-time resource events")
            transitions.add(key)


def validate(record, *, config=None):
    """Validate a document; linked documents require the full configuration.

    The full configuration is for ingestion/validation, not a scheduler argument.
    """
    record = decode(type(record), as_data(record))
    try:
        if isinstance(record, Configuration):
            configuration(record)
            return
        require(isinstance(config, Configuration), "linked document requires configuration")
        ctx = configuration(decode(Configuration, as_data(config)))
        config_id = (
            record.observation.configuration_id
            if isinstance(record, Plan)
            else record.configuration_id
        )
        require(config_id == config.id, "configuration ID mismatch")
        if isinstance(record, PlanningObservation):
            observation(record, ctx)
        elif isinstance(record, PlanningInput):
            from dataclasses import replace

            observation(record.observation, ctx)
            ids = {o.order_id for o in record.observation.known_orders}
            expected = replace(
                config,
                orders=tuple(o for o in config.orders if o.id in ids),
                operations=tuple(o for o in config.operations if o.order_id in ids),
                materials=tuple(m for m in config.materials if m.order_id in ids),
            )
            require(
                record.visible_configuration == expected,
                "planning data must contain exactly observed orders and declared static catalog",
            )
            configuration(record.visible_configuration)
        elif isinstance(record, HiddenScenario):
            scenario(record, ctx)
        elif isinstance(record, Plan):
            observation(record.observation, ctx)
            active = {
                k.order_id: k
                for k in record.observation.known_orders
                if k.cancel_observed_min is None
            }
            completions = index(record.completions, "order_id")
            require(set(completions) == set(active), "K_t coverage: cannot drop unfavorable orders")
            for oid, completion in completions.items():
                known = active[oid]
                require(
                    completion.actual_completion_min == known.actual_completion_min,
                    "actual completion changed",
                )
                if known.actual_completion_min is not None:
                    require(
                        completion.predicted_completion_min is None, "completed order uses actual C"
                    )
                elif record.status == "candidate":
                    require(
                        completion.predicted_completion_min is not None,
                        "missing predicted completion",
                    )
                if completion.predicted_completion_min is not None:
                    require(
                        completion.predicted_completion_min >= record.observation.as_of_min,
                        "prediction in past",
                    )
            bindings = {}
            selected_modes = {}
            for a in record.assignments:
                q = ctx.assignment(a)
                known = index(record.observation.known_orders, "order_id")
                oid = ctx.ops[a.operation_id].order_id
                require(oid in known, "assignment to invisible order")
                if (
                    known[oid].cancel_observed_min is not None
                    or known[oid].actual_completion_min is not None
                ):
                    require(
                        required_tail(a, record.observation, ctx),
                        "assignment requires observed committed tail",
                    )
                require(a.planned_start_min >= record.observation.as_of_min, "plan starts in past")
                require(
                    a.group_id not in bindings or bindings[a.group_id] == q.id,
                    "group identity changed",
                )
                bindings[a.group_id] = q.id
                require(
                    a.operation_id not in selected_modes
                    or selected_modes[a.operation_id] == a.mode_id,
                    "one candidate mode per operation",
                )
                selected_modes[a.operation_id] = a.mode_id
            ctx.compatible_bindings(bindings)
            unique(
                [
                    (a.group_id, a.phase_id, a.attempt, a.restore_sequence)
                    for a in record.assignments
                ],
                "phase assignment",
            )
            exposure = index(record.exposure_estimates, "worker_id")
            require(
                (record.exposure_budget_min is None) == (record.budget_kind == "D0"),
                "D budget presence",
            )
            require(
                record.budget_kind == "D0"
                or set(exposure) == {r.id for r in config.resources if r.kind == "worker"},
                "D prediction coverage",
            )
            for eid in exposure:
                ctx.resource(eid, "worker")
        elif isinstance(record, DispatchCommand):
            require(
                (record.assignment is not None) == (record.action in {"start", "resume"}),
                "dispatch payload",
            )
            require((record.worker_id is not None) == (record.action == "rest"), "rest worker")
            require(
                (record.duration_min is not None) == (record.action in {"rest", "wait"}),
                "rest/wait duration",
            )
            require(
                (record.cleanup_material_id is not None) == (record.action == "cleanup"),
                "cleanup payload",
            )
            if record.worker_id:
                ctx.resource(record.worker_id, "worker")
            if record.cleanup_material_id:
                require(record.cleanup_material_id in ctx.materials, "cleanup material")
            if record.assignment:
                ctx.assignment(record.assignment)
                require(
                    record.assignment.planned_start_min == record.issued_min,
                    "dispatch is immediate",
                )
        elif isinstance(record, ExecutionSnapshot):
            snapshot(record, ctx)
        elif isinstance(record, ExecutionEvent):
            require(
                record.entity_id
                in set(ctx.r)
                | set(ctx.ops)
                | set(ctx.orders)
                | set(ctx.materials)
                | set(ctx.groups),
                "event entity reference",
            )
        elif isinstance(record, RunManifest):
            require(
                record.configuration_sha256
                == hashlib.sha256(dumps(config).encode("utf-8")).hexdigest(),
                "configuration digest mismatch",
            )
            require(
                re.fullmatch(r"[0-9a-f]{40}", record.code_revision) is not None
                or (record.status == "planned" and record.code_revision == "example.uncommitted"),
                "run requires a pinned full Git revision; placeholder only for planned example",
            )
            require(
                record.observation_window_min == config.observation_window_min
                and record.fatigue_cap == config.fatigue_cap,
                "common comparison window/cap",
            )
            require(
                (record.termination_reason is None) == (record.status == "planned"),
                "termination status",
            )
        elif isinstance(record, OfflineEvaluation):
            require(
                record.scenario.configuration_id == config.id, "evaluation scenario configuration"
            )
            scenario(record.scenario, ctx)
            require(
                record.observation_window_min == config.observation_window_min, "evaluation window"
            )
            cancelled = {
                e.entity_id
                for e in record.scenario.events
                if e.type == "cancel" and e.sim_time_min <= record.observation_window_min
            }
            expected = {
                o.id for o in config.orders if o.release_min <= record.observation_window_min
            } - cancelled
            unique(record.evaluation_order_ids, "evaluation order")
            require(set(record.evaluation_order_ids) == expected, "offline J_eval mismatch")
            completions = index(record.completions, "order_id")
            require(set(completions) == expected, "evaluation completion coverage")
            for oid, item in completions.items():
                require(
                    item.actual_completion_min is None
                    or ctx.orders[oid].release_min
                    <= item.actual_completion_min
                    <= record.observation_window_min,
                    "actual completion outside window",
                )
            require(
                set(index(record.workers, "worker_id"))
                == {r.id for r in config.resources if r.kind == "worker"},
                "exposure coverage",
            )
            require(
                record.drained_at_min is None
                or record.drained_at_min <= record.observation_window_min,
                "drain outside window",
            )
            require(
                record.truncated == (record.drained_at_min is None), "truncation/drain mismatch"
            )
        else:
            raise ContractError("unsupported top-level contract")
    except KeyError as error:
        raise ContractError(f"unresolved reference: {error}") from error


def snapshot(s, ctx):
    require(
        set(index(s.workers, "worker_id")) == {r.id for r in ctx.c.resources if r.kind == "worker"},
        "worker state coverage",
    )
    for w in s.workers:
        require(w.fatigue <= ctx.c.fatigue_cap, "state exceeds fatigue cap")
    require(set(index(s.resources, "resource_id")) == set(ctx.r), "resource state coverage")
    for state in s.resources:
        r = ctx.r[state.resource_id]
        if state.failed and r.kind in {"station", "fixture", "equipment"}:
            require(state.release_allowed is not None, "failed fixture release state missing")
    require(set(index(s.orders, "order_id")) == set(ctx.orders), "order state coverage")
    for order in s.orders:
        require(
            not order.released or ctx.orders[order.order_id].release_min <= s.sim_time_min,
            "future released state",
        )
        if order.actual_completion_min is not None:
            require(
                order.released
                and ctx.orders[order.order_id].release_min
                <= order.actual_completion_min
                <= s.sim_time_min,
                "actual completion time",
            )
    execution_details(
        s, ctx, s.sim_time_min, {r.resource_id for r in s.resources if r.failed}, complete=True
    )


def execution_details(s, ctx, at_min, failed, *, complete):
    bindings = index(s.bindings, "group_id")
    for b in s.bindings:
        ctx.binding(b.operation_id, b.group_id, b.allocation_id)
    ctx.compatible_bindings({gid: b.allocation_id for gid, b in bindings.items()})
    preparations = set(index(s.preparations, "robot_id"))
    robots = {r.id for r in ctx.c.resources if r.kind == "robot"}
    require(
        preparations == robots if complete else preparations <= robots, "robot preparation coverage"
    )
    for p in s.preparations:
        refs = (p.operation_id, p.group_id, p.station_id)
        require(
            all(x is None for x in refs) or all(x is not None for x in refs),
            "partial preparation reference",
        )
        if p.valid:
            require(all(x is not None for x in refs), "valid preparation needs origin")
            b = bindings[p.group_id]
            q = ctx.q[b.allocation_id]
            require(
                not failed.intersection(
                    {q.worker_id, q.robot_id, q.equipment_id, q.station_id, q.fixture_id}
                ),
                "failed group resource invalidates preparation",
            )
        if p.group_id:
            b = bindings[p.group_id]
            _, transfer, q = ctx.binding(p.operation_id, p.group_id, b.allocation_id)
            require(
                transfer is None and q.robot_id == p.robot_id and q.station_id == p.station_id,
                "preparation identity mismatch",
            )
    unique(
        [(p.group_id, p.phase_id, p.attempt, p.restore_sequence) for p in s.phases],
        "phase execution",
    )
    for p in s.phases:
        require((p.completed_min is not None) == (p.status == "completed"), "completion status")
        b = bindings[p.group_id]
        op, transfer, q = ctx.binding(p.operation_id, p.group_id, p.allocation_id, p.mode_id)
        current = ctx.q[b.allocation_id]
        if p.allocation_id != b.allocation_id:
            require(
                transfer is None
                and p.phase_id == "setup"
                and p.status == "completed"
                and same_process_identity(q, current)
                and any(
                    b.allocation_id in ctx.modes[mid].allocation_ids
                    and compatible_prefix(ctx, op, ctx.modes[p.mode_id], ctx.modes[mid])
                    for mid in op.mode_ids
                ),
                "historical allocation incompatible with current binding",
            )
        # After a switch boundary, all already-started suffixes retain their mode.
        suffix_modes = {
            x.mode_id for x in s.phases if x.group_id == p.group_id and x.phase_id != "setup"
        }
        if not transfer:
            require(len(suffix_modes) <= 1, "started suffix mode is frozen")
            if suffix_modes and p.mode_id not in suffix_modes:
                target = ctx.modes[next(iter(suffix_modes))]
                require(
                    p.phase_id == "setup"
                    and p.status == "completed"
                    and compatible_prefix(ctx, op, ctx.modes[p.mode_id], target),
                    "mode change outside compatible boundary",
                )
                require(
                    all(
                        p.completed_min <= x.started_min
                        for x in s.phases
                        if x.group_id == p.group_id and x.phase_id != "setup"
                    ),
                    "suffix started before common prefix completed",
                )
        require(p.mode_id in op.mode_ids, "phase mode")
        require(p.started_min <= at_min, "phase from future")
        if p.completed_min is not None:
            require(
                p.started_min <= p.completed_min <= at_min and p.remaining_base_min == 0,
                "completed phase remainder/time",
            )
        mode = ctx.modes[p.mode_id]
        if p.phase_id == "restore":
            require(
                not transfer
                and mode.preparation_phase_id is not None
                and p.restore_sequence > 0
                and p.attempt == 1,
                "restore identity",
            )
            require(
                p.speed_multiplier == 1 and p.sampled_f is None, "restore not fatigue-sensitive"
            )
            require(
                any(
                    previous.group_id == p.group_id
                    and previous.phase_id == mode.preparation_phase_id
                    and previous.status == "completed"
                    and previous.completed_min <= p.started_min
                    for previous in s.phases
                ),
                "restore requires completed original preparation",
            )
        else:
            require(p.restore_sequence == 0, "unexpected restore sequence")
            if transfer:
                require(
                    p.phase_id in {"preposition", "rig", "move", "unload", "reset"}
                    and p.attempt == 1,
                    "transport phase identity",
                )
                require(
                    p.sampled_f is None and p.speed_multiplier == 1,
                    "transport not fatigue-sensitive",
                )
            else:
                phase = index(mode.phases)[p.phase_id]
                require(phase.interruption == "restart" or p.attempt == 1, "resume attempt")
                require(
                    (p.sampled_f is not None) == phase.fatigue_sensitive, "speed sample presence"
                )
                require(
                    phase.fatigue_sensitive or p.speed_multiplier == 1,
                    "fixed phase speed multiplier",
                )
                if phase.requires_preparation and p.status == "running":
                    require(
                        any(
                            x.robot_id == q.robot_id
                            and x.operation_id == op.id
                            and x.group_id == p.group_id
                            and x.station_id == q.station_id
                            and x.valid
                            for x in s.preparations
                        ),
                        "robot work requires matching valid preparation",
                    )
        if not transfer:
            resolved = resolve_process_phase(ctx.c, p.operation_id, p.mode_id, p.phase_id)
            require(
                p.remaining_base_min <= resolved.base_min,
                "remaining net base work exceeds phase cost",
            )
    unique([(x.resource_id, x.owner_group_id, x.purpose) for x in s.locks], "lock")
    owners = {}
    for lock in s.locks:
        r = ctx.resource(lock.resource_id)
        require(lock.owner_group_id in bindings, "lock owner binding")
        owners.setdefault(r.id, set()).add(lock.owner_group_id)
    for rid, groups in owners.items():
        capacity = ctx.r[rid].capacity
        require(
            capacity is None or len(groups) <= capacity,
            "resource capacity: active/held union per owner",
        )
    index(s.materials, "material_id")
    index(s.reservations, "material_id")
    occupancy, slots = {}, set()
    for item in (*s.materials, *s.reservations):
        m = ctx.materials[item.material_id]
        r = ctx.resource(item.location_id)
        require(
            r.kind in {"buffer", "station", "terminal", "crane"}, "invalid material location kind"
        )
        if hasattr(item, "status"):
            require(
                (r.kind == "crane") == (item.status == "in_transit"),
                "load must be explicitly in transit",
            )
        if hasattr(item, "status"):
            if item.status == "scrapped":
                require(
                    r.kind == "terminal" and "scrap" in r.accepted_materials,
                    "scrap terminal purpose",
                )
                continue
            if item.status == "consumed":
                continue
            if r.kind == "terminal":
                require(m.kind in r.accepted_materials, "stored terminal material purpose")
            if item.status == "stored" and m.kind in {"pipe", "bracket"}:
                require(r.kind == "buffer", "intermediate stored material requires buffer")
        if hasattr(item, "owner_group_id"):
            require(item.owner_group_id in bindings, "reservation owner")
            require(r.kind in {"station", "buffer"}, "only finite receiving positions are reserved")
        if r.kind == "buffer":
            require(m.kind in r.accepted_materials and item.slot is None, "typed inventory")
            occupancy[r.id] = occupancy.get(r.id, 0) + m.quantity
        if item.slot is not None:
            require(
                r.kind == "station" and m.kind == "module" and item.slot < r.receiving_slots,
                "receiving slot",
            )
            key = (r.id, item.slot)
            require(key not in slots, "slot double occupied/reserved")
            slots.add(key)
    for rid, count in occupancy.items():
        require(count <= ctx.r[rid].capacity, "inventory plus reservations exceeds capacity")
