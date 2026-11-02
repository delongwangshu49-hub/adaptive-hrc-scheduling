"""Recompute historical dynamic-person ledgers and export scoped E20 facts."""

import math
import sys

from adapters import people_metrics, require
from load import ROOT, csv_write, pin, read, write

sys.path.insert(0, str(ROOT / "src"))
from adaptive_hrc_scheduling.contracts.codec import as_data
from adaptive_hrc_scheduling.contracts.production import decode, digest
from adaptive_hrc_scheduling.domain.production import Configuration
from adaptive_hrc_scheduling.dynamic_workforce import WorkforceHistory


def changes_from_events(events):
    rows, returns = [], []
    for index, e in enumerate(events):
        w = e.get("world")
        if not w or not w["kind"].startswith("PERSON_"):
            continue
        pid = w["entity_id"]
        flags = e["state"]["failed_resources"]
        status = next(
            (
                k
                for k in ("DEPARTED", "DEPARTURE_PENDING", "ABSENT_HOLD", "ABSENT")
                if f"P043.{k}.{pid}" in flags
            ),
            "PRESENT",
        )
        h = next(x for x in e["state"]["humans"] if x["person_id"] == pid)
        rows.append(
            dict(
                person_id=pid,
                time_h=e["occurred_sim_h"],
                status=status,
                event_id=e["id"],
                event_sequence=e["sequence"],
                **{k: h[k] for k in ("fatigue", "exposure", "peak")},
            )
        )
        if w["kind"] == "PERSON_RETURN":
            old = next(x for x in events[index - 1]["state"]["humans"] if x["person_id"] == pid)
            require(old == h, "RETURN_MUST_PRESERVE_FULL_HUMAN_STATE")
            returns.append(
                dict(
                    person_id=pid,
                    event_id=e["id"],
                    time_h=e["occurred_sim_h"],
                    previous=old,
                    returned=h,
                    status="EXACT_CONTINUITY",
                )
            )
    return rows, returns


def recompute(folder, label):
    source = folder / "session-state.json"
    saved = read(source, limit=40_000_000)
    config = decode(Configuration, read(folder / "configuration.json"))
    spec = read(folder / "run-spec.json")
    require(digest(config) == spec["initial_config_sha256"], "WORKFORCE_C0")
    history = WorkforceHistory(config, saved["generations"])
    # Catalog.configuration_sha256 binds immutable C0, while the execution
    # snapshot binds the materialized current configuration after generations.
    require(
        saved["catalog"]["configuration_sha256"] == spec["initial_config_sha256"],
        "WORKFORCE_CATALOG_C0",
    )
    require(
        digest(history.current) == saved["execution"]["config_sha256"],
        "WORKFORCE_CURRENT_EXECUTION_CONFIG",
    )
    state = saved["execution"]["state"]
    changes, returns = changes_from_events(saved["execution"]["events"])
    rates = {r["template_id"]: r["rate_per_h"] for r in spec["cost"]["rates"]}
    people, activity, intervals = people_metrics(
        as_data(history.current), state, changes, saved["generations"], rates
    )
    stats = saved["workforce_statistics"]
    require(stats["common_window_h"] == [0, state["time_h"]], "WORKFORCE_OBSERVATION_WINDOW")
    checks = []
    for row in people:
        old = stats["people"][row["person_id"]]
        for key, old_key in [
            ("presence_h", "presence_h"),
            ("availability_h", "available_h"),
            ("fatigue", "fatigue"),
            ("exposure_F_h", "exposure"),
            ("peak_f", "peak"),
            ("presence_exposure_F_h", "presence_exposure"),
            ("presence_labour_cost", "labour_cost"),
        ]:
            require(
                math.isclose(row[key], old[old_key], rel_tol=1e-8, abs_tol=1e-7),
                "INDEPENDENT_WORKFORCE_METRIC:" + row["person_id"] + ":" + key,
            )
            checks.append(
                dict(person_id=row["person_id"], metric=key, actual=row[key], saved=old[old_key])
            )
    for key, value in [
        ("total_available_h", sum(r["availability_h"] for r in people)),
        ("total_labour_cost", sum(r["presence_labour_cost"] for r in people)),
    ]:
        require(
            math.isclose(value, stats[key], rel_tol=1e-8, abs_tol=1e-7), "WORKFORCE_TOTAL:" + key
        )
    run_id = saved["execution"]["run_id"]
    for collection in (people, activity, intervals, changes):
        for row in collection:
            row.update(
                case=label,
                run_id=run_id,
                scope="ORIGINAL_LOCAL_CHECKPOINT_DYNAMIC_HISTORY_NOT_FIXED_RESEARCH_COMPARISON",
            )
    return dict(
        case=label,
        run_id=run_id,
        people=people,
        activity=activity,
        intervals=intervals,
        changes=changes,
        return_checks=returns,
        checks=checks,
        common_window_h=[0, state["time_h"]],
        common_720h_status="UNKNOWN_INCOMPLETE_LOCAL_CHECKPOINT_NO_TAIL",
        total_exposure_F_h=sum(r["exposure_F_h"] for r in people),
        max_exposure_F_h=max(r["exposure_F_h"] for r in people),
        actual_available_person_h=stats["total_available_h"],
        presence_labour_cost=stats["total_labour_cost"],
        currency=spec["cost"]["currency"],
        labour_policy=spec["cost"]["policy_id"],
        legacy_resource_cost_policy="UNCHANGED_FROZEN_C0_MODEL_REPORTED_SEPARATELY",
        original_source_sha256="dbdf17417d99a8c35a373b8ba4e4a67ae360b3de7c026f337f35e8fcd9fe6d3d",
        inputs=[pin(source), pin(folder / "configuration.json"), pin(folder / "run-spec.json")],
        reproduction_input=dict(
            configuration=as_data(history.current),
            state={k: state[k] for k in ("time_h", "humans", "intervals")},
            changes=changes,
            generations=saved["generations"],
            rates=rates,
            saved_statistics=stats,
        ),
        status="INDEPENDENT_ARITHMETIC_AND_SAVED_STATISTICS_MATCH",
    )


def e20_evidence():
    index = read(ROOT / "docs/delivery/p061_event_chain_trace_r1.json")
    scopes = index["real_Kit_and_derived_scopes"]
    for item in scopes["records"]:
        require(
            pin(ROOT / item["path"])["sha256"] == item["sha256"], "E20_EXISTING_REFERENCE_CHANGED"
        )
    base = ROOT / ".local/p052-closeout-20261028-r2/closeout-evidence/r14-audit"
    facts, chain = read(base / "mechanism-facts.json"), read(base / "chain.json")
    timeline = []
    for b in facts["applied_business"]:
        check = next(
            x for x in chain["checks"] if x["name"] == f"APPLIED_{b['kind']}_{b['target']}"
        )
        receipts = check["evidence"]
        for r in receipts:
            timeline.append(
                dict(
                    run_id=facts["run_id"],
                    scope="REAL_R14_SAME_RUN_PREFIX",
                    request_id=b["request_id"],
                    kind=b["kind"],
                    target=b["target"],
                    phase=r["status"],
                    sim_h=r["sim_h"],
                    actual_applied_sim_h=r.get("actual_applied_sim_h"),
                    event_id=r.get("event_id"),
                    catalog_version=r.get("catalog_version_after"),
                )
            )
    timeline.append(
        dict(
            run_id=facts["run_id"],
            scope="REAL_R14_SAME_RUN_PREFIX",
            kind="FIRST_W3_PRODUCTION",
            phase="STARTED",
            sim_h=facts["first_w3_production"]["sim_h"],
            event_id=facts["first_w3_production"]["event_id"],
        )
    )
    timeline.append(
        dict(
            run_id=facts["run_id"],
            scope="REAL_R14_SAME_RUN_PREFIX",
            kind="FINAL",
            phase="STOPPED",
            sim_h=facts["final"]["final_sim_h"],
            received=1,
            unreceived=3,
            open_obligations=20,
        )
    )
    return dict(
        timeline=timeline,
        products=facts["products"],
        r14_final=facts["final"],
        plan_binding=scopes["r14"]["full_plan"],
        separate_r9=scopes["r9"],
        separate_e21=scopes["e21"],
        scope="APPROVED_SPLIT_EVIDENCE_WITH_ORIGINAL_SAME_KIT_FULL_RECEIPT_NOT_MET",
        inputs=[
            pin(ROOT / "docs/delivery/p061_event_chain_trace_r1.json"),
            pin(base / "chain.json"),
            pin(base / "mechanism-facts.json"),
        ],
    )


def main():
    out = ROOT / "results/p07"
    rows = [
        recompute(ROOT / ".local/p043-20261023" / name, name)
        for name in ("cpu-formal-r2", "kit-formal-r3")
    ]
    write(out / "dynamic_people.json", rows)
    for key, name in [
        ("people", "dynamic_people"),
        ("activity", "dynamic_activity"),
        ("intervals", "dynamic_intervals"),
        ("changes", "dynamic_people_events"),
    ]:
        csv_write(out / f"{name}.csv", [r for case in rows for r in case[key]])
    e20 = e20_evidence()
    write(out / "e20.json", e20)
    csv_write(out / "e20_timeline.csv", e20["timeline"])
    failure_path = ROOT / "docs/delivery/p053_failure_index_r2.json"
    failed = read(failure_path)
    csv_write(
        out / "attempts.csv",
        [
            dict(
                unit=r["unit"], source_root=r["root"], **r["summary"], **r["exit"], scope=r["scope"]
            )
            for r in failed["production_failed_or_censored"]
        ],
    )
    write(out / "attempts.json", dict(source=pin(failure_path), full_original_index=failed))
    print(
        {
            "dynamic_cases": len(rows),
            "people_per_case": [len(r["people"]) for r in rows],
            "independent_value_comparisons": sum(len(r["checks"]) for r in rows),
            "E20_timeline_rows": len(e20["timeline"]),
            "failed_original_attempts": len(failed["production_failed_or_censored"]),
        }
    )


if __name__ == "__main__":
    main()
