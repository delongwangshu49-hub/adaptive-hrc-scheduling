"""Audit saved P06.3 cases and rebuild the final read-only desktop projections.

Use an isolated interpreter containing the candidate wheel. The checker and
desktop source directories are explicit companion inputs, never package sources.
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import adaptive_hrc_scheduling
from adaptive_hrc_scheduling.contracts.session import digest
from adaptive_hrc_scheduling.timeline import compare_envelopes


def verify(directory, output, checkers, desktop):
    package = Path(adaptive_hrc_scheduling.__file__).resolve()
    if not package.is_relative_to(Path(sys.prefix).resolve()):
        raise ValueError("INSTALLED_CANDIDATE_REQUIRED")
    sys.path[:0] = [
        str(checkers.resolve()),
        *(str(path.resolve()) for path in desktop),
        str(Path(__file__).resolve().parent),
    ]
    from p051_desktop.client import Client
    from p063_exact_audit_cache import ExactAuditCache, replay_client
    from p063_schedule_bindings import validate_archive
    from verify_full_schedule_session import verify as verify_plans
    from verify_lifecycle_session import verify as verify_lifecycle

    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()

    def read(name):
        return json.loads((directory / name).read_bytes())

    def save(name, data):
        (output / name).write_text(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
        )

    # Delivered references need their own binding even when immutable proofs
    # are already audited. Reject missing/mismatched references before caching.
    bindings = validate_archive(directory)
    cache = ExactAuditCache(verify_lifecycle, output / "lifecycle-progress.json")
    lifecycle = cache.verify(directory)
    save("lifecycle-independent.json", lifecycle)
    plans = verify_plans(directory)
    save("plans-independent.json", plans)
    client = Client(directory, writable=False)
    try:
        # The unchanged checker above already verified every adopted full proof.
        # Reuse only those exact hashed plans for display, without a second audit.
        for checksum, plan in bindings.plans.items():
            if digest(plan) != checksum:
                raise ValueError("VERIFIED_DISPLAY_PLAN_CHANGED")
            client.schedules.verified[checksum] = plan
        view = replay_client(client)
        if client.error:
            raise ValueError("DESKTOP_RECONSTRUCTION:" + str(client.error))
        latest = read("timeline-latest.json")
        if {r["row_id"]: r for r in latest["rows"]} != client.consumer.rows:
            raise ValueError("LATEST_ROW_RECONSTRUCTION")
        if latest["packet_sha256"] != client.consumer.previous:
            raise ValueError("LATEST_PACKET_RECONSTRUCTION")
        if latest["envelope"] != client.consumer.envelope:
            raise ValueError("LATEST_ENVELOPE_RECONSTRUCTION")
        if view["writable"] or view["forecast_audit_pending"]:
            raise ValueError("OFFLINE_VIEW_MUST_BE_READ_ONLY_AND_AUDITED")
        schedule_binding = bindings.check_projection(view)
        save("schedule-binding-independent.json", schedule_binding)
        # The 3D adapter and the Gantt consume this same delivered observation.
        # This is a domain projection, not a new rendered/native Kit frame.
        observation = client.packet["source"]["observation"]
        scene = dict(
            scope="RECONSTRUCTED_DOMAIN_STATE_NOT_NEW_NATIVE_RENDER",
            envelope=client.consumer.envelope,
            observation=observation,
            people=client.packet["people"],
            devices=client.packet["devices"],
            orders=client.packet["orders"],
            full_schedule=client.packet["full_schedule"],
        )
        relation = compare_envelopes(view["envelope"], scene["envelope"])
        if relation != "SAME_OBSERVATION":
            raise ValueError("REBUILT_DUAL_VIEW_IDENTITY")
        save("desktop-view.json", view)
        save("scene-domain-projection.json", scene)
        stable = {
            key: view[key]
            for key in (
                "envelope",
                "rows",
                "orders",
                "people",
                "devices",
                "catalog",
                "workforce_statistics",
                "business_results",
                "full_schedule",
            )
        }
        repeated = client.project_snapshot()
        if stable != {key: repeated[key] for key in stable}:
            raise ValueError("DISPLAY_RECONSTRUCTION_NOT_STABLE")
        save("deterministic-display-data.json", stable)
        save(
            "presentation-cache.json",
            dict(
                format="P063-SAVED-PRESENTATION-CACHE-1",
                envelope_sha256=digest(view["envelope"]),
                colors=client.colors.cache,
                numbers=client.colors.numbers,
            ),
        )
        commit = read("final-commit.json")
        if any(
            hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected
            for name, expected in commit["projection_files"].items()
        ):
            raise ValueError("COMMITTED_PROJECTION_BYTES")
        origins = []
        companion_origins = []
        companion_roots = [
            checkers.resolve(),
            *(path.resolve() for path in desktop),
            Path(__file__).resolve().parent,
        ]
        for name, module in sorted(sys.modules.items()):
            if name.startswith("adaptive_hrc_scheduling") and getattr(module, "__file__", None):
                path = Path(module.__file__).resolve()
                if not path.is_relative_to(package.parent):
                    raise ValueError("CANDIDATE_MODULE_SHADOWED:" + name)
                origins.append(
                    dict(
                        module=name,
                        path=str(path),
                        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    )
                )
            elif getattr(module, "__file__", None):
                path = Path(module.__file__).resolve()
                if path.is_file() and any(path.is_relative_to(root) for root in companion_roots):
                    companion_origins.append(
                        dict(
                            module=name,
                            path=str(path),
                            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                        )
                    )
        result = dict(
            status="PASS",
            lifecycle=lifecycle,
            plans=plans,
            deterministic_display_sha256=digest(stable),
            packets=client.consumer.sequence,
            events=len(client.consumer.events),
            rows=len(view["rows"]),
            actual_rows=sum(r["row_kind"] == "FACT_PREFIX" for r in view["rows"]),
            full_plan_rows=sum(r["row_kind"] == "FULL_PLAN" for r in view["rows"]),
            archive_status=view["status"],
            writable=view["writable"],
            dual_view_relation=relation,
            native_render_created=False,
            elapsed_s=time.perf_counter() - started,
            package_origins=origins,
            companion_origins=companion_origins,
            lifecycle_execution="UNCHANGED_ORIGINAL_FUNCTION_CODE_WITH_EXACT_SEALED_INPUT_CACHE",
            lifecycle_cache_stats=cache.stats,
            schedule_binding=schedule_binding,
            script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        )
        save("reconstruction-result.json", result)
        print(
            json.dumps(
                {k: v for k, v in result.items() if k not in ("lifecycle", "package_origins")}
            )
        )
        return result
    finally:
        client.schedules.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkers", type=Path, required=True)
    parser.add_argument("--desktop", type=Path, nargs="+", required=True)
    args = parser.parse_args()
    verify(args.directory, args.output, args.checkers, args.desktop)


if __name__ == "__main__":
    main()
