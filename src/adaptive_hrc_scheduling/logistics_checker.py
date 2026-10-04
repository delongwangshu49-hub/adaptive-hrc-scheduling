"""Independent S14 event audit. Does not import the executor or its predicates."""

import math
from dataclasses import dataclass, replace

from adaptive_hrc_scheduling.contracts.codec import ContractError, as_data, decode
from adaptive_hrc_scheduling.contracts.logistics import digest
from adaptive_hrc_scheduling.domain import logistics as m


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
        decode(m.ExecutionSnapshot, as_data(snapshot))
    except (ContractError, TypeError, ValueError) as exc:
        return Report("INCOMPLETE", (Finding("R18", "SNAPSHOT", str(exc)),), None)
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
            while clock < target - 1e-12:
                calendar = {}
                for p in config.people:
                    phase = clock % p.calendar.period_h
                    selected = None
                    for w in p.calendar.windows:
                        if w.start_h <= phase < w.end_h:
                            selected = ("WAIT", clock + w.end_h - phase)
                            break
                        if phase < w.start_h:
                            selected = (
                                "REST" if phase >= p.calendar.windows[0].end_h else "OFF_SHIFT",
                                clock + w.start_h - phase,
                            )
                            break
                    calendar[p.id] = selected or (
                        "OFF_SHIFT",
                        clock + p.calendar.period_h - phase + p.calendar.windows[0].start_h,
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
            need(c.id not in command_states, "R16", "COMMAND_REEXECUTED", e)
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
            need(
                p["released"]
                and (
                    not p["cancelled"]
                    or resumed
                    and op.action == "TRANSFER"
                    or op.action in ("RETURN", "SCRAP", "RELEASE_RESERVATION")
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
                    and all(positions[i][0] == op.location for i in op.component_inputs),
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
                        load.mass_t + rig <= capacity
                        and all(a <= b for a, b in zip(load.size_m, route.max_size_m)),
                        "R08",
                        "LOAD_LIMIT",
                        e,
                    )
                if op.entity_id in stock:
                    need(stock[op.entity_id]["released"], "R12", "UNRELEASED_TRANSFER", e)
            for gate in (*op.quality_gates, *((op.wait_gate,) if op.wait_gate else ())):
                matches = [
                    g
                    for g in gates
                    if g.id == gate and g.product_id == c.product_id and g.attempt == c.attempt
                ]
                need(matches and matches[-1].result == "PASS", "R02", "GATE_NOT_PASSED", e)
            for a in op.material_inputs:
                s = stock[a.lot_id]
                need(
                    s["released"] and s["location"] == op.location,
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
            keys = set(op.equipment) | {r.person_id for r in c.roles}
            if op.entity_id:
                keys.add("ENTITY:" + op.entity_id)
            keys |= {"LOT:" + a.lot_id for a in op.material_inputs}
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
                core = [a for a in config.core_activities if a.product_id == c.product_id]
                need(
                    core
                    and op.location == "OUT1"
                    and op.entity_id == c.product_id
                    and {a.id for a in core} <= {ops[x].activity_id for x in done},
                    "R15",
                    "READY_MISSING_CORE",
                    e,
                )
                for activity in core:
                    if activity.quality_evidence:
                        need(
                            any(
                                g.id == activity.quality_evidence
                                and g.result == "PASS"
                                and g.product_id == c.product_id
                                and g.attempt == c.attempt
                                for g in gates
                            ),
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
                and op.route_id
                and proof is not None,
                "R09",
                "UNEXPECTED_PROGRESS",
                e,
            )
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
                    if op.route_id:
                        end = routes[op.route_id].points[-1]
                        point = (end.x, end.y, end.z)
                    need(
                        len(proof.position_m) == 3 and math.dist(proof.position_m, point) <= 0.001,
                        "R08",
                        "ACTUAL_POSITION",
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
                        location=op.location,
                        arrived=True,
                        identified=True,
                        released=True,
                    )
                    positions[a.lot_id] = (op.location, op.location)
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
        need(state.time_h == clock and state.revision == revision, "R18", "STATE_CLOCK_REVISION", e)
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
        need(
            len(state.intervals) == len(intervals)
            and all(
                a == b
                or all(
                    (abs(v - getattr(b, k)) < 1e-9 if isinstance(v, float) else v == getattr(b, k))
                    for k, v in as_data(a).items()
                )
                for a, b in zip(state.intervals, intervals)
            ),
            "R10",
            "HUMAN_INTERVALS",
            e,
        )
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
            occupancy[loc].add(pid if loc in ("J2", "J3") else ident)
        for run in running.values():
            rop = ops[run.command.operation_id]
            for loc in (rop.location, rop.target):
                if loc in places and rop.entity_id and rop.entity_id not in (*people, *devices):
                    occupancy[loc].add(rop.product_id if loc in ("J2", "J3") else rop.entity_id)
        need(
            all(len(items) <= places[p].capacity for p, items in occupancy.items()),
            "R05",
            "CAPACITY",
            e,
        )
    if snapshot.events:
        need(snapshot.state == snapshot.events[-1].state, "R18", "SNAPSHOT_NOT_LAST_EVENT", None)
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
            snapshot.state == initial,
            "R18",
            "MISSING_HISTORY",
            None,
        )
    ready = sum(p["ready_h"] is not None for p in products.values())
    received = sum(p["received_h"] is not None for p in products.values())
    metrics = m.OfflineEvaluation(
        "S14-ML-1.0",
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
        )
        for f in findings
    )
    return Report(
        "INCOMPLETE" if incomplete else "INVALID" if findings else "PASS", tuple(findings), metrics
    )
