"""P044 bounded continuous driver, separate from historical checkpoint sessions."""

import math
from time import perf_counter as monotonic
from time import sleep

from adaptive_hrc_scheduling.building_human import calendar_state
from adaptive_hrc_scheduling.contracts.codec import as_data, require
from adaptive_hrc_scheduling.contracts.session import digest, validate_record

IDENTITY = "P04.4-SESSION-r1"


def enable(spec, **clock):
    """Explicitly opt a newly created RunSpec into the complete lifetime contract."""
    from copy import deepcopy

    from adaptive_hrc_scheduling.contracts.session import validate_spec

    result = deepcopy(spec)
    result["schema_version"] = IDENTITY
    result["clock"].update(clock)
    return validate_spec(result)


class Lifecycle:
    def __init__(self, session):
        self.session = session
        self.started = monotonic()
        self.phase = "STARTING"
        self.transitions = []
        self.meter = []
        self.final = None
        self.last_advance = None
        self.stop_intake = False
        self.driver = {}
        self.change("RUNNING_OPEN", "LAUNCH")

    @property
    def continuous(self):
        return self.session.spec["mode"] != "FIXED_PROTOCOL"

    def change(self, phase, reason):
        if phase != self.phase:
            self.phase = phase
            self.transitions.append(
                dict(
                    phase=phase,
                    reason=reason,
                    sim_h=self.session.world.s.time_h,
                    wall_s=monotonic() - self.started,
                    event_count=len(self.session.world.events),
                )
            )

    def pending(self):
        s = self.session
        return [
            key
            for key, a in s.admissions.items()
            if next(
                r
                for r in reversed(s.receipts)
                if r["request_id"] == key and r.get("accept_sequence") == a["sequence"]
            )["status"]
            in ("ACCEPTED", "WAITING_BOUNDARY")
        ]

    def obligations(self):
        s, w = self.session, self.session.world
        unreceived = [
            p.product_id for p in w.s.products if not p.cancelled and p.received_h is None
        ]
        physical = [
            x.id
            for x in (*w.config.lots, *w.config.entities)
            if w._mass(x.id) > 1e-9
            and w._position(x.id).location
            not in (
                "SUPPLIER",
                "UNPRODUCED",
                "UNFABRICATED",
                "UNASSEMBLED",
                "EXTERNAL",
                "INCORPORATED",
            )
        ]
        # Received products legitimately remain at the receiving station.
        received = {p.product_id for p in w.s.products if p.received_h is not None}
        physical = [
            key
            for key in physical
            if next(x.product_id for x in (*w.config.lots, *w.config.entities) if x.id == key)
            not in received
        ]
        return dict(
            pending_requests=self.pending(),
            open_products=unreceived,
            physical_residuals=physical,
            running=[r.command.id for r in w.s.running],
            holds=[as_data(x) for x in w.s.owners],
            reservations=[as_data(x) for x in w.s.reservations],
            commitments=[
                c.id
                for c in s.policy.committed
                if c.operation_id not in w.s.completed and not w._product(c.product_id).cancelled
            ],
            expected_receipts_complete=not unreceived,
        )

    def clear(self):
        return all(
            not v for k, v in self.obligations().items() if k != "expected_receipts_complete"
        )

    def limit(self):
        w, clock = self.session.world, self.session.spec["clock"]
        if monotonic() - self.started >= clock["wall_budget_s"]:
            return "WALL_CENSORED"
        if w.s.time_h >= clock["session_until_h"] - 1e-12:
            return "WINDOW_CENSORED"
        if self.session.account.used >= self.session.account.profile.total_seconds:
            return "COMPUTE_CENSORED"
        return None

    def waiting_phase(self):
        if self.session.closed:
            return "DRAINING"
        return (
            "WAITING_BOUNDARY"
            if any(
                self.obligations()[k]
                for k in (
                    "pending_requests",
                    "open_products",
                    "physical_residuals",
                    "running",
                    "holds",
                )
            )
            else "WAITING_INPUT"
        )

    def advance(self, requested, *, idle=False):
        """One bounded step; no catch-up jump after slow search or Kit work."""
        s, w = self.session, self.session.world
        self.last_advance = None
        c = s.spec["clock"]
        start = w.s.time_h
        end = min(
            requested,
            c["session_until_h"],
            start + c["idle_step_h"],
            start + c["simulation_rate"] * c["boundary_poll_wall_s"],
        )
        times = [t for t in s.request_boundaries() if t > start]
        times += [
            r.earliest_end_h
            for r in w.s.running
            if r.status == "STARTED" and r.earliest_end_h > start
        ]
        busy = {r.person_id for run in w.s.running for r in run.command.roles}
        for person in w.config.people:
            phase, bound = calendar_state(person, start)
            times.append(bound)
            if person.valid_until_h > start:
                times.append(person.valid_until_h)
            human = next(h for h in w.s.humans if h.person_id == person.id)
            from adaptive_hrc_scheduling.dynamic_workforce import off_shift

            if person.id not in busy and phase == "WAIT" and not off_shift(w.s, person.id):
                if person.wait_rate:
                    contact = start + max(0, w.config.cap - human.fatigue) / person.wait_rate
                    times.append(max(start, math.nextafter(contact, start)))
        if times:
            end = min(end, min(times))
        if end <= start + 1e-12:
            return "DRAIN_BLOCKED"  # protected HOLD, never clip F or cross a cap
        remaining = c["wall_budget_s"] - (monotonic() - self.started)
        delay = (end - start) / c["simulation_rate"] if self.continuous else 0
        if remaining <= 0:
            return "WALL_CENSORED"
        began = monotonic()
        sleep(min(delay, remaining))
        elapsed = monotonic() - began
        if elapsed >= remaining:
            return "WALL_CENSORED"
        # Producer queues remain writable during the wait. Apply at this boundary
        # before advancing, then re-evaluate bounds on the next loop iteration.
        if not s.queue.empty() or any(
            p.name not in s.ingress_seen for p in (s.output / "inbox").glob("*.json")
        ):
            self.last_advance = "INPUT_WAKE"
            self.meter.append(
                dict(start_h=start, end_h=start, wall_s=elapsed, idle=idle, reason="INPUT_WAKE")
            )
            return None
        if hasattr(s.backend, "world"):
            s.backend.advance_to(end)
            s.backend.deliver()
        else:
            w.advance(end)
        self.meter.append(
            dict(
                start_h=start, end_h=w.s.time_h, wall_s=elapsed, idle=idle, reason="ADVANCE_METERED"
            )
        )
        self.last_advance = "ADVANCE_METERED"
        return None

    def data(self):
        return dict(
            identity=IDENTITY,
            revision="P044-LIFECYCLE-2",
            phase=self.phase,
            transitions=self.transitions,
            meter=self.meter,
            elapsed_wall_s=monotonic() - self.started,
            obligations=self.obligations(),
            final=self.final,
            stop_control=getattr(self, "stop_control", None),
            commitments=as_data(self.session.policy.committed),
            driver=self.driver,
        )

    def finish(self, reason, audit="UNKNOWN"):
        from .session import save_atomic

        s = self.session
        phase = {
            "OPERATIONS_COMPLETE": "COMPLETED",
            "ORDERLY_STOPPED": "STOPPED",
            "ORDERLY_STOP_BLOCKED": "STOP_BLOCKED",
            "COMPUTE_CENSORED": "WINDOW_CENSORED",
            "TURN_LIMIT": "WINDOW_CENSORED",
            "DECLARED_CHECKPOINT": "WINDOW_CENSORED",
        }.get(reason, reason)
        if phase not in (
            "COMPLETED",
            "STOPPED",
            "STOP_BLOCKED",
            "WINDOW_CENSORED",
            "WALL_CENSORED",
            "DRAIN_BLOCKED",
            "FAILED",
        ):
            phase = "DRAIN_BLOCKED"
        if audit == "FAIL":
            phase = "FAILED"
        if phase == "COMPLETED":
            require(self.clear() and (s.closed or not self.continuous), "DRAIN_NOT_CLEAR")
            require(audit == "PASS", "FINAL_AUDIT_REQUIRED")
        s.terminal = True  # single writer fence before final durable transaction
        self.change(phase, reason)
        o = self.obligations()
        self.final = dict(
            phase=phase,
            intake_closed=s.closed,
            pending_requests=len(o["pending_requests"]),
            open_obligations=sum(
                len(o[k])
                for k in ("open_products", "physical_residuals", "reservations", "commitments")
            ),
            running=len(o["running"]),
            holds=len(o["holds"]),
            expected_receipts_complete=o["expected_receipts_complete"],
            audit_status=audit,
            save_status="UNKNOWN",
            catalog_version=s.version,
            last_prefix_hash=s.event_prefix_hash(),
            run_id=s.spec["run_id"],
            epoch=s.spec["epoch"],
            run_spec_sha256=digest(s.spec),
        )
        validate_record("SessionFinal", self.final)
        s.persist()
        # A commit record binds the saved final state. Process exit is external.
        self.final["save_status"] = "COMPLETE"
        s.persist()
        import hashlib

        save_atomic(
            s.output / "final-commit.json",
            dict(
                final=self.final,
                reason=reason,
                session_state_sha256=hashlib.sha256(
                    (s.output / "session-state.json").read_bytes()
                ).hexdigest(),
                projection_files={
                    name: hashlib.sha256((s.output / name).read_bytes()).hexdigest()
                    for name in ("timeline.jsonl", "timeline-latest.json")
                    if phase != "FAILED" or (s.output / name).is_file()
                },
                process_exit="UNKNOWN",
                obligations=o,
                final_sim_h=s.world.s.time_h,
                final_wall_s=monotonic() - self.started,
            ),
        )
