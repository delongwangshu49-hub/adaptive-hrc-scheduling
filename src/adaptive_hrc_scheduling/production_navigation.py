"""Finite pedestrian graph on the declared S15 site; no execution mutations."""

import heapq
import math
from functools import lru_cache
from types import SimpleNamespace

from adaptive_hrc_scheduling import production_supports as supports
from adaptive_hrc_scheduling.contracts.codec import immutable_memo, require
from adaptive_hrc_scheduling.production_geometry import standing_point, transport_sweeps
from adaptive_hrc_scheduling.production_pedestrians import fork_access, fork_walk_phases, walk_yaw


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


class _GeometryContext:
    def __init__(self, config):
        self.config = config


@immutable_memo(maxsize=8)
def _geometry_context(config):
    return _GeometryContext(config)


def boxes(config, state, excluded=()):
    return list(
        _boxes_cached(
            _geometry_context(config),
            tuple(state.running),
            tuple(state.motions),
            tuple(state.positions),
            tuple(state.supports),
            tuple((x.id, x.available) for x in state.lots),
            tuple((x.lot_id, x.quantity) for x in state.reservations),
            tuple(sorted(excluded)),
        )
    )


@lru_cache(maxsize=64)
def _boxes_cached(
    context, running, motions, positions, supports_state, lots, reservations, excluded
):
    state = SimpleNamespace(
        running=running,
        motions=motions,
        positions=positions,
        supports=supports_state,
        lots=tuple(SimpleNamespace(id=i, available=q) for i, q in lots),
        reservations=tuple(SimpleNamespace(lot_id=i, quantity=q) for i, q in reservations),
    )
    return tuple(_boxes_uncached(context.config, state, excluded))


def _boxes_uncached(config, state, excluded=()):
    places = {p.id: p for p in config.places}
    positions = {p.id: p.location for p in state.positions}
    transit = {}
    pedestrian_yaws = {}
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
        if op.action == "WALK" and op.entity_id == "P1":
            points = tuple((p.x, p.y, p.z) for p in rt.points)
            fork_location = positions["FORK-01"]
            if fork_location in places:
                phases, _ = fork_walk_phases(
                    points,
                    places[fork_location].position,
                    leaving=op.location == fork_location,
                    entering=op.target == fork_location,
                )
                pedestrian_yaws[op.entity_id] = walk_yaw(points, point, phases)
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
        if owner not in excluded and owner.split("/", 1)[0] not in excluded:
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
            box(
                person.id,
                (*p[:2], p[2] + 0.95),
                (1.2, 0.6, 1.9) if pedestrian_yaws.get(person.id) == 90 else (0.6, 1.2, 1.9),
            )
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
                d.id + "/Deck" if d.id == "FORK-01" else d.id,
                (x, y - offset, 0.14),
                (1.5, 2.6, 0.18) if d.id == "FORK-01" else (0.8, 0.6, 0.18),
            )
            if d.id == "FORK-01":
                box(d.id + "/Guard", (x, y - 2.7, 1), (1.3, 0.1, 1.6))
                box(d.id + "/Controls", (x, y - 1.7, 1.2), (0.6, 0.3, 0.3))
                for i, dx in enumerate((-0.65, 0.65)):
                    box(d.id + f"/Mast{i}", (x + dx, y - 0.75, 1.25), (0.1, 0.12, 2.5))
                    box(d.id + f"/Forks/Tine{i}", (x + dx, y - 1.45, z - 0.06), (0.12, 1.3, 0.12))
    return result


def transport_blocker(config, state, op, rt):
    conflict = concurrent_crane_blocker(config, state, op, rt)
    if conflict is not None:
        return conflict
    moving = {
        op.entity_id,
        rt.device_id,
        *(r.id for r in op.roles if r.qualification in ("FORK", "CART", "TOOL")),
    }
    obstacles = [b for b in boxes(config, state) if b[0].split("/", 1)[0] not in moving]
    for path, size in transport_sweeps(config, op, rt):
        for a, b in zip(path, path[1:]):
            if clear_segment(a, b, obstacles, size, margin=0):
                continue
            for obstacle in obstacles:
                if not clear_segment(a, b, (obstacle,), size, margin=0):
                    return obstacle[0]
    return None


def concurrent_crane_blocker(config, state, op, rt):
    """Reserve overlapping crane/ground swept volumes until real release.

    Current endpoint geometry alone misses a crane empty return crossing an
    already accepted forklift route. Use only delivered running commands, not
    future jobs or hidden events. Full-route envelopes are conservative.
    """
    operations = {o.id: o for o in config.operations}
    routes = {r.id: r for r in config.routes}
    for running in state.running:
        command = running.command
        if command.operation_id == op.id:
            continue
        other = command.service.operation if command.service else operations[command.operation_id]
        if not other.route_id:
            continue
        other_route = command.service.route if command.service else routes[other.route_id]
        if (rt.device_id == "CR1") == (other_route.device_id == "CR1"):
            continue
        crane, ground, ground_route = (
            (rt, other, other_route) if rt.device_id == "CR1" else (other_route, op, rt)
        )
        crane_min, crane_max = min(p.x for p in crane.points), max(p.x for p in crane.points)
        columns = tuple(
            ("CR1", (crane_min - 2, y - 0.7, 0), (crane_max + 2, y + 0.7, 8.7)) for y in (4, 40)
        )
        paths = transport_sweeps(config, ground, ground_route)
        if ground.action == "WALK":
            paths += ((tuple((p.x, p.y, p.z) for p in ground_route.points), (1.2, 1.2, 1.9)),)
        if any(
            not clear_segment(a, b, columns, size, margin=0)
            for points, size in paths
            for a, b in zip(points, points[1:])
        ):
            return "CONCURRENT_CRANE_SWEEP:" + command.operation_id
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
    low = (
        min(a[0], b[0]) - size[0] / 2 - margin,
        min(a[1], b[1]) - size[1] / 2 - margin,
        min(a[2], b[2]) - size[2] / 2 - margin,
    )
    high = (
        max(a[0], b[0]) + size[0] / 2 + margin,
        max(a[1], b[1]) + size[1] / 2 + margin,
        max(a[2], b[2]) + size[2] / 2 + margin,
    )
    for _, lo, hi in obstacles:
        if (
            high[0] <= lo[0]
            or low[0] >= hi[0]
            or high[1] <= lo[1]
            or low[1] >= hi[1]
            or high[2] <= lo[2]
            or low[2] >= hi[2]
        ):
            continue
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
    cart_place = next(p.location for p in state.positions if p.id == "CART-01")
    if person == "E1" and cart_place in (source, target):
        excluded.extend(("CART-01/Handle", "CART-01/HandlePost"))
    tool_place = next(p.location for p in state.positions if p.id == "TEST1")
    if person == "QA1" and tool_place in (source, target):
        excluded.extend(("TEST1/Handle", "TEST1/HandlePost"))
    return boxes(config, state, excluded)


def walk_blocker(config, state, person, source, target, points):
    obstacles = walk_obstacles(config, state, person, source, target)
    fork_location = next(p.location for p in state.positions if p.id == "FORK-01")
    fork = next((p.position for p in config.places if p.id == fork_location), None)
    phases, turns = (
        fork_walk_phases(
            points, fork, leaving=source == fork_location, entering=target == fork_location
        )
        if person == "P1" and fork is not None
        else ({}, {})
    )
    for index, (a, b) in enumerate(zip(points, points[1:])):
        contacts, yaw = phases.get(index, ((), 0))
        contact_names = {"FORK-01/" + part for part in contacts}
        relevant = [o for o in obstacles if o[0] not in contact_names] if contacts else obstacles
        if clear_segment(a, b, relevant, (1.2, 0.6, 1.9) if yaw else (0.6, 1.2, 1.9)):
            continue
        for obstacle in obstacles:
            if obstacle[0] not in contact_names:
                if not clear_segment(
                    a, b, (obstacle,), (1.2, 0.6, 1.9) if yaw else (0.6, 1.2, 1.9)
                ):
                    return obstacle[0]
    for index, contacts in turns.items():
        p = points[index]
        for name, low, high in obstacles:
            if name in {"FORK-01/" + part for part in contacts}:
                continue
            dx, dy = (max(low[i] - p[i], 0, p[i] - high[i]) for i in (0, 1))
            if (
                low[2] < p[2] + 1.92
                and high[2] > p[2] - 0.02
                and math.hypot(dx, dy) < math.hypot(0.3, 0.6) + 0.02 - 1e-9
            ):
                return name
    return None


def walk(config, state, person, source, target):
    start, end = (standing_point(config, person, loc) for loc in (source, target))
    obstacle = walk_obstacles(config, state, person, source, target)
    obstacle = [
        o for o in obstacle if o[1][2] < (2.12 if person == "P1" else 1.92) and o[2][2] > -0.02
    ]
    fork_location = next(p.location for p in state.positions if p.id == "FORK-01")
    fork = next((p.position for p in config.places if p.id == fork_location), None)

    def access(location, point, entering=False):
        paths = ((point, (*point[:2], 0)),)
        if person == "P1" and fork is not None and location == fork_location:
            options = fork_access(fork)
            if point == options[0][0]:
                paths = options
        if entering:
            paths = tuple(tuple(reversed(path)) for path in paths)
        return tuple(
            path
            for path in paths
            if walk_blocker(config, state, person, source, target, path) is None
        )

    starts, finishes = access(source, start), access(target, end, True)
    require(starts and finishes, "NO_LEGAL_PERSON_ACCESS")
    points = _walk_graph(starts, finishes, tuple(obstacle))
    require(
        walk_blocker(config, state, person, source, target, points) is None, "NO_LEGAL_PERSON_ROUTE"
    )
    return points if len(points) > 1 else (start, end)


@lru_cache(maxsize=128)
def _walk_graph(starts, finishes, obstacle):
    """Cache only the exact visible geometry, endpoints and legal access paths."""
    endpoints = [p[-1] for p in starts] + [p[0] for p in finishes]
    xs = {1, 3, 10, 13, 25, 35, 45, 57, 59, *(p[0] for p in endpoints)}
    ys = {2, 7, 18, 29, 39, 42, *(p[1] for p in endpoints)}
    for _, lo, hi in obstacle:
        if lo[2] >= 1.92 or not any(
            all(lo[i] - 3 <= p[i] <= hi[i] + 3 for i in (0, 1)) for p in endpoints
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
            # Every edge in this row has the same orthogonal coordinate.
            # Reject disjoint obstacle slabs once per row, retaining the exact
            # segment test (and original obstacle order) for possible contacts.
            other = 1 - axis
            fixed = row[0][other]
            half = (0.3, 0.6)[other] + 0.02
            relevant = tuple(
                o for o in obstacle if o[1][other] - half <= fixed <= o[2][other] + half
            )
            for p, q in zip(row, row[1:]):
                if clear_segment(p, q, relevant):
                    edges[p].append(q)
                    edges[q].append(p)
    heap, best = [], {}
    for path in starts:
        cost = sum(math.dist(a, b) for a, b in zip(path, path[1:]))
        best[path[-1]] = cost
        heapq.heappush(heap, (cost, path[-1], path))
    goals = {path[0]: path for path in finishes}
    while heap:
        cost, p, path = heapq.heappop(heap)
        if p in goals:
            return tuple(dict.fromkeys((*path, *goals[p][1:])))
        if cost > best[p]:
            continue
        for q in edges[p]:
            next_cost = cost + math.dist(p, q)
            if next_cost < best.get(q, math.inf):
                best[q] = next_cost
                heapq.heappush(heap, (next_cost, q, (*path, q)))
    require(False, "NO_LEGAL_PERSON_ROUTE")
