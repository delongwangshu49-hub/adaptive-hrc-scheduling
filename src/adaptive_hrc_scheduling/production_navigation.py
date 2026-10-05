"""Finite pedestrian graph on the declared S15 site; no execution mutations."""

import heapq
import math

from adaptive_hrc_scheduling import production_supports as supports
from adaptive_hrc_scheduling.contracts.codec import require
from adaptive_hrc_scheduling.production_geometry import standing_point, transport_sweeps


def ingress_groups(config, state):
    """Visible groups still occupying each existing inbound corridor."""
    lots = {lot.id: lot for lot in config.lots}
    places = {p.id: p for p in config.places}
    reserved = {}
    for item in state.reservations:
        reserved[item.lot_id] = reserved.get(item.lot_id, 0) + item.quantity
    groups = {True: set(), False: set()}
    for stock in state.lots:
        if not stock.arrived or stock.available + reserved.get(stock.id, 0) <= 1e-9:
            continue
        lot = lots[stock.id]
        steel = lot.material == "STEEL"
        corridor = (
            ("RECEIVE", "STEEL", "PRE-IN")
            if steel
            else ("MEP-RECEIVE", "MEP-STORE", "KIT", "F1-KIT", "J3", "F1")
        )
        place = places.get(stock.location)
        root = (place.parent or place.id) if place else stock.location
        if root in corridor or stock.location == "IN_TRANSIT":
            groups[steel].add(lot.group_id)
    return groups


def boxes(config, state, excluded=()):
    places = {p.id: p for p in config.places}
    positions = {p.id: p.location for p in state.positions}
    transit = {}
    operations = {o.id: o for o in config.operations}
    routes = {r.id: r for r in config.routes}
    for run in state.running:
        op = (
            run.command.service.operation
            if run.command.service
            else operations[run.command.operation_id]
        )
        if not op.route_id:
            continue
        rt = run.command.service.route if run.command.service else routes[op.route_id]
        proof = next(
            (
                p
                for p in reversed(state.motions)
                if p.command_id in (run.command.id, run.command.resume_of)
            ),
            None,
        )
        point = proof.position_m if proof else (rt.points[0].x, rt.points[0].y, rt.points[0].z)
        transit[op.entity_id] = point
        if rt.device_id:
            transit[rt.device_id] = point
            for role in op.roles:
                if role.qualification in ("FORK", "CART", "TOOL"):
                    dy, z = {"FORK": (-2.25, 0.2), "CART": (-2.45, 0), "TOOL": (1.25, 0)}[
                        role.qualification
                    ]
                    transit[role.id] = (point[0], point[1] + dy, z)
    result = []
    seen_geometry = set()
    variable_ports = {p.place_id for layout in config.support_layouts for p in layout.contacts}

    def box(owner, center, size):
        if owner not in excluded:
            signature = (tuple(center), tuple(size))
            if owner in places and signature in seen_geometry:
                return
            if owner in places:
                seen_geometry.add(signature)
            result.append(
                (
                    owner,
                    tuple(center[i] - size[i] / 2 for i in range(3)),
                    tuple(center[i] + size[i] / 2 for i in range(3)),
                )
            )

    fixed = {
        "CUT1": ((15, 12, 0.9), (1.6, 1.4, 1.8)),
        "R1": ((35, 12, 1.6), (2.8, 3, 3.2)),
        "WELD-J2": ((30, 16, 0.8), (1.5, 1, 1.6)),
        "WELD-J3": ((50, 16, 0.8), (1.5, 1, 1.6)),
    }
    for owner, (point, size) in fixed.items():
        box(owner, point, size)
    for owner, x in (("FIX-J2", 30), ("FIX-J3", 50)):
        for dx in (-2.5, 0, 2.5):
            box(owner, (x + dx, 12, 0.4), (0.2, 3.2, 0.2))
    for y in (4, 40):
        box("rail-" + str(y), (36, y, 0.08), (40, 0.18, 0.16))
    for p in config.places:
        if p.id.startswith(("CONTROL-", "TEST-")):
            continue
        x, y, z = p.position
        if p.id in variable_ports:
            continue
        if p.parent:
            if p.parent == "J3" and p.id.endswith((".TOP", ".COLUMNS")):
                continue
            if p.parent == "PRE-OUT" and p.id.endswith(".COLUMNS"):
                y += 0.7
            spread = 0.2 if p.id.startswith("PRE-IN.") and p.id.endswith(".ST-C.04.NET") else 0.45
            for dx in (-spread, spread):
                box(p.id, (x + dx, y, z - 0.02), (0.06, 0.5, 0.04))
        elif p.id in (
            "RECEIVE",
            "STEEL",
            "PRE-IN",
            "PRE-OUT",
            "J2",
            "BUF",
            "J3",
            "F1",
            "Q1",
            "OUT1",
            "FG1",
            "FG2",
            "DISPATCH",
            "MEP-RECEIVE",
            "MEP-STORE",
            "KIT",
            "F1-KIT",
        ):
            offsets = (
                (-2.7, 2.7)
                if p.id in ("RECEIVE", "STEEL", "PRE-IN", "PRE-OUT")
                else (-supports.RACK_POST_X, supports.RACK_POST_X)
                if p.id in ("MEP-RECEIVE", "MEP-STORE", "KIT", "F1-KIT")
                else (-1, 1)
            )
            for dx in offsets:
                box(
                    p.id,
                    (
                        x + dx,
                        y + 0.8
                        if p.id
                        in (
                            "RECEIVE",
                            "STEEL",
                            "PRE-IN",
                            "PRE-OUT",
                            "MEP-RECEIVE",
                            "MEP-STORE",
                            "KIT",
                            "F1-KIT",
                        )
                        else y,
                        z / 2,
                    ),
                    (0.25, 0.65, z),
                )
    for rack in state.supports:
        for beam in rack.beams:
            box(f"SC-{rack.root}-{beam.index}", beam.position, supports.BEAM_SIZE)
        for beam in supports.parking(config, rack.root):
            x, y, z = beam.position
            box(f"SC-HOLDER-{rack.root}-{beam.index}", (x, y, z - 0.0225), (0.06, 0.5, 0.005))
    available = {
        item.id: item.available + sum(r.quantity for r in state.reservations if r.lot_id == item.id)
        for item in state.lots
    }
    for obj in (*config.lots, *config.entities):
        loc = positions[obj.id]
        if (
            (loc not in places and obj.id not in transit)
            or obj.id in available
            and available[obj.id] <= 1e-9
        ):
            continue
        p = transit[obj.id] if loc == "IN_TRANSIT" else places[loc].position
        box(obj.id, (*p[:2], p[2] + obj.size_m[2] / 2), obj.size_m)
    for person in config.people:
        loc = positions[person.id]
        if loc in places or person.id in transit:
            p = (
                transit[person.id]
                if loc == "IN_TRANSIT"
                else standing_point(config, person.id, loc)
            )
            box(person.id, (*p[:2], p[2] + 0.95), (0.6, 1.2, 1.9))
    for d in config.devices:
        loc = positions[d.id]
        if (loc not in places and d.id not in transit) or d.kind in ("FIXED", "FIXTURE"):
            continue
        x, y, z = transit[d.id] if loc == "IN_TRANSIT" else places[loc].position
        if d.id == "CR1":
            for yy in (4, 40):
                box(d.id, (x, yy, 4.35), (4, 1.4, 8.7))
        elif d.id == "CART-01":
            parts = [
                ((0, 0, 0.14), (0.8, 0.6, 0.18)),
                ((0, -0.85, 1.1), (0.6, 0.05, 0.05)),
                ((0, -0.85, 0.65), (0.05, 0.05, 1)),
                ((0, 0, 0.75), (0.8, 0.6, 0.12)),
                ((0, -0.15, z - 0.05), (0.65, 1.1, 0.1)),
                *[
                    ((dx, dy, 0.15), (0.24, 0.24, 0.25))
                    for dx in (-0.32, 0.32)
                    for dy in (-0.24, 0.24)
                ],
            ]
            for index, (offset, size) in enumerate(parts):
                name = "/Handle" if index == 1 else "/HandlePost" if index == 2 else ""
                box(d.id + name, (x + offset[0], y - 1.1 + offset[1], offset[2]), size)
        elif d.id == "TEST1":
            parts = [
                ("", (0, 0, 0.14), (0.8, 0.6, 0.18)),
                ("/Handle", (0, 0.75, 1.1), (0.6, 0.05, 0.05)),
                ("/HandlePost", (0, 0.75, 0.65), (0.05, 0.05, 1)),
                ("", (0, 0, 0.75), (0.8, 0.6, 0.12)),
                ("", (0, 0, 0.96), (0.5, 0.4, 0.25)),
                ("", (0, -0.21, 0.96), (0.3, 0.02, 0.14)),
                *[
                    ("", (dx, dy, 0.15), (0.24, 0.24, 0.25))
                    for dx in (-0.32, 0.32)
                    for dy in (-0.24, 0.24)
                ],
            ]
            for name, offset, size in parts:
                box(d.id + name, (x + offset[0], y + offset[1], z + offset[2]), size)
        else:
            offset = 1.8 if d.id == "FORK-01" else 1.1 if d.id == "CART-01" else 0
            box(
                d.id,
                (x, y - offset, 0.14),
                (1.5, 2.6, 0.18) if d.id == "FORK-01" else (0.8, 0.6, 0.18),
            )
            if d.id == "FORK-01":
                box(d.id, (x, y - 2.7, 1), (1.3, 0.1, 1.6))
                for dx in (-0.65, 0.65):
                    box(d.id, (x + dx, y - 0.75, 1.25), (0.1, 0.12, 2.5))
                    box(d.id, (x + dx, y - 1.45, z - 0.06), (0.12, 1.3, 0.12))
    return result


def transport_blocker(config, state, op, rt):
    moving = {
        op.entity_id,
        rt.device_id,
        *(r.id for r in op.roles if r.qualification in ("FORK", "CART", "TOOL")),
    }
    obstacles = [b for b in boxes(config, state) if b[0].split("/", 1)[0] not in moving]
    for path, size in transport_sweeps(config, op, rt):
        for a, b in zip(path, path[1:]):
            for obstacle in obstacles:
                if not clear_segment(a, b, (obstacle,), size, margin=0):
                    return obstacle[0]
    return None


def output_blocker(config, state, op):
    from adaptive_hrc_scheduling.production_geometry import output_shapes

    outputs = output_shapes(config, op)
    if not outputs:
        return None
    quantities = {
        lot.id: lot.available + sum(r.quantity for r in state.reservations if r.lot_id == lot.id)
        for lot in state.lots
    }
    consumed = {a.lot_id for a in op.material_inputs if a.quantity >= quantities[a.lot_id] - 1e-9}
    excluded = consumed | set(op.component_inputs) | {ident for ident, _, _ in outputs}
    obstacles = boxes(config, state, excluded=excluded)
    for _, point, size in outputs:
        for obstacle in obstacles:
            if not clear_segment(point, point, (obstacle,), size, margin=0):
                return obstacle[0]
    return None


def clear_segment(a, b, obstacles, size=(0.6, 1.2, 1.9), margin=0.02):
    # Slab intersection of a segment and the obstacle expanded by actor extents.
    a = (*a[:2], a[2] + size[2] / 2)
    b = (*b[:2], b[2] + size[2] / 2)
    for _, lo, hi in obstacles:
        lower, upper = 0.0, 1.0
        for i in range(3):
            left, right = lo[i] - size[i] / 2 - margin, hi[i] + size[i] / 2 + margin
            delta = b[i] - a[i]
            if abs(delta) < 1e-12:
                if a[i] <= left + 1e-9 or a[i] >= right - 1e-9:
                    lower, upper = 1, 0
                    break
            else:
                item, r = sorted(((left - a[i]) / delta, (right - a[i]) / delta))
                lower, upper = max(lower, item), min(upper, r)
        if lower < upper - 1e-9:
            return False
    return True


def support_paths_clear(config, state, old, layout, elapsed=0):
    """Nominal swept support geometry, shared without executor state mutations."""
    rack = next(r for r in state.supports if r.root == layout.root)
    ids = tuple(f"SC-{layout.root}-{i}" for i in range(22))
    fixed = boxes(config, state, ids)
    poses = {b.index: b.position for b in rack.beams}
    half = tuple(s / 2 for s in supports.BEAM_SIZE)
    for move in supports.movements(config, old, layout):
        if elapsed >= move.end_h - 1e-12:
            continue
        moving = (2 * move.pair_index, 2 * move.pair_index + 1)
        obstacles = fixed + [
            (
                ids[i],
                tuple(p[j] - half[j] for j in range(3)),
                tuple(p[j] + half[j] for j in range(3)),
            )
            for i, p in poses.items()
            if i not in moving
        ]
        for side, path in enumerate(move.paths):
            remaining = max(0, elapsed - move.start_h) * 3600 * supports.SPEED_M_S
            for a, b in zip(path, path[1:]):
                length = math.dist(a, b)
                if remaining >= length:
                    remaining -= length
                    continue
                fraction = remaining / length if length else 1
                start = tuple(v + fraction * (w - v) for v, w in zip(a, b))
                if not clear_segment(
                    (*start[:2], start[2] - half[2]),
                    (*b[:2], b[2] - half[2]),
                    obstacles,
                    supports.BEAM_SIZE,
                    margin=0,
                ):
                    return False
                remaining = 0
            poses[moving[side]] = path[-1]
    return True


def walk_obstacles(config, state, person, source, target):
    excluded = [person]
    # Same designated standing-operator contact group as the existing target model.
    if person == "P1":
        excluded.append("FORK-01")
    cart_place = next(p.location for p in state.positions if p.id == "CART-01")
    if person == "E1" and cart_place in (source, target):
        excluded.extend(("CART-01/Handle", "CART-01/HandlePost"))
    tool_place = next(p.location for p in state.positions if p.id == "TEST1")
    if person == "QA1" and tool_place in (source, target):
        excluded.extend(("TEST1/Handle", "TEST1/HandlePost"))
    return boxes(config, state, excluded)


def walk(config, state, person, source, target):
    start, end = (standing_point(config, person, loc) for loc in (source, target))
    obstacle = walk_obstacles(config, state, person, source, target)
    obstacle = [
        o for o in obstacle if o[1][2] < (2.12 if person == "P1" else 1.92) and o[2][2] > -0.02
    ]
    a, b = (*start[:2], 0), (*end[:2], 0)
    xs = {1, 3, 10, 13, 25, 35, 45, 57, 59, a[0], b[0]}
    ys = {2, 7, 18, 29, 39, 42, a[1], b[1]}
    for _, lo, hi in obstacle:
        if lo[2] >= 1.92 or not any(
            all(lo[i] - 3 <= p[i] <= hi[i] + 3 for i in (0, 1)) for p in (a, b)
        ):
            continue
        xs.update(x for x in (lo[0] - 0.34, hi[0] + 0.34) if 0.31 <= x <= 59.69)
        ys.update(y for y in (lo[1] - 0.64, hi[1] + 0.64) if 0.61 <= y <= 43.39)
    xs, ys = sorted(xs), sorted(ys)
    nodes = {(x, y, 0) for x in xs for y in ys}
    edges = {p: [] for p in nodes}
    for axis in (0, 1):
        groups = {}
        for point in nodes:
            groups.setdefault(point[1 - axis], []).append(point)
        for row in groups.values():
            row.sort(key=lambda p: p[axis])
            for p, q in zip(row, row[1:]):
                if clear_segment(p, q, obstacle):
                    edges[p].append(q)
                    edges[q].append(p)
    heap, best = [(0, a, (a,))], {a: 0}
    while heap:
        cost, p, path = heapq.heappop(heap)
        if p == b:
            points = tuple(dict.fromkeys((start, *path, end)))
            return points if len(points) > 1 else (start, end)
        if cost > best[p]:
            continue
        for q in edges[p]:
            next_cost = cost + math.dist(p, q)
            if next_cost < best.get(q, math.inf):
                best[q] = next_cost
                heapq.heappush(heap, (next_cost, q, (*path, q)))
    require(False, "NO_LEGAL_PERSON_ROUTE")
