"""S08 explicit sampling grants and causal delivery into the S06 planning view.

Sampling belongs to the trusted execution adapter. The scheduler receives only
PlanningInput. Packets are immutable sampled values, never live truth references.
"""

from dataclasses import dataclass, replace

from .contracts.codec import ID, Nonnegative, as_data, decode, require
from .contracts.messages import Estimate, KnownOrder, ObservedExecution, PlanningObservation
from .contracts.planning import planning_input
from .contracts.validation import Context, validate


@dataclass(frozen=True)
class ObservationGrant:
    order_ids: tuple[str, ...]
    fatigue_ids: tuple[str, ...]
    exposure_ids: tuple[str, ...]
    availability_ids: tuple[str, ...]
    execution_group_ids: tuple[str, ...]
    material_ids: tuple[str, ...]
    include_event_history: bool


@dataclass(frozen=True)
class ObservationPacket:
    sampled_min: float
    received_min: float
    observation: PlanningObservation


def sample_observation(config, snapshot, grant, *, packet_id, received_min, event_history=()):
    """Sample only explicit grants, with caller-declared delivery time.

    Missing/noisy sensor values can be supplied by a future declared adapter;
    this deterministic implementation adds no noise or experimental levels.
    Execution grants include historical phase samples/multipliers, bindings,
    locks and preparation dependency records; no current worker truth is implied.
    """
    validate(snapshot, config=config)
    decode(ID, packet_id)
    decode(Nonnegative, received_min)
    require(received_min >= snapshot.sim_time_min, "delivery precedes sampling")
    grant = decode(ObservationGrant, as_data(grant))
    ctx = Context(config)
    for values, domain in (
        (grant.order_ids, ctx.orders),
        (grant.fatigue_ids, ctx.r),
        (grant.exposure_ids, ctx.r),
        (grant.availability_ids, ctx.r),
        (grant.execution_group_ids, ctx.groups),
        (grant.material_ids, ctx.materials),
    ):
        require(
            len(values) == len(set(values)) and set(values) <= domain.keys(), "invalid grant IDs"
        )
    for rid in (*grant.fatigue_ids, *grant.exposure_ids):
        require(ctx.r[rid].kind == "worker", "worker estimate grant required")
    orders = tuple(
        KnownOrder(
            o.order_id,
            received_min,
            received_min if o.cancelled else None,
            received_min if o.actual_completion_min is not None else None,
            o.actual_completion_min,
        )
        for o in snapshot.orders
        if o.released and o.order_id in grant.order_ids
    )
    known = {o.order_id for o in orders}
    workers = {w.worker_id: w for w in snapshot.workers}
    resources = {r.resource_id: r for r in snapshot.resources}
    estimates = []
    for rid in sorted(set(grant.fatigue_ids + grant.exposure_ids + grant.availability_ids)):
        occupied = any(lock.resource_id == rid for lock in snapshot.locks)
        estimates.append(
            Estimate(
                rid,
                snapshot.sim_time_min,
                received_min,
                workers[rid].fatigue if rid in grant.fatigue_ids else None,
                workers[rid].exposure_min if rid in grant.exposure_ids else None,
                not resources[rid].failed
                and not occupied
                and not (rid in workers and workers[rid].activity == "rest")
                if rid in grant.availability_ids
                else None,
            )
        )
    groups = {g for g in grant.execution_group_ids if ctx.groups[g][0].order_id in known}
    # Include preparations only when their origin binding is explicitly granted.
    preparations = tuple(p for p in snapshot.preparations if p.group_id in groups)
    phases = tuple(p for p in snapshot.phases if p.group_id in groups)
    bindings = tuple(b for b in snapshot.bindings if b.group_id in groups)
    materials = tuple(
        m
        for m in snapshot.materials
        if m.material_id in grant.material_ids and ctx.materials[m.material_id].order_id in known
    )
    execution = None
    if grant.execution_group_ids or grant.material_ids:
        execution = ObservedExecution(
            snapshot.sim_time_min,
            received_min,
            bindings,
            phases,
            tuple(lock for lock in snapshot.locks if lock.owner_group_id in groups),
            materials,
            tuple(
                r
                for r in snapshot.reservations
                if r.owner_group_id in groups
                and r.material_id in grant.material_ids
                and ctx.materials[r.material_id].order_id in known
            ),
            preparations,
        )
    event_ids = []
    if grant.include_event_history:
        for event in event_history:
            validate(event, config=config)
            require(
                event.run_id == snapshot.run_id and event.sim_time_min <= snapshot.sim_time_min,
                "event is not from this sampled history",
            )
            # A raw event ID can itself encode hidden entity names: filter owners first.
            entity = event.entity_id
            visible = entity in known or entity in grant.availability_ids
            if entity in ctx.ops:
                visible = ctx.ops[entity].order_id in known
            elif entity in ctx.groups:
                visible = entity in groups
            elif entity in ctx.materials:
                visible = entity in grant.material_ids and ctx.materials[entity].order_id in known
            if visible:
                event_ids.append(event.event_id)
    observation = PlanningObservation(
        "S06-1.1",
        "planning_observation",
        packet_id,
        snapshot.run_id,
        config.id,
        config.units,
        received_min,
        orders,
        tuple(estimates),
        tuple(sorted(set(event_ids))),
        execution,
    )
    validate(observation, config=config)
    return ObservationPacket(snapshot.sim_time_min, received_min, observation)


def planning_view(config, packets, *, as_of_min, observation_id, run_id):
    """Receive a packet ledger causally; late old packets cannot roll back facts.

    Keep the newest sampled execution frame intact, never join partial frames
    into an invented complete snapshot. Missing table entries remain unknown.
    This function is adapter-side; pass its return value alone to a scheduler.
    """
    decode(Nonnegative, as_of_min)
    decode(ID, observation_id)
    decode(ID, run_id)
    packets = tuple(packets)
    require(all(isinstance(p, ObservationPacket) for p in packets), "expected sampled packets")
    require(len({p.observation.id for p in packets}) == len(packets), "duplicate packet ID")
    known, estimates, events = {}, {}, set()
    frame, frame_key = None, None
    for packet in sorted(packets, key=lambda p: (p.received_min, p.observation.id)):
        decode(Nonnegative, packet.sampled_min)
        decode(Nonnegative, packet.received_min)
        require(packet.sampled_min <= packet.received_min, "packet chronology")
        o = packet.observation
        require(o.run_id == run_id and o.as_of_min == packet.received_min, "packet identity/clock")
        validate(o, config=config)
        require(
            all(
                e.sampled_min == packet.sampled_min and e.received_min == packet.received_min
                for e in o.estimates
            ),
            "estimate differs from packet clock",
        )
        require(
            o.execution is None
            or (o.execution.sampled_min, o.execution.received_min)
            == (packet.sampled_min, packet.received_min),
            "frame differs from packet clock",
        )
        if packet.received_min > as_of_min:
            continue
        for k in o.known_orders:
            previous = known.get(k.order_id)
            if previous is None:
                known[k.order_id] = k
            else:
                if (
                    previous.actual_completion_min is not None
                    and k.actual_completion_min is not None
                ):
                    require(
                        previous.actual_completion_min == k.actual_completion_min,
                        "conflicting actual completions",
                    )
                known[k.order_id] = replace(
                    previous,
                    cancel_observed_min=(
                        previous.cancel_observed_min
                        if previous.cancel_observed_min is not None
                        else k.cancel_observed_min
                    ),
                    completion_observed_min=(
                        previous.completion_observed_min
                        if previous.completion_observed_min is not None
                        else k.completion_observed_min
                    ),
                    actual_completion_min=(
                        previous.actual_completion_min
                        if previous.actual_completion_min is not None
                        else k.actual_completion_min
                    ),
                )
        for estimate in o.estimates:
            key = (estimate.sampled_min, estimate.received_min, o.id)
            if estimate.resource_id not in estimates or key > estimates[estimate.resource_id][0]:
                estimates[estimate.resource_id] = (key, estimate)
        events.update(o.observed_event_ids)
        key = (packet.sampled_min, packet.received_min, o.id)
        if o.execution is not None and (frame_key is None or key > frame_key):
            frame, frame_key = o.execution, key
    observation = PlanningObservation(
        "S06-1.1",
        "planning_observation",
        observation_id,
        run_id,
        config.id,
        config.units,
        as_of_min,
        tuple(known[k] for k in sorted(known)),
        tuple(estimates[k][1] for k in sorted(estimates)),
        tuple(sorted(events)),
        frame,
    )
    return planning_input(config, observation)


def online_order_ids(view):
    """K_t from received facts only; no hidden scenario or offline set argument."""
    from .contracts.messages import PlanningInput

    require(isinstance(view, PlanningInput), "planning input required")
    return tuple(k.order_id for k in view.observation.known_orders if k.cancel_observed_min is None)
