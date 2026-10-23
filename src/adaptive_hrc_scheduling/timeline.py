"""P044 delivered-prefix timeline packets and a read-only, fail-closed consumer."""

from copy import deepcopy
from time import monotonic

from .contracts.codec import as_data, require
from .contracts.session import canonical, digest

FORMAT = "P044-TIMELINE-2"


class TimelinePublisher:
    def __init__(self, session):
        self.session = session
        self.cursor = 0
        self.event_cursor = 0
        self.previous = "0" * 64
        self.rows = {}
        self.commands = {}
        self.owners = {}
        self.plans = []
        self.last_plan = None
        self.receipt_cursor = 0
        self.interval_cursor = 0

    def publish(self, observation, plan=None):
        from .control.session import save_atomic

        s, w = self.session, self.session.world
        require(observation.event_ids == tuple(e.id for e in w.events), "PROJECTION_PREFIX")
        before = deepcopy(self.rows)
        events = w.events[self.event_cursor :]
        for event in events:
            command = event.command
            if command and event.kind == "STARTED":
                self.commands[command.id] = command
                operation = (
                    command.service.operation
                    if command.service
                    else w.operations[command.operation_id]
                )
                require(operation.id == command.operation_id, "PROJECTION_OPERATION")
                binding = s.command_bindings.get(command.id)
                require(binding is not None, "PROJECTION_COMMAND_BINDING")
                key = "actual:" + command.id
                self.rows[key] = dict(
                    row_id=key,
                    row_kind="FACT_PREFIX",
                    schedule_state="ACTUAL",
                    command_id=command.id,
                    product_id=command.product_id,
                    order_id=w._product(command.product_id).product_id,
                    operation_id=command.operation_id,
                    activity_id=command.activity_id,
                    attempt=command.attempt,
                    mode=command.mode_id,
                    roles=as_data(command.roles),
                    equipment=list(operation.equipment),
                    operation_sha256=digest(as_data(operation)),
                    admitted_catalog_version=binding["admitted_catalog_version"],
                    admitted_catalog_hash=binding["admitted_catalog_hash"],
                    start_h=event.occurred_sim_h,
                    end_status="OPEN",
                    start_event_id=event.id,
                    start_event_sequence=event.sequence,
                )
                self.rows[key]["order_id"] = next(
                    p.order_id for p in w.config.products if p.id == command.product_id
                )
            if command and event.kind in ("COMPLETED", "EXCEPTION"):
                key = "actual:" + command.id
                if key in self.rows:
                    row = self.rows[key]
                    row["execution_status"] = event.kind
                    if event.kind == "COMPLETED":
                        require(event.readback is not None, "PROJECTION_READBACK_REQUIRED")
                        row.update(
                            end_h=event.occurred_sim_h,
                            end_status="CLOSED",
                            end_event_id=event.id,
                            readback_id=event.readback.evidence_id,
                        )
            # Actual occupancy follows owners, including holds beyond command end.
            current = {(o.resource_id, o.command_id) for o in event.state.owners}
            for pair in current - self.owners.keys():
                key = f"resource:{event.sequence}:{pair[0]}:{pair[1]}"
                self.owners[pair] = key
                self.rows[key] = dict(
                    row_id=key,
                    row_kind="RESOURCE_FACT",
                    schedule_state="ACTUAL",
                    resource_id=pair[0],
                    command_id=pair[1],
                    start_h=event.occurred_sim_h,
                    start_event_id=event.id,
                    end_status="OPEN",
                )
            for pair in self.owners.keys() - current:
                key = self.owners.pop(pair)
                self.rows[key].update(
                    end_h=event.occurred_sim_h, end_status="CLOSED", end_event_id=event.id
                )
            if event.world or event.kind == "EXCEPTION":
                key = "marker:" + event.id
                self.rows[key] = dict(
                    row_id=key,
                    row_kind="MARKER",
                    schedule_state="ACTUAL",
                    event_id=event.id,
                    sim_h=event.occurred_sim_h,
                    kind=event.world.kind if event.world else event.kind,
                    target_id=event.world.entity_id if event.world else event.command_id,
                )
        for row in self.rows.values():
            if row.get("end_status") == "OPEN":
                row["observed_until_h"] = observation.sampled_h
        if plan is not None:
            data = as_data(plan)
            key = digest(data)
            if key != self.last_plan:
                version = len(self.plans) + 1
                source = s.policy.journal[-1] if s.policy.journal else {}
                self.plans.append(
                    dict(
                        plan_version=version,
                        observation_id=observation.id,
                        event_count=len(observation.event_ids),
                        event_prefix_hash=s.event_prefix_hash(),
                        plan=data,
                        reason_event_ids=[e.id for e in events],
                        journal=deepcopy(source),
                        proposal_state="CANDIDATE",
                    )
                )
                for command in plan.commands:
                    row_id = f"plan:{version}:{command.id}"
                    self.rows[row_id] = dict(
                        row_id=row_id,
                        row_kind="PLAN",
                        plan_version=version,
                        proposal_state="CANDIDATE",
                        schedule_state="COMMITTED"
                        if command in s.policy.committed
                        else "TENTATIVE",
                        operation_id=command.operation_id,
                        product_id=command.product_id,
                        command_id=command.id,
                        start_h=command.issued_sim_h,
                        end_status="UNKNOWN",
                        mode=command.mode_id,
                        roles=as_data(command.roles),
                    )
                self.last_plan = key
        for row in self.rows.values():
            if row["row_kind"] == "PLAN" and "command_id" in row:
                command_id = row["command_id"]
                if command_id in self.commands:
                    row["proposal_state"] = "ADOPTED"
                    row["adoption_event_id"] = self.rows["actual:" + command_id]["start_event_id"]
                elif row["plan_version"] < len(self.plans):
                    row["proposal_state"] = "SUPERSEDED"
        scheduled = {
            r["operation_id"]
            for r in self.rows.values()
            if r["row_kind"] in ("FACT_PREFIX", "PLAN")
            and r["schedule_state"] != "UNSCHEDULED"
            and r.get("proposal_state") != "SUPERSEDED"
        }
        for operation in w.config.operations:
            key = "unscheduled:" + operation.id
            if operation.id not in scheduled and operation.id not in w.s.completed:
                self.rows[key] = dict(
                    row_id=key,
                    row_kind="PLAN",
                    operation_id=operation.id,
                    product_id=operation.product_id,
                    schedule_state="UNSCHEDULED",
                    end_status="UNKNOWN",
                )
            else:
                self.rows.pop(key, None)
        from .workforce_metrics import project

        metrics = project(s.spec, s.history, w.snapshot())
        by_interval = {
            (pid, x["start_h"], x["end_h"]): x
            for pid, data in metrics["people"].items()
            for x in data["activity_intervals"]
        }
        for index, interval in enumerate(
            w.s.intervals[self.interval_cursor :], self.interval_cursor
        ):
            key = "person:" + str(index)
            flags = by_interval[(interval.person_id, interval.start_h, interval.end_h)]
            self.rows[key] = dict(
                row_id=key,
                row_kind="PERSON_INTERVAL",
                schedule_state="ACTUAL",
                **as_data(interval),
                presence=flags["presence"],
                availability=flags["availability"],
                labour_cost=(interval.end_h - interval.start_h)
                * metrics["people"][interval.person_id]["rate_per_h"]
                if flags["presence"]
                else 0,
            )
        self.interval_cursor = len(w.s.intervals)
        envelope = dict(
            format=FORMAT,
            run_id=s.spec["run_id"],
            epoch=s.spec["epoch"],
            run_spec_sha256=digest(s.spec),
            initial_config_sha256=s.spec["initial_config_sha256"],
            catalog_version=s.version,
            catalog_hash=s.versions[-1],
            materialized_catalog_sha256=digest(s.catalog),
            state_revision=observation.state.revision,
            observation_id=observation.id,
            event_count=len(observation.event_ids),
            event_prefix_hash=s.event_prefix_hash(),
            plan_version=len(self.plans),
            sampled_sim_h=observation.sampled_h,
            received_sim_h=observation.received_h,
            sampled_monotonic_s=monotonic(),
            source_status="VERIFIED_DELIVERED_PREFIX",
        )
        upserts = [v for k, v in self.rows.items() if before.get(k) != v]
        packet = dict(
            format=FORMAT,
            sequence=self.cursor + 1,
            previous_packet_sha256=self.previous,
            envelope=envelope,
            upserts=upserts,
            removed=sorted(before.keys() - self.rows.keys()),
            events=[as_data(e) for e in events],
            receipts=deepcopy(s.receipts[self.receipt_cursor :]),
            catalog=deepcopy(s.catalog),
            orders=[
                dict(
                    as_data(p),
                    priority=s.history.priorities.get(
                        p.id,
                        next(
                            (
                                x["priority"]
                                for x in s.spec["initial_orders"]
                                if x["order_id"] == p.order_id
                            ),
                            "NORMAL",
                        ),
                    ),
                )
                for p in w.config.products
            ],
            people=[as_data(p) for p in w.config.people],
            devices=[as_data(d) for d in w.config.devices],
            failed_resources=list(w.s.failed_resources),
            workforce_statistics=metrics,
            business_results=deepcopy(s.business_results),
            scene_bindings=deepcopy(s.scene_bindings),
            cache_transitions=deepcopy(s.transitions),
            plan=self.plans[-1] if plan is not None and self.plans else None,
            source_basis=dict(spec=deepcopy(s.spec), configuration=as_data(s.history.initial))
            if self.cursor == 0
            else None,
            source=dict(
                observation=as_data(observation),
                generations=deepcopy(s.history.generations),
                deltas=deepcopy(s.deltas),
                command_bindings=deepcopy(s.command_bindings),
                intervals=as_data(w.s.intervals),
                plans=deepcopy(self.plans),
            ),
        )
        packet["packet_sha256"] = digest(packet)
        with (s.output / "timeline.jsonl").open("ab") as stream:
            stream.write(canonical(packet) + b"\n")
        self.cursor += 1
        self.previous = packet["packet_sha256"]
        self.event_cursor = len(w.events)
        self.receipt_cursor = len(s.receipts)
        save_atomic(
            s.output / "timeline-latest.json",
            dict(
                envelope=envelope,
                sequence=self.cursor,
                packet_sha256=self.previous,
                rows=list(self.rows.values()),
                provenance="REPLAY_VERIFIED_PACKET_PREFIX_REQUIRED",
            ),
        )


class TimelineConsumer:
    """No writer handle. Retain the last verified view after a gap or corruption."""

    def __init__(self, run_id, epoch, run_spec_sha256):
        self.identity = (run_id, epoch, run_spec_sha256)
        self.sequence = 0
        self.previous = "0" * 64
        self.rows = {}
        self.events = []
        self.envelope = None
        self.status = "UNKNOWN"
        self.received_local = None
        self.basis = None
        self.orders = []

    def consume(self, packet):
        p = deepcopy(packet)
        try:
            require(p["format"] == FORMAT, "TIMELINE_FORMAT")
            require(
                p["packet_sha256"] == digest({k: v for k, v in p.items() if k != "packet_sha256"}),
                "TIMELINE_DIGEST",
            )
            e = p["envelope"]
            require(
                e["format"] == FORMAT and e["source_status"] == "VERIFIED_DELIVERED_PREFIX",
                "TIMELINE_ENVELOPE_FORMAT",
            )
            require(
                (e["run_id"], e["epoch"], e["run_spec_sha256"]) == self.identity,
                "TIMELINE_IDENTITY",
            )
            if p["sequence"] == self.sequence and p["packet_sha256"] == self.previous:
                return False
            require(
                p["sequence"] == self.sequence + 1 and p["previous_packet_sha256"] == self.previous,
                "TIMELINE_GAP",
            )
            events = self.events + p["events"]
            require(
                len(events) == e["event_count"] and digest(events) == e["event_prefix_hash"],
                "TIMELINE_PREFIX",
            )
            require(digest(p["catalog"]) == e["materialized_catalog_sha256"], "TIMELINE_CATALOG")
            require(
                self.envelope is None or e["sampled_sim_h"] >= self.envelope["sampled_sim_h"],
                "TIMELINE_TIME",
            )
            for row in p["upserts"]:
                require(
                    row["schedule_state"] in ("ACTUAL", "COMMITTED", "TENTATIVE", "UNSCHEDULED"),
                    "TIMELINE_STATE",
                )
                require(
                    row["row_kind"] != "PLAN" or row["schedule_state"] != "ACTUAL",
                    "TIMELINE_PLAN_AS_FACT",
                )
                if row["row_kind"] == "FACT_PREFIX":
                    starts = [x for x in events if x["id"] == row.get("start_event_id")]
                    require(
                        len(starts) == 1
                        and starts[0]["kind"] == "STARTED"
                        and starts[0]["command_id"] == row.get("command_id")
                        and starts[0]["occurred_sim_h"] == row.get("start_h"),
                        "TIMELINE_FALSE_FACT",
                    )
                    if row.get("end_status") == "CLOSED":
                        ends = [x for x in events if x["id"] == row.get("end_event_id")]
                        require(
                            len(ends) == 1
                            and ends[0]["kind"] == "COMPLETED"
                            and ends[0]["command_id"] == row["command_id"]
                            and ends[0]["readback"] is not None
                            and ends[0]["occurred_sim_h"] == row.get("end_h"),
                            "TIMELINE_FALSE_END",
                        )
                if row.get("proposal_state") == "ADOPTED":
                    require(
                        any(
                            x["id"] == row.get("adoption_event_id")
                            and x["kind"] == "STARTED"
                            and x["command_id"] == row.get("command_id")
                            for x in events
                        ),
                        "TIMELINE_FALSE_ADOPTION",
                    )
            rows = deepcopy(self.rows)
            require(
                len({r["row_id"] for r in p["upserts"]}) == len(p["upserts"])
                and len(set(p["removed"])) == len(p["removed"]),
                "TIMELINE_DUPLICATE_ROW",
            )
            for key in p["removed"]:
                rows.pop(key, None)
            rows.update({r["row_id"]: r for r in p["upserts"]})
            from .timeline_validation import validate

            basis = p["source_basis"] if self.sequence == 0 else self.basis
            require(self.sequence == 0 or p["source_basis"] is None, "TIMELINE_BASIS_CHANGE")
            validate(p, events, rows, basis)
        except (KeyError, TypeError, ValueError, IndexError, StopIteration, AttributeError):
            self.status = "STALE_CORRUPT"
            raise
        self.rows, self.events, self.envelope = rows, events, e
        self.basis, self.orders = basis, p["orders"]
        self.sequence, self.previous = p["sequence"], p["packet_sha256"]
        self.received_local = monotonic()
        self.status = "VERIFIED"
        return True

    def view(self, *, product_id=None, resource_id=None, stale_after_s=5):
        rows = [
            deepcopy(r)
            for r in self.rows.values()
            if (product_id is None or r.get("product_id") == product_id)
            and (resource_id is None or r.get("resource_id", r.get("person_id")) == resource_id)
        ]
        age = None if self.received_local is None else monotonic() - self.received_local
        return dict(
            envelope=deepcopy(self.envelope),
            rows=rows,
            orders=deepcopy(self.orders),
            status="STALE" if self.status == "VERIFIED" and age > stale_after_s else self.status,
            wall_age_status="AGE_UNKNOWN",
            local_residence_s=age,
        )

    def export(self, path, **selection):
        from pathlib import Path

        Path(path).write_bytes(canonical(dict(self.view(**selection), selection=selection)))


def compare_envelopes(left, right):
    require(
        (left["run_id"], left["epoch"]) == (right["run_id"], right["epoch"]), "DUAL_VIEW_IDENTITY"
    )
    fields = (
        "run_spec_sha256",
        "initial_config_sha256",
        "catalog_version",
        "catalog_hash",
        "materialized_catalog_sha256",
        "state_revision",
        "observation_id",
        "event_count",
        "event_prefix_hash",
        "plan_version",
        "sampled_sim_h",
    )
    return "SAME_OBSERVATION" if all(left[k] == right[k] for k in fields) else "ASYNCHRONOUS"
