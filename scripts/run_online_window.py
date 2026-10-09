"""S19 diagnostic allowance on a genuinely executed production prefix."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from build_simulation_production import configuration

from adaptive_hrc_scheduling.algorithms.simulation_joint import SimulationJointProblem
from adaptive_hrc_scheduling.contracts.codec import as_data
from adaptive_hrc_scheduling.control.online import Limits, OnlinePolicy
from adaptive_hrc_scheduling.control.online_timing import OnlineTiming
from adaptive_hrc_scheduling.control.production_decisions import record
from adaptive_hrc_scheduling.control.production_loop import Scenario, run
from adaptive_hrc_scheduling.production_backend import ProductionBackend


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--loaded-failure", action="store_true")
    parser.add_argument(
        "--limits", type=Path, default=Path("examples/online/limits_diagnostic.json")
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    inputs = tuple(
        p
        for pattern in (
            "src/**/*.py",
            "scripts/*online*.py",
            "scripts/*production*.py",
            "examples/online/*.json",
            "src/**/simulation_inputs/*",
        )
        for p in root.glob(pattern)
        if p.is_file()
    )
    sources = {}
    for p in inputs:
        data = p.read_bytes()
        name = p.relative_to(root).as_posix()
        sources[name] = hashlib.sha256(data).hexdigest()
        captured = args.output / "source" / name
        captured.parent.mkdir(parents=True, exist_ok=True)
        captured.write_bytes(data)

    def save(name, data):
        (args.output / name).write_text(json.dumps(as_data(data), indent=2), encoding="utf-8")

    limits_data = json.loads(args.limits.read_text(encoding="utf-8"))
    limits = Limits(**limits_data)
    limits.validate()
    save("predeclared-online-limits.json", limits_data)
    config = configuration()
    save("configuration.json", config)
    warmup = run(
        ProductionBackend(config),
        Scenario(until_h=720),
        warmup_only=True,
        stop_condition=lambda w: (
            not w.s.running
            and any(p.id == "PRODUCT-1.BOTTOM" and p.location == "J2" for p in w.s.positions)
        ),
    )
    if warmup.manifest["termination"] != "DECLARED_CHECKPOINT" or (
        warmup.audit.status != "PASS" or warmup.decision_audit.status != "PASS"
    ):
        raise RuntimeError("Actual preparation prefix failed")
    print("actual prefix verified", warmup.snapshot.state.time_h, flush=True)
    seed = ProductionBackend(config, run_id=warmup.snapshot.run_id, epoch=warmup.snapshot.epoch)
    seed.s, seed.events = warmup.snapshot.state, list(warmup.snapshot.events)
    start, end = seed.s.time_h, seed.s.time_h + 2
    prefix = SimulationJointProblem(
        config,
        seed.observe(),
        seed.snapshot(),
        decisions=tuple(record(d) for d in warmup.decisions),
        end_h=end,
    )
    engine = prefix.world()
    policy = OnlinePolicy(config, limits, end_h=end)
    probe = OnlineTiming(engine, policy)
    result = run(
        engine,
        Scenario(until_h=end, loaded_failure=args.loaded_failure),
        joint_policy=policy,
        continuation=True,
        prefix_decisions=warmup.decisions,
    )
    save("online-timing.json", probe.report())
    save("online-journal.json", policy.journal)
    save("online-feedback.json", probe.feedback)
    probe.close()
    save("state.json", result.snapshot.state)
    for name, records in (
        ("events", (as_data(e) for e in result.snapshot.events)),
        ("decisions", (record(d) for d in result.decisions)),
    ):
        with gzip.open(args.output / (name + ".jsonl.gz"), "wt", encoding="utf-8") as stream:
            for row in records:
                stream.write(json.dumps(row) + "\n")
    candidate_reports = []
    save(
        "online-candidates.json",
        [
            dict(
                candidate=as_data(candidate),
                observation=as_data(problem.observation),
                prefix_state=as_data(problem.prefix.state),
                prefix_event_count=len(problem.prefix.events),
                decisions=problem.decisions,
                rejected=problem.rejected,
                fixed_mode=problem.fixed_mode,
                committed=[dict(command=as_data(c), reason=r) for c, r in problem.committed],
            )
            for problem, candidate in policy.candidates
        ],
    )
    for index, (problem, candidate) in enumerate(policy.candidates):
        # This additional archived check is offline, outside the measured run.
        problem.checkpoint = lambda: None
        check = problem.verify(candidate)
        candidate_reports.append(as_data(check))
        save(f"candidate-{index}.json", candidate)
    if any(
        hashlib.sha256((root / name).read_bytes()).hexdigest() != sha
        for name, sha in sources.items()
    ):
        raise RuntimeError("SOURCE_CHANGED_DURING_MEASUREMENT")
    report = dict(
        status="PASS"
        if result.audit.status == result.decision_audit.status == "PASS"
        and candidate_reports
        and all(r["valid"] for r in candidate_reports)
        else "FAILED",
        start_h=start,
        end_h=end,
        manifest=result.manifest,
        audit=as_data(result.audit),
        decision_audit=as_data(result.decision_audit),
        candidates=candidate_reports,
        sources=sources,
        scope=(
            "SHORT_BUDGET_EXECUTED_PREFIX_NOT_FULL_PRODUCT_EFFECT"
            if limits.decision_seconds == 5 and limits.search_seconds == 0.05
            else "DIAGNOSTIC_ALLOWANCE_NOT_SHORT_BUDGET_OR_FULL_PRODUCT_EFFECT"
        ),
    )
    save("report.json", report)
    print(
        json.dumps({k: v for k, v in report.items() if k not in ("sources", "manifest")}),
        flush=True,
    )
    return report["status"] != "PASS"


if __name__ == "__main__":
    raise SystemExit(main())
