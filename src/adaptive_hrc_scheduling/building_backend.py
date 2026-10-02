"""C05 trusted building executor. Explicit manual dispatch; no scheduling policy.

Atomic transitions, conservative residency and test-only synthetic qualifications.
No industrial qualification, independent S10 checker or Isaac backend is implied.
"""

import copy
import json
import math
from dataclasses import dataclass, replace

from adaptive_hrc_scheduling.building_human import calendar_state, can_work, integrate
from adaptive_hrc_scheduling.contracts.building import (
    ContractError,
    as_data,
    digest,
    dumps,
    evidence_pass,
    loads,
    validate,
)
from adaptive_hrc_scheduling.contracts.codec import require
from adaptive_hrc_scheduling.domain import building as b


@dataclass(frozen=True)
class Receipt:
    accepted: bool
    reason: str


class BuildingBackend:
    def __init__(self, config, scenario=None):
        validate(config)
        self.config = config
        self.activities = {a.id: a for a in config.activities}
        self.products = {p.id: p for p in config.products}
        self.people = {p.id: p for p in config.people}
        self.resources = {r.id: r for r in config.resources}
        self.evidence = {e.id: e for e in config.evidence}
        scenario = scenario or b.HiddenScenario("C04-1.0", config.id, 0, ())
        validate(scenario, config=config)
        scenario = replace(
            scenario, events=tuple(sorted(scenario.events, key=lambda e: (e.time_h, e.id)))
        )
        self.s = b.ExecutionSnapshot(
            "C04-1.0",
            config.id,
            digest(config),
            0,
            0,
            tuple(
                b.ProductState(p.id, "UNASSEMBLED", "RELEASED", False, None, (), False)
                for p in config.products
            ),
            tuple(b.ComponentState(c.id, "UNFABRICATED", False) for c in config.components),
            tuple(
                b.MaterialState(m.id, m.arrived, m.identified, m.released, None)
                for m in config.materials
            ),
            (),
            (),
            tuple(b.HumanState(p.id, p.initial_f, 0, p.initial_f, 0) for p in config.people),
            (),
            (),
            (),
            (),
            (),
            tuple(p.id for p in config.products if p.release_h == 0),
            (),
            0,
            0,
            scenario,
            (),
            (),
            (),
            (),
        )
        self._external_tick()

    @property
    def snapshot(self):
        return self.s

    @property
    def time(self):
        return self.s.time_h

    def checkpoint(self):
        return dumps(self.s, config=self.config)

    @classmethod
    def restore(cls, config, text):
        state = loads(b.ExecutionSnapshot, text, config=config)
        world = cls(config, state.scenario)
        world.s = state
        return world

    def _set(self, **kwargs):
        self.s = replace(self.s, **kwargs)

    def _product(self, pid):
        return next(p for p in self.s.products if p.product_id == pid)

    def _human(self, pid):
        return next(p for p in self.s.people if p.person_id == pid)

    def _attempt(self, aid):
        records = [a for a in self.s.attempts if a.activity_id == aid]
        return max(records, key=lambda a: a.number) if records else None

    def _put_attempt(self, record):
        self._set(
            attempts=tuple(
                a
                for a in self.s.attempts
                if (a.activity_id, a.number) != (record.activity_id, record.number)
            )
            + (record,)
        )

    def _put_product(self, p):
        self._set(products=tuple(p if x.product_id == p.product_id else x for x in self.s.products))

    def _log(self, kind, entity, reason="", attempt=None):
        detail = (
            json.dumps(reason, sort_keys=True, ensure_ascii=False)
            if not isinstance(reason, str)
            else reason
        )
        event = b.ExecutionEvent(
            "C04-1.0",
            self.config.id,
            f"EV-{len(self.s.events) + 1}",
            self.time,
            kind,
            entity,
            attempt,
            detail,
        )
        self._set(events=self.s.events + (event,))

    def _revision(self):
        self._set(revision=self.s.revision + 1)

    def _require_evidence(self, ids, reason):
        require(evidence_pass(self.config, ids), reason)

    def _capacity(self, location, owner):
        owners = {r.owner for r in self.s.residencies if r.location == location}
        require(
            len(owners | {owner}) <= self.resources[location].capacity,
            "DESTINATION_CAPACITY:" + location,
        )

    def _reserve(self, entity, location, owner, reserved):
        self._capacity(location, owner)
        record = b.Residency(entity, location, owner, reserved)
        if record not in self.s.residencies:
            self._set(residencies=self.s.residencies + (record,))

    def _acquire(self, ids, owner):
        require(len(ids) == len(set(ids)), "DUPLICATE_RESOURCE")
        for rid in ids:
            require(rid not in self.s.failed_resources, "RESOURCE_FAILED:" + rid)
            require(
                not any(x.resource_id == rid and x.owner != owner for x in self.s.locks),
                "RESOURCE_BUSY:" + rid,
            )
        self._set(
            locks=self.s.locks
            + tuple(
                b.Lock(rid, owner)
                for rid in ids
                if not any(x.resource_id == rid for x in self.s.locks)
            )
        )

    def _release(self, owner, keep=()):
        self._set(locks=tuple(x for x in self.s.locks if x.owner != owner or x.resource_id in keep))

    def dispatch(self, command):
        validate(command, config=self.config)
        if command.id in self.s.consumed_commands:
            return Receipt(False, "DUPLICATE_COMMAND")
        candidate = copy.copy(self)
        try:
            candidate._dispatch(command)
        except ContractError as error:
            self._set(consumed_commands=self.s.consumed_commands + (command.id,))
            self._log("REJECTED", command.activity_id, str(error), command.attempt)
            return Receipt(False, str(error))
        candidate._set(consumed_commands=candidate.s.consumed_commands + (command.id,))
        candidate._revision()
        self.s = candidate.s
        return Receipt(True, "ACCEPTED")

    def _dispatch(self, c):
        require(c.issued_h == self.time, "COMMAND_TIME")
        require(c.expected_revision == self.s.revision, "STALE_REVISION")
        a = self.activities[c.activity_id]
        p = self._product(a.product_id)
        require(a.product_id in self.s.released_products, "ORDER_NOT_RELEASED")
        require(
            not p.cancelled and p.state not in ("QUARANTINED", "RECEIVED"),
            "CANCELLED_OR_QUARANTINED",
        )
        require(p.state != "QUALITY_HOLD", "QUALITY_HOLD_UNRESOLVED")
        require(not any(x.activity_id == a.id for x in self.s.running), "ALREADY_RUNNING")
        require(not any(x.product_id == p.product_id for x in self.s.services), "SERVICE_COMMITTED")
        mode = next(m for m in a.modes if m.id == c.mode_id)
        self._require_evidence(mode.qualification_ids, "UNQUALIFIED_METHOD")
        self._check_predecessors(a)
        prior = self._attempt(a.id)
        if prior:
            require(
                prior.state in ("NOT_READY", "PAUSED_AT_CHECKPOINT", "WAITING_RELEASE"),
                "ACTIVITY_NOT_STARTABLE",
            )
            require(
                c.attempt == prior.number and c.unit_index == prior.completed_units,
                "PROGRESS_IDENTITY",
            )
            require(prior.mode_id == c.mode_id, "MODE_COMMITMENT")
        else:
            require(c.attempt == 0 and c.unit_index == 0, "INITIAL_ATTEMPT")
            prior = b.Attempt(a.id, 0, mode.id, 0, "NOT_READY", None, False)
        if a.wait_h:
            require(
                prior.wait_until_h is not None and self.time >= prior.wait_until_h,
                "WAIT_NOT_ELAPSED",
            )
            require(a.id in self.s.released_processes, "PROCESS_RELEASE_HOLD")
        if a.code == "READY":
            self._ready(a, p)
            return
        if not mode.units:
            self._put_attempt(replace(prior, state="COMPLETED"))
            self._log("COMPLETED", a.id, attempt=prior.number)
            return
        unit = mode.units[c.unit_index]
        self._require_evidence((unit.checkpoint_id,), "UNQUALIFIED_CHECKPOINT")
        if a.quality_evidence:
            self._require_evidence((a.quality_evidence,), "UNQUALIFIED_INSPECTION")
        bound = {r.role_id: r.person_id for r in c.roles}
        if prior.completed_units and prior.prepared:
            earlier = [
                e
                for e in self.s.events
                if e.kind == "UNIT_START" and e.entity_id == a.id and e.attempt == prior.number
            ]
            if earlier:
                last = json.loads(earlier[-1].reason)
                old = {r["role_id"]: r["person_id"] for r in last["roles"]}
                # Role changes require a separately completed, charged handover.
                for role, pid in bound.items():
                    if role in old and old[role] != pid:
                        require(
                            any(
                                e.kind == "HANDOVER_COMPLETE"
                                and e.entity_id == a.id
                                and json.loads(e.reason).get("incoming") == pid
                                and json.loads(e.reason).get("outgoing") == old[role]
                                for e in self.s.events
                            ),
                            "HANDOVER_REQUIRED",
                        )
        start_f = max((self._human(pid).fatigue for pid in bound.values()), default=0)
        multiplier = 1 + unit.kappa * start_f
        duration = unit.base_h * multiplier
        end = self.time + duration
        require(end > self.time and math.isfinite(end), "UNREPRESENTABLE_TIME")
        self._protect(tuple(bound.values()), end)
        self._faces(a)
        required = tuple(bound.values()) + unit.equipment
        if a.move:
            required += (a.move.route,)
        if a.code == "Q-POND":
            self._set(
                locks=tuple(
                    replace(x, owner=a.id)
                    if x.resource_id == "TEST1" and x.owner == a.product_id + ".TEST"
                    else x
                    for x in self.s.locks
                )
            )
        self._acquire(required, a.id)
        self._check_location(a)
        if a.move:
            self._prepare_move(a)
        if a.code == "KIT":
            self._reserve(p.product_id + ".RAW", "PRE", p.product_id, False)
        material_ids = (
            (a.product_id + ".REPAIR-TEST-KIT",)
            if a.code == "TEST-SET" and prior.number == 1
            else a.material_ids
        )
        if c.unit_index == 0:
            for mid in material_ids:
                material = next(x for x in self.s.materials if x.material_id == mid)
                require(
                    material.arrived
                    and material.identified
                    and material.released
                    and material.consumed_by is None,
                    "MATERIAL_KIT:" + mid,
                )
            for mid in material_ids:
                self._set(
                    materials=tuple(
                        replace(x, consumed_by=a.id) if x.material_id == mid else x
                        for x in self.s.materials
                    )
                )
                self._log(
                    "MATERIAL_CONSUMED",
                    mid,
                    {"activity": a.id, "product": a.product_id},
                    prior.number,
                )
        self._put_attempt(replace(prior, state="RUNNING", prepared=True))
        run = b.Running(
            a.id,
            prior.number,
            c.unit_index,
            mode.id,
            self.time,
            end,
            start_f,
            multiplier,
            c.roles,
            unit.equipment,
            "ACTIVE",
            0,
        )
        self._set(running=self.s.running + (run,))
        self._put_product(replace(p, state="IN_PROCESS"))
        self._log("UNIT_START", a.id, as_data(run), prior.number)

    def _check_predecessors(self, a):
        prerequisites = {a.id}
        while True:
            expanded = prerequisites | {
                edge.source for edge in self.config.edges if edge.target in prerequisites
            }
            if expanded == prerequisites:
                break
            prerequisites = expanded
        for edge in self.config.edges:
            if edge.target not in prerequisites:
                continue
            prior = self._attempt(edge.source)
            require(prior is not None and prior.state == "COMPLETED", "PREDECESSOR:" + edge.source)
            predecessor = self.activities[edge.source]
            if predecessor.quality_evidence:
                require(
                    any(
                        q.activity_id == edge.source
                        and q.attempt == prior.number
                        and q.valid
                        and q.result == "PASS"
                        for q in self.s.quality
                    ),
                    "QUALITY_HOLD:" + edge.source,
                )
            if predecessor.release_evidence:
                require(edge.source in self.s.released_processes, "PROCESS_RELEASE_HOLD")

    def _protect(self, people, end):
        for pid in people:
            person = self.people[pid]
            h = self._human(pid)
            require(h.rest_until_h <= self.time, "REST_COMMITTED")
            require(can_work(person, self.time, end), "CALENDAR_OR_QUALIFICATION")
            require(
                h.fatigue + person.work_rate * (end - self.time) <= self.config.cap,
                "FATIGUE_PROTECTION",
            )

    def _faces(self, a):
        occupants = []
        for run in self.s.running:
            other = self.activities[run.activity_id]
            if other.product_id == a.product_id or other.location == a.location:
                occupants.append(other)
        for attempt in self.s.attempts:
            other = self.activities[attempt.activity_id]
            if (
                attempt.state == "WAITING_RELEASE"
                and other.product_id == a.product_id
                and other.id != a.id
            ):
                occupants.append(other)
        for other in occupants:
            permitted = any(
                {pair.first, pair.second} == {a.face, other.face}
                and evidence_pass(self.config, (pair.qualification_id,))
                for pair in self.config.face_pairs
            )
            require(permitted, "WORK_FACE_CONFLICT")

    def _check_location(self, a):
        require(a.location not in self.s.failed_resources, "LOCATION_FAILED")
        p = self._product(a.product_id)
        if a.move:
            return
        if a.code in ("KIT", "CUT"):
            return
        if a.code in ("W-B", "W-T"):
            cid = a.product_id + (".BOTTOM" if a.code == "W-B" else ".TOP")
            require(
                next(x for x in self.s.components if x.component_id == cid).location == "J2",
                "COMPONENT_LOCATION",
            )
        else:
            require(p.location == a.location, "PRODUCT_LOCATION")

    def _prepare_move(self, a):
        move = a.move
        p = self.products[a.product_id]
        self._require_evidence(move.qualification_ids, "UNQUALIFIED_MOVE")
        require(not self._product(a.product_id).water_present, "TEST_NOT_DRAINED")
        require(
            move.source not in self.s.failed_resources
            and move.target not in self.s.failed_resources,
            "MOVE_LOCATION_FAILED",
        )
        equipment = self.resources[move.equipment]
        for eid in move.entity_ids:
            if eid in self.products:
                require(self._product(eid).location == move.source, "MOVE_SOURCE")
                mass = p.mass_t
            else:
                component = next(x for x in self.config.components if x.id == eid)
                state = next(x for x in self.s.components if x.component_id == eid)
                expected = (
                    "PRE" if component.kind == "COLUMNS" and a.code == "JOIN-IN" else move.source
                )
                require(
                    not state.incorporated and state.location == expected, "MOVE_COMPONENT_SOURCE"
                )
                mass = component.mass_t
            # JOIN-IN checks each stable sub-lift, never an invented combined payload.
            require(mass + p.rigging_t <= equipment.load_t, "MOVE_OVERLOAD")
        for eid in move.entity_ids:
            owner = eid if move.target == "BUF" else a.product_id
            self._reserve(eid, move.target, owner, True)
        self._log(
            "MOVE_RESERVED",
            a.id,
            {"move": as_data(move), "residencies": [as_data(r) for r in self.s.residencies]},
        )

    def _ready(self, a, p):
        require(
            not p.cancelled and p.location == "OUT1" and not p.water_present, "NOT_READY_LOCATION"
        )
        all_activities = [
            x for x in self.config.activities if x.product_id == a.product_id and x.id != a.id
        ]
        require(
            all(
                self._attempt(x.id) is not None and self._attempt(x.id).state == "COMPLETED"
                for x in all_activities
            ),
            "INCOMPLETE_PRODUCT",
        )
        for x in all_activities:
            if x.quality_evidence:
                require(
                    any(
                        q.activity_id == x.id
                        and q.attempt == self._attempt(x.id).number
                        and q.valid
                        and q.result == "PASS"
                        for q in self.s.quality
                    ),
                    "INCOMPLETE_QUALITY",
                )
        require(
            {i.id for i in self.products[a.product_id].bom} <= set(p.installed_bom),
            "INCOMPLETE_BOM",
        )
        self._put_attempt(b.Attempt(a.id, 0, a.modes[0].id, 0, "COMPLETED", None, False))
        self._put_product(replace(p, state="READY", ready_h=self.time))
        self._log("READY", p.product_id)

    def rest(self, person_ids, duration):
        require(math.isfinite(duration) and duration >= self.config.min_rest_h, "REST_DURATION")
        require(
            len(set(person_ids)) == len(person_ids) and set(person_ids) <= set(self.people),
            "REST_PEOPLE",
        )
        require(not any(x.resource_id in person_ids for x in self.s.locks), "REST_WHILE_COMMITTED")
        self._set(
            people=tuple(
                replace(h, rest_until_h=max(h.rest_until_h, self.time + duration))
                if h.person_id in person_ids
                else h
                for h in self.s.people
            )
        )
        self._log(
            "REST_START",
            self.config.id,
            {"people": list(person_ids), "until": self.time + duration},
        )
        self._revision()

    def advance(self, until, *, stop_on_feedback=False):
        """Advance normally, or return at the first new actual event for S12.

        The optional wakeup does not expose future event times or change the
        default C05/S11 run-to-deadline behavior.
        """
        require(type(stop_on_feedback) is bool, "FEEDBACK_WAKE_FLAG")
        require(
            type(until) in (int, float) and math.isfinite(until) and until >= self.time,
            "ADVANCE_TIME",
        )
        require(until == self.time or not self._emergency_hold(), "EMERGENCY_HOLD_NO_SAFE_PATH")
        candidate = copy.copy(self)
        candidate._advance(float(until), stop_on_feedback=stop_on_feedback)
        self.s = candidate.s
        return Receipt(
            not self._emergency_hold(),
            "EMERGENCY_HOLD_NO_SAFE_PATH" if self._emergency_hold() else "ADVANCED",
        )

    def _emergency_hold(self):
        return any(r.state == "EMERGENCY_HOLD" for r in self.s.running + self.s.services)

    def _advance(self, until, *, stop_on_feedback=False):
        while self.time < until:
            if self._emergency_hold():
                # Commit the actual prefix up to the new emergency; never undo its event.
                return
            boundaries = [until]
            boundaries += [r.end_h for r in self.s.running if r.end_h > self.time]
            boundaries += [
                r.start_h + d * r.multiplier
                for r in self.s.running
                if self.activities[r.activity_id].move
                for d in self.activities[r.activity_id].move.landing_h
                if self.time < r.start_h + d * r.multiplier < r.end_h
            ]
            boundaries += [
                t
                for r in self.s.running
                if self.activities[r.activity_id].move
                for t in self._move_boundaries(r)
                if t > self.time
            ]
            boundaries += [r.end_h for r in self.s.services if r.end_h > self.time]
            boundaries += [
                r.start_h + 0.4
                for r in self.s.services
                if r.kind == "CLEANUP" and r.start_h + 0.4 > self.time
            ]
            if self.s.event_cursor < len(self.s.scenario.events):
                boundaries.append(self.s.scenario.events[self.s.event_cursor].time_h)
            boundaries += [
                p.release_h
                for p in self.config.products
                if p.id not in self.s.released_products and p.release_h > self.time
            ]
            boundaries += [
                a.wait_until_h
                for a in self.s.attempts
                if a.wait_until_h is not None and a.wait_until_h > self.time
            ]
            for p in self.people.values():
                _, bound = calendar_state(p, self.time)
                boundaries.append(bound)
                h = self._human(p.id)
                if h.rest_until_h > self.time:
                    boundaries.append(h.rest_until_h)
                elif (
                    not any(x.resource_id == p.id for x in self.s.locks)
                    and calendar_state(p, self.time)[0] == "WAIT"
                ):
                    to_cap = (self.config.cap - h.fatigue) / p.wait_rate
                    if math.nextafter(self.time + to_cap, self.time) <= self.time:
                        self._set(
                            people=tuple(
                                replace(x, rest_until_h=self.time + self.config.min_rest_h)
                                if x.person_id == p.id
                                else x
                                for x in self.s.people
                            )
                        )
                        self._log("PROTECTIVE_REST", p.id)
                        boundaries.append(self.time + self.config.min_rest_h)
                    else:
                        boundaries.append(math.nextafter(self.time + to_cap, self.time))
            next_time = min(t for t in boundaries if t > self.time)
            event_count = len(self.s.events)
            self._integrate_to(next_time)
            self._set(time_h=next_time)
            self._complete_tick()
            self._external_tick()
            self._start_waits()
            self._revision()
            if stop_on_feedback and len(self.s.events) != event_count:
                return

    def _integrate_to(self, end):
        humans = []
        intervals = []
        for p in self.people.values():
            h = self._human(p.id)
            run = next(
                (r for r in self.s.running if any(x.person_id == p.id for x in r.roles)), None
            )
            service = next((s for s in self.s.services if p.id in s.people), None)
            if run:
                activity = "WORK"
            elif service:
                activity = (
                    "HANDOVER"
                    if service.kind == "HANDOVER"
                    else "RESTORE"
                    if service.kind == "RESTORE"
                    else "WORK"
                )
            elif h.rest_until_h > self.time:
                activity = "REST"
            else:
                activity, _ = calendar_state(p, self.time)
            new, interval = integrate(p, h, activity, self.time, end, self.config.cap)
            humans.append(new)
            intervals.append(interval)
        self._set(people=tuple(humans), intervals=self.s.intervals + tuple(intervals))

    def _complete_tick(self):
        for run in tuple(self.s.running):
            a = self.activities[run.activity_id]
            if a.move:
                done = sum(run.start_h + d * run.multiplier <= self.time for d in a.move.landing_h)
                if done > run.landings_done:
                    self._land(a, run, done)
                    run = replace(run, landings_done=done)
                    self._set(
                        running=tuple(
                            run if x.activity_id == run.activity_id else x for x in self.s.running
                        )
                    )
            if a.move:
                self._motion_tick(a, run)
            if run.end_h > self.time:
                continue
            attempt = self._attempt(a.id)
            mode = next(m for m in a.modes if m.id == run.mode_id)
            count = run.unit_index + 1
            finished = count == len(mode.units)
            self._put_attempt(
                replace(
                    attempt,
                    completed_units=count,
                    state="COMPLETED" if finished else "PAUSED_AT_CHECKPOINT",
                )
            )
            keep = []
            if mode.kind == "HR-seq" and not finished:
                keep = ["R1", "FIX-J2"]
            if a.code == "TEST-SET":
                keep = ["TEST1"]
            self._release(a.id, keep)
            if a.code == "TEST-SET":
                self._set(
                    locks=tuple(
                        replace(x, owner=a.product_id + ".TEST") if x.resource_id == "TEST1" else x
                        for x in self.s.locks
                    )
                )
                self._put_product(replace(self._product(a.product_id), water_present=True))
            if a.code == "Q-POND":
                self._release(a.product_id + ".TEST")
                self._put_product(replace(self._product(a.product_id), water_present=False))
            self._set(running=tuple(x for x in self.s.running if x.activity_id != a.id))
            self._log("UNIT_COMPLETE", a.id, as_data(run), run.attempt)
            if finished:
                self._finish_activity(a, run)
        for service in tuple(self.s.services):
            if service.kind == "CLEANUP" and service.start_h + 0.4 <= self.time < service.end_h:
                p = self._product(service.product_id)
                if p.location != "IN_TRANSIT":
                    self._put_product(replace(p, location="IN_TRANSIT"))
                    self._log("CLEANUP_IN_TRANSIT", p.product_id)
            if service.end_h <= self.time:
                self._finish_service(service)

    def _move_boundaries(self, run):
        previous = 0
        out = []
        for landing in self.activities[run.activity_id].move.landing_h:
            out.extend(
                run.start_h + (previous + (landing - previous) * fraction) * run.multiplier
                for fraction in (0.2, 0.4, 0.7, 1)
            )
            previous = landing
        return out

    def _motion_tick(self, a, run):
        previous = 0
        for index, landing in enumerate(a.move.landing_h):
            lift = run.start_h + (previous + (landing - previous) * 0.4) * run.multiplier
            end = run.start_h + landing * run.multiplier
            if lift <= self.time < end:
                eid = a.move.entity_ids[index] if a.code == "JOIN-IN" else a.move.entity_ids[0]
                if eid in self.products:
                    p = self._product(eid)
                    if p.location != "IN_TRANSIT":
                        self._put_product(replace(p, location="IN_TRANSIT"))
                        self._log(
                            "IN_TRANSIT",
                            eid,
                            {"source_held": a.move.source, "target_reserved": a.move.target},
                        )
                else:
                    comp = next(c for c in self.s.components if c.component_id == eid)
                    if comp.location != "IN_TRANSIT":
                        self._set(
                            components=tuple(
                                replace(c, location="IN_TRANSIT") if c == comp else c
                                for c in self.s.components
                            )
                        )
                        self._log(
                            "IN_TRANSIT",
                            eid,
                            {"source_held": a.move.source, "target_reserved": a.move.target},
                        )
            previous = landing

    def _land(self, a, run, done):
        move = a.move
        entities = move.entity_ids[:done] if a.code == "JOIN-IN" else move.entity_ids
        for eid in entities:
            self._set(
                residencies=tuple(
                    r
                    for r in self.s.residencies
                    if not (r.entity_id == eid and r.location != move.target)
                )
            )
            self._set(
                residencies=tuple(
                    replace(r, reserved=False)
                    if r.entity_id == eid and r.location == move.target
                    else r
                    for r in self.s.residencies
                )
            )
            if eid in self.products:
                self._put_product(replace(self._product(eid), location=move.target))
            else:
                self._set(
                    components=tuple(
                        replace(c, location=move.target) if c.component_id == eid else c
                        for c in self.s.components
                    )
                )
        if a.code == "JOIN-IN" and done == len(move.landing_h):
            self._set(
                components=tuple(
                    replace(c, incorporated=True, location="INCORPORATED")
                    if c.component_id in entities
                    else c
                    for c in self.s.components
                )
            )
            self._set(
                residencies=tuple(
                    r
                    for r in self.s.residencies
                    if r.entity_id not in entities
                    and not (r.owner == a.product_id and r.location == "PRE")
                )
            )
            self._reserve(a.product_id, "J3", a.product_id, False)
            self._put_product(replace(self._product(a.product_id), location="J3"))
        self._log(
            "ARRIVAL_CONFIRMED",
            a.id,
            {"entities": list(entities), "target": move.target, "sub_landings": done},
        )

    def _finish_activity(self, a, run):
        p = self._product(a.product_id)
        if a.code == "CUT":
            self._set(
                residencies=tuple(
                    r for r in self.s.residencies if r.entity_id != a.product_id + ".RAW"
                )
            )
            self._set(
                components=tuple(
                    replace(c, location="PRE")
                    if c.component_id
                    in {x.id for x in self.config.components if x.product_id == a.product_id}
                    else c
                    for c in self.s.components
                )
            )
            for c in self.config.components:
                if c.product_id == a.product_id:
                    self._reserve(c.id, "PRE", a.product_id, False)
        if a.code == "JOIN-IN":
            p = self._product(a.product_id)
        installed = set(p.installed_bom)
        for material in self.config.materials:
            if material.id in a.material_ids:
                installed.update(material.bom_ids)
        self._put_product(replace(p, installed_bom=tuple(sorted(installed))))
        self._log("ACTIVITY_COMPLETE", a.id, attempt=run.attempt)
        self._start_waits()

    def _start_waits(self):
        for a in self.config.activities:
            if not a.wait_h or self._product(a.product_id).cancelled:
                continue
            prior = self._attempt(a.id)
            if prior and prior.state != "NOT_READY":
                continue
            edges = [e for e in self.config.edges if e.target == a.id]
            if all(
                self._attempt(e.source) is not None and self._attempt(e.source).state == "COMPLETED"
                for e in edges
            ):
                record = prior or b.Attempt(a.id, 0, a.modes[0].id, 0, "NOT_READY", None, False)
                self._put_attempt(
                    replace(record, state="WAITING_RELEASE", wait_until_h=self.time + a.wait_h)
                )
                self._log("WAIT_START", a.id, {"until": self.time + a.wait_h}, record.number)

    def _external_tick(self):
        for p in self.config.products:
            if p.release_h <= self.time and p.id not in self.s.released_products:
                self._set(released_products=self.s.released_products + (p.id,))
                self._log("ORDER_ARRIVAL", p.id)
        while self.s.event_cursor < len(self.s.scenario.events):
            event = self.s.scenario.events[self.s.event_cursor]
            if event.time_h > self.time:
                break
            require(event.time_h == self.time, "MISSED_EVENT")
            self._apply_event(event)
            self._set(event_cursor=self.s.event_cursor + 1)

    def apply_event(self, event):
        """Trusted fixture/adapter fact at the current clock; never planner input."""
        validate(b.HiddenScenario("C04-1.0", self.config.id, 0, (event,)), config=self.config)
        require(event.time_h == self.time, "EVENT_TIME")
        if any(e.kind == "EXTERNAL" and e.entity_id == event.id for e in self.s.events):
            return Receipt(False, "DUPLICATE_EVENT")
        candidate = copy.copy(self)
        candidate._apply_event(event)
        candidate._revision()
        self.s = candidate.s
        return Receipt(True, "ACCEPTED")

    def _apply_event(self, e):
        if any(x.kind == "EXTERNAL" and x.entity_id == e.id for x in self.s.events):
            return
        if e.kind.startswith("MATERIAL_"):
            material = next(x for x in self.s.materials if x.material_id == e.entity_id)
            require(material.consumed_by is None, "MATERIAL_ALREADY_CONSUMED")
            field = {
                "MATERIAL_ARRIVAL": "arrived",
                "MATERIAL_IDENTIFY": "identified",
                "MATERIAL_RELEASE": "released",
            }[e.kind]
            if field == "released":
                require(material.arrived and material.identified, "MATERIAL_NOT_IDENTIFIED")
            self._set(
                materials=tuple(
                    replace(x, **{field: True}) if x == material else x for x in self.s.materials
                )
            )
        elif e.kind == "PROCESS_RELEASE":
            a = self.activities[e.entity_id]
            attempt = self._attempt(a.id)
            require(
                a.release_evidence is not None
                and attempt is not None
                and attempt.wait_until_h is not None
                and self.time >= attempt.wait_until_h,
                "WAIT_NOT_ELAPSED",
            )
            self._require_evidence((a.release_evidence, "G4"), "UNQUALIFIED_PROCESS_RELEASE")
            if a.id not in self.s.released_processes:
                self._set(released_processes=self.s.released_processes + (a.id,))
            if not a.modes[0].units:
                self._put_attempt(replace(attempt, state="COMPLETED"))
        elif e.kind == "QUALITY_RESULT":
            self._quality(e)
        elif e.kind == "INVALIDATE":
            self._invalidate(e.entity_id)
        elif e.kind == "CANCEL":
            p = self._product(e.entity_id)
            self._put_product(replace(p, cancelled=True, state="CANCEL_PENDING", ready_h=None))
            self._set(
                attempts=tuple(
                    replace(a, state="CANCELLED")
                    if self.activities[a.activity_id].product_id == p.product_id
                    and a.state in ("NOT_READY", "PAUSED_AT_CHECKPOINT", "WAITING_RELEASE")
                    else a
                    for a in self.s.attempts
                )
            )
        elif e.kind == "FAILURE":
            if e.entity_id not in self.s.failed_resources:
                self._set(failed_resources=self.s.failed_resources + (e.entity_id,))
            for run in tuple(self.s.running):
                a = self.activities[run.activity_id]
                dependencies = (
                    run.equipment
                    + (a.location,)
                    + ((a.move.route, a.move.source, a.move.target) if a.move else ())
                )
                if e.entity_id not in dependencies:
                    continue
                if a.move:
                    self._set(
                        running=tuple(
                            replace(r, state="EMERGENCY_HOLD") if r == run else r
                            for r in self.s.running
                        )
                    )
                    self._log("EMERGENCY_HOLD", a.id, "NO_APPROVED_EMERGENCY_PATH", run.attempt)
                else:
                    self._put_attempt(replace(self._attempt(a.id), state="FAILED", prepared=False))
                    self._set(running=tuple(r for r in self.s.running if r != run))
                    self._release(a.id)
                    self._put_product(replace(self._product(a.product_id), state="QUALITY_HOLD"))
                    self._log("INTERRUPTED_REQUIRES_INSPECTION", a.id, as_data(run), run.attempt)
            for service in self.s.services:
                if service.kind == "CLEANUP" and e.entity_id in (
                    "CR1",
                    "ROUTE-MODULE",
                    service.source,
                    service.target,
                ):
                    self._set(
                        services=tuple(
                            replace(x, state="EMERGENCY_HOLD") if x == service else x
                            for x in self.s.services
                        )
                    )
                    self._log("EMERGENCY_HOLD", service.activity_id, "CLEANUP_DEPENDENCY_FAILED")
        elif e.kind == "REPAIR":
            self._set(
                failed_resources=tuple(x for x in self.s.failed_resources if x != e.entity_id)
            )
            # Repairing hardware is not a safe landing or renewed process qualification.
        elif e.kind == "RECEIVED":
            p = self._product(e.entity_id)
            require(p.state == "READY" and not p.cancelled, "RECEIVED_NOT_READY")
            self._put_product(replace(p, state="RECEIVED", location="EXTERNAL"))
            self._set(residencies=tuple(r for r in self.s.residencies if r.owner != p.product_id))
        elif e.kind == "ORDER_ARRIVAL":
            require(self.products[e.entity_id].release_h <= self.time, "EARLY_ORDER_RELEASE")
            if e.entity_id not in self.s.released_products:
                self._set(released_products=self.s.released_products + (e.entity_id,))
        self._log("EXTERNAL", e.id, as_data(e), e.attempt)

    def _quality(self, e):
        a = self.activities[e.entity_id]
        attempt = self._attempt(a.id)
        require(
            a.quality_evidence is not None
            and attempt is not None
            and attempt.state == "COMPLETED"
            and e.attempt == attempt.number,
            "QUALITY_ATTEMPT_NOT_COMPLETE",
        )
        self._require_evidence((a.quality_evidence,), "UNQUALIFIED_INSPECTION")
        require(
            not any(q.activity_id == a.id and q.attempt == e.attempt for q in self.s.quality),
            "QUALITY_RESULT_IMMUTABLE",
        )
        run_events = [
            x
            for x in self.s.events
            if x.kind == "UNIT_START" and x.entity_id == a.id and x.attempt == attempt.number
        ]
        roles = json.loads(run_events[-1].reason)["roles"]
        inspector = next(x["person_id"] for x in roles if x["role_id"] == "QA1")
        record = b.QualityRecord(
            f"QUALITY-{len(self.s.quality) + 1}",
            a.product_id,
            a.id,
            attempt.number,
            self.products[a.product_id].revision,
            self.evidence[a.quality_evidence].revision,
            inspector,
            self.time,
            e.value,
            True,
        )
        self._set(quality=self.s.quality + (record,))
        if e.value != "PASS":
            self._invalidate(a.id, include_self=False)
            self._put_product(
                replace(self._product(a.product_id), state="QUALITY_HOLD", ready_h=None)
            )

    def _invalidate(self, aid, include_self=True):
        affected = {aid}
        while True:
            more = affected | {e.target for e in self.config.edges if e.source in affected}
            if more == affected:
                break
            affected = more
        targets = affected if include_self else affected - {aid}
        self._set(
            quality=tuple(
                replace(q, valid=False) if q.activity_id in targets else q for q in self.s.quality
            )
        )
        for run in tuple(self.s.running):
            if run.activity_id in targets:
                # Do not abandon a suspended load; stop at the committed safe landing.
                if self.activities[run.activity_id].move:
                    continue
                self._set(running=tuple(x for x in self.s.running if x != run))
                self._release(run.activity_id)
                self._put_attempt(
                    replace(self._attempt(run.activity_id), state="FAILED", prepared=False)
                )
        moving = {
            run.activity_id for run in self.s.running if self.activities[run.activity_id].move
        }
        self._set(
            attempts=tuple(
                replace(attempt, state="FAILED", prepared=False)
                if attempt.activity_id in targets and attempt.activity_id not in moving
                else attempt
                for attempt in self.s.attempts
            )
        )
        self._set(
            released_processes=tuple(x for x in self.s.released_processes if x not in targets)
        )
        pid = self.activities[aid].product_id
        self._put_product(replace(self._product(pid), state="QUALITY_HOLD", ready_h=None))
        self._log("INVALIDATED", aid, {"activities": sorted(targets)})

    def observe(self, *, delay_h=0, missing=False):
        require(math.isfinite(delay_h) and delay_h >= 0, "OBSERVATION_DELAY")
        visible = set(self.s.released_products)
        products = tuple(
            b.ObservedProduct(
                p.product_id,
                None if missing else p.state,
                None if missing else p.location,
                ()
                if missing
                else tuple(
                    a.activity_id
                    for a in self.s.attempts
                    if self.activities[a.activity_id].product_id == p.product_id
                    and a.state == "COMPLETED"
                ),
                None if missing else p.cancelled,
            )
            for p in self.s.products
            if p.product_id in visible
        )
        obs = b.PlanningObservation(
            "C04-1.0",
            self.config.id,
            f"OBS-{self.s.revision}-{len(self.s.observation_queue)}",
            self.time,
            self.time + delay_h,
            self.time + delay_h,
            self.s.revision,
            products,
            () if missing else self.s.people,
            ()
            if missing
            else tuple(
                sorted(
                    set(self.s.failed_resources)
                    | {x.resource_id for x in self.s.locks if x.resource_id in self.resources}
                )
            ),
            tuple(e.id for e in self.s.events),
        )
        self._set(observation_queue=self.s.observation_queue + (obs,))
        return self.deliver_observations()

    def deliver_observations(self):
        delivered = tuple(x for x in self.s.observation_queue if x.received_h <= self.time)
        self._set(
            observation_queue=tuple(x for x in self.s.observation_queue if x.received_h > self.time)
        )
        return delivered

    def handover(self, activity_id, outgoing, incoming):
        candidate = copy.copy(self)
        try:
            candidate._handover(activity_id, outgoing, incoming)
        except ContractError as error:
            return Receipt(False, str(error))
        candidate._revision()
        self.s = candidate.s
        return Receipt(True, "ACCEPTED")

    def _handover(self, aid, outgoing, incoming):
        a = self.activities[aid]
        attempt = self._attempt(aid)
        require(
            attempt is not None and attempt.state == "PAUSED_AT_CHECKPOINT", "HANDOVER_CHECKPOINT"
        )
        require(
            outgoing != incoming and outgoing in self.people and incoming in self.people,
            "HANDOVER_PEOPLE",
        )
        require(not self._product(a.product_id).cancelled, "CANCELLED")
        mode = next(m for m in a.modes if m.id == attempt.mode_id)
        unit = mode.units[attempt.completed_units]
        prior = [
            e
            for e in self.s.events
            if e.kind == "UNIT_START" and e.entity_id == aid and e.attempt == attempt.number
        ]
        bindings = json.loads(prior[-1].reason)["roles"]
        roles = [r["role_id"] for r in bindings if r["person_id"] == outgoing]
        require(roles, "HANDOVER_OUTGOING")
        required = [r.qualification for r in unit.roles if r.id in roles]
        require(
            required and all(q in self.people[incoming].qualifications for q in required),
            "HANDOVER_QUALIFICATION",
        )
        self._require_evidence(("G5",), "UNQUALIFIED_HANDOVER")
        self._protect((outgoing, incoming), (self.time + 0.1) + 0.1)
        sid = f"SERVICE-{len(self.s.events) + 1}"
        self._acquire((outgoing, incoming), sid)
        service = b.Service(
            sid,
            "HANDOVER",
            aid,
            a.product_id,
            (outgoing, incoming),
            self.time,
            self.time + 0.1,
            None,
            None,
            "ACTIVE",
            incoming,
            outgoing,
        )
        self._set(services=self.s.services + (service,))
        self._log("HANDOVER_START", aid, as_data(service), attempt.number)

    def repair_quality(self, activity_id):
        candidate = copy.copy(self)
        try:
            candidate._repair_quality(activity_id)
        except ContractError as error:
            return Receipt(False, str(error))
        candidate._revision()
        self.s = candidate.s
        return Receipt(True, "ACCEPTED")

    def _repair_quality(self, aid):
        a = self.activities[aid]
        attempt = self._attempt(aid)
        p = self._product(a.product_id)
        require(a.code == "Q-POND", "UNKNOWN_DISMANTLING_METHOD_HOLD")
        require(attempt is not None and attempt.number == 0, "REPAIR_LIMIT_QUARANTINE_REQUIRED")
        require(
            any(
                q.activity_id == aid and q.attempt == 0 and q.result == "FAIL"
                for q in self.s.quality
            ),
            "REPAIR_REQUIRES_FAILED_INSPECTION",
        )
        require(
            not p.cancelled
            and not any(
                self.activities[r.activity_id].product_id == p.product_id for r in self.s.running
            )
            and not self.s.services,
            "REPAIR_COMMITMENT",
        )
        self._check_predecessors(a)
        self._require_evidence(("G7", "G4"), "UNKNOWN_REPAIR_METHOD_HOLD")
        kit = next(
            (x for x in self.s.materials if x.material_id == a.product_id + ".REPAIR-KIT"), None
        )
        require(
            kit is not None
            and kit.arrived
            and kit.identified
            and kit.released
            and kit.consumed_by is None,
            "REPAIR_MATERIAL",
        )
        people = ("QA1", "T1")
        sample = max(self._human(pid).fatigue + self.people[pid].work_rate * 0.5 for pid in people)
        duration = 0.5 + 1 * (1 + 0.5 * sample)
        self._protect(people, self.time + duration)
        sid = f"SERVICE-{len(self.s.events) + 1}"
        self._acquire(people, sid)
        self._set(
            materials=tuple(
                replace(x, consumed_by=sid) if x == kit else x for x in self.s.materials
            )
        )
        service = b.Service(
            sid,
            "REPAIR",
            aid,
            a.product_id,
            people,
            self.time,
            self.time + duration,
            None,
            None,
            "ACTIVE",
            None,
            None,
        )
        self._set(services=self.s.services + (service,))
        self._log(
            "REPAIR_START",
            aid,
            {
                "service": as_data(service),
                "diagnosis_base_h": 0.5,
                "repair_base_h": 1,
                "sample_after_diagnosis": sample,
                "replacement_kit": kit.material_id,
            },
            1,
        )

    def cleanup(self, product_id, *, roles=("Lop", "Lrig", "Lsig")):
        candidate = copy.copy(self)
        try:
            candidate._cleanup(product_id, roles)
        except ContractError as error:
            return Receipt(False, str(error))
        candidate._revision()
        self.s = candidate.s
        return Receipt(True, "ACCEPTED")

    def _cleanup(self, pid, roles):
        p = self._product(pid)
        require(p.cancelled or p.state == "QUALITY_HOLD", "CLEANUP_NOT_REQUIRED")
        require(p.location in ("J3", "F1", "OUT1"), "UNKNOWN_COMPONENT_CLEARANCE_HOLD")
        require(not p.water_present, "TEST_NOT_DRAINED")
        require(
            p.location not in self.s.failed_resources and "Q1" not in self.s.failed_resources,
            "CLEANUP_LOCATION_FAILED",
        )
        require(
            not any(self.activities[r.activity_id].product_id == pid for r in self.s.running)
            and not any(x.product_id == pid for x in self.s.services),
            "CLEANUP_COMMITTED_TAIL",
        )
        self._require_evidence(("G1", "G6", "G7"), "UNKNOWN_CLEARANCE_METHOD_HOLD")
        require(len(roles) == 3 and len(set(roles)) == 3, "CLEANUP_ROLES")
        for person, qual in zip(roles, ("CRANE", "RIG", "SIGNAL"), strict=True):
            require(
                person in self.people and qual in self.people[person].qualifications,
                "CLEANUP_QUALIFICATION",
            )
        product = self.products[pid]
        require(product.mass_t + product.rigging_t <= self.resources["CR1"].load_t, "MOVE_OVERLOAD")
        self._protect(roles, self.time + 1)
        sid = f"SERVICE-{len(self.s.events) + 1}"
        self._acquire(tuple(roles) + ("CR1", "ROUTE-MODULE"), sid)
        self._reserve(pid, "Q1", pid, True)
        service = b.Service(
            sid,
            "CLEANUP",
            pid + ".CLEANUP",
            pid,
            tuple(roles),
            self.time,
            self.time + 1,
            p.location,
            "Q1",
            "ACTIVE",
            None,
            None,
        )
        self._set(services=self.s.services + (service,))
        self._log("CLEANUP_START", pid, as_data(service))

    def _finish_service(self, service):
        self._release(service.id)
        self._set(services=tuple(x for x in self.s.services if x.id != service.id))
        if service.kind == "HANDOVER":
            self._log(
                "HANDOVER_COMPLETE",
                service.activity_id,
                {"incoming": service.replacement_person, "outgoing": service.outgoing_person},
            )
            new = replace(
                service,
                id=service.id + ".RESTORE",
                kind="RESTORE",
                people=(service.replacement_person,),
                start_h=self.time,
                end_h=self.time + 0.1,
            )
            self._acquire(new.people, new.id)
            self._set(services=self.s.services + (new,))
            self._log("RESTORE_START", service.activity_id, as_data(new))
        elif service.kind == "RESTORE":
            self._log("RESTORE_COMPLETE", service.activity_id)
        elif service.kind == "REPAIR":
            try:
                self._check_predecessors(self.activities[service.activity_id])
                require(not self._product(service.product_id).cancelled, "CANCELLED")
            except ContractError as error:
                self._log("REPAIR_STOPPED", service.activity_id, str(error), 1)
                return
            for code in ("WPROOF", "WAIT-W", "TEST-SET", "WAIT-TEST", "Q-POND"):
                aid = service.product_id + "." + code
                a = self.activities[aid]
                old = self._attempt(aid)
                require(old is not None and old.number == 0, "REPAIR_HISTORY")
                self._put_attempt(
                    b.Attempt(
                        aid,
                        1,
                        a.modes[0].id,
                        len(a.modes[0].units) if code == "WPROOF" else 0,
                        "COMPLETED" if code == "WPROOF" else "NOT_READY",
                        None,
                        code == "WPROOF",
                    )
                )
            self._set(
                released_processes=tuple(
                    x
                    for x in self.s.released_processes
                    if x not in (service.product_id + ".WAIT-W", service.product_id + ".WAIT-TEST")
                )
            )
            self._put_product(replace(self._product(service.product_id), state="IN_PROCESS"))
            self._start_waits()
            self._log("REPAIR_COMPLETE", service.activity_id, as_data(service), 1)
        elif service.kind == "CLEANUP":
            self._set(
                residencies=tuple(r for r in self.s.residencies if r.owner != service.product_id)
            )
            self._reserve(service.product_id, "Q1", service.product_id, False)
            self._put_product(
                replace(
                    self._product(service.product_id),
                    location="Q1",
                    state="QUARANTINED",
                    ready_h=None,
                )
            )
            self._log("CLEANUP_LANDED", service.product_id, as_data(service))
