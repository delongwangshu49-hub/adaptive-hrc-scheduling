"""Compare source-bound SC mechanism witnesses under the S15 numeric tolerances."""

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def compare(light, isaac):
    from adaptive_hrc_scheduling.contracts.codec import decode
    from adaptive_hrc_scheduling.domain import production as m
    from adaptive_hrc_scheduling.production_checker import check_run

    reports = [json.loads((p / "report.json").read_text(encoding="utf-8")) for p in (light, isaac)]
    errors, maxima = [], {"time_h": 0.0, "geometry_m": 0.0, "other_numeric": 0.0}
    error_count = 0

    def error(path, reason):
        nonlocal error_count
        error_count += 1
        if len(errors) < 30:
            errors.append(dict(path=path, reason=reason))

    def same(a, b, path):
        if isinstance(a, bool) or isinstance(b, bool):
            if type(a) is not type(b) or a != b:
                error(path, "discrete value differs")
        elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
            category = (
                "geometry_m"
                if ".position[" in path or ".position_m[" in path
                else "time_h"
                if any(
                    key in path
                    for key in (
                        "time_h",
                        "_sim_h",
                        "started_h",
                        "_end_h",
                        "held_at_h",
                        "active_before_h",
                    )
                )
                else "other_numeric"
            )
            delta = abs(a - b)
            maxima[category] = max(maxima[category], delta)
            tolerance = (
                0.002 if category == "geometry_m" else 1e-8 if category == "time_h" else 1e-9
            )
            if not math.isfinite(delta) or delta > tolerance:
                error(path, f"numeric difference {delta} exceeds {tolerance}")
        elif isinstance(a, dict) and isinstance(b, dict):
            if a.keys() != b.keys():
                error(path, "field coverage differs")
            for key in a.keys() & b.keys():
                # Each run's independent audit verifies its own command digest.
                # Compare correlated command fields below with the fixed clock
                # tolerance instead of requiring equal floating-point JSON bytes.
                if key in ("wall_elapsed_s", "command_sha256"):
                    continue
                if key in ("source", "evidence_id") and (
                    ".readback" in path or ".motions[" in path
                ):
                    continue
                same(a[key], b[key], path + "." + key)
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                error(path, f"sequence length differs: {len(a)} / {len(b)}")
            for index, (x, y) in enumerate(zip(a, b)):
                same(x, y, f"{path}[{index}]")
        elif isinstance(a, str) and isinstance(b, str):
            # Run-specific identities are still compared after a bijective prefix mapping.
            if a.replace("RUN-S15", "RUN-S15-COMPARE", 1) != b.replace(
                "RUN-S15-ISAAC", "RUN-S15-COMPARE", 1
            ):
                error(path, "identity or discrete text differs")
        elif a != b:
            error(path, "value or type differs")

    for report in reports:
        if report.get("status") != "PASS" or not report.get("closed"):
            error("report", "execution did not pass and close")
    if reports[0]["sources"] != reports[1]["sources"]:
        error("sources", "source hashes differ")
    if reports[0].get("runtime") != "LIGHT_EVENT" or reports[1].get("runtime") != "KIT_APPLICATION":
        error("runtime", "expected independent light and Kit application witnesses")
    cases = []
    left = {(c["variant"], c["root"]): c for c in reports[0].get("cases", [])}
    right = {(c["variant"], c["root"]): c for c in reports[1].get("cases", [])}
    if left.keys() != right.keys() or len(left) != 12:
        error("cases", "expected both variants at all six support roots")
    for identity in sorted(left.keys() & right.keys()):
        name = "-".join(identity)
        before = error_count
        same(left[identity], right[identity], name + ".case")
        snapshots = [
            json.loads((p / name / "snapshot.json").read_text(encoding="utf-8"))
            for p in (light, isaac)
        ]
        audits = []
        for folder, snapshot in zip((light, isaac), snapshots):
            configuration = json.loads(
                (folder / name / "configuration.json").read_text(encoding="utf-8")
            )
            audit = check_run(
                decode(m.Configuration, configuration), decode(m.ExecutionSnapshot, snapshot)
            )
            audits.append(audit.status)
            if audit.status != "PASS":
                error(name + ".independent_audit", str(audit.findings[:3]))
        same(*snapshots, name + ".snapshot")
        cases.append(
            dict(
                case=name,
                events_light=len(snapshots[0]["events"]),
                events_isaac=len(snapshots[1]["events"]),
                independent_audits=audits,
                status="PASS" if error_count == before else "FAILED",
            )
        )
    return dict(
        status="PASS" if not errors else "FAILED",
        comparator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        cases=cases,
        findings=errors,
        finding_count=error_count,
        maximum_differences=maxima,
        scope="SC empty-rack mechanism fixtures only",
        exclusions=[
            "run prefix",
            "readback producer/evidence identifier",
            "wall clock",
            "byte digest of independently audited commands; command fields compared",
        ],
        production_chain_verified=False,
        rendered_frame_validation=False,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--light", type=Path, required=True)
    parser.add_argument("--isaac", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.light, args.isaac)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
    print(result["status"])
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
