"""Export already audited same-observation Gantt and scene-domain data."""

import json
import shutil
from collections import Counter
from pathlib import Path

from adapters import require
from load import ROOT, csv_write, pin, read, sha, write

CASES = {
    "normal": ".local/p063-execution-20261101-r1/audits/normal",
    "dynamic": ".local/p063-execution-20261101-r1/audits/dynamic",
    "kit": ".local/p063-execution-20261101-r1/audits/kit",
}
IDENTITY_FIELDS = (
    "run_id",
    "epoch",
    "run_spec_sha256",
    "initial_config_sha256",
    "catalog_hash",
    "catalog_version",
    "state_revision",
    "observation_id",
    "event_count",
    "event_prefix_hash",
)


def validate_pair(view, scene):
    a, b = view["envelope"], scene["envelope"]
    require(
        all(k in a and k in b and a[k] == b[k] for k in IDENTITY_FIELDS),
        "DUAL_DOMAIN_OBSERVATION_IDENTITY",
    )
    require(
        not view["writable"] and not view["forecast_audit_pending"], "OFFLINE_READ_ONLY_AUDITED"
    )
    require(
        scene["scope"]
        in (
            "RECONSTRUCTED_DOMAIN_STATE_NOT_NEW_NATIVE_RENDER",
            "SAVED_KIT_DOMAIN_STATE_NOT_NEW_NATIVE_RENDER",
        ),
        "DOMAIN_RENDER_SCOPE",
    )
    for key in ("people", "devices", "full_schedule"):
        require(key in scene and view[key] == scene[key], "DUAL_DOMAIN_DATA:" + key)
    if "orders" in scene:
        require(view["orders"] == scene["orders"], "DUAL_DOMAIN_DATA:orders")
    else:
        require(
            scene["scope"] == "SAVED_KIT_DOMAIN_STATE_NOT_NEW_NATIVE_RENDER",
            "DOMAIN_ORDER_FIELD_REQUIRED",
        )
        delivered = scene["observation"]["state"]["products"]
        require(
            {p["id"] for p in view["orders"]} == {p["product_id"] for p in delivered},
            "LEGACY_KIT_OBSERVED_PRODUCT_COVERAGE",
        )
    row_ids = [r["row_id"] for r in view["rows"]]
    require(len(row_ids) == len(set(row_ids)), "EXPORTED_ROW_DUPLICATE")
    return {k: a[k] for k in IDENTITY_FIELDS}


def export_case(name, source, output):
    view = read(source / "desktop-view.json", limit=40_000_000)
    scene = read(source / "scene-domain-projection.json")
    identity = validate_pair(view, scene)
    output.mkdir(parents=True, exist_ok=True)
    files = []
    cache_name = "saved-presentation-cache.json" if name == "kit" else "presentation-cache.json"
    for original, new in [
        ("desktop-view.json", "gantt.json"),
        ("scene-domain-projection.json", "scene-domain.json"),
        (cache_name, "presentation-cache.json"),
    ]:
        src, dest = source / original, output / new
        if dest.exists() and sha(dest) != sha(src):
            raise ValueError("EXPORT_WOULD_REPLACE_DIFFERENT_BYTES:" + str(dest))
        if not dest.exists():
            shutil.copyfile(src, dest)
        require(sha(src) == sha(dest), "EXACT_EXPORT_COPY")
        files.append(dict(original=pin(src), export=pin(dest)))
    csv_write(output / "gantt-rows.csv", view["rows"])
    for key in ("orders", "people", "devices"):
        rows = view[key]
        if isinstance(rows, dict):
            rows = [
                dict(id=k, **v) if isinstance(v, dict) else dict(id=k, value=v)
                for k, v in rows.items()
            ]
        csv_write(output / f"{key}.csv", rows)
    return dict(
        case=name,
        identity=identity,
        rows=len(view["rows"]),
        total_gantt_rows=len(view["rows"]),
        planned_full_schedule_rows=sum(
            r["row_kind"] == "FULL_PLAN" and r["schedule_state"] == "PLANNED" for r in view["rows"]
        ),
        row_counts_by_state=dict(Counter(r["schedule_state"] for r in view["rows"])),
        row_counts_by_kind=dict(Counter(r["row_kind"] for r in view["rows"])),
        status="EXACT_SOURCE_COPY_AND_SAME_OBSERVATION",
        legacy_order_binding="DIRECT_ORDER_PAYLOAD"
        if "orders" in scene
        else "OBSERVATION_PRODUCT_IDENTITIES; ORDER_DEFINITIONS_IN_COMPANION_GANTT",
        scope="COMPLETE_NORMAL_CPU" if name == "normal" else "LOCAL_STOPPED_ARCHIVE",
        native_render_created=False,
        age_semantics="ORIGINAL_STALE_READ_ONLY_PRESERVED",
        files=files,
    )


def main():
    outputs = [
        export_case(name, ROOT / path, ROOT / "results/p07/r3/exports" / name)
        for name, path in CASES.items()
    ]
    write(
        ROOT / "results/p07/r3/exports/manifest.json",
        dict(
            format="P07-DUAL-DOMAIN-EXPORT-1",
            cases=outputs,
            source_code=pin(Path(__file__)),
            new_kit_runs=0,
            synchronized_native_screenshot_claim=False,
        ),
    )
    print(
        json.dumps(
            dict(
                status="DUAL_DOMAIN_EXPORTED", cases=len(outputs), rows=[r["rows"] for r in outputs]
            )
        )
    )


if __name__ == "__main__":
    main()
