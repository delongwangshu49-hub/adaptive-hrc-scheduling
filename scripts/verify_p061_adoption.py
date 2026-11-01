"""Bind reconstructed complete dynamic candidates to actual started commands."""

import argparse
import gzip
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from verify_workforce_candidates import verify as verify_complete_candidates  # noqa: E402
from verify_workforce_session import verify  # noqa: E402

from adaptive_hrc_scheduling.algorithms.lns import fingerprint  # noqa: E402
from adaptive_hrc_scheduling.contracts.codec import decode, require  # noqa: E402
from adaptive_hrc_scheduling.contracts.production import digest  # noqa: E402
from adaptive_hrc_scheduling.domain.production import (  # noqa: E402
    Configuration,
    PlanningObservation,
)
from adaptive_hrc_scheduling.dynamic_workforce import WorkforceHistory  # noqa: E402


def read(p):
    return json.loads(p.read_text(encoding="utf-8-sig"))


def file_binding(path):
    with path.open("rb") as stream:
        return dict(
            bytes=path.stat().st_size, sha256=hashlib.file_digest(stream, "sha256").hexdigest()
        )


def candidate_context(data, initial, saved, spec, actual_decisions):
    """Bind the candidate envelope to actual saved inputs, independently of proof labels."""
    obs, snapshot = data["observation"], data["snapshot"]
    require(obs["run_id"] == snapshot["run_id"] == spec["run_id"], "P061_CANDIDATE_RUN")
    require(obs["epoch"] == snapshot["epoch"] == spec["epoch"], "P061_CANDIDATE_EPOCH")
    n = data["prefix_event_count"]
    events = saved["execution"]["events"]
    require(type(n) is int and 0 < n <= len(events), "P061_CANDIDATE_PREFIX_COUNT")
    require(snapshot["events"][:n] == events[:n], "P061_CANDIDATE_ACTUAL_PREFIX")
    matches = [r for r in saved["observations"] if r["observation_id"] == obs["id"]]
    require(len(matches) == 1, "P061_CANDIDATE_OBSERVATION")
    bound = matches[0]
    require(bound["event_count"] == n, "P061_CANDIDATE_OBSERVATION_PREFIX")
    require(
        obs["sampled_h"] == bound["sampled_sim_h"] and obs["received_h"] == bound["received_sim_h"],
        "P061_CANDIDATE_OBSERVATION_CLOCK",
    )
    state = dict(events[n - 1]["state"], intervals=[])
    require(obs["state"] == state, "P061_CANDIDATE_OBSERVED_STATE")
    require(obs["event_ids"] == [e["id"] for e in events[:n]], "P061_CANDIDATE_EVENT_IDS")
    generations = data["catalog_generations"]
    require(
        len(generations) == bound["catalog_version"]
        and generations == saved["generations"][: len(generations)],
        "P061_CANDIDATE_CATALOG_PREFIX",
    )
    history = WorkforceHistory(initial, generations)
    require(
        obs["config_id"] == history.current.id and obs["config_sha256"] == digest(history.current),
        "P061_CANDIDATE_CONFIGURATION",
    )
    source_rows = [r for r in data["decisions"] if r["event_count"] < n]
    require(
        source_rows == [r for r in actual_decisions if r["event_count"] < n],
        "P061_CANDIDATE_ACTUAL_DECISIONS",
    )
    anchor = digest(decode(PlanningObservation, obs))
    require(data["candidate"]["anchor_sha256"] == anchor, "P061_CANDIDATE_ANCHOR")
    return dict(
        run_id=spec["run_id"],
        epoch=spec["epoch"],
        configuration_sha256=obs["config_sha256"],
        observation_id=obs["id"],
        anchor_sha256=anchor,
        prefix_event_count=n,
        actual_prefix_sha256=bound["event_prefix_hash"],
        catalog_version=bound["catalog_version"],
        after_person_arrival=any(g.get("workforce_kind") == "PERSON_ARRIVE" for g in generations),
    )


def run(directory, candidate_proof, output):
    t0 = time.perf_counter()
    proofs = read(candidate_proof)
    assert proofs["status"] == "PASS" and proofs["candidates"]
    assert all(r["truncation_rejected"] for r in proofs["candidates"])
    saved = read(directory / "session-state.json")
    spec = read(directory / "run-spec.json")
    journal = read(directory / "online-journal.json")
    initial = decode(Configuration, read(directory / "configuration.json"))
    with gzip.open(directory / "decisions.jsonl.gz", "rt", encoding="utf-8") as stream:
        actual_decisions = [json.loads(line) for line in stream]
    input_names = (
        "configuration.json",
        "session-state.json",
        "run-spec.json",
        "profile.json",
        "launch-binding.json",
        "online-journal.json",
        "decisions.jsonl.gz",
    )
    input_bindings = {name: file_binding(directory / name) for name in input_names}
    contexts, candidate_bindings, candidate_data = {}, {}, {}
    for proof in proofs["candidates"]:
        name = proof["file"]
        require(Path(name).name == name, "P061_CANDIDATE_FILENAME")
        path = directory / name
        data = read(path)
        context = candidate_context(data, initial, saved, spec, actual_decisions)
        sha = fingerprint(data["candidate"])
        require(sha == proof["candidate_sha256"], "P061_CANDIDATE_FINGERPRINT")
        require(sha not in contexts, "P061_DUPLICATE_CANDIDATE")
        contexts[sha] = context
        candidate_bindings[name] = file_binding(path)
        candidate_data[sha] = dict(
            candidate=data["candidate"], observation=dict(id=data["observation"]["id"])
        )
    # Revalidate the exact complete inputs. A caller-supplied PASS or a re-signed
    # candidate hash cannot stand in for full reconstruction and truncation checks.
    complete_proof = json.loads(json.dumps(verify_complete_candidates(directory)))
    complete_proof_path = output.with_suffix(".complete-proof.json")
    complete_proof_path.write_text(json.dumps(complete_proof, indent=2) + "\n", encoding="utf-8")
    require(complete_proof == proofs, "P061_COMPLETE_PROOF_MISMATCH")
    require(
        input_bindings == {name: file_binding(directory / name) for name in input_names}
        and candidate_bindings
        == {name: file_binding(directory / name) for name in candidate_bindings},
        "P061_CANDIDATE_INPUT_CHANGED_DURING_VALIDATION",
    )
    independent = verify(directory, require_decisions=True)
    events = {e["id"]: e for e in saved["execution"]["events"]}
    candidates = {r["candidate_sha256"]: r for r in proofs["candidates"]}
    needed = {
        r["cache_sha256"]
        for r in journal
        if r.get("selected_source") == "VERIFIED_CACHE" and r.get("receipt_kind") == "STARTED"
    }
    commands = {}
    files = {}
    for sha in needed:
        proof = candidates[sha]
        path = directory / proof["file"]
        raw = candidate_data[sha]
        assert fingerprint(raw["candidate"]) == sha
        commands[sha] = [c for step in raw["candidate"]["steps"] for c in step["plan"]["commands"]]
        files[sha] = dict(
            path=str(path),
            bytes=path.stat().st_size,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            after_person_arrival=contexts[sha]["after_person_arrival"],
            observation_id=raw["observation"]["id"],
            context=contexts[sha],
        )
    rows = []
    for row in journal:
        if row.get("selected_source") != "VERIFIED_CACHE" or row.get("receipt_kind") != "STARTED":
            continue
        event = events[row["receipt_id"]]
        cmd = event["command"]
        sha = row["cache_sha256"]
        origins = [
            r
            for r in journal
            if r["sequence"] <= row["sequence"]
            and r.get("verified_candidate_sha256") == sha
            and r.get("cache_sha256") == sha
        ]
        assert origins, "VERIFIED_CACHE_ORIGIN_REQUIRED"
        origin = origins[-1]
        assert row["cache_origin"] == origin["observation_sha256"]
        require(
            contexts[sha]["anchor_sha256"] == origin["observation_sha256"],
            "P061_ACTUAL_VERIFIED_ANCHOR",
        )
        assert all(
            r.get("cache_sha256") == sha and not r.get("cache_invalidated")
            for r in journal
            if origin["sequence"] <= r["sequence"] <= row["sequence"]
        ), "CACHE_CONTINUITY"
        if "verified_candidate_sha256" in row:
            assert row["verified_candidate_sha256"] == sha
        assert event["kind"] == "STARTED" and cmd["operation_id"] == row["plan_operation"]
        assert event["run_id"] == row["run_id"] == spec["run_id"]
        assert event["epoch"] == row["epoch"] == spec["epoch"]
        actual_start = row["actual_start"]
        assert actual_start["actual_h"] == event["occurred_sim_h"] == row["time_h"]
        assert actual_start["operation"] == cmd["operation_id"]
        assert actual_start["attempt"] == cmd["attempt"]
        bound = saved["command_bindings"][cmd["id"]]
        assert (
            bound["receipt_id"] == event["id"] and bound["observation_id"] == row["observation_id"]
        )
        selected = row["selected_proposal"]
        assert (
            selected["operation"] == cmd["operation_id"]
            and selected["product"] == cmd["product_id"]
        )
        assert selected["roles"] == cmd["roles"] and selected["mode"] == cmd["mode_id"]
        # Cached command IDs/revisions are legitimately rebound at dispatch.
        # Operation, mode, product and exact named crew must belong to the
        # independently verified full candidate, not merely its hash label.
        matches = [
            c
            for c in commands[sha]
            if all(
                c[k] == cmd[k]
                for k in ("operation_id", "product_id", "activity_id", "mode_id", "roles")
            )
        ]
        assert matches, ("COMMAND_NOT_IN_COMPLETE_CANDIDATE", cmd["id"])
        rows.append(
            dict(
                sequence=row["sequence"],
                trigger=row["trigger"],
                run_id=row["run_id"],
                epoch=row["epoch"],
                catalog_version=bound["admitted_catalog_version"],
                observation_id=row["observation_id"],
                observed_prefix_hash=bound["observed_prefix_hash"],
                candidate_sha256=sha,
                receipt_id=event["id"],
                command_id=cmd["id"],
                candidate_verified_sequence=origin["sequence"],
                cache_continuity_verified=True,
                operation_id=cmd["operation_id"],
                actual_sim_h=event["occurred_sim_h"],
                roles=cmd["roles"],
                candidate_command_membership=True,
                after_person_arrival=files[sha]["after_person_arrival"],
            )
        )
    assert rows and any(
        r["after_person_arrival"] and any(p["person_id"] == "W3" for p in r["roles"]) for r in rows
    )
    result = dict(
        identity="P061-T08-ACTUAL-ADOPTION-r2",
        status="PASS",
        at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
        directory=str(directory),
        original_source_sha256=spec["source_sha256"],
        original_run_id=spec["run_id"],
        epoch=spec["epoch"],
        current_independent_reconstruction=independent,
        full_candidates=len(candidates),
        truncated_candidates_rejected=proofs["truncations_rejected"],
        adoptions=rows,
        count=len(rows),
        used_candidate_files=files,
        complete_candidate_revalidation=True,
        complete_candidate_proof=dict(
            path=str(complete_proof_path), **file_binding(complete_proof_path)
        ),
        verified_candidate_contexts=contexts,
        complete_candidate_files=candidate_bindings,
        complete_validation_inputs=input_bindings,
        complete_validator_source=file_binding(
            Path(__file__).with_name("verify_workforce_candidates.py")
        ),
        source_counts=dict(Counter(str(r.get("selected_source")) for r in journal)),
        rule_fallback_cycles=[
            dict(
                sequence=r["sequence"],
                selected_source=r.get("selected_source"),
                reason=r.get("final_reason"),
                receipt_kind=r.get("receipt_kind"),
            )
            for r in journal
            if r.get("selected_source") != "VERIFIED_CACHE"
        ],
        budget=saved["budget"],
        elapsed_s=time.perf_counter() - t0,
        scope="CURRENT_RECONSTRUCTION_OF_ORIGINAL_DYNAMIC_RUN_NO_NEW_SEARCH_OR_PRODUCTION",
    )
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "status",
                    "full_candidates",
                    "truncated_candidates_rejected",
                    "count",
                    "elapsed_s",
                    "scope",
                )
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--candidate-proof", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.directory, args.candidate_proof, args.output)
