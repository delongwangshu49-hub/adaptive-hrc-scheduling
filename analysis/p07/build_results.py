"""Compute complete finite-design results from the source-bound P07 cache."""

import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from adapters import hours, pair_values, people_metrics, product_metrics
from load import ROOT, UNITS, csv_write, pin, read, write
from portable_metrics import occupancy, transport

TIME_FIELDS = (
    "cycle_seconds",
    "decision_seconds",
    "construction_seconds",
    "initial_seconds",
    "search_seconds",
    "repair_seconds",
    "verification_seconds",
    "candidate_gate_seconds",
    "candidate_acceptance_seconds",
    "fallback_seconds",
    "feedback_verification_seconds",
)


def cost_metrics(cache):
    rows = cache["journal"]
    result = dict(
        unit=cache["unit"],
        run_id=cache["run_id"],
        original_runtime_elapsed_s=cache["original_runtime_elapsed_s"],
        cpu_time_s=None,
        peak_memory_bytes=None,
        unmeasured_status="UNKNOWN_NOT_RECORDED_NO_TIMING_RERUN",
        journal_status=cache["journal_source"]["status"],
        nested_timing_policy="FIELDS_ARE_RECORDED_DIAGNOSTICS_NOT_ADDITIVE_COST_COMPONENTS",
    )
    if not rows:
        return dict(
            result,
            search_calls=0,
            cached_plan_dispatches=0,
            budget_overrun_rows=0,
            fixed_mode_no_online_policy=True,
            **{k: None for k in TIME_FIELDS},
        )
    for field in TIME_FIELDS:
        values = [r[field] for r in rows if r.get(field) is not None]
        flattened = [x for v in values for x in (v if isinstance(v, list) else [v])]
        result[field] = sum(flattened) if values else None
    result.update(
        search_calls=sum(bool(r.get("search_call")) for r in rows),
        recorded_decision_rows=len(rows),
        candidate_acceptance_timed_checks=sum(
            len(r.get("candidate_acceptance_seconds") or []) for r in rows
        ),
        candidate_acceptance_count_semantics="TIMED_CHECKS_NOT_ACTUAL_PLAN_ADOPTIONS",
        cached_plan_dispatches=sum(
            bool(r.get("cache_sha256")) and r.get("receipt_kind") == "STARTED" for r in rows
        ),
        cache_invalidations=sum(bool(r.get("cache_invalidated")) for r in rows),
        fallback_dispatches=sum(
            r.get("selected_source") == "RULE" and r.get("receipt_kind") == "STARTED" for r in rows
        ),
        selection_sources=dict(Counter(str(r.get("selected_source")) for r in rows)),
        budget_overrun_rows=sum(
            bool(r.get("budget_exceeded") or r.get("cycle_budget_exceeded")) for r in rows
        ),
        final_used_budget_s=max(
            (r["total_budget"]["used_s"] for r in rows if r.get("total_budget")), default=None
        ),
        maximum_overrun_s=max(
            (r["total_budget"]["overrun_s"] for r in rows if r.get("total_budget")), default=None
        ),
    )
    return result


def compute(cache, policy=None):
    unit = cache["unit"]
    analysis, config, state = cache["analysis"], cache["configuration"], cache["final_state"]
    end = state["time_h"]
    events = [
        dict(e, command=cache["commands"][e["command_id"]] if e["command_id"] else None)
        for e in cache["events"]
    ]
    rates = (
        {r["template_id"]: r["rate_per_h"] for r in policy["cost"]["rates"]}
        if policy and policy.get("cost")
        else None
    )
    people, phases, human_intervals = people_metrics(config, state, rates=rates)
    products = product_metrics(config["products"], state["products"], end)
    for p in products:
        started = [
            e["occurred_sim_h"]
            for e in events
            if e["kind"] == "STARTED"
            and e["command"]
            and e["command"]["product_id"] == p["product_id"]
            and not e["command"]["service"]
        ]
        scheduled = [
            r["time_h"]
            for r in cache["journal"]
            if r.get("selected_proposal")
            and r["selected_proposal"].get("product") == p["product_id"]
        ]
        p.update(
            first_actual_production_h=min(started) if started else None,
            first_recorded_proposal_h=min(scheduled) if scheduled else None,
            proposal_is_not_adoption=True,
            first_registration_h=next(
                (
                    g["sim_h"]
                    for g in cache["generations"]
                    if p["product_id"] in g.get("product_ids", [])
                ),
                0,
            ),
        )
    occ = occupancy(events, end)
    routed = transport(config, events)
    resources = []
    grouped = defaultdict(list)
    for r in cache["resource_intervals"]:
        grouped[(r["resource_id"], r["kind"])].append([r["start_h"], r["end_h"]])
    for (rid, kind), intervals in grouped.items():
        resources.append(
            dict(
                resource_id=rid,
                kind=kind,
                union_h=hours(intervals),
                metric_unit="h",
                denominator_h=end,
            )
        )
    common = analysis["common_horizon"]
    common_rows = {r["person_id"]: r for r in common.get("humans", [])}
    for p in people:
        ch = common_rows.get(p["person_id"])
        p.update(
            common_window_end_h=common["end_h"],
            common_window_status=common["status"],
            common_exposure_F_h=ch["exposure"] if ch else None,
            common_peak_f=ch["peak"] if ch else None,
        )
    released = [p for p in products if p["released"]]
    uncancelled = [p for p in released if not p["cancelled"]]
    summary = dict(
        unit=unit,
        scenario=cache["scenario"],
        method=cache["method"],
        run_id=cache["run_id"],
        epoch=cache["epoch"],
        source_family=cache["source_family"],
        input_configuration_sha256=cache["provenance"]["analysis"].get(
            "configuration_sha256", analysis["configuration_sha256"]
        ),
        evaluation_window_h=720,
        actual_lifecycle_end_h=end,
        lifecycle_sum_E=sum(p["exposure_F_h"] for p in people),
        lifecycle_max_E=max(p["exposure_F_h"] for p in people),
        peak_F=max(p["peak_f"] for p in people),
        common_window_sum_E=common.get("total_exposure"),
        common_window_max_E=common.get("max_exposure"),
        common_window_status=common["status"],
        people_count=len(people),
        presence_person_h=sum(p["presence_h"] for p in people),
        available_person_h=sum(p["availability_h"] for p in people),
        registered_products=len(products),
        released_products=len(released),
        noncancelled_released_products=len(uncancelled),
        cancelled_products=sum(p["cancelled"] for p in released),
        received_products=sum(p["received_h"] is not None for p in released),
        ready_products=sum(p["ready_h"] is not None and not p["cancelled"] for p in released),
        on_time_received_fraction_all_released=sum(p["on_time_received"] for p in released)
        / len(released)
        if released
        else None,
        on_time_ready_fraction_all_released=sum(p["on_time_ready"] for p in released)
        / len(released)
        if released
        else None,
        on_time_received_fraction_noncancelled=sum(p["on_time_received"] for p in uncancelled)
        / len(uncancelled)
        if uncancelled
        else None,
        last_received_h=max(
            (p["received_h"] for p in released if p["received_h"] is not None), default=None
        ),
        internal_finished_peak=occ["internal_finished"]["peak_products"],
        internal_finished_area_product_h=occ["internal_finished"]["area_product_h"],
        wip_peak=occ["wip"]["peak_products"],
        wip_area_product_h=occ["wip"]["area_product_h"],
        transport_m=routed["total_m"],
        empty_transport_m=routed["empty_m"],
        walk_m=routed["walk_m"],
        empty_transport_ratio=routed["empty_ratio"],
        original_actual_exit_code=cache["original_exit"]["exit_code"],
        scope="ORIGINAL_FIXED_PROTOCOL_EXECUTION_PLUS_NEW_OFFLINE_ANALYSIS",
        status="METRICS_COMPUTED_VALIDATION_RECORDED_SEPARATELY",
    )
    for key, expected in [
        ("received_products", "received_count"),
        ("ready_products", "ready_count"),
        ("cancelled_products", "cancelled_count"),
    ]:
        if summary[key] != analysis["actual_whole_metrics"][expected]:
            raise ValueError("ORIGINAL_METRIC_MISMATCH:" + key + ":" + unit)
    if not math.isclose(
        summary["lifecycle_sum_E"], analysis["actual_whole_metrics"]["total_exposure"], abs_tol=1e-6
    ):
        raise ValueError("ORIGINAL_EXPOSURE_MISMATCH:" + unit)
    milestones = list(cache["milestones"])
    for e in events:
        c = e["command"]
        if c and c["resume_of"] and e["kind"] in ("STARTED", "COMPLETED"):
            milestones.append(
                dict(
                    event_id=e["id"],
                    event_sequence=e["sequence"],
                    time_h=e["occurred_sim_h"],
                    kind="RESUME_STARTED" if e["kind"] == "STARTED" else "RESUME_COMPLETED",
                    entity_id=c["id"],
                    product_id=c["product_id"],
                    resume_of=c["resume_of"],
                )
            )
    cancelled = {p["product_id"] for p in products if p["cancelled"]}
    for pid in cancelled:
        tail = [
            e
            for e in events
            if e["kind"] == "COMPLETED" and e["command"] and e["command"]["product_id"] == pid
        ]
        if tail:
            e = tail[-1]
            milestones.append(
                dict(
                    event_id=e["id"],
                    event_sequence=e["sequence"],
                    time_h=e["occurred_sim_h"],
                    kind="LAST_RECORDED_CANCELLED_PRODUCT_COMPLETION",
                    product_id=pid,
                )
            )
    summary["presence_labour_cost"] = (
        sum(p["presence_labour_cost"] for p in people) if rates else None
    )
    summary["labour_currency"] = policy["cost"]["currency"] if rates else None
    orders = []
    for order_id in sorted({p["order_id"] for p in products}):
        members = [p for p in products if p["order_id"] == order_id]
        active = [p for p in members if not p["cancelled"]]
        orders.append(
            dict(
                order_id=order_id,
                product_count=len(members),
                released_products=sum(p["released"] for p in members),
                cancelled_products=sum(p["cancelled"] for p in members),
                received_products=sum(p["received_h"] is not None for p in members),
                all_noncancelled_received=bool(active)
                and all(p["received_h"] is not None for p in active),
                last_noncancelled_receipt_h=max(p["received_h"] for p in active)
                if active and all(p["received_h"] is not None for p in active)
                else None,
            )
        )
    return dict(
        summary=summary,
        orders=orders,
        labour_policy=policy,
        device_ids=[d["id"] for d in config["devices"]],
        products=products,
        people=people,
        activity=phases,
        human_intervals=human_intervals,
        resources=resources,
        occupancy=occ,
        transport=routed,
        costs=cost_metrics(cache),
        milestones=milestones,
        stages=analysis["stages"],
        mode_attempts=analysis["mode_attempts"],
        modes=analysis["modes"],
        generations=cache["generations"],
        resource_intervals=cache["resource_intervals"],
        provenance=cache["provenance"],
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cache", type=Path, default=ROOT / "results/p07/cache/runs")
    p.add_argument("--output", type=Path, default=ROOT / "results/p07/r3")
    p.add_argument("--unit", action="append")
    args = p.parse_args()
    result = []
    policies = read(args.cache / "metadata.json")
    for unit in UNITS:
        if args.unit and unit not in args.unit:
            continue
        cache_path = args.cache / f"{unit}.json"
        if not cache_path.exists():
            cache_path = args.cache / f"{unit}.json.gz"
        cache = read(cache_path, limit=180_000_000)
        row = compute(cache, policies[unit])
        row["cache_pin"] = pin(cache_path)
        write(args.output / "computed" / f"{unit}.json", row)
        result.append(row)
        print(
            json.dumps(
                dict(
                    unit=unit,
                    status="COMPUTED",
                    **{
                        k: row["summary"][k]
                        for k in [
                            "received_products",
                            "cancelled_products",
                            "lifecycle_sum_E",
                            "transport_m",
                        ]
                    },
                )
            ),
            flush=True,
        )
    if args.unit:
        return
    summaries = [r["summary"] for r in result]
    write(args.output / "summary.json", summaries)
    csv_write(args.output / "summary.csv", summaries)
    for name in (
        "orders",
        "products",
        "people",
        "activity",
        "resources",
        "milestones",
        "stages",
        "mode_attempts",
    ):
        csv_write(
            args.output / f"{name}.csv",
            [dict(unit=r["summary"]["unit"], **row) for r in result for row in r[name]],
        )
    csv_write(args.output / "costs.csv", [r["costs"] for r in result])
    write(args.output / "costs.json", [r["costs"] for r in result])
    pairs = []
    for metric in (
        "on_time_received_fraction_all_released",
        "on_time_ready_fraction_all_released",
        "last_received_h",
        "common_window_sum_E",
        "common_window_max_E",
        "transport_m",
        "empty_transport_ratio",
        "wip_area_product_h",
        "available_person_h",
    ):
        pairs.extend(pair_values([r for r in summaries if r["scenario"] != "MECHANISM"], metric))
    csv_write(args.output / "pairs.csv", pairs)
    write(args.output / "pairs.json", pairs)
    mechanism = []
    for label, unit in [
        ("M-H-N", "M-H-N"),
        ("M-H-H", "M-H-H"),
        ("M-HR-N", "N-CPU-EDD"),
        ("M-HR-H", "H-CPU-EDD"),
    ]:
        r = next(x for x in result if x["summary"]["unit"] == unit)
        mechanism.append(
            dict(
                mechanism=label,
                original_unit=unit,
                distinct_additional_sample=not label.startswith("M-HR"),
                phase_count=len(r["stages"]),
                branch_labour_h=sum(s["labour_h"] for s in r["stages"]),
                branch_exposure_F_h=sum(s["crew_exposure_F_h"] for s in r["stages"]),
                **{
                    k: r["summary"][k]
                    for k in [
                        "last_received_h",
                        "common_window_sum_E",
                        "common_window_max_E",
                        "peak_F",
                    ]
                },
            )
        )
    csv_write(args.output / "mechanisms.csv", mechanism)
    write(args.output / "mechanisms.json", mechanism)


if __name__ == "__main__":
    main()
