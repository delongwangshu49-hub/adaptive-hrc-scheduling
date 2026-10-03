"""R5 target layout, world metres. Scene assumptions, never production resources.

Clearances, rated envelopes and masses here are synthetic design inputs, not
equipment certification. The frozen configuration and legacy coordinate frame
remain in model.py/layout.py. Every required transfer has an explicit route.
"""

import heapq
import math
from dataclasses import dataclass

from .model import Box, require, sweep

VERSION = "S13-TARGET-R5-2"
SITE = (60, 44)
PEOPLE = (
    "P1",
    "W1",
    "W2",
    "OP1",
    "AF1",
    "AF2",
    "E1",
    "PL1",
    "T1",
    "T2",
    "C1",
    "QA1",
    "Lop",
    "Lrig",
    "Lsig",
)
# Load-bottom coordinates. Support top is exactly the endpoint bottom.
PADS = {
    "RECEIVE": (6, 7, 0.8),
    "STEEL": (6, 14, 0.8),
    "PRE-IN": (15, 7.5, 0.8),
    "PRE-OUT": (20, 12, 0.8),
    "J2": (30, 12, 0.6),
    "BUF": (40, 12, 0.6),
    "J3": (50, 12, 0.6),
    "F1": (50, 24, 0.6),
    "Q1": (40, 24, 0.6),
    "OUT1": (30, 24, 0.6),
    "FG1": (20, 24, 0.6),
    "FG2": (20, 34, 0.6),
    "DISPATCH": (30, 34, 0.6),
    "MEP-RECEIVE": (6, 23, 0.8),
    "MEP-STORE": (6, 29, 0.8),
    "KIT": (13, 29, 0.8),
    "F1-KIT": (55, 29, 0.8),
    "TEST-PARK": (55, 34, 0),
    "TEST-USE": (55, 25, 0),
}
FIXED = {
    "FIX-J2": Box("FIX-J2", (30, 12, 0.25), (6.2, 3.2, 0.5)),
    "FIX-J3": Box("FIX-J3", (50, 12, 0.25), (6.2, 3.2, 0.5)),
    "CUT1": Box("CUT1", (15, 12, 0.9), (1.6, 1.4, 1.8)),
    "R1": Box("R1", (35, 12, 1.6), (2.8, 3, 3.2)),
    "SCN-WELD-J2": Box("SCN-WELD-J2", (30, 16, 0.8), (1.5, 1, 1.6)),
    "SCN-WELD-J3": Box("SCN-WELD-J3", (50, 16, 0.8), (1.5, 1, 1.6)),
}
HOMES = {p: (3 + (i % 5) * 2, 36 + (i // 5) * 2, 0) for i, p in enumerate(PEOPLE)}
HOMES.update(W1=(25, 18, 0), W2=(45, 7, 0), Lop=(57, 18, 0), Lrig=(45, 18, 0), Lsig=(58, 30, 0))
CONTROL = {"Lop": (57, 18, 0), "Lrig": (45, 18, 0), "Lsig": (58, 30, 0)}
LOADS = {
    "steel": ((2.8, 0.8, 0.2), 0.06),
    "frame": ((6, 3, 0.2), 1.2),
    "columns": ((1.6, 1.6, 2.8), 0.8),
    "module": ((6, 3, 3.2), 8.0),
    "mep": ((1.2, 0.8, 0.6), 0.08),
    "empty": ((0.4, 0.4, 0.4), 0.0),
}
FORK_SIZE = (1.5, 2.6, 2.5)
CART_SIZE = (1.5, 1.1, 1.2)
PERSON_SIZE = (0.6, 1.2, 1.9)


def centers(points, size):
    return [(x, y, z + size[2] / 2) for x, y, z in points]


def length(points):
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def static_boxes():
    boxes = list(FIXED.values())
    # Slim trestles leave forks room underneath, contact at top is intentional.
    for name, (x, y, z) in PADS.items():
        if name.startswith("TEST"):
            continue
        long = name not in ("MEP-RECEIVE", "MEP-STORE", "KIT", "F1-KIT")
        for i, dx in enumerate((-1, 1) if long else (-0.45, 0.45)):
            boxes.append(Box(name + "-support-" + str(i), (x + dx, y, z / 2), (0.25, 0.65, z)))
    boxes.extend(
        [
            Box("rail-south", (36, 4, 0.08), (40, 0.18, 0.16)),
            Box("rail-north", (36, 40, 0.08), (40, 0.18, 0.16)),
        ]
    )
    return boxes


def check_route(points, size, obstacles=(), margin=0):
    require(len(points) >= 2, "EMPTY_ROUTE")
    for p in points:
        require(all(math.isfinite(v) for v in p), "NONFINITE_POSITION")
        require(
            all(size[i] / 2 + margin <= p[i] <= SITE[i] - size[i] / 2 - margin for i in (0, 1)),
            "SITE_CONTAINMENT",
        )
        require(p[2] >= 0, "BELOW_FLOOR")
    sweep(centers(points, size), size, obstacles, margin)


@dataclass(frozen=True)
class Task:
    id: str
    source: str
    target: str
    load: str
    carrier: str
    operator: str
    receiver: str

    @property
    def size(self):
        return LOADS[self.load][0]

    @property
    def points(self):
        a, b = PADS[self.source], PADS[self.target]
        if self.carrier == "CR1":
            # bottom 4.1 + module 3.2 + rig 0.6 = 7.9 < girder underside 8.5
            return (a, (a[0], a[1], 4.1), (b[0], a[1], 4.1), (b[0], b[1], 4.1), b)
        h = 1.05 if self.carrier == "SCN-FORK-01" else 0.9
        if self.source == "RECEIVE":
            mid = ((11, 7, h), (11, 14, h), (6, 14, h))
        elif self.source == "STEEL":
            mid = ((11, 14, h), (11, 7.5, h), (15, 7.5, h))
        elif self.source == "PRE-IN":
            # Cutter remains fixed; load goes past its east side to the output.
            mid = ((20, 7.5, h), (20, 12, h))
        elif self.source == "MEP-RECEIVE":
            mid = ((10, 23, h), (10, 29, h), (6, 29, h))
        else:
            mid = ((b[0], a[1], h), (b[0], b[1], h))
        return (a, (a[0], a[1], h), *mid, b)


TASKS = tuple(
    Task(*row)
    for row in (
        ("S01", "RECEIVE", "STEEL", "steel", "SCN-FORK-01", "P1", "QA1"),
        ("S02", "STEEL", "PRE-IN", "steel", "SCN-FORK-01", "P1", "W1"),
        ("S03", "PRE-IN", "PRE-OUT", "steel", "SCN-FORK-01", "P1", "W1"),
        ("S04", "PRE-OUT", "J2", "steel", "CR1", "Lop", "W1"),
        ("C01", "PRE-OUT", "J2", "frame", "CR1", "Lop", "W1"),
        ("C02", "J2", "BUF", "frame", "CR1", "Lop", "W2"),
        ("C03", "BUF", "J3", "frame", "CR1", "Lop", "W2"),
        ("C04", "PRE-OUT", "J3", "columns", "CR1", "Lop", "W2"),
        ("M01", "J3", "F1", "module", "CR1", "Lop", "AF1"),
        ("M02", "F1", "Q1", "module", "CR1", "Lop", "QA1"),
        ("M03", "Q1", "F1", "module", "CR1", "Lop", "AF1"),
        ("M04", "F1", "OUT1", "module", "CR1", "Lop", "QA1"),
        ("F01", "OUT1", "FG1", "module", "CR1", "Lop", "QA1"),
        ("F02", "OUT1", "FG2", "module", "CR1", "Lop", "QA1"),
        ("F03", "FG1", "DISPATCH", "module", "CR1", "Lop", "QA1"),
        ("F04", "FG2", "DISPATCH", "module", "CR1", "Lop", "QA1"),
        ("P01", "MEP-RECEIVE", "MEP-STORE", "mep", "SCN-CART-01", "E1", "QA1"),
        ("P02", "MEP-STORE", "KIT", "mep", "SCN-CART-01", "E1", "AF1"),
        ("P03", "KIT", "F1-KIT", "mep", "SCN-CART-01", "E1", "AF1"),
    )
)
TASK_BY_ID = {t.id: t for t in TASKS}


def parked_crane_boxes(hook):
    """Stationary structure remains an obstacle to other actors."""
    x, y, _ = hook
    return [
        *(Box(f"crane-support-{i}", (x, v, 4.35), (4, 1.4, 8.7)) for i, v in enumerate((4, 40))),
        Box("crane-girder", (x, 22, 8.8), (0.7, 37, 0.6)),
        Box("crane-trolley", (x, y, 9.25), (1, 1.2, 0.3)),
    ]


def check_crane_structure(points, obstacles):
    """Whole moving structure, also for empty approach/return and live actors."""
    obs = [o for o in obstacles if not o.name.startswith("rail-")]
    for y in (4, 40):
        sweep([(p[0], y, 4.35) for p in points], (4, 1.4, 8.7), obs)
    sweep([(p[0], 22, 8.8) for p in points], (0.7, 37, 0.6), obs)
    sweep([(p[0], p[1], 9.25) for p in points], (1, 1.2, 0.3), obs)


def verify_task(task, obstacles=None, hook_limit=8.2):
    obs = static_boxes() if obstacles is None else obstacles
    if task.carrier != "CR1":
        obs = [*obs, *parked_crane_boxes((30, 18, 8))]
    check_route(task.points, task.size, obs)
    if task.carrier == "CR1":
        require(LOADS[task.load][1] + 1 <= 12, "CRANE_MASS")
        for x, y, z in task.points:
            require(18 <= x <= 54 and 8 <= y <= 36, "HOOK_COVERAGE")
            require(z + task.size[2] + 0.6 <= hook_limit, "HOOK_HEADROOM")
        # Full load plus slings, and moving bogie/leg envelopes.
        check_route(task.points, (task.size[0], task.size[1], task.size[2] + 0.6), obs)
        check_crane_structure(task.points, obs)
    else:
        require(
            task.load in (("steel",) if task.carrier == "SCN-FORK-01" else ("mep",)),
            "LOAD_ADAPTATION",
        )
        # Four-direction synthetic fork carrier: fixed chassis heading, steerable
        # wheels; no unmodelled chassis rotation at orthogonal route corners.
        size = FORK_SIZE if task.carrier == "SCN-FORK-01" else CART_SIZE
        offset = 1.8 if task.carrier == "SCN-FORK-01" else 1.1
        route = tuple((x, y - offset, 0) for x, y, _ in task.points)
        check_route(route, size, obs)
        if task.carrier == "SCN-FORK-01":
            for dx in (-0.65, 0.65):
                check_route(
                    tuple((p[0] + dx, p[1] - 0.25, p[2] - 0.12) for p in task.points),
                    (0.12, 1.3, 0.12),
                    obs,
                )
        else:
            check_route(
                tuple((p[0], p[1] - 0.45, p[2] - 0.1) for p in task.points), (0.65, 1.1, 0.1), obs
            )
        require(
            LOADS[task.load][1] <= (0.3 if task.carrier == "SCN-FORK-01" else 0.1), "CARRIER_MASS"
        )
    return {
        "id": task.id,
        "source_world": task.points[0],
        "target_world": task.points[-1],
        "points_world": task.points,
        "size_m": task.size,
        "mass_t": LOADS[task.load][1],
        "carrier": task.carrier,
        "operator": task.operator,
        "receiver": task.receiver,
        "status": "PASS_GEOMETRY_ONLY",
        "distance_m": length(task.points),
        "production_qualification": "UNKNOWN",
    }


def transfer_matrix(obstacles=None):
    """Every loaded leg and its empty return/approach, plus the testing cart."""
    obs = static_boxes() if obstacles is None else obstacles
    rows = []
    for t in TASKS:
        row = verify_task(t, obs)
        rows.append(
            {
                **row,
                "kind": "LOADED",
                "support": "ADJUSTABLE_SLINGS"
                if t.carrier == "CR1"
                else "TWIN_FORKS"
                if t.carrier == "SCN-FORK-01"
                else "LIFT_TRANSFER_TRAY",
            }
        )
        if t.carrier == "CR1":
            h = t.size[2] + 0.6
            source = (*t.points[0][:2], t.points[0][2] + h)
            end = (*t.points[-1][:2], t.points[-1][2] + h)
            routes = {
                "EMPTY_APPROACH": (
                    (30, 18, 8),
                    (source[0], 18, 8),
                    (source[0], source[1], 8),
                    source,
                ),
                "EMPTY_RETURN": (end, (end[0], end[1], 8), (30, end[1], 8), (30, 18, 8)),
            }
            size = (*t.size[:2], 0.8)
        else:
            offset = 1.8 if t.carrier == "SCN-FORK-01" else 1.1
            routes = {"EMPTY_RETURN": tuple((p[0], p[1] - offset, 0) for p in reversed(t.points))}
            size = FORK_SIZE if t.carrier == "SCN-FORK-01" else CART_SIZE
        for kind, points in routes.items():
            checked = tuple((x, y, z - 0.6) for x, y, z in points) if t.carrier == "CR1" else points
            route_obs = obs if t.carrier == "CR1" else [*obs, *parked_crane_boxes((30, 18, 8))]
            check_route(checked, size, route_obs)
            if t.carrier == "CR1":
                check_crane_structure(points, obs)
            rows.append(
                {
                    **row,
                    "id": t.id + "-" + kind,
                    "kind": kind,
                    "source_world": points[0],
                    "target_world": points[-1],
                    "points_world": points,
                    "size_m": size,
                    "mass_t": 1 if t.carrier == "CR1" else 0,
                    "distance_m": length(points),
                    "support": "EMPTY_RIG"
                    if t.carrier == "CR1"
                    else "SUPPORT_RETRACTED_BEFORE_RETURN",
                }
            )
    for kind, a, b in (
        ("DELIVER", PADS["TEST-PARK"], PADS["TEST-USE"]),
        ("RETRIEVE", PADS["TEST-USE"], PADS["TEST-PARK"]),
    ):
        points = (a, (57, a[1], 0), (57, b[1], 0), b)
        check_route(points, (0.8, 1.1, 1.2), [*obs, *parked_crane_boxes((30, 18, 8))])
        rows.append(
            {
                "id": "TEST-" + kind,
                "kind": kind,
                "source_world": a,
                "target_world": b,
                "points_world": points,
                "size_m": (0.8, 1.1, 1.2),
                "mass_t": 0,
                "carrier": "TEST1",
                "operator": "QA1",
                "receiver": "QA1",
                "support": "WHEELED_TOOL_CART",
                "status": "PASS_GEOMETRY_ONLY",
                "distance_m": length(points),
                "production_qualification": "UNKNOWN",
            }
        )
    return rows


class WalkGraph:
    """Finite rectilinear graph plus legal endpoint spurs; Dijkstra, no teleport."""

    def __init__(self, obstacles=()):
        self.obstacles = tuple(obstacles)

    def route(self, start, end):
        require(start[2] == end[2] == 0, "PERSON_NOT_ON_FLOOR")
        xs = sorted({3, 10, 13, 25, 35, 45, 57, start[0], end[0]})
        ys = sorted({7, 18, 29, 39, start[1], end[1]})
        # Extra lines only attach an endpoint to its nearest existing lane.
        nodes = {
            (x, y, 0)
            for x in xs
            for y in ys
            if x in (3, 10, 13, 25, 35, 45, 57) or y in (7, 18, 29, 39)
        } | {start, end}
        edges = {p: [] for p in nodes}
        for axis in (0, 1):
            groups = {}
            for p in nodes:
                groups.setdefault(p[1 - axis], []).append(p)
            for group in groups.values():
                group.sort(key=lambda p: p[axis])
                for a, b in zip(group, group[1:]):
                    try:
                        check_route((a, b), PERSON_SIZE, self.obstacles, 0.05)
                    except ValueError:
                        continue
                    edges[a].append(b)
                    edges[b].append(a)
        heap, best = [(0, start, (start,))], {start: 0}
        while heap:
            distance, node, path = heapq.heappop(heap)
            if node == end:
                return path if len(path) > 1 else (start, end)
            if distance > best[node]:
                continue
            for other in edges[node]:
                cost = distance + math.dist(node, other)
                if cost < best.get(other, math.inf):
                    best[other] = cost
                    heapq.heappush(heap, (cost, other, (*path, other)))
        raise ValueError("NO_LEGAL_PERSON_ROUTE")
