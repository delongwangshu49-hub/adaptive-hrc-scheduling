"""Reproduce paired S18 production windows from an actually executed common prefix."""

import argparse
import gzip
import json
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

from build_simulation_production import configuration

from adaptive_hrc_scheduling.algorithms.simulation_joint import SimulationJointProblem
from adaptive_hrc_scheduling.contracts.codec import as_data
from adaptive_hrc_scheduling.control.production_decisions import record
from adaptive_hrc_scheduling.control.production_loop import Scenario, run
from adaptive_hrc_scheduling.control.simulation_joint_policy import Budget, SimulationJointPolicy
from adaptive_hrc_scheduling.production_backend import ProductionBackend

METHODS = ("ADAPTIVE_JOINT", "FIXED_H", "FIXED_HR", "NO_OBSERVATION_UPDATE")


def save_trace(folder, snapshot, decisions):
    folder.mkdir()
    for name, rows in (
        ("events", (as_data(e) for e in snapshot.events)),
        ("decisions", decisions),
    ):
        with gzip.open(folder / (name + ".jsonl.gz"), "wt", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, separators=(",", ":")) + "\n")
    (folder / "state.json").write_text(json.dumps(as_data(snapshot.state)), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variant", choices=("SR-W1", "SR-W2"), default="SR-W1")
    parser.add_argument("--window-h", type=float, default=8)
    parser.add_argument("--calls", type=int, default=4)
    parser.add_argument("--per-call-wall-s", type=float, default=120)
    parser.add_argument("--methods", nargs="+", choices=METHODS, default=METHODS)
    args = parser.parse_args()
    if args.calls <= 0 or args.window_h <= 0 or args.per_call_wall_s <= 0:
        parser.error("positive window, calls and wall limit required")
    args.output.mkdir(parents=True, exist_ok=False)
    config = configuration(variant=args.variant)
    (args.output / "configuration.json").write_text(
        json.dumps(as_data(config), indent=2), encoding="utf-8"
    )

    # No seeded completion or teleport: actually receive/prepare/move the first frame.
    def ready(world):
        return any(p.id == "PRODUCT-1.BOTTOM" and p.location == "J2" for p in world.s.positions)

    warmup = run(
        ProductionBackend(config), Scenario(until_h=720), warmup_only=True, stop_condition=ready
    )
    if warmup.manifest["termination"] != "DECLARED_CHECKPOINT":
        raise RuntimeError("Actual common preparation did not reach the declared checkpoint")
    if warmup.audit.status != "PASS" or warmup.decision_audit.status != "PASS":
        raise RuntimeError("Common prefix failed independent reconstruction")
    rows = tuple(record(d) for d in warmup.decisions)
    save_trace(args.output / "common-prefix", warmup.snapshot, rows)
    start = warmup.snapshot.state.time_h
    end = start + args.window_h
    budget = Budget(
        args.calls,
        args.calls,
        2 * args.calls,
        args.calls * args.per_call_wall_s,
        1,
        1,
        args.per_call_wall_s,
        tuple(start + args.window_h * i / args.calls for i in range(args.calls)),
        args.window_h,
    )
    budget.validate()
    # Persist the shared allowance before any paired search executes.
    (args.output / "predeclared-budget.json").write_text(
        json.dumps(asdict(budget), indent=2), encoding="utf-8"
    )
    seed = ProductionBackend(config, run_id=warmup.snapshot.run_id, epoch=warmup.snapshot.epoch)
    seed.s, seed.events = warmup.snapshot.state, list(warmup.snapshot.events)
    common = SimulationJointProblem(
        config, seed.observe(), warmup.snapshot, decisions=rows, end_h=end
    )
    summaries = []
    for method in args.methods:
        policy = SimulationJointPolicy(config, budget, method=method, end_h=end)
        started = perf_counter()
        result = run(
            common.world(),
            Scenario(until_h=end),
            joint_policy=policy,
            continuation=True,
            prefix_decisions=warmup.decisions,
        )
        folder = args.output / method
        save_trace(folder, result.snapshot, (record(d) for d in result.decisions))
        for index, (problem, candidate) in enumerate(policy.candidates, 1):
            candidate_folder = folder / f"candidate-{index:02}"
            save_trace(candidate_folder, problem.prefix, problem.decisions)
            (candidate_folder / "schedule.json").write_text(
                json.dumps(as_data(candidate), indent=2), encoding="utf-8"
            )
        summary = dict(
            method=method,
            manifest=result.manifest,
            audit=as_data(result.audit),
            decision_audit=as_data(result.decision_audit),
            elapsed_s=perf_counter() - started,
        )
        (folder / "result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        summaries.append(summary)
        print(method, result.manifest["termination"], result.audit.status, flush=True)
    (args.output / "summary.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    return (
        0
        if all(s["audit"]["status"] == s["decision_audit"]["status"] == "PASS" for s in summaries)
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
