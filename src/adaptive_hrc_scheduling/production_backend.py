"""S15 production quantity/location executor; observations contain no future scenario."""

import copy
import math
from dataclasses import replace
from types import SimpleNamespace

from adaptive_hrc_scheduling import production_cancel as cancellation
from adaptive_hrc_scheduling import production_rework as rework
from adaptive_hrc_scheduling import production_supports as supports
from adaptive_hrc_scheduling.building_human import calendar_state, can_work
from adaptive_hrc_scheduling.contracts.codec import ContractError, require
from adaptive_hrc_scheduling.contracts.production import digest, qualified, validate
from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.logistics_geometry import interpolate, motion_fraction
from adaptive_hrc_scheduling.production_admission import attempt_owner, completed_activity
from adaptive_hrc_scheduling.production_geometry import standing_point


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


class ProductionBackend:
    def __init__(self, config, *, run_id="RUN-S15", epoch=0, backend="logistics-event"):
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
        self.s = replace(
            self.s,
            masses=tuple(m.MassState(e.id, 0) for e in config.entities),
            supports=supports.initial(config),
            research=config.research,
        )
        self._capacity()

    def _put(self, **values):
        self.s = replace(self.s, **values)

    def _position(self, entity):
        return next(x for x in self.s.positions if x.id == entity)

    def _input_place(self, op, ident):
        return next(
            (p.place_id for p in op.input_places if p.lot_id == ident),
            next(
                (p.place_id for p in op.component_input_places if p.entity_id == ident), op.location
            ),
        )

    def _output_place(self, op, ident):
        return next((p.place_id for p in op.output_places if p.lot_id == ident), op.location)

    def _mass(self, ident):
        if ident in self.lots:
            lot = self._lot(ident)
            return lot.available + sum(r.quantity for r in self.s.reservations if r.lot_id == ident)
        return next(x.installed_t for x in self.s.masses if x.entity_id == ident)

    def _lot(self, entity):
        return next(x for x in self.s.lots if x.id == entity)

    def _product(self, pid):
        return next(x for x in self.s.products if x.product_id == pid)

    def _event(self, kind, command=None, reason="", world=None, proof=None):
        self._put(revision=self.s.revision + 1)
        e = m.ExecutionEvent(
            self.config.schema_version,
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
            replace(self.s, intervals=()),
        )
        self.events.append(e)
        return e

    def snapshot(self):
        return m.ExecutionSnapshot(
            self.config.schema_version,
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
            token = pid if pos.location in ("J2", "J3", "PRE-OUT") else pos.id
            occupied[pos.location].add(token)
        for run in self.s.running:
            op = self.operations[run.command.operation_id]
            if op.target in occupied and op.entity_id not in (*self.people, *self.devices):
                occupied[op.target].add(
                    op.product_id if op.target in ("J2", "J3", "PRE-OUT") else op.entity_id
                )
                occupied[op.location].add(
                    op.product_id if op.location in ("J2", "J3", "PRE-OUT") else op.entity_id
                )
        if reserve:
            entity, location, pid = reserve
            occupied[location].add(pid if location in ("J2", "J3", "PRE-OUT") else entity)
        for place, items in occupied.items():
            require(len(items) <= self.places[place].capacity, "CAPACITY:" + place)
        # Child supports never create additional material-group capacity.
        grouped = {}
        groups = {g.id: g for g in self.config.groups}
        for place, items in occupied.items():
            parent = self.places[place].parent
            if not parent:
                continue
            for ident in items:
                if ident not in self.lots and ident not in self.entities:
                    continue
                group = (
                    self.lots[ident].group_id
                    if ident in self.lots
                    else self.entities[ident].product_id + ".GROUP-STEEL"
                )
                grouped.setdefault(parent, {}).setdefault(group, set()).add(ident)
        for parent, occupants in grouped.items():
            if parent == "BUF":
                count = len(set().union(*occupants.values(), occupied[parent]))
            elif parent in ("J2", "J3", "F1"):
                pids = {
                    self.lots[i].product_id if i in self.lots else self.entities[i].product_id
                    for members in occupants.values()
                    for i in members
                }
                pids.update(occupied[parent])
                count = len(pids)
            else:
                count = len(occupants)
            require(count <= self.places[parent].capacity, "GROUP_CAPACITY:" + parent)
            for gid, members in occupants.items():
                group = groups[gid]
                require(
                    sum(i in self.entities or self.lots[i].disposition != "SCRAP" for i in members)
                    <= group.max_packages,
                    "GROUP_PACKAGE_LIMIT:" + gid,
                )
                require(
                    sum(self._mass(i) for i in members)
                    <= (3.16 if parent == "PRE-OUT" else group.max_mass_t) + 1e-9,
                    "GROUP_MASS_LIMIT:" + gid,
                )

    def _support_layout(self, ident):
        return next((x for x in self.config.support_layouts if x.id == ident), None)

    def _support_state(self, root):
        return next(x for x in self.s.supports if x.root == root)

    def _verified_support_elapsed(self, run):
        op = self.operations[run.command.operation_id]
        layout = self._support_layout(op.support_layout_id)
        old = self._support_layout(self._support_state(layout.root).layout_id)
        progress = next(
            (p.progress for p in self.s.motions if p.command_id == run.command.id),
            run.start_progress,
        )
        return supports.duration(self.config, old, layout) * progress

    def _support_ready(self, ident, location, owner=None):
        layout = supports.for_port(self.config, ident, location)
        if layout is None:
            return
        state = self._support_state(layout.root)
        require(
            not state.clearance_people,
            "SUPPORT_PERSON_NOT_CLEAR:"
            + (state.clearance_people[0] if state.clearance_people else "NONE"),
        )
        require(
            supports.equivalent(self._support_layout(state.layout_id), layout),
            "SUPPORT_NOT_READY:" + layout.id,
        )
        require(
            all(
                o.resource_id != "SUPPORT-ZONE:" + layout.root or o.command_id == owner
                for o in self.s.owners
            ),
            "SUPPORT_ZONE_BUSY",
        )
        require(
            all(
                a.index == b.index and math.dist(a.position, b.position) <= 0.002
                for a, b in zip(state.beams, supports.deployed(self.config, layout), strict=True)
            ),
            "SUPPORT_POSITION_NOT_READY",
        )

    def _support_empty(self, root):
        require(
            all(
                self.places.get(p.location) is None
                or self.places[p.location].parent != root
                or p.id not in self.lots
                or self._mass(p.id) <= 1e-9
                for p in self.s.positions
            ),
            "SUPPORT_CHANGE_OCCUPIED",
        )
        for run in self.s.running:
            other = self.operations[run.command.operation_id]
            if other.action == "SUPPORT_CHANGE":
                continue
            require(
                not any(
                    loc in self.places and self.places[loc].parent == root
                    for loc in (other.location, other.target)
                ),
                "SUPPORT_CHANGE_RESERVED",
            )
        for device in ("FORK-01", "CART-01", "TEST1"):
            loc = self._position(device).location
            require(
                loc not in self.places or (loc != root and self.places[loc].parent != root),
                "SUPPORT_CARRIER_NOT_CLEAR:" + device,
            )

    def _duration(self, op, command):
        from adaptive_hrc_scheduling.production_external import duration, is_external

        if is_external(op):
            return duration(self.config, op)
        if op.action == "SUPPORT_CHANGE":
            layout = self._support_layout(op.support_layout_id)
            old = self._support_layout(self._support_state(layout.root).layout_id)
            return supports.duration(self.config, old, layout)
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
        if self.config.research and op.action == "WALK" and op.target == "J2":
            require(
                not any(
                    (
                        self.operations[r.command.operation_id].branch
                        and self.operations[r.command.operation_id].branch.phase == "ROBOT"
                    )
                    for r in self.s.running
                ),
                "SIM_ENTRY_REQUIRES_STOP",
            )
        if c.service and op.action == "WALK":
            from adaptive_hrc_scheduling.production_navigation import walk_blocker

            points = [(p.x, p.y, p.z) for p in self.routes[op.route_id].points]
            require(
                walk_blocker(self.config, self.s, op.entity_id, op.location, op.target, points)
                is None,
                "DECLARED_WALK_COLLISION",
            )
        resumed = next((r for r in self.s.running if r.command.id == c.resume_of), None)
        attempt = next((a for a in self.s.mode_attempts if a.activity_id == op.activity_id), None)
        core_ids = {a.id for a in self.config.core_activities}
        committed_crew = next(
            (a for a in self.s.activity_crews if a.activity_id == op.activity_id), None
        )
        crew_required = bool(
            self.config.research
            and op.activity_id in core_ids
            and not op.branch
            and not op.handover
            and op.roles
        )
        if crew_required and committed_crew:
            require(c.roles == committed_crew.roles, "SIM_ACTIVITY_CREW_COMMITMENT")
        if op.handover:
            h = op.handover
            require(
                not c.resume_of
                and attempt is not None
                and attempt.state == "COMMITTED"
                and attempt.definition_id == h.definition_id
                and attempt.completed_units
                and attempt.completed_units[-1] == h.after_unit
                and attempt.crew[0].person_id == h.outgoing
                and not any(r.command.activity_id == h.activity_id for r in self.s.running),
                "HANDOVER_NOT_AT_MODEL_STOP",
            )
            require(
                (
                    attempt.handover is None
                    if h.phase == "HANDOVER"
                    else attempt.handover == replace(h, phase="HANDOVER")
                ),
                "HANDOVER_RESTORE_ORDER",
            )
            if h.phase == "HANDOVER":
                for pid in (h.outgoing, h.incoming):
                    person = self.people[pid]
                    human = next(x for x in self.s.humans if x.person_id == pid)
                    require(
                        can_work(person, self.s.time_h, self.s.time_h + 0.2)
                        and human.fatigue + 0.2 * person.work_rate <= self.config.cap + 1e-10,
                        "HANDOVER_RESTORE_PROTECTION",
                    )
        if op.branch:
            require(attempt is None or attempt.handover is None, "SIM_RESTORE_REQUIRED")
            require(not c.resume_of, "SIM_INTERRUPTED_ATTEMPT_HOLD")
            require(
                attempt is None
                or attempt.state == "COMMITTED"
                and attempt.definition_id == op.branch.definition_id
                and attempt.revision == op.branch.revision
                and attempt.assumption_revision == op.branch.assumption_revision,
                "SIM_ATTEMPT_IMMUTABLE",
            )
            require(attempt is not None or op.unit_index == 0, "SIM_SETUP_REQUIRED")
            require(
                attempt is None or not c.roles or c.roles == attempt.crew,
                "SIM_CREW_CHANGE_REQUIRES_HANDOFF",
            )
            if op.branch.phase == "ROBOT":
                require(
                    all(self._position(p.id).location != "J2" for p in self.people.values()),
                    "SIM_ISOLATION_EXIT_REQUIRED",
                )
                require(
                    not any(
                        self.operations[r.command.operation_id].action == "WALK"
                        and self.operations[r.command.operation_id].target == "J2"
                        for r in self.s.running
                    ),
                    "SIM_INCOMING_PERSON_DURING_ROBOT",
                )
        if c.resume_of:
            require(
                resumed is not None
                and resumed.status == "EXCEPTION"
                and resumed.held_at_h is not None,
                "NO_HELD_COMMITMENT",
            )
            bound = [b for b in self.config.bindings if op.id in b.operation_ids]
            if bound:
                binding = bound[0]
                activity = next(
                    a for a in self.config.core_activities if a.id == binding.activity_id
                )
                mode = next(mode for mode in activity.modes if mode.id == binding.mode_id)
                unit = next((u for u in mode.units if u.id == binding.unit_id), None)
                require(unit is not None and unit.resumable, "NONRESUMABLE_UNIT_HOLD")
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
        from adaptive_hrc_scheduling.production_external import blocker as external_blocker
        from adaptive_hrc_scheduling.production_external import is_external

        require(not (resumed and is_external(op)), "EXTERNAL_RECEIPT_UNCERTAIN_HOLD")
        if is_external(op):
            obstruction = external_blocker(self.config, self.s, op)
            require(obstruction is None, "EXTERNAL_ROUTE_COLLISION:" + str(obstruction))
        if c.service and op.action in ("TRANSFER", "RETURN"):
            require(p.cancelled, "CANCEL_SERVICE_REQUIRES_CANCELLATION")
            if op.action == "RETURN":
                require(
                    op.material_inputs[0].quantity == self._lot(op.entity_id).available,
                    "CANCEL_SERVICE_AVAILABLE_QUANTITY",
                )
        require(rework.active(self.config, self.s.gates, op), "REPAIR_NOT_ACTIVATED")
        require(
            p.released
            and (
                not p.cancelled
                or resumed
                and op.action == "TRANSFER"
                or op.action in ("RETURN", "SCRAP", "RELEASE_RESERVATION")
                or c.service is not None
                or cancellation.disposal(self.config, op)
            )
            and p.received_h is None,
            "PRODUCT_UNAVAILABLE",
        )
        require(
            op.id not in self.s.completed
            and all(x in self.s.completed for x in op.prerequisites)
            and all(
                completed_activity(self.config, self.s.completed, a)
                for a in op.activity_prerequisites
            ),
            "PREDECESSORS",
        )
        if any(a.id == op.activity_id and a.code == "KIT" for a in self.config.core_activities):
            raw = [
                self._lot(lot.id)
                for lot in self.config.lots
                if lot.product_id == op.product_id
                and lot.bom_id == "B-ST"
                and lot.material == "STEEL"
                and not lot.parent_ids
            ]
            require(
                raw and all(lot.arrived and lot.identified and lot.released for lot in raw),
                "KIT_INPUT_NOT_RELEASED",
            )
        require(
            not any(r.command.operation_id == op.id and r != resumed for r in self.s.running),
            "ALREADY_RUNNING",
        )
        require(qualified(self.config, op.qualification_ids), "UNKNOWN_QUALIFICATION")
        for gate in op.quality_gates:
            records = rework.quality_records(
                self.config, self.s.gates, gate, c.product_id, c.attempt
            )
            require(records and records[-1].result == "PASS", "QUALITY_HOLD:" + gate)
        if op.wait_after:
            prior = [e for e in self.s.completion_times if e.operation_id == op.wait_after]
            require(
                prior and self.s.time_h + 1e-10 >= prior[-1].time_h + op.wait_h, "PROCESS_WAIT_TIME"
            )
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
        if op.action == "SUPPORT_CHANGE":
            from adaptive_hrc_scheduling.production_navigation import support_paths_clear

            layout = self._support_layout(op.support_layout_id)
            self._support_empty(layout.root)
            old = self._support_layout(self._support_state(layout.root).layout_id)
            require(
                not supports.equivalent(old, layout),
                "SUPPORT_ALREADY_CONFIGURED",
            )
            elapsed = self._verified_support_elapsed(resumed) if resumed else 0
            require(
                support_paths_clear(self.config, self.s, old, layout, elapsed),
                "SUPPORT_PATH_BLOCKED",
            )
        locations = {r.person_id: r.location for r in op.role_locations}
        qualifications = {r.id: r.qualification for r in op.roles}
        duration = (
            max(0, resumed.earliest_end_h - resumed.held_at_h) if resumed else self._duration(op, c)
        )
        if resumed and op.action == "SUPPORT_CHANGE":
            duration = self._duration(op, c) - self._verified_support_elapsed(resumed)
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
        for device in op.equipment:
            d = self.devices[device]
            require(qualified(self.config, (d.qualification,)), "DEVICE_QUALIFICATION")
            if d.kind in ("FIXED", "FIXTURE"):
                require(self._position(device).location == op.location, "FIXED_DEVICE_LOCATION")
            elif d.kind == "TOOL" and not op.route_id:
                require(self._position(device).location == "TEST-USE", "TOOL_NOT_DEPLOYED")
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
                all(
                    self._position(i).location == self._input_place(op, i)
                    for i in op.component_inputs
                ),
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
                if op.entity_id in self.entities and self.entities[op.entity_id].kind == "PRODUCT":
                    require(
                        not any(
                            x.resource_id == "TEST1" and x.command_id == "HELD:" + op.product_id
                            for x in self.s.owners
                        ),
                        "WATER_OR_TOOL_HELD",
                    )
                require(
                    all(a <= b for a, b in zip(load.size_m, route.max_size_m, strict=True)),
                    "UNSUPPORTED_LOAD_ENVELOPE",
                )
                require(route.device_id is not None, "NO_CARRIER")
                rig = self.config.rigging_t if self.devices[route.device_id].kind == "CRANE" else 0
                require(
                    self._mass(op.entity_id) + rig <= self.devices[route.device_id].capacity_t,
                    "OVERLOAD",
                )
            if op.entity_id in self.lots:
                lot = self._lot(op.entity_id)
                require(lot.arrived and lot.identified and lot.released, "MATERIAL_NOT_RELEASED")
            if op.entity_id not in (*self.people, *self.devices):
                self._capacity((op.entity_id, op.target, op.product_id))
        if op.action in ("WORK", "CONVERT", "RESERVE", "RETURN", "SCRAP"):
            for amount in op.material_inputs:
                lot = self._lot(amount.lot_id)
                require(
                    lot.arrived
                    and lot.identified
                    and lot.released
                    and lot.location == self._input_place(op, amount.lot_id),
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
        if op.entity_id in self.lots and op.route_id:
            self._support_ready(op.entity_id, op.location, c.resume_of or c.id)
            self._support_ready(op.entity_id, op.target, c.resume_of or c.id)
        for amount in op.material_outputs:
            self._support_ready(
                amount.lot_id, self._output_place(op, amount.lot_id), c.resume_of or c.id
            )
        from adaptive_hrc_scheduling.production_navigation import output_blocker

        blocker = output_blocker(self.config, self.s, op)
        require(blocker is None, "OUTPUT_COLLISION:" + str(blocker))
        if op.action == "TRANSFER" and op.target == "DISPATCH":
            require(c.product_id in self.s.receive_permits, "RECEIVER_NOT_READY_FOR_SHIPMENT")
        if op.action == "RECEIVE_EXTERNAL":
            require(
                p.ready_h is not None
                and op.location == "DISPATCH"
                and op.target == "EXTERNAL"
                and c.product_id in self.s.receive_permits,
                "RECEIVE_NOT_READY_OR_PERMITTED",
            )
        if op.action == "READY":
            require(
                abs(
                    self._mass(c.product_id)
                    - next(p.mass_t for p in self.config.products if p.id == c.product_id)
                )
                <= 1e-9,
                "READY_BOM_MASS",
            )
            require(op.location == "OUT1" and op.entity_id == c.product_id, "READY_LOCATION")
            core = [a for a in self.config.core_activities if a.product_id == c.product_id]
            require(core, "READY_REQUIRES_CORE")
            require(
                {a.id for a in core if a.code != "READY"}
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
                    and (
                        not o.branch
                        or any(
                            a.activity_id == o.activity_id
                            and a.definition_id == o.branch.definition_id
                            for a in self.s.mode_attempts
                        )
                    )
                ),
                "READY_INCOMPLETE_WORK",
            )
            require(
                all(
                    (
                        records := rework.quality_records(
                            self.config, self.s.gates, a.quality_evidence, c.product_id, c.attempt
                        )
                    )
                    and records[-1].result == "PASS"
                    for a in core
                    if a.quality_evidence
                ),
                "READY_QUALITY_HOLD",
            )
        keys = list(op.equipment) + [r.person_id for r in c.roles]
        if is_external(op):
            keys += ["EXTERNAL-BOUNDARY", "GROUND-SPINE", "WALK-SPINE"]
        if op.action == "SUPPORT_CHANGE":
            keys += ["SUPPORT-ZONE:" + op.location, "GROUND-SPINE", "WALK-SPINE"]
        else:
            touched = [op.location, op.target] + [
                p.place_id for p in (*op.input_places, *op.output_places)
            ]
            keys += [
                "SUPPORT-ZONE:" + self.places[loc].parent
                for loc in touched
                if loc in self.places and self.places[loc].parent in supports.ROOTS
            ]

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
                and owners[key] == "HELD:" + c.product_id
                or op.branch
                and key in (*op.hold_resources, *op.release_resources)
                and owners[key] == attempt_owner(op)
                or op.handover
                and key in op.equipment
                and owners[key] == f"ATTEMPT:{op.handover.activity_id}:0:v1",
                "RESOURCE_BUSY:" + key,
            )
        # Human limits are checked after physical feasibility so preparation
        # cannot conceal an unavailable load or occupied destination.
        if op.route_id and self.routes[op.route_id].device_id:
            from adaptive_hrc_scheduling.production_navigation import transport_blocker

            blocker = transport_blocker(self.config, self.s, op, self.routes[op.route_id])
            require(blocker is None, "TRANSPORT_COLLISION:" + str(blocker))
        for binding in c.roles:
            person = self.people[binding.person_id]
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
        self._put(
            owners=tuple(x for x in self.s.owners if x.resource_id not in keys)
            + tuple(m.Ownership(k, c.id) for k in sorted(set(keys)))
        )
        if crew_required and committed_crew is None:
            self._put(
                activity_crews=self.s.activity_crews + (m.ActivityCrew(op.activity_id, c.roles),)
            )
        if op.branch and attempt is None:
            self._put(
                mode_attempts=self.s.mode_attempts
                + (
                    m.ModeAttempt(
                        op.activity_id,
                        c.attempt,
                        op.branch.definition_id,
                        op.branch.revision,
                        op.branch.output_revision,
                        op.branch.assumption_revision,
                        c.roles,
                        (),
                        self.s.revision,
                        "COMMITTED",
                    ),
                )
            )
        if resumed:
            self._put(running=tuple(r for r in self.s.running if r != resumed))
        return duration

    def dispatch(self, command, *, preflight=None):
        if command.service:
            validate(command, config=self.config)
            op = command.service.operation
            self.operations[op.id] = op
            if command.service.route:
                self.routes[command.service.route.id] = command.service.route
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
                        self._verified_support_elapsed(prior_run)
                        if prior_run
                        and self.operations[command.operation_id].action == "SUPPORT_CHANGE"
                        else prior_run.active_before_h + prior_run.held_at_h - prior_run.started_h
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
        while self.s.time_h < until:
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
                due = max(self.s.time_h, run.earliest_end_h)
                if due > self.s.time_h:
                    self._integrate(due)
                    self._event("CLOCK")
                self.complete(run.command.id, self.light_readback(run.command))
        if until > self.s.time_h:
            self._integrate(until)
            self._event("CLOCK")
        if auto_complete and self.backend == "logistics-event":
            for run in tuple(self.s.running):
                op = self.operations[run.command.operation_id]
                if run.status == "STARTED" and op.action == "SUPPORT_CHANGE":
                    layout = self._support_layout(op.support_layout_id)
                    old = self._support_layout(self._support_state(layout.root).layout_id)
                    elapsed = run.active_before_h + self.s.time_h - run.started_h
                    full = supports.duration(self.config, old, layout)
                    proof = self.light_readback(run.command)
                    self.progress(
                        run.command.id,
                        replace(
                            proof,
                            location="IN_TRANSIT",
                            support=layout.root,
                            landed=False,
                            detached=False,
                            progress=min(elapsed / full, 1 - 1e-12),
                            beams=tuple(
                                m.BeamReadback(p.index, p.position, True, True)
                                for p in supports.sample(self.config, old, layout, elapsed)
                            ),
                        ),
                    )
                    continue
                if run.status != "STARTED" or not op.route_id:
                    continue
                fraction = motion_fraction(
                    SimpleNamespace(
                        routes=tuple(self.routes.values()),
                        setup_h=self.config.setup_h,
                        load_h=self.config.load_h,
                        unload_h=self.config.unload_h,
                    ),
                    op,
                    run,
                    self.s.time_h,
                )
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
        if op.action == "SUPPORT_CHANGE":
            return self._support_progress(run, proof)
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
        if op.action == "REST" and op.entity_id in self.people:
            point = standing_point(self.config, op.entity_id, op.location)
        if op.route_id:
            end = self.routes[op.route_id].points[-1]
            point = (end.x, end.y, end.z)
        from adaptive_hrc_scheduling.production_external import is_external, path

        if is_external(op):
            point = path(self.config, op)[-1]
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
            op.action == "RECEIVE_EXTERNAL" or op.action == "RETURN" and op.target == "EXTERNAL",
            "LIGHT-" + command.id,
            progress=1,
            branch=op.branch,
            handover=op.handover,
            isolated=all(self._position(p).location != "J2" for p in self.people)
            if op.branch
            else None,
            robot_stopped=True if op.branch else None,
            stage_owners=tuple(m.Ownership(i, attempt_owner(op)) for i in op.equipment)
            if op.branch
            else (),
            beams=tuple(
                m.BeamReadback(p.index, p.position, True, True)
                for p in supports.deployed(self.config, self._support_layout(op.support_layout_id))
            )
            if op.action == "SUPPORT_CHANGE"
            else (),
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

    def _support_progress(self, run, proof):
        op = self.operations[run.command.operation_id]
        layout = self._support_layout(op.support_layout_id)
        current = self._support_state(layout.root)
        old = self._support_layout(current.layout_id)
        elapsed = run.active_before_h + self.s.time_h - run.started_h
        full = supports.duration(self.config, old, layout)
        require(
            (proof.run_id, proof.epoch, proof.command_id, proof.sample_sim_h, proof.entity_id)
            == (self.run_id, self.epoch, run.command.id, self.s.time_h, None),
            "SUPPORT_PROGRESS_CONTEXT",
        )
        require(
            proof.source == ("ISAAC_USD" if self.backend == "isaac-usd" else "LIGHT_EXECUTOR"),
            "PROOF_SOURCE",
        )
        require(
            proof.location == "IN_TRANSIT"
            and proof.support == layout.root
            and proof.device_ok
            and proof.path_clear
            and proof.attached
            and not proof.landed
            and not proof.detached,
            "SUPPORT_PROGRESS_STATE",
        )
        require(
            0 <= proof.progress < 1 and abs(proof.progress - elapsed / full) < 1e-8,
            "SUPPORT_PROGRESS_TIME",
        )
        require(
            {p.person_id: p.location for p in proof.role_positions}
            == {p.person_id: p.location for p in op.role_locations},
            "SUPPORT_PROGRESS_ROLES",
        )
        self._support_proof(proof, supports.sample(self.config, old, layout, elapsed))
        updated = replace(
            current, beams=tuple(m.BeamPose(p.index, p.position) for p in proof.beams)
        )
        self._put(
            supports=tuple(updated if x.root == layout.root else x for x in self.s.supports),
            motions=tuple(
                p
                for p in self.s.motions
                if p.command_id not in (run.command.id, run.command.resume_of)
            )
            + (proof,),
        )
        return self._event("PROGRESS", run.command, proof=proof)

    def _support_proof(self, proof, expected):
        require(
            len(proof.beams) == 22 and {p.index for p in proof.beams} == set(range(22)),
            "SUPPORT_READBACK_COVERAGE",
        )
        actual = {p.index: p for p in proof.beams}
        require(
            all(
                actual[p.index].visible
                and actual[p.index].collision_enabled
                and math.dist(actual[p.index].position, p.position) <= 0.002
                for p in expected
            ),
            "SUPPORT_READBACK_INVALID",
        )

    def _proof(self, run, proof):
        require(
            proof.branch == self.operations[run.command.operation_id].branch, "SIM_STAGE_READBACK"
        )
        op = self.operations[run.command.operation_id]
        require(proof.handover == op.handover, "HANDOVER_READBACK")
        if op.branch:
            require(
                proof.stage_owners
                == tuple(m.Ownership(i, attempt_owner(op)) for i in op.equipment),
                "SIM_STAGE_OWNERS_READBACK",
            )
            require(op.branch.phase != "ROBOT" or proof.isolated is True, "SIM_ISOLATION_READBACK")
            require(
                op.production_mode != "HR-seq" or proof.robot_stopped is True,
                "SIM_STOP_CONFIRMATION_READBACK",
            )
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
        require(proof.progress == 1, "INCOMPLETE_FINISH_READBACK")
        if op.action == "SUPPORT_CHANGE":
            expected = supports.deployed(self.config, self._support_layout(op.support_layout_id))
            self._support_proof(proof, expected)
        else:
            require(not proof.beams, "UNEXPECTED_SUPPORT_READBACK")
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
                and math.dist(sample.position_m, self.places[self._input_place(op, ident)].position)
                <= 0.001
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
            if op.action == "REST" and op.entity_id in self.people:
                expected_point = standing_point(self.config, op.entity_id, op.location)
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
        if op.action == "RECEIVE_EXTERNAL" or op.action == "RETURN" and op.target == "EXTERNAL":
            require(proof.departed_boundary, "NO_EXTERNAL_DEPARTURE")
            from adaptive_hrc_scheduling.production_external import path

            require(
                math.dist(proof.position_m, path(self.config, op)[-1]) <= 0.002,
                "EXTERNAL_POSITION_READBACK",
            )

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
        if op.action == "SUPPORT_CHANGE":
            layout = self._support_layout(op.support_layout_id)
            self._put(
                supports=tuple(
                    m.SupportState(
                        layout.root,
                        layout.id,
                        tuple(m.BeamPose(p.index, p.position) for p in proof.beams),
                        ("P1", "E1"),
                    )
                    if x.root == layout.root
                    else x
                    for x in self.s.supports
                )
            )
        mass = {x.entity_id: x.installed_t for x in self.s.masses}
        if op.component_inputs:
            mass[op.entity_id] = sum(mass[i] for i in op.component_inputs)
        if op.component_outputs:
            require(len(op.component_outputs) == 1, "EXPLICIT_SINGLE_COMPONENT_RECIPE")
            mass[op.component_outputs[0]] = sum(a.quantity for a in op.material_inputs)
        elif op.action == "WORK" and op.entity_id in self.entities:
            mass[op.entity_id] += sum(a.quantity for a in op.material_inputs) - op.mass_remove_t
            require(mass[op.entity_id] >= -1e-9, "NEGATIVE_INSTALLED_MASS")
        self._put(masses=tuple(m.MassState(i, max(0, value)) for i, value in mass.items()))
        require(
            all(
                self._lot(a.lot_id).location == self._input_place(op, a.lot_id)
                for a in op.material_inputs
            )
            and all(
                self._position(i).location == self._input_place(op, i) for i in op.component_inputs
            ),
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
                            location=self._output_place(op, a.lot_id),
                            available=a.quantity,
                            arrived=True,
                            identified=True,
                            released=True,
                        ),
                    ),
                    positions=changed(
                        self.s.positions,
                        "id",
                        m.Position(
                            lot.id, self._output_place(op, lot.id), self._output_place(op, lot.id)
                        ),
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
        if op.action == "WALK":
            self._put(
                supports=tuple(
                    replace(
                        rack,
                        clearance_people=tuple(
                            person
                            for person in rack.clearance_people
                            if person != op.entity_id
                            or op.target == f"CONTROL-SUPPORT-{rack.root}-{person}"
                        ),
                    )
                    for rack in self.s.supports
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
            completion_times=self.s.completion_times + (m.CompletionTime(op.id, self.s.time_h),),
            running=tuple(r for r in self.s.running if r != run),
            owners=tuple(x for x in self.s.owners if x.command_id != c.id),
            motions=tuple(p for p in self.s.motions if p.command_id not in (c.id, c.resume_of)),
        )
        if op.handover:
            h = op.handover
            self._put(
                mode_attempts=tuple(
                    replace(
                        a,
                        handover=h if h.phase == "HANDOVER" else None,
                        crew=a.crew
                        if h.phase == "HANDOVER"
                        else (m.RoleBinding(a.crew[0].role_id, h.incoming),),
                    )
                    if a.activity_id == h.activity_id
                    else a
                    for a in self.s.mode_attempts
                ),
                owners=self.s.owners
                + tuple(m.Ownership(i, f"ATTEMPT:{h.activity_id}:0:v1") for i in op.equipment),
            )
        if op.branch:
            self._put(
                mode_attempts=tuple(
                    replace(
                        a,
                        completed_units=(*a.completed_units, op.unit_index),
                        state="COMPLETE" if op.branch.terminal else "COMMITTED",
                    )
                    if a.activity_id == op.activity_id
                    else a
                    for a in self.s.mode_attempts
                ),
                owners=self.s.owners
                + tuple(m.Ownership(i, attempt_owner(op)) for i in op.hold_resources),
            )
        if op.hold_device:
            self._put(owners=self.s.owners + (m.Ownership(op.hold_device, "HELD:" + c.product_id),))
        if p.cancelled and not any(r.command.product_id == c.product_id for r in self.s.running):
            self._unreserve(c.product_id)

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
        if (
            self.operations[run.command.operation_id].branch
            or self.operations[run.command.operation_id].handover
        ):
            self._put(
                mode_attempts=tuple(
                    replace(a, state="HOLD") if a.activity_id == run.command.activity_id else a
                    for a in self.s.mode_attempts
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
                # Delivery-to-delivery ingress dependencies reserve access to
                # rear packages; core process gates remain dispatch constraints.
                first = next(
                    (
                        o
                        for o in self.config.operations
                        if o.entity_id == lot.id and o.id.endswith(".DELIVER-0")
                    ),
                    None,
                )
                if first:
                    require(rework.active(self.config, self.s.gates, first), "REPAIR_NOT_ACTIVATED")
                    require(
                        first.attempt_index == 0
                        or all(p in self.s.completed for p in first.prerequisites),
                        "REPAIR_ARRIVAL_PREDECESSORS",
                    )
                    for gate in first.quality_gates:
                        records = rework.quality_records(
                            self.config, self.s.gates, gate, e.product_id, first.attempt_index
                        )
                        require(records and records[-1].result == "PASS", "ARRIVAL_QUALITY_HOLD")
                    require(
                        all(p in self.s.completed for p in first.prerequisites if ".DELIVER-" in p),
                        "ARRIVAL_DELIVERY_PREDECESSORS",
                    )
                self._support_ready(e.entity_id, e.evidence_id)
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
            activities = [
                a
                for a in self.config.core_activities
                if a.product_id == e.product_id
                and (a.quality_evidence if e.kind == "QUALITY" else a.release_evidence)
                == e.entity_id
            ]
            require(len(activities) == 1, "GATE_PRODUCT_OR_KIND")
            bindings = [b for b in self.config.bindings if b.activity_id == activities[0].id]
            repaired = rework.repair_gate_operation(self.config, e)
            require(
                (
                    e.attempt == 0
                    and all(i in self.s.completed for b in bindings for i in b.operation_ids)
                )
                or (
                    repaired is not None
                    and repaired in self.s.completed
                    and rework.initial_failure(self.config, self.s.gates, e.product_id)
                ),
                "GATE_BEFORE_INSPECTION_OR_WAIT",
            )
            require(
                not any(
                    (g.id, g.product_id, g.attempt) == (e.entity_id, e.product_id, e.attempt)
                    for g in self.s.gates
                ),
                "DUPLICATE_GATE_ATTEMPT",
            )
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
            if self.config.research:
                aids = {a.id for a in self.config.core_activities if a.product_id == e.product_id}
                self._put(
                    mode_attempts=tuple(
                        replace(a, state="HOLD")
                        if a.activity_id in aids and a.state != "COMPLETE"
                        else a
                        for a in self.s.mode_attempts
                    ),
                    running=tuple(
                        replace(r, status="EXCEPTION", held_at_h=self.s.time_h)
                        if r.command.product_id == e.product_id
                        and (
                            self.operations[r.command.operation_id].branch
                            or self.operations[r.command.operation_id].handover
                        )
                        else r
                        for r in self.s.running
                    ),
                )
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
            self.config.schema_version,
            self.config.id,
            self.config_hash,
            self.run_id,
            self.epoch,
            f"OBS-{self.s.revision}",
            self.s.time_h,
            self.s.time_h + delay_h,
            replace(self.s, intervals=()),
            tuple(e.id for e in self.events),
        )
        self.observation_queue.append(obs)
        return obs

    def deliver(self):
        due = tuple(o for o in self.observation_queue if o.received_h <= self.s.time_h)
        self.observation_queue = [o for o in self.observation_queue if o.received_h > self.s.time_h]
        return due
