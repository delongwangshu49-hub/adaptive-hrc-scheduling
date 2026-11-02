"""Pack or replay derived P07 measurement features without private archives."""

import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from adapters import people_metrics, require
from cancellation import build as build_cancellation
from export import validate_pair
from load import ROOT, UNITS, csv_write, install_private_guard, pin, read, sha, write
from tables import build as build_tables
from validation_engine import run as validate_dataset

AUXILIARY = (
    "e20.json",
    "e20_order_details.json",
    "e20_orders.csv",
    "e20_plan_changes.csv",
    "e20_requests.csv",
    "e20_timeline.csv",
    "attempts.json",
    "attempts.csv",
    "cancellation_inputs.json",
)


def result_digest(value):
    value = dict(value)
    value.pop("cache_pin", None)
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def pack(destination):
    data = ROOT / "results/p07/r3"
    require(read(data / "validation.json")["status"] == "PASS", "PACK_REQUIRES_VALIDATION")
    validation = read(data / "validation.json")
    for item in validation["inputs"] + list(validation["source_code"].values()):
        require(sha(ROOT / item["path"]) == item["sha256"], "PACK_VALIDATION_STALE:" + item["path"])
    for source, name in [
        (ROOT / "results/p07/cache/manifest.json", "inventory.json"),
        (ROOT / "results/p07/e20_order_details.json", "e20-reference.json"),
    ]:
        target = destination / name
        if target.exists():
            require(sha(target) == sha(source), "IMMUTABLE_REFERENCE_CHANGED")
        else:
            shutil.copyfile(source, target)
    inputs = destination / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "results/p07/cache/runs/metadata.json", inputs / "metadata.json")
    records = []
    for unit in UNITS:
        source = ROOT / "results/p07/cache/runs" / f"{unit}.json"
        dest = inputs / f"{unit}.json.gz"
        with (
            source.open("rb") as f,
            dest.open("wb") as raw,
            gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as out,
        ):
            shutil.copyfileobj(f, out, length=1024 * 1024)
        records.append(
            dict(
                unit=unit,
                file=dest.name,
                sha256=sha(dest),
                uncompressed_source_sha256=sha(source),
                bytes=dest.stat().st_size,
                expected_result_sha256=result_digest(
                    read(data / "computed" / f"{unit}.json", limit=80_000_000)
                ),
            )
        )
    aux = destination / "auxiliary"
    aux.mkdir(exist_ok=True)
    for name in AUXILIARY:
        shutil.copyfile(data / name, aux / name)
    dynamic = data / "dynamic_people.json"
    with (
        dynamic.open("rb") as f,
        (aux / "dynamic_people.json.gz").open("wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as out,
    ):
        shutil.copyfileobj(f, out)
    archive = aux / "dual-domain.zip"
    source = data / "exports"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in sorted(source.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(source).as_posix())
    write(
        destination / "manifest.json",
        dict(
            format="P07-DERIVED-MEASUREMENT-INPUTS-1",
            classification="COMPACT_DERIVED_FEATURES; NOT_ORIGINAL_FULL_STATE_OR_RAW_EXECUTION_LOGS",
            inputs=records,
            metadata=pin(inputs / "metadata.json"),
            inventory=pin(destination / "inventory.json"),
            E20_reference=pin(destination / "e20-reference.json"),
            auxiliary=[
                dict(file=p.name, sha256=sha(p), bytes=p.stat().st_size)
                for p in sorted(aux.iterdir())
            ],
            private_locator_policy="Any .local provenance locator identifies original private evidence only; replay reads the supplied files, never these locators.",
            original_source_scope="Source versions and original actual exits retained; no newly executed production",
            packing_script=pin(Path(__file__)),
        ),
    )
    print(
        json.dumps(
            dict(
                status="PORTABLE_MEASUREMENT_INPUTS_READY",
                runs=len(records),
                compressed_run_bytes=sum(r["bytes"] for r in records),
            )
        )
    )


def replay(inputs, output, figures=False):
    m = read(inputs / "manifest.json")
    require(m["format"] == "P07-DERIVED-MEASUREMENT-INPUTS-1", "PORTABLE_FORMAT")
    require(
        sha(inputs / "inputs/metadata.json") == m["metadata"]["sha256"], "PORTABLE_METADATA_HASH"
    )
    for r in m["inputs"]:
        require(sha(inputs / "inputs" / r["file"]) == r["sha256"], "PORTABLE_INPUT_HASH")
    for r in m["auxiliary"]:
        require(sha(inputs / "auxiliary" / r["file"]) == r["sha256"], "PORTABLE_AUXILIARY_HASH")
    for key, name in [("inventory", "inventory.json"), ("E20_reference", "e20-reference.json")]:
        require(sha(inputs / name) == m[key]["sha256"], "PORTABLE_SOURCE_REFERENCE_HASH:" + name)
    require(not output.exists() or not any(output.iterdir()), "REPLAY_OUTPUT_MUST_BE_NEW_OR_EMPTY")
    output.mkdir(parents=True, exist_ok=True)
    install_private_guard(output)
    env = dict(
        os.environ,
        P07_REPLAY_ALLOWED_OUTPUT=str(output.resolve()),
        MPLCONFIGDIR=str((output / "matplotlib-cache").resolve()),
    )
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "analysis/p07/build_results.py"),
            "--cache",
            str(inputs / "inputs"),
            "--output",
            str(output),
        ],
        check=True,
        env=env,
    )
    for name in AUXILIARY:
        shutil.copyfile(inputs / "auxiliary" / name, output / name)
    for r in m["inputs"]:
        require(
            result_digest(read(output / "computed" / f"{r['unit']}.json", limit=80_000_000))
            == r["expected_result_sha256"],
            "PORTABLE_ALL_RESULT_VALUES_MATCH_ORIGINAL_ANALYSIS",
        )
    dynamic = read(inputs / "auxiliary/dynamic_people.json.gz", limit=40_000_000)
    for case in dynamic:
        d = case["reproduction_input"]
        people, activity, intervals = people_metrics(
            d["configuration"], d["state"], d["changes"], d["generations"], d["rates"]
        )
        expected = {r["person_id"]: r for r in case["people"]}
        for row in people:
            require(
                all(row[k] == expected[row["person_id"]][k] for k in row),
                "PORTABLE_DYNAMIC_RECOMPUTATION",
            )
    write(output / "dynamic_people.json", dynamic)
    for key, name in [
        ("people", "dynamic_people"),
        ("activity", "dynamic_activity"),
        ("intervals", "dynamic_intervals"),
        ("changes", "dynamic_people_events"),
    ]:
        csv_write(output / f"{name}.csv", [r for case in dynamic for r in case[key]])
    export_dir = output / "exports"
    export_dir.mkdir(exist_ok=True)
    with zipfile.ZipFile(inputs / "auxiliary/dual-domain.zip") as z:
        for info in z.infolist():
            rel = Path(info.filename)
            require(not rel.is_absolute() and ".." not in rel.parts, "ZIP_MEMBER_PATH")
        z.extractall(export_dir)
    for name in ("normal", "dynamic", "kit"):
        validate_pair(
            read(export_dir / name / "gantt.json", limit=40_000_000),
            read(export_dir / name / "scene-domain.json"),
        )
    build_cancellation(output / "cancellation_inputs.json", inputs / "inputs", output)
    build_tables(output, inputs / "inputs")
    result = validate_dataset(
        inputs / "inputs", output, inputs / "inventory.json", inputs / "e20-reference.json"
    )
    result.update(
        scope="PORTABLE_DERIVED_MEASUREMENT_RECOMPUTATION_NOT_NEW_PRODUCTION",
        source_manifest=pin(inputs / "manifest.json"),
    )
    write(output / "validation.json", result)
    if figures:
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "analysis/p07/figures.py"),
                "--data",
                str(output),
                "--output",
                str(output / "figures"),
            ],
            check=True,
            env=env,
        )
    print(
        json.dumps(
            dict(
                status="PORTABLE_REPLAY_PASS",
                private_original_archive_reads_forbidden_by_audit_hook=True,
                new_production_runs=0,
                new_kit_runs=0,
            )
        )
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("pack", "replay"))
    p.add_argument("--inputs", type=Path, default=ROOT / "examples/reproduction/p07/r3")
    p.add_argument("--output", type=Path, default=ROOT / ".local/p07-replay")
    p.add_argument("--figures", action="store_true")
    a = p.parse_args()
    pack(a.inputs) if a.action == "pack" else replay(a.inputs, a.output, a.figures)


if __name__ == "__main__":
    main()
