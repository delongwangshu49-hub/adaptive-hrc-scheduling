"""Run only S20 r2 registered development rows and save reconstructible evidence."""

import argparse
import gzip
from pathlib import Path
from time import perf_counter

from build_simulation_production import configuration
from s20_design import ROOT, file_sha, fingerprint, load_design, read, require, write
from s20_extension_design import EXTENSIONS, check

from adaptive_hrc_scheduling.contracts.codec import as_data
from adaptive_hrc_scheduling.control.production_decisions import record
from adaptive_hrc_scheduling.control.production_loop import Scenario, run
from adaptive_hrc_scheduling.control.research_projection import (
    ObservationSettings,
    ProjectedPolicy,
    audit_projection_history,
    audit_saved_projection,
    export_projection,
)
from adaptive_hrc_scheduling.control.simulation_joint_policy import Budget, SimulationJointPolicy
from adaptive_hrc_scheduling.production_backend import ProductionBackend
from adaptive_hrc_scheduling.research_objective import WeightedObjective
from adaptive_hrc_scheduling.research_tail import check_common_horizon, common_horizon


def authorize(row):
    require(
        row["split"] == "dev" and row["execution_authorization"] == "DEVELOPMENT_ONLY",
        "S20_EXTENSION_DEV_ONLY",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    checked = check()
    catalog, manifest, sources = load_design()
    extension = read(ROOT / EXTENSIONS)
    rows = [r for r in extension["rows"] if r["split"] == "dev"]
    args.output.mkdir(parents=True, exist_ok=False)
    write(
        args.output / "before.json",
        dict(
            check=checked,
            extension_sha256=fingerprint(extension),
            sources=sources,
            declared_rows=rows,
        ),
    )
    configs = {c["id"]: c for c in catalog["configurations"]}
    results = []
    for row in rows:
        authorize(row)
        config = configuration(**configs[row["config_id"]]["builder"])
        budget = Budget(**catalog["budgets"][row["budget_id"]])
        if row["group"] == "D":
            policy = SimulationJointPolicy(
                config,
                budget,
                method=row["method"],
                end_h=1,
                objective=WeightedObjective(**row["objective"]),
            )
        else:
            policy = ProjectedPolicy(
                config,
                budget,
                method=row["method"],
                end_h=1,
                settings=ObservationSettings(**row["observation"]),
            )
        began = perf_counter()
        result = run(ProductionBackend(config), Scenario(until_h=1), joint_policy=policy)
        elapsed = perf_counter() - began
        records = tuple(record(d) for d in result.decisions)
        folder = args.output / row["id"]
        folder.mkdir()
        write(folder / "configuration.json", as_data(config))
        write(folder / "snapshot.json", as_data(result.snapshot))
        write(folder / "decisions.json", records)
        write(folder / "manifest.json", result.manifest)
        tail = common_horizon(config, result.snapshot, records, 1)
        tail_audit = check_common_horizon(config, result.snapshot, records, tail)
        write(folder / "tail.json", tail)
        projection_audit = saved_audit = None
        if row["group"] == "B":
            projection_audit = audit_projection_history(config, result.snapshot, records, policy)
            data = export_projection(policy)
            with gzip.open(folder / "projection.json.gz", "wt", encoding="utf-8") as stream:
                import json

                json.dump(data, stream)
            with gzip.open(folder / "projection.json.gz", "rt", encoding="utf-8") as stream:
                saved = json.load(stream)
            saved_audit = audit_saved_projection(config, result.snapshot, records, saved)
        summary = dict(
            row=row,
            elapsed_s=elapsed,
            actual_audit=result.audit.status,
            causal_audit=result.decision_audit.status,
            termination=result.manifest["termination"],
            time_h=result.manifest["time_h"],
            events=len(result.snapshot.events),
            decisions=len(records),
            projection_audit=projection_audit,
            saved_projection_audit=saved_audit,
            tail_audit=tail_audit,
            budget=policy.budget.report(),
            artifacts={p.name: file_sha(p) for p in folder.iterdir()},
        )
        write(folder / "summary.json", summary)
        results.append(summary)
        print(row["id"], summary["actual_audit"], summary["causal_audit"], flush=True)
    unchanged = all(file_sha(ROOT / p) == h for p, h in sources["files"].items())
    passed = unchanged and all(
        r["actual_audit"] == r["causal_audit"] == r["tail_audit"] == "PASS"
        and all(x["within_budget"] for x in r["budget"]["records"])
        for r in results
    )
    write(
        args.output / "summary.json",
        dict(
            status="PASS" if passed else "FAILED",
            runs=results,
            sources_unchanged=unchanged,
            formal_runs=0,
            tune_runs=0,
            kit_runs=0,
        ),
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
