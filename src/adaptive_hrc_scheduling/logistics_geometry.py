"""Declared world-coordinate conventions shared by contract fixtures and execution."""

import math


def standing_point(config, person, location):
    point = next(p.position for p in config.places if p.id == location)
    if location.startswith("CONTROL-"):
        return tuple(point)
    if location.startswith("TEST-"):
        return (point[0], point[1] + 1.25, 0.0)
    ordinal = next(i for i, p in enumerate(config.people) if p.id == person)
    return (point[0] + 4.0 + 0.9 * (ordinal % 3), point[1] + 2.5, 0.0)


def interpolate(points, fraction, horizontal_speed, vertical_speed):
    costs = [
        (abs(b[0] - a[0]) + abs(b[1] - a[1])) / horizontal_speed + abs(b[2] - a[2]) / vertical_speed
        for a, b in zip(points, points[1:])
    ]
    remaining = max(0, min(1, fraction)) * sum(costs)
    for i, cost in enumerate(costs):
        if remaining <= cost and cost:
            t = remaining / cost
            return tuple(a + (b - a) * t for a, b in zip(points[i], points[i + 1]))
        remaining -= cost
    return tuple(points[-1])


def close(a, b, tolerance=0.001):
    return len(a) == len(b) == 3 and math.dist(a, b) <= tolerance


def motion_fraction(config, operation, run, now_h):
    """Stationary preparation/loading, timed travel, then stationary unloading."""
    route = next(r for r in config.routes if r.id == operation.route_id)
    travel = (
        sum(
            (abs(b.x - a.x) + abs(b.y - a.y)) / route.speed_m_s
            + abs(b.z - a.z) / route.vertical_speed_m_s
            for a, b in zip(route.points, route.points[1:])
        )
        / 3600
    )
    carrying = operation.action in ("TRANSFER", "DEPLOY_TOOL", "RETRIEVE_TOOL")
    lead = operation.base_h + (config.setup_h + config.load_h if carrying else 0)
    base = lead + travel + (config.unload_h if carrying else 0)
    factor = (run.earliest_end_h - run.started_h + run.active_before_h) / base if base else 1
    elapsed = run.active_before_h + now_h - run.started_h
    return max(0, min(1, (elapsed - lead * factor) / max(1e-12, travel * factor)))
