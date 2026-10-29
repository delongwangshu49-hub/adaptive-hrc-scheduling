"""Independently bind complete hypothetical plans to actual saved dispatches."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from adaptive_hrc_scheduling.contracts.codec import require  # noqa: E402
from adaptive_hrc_scheduling.full_schedule import verify_saved  # noqa: E402


def verify(directory):
    root = Path(directory)
    initial = json.loads((root / "configuration.json").read_bytes())
    saved = json.loads((root / "session-state.json").read_bytes())
    report = json.loads((root / "full-schedule-state.json").read_bytes())
    events = saved["execution"]["events"]
    plans, checks = {}, 0
    for entry in report["history"]:
        if entry["status"] != "ADOPTED":
            continue
        checksum = entry["plan_sha256"]
        raw = json.loads((root / "full-schedules" / (checksum + ".json")).read_bytes())
        plan = verify_saved(
            root,
            dict(artifact_sha256=checksum, version=entry["version"], plan_id=raw["plan_id"]),
            initial=initial,
            events=events[: raw["anchor_events"]],
        )
        require(
            plan["anchor_h"] == entry["at_h"] and plan["anchor_events"] == entry["anchor"][2],
            "FULL_ADOPTION_BOUNDARY",
        )
        plans[entry["version"]] = (checksum, plan)
        checks += 1
    require(
        sorted(plans) == list(range(1, report["version"] + 1))
        and report["used_calls"] == len(report["history"])
        and plans[report["version"]][0] == report["plan_sha256"],
        "FULL_VERSION_SEQUENCE",
    )
    starts = {e["command_id"]: e for e in events if e["kind"] == "STARTED"}
    bindings = {b["command_id"]: b for b in report["actual_bindings"]}
    require(
        len(bindings) == len(report["actual_bindings"]) and bindings.keys() == starts.keys(),
        "FULL_ACTUAL_COVERAGE",
    )
    ends = {e["command_id"]: e["occurred_sim_h"] for e in events if e["kind"] == "COMPLETED"}
    for key, event in starts.items():
        b = bindings[key]
        checksum, plan = plans[b["version"]]
        rows = [r for r in plan["intervals"] if r["command_id"] == key]
        require(len(rows) == 1, "FULL_ACTUAL_UNIQUE_COMMAND")
        row, command = rows[0], event["command"]
        ref = saved["command_bindings"][key]["full_schedule"]
        require(
            ref["artifact_sha256"] == checksum
            and ref["version"] == b["version"]
            and ref["plan_id"] == b["plan_id"] == plan["plan_id"]
            and b["receipt_id"] == event["id"]
            and b["start_h"] == event["occurred_sim_h"]
            and abs(row["start_h"] - event["occurred_sim_h"]) < 1e-8,
            "FULL_ACTUAL_PLAN_BINDING",
        )
        require(
            all(
                command[k] == row["command"][k]
                for k in (
                    "operation_id",
                    "product_id",
                    "activity_id",
                    "roles",
                    "mode_id",
                    "issued_sim_h",
                )
            ),
            "FULL_ACTUAL_ASSIGNMENT",
        )
        if key in ends:
            require(abs(row["end_h"] - ends[key]) < 1e-8, "FULL_ACTUAL_COMPLETION_TIME")
        checks += 1
    return dict(
        status="PASS",
        scope="COMPLETE_PLAN_REPLAY_AND_ACTUAL_DISPATCH_BINDING",
        checks=checks,
        versions=len(plans),
        actual_starts=len(starts),
        actual_completions=len(ends),
        solve_calls=report["used_calls"],
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.directory)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
