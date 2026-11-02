"""Source-to-result, cross-table and geometry validation for P07 r3."""

import argparse
from collections import Counter
from pathlib import Path

from adapters import require
from build_results import compute
from cancellation import compute as cancellation_compute
from checks import dynamic_oracle, e20_oracle, equal, fixed_oracle
from export import validate_pair
from load import ROOT, UNITS, pin, read, sha, write
from tables import contents
from tables import rows as table_rows
from validate import independent_occupancy, validate_identity

PAIRED_METRICS = (
    "on_time_received_fraction_all_released",
    "on_time_ready_fraction_all_released",
    "last_received_h",
    "common_window_sum_E",
    "common_window_max_E",
    "transport_m",
    "empty_transport_ratio",
    "wip_area_product_h",
    "available_person_h",
)


def run(cache_dir, data, inventory, reference):
    manifest = read(inventory)
    require([u["unit"] for u in manifest["units"]] == list(UNITS), "COMPLETE_FIXED_INPUT_SET")
    policies = read(cache_dir / "metadata.json")
    computed = {}
    checks = []
    for entry in manifest["units"]:
        unit = entry["unit"]
        cp = cache_dir / f"{unit}.json"
        if not cp.exists():
            cp = cp.with_suffix(".json.gz")
        cache = read(cp, 180_000_000)
        actual = read(data / "computed" / f"{unit}.json", 80_000_000)
        equal(actual["cache_pin"], pin(cp), "consumed_cache_pin")
        validate_identity(cache, actual, entry)
        require(
            cache["provenance"]["extractor"]["sha256"]
            == sha(ROOT / "examples/reproduction/p07/provenance/extractor-r4.py.txt"),
            "FROZEN_ORIGINAL_EXTRACTOR",
        )
        require(cache["original_exit"]["exit_code"] == 0, "ORIGINAL_SELECTED_EXIT")
        independent = fixed_oracle(cache, actual, policies[unit])
        expected = compute(cache, policies[unit])
        actual_without_pin = {k: v for k, v in actual.items() if k != "cache_pin"}
        equal(actual_without_pin, expected, "computed." + unit)
        independent_occ = independent_occupancy(cache)
        for name, oracle in independent_occ.items():
            equal(actual["occupancy"][name]["area_product_h"], oracle["area"], "occupancy.area")
            equal(actual["occupancy"][name]["peak_products"], oracle["peak"], "occupancy.peak")
        if cache["journal"]:
            equal(
                actual["costs"]["cycle_seconds"],
                actual["costs"]["final_used_budget_s"],
                "cycle_budget",
            )
            require(actual["costs"]["search_calls"] <= 7, "ORIGINAL_SEARCH_CEILING")
            equal(
                actual["costs"]["cached_plan_dispatches"],
                sum(
                    r.get("selected_source") == "VERIFIED_CACHE"
                    and r.get("receipt_kind") == "STARTED"
                    for r in cache["journal"]
                ),
                "ACTUAL_CACHE_DISPATCH_SOURCE",
            )
        computed[unit] = actual
        checks.append(dict(unit=unit, run_id=cache["run_id"], cache=pin(cp), **independent))
    summaries = [c["summary"] for c in computed.values()]
    equal(read(data / "summary.json"), summaries, "summary_json")
    equal(read(data / "costs.json"), [c["costs"] for c in computed.values()], "costs_json")
    index = {(s["scenario"], s["method"]): s for s in summaries if s["scenario"] != "MECHANISM"}
    expected_pairs = []
    for metric in PAIRED_METRICS:
        for scenario in sorted({s[0] for s in index}):
            a, b = index[scenario, "ADAPTIVE"], index[scenario, "EDD"]
            for key in ("source_family", "evaluation_window_h", "input_configuration_sha256"):
                equal(a[key], b[key], "pair_scope." + key)
            av, bv = a[metric], b[metric]
            expected_pairs.append(
                dict(
                    scenario=scenario,
                    metric=metric,
                    adaptive=av,
                    edd=bv,
                    delta_adaptive_minus_edd=av - bv if av is not None and bv is not None else None,
                    status="EVALUABLE"
                    if av is not None and bv is not None
                    else "UNKNOWN_METRIC_SOURCE",
                )
            )
    equal(read(data / "pairs.json"), expected_pairs, "paired_values_and_deltas")
    mechanisms = []
    for label, u in [
        ("M-H-N", "M-H-N"),
        ("M-H-H", "M-H-H"),
        ("M-HR-N", "N-CPU-EDD"),
        ("M-HR-H", "H-CPU-EDD"),
    ]:
        c = computed[u]
        mechanisms.append(
            dict(
                mechanism=label,
                original_unit=u,
                distinct_additional_sample=not label.startswith("M-HR"),
                phase_count=len(c["stages"]),
                branch_labour_h=sum(s["labour_h"] for s in c["stages"]),
                branch_exposure_F_h=sum(s["crew_exposure_F_h"] for s in c["stages"]),
                **{
                    k: c["summary"][k]
                    for k in [
                        "last_received_h",
                        "common_window_sum_E",
                        "common_window_max_E",
                        "peak_F",
                    ]
                },
            )
        )
    equal(read(data / "mechanisms.json"), mechanisms, "mechanisms")
    dynamic_values = dynamic_oracle(read(data / "dynamic_people.json", 40_000_000))
    e20_oracle(read(data / "e20_order_details.json"), read(reference))
    cancel_inputs = read(data / "cancellation_inputs.json")
    expected_cancel = {k: [] for k in ("accounts", "lots", "materials")}
    for case in cancel_inputs:
        p = cache_dir / f"{case['unit']}.json"
        if not p.exists():
            p = p.with_suffix(".json.gz")
        result = cancellation_compute(case, read(p, 180_000_000))
        for key in expected_cancel:
            expected_cancel[key].extend(result[key])
    cancelled = read(data / "cancellation.json")
    for key, values in expected_cancel.items():
        equal(cancelled[key], values, "cancellation." + key)
    require(
        len(cancelled["accounts"]) == 2 and len(cancelled["lots"]) == 240, "CANCELLATION_COVERAGE"
    )
    dual = read(data / "exports/manifest.json")
    require(len(dual["cases"]) == 3, "DUAL_CASES")
    for case in dual["cases"]:
        folder = data / "exports" / case["case"]
        view = read(folder / "gantt.json", 40_000_000)
        scene = read(folder / "scene-domain.json")
        equal(case["identity"], validate_pair(view, scene), "dual.identity")
        equal(case["total_gantt_rows"], len(view["rows"]), "dual.total_rows")
        equal(
            case["planned_full_schedule_rows"],
            sum(
                r["row_kind"] == "FULL_PLAN" and r["schedule_state"] == "PLANNED"
                for r in view["rows"]
            ),
            "dual.planned_rows",
        )
        equal(
            case["row_counts_by_state"],
            dict(Counter(r["schedule_state"] for r in view["rows"])),
            "dual.row_states",
        )
        equal(
            case["row_counts_by_kind"],
            dict(Counter(r["row_kind"] for r in view["rows"])),
            "dual.row_kinds",
        )
        for binding in case["files"]:
            filename = Path(binding["export"]["path"]).name
            equal(sha(folder / filename), binding["export"]["sha256"], "dual.export_sha")
            equal(
                binding["original"]["sha256"], binding["export"]["sha256"], "dual.original_copy_sha"
            )
    frames = table_rows(data, computed, cache_dir)
    for name, values in frames.items():
        require((data / name).read_bytes() == contents(values), "CSV_JSON_MISMATCH:" + name)
    failures = read(data / "attempts.json")
    require(
        len(failures["full_original_index"]["production_failed_or_censored"]) == 4,
        "ORIGINAL_FAILURES_RETAINED",
    )
    inputs = [
        pin(p)
        for p in sorted(data.rglob("*"))
        if p.is_file() and p.suffix in (".json", ".csv") and p.name != "validation.json"
    ]
    return dict(
        identity="P07-OFFLINE-VALIDATION-r3",
        status="PASS",
        research_units=checks,
        paired_metrics=len(expected_pairs),
        mechanism_cells=4,
        dynamic_person_value_comparisons=dynamic_values,
        dual_domain_cases=3,
        cancellation_accounts=2,
        csv_json_comparisons=len(frames),
        independent_interval_and_polyline_verification=True,
        independent_dynamic_denominator_sweep=True,
        source_code={p.name: pin(p) for p in sorted((ROOT / "analysis/p07").glob("*.py"))},
        inventory=pin(inventory),
        E20_reference=pin(reference),
        inputs=inputs,
        new_production_runs=0,
        new_kit_runs=0,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data", type=Path, default=ROOT / "results/p07/r3")
    p.add_argument("--cache", type=Path, default=ROOT / "results/p07/cache/runs")
    p.add_argument(
        "--inventory", type=Path, default=ROOT / "examples/reproduction/p07/r3/inventory.json"
    )
    p.add_argument(
        "--reference", type=Path, default=ROOT / "examples/reproduction/p07/r3/e20-reference.json"
    )
    a = p.parse_args()
    try:
        result = run(a.cache, a.data, a.inventory, a.reference)
    except Exception as error:
        write(
            a.data / "validation.json",
            dict(status="FAIL", identity="P07-OFFLINE-VALIDATION-r3", reason=str(error)),
        )
        raise
    write(a.data / "validation.json", result)
    print(
        dict(
            status="PASS",
            fixed_units=len(result["research_units"]),
            paired_metrics=result["paired_metrics"],
            dynamic_checks=result["dynamic_person_value_comparisons"],
            csv_checks=result["csv_json_comparisons"],
        )
    )


if __name__ == "__main__":
    main()
