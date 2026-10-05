"""Stream and independently audit source-bound S15 chain comparisons."""

import argparse
import gzip
import hashlib
import json
import math
import sys
from itertools import zip_longest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def compare(light, isaac, audit_source_root=ROOT):
    sys.path.insert(0, str(audit_source_root / "src"))
    from adaptive_hrc_scheduling.contracts.codec import decode
    from adaptive_hrc_scheduling.contracts.production import digest
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
            error("report", "witness did not meet its declared exit and close")
    if reports[0]["sources"] != reports[1]["sources"]:
        error("sources", "source hashes differ")
    audit_sources = {}
    for name, expected in reports[0]["sources"].items():
        if name.startswith("src/") and name.endswith(".py"):
            actual = hashlib.sha256((audit_source_root / name).read_bytes()).hexdigest()
            audit_sources[name] = actual
            if actual != expected:
                error("audit_source." + name, "audit implementation differs from captured source")
    if [r.get("runtime") for r in reports] != ["LIGHT_EVENT", "KIT_APPLICATION"]:
        error("runtime", "requires light and actual Kit application")
    same(reports[0]["manifest"]["scenario"], reports[1]["manifest"]["scenario"], "scenario")
    configurations = [
        json.loads((p / "configuration.json").read_text(encoding="utf-8")) for p in (light, isaac)
    ]
    same(*configurations, "configuration")
    states = [json.loads((p / "state.json").read_text(encoding="utf-8")) for p in (light, isaac)]
    same(*states, "state")
    counts = {}
    for filename in ("events.jsonl.gz", "decisions.jsonl.gz"):
        with (
            gzip.open(light / filename, "rt", encoding="utf-8") as left,
            gzip.open(isaac / filename, "rt", encoding="utf-8") as right,
        ):
            count = 0
            for count, pair in enumerate(zip_longest(left, right), 1):
                if None in pair:
                    error(filename, "sequence length differs")
                    continue
                same(*(json.loads(line) for line in pair), f"{filename}[{count}]")
            counts[filename] = count

    class EventStream:
        def __init__(self, path):
            self.path = path
            self.last = None

        def __iter__(self):
            with gzip.open(self.path, "rt", encoding="utf-8") as stream:
                for line in stream:
                    self.last = decode(m.ExecutionEvent, json.loads(line))
                    yield self.last

        def __bool__(self):
            return self.last is not None

        def __getitem__(self, index):
            if index != -1 or self.last is None:
                raise IndexError(index)
            return self.last

    audits = []
    backpressure_witnesses = []
    for folder, report, config, state in zip((light, isaac), reports, configurations, states):
        config = decode(m.Configuration, config)
        if digest(config) != report["manifest"]["config_sha256"]:
            error("configuration", "manifest digest differs")
        events = EventStream(folder / "events.jsonl.gz")
        with gzip.open(events.path, "rt", encoding="utf-8") as stream:
            first = json.loads(next(stream))
        snapshot = m.ExecutionSnapshot(
            first["schema_version"],
            first["config_id"],
            first["config_sha256"],
            first["run_id"],
            first["epoch"],
            decode(m.State, state),
            events,
        )
        audit = check_run(config, snapshot)
        audits.append(audit.status)
        if audit.status != "PASS":
            error("independent_audit", str(audit.findings[:5]))
        if report["manifest"]["scenario"]["id"] == "B2_SUPPLEMENTAL_960":
            from adaptive_hrc_scheduling.control.production_loop import Scenario, validate_scenario
            from adaptive_hrc_scheduling.production_witness import buffer_backpressure

            validate_scenario(config, Scenario(**report["manifest"]["scenario"]))
            with gzip.open(folder / "decisions.jsonl.gz", "rt", encoding="utf-8") as stream:
                decisions = [json.loads(line) for line in stream]
            witness = buffer_backpressure(
                config,
                EventStream(folder / "events.jsonl.gz"),
                (
                    (d["sampled_h"], bool(d["plan"]["commands"]), d["plan"]["reason"])
                    for d in decisions
                ),
            )
            backpressure_witnesses.append(witness)
            if (
                witness is None
                or sum(p.received_h is not None for p in snapshot.state.products) != 3
            ):
                error("WV01_coverage", "requires positive buffer backpressure and three receptions")
            same(witness, report.get("buffer_backpressure"), "buffer_backpressure_report")
    return dict(
        status="PASS" if not error_count else "FAILED",
        comparator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        independent_audits=audits,
        buffer_backpressure_witnesses=backpressure_witnesses,
        audit_source_sha256=audit_sources,
        compared_records=counts,
        findings=errors,
        finding_count=error_count,
        maximum_differences=maxima,
        scenario=reports[0]["manifest"]["scenario"],
        config_sha256=reports[0]["manifest"]["config_sha256"],
        scope="declared scenario only; no full S15 verdict",
        S15_complete=False,
        exclusions=[
            "run prefix",
            "readback producer/evidence identifier",
            "wall clock",
            "byte digest of independently audited commands; command fields compared",
        ],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--light", type=Path, required=True)
    parser.add_argument("--isaac", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit-source-root", type=Path, default=ROOT)
    args = parser.parse_args()
    result = compare(args.light, args.isaac, args.audit_source_root)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
    print(result["status"])
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
