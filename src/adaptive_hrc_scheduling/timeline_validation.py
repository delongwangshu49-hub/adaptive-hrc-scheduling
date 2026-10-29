"""Semantic read-side validation against frozen C0 and delivered execution evidence.

The packet transport must originate from the selected run. Hashes provide integrity,
not sender authentication. Historical v1 streams need independent saved-run review.
"""

from dataclasses import replace

from .contracts.codec import as_data, decode, require
from .contracts.production import digest as configuration_digest
from .contracts.session import digest
from .domain import production as m
from .dynamic_workforce import WorkforceHistory, status
from .production_backend import ProductionBackend
from .timeline_memory import share_record
from .workforce_metrics import project


def validate(packet, events, rows, basis, *, prefix_hashes=None, cache=None):
    """Revalidate all semantic obligations; cache only exact immutable decodes.

    The optional cache belongs to one consumer and is committed only after the
    complete validation succeeds. The default path remains an uncached oracle.
    No audit, row comparison, catalog check or packet hash is omitted.
    """
    memo = cache if cache is not None else {}
    basis_key = digest(basis)
    spec = basis["spec"]
    initial = memo.get("initial") if memo.get("basis_key") == basis_key else None
    if initial is None:
        initial = decode(m.Configuration, basis["configuration"])
        initial_snapshot = ProductionBackend(
            initial, run_id=spec["run_id"], epoch=spec["epoch"]
        ).snapshot()
    else:
        initial_snapshot = memo["initial_snapshot"]
    e, source = packet["envelope"], packet["source"]
    require(digest(spec) == e["run_spec_sha256"], "TIMELINE_FROZEN_SPEC")
    require(
        configuration_digest(initial)
        == spec["initial_config_sha256"]
        == e["initial_config_sha256"],
        "TIMELINE_C0",
    )
    event_ids = {x["id"] for x in events}
    require(len(event_ids) == len(events), "TIMELINE_EVENT_IDS")
    require(
        all(x["event_id"] in event_ids for x in source["generations"]), "TIMELINE_FUTURE_GENERATION"
    )
    generations_key = digest(source["generations"])
    history = (
        memo.get("history")
        if memo.get("basis_key") == basis_key and memo.get("generations_key") == generations_key
        else None
    )
    if history is None:
        history = WorkforceHistory(initial, source["generations"])
    cfg = history.current
    old_events = memo.get("event_rows", ()) if memo.get("basis_key") == basis_key else ()
    event_offset = (
        len(old_events)
        if len(events) >= len(old_events) and events[: len(old_events)] == list(old_events)
        else 0
    )
    prior_decoded = memo["decoded_events"] if event_offset else ()
    appended = []
    previous_state = prior_decoded[-1].state if prior_decoded else None
    for raw_event in events[event_offset:]:
        event = decode(m.ExecutionEvent, raw_event)
        if previous_state is not None:
            event = replace(event, state=share_record(event.state, previous_state))
        appended.append(event)
        previous_state = event.state
    decoded = prior_decoded + tuple(appended)
    initial_state = initial_snapshot.state
    raw = events[-1]["state"] if events else as_data(initial_state)
    obs = source["observation"]
    require(obs["state"] == dict(raw, intervals=[]), "TIMELINE_OBSERVED_STATE")
    require(
        obs["id"] == e["observation_id"] == "OBS-" + str(raw["revision"])
        and e["state_revision"] == raw["revision"]
        and obs["event_ids"] == [x["id"] for x in events]
        and obs["sampled_h"] == e["sampled_sim_h"] == raw["time_h"]
        and obs["received_h"] == e["received_sim_h"]
        and (obs["run_id"], obs["epoch"]) == (spec["run_id"], spec["epoch"]),
        "TIMELINE_OBSERVATION",
    )
    catalog = dict(
        configuration_sha256=spec["initial_config_sha256"],
        objects={
            x.id: dict(revision=0, kind=kind, available=True)
            for kind, objects in (
                ("product", initial.products),
                ("person", initial.people),
                ("device", initial.devices),
            )
            for x in objects
        },
    )
    for p in initial.products:
        obj = catalog["objects"].setdefault(
            p.order_id, dict(revision=0, kind="order", available=True, product_ids=[])
        )
        obj["product_ids"].append(p.id)
    versions = [digest(catalog)]
    byid = {x["id"]: x for x in events}
    payload_keys = (
        "delta_id",
        "request_id",
        "request_digest",
        "kind",
        "accept_sequence",
        "actual_sim_h",
        "read_set_hash",
        "state_revision_before",
        "state_revision_after",
        "object_ids",
        "generation_sha256",
        "commit_event_id",
    )
    for i, delta in enumerate(source["deltas"], 1):
        event = byid[delta["commit_event_id"]]
        require(
            (delta["old_version"], delta["new_version"], delta["old_hash"])
            == (i - 1, i, versions[-1]),
            "TIMELINE_DELTA_VERSION",
        )
        require(
            event["state"]["revision"] <= delta["state_revision_after"] <= raw["revision"]
            and delta["actual_sim_h"] == event["occurred_sim_h"],
            "TIMELINE_DELTA_EVENT",
        )
        value = digest(
            dict(previous_hash=versions[-1], version=i, delta={k: delta[k] for k in payload_keys})
        )
        require(value == delta["new_hash"], "TIMELINE_DELTA_HASH")
        kind = delta["kind"]
        generation = next((g for g in source["generations"] if g["event_id"] == event["id"]), None)
        if kind == "ORDER_CREATE":
            require(generation is not None, "TIMELINE_ORDER_SOURCE")
            for pid in generation["product_ids"]:
                catalog["objects"][pid] = dict(revision=0, kind="product", available=True)
            catalog["objects"][generation["payload"]["order_id"]] = dict(
                revision=0, kind="order", available=True, product_ids=generation["product_ids"]
            )
        elif kind == "ORDER_UPDATE":
            require(
                generation is not None and generation.get("order_update"),
                "TIMELINE_ORDER_UPDATE_SOURCE",
            )
            obj = catalog["objects"][generation["payload"]["order_id"]]
            obj.update(
                revision=obj["revision"] + 1,
                due_sim_h=generation["payload"]["due_sim_h"],
                priority=generation["payload"]["priority"],
            )
        elif kind.startswith("PERSON_"):
            require(generation is not None, "TIMELINE_PERSON_SOURCE")
            target = generation["target_id"]
            obj = catalog["objects"].setdefault(target, dict(revision=-1, kind="person"))
            obj["revision"] += 1
            presence = status(decode(m.State, event["state"]), target)
            obj.update(available=presence == "PRESENT", presence_status=presence)
            if kind == "PERSON_ARRIVE":
                obj.update(
                    parameter_template_id=generation["payload"]["parameter_template_id"],
                    qualification_version=1,
                )
        else:
            for key in delta["object_ids"]:
                obj = catalog["objects"][key]
                obj.update(revision=obj["revision"] + 1, available=kind == "DEVICE_REPAIR")
        require(
            digest(catalog) == delta["materialized_catalog_sha256"], "TIMELINE_DELTA_MATERIALIZED"
        )
        versions.append(value)
    require(
        e["catalog_version"] == len(versions) - 1
        and e["catalog_hash"] == versions[-1]
        and packet["catalog"] == catalog,
        "TIMELINE_CATALOG_REBUILT",
    )
    priorities = {x["order_id"]: x["priority"] for x in spec["initial_orders"]}
    expected_orders = [
        dict(
            as_data(p), priority=history.priorities.get(p.id, priorities.get(p.order_id, "NORMAL"))
        )
        for p in cfg.products
    ]
    require(
        packet["orders"] == expected_orders
        and packet["people"] == as_data(cfg.people)
        and packet["devices"] == as_data(cfg.devices),
        "TIMELINE_BUSINESS_CATALOG",
    )
    require(packet["failed_resources"] == raw["failed_resources"], "TIMELINE_FAILED_RESOURCES")
    plans = source["plans"]
    require(
        e["plan_version"] == len(plans)
        and (packet["plan"] is None or plans and packet["plan"] == plans[-1]),
        "TIMELINE_PLAN_VERSION",
    )
    planned = {}
    for i, plan in enumerate(plans, 1):
        require(
            plan["plan_version"] == i
            and plan["event_count"] <= len(events)
            and plan["event_prefix_hash"]
            == (
                prefix_hashes[plan["event_count"]]
                if prefix_hashes is not None
                else digest(events[: plan["event_count"]])
            ),
            "TIMELINE_PLAN_PREFIX",
        )
        for cmd in plan["plan"]["commands"]:
            key = f"plan:{i}:{cmd['id']}"
            choice = dict(
                operation=cmd["operation_id"],
                product=cmd["product_id"],
                attempt=cmd["attempt"],
                mode=cmd["mode_id"],
                roles=cmd["roles"],
                start_h=cmd["issued_sim_h"],
            )
            row = dict(
                row_id=key,
                row_kind="PLAN",
                plan_version=i,
                proposal_state="CANDIDATE",
                schedule_state="COMMITTED"
                if choice in plan["journal"].get("commitments_after", [])
                else "TENTATIVE",
                operation_id=cmd["operation_id"],
                product_id=cmd["product_id"],
                command_id=cmd["id"],
                start_h=cmd["issued_sim_h"],
                end_status="UNKNOWN",
                mode=cmd["mode_id"],
                roles=cmd["roles"],
            )
            start = next(
                (x for x in events if x["kind"] == "STARTED" and x["command_id"] == cmd["id"]), None
            )
            if start:
                row.update(proposal_state="ADOPTED", adoption_event_id=start["id"])
            elif i < len(plans):
                row["proposal_state"] = "SUPERSEDED"
            planned[key] = row
    # Reconstruct actual rows, including closure even if a row claims to be OPEN.
    expected, active = {}, {}
    for event in events:
        cmd = event["command"]
        if event["kind"] == "STARTED" and cmd:
            op = (
                cmd["service"]["operation"]
                if cmd["service"]
                else next(as_data(o) for o in cfg.operations if o.id == cmd["operation_id"])
            )
            binding = source["command_bindings"][cmd["id"]]
            version = binding["admitted_catalog_version"]
            require(
                0 <= version < len(versions)
                and binding["admitted_catalog_hash"] == versions[version],
                "TIMELINE_COMMAND_VERSION",
            )
            key = "actual:" + cmd["id"]
            expected[key] = dict(
                row_id=key,
                row_kind="FACT_PREFIX",
                schedule_state="ACTUAL",
                command_id=cmd["id"],
                product_id=cmd["product_id"],
                order_id=next(p.order_id for p in cfg.products if p.id == cmd["product_id"]),
                operation_id=cmd["operation_id"],
                activity_id=cmd["activity_id"],
                attempt=cmd["attempt"],
                mode=cmd["mode_id"],
                roles=cmd["roles"],
                equipment=op["equipment"],
                operation_sha256=digest(op),
                admitted_catalog_version=version,
                admitted_catalog_hash=versions[version],
                start_h=event["occurred_sim_h"],
                start_event_id=event["id"],
                start_event_sequence=event["sequence"],
                end_status="OPEN",
            )
        if cmd and event["kind"] in ("COMPLETED", "EXCEPTION"):
            row = expected["actual:" + cmd["id"]]
            row["execution_status"] = event["kind"]
            if event["kind"] == "COMPLETED":
                row.update(
                    end_status="CLOSED",
                    end_h=event["occurred_sim_h"],
                    end_event_id=event["id"],
                    readback_id=event["readback"]["evidence_id"],
                )
        owned = {(o["resource_id"], o["command_id"]) for o in event["state"]["owners"]}
        for pair in owned - active.keys():
            key = f"resource:{event['sequence']}:{pair[0]}:{pair[1]}"
            active[pair] = key
            expected[key] = dict(
                row_id=key,
                row_kind="RESOURCE_FACT",
                schedule_state="ACTUAL",
                resource_id=pair[0],
                command_id=pair[1],
                start_h=event["occurred_sim_h"],
                start_event_id=event["id"],
                end_status="OPEN",
            )
        for pair in active.keys() - owned:
            expected[active.pop(pair)].update(
                end_status="CLOSED", end_h=event["occurred_sim_h"], end_event_id=event["id"]
            )
        if event["world"] or event["kind"] == "EXCEPTION":
            key = "marker:" + event["id"]
            expected[key] = dict(
                row_id=key,
                row_kind="MARKER",
                schedule_state="ACTUAL",
                event_id=event["id"],
                sim_h=event["occurred_sim_h"],
                kind=event["world"]["kind"] if event["world"] else event["kind"],
                target_id=event["world"]["entity_id"] if event["world"] else event["command_id"],
            )
    old_intervals = memo.get("interval_rows", ()) if memo.get("basis_key") == basis_key else ()
    interval_offset = (
        len(old_intervals)
        if len(source["intervals"]) >= len(old_intervals)
        and source["intervals"][: len(old_intervals)] == list(old_intervals)
        else 0
    )
    decoded_intervals = (memo["decoded_intervals"] if interval_offset else ()) + tuple(
        decode(m.HumanInterval, x) for x in source["intervals"][interval_offset:]
    )
    state = replace(decode(m.State, dict(raw, intervals=[])), intervals=decoded_intervals)
    snapshot = replace(
        initial_snapshot,
        state=state,
        events=decoded,
        config_sha256=configuration_digest(cfg),
    )
    from .control.audit_cache import ExecutionCheckpoint
    from .production_checker import check_run

    checkpoint = (
        memo["checkpoint"].fork() if memo.get("checkpoint") is not None else ExecutionCheckpoint()
    )
    audit = check_run(
        cfg,
        snapshot,
        catalog=history,
        checkpoint=checkpoint if cache is not None else None,
        catalog_checkpoint=cache is not None,
    )
    require(audit.status == "PASS", "TIMELINE_EXECUTION_SOURCE:" + str(audit.findings))
    metrics = project(spec, history, snapshot)
    require(packet["workforce_statistics"] == metrics, "TIMELINE_METRICS")
    for index, interval in enumerate(source["intervals"]):
        stats = metrics["people"][interval["person_id"]]
        flags = next(
            x
            for x in stats["activity_intervals"]
            if x["start_h"] == interval["start_h"] and x["end_h"] == interval["end_h"]
        )
        key = "person:" + str(index)
        expected[key] = dict(
            row_id=key,
            row_kind="PERSON_INTERVAL",
            schedule_state="ACTUAL",
            **interval,
            presence=flags["presence"],
            availability=flags["availability"],
            labour_cost=(interval["end_h"] - interval["start_h"]) * stats["rate_per_h"]
            if flags["presence"]
            else 0,
        )
    # Only the top-level observation bound is removed; nested values stay read-only.
    actual = {k: dict(v) for k, v in rows.items() if v["row_kind"] != "PLAN"}
    for key, row in actual.items():
        observed = row.pop("observed_until_h", None)
        if row.get("end_status") == "OPEN":
            require(observed == e["sampled_sim_h"], "TIMELINE_OPEN_BOUND")
    require(actual == expected, "TIMELINE_ROWS_FROM_SOURCE")
    scheduled = {
        r["operation_id"]
        for r in [*expected.values(), *planned.values()]
        if r["row_kind"] in ("FACT_PREFIX", "PLAN") and r.get("proposal_state") != "SUPERSEDED"
    }
    for op in cfg.operations:
        if op.id not in scheduled and op.id not in raw["completed"]:
            key = "unscheduled:" + op.id
            planned[key] = dict(
                row_id=key,
                row_kind="PLAN",
                operation_id=op.id,
                product_id=op.product_id,
                schedule_state="UNSCHEDULED",
                end_status="UNKNOWN",
            )
    require(
        {k: v for k, v in rows.items() if v["row_kind"] == "PLAN"} == planned, "TIMELINE_PLAN_ROWS"
    )
    if cache is not None:
        cache.update(
            basis_key=basis_key,
            initial=initial,
            initial_snapshot=initial_snapshot,
            generations_key=generations_key,
            history=history,
            event_rows=tuple(events),
            decoded_events=decoded,
            interval_rows=tuple(source["intervals"]),
            decoded_intervals=decoded_intervals,
            checkpoint=checkpoint,
        )
