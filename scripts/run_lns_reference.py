"""Reproduce S17 fixed-mode LNS versus CP-SAT on the same explicit static inputs."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from adaptive_hrc_scheduling.algorithms.lns import Options, search
from adaptive_hrc_scheduling.algorithms.static_lns import StaticProblem
from adaptive_hrc_scheduling.reference.baselines import enumerate_independent, rule_schedule
from adaptive_hrc_scheduling.reference.cases import all_cases
from adaptive_hrc_scheduling.reference.checker import check, check_hours, to_hours
from adaptive_hrc_scheduling.reference.cpsat import solve
from adaptive_hrc_scheduling.reference.domain import Entry, digest


def signature(result):
    data = asdict(result)
    data.pop("wall_seconds")
    for row in data["history"]:
        row.pop("wall_seconds")
    return data


def run(output, *, check_replay=False):
    output.mkdir(parents=True, exist_ok=True)
    summary = {
        "schema_version": "S17-EVIDENCE-1",
        "scope": "FIXED_MODE_STATIC_DEVELOPMENT",
        "cases": [],
    }
    cases = []
    for index, instance in enumerate(all_cases()):
        modes = {t.id: t.alternatives[0].id for t in instance.tasks}
        options = Options(
            seed=17, iterations=8, destroy_size=2, repair_trials=1000, wall_seconds=60, stagnation=8
        )
        problem = StaticProblem(instance, modes)
        fixed_instance = problem.fixed_instance
        exact = solve(fixed_instance)
        baseline = rule_schedule(fixed_instance)
        result = search(problem, options)
        if check_replay:
            assert signature(result) == signature(search(StaticProblem(instance, modes), options))
        if result.best is not None:
            assert check(fixed_instance, result.best).valid
            assert check_hours(fixed_instance, to_hours(fixed_instance, result.best)).valid
            assert result.best_score <= result.initial_score
            if exact.best_bound is not None:
                assert result.best_score[0] >= exact.best_bound
        feasible_set_count = None
        if index < 4:
            oracle = enumerate_independent(fixed_instance)
            assert result.best in oracle
            assert exact.objective == min(check(fixed_instance, s).objective for s in oracle)
            feasible_set_count = len(oracle)
        score = result.best_score[0] if result.best_score is not None else None
        row = {
            "id": instance.id,
            "fixed_instance_sha256": digest(fixed_instance),
            "fixed_modes": modes,
            "domain_version": instance.schema_version,
            "layout_version": instance.layout_version,
            "baseline_status": baseline.status,
            "baseline_objective": baseline.objective,
            "lns_status": result.status,
            "lns_objective": score,
            "termination": result.termination,
            "iterations": len(result.history),
            "improvements": sum(h.improved for h in result.history),
            "cp_status": exact.status,
            "cp_objective": exact.objective,
            "cp_bound": exact.best_bound,
            "cp_relative_gap": exact.relative_gap,
            "lns_over_cp_value": score / exact.objective
            if score is not None and exact.objective
            else None,
            "relative_gap_to_cp_bound": (score - exact.best_bound) / max(1, abs(score))
            if score is not None and exact.best_bound is not None
            else None,
            "complete_fixed_feasible_set_count": feasible_set_count,
            "checker": "PASS_S16_STATIC" if score is not None else "NO_RETURNED_PLAN",
            "replay": check_replay,
        }
        summary["cases"].append(row)
        cases.append({"instance": asdict(fixed_instance), "options": asdict(options)})
        (output / (instance.id + ".json")).write_text(
            json.dumps(
                {
                    "input": asdict(fixed_instance),
                    "baseline": asdict(baseline),
                    "cp": asdict(exact),
                    "lns": asdict(result),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    instance = all_cases()[0]
    initial = (Entry("A", "H", 1, 3), Entry("B", "H", 3, 4))
    demo = search(
        StaticProblem(instance, {"A": "H", "B": "H"}, initial=initial),
        Options(seed=17, iterations=4),
    )
    assert demo.initial_score == (4,) and demo.best_score == (3,)
    summary["delayed_initial_control"] = {
        "initial": 4,
        "lns": 3,
        "cp": 3,
        "scope": "DEVELOPMENT_MECHANISM_ONLY",
    }
    (output / "cases.json").write_text(json.dumps(cases, indent=2) + "\n", encoding="utf-8")
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.output, check_replay=args.check), indent=2))
