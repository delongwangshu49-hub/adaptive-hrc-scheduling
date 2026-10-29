"""Display-only work identities and adjacency from the complete verified prefix."""

from copy import deepcopy

from .colors import assign

PALETTE = ("#C08E77", "#C5AD7A", "#99A67F", "#A59689")


def person_results(events):
    """Display actual person states from verified events, never from admission."""
    results = []
    for event in events:
        world = event.get("world") or {}
        if world.get("kind") not in (
            "PERSON_ARRIVE",
            "PERSON_DEPART",
            "PERSON_ABSENT",
            "PERSON_RETURN",
        ):
            continue
        pid = world["entity_id"]
        flags = event["state"]["failed_resources"]
        state = next(
            (
                name
                for name in ("ABSENT_HOLD", "ABSENT", "DEPARTURE_PENDING", "DEPARTED")
                if "P043." + name + "." + pid in flags
            ),
            "PRESENT",
        )
        results.append(
            dict(
                request_id=world["evidence_id"],
                person_id=pid,
                event_id=event["id"],
                sim_h=event["occurred_sim_h"],
                status=state,
                scope="VERIFIED_EXECUTION_EVENT_PERSON_STATE",
            )
        )
    return results


class WorkColors:
    def __init__(self, run_id, epoch):
        self.identity = run_id, epoch
        self.cache = {}
        self.numbers = {}

    def project(self, view, configuration):
        e = view["envelope"]
        if (e["run_id"], e["epoch"]) != self.identity:
            raise ValueError("COLOR_IDENTITY")
        operations = {x["id"]: x for x in configuration["operations"]}
        rows = deepcopy(view["rows"])
        commands = {r["command_id"]: r for r in rows if r.get("row_kind") == "FACT_PREFIX"}
        works = set()
        spans = []
        for row in rows:
            linked = commands.get(row.get("command_id"), {})
            op = operations.get(row.get("operation_id", linked.get("operation_id")), {})
            product = (
                row.get("product_id", linked.get("product_id", op.get("product_id", ""))) or ""
            )
            activity = row.get("activity_id", linked.get("activity_id", op.get("activity_id", "")))
            if product and "product_id" not in row:
                row["display_product_id"] = product
            if not product or not activity:
                # Occupancy/person intervals retain command/person identity, never
                # acquire a fictional product from their visible row number.
                activity = "service:" + str(
                    row.get("command_id") or row.get("person_id") or row["row_id"]
                )
            key = "/".join(map(str, (*self.identity, product, activity)))
            row["work_key"] = key
            works.add(key)
            resources = set(row.get("equipment", op.get("equipment", [])))
            resources.update(x["person_id"] for x in row.get("roles", []))
            resources.update([row[k] for k in ("resource_id", "person_id") if row.get(k)])
            start = row.get("start_h", row.get("sim_h"))
            end = row.get("end_h", row.get("observed_until_h", row.get("forecast_until_h", start)))
            # Unknown ends are points, never invented durations.
            row["display_end_h"] = end
            row["canonical_lane"] = product or row.get(
                "resource_id", row.get("person_id", "events")
            )
            if start is not None and end is not None:
                spans.append((key, row["canonical_lane"], resources, start, end))
        lanes = {name: n for n, name in enumerate(sorted({s[1] for s in spans}))}
        edges = set()
        buckets = {}
        for entry in spans:
            for resource in entry[2]:
                buckets.setdefault(("resource", resource), []).append(entry)
            index = lanes[entry[1]]
            for adjacent in (index - 1, index):
                buckets.setdefault(("lane", adjacent), []).append(entry)
        for entries in buckets.values():
            active = []
            for entry in sorted(entries, key=lambda x: (x[3], x[4], x[0])):
                active = [x for x in active if x[4] + 1e-9 >= entry[3]]
                for other in active:
                    if entry[0] != other[0]:
                        edges.add(tuple(sorted((entry[0], other[0]))))
                active.append(entry)
        self.cache, collisions = assign(sorted(works), sorted(edges), self.cache)
        conflict_keys = {k for pair in collisions for k in pair}
        for key in sorted(works):
            self.numbers.setdefault(key, "W" + str(len(self.numbers) + 1).zfill(3))
        for row in rows:
            key = row["work_key"]
            row.update(
                color_slot=self.cache[key],
                color=PALETTE[self.cache[key]],
                work_number=self.numbers[key],
                color_collision=key in conflict_keys,
                color_version="P051-EARTH-r1",
            )
        return {**view, "rows": rows, "color_collision_pairs": collisions}
