"""Versioned scene-only layout. Coordinates below are production-core local metres.

World = local + CORE_ORIGIN. These objects never extend domain resources.
"""

from .model import ZONES, Box, require, sweep

VERSION = "S13-LAYOUT-r2"
CORE_ORIGIN = (14, 4, 0)
SITE_SIZE = (60, 44)
SUPPLY = {
    "SCN-RECEIVE": ((-7, 1, 0), (10, 6), "QUARANTINED BATCH", 2),
    "SCN-STEEL": ((-7, 10, 0), (10, 8), "STEEL RELEASED", 3),
    "SCN-PANELS": ((-7, 19, 0), (10, 6), "PANELS", 2),
    "SCN-MEP": ((-7, 27, 0), (10, 6), "MEP KITS", 2),
    "SCN-RETURN": ((-7, 34, 0), (10, 4), "RETURN HOLD", 1),
    "SCN-KIT": ((6, 24, 0), (8, 8), "KIT HANDOFF", 2),
}
# Fixed shelves occupy the west side; east-facing extraction ends remain open.
RACKS = tuple(
    Box(name, (-10.5, center[1], 0.7), (1, size[1] - 1, 1.4))
    for name, (center, size, _, _) in SUPPLY.items()
    if name != "SCN-KIT"
)
MATERIAL_PATHS = {
    "steel_to_input": ((-7, 10, 0.6), (-7, 7, 0.6), (1, 7, 0.6)),
    "cut_feed": ((1, 7, 0.6), (1, 8.5, 0.6)),
    "cut_to_output": ((1, 8.5, 0.6), (6, 8.5, 0.6), (6, 7.5, 0.6)),
    "mep_to_f1": (
        (-6, 27, 0.6),
        (-1, 27, 0.6),
        (-1, 28.8, 0.6),
        (31, 28.8, 0.6),
        (31, 27.5, 0.6),
        (32, 27.5, 0.6),
    ),
    "weld_j2_j3": (
        (12, 10, 0),
        (11, 10, 0),
        (11, 15.6, 0),
        (31, 15.6, 0),
        (31, 11, 0),
        (32, 11, 0),
    ),
    "test_delivery": ((31, 26, 0), (32, 26, 0), (32, 25, 0)),
}


def world(point):
    return tuple(a + b for a, b in zip(point, CORE_ORIGIN, strict=True))


def local(point):
    return tuple(a - b for a, b in zip(point, CORE_ORIGIN, strict=True))


def person_home(index):
    return (2 + index * 1.5, 36, 0)


def person_path(index, destination):
    """West gate bypasses both rails; module-lane crossing needs an idle crane."""
    start = person_home(index)
    x, y, z = destination
    return (start, (start[0], 37.5, 0), (-1, 37.5, 0), (-1, 15.8, 0), (x, 15.8, 0), (x, y, z))


PERSON_STATIONS = {
    "P1": (1, 11, 0),
    "W1": (11, 9, 0),
    "W2": (11, 11.5, 0),
    "OP1": (20.8, 15, 0),
    "AF1": (40.5, 22, 0),
    "AF2": (40.5, 23, 0),
    "E1": (40.5, 24, 0),
    "PL1": (40.5, 25, 0),
    "T1": (40.5, 26, 0),
    "T2": (40.5, 27, 0),
    "C1": (31, 14.8, 0),
    "QA1": (41.5, 26, 0),
    "Lop": (42, 15, 0),
    "Lrig": (41, 12, 0),
    "Lsig": (42, 10, 0),
}


def length(points):
    return sum(sum(abs(a - b) for a, b in zip(p, q)) for p, q in zip(points, points[1:]))


def layout_comparison():
    """Finite candidates, identical object sizes and routes; no makespan inference.

    Candidate A places required upstream pads in the original western core. B
    separates them in the west extension. All overlap pairs and endpoints are
    reported, including the infeasible candidate rather than hiding it.
    """
    result = []
    for name, offset, site in (
        ("A-original-plus-supply", (0, 0), (42, 34)),
        ("B-west-supply", (14, 4), SITE_SIZE),
    ):
        bays = [
            Box(k, (x + offset[0], y + offset[1], 0.5), (8, 8, 1)) for k, (x, y) in ZONES.items()
        ]
        pads = [Box(k, (p[0] + 14, p[1] + 4, 0.5), (*s, 1)) for k, (p, s, _, _) in SUPPLY.items()]
        clashes = [(a.name, b.name) for a in bays for b in pads if a.overlaps(b)]
        endpoints = {k: (x + offset[0], y + offset[1]) for k, (x, y) in ZONES.items()}
        edges = (
            ("PRE", "J2"),
            ("J2", "BUF"),
            ("BUF", "J3"),
            ("PRE", "J3"),
            ("J3", "F1"),
            ("F1", "OUT1"),
            ("F1", "Q1"),
        )
        distances = {a + "-" + b: length([endpoints[a], endpoints[b]]) for a, b in edges}
        result.append(
            {
                "candidate": name,
                "site_m": site,
                "outside_site": [
                    p.name
                    for p in pads
                    if any(
                        p.center[i] - p.size[i] / 2 < 0 or p.center[i] + p.size[i] / 2 > site[i]
                        for i in (0, 1)
                    )
                ],
                "pad_bay_conflicts": clashes,
                "core_origin": offset,
                "required_endpoint_manhattan_m": distances,
                "supply_to_pre_m": length([(7, 14), endpoints["PRE"]]),
                "crane_endpoint_coverage": all(
                    4 <= x <= 38 and 6.5 <= y <= 27.5 for x, y in ZONES.values()
                ),
                "person_route_count": len(PERSON_STATIONS),
                "shared_crossing_ids": ["SCN-X-MODULE", "SCN-X-SUPPLY"],
                "station_reachability": "REQUIRES_USD_SWEEP" if not clashes else "BLOCKED",
                "selected": not clashes,
            }
        )
    return result


def check_site(points, size):
    for p in points:
        w = world(p)
        require(
            all(size[i] / 2 <= w[i] <= SITE_SIZE[i] - size[i] / 2 for i in (0, 1)),
            "SITE_CONTAINMENT",
        )
    sweep(points, size, RACKS)
