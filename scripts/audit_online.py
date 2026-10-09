"""Recompute S19 change/timing/protection evidence from saved actual event records."""

import argparse
import gzip
import json
import math
from dataclasses import fields, is_dataclass, replace
from pathlib import Path

from adaptive_hrc_scheduling.algorithms.lns import fingerprint
from adaptive_hrc_scheduling.contracts.codec import as_data, decode
from adaptive_hrc_scheduling.contracts.production import digest
from adaptive_hrc_scheduling.control.production_decisions import initial_visible_state
from adaptive_hrc_scheduling.domain import production as m


def initial_state_from_wire(config, wire):
    """Preserve validated JSON numeric spelling for byte-bound initial anchors."""

    def restore(value, saved):
        if is_dataclass(value):
            return replace(
                value,
                **{f.name: restore(getattr(value, f.name), saved[f.name]) for f in fields(value)},
            )
        if isinstance(value, tuple):
            return tuple(restore(v, s) for v, s in zip(value, saved))
        # decode() has already checked all types and values. An initial support
        # coordinate copied from 12 must remain 12, rather than becoming 12.0,
        # because the original protection anchor hashes the exact JSON numbers.
        return saved if type(value) is float else value

    return initial_visible_state(restore(config, wire))


def distribution(values):
    ordered = sorted(values)
    if not ordered:
        return dict(count=0, total_s=0.0, max_s=None, p50_s=None, p95_s=None)
    size = len(ordered)
    return dict(
        count=size,
        total_s=sum(ordered),
        max_s=ordered[-1],
        p50_s=ordered[(size - 1) // 2],
        p95_s=ordered[min(size - 1, int(size * 0.95))],
    )


def same_distribution(actual, expected):
    if (
        actual.keys() != expected.keys()
        or type(actual.get("count")) is not int
        or actual["count"] != expected["count"]
    ):
        return False
    for key, value in expected.items():
        saved = actual[key]
        if value is None:
            if saved is not None:
                return False
        elif type(saved) not in (int, float) or not math.isfinite(saved):
            return False
        elif not math.isclose(saved, value, rel_tol=1e-9, abs_tol=1e-8):
            return False
    return True


def coverage(folder, rows, event_ids, event_kinds, timing):
    # Read the original report without retaining its old duplicate journal.
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    continuation = report["manifest"].get("continuation", False)
    start_h = report.get("start_h", 0)
    termination = report["manifest"]["termination"]
    del report
    errors = []
    base = timing.get("initial_event_count")
    if base is None:
        # The earlier full-from-origin measurements predate this metadata.
        if continuation:
            errors.append(dict(reason="MISSING_MEASUREMENT_PREFIX"))
        base = 0
    if type(base) is not int or not 0 <= base <= len(event_ids):
        errors.append(dict(reason="MEASUREMENT_PREFIX_RANGE"))
        base = 0
    decisions = []
    with gzip.open(folder / "decisions.jsonl.gz", "rt", encoding="utf-8") as stream:
        for line in stream:
            decision = json.loads(line)
            if continuation and (decision["event_count"] < base or decision["sampled_h"] < start_h):
                continue
            decisions.append(decision)
    if (
        termination == "DECLARED_CHECKPOINT"
        and decisions
        and decisions[-1]["plan"]["reason"] == "DECLARED_CHECKPOINT"
        and not decisions[-1]["plan"]["commands"]
        and decisions[-1]["receipt_id"] is None
    ):
        decisions.pop()  # Driver closing record; no policy cycle occurred.
    pause_path = folder / "online-pause.json"
    pause = json.loads(pause_path.read_text(encoding="utf-8")) if pause_path.exists() else None
    matched, pause_rows = 0, 0
    valid = True
    for row in rows:
        decision = decisions[matched] if matched < len(decisions) else None
        same = decision is not None and (
            row["run_id"],
            row["epoch"],
            row["observation_id"],
            row["event_count"],
            row["time_h"],
            row.get("final_reason"),
            row.get("dispatched"),
            row.get("receipt_kind"),
        ) == (
            decision["run_id"],
            decision["epoch"],
            decision["observation_id"],
            decision["event_count"],
            decision["sampled_h"],
            decision["plan"]["reason"],
            bool(decision["plan"]["commands"]),
            event_kinds.get(decision["receipt_id"]),
        )
        stale_wait = (
            decision is not None
            and row.get("stale_dispatch_rejected")
            and row.get("final_reason") == decision["plan"]["reason"] == "S19:STALE_OBSERVATION"
            and not row.get("dispatched")
            and not decision["plan"]["commands"]
            and row.get("receipt_kind") is None
            and decision["receipt_id"] is None
            and (row["run_id"], row["epoch"]) == (decision["run_id"], decision["epoch"])
            and row["event_count"] <= decision["event_count"]
            and row["time_h"] <= decision["sampled_h"]
        )
        if same or stale_wait:
            matched += 1
        elif (
            pause
            and pause_rows == 0
            and pause["state_unchanged"]
            and pause["no_dispatch"]
            and row.get("final_reason") == "S19:PAUSED"
            and not row.get("dispatched")
            and row.get("receipt_kind") is None
            and row["time_h"] == pause["time_h"]
            and row["protected_sha256"] == pause["protected_sha256"]
        ):
            pause_rows += 1  # Explicit interface witness, outside driver decisions.
        else:
            valid = False
            break
    if not valid or matched != len(decisions) or pause_rows != int(pause is not None):
        errors.append(dict(reason="JOURNAL_DECISION_COVERAGE"))
    maximum = max((row["event_count"] for row in rows), default=base)
    if any(not base <= row["event_count"] <= len(event_ids) for row in rows):
        errors.append(dict(reason="JOURNAL_MEASUREMENT_RANGE"))
    if set(timing["unobserved_event_ids"]) != set(event_ids[maximum:]):
        errors.append(dict(reason="UNOBSERVED_EVENT_COVERAGE"))
    if not all("cycle_seconds" in row for row in rows) or not same_distribution(
        timing["cycles"], distribution([row.get("cycle_seconds", 0) for row in rows])
    ):
        errors.append(dict(reason="CYCLE_SUMMARY_MISMATCH"))
    return (
        errors,
        set(event_ids[base:maximum]),
        dict(
            initial_event_count=base,
            driver_decisions=len(decisions),
            matched_driver_decisions=matched,
            standalone_pause_rows=pause_rows,
        ),
    )


def recompute(before, after):
    def mapping(rows):
        out = {(r["operation"], r["attempt"]): r for r in rows}
        if len(out) != len(rows):
            raise ValueError("duplicate operation/attempt")
        return out

    a, b = mapping(before), mapping(after)
    shared = [key for key in a if key in b]
    new_order = [key for key in b if key in a]
    changed = dict(
        comparable=len(shared),
        added=len(b) - len(shared),
        removed=len(a) - len(shared),
        order_inversions=0,
        mode_changes=0,
        crew_changes=0,
        start_changes=0,
        total_start_shift_h=0,
    )
    for i, key in enumerate(shared):
        for other in shared[i + 1 :]:
            changed["order_inversions"] += new_order.index(key) > new_order.index(other)
        for field, count in (
            ("mode", "mode_changes"),
            ("roles", "crew_changes"),
            ("start_h", "start_changes"),
        ):
            changed[count] += a[key][field] != b[key][field]
        changed["total_start_shift_h"] += abs(a[key]["start_h"] - b[key]["start_h"])
    return changed


def audit(folder):
    wire = json.loads((folder / "configuration.json").read_text(encoding="utf-8"))
    config = decode(m.Configuration, wire)
    rows = json.loads((folder / "online-journal.json").read_text(encoding="utf-8"))
    limits = json.loads((folder / "predeclared-online-limits.json").read_text(encoding="utf-8"))
    counts = {r["event_count"] for r in rows}
    states = {0: as_data(initial_state_from_wire(config, wire))}
    event_ids, event_kinds, prefixes = [], {}, {0: ()}
    with gzip.open(folder / "events.jsonl.gz", "rt", encoding="utf-8") as stream:
        for index, line in enumerate(stream, 1):
            event = json.loads(line)
            event_ids.append(event["id"])
            event_kinds[event["id"]] = event["kind"]
            if index in counts:
                states[index] = event["state"]
                prefixes[index] = tuple(event_ids)
    timing = json.loads((folder / "online-timing.json").read_text(encoding="utf-8"))
    errors, expected_feedback, coverage_result = coverage(
        folder, rows, event_ids, event_kinds, timing
    )
    totals = {}
    protections = (
        "running",
        "owners",
        "reservations",
        "positions",
        "lots",
        "motions",
        "supports",
        "mode_attempts",
        "activity_crews",
    )
    for index, row in enumerate(rows):
        try:
            change = recompute(row["before"], row["after"])
            # Count fields are exact. Different independent summation orders
            # may round the same non-negative floating-point shifts differently.
            saved_change = row["change"]
            shift = "total_start_shift_h"
            if change.keys() != saved_change.keys() or any(
                not math.isclose(change[key], saved_change[key], rel_tol=1e-9, abs_tol=1e-8)
                if key == shift
                else change[key] != saved_change[key]
                for key in change
            ):
                raise ValueError("CHANGE_COUNT")
            for k, v in change.items():
                totals[k] = totals.get(k, 0) + v
            state = states[row["event_count"]]
            if fingerprint({k: state[k] for k in protections}) != row["protected_sha256"]:
                raise ValueError("PROTECTION_ANCHOR")
            obs = m.PlanningObservation(
                config.schema_version,
                config.id,
                digest(config),
                row["run_id"],
                row["epoch"],
                row["observation_id"],
                row["time_h"],
                row["time_h"],
                decode(m.State, state),
                prefixes[row["event_count"]],
            )
            if digest(obs) != row["observation_sha256"]:
                raise ValueError("OBSERVATION_ANCHOR")
            for key in (
                "decision_seconds",
                "search_seconds",
                "verification_seconds",
                "cycle_seconds",
            ):
                value = row.get(key, 0)
                if not math.isfinite(value) or value < 0:
                    raise ValueError("TIMING_VALUE")
            if row["verification_seconds"] > row["search_seconds"] + 1e-8:
                raise ValueError("VALIDATION_NOT_INSIDE_SEARCH_TIME")
            if row["budget_exceeded"] != (row["decision_seconds"] > limits["decision_seconds"]):
                raise ValueError("HIDDEN_DECISION_OVERRUN")
            if "cycle_seconds" in row and row["cycle_budget_exceeded"] != (
                row["cycle_seconds"] > limits["decision_seconds"]
            ):
                raise ValueError("HIDDEN_CYCLE_OVERRUN")
        except (KeyError, ValueError, TypeError) as exc:
            errors.append(dict(row=index, reason=str(exc)))
    feedback = json.loads((folder / "online-feedback.json").read_text(encoding="utf-8"))
    seen_feedback = set()
    for index, item in enumerate(feedback):
        if item["event_id"] in seen_feedback or event_kinds.get(item["event_id"]) != item["kind"]:
            errors.append(dict(feedback=index, reason="FEEDBACK_EVENT_ANCHOR"))
        seen_feedback.add(item["event_id"])
        if any(
            not math.isfinite(item[key])
            for key in (
                "produced_s",
                "observed_s",
                "decision_end_s",
                "observation_latency_s",
                "decision_latency_s",
            )
        ):
            errors.append(dict(feedback=index, reason="FEEDBACK_NONFINITE"))
        if not 0 <= item["produced_s"] <= item["observed_s"] <= item["decision_end_s"]:
            errors.append(dict(feedback=index, reason="FEEDBACK_WALL_ORDER"))
        if abs(item["observed_s"] - item["produced_s"] - item["observation_latency_s"]) > 1e-8:
            errors.append(dict(feedback=index, reason="FEEDBACK_OBSERVATION_RECOMPUTATION"))
        if abs(item["decision_end_s"] - item["produced_s"] - item["decision_latency_s"]) > 1e-8:
            errors.append(dict(feedback=index, reason="FEEDBACK_WALL_RECOMPUTATION"))
    if seen_feedback != expected_feedback:
        errors.append(dict(reason="FEEDBACK_EVENT_COVERAGE"))
    for name, values, reason in (
        (
            "feedback_to_observation",
            [r["observed_s"] - r["produced_s"] for r in feedback],
            "FEEDBACK_OBSERVATION_SUMMARY_MISMATCH",
        ),
        (
            "feedback_to_decision_end",
            [r["decision_end_s"] - r["produced_s"] for r in feedback],
            "FEEDBACK_DECISION_SUMMARY_MISMATCH",
        ),
    ):
        if not same_distribution(timing[name], distribution(values)):
            errors.append(dict(reason=reason))
    return dict(
        status="FAIL" if errors else "PASS",
        rows=len(rows),
        feedback=len(feedback),
        coverage=coverage_result,
        change_totals=totals,
        errors=errors[:30],
        error_count=len(errors),
        scope="INDEPENDENT_SAVED_ANCHORS_AND_METRIC_RECOMPUTATION_NOT_A_CLOCK_CERTIFICATION",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.folder)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return result["status"] != "PASS"


if __name__ == "__main__":
    raise SystemExit(main())
