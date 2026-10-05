"""Observation-only dispatch with explicit walking, empty travel, and recovery."""

import copy
import time
from dataclasses import replace

from adaptive_hrc_scheduling import production_cancel as cancellation
from adaptive_hrc_scheduling import production_supports as supports
from adaptive_hrc_scheduling.building_human import calendar_state
from adaptive_hrc_scheduling.contracts.codec import ContractError
from adaptive_hrc_scheduling.contracts.production import mode_for, validate
from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.production_backend import ProductionBackend
from adaptive_hrc_scheduling.production_geometry import route, standing_point, transport_sweeps
from adaptive_hrc_scheduling.production_navigation import clear_segment, ingress_groups, walk
from adaptive_hrc_scheduling.production_rework import active


def planning_input(config, observation, budget_ms=100):
    validate(observation, config=config)
    released = {p.product_id for p in observation.state.products if p.released}
    cancelled = {p.product_id for p in observation.state.products if p.cancelled}
    value = m.PlanningInput(
        "S15-PROD-1.0",
        config.id,
        observation,
        tuple(
            o
            for o in config.operations
            if o.product_id in released
            and active(config, observation.state.gates, o)
            and (
                o.product_id not in cancelled
                or cancellation.disposal(config, o)
                or o.action in ("RETURN", "SCRAP", "RELEASE_RESERVATION")
                or any(r.command.operation_id == o.id for r in observation.state.running)
            )
        ),
        budget_ms,
    )
    validate(value, config=config)
    return value


def choose(config, value, *, rule="EDD", sequence=0, excluded_operations=()):
    validate(value, config=config)
    if rule not in ("EDD", "SPT", "FASTEST_LEGAL"):
        raise ValueError("Unknown rule")
    start, obs = time.perf_counter(), value.observation
    world = ProductionBackend(config, run_id=obs.run_id, epoch=obs.epoch)
    world.s = obs.state
    for running in obs.state.running:
        if running.command.service:
            service = running.command.service
            world.operations[service.operation.id] = service.operation
            if service.route:
                world.routes[service.route.id] = service.route
    positions = {p.id: p.location for p in obs.state.positions}
    busy = {o.resource_id for o in obs.state.owners}
    deadlines = {p.id: p.due_h for p in config.products}
    reasons = []
    walk_cache = {}
    done = set(obs.state.completed)
    occupied_ingress = ingress_groups(config, obs.state)
    cancel_services = {
        s.operation.id: s
        for s in cancellation.candidates(config, obs.state)
        if s.operation.id not in excluded_operations
    }
    for item in cancel_services.values():
        world.operations[item.operation.id] = item.operation
        if item.route:
            world.routes[item.route.id] = item.route

    def command(op, service=None, held=None):
        service = service or cancel_services.get(op.id)
        return m.DispatchCommand(
            "S15-PROD-1.0",
            config.id,
            obs.config_sha256,
            obs.run_id,
            obs.epoch,
            f"PLAN-{obs.state.revision}-{sequence}-{op.id}",
            op.product_id,
            op.activity_id,
            op.id,
            op.attempt_index,
            op.unit_index,
            mode_for(op),
            obs.sampled_h,
            obs.state.revision,
            held.command.roles if held else tuple(m.RoleBinding(r.id, r.id) for r in op.roles),
            resume_of=held.command.id if held else None,
            service=service,
        )

    def admissible(cmd):
        candidate = copy.copy(world)
        if cmd.service:
            candidate.operations, candidate.routes = dict(world.operations), dict(world.routes)
            candidate.operations[cmd.operation_id] = cmd.service.operation
            if cmd.service.route:
                candidate.routes[cmd.service.route.id] = cmd.service.route
        try:
            candidate._admit(cmd)
            return None
        except ContractError as exc:
            return str(exc)

    def service_for(parent, entity, destination=None, rest=False):
        source = positions[entity]
        if source not in world.places or entity in busy or "ENTITY:" + entity in busy:
            return None
        person = entity in world.people
        action = "REST" if rest else "WALK" if person else "EMPTY_RETURN"
        ident = f"SERVICE-{obs.state.revision}-{entity}-{action}"
        if person:
            roles = (m.Role(entity, world.people[entity].qualifications[0]),)
            locations, equipment = (m.PersonPosition(entity, source),), ()
        else:
            ids = (
                ("Lop", "Lrig", "Lsig")
                if entity == "CR1"
                else ("P1" if entity == "FORK-01" else "E1" if entity == "CART-01" else "QA1",)
            )
            quals = (
                ("CRANE", "RIG", "SIGNAL")
                if entity == "CR1"
                else ("FORK" if entity == "FORK-01" else "CART" if entity == "CART-01" else "TOOL",)
            )
            roles = tuple(m.Role(i, q) for i, q in zip(ids, quals))
            locations = tuple(
                m.PersonPosition(i, "CONTROL-" + i if entity == "CR1" else source) for i in ids
            )
            equipment = (entity,)
            for loc in locations:
                if positions[loc.person_id] != loc.location:
                    return service_for(parent, loc.person_id, loc.location)
        rt = (
            None
            if rest
            else route(
                config,
                "ROUTE-" + ident,
                source,
                destination,
                None if person else entity,
                person=entity if person else None,
                empty=not person,
            )
        )
        if person and not rest:
            try:
                walk_key = (entity, source, destination)
                if walk_key not in walk_cache:
                    try:
                        walk_cache[walk_key] = walk(config, obs.state, entity, source, destination)
                    except ContractError as exc:
                        walk_cache[walk_key] = str(exc)
                if isinstance(walk_cache[walk_key], str):
                    raise ContractError(walk_cache[walk_key])
                rt = replace(
                    rt,
                    points=tuple(m.Point(*p) for p in walk_cache[walk_key]),
                )
            except ContractError as exc:
                reasons.append(ident + ":" + str(exc))
                return None
        op = m.Operation(
            ident,
            parent.product_id,
            ident,
            action,
            "REST"
            if rest
            else "WALK"
            if person
            else "WORK"
            if entity == "CR1"
            else "DRIVE"
            if entity == "FORK-01"
            else "PUSH",
            (),
            roles,
            locations,
            equipment,
            source,
            None if rest else destination,
            rt.id if rt else None,
            entity,
            (),
            (),
            0,
            config.min_rest_h if rest else 0,
            0,
            ("ML-METHOD",),
            (),
            None,
            None,
            None,
        )
        cmd = command(op, m.Service(op, rt))
        reason = admissible(cmd)
        if reason:
            reasons.append(ident + ":" + reason)
        if reason == "HUMAN_CAP" and not rest:
            for role in roles:
                rested = service_for(parent, role.id, rest=True)
                if rested:
                    return rested
        return cmd if reason is None else None

    unfinished = next((o for o in value.operations if o.id not in done), None)
    if unfinished is None and any(not p.released for p in obs.state.products):
        # A known but unreleased order can keep the event clock running after
        # all released work finishes. Rest still belongs to a released product;
        # this does not expose its future arrival time or prepare its material.
        unfinished = next(iter(value.operations), None)
    if unfinished is not None:
        for human in obs.state.humans:
            person = world.people[human.person_id]
            phase, shift_end = calendar_state(person, obs.sampled_h)
            if (
                phase == "WAIT"
                and human.person_id not in busy
                and human.fatigue + person.wait_rate * (shift_end - obs.sampled_h)
                > config.cap + 1e-10
            ):
                # WAIT is exposure, not recovery. Reserve an explicit existing
                # minimum rest before an idle person can cross the cap while
                # another command runs or the driver advances its event clock.
                rest = service_for(unfinished, human.person_id, rest=True)
                if rest:
                    return m.Plan(
                        "S15-PROD-1.0", config.id, obs.id, (rest,), "CANDIDATE", "IDLE_CAP_REST"
                    )

    for rack in obs.state.supports:
        if not rack.clearance_people:
            continue
        layout = world._support_layout(rack.layout_id)
        parent = next(
            (
                o
                for o in value.operations
                if o.entity_id in world.lots
                and world.lots[o.entity_id].group_id == layout.group_id
                and o.id not in done
            ),
            None,
        )
        if parent is None:
            continue
        for person in rack.clearance_people:
            cleared = service_for(parent, person, "CONTROL-" + person)
            if cleared:
                return m.Plan(
                    "S15-PROD-1.0",
                    config.id,
                    obs.id,
                    (cleared,),
                    "CANDIDATE",
                    "PREPARE:" + parent.id,
                )

    for carrier, park in (("FORK-01", "FORK-PARK"), ("CART-01", "CART-PARK")):
        location = positions[carrier]
        if location not in world.places or world.places[location].parent not in ("F1", "J3"):
            continue
        pending_pickup = any(
            o.route_id
            and world.routes[o.route_id].device_id == carrier
            and o.location == location
            and positions.get(o.entity_id) == location
            and o.id not in obs.state.completed
            and all(p in obs.state.completed for p in o.prerequisites)
            for o in value.operations
        )
        if pending_pickup:
            continue
        previous = next(
            (
                o
                for o in config.operations
                if o.route_id
                and o.target == location
                and world.routes[o.route_id].device_id == carrier
                and o.id in obs.state.completed
            ),
            None,
        )
        if previous and previous.id in {o.id for o in value.operations}:
            cleanup = service_for(previous, carrier, park)
            if cleanup:
                return m.Plan(
                    "S15-PROD-1.0",
                    config.id,
                    obs.id,
                    (cleanup,),
                    "CANDIDATE",
                    "PREPARE:" + previous.id,
                )

    def priority(o):
        stage = int(o.id.rsplit(".DELIVER-", 1)[1]) if ".DELIVER-" in o.id else -1
        point = world.places[o.location].position
        return (
            deadlines[o.product_id] if rule == "EDD" else o.base_h,
            -stage,
            point[1] if stage >= 0 else 0,
            -point[2] if stage >= 0 else 0,
            -point[0] if stage >= 0 else 0,
            o.id,
        )

    cancelled = {p.product_id for p in obs.state.products if p.cancelled}
    candidates = sorted(
        [
            o
            for o in value.operations
            if o.product_id not in cancelled
            or cancellation.disposal(config, o)
            or o.action in ("RETURN", "SCRAP", "RELEASE_RESERVATION")
            or any(r.command.operation_id == o.id for r in obs.state.running)
        ]
        + [s.operation for s in cancel_services.values()],
        key=priority,
    )

    def traffic_clearance(op):
        if op.route_id and world.routes[op.route_id].device_id in ("FORK-01", "CART-01", "TEST1"):
            rt = world.routes[op.route_id]
            p = standing_point(config, "Lsig", "CONTROL-Lsig")
            obstacle = (
                ("Lsig", (p[0] - 0.3, p[1] - 0.6, p[2]), (p[0] + 0.3, p[1] + 0.6, p[2] + 1.9)),
            )
            blocked = any(
                not clear_segment(a, b, obstacle, dimensions, margin=0)
                for path, dimensions in transport_sweeps(config, op, rt)
                for a, b in zip(path, path[1:])
            )
            if positions["Lsig"] == "CONTROL-Lsig" and blocked:
                return service_for(op, "Lsig", "CONTROL-PARK-Lsig")
        return None

    def support_preparation(parent, layout_id):
        layout = next(x for x in config.support_layouts if x.id == layout_id)
        op = supports.change_operation(
            config, layout, parent.product_id, f"SERVICE-{obs.state.revision}-{layout.root}-SUPPORT"
        )
        cmd = command(op, m.Service(op, None))
        reason = admissible(cmd)
        if reason is None:
            return cmd
        reasons.append(op.id + ":" + reason)
        if reason.startswith("SUPPORT_CARRIER_NOT_CLEAR:"):
            device = reason.split(":", 1)[1]
            return service_for(parent, device, "FORK-PARK" if device == "FORK-01" else "CART-PARK")
        if reason == "PERSON_NOT_PRESENT":
            probe = copy.copy(world)
            probe.operations = dict(world.operations, **{op.id: op})
            destinations = {p.person_id: p.location for p in op.role_locations}
            probe.s = replace(
                world.s,
                positions=tuple(
                    replace(p, location=destinations[p.id], support=destinations[p.id])
                    if p.id in destinations
                    else p
                    for p in world.s.positions
                ),
            )
            try:
                probe._admit(cmd)
            except ContractError as exc:
                reasons.append(op.id + ":" + str(exc))
                return None
            for p in op.role_locations:
                if positions[p.person_id] != p.location:
                    return service_for(parent, p.person_id, p.location)
        if reason == "HUMAN_CAP":
            for p in op.role_locations:
                rested = service_for(parent, p.person_id, rest=True)
                if rested:
                    return rested
        return None

    def support_plan(parent, layout_id):
        cmd = support_preparation(parent, layout_id)
        return (
            m.Plan("S15-PROD-1.0", config.id, obs.id, (cmd,), "CANDIDATE", "PREPARE:" + parent.id)
            if cmd
            else None
        )

    for op in candidates:
        if (time.perf_counter() - start) * 1000 > value.budget_ms:
            return m.Plan("S15-PROD-1.0", config.id, obs.id, (), "NO_PLAN_FOUND", "DECISION_BUDGET")
        held = next((r for r in obs.state.running if r.command.operation_id == op.id), None)
        if op.id in done or held and held.status != "EXCEPTION":
            continue
        if not set(op.prerequisites) <= done:
            reasons.append(op.id + ":PREDECESSORS")
            continue
        if op.entity_id in world.lots and not world._lot(op.entity_id).arrived:
            lot = world.lots[op.entity_id]
            steel = lot.bom_id == "B-ST" and lot.material == "STEEL"
            if occupied_ingress[steel] - {lot.group_id}:
                reasons.append(op.id + ":INGRESS_GROUP_BUSY")
                continue
            layout = supports.for_port(config, op.entity_id, op.location)
            if layout is not None and world.places[op.location].parent == "MEP-RECEIVE":
                current = world._support_layout(world._support_state(layout.root).layout_id)
                if not supports.equivalent(current, layout):
                    prepared = support_plan(op, layout.id)
                    if prepared:
                        return prepared
        cmd = command(op, held=held)
        reason = admissible(cmd)
        if reason is None:
            clear = traffic_clearance(op)
            if clear:
                return m.Plan(
                    "S15-PROD-1.0", config.id, obs.id, (clear,), "CANDIDATE", "PREPARE:" + op.id
                )
            return m.Plan("S15-PROD-1.0", config.id, obs.id, (cmd,), "CANDIDATE", rule)
        reasons.append(op.id + ":" + reason)
        if reason == "TRANSPORT_COLLISION:Lsig":
            clear = traffic_clearance(op)
            if clear:
                return m.Plan(
                    "S15-PROD-1.0", config.id, obs.id, (clear,), "CANDIDATE", "PREPARE:" + op.id
                )
        if reason.startswith("SUPPORT_NOT_READY:"):
            prepared = support_plan(op, reason.split(":", 1)[1])
            if prepared:
                return prepared
            continue
        if reason == "KIT_INPUT_NOT_RELEASED" and positions["FORK-01"] == "RECEIVE":
            prepared = service_for(op, "FORK-01", "STEEL")
            if prepared:
                return m.Plan(
                    "S15-PROD-1.0", config.id, obs.id, (prepared,), "CANDIDATE", "PREPARE:" + op.id
                )
        if held or reason not in ("PERSON_NOT_PRESENT", "DEVICE_NOT_AT_SOURCE", "HUMAN_CAP"):
            continue
        # Test other admission constraints before investing in preparation. This is
        # an estimate only; neither observation nor execution state is changed.
        probe = copy.copy(world)
        destinations = {p.person_id: p.location for p in op.role_locations}
        if op.route_id:
            carrier = world.routes[op.route_id].device_id
            if carrier:
                destinations[carrier] = op.location
        probe.s = replace(
            world.s,
            positions=tuple(
                replace(p, location=destinations[p.id], support=destinations[p.id])
                if p.id in destinations
                else p
                for p in world.s.positions
            ),
        )
        try:
            probe._admit(cmd)
        except ContractError as exc:
            if str(exc) == "TRANSPORT_COLLISION:Lsig":
                clear = traffic_clearance(op)
                if clear:
                    return m.Plan(
                        "S15-PROD-1.0", config.id, obs.id, (clear,), "CANDIDATE", "PREPARE:" + op.id
                    )
            if str(exc).startswith("SUPPORT_NOT_READY:"):
                prepared = support_plan(op, str(exc).split(":", 1)[1])
                if prepared:
                    return prepared
                continue
            if str(exc) != "HUMAN_CAP":
                reasons.append(op.id + ":" + str(exc))
                continue
        clear = traffic_clearance(op)
        if clear:
            return m.Plan(
                "S15-PROD-1.0", config.id, obs.id, (clear,), "CANDIDATE", "PREPARE:" + op.id
            )
        if op.route_id:
            device = world.routes[op.route_id].device_id
            if device and positions[device] != op.location:
                prepared = service_for(op, device, op.location)
                if prepared:
                    return m.Plan(
                        "S15-PROD-1.0",
                        config.id,
                        obs.id,
                        (prepared,),
                        "CANDIDATE",
                        "PREPARE:" + op.id,
                    )
                continue
        for role in op.role_locations:
            prepared = None
            if positions[role.person_id] != role.location:
                prepared = service_for(op, role.person_id, role.location)
            elif reason == "HUMAN_CAP":
                prepared = service_for(op, role.person_id, rest=True)
            if prepared:
                return m.Plan(
                    "S15-PROD-1.0",
                    config.id,
                    obs.id,
                    (prepared,),
                    "CANDIDATE",
                    "PREPARE:" + op.id,
                )
    return m.Plan(
        "S15-PROD-1.0", config.id, obs.id, (), "WAIT", ";".join(reasons) or "NO_PENDING_OPERATION"
    )
