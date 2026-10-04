"""S14 transactional quantity/location executor; observations contain no future scenario."""

import copy
import math
from dataclasses import replace

from adaptive_hrc_scheduling.building_human import calendar_state, can_work
from adaptive_hrc_scheduling.contracts.codec import ContractError, require
from adaptive_hrc_scheduling.contracts.logistics import digest, qualified, validate
from adaptive_hrc_scheduling.domain import logistics as m
from adaptive_hrc_scheduling.logistics_geometry import interpolate, motion_fraction


def changed(rows, key, value):
    return tuple(value if getattr(x, key) == getattr(value, key) else x for x in rows)


def route_hours(route):
    return sum(
        (abs(b.x - a.x) + abs(b.y - a.y)) / route.speed_m_s / 3600
        + abs(b.z - a.z) / route.vertical_speed_m_s / 3600
        for a, b in zip(route.points, route.points[1:])
    )


def role_destination(op, role_id):
    qualification = next(r.qualification for r in op.roles if r.id == role_id)
    if op.action == "WALK" or op.route_id and qualification in ("FORK", "CART", "TOOL"):
        return op.target
    return next(r.location for r in op.role_locations if r.person_id == role_id)


def initial_state(c):
    return m.State(
        0,
        0,
        tuple(
            m.LotState(
                x.id,
                x.initial_location,
                x.quantity if x.arrived else 0,
                0,
                0,
                0,
                0,
                x.arrived,
                x.identified,
                x.released,
            )
            for x in c.lots
        ),
        (),
        tuple(
            m.Position(x.id, x.initial_location, x.initial_location)
            for x in (*c.lots, *c.entities, *c.devices)
        )
        + tuple(m.Position(x.person_id, x.location, x.location) for x in c.person_positions),
        (),
        tuple(
            m.ProductState(
                p.id, p.release_h == 0, False, 0 if p.id in c.initial_ready_products else None, None
            )
            for p in c.products
        ),
        tuple(m.HumanState(p.id, p.initial_f, 0, p.initial_f, 0) for p in c.people),
        (),
        (),
        (),
        (),
        (),
        (),
    )


class LogisticsBackend:
    def __init__(self, config, *, run_id="RUN-S14", epoch=0, backend="logistics-event"):
        validate(config)
        self.config = config
        self.config_hash = digest(config)
        self.run_id, self.epoch, self.backend = run_id, epoch, backend
        self.s = initial_state(config)
        self.events = []
        self.commands = {}
        self.world_ids = {}
        self.observation_queue = []
        self.operations = {x.id: x for x in config.operations}
        self.devices = {x.id: x for x in config.devices}
        self.people = {x.id: x for x in config.people}
        self.places = {x.id: x for x in config.places}
        self.routes = {x.id: x for x in config.routes}
        self.lots = {x.id: x for x in config.lots}
        self.entities = {x.id: x for x in config.entities}
        self._capacity()

    def _put(self, **values):
        self.s = replace(self.s, **values)

    def _position(self, entity):
        return next(x for x in self.s.positions if x.id == entity)

    def _lot(self, entity):
        return next(x for x in self.s.lots if x.id == entity)

    def _product(self, pid):
        return next(x for x in self.s.products if x.product_id == pid)

    def _event(self, kind, command=None, reason="", world=None, proof=None):
        self._put(revision=self.s.revision + 1)
        e = m.ExecutionEvent(
            "S14-ML-1.0",
            self.config.id,
            self.config_hash,
            self.run_id,
            self.epoch,
            f"EV-{len(self.events) + 1}",
            len(self.events) + 1,
            command.id if command else None,
            command.product_id if command else world.product_id if world else None,
            command.activity_id if command else None,
            command.attempt if command else None,
            kind,
            self.s.time_h,
            self.s.time_h,
            0,
            reason,
            command,
            digest(command) if command else None,
            world,
            proof,
            self.s,
        )
        self.events.append(e)
        return e

    def snapshot(self):
        return m.ExecutionSnapshot(
            "S14-ML-1.0",
            self.config.id,
            self.config_hash,
            self.run_id,
            self.epoch,
            self.s,
            tuple(self.events),
        )

    def reset(self):
        self.__init__(self.config, run_id=self.run_id, epoch=self.epoch + 1, backend=self.backend)

    def _capacity(self, reserve=None):
        occupied = {p.id: set() for p in self.config.places}
        for pos in self.s.positions:
            if pos.location not in occupied or pos.id in (*self.people, *self.devices):
                continue
            if pos.id in self.lots:
                lot = self._lot(pos.id)
                reserved = sum(r.quantity for r in self.s.reservations if r.lot_id == pos.id)
                if lot.available + reserved <= 1e-9:
                    continue
            pid = (
                self.lots[pos.id].product_id
                if pos.id in self.lots
                else self.entities[pos.id].product_id
            )
            token = pid if pos.location in ("J2", "J3") else pos.id
            occupied[pos.location].add(token)
        for run in self.s.running:
            op = self.operations[run.command.operation_id]
            if op.target in occupied and op.entity_id not in (*self.people, *self.devices):
                occupied[op.target].add(
                    op.product_id if op.target in ("J2", "J3") else op.entity_id
                )
                occupied[op.location].add(
                    op.product_id if op.location in ("J2", "J3") else op.entity_id
                )
        if reserve:
            entity, location, pid = reserve
            occupied[location].add(pid if location in ("J2", "J3") else entity)
        for place, items in occupied.items():
            require(len(items) <= self.places[place].capacity, "CAPACITY:" + place)

    def _duration(self, op, command):
        duration = op.base_h
        if op.route_id:
            duration += route_hours(self.routes[op.route_id])
            if op.action in ("TRANSFER", "DEPLOY_TOOL", "RETRIEVE_TOOL"):
                duration += self.config.setup_h + self.config.load_h + self.config.unload_h
        maximum = max(
            (
                next(x.fatigue for x in self.s.humans if x.person_id == r.person_id)
                for r in command.roles
            ),
            default=0,
        )
        return duration * (1 + op.kappa * maximum)

    def _admit(self, c):
        op = self.operations[c.operation_id]
        resumed = next((r for r in self.s.running if r.command.id == c.resume_of), None)
        if c.resume_of:
            require(
                resumed is not None
                and resumed.status == "EXCEPTION"
                and resumed.held_at_h is not None,
                "NO_HELD_COMMITMENT",
            )
            require(
                (
                    resumed.command.operation_id,
                    resumed.command.product_id,
                    resumed.command.activity_id,
                    resumed.command.attempt,
                    resumed.command.unit_index,
                    resumed.command.mode_id,
                    resumed.command.roles,
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
                "RESUME_IDENTITY_CHANGED",
            )
        require(
            c.issued_sim_h == self.s.time_h and c.expected_revision == self.s.revision,
            "STALE_REVISION_OR_TIME",
        )
        p = self._product(c.product_id)
        require(
            p.released
            and (
                not p.cancelled
                or resumed
                and op.action == "TRANSFER"
                or op.action in ("RETURN", "SCRAP", "RELEASE_RESERVATION")
            )
            and p.received_h is None,
            "PRODUCT_UNAVAILABLE",
        )
        require(
            op.id not in self.s.completed and all(x in self.s.completed for x in op.prerequisites),
            "PREDECESSORS",
        )
        require(
            not any(r.command.operation_id == op.id and r != resumed for r in self.s.running),
            "ALREADY_RUNNING",
        )
        require(qualified(self.config, op.qualification_ids), "UNKNOWN_QUALIFICATION")
        for gate in op.quality_gates:
            records = [
                g
                for g in self.s.gates
                if g.id == gate and g.product_id == c.product_id and g.attempt == c.attempt
            ]
            require(records and records[-1].result == "PASS", "QUALITY_HOLD:" + gate)
        if op.wait_gate:
            wait_records = [
                g
                for g in self.s.gates
                if g.id == op.wait_gate and g.product_id == c.product_id and g.attempt == c.attempt
            ]
            require(
                wait_records and wait_records[-1].result == "PASS",
                "WAIT_RELEASE_HOLD",
            )
        locations = {r.person_id: r.location for r in op.role_locations}
        qualifications = {r.id: r.qualification for r in op.roles}
        duration = (
            max(0, resumed.earliest_end_h - resumed.held_at_h) if resumed else self._duration(op, c)
        )
        for binding in c.roles:
            person = self.people[binding.person_id]
            require(
                qualifications[binding.role_id] in person.qualifications, "PERSON_QUALIFICATION"
            )
            require(
                self._position(person.id).location == locations[binding.role_id]
                or resumed
                and self._position(person.id).location == "IN_TRANSIT",
                "PERSON_NOT_PRESENT",
            )
            require(
                op.action == "REST" or can_work(person, self.s.time_h, self.s.time_h + duration),
                "CALENDAR",
            )
            human = next(x for x in self.s.humans if x.person_id == person.id)
            require(
                op.action == "REST"
                or human.fatigue + duration * person.work_rate <= self.config.cap + 1e-10,
                "HUMAN_CAP",
            )
        for device in op.equipment:
            d = self.devices[device]
            require(qualified(self.config, (d.qualification,)), "DEVICE_QUALIFICATION")
            if d.kind in ("FIXED", "FIXTURE"):
                require(self._position(device).location == op.location, "FIXED_DEVICE_LOCATION")
            elif op.route_id and self.routes[op.route_id].device_id == device:
                require(
                    self._position(device).location == op.location
                    or resumed
                    and self._position(device).location == "IN_TRANSIT",
                    "DEVICE_NOT_AT_SOURCE",
                )
        require(not (set(op.equipment) & set(self.s.failed_resources)), "DEVICE_FAILED")
        if op.entity_id and not op.component_inputs:
            require(
                self._position(op.entity_id).location == op.location
                or resumed
                and self._position(op.entity_id).location == "IN_TRANSIT",
                "ENTITY_NOT_AT_SOURCE",
            )
        if op.component_inputs:
            require(
                self._position(op.entity_id).location == "UNASSEMBLED", "ASSEMBLY_ALREADY_EXISTS"
            )
            require(
                all(self._position(i).location == op.location for i in op.component_inputs),
                "COMPONENT_NOT_DELIVERED",
            )
        require(
            all(self._position(i).location == "UNFABRICATED" for i in op.component_outputs),
            "COMPONENT_ALREADY_EXISTS",
        )
        if op.route_id:
            route = self.routes[op.route_id]
            require(qualified(self.config, (route.qualification,)), "ROUTE_QUALIFICATION")
            require(not (set(route.segments) & set(self.s.failed_resources)), "PATH_BLOCKED")
            load = self.lots.get(op.entity_id) or self.entities.get(op.entity_id)
            if load:
                require(
                    all(a <= b for a, b in zip(load.size_m, route.max_size_m, strict=True)),
                    "UNSUPPORTED_LOAD_ENVELOPE",
                )
                require(route.device_id is not None, "NO_CARRIER")
                rig = self.config.rigging_t if self.devices[route.device_id].kind == "CRANE" else 0
                require(load.mass_t + rig <= self.devices[route.device_id].capacity_t, "OVERLOAD")
            if op.entity_id in self.lots:
                lot = self._lot(op.entity_id)
                require(lot.arrived and lot.identified and lot.released, "MATERIAL_NOT_RELEASED")
            if op.entity_id not in (*self.people, *self.devices):
                self._capacity((op.entity_id, op.target, op.product_id))
        if op.action in ("WORK", "CONVERT", "RESERVE", "RETURN", "SCRAP"):
            for amount in op.material_inputs:
                lot = self._lot(amount.lot_id)
                require(
                    lot.arrived and lot.identified and lot.released and lot.location == op.location,
                    "MATERIAL_NOT_DELIVERED_OR_RELEASED",
                )
                if op.action in ("WORK", "CONVERT"):
                    quantity = sum(
                        r.quantity
                        for r in self.s.reservations
                        if (r.lot_id, r.product_id, r.activity_id, r.attempt)
                        == (amount.lot_id, c.product_id, c.activity_id, c.attempt)
                    )
                    require(quantity >= amount.quantity - 1e-9, "MATERIAL_NOT_RESERVED")
                else:
                    require(lot.available >= amount.quantity - 1e-9, "INSUFFICIENT_MATERIAL")
        if op.action == "CONVERT":
            for amount in op.material_outputs:
                require(
                    not self._lot(amount.lot_id).arrived
                    and amount.quantity <= self.lots[amount.lot_id].quantity,
                    "OUTPUT_ALREADY_EXISTS",
                )
        if op.action == "RECEIVE_EXTERNAL":
            require(
                p.ready_h is not None
                and op.location == "DISPATCH"
                and op.target == "EXTERNAL"
                and c.product_id in self.s.receive_permits,
                "RECEIVE_NOT_READY_OR_PERMITTED",
            )
        if op.action == "READY":
            require(op.location == "OUT1" and op.entity_id == c.product_id, "READY_LOCATION")
            core = [a for a in self.config.core_activities if a.product_id == c.product_id]
            require(core, "READY_REQUIRES_CORE")
            require(
                {a.id for a in core}
                <= {o.activity_id for o in self.config.operations if o.id in self.s.completed},
                "READY_MISSING_CORE_MAPPING",
            )
            require(
                all(
                    o.id in self.s.completed
                    for o in self.config.operations
                    if o.product_id == c.product_id
                    and o.action == "WORK"
                    and o.activity_id in {a.id for a in core}
                ),
                "READY_INCOMPLETE_WORK",
            )
            require(
                all(
                    any(
                        g.id == a.quality_evidence
                        and g.result == "PASS"
                        and g.product_id == c.product_id
                        for g in self.s.gates
                    )
                    for a in core
                    if a.quality_evidence
                ),
                "READY_QUALITY_HOLD",
            )
        keys = list(op.equipment) + [r.person_id for r in c.roles]
        if op.route_id:
            keys += list(self.routes[op.route_id].segments)
        keys += ["ENTITY:" + op.entity_id] if op.entity_id else []
        keys += ["ENTITY:" + i for i in op.component_inputs]
        keys += ["ENTITY:" + i for i in op.component_outputs]
        keys += ["ENTITY:" + a.lot_id for a in (*op.material_inputs, *op.material_outputs)]
        keys = list(dict.fromkeys(keys))
        if op.target in self.places and op.entity_id not in (*self.people, *self.devices):
            keys += ["SLOT:" + op.target]
        owners = {x.resource_id: x.command_id for x in self.s.owners}
        for key in keys:
            require(
                key not in owners
                or resumed
                and owners[key] == resumed.command.id
                or key == op.release_device
                and owners[key] == "HELD:" + c.product_id,
                "RESOURCE_BUSY:" + key,
            )
        self._put(
            owners=tuple(x for x in self.s.owners if x.resource_id not in keys)
            + tuple(m.Ownership(k, c.id) for k in sorted(set(keys)))
        )
        if resumed:
            self._put(running=tuple(r for r in self.s.running if r != resumed))
        return duration

    def dispatch(self, command, *, preflight=None):
        validate(command, config=self.config)
        require((command.run_id, command.epoch) == (self.run_id, self.epoch), "STALE_EPOCH")
        fingerprint = digest(command)
        if command.id in self.commands:
            prior, receipt = self.commands[command.id]
            require(prior == fingerprint, "COMMAND_ID_PAYLOAD_CONFLICT")
            return receipt
        candidate = copy.copy(self)
        candidate.events = list(self.events)
        prior_run = next((r for r in self.s.running if r.command.id == command.resume_of), None)
        try:
            duration = candidate._admit(command)
            if preflight is not None:
                preflight(command)
        except ContractError as exc:
            reason = str(exc)
            temporary = reason.startswith(
                (
                    "CAPACITY:",
                    "RESOURCE_BUSY:",
                    "PERSON_NOT_PRESENT",
                    "DEVICE_NOT_AT_SOURCE",
                    "PATH_BLOCKED",
                    "DEVICE_FAILED",
                    "MATERIAL_NOT_DELIVERED",
                    "PREDECESSORS",
                )
            )
            receipt = self._event("DEFERRED" if temporary else "REJECTED", command, reason)
        else:
            candidate._event("ACCEPTED", command)
            candidate._put(
                running=candidate.s.running
                + (
                    m.Running(
                        command,
                        candidate.s.time_h,
                        candidate.s.time_h + duration,
                        "STARTED",
                        None,
                        next(
                            (
                                p.progress
                                for p in candidate.s.motions
                                if p.command_id == command.resume_of
                            ),
                            0,
                        ),
                        prior_run.active_before_h + prior_run.held_at_h - prior_run.started_h
                        if prior_run
                        else 0,
                    ),
                )
            )
            receipt = candidate._event("STARTED", command)
            self.s, self.events = candidate.s, candidate.events
        self.commands[command.id] = (fingerprint, receipt)
        return receipt

    def _integrate(self, until):
        while self.s.time_h < until - 1e-12:
            start = self.s.time_h
            end = min(until, *(calendar_state(p, start)[1] for p in self.config.people))
            busy = {}
            for run in self.s.running:
                op = self.operations[run.command.operation_id]
                for r in run.command.roles:
                    busy[r.person_id] = (
                        run.command.id,
                        "EMERGENCY_HOLD" if run.status == "EXCEPTION" else op.phase,
                    )
            humans, intervals = [], []
            for person in self.config.people:
                old = next(x for x in self.s.humans if x.person_id == person.id)
                command_id, phase = busy.get(person.id, (None, calendar_state(person, start)[0]))
                recovering = phase in ("REST", "OFF_SHIFT")
                rate = (
                    person.recovery_rate
                    if recovering
                    else person.wait_rate
                    if phase == "WAIT"
                    else person.work_rate
                )
                dt = end - start
                if recovering:
                    active = min(dt, old.fatigue / rate) if rate else dt
                    final = max(0, old.fatigue - rate * dt)
                    exposure = active * (old.fatigue + final) / 2
                else:
                    final = old.fatigue + rate * dt
                    exposure = dt * (old.fatigue + final) / 2
                require(final < 1, "HUMAN_STATE_OUT_OF_RANGE")
                humans.append(
                    replace(
                        old,
                        fatigue=final,
                        exposure=old.exposure + exposure,
                        peak=max(old.peak, final),
                    )
                )
                intervals.append(
                    m.HumanInterval(
                        person.id, command_id, start, end, phase, rate, old.fatigue, final, exposure
                    )
                )
            self._put(
                time_h=end, humans=tuple(humans), intervals=self.s.intervals + tuple(intervals)
            )

    def advance(self, until, *, auto_complete=True):
        require(math.isfinite(until) and until >= self.s.time_h, "TIME_REVERSED")
        if auto_complete:
            require(self.backend == "logistics-event", "ISAAC_REQUIRES_READBACK")
            while True:
                pending = [
                    r
                    for r in self.s.running
                    if r.status == "STARTED" and r.earliest_end_h <= until + 1e-12
                ]
                if not pending:
                    break
                run = min(pending, key=lambda r: (r.earliest_end_h, r.command.id))
                self._integrate(max(self.s.time_h, run.earliest_end_h))
                self._event("CLOCK")
                self.complete(run.command.id, self.light_readback(run.command))
        if until > self.s.time_h:
            self._integrate(until)
            self._event("CLOCK")
        if auto_complete and self.backend == "logistics-event":
            for run in tuple(self.s.running):
                op = self.operations[run.command.operation_id]
                if run.status != "STARTED" or not op.route_id:
                    continue
                fraction = motion_fraction(self.config, op, run, self.s.time_h)
                if fraction <= 0:
                    continue
                fraction = min(fraction, 1 - 1e-12)
                route = self.routes[op.route_id]
                proof = self.light_readback(run.command)
                roles = []
                for r in run.command.roles:
                    mobile = op.action == "WALK" or next(
                        x.qualification for x in op.roles if x.id == r.role_id
                    ) in ("FORK", "CART", "TOOL")
                    roles.append(
                        m.PersonPosition(
                            r.person_id,
                            "IN_TRANSIT"
                            if mobile
                            else next(
                                x.location for x in op.role_locations if x.person_id == r.role_id
                            ),
                        )
                    )
                point = interpolate(
                    tuple((p.x, p.y, p.z) for p in route.points),
                    fraction,
                    route.speed_m_s,
                    route.vertical_speed_m_s,
                )
                self.progress(
                    run.command.id,
                    replace(
                        proof,
                        location="IN_TRANSIT",
                        support=route.device_id or op.entity_id,
                        position_m=point,
                        role_positions=tuple(roles),
                        landed=False,
                        detached=False,
                        progress=fraction,
                    ),
                )

    def progress(self, command_id, proof):
        """Record an execution-side intermediate sample without releasing commitments."""
        from adaptive_hrc_scheduling.contracts.codec import as_data, decode

        decode(m.Readback, as_data(proof))
        run = next((r for r in self.s.running if r.command.id == command_id), None)
        require(run is not None and run.status == "STARTED", "NO_RUNNING_COMMAND")
        op = self.operations[run.command.operation_id]
        require(op.route_id is not None, "NO_MOTION")
        require(
            (proof.run_id, proof.epoch, proof.command_id, proof.entity_id, proof.sample_sim_h)
            == (self.run_id, self.epoch, command_id, op.entity_id, self.s.time_h),
            "PROGRESS_CONTEXT",
        )
        require(
            proof.source == ("ISAAC_USD" if self.backend == "isaac-usd" else "LIGHT_EXECUTOR"),
            "PROOF_SOURCE",
        )
        route = self.routes[op.route_id]
        support = route.device_id or op.entity_id
        require(
            proof.location == "IN_TRANSIT"
            and proof.support == support
            and proof.attached
            and not proof.landed
            and not proof.detached
            and proof.device_ok
            and proof.path_clear,
            "INVALID_TRANSIT_SUPPORT",
        )
        previous = max(
            (
                p.progress
                for p in self.s.motions
                if p.command_id in (command_id, run.command.resume_of)
            ),
            default=run.start_progress,
        )
        require(previous <= proof.progress < 1 and len(proof.position_m) == 3, "PROGRESS_REVERSED")
        points = [(p.x, p.y, p.z) for p in route.points]
        distances = []
        for a, b in zip(points, points[1:]):
            delta = [y - x for x, y in zip(a, b)]
            norm = sum(x * x for x in delta)
            ratio = (
                max(
                    0, min(1, sum((proof.position_m[i] - a[i]) * delta[i] for i in range(3)) / norm)
                )
                if norm
                else 0
            )
            distances.append(
                math.dist(proof.position_m, tuple(a[i] + ratio * delta[i] for i in range(3)))
            )
        require(min(distances) <= 0.001, "OFF_ROUTE_READBACK")
        mobile = {
            r.person_id
            for r in run.command.roles
            if op.action == "WALK"
            or next(x.qualification for x in op.roles if x.id == r.role_id)
            in ("FORK", "CART", "TOOL")
        }
        stationary = {
            r.person_id: next(x.location for x in op.role_locations if x.person_id == r.role_id)
            for r in run.command.roles
            if r.person_id not in mobile
        }
        require(
            {x.person_id: x.location for x in proof.role_positions}
            == {**stationary, **{p: "IN_TRANSIT" for p in mobile}},
            "PROGRESS_ROLES",
        )
        positions = changed(self.s.positions, "id", m.Position(op.entity_id, "IN_TRANSIT", support))
        for person in mobile:
            positions = changed(positions, "id", m.Position(person, "IN_TRANSIT", support))
        if route.device_id:
            positions = changed(
                positions, "id", m.Position(route.device_id, "IN_TRANSIT", route.device_id)
            )
        self._put(
            positions=positions,
            motions=tuple(
                p for p in self.s.motions if p.command_id not in (command_id, run.command.resume_of)
            )
            + (proof,),
        )
        if op.entity_id in self.lots:
            self._put(
                lots=changed(
                    self.s.lots, "id", replace(self._lot(op.entity_id), location="IN_TRANSIT")
                )
            )
        return self._event("PROGRESS", run.command, proof=proof)

    def light_readback(self, command):
        require(self.backend == "logistics-event", "LIGHT_PROOF_FORBIDDEN")
        op = self.operations[command.operation_id]
        location = op.target or op.location
        point = (
            self.places[location].position
            if location in self.places
            else self.places[op.location].position
        )
        if op.route_id:
            end = self.routes[op.route_id].points[-1]
            point = (end.x, end.y, end.z)
        roles = {r.role_id: r.person_id for r in command.roles}
        positions = tuple(
            m.PersonPosition(roles[x.person_id], role_destination(op, x.person_id))
            for x in op.role_locations
        )
        return m.Readback(
            "LIGHT_EXECUTOR",
            self.run_id,
            self.epoch,
            command.id,
            self.s.time_h,
            op.entity_id,
            location,
            location,
            point,
            positions,
            True,
            True,
            True,
            True,
            True,
            op.action == "RECEIVE_EXTERNAL",
            "LIGHT-" + command.id,
            inputs=tuple(
                m.InputReadback(
                    i,
                    self.places[self._position(i).location].position,
                    self._lot(i).available
                    + sum(r.quantity for r in self.s.reservations if r.lot_id == i)
                    if i in self.lots
                    else None,
                    True,
                    True,
                )
                for i in (*[a.lot_id for a in op.material_inputs], *op.component_inputs)
            ),
        )

    def _proof(self, run, proof):
        op = self.operations[run.command.operation_id]
        require(
            (proof.run_id, proof.epoch, proof.command_id)
            == (self.run_id, self.epoch, run.command.id),
            "PROOF_CORRELATION",
        )
        require(
            proof.source == ("ISAAC_USD" if self.backend == "isaac-usd" else "LIGHT_EXECUTOR"),
            "PROOF_SOURCE",
        )
        require(
            proof.sample_sim_h == self.s.time_h and self.s.time_h + 1e-10 >= run.earliest_end_h,
            "EARLY_OR_STALE_READBACK",
        )
        require(proof.device_ok and proof.path_clear, "EXECUTION_FAULT")
        inputs = {x.entity_id: x for x in proof.inputs}
        amounts = {a.lot_id: a.quantity for a in op.material_inputs}
        require(
            len(inputs) == len(proof.inputs)
            and set(inputs) == set(amounts) | set(op.component_inputs),
            "INPUT_READBACK_COVERAGE",
        )
        for ident, sample in inputs.items():
            require(
                len(sample.position_m) == 3
                and math.dist(sample.position_m, self.places[op.location].position) <= 0.001
                and sample.visible
                and sample.supported,
                "INPUT_READBACK_INVALID:" + ident,
            )
            require(
                sample.quantity is not None
                and sample.quantity >= amounts[ident] - 1e-9
                and abs(
                    sample.quantity
                    - self._lot(ident).available
                    - sum(r.quantity for r in self.s.reservations if r.lot_id == ident)
                )
                < 1e-9
                if ident in amounts
                else sample.quantity is None,
                "INPUT_READBACK_QUANTITY:" + ident,
            )
        require(
            proof.entity_id == op.entity_id and proof.location == (op.target or op.location),
            "ARRIVAL_FAILED",
        )
        require(
            proof.landed and proof.detached and proof.support == proof.location, "UNSUPPORTED_LOAD"
        )
        if op.route_id:
            require(proof.attached, "NO_ATTACHMENT_HISTORY")
        if proof.location in self.places:
            expected_point = self.places[proof.location].position
            if op.route_id:
                end = self.routes[op.route_id].points[-1]
                expected_point = (end.x, end.y, end.z)
            require(
                len(proof.position_m) == 3 and math.dist(proof.position_m, expected_point) <= 0.001,
                "ACTUAL_POSITION_MISMATCH",
            )
        roles = {r.role_id: r.person_id for r in run.command.roles}
        expected = {
            (roles[x.person_id], role_destination(op, x.person_id)) for x in op.role_locations
        }
        require(
            {(x.person_id, x.location) for x in proof.role_positions} == expected, "ROLE_READBACK"
        )
        if op.action == "RECEIVE_EXTERNAL":
            require(proof.departed_boundary, "NO_EXTERNAL_DEPARTURE")

    def complete(self, command_id, proof):
        run = next((r for r in self.s.running if r.command.id == command_id), None)
        require(run is not None and run.status == "STARTED", "NO_RUNNING_COMMAND")
        from adaptive_hrc_scheduling.contracts.codec import as_data, decode

        decode(m.Readback, as_data(proof))
        self._proof(run, proof)
        candidate = copy.copy(self)
        candidate.events = list(self.events)
        candidate._finish(run, proof)
        candidate._capacity()
        receipt = candidate._event("COMPLETED", run.command, proof=proof)
        self.s, self.events = candidate.s, candidate.events
        self.commands[command_id] = (digest(run.command), receipt)
        return receipt

    def _finish(self, run, proof):
        c = run.command
        op = self.operations[c.operation_id]
        require(
            all(self._lot(a.lot_id).location == op.location for a in op.material_inputs)
            and all(self._position(i).location == op.location for i in op.component_inputs),
            "INPUT_MOVED_BEFORE_COMPLETION",
        )
        for component in op.component_inputs:
            self._put(
                positions=changed(
                    self.s.positions, "id", m.Position(component, "INCORPORATED", op.entity_id)
                )
            )
        for component in op.component_outputs:
            self._put(
                positions=changed(
                    self.s.positions, "id", m.Position(component, op.location, op.location)
                )
            )
        require(
            not self._product(c.product_id).cancelled
            or op.action not in ("READY", "RECEIVE_EXTERNAL", "RESERVE"),
            "CANCELLED_BEFORE_COMMIT",
        )
        if op.action == "RESERVE":
            for a in op.material_inputs:
                lot = self._lot(a.lot_id)
                self._put(
                    lots=changed(
                        self.s.lots, "id", replace(lot, available=lot.available - a.quantity)
                    ),
                    reservations=self.s.reservations
                    + (
                        m.Reservation(a.lot_id, c.product_id, c.activity_id, c.attempt, a.quantity),
                    ),
                )
        elif op.action in ("WORK", "CONVERT"):
            for a in op.material_inputs:
                left = a.quantity
                reservations = []
                for r in self.s.reservations:
                    if (r.lot_id, r.product_id, r.activity_id, r.attempt) == (
                        a.lot_id,
                        c.product_id,
                        c.activity_id,
                        c.attempt,
                    ):
                        take = min(left, r.quantity)
                        left -= take
                        if r.quantity > take + 1e-10:
                            reservations.append(replace(r, quantity=r.quantity - take))
                    else:
                        reservations.append(r)
                require(left <= 1e-9, "RESERVATION_LOST")
                lot = self._lot(a.lot_id)
                field = "converted" if op.action == "CONVERT" else "consumed"
                self._put(
                    lots=changed(
                        self.s.lots, "id", replace(lot, **{field: getattr(lot, field) + a.quantity})
                    ),
                    reservations=tuple(reservations),
                )
            for a in op.material_outputs:
                lot = self._lot(a.lot_id)
                self._put(
                    lots=changed(
                        self.s.lots,
                        "id",
                        replace(
                            lot,
                            location=op.location,
                            available=a.quantity,
                            arrived=True,
                            identified=True,
                            released=True,
                        ),
                    ),
                    positions=changed(
                        self.s.positions, "id", m.Position(lot.id, op.location, op.location)
                    ),
                )
        elif op.action in ("RETURN", "SCRAP"):
            for a in op.material_inputs:
                lot = self._lot(a.lot_id)
                field = "returned" if op.action == "RETURN" else "scrapped"
                self._put(
                    lots=changed(
                        self.s.lots,
                        "id",
                        replace(
                            lot,
                            available=lot.available - a.quantity,
                            **{field: getattr(lot, field) + a.quantity},
                        ),
                    )
                )
        elif op.action == "RELEASE_RESERVATION":
            self._unreserve(c.product_id, c.activity_id)
        if op.target and op.entity_id:
            self._put(
                positions=changed(
                    self.s.positions, "id", m.Position(op.entity_id, op.target, op.target)
                )
            )
            if op.entity_id in self.lots:
                self._put(
                    lots=changed(
                        self.s.lots, "id", replace(self._lot(op.entity_id), location=op.target)
                    )
                )
            if op.route_id and self.routes[op.route_id].device_id:
                device = self.routes[op.route_id].device_id
                self._put(
                    positions=changed(
                        self.s.positions, "id", m.Position(device, op.target, op.target)
                    )
                )
        for role in proof.role_positions:
            self._put(
                positions=changed(
                    self.s.positions, "id", m.Position(role.person_id, role.location, role.location)
                )
            )
        p = self._product(c.product_id)
        if op.action == "READY":
            self._put(
                products=changed(self.s.products, "product_id", replace(p, ready_h=self.s.time_h))
            )
        elif op.action == "RECEIVE_EXTERNAL":
            self._put(
                products=changed(
                    self.s.products, "product_id", replace(p, received_h=self.s.time_h)
                ),
                receive_permits=tuple(x for x in self.s.receive_permits if x != c.product_id),
            )
        self._put(
            completed=self.s.completed + (op.id,),
            running=tuple(r for r in self.s.running if r != run),
            owners=tuple(x for x in self.s.owners if x.command_id != c.id),
            motions=tuple(p for p in self.s.motions if p.command_id not in (c.id, c.resume_of)),
        )
        if op.hold_device:
            self._put(owners=self.s.owners + (m.Ownership(op.hold_device, "HELD:" + c.product_id),))

    def _unreserve(self, product, activity=None):
        keep = []
        for r in self.s.reservations:
            if r.product_id == product and (activity is None or r.activity_id == activity):
                lot = self._lot(r.lot_id)
                self._put(
                    lots=changed(
                        self.s.lots, "id", replace(lot, available=lot.available + r.quantity)
                    )
                )
            else:
                keep.append(r)
        self._put(reservations=tuple(keep))

    def exception(self, command_id, reason):
        run = next(r for r in self.s.running if r.command.id == command_id)
        self._put(
            running=tuple(
                replace(r, status="EXCEPTION", held_at_h=self.s.time_h) if r == run else r
                for r in self.s.running
            )
        )
        receipt = self._event("EXCEPTION", run.command, reason)
        self.commands[command_id] = (digest(run.command), receipt)
        return receipt

    def apply_world(self, event):
        from adaptive_hrc_scheduling.contracts.codec import as_data, decode

        decode(m.WorldEvent, as_data(event))
        require((event.run_id, event.epoch) == (self.run_id, self.epoch), "STALE_EPOCH")
        if event.id in self.world_ids:
            require(self.world_ids[event.id] == digest(event), "EVENT_PAYLOAD_CONFLICT")
            return None
        require(event.occurred_sim_h == self.s.time_h, "WORLD_TIME")
        require(event.product_id in {p.id for p in self.config.products}, "UNKNOWN_PRODUCT")
        candidate = copy.copy(self)
        candidate.events = list(self.events)
        candidate._world(event)
        candidate._capacity()
        receipt = candidate._event("WORLD", world=event)
        self.s, self.events = candidate.s, candidate.events
        self.world_ids[event.id] = digest(event)
        return receipt

    def _world(self, e):
        if e.kind in ("ARRIVAL", "IDENTIFY", "RELEASE"):
            require(
                e.entity_id in self.lots and self.lots[e.entity_id].product_id == e.product_id,
                "FOREIGN_LOT",
            )
            lot = self._lot(e.entity_id)
            if e.kind == "ARRIVAL":
                require(
                    not lot.arrived and not self.lots[lot.id].parent_ids,
                    "DUPLICATE_OR_CONVERTED_ARRIVAL",
                )
                require(e.evidence_id in self.places, "ARRIVAL_PLACE")
                lot = replace(
                    lot, arrived=True, available=self.lots[lot.id].quantity, location=e.evidence_id
                )
                self._put(
                    positions=changed(
                        self.s.positions, "id", m.Position(lot.id, lot.location, lot.location)
                    )
                )
            elif e.kind == "IDENTIFY":
                require(lot.arrived, "IDENTIFY_BEFORE_ARRIVAL")
                lot = replace(lot, identified=True)
            else:
                require(
                    lot.arrived
                    and lot.identified
                    and e.result == "PASS"
                    and qualified(self.config, (e.evidence_id,)),
                    "UNQUALIFIED_MATERIAL_RELEASE",
                )
                lot = replace(lot, released=True)
            self._put(lots=changed(self.s.lots, "id", lot))
        elif e.kind in ("QUALITY", "PROCESS_RELEASE"):
            require(e.entity_id in {x.id for x in self.config.evidence}, "UNKNOWN_GATE")
            require(
                e.result != "PASS" or qualified(self.config, (e.evidence_id, e.entity_id)),
                "UNQUALIFIED_QUALITY",
            )
            self._put(
                gates=self.s.gates
                + (
                    m.Gate(
                        e.entity_id, e.product_id, e.attempt, e.result, self.s.time_h, e.evidence_id
                    ),
                )
            )
        elif e.kind == "FAILURE":
            valid = set(self.devices) | {s for r in self.config.routes for s in r.segments}
            require(e.entity_id in valid, "UNKNOWN_FAILURE_RESOURCE")
            self._put(failed_resources=tuple(sorted(set(self.s.failed_resources) | {e.entity_id})))
            for run in tuple(self.s.running):
                op = self.operations[run.command.operation_id]
                deps = set(op.equipment) | set(
                    self.routes[op.route_id].segments if op.route_id else ()
                )
                if e.entity_id in deps:
                    self._put(
                        running=tuple(
                            replace(x, status="EXCEPTION", held_at_h=self.s.time_h)
                            if x == run and x.status != "EXCEPTION"
                            else x
                            for x in self.s.running
                        )
                    )
        elif e.kind == "REPAIR":
            require(e.entity_id in self.s.failed_resources, "NOT_FAILED")
            self._put(
                failed_resources=tuple(x for x in self.s.failed_resources if x != e.entity_id)
            )
        elif e.kind == "CANCEL":
            p = self._product(e.product_id)
            require(p.received_h is None, "CANCEL_RECEIVED")
            self._put(products=changed(self.s.products, "product_id", replace(p, cancelled=True)))
            if not any(r.command.product_id == e.product_id for r in self.s.running):
                self._unreserve(e.product_id)
        elif e.kind == "ORDER_ARRIVAL":
            p = self._product(e.product_id)
            require(
                next(p.release_h for p in self.config.products if p.id == e.product_id)
                <= self.s.time_h,
                "EARLY_ORDER",
            )
            self._put(products=changed(self.s.products, "product_id", replace(p, released=True)))
        elif e.kind == "RECEIVE_PERMIT":
            require(
                qualified(self.config, (e.evidence_id,)) and e.result == "PASS",
                "RECEIVER_NOT_READY",
            )
            self._put(receive_permits=tuple(sorted(set(self.s.receive_permits) | {e.product_id})))

    def observe(self, delay_h=0):
        require(math.isfinite(delay_h) and delay_h >= 0, "OBSERVATION_DELAY")
        obs = m.PlanningObservation(
            "S14-ML-1.0",
            self.config.id,
            self.config_hash,
            self.run_id,
            self.epoch,
            f"OBS-{self.s.revision}",
            self.s.time_h,
            self.s.time_h + delay_h,
            self.s,
            tuple(e.id for e in self.events),
        )
        self.observation_queue.append(obs)
        return obs

    def deliver(self):
        due = tuple(o for o in self.observation_queue if o.received_h <= self.s.time_h)
        self.observation_queue = [o for o in self.observation_queue if o.received_h > self.s.time_h]
        return due
