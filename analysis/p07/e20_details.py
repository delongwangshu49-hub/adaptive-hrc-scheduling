"""Fill named E20 timing fields from the original saved run, without replay."""

import gzip
import json
import sys

import ijson
from adapters import product_metrics, require
from load import ROOT, csv_write, pin, read, write

sys.path.insert(0, str(ROOT / "src"))
from adaptive_hrc_scheduling.contracts.codec import as_data
from adaptive_hrc_scheduling.contracts.production import decode, digest
from adaptive_hrc_scheduling.domain.production import Configuration
from adaptive_hrc_scheduling.dynamic_workforce import WorkforceHistory

BASE = (
    ROOT
    / ".local/p052-execution-20261025-r1/kit-r14/runs/P051-E20-866d7cd0e9594603b92f6463dc5bb0a4"
)


def field(path, name):
    with path.open("rb") as f:
        return next(ijson.items(f, name, use_float=True))


def build():
    prior = read(ROOT / "results/p07/e20.json")
    session = BASE / "session/session-state.json"
    source_pin = pin(session)
    require(
        source_pin["sha256"] == prior["r14_final"]["session_state_sha256"],
        "E20_ORIGINAL_SAVED_HASH",
    )
    # Existing small chain indexes contain APPLIED receipts, but not every
    # ACCEPTED timestamp. These two targeted streaming field reads fill that
    # reporting gap; no full session object or lifecycle audit is constructed.
    receipts = field(session, "receipts")
    requests = field(session, "requests")
    generations = field(session, "generations")
    initial = decode(Configuration, read(BASE / "session/configuration.json"))
    current = WorkforceHistory(initial, generations).current
    require(digest(current) == generations[-1]["config_sha256"], "E20_MATERIALIZED_CATALOG")
    cfg = as_data(current)
    history = read(BASE / "session/full-schedule-state.json")
    plan_rows = []
    first_planned = {}
    source_pins = [
        source_pin,
        pin(BASE / "session/configuration.json"),
        pin(BASE / "session/full-schedule-state.json"),
    ]
    for h in history["history"]:
        products = []
        if h["status"] == "ADOPTED":
            pp = BASE / "session/full-schedules" / f"{h['plan_sha256']}.json"
            rawpin = pin(pp)
            require(rawpin["sha256"] == h["plan_sha256"], "E20_PLAN_ARTIFACT_HASH")
            source_pins.append(rawpin)
            with pp.open("rb") as f:
                for iv in ijson.items(f, "intervals.item", use_float=True):
                    pid = iv["product_id"]
                    products.append(pid)
                    first_planned.setdefault(pid, h["at_h"])
        plan_rows.append(
            dict(
                run_id=prior["r14_final"]["final"]["run_id"],
                at_h=h["at_h"],
                status=h["status"],
                version=h.get("version"),
                reason=h["reason"],
                predicted_finish_h=h.get("chosen_h"),
                product_ids=sorted(set(products)),
                scope="ADOPTED_HYPOTHETICAL_FULL_PLAN_NOT_ACTUAL_COMPLETION",
            )
        )
    arrivals, first_started, sequence = {}, {}, {}
    ep = BASE / "events.jsonl.gz"
    with gzip.open(ep, "rt", encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            sequence[e["id"]] = e["sequence"]
            w = e.get("world")
            if w and w["kind"] in ("ORDER_ARRIVAL", "ARRIVAL"):
                pid = w.get("product_id")
                if pid:
                    arrivals.setdefault(pid, (e["occurred_sim_h"], e["sequence"], e["id"]))
            c = e.get("command")
            if e["kind"] == "STARTED" and c and not c["service"]:
                first_started.setdefault(c["product_id"], e["occurred_sim_h"])
    first_observed = {}
    dp = BASE / "decisions.jsonl.gz"
    with gzip.open(dp, "rt", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            for pid, (_, seq, _) in arrivals.items():
                if d["event_count"] >= seq:
                    first_observed.setdefault(pid, d["received_h"])
    by_id = {}
    for r in receipts:
        by_id.setdefault(r["request_id"], []).append(r)
    product_rows = product_metrics(
        cfg["products"], prior["products"], prior["r14_final"]["final_sim_h"]
    )
    for row in product_rows:
        req = next(
            (
                r
                for r in requests.values()
                if r["kind"] == "ORDER_CREATE" and r["target_id"] == row["order_id"]
            ),
            None,
        )
        rs = by_id.get(req["request_id"], []) if req else []
        accepted = next((r for r in rs if r["status"] == "ACCEPTED"), None)
        applied = next((r for r in rs if r["status"] == "APPLIED"), None)
        row.update(
            run_id=prior["r14_final"]["final"]["run_id"],
            epoch=0,
            scope="ORIGINAL_R14_REAL_KIT_STOPPED_PREFIX_NOT_ALL_RECEIVED",
            initial_or_new="DYNAMIC_NEW" if req else "INITIAL",
            request_id=req["request_id"] if req else None,
            accepted_sim_h=accepted["sim_h"] if accepted else None,
            accepted_wall_utc=accepted["at_utc"] if accepted else None,
            registration_applied_h=applied.get("actual_applied_sim_h", applied["sim_h"])
            if applied
            else 0,
            actual_arrival_h=arrivals.get(row["product_id"], (None, None, None))[0],
            first_observed_decision_h=first_observed.get(row["product_id"]),
            first_adopted_arrangement_h=first_planned.get(row["product_id"]),
            first_actual_production_h=first_started.get(row["product_id"]),
        )
    timeline = []
    for rid, req in requests.items():
        for r in by_id.get(rid, []):
            timeline.append(
                dict(
                    run_id=req["run_id"],
                    scope="ORIGINAL_R14_SAME_RUN",
                    request_id=rid,
                    kind=req["kind"],
                    target=req["target_id"],
                    phase=r["status"],
                    sim_h=r["sim_h"],
                    actual_applied_sim_h=r.get("actual_applied_sim_h"),
                    event_id=r.get("event_id"),
                    catalog_version=r.get("catalog_version_after"),
                )
            )
    require(
        sum(r["initial_or_new"] == "DYNAMIC_NEW" for r in product_rows) == 3,
        "E20_THREE_NEW_PRODUCTS",
    )
    require(
        all(
            r["accepted_sim_h"] is not None and r["first_adopted_arrangement_h"] is not None
            for r in product_rows
            if r["initial_or_new"] == "DYNAMIC_NEW"
        ),
        "E20_NEW_ORDER_TIMING_COVERAGE",
    )
    require(
        all(
            r["actual_arrival_h"] is not None and r["first_observed_decision_h"] is not None
            for r in product_rows
            if r["initial_or_new"] == "DYNAMIC_NEW"
        ),
        "E20_ARRIVAL_OBSERVATION_COVERAGE",
    )
    write(
        ROOT / "results/p07/e20_order_details.json",
        dict(
            products=product_rows,
            plan_changes=plan_rows,
            timeline=timeline,
            inputs=source_pins + [pin(ep), pin(dp)],
            gap_fill_reason="Existing chain summary lacks ACCEPTED timestamps and per-product first adopted arrangement/actual start; targeted original saved fields and events used",
            status="SOURCE_HASH_BOUND_TIMINGS_EXTRACTED_NO_NEW_EXECUTION",
        ),
    )
    csv_write(ROOT / "results/p07/e20_orders.csv", product_rows)
    csv_write(ROOT / "results/p07/e20_plan_changes.csv", plan_rows)
    csv_write(ROOT / "results/p07/e20_requests.csv", timeline)
    print(
        json.dumps(
            dict(
                status="E20_DETAILS_EXTRACTED",
                products=len(product_rows),
                plan_attempts=len(plan_rows),
                receipt_rows=len(timeline),
            )
        )
    )


if __name__ == "__main__":
    build()
