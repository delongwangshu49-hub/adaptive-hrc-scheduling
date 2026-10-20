"""Execute only the four registered 1 h S20 development rows, never tune/test rows."""

import argparse
import gzip
import json
from pathlib import Path
from time import perf_counter

from build_simulation_production import configuration
from s20_design import (
    ROOT,
    authorize_development,
    file_sha,
    fingerprint,
    load_design,
    validate_design,
    write,
)

from adaptive_hrc_scheduling.contracts.codec import as_data
from adaptive_hrc_scheduling.control.production_decisions import record
from adaptive_hrc_scheduling.control.production_loop import Scenario, run
from adaptive_hrc_scheduling.control.simulation_joint_policy import Budget, SimulationJointPolicy
from adaptive_hrc_scheduling.production_backend import ProductionBackend


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    catalog, manifest, sources = load_design()
    design_check = validate_design(catalog, manifest, sources)
    args.output.mkdir(parents=True, exist_ok=False)
    rows = [r for r in manifest["rows"] if r["split"] == "dev"]
    harness = {
        p: file_sha(ROOT / p) for p in ("scripts/s20_design.py", "scripts/run_s20_development.py")
    }
    write(
        args.output / "before.json",
        {
            "design_check": design_check,
            "manifest_sha256": fingerprint(manifest),
            "rows": rows,
            "runner_sha256": file_sha(Path(__file__)),
            "harness_sha256": harness,
            "sources": sources,
            "scope": "PARSER_TRACE_AND_SHARED_POLICY_SMOKE_NOT_METHOD_EFFECT",
        },
    )
    configurations = {c["id"]: c for c in catalog["configurations"]}
    reports = []
    for row in rows:
        authorize_development(row)
        folder = args.output / row["method"]
        folder.mkdir()
        config = configuration(**configurations[row["config_id"]]["builder"])
        allowance = Budget(**catalog["budgets"][row["budget_id"]])
        policy = SimulationJointPolicy(config, allowance, method=row["method"], end_h=1)
        began = perf_counter()
        result = run(ProductionBackend(config), Scenario(**row["scenario"]), joint_policy=policy)
        elapsed = perf_counter() - began
        for name, records in (
            ("events", [as_data(e) for e in result.snapshot.events]),
            ("decisions", [record(d) for d in result.decisions]),
        ):
            with gzip.open(folder / (name + ".jsonl.gz"), "wt", encoding="utf-8") as stream:
                for item in records:
                    stream.write(json.dumps(item) + "\n")
        write(folder / "state.json", as_data(result.snapshot.state))
        write(folder / "configuration.json", as_data(config))
        write(folder / "manifest.json", result.manifest)
        summary = {
            "row_id": row["id"],
            "method": row["method"],
            "split": "dev",
            "elapsed_s": elapsed,
            "audit": result.audit.status,
            "decision_audit": result.decision_audit.status,
            "termination": result.manifest["termination"],
            "time_h": result.manifest["time_h"],
            "ready": result.manifest["ready"],
            "received": result.manifest["received"],
            "events": len(result.snapshot.events),
            "decisions": len(result.decisions),
            "budget": policy.budget.report(),
            "artifacts": {p.name: file_sha(p) for p in sorted(folder.iterdir())},
        }
        write(folder / "summary.json", summary)
        reports.append(summary)
        print(
            row["method"],
            summary["termination"],
            summary["audit"],
            summary["decision_audit"],
            flush=True,
        )
    unchanged = all(file_sha(ROOT / p) == h for p, h in sources["files"].items())
    harness_unchanged = all(file_sha(ROOT / p) == h for p, h in harness.items())
    write(
        args.output / "summary.json",
        {
            "scope": "S20_DEVELOPMENT_ONLY",
            "runs": reports,
            "test_runs": 0,
            "tuning_runs": 0,
            "kit_runs": 0,
            "source_unchanged": unchanged,
            "harness_unchanged": harness_unchanged,
        },
    )
    passed = all(
        r["audit"] == r["decision_audit"] == "PASS"
        and r["termination"] == "WINDOW_CENSORED"
        and r["time_h"] == 1
        and all(record["within_budget"] for record in r["budget"]["records"])
        for r in reports
    )
    return 0 if passed and unchanged and harness_unchanged else 1


if __name__ == "__main__":
    raise SystemExit(main())
