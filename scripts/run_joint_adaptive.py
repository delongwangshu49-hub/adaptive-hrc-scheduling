"""Actual conditional replanning witnesses; not production HR qualification."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from build_building_contracts import build_configuration, synthetic_fixture
from run_building_witness import run_activity
from run_joint_mechanisms import problem
from run_joint_rolling import prepare

from adaptive_hrc_scheduling.algorithms.lns import Options, fingerprint
from adaptive_hrc_scheduling.building_backend import BuildingBackend
from adaptive_hrc_scheduling.control.joint_adaptive_loop import run_adaptive
from adaptive_hrc_scheduling.control.joint_rolling_loop import Journal, run_frozen
from adaptive_hrc_scheduling.domain import building as b


def before_move(future=()):
    config = synthetic_fixture(build_configuration(), hr=True)
    journal = Journal(BuildingBackend(config, b.HiddenScenario("C04-1.0", config.id, 0, future)))
    for code in ("KIT", "CUT"):
        run_activity(journal, "PRODUCT-1." + code)
    return journal


def run_cases(raw_output=None):
    options = Options(seed=18, iterations=2, repair_trials=6, wall_seconds=30, stagnation=4)
    at = prepare().time + 0.1
    during_move = before_move().time + 0.01
    rows = []
    for name, events, fixed, late, early in (
        ("NORMAL", (), None, False, False),
        (
            "IRRELEVANT_FAILURE",
            (b.WorldEvent("F", at, "FAILURE", "TEST1", None, None),),
            None,
            False,
            False,
        ),
        (
            "SETUP_FAILURE",
            (b.WorldEvent("F", at, "FAILURE", "R1", None, None),),
            None,
            False,
            False,
        ),
        ("CANCEL", (b.WorldEvent("C", at, "CANCEL", "PRODUCT-1", None, None),), None, False, False),
        ("LATE_FIXED_HR", (), "HR-seq", True, False),
        ("LATE_FIXED_H", (), "H", True, False),
        ("BEFORE_MOVE_NORMAL", (), None, False, True),
        (
            "BEFORE_MOVE_R1_FAILURE",
            (b.WorldEvent("F", during_move, "FAILURE", "R1", None, None),),
            None,
            False,
            True,
        ),
    ):
        journal = before_move(events) if early else prepare(future=events, late_unload=late)
        anchor = problem(journal, fixed=fixed)
        result = run_adaptive(journal, anchor, options)
        if raw_output is not None:
            raw_output.mkdir(parents=True, exist_ok=True)
            (raw_output / (name + ".json")).write_text(
                json.dumps(asdict(result), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        mode_ids = sorted(
            {
                t.decision.plan.commands[0].mode_id
                for t in result.turns
                if t.decision.plan.commands
                and t.decision.plan.commands[0].activity_id == "PRODUCT-1.W-B"
            }
        )
        row = {
            "name": name,
            "status": result.status,
            "reason": result.reason,
            "actual_score": result.actual_score,
            "actual_weld_mode_ids": mode_ids,
            "execution_audit": result.execution_audit.status,
            "decision_findings": result.decision_findings,
            "replans": len(result.replans),
            "end_h": anchor.end,
            "actual_end_h": result.trace.time_h,
            "first_candidate_sha256": fingerprint(result.replans[0].proposal.best),
            "actual_trace_sha256": fingerprint(result.trace),
            "replan_stream_sha256": fingerprint(result.replans),
            "search_wall_seconds": sum(r.proposal.wall_seconds for r in result.replans),
            "repair_trials": sum(i.trials for r in result.replans for i in r.proposal.history),
        }
        if early:
            control = before_move(events)
            frozen = run_frozen(control, problem(control), options)
            row["frozen_status"] = frozen.status
            row["frozen_actual_score"] = frozen.actual_score
            row["frozen_first_candidate_sha256"] = fingerprint(frozen.proposal.best)
            row["frozen_execution_audit"] = frozen.execution_audit.status
            row["frozen_decision_findings"] = frozen.decision_findings
            if raw_output is not None:
                (raw_output / (name + "_FROZEN.json")).write_text(
                    json.dumps(asdict(frozen), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
        rows.append(row)
    return {
        "scope": "CONDITIONAL_C04_ADAPTIVE_TARGET_TAIL",
        "research": "BLOCKED_G2_OPEN",
        "options_per_search": asdict(options),
        "cases": rows,
        "limitations": [
            "Not production HR, full-module completion or industrial qualification.",
            "Frozen control searches once; adaptive searches each call. No matched-total-budget effect claim.",
            "No legal suffix stops with actual facts retained; no S19 fallback implemented.",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path)
    args = parser.parse_args()
    data = run_cases(args.raw_output)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False))
