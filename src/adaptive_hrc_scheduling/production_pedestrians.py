"""Finite operator access geometry; no vehicle dimensions or state changes."""

from adaptive_hrc_scheduling.production_geometry import FORK_OPERATOR_DY

FORK_ACCESS_X = 1.5
FORK_ACCESS_Y = -2.5
FORK_CONTACT_PARTS = ("Deck", "Guard", "Controls")


def fork_access(point):
    """The existing standing point and two axis-aligned side access paths."""
    x, y = point[:2]
    operator = (x, y + FORK_OPERATOR_DY, 0.2)
    return tuple(
        (
            operator,
            (x, y + FORK_ACCESS_Y, 0.2),
            (x + side * FORK_ACCESS_X, y + FORK_ACCESS_Y, 0.2),
            (x + side * FORK_ACCESS_X, y + FORK_ACCESS_Y, 0),
        )
        for side in (-1, 1)
    )


def fork_walk_phases(points, point, *, leaving=False, entering=False, tolerance=1e-9):
    """Return verified access segments and conservative quarter-turn locations.

    The full body envelope is retained. Its contact with the deck, rear guard
    and controls is limited to the existing operator access strip; no other
    segment or part is excluded. In particular this cannot cross behind the
    guard, through the mast or through the whole parked vehicle.
    """

    def same(a, b):
        return all(abs(x - y) <= tolerance for x, y in zip(a, b))

    phases, turns = {}, {}
    for path in fork_access(point):
        if len(points) < len(path):
            continue
        if leaving and all(same(a, b) for a, b in zip(points[:4], path)):
            phases.update({0: (FORK_CONTACT_PARTS, 0), 1: (FORK_CONTACT_PARTS, 90), 2: ((), 0)})
            turns.update({1: FORK_CONTACT_PARTS, 2: ()})
        if entering and all(same(a, b) for a, b in zip(points[-4:], reversed(path))):
            start = len(points) - 4
            phases.update(
                {
                    start: ((), 0),
                    start + 1: (FORK_CONTACT_PARTS, 90),
                    start + 2: (FORK_CONTACT_PARTS, 0),
                }
            )
            turns.update({start + 1: (), start + 2: FORK_CONTACT_PARTS})
    return phases, turns


def walk_yaw(points, point, phases):
    """The finite access side-step is the only 90-degree walking pose."""
    for index, (a, b) in enumerate(zip(points, points[1:])):
        if (
            phases.get(index, ((), 0))[1] == 90
            and abs(a[2] - 0.2) < 1e-9
            and abs(b[2] - 0.2) < 1e-9
            and abs(a[1] - b[1]) < 1e-9
            and abs(a[0] - b[0]) > 1e-9
            and abs(point[1] - a[1]) < 1e-9
            and abs(point[2] - a[2]) < 1e-9
            and min(a[0], b[0]) + 1e-9 < point[0] < max(a[0], b[0]) - 1e-9
        ):
            return 90
    return 0
