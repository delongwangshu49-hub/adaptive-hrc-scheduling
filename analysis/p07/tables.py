"""Deterministic CSV views of the checked P07 JSON results."""

import csv
import io
import json

from adapters import require
from load import UNITS, csv_write, read


def contents(rows):
    keys = list(dict.fromkeys(k for r in rows for k in r))
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=keys)
    writer.writeheader()
    for r in rows:
        writer.writerow(
            {
                k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                for k, v in r.items()
            }
        )
    return out.getvalue().encode("utf-8")


def rows(data, computed=None, cache_dir=None):
    if computed is None:
        computed = {u: read(data / "computed" / f"{u}.json", 80_000_000) for u in UNITS}
    result = {
        name + ".csv": read(data / (name + ".json"))
        for name in ("summary", "pairs", "costs", "mechanisms")
    }
    for name in (
        "orders",
        "products",
        "people",
        "activity",
        "resources",
        "milestones",
        "stages",
        "mode_attempts",
        "human_intervals",
    ):
        result[name + ".csv"] = [dict(unit=u, **r) for u, c in computed.items() for r in c[name]]
    result["transport.csv"] = [
        dict(unit=u, **{k: v for k, v in c["transport"].items() if k not in ("commands", "chains")})
        for u, c in computed.items()
    ]
    result["transport_chains.csv"] = [
        dict(unit=u, **r) for u, c in computed.items() for r in c["transport"]["chains"]
    ]
    if cache_dir is not None:
        command_rows = []
        for u in UNITS:
            p = cache_dir / f"{u}.json"
            if not p.exists():
                p = p.with_suffix(".json.gz")
            commands = read(p, 180_000_000)["commands"]
            for cid, c in commands.items():
                root = cid
                seen = set()
                while commands[root]["resume_of"]:
                    require(root not in seen, "TABLE_RESUME_CYCLE")
                    seen.add(root)
                    root = commands[root]["resume_of"]
                command_rows.append(
                    dict(
                        unit=u,
                        command_id=cid,
                        root_command_id=root,
                        resume_of=c["resume_of"],
                        product_id=c["product_id"],
                        activity_id=c["activity_id"],
                        operation_id=c["operation_id"],
                        route_id=c["service"]["route"]["id"]
                        if c.get("service") and c["service"].get("route")
                        else None,
                    )
                )
        result["transport_commands.csv"] = command_rows
    dynamic = read(data / "dynamic_people.json", 40_000_000)
    for key, name in [
        ("people", "dynamic_people"),
        ("activity", "dynamic_activity"),
        ("intervals", "dynamic_intervals"),
        ("changes", "dynamic_people_events"),
    ]:
        result[name + ".csv"] = [r for c in dynamic for r in c[key]]
    e20 = read(data / "e20_order_details.json")
    for name, key in [
        ("e20_orders", "products"),
        ("e20_plan_changes", "plan_changes"),
        ("e20_requests", "timeline"),
    ]:
        result[name + ".csv"] = e20[key]
    result["e20_timeline.csv"] = read(data / "e20.json")["timeline"]
    order_rows = []
    for oid in sorted({p["order_id"] for p in e20["products"]}):
        products = [p for p in e20["products"] if p["order_id"] == oid]
        order_rows.append(
            dict(
                order_id=oid,
                run_id=products[0]["run_id"],
                product_ids=[p["product_id"] for p in products],
                registered_products=len(products),
                released_products=sum(p["released"] for p in products),
                received_products=sum(p["received_h"] is not None for p in products),
                incomplete_products=sum(p["incomplete"] for p in products),
                all_received=all(p["received_h"] is not None for p in products),
                observation_end_h=387.7324633333333,
                scope="ORIGINAL_R14_STOPPED_PREFIX",
            )
        )
    result["e20_order_summary.csv"] = order_rows
    failed = read(data / "attempts.json")["full_original_index"]["production_failed_or_censored"]
    result["attempts.csv"] = [
        dict(unit=r["unit"], source_root=r["root"], **r["summary"], **r["exit"], scope=r["scope"])
        for r in failed
    ]
    cancel = read(data / "cancellation.json")
    for key in ("accounts", "lots", "materials"):
        result["cancellation_" + key + ".csv"] = cancel[key]
    for case in ("normal", "dynamic", "kit"):
        view = read(data / "exports" / case / "gantt.json", 40_000_000)
        result[f"exports/{case}/gantt-rows.csv"] = view["rows"]
        for key in ("orders", "people", "devices"):
            values = view[key]
            if isinstance(values, dict):
                values = [
                    dict(id=k, **v) if isinstance(v, dict) else dict(id=k, value=v)
                    for k, v in values.items()
                ]
            result[f"exports/{case}/{key}.csv"] = values
    return result


def build(data, cache_dir):
    for name, values in rows(data, cache_dir=cache_dir).items():
        csv_write(data / name, values)
