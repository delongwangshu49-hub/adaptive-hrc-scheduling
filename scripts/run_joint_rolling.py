"""Conditional C04 cross-tick execution; no S15 HR or real G2 claim."""

import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path

from build_building_contracts import build_configuration, synthetic_fixture
from run_building_witness import run_activity
from run_joint_mechanisms import first_mode, problem

from adaptive_hrc_scheduling.algorithms.joint_rolling import FrozenTailPolicy
from adaptive_hrc_scheduling.algorithms.lns import Options, fingerprint
from adaptive_hrc_scheduling.building_backend import BuildingBackend
from adaptive_hrc_scheduling.control.joint_rolling_loop import Journal, run_frozen
from adaptive_hrc_scheduling.domain import building as b


def prepare(*, future=(), late_unload=False):
    c = synthetic_fixture(build_configuration(), hr=True)
    if late_unload:
        c = replace(
            c,
            people=tuple(
                replace(p, calendar=b.Calendar(24, (b.Window(0, 3), b.Window(7, 8.5))))
                if p.id == "OP1"
                else p
                for p in c.people
            ),
        )
    journal = Journal(BuildingBackend(c, b.HiddenScenario("C04-1.0", c.id, 0, tuple(future))))
    for code in ("KIT", "CUT", "MV-IN-B"):
        run_activity(journal, "PRODUCT-1." + code)
    return journal


def summary(result, anchor):
    return {
        "scope": "CONDITIONAL_C04_CROSS_TICK_FIXED_PROGRAM_EXECUTION",
        "status": result.status,
        "reason": result.reason,
        "nominal_candidate_sha256": fingerprint(result.proposal.best),
        "nominal_mode": first_mode(result.proposal, anchor.feedback.configuration),
        "nominal_score": result.proposal.best_score,
        "actual_score": result.actual_score,
        "window_complete": result.window_complete,
        "actual_end_h": result.trace.time_h,
        "planned_end_h": anchor.end,
        "execution_audit": result.execution_audit.status,
        "decision_findings": result.decision_findings,
        "request_count": len(result.requests),
        "turn_count_including_preparation": len(result.turns),
        "request_stream_sha256": fingerprint(result.requests),
        "actual_trace_sha256": fingerprint(result.trace),
        "nominal_program_sha256": result.requests[0].plan_sha256 if result.requests else None,
        "preserved_J2": any(r.location == "J2" for r in result.trace.residencies),
        "held_resources_at_end": sorted(lock.resource_id for lock in result.trace.locks),
        "completed_targets": [
            t
            for t in anchor.targets
            if any(a.activity_id == t and a.state == "COMPLETED" for a in result.trace.attempts)
        ],
    }


def run_cases(raw_output=None):
    options = Options(seed=18, iterations=2, repair_trials=6, wall_seconds=30, stagnation=4)
    initial = prepare()
    at = initial.time + 0.1
    completion_calls = len(FrozenTailPolicy(problem(initial), options).steps)
    rows = []
    for name, events, fixed, late, calls in (
        ("NORMAL", (), None, False, 1000),
        (
            "EARLY_R1_FAILURE",
            (b.WorldEvent("FAIL-R1", at, "FAILURE", "R1", None, None),),
            None,
            False,
            1000,
        ),
        (
            "IRRELEVANT_TEST1_FAILURE",
            (b.WorldEvent("FAIL-TEST", at, "FAILURE", "TEST1", None, None),),
            None,
            False,
            1000,
        ),
        (
            "CANCEL_DURING_SETUP",
            (b.WorldEvent("CANCEL", at, "CANCEL", "PRODUCT-1", None, None),),
            None,
            False,
            1000,
        ),
        ("LATE_UNLOAD_FIXED_HR", (), "HR-seq", True, 1000),
        ("LATE_UNLOAD_FIXED_H", (), "H", True, 1000),
        (
            "FAILURE_WHILE_WAITING_FOR_UNLOAD",
            (b.WorldEvent("FAIL-HELD", 4, "FAILURE", "R1", None, None),),
            "HR-seq",
            True,
            1000,
        ),
        ("ONE_CALL_CENSORED", (), None, False, 1),
        ("CALL_BUDGET_AT_ACTUAL_END", (), None, False, completion_calls),
    ):
        journal = prepare(future=events, late_unload=late)
        anchor = problem(journal, fixed=fixed)
        result = run_frozen(journal, anchor, options, max_calls=calls)
        if raw_output is not None:
            raw_output.mkdir(parents=True, exist_ok=True)
            (raw_output / (name + ".json")).write_text(
                json.dumps(asdict(result), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        row = summary(result, anchor)
        row.update(name=name, options=asdict(options))
        rows.append(row)
    return {
        "research": "BLOCKED_G2_OPEN",
        "cases": rows,
        "new_kit_run": False,
        "new_production_hr_mapping": False,
        "limitations": [
            "Conditional C04 target-tail execution, not S15 production HR or full-module completion.",
            "One sealed nominal plan; later visible state only gates safety, clock/receipt identity and actual auditing.",
            "Early feedback resumes the same waiting deadline; rejection/missed schedule never triggers search.",
            "Censored windows have no comparable full-window performance score; prior failures remain.",
        ],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path)
    args = parser.parse_args()
    data = run_cases(args.raw_output)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            [
                {
                    k: row[k]
                    for k in (
                        "name",
                        "status",
                        "reason",
                        "actual_score",
                        "execution_audit",
                        "decision_findings",
                    )
                }
                for row in data["cases"]
            ]
        )
    )


if __name__ == "__main__":
    main()
