"""Independent P07 numerical/provenance gates for the offline deliverables."""

from adapters import require


def validate_identity(cache, computed, entry):
    require(
        computed["summary"]["run_id"] == cache["run_id"]
        and computed["summary"]["epoch"] == cache["epoch"],
        "COMPUTED_RUN_EPOCH",
    )
    require(
        computed["summary"]["source_family"] == entry["source_family"], "COMPARISON_SOURCE_FAMILY"
    )
    for key in ("analysis", "independent", "configuration", "events"):
        require(cache["provenance"][key] == entry[key], "CACHE_SOURCE_PIN:" + key)
    require(
        cache["provenance"]["source"]["sha256"] == entry["source"]["expected_sha256"],
        "RAW_SOURCE_PIN",
    )
    require(computed["summary"]["evaluation_window_h"] == 720, "FIXED_COMPARISON_WINDOW")


def independent_occupancy(cache):
    # Explicit event-level vectors: peaks before same-time states collapse,
    # rectangle integration only between subsequent event times.
    started = set()
    points = []
    for e in cache["events"]:
        c = cache["commands"].get(e["command_id"])
        if e["kind"] == "STARTED" and c and c["service"] is None:
            started.add(c["product_id"])
        p = e["state"]["products"]
        points.append(
            (
                e["occurred_sim_h"],
                sum(x["ready_h"] is not None and x["received_h"] is None for x in p),
                len([x for x in p if x["product_id"] in started and x["ready_h"] is None]),
            )
        )
    end = cache["final_state"]["time_h"]
    out = {}
    for name, column in [("internal_finished", 1), ("wip", 2)]:
        area = sum(a[column] * (b[0] - a[0]) for a, b in zip(points, points[1:]))
        area += points[-1][column] * (end - points[-1][0])
        out[name] = dict(area=area, peak=max(x[column] for x in points))
    return out


def main():
    from validation_engine import main as validate_all

    validate_all()


if __name__ == "__main__":
    main()
