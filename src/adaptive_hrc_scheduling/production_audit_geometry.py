"""Independent pedestrian collision decisions on reconstructed scene geometry.

The scene's part boxes are data shared with the declared layout. No executor
path predicate, route finder or contact-acceptance function is called here.
"""

from adaptive_hrc_scheduling.production_navigation import boxes
from adaptive_hrc_scheduling.production_pedestrians import FORK_ACCESS_X, FORK_ACCESS_Y


def walk_collision(config, state, operation, route):
    positions = {p.id: p.location for p in state.positions}
    places = {p.id: p.position for p in config.places}
    person = operation.entity_id
    points = tuple((p.x, p.y, p.z) for p in route.points)
    excluded = {person}
    for actor, device in (("E1", "CART-01"), ("QA1", "TEST1")):
        if person == actor and positions[device] in (operation.location, operation.target):
            excluded.update((device + "/Handle", device + "/HandlePost"))
    obstacles = boxes(config, state, excluded)
    fork_location = positions["FORK-01"]
    fork = places.get(fork_location)

    def matching(a, b):
        return all(abs(x - y) <= 1e-9 for x, y in zip(a, b))

    phases, turns = {}, {}
    if person == "P1" and fork is not None and len(points) >= 4:
        operator = (fork[0], fork[1] - 2.25, 0.2)
        for side in (-1, 1):
            pivot = (fork[0], fork[1] + FORK_ACCESS_Y, 0.2)
            gate = (fork[0] + side * FORK_ACCESS_X, pivot[1], 0.2)
            path = (operator, pivot, gate, (*gate[:2], 0))
            departure = operation.location == fork_location and all(
                matching(a, b) for a, b in zip(points[:4], path)
            )
            arrival = operation.target == fork_location and all(
                matching(a, b) for a, b in zip(points[-4:], reversed(path))
            )
            cab = {"FORK-01/Deck", "FORK-01/Guard", "FORK-01/Controls"}
            if departure:
                phases.update({0: (cab, False), 1: (cab, True)})
                turns.update({1: cab, 2: set()})
            if arrival:
                phases.update({len(points) - 3: (cab, True), len(points) - 2: (cab, False)})
                turns.update({len(points) - 3: set(), len(points) - 2: cab})
    for index, (a, b) in enumerate(zip(points, points[1:])):
        contacts, rotated = phases.get(index, (set(), False))
        for name, low, high in obstacles:
            if name in contacts:
                continue
            # Clip the interval in which a foot-point path occupies each
            # expanded box axis. All three intervals must overlap for a hit.
            intervals = [(0.0, 1.0)]
            for axis, half in enumerate((0.6, 0.3, 0.95) if rotated else (0.3, 0.6, 0.95)):
                offset = 0.95 if axis == 2 else 0
                left = low[axis] - half - 0.02 - offset
                right = high[axis] + half + 0.02 - offset
                delta = b[axis] - a[axis]
                if abs(delta) < 1e-12:
                    if not left + 1e-9 < a[axis] < right - 1e-9:
                        intervals = []
                        break
                else:
                    intervals.append(
                        tuple(sorted(((left - a[axis]) / delta, (right - a[axis]) / delta)))
                    )
            if intervals and max(x[0] for x in intervals) < min(x[1] for x in intervals) - 1e-9:
                return name
    for index, contacts in turns.items():
        p = points[index]
        for name, low, high in obstacles:
            if name in contacts or low[2] >= p[2] + 1.92 or high[2] <= p[2] - 0.02:
                continue
            distance_squared = sum(
                (low[i] - p[i]) ** 2
                if p[i] < low[i]
                else (p[i] - high[i]) ** 2
                if p[i] > high[i]
                else 0
                for i in (0, 1)
            )
            if distance_squared < ((0.3**2 + 0.6**2) ** 0.5 + 0.02 - 1e-9) ** 2:
                return name
    return None
