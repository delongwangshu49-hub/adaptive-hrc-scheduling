"""Independent S15 event audit. Does not import the executor or its predicates."""

import math
from dataclasses import dataclass, replace
from types import SimpleNamespace

from adaptive_hrc_scheduling import production_cancel as cancellation
from adaptive_hrc_scheduling import production_rework as rework
from adaptive_hrc_scheduling import production_supports as supports
from adaptive_hrc_scheduling.contracts.codec import ContractError, as_data, decode
from adaptive_hrc_scheduling.contracts.production import digest, validate
from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.production_external import blocker as external_blocker
from adaptive_hrc_scheduling.production_external import is_external
from adaptive_hrc_scheduling.production_geometry import standing_point, validate_service
from adaptive_hrc_scheduling.production_navigation import (
    output_blocker,
    support_paths_clear,
    transport_blocker,
)


@dataclass(frozen=True)
class Finding:
    rule: str
    event_id: str
    reason: str


@dataclass(frozen=True)
class Report:
    status: str
    findings: tuple[Finding, ...]
    metrics: m.OfflineEvaluation | None


def check_run(config, snapshot):
    try:
        return _check_run(config, snapshot)
    except (KeyError, IndexError, TypeError, ValueError, StopIteration) as exc:
        return Report(
            "INCOMPLETE", (Finding("R18", "SNAPSHOT", "MALFORMED_HISTORY:" + str(exc)),), None
        )


def _check_run(config, snapshot):
    findings = []

    def need(ok, rule, reason, event):
        if not ok:
            findings.append(Finding(rule, event.id if event else "SNAPSHOT", reason))

    try:
        decode(m.Configuration, as_data(config))
        decode(m.ExecutionSnapshot, as_data(replace(snapshot, events=())))
    except (ContractError, TypeError, ValueError) as exc:
        return Report("INCOMPLETE", (Finding("R18", "SNAPSHOT", str(exc)),), None)
    try:
        validate(config)
    except ContractError as exc:
        return Report("INVALID", (Finding("R18", "SNAPSHOT", str(exc)),), None)
    need(snapshot.config_sha256 == digest(config), "R18", "CONFIG_DIGEST", None)
    ops = {o.id: o for o in config.operations}
    people = {p.id: p for p in config.people}
    devices = {d.id: d for d in config.devices}
    places = {p.id: p for p in config.places}
    routes = {r.id: r for r in config.routes}
    lots = {x.id: x for x in config.lots}
    entities = {x.id: x for x in config.entities}
    evidence = {x.id: x for x in config.evidence}

    def allowed(ids):
        return all(
            i in evidence
            and evidence[i].status == "PASS"
            and evidence[i].reference
            and (
                evidence[i].basis == "INDUSTRIAL"
                or config.purpose == "SYNTHETIC_TEST_ONLY"
                and evidence[i].basis == "SYNTHETIC_TEST"
            )
            for i in ids
        )

    stock = {
        x.id: dict(
            available=x.quantity if x.arrived else 0,
            consumed=0,
            converted=0,
            scrapped=0,
            returned=0,
            location=x.initial_location,
            arrived=x.arrived,
            identified=x.identified,
            released=x.released,
        )
        for x in config.lots
    }
    positions = {
        x.id: (x.initial_location, x.initial_location)
        for x in (*config.lots, *config.entities, *config.devices)
    }
    positions.update({x.person_id: (x.location, x.location) for x in config.person_positions})
    products = {
        p.id: dict(
            released=p.release_h == 0,
            cancelled=False,
            ready_h=0 if p.id in config.initial_ready_products else None,
            received_h=None,
        )
        for p in config.products
    }
    reserved = {}
    owners = {}
    running = {}
    done = []
    gates = []
    failed = set()
    permits = set()
    humans = {p.id: [p.initial_f, 0, p.initial_f] for p in config.people}
    intervals = []
    masses = {entity.id: 0 for entity in config.entities}
    completions = {}
    support_states = {x.root: x for x in supports.initial(config)}
    support_layouts = {x.id: x for x in config.support_layouts}

    def check_support_port(ident, location, event, owner=None):
        layout = supports.for_port(config, ident, location)
        if layout:
            observed = support_states[layout.root]
            need(not observed.clearance_people, "R04", "SUPPORT_PERSON_NOT_CLEAR", event)
            prior = support_layouts.get(observed.layout_id)
            need(supports.equivalent(prior, layout), "R08", "SUPPORT_LAYOUT_NOT_READY", event)
            need(
                owners.get("SUPPORT-ZONE:" + layout.root) in (None, owner),
                "R04",
                "SUPPORT_ZONE_BUSY",
                event,
            )

    def check_beams(proof, expected, event):
        actual = {p.index: p for p in proof.beams}
        need(
            len(proof.beams) == 22 and set(actual) == set(range(22)),
            "R18",
            "SUPPORT_READBACK_COVERAGE",
            event,
        )
        need(
            all(
                p.index in actual
                and actual[p.index].visible
                and actual[p.index].collision_enabled
                and math.dist(actual[p.index].position, p.position) <= 0.002
                for p in expected
            ),
            "R08",
            "SUPPORT_READBACK_INVALID",
            event,
        )

    def input_place(op, ident):
        return next(
            (p.place_id for p in op.input_places if p.lot_id == ident),
            next(
                (p.place_id for p in op.component_input_places if p.entity_id == ident), op.location
            ),
        )

    def output_place(op, ident):
        return next((p.place_id for p in op.output_places if p.lot_id == ident), op.location)

    def physical_mass(ident):
        return (
            stock[ident]["available"] + sum(v for k, v in reserved.items() if k[0] == ident)
            if ident in stock
            else masses[ident]
        )

    clock = 0
    revision = 0
    event_ids = set()
    command_states = {}
    resume_durations = {}
    resume_progress = {}
    resume_elapsed = {}
    motions = {}
    command_hashes = {}
    world_ids = set()
    for ordinal, e in enumerate(snapshot.events, 1):
        try:
            decode(m.ExecutionEvent, as_data(e))
        except ContractError as exc:
            return Report("INCOMPLETE", (Finding("R18", e.id, str(exc)),), None)
        need(e.sequence == ordinal and e.id not in event_ids, "R16", "EVENT_GAP_OR_DUPLICATE", e)
        event_ids.add(e.id)
        need(
            (e.run_id, e.epoch, e.config_id, e.config_sha256)
            == (snapshot.run_id, snapshot.epoch, config.id, digest(config)),
            "R18",
            "EVENT_CONTEXT",
            e,
        )
        need(
            e.occurred_sim_h >= clock and e.received_sim_h >= e.occurred_sim_h,
            "R16",
            "EVENT_TIME",
            e,
        )
        c = e.command
        if c and c.service:
            try:
                validate_service(config, c.service)
            except ContractError as exc:
                need(False, "R18", str(exc), e)
            service = c.service
            need(
                c.operation_id not in {o.id for o in config.operations},
                "R18",
                "SERVICE_ID_COLLISION",
                e,
            )
            need(
                c.operation_id not in ops or ops[c.operation_id] == service.operation,
                "R18",
                "SERVICE_REDEFINITION",
                e,
            )
            ops[c.operation_id] = service.operation
            if service.route:
                need(
                    service.route.id not in routes or routes[service.route.id] == service.route,
                    "R18",
                    "ROUTE_REDEFINITION",
                    e,
                )
                routes[service.route.id] = service.route
        op = ops.get(c.operation_id) if c else None
        if c:
            need(op is not None, "R18", "UNKNOWN_OPERATION", e)
            if op is None:
                continue
            expected_mode = (
                "MOVE"
                if op.route_id
                else "WAIT"
                if op.action == "REST"
                else "H-team"
                if len(op.roles) > 1
                else "H"
                if op.roles
                else "GATE"
            )
            expected_mode = op.production_mode or expected_mode
            need(c.mode_id == expected_mode, "R18", "COMMAND_MODE", e)
            need(
                (c.run_id, c.epoch, c.config_sha256, c.product_id, c.activity_id)
                == (snapshot.run_id, snapshot.epoch, digest(config), op.product_id, op.activity_id),
                "R18",
                "COMMAND_CONTEXT",
                e,
            )
            need(
                e.command_sha256 == digest(c)
                and (e.command_id, e.product_id, e.activity_id, e.attempt)
                == (c.id, c.product_id, c.activity_id, c.attempt),
                "R18",
                "EVENT_CORRELATION",
                e,
            )
            need(
                c.id not in command_hashes or command_hashes[c.id] == digest(c),
                "R16",
                "PAYLOAD_CONFLICT",
                e,
            )
            command_hashes[c.id] = digest(c)
        # Recompute every person's entire time interval using the configured equation.
        if e.occurred_sim_h > clock:
            need(e.kind == "CLOCK", "R10", "MISSING_CLOCK_INTERVAL", e)
            target = e.occurred_sim_h
            while clock < target:
                calendar = {}
                for p in config.people:
                    phase = clock % p.calendar.period_h
                    selected = None
                    for w in p.calendar.windows:
                        if w.start_h <= phase < w.end_h:
                            selected = ("WAIT", clock + (w.end_h - phase))
                            break
                        if phase < w.start_h:
                            selected = (
                                "REST" if phase >= p.calendar.windows[0].end_h else "OFF_SHIFT",
                                clock + (w.start_h - phase),
                            )
                            break
                    calendar[p.id] = selected or (
                        "OFF_SHIFT",
                        clock + (p.calendar.period_h - phase) + p.calendar.windows[0].start_h,
                    )
                end = min(target, *(v[1] for v in calendar.values()))
                busy = {}
                for run in running.values():
                    rop = ops[run.command.operation_id]
                    for r in run.command.roles:
                        need(r.person_id not in busy, "R04", "PERSON_OVERLAP", e)
                        busy[r.person_id] = (
                            run.command.id,
                            "EMERGENCY_HOLD" if run.status == "EXCEPTION" else rop.phase,
                        )
                for p in config.people:
                    cid, phase = busy.get(p.id, (None, calendar[p.id][0]))
                    start_f, exposure, peak = humans[p.id]
                    rate = (
                        p.recovery_rate
                        if phase in ("REST", "OFF_SHIFT")
                        else p.wait_rate
                        if phase == "WAIT"
                        else p.work_rate
                    )
                    dt = end - clock
                    if phase in ("REST", "OFF_SHIFT"):
                        final = max(0, start_f - rate * dt)
                        area = (
                            min(dt, start_f / rate) * (start_f + final) / 2
                            if rate
                            else dt * start_f
                        )
                    else:
                        final = start_f + rate * dt
                        area = dt * (start_f + final) / 2
                    need(final <= config.cap + 1e-9, "R10", "CAP_EXCEEDED", e)
                    humans[p.id] = [final, exposure + area, max(peak, final)]
                    intervals.append(
                        m.HumanInterval(p.id, cid, clock, end, phase, rate, start_f, final, area)
                    )
                clock = end
        if e.kind == "ACCEPTED" and c:
            need(rework.active(config, gates, op), "R03", "REPAIR_NOT_ACTIVATED", e)
            resumed = running.get(c.resume_of)
            if c.resume_of:
                need(
                    resumed is not None
                    and resumed.status == "EXCEPTION"
                    and resumed.held_at_h is not None,
                    "R09",
                    "NO_HELD_COMMITMENT",
                    e,
                )
                if resumed:
                    previous = resumed.command
                    need(
                        (
                            previous.operation_id,
                            previous.product_id,
                            previous.activity_id,
                            previous.attempt,
                            previous.unit_index,
                            previous.mode_id,
                            previous.roles,
                        )
                        == (
                            c.operation_id,
                            c.product_id,
                            c.activity_id,
                            c.attempt,
                            c.unit_index,
                            c.mode_id,
                            c.roles,
                        ),
                        "R09",
                        "RESUME_IDENTITY",
                        e,
                    )
                    resume_durations[c.id] = max(0, resumed.earliest_end_h - resumed.held_at_h)
                    resume_elapsed[c.id] = (
                        resumed.active_before_h + resumed.held_at_h - resumed.started_h
                    )
                    resume_progress[c.id] = (
                        motions[c.resume_of].progress
                        if c.resume_of in motions
                        else resumed.start_progress
                    )
                    if op.action == "SUPPORT_CHANGE":
                        old = support_layouts.get(support_states[op.location].layout_id)
                        target = support_layouts[op.support_layout_id]
                        count = len({p.pair_index for p in old.contacts}) if old else 0
                        count += len({p.pair_index for p in target.contacts})
                        full = 0.04 + 0.02 * count
                        resume_elapsed[c.id] = full * resume_progress[c.id]
                        resume_durations[c.id] = full - resume_elapsed[c.id]
            need(c.id not in command_states, "R16", "COMMAND_REEXECUTED", e)
            if c.resume_of:
                bound = [b for b in config.bindings if op.id in b.operation_ids]
                if bound:
                    b = bound[0]
                    a = next(a for a in config.core_activities if a.id == b.activity_id)
                    mode = next(mode for mode in a.modes if mode.id == b.mode_id)
                    unit = next((u for u in mode.units if u.id == b.unit_id), None)
                    need(unit is not None and unit.resumable, "R14", "NONRESUMABLE_UNIT_HOLD", e)
            need(
                c.issued_sim_h == clock and c.expected_revision == revision,
                "R18",
                "STALE_DISPATCH",
                e,
            )
            need(
                op.id not in done and all(x in done for x in op.prerequisites),
                "R02",
                "PREDECESSORS",
                e,
            )
            p = products[c.product_id]
            if any(a.id == op.activity_id and a.code == "KIT" for a in config.core_activities):
                raw = [
                    stock[lot.id]
                    for lot in config.lots
                    if lot.product_id == op.product_id
                    and lot.bom_id == "B-ST"
                    and lot.material == "STEEL"
                    and not lot.parent_ids
                ]
                need(
                    bool(raw)
                    and all(
                        lot["arrived"] and lot["identified"] and lot["released"] for lot in raw
                    ),
                    "R01",
                    "KIT_INPUT_NOT_RELEASED",
                    e,
                )
            if c.service and op.action in ("TRANSFER", "RETURN"):
                need(p["cancelled"], "R13", "CANCEL_SERVICE_REQUIRES_CANCELLATION", e)
                if op.action == "RETURN":
                    need(
                        op.material_inputs[0].quantity == stock[op.entity_id]["available"],
                        "R01",
                        "CANCEL_SERVICE_AVAILABLE_QUANTITY",
                        e,
                    )
            need(
                p["released"]
                and (
                    not p["cancelled"]
                    or resumed
                    and op.action == "TRANSFER"
                    or op.action in ("RETURN", "SCRAP", "RELEASE_RESERVATION")
                    or c.service is not None
                    or cancellation.disposal(config, op)
                )
                and p["received_h"] is None,
                "R13",
                "PRODUCT_UNAVAILABLE",
                e,
            )
            need(allowed(op.qualification_ids), "R03", "UNKNOWN_METHOD", e)
            need(
                {r.role_id for r in c.roles} == {r.id for r in op.roles}
                and len({r.person_id for r in c.roles}) == len(c.roles),
                "R04",
                "ROLE_COVERAGE",
                e,
            )
            rloc = {x.person_id: x.location for x in op.role_locations}
            rqual = {x.id: x.qualification for x in op.roles}
            for r in c.roles:
                need(
                    r.person_id in people
                    and rqual.get(r.role_id) in people[r.person_id].qualifications,
                    "R04",
                    "ROLE_QUALIFICATION",
                    e,
                )
                need(
                    positions.get(r.person_id, (None, None))[0] == rloc.get(r.role_id)
                    or resumed
                    and positions[r.person_id][0] == "IN_TRANSIT",
                    "R04",
                    "PERSON_NOT_PRESENT",
                    e,
                )
            for d in op.equipment:
                need(
                    d in devices and allowed((devices[d].qualification,)),
                    "R08",
                    "DEVICE_QUALIFICATION",
                    e,
                )
                if d in devices and devices[d].kind in ("FIXED", "FIXTURE"):
                    need(positions[d][0] == op.location, "R08", "FIXED_DEVICE_MOVED", e)
            need(not (set(op.equipment) & failed), "R08", "DEVICE_FAILED", e)
            if op.entity_id and not op.component_inputs:
                need(
                    positions[op.entity_id][0] == op.location
                    or resumed
                    and positions[op.entity_id][0] == "IN_TRANSIT",
                    "R01",
                    "SOURCE_MISMATCH",
                    e,
                )
            if op.component_inputs:
                need(
                    positions[op.entity_id][0] == "UNASSEMBLED"
                    and all(positions[i][0] == input_place(op, i) for i in op.component_inputs),
                    "R01",
                    "MISSING_ASSEMBLY_COMPONENT",
                    e,
                )
            need(
                all(positions[i][0] == "UNFABRICATED" for i in op.component_outputs),
                "R01",
                "COMPONENT_CREATED_TWICE",
                e,
            )
            if op.route_id:
                route = routes[op.route_id]
                need(
                    allowed((route.qualification,)) and not (set(route.segments) & failed),
                    "R08",
                    "ROUTE_UNAVAILABLE",
                    e,
                )
                if route.device_id:
                    need(
                        positions[route.device_id][0] == op.location
                        or resumed
                        and positions[route.device_id][0] == "IN_TRANSIT",
                        "R08",
                        "DEVICE_NOT_AT_SOURCE",
                        e,
                    )
                load = lots.get(op.entity_id) or entities.get(op.entity_id)
                if load:
                    need(route.device_id is not None, "R08", "NO_CARRIER", e)
                    capacity = devices[route.device_id].capacity_t if route.device_id else 0
                    rig = (
                        config.rigging_t
                        if route.device_id and devices[route.device_id].kind == "CRANE"
                        else 0
                    )
                    need(
                        physical_mass(op.entity_id) + rig <= capacity
                        and all(a <= b for a, b in zip(load.size_m, route.max_size_m)),
                        "R08",
                        "LOAD_LIMIT",
                        e,
                    )
                if op.entity_id in stock:
                    need(stock[op.entity_id]["released"], "R12", "UNRELEASED_TRANSFER", e)
            if op.wait_after:
                need(
                    op.wait_after in completions
                    and clock + 1e-10 >= completions[op.wait_after] + op.wait_h,
                    "R02",
                    "PROCESS_WAIT_TIME",
                    e,
                )
            for gate in (*op.quality_gates, *((op.wait_gate,) if op.wait_gate else ())):
                matches = rework.quality_records(config, gates, gate, c.product_id, c.attempt)
                need(matches and matches[-1].result == "PASS", "R02", "GATE_NOT_PASSED", e)
            for a in op.material_inputs:
                s = stock[a.lot_id]
                need(
                    s["released"] and s["location"] == input_place(op, a.lot_id),
                    "R12",
                    "MATERIAL_NOT_DELIVERED",
                    e,
                )
                qty = (
                    reserved.get((a.lot_id, c.product_id, c.activity_id, c.attempt), 0)
                    if op.action in ("WORK", "CONVERT")
                    else s["available"]
                )
                need(qty + 1e-9 >= a.quantity, "R01", "QUANTITY_OVERCOMMITTED", e)
            if (
                op.action == "SUPPORT_CHANGE"
                or op.route_id
                or op.material_outputs
                or op.component_outputs
                or op.component_inputs
                or is_external(op)
            ):
                geometry_state = SimpleNamespace(
                    running=tuple(running.values()),
                    motions=tuple(motions.values()),
                    supports=tuple(support_states.values()),
                    positions=tuple(m.Position(i, *p) for i, p in positions.items()),
                    lots=tuple(
                        SimpleNamespace(id=i, available=s["available"]) for i, s in stock.items()
                    ),
                    reservations=tuple(
                        SimpleNamespace(lot_id=k[0], quantity=q) for k, q in reserved.items()
                    ),
                )
            if op.material_outputs or op.component_outputs or op.component_inputs:
                blocker = output_blocker(config, geometry_state, op)
                need(blocker is None, "R08", "OUTPUT_COLLISION:" + str(blocker), e)
            if op.route_id and routes[op.route_id].device_id:
                blocker = transport_blocker(config, geometry_state, op, routes[op.route_id])
                need(blocker is None, "R08", "TRANSPORT_COLLISION:" + str(blocker), e)
            if is_external(op):
                blocker = external_blocker(config, geometry_state, op)
                need(blocker is None, "R08", "EXTERNAL_ROUTE_COLLISION:" + str(blocker), e)
            if op.action == "TRANSFER" and op.target == "DISPATCH":
                need(c.product_id in permits, "R15", "RECEIVER_NOT_READY_FOR_SHIPMENT", e)
            if op.action == "SUPPORT_CHANGE":
                layout = support_layouts[op.support_layout_id]
                need(
                    support_paths_clear(
                        config,
                        geometry_state,
                        support_layouts.get(support_states[layout.root].layout_id),
                        layout,
                        resume_elapsed.get(c.id, 0),
                    ),
                    "R08",
                    "SUPPORT_PATH_BLOCKED",
                    e,
                )
                need(
                    not supports.equivalent(
                        support_layouts.get(support_states[layout.root].layout_id), layout
                    ),
                    "R08",
                    "SUPPORT_ALREADY_CONFIGURED",
                    e,
                )
                need(
                    all(
                        loc not in places
                        or places[loc].parent != layout.root
                        or ident not in lots
                        or physical_mass(ident) <= 1e-9
                        for ident, (loc, _) in positions.items()
                    ),
                    "R05",
                    "SUPPORT_CHANGE_OCCUPIED",
                    e,
                )
                need(
                    all(
                        not any(
                            loc in places and places[loc].parent == layout.root
                            for loc in (
                                ops[r.command.operation_id].location,
                                ops[r.command.operation_id].target,
                            )
                        )
                        for r in running.values()
                        if r.command.id != c.resume_of
                    ),
                    "R05",
                    "SUPPORT_CHANGE_RESERVED",
                    e,
                )
                for device in ("FORK-01", "CART-01", "TEST1"):
                    loc = positions[device][0]
                    need(
                        loc not in places
                        or (loc != layout.root and places[loc].parent != layout.root),
                        "R05",
                        "SUPPORT_CARRIER_NOT_CLEAR",
                        e,
                    )
            if op.entity_id in lots and op.route_id:
                check_support_port(op.entity_id, op.location, e, c.resume_of or c.id)
                check_support_port(op.entity_id, op.target, e, c.resume_of or c.id)
            for amount in op.material_outputs:
                check_support_port(
                    amount.lot_id, output_place(op, amount.lot_id), e, c.resume_of or c.id
                )
            keys = set(op.equipment) | {r.person_id for r in c.roles}
            if is_external(op):
                need(not resumed, "R15", "EXTERNAL_RECEIPT_UNCERTAIN_HOLD", e)
                keys |= {"EXTERNAL-BOUNDARY", "GROUND-SPINE", "WALK-SPINE"}
            if op.action == "SUPPORT_CHANGE":
                keys |= {"SUPPORT-ZONE:" + op.location, "GROUND-SPINE", "WALK-SPINE"}
            else:
                touched = [op.location, op.target] + [
                    p.place_id for p in (*op.input_places, *op.output_places)
                ]
                keys |= {
                    "SUPPORT-ZONE:" + places[loc].parent
                    for loc in touched
                    if loc in places and places[loc].parent in supports.ROOTS
                }

            if op.entity_id:
                keys.add("ENTITY:" + op.entity_id)
            keys |= {"ENTITY:" + a.lot_id for a in (*op.material_inputs, *op.material_outputs)}
            keys |= {"ENTITY:" + i for i in op.component_inputs}
            keys |= {"ENTITY:" + i for i in op.component_outputs}
            if op.route_id:
                keys |= set(routes[op.route_id].segments)
            if op.target in places and op.entity_id not in (*people, *devices):
                keys.add("SLOT:" + op.target)
            for key in keys:
                need(
                    key not in owners
                    or resumed
                    and owners[key] == resumed.command.id
                    or key == op.release_device
                    and owners[key] == "HELD:" + c.product_id,
                    "R04",
                    "RESOURCE_OVERLAP",
                    e,
                )
                owners[key] = c.id
            if op.action == "RECEIVE_EXTERNAL":
                need(
                    p["ready_h"] is not None
                    and c.product_id in permits
                    and op.location == "DISPATCH",
                    "R15",
                    "EARLY_RECEIVED",
                    e,
                )
            if op.action == "READY":
                need(
                    abs(
                        masses[c.product_id]
                        - next(p.mass_t for p in config.products if p.id == c.product_id)
                    )
                    <= 1e-9,
                    "R01",
                    "READY_BOM_MASS",
                    e,
                )
                core = [a for a in config.core_activities if a.product_id == c.product_id]
                need(
                    core
                    and op.location == "OUT1"
                    and op.entity_id == c.product_id
                    and {a.id for a in core if a.code != "READY"}
                    <= {ops[x].activity_id for x in done},
                    "R15",
                    "READY_MISSING_CORE",
                    e,
                )
                for activity in core:
                    if activity.quality_evidence:
                        need(
                            (
                                records := rework.quality_records(
                                    config,
                                    gates,
                                    activity.quality_evidence,
                                    c.product_id,
                                    c.attempt,
                                )
                            )
                            and records[-1].result == "PASS",
                            "R15",
                            "READY_QUALITY_HOLD",
                            e,
                        )
            command_states[c.id] = "ACCEPTED"
            if resumed:
                del running[resumed.command.id]
        elif e.kind == "STARTED" and c:
            need(command_states.get(c.id) == "ACCEPTED", "R16", "START_WITHOUT_ACCEPT", e)
            duration = op.base_h
            from adaptive_hrc_scheduling.production_external import path

            if is_external(op):
                points = path(config, op)
                duration = (
                    config.setup_h
                    + config.load_h
                    + config.unload_h
                    + sum(
                        ((abs(b[0] - a[0]) + abs(b[1] - a[1])) / 0.5 + abs(b[2] - a[2]) / 0.2)
                        / 3600
                        for a, b in zip(points, points[1:])
                    )
                )
            if op.action == "SUPPORT_CHANGE":
                layout = support_layouts[op.support_layout_id]
                old = support_layouts.get(support_states[layout.root].layout_id)
                old_count = len({p.pair_index for p in old.contacts}) if old else 0
                duration = 0.04 + 0.02 * (old_count + len({p.pair_index for p in layout.contacts}))

            if op.route_id:
                rt = routes[op.route_id]
                duration += sum(
                    (
                        (abs(b.x - a.x) + abs(b.y - a.y)) / rt.speed_m_s
                        + abs(b.z - a.z) / rt.vertical_speed_m_s
                    )
                    / 3600
                    for a, b in zip(rt.points, rt.points[1:])
                )
                if op.action in ("TRANSFER", "DEPLOY_TOOL", "RETRIEVE_TOOL"):
                    duration += config.setup_h + config.load_h + config.unload_h
            duration *= 1 + op.kappa * max((humans[r.person_id][0] for r in c.roles), default=0)
            duration = resume_durations.get(c.id, duration)
            for r in c.roles:
                p = people[r.person_id]
                phase = clock % p.calendar.period_h
                need(
                    op.action == "REST"
                    or any(
                        w.start_h <= phase and phase + duration <= w.end_h + 1e-10
                        for w in p.calendar.windows
                    )
                    and clock + duration <= p.valid_until_h,
                    "R10",
                    "CALENDAR",
                    e,
                )
                need(
                    op.action == "REST"
                    or humans[p.id][0] + duration * p.work_rate <= config.cap + 1e-10,
                    "R10",
                    "UNSAFE_START",
                    e,
                )
            running[c.id] = m.Running(
                c,
                clock,
                clock + duration,
                "STARTED",
                start_progress=resume_progress.get(c.id, 0),
                active_before_h=resume_elapsed.get(c.id, 0),
            )
            command_states[c.id] = "STARTED"
        elif e.kind == "PROGRESS" and c:
            proof = e.readback
            need(
                c.id in running
                and running[c.id].status == "STARTED"
                and (op.route_id or op.action == "SUPPORT_CHANGE")
                and proof is not None,
                "R09",
                "UNEXPECTED_PROGRESS",
                e,
            )
            if proof and op.action == "SUPPORT_CHANGE" and c.id in running:
                layout = support_layouts[op.support_layout_id]
                current = support_states[layout.root]
                old = support_layouts.get(current.layout_id)
                run = running[c.id]
                elapsed = run.active_before_h + clock - run.started_h
                total = 0.04 + 0.02 * (
                    (len({p.pair_index for p in old.contacts}) if old else 0)
                    + len({p.pair_index for p in layout.contacts})
                )
                need(
                    (
                        proof.run_id,
                        proof.epoch,
                        proof.command_id,
                        proof.sample_sim_h,
                        proof.entity_id,
                    )
                    == (snapshot.run_id, snapshot.epoch, c.id, clock, None),
                    "R18",
                    "SUPPORT_PROGRESS_CONTEXT",
                    e,
                )
                need(
                    proof.location == "IN_TRANSIT"
                    and proof.support == layout.root
                    and proof.path_clear
                    and proof.device_ok
                    and proof.attached
                    and not proof.landed
                    and not proof.detached
                    and 0 <= proof.progress < 1
                    and abs(proof.progress - elapsed / total) < 1e-8,
                    "R08",
                    "SUPPORT_PROGRESS_STATE_TIME",
                    e,
                )
                need(
                    {p.person_id: p.location for p in proof.role_positions}
                    == {p.person_id: p.location for p in op.role_locations},
                    "R04",
                    "SUPPORT_PROGRESS_ROLES",
                    e,
                )
                check_beams(proof, supports.sample(config, old, layout, elapsed), e)
                support_states[layout.root] = replace(
                    current, beams=tuple(m.BeamPose(p.index, p.position) for p in proof.beams)
                )
                motions.pop(c.resume_of, None)
                motions[c.id] = proof
            if proof and op.route_id:
                route = routes[op.route_id]
                support = route.device_id or op.entity_id
                need(
                    (
                        proof.run_id,
                        proof.epoch,
                        proof.command_id,
                        proof.entity_id,
                        proof.sample_sim_h,
                    )
                    == (snapshot.run_id, snapshot.epoch, c.id, op.entity_id, clock),
                    "R18",
                    "PROGRESS_CONTEXT",
                    e,
                )
                need(
                    proof.location == "IN_TRANSIT"
                    and proof.support == support
                    and proof.attached
                    and not proof.landed
                    and not proof.detached
                    and proof.device_ok
                    and proof.path_clear,
                    "R08",
                    "TRANSIT_SUPPORT",
                    e,
                )
                prior = motions.get(c.id) or motions.get(c.resume_of)
                need(
                    (prior.progress if prior else running[c.id].start_progress)
                    <= proof.progress
                    < 1,
                    "R09",
                    "PROGRESS_REVERSED",
                    e,
                )
                points = [(p.x, p.y, p.z) for p in route.points]
                distances = []
                for a, b in zip(points, points[1:]):
                    vector = tuple(y - x for x, y in zip(a, b))
                    norm = sum(v * v for v in vector)
                    t = (
                        max(
                            0,
                            min(
                                1,
                                sum((proof.position_m[i] - a[i]) * vector[i] for i in range(3))
                                / norm,
                            ),
                        )
                        if norm
                        else 0
                    )
                    distances.append(
                        math.dist(proof.position_m, tuple(a[i] + t * vector[i] for i in range(3)))
                    )
                need(min(distances) <= 0.001, "R08", "OFF_ROUTE_SAMPLE", e)
                expected = {}
                for role in c.roles:
                    qual = next(r.qualification for r in op.roles if r.id == role.role_id)
                    mobile = op.action == "WALK" or qual in ("FORK", "CART", "TOOL")
                    loc = (
                        "IN_TRANSIT"
                        if mobile
                        else next(
                            x.location for x in op.role_locations if x.person_id == role.role_id
                        )
                    )
                    expected[role.person_id] = loc
                    if mobile:
                        positions[role.person_id] = (loc, support)
                need(
                    {p.person_id: p.location for p in proof.role_positions} == expected,
                    "R04",
                    "PROGRESS_ROLES",
                    e,
                )
                positions[op.entity_id] = ("IN_TRANSIT", support)
                if route.device_id:
                    positions[route.device_id] = ("IN_TRANSIT", route.device_id)
                if op.entity_id in stock:
                    stock[op.entity_id]["location"] = "IN_TRANSIT"
                motions.pop(c.resume_of, None)
                motions[c.id] = proof
        elif e.kind in ("REJECTED", "DEFERRED") and c:
            need(c.id not in command_states, "R16", "REJECT_AFTER_EXECUTION", e)
            command_states[c.id] = e.kind
        elif e.kind == "EXCEPTION" and c:
            need(c.id in running, "R16", "EXCEPTION_WITHOUT_START", e)
            if c.id in running:
                running[c.id] = replace(running[c.id], status="EXCEPTION", held_at_h=clock)
            command_states[c.id] = "EXCEPTION"
        elif e.kind == "COMPLETED" and c:
            need(
                e.readback is not None and e.readback.progress == 1,
                "R08",
                "INCOMPLETE_FINISH_READBACK",
                e,
            )
            if op.component_inputs:
                masses[op.entity_id] = sum(masses[i] for i in op.component_inputs)
            if op.component_outputs:
                masses[op.component_outputs[0]] = sum(a.quantity for a in op.material_inputs)
            elif op.action == "WORK" and op.entity_id in entities:
                masses[op.entity_id] += (
                    sum(a.quantity for a in op.material_inputs) - op.mass_remove_t
                )
            completions[op.id] = clock
            motions.pop(c.id, None)
            motions.pop(c.resume_of, None)
            for component in op.component_inputs:
                positions[component] = ("INCORPORATED", op.entity_id)
            for component in op.component_outputs:
                positions[component] = (op.location, op.location)
            need(
                c.id in running and running[c.id].status == "STARTED",
                "R16",
                "COMPLETION_WITHOUT_ACTIVE_START",
                e,
            )
            proof = e.readback
            need(proof is not None, "R18", "MISSING_READBACK", e)
            if proof:
                if op.action == "SUPPORT_CHANGE":
                    layout = support_layouts[op.support_layout_id]
                    check_beams(proof, supports.deployed(config, layout), e)
                    support_states[layout.root] = m.SupportState(
                        layout.root,
                        layout.id,
                        tuple(m.BeamPose(p.index, p.position) for p in proof.beams),
                        ("P1", "E1"),
                    )
                else:
                    need(not proof.beams, "R08", "UNEXPECTED_SUPPORT_READBACK", e)
                input_samples = {x.entity_id: x for x in proof.inputs}
                required_inputs = {a.lot_id: a.quantity for a in op.material_inputs}
                need(
                    len(input_samples) == len(proof.inputs)
                    and set(input_samples) == set(required_inputs) | set(op.component_inputs),
                    "R18",
                    "MISSING_INPUT_READBACK",
                    e,
                )
                for ident, sample in input_samples.items():
                    need(
                        len(sample.position_m) == 3
                        and math.dist(sample.position_m, places[input_place(op, ident)].position)
                        <= 0.001
                        and sample.visible
                        and sample.supported,
                        "R08",
                        "INVALID_INPUT_READBACK:" + ident,
                        e,
                    )
                    need(
                        sample.quantity is not None
                        and sample.quantity >= required_inputs[ident] - 1e-9
                        and abs(
                            sample.quantity
                            - stock[ident]["available"]
                            - sum(qty for key, qty in reserved.items() if key[0] == ident)
                        )
                        < 1e-9
                        if ident in required_inputs
                        else sample.quantity is None,
                        "R01",
                        "INPUT_QUANTITY:" + ident,
                        e,
                    )
                need(
                    (
                        proof.run_id,
                        proof.epoch,
                        proof.command_id,
                        proof.entity_id,
                        proof.sample_sim_h,
                    )
                    == (snapshot.run_id, snapshot.epoch, c.id, op.entity_id, clock),
                    "R18",
                    "PROOF_CONTEXT",
                    e,
                )
                need(
                    proof.device_ok
                    and proof.path_clear
                    and proof.landed
                    and proof.detached
                    and proof.support == proof.location,
                    "R08",
                    "FALSE_LANDING",
                    e,
                )
                need(proof.location == (op.target or op.location), "R08", "WRONG_DESTINATION", e)
                if proof.location in places:
                    point = places[proof.location].position
                    if op.action == "REST" and op.entity_id in people:
                        point = standing_point(config, op.entity_id, op.location)
                    if op.route_id:
                        end = routes[op.route_id].points[-1]
                        point = (end.x, end.y, end.z)
                    need(
                        len(proof.position_m) == 3 and math.dist(proof.position_m, point) <= 0.001,
                        "R08",
                        "ACTUAL_POSITION",
                        e,
                    )
                elif (
                    op.action == "RECEIVE_EXTERNAL"
                    or op.action == "RETURN"
                    and op.target == "EXTERNAL"
                ):
                    from adaptive_hrc_scheduling.production_external import path

                    need(
                        math.dist(proof.position_m, path(config, op)[-1]) <= 0.002,
                        "R08",
                        "EXTERNAL_POSITION_READBACK",
                        e,
                    )
                if op.route_id:
                    need(proof.attached, "R08", "NO_ATTACHMENT", e)
                expected_roles = {}
                qualifications = {r.id: r.qualification for r in op.roles}
                for binding in c.roles:
                    loc = (
                        op.target
                        if op.action == "WALK"
                        or op.route_id
                        and qualifications[binding.role_id] in ("FORK", "CART", "TOOL")
                        else next(
                            x.location for x in op.role_locations if x.person_id == binding.role_id
                        )
                    )
                    expected_roles[binding.person_id] = loc
                need(
                    {x.person_id: x.location for x in proof.role_positions} == expected_roles,
                    "R04",
                    "ACTUAL_ROLES",
                    e,
                )
                for pid, loc in expected_roles.items():
                    positions[pid] = (loc, loc)
            if c.id in running:
                need(clock + 1e-9 >= running[c.id].earliest_end_h, "R09", "EARLY_COMPLETION", e)
                del running[c.id]
            if op.action == "RESERVE":
                for a in op.material_inputs:
                    stock[a.lot_id]["available"] -= a.quantity
                    key = (a.lot_id, c.product_id, c.activity_id, c.attempt)
                    reserved[key] = reserved.get(key, 0) + a.quantity
            elif op.action in ("WORK", "CONVERT"):
                for a in op.material_inputs:
                    key = (a.lot_id, c.product_id, c.activity_id, c.attempt)
                    reserved[key] = reserved.get(key, 0) - a.quantity
                    stock[a.lot_id]["converted" if op.action == "CONVERT" else "consumed"] += (
                        a.quantity
                    )
                for a in op.material_outputs:
                    s = stock[a.lot_id]
                    need(not s["arrived"], "R01", "OUTPUT_CREATED_TWICE", e)
                    s.update(
                        available=a.quantity,
                        location=output_place(op, a.lot_id),
                        arrived=True,
                        identified=True,
                        released=True,
                    )
                    positions[a.lot_id] = (output_place(op, a.lot_id), output_place(op, a.lot_id))
            elif op.action in ("SCRAP", "RETURN"):
                for a in op.material_inputs:
                    stock[a.lot_id]["available"] -= a.quantity
                    stock[a.lot_id]["scrapped" if op.action == "SCRAP" else "returned"] += (
                        a.quantity
                    )
            elif op.action == "RELEASE_RESERVATION":
                for key, qty in list(reserved.items()):
                    if key[1:3] == (c.product_id, c.activity_id):
                        stock[key[0]]["available"] += qty
                        del reserved[key]
            if op.target and op.entity_id:
                positions[op.entity_id] = (op.target, op.target)
                if op.entity_id in stock:
                    stock[op.entity_id]["location"] = op.target
                if op.route_id and routes[op.route_id].device_id:
                    positions[routes[op.route_id].device_id] = (op.target, op.target)
            if op.action == "READY":
                need(not products[c.product_id]["cancelled"], "R15", "CANCELLED_READY", e)
                need(config.core_activities and op.location == "OUT1", "R15", "INCOMPLETE_READY", e)
                products[c.product_id]["ready_h"] = clock
            elif op.action == "RECEIVE_EXTERNAL":
                need(
                    not products[c.product_id]["cancelled"]
                    and proof is not None
                    and proof.departed_boundary,
                    "R15",
                    "FALSE_EXTERNAL_RECEIPT",
                    e,
                )
                products[c.product_id]["received_h"] = clock
                permits.discard(c.product_id)
            owners = {k: v for k, v in owners.items() if v != c.id}
            if op.hold_device:
                owners[op.hold_device] = "HELD:" + c.product_id
            done.append(op.id)
            if products[c.product_id]["cancelled"] and not any(
                r.command.product_id == c.product_id for r in running.values()
            ):
                for key, qty in list(reserved.items()):
                    if key[1] == c.product_id:
                        stock[key[0]]["available"] += qty
                        del reserved[key]
            command_states[c.id] = "COMPLETED"
        elif e.kind == "WORLD":
            w = e.world
            need(w is not None, "R18", "MISSING_WORLD", e)
            if w:
                need(
                    w.id not in world_ids
                    and (w.run_id, w.epoch, w.occurred_sim_h)
                    == (snapshot.run_id, snapshot.epoch, clock),
                    "R16",
                    "WORLD_DUPLICATE_OR_CONTEXT",
                    e,
                )
                world_ids.add(w.id)
                if w.kind in ("ARRIVAL", "IDENTIFY", "RELEASE"):
                    need(w.entity_id in stock, "R01", "UNKNOWN_LOT", e)
                    if w.entity_id in stock:
                        s = stock[w.entity_id]
                        need(lots[w.entity_id].product_id == w.product_id, "R01", "FOREIGN_LOT", e)
                        if w.kind == "ARRIVAL":
                            first = next(
                                (
                                    o
                                    for o in config.operations
                                    if o.entity_id == w.entity_id and o.id.endswith(".DELIVER-0")
                                ),
                                None,
                            )
                            if first:
                                need(
                                    rework.active(config, gates, first),
                                    "R03",
                                    "REPAIR_NOT_ACTIVATED",
                                    e,
                                )
                                need(
                                    first.attempt_index == 0
                                    or all(p in done for p in first.prerequisites),
                                    "R01",
                                    "REPAIR_ARRIVAL_PREDECESSORS",
                                    e,
                                )
                                for gate in first.quality_gates:
                                    records = rework.quality_records(
                                        config, gates, gate, w.product_id, first.attempt_index
                                    )
                                    need(
                                        records and records[-1].result == "PASS",
                                        "R03",
                                        "ARRIVAL_QUALITY_HOLD",
                                        e,
                                    )
                                need(
                                    all(p in done for p in first.prerequisites if ".DELIVER-" in p),
                                    "R01",
                                    "ARRIVAL_DELIVERY_PREDECESSORS",
                                    e,
                                )
                            check_support_port(w.entity_id, w.evidence_id, e)
                            need(
                                not s["arrived"] and not lots[w.entity_id].parent_ids,
                                "R01",
                                "DUPLICATE_ARRIVAL",
                                e,
                            )
                            s.update(
                                arrived=True,
                                available=lots[w.entity_id].quantity,
                                location=w.evidence_id,
                            )
                            positions[w.entity_id] = (w.evidence_id, w.evidence_id)
                        elif w.kind == "IDENTIFY":
                            need(s["arrived"], "R12", "IDENTIFY_UNARRIVED", e)
                            s["identified"] = True
                        else:
                            need(
                                s["arrived"]
                                and s["identified"]
                                and allowed((w.evidence_id,))
                                and w.result == "PASS",
                                "R12",
                                "FALSE_RELEASE",
                                e,
                            )
                            s["released"] = True
                elif w.kind in ("QUALITY", "PROCESS_RELEASE"):
                    matched = [
                        a
                        for a in config.core_activities
                        if a.product_id == w.product_id
                        and (a.quality_evidence if w.kind == "QUALITY" else a.release_evidence)
                        == w.entity_id
                    ]
                    repaired = rework.repair_gate_operation(config, w)
                    need(
                        len(matched) == 1
                        and (
                            (
                                w.attempt == 0
                                and all(
                                    i in done
                                    for b in config.bindings
                                    if matched and b.activity_id == matched[0].id
                                    for i in b.operation_ids
                                )
                            )
                            or (
                                repaired is not None
                                and repaired in done
                                and rework.initial_failure(config, gates, w.product_id)
                            )
                        ),
                        "R03",
                        "GATE_BEFORE_INSPECTION_OR_WAIT",
                        e,
                    )
                    need(
                        not any(
                            (g.id, g.product_id, g.attempt)
                            == (w.entity_id, w.product_id, w.attempt)
                            for g in gates
                        ),
                        "R03",
                        "DUPLICATE_GATE_ATTEMPT",
                        e,
                    )
                    need(
                        w.result != "PASS" or allowed((w.entity_id, w.evidence_id)),
                        "R03",
                        "FALSE_GATE_PASS",
                        e,
                    )
                    gates.append(
                        m.Gate(w.entity_id, w.product_id, w.attempt, w.result, clock, w.evidence_id)
                    )
                elif w.kind == "FAILURE":
                    failed.add(w.entity_id)
                    for key, run in list(running.items()):
                        rop = ops[run.command.operation_id]
                        if w.entity_id in (
                            *rop.equipment,
                            *(routes[rop.route_id].segments if rop.route_id else ()),
                        ):
                            if run.status != "EXCEPTION":
                                running[key] = replace(run, status="EXCEPTION", held_at_h=clock)
                elif w.kind == "REPAIR":
                    failed.discard(w.entity_id)
                elif w.kind == "CANCEL":
                    products[w.product_id]["cancelled"] = True
                    if not any(r.command.product_id == w.product_id for r in running.values()):
                        for key, qty in list(reserved.items()):
                            if key[1] == w.product_id:
                                stock[key[0]]["available"] += qty
                                del reserved[key]
                elif w.kind == "ORDER_ARRIVAL":
                    need(
                        next(p.release_h for p in config.products if p.id == w.product_id) <= clock,
                        "R14",
                        "EARLY_RELEASE",
                        e,
                    )
                    products[w.product_id]["released"] = True
                elif w.kind == "RECEIVE_PERMIT":
                    need(allowed((w.evidence_id,)) and w.result == "PASS", "R15", "FALSE_PERMIT", e)
                    permits.add(w.product_id)
        revision += 1
        state = e.state
        need(
            len(state.masses) == len(masses)
            and all(abs(x.installed_t - masses[x.entity_id]) <= 1e-9 for x in state.masses),
            "R01",
            "INSTALLED_MASS_LEDGER",
            e,
        )
        need(
            {x.operation_id: x.time_h for x in state.completion_times} == completions
            and len(state.completion_times) == len(completions),
            "R02",
            "COMPLETION_TIME_LEDGER",
            e,
        )
        if e.kind == "COMPLETED" and c and op.action == "WALK":
            support_states = {
                root: replace(
                    rack,
                    clearance_people=tuple(
                        person
                        for person in rack.clearance_people
                        if person != op.entity_id or op.target == f"CONTROL-SUPPORT-{root}-{person}"
                    ),
                )
                for root, rack in support_states.items()
            }
        need(state.time_h == clock and state.revision == revision, "R18", "STATE_CLOCK_REVISION", e)
        need(
            {x.root: x for x in state.supports} == support_states
            and len(state.supports) == len(support_states),
            "R08",
            "SUPPORT_STATE_LEDGER",
            e,
        )

        need(
            {p.id: (p.location, p.support) for p in state.positions} == positions,
            "R01",
            "POSITION_LEDGER",
            e,
        )
        need(
            {r.resource_id: r.command_id for r in state.owners} == owners
            and len(state.owners) == len(owners),
            "R04",
            "OWNERSHIP_LEDGER",
            e,
        )
        need(
            len(state.running) == len(running)
            and all(
                r.command.id in running
                and r.command == running[r.command.id].command
                and r.status == running[r.command.id].status
                and r.held_at_h == running[r.command.id].held_at_h
                and r.start_progress == running[r.command.id].start_progress
                and abs(r.active_before_h - running[r.command.id].active_before_h) < 1e-9
                and abs(r.started_h - running[r.command.id].started_h) < 1e-9
                and abs(r.earliest_end_h - running[r.command.id].earliest_end_h) < 1e-9
                for r in state.running
            ),
            "R09",
            "RUNNING_LEDGER",
            e,
        )
        need({p.command_id: p for p in state.motions} == motions, "R09", "MOTION_LEDGER", e)
        need(list(state.completed) == done, "R02", "COMPLETION_LEDGER", e)
        for active in running.values():
            active_op = ops[active.command.operation_id]
            for amount in active_op.material_inputs:
                need(
                    positions[amount.lot_id][0] == input_place(active_op, amount.lot_id),
                    "R04",
                    "ACTIVE_MATERIAL_MOVED:" + amount.lot_id,
                    e,
                )
        need(
            list(state.gates) == gates
            and set(state.failed_resources) == failed
            and set(state.receive_permits) == permits,
            "R02",
            "GATE_OR_FAILURE_LEDGER",
            e,
        )
        actual_res = {}
        for r in state.reservations:
            key = (r.lot_id, r.product_id, r.activity_id, r.attempt)
            actual_res[key] = actual_res.get(key, 0) + r.quantity
        expected_res = {k: v for k, v in reserved.items() if v > 1e-9}
        need(actual_res == expected_res, "R01", "RESERVATION_LEDGER", e)
        for lot in state.lots:
            actual = as_data(lot)
            del actual["id"]
            need(actual == stock.get(lot.id), "R01", "LOT_LEDGER", e)
            need(lot.available >= -1e-9, "R01", "NEGATIVE_STOCK", e)
        need(len(state.lots) == len(stock), "R01", "MISSING_LOT", e)
        for p in state.products:
            data = as_data(p)
            del data["product_id"]
            need(data == products.get(p.product_id), "R15", "PRODUCT_LEDGER", e)
        need(len(state.products) == len(products), "R01", "MISSING_PRODUCT", e)
        need(len(state.humans) == len(humans), "R10", "MISSING_PERSON", e)
        for h in state.humans:
            need(
                h.person_id in humans
                and all(
                    abs(a - b) < 1e-9
                    for a, b in zip((h.fatigue, h.exposure, h.peak), humans[h.person_id])
                ),
                "R10",
                "HUMAN_INTEGRAL",
                e,
            )
        need(not state.intervals, "R10", "EVENT_INTERVALS_MUST_BE_COMPACT", e)
        occupancy = {p: set() for p in places}
        for ident, (loc, _) in positions.items():
            if loc not in places or ident in (*people, *devices):
                continue
            if (
                ident in stock
                and stock[ident]["available"] + sum(v for k, v in reserved.items() if k[0] == ident)
                <= 1e-9
            ):
                continue
            pid = lots[ident].product_id if ident in lots else entities[ident].product_id
            occupancy[loc].add(pid if loc in ("J2", "J3", "PRE-OUT") else ident)
        for run in running.values():
            rop = ops[run.command.operation_id]
            for loc in (rop.location, rop.target):
                if loc in places and rop.entity_id and rop.entity_id not in (*people, *devices):
                    occupancy[loc].add(
                        rop.product_id if loc in ("J2", "J3", "PRE-OUT") else rop.entity_id
                    )
        need(
            all(len(items) <= places[p].capacity for p, items in occupancy.items()),
            "R05",
            "CAPACITY",
            e,
        )
        groups = {g.id: g for g in config.groups}
        grouped = {}
        for loc, idents in occupancy.items():
            parent = places[loc].parent
            if parent is None:
                continue
            for ident in idents:
                gid = (
                    lots[ident].group_id
                    if ident in lots
                    else entities[ident].product_id + ".GROUP-STEEL"
                )
                grouped.setdefault(parent, {}).setdefault(gid, set()).add(ident)
        for parent, contents in grouped.items():
            if parent == "BUF":
                count = len(set().union(*contents.values(), occupancy[parent]))
            elif parent in ("J2", "J3", "F1"):
                products_at = {
                    lots[i].product_id if i in lots else entities[i].product_id
                    for members in contents.values()
                    for i in members
                }
                products_at.update(occupancy[parent])
                count = len(products_at)
            else:
                count = len(contents)
            need(count <= places[parent].capacity, "R05", "GROUP_CAPACITY:" + parent, e)
            for gid, idents in contents.items():
                limit = 3.16 if parent == "PRE-OUT" else groups[gid].max_mass_t
                need(
                    sum(physical_mass(i) for i in idents) <= limit + 1e-9,
                    "R05",
                    "GROUP_MASS_LIMIT",
                    e,
                )
                need(
                    sum(i in entities or lots[i].disposition != "SCRAP" for i in idents)
                    <= groups[gid].max_packages,
                    "R05",
                    "GROUP_PACKAGE_LIMIT",
                    e,
                )
    if snapshot.events:
        need(
            replace(snapshot.state, intervals=()) == snapshot.events[-1].state,
            "R18",
            "SNAPSHOT_NOT_LAST_EVENT",
            None,
        )
    else:
        initial = m.State(
            0,
            0,
            tuple(m.LotState(id=i, **values) for i, values in stock.items()),
            (),
            tuple(m.Position(i, *value) for i, value in positions.items()),
            (),
            tuple(m.ProductState(product_id=i, **value) for i, value in products.items()),
            tuple(m.HumanState(i, *value, 0) for i, value in humans.items()),
            (),
            (),
            (),
            (),
            (),
            (),
        )
        need(
            snapshot.state
            == replace(
                initial,
                masses=tuple(m.MassState(i, 0) for i in masses),
                supports=tuple(support_states.values()),
            ),
            "R18",
            "MISSING_HISTORY",
            None,
        )
    need(
        len(snapshot.state.intervals) == len(intervals)
        and all(
            all(
                abs(v - getattr(b, k)) < 1e-9 if isinstance(v, float) else v == getattr(b, k)
                for k, v in as_data(a).items()
            )
            for a, b in zip(snapshot.state.intervals, intervals)
        ),
        "R10",
        "HUMAN_INTERVALS",
        None,
    )
    ready = sum(p["ready_h"] is not None for p in products.values())
    received = sum(p["received_h"] is not None for p in products.values())
    metrics = m.OfflineEvaluation(
        "S15-PROD-1.0",
        config.id,
        clock,
        ready,
        received,
        ready - received,
        sum(p["cancelled"] for p in products.values()),
        len(products) - ready,
        sum(h[1] for h in humans.values()),
        max((h[1] for h in humans.values()), default=0),
        "INDEPENDENT_EVENT_RECONSTRUCTION",
    )
    incomplete = any(
        f.reason
        in (
            "EVENT_GAP_OR_DUPLICATE",
            "MISSING_HISTORY",
            "MISSING_CLOCK_INTERVAL",
            "MISSING_READBACK",
            "MISSING_INPUT_READBACK",
        )
        for f in findings
    )
    return Report(
        "INCOMPLETE" if incomplete else "INVALID" if findings else "PASS", tuple(findings), metrics
    )
