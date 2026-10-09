"""Source-bound S15 decision records and independent prefix/receipt audit.

This does not invoke the planner, executor or admission predicates. Execution
validity is checked separately by production_checker; both reports must pass.
The production driver declares zero-delay, complete-prefix observations.
"""

import hashlib
import json
from dataclasses import replace
from itertools import islice

from adaptive_hrc_scheduling import production_supports as supports
from adaptive_hrc_scheduling.contracts.codec import (
    ContractError,
    as_data,
    canonical_json,
    decode,
)
from adaptive_hrc_scheduling.contracts.production import digest, legacy_fields, validate, wire
from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.production_checker import Finding, Report

PROTOCOL = "S15-DECISION-1"
FIELDS = {
    "schema_version",
    "config_id",
    "config_sha256",
    "run_id",
    "epoch",
    "observation_id",
    "state_revision",
    "sampled_h",
    "received_h",
    "state_sha256",
    "event_count",
    "event_ids_sha256",
    "plan",
    "rejected_parents",
    "receipt_id",
}
DISPATCH_KINDS = {"ACCEPTED", "STARTED", "REJECTED", "DEFERRED"}


def fingerprint(value):
    if isinstance(value, m.State):
        return _state_fingerprint(value)
    return _fingerprint(value)


def _state_fingerprint(value):
    if value.research is not None:
        return hashlib.sha256(canonical_json(value, normalize_numbers=True).encode()).hexdigest()
    return _fingerprint(value)


def _fingerprint(value):
    # Integer-valued floats and integers have identical numerical semantics in
    # a decoded State. Normalize only that representation difference, not time
    # tolerance, identifiers, array order, unknown fields or boolean types.
    def normalized(item):
        if isinstance(item, dict):
            return {k: normalized(v) for k, v in item.items()}
        if isinstance(item, list):
            return [normalized(v) for v in item]
        if isinstance(item, float) and item.is_integer():
            return int(item)
        return item

    data = as_data(value)
    if (
        getattr(value, "schema_version", None) == "S15-PROD-1.0"
        or isinstance(value, m.State)
        and value.research is None
    ):
        data = legacy_fields(data)
    return hashlib.sha256(
        json.dumps(
            normalized(data), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def record(decision):
    obs = decision.observation
    return {
        "schema_version": PROTOCOL,
        "config_id": obs.config_id,
        "config_sha256": obs.config_sha256,
        "run_id": obs.run_id,
        "epoch": obs.epoch,
        "observation_id": obs.id,
        "state_revision": obs.state.revision,
        "sampled_h": obs.sampled_h,
        "received_h": obs.received_h,
        "state_sha256": fingerprint(obs.state),
        "event_count": len(obs.event_ids),
        "event_ids_sha256": fingerprint(obs.event_ids),
        "plan": wire(decision.plan),
        "rejected_parents": list(decision.rejected_parents),
        "receipt_id": decision.receipt_id,
    }


def initial_visible_state(config):
    """Construct the declared initial observation without instantiating an executor."""
    return m.State(
        time_h=0,
        revision=0,
        lots=tuple(
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
            for x in config.lots
        ),
        reservations=(),
        positions=tuple(
            m.Position(x.id, x.initial_location, x.initial_location)
            for x in (*config.lots, *config.entities, *config.devices)
        )
        + tuple(m.Position(x.person_id, x.location, x.location) for x in config.person_positions),
        owners=(),
        products=tuple(
            m.ProductState(
                p.id,
                p.release_h == 0,
                False,
                0 if p.id in config.initial_ready_products else None,
                None,
            )
            for p in config.products
        ),
        humans=tuple(m.HumanState(p.id, p.initial_f, 0, p.initial_f, 0) for p in config.people),
        completed=(),
        running=(),
        gates=(),
        failed_resources=(),
        intervals=(),
        receive_permits=(),
        masses=tuple(m.MassState(x.id, 0) for x in config.entities),
        supports=supports.initial(config),
        research=config.research,
    )


def check_decisions(config, snapshot, records, *, checkpoint=None):
    findings = []
    incomplete = False

    def need(ok, reason, ident, *, missing=False):
        nonlocal incomplete
        if not ok:
            incomplete |= missing
            findings.append(Finding("R16", ident, reason))

    try:
        records = tuple(records)
        if checkpoint is not None:
            prior = checkpoint.reuse(config, snapshot, records)
            if prior is not None:
                return prior
        offset, saved = (
            checkpoint.restore_rows(config, snapshot, records)
            if checkpoint is not None
            else (0, None)
        )
        event_offset = len(saved["prefix"]) if saved is not None else 0
        stream = islice(snapshot.events, event_offset, None)
        next_event = next(stream, None)
        prefix = []
        state = initial_visible_state(config)
        previous = None
        config_hash = digest(config)
        seen_commands, observed_rejections = set(), set()
        count = 0
        if saved is not None:
            prefix, state = saved["prefix"], saved["state"]
            seen_commands, observed_rejections = (
                saved["seen_commands"],
                saved["observed_rejections"],
            )

        def consume(limit=None):
            nonlocal next_event, state
            receipts, initiated = [], []
            while next_event is not None and (limit is None or len(prefix) < limit):
                event = next_event
                need(event.sequence == len(prefix) + 1, "DECISION_EVENT_PREFIX_GAP", event.id)
                need(
                    (event.run_id, event.epoch, event.config_id, event.config_sha256)
                    == (snapshot.run_id, snapshot.epoch, config.id, snapshot.config_sha256),
                    "DECISION_EVENT_CONTEXT",
                    event.id,
                )
                prefix.append(event.id)
                state = event.state
                if event.kind in DISPATCH_KINDS:
                    initiated.append(event)
                if previous and event.id == previous[0]["receipt_id"]:
                    receipts.append(event)
                if event.kind == "EXCEPTION" and event.command:
                    observed_rejections.add(event.command.operation_id)
                next_event = next(stream, None)
            if previous is None:
                need(not initiated, "DISPATCH_WITHOUT_DECISION", "PREFIX", missing=True)
                return
            row, plan = previous
            ident = row["observation_id"]
            if not plan.commands:
                need(
                    row["receipt_id"] is None and not initiated,
                    "WAIT_WITH_DISPATCH_OR_RECEIPT",
                    ident,
                )
                return
            command = plan.commands[0]
            need(
                [e.kind for e in initiated]
                in (["ACCEPTED", "STARTED"], ["REJECTED"], ["DEFERRED"]),
                "MISSING_OR_EXTRA_DISPATCH",
                ident,
                missing=True,
            )
            need(all(e.command == command for e in initiated), "PLAN_DISPATCH_MISMATCH", ident)
            need(len(receipts) == 1, "RECEIPT_NOT_IN_DECISION_INTERVAL", ident, missing=True)
            if receipts:
                receipt = receipts[0]
                need(receipt.command == command, "PLAN_RECEIPT_MISMATCH", ident)
                need(
                    bool(initiated)
                    and (
                        receipt == initiated[-1]
                        or receipt.kind == "EXCEPTION"
                        and receipt.reason.startswith("PORT_START:")
                    ),
                    "NOT_THE_DISPATCH_RESULT",
                    ident,
                )
                need(
                    receipt.kind in DISPATCH_KINDS
                    or receipt.kind == "EXCEPTION"
                    and receipt.reason.startswith("PORT_START:"),
                    "NOT_A_DISPATCH_RECEIPT",
                    ident,
                )
                need(receipt.occurred_sim_h == row["sampled_h"], "DISPATCH_RECEIPT_TIME", ident)
                if receipt.kind != "STARTED":
                    observed_rejections.add(
                        plan.reason.removeprefix("PREPARE:")
                        if plan.reason.startswith("PREPARE:")
                        else command.operation_id
                    )

        for count, row in enumerate(records[offset:], offset + 1):
            if not isinstance(row, dict) or set(row) != FIELDS or row["schema_version"] != PROTOCOL:
                need(False, "MISSING_OR_UNKNOWN_DECISION_SCHEMA", f"DECISION-{count}", missing=True)
                break
            ident = row["observation_id"]
            n = row["event_count"]
            if type(n) is not int or n < 0 or (previous is not None and n <= len(prefix)):
                need(False, "INVALID_OR_REPEATED_OBSERVATION_PREFIX", ident)
                break
            consume(n)
            need(len(prefix) == n, "OBSERVATION_PREFIX_MISSING", ident, missing=True)
            need(
                (row["config_id"], row["config_sha256"], row["run_id"], row["epoch"])
                == (config.id, config_hash, snapshot.run_id, snapshot.epoch),
                "DECISION_CONTEXT",
                ident,
            )
            need(
                row["state_revision"] == state.revision and ident == f"OBS-{state.revision}",
                "OBSERVATION_VERSION_OR_ID",
                ident,
            )
            need(
                row["sampled_h"] == row["received_h"] == state.time_h,
                "OBSERVATION_NOT_CURRENT_DELIVERED_PREFIX",
                ident,
            )
            need(row["state_sha256"] == fingerprint(state), "OBSERVATION_STATE_DIGEST", ident)
            need(
                row["event_ids_sha256"] == fingerprint(tuple(prefix)),
                "OBSERVATION_EVENT_IDS_DIGEST",
                ident,
            )
            excluded = row["rejected_parents"]
            need(
                isinstance(excluded, list)
                and len(set(excluded)) == len(excluded)
                and set(excluded) <= observed_rejections,
                "UNOBSERVED_REJECTION_FILTER",
                ident,
            )
            plan = decode(
                m.Plan,
                legacy_fields(row["plan"], expand=True)
                if config.schema_version == "S15-PROD-1.0"
                else row["plan"],
            )
            validate(plan, config=config)
            need(
                plan.observation_id == ident and plan.config_id == config.id,
                "PLAN_OBSERVATION_CONTEXT",
                ident,
            )
            need(
                len(plan.commands) <= 1
                and (
                    plan.status == "CANDIDATE"
                    if plan.commands
                    else plan.status in ("WAIT", "NO_PLAN_FOUND")
                ),
                "PLAN_COMMAND_STATUS",
                ident,
            )
            for command in plan.commands:
                need(
                    (command.run_id, command.epoch, command.expected_revision, command.issued_sim_h)
                    == (snapshot.run_id, snapshot.epoch, state.revision, state.time_h),
                    "COMMAND_OBSERVATION_CONTEXT",
                    ident,
                )
                need(command.id not in seen_commands, "DUPLICATE_DECISION_COMMAND", ident)
                seen_commands.add(command.id)
                need(command.operation_id not in excluded, "DISPATCH_EXCLUDED_OPERATION", ident)
            previous = (row, plan)
        consume()
        need(count > 0 and previous is not None, "MISSING_DECISIONS", "SNAPSHOT", missing=True)
        if previous:
            row, plan = previous
            need(
                not plan.commands and row["event_count"] == len(prefix),
                "MISSING_TERMINAL_OBSERVATION",
                row["observation_id"],
                missing=True,
            )
        need(
            fingerprint(state) == fingerprint(replace(snapshot.state, intervals=())),
            "DECISION_FINAL_STATE_MISMATCH",
            "SNAPSHOT",
        )
    except (ContractError, TypeError, ValueError, KeyError, IndexError, AttributeError) as exc:
        need(False, "MALFORMED_DECISION_HISTORY:" + str(exc), "SNAPSHOT", missing=True)
    report = Report(
        "INCOMPLETE" if incomplete else "INVALID" if findings else "PASS", tuple(findings), None
    )
    if checkpoint is not None and report.status == "PASS":
        checkpoint.save_rows(
            config,
            snapshot,
            records,
            dict(
                prefix=prefix,
                state=state,
                seen_commands=seen_commands,
                observed_rejections=observed_rejections,
            ),
        )
        checkpoint.certify(config, snapshot, report, records)
    return report
