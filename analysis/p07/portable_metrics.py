"""Source-identical S21 arithmetic extracted for standalone P07 distribution.

Original functions and source identity: see portable_metrics_origin.json.
"""

import math
from collections import defaultdict

from adapters import require


def actual_arc(route, fraction):
    points = route["points"]
    segments = []
    for a, b in zip(points, points[1:]):
        delta = [b[k] - a[k] for k in ("x", "y", "z")]
        cost = (abs(delta[0]) + abs(delta[1])) / route["speed_m_s"] + abs(delta[2]) / route[
            "vertical_speed_m_s"
        ]
        segments.append((cost, math.sqrt(sum(x * x for x in delta))))
    remaining = max(0, min(1, fraction)) * sum(cost for cost, _ in segments)
    distance = 0.0
    for cost, length in segments:
        if cost:
            distance += length * min(1, max(0, remaining / cost))
            remaining -= cost
    return distance


def occupancy(events, end_h):
    """Integrate by clock; retain every actual revision when taking peaks."""
    started = set()
    previous_time = 0.0
    levels = {"internal_finished": 0, "wip": 0}
    areas = {k: 0.0 for k in levels}
    peaks = {k: 0 for k in levels}
    series = {k: [[0, 0]] for k in levels}
    for event in events:
        time = event["occurred_sim_h"]
        require(previous_time <= time <= end_h, "OCCUPANCY_EVENT_CLOCK")
        for key in levels:
            areas[key] += levels[key] * (time - previous_time)
        c = event["command"]
        if event["kind"] == "STARTED" and c and not c["service"]:
            started.add(c["product_id"])
        products = event["state"]["products"]
        current = dict(
            internal_finished=sum(
                p["ready_h"] is not None and p["received_h"] is None for p in products
            ),
            wip=sum(p["product_id"] in started and p["ready_h"] is None for p in products),
        )
        for key, value in current.items():
            peaks[key] = max(peaks[key], value)
            if value != levels[key]:
                series[key].append([time, value])
            levels[key] = value
        previous_time = time
    return {
        key: dict(
            area_product_h=areas[key] + levels[key] * (end_h - previous_time),
            peak_products=peaks[key],
            series=series[key] + [[end_h, levels[key]]],
            peak_rule="MAX_ACTUAL_EVENT_REVISION_STATE_INCLUDING_ZERO_DURATION_OCCUPANCY",
        )
        for key in levels
    }


def transport(config, events):
    operations = {o["id"]: o for o in config["operations"]}
    routes = {r["id"]: r for r in config["routes"]}
    commands = {}
    progress = defaultdict(float)
    for event in events:
        c = event["command"]
        if c and event["kind"] == "STARTED":
            op = c["service"]["operation"] if c["service"] else operations[c["operation_id"]]
            route = c["service"]["route"] if c["service"] else routes.get(op["route_id"])
            if route:
                commands[c["id"]] = (c, op, route)
        if c and event["kind"] == "COMPLETED":
            progress[c["id"]] = 1.0
        rb = event["readback"]
        if rb:
            progress[rb["command_id"]] = max(progress[rb["command_id"]], rb["progress"])

    def root(key):
        seen = set()
        while commands[key][0]["resume_of"]:
            require(key not in seen, "TRANSPORT_RESUME_CYCLE")
            seen.add(key)
            key = commands[key][0]["resume_of"]
            require(key in commands, "TRANSPORT_MISSING_RESUME_SOURCE")
        return key

    groups = {}
    for key, (_, op, route) in commands.items():
        base = root(key)
        prior = groups.get(base)
        require(
            prior is None or prior[1] == op and prior[2] == route, "TRANSPORT_RESUME_ROUTE_CHANGED"
        )
        groups[base] = (max(progress[key], prior[0] if prior else 0), op, route)
    total = empty = walk = 0.0
    rows = []
    for key, (fraction, op, route) in groups.items():
        distance = actual_arc(route, fraction)
        walking = op["action"] == "WALK"
        is_empty = op["action"] == "EMPTY_RETURN"
        if walking:
            walk += distance
        else:
            total += distance
            if is_empty:
                empty += distance
        rows.append(
            dict(
                root_command_id=key,
                action=op["action"],
                progress=fraction,
                actual_m=distance,
                category="WALK" if walking else "EMPTY_RETURN" if is_empty else "LOADED_OR_TOOL",
            )
        )
    return dict(
        total_m=total,
        empty_m=empty,
        loaded_or_tool_m=total - empty,
        walk_m=walk,
        all_routed_m=total + walk,
        empty_ratio=empty / total if total else None,
        rule="ACTUAL_TIME_WEIGHTED_ROUTE_PROGRESS_TO_ARCLENGTH_RESUME_CHAIN_DEDUPLICATED",
        empty_rule="ACTION_EMPTY_RETURN; WALK_REPORTED_SEPARATELY",
        commands=len(groups),
        chains=rows,
        measurement_version="S21-TRANSPORT-ANALYSIS-r1",
    )


def disturbance(metric):
    scenario = metric["scenario"]
    worlds = metric["actual_world_events"]
    if scenario.get("loaded_failure"):
        observed = any(e["kind"] == "FAILURE" for e in worlds)
        flag = metric["failure_triggered"]
        return dict(
            kind="LOADED_FAILURE",
            assignment_applied=observed,
            triggered=observed if observed == flag else None,
            status="CONFIRMED_TRIGGERED"
            if observed and flag
            else "NOT_TRIGGERED"
            if not observed and not flag
            else "UNKNOWN_METADATA_MISMATCH",
            rule="ACTUAL_LOADED_FAILURE_FLAG_AND_WORLD_FAILURE_AGREE",
        )
    if scenario.get("delayed_lot"):
        lot, bound = scenario["delayed_lot"], scenario["arrival_after_h"]
        applied = any(
            e["kind"] == "ARRIVAL" and e["entity_id"] == lot and e["time_h"] >= bound
            for e in worlds
        )
        proven = any(
            i["start_h"] < bound
            and min(i["end_h"], bound) > i["start_h"]
            and i["reason"].startswith("S18_SHIELD:")
            and lot in i["reason"]
            and i["category"] == "MATERIAL"
            for i in metric["waiting"]["intervals"]
        )
        return dict(
            kind="LATE_MATERIAL",
            assignment_applied=applied,
            triggered=True if proven else None,
            status="CONFIRMED_TRIGGERED" if proven else "UNKNOWN_WAIT_ATTRIBUTION",
            rule="DELAYED_ARRIVAL_FACT_ALONE_IS_NOT_PROOF_OF_ACTUAL_MATERIAL_WAIT",
        )
    if scenario.get("receive_after_h"):
        bound = scenario["receive_after_h"]
        active = any(
            p["ready_h"] is not None
            and p["ready_h"] < min(bound, metric["observed_end_h"])
            and (p["received_h"] is None or p["received_h"] >= bound)
            for p in metric["products"]
        )
        applied = any(e["kind"] == "RECEIVE_PERMIT" and e["time_h"] >= bound for e in worlds)
        return dict(
            kind="LATE_RECEIPT",
            assignment_applied=applied,
            triggered=active,
            status="CONFIRMED_TRIGGERED" if active else "NOT_TRIGGERED",
            rule="POSITIVE_ACTUAL_READY_WITHOUT_RECEIPT_INTERVAL_BEFORE_PERMISSION_GATE_NOT_EXCLUSIVE_CAUSAL_ATTRIBUTION",
        )
    return dict(
        kind="NORMAL",
        assignment_applied=False,
        triggered=False,
        status="NORMAL",
        rule="NO_CHALLENGE",
    )
