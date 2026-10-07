"""Reproduce S16 development witnesses, full tiny-set proofs and matched rules."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from adaptive_hrc_scheduling.reference.baselines import enumerate_independent, rule_schedule
from adaptive_hrc_scheduling.reference.cases import all_cases
from adaptive_hrc_scheduling.reference.checker import check, check_hours, to_hours
from adaptive_hrc_scheduling.reference.cpsat import Options, enumerate_cp, solve
from adaptive_hrc_scheduling.reference.domain import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema_version": "S16-EVIDENCE-1.0",
        "scope": "SYNTHETIC_STATIC_REFERENCE",
        "cases": [],
    }
    for index, instance in enumerate(all_cases()):
        result = solve(instance)
        if result.schedule:
            assert check_hours(instance, to_hours(instance, result.schedule)).valid
        row = {
            "id": instance.id,
            "instance_sha256": digest(instance),
            "status": result.status,
            "objective": result.objective,
            "best_bound": result.best_bound,
            "relative_gap": result.relative_gap,
            "checker": result.checker,
            "solver_version": result.solver_version,
            "budget_seconds": result.budget_seconds,
            "seed": result.seed,
            "workers": result.workers,
            "termination": result.termination,
        }
        if index < 4:
            independent = enumerate_independent(instance)
            actual, complete = enumerate_cp(instance)
            assert complete and actual == independent
            optimum = min(check(instance, s).objective for s in independent)
            assert result.objective == optimum
            row["complete_feasible_set"] = {
                "count": len(actual),
                "equal": True,
                "hand_optimum": optimum,
            }
        rules = [rule_schedule(instance, r) for r in ("EDD", "SPT", "FASTEST_MODE")]
        row["rules"] = [
            {
                "rule": r.rule,
                "status": r.status,
                "objective": r.objective,
                "instance_sha256": r.instance_sha256,
            }
            for r in rules
        ]
        if args.check:
            assert all(r.instance_sha256 == result.instance_sha256 for r in rules)
            if result.schedule:
                assert check(instance, result.schedule).valid
                assert all(
                    r.status == "FEASIBLE" and r.objective >= result.objective for r in rules
                )
        detail = {
            "instance": asdict(instance),
            "solver": asdict(result),
            "rules": [asdict(r) for r in rules],
        }
        (args.output / (instance.id + ".json")).write_text(
            json.dumps(detail, indent=2) + "\n", encoding="utf-8"
        )
        summary["cases"].append(row)
    for name, options in (
        ("ZERO_BUDGET", Options(wall_seconds=0)),
        ("CALLBACK_STOP", Options(stop_after_solutions=1, presolve=False)),
    ):
        result = solve(all_cases()[2], options)
        summary[name] = {
            k: v
            for k, v in asdict(result).items()
            if k not in ("schedule", "total_wall_seconds", "solver_wall_seconds")
        }
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
