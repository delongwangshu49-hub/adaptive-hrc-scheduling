"""P06.1 saved-copy corruption controls, including re-signed semantic forgeries.

Uses the unchanged workforce verifier with both original evidence paths bound.
Retains every damaged state compressed, each result, and original input hashes.
Does not run an optimizer, a production worker, a GUI, or a physical backend.
"""

import argparse
import copy
import gzip
import hashlib
import json
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from verify_workforce_session import verify  # noqa: E402

from adaptive_hrc_scheduling.contracts.session import digest, request_digest  # noqa: E402


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def file_pin(path):
    assert path.stat().st_size < 32 * 1024 * 1024, path
    return dict(bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())


REPLAY_TARGETS = frozenset(
    (
        "run-spec.json",
        "profile.json",
        "launch-binding.json",
        "configuration.json",
        "session-state.json",
        "decisions.jsonl.gz",
        "online-journal.json",
    )
)


def replay_descriptor(path, target, encoding="identity"):
    return dict(path=str(path.resolve()), target=target, encoding=encoding, **file_pin(path))


def bind_replay_inputs(original_files, state_copy, component, decisions_copy=None):
    """Describe every actual replay input, including the damaged component itself."""
    by_name = {p.name: p for p in original_files}
    if set(by_name) != REPLAY_TARGETS:
        raise ValueError("P061_REPLAY_INPUT_SET")
    inputs = []
    for name in sorted(REPLAY_TARGETS):
        path = (
            state_copy
            if name == "session-state.json"
            else (
                decisions_copy
                if name == "decisions.jsonl.gz" and component == "decisions"
                else by_name[name]
            )
        )
        if path is None or not path.is_file():
            raise ValueError("P061_EVIDENCE_MISSING:" + name)
        inputs.append(
            replay_descriptor(path, name, "gzip" if name == "session-state.json" else "identity")
        )
    damaged_target = "decisions.jsonl.gz" if component == "decisions" else "session-state.json"
    return dict(
        replay_inputs=inputs, damaged_files=[r for r in inputs if r["target"] == damaged_target]
    )


def replay_case(case, output):
    """Replay an indexed bad case; missing evidence is never counted as rejection."""
    try:
        inputs = case["replay_inputs"]
        if len(inputs) != len(REPLAY_TARGETS) or {r["target"] for r in inputs} != REPLAY_TARGETS:
            raise ValueError("P061_REPLAY_INPUT_SET")
        damaged = case["damaged_files"]
        expected = (
            "decisions.jsonl.gz" if case["component"] == "decisions" else "session-state.json"
        )
        if len(damaged) != 1 or damaged[0]["target"] != expected or damaged[0] not in inputs:
            raise ValueError("P061_DAMAGED_COMPONENT_BINDING")
        for item in inputs:
            path = Path(item["path"])
            if not path.is_file():
                raise ValueError("P061_EVIDENCE_MISSING:" + item["target"])
            if file_pin(path) != {k: item[k] for k in ("bytes", "sha256")}:
                raise ValueError("P061_EVIDENCE_HASH_MISMATCH:" + item["target"])
            encoding = "gzip" if item["target"] == "session-state.json" else "identity"
            if item["encoding"] != encoding:
                raise ValueError("P061_EVIDENCE_ENCODING:" + item["target"])
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return dict(case=case.get("case"), status="EVIDENCE_INCOMPLETE", reason=str(exc))
    output.mkdir(parents=True, exist_ok=False)
    for item in inputs:
        destination = output / item["target"]
        if item["encoding"] == "gzip":
            with gzip.open(item["path"], "rb") as source, destination.open("xb") as dest:
                shutil.copyfileobj(source, dest)
        else:
            shutil.copy2(item["path"], destination)
    try:
        verify(output, require_decisions=True)
    except (ValueError, KeyError, TypeError) as exc:
        result = dict(
            case=case["case"], status="REJECTED", reason=str(exc), exception=type(exc).__name__
        )
    else:
        result = dict(case=case["case"], status="CORRUPTION_ACCEPTED", reason=None)
    result["replay_inputs"] = inputs
    write(output / "replay-result.json", result)
    return result


def rechain_receipts(saved):
    previous = "0" * 64
    for i, row in enumerate(saved["receipts"], 1):
        row.update(receipt_id=f"RECEIPT-{i}", receipt_sequence=i, previous_receipt_hash=previous)
        previous = digest(row)


def rechain_deltas(saved):
    fields = (
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
    previous = digest(saved["initial_catalog"])
    saved["versions"] = [previous]
    for i, row in enumerate(saved["deltas"], 1):
        row.update(old_hash=previous, old_version=i - 1, new_version=i)
        row["new_hash"] = digest(
            dict(previous_hash=previous, version=i, delta={k: row[k] for k in fields})
        )
        previous = row["new_hash"]
        saved["versions"].append(previous)


def resign_request(saved, key):
    request = saved["requests"][key]
    request["request_digest"] = request_digest(request)
    for row in saved["receipts"]:
        if row["request_id"] == key:
            row["request_digest"] = request["request_digest"]
    for row in saved["deltas"]:
        if row["request_id"] == key:
            row["request_digest"] = request["request_digest"]
    for row in saved["generations"]:
        if row["request_id"] == key and "request_digest" in row:
            row["request_digest"] = request["request_digest"]
    rechain_receipts(saved)
    for row in saved["deltas"]:
        generation = next(
            (g for g in saved["generations"] if g["request_id"] == row["request_id"]), None
        )
        if generation:
            row["generation_sha256"] = digest(generation)
    rechain_deltas(saved)


def run(session_directory, evidence_directory, output, case_filter=None):
    t0 = time.perf_counter()
    output.mkdir(parents=True, exist_ok=False)
    original_files = [
        session_directory / name
        for name in (
            "run-spec.json",
            "profile.json",
            "launch-binding.json",
            "configuration.json",
            "session-state.json",
        )
    ]
    original_files += [
        evidence_directory / name for name in ("decisions.jsonl.gz", "online-journal.json")
    ]
    before = {str(p): file_pin(p) for p in original_files}
    write(
        output / "started.json",
        dict(
            at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
            inputs=before,
            command=sys.argv,
        ),
    )
    original = read(session_directory / "session-state.json")
    with gzip.open(evidence_directory / "decisions.jsonl.gz", "rt", encoding="utf-8") as stream:
        original_decisions = [json.loads(line) for line in stream]
    original_journal = read(evidence_directory / "online-journal.json")
    original_check = verify(
        session_directory, evidence_directory=evidence_directory, require_decisions=True
    )
    write(output / "positive-control.json", original_check)
    scratch = output / "scratch"
    scratch.mkdir()
    for path in original_files:
        if path.name != "session-state.json":
            shutil.copy2(path, scratch / path.name)
    order_key = next(k for k, r in original["requests"].items() if r["kind"] == "ORDER_CREATE")
    person_key = next(k for k, r in original["requests"].items() if r["kind"] == "PERSON_ARRIVE")
    person = original["requests"][person_key]["target_id"]

    cases = []

    def case(name, mutate, semantic_resigned=False, component="session"):
        cases.append((name, mutate, semantic_resigned, component))

    case("delta_hash_broken", lambda s, d, j: s["deltas"][0].update(new_hash="0" * 64))

    def delta_objects(s, d, j):
        s["deltas"][-1]["object_ids"].append("FORGED")
        rechain_deltas(s)

    case("delta_wrong_objects_resigned", delta_objects, True)

    def missing_applied(s, d, j):
        s["receipts"] = [
            r
            for r in s["receipts"]
            if not (r["request_id"] == order_key and r["status"] == "APPLIED")
        ]
        rechain_receipts(s)

    case("missing_APPLIED_rechained", missing_applied, True)

    def duplicate_applied(s, d, j):
        s["receipts"].append(
            copy.deepcopy(next(r for r in s["receipts"] if r["status"] == "APPLIED"))
        )
        rechain_receipts(s)

    case("duplicate_APPLIED_rechained", duplicate_applied, True)

    def changed_request(s, d, j):
        s["requests"][order_key]["payload"]["priority"] = "URGENT"
        resign_request(s, order_key)

    case("request_changed_content_resigned", changed_request, True)

    def expired_request(s, d, j):
        s["requests"][order_key]["expires_sim_h"] = 0.025
        resign_request(s, order_key)

    case("request_expired_at_apply_resigned", expired_request, True)

    def cross_run(s, d, j):
        s["requests"][order_key]["run_id"] = "OTHER-RUN"
        resign_request(s, order_key)

    case("request_cross_run_resigned", cross_run, True)

    def old_epoch(s, d, j):
        s["requests"][order_key]["epoch"] = 99
        resign_request(s, order_key)

    case("request_wrong_epoch_resigned", old_epoch, True)

    def wrong_qualification(s, d, j):
        g = next(g for g in s["generations"] if g["request_id"] == person_key)
        g["payload"]["qualification_sha256"] = "0" * 64
        s["requests"][person_key]["payload"]["qualification_sha256"] = "0" * 64
        resign_request(s, person_key)

    case("person_qualification_resigned", wrong_qualification, True)

    def unknown_qualification(s, d, j):
        g = next(g for g in s["generations"] if g["request_id"] == person_key)
        g["payload"]["qualifications"] = ["UNKNOWN-QUALIFICATION"]
        s["requests"][person_key]["payload"]["qualifications"] = ["UNKNOWN-QUALIFICATION"]
        resign_request(s, person_key)

    case("person_known_field_unknown_qualification_resigned", unknown_qualification, True)

    def calendar_forged(s, d, j):
        g = next(g for g in s["generations"] if g["request_id"] == person_key)
        g["payload"]["calendar_sha256"] = "0" * 64
        s["requests"][person_key]["payload"]["calendar_sha256"] = "0" * 64
        resign_request(s, person_key)

    case("person_calendar_binding_resigned", calendar_forged, True)

    def wrong_template(s, d, j):
        g = next(g for g in s["generations"] if g["request_id"] == order_key)
        g["payload"]["template_sha256"] = "0" * 64
        s["requests"][order_key]["payload"]["template_sha256"] = "0" * 64
        resign_request(s, order_key)

    case("order_template_resigned", wrong_template, True)
    case("generation_missing", lambda s, d, j: s["generations"].pop())
    case("scene_missing", lambda s, d, j: s.update(scene_bindings=[]))
    case(
        "scene_person_not_ready",
        lambda s, d, j: next(r for r in s["scene_bindings"] if r["domain_id"] == person).update(
            ready=False
        ),
    )
    case(
        "scene_person_identity_reused",
        lambda s, d, j: next(r for r in s["scene_bindings"] if r["domain_id"] == person).update(
            scene_entity_id="W1"
        ),
    )
    case(
        "material_catalog_binding",
        lambda s, d, j: s["catalog"]["objects"][s["requests"][order_key]["target_id"]].update(
            product_ids=["WRONG"]
        ),
    )
    case(
        "material_due_before_arrival",
        lambda s, d, j: s["material_due"].update({next(iter(s["material_due"])): -1}),
    )
    case(
        "capacity_projection_forged",
        lambda s, d, j: s["capacity_events"][-1]["counts"].update(count_wip=99),
    )
    case("capacity_history_missing", lambda s, d, j: s.update(capacity_events=[]))
    case(
        "event_commit_time_forged",
        lambda s, d, j: next(
            e for e in s["execution"]["events"] if e["id"] == s["deltas"][-1]["commit_event_id"]
        ).update(occurred_sim_h=99),
    )
    case("event_run_identity_forged", lambda s, d, j: s["execution"].update(run_id="OTHER-RUN"))
    case(
        "observation_prefix_forged",
        lambda s, d, j: s["observations"][-1].update(event_prefix_hash="0" * 64),
    )
    case(
        "command_binding_missing",
        lambda s, d, j: s["command_bindings"].pop(next(iter(s["command_bindings"]))),
    )
    case(
        "command_binding_old_catalog",
        lambda s, d, j: list(s["command_bindings"].values())[-1].update(admitted_catalog_version=0),
    )
    case(
        "cache_unknown_invalidated_key",
        lambda s, d, j: s["cache_transitions"][-1].update(invalidated_keys=["FORGED"]),
    )
    case(
        "cache_commitment_hash_broken",
        lambda s, d, j: s["cache_transitions"][-1].update(protected_after_hash="0" * 64),
    )
    case(
        "person_exposure_reset",
        lambda s, d, j: s["workforce_statistics"]["people"][person].update(exposure=0),
    )
    case(
        "person_labour_cost_forged",
        lambda s, d, j: s["workforce_statistics"]["people"][person].update(labour_cost=0),
    )
    case(
        "person_presence_missing",
        lambda s, d, j: s["workforce_statistics"]["people"][person].update(presence_intervals=[]),
    )
    case(
        "person_business_status_forged",
        lambda s, d, j: s["workforce_results"][0].update(status="DEPARTED"),
    )
    case(
        "decision_observation_wrong",
        lambda s, d, j: d[0].update(observation_id="FORGED"),
        component="decisions",
    )
    case(
        "decision_run_wrong", lambda s, d, j: d[0].update(run_id="OTHER-RUN"), component="decisions"
    )
    case(
        "decision_plan_command_missing",
        lambda s, d, j: d[0]["plan"].update(commands=[]),
        component="decisions",
    )
    case(
        "decision_event_prefix_wrong",
        lambda s, d, j: d[0].update(event_ids_sha256="0" * 64),
        component="decisions",
    )

    results = []
    if case_filter:
        names = set(case_filter)
        assert names <= {x[0] for x in cases}, "UNKNOWN_CASE_FILTER"
        cases = [c for c in cases if c[0] in names]
    for name, mutate, resigned, component in cases:
        started = time.perf_counter()
        saved, decisions, journal = (
            copy.deepcopy(original),
            copy.deepcopy(original_decisions),
            copy.deepcopy(original_journal),
        )
        mutate(saved, decisions, journal)
        dest = output / name
        dest.mkdir()
        raw = json.dumps(saved, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        with gzip.open(dest / "session-state.json.gz", "wb", compresslevel=3) as stream:
            stream.write(raw)
        (scratch / "session-state.json").write_bytes(raw)
        with gzip.open(scratch / "decisions.jsonl.gz", "wt", encoding="utf-8") as stream:
            for row in decisions:
                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        if component == "decisions":
            shutil.copy2(scratch / "decisions.jsonl.gz", dest / "decisions.jsonl.gz")
        write(scratch / "online-journal.json", journal)
        try:
            verify(scratch, evidence_directory=scratch, require_decisions=True)
        except (ValueError, KeyError, TypeError) as exc:
            result = dict(
                case=name, status="REJECTED", reason=str(exc), exception=type(exc).__name__
            )
        else:
            result = dict(case=name, status="CORRUPTION_ACCEPTED", reason=None)
        result.update(
            resigned=resigned,
            component=component,
            elapsed_s=time.perf_counter() - started,
            damaged_state_sha256=hashlib.sha256(raw).hexdigest(),
            raw_state_bytes=len(raw),
            bad_copy=str(dest / "session-state.json.gz"),
        )
        result.update(
            bind_replay_inputs(
                original_files,
                dest / "session-state.json.gz",
                component,
                dest / "decisions.jsonl.gz" if component == "decisions" else None,
            )
        )
        write(dest / "result.json", result)
        results.append(result)
        print(json.dumps(result), flush=True)
    after = {str(p): file_pin(p) for p in original_files}
    assert before == after, "ORIGINAL_INPUT_CHANGED"
    accepted = [r for r in results if r["status"] != "REJECTED"]
    summary = dict(
        identity="P061-SAVED-NEGATIVE-r1",
        status="PASS" if not accepted else "FAIL",
        at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
        cases=results,
        count=len(results),
        accepted_corruptions=accepted,
        original_inputs=before,
        original_inputs_unchanged=True,
        positive_control=original_check,
        elapsed_s=time.perf_counter() - t0,
    )
    write(output / "result.json", summary)
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("session_directory", type=Path, nargs="?")
    p.add_argument("--evidence-directory", type=Path)
    p.add_argument("--replay-index", type=Path)
    p.add_argument("--case")
    p.add_argument("--output-directory", type=Path, required=True)
    p.add_argument("--case-filter", nargs="+")
    a = p.parse_args()
    if a.replay_index:
        if not a.case:
            p.error("--replay-index requires --case")
        selected = [r for r in read(a.replay_index)["cases"] if r["case"] == a.case]
        if len(selected) != 1:
            p.error("--case must name exactly one indexed case")
        report = replay_case(selected[0], a.output_directory)
        print(json.dumps(report))
        sys.exit(0 if report["status"] == "REJECTED" else 1)
    if a.session_directory is None or a.evidence_directory is None:
        p.error("generation requires session_directory and --evidence-directory")
    report = run(a.session_directory, a.evidence_directory, a.output_directory, a.case_filter)
    print(
        json.dumps(
            {
                k: v
                for k, v in report.items()
                if k not in ("cases", "positive_control", "original_inputs")
            }
        )
    )
    sys.exit(0 if report["status"] == "PASS" else 1)
