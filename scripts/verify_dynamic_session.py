"""Independent P042 saved generation/version/execution/causal reconstruction."""

import argparse
import copy
import gzip
import hashlib
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from verify_dynamic_capacity import verify_capacity  # noqa: E402

from adaptive_hrc_scheduling.contracts.codec import decode  # noqa: E402
from adaptive_hrc_scheduling.contracts.production import digest, validate  # noqa: E402
from adaptive_hrc_scheduling.contracts.session import (  # noqa: E402
    canonical,  # noqa: E402
    validate_record,
    validate_request,
    validate_spec,
)
from adaptive_hrc_scheduling.contracts.session import digest as sha  # noqa: E402
from adaptive_hrc_scheduling.control.production_decisions import check_decisions  # noqa: E402
from adaptive_hrc_scheduling.domain import production as m  # noqa: E402
from adaptive_hrc_scheduling.dynamic_orders import MATERIAL_PLANS, CatalogHistory  # noqa: E402
from adaptive_hrc_scheduling.production_checker import check_run  # noqa: E402


def verify(directory, *, evidence_directory=None, require_decisions=True):
    directory = Path(directory)
    evidence = Path(evidence_directory) if evidence_directory else directory

    def read(name):
        return json.loads((directory / name).read_text(encoding="utf-8"))

    checks = []

    def check(value, reason):
        if not value:
            raise ValueError(reason)
        checks.append(reason)

    spec = validate_spec(read("run-spec.json"))
    saved, profile, binding = (
        read("session-state.json"),
        read("profile.json"),
        read("launch-binding.json"),
    )
    check(saved["dynamic_format"] in ("P042-DYNAMIC-1", "P042-DYNAMIC-2"), "DYNAMIC_FORMAT")
    check(
        saved["binding"] == binding and binding["run_spec_sha256"] == sha(spec), "IMMUTABLE_RUNSPEC"
    )
    check(sha(profile) == spec["profile_sha256"] == binding["profile_sha256"], "PROFILE_BINDING")
    check(profile["objective"] == "P042_URGENCY_DUE_PROGRESS_EXPOSURE-r1", "DYNAMIC_OBJECTIVE")
    check(binding["case"] == spec["scenario"], "SCENARIO_BINDING")
    check(
        (
            binding["run_id"],
            binding["epoch"],
            binding["backend"],
            binding["method"],
            binding["mode"],
            binding["source_sha256"],
        )
        == (
            spec["run_id"],
            spec["epoch"],
            spec["backend"],
            spec["method"],
            spec["mode"],
            spec["source_sha256"],
        ),
        "LAUNCH_BINDING",
    )
    initial = decode(m.Configuration, read("configuration.json"))
    check(digest(initial) == spec["initial_config_sha256"], "FROZEN_C0")
    validate(initial)
    history = CatalogHistory(initial, saved["generations"])
    snapshot = decode(m.ExecutionSnapshot, saved["execution"])
    events = snapshot.events
    prefix_hashes = [sha([])]
    prefix_hasher = hashlib.sha256(b"[")
    for n, event in enumerate(events):
        if n:
            prefix_hasher.update(b",")
        prefix_hasher.update(canonical(__import__("dataclasses").asdict(event)))
        current = prefix_hasher.copy()
        current.update(b"]")
        prefix_hashes.append(current.hexdigest())
    check(
        (snapshot.run_id, snapshot.epoch) == (spec["run_id"], spec["epoch"]), "EXECUTION_IDENTITY"
    )
    check(
        history.config_at(events) == history.current
        and digest(history.current) == snapshot.config_sha256,
        "MATERIALIZED_CONFIGURATION",
    )
    requests, receipts = saved["requests"], saved["receipts"]
    for key, request in requests.items():
        validate_request(request)
        check(
            key == request["request_id"]
            and (request["run_id"], request["epoch"]) == (spec["run_id"], spec["epoch"]),
            "REQUEST:" + key,
        )
    terminal, previous, accepted, applied = {}, "0" * 64, {}, {}
    accepted_sequence = 0
    for n, row in enumerate(receipts, 1):
        validate_record("Receipt", row)
        check(
            row["receipt_sequence"] == n
            and row["receipt_id"] == f"RECEIPT-{n}"
            and row["previous_receipt_hash"] == previous,
            f"RECEIPT_CHAIN:{n}",
        )
        previous = sha(row)
        key = row["request_id"], row["request_digest"]
        check(key not in terminal, f"TERMINAL_IMMUTABLE:{n}")
        if row["status"] in ("ACCEPTED", "WAITING_BOUNDARY", "APPLIED"):
            request = requests[row["request_id"]]
            check(row["request_digest"] == request["request_digest"], f"RECEIPT_REQUEST:{n}")
            check(
                type(row.get("accept_sequence")) is int and row["accept_sequence"] > 0,
                f"ACCEPT_SEQUENCE:{n}",
            )
        if row["status"] == "ACCEPTED":
            accepted_sequence += 1
            check(
                row["request_id"] not in accepted
                and row["accept_sequence"] == accepted_sequence
                and saved["admissions"][row["request_id"]]["sequence"] == accepted_sequence
                and row["catalog_version_before"]
                == row["catalog_version_after"]
                == saved["admissions"][row["request_id"]]["accepted_version"]
                and row["state_revision"]
                == saved["admissions"][row["request_id"]]["accepted_revision"],
                f"ACCEPTED_BINDING:{n}",
            )
            accepted[row["request_id"]] = row
        elif row["status"] in ("WAITING_BOUNDARY", "APPLIED") or "accept_sequence" in row:
            check(
                row["request_id"] in accepted
                and row["accept_sequence"] == accepted[row["request_id"]]["accept_sequence"],
                f"RECEIPT_ADMISSION:{n}",
            )
        if row["status"] == "APPLIED":
            applied[row["request_id"]] = row
        if row["status"] in ("APPLIED", "REJECTED"):
            terminal[key] = row
    catalog = copy.deepcopy(saved["initial_catalog"])
    check(catalog["configuration_sha256"] == spec["initial_config_sha256"], "INITIAL_CATALOG_C0")
    versions, by_id = [sha(catalog)], {e.id: e for e in events}
    generations = {r["request_id"]: r for r in saved["generations"]}
    commit_counts = []
    payload_keys = (
        "delta_id",
        "request_id",
        "request_digest",
        "kind",
        "accept_sequence",
        "actual_sim_h",
        "read_set_hash",
        "state_revision_before",
        "state_revision_after",
        "object_ids",
        "generation_sha256",
        "commit_event_id",
    )
    for i, delta in enumerate(saved["deltas"], 1):
        check(
            (delta["old_version"], delta["new_version"], delta["old_hash"])
            == (i - 1, i, versions[-1]),
            f"DELTA_VERSION:{i}",
        )
        check(
            delta["new_hash"]
            == sha(
                dict(
                    previous_hash=versions[-1], version=i, delta={k: delta[k] for k in payload_keys}
                )
            ),
            f"DELTA_CHAIN:{i}",
        )
        request = requests[delta["request_id"]]
        event = by_id[delta["commit_event_id"]]
        check(
            request["request_digest"] == delta["request_digest"]
            and request["kind"] == delta["kind"],
            f"DELTA_REQUEST:{i}",
        )
        check(
            event.occurred_sim_h == delta["actual_sim_h"]
            and event.state.revision == delta["state_revision_before"] + 1,
            f"ACTUAL_COMMIT:{i}",
        )
        admission = saved["admissions"][request["request_id"]]
        receipt = applied.get(request["request_id"])
        check(receipt is not None, f"APPLIED_REQUIRED:{i}")
        check(
            receipt["event_id"] == event.id
            and receipt["request_digest"] == delta["request_digest"]
            and receipt["accept_sequence"] == delta["accept_sequence"]
            and receipt["catalog_version_before"] == delta["old_version"]
            and receipt["catalog_version_after"] == delta["new_version"]
            and receipt["actual_applied_sim_h"] == receipt["sim_h"] == delta["actual_sim_h"]
            and receipt["state_revision"] == delta["state_revision_after"],
            f"APPLIED_COMMIT_BINDING:{i}",
        )
        final_event = next(
            (e for e in events if e.state.revision == delta["state_revision_after"]), None
        )
        check(
            final_event is not None
            and final_event.sequence >= event.sequence
            and final_event.occurred_sim_h == delta["actual_sim_h"]
            and accepted[request["request_id"]]["sim_h"] <= delta["actual_sim_h"]
            and admission["due_h"]
            == request.get("requested_sim_h", accepted[request["request_id"]]["sim_h"])
            and admission["due_h"] <= delta["actual_sim_h"] <= request["expires_sim_h"],
            f"APPLIED_ACTUAL_BOUNDARY:{i}",
        )
        check(
            admission["sequence"]
            == delta["accept_sequence"]
            == accepted[request["request_id"]]["accept_sequence"],
            f"ADMISSION:{i}",
        )
        check(
            sha(admission["read_set"]) == admission["read_set_hash"] == delta["read_set_hash"],
            f"READ_SET:{i}",
        )
        if delta["kind"] == "ORDER_CREATE":
            g = generations[request["request_id"]]
            check(
                g["payload"] == request["payload"]
                and sha(g) == delta["generation_sha256"]
                and g["event_id"] == event.id
                and g["catalog_version"] == i,
                f"GENERATION_SOURCE:{i}",
            )
            ids = g["product_ids"]
            check(
                len(ids) == request["payload"]["quantity"]
                and not set(ids) & catalog["objects"].keys()
                and request["target_id"] not in catalog["objects"],
                f"FIRST_REGISTRATION:{i}",
            )
            check(
                event.world.kind == "CATALOG_REGISTER"
                and request["payload"]["due_sim_h"] > event.occurred_sim_h,
                f"DUE_ARRIVAL:{i}",
            )
            if "before_event_count" in g:
                check(
                    g["before_event_count"] == event.sequence - 1
                    and g["before_prefix_sha256"] == prefix_hashes[event.sequence - 1]
                    and g["protected_before_sha256"] == g["protected_after_sha256"],
                    f"ORIGINAL_PREFIX_PROTECTED:{i}",
                )
            for pid in ids:
                catalog["objects"][pid] = dict(revision=0, kind="product", available=True)
                check(
                    saved["material_due"][pid]
                    == g["sim_h"] + MATERIAL_PLANS[g["payload"]["material_plan_id"]],
                    "MATERIAL_PLAN:" + pid,
                )
            catalog["objects"][request["target_id"]] = dict(
                revision=0, kind="order", available=True, product_ids=ids
            )
            check(delta["object_ids"] == [request["target_id"], *ids], f"GENERATED_OBJECTS:{i}")
        else:
            check(sha(request["payload"]) == delta["generation_sha256"], f"WORLD_PAYLOAD:{i}")
            for ident in delta["object_ids"]:
                catalog["objects"][ident]["revision"] += 1
                catalog["objects"][ident]["available"] = delta["kind"] == "DEVICE_REPAIR"
        check(sha(catalog) == delta["materialized_catalog_sha256"], f"CATALOG_RECONSTRUCTED:{i}")
        versions.append(delta["new_hash"])
        commit_counts.append((event.sequence, i))
    check(catalog == saved["catalog"] and versions == saved["versions"], "FINAL_CATALOG_CHAIN")
    committed = {d["request_id"] for d in saved["deltas"]}
    check(len(committed) == len(saved["deltas"]), "ONE_COMMIT_PER_REQUEST")
    check(
        committed
        == {key for key in applied if requests[key]["kind"] not in ("CLOSE_INPUT", "STOP_REQUEST")},
        "APPLIED_COMMIT_COVERAGE",
    )
    for key, row in applied.items():
        if key in committed:
            continue
        check(
            requests[key]["kind"] in ("CLOSE_INPUT", "STOP_REQUEST")
            and "event_id" not in row
            and row["catalog_version_before"] == row["catalog_version_after"]
            and row["actual_applied_sim_h"] == row["sim_h"]
            and accepted[key]["sim_h"] <= row["sim_h"] <= requests[key]["expires_sim_h"],
            "CONTROL_APPLIED:" + key,
        )
    observations = {row["observation_id"]: row for row in saved["observations"]}

    def version_at(count):
        return max((v for n, v in commit_counts if n <= count), default=0)

    for row in observations.values():
        n = row["event_count"]
        state = events[n - 1].state if n else None
        check(
            0 <= n <= len(events) and row["event_prefix_hash"] == prefix_hashes[n],
            "OBSERVED_PREFIX:" + row["observation_id"],
        )
        check(
            row["catalog_version"] == version_at(n)
            and row["catalog_hash"] == versions[version_at(n)],
            "OBSERVED_VIEW:" + row["observation_id"],
        )
        check(
            (row["run_id"], row["epoch"]) == (spec["run_id"], spec["epoch"])
            and (state is None or row["state_revision"] == state.revision),
            "OBSERVED_IDENTITY:" + row["observation_id"],
        )
        if state is not None:
            check(
                row["observation_id"] == f"OBS-{state.revision}"
                and row["sampled_sim_h"] == row["received_sim_h"] == state.time_h,
                "OBSERVED_CLOCK:" + row["observation_id"],
            )
    starts = {e.command.id: e for e in events if e.kind == "STARTED"}
    launch = saved["launch_event_count"]
    check(
        set(saved["command_bindings"])
        == {e.command.id for e in events[launch:] if e.kind == "STARTED"},
        "STARTED_COVERAGE",
    )
    for ident, row in saved["command_bindings"].items():
        event = starts[ident]
        obs = observations[row["observation_id"]]
        check(
            row["command_sha256"] == digest(event.command) and row["receipt_id"] == event.id,
            "ACTUAL_DISPATCH:" + ident,
        )
        check(
            row["admitted_catalog_version"] == obs["catalog_version"] == version_at(event.sequence)
            and row["admitted_catalog_hash"] == obs["catalog_hash"]
            and row["observed_prefix_hash"] == obs["event_prefix_hash"]
            and event.command.expected_revision == obs["state_revision"],
            "DISPATCH_VIEW:" + ident,
        )
        view = history.config_at(events[: obs["event_count"]])
        check(digest(view) == event.command.config_sha256, "DISPATCH_MATERIALIZED_VIEW:" + ident)
    scene = {
        r["domain_id"]: r
        for r in saved["scene_bindings"]
        if r["scope"] == "DYNAMIC_EMPTY_ENTITY_READBACK"
    }
    expected = {x.id for x in (*history.current.lots, *history.current.entities)} - {
        x.id for x in (*initial.lots, *initial.entities)
    }
    check(set(scene) == expected, "DYNAMIC_SCENE_COVERAGE")
    for g in saved["generations"]:
        view = history.views[g["config_sha256"]]
        for x in (*view.lots, *view.entities):
            if x.product_id not in g["product_ids"]:
                continue
            row = scene[x.id]
            check(
                row["scene_entity_id"] == x.id
                and row["catalog_version"] == g["catalog_version"]
                and row["event_id"] == g["event_id"]
                and row["template_revision"] == "v1",
                "SCENE_BINDING:" + x.id,
            )
            if spec["backend"] == "ISAAC":
                check(
                    row["prim_path"].startswith("/World/")
                    and row["actual_position_m"] == [-30, 0, 0]
                    and not row["visible"]
                    and (row["run_id"], row["epoch"]) == (spec["run_id"], spec["epoch"]),
                    "REAL_EMPTY_USD_READBACK:" + x.id,
                )
            else:
                check(row["prim_path"] == "CPU:N/A", "CPU_SCENE:" + x.id)
    reconstructed_capacity = verify_capacity(spec, saved, history, snapshot, check)
    for row in saved["cache_transitions"]:
        check(row["protected_before_hash"] == row["protected_after_hash"], "COMMITMENT_PROTECTION")
        known = set(row["known_uncommitted_keys"])
        invalid = set(row["invalidated_keys"])
        survived = row["surviving_commands"]
        check(invalid <= known and set(survived) == known - invalid, "CACHE_DEPENDENCY_DOMAIN")
        check(
            set(row["reused_keys"]) <= set(row["revalidated_keys"]) <= set(survived),
            "CACHE_REUSE_DOMAIN",
        )
        check(
            {p["original_key"] for p in row["reuse_proofs"]} == set(row["reused_keys"]),
            "CACHE_REUSE_PROOF_COVERAGE",
        )
        for proof in row["reuse_proofs"]:
            event = starts[proof["command_id"]]
            check(
                proof["receipt_id"] == event.id
                and proof["command_sha256"] == digest(event.command)
                and proof["original_command_sha256"] == sha(survived[proof["original_key"]]),
                "ACTUAL_CACHE_REUSE",
            )
    budget = saved["budget"]
    check(
        budget["profile"] == profile and budget["profile_sha256"] == spec["profile_sha256"],
        "ACTUAL_BUDGET_PROFILE",
    )
    used = 0
    sequences = []
    for n, entry in enumerate(budget["entries"]):
        elapsed = entry["elapsed_s"]
        check(
            type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0,
            f"BUDGET_ELAPSED:{n}",
        )
        used += elapsed
        sequences.append(entry["sequence"])
        check(
            abs(entry["used_s"] - used) < 1e-7
            and abs(entry["remaining_s"] - max(0, profile["total_seconds"] - used)) < 1e-7
            and abs(entry["overrun_s"] - max(0, used - profile["total_seconds"])) < 1e-7,
            f"BUDGET_ACCOUNT:{n}",
        )
    check(
        sequences == sorted(set(sequences)) and abs(budget["used_s"] - used) < 1e-7, "TOTAL_BUDGET"
    )
    journal_path = evidence / "online-journal.json"
    if journal_path.exists():
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        indexed = {r["sequence"]: r for r in journal}
        for entry in budget["entries"]:
            check(indexed[entry["sequence"]]["total_budget"] == entry, "BUDGET_ACTUAL_CYCLE")
        check(
            budget["change_searches"]
            == sum(
                bool(r.get("search_call")) and r["trigger"] in ("FEEDBACK", "CATALOG_CHANGED")
                for r in journal
            ),
            "ACTUAL_CHANGE_SEARCH_COUNT",
        )
    elif require_decisions:
        check(False, "SEARCH_JOURNAL_REQUIRED")
    for event in events:
        if event.readback is not None:
            check(
                event.readback.source
                == ("ISAAC_USD" if spec["backend"] == "ISAAC" else "LIGHT_EXECUTOR"),
                "ACTUAL_READBACK_SOURCE:" + event.id,
            )
        if (
            event.world
            and event.world.kind == "ARRIVAL"
            and event.world.product_id in saved["material_due"]
        ):
            check(
                event.occurred_sim_h >= saved["material_due"][event.world.product_id],
                "ACTUAL_MATERIAL_TIME:" + event.id,
            )
    check(
        binding["launch_prefix_hash"] == prefix_hashes[launch],
        "LAUNCH_PREFIX_UNCHANGED",
    )
    audit = check_run(history.current, snapshot, catalog=history)
    check(audit.status == "PASS", "EXECUTION:" + ";".join(f.reason for f in audit.findings))
    decision_status = "NOT_PROVIDED"
    path = evidence / "decisions.jsonl.gz"
    if path.exists():
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            rows = [json.loads(line) for line in stream]
        decision = check_decisions(history.current, snapshot, rows, catalog=history)
        check(decision.status == "PASS", "CAUSAL:" + ";".join(f.reason for f in decision.findings))
        decision_status = decision.status
    elif require_decisions:
        check(False, "DECISIONS_REQUIRED")
    return dict(
        status="PASS",
        identity="P042-INDEPENDENT-r2",
        count=len(checks),
        checks=checks,
        catalog_version=len(saved["deltas"]),
        generations=len(history.generations),
        products=len(history.current.products),
        capacity=reconstructed_capacity,
        execution_audit=audit.status,
        decision_audit=decision_status,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--evidence-directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.directory, evidence_directory=args.evidence_directory)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "checks"}))


if __name__ == "__main__":
    main()
