"""Independently bind future promises and actual start deviations to saved events."""

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path

from audit_online import audit
from audit_online_provenance import (
    PlanHistory,
    candidate_sources,
    decision_for,
    decision_sources,
    states_at,
)


def commitments(folder):
    rows = json.loads((folder / "online-journal.json").read_text(encoding="utf-8"))
    limits = json.loads((folder / "predeclared-online-limits.json").read_text(encoding="utf-8"))
    config = json.loads((folder / "configuration.json").read_text(encoding="utf-8"))
    products = {o["id"]: o["product_id"] for o in config["operations"]}
    candidates = {}
    files = sorted(folder.glob("candidate-*.json"))
    combined = folder / "online-candidates.json"
    captured = [json.loads(p.read_text(encoding="utf-8")) for p in files]
    if combined.exists():
        captured += [r["candidate"] for r in json.loads(combined.read_text(encoding="utf-8"))]
    for candidate in captured:
        sha = hashlib.sha256(
            json.dumps(candidate, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        commands = [c for step in candidate["steps"] for c in step["plan"]["commands"]]
        candidates[sha] = {(c["operation_id"], c["attempt"]): c for c in commands}
        products.update((c["operation_id"], c["product_id"]) for c in commands)
    events = {}
    with gzip.open(folder / "events.jsonl.gz", "rt", encoding="utf-8") as stream:
        for count, line in enumerate(stream, 1):
            event = json.loads(line)
            if event["kind"] == "STARTED":
                events[event["id"]] = {k: event[k] for k in ("command", "occurred_sim_h")}
    history = PlanHistory(candidate_sources(folder))
    decisions = decision_sources(folder)
    errors, previous = [], []
    totals = dict(
        future_promises=0,
        protected_comparisons=0,
        actual_starts=0,
        delayed_starts=0,
        total_delay_h=0.0,
        max_delay_h=0.0,
    )
    identity = None
    states = states_at(folder, (r["event_count"] for r in rows))
    for index, (row, state) in enumerate(zip(rows, states)):
        try:
            decision = decision_for(row, decisions)
            if decision is not None and row.get("receipt_id") != decision["receipt_id"]:
                raise ValueError("ACTUAL_RECEIPT_SOURCE")
            history.check(row, state, decision)
            current_identity = (row["run_id"], row["epoch"])
            before, after = row["commitments_before"], row["commitments_after"]
            if before != (previous if identity == current_identity else []):
                raise ValueError("COMMITMENT_HISTORY")
            identity = current_identity

            def keys(values):
                return {(x["operation"], x["attempt"]): x for x in values}

            old, new = keys(before), keys(after)
            if len(old) != len(before) or len(new) != len(after):
                raise ValueError("DUPLICATE_COMMITMENT")
            released = {
                (x["operation"], x["attempt"]): x["reason"] for x in row["commitment_releases"]
            }
            if set(old) - set(new) != set(released):
                raise ValueError("UNEXPLAINED_COMMITMENT_REMOVAL")
            started = set(state.get("completed", [])) | {
                r["command"]["operation_id"] for r in state.get("running", [])
            }
            cancelled = {p["product_id"] for p in state.get("products", []) if p["cancelled"]}
            for key, reason in released.items():
                if reason == "STARTED_OR_COMPLETED":
                    if key[0] not in started:
                        raise ValueError("UNOBSERVED_COMMITMENT_RELEASE")
                elif reason == "OBSERVED_CANCELLATION":
                    if products.get(key[0]) not in cancelled:
                        raise ValueError("UNOBSERVED_CANCELLATION")
                else:
                    raise ValueError("UNKNOWN_COMMITMENT_RELEASE")
            retained = [key for key in old if key not in released]
            if [key for key in new if key in old] != retained or any(
                old[k] != new[k] for k in retained
            ):
                raise ValueError("COMMITMENT_CHANGED")
            totals["protected_comparisons"] += len(retained)
            pending = keys(row["after"])
            for key in set(new) - set(old):
                promise = new[key]
                source = candidates.get(row["cache_sha256"], {}).get(key)
                if (
                    promise != pending.get(key)
                    or source is None
                    or promise["mode"] != source["mode_id"]
                    or promise["roles"] != source["roles"]
                    or promise["start_h"] != source["issued_sim_h"]
                    or promise.get("product", source["product_id"]) != source["product_id"]
                    or promise["start_h"] > row["time_h"] + limits["future_commitment_h"]
                    or limits["future_commitment_h"] <= 0
                ):
                    raise ValueError("UNVERIFIED_FUTURE_PROMISE")
                totals["future_promises"] += int(promise["start_h"] > row["time_h"])
            actual = row["actual_start"]
            receipt = events.get(row.get("receipt_id"))
            if row["receipt_kind"] == "STARTED":
                if receipt is None or actual is None or row["selected_proposal"] is None:
                    raise ValueError("MISSING_ACTUAL_START")
                proposal, command = row["selected_proposal"], receipt["command"]
                if decision is None or decision["plan"]["commands"] != [command]:
                    raise ValueError("ACTUAL_COMMAND_SOURCE")
                if (
                    (actual["operation"], actual["attempt"])
                    != (command["operation_id"], command["attempt"])
                    or actual["proposed_h"] != proposal["start_h"]
                    or proposal["operation"] != command["operation_id"]
                    or proposal["attempt"] != command["attempt"]
                    or proposal["mode"] != command["mode_id"]
                    or proposal["roles"] != command["roles"]
                    or proposal.get("product", command["product_id"]) != command["product_id"]
                    or actual["actual_h"] != receipt["occurred_sim_h"]
                    or not math.isclose(
                        actual["delay_h"], actual["actual_h"] - actual["proposed_h"], abs_tol=1e-10
                    )
                    or actual["delay_h"] < -1e-10
                ):
                    raise ValueError("ACTUAL_START_DEVIATION")
                totals["actual_starts"] += 1
                totals["delayed_starts"] += int(actual["delay_h"] > 1e-10)
                totals["total_delay_h"] += actual["delay_h"]
                totals["max_delay_h"] = max(totals["max_delay_h"], actual["delay_h"])
            elif actual is not None:
                raise ValueError("START_WITHOUT_RECEIPT")
            previous = after
        except (ValueError, KeyError, TypeError) as exc:
            errors.append(dict(row=index, reason=str(exc)))
    return dict(status="PASS" if not errors else "FAILED", errors=errors, totals=totals)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = dict(base=audit(args.folder), commitments=commitments(args.folder))
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    return any(value["status"] != "PASS" for value in result.values())


if __name__ == "__main__":
    raise SystemExit(main())
