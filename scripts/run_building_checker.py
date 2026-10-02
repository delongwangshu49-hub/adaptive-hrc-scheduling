"""Reproduce S10 fixed evidence and compact public summaries.

The C05 script only generates test evidence; checker.py imports no executor.
Full input traces are written only to the explicitly supplied output directory.
This is not a scheduler or an industrial qualification demonstration.
"""

import argparse
import importlib.util
import json
from dataclasses import asdict, replace
from pathlib import Path

from adaptive_hrc_scheduling.checker import check_run

ROOT = Path(__file__).resolve().parents[1]


def write(path, data):
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def run(output):
    spec = importlib.util.spec_from_file_location(
        "s10_fixed_witness", ROOT / "scripts/run_building_witness.py"
    )
    witness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(witness)
    output.mkdir(parents=True, exist_ok=True)
    summary = {
        "report_version": "S10-1.1",
        "scope": "SYNTHETIC_TEST_ONLY",
        "industrial_qualification": "NOT_ESTABLISHED",
        "normal": [],
        "counterexamples": [],
    }
    for variant in ("SR-W1", "SR-W2"):
        world = witness.run_chain(variant=variant)
        world.advance(world.time + 1)
        witness.fact(world, "RECEIVED", "PRODUCT-1")
        world.advance(240)
        result = check_run(world.config, world.s)
        write(
            output / (variant + "-input.json"),
            {"configuration": asdict(world.config), "snapshot": asdict(world.s)},
        )
        write(output / (variant + "-report.json"), result.to_dict())
        if result.status != "PASS":
            raise RuntimeError(variant + ": " + result.status)
        stable_metrics = dict(result.metrics)
        stable_metrics.pop("checker_wall_ms")
        summary["normal"].append(
            {
                "variant": variant,
                "status": result.status,
                "metrics": stable_metrics,
                "rule_scope": result.rule_scope,
            }
        )
        if variant == "SR-W1":
            false_ready = replace(world.s, products=(replace(world.s.products[0], ready_h=1),))
            missing = replace(world.s, events=world.s.events[1:])
            for name, mutated, fragment in (
                ("false_ready", false_ready, {"products[0].ready_h": 1}),
                ("missing_first_event", missing, {"removed_event": asdict(world.s.events[0])}),
            ):
                report = check_run(world.config, mutated)
                write(output / (name + "-report.json"), report.to_dict())
                if report.status == "PASS":
                    raise RuntimeError("Mutation not detected: " + name)
                summary["counterexamples"].append(
                    {
                        "name": name,
                        "mutation_fragment": fragment,
                        "status": report.status,
                        "first_findings": [asdict(f) for f in report.findings[:3]],
                    }
                )
    write(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Local evidence directory; full raw traces must not be published",
    )
    args = parser.parse_args()
    result = run(args.output)
    print(
        json.dumps(
            {
                "normal": [r["status"] for r in result["normal"]],
                "counterexamples": [r["status"] for r in result["counterexamples"]],
            }
        )
    )


if __name__ == "__main__":
    main()
