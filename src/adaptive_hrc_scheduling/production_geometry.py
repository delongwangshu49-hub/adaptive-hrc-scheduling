"""Finite-aisle S15 geometry and explicitly bounded package packing."""

from dataclasses import replace

from adaptive_hrc_scheduling.contracts.codec import require
from adaptive_hrc_scheduling.domain import production as m

FORK_OPERATOR_DY = -2.25


def output_shapes(config, op):
    """Bottom-centered occupied volumes created by this transformation."""
    loads = {x.id: x for x in (*config.lots, *config.entities)}
    places = {p.id: p.position for p in config.places}
    outputs = [(i, op.location) for i in op.component_outputs]
    outputs += [(p.lot_id, p.place_id) for p in op.output_places]
    if op.component_inputs:
        outputs.append((op.entity_id, op.target or op.location))
    return tuple((ident, places[location], loads[ident].size_m) for ident, location in outputs)


def transport_sweeps(config, op, rt):
    """Bottom-centered load, carrier-part and operator paths in shared geometry."""
    points = tuple((p.x, p.y, p.z) for p in rt.points)
    loads = {x.id: x for x in (*config.lots, *config.entities)}
    size = loads[op.entity_id].size_m if op.entity_id in loads else None
    paths = []

    def part(offset, dimensions, lifts=False):
        paths.append(
            (
                tuple(
                    (x + offset[0], y + offset[1], (z if lifts else 0) + offset[2])
                    for x, y, z in points
                ),
                dimensions,
            )
        )

    if size:
        part((0, 0, 0), size, True)
    if rt.device_id == "FORK-01":
        part((0, -1.8, 0.05), (1.5, 2.6, 0.18))
        part((0, -2.7, 0.2), (1.3, 0.1, 1.6))
        for dx in (-0.65, 0.65):
            part((dx, -0.75, 0), (0.1, 0.12, 2.5))
        spread = 0.2 if size and size[0] < 1.5 else 0.65
        for dx in (-spread, spread):
            part(
                (dx, -1.45 if op.action == "EMPTY_RETURN" else -0.25, -0.12),
                (0.12, 1.3, 0.12),
                True,
            )
        part((0, FORK_OPERATOR_DY, 0.2), (0.6, 1.2, 1.9))
    elif rt.device_id in ("CART-01", "TEST1"):
        cart = rt.device_id == "CART-01"
        shift = -1.1 if cart else 0
        for offset, dimensions in (
            ((0, 0, 0.05), (0.8, 0.6, 0.18)),
            ((0, -0.85 if cart else 0.75, 1.075), (0.6, 0.05, 0.05)),
            ((0, -0.85 if cart else 0.75, 0.15), (0.05, 0.05, 1)),
            ((0, 0, 0.69), (0.8, 0.6, 0.12)),
            *[
                ((dx, dy, 0.025), (0.24, 0.24, 0.25))
                for dx in (-0.32, 0.32)
                for dy in (-0.24, 0.24)
            ],
        ):
            part((offset[0], shift + offset[1], offset[2]), dimensions, not cart)
        if cart:
            part(
                (0, shift + (-0.15 if op.action == "EMPTY_RETURN" else 0.65), -0.1),
                (0.65, 1.1, 0.1),
                True,
            )
        else:
            part((0, 0, 0.835), (0.5, 0.4, 0.25), True)
            part((0, -0.21, 0.89), (0.3, 0.02, 0.14), True)
        part((0, -2.45 if cart else 1.25, 0), (0.6, 1.2, 1.9))
    elif rt.device_id == "CR1":
        if size:
            part((0, 0, 0), (size[0], size[1], size[2] + 0.6), True)
        else:
            part((0, 0, -0.6), (6, 3, 0.8), True)
    return tuple(paths)


def standing_point(config, person, location):
    places = {p.id: p for p in config.places}
    point = places[location].position
    if location.startswith("CONTROL-"):
        return tuple(point)
    if location == "F1" and person in ("P1", "E1"):
        # At the process station these people receive/install materials;
        # they are not operating a vehicle positioned at the module center.
        # Keep separate full-size places beside the existing north work rows.
        return (point[0] + 1.5, point[1] + (2.4 if person == "P1" else 3.8), 0)
    if person in ("P1", "E1"):
        return (
            point[0],
            point[1] + (FORK_OPERATOR_DY if person == "P1" else -2.45),
            0.2 if person == "P1" else 0,
        )
    if location.startswith("TEST-"):
        return (point[0], point[1] + 1.25, 0)
    root = places[location].parent or location
    point = places[root].position
    ordinal = next(i for i, p in enumerate(config.people) if p.id == person)
    workers = [p.id for p in config.people if p.id not in ("P1", "E1", "Lop", "Lrig", "Lsig")]
    if root == "F1" and person in workers:
        station = workers.index(person)
        # The two finite rows fit between F1 and OUT1, clear of the west
        # material face and the southern carrier aisle.
        return (point[0] - 3 + 0.9 * (station % 5), point[1] + 2.4 + 1.4 * (station // 5), 0)
    return (
        min(58, point[0] + 4 + 0.9 * (ordinal % 4)),
        point[1] + (1.5 if root == "J3" else -5) + 1.4 * (ordinal // 4),
        0,
    )


def pack(boxes, bounds, vertical_clearance=0, depth_first=False):
    """Bounded shelves with the incoming carrier's declared access gap."""
    occupied = []
    result = {}
    gaps = (
        vertical_clearance
        if isinstance(vertical_clearance, dict)
        else {i: vertical_clearance for i, _ in boxes}
    )
    for ident, size in sorted(boxes, key=lambda x: (-x[1][0] * x[1][1], -x[1][2], x[0])):
        gap = gaps[ident]
        xs = {0.0, *(p[0] + s[0] for p, s, _ in occupied)}
        ys = {0.0, *(p[1] + s[1] for p, s, _ in occupied)}
        zs = {0.0, *(p[2] + s[2] + gap for p, s, _ in occupied)}
        possible = []
        for x in xs:
            for y in ys:
                for z in zs:
                    point = (x, y, z)
                    if any(point[i] + size[i] > bounds[i] + 1e-9 for i in range(3)):
                        continue
                    conflict = False
                    for q, other, other_gap in occupied:
                        horizontal = all(
                            point[i] < q[i] + other[i] - 1e-9 and q[i] < point[i] + size[i] - 1e-9
                            for i in (0, 1)
                        )
                        separated = (
                            z >= q[2] + other[2] + gap - 1e-9
                            or q[2] >= z + size[2] + other_gap - 1e-9
                        )
                        if horizontal and not separated:
                            conflict = True
                            break
                    if not conflict:
                        possible.append(point)
        require(possible, "APPROVED_GROUP_PACKING_INFEASIBLE:" + ident)
        p = min(possible, key=lambda p: (p[1], p[2], p[0]) if depth_first else (p[2], p[1], p[0]))
        occupied.append((p, size, gap))
        result[ident] = (
            p[0] + size[0] / 2 - bounds[0] / 2,
            bounds[1] / 2 - p[1] - size[1] / 2
            if depth_first
            else p[1] + size[1] / 2 - bounds[1] / 2,
            p[2],
        )
    return result


def ground_points(config, source, target, device, *, empty=False):
    places = {p.id: p for p in config.places}
    a, b = (places[i].position for i in (source, target))
    if a == b:
        return (a, b)
    roots = [places[places[i].parent or i] for i in (source, target)]
    ay, by = (p.position[1] - (1.6 if device == "CART-01" else 2.2) for p in roots)
    if device == "FORK-01":
        if roots[0].id in ("MEP-RECEIVE", "MEP-STORE", "KIT", "F1-KIT"):
            ay = roots[0].position[1] - 1.4
        if roots[1].id in ("MEP-RECEIVE", "MEP-STORE", "KIT", "F1-KIT"):
            by = roots[1].position[1] - 1.4
    if source == "FORK-PARK":
        ay = a[1]
    if target == "FORK-PARK":
        by = b[1]
    if device == "CART-01":
        if roots[0].id == "F1":
            ay = roots[0].position[1] - 2.3
        if roots[1].id == "F1":
            by = roots[1].position[1] - 2.3
    if roots[0].id == "PRE-IN" and a[0] > 15.8:
        ay = 7.77
    if roots[1].id == "PRE-IN" and b[0] > 15.8:
        by = 7.77
    if roots[0].id == "PRE-OUT" and a[0] < 19:
        ay = 12.3
    if roots[1].id == "PRE-OUT" and b[0] < 19:
        by = 12.3
    h = 0 if device == "TEST1" else max(a[2], b[2], 2.8 if device == "FORK-01" else 0.9)
    # Exit and enter the shelf horizontally; never lift through another tier.
    # Use the western bypass around receiving/storage supports.
    left = 10.5 if a[0] < 21 else 58.2 if a[0] > 53 else 24.4
    right = 10.5 if b[0] < 21 else 58.2 if b[0] > 53 else 24.4
    if roots[0].id == "PRE-OUT":
        left = 24.4
    if roots[1].id == "PRE-OUT":
        right = 24.4
    cross_y = 19 if all(p.id in ("RECEIVE", "STEEL", "PRE-IN", "PRE-OUT") for p in roots) else 21.8
    middle = (
        ((left, ay, h), (left, by, h))
        if left == right
        else ((left, ay, h), (left, cross_y, h), (right, cross_y, h), (right, by, h))
    )
    adock = 11.9 if roots[0].id == "PRE-OUT" and a[0] < 19 else ay
    bdock = 11.9 if roots[1].id == "PRE-OUT" and b[0] < 19 else by
    if source.startswith("PRE-IN.") and source.endswith(".ST-C.04.NET"):
        adock = a[1]
    if target.startswith("PRE-IN.") and target.endswith(".ST-C.04.NET"):
        bdock = b[1]
    points = (
        a,
        (a[0], adock, a[2]),
        (a[0], adock, h),
        (a[0], ay, h),
        *middle,
        (b[0], by, h),
        (b[0], bdock, h),
        (b[0], bdock, b[2]),
        b,
    )
    # Broad floor packs cannot pass through the permanently deployed bars of
    # the front wet-material columns. Enter/leave their rear row laterally;
    # the fork remains on the ground and the load only lifts outside the rack.
    if device == "FORK-01":

        def side_access(location, root, point, dock, outgoing):
            if not any(
                code in location
                for code in (
                    ".FL.",
                    ".EN-L.",
                    ".FI-C.",
                    ".EN-X.",
                    ".FI-D.",
                    ".FI-W.",
                    ".FI-K.",
                    ".FI-S.",
                )
            ) or root.id not in (
                "MEP-RECEIVE",
                "MEP-STORE",
                "KIT",
                "F1-KIT",
                "F1",
            ):
                return None
            rack_x = root.position[0] - (4.5 if root.id == "F1" else 0)
            side_x = rack_x + (-3 if root.id == "F1" else 3)
            # A 0.125 m lift clears the retained 0.8 m trestles with
            # 0.12 m tines. The declared 0.17 m tier gap leaves room below
            # the next 0.04 m support bar; every segment is still swept.
            # Empty retracted tines first lower in the clear central tine
            # lanes. Crossing laterally at a loaded shelf height would strike
            # the front column's higher support bars.
            lifted = 0.3 if empty else point[2] + (0.125 if ".FL." in location else 0.1205)
            spur = (
                point,
                (*point[:2], lifted),
                (side_x, point[1], lifted),
                (side_x, point[1], h),
                (side_x, dock, h),
            )
            return spur if outgoing else tuple(reversed(spur))

        entrance = side_access(source, roots[0], a, ay, True)
        exit_ = side_access(target, roots[1], b, by, False)
        if entrance or exit_:
            first = entrance or (a, (a[0], adock, a[2]), (a[0], adock, h), (a[0], ay, h))
            last = exit_ or ((b[0], by, h), (b[0], bdock, h), (b[0], bdock, b[2]), b)
            points = (*first, *middle, *last)
    return tuple(p for i, p in enumerate(points) if i == 0 or p != points[i - 1])


def route(config, ident, source, target, device, *, person=None, empty=False):
    """Construct a declared aisle route; execution must still check swept clearance."""
    places = {p.id: p for p in config.places}
    a, b = places[source].position, places[target].position
    if person:
        a, b = (standing_point(config, person, x) for x in (source, target))
        # Fixed pedestrian spine, then station spur; blocked spurs remain failures.
        points = (a, (a[0], 42, 0), (b[0], 42, 0), b)
        segments, speed, vertical, size = ("WALK-SPINE", "GROUND-SPINE"), 1, 1, (0.6, 1.2, 1.9)
    elif device == "CR1":
        a, b = (*a[:2], 8), (*b[:2], 8)
        points = (a, (b[0], a[1], 8), b)
        segments, speed, vertical, size = ("AISLE-CR1",), 0.5, 0.2, (6, 3, 3.2)
    else:
        # Ground carriers travel on the same declared outer spine in both engines.
        points = ground_points(config, source, target, device, empty=empty)
        segments, speed, vertical, size = ("GROUND-SPINE",), 0.5, 0.5, (6, 3, 3.2)
    return m.Route(
        ident,
        source,
        target,
        device,
        segments,
        tuple(m.Point(*p) for p in points),
        speed,
        vertical,
        "ML-ROUTE",
        size,
    )


def validate_service(config, service):
    op, rt = service.operation, service.route
    if op.action in ("TRANSFER", "RETURN"):
        from adaptive_hrc_scheduling.production_cancel import validate

        validate(config, service)
        return
    if op.action == "SUPPORT_CHANGE":
        from adaptive_hrc_scheduling.production_supports import change_operation

        layout = next((x for x in config.support_layouts if x.id == op.support_layout_id), None)
        require(layout is not None and rt is None, "SUPPORT_SERVICE_LAYOUT")
        require(
            op == change_operation(config, layout, op.product_id, op.id), "SUPPORT_SERVICE_FIELDS"
        )
        require(any(p.id == op.product_id for p in config.products), "SUPPORT_SERVICE_PRODUCT")
        return
    require(op.support_layout_id is None, "UNEXPECTED_SUPPORT_LAYOUT")
    require(op.action in ("WALK", "EMPTY_RETURN", "REST"), "ILLEGAL_SERVICE_ACTION")
    require(
        not (
            op.material_inputs
            or op.material_outputs
            or op.component_inputs
            or op.component_outputs
            or op.component_input_places
            or op.prerequisites
            or op.hold_device
            or op.release_device
            or op.wait_gate
            or op.quality_gates
            or op.input_places
            or op.output_places
            or op.mass_remove_t
            or op.wait_after
            or op.wait_h
            or op.scrap_quantity
            or op.production_mode
        ),
        "SERVICE_SIDE_EFFECT",
    )
    require(op.product_id in {p.id for p in config.products}, "SERVICE_PRODUCT")
    require(op.attempt_index == op.unit_index == 0 and op.kappa == 0, "SERVICE_CONTEXT")
    people, devices = {p.id: p for p in config.people}, {d.id: d for d in config.devices}
    places = {p.id for p in config.places}
    require(op.location in places and (op.target is None or op.target in places), "SERVICE_PLACE")
    require(op.qualification_ids == ("ML-METHOD",), "SERVICE_QUALIFICATION")
    if op.action in ("WALK", "REST"):
        require(
            op.entity_id in people and len(op.roles) == 1 and not op.equipment, "SERVICE_PERSON"
        )
        require(
            op.roles[0].id == op.entity_id
            and op.roles[0].qualification in people[op.entity_id].qualifications,
            "SERVICE_ROLE",
        )
        require(
            op.role_locations == (m.PersonPosition(op.entity_id, op.location),),
            "SERVICE_ROLE_LOCATION",
        )
    else:
        require(
            op.entity_id in devices
            and devices[op.entity_id].kind != "FIXED"
            and op.equipment == (op.entity_id,),
            "SERVICE_DEVICE",
        )
        expected = (
            ("Lop", "Lrig", "Lsig")
            if op.entity_id == "CR1"
            else (
                "P1" if op.entity_id == "FORK-01" else "E1" if op.entity_id == "CART-01" else "QA1",
            )
        )
        require(tuple(r.id for r in op.roles) == expected, "SERVICE_DEVICE_ROLES")
        qualifications = (
            ("CRANE", "RIG", "SIGNAL")
            if op.entity_id == "CR1"
            else (
                "FORK"
                if op.entity_id == "FORK-01"
                else "CART"
                if op.entity_id == "CART-01"
                else "TOOL",
            )
        )
        require(
            tuple(r.qualification for r in op.roles) == qualifications,
            "SERVICE_DEVICE_QUALIFICATIONS",
        )
        require(
            op.role_locations
            == tuple(
                m.PersonPosition(i, "CONTROL-" + i if op.entity_id == "CR1" else op.location)
                for i in expected
            ),
            "SERVICE_DEVICE_ROLE_LOCATION",
        )
    if op.action == "REST":
        require(
            rt is None
            and op.route_id is None
            and op.target is None
            and op.base_h == config.min_rest_h
            and op.phase == "REST",
            "SERVICE_REST",
        )
    else:
        require(
            rt is not None and op.target is not None and op.base_h == 0, "SERVICE_ROUTE_REQUIRED"
        )
        require(op.route_id == rt.id, "SERVICE_ROUTE_ID")
        expected = route(
            config,
            rt.id,
            op.location,
            op.target,
            op.entity_id if op.action == "EMPTY_RETURN" else None,
            person=op.entity_id if op.action == "WALK" else None,
            empty=op.action == "EMPTY_RETURN",
        )
        if op.action == "WALK":
            require(
                replace(rt, points=expected.points) == expected and len(rt.points) >= 2,
                "UNDECLARED_WALK_PARAMETERS",
            )
            require(
                rt.points[0] == expected.points[0] and rt.points[-1] == expected.points[-1],
                "WALK_ENDPOINTS",
            )
            require(
                all(0 <= p.x <= 60 and 0 <= p.y <= 44 and 0 <= p.z <= 0.2 for p in rt.points),
                "WALK_SITE_LIMIT",
            )
        else:
            require(rt == expected, "UNDECLARED_SERVICE_ROUTE")
    return service
