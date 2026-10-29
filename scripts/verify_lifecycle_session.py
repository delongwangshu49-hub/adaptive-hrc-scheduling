"""Independent P044 final-state, metering and delivered timeline reconstruction."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from verify_session import sha
from verify_workforce_session import verify as verify_workforce

from adaptive_hrc_scheduling.contracts.codec import as_data, decode
from adaptive_hrc_scheduling.contracts.session import validate_record
from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.dynamic_workforce import WorkforceHistory


def verify(directory):
    root = Path(directory)

    def read(name):
        return json.loads((root / name).read_text(encoding="utf-8"))

    checks = []

    def check(value, reason):
        if not value:
            raise ValueError(reason)
        checks.append(reason)

    base = verify_workforce(root, require_decisions=True)
    spec, state, commit = (
        read("run-spec.json"),
        read("session-state.json"),
        read("final-commit.json"),
    )
    check(spec["schema_version"] == "P04.4-SESSION-r1", "LIFETIME_IDENTITY")
    check(
        hashlib.sha256((root / "session-state.json").read_bytes()).hexdigest()
        == commit["session_state_sha256"],
        "FINAL_STATE_COMMIT",
    )
    life = state["lifecycle"]
    final = life["final"]
    validate_record("SessionFinal", final)
    raw = state["execution"]["state"]
    events = state["execution"]["events"]
    check(final == commit["final"] and state["terminal"], "TERMINAL_COMMIT")
    check(
        (final["run_id"], final["epoch"], final["run_spec_sha256"])
        == (spec["run_id"], spec["epoch"], sha(spec)),
        "FINAL_RUNSPEC",
    )
    check(final["last_prefix_hash"] == sha(events), "FINAL_PREFIX")
    check(
        set(commit["projection_files"]) == {"timeline.jsonl", "timeline-latest.json"},
        "REQUIRED_PROJECTION_COMMIT",
    )
    check(
        final["phase"] == life["phase"] == life["transitions"][-1]["phase"]
        and commit["reason"] == life["transitions"][-1]["reason"]
        and commit["final_sim_h"] == raw["time_h"]
        and final["catalog_version"] == len(state["versions"]) - 1,
        "FINAL_CONSISTENCY",
    )
    check(
        final["phase"]
        in (
            "COMPLETED",
            "STOPPED",
            "STOP_BLOCKED",
            "WINDOW_CENSORED",
            "WALL_CENSORED",
            "DRAIN_BLOCKED",
            "FAILED",
        ),
        "FINAL_PHASE_ENUM",
    )
    reason = commit["reason"]
    if final["phase"] == "WINDOW_CENSORED":
        check(
            (
                reason == "WINDOW_CENSORED"
                and raw["time_h"] >= spec["clock"]["session_until_h"] - 1e-12
            )
            or (
                reason == "COMPUTE_CENSORED"
                and state["budget"]["used_s"] >= read("profile.json")["total_seconds"]
            )
            or (
                reason == "TURN_LIMIT"
                and life.get("driver", {}).get("turn_limit", 0) > 0
                and life["driver"]["turns_entered"] == life["driver"]["turn_limit"]
            )
            or (
                reason == "DECLARED_CHECKPOINT"
                and life.get("driver", {}).get("checkpoint_reached") is True
            ),
            "WINDOW_LIMIT_EVIDENCE",
        )
    if final["phase"] == "WALL_CENSORED":
        check(
            reason == "WALL_CENSORED" and life["elapsed_wall_s"] >= spec["clock"]["wall_budget_s"],
            "WALL_LIMIT_EVIDENCE",
        )
    for phase, why in (
        ("COMPLETED", "OPERATIONS_COMPLETE"),
        ("STOPPED", "ORDERLY_STOPPED"),
        ("STOP_BLOCKED", "ORDERLY_STOP_BLOCKED"),
    ):
        if final["phase"] == phase:
            check(reason == why, "FINAL_REASON:" + phase)
    if final["phase"] == "STOPPED":
        check(not raw["running"], "STOPPED_RUNNING_CLEAR")
    if final["phase"] == "STOP_BLOCKED":
        check(bool(raw["running"]), "STOP_BLOCKED_RUNNING")
    for name, expected in commit["projection_files"].items():
        check(
            hashlib.sha256((root / name).read_bytes()).hexdigest() == expected,
            "PROJECTION_COMMIT:" + name,
        )
    check(final["save_status"] == "COMPLETE" and final["audit_status"] == "PASS", "FINAL_AUDITS")
    check(
        "process_exit_code" not in final and commit["process_exit"] == "UNKNOWN", "NO_INFERRED_EXIT"
    )
    receipts = state["receipts"]
    pending = []
    for key, a in state["admissions"].items():
        last = next(
            r
            for r in reversed(receipts)
            if r["request_id"] == key and r.get("accept_sequence") == a["sequence"]
        )
        if last["status"] in ("ACCEPTED", "WAITING_BOUNDARY"):
            pending.append(key)
        accepted = next(r for r in receipts if r["request_id"] == key and r["status"] == "ACCEPTED")
        req = state["requests"][key]
        due = req.get("requested_sim_h", accepted["sim_h"])
        check(a["due_h"] == due, "RESOLVED_TIME:" + key)
        if last["status"] == "APPLIED":
            check(due <= last["sim_h"] <= req["expires_sim_h"], "APPLIED_WINDOW:" + key)
    check(final["pending_requests"] == len(pending), "PENDING_REBUILT")
    check(
        final["running"] == len(raw["running"]) and final["holds"] == len(raw["owners"]),
        "RUNNING_HOLDS_REBUILT",
    )
    open_products = [p for p in raw["products"] if not p["cancelled"] and p["received_h"] is None]
    check(final["expected_receipts_complete"] == (not open_products), "RECEIPTS_REBUILT")
    closes = [
        r
        for r in receipts
        if r["status"] == "APPLIED" and state["requests"][r["request_id"]]["kind"] == "CLOSE_INPUT"
    ]
    check(final["intake_closed"] == state["closed"] == bool(closes), "CLOSE_EVIDENCE")
    if closes:
        close = closes[0]
        fence = max(
            r["accept_sequence"]
            for r in receipts[: close["receipt_sequence"]]
            if r["status"] == "ACCEPTED"
        )
        check(fence == state["close_accept_sequence"], "CLOSE_FENCE")
        check(
            not any(
                r["status"] == "ACCEPTED"
                and r["accept_sequence"] > fence
                and state["requests"][r["request_id"]]["kind"] in ("ORDER_CREATE", "PERSON_ARRIVE")
                for r in receipts
            ),
            "CLOSED_NEW_INTAKE",
        )
    history = WorkforceHistory(
        decode(m.Configuration, read("configuration.json")), state["generations"]
    )
    journal = read("online-journal.json")
    from adaptive_hrc_scheduling.full_schedule import is_fixed

    full_schedule = is_fixed(history.initial)
    if full_schedule:
        check(
            all(
                r.get("phase") == "FULL_PLAN_BUILD"
                or r.get("selected_source") == "VERIFIED_FULL_PLAN"
                for r in journal
            ),
            "FULL_PLAN_JOURNAL_SOURCE",
        )
        choices = []  # Full future plan is revisable; it is not the old protected cache.
    else:
        choices = journal[-1]["commitments_after"] if journal else []
    commands = life.get("commitments", [])
    normalized = [
        dict(
            operation=c["operation_id"],
            product=c["product_id"],
            attempt=c["attempt"],
            mode=c["mode_id"],
            roles=c["roles"],
            start_h=c["issued_sim_h"],
        )
        for c in commands
    ]
    check(normalized == choices, "COMMITMENT_JOURNAL_SOURCE")
    cancelled = {p["product_id"] for p in raw["products"] if p["cancelled"]}
    remaining = [
        c["id"]
        for c in commands
        if c["operation_id"] not in raw["completed"] and c["product_id"] not in cancelled
    ]
    check(
        commit["obligations"]["commitments"] == life["obligations"]["commitments"] == remaining,
        "COMMITMENTS_REBUILT",
    )
    positions = {p["id"]: p["location"] for p in raw["positions"]}
    masses = {p["entity_id"]: p["installed_t"] for p in raw["masses"]} if raw["masses"] else {}
    lots = {p["id"]: p for p in raw["lots"]}
    received = {p["product_id"] for p in raw["products"] if p["received_h"] is not None}
    physical = []
    for x in (*history.current.lots, *history.current.entities):
        mass = masses.get(x.id, 0)
        if x.id in lots:
            row = lots[x.id]
            mass = row["available"] + sum(
                r["quantity"] for r in raw["reservations"] if r["lot_id"] == x.id
            )
        if (
            mass > 1e-9
            and positions[x.id]
            not in (
                "SUPPLIER",
                "UNPRODUCED",
                "UNFABRICATED",
                "UNASSEMBLED",
                "EXTERNAL",
                "INCORPORATED",
            )
            and x.product_id not in received
        ):
            physical.append(x.id)
    check(
        sorted(physical) == sorted(commit["obligations"]["physical_residuals"]), "PHYSICAL_REBUILT"
    )
    check(
        final["open_obligations"]
        == len(open_products)
        + len(physical)
        + len(raw["reservations"])
        + len(commit["obligations"]["commitments"]),
        "OBLIGATION_COUNT",
    )
    if final["phase"] == "COMPLETED":
        check(
            not pending
            and not open_products
            and not raw["running"]
            and not raw["owners"]
            and not raw["reservations"]
            and not physical,
            "COMPLETED_DRAIN",
        )
        check(final["open_obligations"] == 0 and not remaining, "COMPLETED_ZERO_OBLIGATIONS")
        check(spec["mode"] == "FIXED_PROTOCOL" or bool(closes), "COMPLETED_MODE")
    if final["phase"].startswith("STOP"):
        control = life.get("stop_control") or {}
        callback = control.get("source") == "WORKER_ORDERLY_STOP_CALLBACK"
        if callback:
            n = control["event_count_at_boundary"]
            from adaptive_hrc_scheduling.production_backend import ProductionBackend

            check(type(n) is int and 0 <= n <= len(events), "STOP_CALLBACK_INDEX")
            observed = (
                events[n - 1]["state"]
                if n
                else as_data(
                    ProductionBackend(history.initial, run_id=spec["run_id"], epoch=spec["epoch"]).s
                )
            )
            check(
                n <= len(events)
                and observed is not None
                and observed["revision"] == control["accepted_revision"]
                and observed["time_h"] == control["accepted_h"],
                "STOP_CALLBACK_BOUNDARY",
            )
        check(
            any(
                r["status"] == "APPLIED"
                and state["requests"][r["request_id"]]["kind"] == "STOP_REQUEST"
                for r in receipts
            )
            or callback,
            "STOP_EVIDENCE",
        )
    last_h = 0
    for i, row in enumerate(life["meter"]):
        check(abs(row["start_h"] - last_h) < 1e-9, "METER_CONTIGUOUS:" + str(i))
        dt = row["end_h"] - row["start_h"]
        check(0 <= dt <= spec["clock"]["idle_step_h"] + 1e-9, "METER_BOUND:" + str(i))
        if spec["mode"] != "FIXED_PROTOCOL":
            check(
                row["wall_s"] + 1e-6 >= dt / spec["clock"]["simulation_rate"],
                "METER_RATE:" + str(i),
            )
        last_h = row["end_h"]
    check(abs(last_h - raw["time_h"]) < 1e-9, "METER_FINAL")
    rows = {}
    prefix = []
    previous = "0" * 64
    plan_versions = []
    transport_state = {}
    with gzip.open(root / "decisions.jsonl.gz", "rt", encoding="utf-8") as stream:
        decision_plans = [json.loads(line)["plan"] for line in stream if line.strip()]
    for n, line in enumerate((root / "timeline.jsonl").read_text(encoding="utf-8").splitlines(), 1):
        packet = json.loads(line)
        check(
            packet["sequence"] == n and packet["previous_packet_sha256"] == previous,
            "PACKET_SEQUENCE:" + str(n),
        )
        previous = sha({k: v for k, v in packet.items() if k != "packet_sha256"})
        check(previous == packet["packet_sha256"], "PACKET_HASH:" + str(n))
        if packet.get("progress_delta"):
            from adaptive_hrc_scheduling.timeline_transport import unpack

            check(full_schedule, "FULL_PROGRESS_SCENARIO")
            transport_state = unpack(packet, transport_state)
        prefix += packet["events"]
        e = packet["envelope"]
        if packet["plan"] is not None and (
            not plan_versions or packet["plan"]["plan_version"] != len(plan_versions)
        ):
            check(packet["plan"]["plan_version"] == len(plan_versions) + 1, "PLAN_VERSION_SEQUENCE")
            plan_versions.append(packet["plan"])
        if packet["plan"] is not None:
            check(packet["plan"]["plan"] in decision_plans, "PLAN_DECISION_SOURCE")
        check(e["plan_version"] == len(plan_versions), "ENVELOPE_PLAN_VERSION")
        check(
            prefix == events[: len(prefix)]
            and len(prefix) == e["event_count"]
            and sha(prefix) == e["event_prefix_hash"],
            "DELIVERED_PREFIX:" + str(n),
        )
        check(
            (e["run_id"], e["epoch"], e["run_spec_sha256"])
            == (spec["run_id"], spec["epoch"], sha(spec)),
            "PROJECTION_IDENTITY:" + str(n),
        )
        check(
            sha(packet["catalog"]) == e["materialized_catalog_sha256"],
            "PROJECTION_CATALOG:" + str(n),
        )
        cfg = history.config_at(decode(m.ExecutionEvent, x) for x in prefix)
        version = sum(d["commit_event_id"] in {x["id"] for x in prefix} for d in state["deltas"])
        check(
            e["initial_config_sha256"] == spec["initial_config_sha256"]
            and e["catalog_version"] == version
            and e["catalog_hash"] == state["versions"][version]
            and any(
                all(
                    e[k] == o[k]
                    for k in (
                        "observation_id",
                        "state_revision",
                        "event_count",
                        "event_prefix_hash",
                        "catalog_version",
                        "catalog_hash",
                        "sampled_sim_h",
                        "received_sim_h",
                    )
                )
                for o in state["observations"]
            ),
            "ENVELOPE_OBSERVATION",
        )
        check(
            e["materialized_catalog_sha256"]
            == (
                state["deltas"][version - 1]["materialized_catalog_sha256"]
                if version
                else sha(state["initial_catalog"])
            ),
            "MATERIALIZED_VERSION_SOURCE",
        )
        orders = as_data(cfg.products)
        modern = packet["format"] == "P044-TIMELINE-2"
        check(
            packet["format"] in ("P044-TIMELINE-1", "P044-TIMELINE-2")
            and e["format"] == packet["format"],
            "PROJECTION_FORMAT",
        )
        if modern:
            priority = {p["order_id"]: p["priority"] for p in spec["initial_orders"]}
            for g in state["generations"]:
                if g["event_id"] in {x["id"] for x in prefix} and not g.get("workforce_kind"):
                    priority[g["payload"]["order_id"]] = g["payload"]["priority"]
            orders = [dict(p, priority=priority[p["order_id"]]) for p in orders]
            source = packet["source"]
            check(source["plans"] == plan_versions, "SOURCE_PLAN_VERSIONS")
            check(
                source["generations"]
                == [g for g in state["generations"] if g["event_id"] in {x["id"] for x in prefix}]
                and source["deltas"] == state["deltas"][:version],
                "PROJECTION_SOURCE_HISTORY",
            )
            check(
                source["intervals"]
                == [x for x in raw["intervals"] if x["end_h"] <= e["sampled_sim_h"]],
                "PROJECTION_SOURCE_INTERVALS",
            )
            check(
                all(
                    v == state["command_bindings"][k] for k, v in source["command_bindings"].items()
                ),
                "PROJECTION_SOURCE_COMMANDS",
            )
            check(
                source["observation"]["state"]
                == (
                    dict(prefix[-1]["state"], intervals=[])
                    if prefix
                    else as_data(
                        __import__(
                            "adaptive_hrc_scheduling.production_backend",
                            fromlist=["ProductionBackend"],
                        )
                        .ProductionBackend(
                            history.initial, run_id=spec["run_id"], epoch=spec["epoch"]
                        )
                        .s
                    )
                )
                and source["observation"]["id"] == e["observation_id"]
                and source["observation"]["sampled_h"] == e["sampled_sim_h"]
                and source["observation"]["received_h"] == e["received_sim_h"],
                "PROJECTION_SOURCE_OBSERVATION",
            )
            if n == 1:
                check(
                    packet["source_basis"]
                    == dict(spec=spec, configuration=read("configuration.json")),
                    "PROJECTION_SOURCE_BASIS",
                )
        check(
            packet["orders"] == orders
            and packet["people"] == as_data(cfg.people)
            and packet["devices"] == as_data(cfg.devices),
            "BUSINESS_ATTRIBUTES",
        )
        check(
            [p.id for p in cfg.products] == [p["id"] for p in packet["orders"]]
            and [p.id for p in cfg.people] == [p["id"] for p in packet["people"]],
            "NO_FUTURE_CATALOG:" + str(n),
        )
        byid = {x["id"]: x for x in prefix}
        for row in packet["upserts"]:
            if row["row_kind"] == "RESOURCE_FACT":
                start = byid[row["start_event_id"]]
                pair = {"resource_id": row["resource_id"], "command_id": row["command_id"]}
                check(
                    pair in start["state"]["owners"] and start["occurred_sim_h"] == row["start_h"],
                    "RESOURCE_START",
                )
                if row["end_status"] == "CLOSED":
                    end = byid[row["end_event_id"]]
                    check(
                        pair not in end["state"]["owners"]
                        and end["occurred_sim_h"] == row["end_h"],
                        "RESOURCE_END",
                    )
            if row["row_kind"] == "FACT_PREFIX":
                start = byid[row["start_event_id"]]
                check(
                    start["kind"] == "STARTED"
                    and start["command_id"] == row["command_id"]
                    and start["occurred_sim_h"] == row["start_h"],
                    "ACTUAL_START",
                )
                cmd = start["command"]
                check(
                    all(
                        row[k] == cmd[v]
                        for k, v in {
                            "product_id": "product_id",
                            "operation_id": "operation_id",
                            "activity_id": "activity_id",
                            "attempt": "attempt",
                            "mode": "mode_id",
                        }.items()
                    )
                    and row["order_id"]
                    == next(p.order_id for p in cfg.products if p.id == cmd["product_id"])
                    and row["start_event_sequence"] == start["sequence"],
                    "FACT_COMMAND_IDENTITY",
                )
                binding = state["command_bindings"][cmd["id"]]
                check(
                    all(
                        row[k] == binding[k]
                        for k in ("admitted_catalog_version", "admitted_catalog_hash")
                    ),
                    "FACT_ADMISSION",
                )
                completed = [
                    x for x in prefix if x["kind"] == "COMPLETED" and x["command_id"] == cmd["id"]
                ]
                check((row["end_status"] == "CLOSED") == bool(completed), "FACT_CLOSURE_REQUIRED")
                op = (
                    cmd["service"]["operation"]
                    if cmd["service"]
                    else next(
                        __import__("dataclasses").asdict(o)
                        for o in cfg.operations
                        if o.id == cmd["operation_id"]
                    )
                )
                check(
                    sha(op) == row["operation_sha256"]
                    and list(op["equipment"]) == row["equipment"]
                    and cmd["roles"] == row["roles"],
                    "COMMAND_RESOURCES",
                )
                check(row["schedule_state"] == "ACTUAL", "FACT_SCHEDULE")
                if row["end_status"] == "CLOSED":
                    end = byid[row["end_event_id"]]
                    check(
                        end["kind"] == "COMPLETED"
                        and end["command_id"] == cmd["id"]
                        and end["occurred_sim_h"] == row["end_h"]
                        and end["readback"]["evidence_id"] == row["readback_id"],
                        "ACTUAL_END",
                    )
            if row["row_kind"] == "PLAN":
                check(
                    row["schedule_state"] in ("COMMITTED", "TENTATIVE", "UNSCHEDULED"),
                    "PLAN_NOT_ACTUAL",
                )
                if row.get("proposal_state") == "ADOPTED":
                    check(
                        byid[row["adoption_event_id"]]["kind"] == "STARTED"
                        and byid[row["adoption_event_id"]]["command_id"] == row["command_id"],
                        "ADOPTION_PROOF",
                    )
            rows[row["row_id"]] = row
        for key in packet["removed"]:
            rows.pop(key)
        resources, owners, markers = {}, {}, {}
        for event in prefix:
            owned = {(x["resource_id"], x["command_id"]) for x in event["state"]["owners"]}
            for pair in owned - owners.keys():
                key = (event["id"], *pair)
                owners[pair] = key
                resources[key] = [event["occurred_sim_h"], None]
            for pair in owners.keys() - owned:
                resources[owners.pop(pair)][1] = event["occurred_sim_h"]
            if event["world"] or event["kind"] == "EXCEPTION":
                markers["marker:" + event["id"]] = [
                    event["id"],
                    event["occurred_sim_h"],
                    event["world"]["kind"] if event["world"] else event["kind"],
                    event["world"]["entity_id"] if event["world"] else event["command_id"],
                ]
        check(
            {
                (r["start_event_id"], r["resource_id"], r["command_id"]): [
                    r["start_h"],
                    r.get("end_h"),
                ]
                for r in rows.values()
                if r["row_kind"] == "RESOURCE_FACT"
            }
            == resources,
            "PACKET_RESOURCE_RECONSTRUCTION",
        )
        check(
            {
                k: [r["event_id"], r["sim_h"], r["kind"], r["target_id"]]
                for k, r in rows.items()
                if r["row_kind"] == "MARKER"
            }
            == markers,
            "PACKET_MARKERS",
        )
        check(
            sum(r["row_kind"] == "PERSON_INTERVAL" for r in rows.values())
            == sum(x["end_h"] <= e["sampled_sim_h"] for x in raw["intervals"]),
            "PACKET_PERSON_COVERAGE",
        )
        check(
            {r["command_id"] for r in rows.values() if r["row_kind"] == "FACT_PREFIX"}
            == {x["command_id"] for x in prefix if x["kind"] == "STARTED"},
            "PACKET_FACT_COVERAGE",
        )
        for row in rows.values():
            if row["row_kind"] == "FACT_PREFIX":
                check(
                    (row["end_status"] == "CLOSED")
                    == any(
                        x["kind"] == "COMPLETED" and x["command_id"] == row["command_id"]
                        for x in prefix
                    ),
                    "PACKET_FACT_CLOSURE",
                )
            if row["row_kind"] == "PERSON_INTERVAL":
                idx = int(row["row_id"].split(":")[1])
                interval = raw["intervals"][idx]
                stats = state["workforce_statistics"]["people"][interval["person_id"]]
                flags = next(
                    x
                    for x in stats["activity_intervals"]
                    if x["start_h"] == interval["start_h"] and x["end_h"] == interval["end_h"]
                )
                check(
                    all(row[k] == v for k, v in interval.items())
                    and row["end_h"] <= e["sampled_sim_h"]
                    and row["presence"] == flags["presence"]
                    and row["availability"] == flags["availability"]
                    and abs(
                        row["labour_cost"]
                        - (
                            (row["end_h"] - row["start_h"]) * stats["rate_per_h"]
                            if flags["presence"]
                            else 0
                        )
                    )
                    < 1e-9,
                    "PACKET_PERSON_COST",
                )
    latest = read("timeline-latest.json")
    check(
        latest["rows"] == list(rows.values()) and latest["packet_sha256"] == previous,
        "LATEST_REPLAY",
    )
    check(latest["envelope"] == e and latest["sequence"] == n, "LATEST_ENVELOPE")
    check(len(prefix) == len(events), "FINAL_PROJECTION_PREFIX")
    check(
        {r["command_id"] for r in rows.values() if r["row_kind"] == "FACT_PREFIX"}
        == {e["command_id"] for e in events if e["kind"] == "STARTED"},
        "ACTUAL_COVERAGE",
    )
    expected_resources = {}
    active = {}
    for event in events:
        owned = {(x["resource_id"], x["command_id"]) for x in event["state"]["owners"]}
        for pair in owned - active.keys():
            key = (event["id"], *pair)
            active[pair] = key
            expected_resources[key] = [event["occurred_sim_h"], None]
        for pair in active.keys() - owned:
            expected_resources[active.pop(pair)][1] = event["occurred_sim_h"]
    check(
        {
            (r["start_event_id"], r["resource_id"], r["command_id"]): [r["start_h"], r.get("end_h")]
            for r in rows.values()
            if r["row_kind"] == "RESOURCE_FACT"
        }
        == expected_resources,
        "RESOURCE_OCCUPANCY_REBUILT",
    )
    person_rows = [r for r in rows.values() if r["row_kind"] == "PERSON_INTERVAL"]
    check(len(person_rows) == len(raw["intervals"]), "PERSON_INTERVAL_COVERAGE")
    for index, interval in enumerate(raw["intervals"]):
        row = rows["person:" + str(index)]
        check(all(row[k] == v for k, v in interval.items()), "PERSON_INTERVAL_RAW:" + str(index))
        if row["row_kind"] == "PERSON_INTERVAL":
            stats = state["workforce_statistics"]["people"][interval["person_id"]]
            source = next(
                x
                for x in stats["activity_intervals"]
                if x["start_h"] == interval["start_h"] and x["end_h"] == interval["end_h"]
            )
            cost = (
                (interval["end_h"] - interval["start_h"]) * stats["rate_per_h"]
                if source["presence"]
                else 0
            )
            check(
                row["presence"] == source["presence"]
                and row["availability"] == source["availability"]
                and abs(row["labour_cost"] - cost) < 1e-9,
                "PERSON_COST:" + str(index),
            )
    return dict(
        status="PASS",
        identity="P044-INDEPENDENT-r2",
        checks=len(checks),
        base=base,
        events=len(events),
        projection_packets=n,
        projection_rows=len(rows),
        phase=final["phase"],
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(args.directory)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
