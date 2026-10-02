"""Reproduce S11 synthetic cases; full candidate evidence stays in --output."""

import argparse
import importlib.util
import json
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path

from adaptive_hrc_scheduling.building_backend import BuildingBackend
from adaptive_hrc_scheduling.contracts.codec import as_data
from adaptive_hrc_scheduling.planning.decoder import Options, generate_plan

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "s11_fixture", ROOT / "scripts/build_building_contracts.py"
)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


def reproduce(output):
    cases = json.loads((ROOT / "examples/rule_planners/cases.json").read_text(encoding="utf-8"))
    rows = []
    for case in cases:
        c = generator.build_configuration(case["variant"], products=case.get("products", 1))
        if case["fixture"] == "synthetic":
            c = generator.synthetic_fixture(c)
        if case.get("overload"):
            c = replace(c, products=tuple(replace(p, mass_t=12) for p in c.products))
        opts = Options(**case["options"])
        result = generate_plan(c, BuildingBackend(c).observe()[0], opts)
        destination = output / case["id"]
        destination.mkdir(parents=True, exist_ok=True)
        evidence = asdict(result)
        (destination / "candidate.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        counts = Counter(w.reason.split(":", 1)[0] for w in result.waits)
        rows.append(
            {
                "id": case["id"],
                "status": result.status,
                "reason": result.reason,
                "expected_status": case["expected_status"],
                "assumptions": list(result.assumptions),
                "checker_status": result.report.status if result.report else "NO_CANDIDATE",
                "report_version": result.report.report_version if result.report else None,
                "commands": len(result.plan.commands) if result.plan else 0,
                "trace_end_h": result.trace.time_h if result.trace else None,
                "ready": as_data(result.plan.predicted_ready) if result.plan else None,
                "decisions": result.decisions,
                "wait_reason_counts": dict(sorted(counts.items())),
            }
        )
        if result.status != case["expected_status"]:
            raise RuntimeError(f"{case['id']}: {result.status} != {case['expected_status']}")
    summary = {
        "version": "S11-1.1",
        "scope": "STATIC_SYNTHETIC_CODE_VALIDATION",
        "industrial_qualification": "NOT_ESTABLISHED",
        "default_hr": "DISABLED",
        "gaps": ["G1", "G2", "G4", "G5", "G6", "G7"],
        "cases": rows,
    }
    return json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = reproduce(args.output)
    (args.output / "summary.json").write_text(text, encoding="utf-8")
    if args.check:
        expected = (ROOT / "examples/rule_planners/summary.json").read_text(encoding="utf-8")
        if expected != text:
            raise SystemExit("Public summary differs from generated cases")
    print("S11 cases reproduced; complete evidence written locally.")


if __name__ == "__main__":
    main()
