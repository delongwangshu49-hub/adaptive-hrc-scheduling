"""Reconstruct sparse capacity measurements and WIP admission from saved states.

No Session, backend, planner or executor predicates are used. Measurements are
sparse; physical capacity and actual ingress/dispatch are checked at every event.
"""

from adaptive_hrc_scheduling.control.production_decisions import initial_visible_state


def verify_capacity(spec, saved, history, snapshot, check):
    cap, events = spec["capacity"], snapshot.events
    launch = saved["launch_event_count"]
    check(type(launch) is int and 0 <= launch <= len(events), "CAPACITY_LAUNCH")
    initial = initial_visible_state(history.initial)
    launch_state = events[launch - 1].state if launch else initial
    products = {p.id: p for p in history.initial.products}
    active = set(
        sorted(
            (p.product_id for p in launch_state.products if p.released),
            key=lambda pid: (products[pid].due_h, pid),
        )[: cap["max_wip_products"]]
    )
    rows = saved["capacity_events"]
    check(type(rows) is list and bool(rows), "CAPACITY_HISTORY_REQUIRED")
    grouped, previous = {}, launch
    for i, row in enumerate(rows):
        n = row["event_count"]
        check(type(n) is int and previous <= n <= len(events), f"CAPACITY_EVENT_BOUNDARY:{i}")
        check(
            set(row)
            == {"counts", "event_count", "sim_h", "status"}
            | ({"product_id"} if row["status"] == "WIP_ADMITTED" else set()),
            f"CAPACITY_FIELDS:{i}",
        )
        grouped.setdefault(n, []).append((i, row))
        previous = n
    generation_ends = {
        g["before_event_count"] + 1 + len(g["product_ids"])
        for g in history.generations
        if not g.get("workforce_kind") and not g.get("order_update")
    }
    view = history.initial
    final_counts = None
    for n in range(launch, len(events) + 1):
        if n and events[n - 1].id in history.by_event:
            generation = history.by_event[events[n - 1].id]
            prior = events[n - 2].state if n > 1 else initial
            prior_open = {
                p.product_id for p in prior.products if not p.cancelled and p.received_h is None
            }
            quantity = (
                0 if generation.get("order_update") else len(generation.get("product_ids", []))
            )
            check(
                len(prior.products) + quantity <= cap["max_lifetime_products"]
                and len(prior_open) + quantity <= cap["max_open_products"]
                and len(prior_open - active) + quantity <= cap["max_queued_products"],
                f"CREATE_CAPACITY_ADMISSION:{n}",
            )
            view = history.views[generation["config_sha256"]]
        state = events[n - 1].state if n else initial
        positions = {p.id: p.location for p in state.positions}
        mass = {x.entity_id: x.installed_t for x in state.masses}
        mass.update({x.id: x.available for x in state.lots})
        for r in state.reservations:
            mass[r.lot_id] += r.quantity
        loads = (*view.lots, *view.entities)
        physical = {
            x.product_id
            for x in loads
            if mass[x.id] > 1e-9
            and positions[x.id]
            not in (
                "SUPPLIER",
                "UNPRODUCED",
                "UNFABRICATED",
                "UNASSEMBLED",
                "EXTERNAL",
                "INCORPORATED",
            )
        }
        uncleared = {
            x.product_id
            for x in loads
            if mass[x.id] > 1e-9
            and positions[x.id] not in ("EXTERNAL", "SUPPLIER", "UNPRODUCED", "INCORPORATED")
        } | {r.command.product_id for r in state.running}
        states = {p.product_id: p for p in state.products}
        open_ids = {pid for pid, p in states.items() if not p.cancelled and p.received_h is None}
        definitions = {p.id: p for p in view.products}

        def counts():
            return dict(
                count_registered=len(states),
                count_open=len(open_ids),
                count_queued=len(open_ids - active),
                count_instantiated=len(states),
                count_space_reserved=len(active),
                count_wip=len(physical),
                count_scene_entities=len(loads),
            )

        def eligible():
            return sorted(
                (
                    pid
                    for pid, p in states.items()
                    if p.released and not p.cancelled and p.received_h is None and pid not in active
                ),
                key=lambda pid: (
                    history.priorities.get(pid) != "URGENT",
                    definitions[pid].due_h,
                    pid,
                ),
            )

        # A row describes the state after its event_count. It cannot authorize
        # ingress or a STARTED event that has already happened at that boundary.
        if n > launch:
            event = events[n - 1]
            if event.kind == "STARTED":
                pid = event.command.product_id
                check(pid in active or states[pid].cancelled, "WIP_ACTUAL_DISPATCH:" + event.id)
            if event.world and event.world.kind == "ARRIVAL":
                check(event.world.product_id in active, "WIP_ACTUAL_INGRESS:" + event.id)
        at_boundary = grouped.get(n, ())
        if at_boundary:
            active.difference_update(
                pid
                for pid, p in states.items()
                if p.received_h is not None or p.cancelled and pid not in uncleared
            )
        for i, row in at_boundary:
            check(row["sim_h"] == state.time_h, f"CAPACITY_CLOCK:{i}")
            if row["status"] == "WIP_ADMITTED":
                candidates = eligible()
                check(
                    len(active) < cap["max_wip_products"]
                    and bool(candidates)
                    and row["product_id"] == candidates[0],
                    f"WIP_ADMISSION:{i}",
                )
                active.add(row["product_id"])
            else:
                check(
                    row["status"] == ("WAITING_SPACE" if open_ids - active else "CAPACITY"),
                    f"CAPACITY_STATUS:{i}",
                )
            expected = counts()
            check(
                type(row["counts"]) is dict
                and set(row["counts"]) == set(expected)
                and all(type(v) is int and v >= 0 for v in row["counts"].values())
                and row["counts"] == expected,
                f"CAPACITY_RECONSTRUCTED:{i}",
            )
        if at_boundary:
            check(
                not eligible() or len(active) == cap["max_wip_products"],
                f"WIP_ADMISSION_COVERAGE:{n}",
            )
        if n in generation_ends:
            check(bool(at_boundary), f"GENERATION_CAPACITY_COVERAGE:{n}")
        expected = counts()
        # Registration can transiently precede the batch's WIP admission.
        check(
            expected["count_registered"] <= cap["max_lifetime_products"]
            and expected["count_open"] <= cap["max_open_products"]
            and expected["count_wip"] <= cap["max_wip_products"]
            and expected["count_space_reserved"] <= cap["max_wip_products"],
            f"CAPACITY_LIMITS:{n}",
        )
        check(physical <= active, f"PHYSICAL_WIP_ADMISSION:{n}")
        if at_boundary:
            check(expected["count_queued"] <= cap["max_queued_products"], f"QUEUE_LIMIT:{n}")
        final_counts = expected
    check(
        type(saved["active_products"]) is list and saved["active_products"] == sorted(active),
        "FINAL_ACTIVE_PRODUCTS",
    )
    if saved["dynamic_format"] == "P042-DYNAMIC-2":
        check(rows[-1]["counts"] == final_counts, "FINAL_CAPACITY_CHECKPOINT")
    return final_counts
