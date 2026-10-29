"""Versioned priority/deadline edits for the fixed-hour full-schedule scenario."""

from copy import deepcopy
from dataclasses import replace

from .contracts.codec import as_data, require
from .contracts.production import digest as config_digest
from .contracts.production import validate
from .contracts.session import digest, validate_record
from .domain import production as m
from .full_schedule import is_fixed


def configuration(config, payload, now):
    require(is_fixed(config), "FULL_SCENARIO_REQUIRED")
    ids = [p.id for p in config.products if p.order_id == payload["order_id"]]
    require(bool(ids), "UNKNOWN_ORDER")
    require(payload["due_sim_h"] > now, "DUE_PASSED")
    require(payload["priority"] in ("NORMAL", "URGENT"), "PRIORITY_INVALID")
    return validate(
        replace(
            config,
            products=tuple(
                replace(p, due_h=payload["due_sim_h"]) if p.id in ids else p
                for p in config.products
            ),
        )
    ), ids


def check(session, request):
    target = session.catalog["objects"].get(request["target_id"])
    require(
        target is not None and target["kind"] == "order" and target["available"], "ORDER_NOT_OPEN"
    )
    require(request["target_id"] == request["payload"]["order_id"], "TARGET_PAYLOAD_MISMATCH")
    ids = session.order_products[request["target_id"]]
    require(
        any(
            p.product_id in ids and not p.cancelled and p.received_h is None
            for p in session.world.s.products
        ),
        "ORDER_NOT_OPEN",
    )
    return configuration(session.world.config, request["payload"], session.world.s.time_h)


def apply(session, request, admission):
    s, w = session, session.world
    config, ids = check(s, request)
    before, revision = s.version, w.s.revision
    row = dict(
        order_update=True,
        request_id=request["request_id"],
        request_digest=request["request_digest"],
        payload=deepcopy(request["payload"]),
        sim_h=w.s.time_h,
        product_ids=ids,
        before_config_sha256=w.config_hash,
        config_sha256=config_digest(config),
        event_id=f"EV-{len(w.events) + 1}",
        catalog_version=before + 1,
        before_event_count=len(w.events),
        before_prefix_sha256=s.event_prefix_hash(),
        protected_state_sha256=digest(as_data(replace(w.s, intervals=()))),
    )
    s.history.append(row)
    w.config, w.config_hash = config, config_digest(config)
    if hasattr(s.backend, "world"):
        s.backend.ledger.catalog, s.backend.ledger.config = s.history, config
    event = s.backend.apply_world(
        m.WorldEvent(
            "UPDATE-" + request["request_id"],
            w.run_id,
            w.epoch,
            w.s.time_h,
            "CATALOG_REGISTER",
            request["target_id"],
            ids[0],
            0,
            "PASS",
            "P051-ORDER-METADATA",
        )
    )
    require(event.id == row["event_id"], "ORDER_UPDATE_EVENT")
    obj = s.catalog["objects"][request["target_id"]]
    obj.update(
        revision=obj["revision"] + 1,
        due_sim_h=request["payload"]["due_sim_h"],
        priority=request["payload"]["priority"],
    )
    payload = dict(
        delta_id=f"DELTA-{before + 1}",
        request_id=request["request_id"],
        request_digest=request["request_digest"],
        kind="ORDER_UPDATE",
        accept_sequence=admission["sequence"],
        actual_sim_h=w.s.time_h,
        read_set_hash=admission["read_set_hash"],
        state_revision_before=revision,
        state_revision_after=w.s.revision,
        object_ids=[request["target_id"]],
        generation_sha256=digest(row),
        commit_event_id=event.id,
    )
    checksum = digest(dict(previous_hash=s.versions[-1], version=before + 1, delta=payload))
    delta = dict(
        payload,
        old_version=before,
        new_version=before + 1,
        old_hash=s.versions[-1],
        new_hash=checksum,
        materialized_catalog_sha256=digest(s.catalog),
    )
    validate_record("CatalogDelta", delta)
    s.deltas.append(delta)
    s.versions.append(checksum)
    s.policy.config = config
    s.policy.catalog_changed(ids, w.operations, [event.id], tuple(r.command for r in w.s.running))
    s.business_results.append(
        dict(
            request_id=request["request_id"],
            status="ORDER_UPDATED",
            product_ids=ids,
            event_id=event.id,
            catalog_version=s.version,
            sim_h=w.s.time_h,
        )
    )
    s.refresh_capacity()
    s._receipt(
        request,
        "APPLIED",
        "ORDER_UPDATED",
        sequence=admission["sequence"],
        event=event,
        before=before,
    )
