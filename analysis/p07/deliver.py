"""Build P07 source, requirement and claim indexes from validated measurements."""

import csv
from datetime import datetime, timezone

from load import ROOT, UNITS, csv_write, pin, read, write


def main():
    data = ROOT / "results/p07/r3"
    out = ROOT / "docs/delivery"
    validation = read(data / "validation.json")
    assert validation["status"] == "PASS"
    for item in validation["inputs"] + list(validation["source_code"].values()):
        assert pin(ROOT / item["path"]) == item, "STALE_VALIDATED_INPUT:" + item["path"]
    computed = {u: read(data / "computed" / f"{u}.json", 80_000_000) for u in UNITS}
    dynamic = read(data / "dynamic_people.json", 40_000_000)
    dual = read(data / "exports/manifest.json")
    e20 = read(data / "e20_order_details.json")
    e20_orders = []
    for oid in sorted({p["order_id"] for p in e20["products"]}):
        products = [p for p in e20["products"] if p["order_id"] == oid]
        e20_orders.append(
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
    assert len(e20_orders) == 3 and sum(r["registered_products"] for r in e20_orders) == 4
    csv_write(data / "e20_order_summary.csv", e20_orders)
    requirements = {
        "Q01": (
            "T05;T09;I03;I05",
            "orders.csv;products.csv;e20_orders.csv;e20_requests.csv",
            "Dynamic catalog and actual request/observation/adoption/execution times; order and product counts separate",
        ),
        "Q02": (
            "T05;T09",
            "products.csv;attempts.json;cancellation_accounts.csv;cancellation_lots.csv;cancellation_materials.csv",
            "Cancellation, receipt, right censoring, typed material balances and command-linked sunk resources retained; STOCK is not WIP/J3",
        ),
        "Q03": (
            "T01;T09",
            "resources.csv;summary.csv",
            "Per-revision peaks, time area and resource unions; WAIT causes not uniquely inferred",
        ),
        "Q04": (
            "T01;T04;T09",
            "transport.csv;transport_commands.csv;transport_chains.csv",
            "Actual command/root/resume chain segments; WALK and empty return separate",
        ),
        "Q05": (
            "T03;I06",
            "dynamic_people.csv;dynamic_people_events.csv;dynamic_intervals.csv",
            "All historical IDs, newcomer defined time, return continuity and eligibility",
        ),
        "Q06": (
            "T03;T09;I06",
            "people.csv;activity.csv;dynamic_people.json",
            "Actual lifecycle vs common 720h; recorded presence labour rates only, frozen resource fees separate",
        ),
        "Q07": (
            "T09",
            "summary.csv;pairs.csv",
            "Five within-scenario pairs, nine paired metrics each; no pooled effect or significance inference",
        ),
        "Q08": (
            "T02;T03;T09",
            "mechanisms.csv;stages.csv;mode_attempts.csv",
            "Four mechanism cells, two HR aliases; only 12 distinct research executions",
        ),
        "Q09": (
            "T08;T09",
            "costs.csv",
            "Original timings and actual dispatch source; nested fields not summed; CPU/peak memory unmeasured",
        ),
        "Q10": (
            "T04;T05;T07;T09",
            "milestones.csv;e20_orders.csv",
            "Actual failure/repair/resume and order outcomes; un-frozen 8h catch-up not evaluated",
        ),
        "Q11": (
            "T07;T08;I03;I05;E20",
            "e20_timeline.csv;e20_plan_changes.csv;e20_order_details.json",
            "r14 same-run four products, five attempts and adopted schedules; 1 received / 3 incomplete",
        ),
        "Q12": (
            "T06;T07;I07;E18;E22",
            "exports/manifest.json",
            "Three same-observation domain pairs, original presentation caches; no new native render",
        ),
        "Q13": (
            "T01;T02;T03;T04;T05;T06;T07;T08;T09;I03;I05;I06;I07;E18;E20;E22",
            "p07_source_registry_r3.json;claim_evidence_r3.tsv;feedback_metric_binding_r3.json",
            "Source hashes, windows and scope plus independent portable derived-data replay",
        ),
        "Q14": (
            "G07",
            "p07_completion_r3.json",
            "Local technical exit and exact G07 candidate; preparation authorized, actual publication awaits its own authorization",
        ),
    }
    rows = []
    for unit, c in computed.items():
        s = c["summary"]
        for metric in (
            "received_products",
            "cancelled_products",
            "last_received_h",
            "common_window_sum_E",
            "lifecycle_sum_E",
            "presence_labour_cost",
            "available_person_h",
            "transport_m",
            "internal_finished_peak",
            "wip_area_product_h",
        ):
            rows.append(
                dict(
                    claim_id=f"{unit}:{metric}",
                    requirements="T01;T03;T09",
                    metric=metric,
                    value=s[metric],
                    window="[0,720h] DERIVED_REST_TAIL"
                    if metric.startswith("common_")
                    else f"[0,{s['actual_lifecycle_end_h']}] actual lifecycle",
                    denominator=f"registered={s['registered_products']};released={s['released_products']};noncancelled={s['noncancelled_released_products']};people={s['people_count']}",
                    run_id=s["run_id"],
                    epoch=s["epoch"],
                    source_family=s["source_family"],
                    configuration_sha256=s["input_configuration_sha256"],
                    source_sha256=c["provenance"]["source"]["sha256"],
                    result=f"results/p07/r3/computed/{unit}.json",
                    result_sha256=pin(data / "computed" / f"{unit}.json")["sha256"],
                    script="analysis/p07/build_results.py",
                    figure="figures/p07/r3/manifest.json",
                    status="RECORDED_VALUE"
                    if s[metric] is not None
                    else "UNKNOWN_NO_DECLARED_SOURCE_POLICY",
                    scope=s["scope"],
                )
            )
    for p in read(data / "pairs.json"):
        rows.append(
            dict(
                claim_id=f"PAIR:{p['scenario']}:{p['metric']}",
                requirements="T09",
                **p,
                result="results/p07/r3/pairs.json",
                result_sha256=pin(data / "pairs.json")["sha256"],
                scope="WITHIN_SCENARIO_FIXED_PROTOCOL; NO_SIGNIFICANCE_INFERENCE",
            )
        )
    for c in dynamic:
        for metric in (
            "actual_available_person_h",
            "presence_labour_cost",
            "total_exposure_F_h",
            "max_exposure_F_h",
        ):
            rows.append(
                dict(
                    claim_id=f"{c['case']}:{metric}",
                    requirements="T03;I06",
                    metric=metric,
                    value=c[metric],
                    run_id=c["run_id"],
                    window=c["common_window_h"],
                    denominator="all 16 historical IDs; actual presence/calendar/qualification/status",
                    result="results/p07/r3/dynamic_people.json",
                    result_sha256=pin(data / "dynamic_people.json")["sha256"],
                    source_sha256=c["original_source_sha256"],
                    status=c["status"],
                    scope="LOCAL_SAVED_CHECKPOINT; NOT_A_CROSS_CASE_EFFECT; NO_720H_TAIL",
                )
            )
    for c in dual["cases"]:
        rows.append(
            dict(
                claim_id=f"DUAL:{c['case']}",
                requirements="T06;I07;E18;E22",
                metric="planned_full_schedule_rows",
                value=c["planned_full_schedule_rows"],
                total_gantt_rows=c["total_gantt_rows"],
                **c["identity"],
                result="results/p07/r3/exports/manifest.json",
                result_sha256=pin(data / "exports/manifest.json")["sha256"],
                scope=c["scope"],
                status=c["status"],
            )
        )
    rows.append(
        dict(
            claim_id="E20:r14",
            requirements="T05;T07;T08;I03;I05;E20",
            metric="received_vs_incomplete",
            value="1/4 received; 3/4 incomplete; 4 adopted / 5 solve attempts",
            run_id=e20["products"][0]["run_id"],
            window="[0,387.7324633333333h] STOPPED",
            denominator="4 registered and released products; 3 orders",
            result="results/p07/r3/e20_order_details.json",
            result_sha256=pin(data / "e20_order_details.json")["sha256"],
            scope="ORIGINAL_REAL_KIT_PREFIX; SAME_KIT_ALL_RECEIVED_NOT_MET",
            status="NOT_MET",
        )
    )
    cancellation = read(data / "cancellation.json")
    for account in cancellation["accounts"]:
        for metric in (
            "returned_lots",
            "residual_available_lots",
            "installed_mass_t",
            "active_resource_holders",
            "command_linked_person_h",
            "actual_transport_m",
        ):
            rows.append(
                dict(
                    claim_id=f"CANCEL:{account['unit']}:{metric}",
                    requirements="T05;T09;I03",
                    metric=metric,
                    value=account[metric],
                    run_id=account["run_id"],
                    epoch=account["epoch"],
                    window=f"[0,{account['observed_end_h']}] original WINDOW_CENSORED",
                    denominator=account["product_id"],
                    result="results/p07/r3/cancellation.json",
                    result_sha256=pin(data / "cancellation.json")["sha256"],
                    status="RECORDED_VALUE",
                    scope=account["attribution"],
                )
            )
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with (out / "claim_evidence_r3.tsv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, keys, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    registry = dict(
        format="P07-SOURCE-REGISTRY-r3",
        created_at=datetime.now(timezone.utc).isoformat(),
        fixed_research=[
            dict(
                unit=u,
                identity=c["summary"],
                original_inputs=c["provenance"],
                derived_result=pin(data / "computed" / f"{u}.json"),
                labour_policy=c["labour_policy"],
            )
            for u, c in computed.items()
        ],
        dynamic_people=[
            dict(case=c["case"], run_id=c["run_id"], inputs=c["inputs"], scope=c["status"])
            for c in dynamic
        ],
        dynamic_orders=dict(inputs=e20["inputs"], result=pin(data / "e20_order_details.json")),
        cancellation=dict(
            input=pin(data / "cancellation_inputs.json"), result=pin(data / "cancellation.json")
        ),
        exports=dual,
        original_failed_attempts=read(data / "attempts.json"),
        original_frozen_extractor=pin(
            ROOT / "examples/reproduction/p07/provenance/extractor-r4.py.txt"
        ),
        current_analysis_source=[pin(p) for p in sorted((ROOT / "analysis/p07").glob("*.py"))],
        reused_algorithms=[
            pin(ROOT / "analysis/p07/portable_metrics.py"),
            pin(ROOT / "analysis/p07/portable_metrics_origin.json"),
        ],
        portable_inputs=pin(ROOT / "examples/reproduction/p07/r3/manifest.json"),
        requirements=[
            dict(
                id=k,
                requirements=v[0].split(";"),
                artifacts=v[1].split(";"),
                scope=v[2],
                status="LOCAL_TECHNICAL_COMPLETE"
                if k != "Q14"
                else "G07_CANDIDATE_PREPARATION_AUTHORIZED_ACTUAL_PUBLICATION_NOT_AUTHORIZED",
            )
            for k, v in requirements.items()
        ],
        fixed_source_policy="c1 N/H/F; c2 U/C; mechanism HR aliases do not add independent samples",
        private_path_policy="Historical .local locators are evidence identities, never the portable replay entry point",
        new_production_runs=0,
        new_kit_runs=0,
        new_solve_runs=0,
    )
    write(out / "p07_source_registry_r3.json", registry)
    write(
        out / "feedback_metric_binding_r3.json",
        dict(
            requirements=registry["requirements"],
            claims=pin(out / "claim_evidence_r3.tsv"),
            source_registry=pin(out / "p07_source_registry_r3.json"),
            validation=pin(data / "validation.json"),
            figures=pin(ROOT / "figures/p07/r3/manifest.json"),
            metric_definition="docs/metrics/p07_metrics_definition_r3.md",
            real_time_semantics="P07 offline adapters do not alter GUI, backend or online metric semantics",
            upstream_contracts=[
                pin(ROOT / p)
                for p in [
                    "docs/delivery/requirements.tsv",
                    "docs/delivery/interaction_requirements_r2.tsv",
                    "docs/delivery/p061_interaction_validation_r2.tsv",
                    "docs/delivery/p063_reproduction_r1.json",
                ]
            ],
            actual_vs_planned="original execution facts, adopted schedule, forecast and derived REST tails remain separate",
        ),
    )
    csv_write(
        data / "human_intervals.csv",
        [dict(unit=u, **r) for u, c in computed.items() for r in c["human_intervals"]],
    )
    csv_write(
        data / "transport.csv",
        [
            dict(
                unit=u,
                **{k: v for k, v in c["transport"].items() if k not in ("commands", "chains")},
            )
            for u, c in computed.items()
        ],
    )
    for key in ("chains",):
        csv_write(
            data / f"transport_{key}.csv",
            [dict(unit=u, **r) for u, c in computed.items() for r in c["transport"][key]],
        )
    command_rows = []
    for u in UNITS:
        cache = read(ROOT / "examples/reproduction/p07/r3/inputs" / f"{u}.json.gz", 180_000_000)
        commands = cache["commands"]
        for cid, c in commands.items():
            root = cid
            seen = set()
            while commands[root]["resume_of"]:
                assert root not in seen
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
    csv_write(data / "transport_commands.csv", command_rows)
    print(
        dict(
            status="SOURCE_AND_CLAIM_INDEX_COMPLETE",
            claims=len(rows),
            requirements=len(requirements),
        )
    )


if __name__ == "__main__":
    main()
