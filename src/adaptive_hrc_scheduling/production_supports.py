"""SC01–SC04 finite support layouts and nominal attachment motion geometry.

These are shared geometric data calculations, not execution or audit decisions.
"""

import math
from dataclasses import dataclass

from adaptive_hrc_scheduling.contracts.codec import require
from adaptive_hrc_scheduling.domain import production as m

APPROVAL = "S15-SC-APPROVAL-001"
PROPOSAL_SHA256 = "ffab6862a5d4000103b3bef091081b7d7e732050d4304075782b719670301f43"
ROOTS = ("MEP-RECEIVE", "MEP-STORE", "KIT", "F1-KIT", "J3", "F1")
BEAM_SIZE = (0.06, 0.5, 0.04)
PAIR_H = 0.02
PREPARE_H = 0.02
VERIFY_H = 0.02
SPEED_M_S = 0.10
RACK_POST_X = 1.25


def center(config, root):
    point = next(p.position for p in config.places if p.id == root)
    if root in ("J3", "F1"):
        return (point[0] + (4.5 if root == "J3" else -4.5), point[1], 0.8)
    return point


def parking(config, root):
    x, y, _ = center(config, root)
    # J3 has no broad floor-pack lateral spur; preserve its pedestrian gap.
    parking_y = y if root == "J3" else y + 0.9
    parking_x = 1.35 if root == "J3" else 1.05
    return tuple(
        m.BeamPose(2 * pair + side, (x + sign * parking_x, parking_y, 0.06 + pair * 0.05))
        for pair in range(11)
        for side, sign in enumerate((-1, 1))
    )


def initial(config):
    return tuple(m.SupportState(root, None, parking(config, root)) for root in ROOTS)


def layouts(config):
    """Every non-steel material port belongs to exactly one phase layout."""
    lots = {lot.id: lot for lot in config.lots}
    places = {p.id: p for p in config.places}
    groups = {}
    for op in config.operations:
        ports = [(p.lot_id, p.place_id) for p in (*op.input_places, *op.output_places)]
        if op.entity_id in lots:
            ports += [(op.entity_id, loc) for loc in (op.location, op.target) if loc in places]
        for ident, loc in ports:
            lot, place = lots[ident], places[loc]
            if place.parent not in ROOTS:
                continue
            key = (place.parent, lot.group_id, lot.disposition)
            groups.setdefault(key, {})[loc] = tuple(place.position)
    result = []
    for (root, gid, phase), ports in sorted(groups.items()):
        points = sorted(set(ports.values()), key=lambda p: (p[2], -p[1], p[0]))
        require(len(points) <= 11, "SUPPORT_PAIR_LIMIT")
        result.append(
            m.SupportLayout(
                f"SUPPORT-{root}-{gid}-{phase}",
                root,
                gid,
                tuple(
                    m.SupportContact(loc, points.index(p), p) for loc, p in sorted(ports.items())
                ),
            )
        )
    return tuple(result)


def deployed(config, layout):
    poses = list(parking(config, layout.root))
    for contact in layout.contacts:
        x, y, z = contact.position
        for side, sign in enumerate((-1, 1)):
            index = 2 * contact.pair_index + side
            poses[index] = m.BeamPose(index, (x + sign * 0.45, y, z - 0.02))
    return tuple(poses)


def pair_count(layout):
    return len({c.pair_index for c in layout.contacts}) if layout else 0


def equivalent(left, right):
    if left is None or right is None:
        return left is right
    return left.root == right.root and {(c.pair_index, c.position) for c in left.contacts} == {
        (c.pair_index, c.position) for c in right.contacts
    }


def for_port(config, lot_id, location):
    lot = next((lot for lot in config.lots if lot.id == lot_id), None)
    if lot is None:
        return None
    return next(
        (
            layout
            for layout in config.support_layouts
            if layout.group_id == lot.group_id
            and any(c.place_id == location for c in layout.contacts)
        ),
        None,
    )


def change_operation(config, layout, product_id, ident):
    return m.Operation(
        ident,
        product_id,
        ident,
        "SUPPORT_CHANGE",
        "SETUP",
        (),
        (m.Role("P1", "SC-SUPPORT"), m.Role("E1", "SC-SUPPORT")),
        tuple(m.PersonPosition(p, f"CONTROL-SUPPORT-{layout.root}-{p}") for p in ("P1", "E1")),
        (),
        layout.root,
        None,
        None,
        None,
        (),
        (),
        0,
        0,
        0,
        ("SC-SUPPORT",),
        (),
        None,
        None,
        None,
        support_layout_id=layout.id,
    )


@dataclass(frozen=True)
class PairMotion:
    pair_index: int
    start_h: float
    end_h: float
    paths: tuple[tuple[tuple[float, ...], ...], ...]


def movements(config, old, new):
    """Move existing bars through an empty rack; nothing is created or hidden."""
    require(old is None or old.root == new.root, "SUPPORT_ROOT_CHANGED")
    if equivalent(old, new):
        return ()
    x, y, _ = center(config, new.root)
    park = parking(config, new.root)
    actions = []
    elapsed = PREPARE_H
    for layout, removing in ((old, True), (new, False)):
        if layout is None:
            continue
        height_limit = (
            2.45
            if (
                config.support_height_approval_id == "S15-SH-APPROVAL-001"
                and next(g.activity_code for g in config.groups if g.id == layout.group_id)
                == "LINING"
            )
            else 2.4
        )
        current = deployed(config, layout)
        indices = sorted(
            {c.pair_index for c in layout.contacts},
            key=lambda i: current[2 * i].position[2],
            reverse=removing,
        )
        for pair in indices:
            paths = []
            for side, sign in enumerate((-1, 1)):
                index = 2 * pair + side
                source, target = park[index].position, current[index].position
                outside = x + sign * 1.45
                # Deployment ascends and retrieval descends: the remaining
                # installed bars are below this pair. Use their bounded local
                # clearance height, keeping the approved speed/time budget.
                travel_height = (
                    2.4 if new.root == "J3" else min(height_limit, max(0.65, target[2] + 0.06))
                )
                # Rear storage is inside the retained trestle line. First move
                # forward below the material deck, then around the trestle;
                # a direct lateral pull would pass through that real post.
                turn_y = source[1] if new.root == "J3" else y + 0.2
                points = (
                    source,
                    (source[0], turn_y, source[2]),
                    (outside, turn_y, source[2]),
                    (outside, turn_y, travel_height),
                    (outside, target[1], travel_height),
                    (target[0], target[1], travel_height),
                    target,
                )
                points = tuple(p for i, p in enumerate(points) if i == 0 or p != points[i - 1])
                if removing:
                    points = tuple(reversed(points))
                require(
                    all(
                        abs(p[0] - x) + BEAM_SIZE[0] / 2 <= 1.5 + 1e-9
                        and abs(p[1] - y) + BEAM_SIZE[1] / 2 <= 1.2 + 1e-9
                        and 0 <= p[2] - BEAM_SIZE[2] / 2
                        and p[2] <= height_limit + 1e-9
                        for p in points
                    ),
                    "SUPPORT_MOTION_BOUND",
                )
                distance = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
                require(distance / SPEED_M_S <= PAIR_H * 3600 + 1e-9, "SUPPORT_PAIR_TIME_LIMIT")
                paths.append(points)
            actions.append(PairMotion(pair, elapsed, elapsed + PAIR_H, tuple(paths)))
            elapsed += PAIR_H
    return tuple(actions)


def duration(config, old, new):
    steps = movements(config, old, new)
    return steps[-1].end_h + VERIFY_H if steps else 0


def sample(config, old, new, elapsed_h):
    positions = list(deployed(config, old) if old else parking(config, new.root))
    for move in movements(config, old, new):
        if elapsed_h < move.start_h:
            break
        for side, points in enumerate(move.paths):
            length = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
            travel = min(length, max(0, elapsed_h - move.start_h) * 3600 * SPEED_M_S)
            point = points[-1]
            for a, b in zip(points, points[1:]):
                segment = math.dist(a, b)
                if travel <= segment:
                    ratio = travel / segment if segment else 1
                    point = tuple(v + ratio * (w - v) for v, w in zip(a, b))
                    break
                travel -= segment
            index = 2 * move.pair_index + side
            positions[index] = m.BeamPose(index, point)
    return tuple(positions)
