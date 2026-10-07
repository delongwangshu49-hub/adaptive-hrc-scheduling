"""S17 local test injection into the unchanged S15 driver; no new Kit claims."""

import argparse
import functools
import json
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

from build_production_contracts import Builder

from adaptive_hrc_scheduling.algorithms.lns import Options, fingerprint, search
from adaptive_hrc_scheduling.algorithms.production_lns import ProductionProblem
from adaptive_hrc_scheduling.contracts import codec
from adaptive_hrc_scheduling.contracts.codec import as_data
from adaptive_hrc_scheduling.control import production_loop as loop
from adaptive_hrc_scheduling.control.production_decisions import record
from adaptive_hrc_scheduling.production_backend import ProductionBackend


def run(output):
    OUT = output
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for variant in ("SR-W1", "SR-W2"):
        config = Builder(variant=variant, synthetic=True).configuration()

        def progress(backend, stage):
            if stage == "before_audit":
                print(variant, stage, len(backend.events), backend.s.time_h, flush=True)

        baseline = loop.run(
            ProductionBackend(config), loop.Scenario(until_h=720), execution_hook=progress
        )
        print(variant, "BASELINE", baseline.manifest, flush=True)
        assert baseline.audit.status == "PASS" and baseline.decision_audit.status == "PASS"
        assert baseline.manifest["termination"] == "OPERATIONS_COMPLETE"
        world = ProductionBackend(config)
        past = []
        searches = []
        original = loop.choose

        def dispatch(config, value, **kwargs):
            if past:
                d = past[-1]
                if d.plan.commands:
                    cmd = d.plan.commands[0]
                    receipt = next(
                        e
                        for e in reversed(world.events)
                        if e.command_id == cmd.id and e.kind in ("STARTED", "REJECTED", "DEFERRED")
                    )
                    d.receipt_id = receipt.id
            if len(searches) < 12:
                began = perf_counter()
                problem = ProductionProblem(
                    config,
                    value,
                    world.snapshot(),
                    decisions=tuple(record(d) for d in past),
                    sequence=kwargs["sequence"],
                    rejected=kwargs["excluded_operations"],
                )
                result = search(
                    problem,
                    Options(seed=17, iterations=2, repair_trials=2, wall_seconds=60, stagnation=2),
                )
                assert result.status == "FEASIBLE" and problem.verify(result.best).valid
                plan = result.best
                searches.append(
                    asdict(result) | {"total_call_wall_seconds": perf_counter() - began}
                )
                print(
                    variant,
                    "LNS",
                    len(searches),
                    result.initial_score,
                    result.best_score,
                    result.termination,
                    flush=True,
                )
            else:
                plan = original(config, value, **kwargs)
            past.append(
                SimpleNamespace(
                    observation=value.observation,
                    plan=plan,
                    rejected_parents=tuple(sorted(kwargs["excluded_operations"])),
                    receipt_id=None,
                )
            )
            return plan

        with patch.object(loop, "choose", dispatch):
            actual = loop.run(world, loop.Scenario(until_h=720), execution_hook=progress)
        assert actual.audit.status == "PASS" and actual.decision_audit.status == "PASS"
        assert actual.manifest["termination"] == "OPERATIONS_COMPLETE"
        assert actual.manifest["received"] == 1
        detail = {
            "config_sha256": baseline.manifest["config_sha256"],
            "baseline": baseline.manifest,
            "intervention": actual.manifest,
            "searches": searches,
            "baseline_snapshot_sha256": fingerprint(baseline.snapshot),
            "lns_snapshot_sha256": fingerprint(actual.snapshot),
        }
        (OUT / (variant + ".json")).write_text(
            json.dumps(detail, indent=2) + "\n", encoding="utf-8"
        )
        (OUT / (variant + "-baseline-snapshot.json")).write_text(
            json.dumps(as_data(baseline.snapshot)) + "\n", encoding="utf-8"
        )
        (OUT / (variant + "-lns-snapshot.json")).write_text(
            json.dumps(as_data(actual.snapshot)) + "\n", encoding="utf-8"
        )
        (OUT / (variant + "-decisions.json")).write_text(
            json.dumps([record(d) for d in actual.decisions]) + "\n", encoding="utf-8"
        )
        row = {
            "variant": variant,
            "config_sha256": detail["config_sha256"],
            "lns_calls": len(searches),
            "search_iterations": sum(len(s["history"]) for s in searches),
            "baseline_time_h": baseline.manifest["time_h"],
            "lns_time_h": actual.manifest["time_h"],
            "baseline_completed": baseline.manifest["completed_static_operations"],
            "lns_completed": actual.manifest["completed_static_operations"],
            "operations": len(config.operations),
            "ready": actual.manifest["ready"],
            "received": actual.manifest["received"],
            "baseline_audit": baseline.audit.status,
            "lns_audit": actual.audit.status,
            "baseline_decision_audit": baseline.decision_audit.status,
            "lns_decision_audit": actual.decision_audit.status,
            "baseline_exposure": asdict(baseline.audit.metrics),
            "lns_exposure": asdict(actual.audit.metrics),
            "same_config": True,
            "scope": "12_CURRENT_WINDOW_LNS_CALLS_THEN_UNCHANGED_EDD",
        }
        rows.append(row)
        print(variant, "DONE", row, flush=True)
    (OUT / "summary.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")

    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # Only immutable dataclass annotations are cached. Every data decode,
    # contract check, admission, state reconstruction and audit still executes.
    original = codec.get_type_hints
    with patch.object(codec, "get_type_hints", functools.lru_cache(maxsize=None)(original)):
        run(args.output)
