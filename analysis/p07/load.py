"""Bounded input inventory and content identities for saved P07 evidence."""

import argparse
import csv
import gzip
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
P053 = Path(".local/p053-execution-20261028-r2")
UNITS = (
    "N-CPU-EDD",
    "N-CPU-ADAPTIVE",
    "H-CPU-EDD",
    "H-CPU-ADAPTIVE",
    "F-CPU-EDD",
    "F-CPU-ADAPTIVE",
    "U-CPU-EDD-r3",
    "U-CPU-ADAPTIVE-r3",
    "C-STOCK-CPU-EDD-r4",
    "C-STOCK-CPU-ADAPTIVE-r4",
    "M-H-N",
    "M-H-H",
)


def install_private_guard(output):
    """Make portable replay fail on any original private-archive file read."""
    private = (ROOT / ".local").resolve()
    allowed = [Path(output).resolve(), Path(sys.prefix).resolve()]

    def guard(event, args):
        if event != "open" or not args or not isinstance(args[0], (str, bytes, os.PathLike)):
            return
        path = Path(os.fsdecode(args[0])).resolve()
        if path.is_relative_to(private) and not any(path.is_relative_to(p) for p in allowed):
            raise PermissionError("P07_PORTABLE_REPLAY_PRIVATE_ARCHIVE_READ_FORBIDDEN")

    sys.addaudithook(guard)


if os.environ.get("P07_REPLAY_ALLOWED_OUTPUT"):
    install_private_guard(os.environ["P07_REPLAY_ALLOWED_OUTPUT"])


def read(path, limit=8_000_000):
    path = Path(path)
    if path.stat().st_size > limit:
        raise ValueError(f"BOUNDED_JSON_REQUIRED:{path.name}")
    if path.suffix == ".gz":
        with gzip.open(path, "rb") as f:
            data = f.read(limit + 1)
        if len(data) > limit:
            raise ValueError("DECOMPRESSED_JSON_LIMIT:" + path.name)
        return json.loads(data)
    return json.loads(path.read_bytes())


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def csv_write(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", encoding="utf-8", newline="") as stream:
        out = csv.DictWriter(stream, fieldnames=keys)
        out.writeheader()
        for row in rows:
            out.writerow(
                {
                    k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                    for k, v in row.items()
                }
            )


def pin(path, root=ROOT):
    path = Path(path)
    if not path.is_absolute():
        path = root / path
    return dict(path=path.relative_to(root).as_posix(), bytes=path.stat().st_size, sha256=sha(path))


def inventory(root=ROOT):
    units = []
    coverage = []
    for unit in UNITS:
        ap = root / P053 / f"{unit}-analysis.json"
        a = read(ap)
        source = root / a["source_path"]
        if source.stat().st_size != a["source_bytes"]:
            raise ValueError("SOURCE_SIZE_CHANGED:" + unit)
        independent = root / a["independent_path"]
        if sha(independent) != a["independent_sha256"]:
            raise ValueError("INDEPENDENT_IDENTITY_CHANGED:" + unit)
        folder = root / P053 / "runs" / unit
        ep = root / P053 / f"{unit}-exit.json"
        if read(ep)["exit_code"] != 0:
            raise ValueError("SELECTED_ACTUAL_EXIT_NONZERO:" + unit)
        event_path = folder / "events.jsonl.gz"
        event_format = "JSONL_GZIP"
        if not event_path.exists():
            event_path = source
            event_format = "SNAPSHOT_EVENTS_ARRAY"
        units.append(
            dict(
                unit=unit,
                scenario=unit[0] if not unit.startswith("M-") else "MECHANISM",
                method="ADAPTIVE"
                if "ADAPTIVE" in unit
                else "H"
                if unit.startswith("M-")
                else "EDD",
                source_family="P053-c2" if unit[0] in "UC" else "P053-c1",
                analysis=pin(ap, root),
                independent=pin(independent, root),
                source=dict(
                    path=source.relative_to(root).as_posix(),
                    bytes=source.stat().st_size,
                    expected_sha256=a["source_sha256"],
                ),
                configuration=pin(folder / "configuration.json", root),
                events=dict(pin(event_path, root), format=event_format),
                exit=pin(ep, root),
                available_fields=list(a),
                extraction_status="PENDING_RAW_EVENT_FEATURE_EXTRACTION",
            )
        )
        coverage.append(
            dict(
                input_class="FIXED_RESEARCH",
                unit=unit,
                small_analysis=True,
                dynamic_presence=False,
                raw_event_file=True,
                need="event features, full activity intervals, cost attribution",
            )
        )
    extra = [
        ("DYNAMIC_PEOPLE", ".local/p043-20261023/cpu-formal-r2/session-state.json"),
        ("DYNAMIC_PEOPLE", ".local/p043-20261023/kit-formal-r3/session-state.json"),
        ("DYNAMIC_ORDER_AND_E20", "docs/delivery/p061_event_chain_trace_r1.json"),
        ("FAILURE_CENSOR", "docs/delivery/p053_failure_index_r2.json"),
        ("DUAL_DOMAIN", "docs/delivery/p063_reproduction_r1.json"),
        ("RECOVERY", "docs/delivery/p062_recovery_continuity_r1.json"),
    ]
    for kind, path in extra:
        coverage.append(
            dict(
                input_class=kind,
                path=path,
                exists=(root / path).exists(),
                status="LOCATED" if (root / path).exists() else "LOCATE_EXACT_LAYOUT",
            )
        )
    return dict(
        identity="P07-INPUT-INVENTORY-r1",
        at=datetime.now(timezone.utc).isoformat(),
        units=units,
        field_coverage=coverage,
        mechanism_aliases={"M-HR-N": "N-CPU-EDD", "M-HR-H": "H-CPU-EDD"},
        new_production_runs=0,
        new_kit_runs=0,
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--output", type=Path, default=ROOT / "results/p07/cache/manifest.json")
    args = p.parse_args()
    result = inventory(args.root)
    write(args.output, result)
    print(
        json.dumps(
            dict(
                status="INVENTORY_COMPLETE",
                units=len(result["units"]),
                classes=sorted({r["input_class"] for r in result["field_coverage"]}),
            )
        )
    )


if __name__ == "__main__":
    main()
