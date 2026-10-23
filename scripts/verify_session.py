"""Reconstruct P04.1 saved versions and admission bindings independently of Session."""

import argparse
import copy
import gzip
import hashlib
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from adaptive_hrc_scheduling.contracts.codec import as_data  # noqa: E402
from adaptive_hrc_scheduling.contracts.production import decode  # noqa: E402
from adaptive_hrc_scheduling.contracts.production import digest as production_digest
from adaptive_hrc_scheduling.control.production_decisions import check_decisions  # noqa: E402
from adaptive_hrc_scheduling.domain.production import Configuration, ExecutionSnapshot  # noqa: E402
from adaptive_hrc_scheduling.production_checker import check_run  # noqa: E402


def sha(data):
    def norm(v):
        if isinstance(v, dict):
            return {k: norm(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [norm(x) for x in v]
        if type(v) is float:
            assert math.isfinite(v)
            return int(v) if int(v) == v else v
        return v

    return hashlib.sha256(
        json.dumps(
            norm(data), sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def verify(directory, *, evidence_directory=None, require_decisions=False):
    directory = Path(directory)
    state_path = directory / "session-state.json"
    if state_path.is_file():
        header = json.loads(state_path.read_text(encoding="utf-8"))
        if header.get("generations"):
            from verify_dynamic_session import verify as verify_dynamic

            return verify_dynamic(
                directory,
                evidence_directory=evidence_directory,
                require_decisions=require_decisions,
            )

    def read(name):
        return json.loads((directory / name).read_text(encoding="utf-8"))

    spec, saved, profile = read("run-spec.json"), read("session-state.json"), read("profile.json")
    checks = []

    def check(condition, reason):
        if not condition:
            raise ValueError(reason)
        checks.append(reason)

    evidence_directory = Path(evidence_directory) if evidence_directory else directory
    config_path = evidence_directory / "configuration.json"
    check(config_path.is_file(), "CONFIGURATION_REQUIRED")
    config = decode(Configuration, json.loads(config_path.read_text(encoding="utf-8")))
    check(production_digest(config) == spec["initial_config_sha256"], "CONFIGURATION_RESTORED")
    modern = saved.get("session_format") == "P041-SESSION-r2"

    binding = saved["binding"]
    check(binding["run_spec_sha256"] == sha(spec), "RUNSPEC_DIGEST")
    check(spec["profile_sha256"] == sha(profile) == binding["profile_sha256"], "PROFILE_DIGEST")
    check(
        (spec["run_id"], spec["epoch"], spec["method"], spec["mode"], spec["scenario"])
        == (
            binding["run_id"],
            binding["epoch"],
            binding["method"],
            binding["mode"],
            binding["case"],
        ),
        "ACTUAL_LAUNCH",
    )
    check(
        binding["backend"] == spec["backend"] and binding["source_sha256"] == spec["source_sha256"],
        "LAUNCH_SOURCE_BACKEND",
    )
    check(binding["profile_id"] == spec["budget_profile_id"] == profile["id"], "PROFILE_ID")
    state = copy.deepcopy(saved["initial_catalog"])
    versions = [sha(state)]
    snapshot = decode(ExecutionSnapshot, saved["execution"])
    events = list(snapshot.events)
    by_id = {e.id: e for e in events}
    check(
        snapshot.config_sha256 == spec["initial_config_sha256"] == state["configuration_sha256"],
        "FROZEN_C0",
    )
    requests = saved["requests"]
    for key, req in requests.items():
        check(
            key == req["request_id"]
            and req["request_digest"]
            == sha({k: v for k, v in req.items() if k != "request_digest"}),
            "REQUEST_DIGEST:" + key,
        )
        check(
            (req["run_id"], req["epoch"]) == (spec["run_id"], spec["epoch"]),
            "REQUEST_IDENTITY:" + key,
        )
    previous = "0" * 64
    terminal = {}
    for i, receipt in enumerate(saved["receipts"], 1):
        check(
            receipt["receipt_sequence"] == i and receipt["previous_receipt_hash"] == previous,
            "RECEIPT_CHAIN:" + str(i),
        )
        check(
            "accept_sequence" not in receipt
            or type(receipt["accept_sequence"]) is int
            and receipt["accept_sequence"] > 0,
            "NONNULL_SEQUENCE:" + str(i),
        )
        previous = sha(receipt)
        key = (receipt["request_id"], receipt["request_digest"])
        check(
            key not in terminal or terminal[key] == receipt["status"], "RECEIPT_TERMINAL:" + str(i)
        )
        if receipt["status"] in ("APPLIED", "REJECTED"):
            terminal[key] = receipt["status"]
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
            "DELTA_VERSION:" + str(i),
        )
        payload = {k: delta[k] for k in payload_keys}
        h = sha(dict(previous_hash=versions[-1], version=i, delta=payload))
        check(h == delta["new_hash"], "DELTA_HASH:" + str(i))
        req = requests[delta["request_id"]]
        event = by_id[delta["commit_event_id"]]
        target = req["target_id"]
        obj = state["objects"][target]
        entity = obj["product_ids"][0] if obj["kind"] == "order" else target
        affected = [target, entity] if entity != target else [target]
        check(
            req["request_digest"] == delta["request_digest"]
            and event.world is not None
            and event.world.entity_id == entity
            and delta["object_ids"] == affected
            and event.occurred_sim_h == delta["actual_sim_h"]
            and event.state.revision == delta["state_revision_after"],
            "ACTUAL_WORLD_EVENT:" + str(i),
        )
        check(
            any(
                r["request_id"] == req["request_id"]
                and r["status"] == "APPLIED"
                and r.get("event_id") == event.id
                for r in saved["receipts"]
            ),
            "APPLIED_RECEIPT:" + str(i),
        )
        for ident in affected:
            obj = state["objects"][ident]
            obj["revision"] += 1
            obj["available"] = req["kind"] == "DEVICE_REPAIR"
        check(sha(state) == delta["materialized_catalog_sha256"], "MATERIALIZED:" + str(i))
        versions.append(h)
    check(versions == saved["versions"] and state == saved["catalog"], "CATALOG_RECONSTRUCTION")
    expected_catalog = dict(
        configuration_sha256=production_digest(config),
        objects={
            x.id: dict(revision=0, kind=kind, available=True)
            for kind, objects in (
                ("product", config.products),
                ("person", config.people),
                ("device", config.devices),
            )
            for x in objects
        },
    )
    if modern:
        for p in config.products:
            expected_catalog["objects"][p.order_id] = dict(
                revision=0, kind="order", available=True, product_ids=[p.id]
            )
        check(
            [r["order_id"] for r in spec["initial_orders"]]
            == [p.order_id for p in config.products],
            "INITIAL_ORDER_IDENTITY",
        )
    check(saved["initial_catalog"] == expected_catalog, "INITIAL_CATALOG_FROM_C0")
    observations = {}
    for row in saved["observations"]:
        count, v = row["event_count"], row["catalog_version"]
        check(
            type(count) is int
            and type(v) is int
            and 0 <= v < len(versions)
            and 0 <= count <= len(events)
            and row["catalog_hash"] == versions[v]
            and row["event_prefix_hash"] == sha([as_data(e) for e in events[:count]]),
            "OBSERVATION_PREFIX:" + row["observation_id"],
        )
        check(
            v == sum(by_id[d["commit_event_id"]].sequence <= count for d in saved["deltas"]),
            "APPLICABLE_CATALOG:" + row["observation_id"],
        )
        check(
            (row["run_id"], row["epoch"]) == (spec["run_id"], spec["epoch"])
            and row["state_revision"] == (events[count - 1].state.revision if count else 0),
            "OBSERVATION_IDENTITY:" + row["observation_id"],
        )
        check(row["observation_id"] not in observations, "UNIQUE_OBSERVATION")
        observations[row["observation_id"]] = row
    cutoff = saved.get(
        "launch_event_count", min((r["event_count"] for r in saved["observations"]), default=0)
    )
    check(type(cutoff) is int and 0 <= cutoff <= len(events), "LAUNCH_PREFIX")
    if modern:
        check(read("launch-binding.json") == binding, "LAUNCH_BINDING_SAVED_COPY")
        check(
            binding["launch_event_count"] == cutoff
            and binding["launch_prefix_hash"] == sha([as_data(e) for e in events[:cutoff]])
            and all(o["event_count"] >= cutoff for o in saved["observations"]),
            "LAUNCH_PREFIX_BINDING",
        )
    actual_commands = {e.command.id for e in events if e.kind == "STARTED" and e.sequence > cutoff}
    check(actual_commands == set(saved["command_bindings"]), "COMMAND_BINDING_COVERAGE")
    for key, row in saved["command_bindings"].items():
        event = by_id[row["receipt_id"]]
        command = event.command
        check(
            command is not None
            and command.id == key
            and event.kind == "STARTED"
            and production_digest(command) == row["command_sha256"],
            "COMMAND_ORIGINAL:" + key,
        )
        v = row["admitted_catalog_version"]
        check(
            type(v) is int
            and 0 <= v < len(versions)
            and row["admitted_catalog_hash"] == versions[v],
            "COMMAND_VERSION:" + key,
        )
        check(
            any(
                o["observation_id"] == row["observation_id"]
                and o["catalog_version"] == v
                and o["event_prefix_hash"] == row["observed_prefix_hash"]
                for o in saved["observations"]
            ),
            "COMMAND_OBSERVED_VIEW:" + key,
        )
        observation = observations[row["observation_id"]]
        check(
            row["state_revision"] == command.expected_revision == observation["state_revision"]
            and row["dependency_hash"] == sha(as_data(command))
            and observation["event_count"] < event.sequence,
            "COMMAND_CURRENT_ADMISSION:" + key,
        )
    for i, row in enumerate(saved["cache_transitions"], 1):
        check(
            set(row["invalidated_keys"]) <= set(row["known_uncommitted_keys"]),
            "CACHE_KNOWN:" + str(i),
        )
        check(
            row["protected_before_hash"] == row["protected_after_hash"],
            "PROMISES_RETAINED:" + str(i),
        )
        check(
            set(row["reused_keys"]) <= set(row["revalidated_keys"]), "REUSE_REVALIDATED:" + str(i)
        )
        check(
            set(row["revalidated_keys"])
            <= set(row["known_uncommitted_keys"]) - set(row["invalidated_keys"]),
            "REUSE_SURVIVORS:" + str(i),
        )
        if modern:
            proofs = row["reuse_proofs"]
            check(
                {p["original_key"] for p in proofs} == set(row["reused_keys"]),
                "REUSE_PROOF_COVERAGE:" + str(i),
            )
            for proof in proofs:
                original = row["surviving_commands"][proof["original_key"]]
                binding_row = saved["command_bindings"][proof["command_id"]]
                event = by_id[proof["receipt_id"]]

                def choice(value):
                    return {
                        k: v
                        for k, v in value.items()
                        if k not in ("id", "issued_sim_h", "expected_revision")
                    }

                check(
                    proof["original_command_sha256"] == sha(original)
                    and proof["command_sha256"] == binding_row["command_sha256"]
                    and proof["observation_id"] == binding_row["observation_id"]
                    and proof["observed_prefix_hash"] == binding_row["observed_prefix_hash"]
                    and proof["catalog_version"]
                    == binding_row["admitted_catalog_version"]
                    >= row["new_catalog_version"]
                    and event.id == binding_row["receipt_id"]
                    and event.kind == "STARTED"
                    and choice(original) == choice(as_data(event.command)),
                    "REUSE_ACTUAL_START:" + str(i),
                )
    scenes = saved["scene_bindings"]
    check(len(scenes) == len(saved["deltas"]), "SCENE_BINDING_COVERAGE")
    mapping = {}
    if spec["backend"] == "ISAAC":
        catalog_path = evidence_directory / "entity-catalog.json"
        check(catalog_path.is_file(), "SCENE_CATALOG_REQUIRED")
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        check(
            (catalog["run_id"], catalog["epoch"], catalog["config_sha256"])
            == (spec["run_id"], spec["epoch"], spec["initial_config_sha256"]),
            "SCENE_CATALOG_IDENTITY",
        )
        for obj in catalog["entities"]:
            for target in obj["targets"]:
                mapping.setdefault(target, set()).update(obj["paths"])
    for delta, scene in zip(saved["deltas"], scenes):
        req = requests[delta["request_id"]]
        event = by_id[delta["commit_event_id"]]
        check(
            (
                scene["domain_id"],
                scene["scene_entity_id"],
                scene["catalog_version"],
                scene["event_id"],
            )
            == (req["target_id"], event.world.entity_id, delta["new_version"], event.id),
            "SCENE_APPLICABLE_VERSION",
        )
        check(
            scene["prim_path"] == "CPU:N/A"
            if spec["backend"] == "CPU"
            else scene["prim_path"] in mapping.get(scene["scene_entity_id"], ()),
            "SCENE_ACTUAL_MAPPING",
        )
    budget = saved["budget"]
    check(
        budget["profile"] == profile and budget["profile_sha256"] == sha(profile),
        "TOTAL_BUDGET_PROFILE",
    )
    used = 0.0
    for index, entry in enumerate(budget["entries"], 1):
        elapsed = entry["elapsed_s"]
        check(
            type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0,
            "BUDGET_ELAPSED:" + str(index),
        )
        used += elapsed
        check(
            abs(entry["used_s"] - used) < 1e-7
            and abs(entry["remaining_s"] - max(0, profile["total_seconds"] - used)) < 1e-7
            and abs(entry["overrun_s"] - max(0, used - profile["total_seconds"])) < 1e-7,
            "BUDGET_RUNNING_TOTAL:" + str(index),
        )
    check(
        abs(sum(e["elapsed_s"] for e in budget["entries"]) - budget["used_s"]) < 1e-7,
        "TOTAL_BUDGET_SUM",
    )
    if modern and spec["mode"] == "INTERACTIVE_REPLAY":
        replay = saved["replay_source"]
        check(
            type(replay) is dict
            and set(replay) == {"requests"}
            and sha(replay) == spec["replay_source_sha256"],
            "REPLAY_SOURCE_BINDING",
        )
        check(
            all(requests[key] in replay["requests"] for key in saved["admissions"]),
            "REPLAY_JOURNAL_REQUESTS",
        )
    check(check_run(config, snapshot).status == "PASS", "INDEPENDENT_EXECUTION")
    decisions_path = evidence_directory / "decisions.jsonl.gz"
    check(
        not require_decisions or decisions_path.is_file(),
        "DECISIONS_REQUIRED" if require_decisions else "DECISION_SCOPE_DECLARED",
    )
    if decisions_path.exists():
        with gzip.open(decisions_path, "rt", encoding="utf-8") as stream:
            rows = tuple(json.loads(line) for line in stream)
        check(check_decisions(config, snapshot, rows).status == "PASS", "INDEPENDENT_DECISIONS")
    return dict(
        status="PASS",
        scope="EXECUTION_DECISIONS_AND_SESSION_BINDINGS"
        if decisions_path.exists()
        else "EXECUTION_AND_SESSION_BINDINGS",
        decision_audit="PASS" if decisions_path.exists() else "NOT_PROVIDED",
        session_format=saved.get("session_format", "P041-SESSION-r1-LEGACY"),
        count=len(checks),
        checks=checks,
        catalog_version=len(versions) - 1,
        command_bindings=len(saved["command_bindings"]),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence-directory", type=Path)
    parser.add_argument("--require-decisions", action="store_true")
    args = parser.parse_args()
    result = verify(
        args.directory,
        evidence_directory=args.evidence_directory,
        require_decisions=args.require_decisions,
    )
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "checks"}))


if __name__ == "__main__":
    main()
