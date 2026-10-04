"""Separate S14 strict boundary. The C04 validator and schemas are unchanged."""

import hashlib
import json
from functools import lru_cache

from adaptive_hrc_scheduling.contracts.codec import ContractError, _pairs, as_data, decode, require
from adaptive_hrc_scheduling.domain import logistics as m
from adaptive_hrc_scheduling.logistics_geometry import close, standing_point

TOP_LEVEL = (
    m.Configuration,
    m.DispatchCommand,
    m.ExecutionEvent,
    m.ExecutionSnapshot,
    m.PlanningObservation,
    m.PlanningInput,
    m.Plan,
    m.HiddenScenario,
    m.OfflineEvaluation,
    m.RunManifest,
)


def _digest(record):
    canonical = as_data(decode(type(record), as_data(record)))
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


@lru_cache(maxsize=32)
def _configuration_digest(record):
    return _digest(record)


def digest(record):
    return _configuration_digest(record) if isinstance(record, m.Configuration) else _digest(record)


def index(items):
    out = {x.id: x for x in items}
    require(len(out) == len(items), "DUPLICATE_ID")
    return out


def qualified(config, ids):
    evidence = {x.id: x for x in config.evidence}
    return all(
        i in evidence
        and evidence[i].status == "PASS"
        and (
            evidence[i].basis == "INDUSTRIAL"
            or config.purpose == "SYNTHETIC_TEST_ONLY"
            and evidence[i].basis == "SYNTHETIC_TEST"
        )
        and evidence[i].reference
        for i in ids
    )


def mode_for(operation):
    if operation.route_id:
        return "MOVE"
    if operation.action == "REST":
        return "WAIT"
    return "H-team" if len(operation.roles) > 1 else "H" if operation.roles else "GATE"


def validate(record, *, config=None):
    require(type(record) in TOP_LEVEL, "UNSUPPORTED_S14_RECORD")
    decode(type(record), as_data(record))
    if isinstance(record, m.Configuration):
        c = record
        # The 37-node graph is preserved reference data, not an executable mapping.
        # Do not promote abbreviated witness operations to production semantics.
        require(c.scope == "WITNESS_FRAGMENT", "PRODUCTION_MAPPING_NOT_IMPLEMENTED")
        people, places, devices, lots, entities, operations, products, evidence = (
            index(x)
            for x in (
                c.people,
                c.places,
                c.devices,
                c.lots,
                c.entities,
                c.operations,
                c.products,
                c.evidence,
            )
        )
        routes = index(c.routes)
        core = index(c.core_activities)
        require(
            all(sum(a.product_id == p for a in core.values()) == 37 for p in products),
            "CORE_ACTIVITY_COVERAGE",
        )
        require(
            all(
                e.source in core
                and e.target in core
                and core[e.source].product_id == core[e.target].product_id
                for e in c.core_edges
            ),
            "CORE_EDGE_REFERENCE",
        )
        require(c.people and c.products and c.places and c.operations, "EMPTY_CONFIGURATION")
        require(
            len(set(lots) | set(entities) | set(people) | set(devices))
            == len(lots) + len(entities) + len(people) + len(devices),
            "PHYSICAL_ID_COLLISION",
        )
        require(
            set(x.person_id for x in c.person_positions) == set(people)
            and len(c.person_positions) == len(people),
            "PERSON_POSITION_COVERAGE",
        )
        require(all(x.location in places for x in c.person_positions), "PERSON_LOCATION")
        for p in c.people:
            require(
                p.initial_f <= c.cap and len(set(p.qualifications)) == len(p.qualifications),
                "PERSON_CAP_QUALIFICATIONS",
            )
            require(
                p.calendar.windows
                and all(
                    0 <= w.start_h < w.end_h <= p.calendar.period_h for w in p.calendar.windows
                ),
                "CALENDAR",
            )
            require(
                all(
                    a.end_h <= b.start_h for a, b in zip(p.calendar.windows, p.calendar.windows[1:])
                ),
                "CALENDAR_OVERLAP",
            )
        for p in c.places:
            require(len(p.position) == 3, "PLACE_DIMENSION")
        for d in c.devices:
            require(
                d.initial_location in places and d.qualification in evidence, "DEVICE_REFERENCE"
            )
        require(not ({"WELD1", "HST1"} & set(devices)), "LEGACY_DEVICE_IN_TARGET")
        for r in c.routes:
            require(
                r.source in places and r.target in places and r.source != r.target, "ROUTE_PLACES"
            )
            require(r.device_id is None or r.device_id in devices, "ROUTE_DEVICE")
            require(r.segments and len(set(r.segments)) == len(r.segments), "ROUTE_SEGMENTS")
            require(len(r.points) >= 2 and len(r.max_size_m) == 3, "ROUTE_GEOMETRY")
            require(r.qualification in evidence, "ROUTE_QUALIFICATION")
        for lot in c.lots:
            require(
                lot.product_id in products
                and lot.initial_location in (*places, "SUPPLIER", "UNPRODUCED"),
                "LOT_REFERENCE",
            )
            require(not lot.released or lot.arrived and lot.identified, "UNRELEASED_LOT")
            require(
                len(lot.size_m) == 3
                and set(lot.parent_ids) <= set(lots)
                and lot.id not in lot.parent_ids,
                "LOT_LINEAGE",
            )
            require(
                lot.arrived == (lot.initial_location not in ("SUPPLIER", "UNPRODUCED")),
                "LOT_ARRIVAL_LOCATION",
            )
        for e in c.entities:
            require(
                e.product_id in products
                and e.initial_location in (*places, "UNFABRICATED", "UNASSEMBLED", "EXTERNAL"),
                "ENTITY_REFERENCE",
            )
            require(len(e.size_m) == 3, "ENTITY_SIZE")
        for o in c.operations:
            require(o.product_id in products and o.location in places, "OPERATION_REFERENCE")
            require((o.action == "REST") == (o.phase == "REST"), "REST_PHASE_MISMATCH")
            if o.action == "REST":
                require(
                    o.base_h >= c.min_rest_h
                    and not (o.equipment or o.material_inputs or o.material_outputs or o.route_id),
                    "ILLEGAL_REST",
                )
            require(
                len(set(o.component_inputs)) == len(o.component_inputs)
                and all(
                    i in entities and entities[i].product_id == o.product_id
                    for i in o.component_inputs
                ),
                "COMPONENT_INPUTS",
            )
            if o.component_inputs:
                require(
                    o.action == "WORK"
                    and o.entity_id in entities
                    and entities[o.entity_id].kind == "PRODUCT"
                    and o.entity_id not in o.component_inputs
                    and o.target == o.location,
                    "ASSEMBLY_FIELDS",
                )
            require(
                len(set(o.component_outputs)) == len(o.component_outputs)
                and all(
                    i in entities
                    and entities[i].product_id == o.product_id
                    and entities[i].kind == "COMPONENT"
                    for i in o.component_outputs
                ),
                "COMPONENT_OUTPUTS",
            )
            if o.component_outputs:
                require(
                    o.action in ("WORK", "CONVERT")
                    and o.material_inputs
                    and not o.component_inputs,
                    "COMPONENT_PRODUCTION_RECIPE",
                )
            require(o.target is None or o.target in (*places, "EXTERNAL"), "OPERATION_TARGET")
            require(
                o.entity_id is None or o.entity_id in (*lots, *entities, *people, *devices),
                "OPERATION_ENTITY",
            )
            if o.entity_id in lots or o.entity_id in entities:
                require(
                    (lots.get(o.entity_id) or entities[o.entity_id]).product_id == o.product_id,
                    "FOREIGN_ENTITY",
                )
            if o.action == "RECEIVE_EXTERNAL":
                require(
                    o.entity_id == o.product_id
                    and o.entity_id in entities
                    and entities[o.entity_id].kind == "PRODUCT"
                    and o.location == "DISPATCH"
                    and o.target == "EXTERNAL",
                    "EXTERNAL_PRODUCT_IDENTITY",
                )
            require(
                set(o.equipment) <= set(devices) and len(set(o.equipment)) == len(o.equipment),
                "OPERATION_EQUIPMENT",
            )
            require(len({r.id for r in o.roles}) == len(o.roles), "ROLE_DUPLICATE")
            require(
                {r.person_id for r in o.role_locations} == {r.id for r in o.roles}
                and len(o.role_locations) == len(o.roles)
                and all(r.location in places for r in o.role_locations),
                "ROLE_LOCATION_COVERAGE",
            )
            require(
                set(o.prerequisites) <= set(operations) and o.id not in o.prerequisites,
                "PREREQUISITE_REFERENCE",
            )
            require(
                set(o.qualification_ids) <= set(evidence) and o.qualification_ids,
                "OPERATION_QUALIFICATION",
            )
            require(o.route_id is None or o.route_id in routes, "OPERATION_ROUTE")
            if o.action in ("TRANSFER", "WALK", "EMPTY_RETURN", "DEPLOY_TOOL", "RETRIEVE_TOOL"):
                require(
                    o.route_id is not None and o.target is not None and o.entity_id is not None,
                    "MOTION_FIELDS",
                )
                route = routes[o.route_id]
                if o.action in ("EMPTY_RETURN", "DEPLOY_TOOL", "RETRIEVE_TOOL"):
                    require(
                        o.entity_id in devices and route.device_id == o.entity_id,
                        "SELF_CARRIER_IDENTITY",
                    )
                require(
                    (route.source, route.target) == (o.location, o.target), "MOTION_ROUTE_MISMATCH"
                )
                require(
                    route.device_id is None or route.device_id in o.equipment,
                    "MOTION_DEVICE_MISMATCH",
                )
                if o.entity_id in devices:
                    require(devices[o.entity_id].kind != "FIXED", "FIXED_DEVICE_MOTION")
                endpoints = [
                    (route.points[0].x, route.points[0].y, route.points[0].z),
                    (route.points[-1].x, route.points[-1].y, route.points[-1].z),
                ]
                if o.action == "WALK":
                    expected = [standing_point(c, o.entity_id, x) for x in (o.location, o.target)]
                elif o.action == "EMPTY_RETURN" and o.entity_id == "CR1":
                    expected = [(*places[x].position[:2], 8) for x in (o.location, o.target)]
                else:
                    expected = [places[x].position for x in (o.location, o.target)]
                require(
                    all(close(a, b) for a, b in zip(endpoints, expected)), "ROUTE_ENDPOINT_MISMATCH"
                )
            for amount in (*o.material_inputs, *o.material_outputs):
                require(
                    amount.lot_id in lots and lots[amount.lot_id].product_id == o.product_id,
                    "FOREIGN_MATERIAL",
                )
            for amounts in (o.material_inputs, o.material_outputs):
                require(len({a.lot_id for a in amounts}) == len(amounts), "DUPLICATE_AMOUNT")
            if o.action == "CONVERT":
                require(o.material_inputs and o.material_outputs, "EMPTY_RECIPE")
                all_lots = [lots[a.lot_id] for a in (*o.material_inputs, *o.material_outputs)]
                require(
                    len({(x.material, x.unit) for x in all_lots}) == 1, "UNDEFINED_UNIT_CONVERSION"
                )
                require(
                    abs(
                        sum(a.quantity for a in o.material_inputs)
                        - sum(a.quantity for a in o.material_outputs)
                        - o.scrap_quantity
                    )
                    < 1e-9,
                    "RECIPE_CONSERVATION",
                )
                require(
                    not (
                        set(a.lot_id for a in o.material_inputs)
                        & set(a.lot_id for a in o.material_outputs)
                    ),
                    "RECIPE_REUSES_INPUT",
                )
                require(
                    all(
                        set(x.parent_ids) == set(a.lot_id for a in o.material_inputs)
                        for x in [lots[a.lot_id] for a in o.material_outputs]
                    ),
                    "RECIPE_LINEAGE",
                )
            require(o.hold_device is None or o.hold_device in o.equipment, "HOLD_DEVICE")
            require(o.release_device is None or o.release_device in o.equipment, "RELEASE_DEVICE")
        pending = set(operations)
        while pending:
            ready = {i for i in pending if not (set(operations[i].prerequisites) & pending)}
            require(ready, "OPERATION_CYCLE")
            pending -= ready
        require(set(c.initial_ready_products) <= set(products), "INITIAL_READY_REFERENCE")
        if c.initial_ready_products:
            require(
                c.scope == "WITNESS_FRAGMENT"
                and c.purpose == "SYNTHETIC_TEST_ONLY"
                and c.initial_ready_evidence
                and qualified(c, c.initial_ready_evidence),
                "UNPROVEN_INITIAL_READY",
            )
        for e in c.evidence:
            require(
                e.status != "PASS" or e.basis != "UNRESOLVED" and e.reference, "FALSE_EVIDENCE_PASS"
            )
            require(
                e.basis != "SYNTHETIC_TEST" or c.purpose == "SYNTHETIC_TEST_ONLY",
                "SYNTHETIC_PROVENANCE",
            )
        for a in c.core_activities:
            require(a.product_id in products, "CORE_PRODUCT")
            require(
                all(not mode.enabled for mode in a.modes if mode.kind == "HR-seq"), "HR_DISABLED"
            )
        return record
    require(config is not None and record.config_id == config.id, "CONFIG_REFERENCE")
    if hasattr(record, "config_sha256"):
        require(record.config_sha256 == digest(config), "CONFIG_DIGEST")
    if isinstance(record, m.DispatchCommand):
        ops = {o.id: o for o in config.operations}
        require(record.operation_id in ops, "UNKNOWN_OPERATION")
        o = ops[record.operation_id]
        require(record.mode_id == mode_for(o), "COMMAND_MODE")
        if o.action == "WALK":
            require(
                len(record.roles) == 1 and record.roles[0].person_id == o.entity_id,
                "WALK_PERSON_IDENTITY",
            )
        require(
            (record.product_id, record.activity_id) == (o.product_id, o.activity_id),
            "COMMAND_IDENTITY",
        )
        require(
            (record.attempt, record.unit_index) == (o.attempt_index, o.unit_index),
            "UNSUPPORTED_ATTEMPT_OR_UNIT",
        )
        require(
            len({x.role_id for x in record.roles}) == len(record.roles), "DUPLICATE_ROLE_BINDING"
        )
        require(len({x.person_id for x in record.roles}) == len(record.roles), "PERSON_DOUBLE_ROLE")
        require({x.role_id for x in record.roles} == {x.id for x in o.roles}, "ROLE_COVERAGE")
        require(
            {x.person_id for x in record.roles} <= {x.id for x in config.people}, "UNKNOWN_PERSON"
        )
    if isinstance(record, m.ExecutionEvent):
        require(record.received_sim_h >= record.occurred_sim_h, "EVENT_ARRIVAL_TIME")
        if record.command:
            validate(record.command, config=config)
            require(record.command_sha256 == digest(record.command), "PAYLOAD_DIGEST")
            require(
                (
                    record.run_id,
                    record.epoch,
                    record.command_id,
                    record.product_id,
                    record.activity_id,
                    record.attempt,
                )
                == (
                    record.command.run_id,
                    record.command.epoch,
                    record.command.id,
                    record.command.product_id,
                    record.command.activity_id,
                    record.command.attempt,
                ),
                "EVENT_CORRELATION",
            )
        else:
            require(record.kind in ("WORLD", "CLOCK"), "MISSING_COMMAND")
    if isinstance(record, m.PlanningObservation):
        require(record.sampled_h == record.state.time_h <= record.received_h, "OBSERVATION_TIME")
    if isinstance(record, m.PlanningInput):
        validate(record.observation, config=config)
        released = {p.product_id for p in record.observation.state.products if p.released}
        require(
            all(o.product_id in released and o in config.operations for o in record.operations),
            "UNOBSERVED_OPERATION",
        )
    if isinstance(record, m.Plan):
        for c in record.commands:
            validate(c, config=config)
    if isinstance(record, m.ExecutionSnapshot):
        for e in record.events:
            validate(e, config=config)
            require((e.run_id, e.epoch) == (record.run_id, record.epoch), "MIXED_EPOCH")
    return record


def dumps(record, *, config=None):
    validate(record, config=config)
    return (
        json.dumps(as_data(record), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    )


def loads(kind, text, *, config=None):
    try:
        value = json.loads(text, object_pairs_hook=_pairs)
    except (ValueError, UnicodeError) as exc:
        raise ContractError(str(exc)) from exc
    return validate(decode(kind, value), config=config)
