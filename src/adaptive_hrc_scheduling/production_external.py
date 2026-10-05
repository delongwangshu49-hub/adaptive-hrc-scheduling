"""Declared synthetic boundary transport, separate from internal devices."""


def is_external(op):
    return op.action == "RECEIVE_EXTERNAL" or op.action == "RETURN" and op.target == "EXTERNAL"


def path(config, op):
    start = next(p.position for p in config.places if p.id == op.location)
    loads = (*config.lots, *config.entities)
    obj = next(x for x in loads if x.id == op.entity_id)
    # Separate finite receiver positions keep every departed physical object.
    index = next(i for i, x in enumerate(loads) if x.id == op.entity_id)
    x = (
        64 + 8 * index
        if op.action == "RECEIVE_EXTERNAL"
        else -2 - sum(x.size_m[0] + 0.5 for x in loads[:index]) - obj.size_m[0] / 2
    )
    end = (x, start[1], start[2] if op.action == "RECEIVE_EXTERNAL" else 0.1)
    if op.action == "RECEIVE_EXTERNAL":
        return (start, (*start[:2], 4.1), (x, start[1], 4.1), end)
    boundary = (-2 - obj.size_m[0] / 2, start[1], start[2])
    return (start, boundary, (*boundary[:2], 2.6), (x, start[1], 2.6), end)


def duration(config, op):
    # Existing geometric speeds, preparation and handoff accounting. The
    # external fixture does not acquire a new internal production resource.
    points = path(config, op)
    return (
        config.setup_h
        + config.load_h
        + config.unload_h
        + sum(
            ((abs(b[0] - a[0]) + abs(b[1] - a[1])) / 0.5 + abs(b[2] - a[2]) / 0.2) / 3600
            for a, b in zip(points, points[1:])
        )
    )


def blocker(config, state, op):
    from adaptive_hrc_scheduling.production_navigation import boxes, clear_segment

    obj = next(x for x in (*config.lots, *config.entities) if x.id == op.entity_id)
    obstacles = boxes(config, state, (op.entity_id,))
    points = path(config, op)
    for a, b in zip(points, points[1:]):
        for obstacle in obstacles:
            if not clear_segment(a, b, (obstacle,), obj.size_m, margin=0):
                return obstacle[0]
    return None
