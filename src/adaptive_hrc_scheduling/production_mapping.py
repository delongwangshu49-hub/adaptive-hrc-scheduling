"""Approved S15 static mapping checks; contains no runtime state transitions."""

import hashlib
import json
from importlib.resources import files

from adaptive_hrc_scheduling import production_supports as supports
from adaptive_hrc_scheduling.contracts.codec import require

RECIPE_DIGEST = "cc7753f0d43ce0a45a5e521d0b283db337922de86ea81734a2605842ea9909b2"


def recipe():
    raw = files("adaptive_hrc_scheduling").joinpath("production_recipe.json").read_bytes()
    require(hashlib.sha256(raw).hexdigest() == RECIPE_DIGEST, "APPROVED_RECIPE_DRIFT")
    return json.loads(raw)


def validate_mapping(config):
    require(config.scope == "PRODUCTION", "S15_REQUIRES_PRODUCTION_MAPPING")
    require(config.recipe_sha256 == RECIPE_DIGEST, "UNAPPROVED_RECIPE")
    require(not config.initial_ready_products, "PRODUCTION_CANNOT_START_READY")
    validate_recipe(config)
    ops = {o.id: o for o in config.operations}
    activities = {a.id: a for a in config.core_activities}
    groups = {g.id: g for g in config.groups}
    places = {p.id: p for p in config.places}
    require(len(groups) == len(config.groups), "DUPLICATE_GROUP")
    for lot in config.lots:
        require(lot.group_id in groups, "LOT_GROUP_MISSING")
        require(groups[lot.group_id].product_id == lot.product_id, "FOREIGN_GROUP")
    for place in config.places:
        require(place.parent is None or place.parent in places, "SLOT_PARENT")
        require(place.parent is None or places[place.parent].parent is None, "SLOT_PARENT_DEPTH")
    lots = {lot.id: lot for lot in config.lots}
    material_ports = {
        (port.lot_id, port.place_id)
        for op in config.operations
        for port in (*op.input_places, *op.output_places)
    }
    material_ports.update(
        (op.entity_id, loc)
        for op in config.operations
        if op.entity_id in lots
        for loc in (op.location, op.target)
        if loc in places
    )
    for ident, loc in material_ports:
        place = places[loc]
        if place.parent not in supports.ROOTS:
            continue
        lot = lots[ident]
        center = supports.center(config, place.parent)
        bounds = groups[lot.group_id].size_m
        require(
            all(
                abs(place.position[i] - center[i]) + lot.size_m[i] / 2 <= bounds[i] / 2 + 1e-9
                for i in (0, 1)
            )
            and place.position[2] >= center[2] - 1e-9
            and place.position[2] + lot.size_m[2] <= center[2] + bounds[2] + 1e-9,
            "MATERIAL_GROUP_ENVELOPE:" + ident + ":" + loc,
        )
    for op in config.operations:
        for amounts, ports in (
            (op.material_inputs, op.input_places),
            (op.material_outputs, op.output_places),
        ):
            require(len({p.lot_id for p in ports}) == len(ports), "DUPLICATE_MATERIAL_PORT")
            require(
                {p.lot_id for p in ports} == {a.lot_id for a in amounts}, "MATERIAL_PORT_COVERAGE"
            )
            require(all(p.place_id in places for p in ports), "MATERIAL_PORT_LOCATION")
        if op.wait_after:
            require(op.wait_after in ops and op.wait_h > 0, "WAIT_ORIGIN")
    expected = set()
    modes = {}
    for a in activities.values():
        active = [mode for mode in a.modes if mode.enabled]
        require(len(active) == 1 and active[0].kind != "HR-seq", "S15_LEGAL_MODE")
        mode = active[0]
        modes[a.id] = mode
        expected.update((a.id, mode.id, u.id) for u in mode.units)
        if not mode.units:
            expected.add((a.id, mode.id, "GATE"))
    seen = set()
    bound_operations = set()
    by_activity = {}
    for b in config.bindings:
        key = (b.activity_id, b.mode_id, b.unit_id)
        require(key in expected and key not in seen, "CORE_BINDING_IDENTITY")
        seen.add(key)
        require(b.operation_ids and set(b.operation_ids) <= ops.keys(), "CORE_BINDING_OPERATION")
        require(not (set(b.operation_ids) & bound_operations), "CORE_UNIT_REUSED")
        bound_operations.update(b.operation_ids)
        a, mode = activities[b.activity_id], modes[b.activity_id]
        mapped = [ops[i] for i in b.operation_ids]
        require(
            all(
                o.activity_id == a.id
                and o.product_id == a.product_id
                and o.attempt_index == 0
                and o.production_mode == mode.kind
                for o in mapped
            ),
            "CORE_OPERATION_CONTEXT",
        )
        by_activity.setdefault(a.id, []).extend(b.operation_ids)
        if b.unit_id == "GATE":
            require(
                sum(o.base_h for o in mapped) == 0 and not any(o.roles for o in mapped),
                "GATE_HAS_LABOUR",
            )
        else:
            u = next(u for u in mode.units if u.id == b.unit_id)
            require(
                all(o.roles == u.roles and o.equipment == u.equipment for o in mapped),
                "CORE_ROLES_OR_EQUIPMENT",
            )
            require(all(o.kappa == u.kappa for o in mapped), "CORE_KAPPA")
            if mode.kind == "MOVE":
                require(
                    all(o.action == "TRANSFER" and o.route_id and o.base_h == 0 for o in mapped),
                    "MOVE_TIME_MAPPING",
                )
            else:
                require(
                    len(mapped) == 1 and mapped[0].base_h == u.base_h, "CORE_PROCESS_TIME_MAPPING"
                )
                require(
                    mapped[0].phase == ("SETUP" if u.phase == "SETUP" else "WORK"),
                    "CORE_PHASE_MAPPING",
                )
    require(seen == expected, "INCOMPLETE_CORE_MAPPING")
    ancestors = {}
    pending = set(ops)
    while pending:
        ready = [i for i in sorted(pending) if set(ops[i].prerequisites) <= ancestors.keys()]
        require(ready, "PRODUCTION_OPERATION_CYCLE")
        for i in ready:
            ancestors[i] = set(ops[i].prerequisites)
            for p in ops[i].prerequisites:
                ancestors[i].update(ancestors[p])
            pending.remove(i)
    for a in activities.values():
        previous = set()
        mapped = [ops[i] for i in by_activity[a.id]]
        if a.wait_h:
            require(
                len(mapped) == 1
                and mapped[0].wait_h == a.wait_h
                and mapped[0].wait_after in ancestors[mapped[0].id],
                "CORE_WAIT_DURATION_MAPPING",
            )
        if a.code == "TEST-SET":
            require(mapped[-1].hold_device == "TEST1", "TEST_CONTINUOUS_HOLD")
        if a.code == "Q-POND":
            require(
                mapped[-1].release_device == "TEST1" and mapped[-1].mass_remove_t == 0.1,
                "TEST_DRAIN_AND_RELEASE",
            )
        for u in (*modes[a.id].units,):
            b = next(b for b in config.bindings if b.activity_id == a.id and b.unit_id == u.id)
            require(all(previous <= ancestors[i] for i in b.operation_ids), "CORE_UNIT_ORDER")
            previous.update(b.operation_ids)
    for e in config.core_edges:
        before, after = set(by_activity[e.source]), by_activity[e.target]
        require(all(before <= ancestors[i] for i in after), "CORE_PRECEDENCE_MAPPING")
        source = activities[e.source]
        if e.relation == "quality":
            require(
                all(source.quality_evidence in ops[i].quality_gates for i in after),
                "CORE_QUALITY_MAPPING",
            )
        if e.relation == "wait_release":
            require(
                all(ops[i].wait_gate == source.release_evidence for i in after), "CORE_WAIT_MAPPING"
            )
    return config


def validate_recipe(config):
    """Bind every primary package to the owner's approved numerical recipe."""
    approved = recipe()
    lots = {lot.id: lot for lot in config.lots}
    expected_primary = set()
    for product in config.products:
        require(product.variant in approved["finished_mass_t"], "UNAPPROVED_VARIANT")
        require(
            product.mass_t == approved["finished_mass_t"][product.variant], "FINISHED_MASS_DRIFT"
        )
        rows = list(approved["rows"])
        if product.variant == "SR-W2":
            rows += [
                dict(
                    r,
                    gross_mass_each_t=r["mass_t"],
                    net_mass_each_t=r["mass_t"],
                    scrap_each_t=0,
                    transport_size_m=r["size_m"],
                )
                for r in approved["extensions"]
            ]
        rows += [
            dict(
                id="WATER",
                bom_id="AUX-WATER",
                packages=2,
                gross_mass_each_t=0.05,
                net_mass_each_t=0.05,
                scrap_each_t=0,
                transport_size_m=[1.2, 0.8, 0.6],
                carrier="CART-01",
            )
        ]
        for row in rows:
            for n in range(1, row["packages"] + 1):
                ident = f"{product.id}.{row['id']}.{n:02}"
                expected_primary.add(ident)
                require(ident in lots, "MISSING_APPROVED_PACKAGE:" + ident)
                lot = lots[ident]
                require(
                    lot.product_id == product.id
                    and lot.bom_id == row["bom_id"]
                    and lot.quantity == lot.mass_t == row["gross_mass_each_t"]
                    and lot.size_m == tuple(row["transport_size_m"])
                    and lot.unit == "t"
                    and not lot.parent_ids
                    and not lot.arrived,
                    "APPROVED_PACKAGE_DRIFT:" + ident,
                )
                moves = [
                    o for o in config.operations if o.entity_id == ident and o.action == "TRANSFER"
                ]
                routes = {r.id: r for r in config.routes}
                require(
                    moves and all(routes[o.route_id].device_id == row["carrier"] for o in moves),
                    "PACKAGE_CARRIER_DRIFT:" + ident,
                )
                consumption = [
                    (o, a.quantity)
                    for o in config.operations
                    if o.action in ("WORK", "CONVERT")
                    for a in o.material_inputs
                    if a.lot_id == ident
                ]
                require(
                    abs(sum(q for o, q in consumption) - lot.quantity) <= 1e-9,
                    "PACKAGE_CONSUMPTION_COVERAGE:" + ident,
                )
                expected_code = (
                    "CUT"
                    if row["scrap_each_t"]
                    else "TEST-SET"
                    if row["id"] == "WATER"
                    else row["activity"]
                )
                core_ids = {
                    a.id
                    for a in config.core_activities
                    if a.product_id == product.id and a.code == expected_code
                }
                require(
                    all(o.activity_id in core_ids for o, q in consumption),
                    "WRONG_CONSUMING_ACTIVITY:" + ident,
                )
                if row["scrap_each_t"]:
                    require(ident + ".NET" in lots, "MISSING_CONVERTED_PACKAGE")
                    net = lots[ident + ".NET"]
                    require(
                        net.quantity == net.mass_t == row["net_mass_each_t"]
                        and net.parent_ids == (ident,)
                        and net.product_id == product.id
                        and net.size_m == lot.size_m
                        and net.initial_location == "UNPRODUCED"
                        and not (net.arrived or net.identified or net.released),
                        "STEEL_CONVERSION_DRIFT",
                    )
                expected_roots = (
                    ("RECEIVE", "STEEL", "PRE-IN")
                    if row["scrap_each_t"]
                    else (
                        "MEP-RECEIVE",
                        "MEP-STORE",
                        "KIT",
                        "F1-KIT",
                        "J3" if row.get("activity") == "COAT" else "F1",
                    )
                )
                moves = [
                    o for o in config.operations if o.action == "TRANSFER" and o.entity_id == ident
                ]
                places = {p.id: p for p in config.places}
                require(
                    len(moves) == len(expected_roots) - 1
                    and all(
                        (
                            places[o.location].parent or o.location,
                            places[o.target].parent or o.target,
                        )
                        == (a, b)
                        for o, a, b in zip(moves, expected_roots, expected_roots[1:])
                    ),
                    "PACKAGE_ROUTE_CHAIN:" + ident,
                )
        expected_entities = {product.id: (product.mass_t, (6, 3, 3.2), "UNASSEMBLED")}
        expected_entities.update(
            {
                product.id + "." + name: (mass, size, "UNFABRICATED")
                for name, mass, size in [
                    ("BOTTOM", 1.2, (6, 3, 0.2)),
                    ("TOP", 1.2, (6, 3, 0.2)),
                    ("COLUMNS", 0.76, (1.6, 1.6, 2.8)),
                ]
            }
        )
        actual_entities = {e.id: e for e in config.entities if e.product_id == product.id}
        require(set(actual_entities) == set(expected_entities), "PRODUCT_ENTITY_COVERAGE")
        for ident, expected in expected_entities.items():
            entity = actual_entities[ident]
            require(
                (entity.mass_t, entity.size_m, entity.initial_location) == expected,
                "APPROVED_COMPONENT_DRIFT:" + ident,
            )
        for suffix, row in (("BOTTOM", "ST-B"), ("TOP", "ST-T"), ("COLUMNS", "ST-C")):
            component = product.id + "." + suffix
            forms = [o for o in config.operations if component in o.component_outputs]
            expected_nets = {
                i: lot.quantity
                for i, lot in lots.items()
                if i.startswith(product.id + "." + row + ".") and i.endswith(".NET")
            }
            require(
                len(forms) == 1
                and forms[0].action == "CONVERT"
                and forms[0].component_outputs == (component,)
                and {a.lot_id: a.quantity for a in forms[0].material_inputs} == expected_nets,
                "COMPONENT_KITTING_CONVERSION",
            )
        groups = [g for g in config.groups if g.product_id == product.id]
        for g in groups:
            steel = g.activity_code == "STEEL"
            require(
                (g.max_packages, g.max_mass_t, g.size_m)
                == ((28, 3.318, (6, 2.4, 1.6)) if steel else (11, 1.2, (2.4, 2.4, 2))),
                "APPROVED_GROUP_CAPACITY_DRIFT",
            )
    from adaptive_hrc_scheduling.production_rework import validate_rework

    expected_primary.update(validate_rework(config))
    require(
        {lot.id for lot in config.lots if not lot.parent_ids} == expected_primary,
        "UNAPPROVED_PRIMARY_PACKAGE",
    )
